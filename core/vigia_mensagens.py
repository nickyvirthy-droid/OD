"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/vigia_mensagens.py
Descrição: VIGIA DAS MENSAGENS — auditoria DIÁRIA das conversas do chat
           + REPARO AUTOMÁTICO de causas determinísticas, sempre pelo
           pipeline da casa (CoderEngine: sandbox → compile → backup →
           promoção) + gate completo + commit/push (regra 7.1) + restart
           verde (regra 7.3). Vereditos sem estratégia de conserto
           determinístico não são adivinhados: viram FILA com o motivo.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Pedido do dono (26/10): "existe algum tipo de vigia para as mensagens?
percebi que algumas perguntas não recebem respostas corretas. o sistema
tem como verificar isso pelo menos uma vez no dia e consertar?" — e,
quando perguntei a régua do conserto, ele respondeu: **"Reparo
automático completo"**, mandando eu partir dos achados da auditoria do
dia (15 ok / 10 resposta_errada / 5 inconsistente em 30 turnos).

O que o job faz (uma vez por dia, `od-vigia-mensagens.timer` 04:30):

  1. AUDITA — `core.chat_audit` sobre as últimas N horas (`--ultimas`,
     janela nova do auditor) com throttle (Groq devolve HTTP 429 em
     rajada; a reserva local assume, mas o veredito piora). Os
     vereditos `resposta_errada | devaneio | inconsistente | erro` vão
     para a FILA — o juiz ACHA, mas consertar alucinação de LLM sozinho
     não é determinístico, e é essa a régua registrada pelo dono.
  2. SONDAGEM — sondas DETERMINÍSTICAS (sem LLM no caminho) cobrem as
     causas que têm conserto conhecido. Cada sonda pergunta "o defeito
     está no código de hoje?" e responde True/False.
  3. REPARA — só sonda VERMELHA dispara reparo, e o reparo passa pelo
     CoderEngine (SANDBOX → compile → backup → promoção atômica); em
     seguida o GATE COMPLETO roda uma vez. Verde → commit + push +
     restart verde + aviso. Vermelho → ROLLBACK bit a bit
     (`git checkout --` só nos arquivos que EU alterei) + fila + alerta.
  4. REGISTRA — relatório JSON em `analise/` e resumo no Telegram
     (regra 15). Falha de qualquer etapa vira item de fila: nunca
     silêncio.

Garantias (régua da casa, não intenção):
  * reparo SÓ com árvore limpa nos arquivos-alvo (resíduo de sessão
    alheia nunca é sobrescrito);
  * estratégia com âncora ausente não escrebe nada — vira fila;
  * idempotente: código já consertado → sonda verde → nenhum trabalho;
  * sem LLM escrevendo código: o juiz só CLASSIFICA; quem escreve é a
    estratégia determinística (ancoras no texto do arquivo);
  * `--sem-reparo` audita e reporta sem tocar em nada (dry-run de
    política).

Legado do diagnóstico de 26/10 (iniciar/, §4): as duas causas que se
reproduziram no código daquele dia — e que as sondas cobrem — foram
(1) 'ligar TV'/'desligar o ar' fora do regex de comando (infinitivo) e
(2) `network_hosts` listando as bridges do Docker como se fossem
aparelhos da casa.

Uso:
    python -m core.vigia_mensagens                  # diário (últimas 24 h)
    python -m core.vigia_mensagens --sem-reparo     # audita e reporta
    python -m core.vigia_mensagens --horas 48 --sem-aviso
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error as _urllib_error
from urllib import request as _urllib_request

from core.logger import get_logger

log = get_logger("omega.core.vigia_mensagens")

RAIZ = Path(__file__).resolve().parents[1]

# Prefixos de interface que NÃO são aparelhos de gente na rede da casa
# (bridges do Docker/veth, virbr do libvirt, túneis tailscale/wg/tun).
PREFIXOS_VIRTUAIS = ("br-", "docker", "veth", "virbr", "tailscale",
                     "zt", "wg", "tun", "tap")

# Pausa entre juizadas: em 26/10 o Groq devolveu HTTP 429 (TPM 8000) em
# 4 de 30 turnos e a reserva local assumiu (design ok, veredito pior).
THROTTLE_JUIZ = 1.5

