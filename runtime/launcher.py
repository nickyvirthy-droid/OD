"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/launcher.py
Descrição: Launcher do sistema REAL — monta o Orchestrator com o provider
           LLM local (OpenAICompatProvider -> llama-server) e memórias em
           disco, e sobe os serviços: API REST (porta 8000) e Telegram Bot
           (polling com o token de .env).

Uso:
    .venv/bin/python -m runtime.launcher api       # sobe a API REST
    .venv/bin/python -m runtime.launcher telegram  # sobe o bot do Telegram
    .venv/bin/python -m runtime.launcher mqtt      # sobe a ponte MQTT
    .venv/bin/python -m runtime.launcher recovery  # ciclo percepção + auto-reparo
    .venv/bin/python -m runtime.launcher all       # api + bot + mqtt + recovery
    .venv/bin/python -m runtime.launcher capabilities  # manifesto JSON e sai

Configuração (variáveis de ambiente / .env no raiz do repo):
    TELEGRAM_BOT_TOKEN  Token do bot PRINCIPAL — a Nicky, conversa e
                        comandos (obrigatório p/ telegram).
    OD_TELEGRAM_ADMINS  IDs admin separados por vírgula (comandos admin).
    OD_TELEGRAM_USUARIOS_TOKEN  Bot de ALERTAS DE USUÁRIOS (@Nexus_Nicky_
                        bot): 💬 chat das peças, 🔑 registro de posse.
                        Vazio = cai no chat (a Nicky).
    OD_TELEGRAM_MONITOR_TOKEN  Bot de MONITORAMENTO (@nicky_monitor_bot):
                        notifier (saúde/restart/disco/stack), presença,
                        face e resumo do orquestrador. Vazio = cai no chat.
    OD_TELEGRAM_USUARIOS_CHAT / OD_TELEGRAM_MONITOR_CHAT  Chat por papel
                        (default OD_TELEGRAM_ADMINS).
    OD_LLM_URL          Endpoint OpenAI-compat (default 127.0.0.1:8081).
    OD_LLM_TIMEOUT_S    Timeout por chamada LLM (default 240).
    OD_API_PORT         Porta da API REST (default 8000).
    OD_API_HOST         Bind da API (default 0.0.0.0 — LAN/site; use
                        127.0.0.1 para só local).
    OD_API_KEY          Chave X-API-Key da API (endpoints protegidos).
    OD_API_AUTH_ALL     "0" libera os endpoints públicos sem chave
                        (default 1 — chave exigida em TODOS os endpoints).
    OD_MQTT_ENABLED     "0" desliga a ponte MQTT no modo all (default 1).
    OD_MQTT_HOST/PORT   Broker Mosquitto (default 127.0.0.1:1883).
    OD_MQTT_CLIENT_ID   Identificador no broker (default od-core).
    OD_MQTT_USERNAME    Usuário do broker (vazio = anônimo).
    OD_MQTT_PASSWORD    Senha do broker (vazia = sem senha). Rotação
                        2026-09-30: senha alucinada vazou no cache LLM
                        (§12.1) e o broker aceitava anônimo — agora auth
                        obrigatória no mosquitto + credencial aqui.
    OD_MQTT_SUBSCRIBE   Filtros de entrada, vírgula (default "od/in/#").
    OD_PRESENCE_ENABLED "0" desliga o Presence Monitor (default 1).
    OD_HA_CREDENTIALS   Caminho das credenciais do HA (default
                        config/iot_credentials.json).
    OD_PRESENCE_POLL_S  Intervalo do poll de presença (default 30).
    OD_VISION_ENABLED   "1" liga o Face Detector (webcam) no modo all
                        (default 0 — câmera só quando ativado).
    OD_VISION_DEVICE    Dispositivo da webcam (default /dev/video0).
    OD_VISION_POLL_S    Intervalo de captura (default 5).
    OD_VOICE_STT        "0" desliga a transcrição de voz recebida
                        (whisper.cpp) no bot E na API /transcribe (default 1).
    OD_VOICE_TTS        "0" desliga a resposta por voz (Piper) no bot E na
                        API /tts (default 1).
    OD_VOICE_PROFILE    Voz do TTS (default dii; "regulus" = faber).
    OD_AUDIT_FILE       Trilha de auditoria JSONL (Fase 7.1, default
                        logs/audit.jsonl na raiz do repo).
    OD_SELF_REPAIR_ENABLED "0" desliga o RecoveryLoop (percepção + auto-reparo;
                        default 1).
    OD_RECOVERY_INTERVAL_S Intervalo do ciclo de auto-recuperação em segundos
                        (default 300 — 5min, espelho do main_cycle do Nexus).
    OD_NOTIFIER_ENABLED "0" desliga o ProactiveNotifier (alertas proativos;
                        default 1).
    OD_DB_URL           DSN PostgreSQL (postgres://user:pass@host:port/db)
                        — ativa o backend PostgreSQL da Database Layer                         (driver pg8000). Sem a var, usa SQLite
                        (data/od.db). Provisione com
                        `sudo bash runtime/install_postgres.sh`.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
from typing import Any, Awaitable, Callable, Optional

from core.event_bus import EventBus
from core.identity import parse_aliases
from core.logger import get_logger
from core.supervision import SupervisionRegistry, get_supervision

__signature__ = "OD // CORE"

log = get_logger("omega.runtime.launcher")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
DATA_DIR = REPO_ROOT / "data"


def load_env(path: pathlib.Path = ENV_PATH) -> dict[str, str]:
    """Carrega variáveis do .env (stdlib — sem python-dotenv)."""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


_ENV_CACHE: Optional[dict[str, str]] = None


def env(name: str, default: str = "") -> str:
    """Valor de ambiente: os.environ primeiro, .env depois."""
    global _ENV_CACHE
    if _ENV_CACHE is None:
        _ENV_CACHE = dict(os.environ)
        _ENV_CACHE.update(load_env())
    return _ENV_CACHE.get(name, default)


def build_audit_system() -> Any:
    """Audit System real (Fase 7.1): trilha persistente JSONL."""
    from observability.audit import AuditSystem

    configured = env("OD_AUDIT_FILE", "")
    file_path = (
        pathlib.Path(configured)
        if configured
        else REPO_ROOT / "logs" / "audit.jsonl"
    )
    return AuditSystem(file_path=file_path)


def build_rag() -> Optional[Any]:
    """Pipeline RAG (Parte B — NOMAD): corpus interno + retrieval no prompt.

    Indexa docs/ + knowledge/ (todo interno — o papel user/anônimo não
    recebe bloco nenhum, a visibilidade é por chunk), sincroniza de forma
    idempotente a cada boot e calibra a janela de tokens pelo modelo
    servido (OD_LLM_MODEL). Desde a v1.36.1 a sincronização roda em
    BACKGROUND: o índice persistido é carregado (store.load) e o boot
    segue — a re-sincronia completa em paralelo; consultas antes do fim
    degradam para "" (sem retrieval), como já era sem corpus.
    OD_RAG_SYNC_BACKGROUND=0 volta ao comportamento síncrono (testes).
    OD_RAG_ENABLED=0 desliga; falha degrada com None (o pipeline segue
    sem retrieval, nunca derruba o core).
    """
    if env("OD_RAG_ENABLED", "1") == "0":
        return None
    try:
        from memory.rag import RAGPipeline, fontes_padrao, janela_do_modelo
        from memory.vector import HashEmbeddingProvider, VectorStore
        from memory.rag import ProviderSemStopwords

        store = VectorStore(
            store_dir=DATA_DIR / "vector_memory",
            provider=ProviderSemStopwords(HashEmbeddingProvider()),
            top_k=24,  # coerente com TOP_K_CANDIDATOS (medição: alvo em 15º)
        )
        carregados = store.load()
        modelo = env("OD_LLM_MODEL", "qwen2.5-coder-3b")
        pipeline = RAGPipeline(
            store,
            fontes=fontes_padrao(REPO_ROOT),
            janela=janela_do_modelo(modelo),
            tokens_resposta=int(env("OD_LLM_MAX_TOKENS", "512")),
        )
        if env("OD_RAG_SYNC_BACKGROUND", "1") == "0":
            stats = pipeline.sync()
            log.info(
                "RAG ligado (Parte B NOMAD)",
                modelo=modelo,
                janela=janela_do_modelo(modelo),
                chunks=stats["chunks"],
                novos=stats["novos"],
                atualizados=stats["atualizados"],
                iguais=stats["iguais"],
                removidos=stats["removidos"],
            )
        else:
            # v1.36.1: sync em paralelo — a re-sincronia de 442 chunks de
            # 17/10 custou ~179s de boot esperando no caminho crítico.
            pipeline.sync_em_background()
            log.info(
                "RAG ligado (Parte B NOMAD) | sync em background",
                modelo=modelo,
                janela=janela_do_modelo(modelo),
                chunks_carregados=carregados,
            )
        return pipeline
    except Exception as exc:
        log.warn("RAG desabilitado", error=f"{type(exc).__name__}: {exc}")
        return None


def build_orchestrator(database: Any = None) -> Any:
    """Orchestrator real: LLM local + memórias persistentes em data/."""
    from core.llm import OpenAICompatProvider
    from core.orchestrator import Orchestrator, OrchestratorConfig
    from memory.cache import LLMCache
    from memory.history import ConversationHistory

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    llm_timeout = float(env("OD_LLM_TIMEOUT_S", "240"))
    provider = OpenAICompatProvider(
        name="gemma-local",
        base_url=env("OD_LLM_URL", "http://127.0.0.1:8081"),
        timeout=llm_timeout,
        # 512: resposta completa em CPU (~5 tok/s) mantém pior caso < 2min
        max_tokens=int(env("OD_LLM_MAX_TOKENS", "512")),
    )
    # Identidade da Interface Viva injetada por padrão (agents/personality)
    from agents.nicky_virthy.personality import (
        DEFAULT_PROFILE,
        get_system_prompt,
    )

    profile = env("OD_PROFILE", DEFAULT_PROFILE)
    # Mémoria: Database quando disponível, senão JSON (fallback)
    db_kwargs = {"database": database} if database is not None else {}
    # Parte B (NOMAD): retrieval no prompt + orçamento de tokens por modelo.
    # O orçamento só liga quando há RAG — sem ele, o comportamento do
    # histórico é exatamente o de antes (limite por turnos).
    rag = build_rag()
    from memory.rag import janela_do_modelo

    orchestrator = Orchestrator(
        providers=[provider],
        history=ConversationHistory(
            base_dir=DATA_DIR / "conversations", **db_kwargs
        ),
        cache=LLMCache(
            cache_dir=DATA_DIR / "llm_cache",
            profile=profile,
            max_entries=int(env("OD_CACHE_ENTRIES", "2000")),
            **db_kwargs,
        ),
        rag=rag,
        config=OrchestratorConfig(
            llm_timeout_s=llm_timeout,
            default_system_prompt=get_system_prompt(profile),
            orcamento_janela=(
                janela_do_modelo(env("OD_LLM_MODEL", "qwen2.5-coder-3b"))
                if rag is not None
                else 0
            ),
            orcamento_resposta=int(env("OD_LLM_MAX_TOKENS", "512")),
        ),
    )
    log.info(
        "Orchestrator real montado",
        llm=provider.name,
        url=provider.base_url,
        history=str(DATA_DIR / "conversations"),
        backend="db" if database else "json",
        rag=rag.dump() if rag is not None else "desligado",
    )
    return orchestrator


def build_push() -> Any:
    """Push FCM (core/push.py): registro de dispositivos + envio ao celular.

    Dormente por padrão: sem a service account (OD_FCM_CREDENTIALS ou
    config/firebase-service-account.json) o serviço sobe desligado — o
    registro de tokens continua funcionando, o envio é que não sai.
    OD_PUSH_ENABLED=0 desliga de vez. Ver docs/FIREBASE_SETUP.md.
    """
    from core.push import build_push_service, configure_push

    service = build_push_service(DATA_DIR)
    configure_push(service)
    return service


def build_user_store(database: Any) -> Optional[Any]:
    """UserStore (auth de usuários) — habilitado quando há Database.

    Compartilhado entre a API REST e o WebSocket: mesmas sessões e mesmas API
    keys nos dois transportes (o streaming precisa resolver a identidade igual
    ao POST /message). OD_AUTH_ENABLED=0 desliga.
    """
    if database is None or env("OD_AUTH_ENABLED", "1") == "0":
        return None
    try:
        from integrations.api.auth import UserStore

        store = UserStore(database)
        log.info("Auth de usuários habilitado")
        return store
    except Exception as exc:
        log.warn("Auth desabilitado", error=str(exc))
        return None


def build_registry(database: Any) -> Optional[Any]:
    """RegistryStore (Registro Mestre de peças) — habilitado com Database.

    Item 2 da pauta (2026-10-09): banco de todas as peças físicas com
    consulta pública de autenticidade. Sem Database degrada com None
    (a rota /registry/{codigo} responde 503).
    """
    if database is None:
        return None
    try:
        from core.registry import RegistryStore

        store = RegistryStore(database, photo_dir=DATA_DIR / "registry_photos")
        # Migração do ID antigo (OD-PROD-…) para o formato unificado —
        # idempotente; loga os pares para prova viva.
        migrados = store.migrar_ids_legados()
        if migrados:
            log.info("Registro Mestre: IDs migrados para o formato unificado",
                     total=len(migrados),
                     exemplo=f"{migrados[0][0]} -> {migrados[0][1]}")
        # Ciclo fechado da frente NV (16/10): toda coleção citada por
        # peça NV vira entidade ABERTA (idempotente) — peças anteriores
        # a esta frente não ficam órfãs; o dono encerra o ciclo quando
        # quiser fechar de verdade.
        criadas = store.criar_colecoes_de_pecas()
        if criadas:
            log.info("Coleções NV abertas a partir das peças existentes",
                     total=len(criadas), exemplo=criadas[0])
        log.info("Registro Mestre de peças habilitado")
        return store
    except Exception as exc:
        log.warn("Registro Mestre desabilitado", error=str(exc))
        return None


def build_download_queue() -> Optional[Any]:
    """Fila de downloads resumable (Parte D do NOMAD, 2026-10-14).

    Worker em thread própria dentro do processo da API: retomada por
    Range, retry com backoff, dedup e estado em
    data/downloads_fila.json — o que estava em voo volta para a fila no
    boot. Falha ao subir = fila None (rotas respondem 503); o resto do
    sistema nunca cai junto com um extra.
    """
    try:
        from core.downloads import DownloadQueue

        fila = DownloadQueue(
            max_tentativas=int(env("OD_DOWNLOADS_TENTATIVAS", "5")),
        )
        fila.start()
        log.info("Fila de downloads no ar", raiz=str(fila.raiz),
                 tentativas=fila.max_tentativas)
        return fila
    except Exception as exc:
        log.warn("Fila de downloads desabilitada", error=str(exc))
        return None


def build_auto_update(
    orchestrator: Any = None, fila: Any = None, health: Any = None,
    push: Any = None,
) -> Optional[Any]:
    """Auto-update de modelos/conteúdo (Parte E do NOMAD, 2026-10-14).

    Ciclo supervisionado com as camadas do Nômade: janela noturna,
    cool-off ancorado em "primeiro visto", só minor/patch, cap de bytes,
    auto-disable após 3 falhas duras e pre-flight de disco/sha/URL. O
    avaliar() é puro (o dry-run do painel usa o MESMO caminho); a
    execução é contida: download na fila da Parte D (retomada/sha de
    graça), re-sync do índice RAG idempotente, arquivo final staged em
    data/downloads (troca de modelo em uso é decisão do dono).

    Falha ao construir = None (o core segue sem auto-update — nunca
    derruba o processo por um extra). OD_UPDATE_ENABLED=0 desliga.
    `push` (PushService): aviso "auto-update aplicado" no celular do
    dono (TODO §3.8, 2026-10-16) — best-effort, nunca derruba o ciclo.
    """
    try:
        from core.auto_update import AutoUpdateService, ConfigUpdate

        cfg = ConfigUpdate.de_env(env)
        if not cfg.habilitado:
            return None

        rag = getattr(orchestrator, "rag", None) if orchestrator else None
        raiz = (fila.raiz if fila is not None
                else DATA_DIR / "downloads")
        svc = AutoUpdateService(
            cfg=cfg,
            estado_path=DATA_DIR / "auto_update_estado.json",
            manifesto_path=DATA_DIR / "auto_update_alvos.json",
            raiz_downloads=raiz,
            repo_root=REPO_ROOT,
            rag_sync_fn=(rag.sync if rag is not None else None),
            fila=fila,
            push=push,
        )
        svc.start()   # consumidor dos eventos da fila (sucesso/falha)
        # Manifesto editável do dono: nasce com o exemplo (só se não existe
        # — uma edição sua nunca é sobrescrita) para o fluxo ser descobrível.
        try:
            if not svc.manifesto_path.exists():
                from core.auto_update import MANIFESTO_EXEMPLO
                svc.manifesto_path.parent.mkdir(parents=True, exist_ok=True)
                svc.manifesto_path.write_text(
                    json.dumps(MANIFESTO_EXEMPLO, ensure_ascii=False,
                               indent=2),
                    encoding="utf-8",
                )
                log.info("Manifesto de auto-update criado",
                         arquivo=str(svc.manifesto_path))
        except Exception as exc:
            log.warn("Manifesto de auto-update não criado", error=str(exc))
        if health is not None:
            health.register("auto_update", svc.health_check, critical=False)
        log.info("Auto-update no ar (Parte E NOMAD)",
                 janela=cfg.janela, cooloff_h=cfg.cooloff_s / 3600.0,
                 cap_mb=cfg.cap_bytes // 1024 ** 2,
                 max_falhas=cfg.max_falhas,
                 intervalo_min=cfg.intervalo_s / 60.0,
                 rag=("ligado" if rag is not None else "ausente"))
        return svc
    except Exception as exc:
        log.warn("Auto-update desabilitado", error=str(exc))
        return None


def build_backups(push: Any = None) -> list[Any]:
    """Backups automáticos (TODO §3.6, 2026-10-16) — um por PERFIL.

    Ordem do dono: perfil `estado` (diário, 03:00) com `.env` + `data/`
    SEM `captures/` e SEM `vector_memory/`; perfil `capturas` (semanal,
    04:00) com as fotos/vídeos JUNTO — os dois LOCAIS (`backups/auto/` e
    `backups/auto-capturas/`), porque ele transfere para o HD externo. O
    snapshot é UM `.tar.gz` (fácil de copiar), gravado atômico (tmp →
    `os.replace`), `0600` porque leva o `.env` dentro.

    Catch-up em ambos: servidor desligado no horário/dia ⇒ o primeiro tick
    depois roda. Falha avisa no celular (best-effort, 1 push a cada 6 h) e
    cada perfil tem check não-crítico próprio no /health. `OD_BACKUP=0` e
    `OD_BACKUP_CAPTURAS=0` desligam cada um (loop/check/bloco somem).

    Em 17/10 entrou o terceiro tipo na mesma lista: o **snapshot de HD**
    (core/hd_backup.py) — um serviço POR HD externo (Mídias e Arquivos),
    interface par-a-par com o `BackupService`. Por isso ele vem daqui:
    loops, bloco `backup` do /dashboard/stats e checks do /health são
    genéricos na lista e vêm de graça. `OD_HD_SNAPSHOT=0` desliga só ele.
    """
    try:
        from core.backup import build_services

        servicos = build_services(repo_root=REPO_ROOT, env=env, push=push)
        if not servicos:
            log.info("Backups desligados (OD_BACKUP=0 e OD_BACKUP_CAPTURAS=0)")
        try:
            from core.hd_backup import build_hd_services

            servicos += build_hd_services(
                repo_root=REPO_ROOT, env=env, push=push
            )
        except Exception as exc:
            log.warn("Snapshots de HD desabilitados", error=str(exc))
        for svc in servicos:
            cfg = svc.cfg
            log.info(
                "Backup no ar (TODO §3.6)",
                perfil=cfg.nome,
                rotulo=cfg.rotulo,
                hora=cfg.hora,
                cadencia_dias=cfg.cadencia_dias,
                raiz=str(cfg.raiz),
                prefixo=cfg.prefixo,
                diarios=cfg.diarios,
                semanais=cfg.semanais,
                excluidos=",".join(cfg.excluidos),
                intervalo_min=round(cfg.intervalo_s / 60.0, 1),
            )
        return servicos
    except Exception as exc:
        log.warn("Backups automáticos desabilitados", error=str(exc))
        return []


async def _run_backup_forever(svc: Any) -> None:
    """Loop do backup (um por perfil): decisão a cada intervalo.

    O `tick()` avalia barato (config + estado + espaço em disco) e só
    empacota quando é hora; o empacotamento roda em `to_thread` — montar
    o tar é I/O (316 MB no perfil das capturas) e não pode prender o
    event loop dos outros loops. Exceção é contida no `_supervise`; um
    ciclo ruim não mata o loop.
    """
    while True:
        try:
            resultado = await asyncio.to_thread(svc.tick)
            if resultado.executado:
                log.info("Ciclo de backup encerrado",
                         perfil=svc.cfg.nome, ok=resultado.ok,
                         arquivo=resultado.arquivo, erro=resultado.erro)
        except asyncio.CancelledError:  # pragma: no cover — shutdown
            raise
        except Exception as exc:  # um ciclo ruim não mata o loop
            log.error("Ciclo de backup falhou", error=str(exc))
        await asyncio.sleep(svc.cfg.intervalo_s)


async def _run_auto_update_forever(svc: Any) -> None:
    """Loop do auto-update: um tick por intervalo, nunca quente.

    Cada tick é um `tick()` completo (avalia + executa + persiste) — e
    roda em thread (to_thread) porque o re-sync do RAG pode embutir
    chunks novos: I/O pesado não pode prender o event loop dos outros
    loops (Telegram/WebSocket dividem o mesmo loop). O janela/cool-off
    fazem o resto: fora da hora é avaliação barata; dentro, o que passou
    vai para a fila. Exceção é contida no _supervise.
    """
    while True:
        try:
            await asyncio.to_thread(svc.tick)
        except asyncio.CancelledError:  # pragma: no cover — shutdown
            raise
        except Exception as exc:  # um ciclo ruim não mata o loop
            log.error("Ciclo de auto-update falhou", error=str(exc))
        await asyncio.sleep(svc.cfg.intervalo_s)


def build_chat_notify() -> Optional[Any]:
    """Aviso de sala de bate-papo das peças → Telegram do dono (1.23.0).

    A API REST é síncrona (thread do http.server); o sink do Telegram é
    async no loop principal — o wrapper agenda a corrente com
    run_coroutine_threadsafe. Falha de envio nunca propaga (a mensagem
    da sala já foi gravada; o aviso é cortesia).
    """
    notify = build_telegram_sink("usuarios")  # Nexus anuncia a sala
    if notify is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover — fora do loop
        return None

    def sync_notify(text: str) -> None:
        try:
            asyncio.run_coroutine_threadsafe(notify(text), loop)
        except Exception:  # pragma: no cover
            log.debug("chat_notify não agendado")

    return sync_notify


def build_voice_handlers() -> tuple[Any, Any]:
    """Adaptadores SYNC de voz para a API REST (/transcribe e /tts).

    v1.17.3: o REST nunca teve os motores plugados — /transcribe e /tts
    respondiam 501 no ar; só o Telegram falava. Os handlers do APIServer são
    sync (BaseHTTPRequestHandler), então cada adaptador roda o motor async
    (WhisperSTT/PiperTTS) num event loop próprio por chamada — 1 thread por
    request, padrão do ThreadingHTTPServer.

    Retorna (stt, tts); um dos dois pode ser None quando o binário não existe
    ou OD_VOICE_STT/OD_VOICE_TTS=0 — a rota correspondente segue 501.
    """
    stt = tts = None
    loop_runner = asyncio.run

    # O binário Piper precisa das libs próprias (libespeak-ng, libpiper_phonemize,
    # libonnxruntime) que NÃO estão no loader path do sistema: sem
    # LD_LIBRARY_PATH ele morre com exit 127 — causa silenciosa de síntese
    # vazia. O deploy em /opt/omegadrakon/voice/piper traz as libs junto; o
    # diretório do próprio binário e o paralelo em /opt são os candidatos.
    # FORÇA o caminho correto (testes podem poluir o env com valor vazio/errado).
    lib_dir = None
    for candidato in (
        "/opt/omegadrakon/voice/piper",  # deploy real tem as libs
        str(REPO_ROOT / "voice" / "tts"),  # fallback repo
    ):
        if pathlib.Path(candidato, "libpiper_phonemize.so.1").is_file():
            lib_dir = candidato
            break
    if lib_dir:
        os.environ["LD_LIBRARY_PATH"] = lib_dir

    if env("OD_VOICE_STT", "1") != "0":
        from tools.audio import WhisperSTT

        whisper = WhisperSTT()
        if whisper.available:

            def _stt_handler(audio: bytes) -> Optional[str]:
                """bytes de áudio → texto (whisper.cpp via ffmpeg)."""
                with tempfile.TemporaryDirectory(prefix="od_api_stt_") as tmp_dir:
                    audio_path = pathlib.Path(tmp_dir) / "voz.webm"
                    audio_path.write_bytes(audio)
                    return loop_runner(whisper.transcribe(audio_path))

            stt = _stt_handler
            log.info("Voz STT habilitada na API (whisper.cpp)")
        else:
            log.warn("Voz STT indisponível na API — whisper.cpp ausente")

    if env("OD_VOICE_TTS", "1") != "0":
        from tools.audio import PiperTTS

        piper = PiperTTS()
        if piper.available:
            profile = env("OD_VOICE_PROFILE", "default")

            def _tts_handler(text: str) -> Optional[bytes]:
                """texto → bytes WAV (Piper, voz do perfil)."""
                return loop_runner(piper.synthesize(text, profile=profile))

            tts = _tts_handler
            log.info("Voz TTS habilitada na API (Piper)", voice=profile)
        else:
            log.warn("Voz TTS indisponível na API — Piper ausente")

    return stt, tts


def build_api_server(
    orchestrator: Any, metrics: Any = None, health: Any = None,
    action_registry: Any = None, push: Any = None, database: Any = None,
    user_store: Any = None, registry: Any = None, chat_notify: Any = None,
    vector: Any = None, downloads: Any = None, auto_update: Any = None,
    supply_depot: Any = None, nomad_tools: Any = None, notifier: Any = None,
    backups: Any = None,
):
    """APIServer (integrations/api) sobre o Orchestrator real."""
    from integrations.api import APIConfig, APIServer

    api_key = env("OD_API_KEY", "")
    host = env("OD_API_HOST", "0.0.0.0")  # LAN (site 192.168.0.250:8000)
    port = int(env("OD_API_PORT", "8000"))

    # UserStore (auth de usuários) — habilitado quando há database
    if user_store is None:
        user_store = build_user_store(database)

    # VectorStore do RAG (Parte B) — o MESMO store do prompt alimenta
    # GET /memory/{uid}/search (antes respondia 501: store nunca conectado).
    if vector is None and orchestrator is not None:
        rag = getattr(orchestrator, "rag", None)
        if rag is not None:
            vector = rag.store

    # Voz (v1.17.3): motores reais na API — /transcribe e /tts deixam de
    # ser 501 quando os binários da Fase 6 existem (mesmos do Telegram).
    voice_stt, voice_tts = build_voice_handlers()

    # auth_all: bind exposto na LAN exige X-API-Key em TODOS os endpoints
    server = APIServer(
        orchestrator,
        config=APIConfig(
            host=host,
            port=port,
            api_key=api_key,
            auth_all=env("OD_API_AUTH_ALL", "1") != "0",
            metrics=metrics,  # Fase 7.2: /metrics renderiza o coletor
            health=health,  # Fase 7.3: /health responde o agregado
            action_registry=action_registry,  # v1.2.0: /executa + /actions
            push=push,  # v1.3.0: /push/* (app Android)
            user_store=user_store,  # auth de usuários (registro/login/sessão)
            registry=registry,  # Registro Mestre de peças (item 2 pauta)
            chat_notify=chat_notify,  # sala das peças → Telegram do dono
            downloads=downloads,  # Parte D: fila de downloads resumable
            auto_update=auto_update,  # Parte E: auto-update de conteúdo
            supply_depot=supply_depot,  # Parte F: catálogo de ferramentas
            nomad_tools=nomad_tools,  # DECISÃO FINAL: saúde das 8 no stats
            notifier=notifier,  # métricas do notifier no Status (2026-10-16)
            backups=backups,  # TODO §3.6: perfis do backup automático
            public_url=env(  # Etapa 4: base do QR de posse no cartão
                "OD_PUBLIC_URL", "https://nicky-server.tail1b1f51.ts.net"
            ),
            stt=voice_stt,  # v1.17.3: /transcribe real (whisper.cpp)
            tts=voice_tts,  # v1.17.3: /tts real (Piper)
            # Freio contra força bruta no login (LoginGuard)
            login_max_attempts=int(env("OD_LOGIN_MAX_ATTEMPTS", "5")),
            login_window_s=float(env("OD_LOGIN_WINDOW_S", "300")),
            login_lockout_s=float(env("OD_LOGIN_LOCKOUT_S", "900")),
            # Alias de transporte legado → conta do dono (core/identity.py):
            # o app manda `user_id: "app"` fixo; apontar para a conta faz a
            # conversa do celular cair no histórico do dono.
            account_aliases=parse_aliases(env("OD_ACCOUNT_ALIASES", "")),
            # Conta do dono: a OD_API_KEY é a chave dele (o dono pode tudo,
            # com confirmação nas destrutivas).
            owner_username=env("OD_OWNER_USERNAME", "alex"),
        ),
        vector=vector,  # Parte B: /memory/{uid}/search com store real
    )
    return server


def build_ws_server(orchestrator: Any, user_store: Any = None) -> Optional[Any]:
    """WebSocket server para streaming token-a-token (v1.3.0).

    Roda em porta separada (OD_WS_PORT, padrão 8001) e compartilha
    o Orchestrator e o UserStore com a API REST.
    """
    # Verificar se streaming está habilitado
    if env("OD_WS_ENABLED", "1") == "0":
        return None

    api_key = env("OD_API_KEY", "")
    port = int(env("OD_WS_PORT", "8001"))
    api_keys = {api_key} if api_key else set()

    from integrations.api.ws_server import WebSocketServer

    server = WebSocketServer(
        orchestrator,
        port=port,
        api_keys=api_keys,
        user_store=user_store,  # sessão/API key de usuário também autenticam
        # Mesmo mapa do REST: o streaming do app cai no balde da conta.
        account_aliases=parse_aliases(env("OD_ACCOUNT_ALIASES", "")),
        # Mesma conta do dono do REST: define quem fala como admin no stream.
        owner_username=env("OD_OWNER_USERNAME", "alex"),
    )
    log.info(
        "WebSocket server configurado",
        port=port,
        auth="usuário+sessão" if user_store is not None else "OD_API_KEY",
    )
    return server


def build_database() -> Any:
    """Database Layer real (Fase 7.5): PostgreSQL (OD_DB_URL) ou SQLite.

    - `OD_DB_URL=postgres://user:pass@host:port/db` → backend PostgreSQL       (driver pg8000, Python puro);
    - sem OD_DB_URL → SQLite em data/od.db (comportamento legado).

    Conecta as actions de banco do catálogo (database_tables/schema/query)
    via configure_database().
    """
    from storage import Database
    from tools.actions import configure_database

    dsn = env("OD_DB_URL", "")
    if dsn:
        db = Database(pool_size=5, dsn=dsn)
        display = _mask_dsn(dsn)
    else:
        db = Database(REPO_ROOT / "data" / "od.db", pool_size=5)
        display = db.path
    configure_database(db)
    # path no log SEM credenciais (senha nunca vai para journald/syslog)
    log.info("Database Layer ativo", backend=db.backend, path=display)
    return db


def build_plugins() -> Any:
    """Plugin System real (Fase 7.4): carrega plugins de plugins/.

    Actions vão para um ActionRegistry e workflows para um WorkflowEngine
    (permission plugin.<nome> — gate do Security Layer na execução).
    """
    from core.workflows import WorkflowEngine
    from plugins import PluginManager
    from tools.registry import ActionRegistry

    registry = ActionRegistry()
    engine = WorkflowEngine()
    manager = PluginManager(
        root=REPO_ROOT / "plugins",
        registry=registry,
        workflow_engine=engine,
    )
    loaded = manager.load_all()
    log.info(
        "Plugin System ativo",
        plugins=loaded,
        root=str(manager.root),
    )
    return manager


def build_action_registry() -> Any:
    """Action Registry com as 56 actions do catálogo.

    Este registry é usado pelo Telegram Bot para executar actions via
    comando /executa (admin_only). As actions são registradas com
    permission própria (gate do Security Layer na execução).

    Retorna um ActionRegistry populado com todas as actions.
    """
    from core.security import SecurityManager
    from tools.actions import build_registry
    from tools.registry import ActionRegistry

    security = SecurityManager(mode="strict")
    registry = build_registry(security=security)
    # Home Assistant (v1.8.0): injeta o cliente HA nas actions iot_* — o
    # HA está no ar (health "HA alcançável") e as conversas mostravam o
    # LLM alucinando clima que o weather.* do HA sabe de verdade. Sem
    # credenciais, as actions degradam (ok=False) e o chat cai no LLM.
    try:
        from integrations.homeassistant import HAClient, HACredentials

        creds_path = REPO_ROOT / env(
            "OD_HA_CREDENTIALS", "config/iot_credentials.json"
        )
        if creds_path.exists():
            from tools.actions.actions import configure_ha_client

            client = HAClient(HACredentials.from_file(str(creds_path)))
            configure_ha_client(client)
            # Resolução de alvo do controle de luzes ('liga a luz da
            # cozinha' → switch.luz_cozinha_...): as entidades ficam em
            # memória no import; comandos revalidam o estado na execução.
            try:
                from core.intents import configure_ha_entities

                configure_ha_entities(client.list_states())
            except Exception as exc:  # pragma: no cover
                log.warn("Resolução de alvo de luzes sem entidades", error=str(exc))
            log.info("Actions iot_* ligadas ao Home Assistant")
    except Exception as exc:  # pragma: no cover — degrada sem HA
        log.warn("Actions iot_* sem Home Assistant", error=str(exc))
    # Google Workspace: injeta o GoogleClient nas actions google_*
    # — SOMENTE LEITURA. Sem credenciais/token, as actions degradam com
    # ok=False (o chat responde que o Google não está configurado) e nada
    # mais quebra; `runtime/google_auth.py` faz a autorização.
    try:
        from integrations.google import build_google_client

        google_creds = REPO_ROOT / env(
            "OD_GOOGLE_CREDENTIALS", "config/google_credentials.json"
        )
        google_token = REPO_ROOT / env(
            "OD_GOOGLE_TOKEN", "data/google_token.json"
        )
        if google_creds.exists():
            from tools.actions.actions import configure_google_client

            google_client = build_google_client(
                str(google_creds), str(google_token)
            )
            configure_google_client(google_client)
            log.info(
                "Actions google_* ligadas ao Google Workspace",
                autorizado=google_client.authorized,
            )
    except Exception as exc:  # pragma: no cover — degrada sem Google
        log.warn("Actions google_* sem credenciais do Google", error=str(exc))
    log.info(
        "Action Registry ativo",
        actions=registry.metrics.actions,
        security=True,
    )
    return registry


def build_health(
    orchestrator: Any = None,
    audit: Any = None,
    metrics: Any = None,
    database: Any = None,
) -> Any:
    """HealthMonitor real (Fase 7.3): checks dos componentes do od-core.

    Orchestrator e LLM são críticos (derrubam o status para down);
    Audit, Metrics, Database, Home Assistant e MQTT degradam
    (não-críticos). HA e MQTT são checks EXTERNOS (v1.0.0, item 1.4):
    começam como "não configurado (ok)" e são substituídos pelos checks
    reais via register_external_health_checks() quando os componentes
    existem no runtime.
    """
    from observability.health import HealthMonitor

    monitor = HealthMonitor()

    def _check_orchestrator(mon: Any) -> dict[str, Any]:
        if orchestrator is None:
            return {"ok": False, "status": "down", "detail": "sem orchestrator"}
        return {"ok": True, "status": "up", "detail": "orchestrator conectado"}

    def _check_llm(mon: Any) -> dict[str, Any]:
        if orchestrator is None:
            return {"ok": True, "status": "up", "detail": "LLM não avaliável"}
        available = []
        for provider in orchestrator.providers:
            probe = getattr(provider, "is_available", None)
            try:
                if probe is None or probe():
                    available.append(
                        getattr(provider, "name", "") or type(provider).__name__
                    )
            except Exception:  # pragma: no cover — sonda quebrou
                continue
        if available:
            return {
                "ok": True,
                "status": "up",
                "detail": f"{len(available)} provider(s): {', '.join(available)}",
            }
        return {"ok": False, "status": "down", "detail": "nenhum provider de LLM disponível"}

    def _check_audit(mon: Any) -> dict[str, Any]:
        if audit is None:
            return {"ok": True, "status": "up", "detail": "audit ausente (ok)"}
        h = audit.health()
        ok = bool(h.get("ok"))
        return {
            "ok": ok,
            "status": "up" if ok else "down",
            "detail": f"trilha {h.get('file')}",
        }

    def _check_metrics(mon: Any) -> dict[str, Any]:
        if metrics is None:
            return {"ok": True, "status": "up", "detail": "metrics ausente (ok)"}
        h = metrics.health()
        return {"ok": bool(h.get("ok")), "status": "up", "detail": f"{h.get('metrics')} métricas"}

    def _check_database(mon: Any) -> dict[str, Any]:
        if database is None:
            return {"ok": True, "status": "up", "detail": "database ausente (ok)"}
        h = database.health()
        return {
            "ok": bool(h.get("ok")),
            "status": "up" if h.get("ok") else "down",
            "detail": f"{h.get('tables')} tabelas",
        }

    def _check_homeassistant_placeholder(mon: Any) -> dict[str, Any]:
        """Placeholder até o PresenceMonitor (cliente HA) ser construído."""
        return {"ok": True, "status": "up", "detail": "homeassistant não configurado (ok)"}

    def _check_mqtt_placeholder(mon: Any) -> dict[str, Any]:
        """Placeholder até a ponte MQTT ser construída."""
        return {"ok": True, "status": "up", "detail": "mqtt não configurado (ok)"}

    def _check_loops(mon: Any) -> dict[str, Any]:
        """Loops do núcleo (2026-09-15): queda recente degrada o /health.

        Cada loop do modo all é supervisionado (não pode derrubar o core);
        este check é o que torna a queda visível em vez de silenciosa.
        """
        return get_supervision().health()

    monitor.register("orchestrator", _check_orchestrator, critical=True)
    monitor.register("llm", _check_llm, critical=True)
    monitor.register("audit", _check_audit, critical=False)
    monitor.register("metrics", _check_metrics, critical=False)
    monitor.register("database", _check_database, critical=False)
    # Checks externos não-críticos (v1.0.0 item 1.4) — sempre presentes;
    # o estado real entra quando o componente existe (register substitui).
    monitor.register("homeassistant", _check_homeassistant_placeholder, critical=False)
    monitor.register("mqtt", _check_mqtt_placeholder, critical=False)
    monitor.register("loops", _check_loops, critical=False)
    return monitor


def _homeassistant_check(presence: Any) -> Any:
    """Check externo do Home Assistant: delega ao health() do monitor real.

    presence.health() expõe ok/connected/detail a partir da última leitura
    do HA (PresenceMonitor marca _reachable True/False em cada poll).
    """

    def check(mon: Any) -> dict[str, Any]:
        try:
            h = presence.health()
        except Exception as exc:  # pragma: no cover — presença quebrada
            return {"ok": False, "status": "down", "detail": f"check quebrado: {type(exc).__name__}"}
        ok = bool(h.get("ok", True))
        detail = str(h.get("detail") or ("HA ok" if ok else "HA inacessível"))
        return {"ok": ok, "status": "up" if ok else "degraded", "detail": detail}

    return check


def _mqtt_check(bridge: Any) -> Any:
    """Check externo do MQTT/Mosquitto: delega ao health() da ponte real.

    MQTTBridge.health() reporta ok = conectado ao broker.
    """

    def check(mon: Any) -> dict[str, Any]:
        try:
            h = bridge.health()
        except Exception as exc:  # pragma: no cover — ponte quebrada
            return {"ok": False, "status": "down", "detail": f"check quebrado: {type(exc).__name__}"}
        ok = bool(h.get("ok") or h.get("connected"))
        host = h.get("host", "?")
        return {
            "ok": ok,
            "status": "up" if ok else "degraded",
            "detail": f"broker {host} " + ("conectado" if ok else "sem conexão"),
        }

    return check


def register_external_health_checks(
    health: Any,
    *,
    homeassistant: Any = None,
    mqtt: Any = None,
) -> None:
    """Registra (ou substitui) os checks externos não-críticos no monitor.

    v1.0.0 item 1.4: HA (via PresenceMonitor) e MQTT/Mosquitto (via ponte)
    entram no /health assim que os componentes existem no runtime. Quando o
    componente é None, o placeholder (ok) do build_health permanece.
    """
    if health is None:
        return
    if homeassistant is not None:
        health.register(
            "homeassistant", _homeassistant_check(homeassistant), critical=False
        )
    if mqtt is not None:
        health.register("mqtt", _mqtt_check(mqtt), critical=False)


def register_nomad_health_checks(health: Any) -> Any:
    """Registra as 8 ferramentas do stack Nômade no /health (não-crítico).

    A DECISÃO FINAL 12/10 pedia "integrar healthchecks dos tools no
    /health do OD" — antes desta peça as 9 eram invisíveis (Stirling PDF
    1.917 restarts em crash loop sem ninguém saber). Cada ferramenta vira
    um check `tool_<nome>` (core/nomad_tools.py); nenhuma é crítica: uma
    ferramenta fora degrada o /health em vez de derrubá-lo. Devolve o
    monitor (para o notifier) ou None quando desligado (OD_NOMAD_TOOLS=0).
    """
    if health is None:
        return None
    if env("OD_NOMAD_TOOLS", "1") == "0":
        log.info("Ferramentas Nômades fora do /health (OD_NOMAD_TOOLS=0)")
        return None
    from core.nomad_tools import monitor_padrao

    monitor = monitor_padrao()
    registrados = monitor.registrar_no_health(health)
    log.info(
        "Ferramentas Nômades no /health (DECISÃO FINAL)",
        ferramentas=len(registrados),
    )
    return monitor


def ligar_metricas_auto_update(metrics: Any, auto_update: Any) -> bool:
    """Põe o auto-update como fonte viva do coletor (TODO §3.2).

    O `/metrics` passa a expor os contadores do ciclo
    (`od_auto_update_tick_total`, `..._aplicado_total`, `..._falha_total`
    e os demais) sem abrir o painel. A ligação é **tardia** de propósito:
    o coletor nasce em `build_metrics` (o `/health` depende dele) e o
    serviço de auto-update só existe depois. Best-effort: sem coletor ou
    sem serviço (desligado por env), o boot segue igual e devolve False.
    """
    if metrics is None or auto_update is None:
        return False
    try:
        metrics.add_source(auto_update.prometheus_lines)
    except Exception as exc:  # pragma: no cover — coletor exótico
        log.warn("Métricas do auto-update não ligadas", error=str(exc))
        return False
    log.info("Métricas do auto-update no /metrics (TODO §3.2)")
    return True


def build_metrics(orchestrator: Any = None, audit: Any = None) -> Any:
    """Metrics Collector real (Fase 7.2): fontes vivas do od-core.

    Uptime, Orchestrator e Audit System expõem seus snapshots via sources;
    a API REST adiciona os contadores od_api_* (config.metrics).
    """
    from observability.metrics import MetricsCollector

    collector = MetricsCollector()
    started = time.time()

    def _uptime_source() -> list[str]:
        return [f"od_uptime_seconds {int(time.time() - started)}"]

    def _orchestrator_source() -> list[str]:
        if orchestrator is None:
            return []
        m = orchestrator.metrics.snapshot()
        lines = [
            "# TYPE od_processed_total counter",
            f"od_processed_total {m['processed']}",
            f"od_llm_total {m['llm']}",
            f"od_fallback_total {m['fallback']}",
            f"od_cache_hits_total {m['cache_hits']}",
            f"od_quick_total {m['quick']}",
            f"od_datetime_total {m['datetime']}",
            f"od_rate_limited_total {m['rate_limited']}",
            f"od_errors_total {m['errors']}",
        ]
        return lines

    def _audit_source() -> list[str]:
        if audit is None:
            return []
        m = audit.metrics.snapshot()
        return [
            "# TYPE od_audit_total counter",
            f"od_audit_total {m['total']}",
            f"od_audit_persisted_total {m['persisted']}",
            f"od_audit_allowed_total {m['allowed']}",
            f"od_audit_denied_total {m['denied']}",
            f"od_audit_failed_total {m['failed']}",
            f"od_audit_errors_total {m['errors']}",
        ]

    collector.add_source(_uptime_source)
    collector.add_source(_orchestrator_source)
    collector.add_source(_audit_source)
    return collector


def build_telegram_bot(
    orchestrator: Any,
    action_registry: Any = None,
    auto_extension: Any = None,
    user_store: Any = None,
):
    """TelegramBot real (HTTPTransport) sobre o Orchestrator.

    Voz (v0.21.0): se os binários reais da Fase 6 existirem, o bot
    transcreve áudios recebidos (whisper.cpp) e responde por voz (Piper)
    — controlado por OD_VOICE_STT / OD_VOICE_TTS.
    Auto Extension (v0.27.4): quando disponível, expõe /gerar no bot.
    """
    from integrations.telegram import HTTPTransport, TelegramBot

    token = env("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN ausente — configure o .env (veja runtime/launcher.py)"
        )
    admins = _admin_ids()
    transport = HTTPTransport(token, timeout=30.0)
    offset_file = env("OD_TELEGRAM_OFFSET_FILE", "")

    stt = tts = None
    if env("OD_VOICE_STT", "1") != "0":
        from integrations.telegram.voice import TelegramVoiceSTT
        from tools.audio import WhisperSTT

        whisper = WhisperSTT()
        if whisper.available:
            stt = TelegramVoiceSTT(whisper)
            log.info("Voz STT habilitada (whisper.cpp)")
        else:
            log.warn("Voz STT indisponível — whisper.cpp ausente")
    if env("OD_VOICE_TTS", "1") != "0":
        from integrations.telegram.voice import TelegramVoiceTTS
        from tools.audio import PiperTTS

        piper = PiperTTS()
        if piper.available:
            profile = env("OD_VOICE_PROFILE", "default")
            tts = TelegramVoiceTTS(piper, profile=profile)
            log.info("Voz TTS habilitada (Piper)", voice=profile)
        else:
            log.warn("Voz TTS indisponível — Piper ausente")

    bot = TelegramBot(
        transport,
        orchestrator,
        admin_ids=admins,
        stt=stt,
        tts=tts,
        offset_file=(
            offset_file or str(DATA_DIR / "telegram_offset.json")
        ),
        action_registry=action_registry,
        auto_extension=auto_extension,
        # Mesmo mapa do REST/WS: o chat do Telegram cai no balde da conta.
        account_aliases=parse_aliases(env("OD_ACCOUNT_ALIASES", "")),
        # UserStore: /entrar vincula o chat a uma conta (histórico contínuo).
        user_store=user_store,
    )
    return bot


def build_presence_monitor() -> Any:
    """PresenceMonitor (Fase 6.2) sobre o Home Assistant real.

    Lê as credenciais de config/iot_credentials.json (token do HA),
    monitora person.*/device_tracker.* e notifica o admin no Telegram
    quando alguém chega ou sai de casa. Retorna None sem credenciais.
    """
    from integrations.homeassistant import (
        HACredentials,
        HAClient,
        PresenceConfig,
        PresenceMonitor,
    )

    creds_path = env("OD_HA_CREDENTIALS", "config/iot_credentials.json")
    path = REPO_ROOT / creds_path
    if not path.exists():
        log.warn("Presence desativado — sem credenciais HA", path=str(path))
        return None
    try:
        creds = HACredentials.from_file(path)
    except Exception as exc:  # pragma: no cover — arquivo corrompido
        log.warn("Presence desativado — credenciais HA inválidas", error=str(exc))
        return None
    client = HAClient(creds)
    monitor = PresenceMonitor(
        client,
        config=PresenceConfig(
            poll_interval_s=float(env("OD_PRESENCE_POLL_S", "30")),
            state_file=str(DATA_DIR / "presence_state.json"),
        ),
    )
    return monitor


def build_face_detector() -> Optional[Any]:
    """FaceDetector real (Fase 6.1) sobre a webcam do servidor.

    Retorna None se o OpenCV não estiver disponível ou a webcam não abrir.
    Notifica o admin no Telegram quando uma presença facial é confirmada
    (buffer 3 detecções consecutivas — sem alarme falso de sombra).
    """
    from tools.vision import CV2_AVAILABLE, FaceConfig, FaceDetector

    if not CV2_AVAILABLE:
        log.warn("Vision desativado — OpenCV ausente")
        return None
    detector = FaceDetector(
        config=FaceConfig(
            device=env("OD_VISION_DEVICE", "/dev/video0"),
            poll_interval_s=float(env("OD_VISION_POLL_S", "5.0")),
            captures_dir=str(DATA_DIR / "captures"),
        )
    )
    if detector._cascade is None:
        log.warn("Vision desativado — Haar Cascade indisponível")
        return None
    return detector


def build_mqtt_bridge(event_bus: Any):
    """MQTTBridge real sobre o broker Mosquitto (env OD_MQTT_*)."""
    from integrations.mqtt import MQTTBridge, MQTTClient, MQTTConfig

    client = MQTTClient(
        env("OD_MQTT_HOST", "127.0.0.1"),
        int(env("OD_MQTT_PORT", "1883")),
        client_id=env("OD_MQTT_CLIENT_ID", "od-core"),
        username=env("OD_MQTT_USERNAME", "") or None,
        password=env("OD_MQTT_PASSWORD", "") or None,
        keepalive=30,
    )
    bridge = MQTTBridge(
        client,
        event_bus=event_bus,
        config=MQTTConfig(poll_timeout_s=0.5, reconnect_delay_s=5.0),
    )
    # Tópicos de entrada (mensagens → Event Bus como mqtt.message)
    topics = [
        t.strip()
        for t in env("OD_MQTT_SUBSCRIBE", "od/in/#").split(",")
        if t.strip()
    ]
    bridge.subscribe(topics)
    return bridge


async def _run_api_forever(
    orchestrator: Any, metrics: Any = None, health: Any = None,
    action_registry: Any = None, push: Any = None, database: Any = None,
    downloads: Any = None, auto_update: Any = None, supply_depot: Any = None,
    nomad_tools: Any = None, notifier: Any = None, backups: Any = None,
) -> None:
    # Um único UserStore para REST e WebSocket: mesma sessão vale nos dois.
    user_store = build_user_store(database)
    # Registro Mestre de peças (item 2 da pauta) — banco + consulta pública.
    registry = build_registry(database)
    # Avisos da sala de bate-papo das peças ao dono no Telegram (1.23.0).
    chat_notify = build_chat_notify()
    # Fila de downloads resumable (Parte D do NOMAD) — worker próprio.
    # No modo all ela vem de fora compartilhada com o auto-update (Parte E).
    downloads = downloads if downloads is not None else build_download_queue()
    # Conecta o ActionRegistry ao Orchestrador TAMBÉM no caminho da API:
    # sem isto o fast path de intenções (Etapa 3.5) fica desligado no chat —
    # "qual o ip do servidor?" caía no LLM em vez da action real (v1.6.1).
    # Antes o connect era feito só no loop do Telegram.
    if action_registry is not None:
        orchestrator.set_action_registry(action_registry)
        log.info("ActionRegistry conectado ao Orchestrator (API)")
    server = build_api_server(
        orchestrator, metrics=metrics, health=health,
        action_registry=action_registry, push=push, database=database,
        user_store=user_store, registry=registry, chat_notify=chat_notify,
        downloads=downloads, auto_update=auto_update,
        supply_depot=supply_depot,  # Parte F: Supply Depot no painel
        nomad_tools=nomad_tools,  # DECISÃO FINAL: saúde das 8 no stats
        notifier=notifier,  # métricas do notifier no /dashboard/stats
        backups=backups,  # TODO §3.6: um bloco por perfil no stats
    )
    server.serve_background()
    log.info("API REST no ar", port=server.bound_port)

    # WebSocket server para streaming (v1.3.0). Opcional por natureza: se não
    # subir (porta ocupada, websockets ausente), a falha fica contida aqui — o
    # REST e o resto do núcleo NÃO podem cair por causa de um extra de chat.
    ws_server = None
    try:
        ws_server = build_ws_server(orchestrator, user_store=user_store)
        if ws_server:
            ws_server.start()
    except Exception as exc:
        log.warn(
            "WebSocket server não subiu — seguindo sem streaming",
            error=f"{type(exc).__name__}: {exc}",
        )
        ws_server = None

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:  # pragma: no cover
        server.stop()
        if downloads is not None:
            downloads.stop()   # o estado é gravado; o boot re-enfileira
        if ws_server:
            ws_server.stop()


async def _run_telegram_forever(
    orchestrator: Any,
    action_registry: Any = None,
    auto_extension: Any = None,
    database: Any = None,
) -> None:
    bot = build_telegram_bot(
        orchestrator,
        action_registry=action_registry,
        auto_extension=auto_extension,
        user_store=build_user_store(database),
    )
    log.info("Telegram bot iniciando polling...", admins=len(bot.admin_ids))
    await bot.run(interval=1.0)
    # Conecta ActionRegistry ao Orchestrator para execução de ações
    if action_registry is not None:
        orchestrator.set_action_registry(action_registry)
        log.info("ActionRegistry conectado ao Orchestrator")


def build_supply_depot(action_registry: Any, health: Any = None) -> Optional[Any]:
    """Supply Depot (Parte F do NOMAD, 2026-10-15).

    Catálogo persistente de ferramentas/skills do orquestrador, estilo
    catálogo do Nômade: pré-voo antes de instalar/atualizar (conflito de
    nome, versão semver com downgrade bloqueado, tamanho/disco), backup +
    rollback de cada versão e customização do dono que sobrevive a
    atualização. No boot, `carregar()` restaura tudo no ActionRegistry —
    a ferramenta gerada pelo /gerar não some mais quando o core reinicia.

    Falha ao construir = None (o core segue sem depot — nunca derruba o
    processo por um extra). OD_SUPPLY_DEPOT=0 desliga.
    """
    if action_registry is None:
        return None
    if env("OD_SUPPLY_DEPOT", "1") == "0":
        return None
    try:
        from tools.supply_depot import SupplyDepot

        depot = SupplyDepot(
            registry=action_registry,
            catalogo_path=DATA_DIR / "ferramentas_catalogo.json",
            codigos_dir=DATA_DIR / "ferramentas",
            backup_dir=DATA_DIR / "ferramentas_backup",
            raiz=DATA_DIR,
        )
        estado = depot.carregar()
        if health is not None:
            health.register("supply_depot", depot.health_check, critical=False)
        log.info("Supply Depot no ar (Parte F NOMAD)",
                 carregadas=estado["carregadas"], erros=estado["erros"],
                 catalogo=depot.resumo()["total"])
        return depot
    except Exception as exc:
        log.warn("Supply Depot desabilitado", error=str(exc))
        return None


def build_auto_extension(
    orchestrator: Any, action_registry: Any, depot: Any = None,
) -> Optional[Any]:
    """Auto Extension (Fase 6.6): gera ferramentas via LLM no registry.

    Usa o primeiro provider LLM do Orchestrator (generate/prompt, timeout)
    e registra no ActionRegistry com permission auto_extension.generated
    (Security Layer media toda execução). Exposto no bot via /gerar.

    Com o Supply Depot (Parte F), o /gerar passa a: pré-voar ANTES do LLM
    (conflito honesto, sem custo de token) e persistir a ferramenta gerada
    em disco (sobrevive a restart, atualizável com rollback).
    """
    if action_registry is None or orchestrator is None:
        return None
    from core.security import SecurityManager
    from tools.auto_extension import AutoExtension

    providers = list(getattr(orchestrator, "providers", None) or [])
    if not providers:
        return None
    return AutoExtension(
        llm=providers[0],
        registry=action_registry,
        security=SecurityManager(mode="strict"),
        depot=depot,
    )


def build_recovery(
    audit: Any = None,
    health: Any = None,
) -> Optional[Any]:
    """RecoveryLoop (v0.27.4): percepção periódica + auto-reparo.

    Fecha o loop de auto-recuperação: Telemetry.collect() periódica alimenta
    o check "perception" do Health Monitor; SelfRepairEngine repara .py
    quebrados mediado pelo Coder Engine. OD_SELF_REPAIR_ENABLED=0 desliga.
    """
    from core.coder import CoderEngine
    from core.recovery import RecoveryLoop
    from core.self_repair import SelfRepairEngine
    from tools.telemetry import Telemetry

    if env("OD_SELF_REPAIR_ENABLED", "1") == "0":
        return None
    coder = CoderEngine(root=REPO_ROOT)
    repair = SelfRepairEngine(coder=coder)
    loop = RecoveryLoop(
        root=REPO_ROOT,
        telemetry=Telemetry(),
        repair=repair,
        audit=audit,
        interval_s=float(env("OD_RECOVERY_INTERVAL_S", "300")),
    )
    if health is not None:
        health.register("perception", loop.perception_check, critical=False)
    return loop


def build_notifier(
    orchestrator: Any,
    *,
    sink: Any = None,
    event_bus: Any = None,
    push: Any = None,
    nomad_tools: Any = None,
    health: Any = None,
) -> Optional[Any]:
    """ProactiveNotifier (Fase 5.3): alertas proativos com sinks plugáveis.

    Sondas padrão (orchestrator/llm/disco/restart) com anti-spam (1/hora) e
    estado persistido em data/notifier_state.json. OD_NOTIFIER_ENABLED=0
    desliga.

    Sinks: Telegram (texto ao admin) e push FCM (alerta no app — o mesmo
    texto vira notificação no celular; push desligado não é erro).

    `nomad_tools` (monitor das 8 ferramentas do stack Nômade, ligado no
    main via register_nomad_health_checks) adiciona a sonda `tool:<nome>`
    — ferramenta fora por 120s+ vira alerta no Telegram.

    Observabilidade/Alertas (TODO §3.6, 2026-10-16) — duas pontes novas:
      * `health`: o HealthMonitor do /health entra no notifier →
        degraded/down vira mensagem pro dono (OD_NOTIFIER_HEALTH=0 desliga);
      * NRestarts do systemd → queda anormal do od-core vira mensagem
        (OD_NOTIFIER_NRESTARTS=0 desliga; só liga com INVOCATION_ID —
        dentro de serviço systemd — ou OD_SERVICE_UNIT explícito).
    O limiar de disco passa a ser configurável: OD_DISK_THRESHOLD_PERCENT
    (padrão 85, o do legado).
    """
    from integrations.notifier import (
        DEFAULT_DISK_THRESHOLD_PERCENT,
        NotifierConfig,
        ProactiveNotifier,
        nrestarts_do_systemd,
    )

    if env("OD_NOTIFIER_ENABLED", "1") == "0":
        return None
    sinks = [s for s in (sink, push.sink() if push is not None else None)
             if s is not None]
    config = NotifierConfig(
        state_file=DATA_DIR / "notifier_state.json",
        disk_threshold_percent=float(
            env("OD_DISK_THRESHOLD_PERCENT",
                str(DEFAULT_DISK_THRESHOLD_PERCENT))
        ),
    )
    health_monitor = health if env("OD_NOTIFIER_HEALTH", "1") != "0" else None
    unidade = env("OD_SERVICE_UNIT", "od-core.service")
    em_systemd = bool(os.environ.get("INVOCATION_ID")) or bool(
        env("OD_SERVICE_UNIT", "")
    )
    nrestarts_fn = None
    if env("OD_NOTIFIER_NRESTARTS", "1") != "0" and em_systemd:
        from functools import partial

        nrestarts_fn = partial(nrestarts_do_systemd, unidade)
    return ProactiveNotifier(
        orchestrator,
        config=config,
        sinks=sinks,
        event_bus=event_bus,
        nomad_tools=nomad_tools,
        health_monitor=health_monitor,
        nrestarts_fn=nrestarts_fn,
        unidade=unidade,
    )


async def _run_recovery_forever(loop: Any) -> None:
    """Ciclo de auto-recuperação: percepção + auto-reparo periódico."""
    log.info(
        "RecoveryLoop iniciando ciclo periódico...",
        interval_s=loop.interval_s,
    )
    await loop.run()


async def _run_mqtt_forever(bridge: Any) -> None:
    """Loop da ponte MQTT (reconecta sozinha se o broker cair)."""
    log.info("Ponte MQTT iniciando loop...")
    await bridge.run()


# Três bots do dono (divisão dele em 20/10): um bot por papel. O vazio
# de um papel cai no bot de chat — degradação honesta: um bot fora
# nunca cala o sistema.
PAPEIS_BOT: dict[str, tuple[str, str]] = {
    # @Nicky_Virthy_bot — conversa, comandos do dono
    "chat": ("TELEGRAM_BOT_TOKEN", "OD_TELEGRAM_ADMINS"),
    # @Nexus_Nicky_bot — alertas de usuários pedindo informação
    # (💬 chat das peças, 🔑 registro de posse)
    "usuarios": ("OD_TELEGRAM_USUARIOS_TOKEN", "OD_TELEGRAM_USUARIOS_CHAT"),
    # @nicky_monitor_bot — monitoramento e alertas do sistema
    # (notifier, presença, face, orquestrador)
    "monitor": ("OD_TELEGRAM_MONITOR_TOKEN", "OD_TELEGRAM_MONITOR_CHAT"),
}


def _chat_ids(chave: str) -> set[int]:
    return {
        int(part)
        for part in env(chave, "").split(",")
        if part.strip().isdigit()
    }


def _admin_ids() -> set[int]:
    return _chat_ids("OD_TELEGRAM_ADMINS")


def build_telegram_sink(papel: str = "chat") -> Optional[Any]:
    """Sink de notificação no Telegram do dono — um bot por papel.

    Divisão do dono (20/10), 3 bots, 3 papéis:

      * ``chat`` — a Nicky (@Nicky_Virthy_bot): conversa, comandos;
      * ``usuarios`` — @Nexus_Nicky_bot: alertas de usuários pedindo
        informação (💬 chat das peças, 🔑 registro de posse);
      * ``monitor`` — @nicky_monitor_bot: monitoramento/alertas do
        sistema (notifier, presença, face, resumo do orquestrador).

    Cada papel tem token e chat próprios (``OD_TELEGRAM_<PAPEL>_TOKEN`` /
    ``OD_TELEGRAM_<PAPEL>_CHAT``) e, quando vazios, **cai no bot de
    chat** — um token ausente degrada, não silencia.
    """
    from integrations.telegram import HTTPTransport

    token_env, chat_env = PAPEIS_BOT.get(papel, PAPEIS_BOT["chat"])
    token = env(token_env, "") or env("TELEGRAM_BOT_TOKEN", "")
    chats = sorted(_chat_ids(chat_env)) or sorted(_admin_ids())
    if not token or not chats:
        return None
    transport = HTTPTransport(token, timeout=20.0)
    chat_id = chats[0]

    async def notify(text: str) -> None:
        await transport.send_message(chat_id, text)

    return notify


async def _send_presence_welcome(sink: Any) -> None:
    """Aviso único de ativação do presence (persistido — sem spam)."""
    flag = DATA_DIR / "presence_welcome_sent.flag"
    if flag.exists():
        return
    try:
        await sink(
            "🟢 Monitor de presença ativo — agora acompanho o Home "
            "Assistant e aviso quando você chegar ou sair de casa."
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        flag.write_text("1", encoding="utf-8")
    except Exception as exc:  # pragma: no cover — rede falhou
        log.warn("Aviso de ativação não enviado", error=str(exc))


async def _run_vision_forever(event_bus: Any, detector: Any) -> None:
    """Loop do Face Detector (webcam) com notificação de presença.

    Usa o MESMO Event Bus do núcleo (barramento único — presença/MQTT/
    visão compartilham o bus). Correção v0.28.1: a chamada passava 2 args
    e a assinatura aceitava 1 — crash no startup do modo all quando a
    webcam está habilitada (OD_VISION_ENABLED=1).

    Correção (2026-09-14): o Event Bus entrega o `Event` ao handler (o payload
    fica em `event.data`) — o handler antigo chamava `.get()` direto no
    Event e caía em `AttributeError: 'Event' object has no attribute 'get'`
    a cada `face.presence`, esgotando as 3 tentativas e indo para dead
    letter (visível no journal do od-core até 2026-09-14).
    """
    sink = build_telegram_sink("monitor")
    notified = False

    async def on_change(event: Any) -> None:
        """Presença facial confirmada → aviso único no Telegram."""
        nonlocal notified
        data = getattr(event, "data", None) or {}
        if not isinstance(data, dict) or not data.get("confirmed"):
            return
        if sink is not None and not notified:
            await sink(
                "👤 Presença facial detectada na câmera do servidor "
                "(alguém está na frente)."
            )
            notified = True

    from tools.vision import FACE_TOPIC

    event_bus.subscribe_handler(FACE_TOPIC, on_change)
    detector.event_bus = event_bus
    log.info("Face Detector iniciando captura da webcam...")
    await detector.run()


async def _run_presence_forever(monitor: Any) -> None:
    """Loop do Presence Monitor (poll no HA + notificação Telegram)."""
    sink = build_telegram_sink("monitor")
    if sink is not None:
        from integrations.homeassistant import PresenceMonitor

        async def notify(change: Any) -> None:
            await sink(PresenceMonitor.format_change(change))

        monitor.add_sink(notify)
        await _send_presence_welcome(sink)
    log.info("Presence Monitor iniciando poll no HA...")
    await monitor.run()


async def _supervise(
    name: str,
    factory: Callable[[], Awaitable[None]],
    *,
    restart: bool = True,
    delay_s: float = 5.0,
    registry: Optional[SupervisionRegistry] = None,
) -> None:
    """Roda um loop do núcleo isolado: a morte dele não derruba o processo.

    O `asyncio.gather(*tasks)` do modo all propaga qualquer exceção de
    qualquer task — foi por isso que um timeout de rede do Telegram derrubou o
    core INTEIRO 89 vezes entre 2026-09-13 e 2026-09-15 (o systemd reiniciava
    o serviço a cada queda, ~10 s fora do ar). Aqui a exceção fica contida, é
    registrada e, se o loop for reiniciável, ele volta com espera; os outros
    loops nunca param.

    Cada queda entra no registro de supervisão (core/supervision.py), que
    alimenta o check "loops" do /health e o alerta do notifier.

    Args:
        name:     Rótulo do loop no log (api, telegram, mqtt, presence...).
        restart:  False para loops que não podem ser recriados — a API sobe o
                  servidor HTTP no primeiro build, então recriá-la conflita
                  na porta.
        delay_s:  Espera antes de reiniciar (evita laço quente).
        registry: Registro de supervisão (default: o do processo).
    """
    supervision = registry if registry is not None else get_supervision()
    while True:
        try:
            await factory()
        except asyncio.CancelledError:  # pragma: no cover — shutdown normal
            raise
        except Exception as exc:  # pragma: no cover — loop quebrou
            queda = supervision.record_drop(
                name, kind=type(exc).__name__, detail=str(exc)
            )
            log.error(
                "Loop do núcleo caiu",
                loop=name, error=type(exc).__name__, detail=str(exc),
                quedas=queda.failures,
            )
        else:  # pragma: no cover — loop retornou sozinho
            supervision.record_drop(
                name, kind="Returned", detail="loop retornou sozinho"
            )
            log.warn("Loop do núcleo retornou", loop=name)
        if not restart:
            return
        restarts = supervision.record_restart(name)
        log.warn(
            "Loop do núcleo reiniciando", loop=name,
            delay_s=delay_s, reinicios=restarts,
        )
        await asyncio.sleep(delay_s)


def _mask_dsn(dsn: str) -> str:
    """Mascara a senha de um DSN para logs (nunca expor credencial)."""
    try:
        import urllib.parse

        parsed = urllib.parse.urlparse(dsn)
        host = parsed.hostname or ""
        port = parsed.port or ""
        db = (parsed.path or "/").lstrip("/")
        user = urllib.parse.unquote(parsed.username or "")
        auth = f"{user}@" if user else ""
        return f"postgres://{auth}{host}:{port}/{db}"
    except Exception:  # pragma: no cover — fallback genérico
        return "postgres://<dsn>"


def _build_event_bus() -> EventBus:
    """Cria o EventBus único usado em todos os modos (exceto modo dedicado)."""
    return EventBus()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    # Modo de introspecção: imprime o manifesto de capacidades e sai.
    if mode == "capabilities":
        from core.capabilities import render_json
        print(render_json())
        return 0
    # Database Layer é montada PRIMEIRO (v1.0.0 item 1.2 — memória usa DB)
    database = build_database()
    orchestrator = build_orchestrator(database=database)
    audit = build_audit_system()
    audit.record(
        source="launcher",
        action="system.startup",
        outcome="info",
        detail=f"od-core no ar (modo {mode}).",
        data={"mode": mode, "pid": os.getpid()},
    )
    log.info(
        "Audit System ativo",
        file=str(audit.file_path) if audit.file_path else "(memória)",
    )
    metrics = build_metrics(orchestrator=orchestrator, audit=audit)
    log.info(
        "Metrics Collector ativo",
        sources=metrics.health()["sources"],
    )
    health = build_health(
        orchestrator=orchestrator,
        audit=audit,
        metrics=metrics,
        database=database,
    )
    log.info(
        "Health Monitor ativo",
        components=len(health.components),
    )
    # Plugin System: acessível via plugins.registry e plugins.engine
    # (Fase 7.4) — carrega plugins de plugins/ com actions e workflows.
    plugins = build_plugins()
    # Action Registry: o catálogo de 56 actions está disponível para
    # execução via Telegram Bot (/executa) e Orchestrator.
    action_registry = build_action_registry()
    # Supply Depot (Parte F do NOMAD): catálogo persistente de ferramentas
    # com pré-voo/rollback — restaura no boot ANTES do auto-extension.
    supply_depot = build_supply_depot(action_registry, health=health)
    # Auto Extension (v0.27.4): gera ferramentas via LLM (/gerar no bot).
    auto_extension = build_auto_extension(
        orchestrator, action_registry, depot=supply_depot,
    )
    # RecoveryLoop (v0.27.4): fecha o loop — percepção + auto-reparo.
    recovery = build_recovery(audit, health)
    mqtt_enabled = env("OD_MQTT_ENABLED", "1") != "0"
    presence_enabled = env("OD_PRESENCE_ENABLED", "1") != "0"
    presence_monitor = build_presence_monitor() if presence_enabled else None
    vision_enabled = env("OD_VISION_ENABLED", "0") != "0"
    face_detector = build_face_detector() if vision_enabled else None
    # Checks externos (v1.0.0 item 1.4): presence monitor pronto no main
    register_external_health_checks(health, homeassistant=presence_monitor)
    # Ferramentas Nômades (DECISÃO FINAL): as 8 do compose entram no
    # /health (tool_kiwix, tool_stirling_pdf...) e no notifier.
    nomad_tools_monitor = register_nomad_health_checks(health)
    # Push FCM: registro de dispositivos + alertas no celular (v1.3.0).
    push = build_push()
    # Fila de downloads (Parte D) compartilhada: API REST + auto-update.
    downloads = build_download_queue()
    # Auto-update de modelos/conteúdo (Parte E do NOMAD).
    auto_update = build_auto_update(
        orchestrator, fila=downloads, health=health,
        push=push,  # aviso FCM "auto-update aplicado" (TODO §3.8)
    )
    # Métricas Prometheus do auto-update (TODO §3.2): o serviço entra como
    # fonte viva do coletor DEPOIS de montado (o coletor existe antes
    # dele — build_metrics roda cedo, o health depende dele).
    ligar_metricas_auto_update(metrics, auto_update)
    # Backups automáticos (TODO §3.6): perfil do estado (diário, 03:00) e
    # perfil das capturas (semanal, 04:00) — cada um com check não-crítico
    # próprio no /health.
    backups = build_backups(push=push)
    for _svc_backup in backups:
        _svc_backup.registrar_no_health(health)

    async def _all() -> None:
        # Event Bus único da entrega (bridge MQTT ↔ núcleo)
        event_bus = EventBus()
        # Cada loop vai supervisionado: um que cai sozinho não pode levar o
        # core junto (o gather propaga a exceção de qualquer task).
        tasks = [
            _supervise("api", lambda: _run_api_forever(
                orchestrator, metrics, health,
                action_registry=action_registry, push=push, database=database,
                downloads=downloads, auto_update=auto_update,
                supply_depot=supply_depot,  # Parte F: Supply Depot
                nomad_tools=nomad_tools_monitor,  # DECISÃO FINAL: 9 tools
                # métricas no Status — fechamento tardio: o notifier é
                # construído logo abaixo, ainda ANTES do gather invocar
                # esta factory.
                notifier=notifier,
                backups=backups,  # TODO §3.6: bloco por perfil no stats
            ), restart=False),
            _supervise("telegram", lambda: _run_telegram_forever(
                orchestrator,
                action_registry=action_registry,
                auto_extension=auto_extension,
                database=database,
            )),
        ]
        if auto_update is not None:
            tasks.append(_supervise(
                "auto-update", lambda: _run_auto_update_forever(auto_update),
            ))
            log.info("Loop de auto-update habilitado (Parte E NOMAD)")
        for _svc_backup in backups:
            tasks.append(_supervise(
                f"backup-{_svc_backup.cfg.nome}",
                lambda svc=_svc_backup: _run_backup_forever(svc),
            ))
            log.info("Loop de backup habilitado (TODO §3.6)",
                     perfil=_svc_backup.cfg.nome)
        if recovery is not None:
            tasks.append(
                _supervise("recovery", lambda: _run_recovery_forever(recovery))
            )
            log.info("RecoveryLoop habilitado (percepção + auto-reparo)")
        notifier = build_notifier(
            orchestrator,
            sink=build_telegram_sink("monitor"),
            event_bus=event_bus,
            push=push,
            nomad_tools=nomad_tools_monitor,
            health=health,
        )
        if notifier is not None:
            notifier.start()
            log.info(
                "ProactiveNotifier habilitado (alertas proativos)",
                health_ponte=notifier.health_monitor is not None,
                nrestarts=notifier.nrestarts_fn is not None,
                disco_pct=notifier.config.disk_threshold_percent,
            )
        if mqtt_enabled:
            bridge = build_mqtt_bridge(event_bus)
            register_external_health_checks(
                health, homeassistant=presence_monitor, mqtt=bridge
            )
            tasks.append(
                _supervise("mqtt", lambda: _run_mqtt_forever(bridge))
            )
            log.info("Ponte MQTT habilitada (od-core)")
        if presence_monitor is not None:
            tasks.append(
                _supervise(
                    "presence", lambda: _run_presence_forever(presence_monitor)
                )
            )
            log.info("Presence Monitor habilitado (od-core)")
        if face_detector is not None:
            tasks.append(
                _supervise(
                    "vision", lambda: _run_vision_forever(event_bus, face_detector)
                )
            )
            log.info("Face Detector habilitado (od-core)")
        await asyncio.gather(*tasks)

    if mode == "api":
        asyncio.run(_run_api_forever(
            orchestrator, metrics, health,
            action_registry=action_registry, push=push,
        ))
    elif mode == "telegram":
        asyncio.run(_run_telegram_forever(
            orchestrator, action_registry=action_registry, database=database
        ))
    elif mode == "mqtt":
        bridge = build_mqtt_bridge(EventBus())
        register_external_health_checks(health, mqtt=bridge)
        asyncio.run(_run_mqtt_forever(bridge))
    elif mode == "recovery":
        loop = recovery or build_recovery(audit, health)
        if loop is None:
            print("recovery indisponível (OD_SELF_REPAIR_ENABLED=0)")
            return 2
        asyncio.run(_run_recovery_forever(loop))
    elif mode == "presence":
        monitor = presence_monitor or build_presence_monitor()
        if monitor is None:
            print("presence indisponível — credenciais HA ausentes")
            return 2
        register_external_health_checks(health, homeassistant=monitor)
        asyncio.run(_run_presence_forever(monitor))
    elif mode == "vision":
        detector = face_detector or build_face_detector()
        if detector is None:
            print("vision indisponível — OpenCV ou webcam ausente")
            return 2
        asyncio.run(_run_vision_forever(_build_event_bus(), detector))
    elif mode == "all":
        asyncio.run(_all())
    else:
        print(
            f"modo desconhecido: {mode!r} "
            "(api|telegram|mqtt|presence|vision|recovery|all|capabilities)"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
