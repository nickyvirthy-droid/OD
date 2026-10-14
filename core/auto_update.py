"""OMEGA DRAKON • CORE
Módulo: core/auto_update.py — Parte E do Project NOMAD

Auto-update de modelos/conteúdo em camadas: janela, cool-off, só
minor/patch, cap de bytes, auto-disable e pre-flight — aplicado ao que o
assistente baixa/produz (modelo LLM, vozes STT/TTS, índice RAG).

Segundo o padrão de ouro do Nômade (docs/ANALISE_PROJECT_NOMAD.md §2.1.1):
o `avaliar()` é um pipeline de decisão PURO — relógio, estado, espaço em
disco e a lista de alvos entram por parâmetro; o MESMO caminho roda em
produção e no dry-run do CI, sem rede, sem disco, sem I/O. O executor
(AutoUpdateService) é a parte suja: ele lê o manifesto, enfileira
downloads na fila da Parte D (que já entrega retomada por Range, sha256
e dedup de graça) e persiste o estado em JSON atômico.

Camadas do avaliar() — nesta ordem, cada uma com motivo registrado:
  1. auto-disable   alvo desligado por N falhas duras (skip não conta)
  2. inativa        marcada como inativa no manifesto (dono disse não)
  3. sem mudança    versão nova vaza ou igual à instalada
  4. major          só minor/patch atualizam sozinhos (major é com o dono)
  5. janela         só dentro da janela (default 02:00–06:00)
  6. cool-off       ancorado em "primeiro visto" (a nova versão tem que
                    ficar X horas vista antes de aplicar — evita loop de
                    update atrás de release queimada; conteúdo local = 0)
  7. backoff        falha anterior ainda em espera (falha × intervalo)
  8. cap + preflight orçamento de bytes por ciclo, espaço em disco,
                    sha256 com 64 hex e URL http(s)

Nada de dependência nova: stdlib pura.

Baseado em:
  - docs/ANALISE_PROJECT_NOMAD.md (Parte E + §2.1 padrões do Nômade)
  - core/downloads.py (Parte D — o motor de download)
  - integrations/notifier.py (padrão de cool-off/estado persistido)
Arquiteto: Omega Drakon
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import queue as queue_mod
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from core.logger import get_logger
from core.downloads import CONCLUIDO, ERRO

log = get_logger("omega.core.auto_update")

# --- Constantes (defaults; tudo sobrescrevível por env/manifesto) ----------

JANELA_PADRAO = "02:00-06:00"      # janela noturna do Nômade
COOLOFF_PADRAO_S = 6 * 3600.0      # 6 h entre "primeiro visto" e aplicar
CAP_PADRAO_BYTES = 2 * 1024 ** 3   # 2 GiB por ciclo (guardrail de disco)
MAX_FALHAS_PADRAO = 3              # falhas duras seguidas → auto-disable
INTERVALO_PADRAO_S = 1800.0        # tick a cada 30 min
MARGEM_DISCO = 1.10                # 10% de folga no preflight de espaço
MENSAGEM_MAX = 200                 # limite do motivo gravado/retornado

ESTADO_PADRAO = Path("data/auto_update_estado.json")
ALVOS_MANIFESTO_PADRAO = Path("data/auto_update_alvos.json")

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# --- Ações e ações de pós-download ----------------------------------------

ACAO_NADA = "nada"          # alvo declarado sem ação (só estado)
ACAO_BAIXAR = "baixar"      # baixa url → destino (fila da Parte D)
ACAO_RAG_SYNC = "rag_sync"  # re-sincroniza o índice RAG (conteúdo local)

POS_NADA = "nada"      # arquivo fica staged em data/downloads (verificado)
POS_MOVER = "mover"    # os.replace atômico para mover_para (árvore do repo)

# Ações de decisão
APLICAR = "aplicar"
AGUARDAR = "aguardar"
PULAR = "pular"


def _curto(texto: str) -> str:
    """Recorta mensagem para caber em log/estado sem virar ensaio."""
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= MENSAGEM_MAX else texto[: MENSAGEM_MAX - 1] + "…"


def _parse_semver(valor: str) -> Optional[tuple[int, int, int]]:
    """X.Y.Z canônico ou None (hash/rotulo não é semver)."""
    m = _SEMVER.match(valor.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


# --- Modelo de dados -------------------------------------------------------


@dataclass
class AlvoUpdate:
    """Um candidato a atualização (conteúdo local ou arquivo remoto).

    O `versao_nova` é a única chave do fluxo:
      - vazio            → nada pendente (estado só);
      - != instalada     → atualização disponível (pelo pipeline todo).
    Para alvos locais (índice RAG) o provedor calcula `versao_nova` a
    partir do conteúdo em disco; para arquivos, o DONO edita o manifesto
    (lockfile declarativo: url + sha256 + versão de destino).
    """

    id: str
    nome: str
    categoria: str = "conteudo"        # conteudo | modelo | voz
    acao: str = ACAO_NADA              # nada | baixar | rag_sync
    url: str = ""
    sha256: str = ""                   # hash esperado (64 hex) do download
    destino: str = ""                  # relativo à raiz de downloads
    pos_download: str = POS_NADA       # nada | mover
    mover_para: str = ""               # relativo à RAIZ DO REPO (só mover)
    versao_atual: str = ""             # o que está declarado instalado
    versao_nova: str = ""              # "" = nada pendente
    bytes_estimados: int = -1          # -1 = desconhecido (não trava cap)
    ativa: bool = True
    cooloff_s: Optional[float] = None  # override (conteúdo local = 0.0)

    def para_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "nome": self.nome, "categoria": self.categoria,
            "acao": self.acao, "url": self.url, "destino": self.destino,
            "pos_download": self.pos_download, "mover_para": self.mover_para,
            "versao_atual": self.versao_atual, "versao_nova": self.versao_nova,
            "bytes_estimados": self.bytes_estimados, "ativa": self.ativa,
        }


@dataclass
class EstadoAlvo:
    """Estado persistido por alvo (data/auto_update_estado.json)."""

    id: str
    versao_instalada: str = ""
    primeiro_visto: Optional[float] = None   # âncora do cool-off
    vista_versao: str = ""                   # a qual versão o âncora refere
    falhas: int = 0                          # falhas DURAS consecutivas
    desabilitado: bool = False               # auto-disable (3 falhas)
    motivo_desabilitado: str = ""
    ultima_tentativa: Optional[float] = None
    ultimo_erro: str = ""
    ultima_sucesso: Optional[float] = None

    def para_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "versao_instalada": self.versao_instalada,
            "primeiro_visto": self.primeiro_visto,
            "vista_versao": self.vista_versao, "falhas": self.falhas,
            "desabilitado": self.desabilitado,
            "motivo_desabilitado": self.motivo_desabilitado,
            "ultima_tentativa": self.ultima_tentativa,
            "ultimo_erro": self.ultimo_erro,
            "ultima_sucesso": self.ultima_sucesso,
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "EstadoAlvo":
        est = cls(id=str(dados.get("id", "")))
        for f in ("versao_instalada", "vista_versao", "motivo_desabilitado",
                  "ultimo_erro"):
            setattr(est, f, str(dados.get(f, "") or ""))
        for f in ("primeiro_visto", "ultima_tentativa", "ultima_sucesso"):
            valor = dados.get(f)
            setattr(est, f, float(valor) if valor is not None else None)
        est.falhas = int(dados.get("falhas", 0) or 0)
        est.desabilitado = bool(dados.get("desabilitado", False))
        return est


@dataclass
class ConfigUpdate:
    """Configuração do serviço (env OD_UPDATE_*)."""

    habilitado: bool = True
    janela: str = JANELA_PADRAO
    cooloff_s: float = COOLOFF_PADRAO_S
    cap_bytes: int = CAP_PADRAO_BYTES
    max_falhas: int = MAX_FALHAS_PADRAO
    intervalo_s: float = INTERVALO_PADRAO_S

    @classmethod
    def de_env(cls, env: Callable[[str, str], str]) -> "ConfigUpdate":
        """Lê o .env no padrão do launcher (`env(nome, default)`)."""
        janela = env("OD_UPDATE_JANELA", JANELA_PADRAO).strip()
        if not _JANELA_VALIDA.match(janela):  # type: ignore[misc]
            log.warn("Janela de auto-update inválida — usando default",
                     valor=janela, default=JANELA_PADRAO)
            janela = JANELA_PADRAO
        return cls(
            habilitado=env("OD_UPDATE_ENABLED", "1") != "0",
            janela=janela,
            cooloff_s=float(env("OD_UPDATE_COOLOFF_H", "6")) * 3600.0,
            cap_bytes=int(env("OD_UPDATE_CAP_MB", "2048")) * 1024 ** 2,
            max_falhas=int(env("OD_UPDATE_MAX_FALHAS", "3")),
            intervalo_s=float(env("OD_UPDATE_INTERVALO_MIN", "30")) * 60.0,
        )

    def para_dict(self) -> dict[str, Any]:
        ini, fim = _janela_limites(self.janela)
        return {
            "habilitado": self.habilitado, "janela": self.janela,
            "cooloff_h": round(self.cooloff_s / 3600.0, 2),
            "cap_mb": self.cap_bytes // 1024 ** 2,
            "max_falhas": self.max_falhas,
            "intervalo_min": round(self.intervalo_s / 60.0, 1),
            "janela_ini": ini, "janela_fim": fim,
        }


@dataclass
class DecisaoUpdate:
    """Resultado da avaliação de UM alvo — sempre com motivo."""

    alvo: str
    acao: str              # aplicar | aguardar | pular
    motivo: str
    bytes: int = 0         # bytes que SERIAM gastos (contabilidade do cap)

    def para_dict(self) -> dict[str, Any]:
        return {"alvo": self.alvo, "acao": self.acao,
                "motivo": self.motivo, "bytes": self.bytes}


# --- Janela ----------------------------------------------------------------

_JANELA_VALIDA = re.compile(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$")


def _hhmm(texto: str) -> int:
    """'HH:MM' → minutos desde 00:00 (validado no ConfigUpdate)."""
    hora, minuto = texto.split(":")
    return int(hora) * 60 + int(minuto)


def _janela_limites(janela: str) -> tuple[int, int]:
    """Minutos (ini, fim) de uma janela 'HH:MM-HH:MM'."""
    ini_s, fim_s = janela.split("-")
    return _hhmm(ini_s), _hhmm(fim_s)


def na_janela(janela: str, agora: float) -> bool:
    """Está dentro da janela? Suporta janela que atravessa a meia-noite."""
    ini, fim = _janela_limites(janela)
    minuto = time.localtime(agora).tm_hour * 60 + time.localtime(agora).tm_min
    if ini <= fim:
        return ini <= minuto < fim
    return minuto >= ini or minuto < fim


def proxima_janela(janela: str, agora: float) -> float:
    """Timestamp da próxima abertura de janela (para o motivo/agendamento)."""
    ini, _ = _janela_limites(janela)
    lt = time.localtime(agora)
    hoje_ini = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            ini // 60, ini % 60, 0, 0, 0, -1))
    if hoje_ini > agora:
        return hoje_ini
    return hoje_ini + 86400.0


# --- Pipeline de decisão PURO ----------------------------------------------


def avaliar(
    alvos: list[AlvoUpdate],
    estado: dict[str, EstadoAlvo],
    cfg: ConfigUpdate,
    *,
    agora: float,
    espaco_livre: int,
) -> list[DecisaoUpdate]:
    """Avalia todos os alvos contra as 8 camadas — PURO, sem I/O.

    `estado` é lido como dict id→EstadoAlvo; o cool-off pode ANCORAR o
    `primeiro_visto` (mutação do dict recebido é intencional e documentada:
    quem chama decide se persiste — o dry-run passa uma cópia).
    O cap de bytes é contábil: cada `aplicar` de download desconta do
    orçamento dos próximos alvos do MESMO ciclo.
    """
    decisoes: list[DecisaoUpdate] = []
    gasto = 0
    for alvo in alvos:
        est = estado.get(alvo.id)
        if est is None:
            est = EstadoAlvo(id=alvo.id)
            estado[alvo.id] = est
        decisoes.append(
            _avaliar_um(alvo, est, cfg, agora=agora,
                        espaco_livre=espaco_livre, gasto=gasto)
        )
        if decisoes[-1].acao == APLICAR:
            gasto += max(decisoes[-1].bytes, 0)
    return decisoes


def _avaliar_um(
    alvo: AlvoUpdate,
    est: EstadoAlvo,
    cfg: ConfigUpdate,
    *,
    agora: float,
    espaco_livre: int,
    gasto: int,
) -> DecisaoUpdate:
    """As 8 camadas para UM alvo, na ordem. Puro (exceto âncora do cool-off)."""
    d = DecisaoUpdate(alvo=alvo.id, acao=PULAR, motivo="", bytes=0)

    # 1. auto-disable — o dono só liga de novo pelo painel (reset).
    if est.desabilitado:
        d.motivo = f"desabilitado: {_curto(est.motivo_desabilitado)}"
        return d

    # 2. inativa no manifesto — decisão do dono, respeitada sem reclamar.
    if not alvo.ativa:
        d.motivo = "inativa_no_manifesto"
        return d

    # 3. sem mudança — nada novo, ou versão nova vazia (só registro).
    if not alvo.versao_nova or alvo.versao_nova == est.versao_instalada:
        d.motivo = "sem_atualizacao"
        return d

    # 4. só minor/patch — major é decisão do dono (nunca automática).
    #    Versões não-semver (hash de conteúdo) não têm "major": passam.
    semver_nova = _parse_semver(alvo.versao_nova)
    semver_atual = _parse_semver(est.versao_instalada or alvo.versao_atual)
    if semver_nova and semver_atual and semver_nova[0] > semver_atual[0]:
        d.motivo = (f"major_requer_dono: {alvo.versao_atual or est.versao_instalada}"
                    f" → {alvo.versao_nova}")
        return d

    # 5. janela — atualização pesada só de madrugada.
    if not na_janela(cfg.janela, agora):
        prox = proxima_janela(cfg.janela, agora)
        d.acao = AGUARDAR
        d.motivo = f"fora_da_janela (abre {time.strftime('%H:%M', time.localtime(prox))})"
        return d

    # 6. cool-off ancorado em "primeiro visto" — se a versão vista mudou,
    #    o âncora recomeça (uma versão nova sempre paga o cool-off inteiro).
    cooloff = (alvo.cooloff_s if alvo.cooloff_s is not None else cfg.cooloff_s)
    if est.vista_versao != alvo.versao_nova:
        est.vista_versao = alvo.versao_nova
        est.primeiro_visto = agora
    if cooloff > 0 and est.primeiro_visto is not None:
        decorrido = agora - est.primeiro_visto
        if decorrido < cooloff:
            falta = (cooloff - decorrido) / 3600.0
            d.acao = AGUARDAR
            d.motivo = f"cooloff (faltam {falta:.1f}h de {cooloff / 3600:.0f}h)"
            return d

    # 7. backoff pós-falha — falha dura volta mais tarde, sem loop quente.
    if est.falhas > 0 and est.ultima_tentativa is not None:
        espera = cfg.intervalo_s * est.falhas
        if agora - est.ultima_tentativa < espera:
            d.acao = AGUARDAR
            d.motivo = f"backoff_apos_falha ({est.falhas} falha(s), espera {espera / 60:.0f} min)"
            return d

    # 8. cap de bytes + pre-flight — o orçamento só estanca download; conteúdo
    #    local (bytes 0) nunca é barrado por disco.
    bytes_dentro = max(alvo.bytes_estimados, 0)
    if alvo.acao == ACAO_BAIXAR:
        if bytes_dentro and gasto + bytes_dentro > cfg.cap_bytes:
            d.motivo = (f"cap_de_bytes (ciclo gasta {bytes_dentro // 1024 ** 2} MB"
                        f" + {gasto // 1024 ** 2} já gastos > cap"
                        f" {cfg.cap_bytes // 1024 ** 2} MB)")
            return d
        if bytes_dentro and bytes_dentro * MARGEM_DISCO > espaco_livre:
            d.motivo = (f"sem_espaco (precisa ~{bytes_dentro // 1024 ** 2} MB,"
                        f" livre {espaco_livre // 1024 ** 2} MB)")
            return d
        partes = urlsplit(alvo.url)
        if partes.scheme not in ("http", "https") or not partes.netloc:
            d.motivo = f"url_invalida: {alvo.url[:60]}"
            return d
        if alvo.sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", alvo.sha256):
            d.motivo = f"sha256_invalido: {alvo.sha256[:16]}…"
            return d

    # Tudo passou.
    d.acao = APLICAR
    d.bytes = bytes_dentro
    d.motivo = (f"atualizacao_disponivel: {est.versao_instalada or alvo.versao_atual or '?'}"
                f" → {alvo.versao_nova}")
    return d


# --- Executor --------------------------------------------------------------


class AutoUpdateService:
    """Ciclo de auto-update: avalia (puro) e executa (sujo, mas contido).

    O executor NUNCA mexe em serviço rodando: downloads são baixados e
    verificados (sha256 pela fila da Parte D) e ficam staged em
    data/downloads; `pos_download: mover` faz os.replace atômico para
    dentro da árvore do repo (validado — fora da raiz é erro permanente).
    A troca de um modelo em uso (restart do llama-server etc.) é decisão
    explícita do dono — aqui fica a peça pronta e conferida.
    """

    def __init__(
        self,
        *,
        cfg: ConfigUpdate,
        estado_path: Path,
        manifesto_path: Path,
        raiz_downloads: Path,
        repo_root: Path,
        alvos_fn: Optional[Callable[[], list[AlvoUpdate]]] = None,
        rag_sync_fn: Optional[Callable[[], dict[str, int]]] = None,
        fila: Any = None,
        clock: Callable[[], float] = time.time,
        espaco_livre_fn: Optional[Callable[[Path], int]] = None,
    ) -> None:
        self.cfg = cfg
        self.estado_path = Path(estado_path)
        self.manifesto_path = Path(manifesto_path)
        self.raiz_downloads = Path(raiz_downloads)
        self.repo_root = Path(repo_root)
        self._alvos_fn = alvos_fn
        self._rag_sync_fn = rag_sync_fn
        self.fila = fila
        self._clock = clock
        self._espaco_livre_fn = espaco_livre_fn or _espaco_livre
        self._lock = threading.Lock()
        self._pendentes: dict[str, str] = {}   # job_id → alvo_id
        self._consumidor: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self.ultimas_decisoes: list[dict[str, Any]] = []
        self.ultimo_tick: Optional[float] = None

    # -- Estado -------------------------------------------------------------

    def carregar_estado(self) -> dict[str, EstadoAlvo]:
        """Lê o estado persistido (dict vazio se ausente/corrompido)."""
        try:
            bruto = json.loads(self.estado_path.read_text(encoding="utf-8"))
            alvos = bruto.get("alvos", bruto) if isinstance(bruto, dict) else {}
            return {
                str(k): EstadoAlvo.de_dict({"id": k, **v})
                for k, v in alvos.items()
                if isinstance(v, dict)
            }
        except FileNotFoundError:
            return {}
        except Exception as exc:  # estado corrompido não derruba o ciclo
            log.warn("Estado de auto-update ilegível — começando do zero",
                     error=_curto(exc))
            return {}

    def gravar_estado(self, estado: dict[str, EstadoAlvo]) -> None:
        """Escrita atômica (tmp → rename), mesmo padrão da fila da Parte D."""
        try:
            self.estado_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.estado_path.with_suffix(".tmp")
            payload = {"alvos": {k: v.para_dict() for k, v in estado.items()}}
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            os.replace(tmp, self.estado_path)
        except Exception as exc:
            log.warn("Estado de auto-update não gravado", error=_curto(exc))

    def resetar_alvo(self, alvo_id: str) -> bool:
        """Liga de novo um alvo auto-desligado (o dono manda, não a máquina)."""
        with self._lock:
            estado = self.carregar_estado()
            est = estado.get(alvo_id)
            if est is None:
                return False
            est.desabilitado = False
            est.motivo_desabilitado = ""
            est.falhas = 0
            est.primeiro_visto = None
            est.ultimo_erro = ""
            self.gravar_estado(estado)
        log.info("Alvo de auto-update religado pelo dono", alvo=alvo_id)
        return True

    # -- Alvos --------------------------------------------------------------

    def carregar_manifesto(self) -> list[AlvoUpdate]:
        """Manifesto editável pelo dono (lockfile declarativo de arquivos).

        JSON: {"alvos": [ {id, nome, categoria, acao, url, sha256, destino,
        pos_download, mover_para, versao_atual, versao_nova, bytes_estimados,
        ativa} ]}. Campo desconhecido é ignorado; id duplicado fica com o
        último; erro de sintaxe vira lista vazia com warn (o dono vê no painel).
        """
        try:
            bruto = json.loads(self.manifesto_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except Exception as exc:
            log.warn("Manifesto de auto-update ilegível",
                     arquivo=str(self.manifesto_path), error=_curto(exc))
            return []
        alvos: dict[str, AlvoUpdate] = {}
        for item in bruto.get("alvos", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            try:
                alvo = AlvoUpdate(
                    id=str(item["id"]),
                    nome=str(item.get("nome", item["id"])),
                    categoria=str(item.get("categoria", "modelo")),
                    acao=str(item.get("acao", ACAO_BAIXAR)),
                    url=str(item.get("url", "")),
                    sha256=str(item.get("sha256", "")),
                    destino=str(item.get("destino", "")),
                    pos_download=str(item.get("pos_download", POS_NADA)),
                    mover_para=str(item.get("mover_para", "")),
                    versao_atual=str(item.get("versao_atual", "")),
                    versao_nova=str(item.get("versao_nova", "")),
                    bytes_estimados=int(item.get("bytes_estimados", -1) or -1),
                    ativa=bool(item.get("ativa", True)),
                )
                cooloff = item.get("cooloff_h")
                alvo.cooloff_s = (float(cooloff) * 3600.0
                                  if cooloff is not None else None)
                alvos[alvo.id] = alvo
            except Exception as exc:
                log.warn("Alvo do manifesto ignorado", id=str(item.get("id")),
                         error=_curto(exc))
        return list(alvos.values())

    def _alvos(self) -> list[AlvoUpdate]:
        """Alvos do ciclo: provedor custom (testes) OU rag + manifesto."""
        if self._alvos_fn is not None:
            return self._alvos_fn()
        alvos = list(_alvos_rag(self.repo_root, self._tem_rag()))
        alvos.extend(self.carregar_manifesto())
        return alvos

    def _tem_rag(self) -> bool:
        return self._rag_sync_fn is not None

    # -- Ciclo ---------------------------------------------------------------

    def tick(self, *, dry_run: bool = False) -> list[DecisaoUpdate]:
        """Um ciclo completo: avalia e (se não for dry-run) executa.

        dry_run=True: avalia sobre CÓPIA do estado, não executa nada e não
        persiste — é o caminho do CI e do botão do painel.
        """
        agora = self._clock()
        estado = self.carregar_estado()
        if dry_run:
            estado = copy.deepcopy(estado)
        alvos = self._alvos()
        espaco = self._espaco_livre_fn(self.raiz_downloads)
        decisoes = avaliar(alvos, estado, self.cfg,
                           agora=agora, espaco_livre=espaco)

        if not dry_run:
            with self._lock:
                por_id = {a.id: a for a in alvos}
                for decisao in decisoes:
                    if decisao.acao != APLICAR:
                        continue
                    alvo = por_id.get(decisao.alvo)
                    if alvo is not None:
                        self._aplicar(alvo, estado, agora)
                self.gravar_estado(estado)
            self.ultimo_tick = agora

        self.ultimas_decisoes = [d.para_dict() for d in decisoes]
        aplicados = [d.alvo for d in decisoes if d.acao == APLICAR]
        resumo = ", ".join(f"{d.alvo}={d.acao}" for d in decisoes) or "sem alvos"
        log.info(
            "Auto-update tick" + (" (dry-run)" if dry_run else ""),
            alvos=len(decisoes), aplicar=len(aplicados), resumo=resumo,
        )
        return decisoes

    def _aplicar(self, alvo: AlvoUpdate, estado: dict[str, EstadoAlvo],
                 agora: float) -> None:
        """Executa UM 'aplicar': rag_sync local ou enfileira o download."""
        est = estado.setdefault(alvo.id, EstadoAlvo(id=alvo.id))
        est.ultima_tentativa = agora

        if alvo.acao == ACAO_RAG_SYNC:
            self._executar_rag_sync(alvo, est, agora)
            return
        if alvo.acao == ACAO_BAIXAR:
            self._enfileirar(alvo, est, agora)
            return
        # ACAO_NADA com versão nova: só registra (manifesto ainda sem ação).
        log.info("Alvo com atualização pendente sem ação declarada",
                 alvo=alvo.id, versao=alvo.versao_nova)

    def _executar_rag_sync(self, alvo: AlvoUpdate, est: EstadoAlvo,
                           agora: float) -> None:
        """Re-sincroniza o índice RAG (idempotente; VectorStore é RLock)."""
        if self._rag_sync_fn is None:
            self._registrar_falha(est, "rag_indisponivel", agora, dura=True)
            return
        try:
            stats = self._rag_sync_fn()
        except Exception as exc:
            self._registrar_falha(est, f"rag_sync: {_curto(exc)}", agora,
                                  dura=True)
            return
        est.versao_instalada = alvo.versao_nova
        est.falhas = 0
        est.ultimo_erro = ""
        est.ultima_sucesso = agora
        log.info("Índice RAG re-sincronizado (auto-update)", alvo=alvo.id,
                 arquivos=stats.get("arquivos", 0),
                 chunks=stats.get("chunks", 0),
                 novos=stats.get("novos", 0),
                 atualizados=stats.get("atualizados", 0),
                 removidos=stats.get("removidos", 0))

    def _enfileirar(self, alvo: AlvoUpdate, est: EstadoAlvo,
                    agora: float) -> None:
        """Enfileira o download na fila da Parte D (motor com retomada)."""
        if self.fila is None:
            self._registrar_falha(est, "fila_de_downloads_ausente", agora,
                                  dura=True)
            return
        try:
            job, criado = self.fila.enqueue(
                alvo.url, destino=alvo.destino, sha256=alvo.sha256,
            )
        except Exception as exc:
            self._registrar_falha(est, f"enqueue: {_curto(exc)}", agora,
                                  dura=True)
            return
        if not criado:
            # Dedup: já há um download ativo da mesma URL — não é falha.
            log.info("Auto-update: download já em andamento (dedup)",
                     alvo=alvo.id, job=job.id)
            self._pendentes[job.id] = alvo.id
            return
        self._pendentes[job.id] = alvo.id
        log.info("Auto-update enfileirou download", alvo=alvo.id,
                 job=job.id, bytes=alvo.bytes_estimados)

    # -- Resultado do download (eventos da fila) -----------------------------

    def tratar_evento(self, pacote: dict[str, Any]) -> None:
        """Reage a eventos da fila: sucesso conclui, erro falha (severidade).

        `skip` vs `failure` do Nômade: erro transitório da fila (que o
        motor já reenfileira) não chega aqui; o `erro` terminal é falha
        DURA e conta para o auto-disable.
        """
        job = pacote.get("job")
        if not isinstance(job, dict):
            return
        alvo_id = self._pendentes.get(str(job.get("id", "")))
        if alvo_id is None:
            return
        status = job.get("status")
        if status == CONCLUIDO:
            self._pendentes.pop(str(job.get("id")), None)
            self._concluir(alvo_id, str(job.get("id", "")))
        elif status == ERRO:
            self._pendentes.pop(str(job.get("id")), None)
            with self._lock:
                estado = self.carregar_estado()
                est = estado.setdefault(alvo_id, EstadoAlvo(id=alvo_id))
                self._registrar_falha(
                    est, f"download: {_curto(job.get('erro') or 'falhou')}",
                    self._clock(), dura=True,
                )
                self.gravar_estado(estado)

    def _concluir(self, alvo_id: str, job_id: str) -> None:
        """Download terminou: registra sucesso e (se pedido) move o arquivo."""
        with self._lock:
            estado = self.carregar_estado()
            est = estado.setdefault(alvo_id, EstadoAlvo(id=alvo_id))
            alvo = self._alvo_por_id(alvo_id)
            agora = self._clock()
            if alvo is not None and alvo.pos_download == POS_MOVER:
                erro = self._mover(alvo, est)
                if erro:
                    self._registrar_falha(est, erro, agora, dura=True)
                    self.gravar_estado(estado)
                    return
            est.versao_instalada = (alvo.versao_nova if alvo is not None
                                    else est.versao_instalada)
            est.falhas = 0
            est.ultimo_erro = ""
            est.ultima_sucesso = agora
            self.gravar_estado(estado)
        log.info("Auto-update: download concluído e verificado",
                 alvo=alvo_id, job=job_id)

    def _alvo_por_id(self, alvo_id: str) -> Optional[AlvoUpdate]:
        try:
            for alvo in self._alvos():
                if alvo.id == alvo_id:
                    return alvo
        except Exception:  # manifesto ilegível no meio do caminho
            return None
        return None

    def _mover(self, alvo: AlvoUpdate, est: EstadoAlvo) -> Optional[str]:
        """os.replace atômico para mover_para — travado na árvore do repo."""
        if not alvo.mover_para:
            return "mover_para_vazio"
        destino = (self.repo_root / alvo.mover_para).resolve()
        try:
            destino.relative_to(self.repo_root.resolve())
        except ValueError:
            return f"mover_para_fora_da_arvore: {alvo.mover_para[:60]}"
        origem = (self.raiz_downloads / alvo.destino).resolve()
        if not origem.is_file():
            return "arquivo_baixado_ausente"
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            os.replace(origem, destino)
        except Exception as exc:
            return f"mover: {_curto(exc)}"
        log.info("Auto-update: arquivo movido para o destino",
                 alvo=alvo.id, destino=str(destino))
        return None

    def _registrar_falha(self, est: EstadoAlvo, motivo: str, agora: float,
                         *, dura: bool) -> None:
        """Severidade do Nômade: só falha DURA conta para o auto-disable."""
        est.ultimo_erro = _curto(motivo)
        if not dura:
            log.warn("Auto-update: skip (não conta para auto-disable)",
                     alvo=est.id, motivo=est.ultimo_erro)
            return
        est.falhas += 1
        log.warn("Auto-update: falha", alvo=est.id, falhas=est.falhas,
                 motivo=est.ultimo_erro)
        if est.falhas >= self.cfg.max_falhas and not est.desabilitado:
            est.desabilitado = True
            est.motivo_desabilitado = _curto(
                f"{est.falhas} falhas seguidas: {est.ultimo_erro}"
            )
            log.error("Auto-update DESLIGADO automaticamente",
                      alvo=est.id, motivo=est.motivo_desabilitado,
                      religavel_pelo_painel=True)

    # -- Consumo dos eventos da fila -----------------------------------------

    def start(self) -> None:
        """Assina a fila da Parte D numa thread própria (SSE interno)."""
        if self.fila is None or self._consumidor is not None:
            return
        try:
            eventos, self._cancela = self.fila.subscribe()
        except Exception as exc:  # pragma: no cover — fila sem subscribe
            log.warn("Auto-update sem stream da fila", error=_curto(exc))
            return

        def _consumir() -> None:
            while not self._parar.is_set():
                try:
                    pacote = eventos.get(timeout=1.0)
                except queue_mod.Empty:
                    continue
                except Exception:  # pragma: no cover — fila fechando
                    return
                try:
                    self.tratar_evento(pacote)
                except Exception as exc:  # um evento não derruba o loop
                    log.warn("Auto-update: evento ignorado", error=_curto(exc))

        self._consumidor = threading.Thread(
            target=_consumir, name="od-auto-update", daemon=True,
        )
        self._consumidor.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Para o consumidor de eventos (estado já foi gravado a cada tick)."""
        self._parar.set()
        cancela = getattr(self, "_cancela", None)
        if cancela is not None:
            try:
                cancela()
            except Exception:  # pragma: no cover
                pass
        if self._consumidor is not None:
            self._consumidor.join(timeout=timeout)
            self._consumidor = None

    # -- Visibilidade ----------------------------------------------------------

    def estado_resumo(self) -> dict[str, Any]:
        """Painel: config + estado por alvo + últimas decisões + pendentes."""
        estado = self.carregar_estado()
        alvos = []
        try:
            alvos = [a.para_dict() for a in self._alvos()]
        except Exception as exc:  # pragma: no cover — manifesto ilegível
            log.warn("Auto-update: alvos ilegíveis no resumo", error=_curto(exc))
        return {
            "config": self.cfg.para_dict(),
            "alvos": alvos,
            "estado": [estado[a["id"]].para_dict() if a["id"] in estado
                       else EstadoAlvo(id=a["id"]).para_dict()
                       for a in alvos],
            "desabilitados": [e.para_dict() for e in estado.values()
                              if e.desabilitado],
            "pendentes": [{"alvo": a_id, "job": j_id}
                          for j_id, a_id in self._pendentes.items()],
            "ultimas_decisoes": self.ultimas_decisoes,
            "ultimo_tick": self.ultimo_tick,
        }

    def health_check(self, _monitor: Any = None) -> dict[str, Any]:
        """Check do HealthMonitor (não-crítico): só o essencial.

        O monitor invoca `check(monitor)` (HealthCheckFn de
        observability/health.py) — o argumento é aceito e ignorado aqui.
        """
        estado = self.carregar_estado()
        desligados = [e.id for e in estado.values() if e.desabilitado]
        return {
            "ok": not desligados,
            # chave "detail" = contrato do HealthMonitor (observability/
            # health.py lê ok/status/detail do dict retornado).
            "detail": (f"auto-update: {len(desligados)} alvo(s) desligado(s)"
                       if desligados else "auto-update operando"),
            "desligados": desligados,
            "ultimo_tick": self.ultimo_tick,
        }