# Gate oficial do repositório (.coveragerc define os paths; >= 90%).
GATE_CMD = (sys.executable, "-m", "pytest", "--cov", "--cov-config=.coveragerc",
            "--cov-fail-under=90", "-q")


# ---------------------------------------------------------------------------
# Utilitários de ambiente / git / gate
# ---------------------------------------------------------------------------

def _ler_env() -> None:
    """Carrega o `.env` do repositório no ambiente (nunca sobrescreve).

    O job roda fora do od-core (systemd user), então OD_DB_URL /
    TELEGRAM_* precisam vir daqui — mesmas chaves do serviço principal.
    """
    env = RAIZ / ".env"
    if not env.exists():
        return
    try:
        linhas = env.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warn("Vigia: .env ilegível", error=str(exc))
        return
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip())


def _git(*args: str, timeout: float = 180.0) -> tuple[int, str]:
    """Um comando git no repositório. Devolve (rc, saída combinada)."""
    try:
        proc = subprocess.run(("git",) + args, cwd=str(RAIZ),
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _arquivos_limpos(arquivos: tuple[str, ...] | list[str]) -> bool:
    """True se os arquivos-alvo estão SEM resíduo de sessão alheia.

    Regra da casa: nunca sobrescrever trabalho de terceiros. Sujo → a
    sonda vira fila, não reparo.
    """
    rc, saida = _git("status", "--porcelain", "--", *arquivos)
    return rc == 0 and not saida


def _commitar(mensagem: str, arquivos: tuple[str, ...] | list[str]) -> bool:
    """Commit + push dos arquivos reparados (regra 7.1, pós-validação)."""
    rc, _ = _git("add", "--", *arquivos)
    if rc != 0:
        log.crit("Vigia: git add falhou", arquivos=list(arquivos))
        return False
    rc, saida = _git("commit", "-m", mensagem)
    if rc != 0:
        log.crit("Vigia: git commit falhou", erro=saida[-300:])
        return False
    rc, saida = _git("push", "origin", "master")
    if rc != 0:
        log.crit("Vigia: git push falhou", erro=saida[-300:])
        return False
    return True


def _rollback(arquivos: tuple[str, ...] | list[str]) -> bool:
    """Desfaz APENAS os arquivos que o vigia alterou (bit a bit)."""
    rc, saida = _git("checkout", "--", *arquivos)
    if rc != 0:
        log.crit("Vigia: rollback falhou", erro=saida[-300:])
        return False
    return True


def _rodar_gate(timeout: float = 1500.0) -> tuple[bool, str]:
    """Roda o gate oficial (pytest --cov >= 90). Devolve (verde, cauda)."""
    try:
        proc = subprocess.run(GATE_CMD, cwd=str(RAIZ), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    cauda = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-3:])
    return proc.returncode == 0, cauda


def _saude_od_core(timeout: float = 10.0) -> bool:
    """Health do od-core na porta 8000 (X-API-Key do OD_API_KEY)."""
    chave = os.environ.get("OD_API_KEY", "")
    req = _urllib_request.Request(
        "http://127.0.0.1:8000/health",
        headers={"X-API-Key": chave} if chave else {},
    )
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (_urllib_error.URLError, OSError, ValueError):
        return False


