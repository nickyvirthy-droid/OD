"""OMEGA DRAKON • CORE
Módulo: core/hd_backup.py — snapshot do sistema para os HDs externos
(TODO §3.6 extensão / pendência "2 snapshots p/ HD externo", ordem do
dono de 16/10, montado em 17/10 quando as duas HDs ganharam fstab e
dono iguais)

O que é: um snapshot DIRETÓRIO por dia em cada HD externo, via `rsync
--link-dest` — a primeira rodada copia tudo (~5 GB) e as seguintes só
enviam o que mudou, com arquivos inalterados virando HARDLINKS (mesmo
conteúdo ⇒ mesmo inode ⇒ não duplica espaço no disco da HD).

  - `Mídias`  → `/home/alex/dados/od_snapshots/`  (801 GB livres)
  - `Arquivos` → `/mnt/Arquivos/od_snapshots/`    (120 GB livres)

Por que um serviço POR ALVO (e não um serviço só): as duas HDs podem
estar plugadas em momentos diferentes (fstab tem `nofail` de propósito)
— cada alvo tem janela, estado, falhas e check de saúde PRÓPRIOS: a
Mídias desconectada não trava a Arquivos nem esconde a verdade.

O que entra em TODO snapshot (lista de fontes — o 3D é o PRIMEIRO por
ser a linha vermelha do TODO, intocável):
  - `/home/alex/3D`             STLs pagos do dono (1,2 GB)
  - `<repo>`                    Omega Drakon inteiro (.env, git, docs,
                                data/ com as capturas)
  - `/home/alex/omegadrakon-tools`  dados das tools (exceto zim e
                                heap_dumps — ver exclusões)
  - `/srv/omegadrakon`          config do Homeassistant (88 MB)
  - `/etc/fstab`                como o disco deve montar (arquivo único)

Exclusões registradas (nunca entram, cada uma com motivo):
  - `<repo>/.venv`        recriável em 1 min (pip install)
  - `<repo>/backups`      os tars locais têm retenção e destino próprios
  - `<repo>/data/vector_memory`  índice do RAG, reconstruível (memory/rag.py)
  - `omegadrakon-tools/zim`  14 GB baixáveis pela action
                           `nomad_wikipedia_zim_download`
  - `stirling-pdf/configs/heap_dumps`  2,8 GB de artefato da era do OOM
                           (o dump continua no disco original; só não viaja)
  - `__pycache__`, `.pytest_cache`, `*.pyc`, `*.part`  lixo de build

Dados voláteis (SQLite) ganham tratamento próprio: `homebox.db` e o
`db.sqlite3` do Vaultwarden são copiados pelo **backup API do sqlite3**
(ponto consistente, WAL consolidado num arquivo só) e EXCLUÍDOS do
rsync — sem isso o `--link-dest` poderia herdar um arquivo vivo pela
via errada (cópia rasgada de banco é restore que não abre).

Padrão da casa (mesmo desenho do core/backup.py): o `avaliar()` é
pipeline de decisão PURO (relógio, estado, montagem do alvo e espaço
entram por parâmetro, sem I/O) e o MESMO caminho roda em produção e no
teste. Interface **compatível com `BackupService`** (`cfg`, `tick()`,
`snapshot()`, `check_saude()`, `registrar_no_health()`) — por isso o
`build_backups()` do launcher simplesmente acrescenta estes serviços à
mesma lista: loops, bloco `backup` do `/dashboard/stats` e os checks do
`/health` vêm todos de graça, sem ramiﬁcação nova.

Camadas do `avaliar()` — nesta ordem, cada uma com motivo:
  1. desligado        `OD_HD_SNAPSHOT=0` (o dono manda)
  2. antes da hora / já feito   (mesma janela/catch-up do backup tar)
  3. alvo_ausente     o ponto de montagem não está montado (HD
                      desplugada) — skip honesto; o check degrada e o
                      catch-up roda no primeiro tick depois de plugar
  4. disco            espaço livre < estimativa × 1,10 (guardrail)
  5. rodar

Retenção: reaproveita `calcular_retencao` do `core/backup.py` com
sufixo vazio (diretório, não `.tar.gz`) — 7 diários + 8 semanais por
HD; nome fora do padrão nunca entra na lista de remoção (diretório do
dono intocável). Publicação atômica: monta em `.tmp_<nome>` e renomeia;
o diretório do dia já existente (re-rodada) é substituído — artefato
nosso, apagado só ele.

Falha grita, sucesso silencioso: mesmo cooldown de 6 h de push do
backup tar. Nomes de knob: `OD_HD_SNAPSHOT`, `OD_HD_HORA`,
`OD_HD_CADENCIA_DIAS`, `OD_HD_INTERVALO_MIN`, `OD_HD_ALVOS`
(`Rótulo=/caminho,...`), `OD_HD_PASTA`, `OD_HD_DIARIOS`,
`OD_HD_SEMANAIS`, `OD_HD_EXCLUIR`.

Baseado em:
  - core/backup.py (avaliar puro, retenção, estado atômico, health)
  - /etc/fstab das duas HDs (UUID + nofail, 17/10 — nofail é o que
    permite pular sem drama quando o dono despluga uma)
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from core.backup import (
    AGUARDAR,
    ALERTA_FALHA_COOLDOWN_S,
    MARGEM_DISCO,
    PULAR,
    RODAR,
    DecisaoBackup,
    ResultadoBackup,
    calcular_retencao,
    proxima_janela,
    timestamp_do_nome,
)
from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.hd_backup")

# --- Constantes (defaults; tudo sobrescrevível por env) --------------------

PREFIXO_PADRAO = "snapshot_od"
HORA_PADRAO = "03:40"                # depois do estado (03:00), antes das 04:00
INTERVALO_PADRAO_S = 900.0           # tick a cada 15 min (decisão barata)
CADENCIA_PADRAO_DIAS = 1             # diário
DIARIOS_PADRAO = 7                   # retenção HD: mais recentes (hardlinks ⇒ barato)
SEMANAIS_PADRAO = 8                  # retenção HD: 1 por semana ISO
# Primeira rodada copia tudo (~5 GB medidos 17/10: 1,2 de 3D + 3,7 de
# repo + 88 MB de HA + ~2 MB de tools/fstab); o estado passa a valer o
# tamanho medido depois do 1º sucesso (mesma alquimia do backup tar).
ESTIMATIVA_PADRAO_BYTES = 5 * 1024 ** 3
PASTA_PADRAO = "od_snapshots"
# `Rótulo=/caminho` por vírgula — rótulo é o nome do dono (aparece no
# check do /health e no stats), caminho é o ponto de montagem.
ALVOS_PADRAO = "Mídias=/home/alex/dados,Arquivos=/mnt/Arquivos"
# Dados voláteis: backup API do sqlite3 (arquivo único, WAL consolidado),
# excluídos do rsync para nunca viajar pela via rasgada.
DB_FONTES: tuple[str, ...] = (
    "/home/alex/omegadrakon-tools/homebox/homebox.db",
    "/home/alex/omegadrakon-tools/vaultwarden/db.sqlite3",
)
# Lixo de build em qualquer nível (padrão sem `/` casa com qualquer
# componente do caminho no rsync).
LIXO_GERAL: tuple[str, ...] = ("__pycache__", ".pytest_cache", "*.pyc", "*.part")
# Exclusões FORA do repo (caminho absoluto no transfer root do rsync).
EXCLUIDOS_FORA_DO_REPO: tuple[str, ...] = (
    "/home/alex/omegadrakon-tools/zim",
    "/home/alex/omegadrakon-tools/stirling-pdf/configs/heap_dumps",
)
HORA_RE = re.compile(r"^\d{1,2}:\d{2}$")
MENSAGEM_MAX = 200
# Run interrompido deixa `.tmp_` para trás: limpo na próxima retenção.
TMP_IDADE_MAX_S = 6 * 3600.0
# Recibo de ilegíveis (ver `_achar_ilegiveis`): só o PRIMEIRO lote vai no
# `info.json`; o total sempre. Limite contra arquivo de log gigante.
ILEGETIVEIS_MAX = 100


def _curto(texto: Any) -> str:
    return str(texto)[:MENSAGEM_MAX]


def _slug(texto: str) -> str:
    """Rótulo do dono → pedaço de nome de arquivo/check (sem acento)."""
    base = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in base if not unicodedata.combining(c))
    limpo = re.sub(r"[^a-zA-Z0-9]+", "_", sem_acento).strip("_").lower()
    return limpo or "alvo"


def _timestamp_dir(nome: str, prefixo: str) -> Optional[float]:
    """Epoch do diretório canônico — o MESMO padrão do tar com sufixo
    vazio (reuso do `core.backup.timestamp_do_nome`, sem duplicar regra)."""
    return timestamp_do_nome(nome, prefixo, "")


def nome_dir(quando_wall: float, prefixo: str = PREFIXO_PADRAO) -> str:
    """Nome canônico do snapshot-dir (hora local): `PREFIXO-AAAA-MM-DD_HHMM`."""
    return datetime.fromtimestamp(quando_wall).strftime(f"{prefixo}-%Y-%m-%d_%H%M")


# --- Configuração ----------------------------------------------------------


@dataclass
class ConfigHD:
    """Configuração de UM alvo (interface par-a-par com ConfigBackup)."""

    habilitado: bool = True
    nome: str = "hd"
    rotulo: str = "Snapshot HD"
    check_nome: str = "hd"
    prefixo: str = PREFIXO_PADRAO
    hora: str = HORA_PADRAO
    cadencia_dias: int = CADENCIA_PADRAO_DIAS
    intervalo_s: float = INTERVALO_PADRAO_S
    diarios: int = DIARIOS_PADRAO
    semanais: int = SEMANAIS_PADRAO
    fontes: tuple[str, ...] = ()
    excluidos: tuple[str, ...] = ()
    estimativa_bytes: int = ESTIMATIVA_PADRAO_BYTES
    raiz: Path = Path(PASTA_PADRAO)      # subdiretório DENTRO do alvo
    estado_path: Path = Path("data/backup_hd_estado.json")
    alvo: str = ""                       # ponto de montagem da HD
    versao: str = ""

    @classmethod
    def de_env(
        cls,
        env: Callable[[str, str], str],
        *,
        alvo_rotulo: str,
        alvo_caminho: str,
        repo_root: Path,
        fontes: tuple[str, ...],
    ) -> "ConfigHD":
        """Lê o `.env` no padrão do launcher (`env(nome, default)`)."""
        hora = env("OD_HD_HORA", HORA_PADRAO).strip()
        valido = HORA_RE.match(hora)
        if valido:
            partes = hora.split(":")
            valido = int(partes[0]) <= 23 and int(partes[1]) <= 59
        if not valido:
            log.warn("Horário de snapshot HD inválido — usando default",
                     valor=hora, default=HORA_PADRAO)
            hora = HORA_PADRAO
        excluidos = tuple(
            item.strip().strip("/")
            for item in env("OD_HD_EXCLUIR", "").split(",")
            if item.strip()
        ) or fontes_excluidas(repo_root)
        raiz = Path(env("OD_HD_PASTA", PASTA_PADRAO)).name or PASTA_PADRAO
        slug = _slug(alvo_rotulo)
        return cls(
            habilitado=env("OD_HD_SNAPSHOT", "1") != "0",
            nome=f"hd_{slug}",
            rotulo=f"Snapshot HD {alvo_rotulo}",
            check_nome=f"hd_{slug}",
            prefixo=PREFIXO_PADRAO,
            hora=hora,
            cadencia_dias=max(
                1, int(env("OD_HD_CADENCIA_DIAS", str(CADENCIA_PADRAO_DIAS)))
            ),
            intervalo_s=float(env("OD_HD_INTERVALO_MIN", "15")) * 60.0,
            diarios=max(0, int(env("OD_HD_DIARIOS", str(DIARIOS_PADRAO)))),
            semanais=max(0, int(env("OD_HD_SEMANAIS", str(SEMANAIS_PADRAO)))),
            excluidos=excluidos,
            raiz=raiz,
            estado_path=Path(
                env("OD_HD_ESTADO", f"data/backup_hd_{slug}_estado.json")
            ),
            fontes=fontes,   # as fontes vêm do build, nunca do env
            alvo=alvo_caminho,
            versao=env("OD_VERSION", ""),
        )

    def para_dict(self) -> dict[str, Any]:
        return {
            "nome": self.nome,
            "rotulo": self.rotulo,
            "habilitado": self.habilitado,
            "hora": self.hora,
            "cadencia_dias": self.cadencia_dias,
            "intervalo_min": round(self.intervalo_s / 60.0, 1),
            "diarios": self.diarios,
            "semanais": self.semanais,
            "fontes": list(self.fontes),
            "excluidos": list(self.excluidos),
            "prefixo": self.prefixo,
            "raiz": str(self.raiz),
            "alvo": self.alvo,
        }


def fontes_do_sistema(repo_root: Path) -> tuple[str, ...]:
    """Fontes padrão: o 3D PRIMEIRO (linha vermelha do TODO), depois o resto."""
    return (
        "/home/alex/3D",
        str(repo_root),
        "/home/alex/omegadrakon-tools",
        "/srv/omegadrakon",
        "/etc/fstab",
    )


def fontes_excluidas(repo_root: Path) -> tuple[str, ...]:
    """Exclusões padrão (absolutas no transfer root do rsync)."""
    raiz = str(Path(repo_root)).rstrip("/")
    return (
        f"/{raiz}/.venv".replace("//", "/"),
        f"/{raiz}/backups".replace("//", "/"),
        f"/{raiz}/data/vector_memory".replace("//", "/"),
        *EXCLUIDOS_FORA_DO_REPO,
        *LIXO_GERAL,
    )


def parse_alvos(texto: str) -> list[tuple[str, str]]:
    """`Mídias=/a,Arquivos=/b` → [(rótulo, caminho), ...] (ordem preservada)."""
    alvos: list[tuple[str, str]] = []
    for item in texto.split(","):
        item = item.strip()
        if not item:
            continue
        rotulo, separador, caminho = item.partition("=")
        if not separador or not caminho.strip():
            log.warn("Alvo de snapshot HD ignorado (formato Rótulo=/caminho)",
                     item=item)
            continue
        alvos.append((rotulo.strip(), caminho.strip()))
    return alvos


# --- Decisão (pura) --------------------------------------------------------


def avaliar(
    cfg: ConfigHD,
    estado: dict[str, Any],
    *,
    agora_wall: float,
    montado: bool,
    espaco_livre: Optional[int] = None,
) -> DecisaoBackup:
    """Decide se é hora do snapshot NESTE alvo — sem I/O.

    Mesma pilha do `core/backup.avaliar()` + a camada `alvo_ausente` (HD
    desplugada — `nofail` no fstab: o boot não trava, o snapshot pula e
    o catch-up roda no primeiro tick depois de plugar).
    """
    if not cfg.habilitado:
        return DecisaoBackup(acao=PULAR, motivo="desligado")

    ultimo = float(estado.get("ultimo_sucesso") or 0.0) or None
    agendado = proxima_janela(
        ultimo, cadencia_dias=cfg.cadencia_dias, hora=cfg.hora,
        agora_wall=agora_wall,
    )
    precisa = int(estado.get("ultimo_bytes") or 0) or cfg.estimativa_bytes
    if agora_wall < agendado:
        feito_hoje = (
            ultimo is not None
            and datetime.fromtimestamp(ultimo).date()
            == datetime.fromtimestamp(agora_wall).date()
        )
        return DecisaoBackup(
            acao=AGUARDAR,
            motivo="ja_feito" if feito_hoje else "antes_da_hora",
            agendado_wall=agendado,
            proximo_em_s=agendado - agora_wall,
            precisa_bytes=precisa,
            espaco_livre=espaco_livre,
        )

    if not montado:
        return DecisaoBackup(
            acao=PULAR,
            motivo="alvo_ausente",
            agendado_wall=agendado,
            precisa_bytes=precisa,
            espaco_livre=espaco_livre,
        )

    faltando = int(precisa * MARGEM_DISCO)
    if espaco_livre is not None and espaco_livre < faltando:
        return DecisaoBackup(
            acao=PULAR,
            motivo="disco_insuficiente",
            agendado_wall=agendado,
            precisa_bytes=precisa,
            espaco_livre=espaco_livre,
        )

    return DecisaoBackup(
        acao=RODAR,
        motivo="agendado",
        agendado_wall=agendado,
        precisa_bytes=precisa,
        espaco_livre=espaco_livre,
    )


# --- Executor --------------------------------------------------------------


def _espaco_livre(caminho: Path) -> Optional[int]:
    alvo = Path(caminho)
    while not alvo.exists() and alvo != alvo.parent:
        alvo = alvo.parent
    try:
        livre = shutil.disk_usage(alvo).free
    except OSError:
        return None
    return int(livre)


def _montado_padrao(caminho: Path) -> bool:
    """A HD está MESMO montada (fstab nofail: pasta existe sem disco)."""
    try:
        return os.path.ismount(Path(caminho))
    except OSError:  # pragma: no cover — FS exótico
        return False


class HDBackupService:
    """Executor do snapshot-dir de UM alvo: rsync + retenção + estado.

    Interface par-a-par com `core.backup.BackupService` (cfg, tick,
    snapshot, check_saude, registrar_no_health) — o launcher trata os
    dois pela mesma lista.
    """

    def __init__(
        self,
        *,
        cfg: ConfigHD,
        push: Any = None,
        clock: Callable[[], float] = time.time,
        espaco_livre_fn: Optional[Callable[[Path], Optional[int]]] = None,
        montado_fn: Optional[Callable[[Path], bool]] = None,
        rsync_bin: str = "rsync",
    ) -> None:
        self.cfg = cfg
        self._push = push
        self._clock = clock
        self._espaco_livre_fn = espaco_livre_fn or _espaco_livre
        self._montado_fn = montado_fn or _montado_padrao
        self._rsync = rsync_bin
        self._lock = threading.RLock()

    # -- Estado persistido ---------------------------------------------------

    def carregar_estado(self) -> dict[str, Any]:
        try:
            dados = json.loads(
                self.cfg.estado_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        return dados if isinstance(dados, dict) else {}

    def gravar_estado(self, estado: dict[str, Any]) -> None:
        """Grava atômico (tmp → os.replace): crash não corrompe o estado."""
        try:
            self.cfg.estado_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cfg.estado_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(estado, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, self.cfg.estado_path)
        except OSError as exc:
            log.warn("Estado do snapshot HD não gravado", error=_curto(exc))

    # -- Snapshots em disco --------------------------------------------------

    def raiz_alvo(self) -> Path:
        return Path(self.cfg.alvo) / self.cfg.raiz

    def lista(self) -> dict[str, dict[str, Any]]:
        """Snapshots-dir presentes (mais novo primeiro) — painel/stats.

        O tamanho sai do `info.json` de cada snapshot (gravado na criação)
        — somar milhares de arquivos a cada /stats seria loucura; fallback
        é o stat do diretório (caso legado/manual).
        """
        raiz = self.raiz_alvo()
        if not raiz.is_dir() or not self._montado_fn(Path(self.cfg.alvo)):
            return {}
        itens: dict[str, dict[str, Any]] = {}
        for caminho in sorted(raiz.iterdir()):
            if not caminho.is_dir() or caminho.name.startswith(".tmp_"):
                continue
            quando = _timestamp_dir(caminho.name, self.cfg.prefixo)
            if quando is None:
                continue
            bytes_total = 0
            info_path = caminho / "info.json"
            try:
                dados_info = json.loads(info_path.read_text(encoding="utf-8"))
                bytes_total = int(dados_info.get("bytes") or 0)
            except (OSError, json.JSONDecodeError, ValueError):
                try:
                    bytes_total = int(caminho.stat().st_size)
                except OSError:  # pragma: no cover — corrida
                    continue
            itens[caminho.name] = {
                "arquivo": caminho.name,
                "bytes": bytes_total,
                "criado_wall": round(quando, 3),
                "criado": datetime.fromtimestamp(quando).strftime(
                    "%d/%m/%Y %H:%M"
                ),
            }
        ordenado = sorted(
            itens.items(), key=lambda par: par[1]["criado_wall"], reverse=True
        )
        return dict(ordenado)

    def snapshot(self) -> dict[str, Any]:
        """Estado + config + snapshots — base do /dashboard/stats."""
        estado = self.carregar_estado()
        agora = self._clock()
        agendado = proxima_janela(
            float(estado.get("ultimo_sucesso") or 0.0) or None,
            cadencia_dias=self.cfg.cadencia_dias, hora=self.cfg.hora,
            agora_wall=agora,
        )
        ultimo = float(estado.get("ultimo_sucesso") or 0.0)
        montado = self._montado_fn(Path(self.cfg.alvo))
        return {
            "nome": self.cfg.nome,
            "rotulo": self.cfg.rotulo,
            "config": self.cfg.para_dict(),
            "alvo": self.cfg.alvo,
            "montado": bool(montado),
            "ultimo_sucesso": round(ultimo, 3) if ultimo else 0.0,
            "ultimo_sucesso_em": (
                datetime.fromtimestamp(ultimo).strftime("%d/%m/%Y %H:%M")
                if ultimo else ""
            ),
            "ultimo_arquivo": estado.get("ultimo_arquivo", ""),
            "ultimo_bytes": int(estado.get("ultimo_bytes") or 0),
            "ultimo_ilegiveis": int(estado.get("ultimo_ilegiveis") or 0),
            "ultimo_sha256": estado.get("ultimo_sha256", ""),
            "rodadas": int(estado.get("rodadas") or 0),
            "falhas": int(estado.get("falhas") or 0),
            "ultimo_erro": estado.get("ultimo_erro", ""),
            "pendente_hoje": bool(agora >= agendado and ultimo < agendado),
            "arquivos": self.lista(),
        }

    # -- Saúde ---------------------------------------------------------------

    def check_saude(self) -> dict[str, Any]:
        """Check não-crítico do /health: o snapshot DESTE alvo saiu?"""
        agora = self._clock()
        estado = self.carregar_estado()
        ultimo = float(estado.get("ultimo_sucesso") or 0.0)
        agendado = proxima_janela(
            ultimo or None, cadencia_dias=self.cfg.cadencia_dias,
            hora=self.cfg.hora, agora_wall=agora,
        )
        montado = self._montado_fn(Path(self.cfg.alvo))
        rotulo = self.cfg.rotulo
        if ultimo and agora < agendado:
            horas = (agora - ultimo) / 3600.0
            tamanho = int(estado.get("ultimo_bytes") or 0) / 1024 ** 3
            arquivo = str(estado.get("ultimo_arquivo") or "")
            return {
                "ok": True,
                "status": "up",
                "detail": (
                    f"{rotulo} ok ({arquivo}, {tamanho:.2f} GB, "
                    f"há {horas:.1f} h)."
                ),
            }
        if agora < agendado:
            faltam = (agendado - agora) / 60.0
            return {
                "ok": True,
                "status": "up",
                "detail": (
                    f"{rotulo} agendado para {self.cfg.hora} "
                    f"(em {faltam:.0f} min)."
                ),
            }
        if not montado:
            return {
                "ok": False,
                "status": "degraded",
                "detail": (
                    f"{rotulo} PENDENTE — HD desconectada de "
                    f"{self.cfg.alvo} (plugue que o catch-up roda "
                    "sozinho no próximo tick)."
                ),
            }
        erro = str(estado.get("ultimo_erro") or "")
        sufixo = f" — último erro: {erro}" if erro else ""
        return {
            "ok": False,
            "status": "degraded",
            "detail": (
                f"{rotulo} PENDENTE (agendado {self.cfg.hora}, "
                f"falhas={int(estado.get('falhas') or 0)}){sufixo}"
            ),
        }

    def registrar_no_health(self, health: Any) -> Optional[str]:
        """Registra o check deste alvo (não-crítico) no HealthMonitor."""
        if health is None:
            return None
        health.register(self.cfg.check_nome,
                        lambda _monitor: self.check_saude(),
                        critical=False)
        return self.cfg.check_nome

    # -- Ciclo ---------------------------------------------------------------

    def avaliar(self) -> DecisaoBackup:
        return avaliar(
            self.cfg,
            self.carregar_estado(),
            agora_wall=self._clock(),
            montado=self._montado_fn(Path(self.cfg.alvo)),
            espaco_livre=self._espaco_livre_fn(Path(self.cfg.alvo)),
        )

    def tick(self, *, forcar: bool = False) -> ResultadoBackup:
        """Um ciclo: avalia e, se for hora (ou `forcar`), executa."""
        with self._lock:
            decisao = self.avaliar()
            if not forcar and decisao.acao != RODAR:
                log.debug("Snapshot HD: nada a fazer",
                          motivo=decisao.motivo, alvo=self.cfg.nome)
                return ResultadoBackup(
                    acao=decisao.acao, motivo=decisao.motivo
                )
            return self._executar(
                motivo="manual" if forcar else decisao.motivo
            )

    def rodar_agora(self) -> ResultadoBackup:
        """Snapshot fora da agenda (botão do painel / operação do dono)."""
        return self.tick(forcar=True)

    # -- Execução ------------------------------------------------------------

    def _executar(self, *, motivo: str) -> ResultadoBackup:
        inicio = self._clock()
        estado = self.carregar_estado()
        alvo = Path(self.cfg.alvo)
        try:
            if not self._montado_fn(alvo):
                raise RuntimeError("alvo desmontado no meio do caminho")
            raiz = self.raiz_alvo()
            raiz.mkdir(parents=True, exist_ok=True)
            nome = nome_dir(inicio, self.cfg.prefixo)
            final = raiz / nome
            tmp = raiz / f".tmp_{nome}"
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)

            fontes_vivas = [
                fonte for fonte in self.cfg.fontes if Path(fonte).exists()
            ]
            if not fontes_vivas:
                raise RuntimeError("nenhuma fonte existe — nada a copiar")

            transferidos, ilegiveis, total_ilegiveis = self._rsync_para(
                tmp, fontes_vivas
            )
            movidos = transferidos + self._copiar_dbs(tmp)
            if total_ilegiveis:
                log.warn("Snapshot HD: ilegíveis fora do snapshot (recibo "
                         "no info.json — sem copia sem sudo)",
                         alvo=self.cfg.nome, total=total_ilegiveis,
                         exemplo=ilegiveis[0] if ilegiveis else "-")
            bytes_total = self._gravar_info(
                tmp, nome=nome, fontes=fontes_vivas,
                bytes_transferidos=movidos,
                ilegiveis=ilegiveis, total_ilegiveis=total_ilegiveis,
            )

            # Publicação atômica: re-rodada no mesmo dia substitui SÓ o
            # artefatório nosso daquele dia (o diretório é do sistema).
            if final.exists():
                shutil.rmtree(final)
            os.replace(tmp, final)

            removidos = self._aplicar_retencao()
            duracao = max(0.0, self._clock() - inicio)
            estado.update({
                "ultimo_sucesso": inicio,
                "ultimo_bytes": bytes_total,
                "ultimo_arquivo": nome,
                "ultimo_ilegiveis": total_ilegiveis,
                "ultimo_erro": "",
                "falhas": 0,
                "rodadas": int(estado.get("rodadas") or 0) + 1,
            })
            self.gravar_estado(estado)
            log.info("Snapshot HD criado",
                     alvo=self.cfg.nome, nome=nome,
                     bytes=bytes_total, duracao_s=round(duracao, 1),
                     removidos=len(removidos), motivo=motivo)
            return ResultadoBackup(
                acao=RODAR, motivo=motivo, executado=True,
                arquivo=nome, bytes=bytes_total, removidos=removidos,
                duracao_s=duracao,
            )
        except Exception as exc:
            erro = _curto(exc)
            estado["falhas"] = int(estado.get("falhas") or 0) + 1
            estado["ultimo_erro"] = erro
            self.gravar_estado(estado)
            log.warn("Snapshot HD falhou", alvo=self.cfg.nome, error=erro)
            self._alertar_falha(estado, erro)
            return ResultadoBackup(
                acao=RODAR, motivo=motivo, erro=erro,
                duracao_s=max(0.0, self._clock() - inicio),
            )

    def _rsync_para(self, destino: Path, fontes: list[str]) -> tuple[int, list[str], int]:
        """rsync -a --relative --link-dest → só o que mudou custa espaço.

        Antes: varredura de ILEGÍVEIS (arquivos que o `alex` não lê, os
        root:root `0600` do `.storage` do Homeassistant) — são EXCLUÍDOS
        por caminho e entram no `info.json` como recibo (o restaurador
        sabe exatamente o que ficou de fora; sem sudo não há como
        copiar). O rsync 3.2.7 **não** tem `--skip-bad-files` (medido em
        17/10: a flag é de ≥3.4) e rc=23 derrubaria o snapshot inteiro
        por 5 arquivos — mas um arquivo ilegível NOVO que a varredura
        pegar também é excluído com recibo, e erro de verdade (rc≠0/24)
        continua gritando.

        Retorna (bytes transferidos, lista de ilegíveis, total de
        ilegíveis). rc 24 (arquivo sumiu no meio — log girando) é
        aceito como sucesso parcial honesto.
        """
        ilegiveis, total_ilegiveis = self._achar_ilegiveis(fontes)
        anterior = self._anterior(destino.parent)
        cmd = [self._rsync, "-a", "--relative", "--stats"]
        if anterior is not None:
            cmd.append(f"--link-dest={anterior.resolve()}")
        for excluido in self.cfg.excluidos:
            # Padrão passa COMO VEIO: com `/` ancora na raiz do transfer
            # (caminhos absolutos de fontes_excluidas); sem `/` casa em
            # qualquer nível (lixo geral como __pycache__). Ancorar tudo
            # — o erro que os testes pegaram — matava o lixo geral.
            cmd.append(f"--exclude={excluido}")
        for db in DB_FONTES:
            cmd.append(f"--exclude={db}*")
        for caminho in ilegiveis:
            cmd.append(f"--exclude={caminho}")
        cmd.extend(fontes)
        cmd.append(str(destino) + "/")
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
        )
        if proc.returncode not in (0, 24):
            raise RuntimeError(
                f"rsync rc={proc.returncode}: {_curto(proc.stderr)}"
            )
        return self._bytes_transferidos(proc.stdout), ilegiveis, total_ilegiveis

    def _achar_ilegiveis(self, fontes: list[str]) -> tuple[list[str], int]:
        """O que o `alex` não alcança — recibo honesto do que não viaja.

        `os.access` de verdade (não a permissão escrita): dono sem bit
        `r` não lê mesmo sendo dono. Diretório não listável chega pelo
        `onerror` do walk.
        """
        achados: list[str] = []
        total = 0

        def _erro(exc: OSError) -> None:
            nonlocal total
            total += 1
            caminho = getattr(exc, "filename", "") or ""
            if caminho and len(achados) < ILEGETIVEIS_MAX:
                achados.append(caminho)

        for fonte in fontes:
            raiz = Path(fonte)
            if raiz.is_file():
                if not os.access(raiz, os.R_OK):
                    total += 1
                    if len(achados) < ILEGETIVEIS_MAX:
                        achados.append(str(raiz))
                continue
            for atual, _dirs, arquivos in os.walk(raiz, onerror=_erro):
                for nome in arquivos:
                    caminho = os.path.join(atual, nome)
                    if not os.access(caminho, os.R_OK):
                        total += 1
                        if len(achados) < ILEGETIVEIS_MAX:
                            achados.append(caminho)
        return achados, total

    @staticmethod
    def _bytes_transferidos(stats: str) -> int:
        r"""`Total transferred file size` do `--stats` — à prova de locale.

        O rsync formata números no locale do serviço (`en_US`: `5,268,052,376`)
        — `(\d+)` puro pegava só o `5` (bug de produção medido em 17/10;
        a suíte não pegou porque a payload do teste tinha 8 bytes, abaixo
        do primeiro separador de milhar). Tira tudo que não é dígito.
        """
        m = re.search(
            r"Total transferred file size:\s+([\d][\d.,\u00a0\u202f ]*)",
            stats,
        )
        if not m:
            return 0
        digitos = re.sub(r"\D", "", m.group(1))
        return int(digitos) if digitos else 0

    def _anterior(self, raiz: Path) -> Optional[Path]:
        """Snapshot publicado mais recente (para o --link-dest)."""
        try:
            filhos = list(raiz.iterdir())
        except OSError:
            return None
        validos = [
            (filho.name, ts)
            for filho in filhos
            if filho.is_dir()
            and not filho.name.startswith(".tmp_")
            and (ts := _timestamp_dir(filho.name, self.cfg.prefixo))
            is not None
        ]
        if not validos:
            return None
        validos.sort(key=lambda par: par[1], reverse=True)
        return raiz / validos[0][0]

    def _copiar_dbs(self, destino: Path) -> int:
        """SQLite volátil → backup API (ponto consistente, WAL dentro).

        Cuidado clássico: `destino / origem` com `origem` ABSOLUTA o
        `/` absoluto vence (pathlib) e o "destino" vira o PRÓPRIO arquivo
        — backup de um banco nele mesmo trava para sempre. Mesma remoção
        do leading `/` que o `rsync -R` faz.
        """
        total = 0
        for origem in DB_FONTES:
            origem_path = Path(origem)
            if not origem_path.is_file():
                continue
            relativa = (
                Path(*origem_path.parts[1:])
                if origem_path.is_absolute() else origem_path
            )
            alvo = destino / relativa
            alvo.parent.mkdir(parents=True, exist_ok=True)
            fonte = sqlite3.connect(str(origem_path), timeout=10)
            saida = sqlite3.connect(str(alvo))
            try:
                fonte.backup(saida)
            finally:
                saida.close()
                fonte.close()
            total += alvo.stat().st_size
        return total

    @staticmethod
    def _tam_total(raiz: Path) -> int:
        total = 0
        for atual, _dirs, arquivos in os.walk(raiz):
            for nome in arquivos:
                try:
                    total += (Path(atual) / nome).stat().st_size
                except OSError:  # pragma: no cover — corrida
                    continue
        return total

    def _gravar_info(self, destino: Path, *, nome: str, fontes: list[str],
                     bytes_transferidos: int,
                     ilegiveis: Optional[list[str]] = None,
                     total_ilegiveis: int = 0) -> int:
        """`info.json` do snapshot: o que é, quando, de onde — p/ restaurar.

        `ilegiveis` é o RECIBO do que ficou de fora (arquivos que o
        `alex` não lê): o restaurador lê e sabe o que precisa de sudo.
        """
        bytes_total = self._tam_total(destino)
        dados = {
            "nome": nome,
            "alvo": self.cfg.alvo,
            "gerado_em": datetime.fromtimestamp(self._clock()).isoformat(
                timespec="seconds"
            ),
            "od_version": self.cfg.versao,
            "git": self._git_rev(),
            "fontes": fontes,
            "excluidos": list(self.cfg.excluidos),
            "ilegiveis": sorted(set(ilegiveis or [])),
            "ilegiveis_total": int(total_ilegiveis),
            "bytes_transferidos": bytes_transferidos,
            "bytes": bytes_total,
        }
        (destino / "info.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return bytes_total

    def _git_rev(self) -> str:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(self.cfg.fontes[1]) if len(self.cfg.fontes) > 1 else ".",
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def _aplicar_retencao(self) -> list[str]:
        """7 diários + 8 semanais por HD — nome fora do padrão intocável.

        Limpa aqui também `.tmp_` órfão de run interrompido (artefato
        NOSSO, >6 h — usa o relógio real porque a idade é contra o mtime
        real do arquivo, par coerente). Só diretórios entram na lista:
        arquivo solto com nome no padrão nunca é candidato a `rmtree`.
        """
        raiz = self.raiz_alvo()
        try:
            filhos = list(raiz.iterdir())
        except OSError:
            return []
        agora_real = time.time()
        for filho in filhos:
            if not filho.name.startswith(".tmp_") or not filho.is_dir():
                continue
            try:
                if (agora_real - filho.stat().st_mtime) > TMP_IDADE_MAX_S:
                    shutil.rmtree(filho)
            except OSError:  # pragma: no cover — corrida
                continue
        nomes = [
            filho.name for filho in filhos
            if filho.is_dir()
            and not filho.name.startswith(".tmp_")
            and _timestamp_dir(filho.name, self.cfg.prefixo) is not None
        ]
        decisao = calcular_retencao(
            nomes, diarios=self.cfg.diarios, semanais=self.cfg.semanais,
            prefixo=self.cfg.prefixo, sufixo="",
        )
        removidos: list[str] = []
        for nome in decisao.remover:
            caminho = raiz / nome
            try:
                shutil.rmtree(caminho)
                removidos.append(nome)
            except OSError as exc:  # pragma: no cover — corrida
                log.warn("Retenção do HD não removeu", nome=nome,
                         error=_curto(exc))
        return removidos

    def _alertar_falha(self, estado: dict[str, Any], erro: str) -> None:
        """Avisa o dono no celular — no máximo 1 push a cada 6 h."""
        if self._push is None:
            return
        agora = self._clock()
        ultimo = float(estado.get("ultimo_alerta_falha") or 0.0)
        if ultimo and (agora - ultimo) < ALERTA_FALHA_COOLDOWN_S:
            log.info("Aviso de falha do snapshot HD em espera (cooldown)",
                     alvo=self.cfg.nome)
            return
        estado["ultimo_alerta_falha"] = agora
        self.gravar_estado(estado)
        try:
            self._push.notify(
                f"{self.cfg.rotulo} falhou",
                f"O snapshot não foi criado: {erro}",
                data={"origem": f"hd-backup-{self.cfg.nome}"},
            )
        except Exception as exc:  # pragma: no cover — push degrada sozinho
            log.warn("Snapshot HD: aviso de push falhou", error=_curto(exc))


def build_hd_services(
    *,
    repo_root: Path,
    env: Optional[Callable[[str, str], str]] = None,
    push: Any = None,
    clock: Callable[[], float] = time.time,
    espaco_livre_fn: Optional[Callable[[Path], Optional[int]]] = None,
    montado_fn: Optional[Callable[[Path], bool]] = None,
    alvos_texto: Optional[str] = None,
) -> list[HDBackupService]:
    """Um serviço POR ALVO ligado no env — [] quando desligado.

    Ponto ÚNICO de construção (launcher e teste usam o mesmo caminho):
    `OD_HD_ALVOS` dá os pares `Rótulo=/caminho` (default = as duas HDs
    do dono) e `OD_HD_SNAPSHOT=0` desliga tudo (sem loop, sem check, sem
    bloco no stats).
    """
    leitor = env or (lambda _nome, padrao: padrao)
    if leitor("OD_HD_SNAPSHOT", "1") == "0":
        return []
    texto = alvos_texto if alvos_texto is not None else leitor(
        "OD_HD_ALVOS", ALVOS_PADRAO
    )
    fontes = fontes_do_sistema(repo_root)
    servicos: list[HDBackupService] = []
    for rotulo, caminho in parse_alvos(texto):
        config = ConfigHD.de_env(
            leitor, alvo_rotulo=rotulo, alvo_caminho=caminho,
            repo_root=repo_root, fontes=fontes,
        )
        servicos.append(HDBackupService(
            cfg=config, push=push, clock=clock,
            espaco_livre_fn=espaco_livre_fn, montado_fn=montado_fn,
        ))
    return servicos