# --- Provedores de alvo ------------------------------------------------------


def _espaco_livre(caminho: Path) -> int:
    """Espaço livre do filesystem de um caminho (preflight de disco)."""
    try:
        caminho.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(caminho).free
    except Exception:  # pragma: no cover — disco sem medição
        return 0


def hash_conteudo(raiz: Path, pastas: tuple[str, ...] = ("docs", "knowledge"),
                  ext: str = ".md") -> str:
    """Versão do corpus interno: sha1 curto de (nome, sha) de cada arquivo.

    Mesma filosofia do doc_id do RAG: determinístico pelo CONTEÚDO — editar
    um .md muda a versão; nada mudou → versão igual → "sem atualizacao".
    """
    h = hashlib.sha1()
    for pasta in pastas:
        alvo = raiz / pasta
        if not alvo.is_dir():
            continue
        for arq in sorted(alvo.glob(f"*{ext}")):
            h.update(arq.name.encode("utf-8"))
            h.update(arq.read_bytes())
    return h.hexdigest()[:12]


def _alvos_rag(repo_root: Path, tem_rag: bool) -> list[AlvoUpdate]:
    """Alvo `indice-rag`: resync quando docs/ ou knowledge/ mudam.

    Conteúdo LOCAL — cool-off zero (não há upstream para se proteger; o
    sync é idempotente e o VectorStore tem lock). Sem RAG no runtime o
    alvo nem entra (sem o quê sincronizar).
    """
    if not tem_rag:
        return []
    return [AlvoUpdate(
        id="indice-rag",
        nome="Índice RAG (docs/ + knowledge/)",
        categoria="conteudo",
        acao=ACAO_RAG_SYNC,
        versao_nova=hash_conteudo(repo_root),
        cooloff_s=0.0,
    )]


MANIFESTO_EXEMPLO = {
    "_comentario": (
        "Manifesto de auto-update (Parte E) — edite e salve; o ciclo "
        "pega na próxima janela. fluxo: (1) descubra a versão nova e o "
        "sha256 do arquivo; (2) preencha versao_nova + url + sha256 + "
        "bytes_estimados; (3) mantenha ativa=true; (4) dry-run no painel "
        "conferindo; (5) a janela aplica (download + verificação + staging "
        "em data/downloads; pos_download=mover troca de lugar sozinho). "
        "major (X novo) nunca aplica sozinho — é com você."
    ),
    "alvos": [],
}