def _reiniciar_od_core(espera: float = 60.0) -> bool:
    """Restart verde (regra 7.3) + confirmação de health. Nunca às cegas."""
    try:
        proc = subprocess.run(("systemctl", "--user", "restart", "od-core"),
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.crit("Vigia: restart não rodou", error=str(exc))
        return False
    if proc.returncode != 0:
        log.crit("Vigia: restart recusado", erro=proc.stderr.strip()[-200:])
        return False
    limite = time.time() + espera
    while time.time() < limite:
        if _saude_od_core():
            return True
        time.sleep(3.0)
    return False


def _avisar(texto: str) -> bool:
    """Resumo no Telegram do dono (regra 15: sem silêncio)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("OD_TELEGRAM_ADMINS", "")
    if not token or not chat:
        log.warn("Vigia: sem Telegram configurado — resumo só no relatório")
        return False
    corpo = json.dumps({"chat_id": int(chat), "text": texto[:4000]}).encode()
    req = _urllib_request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=corpo, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with _urllib_request.urlopen(req, timeout=25.0) as resp:
            return resp.status == 200
    except (ValueError, _urllib_error.URLError, OSError) as exc:
        log.warn("Vigia: aviso Telegram falhou", error=str(exc)[:200])
        return False


# ---------------------------------------------------------------------------
# Sondas determinísticas (sem LLM): detectam E consertam
# ---------------------------------------------------------------------------

# Frases-expectativa da sonda de rota: cada uma precisa virar
# ha_device_control com `on` correto. Valem COM e SEM entidades do HA
# carregadas — o `on` sai do tuple (sem entidade) ou do strip de alvo
# (com entidade); nos dois casos 'desligar/apagar' caem no lado off.
FRASES_ROTA = (
    ("ligar TV", True),
    ("desligar o ar-condicionado", False),
    ("apagar a luz da cozinha", False),
    ("acender a luz do corredor", True),
)

# ARP sintético da sonda de rede: 1 vizinho da casa + 1 contêiner do
# Docker atrás de bridge. Serviu de prova viva em 26/10 (a rede tem
# 11 LAN + 9 bridges hoje).
ARP_SINTETICO = (
    "IP address       HW type     Flags       HW address            Mask     Device\n"
    "192.168.0.10     0x1         0x2         aa:bb:cc:dd:ee:01     *        wlx000f0037acf0\n"
    "172.19.0.4       0x1         0x2         02:42:ac:13:00:04     *        br-b7119289ffc4\n"
)


class Sonda:
    """Sonda determinística: pergunta 'o defeito está no código de hoje?'.

    Subclasses implementam `vermelha()` (detecção), `reparo()` (conteúdo
    novo por arquivo, ancorado no texto atual) e `confere_staged()`
    (a etapa de testes do CoderEngine sobre o artefato do sandbox).
    """

    nome = ""
    classe = ""
    arquivos: tuple[str, ...] = ()
    descricao = ""

    def vermelha(self, *args: Any, **kwargs: Any) -> bool:
        raise NotImplementedError

    def reparo(self, conteudo: Optional[str] = None) -> dict[str, Any]:
        raise NotImplementedError

    def confere_staged(self, texto: str) -> bool:
        raise NotImplementedError

    def runner(self) -> Callable[..., bool]:
        """Runner do CoderEngine: confere o artefato staged (kwargs)."""
        confere = self.confere_staged

        def _runner(*, relpath: str, staged_file: str, sandbox_dir: str,
                    original_file: str) -> bool:
            try:
                texto = Path(staged_file).read_text(encoding="utf-8")
            except (OSError, TypeError):
                return False
            return bool(confere(texto))

        _runner.__name__ = f"confere_{self.nome}"
        return _runner

    def resumo(self) -> str:
        return self.descricao


class SondaRotaAparelho(Sonda):
    """'ligar TV' / 'desligar o ar' precisam chegar em ha_device_control.

    Diagnóstico de 26/10: o infinitivo (ligar, desligar, apagar,
    acender, conectar) estava FORA do regex `_comando` — só as formas
    'liga/ligue/desliga/…' casavam. Resultado real: 'ligar TV' caiu no
    LLM e a rota de compromissos respondeu; 'desligar o ar-condicionado'
    e 'apagar a luz da cozinha' idem (10 turnos 'resposta_errada' na
    auditoria do dia).
    """

    nome = "rota_aparelho_infinitivo"
    classe = "rota_errada"
    arquivos = ("core/intents.py",)
    descricao = ("infinitivo fora do regex de comando: 'ligar TV' e "
                 "'desligar o ar' não chegam em ha_device_control")

    def _detect(self) -> Callable[..., Any]:
        from core.intents import detect_action_intent
        return detect_action_intent

    def vermelha(self, detect: Optional[Callable[..., Any]] = None) -> bool:
        """True se ALGUMA frase-expectativa não roteia como deveria."""
        fn = detect or self._detect()
        for frase, on in FRASES_ROTA:
            try:
                achado = fn(frase)
            except Exception as exc:  # detector quebrado = sonda vermelha
                log.warn("Vigia: probe de rota explodiu",
                         frase=frase, error=str(exc)[:160])
                return True
            ok = (isinstance(achado, tuple) and achado
                  and achado[0] == "ha_device_control"
                  and bool(achado[1].get("on")) is on)
            if not ok:
                return True
        return False

    def reparo(self, conteudo: Optional[str] = None) -> dict[str, Any]:
        """Troca os 3 pontos de âncora por listas com infinitivo."""
        texto = conteudo
        if texto is None:
            if not self.vermelha():
                return {"status": "sem_defeito"}
            texto = (RAIZ / "core/intents.py").read_text(encoding="utf-8")
        faltando: list[str] = []
        novo = texto
        for rotulo, antigo, novo_bloco in _TROCAS_INTENTS:
            if antigo in novo:
                novo = novo.replace(antigo, novo_bloco, 1)
            else:
                faltando.append(rotulo)
        if faltando:
            return {"status": "ancora_ausente", "faltando": faltando}
        if novo == texto:
            return {"status": "sem_defeito"}
        return {"status": "aplicado",
                "arquivos": {"core/intents.py": novo}}

    def confere_staged(self, texto: str) -> bool:
        return ("ligar|" in texto and "desligar|" in texto
                and '"apagar"' in texto and '"desconectar"' in texto)


class SondaRedeSemBridge(Sonda):
    """`network_hosts` não pode contar bridges do Docker como gente.

    Diagnóstico de 26/10: 'quantas pessoas estão conectadas' devolveu 20
    vizinhos, sendo 9 atrás de `br-b7119289ffc4` (contêineres). A casa
    tem 11 aparelhos de gente; o resto é infraestrutura.
    """

    nome = "rede_sem_bridge"
    classe = "network_hosts_bridge"
    arquivos = ("tools/actions/actions.py",)
    descricao = ("network_hosts lista bridges virtuais (docker/veth) como "
                 "dispositivos da casa")

    def _hosts(self, arp: Optional[str] = None) -> list[dict[str, Any]]:
        if arp is None:
            from tools.actions.actions import network_hosts
            try:
                return list(network_hosts().get("hosts") or [])
            except Exception as exc:
                log.warn("Vigia: network_hosts explodiu", error=str(exc)[:160])
                return []
        return _hosts_com_arp(arp)

    def vermelha(self, arp: Optional[str] = None) -> bool:
        """True se a resposta ainda traz interface virtual (bridge)."""
        return any(
            str(h.get("interface") or "").startswith(PREFIXOS_VIRTUAIS)
            for h in self._hosts(arp)
        )

    def reparo(self, conteudo: Optional[str] = None) -> dict[str, Any]:
        """Insere a constante de ifaces virtuais + o `continue` do filtro."""
        texto = conteudo
        if texto is None:
            if not self.vermelha():
                return {"status": "sem_defeito"}
            texto = (RAIZ / "tools/actions/actions.py").read_text(
                encoding="utf-8")
        faltando: list[str] = []
        novo = texto
        for rotulo, antigo, novo_bloco in _TROCAS_REDE:
            if antigo in novo:
                novo = novo.replace(antigo, novo_bloco, 1)
            else:
                faltando.append(rotulo)
        if faltando:
            return {"status": "ancora_ausente", "faltando": faltando}
        if novo == texto:
            return {"status": "sem_defeito"}
        return {"status": "aplicado",
                "arquivos": {"tools/actions/actions.py": novo}}

    def confere_staged(self, texto: str) -> bool:
        return ("_IFACES_VIRTUAIS" in texto
                and "iface.startswith(_IFACES_VIRTUAIS)" in texto)


# Âncoras exatas do código de 26/10 (verificadas: 1 ocorrência cada).
# Se alguém refatorar os blocos, a âncora some → status "ancora_ausente"
# → FILA (nunca escrita às cegas) e a guarda de teste aponta a mudança.
_TROCAS_INTENTS = (
    ("A1 · regex _comando (detecção)",
     '    _comando = re.search(\n'
     '        r"\\b(liga|ligue|acende|acenda|acende|desliga|desligue|apaga|apague|"\n'
     '        r"toggle|desconecta|desconecte|desplug|conecta|conecte|plug)\\b",\n'
     "        low,\n"
     "    )",
     '    _comando = re.search(\n'
     "        # 26/10 (Vigia das Mensagens): o INFINITIVO entra — 'ligar TV',\n"
     "        # 'desligar o ar' e 'apagar a luz' caíam no LLM (a rota de\n"
     "        # compromissos chegou a responder por eles). Os verbos que\n"
     "        # DESLIGAM também estão no tuple do `on` logo abaixo.\n"
     '        r"\\b(ligar|ligue|liga|acender|acenda|acende|desligar|desligue|"\n'
     '        r"desliga|apagar|apague|apaga|toggle|desconectar|desconecte|"\n'
     '        r"desconecta|desplugar|desplug|conectar|conecte|conecta|"\n'
     '        r"plugar|plug)\\b",\n'
     "        low,\n"
     "    )"),
    ("A2 · cálculo do `on` (_detect_operational)",
     '            _comando.group(1) not in ("desliga", "desligue", "apaga", "apague",\n'
     '                                      "desconecta", "desconecte", "desplug")',
     '            _comando.group(1) not in ("desligar", "desliga", "desligue",\n'
     '                                      "apagar", "apaga", "apague",\n'
     '                                      "desconectar", "desconecta",\n'
     '                                      "desconecte", "desplugar", "desplug")'),
    ("A3 · strip de verbo (resolve_light_target)",
     '        r"\\b(liga|ligue|acende|desliga|desligue|apaga|apague|toggle|a|o|as|os|"',
     '        r"\\b(ligar|ligue|liga|acender|acende|desligar|desligue|desliga|"\n'
     '        r"apagar|apague|apaga|toggle|a|o|as|os|"'),
)

_TROCAS_REDE = (
    ("B1 · constante de ifaces virtuais",
     "def network_hosts() -> dict[str, Any]:",
     "# 26/10 (Vigia das Mensagens): bridges virtuais (docker, veth,\n"
     "# tailscale…) não são aparelhos de ninguém na rede da casa —\n"
     '# "quantas pessoas estão conectadas" listava 9 contêineres do\n'
     "# Docker atrás de br-b7119289ffc4.\n"
     '_IFACES_VIRTUAIS = ("br-", "docker", "veth", "virbr", "tailscale",\n'
     '                    "zt", "wg", "tun", "tap")\n'
     "\n"
     "\n"
     "def network_hosts() -> dict[str, Any]:"),
    ("B2 · continue das bridges",
     '        if mac == "00:00:00:00:00:00":\n'
     "            continue  # entrada sem vizinho resolvido",
     '        if mac == "00:00:00:00:00:00":\n'
     "            continue  # entrada sem vizinho resolvido\n"
     "        if iface.startswith(_IFACES_VIRTUAIS):\n"
     "            continue  # bridge/container: não é dispositivo da casa"),
)

SONDAS: tuple[Sonda, ...] = (SondaRotaAparelho(), SondaRedeSemBridge())


def _hosts_com_arp(arp: str) -> list[dict[str, Any]]:
    """`network_hosts()` lendo um ARP sintético (injeção temporária).

    A sonda precisa ser determinística em qualquer máquina (CI sem
    Docker, caixa sem vizinhos): o `_read_proc` é trocado só durante a
    chamada e devolvido no `finally`.
    """
    from tools.actions import actions as ac
    original = ac._read_proc
    ac._read_proc = lambda _nome: arp  # type: ignore[assignment]
    try:
        return list(ac.network_hosts().get("hosts") or [])
    finally:
        ac._read_proc = original


# ---------------------------------------------------------------------------
# Auditoria da janela (o juiz acha; sem estratégia = fila)
# ---------------------------------------------------------------------------

def _auditar_janela(horas: float) -> dict[str, Any]:
    """Audita as últimas `horas` horas. Nunca derruba o job (defesa)."""
    from core import chat_audit as ca
    desde = time.time() - float(horas) * 3600.0
    relatorio: dict[str, Any] = {
        "fonte": "vazia", "turnos": 0, "janela_horas": horas,
        "contagens": {}, "problematicos": 0, "caminho": "", "erro": "",
    }
    try:
        turnos, fonte = ca.carregar_turnos_cascata(
            dsn=os.environ.get("OD_DB_URL", ""),
            sqlite_path=RAIZ / "data" / "od.db",
            json_dir=RAIZ / "data" / "conversations",
            desde=desde,
        )
    except Exception as exc:  # banco fora = auditoria relatada, não crise
        relatorio["erro"] = f"cascata de fontes falhou: {exc}"[:300]
        return relatorio
    relatorio["fonte"] = fonte
    relatorio["turnos"] = len(turnos)
    if not turnos:
        return relatorio
    try:
        juiz = ca.montar_juiz("auto", os.environ.get)
        resultados = ca.auditar(turnos, juiz, throttle=THROTTLE_JUIZ)
    except Exception as exc:
        relatorio["erro"] = f"juiz indisponível: {exc}"[:300]
        return relatorio
    completo = ca.gerar_relatorio(resultados, fonte=fonte)
    caminho = ca.salvar_relatorio(completo, RAIZ / "analise")
    relatorio.update(completo)
    relatorio["caminho"] = str(caminho)
    return relatorio


def _fila_do_auditor(auditoria: dict[str, Any]) -> list[dict[str, Any]]:
    """Vereditos ≠ ok viram fila: o juiz acha, o conserto é humano.

    A régua do dono (26/10) é explícita: reparo automático para causas
    DETERMINÍSTICAS (as sondas acima); alucinação/contradição de juiz
    não tem conserto determinístico honesto — e adivinhar custaria uma
    resposta errada nova no lugar da errada antiga.
    """
    fila: list[dict[str, Any]] = []
    for r in auditoria.get("resultados", []):
        if r.get("veredito") == "ok":
            continue
        fila.append({
            "origem": "auditoria",
            "veredito": r.get("veredito", "?"),
            "juiz": r.get("juiz", "?"),
            "quando": r.get("quando", ""),
            "pergunta": (r.get("pergunta") or "")[:140],
            "motivo": "sem estratégia de reparo determinístico",
        })
    return fila


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

async def _aplicar(sonda: Sonda, arquivos: dict[str, str]) -> list[str]:
    """Aplica o conteúdo novo via CoderEngine (sandbox → promoção).

    Devolve os arquivos efetivamente promovidos (vazio = nada aplicado).
    """
    from core.coder import CoderEngine
    engine = CoderEngine(root=RAIZ)
    runner = sonda.runner()
    aplicados: list[str] = []
    for rel, conteudo in arquivos.items():
        try:
            resultado = await engine.apply_change(
                rel,
                content=conteudo,
                runner=runner,
                message=f"vigia-mensagens[{sonda.nome}]: {sonda.resumo()[:80]}",
                role="admin",
                session_id="od-vigia-mensagens",
            )
        except Exception as exc:
            log.crit("Vigia: CoderEngine explodiu", sonda=sonda.nome,
                     arquivo=rel, error=str(exc)[:200])
            return []
        if not resultado.ok:
            log.crit("Vigia: mudança recusada", sonda=sonda.nome,
                     arquivo=rel, status=resultado.status,
                     erros=[e[:160] for e in resultado.errors[:3]])
            return []
        aplicados.append(rel)
        log.info("Vigia: mudança promovida", sonda=sonda.nome, arquivo=rel,
                 resumo=resultado.summary[:120])
    return aplicados


async def rodar(*, horas: float = 24.0, reparar: bool = True,
                aviso: bool = True, gate: bool = True,
                dry_run: bool = False) -> dict[str, Any]:
    """Um ciclo completo do vigia. Sempre devolve relatório (nunca silêncio).

    `dry_run` = sem git, sem gate, sem Telegram: só sondagem + relatório
    (é o modo de inspeção e também o modo dos testes).
    """
    inicio = time.time()
    relatorio: dict[str, Any] = {
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "janela_horas": horas,
        "modo": ("seco" if dry_run
                 else ("auditoria" if not reparar else "reparo")),
        "auditoria": {},
        "sondas": [],
        "fila": [],
        "aplicados": [],
        "gate": {"executado": False, "verde": False, "saida": ""},
        "commit": {"feito": False},
        "reinicio": {"feito": False},
        "avisado": False,
        "duracao_s": 0.0,
    }

    # 1) Auditoria da janela (o juiz acha; sem estratégia = fila).
    auditoria = await asyncio.to_thread(_auditar_janela, horas)
    resumo_aud = {k: auditoria.get(k) for k in
                  ("fonte", "turnos", "problematicos", "janela_horas", "erro")}
    resumo_aud["contagens"] = auditoria.get("contagens", {})
    relatorio["auditoria"] = resumo_aud
    relatorio["fila"] = _fila_do_auditor(auditoria)

    # 2) Sondagem determinística (independente do juiz: cobre regressão
    #    mesmo sem nenhuma conversa do dia ter batido no defeito).
    vermelhas: list[Sonda] = []
    for sonda in SONDAS:
        try:
            vermelha = sonda.vermelha()
        except Exception as exc:
            log.crit("Vigia: sonda inesperadamente quebrada",
                     sonda=sonda.nome, error=str(exc)[:200])
            relatorio["fila"].append({
                "origem": "sonda", "sonda": sonda.nome,
                "motivo": f"sonda quebrou: {exc}"[:200],
            })
            continue
        relatorio["sondas"].append({
            "nome": sonda.nome, "estado": "vermelha" if vermelha else "verde",
            "descricao": sonda.resumo(),
        })
        if vermelha:
            vermelhas.append(sonda)

    # 3) Reparo (só se autorizado; só sonda vermelha; só árvore limpa).
    if vermelhas and reparar and not dry_run:
        arquivos_alvo: list[str] = []
        for sonda in vermelhas:
            if not _arquivos_limpos(sonda.arquivos):
                relatorio["fila"].append({
                    "origem": "reparo", "sonda": sonda.nome,
                    "motivo": "arquivo sujo (resíduo de sessão alheia) — "
                              "não sobrescrevo",
                })
                continue
            rep = sonda.reparo()
            if rep["status"] == "ancora_ausente":
                relatorio["fila"].append({
                    "origem": "reparo", "sonda": sonda.nome,
                    "motivo": "âncora ausente — refatorou sem o vigia saber",
                    "faltando": rep.get("faltando", []),
                })
                continue
            if rep["status"] == "sem_defeito":
                continue
            aplicados = await _aplicar(sonda, rep["arquivos"])
            if not aplicados:
                relatorio["fila"].append({
                    "origem": "reparo", "sonda": sonda.nome,
                    "motivo": "CoderEngine recusou (sandbox/teste/promoção)",
                })
                continue
            arquivos_alvo.extend(aplicados)
            relatorio["aplicados"].append({
                "sonda": sonda.nome, "arquivos": aplicados,
            })
        arquivos_alvo = sorted(set(arquivos_alvo))

        # 4) Prova + gate + commit/rollback.
        if arquivos_alvo:
            provas = []
            for sonda in vermelhas:
                try:
                    verde = not sonda.vermelha()
                except Exception:
                    verde = False
                provas.append({"sonda": sonda.nome,
                               "depois": "verde" if verde else "vermelha"})
                if not verde:
                    relatorio["fila"].append({
                        "origem": "reparo", "sonda": sonda.nome,
                        "motivo": "aplicado mas a sonda continua vermelha",
                    })
            relatorio["provas"] = provas

            if gate:
                verde_gate, cauda = await asyncio.to_thread(_rodar_gate)
                relatorio["gate"] = {"executado": True, "verde": verde_gate,
                                     "saida": cauda}
            else:
                verde_gate = True

            if verde_gate:
                mensagem = ("vigia-mensagens: conserto automático — "
                            + ", ".join(a["sonda"] for a in
                                        relatorio["aplicados"]))
                relatorio["commit"]["feito"] = await asyncio.to_thread(
                    _commitar, mensagem, arquivos_alvo)
                relatorio["commit"]["arquivos"] = arquivos_alvo
                if relatorio["commit"]["feito"] and os.environ.get(
                        "OD_VIGIA_RESTART", "1") != "0":
                    ok_restart = await asyncio.to_thread(_reiniciar_od_core)
                    relatorio["reinicio"] = {"feito": ok_restart}
                    if not ok_restart:
                        relatorio["fila"].append({
                            "origem": "reinicio",
                            "motivo": "od-core não voltou saudável após o "
                                      "restart — conferir manualmente",
                        })
            else:
                if await asyncio.to_thread(_rollback, arquivos_alvo):
                    relatorio["aplicados"] = []
                    relatorio["rollback"] = True
                relatorio["fila"].append({
                    "origem": "gate",
                    "motivo": "gate vermelho — rollback executado "
                              "(arquivos devolvidos bit a bit)",
                })
    elif vermelhas and not reparar:
        for sonda in vermelhas:
            relatorio["fila"].append({
                "origem": "sonda", "sonda": sonda.nome,
                "motivo": "vermelha, mas --sem-reparo (só auditoria)",
            })

    # 5) Relatório + aviso (regra 15: sem silêncio; só quando há notícia).
    relatorio["duracao_s"] = round(time.time() - inicio, 1)
    caminho = RAIZ / "analise" / (
        f"relatorio_vigia_mensagens_{time.strftime('%Y%m%d-%H%M%S')}.json")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(relatorio, ensure_ascii=False,
                                      indent=2), encoding="utf-8")
        relatorio["relatorio"] = str(caminho)
    except OSError as exc:
        log.warn("Vigia: relatório não gravou", error=str(exc)[:160])

    noticia = (relatorio["aplicados"] or relatorio["fila"]
               or relatorio["auditoria"].get("problematicos"))
    if aviso and not dry_run and noticia:
        relatorio["avisado"] = await asyncio.to_thread(
            _avisar, _resumo_telegram(relatorio))

    log.info("Vigia: ciclo concluído",
             modo=relatorio["modo"],
             turnos=relatorio["auditoria"].get("turnos", 0),
             sondas_vermelhas=len(vermelhas),
             aplicados=len(relatorio["aplicados"]),
             fila=len(relatorio["fila"]),
             verde=relatorio["gate"].get("verde", False),
             duracao_s=relatorio["duracao_s"])
    return relatorio


def _resumo_telegram(relatorio: dict[str, Any]) -> str:
    """Resumo curto para o Telegram (o JSON completo fica em analise/)."""
    aud = relatorio.get("auditoria", {})
    linhas = ["🔭 Vigia das Mensagens — ciclo diário",
              f"Janela: {aud.get('janela_horas', '?')} h · turnos: "
              f"{aud.get('turnos', 0)} · fonte: {aud.get('fonte', '?')}"]
    contagens = aud.get("contagens") or {}
    if contagens:
        limpo = " · ".join(f"{k}: {v}" for k, v in sorted(contagens.items()))
        linhas.append(f"Juiz: {limpo}")
    if aud.get("erro"):
        linhas.append(f"⚠️ Auditoria: {aud['erro'][:160]}")
    for item in relatorio.get("aplicados", []):
        linhas.append(f"🛠️ Consertado sozinho: {item['sonda']} "
                      f"({', '.join(item['arquivos'])})")
    if relatorio.get("rollback"):
        linhas.append("↩️ Gate vermelho: rollback executado (nada mudou).")
    elif relatorio.get("gate", {}).get("executado"):
        linhas.append("✅ Gate: "
                      + ("verde" if relatorio["gate"]["verde"] else "vermelho"))
    if relatorio.get("commit", {}).get("feito"):
        linhas.append("📦 Commit + push feitos"
                      + (" · od-core reiniciado 🟢"
                         if relatorio.get("reinicio", {}).get("feito")
                         else " · sem restart"))
    fila = relatorio.get("fila", [])
    if fila:
        linhas.append(f"📋 Fila de conserto ({len(fila)}):")
        for item in fila[:8]:
            rotulo = item.get("sonda") or item.get("veredito") or "item"
            linhas.append(f"  • {rotulo}: {str(item.get('motivo', ''))[:90]}")
        if len(fila) > 8:
            linhas.append(f"  … e mais {len(fila) - 8} (ver relatório)")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vigia_mensagens",
        description="Auditoria diária do chat + reparo automático "
                    "(somente causas determinísticas).")
    parser.add_argument("--horas", type=float, default=24.0,
                        help="janela da auditoria em horas (padrão: 24)")
    parser.add_argument("--sem-reparo", action="store_true",
                        help="audita e reporta sem tocar em código")
    parser.add_argument("--sem-aviso", action="store_true",
                        help="não envia o resumo para o Telegram")
    parser.add_argument("--sem-gate", action="store_true",
                        help="repara sem rodar o gate (uso de teste)")
    parser.add_argument("--seco", action="store_true",
                        help="dry-run total: sem git, gate nem Telegram")
    args = parser.parse_args(argv)

    _ler_env()
    relatorio = asyncio.run(rodar(
        horas=args.horas,
        reparar=not args.sem_reparo,
        aviso=not args.sem_aviso,
        gate=not args.sem_gate,
        dry_run=args.seco,
    ))
    aud = relatorio.get("auditoria", {})
    print(f"modo={relatorio['modo']} · turnos={aud.get('turnos', 0)} · "
          f"problemáticos={aud.get('problematicos', 0)} · "
          f"sondas={[s['estado'] for s in relatorio['sondas']]} · "
          f"aplicados={len(relatorio['aplicados'])} · "
          f"fila={len(relatorio['fila'])} · "
          f"gate={'verde' if relatorio['gate'].get('verde') else 'não/vermelho'}")
    if relatorio.get("relatorio"):
        print(f"relatório: {relatorio['relatorio']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
