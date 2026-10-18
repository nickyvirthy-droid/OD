"""OMEGA DRAKON • CORE
Módulo: core/backup.py — backup automático do estado irrecuperável (TODO §3.6)

O que é: UM `.tar.gz` por snapshot, na máquina, pensado para o dono
copiar para um HD externo (local-only por decisão dele, 16/10/2026), em
DOIS perfis com propósitos diferentes:

  - `estado` (diário, 03:00 local, `backups/auto/`): `.env` + `data/` SEM
    `captures/` e SEM `vector_memory/` — tokens, filas, devices, estados
    (~185 KB por rodada). Retenção 3 diários + 8 semanais.
  - `capturas` (semanal, 04:00 local, `backups/auto-capturas/`): `.env` +
    `data/` SEM `vector_memory/` — ou seja, **as fotos e vídeos de
    `data/captures` entram** (316 MB medidos em 16/10, que o gzip NÃO
    reduz: mídia já comprimida). Retenção 4 semanas (~1,3 GB dos 86 GB
    livres medidos). Todo dia seria desperdício: é um acervo append-only.

O índice do RAG (`data/vector_memory`, 11 MB) fica fora dos dois perfis
por ser reconstruível a partir dos documentos (`memory/rag.py`).

Padrão da casa (mesmo desenho do auto-update/Parte E e das tools Nômades):
o `avaliar()` é um pipeline de decisão PURO — relógio, estado, espaço em
disco e os nomes já no diretório entram por parâmetro, sem I/O — e o
MESMO caminho roda em produção, no teste e num eventual dry-run. O
executor (`BackupService`) é a parte suja: monta o tar, grava atômico
(tmp → `os.replace`), persiste o estado em JSON atômico e aplica a
retenção.

Camadas do `avaliar()` — nesta ordem, cada uma com motivo registrado:
  1. desligado        `OD_BACKUP=0` / `OD_BACKUP_CAPTURAS=0` (o dono
                      manda, não a máquina)
  2. antes da hora    a janela ainda não abriu (HH:MM do dia, ou o dia
                      certo da cadência)
  3. já feito         houve sucesso hoje e a próxima janela é depois
  4. disco            espaço livre < estimativa × 1,10 (guardrail de
                      disco — nada de o snapshot ser a gota que enche o
                      copo)
  5. rodar            (com catch-up: se o servidor estava desligado no
                      horário/dia, o primeiro tick depois disso roda)

A janela sai da CADÊNCIA (`cadencia_dias`): 1 = diário, 7 = semanal —
`proxima_janela()` é a mesma conta para os dois e mantém os motivos.

Retenção (decisão do dono): no perfil do estado, 3 diários + 8 semanais
= no máximo 11 arquivos (~2 MB); no das capturas, 4 semanais (~1,3 GB).
A regra é pura e testável (`calcular_retencao`): fica o mais recente de
cada uma das N semanas ISO mais recentes + os K arquivos mais recentes;
nome fora do padrão (ou de outro perfil/prefixo) nunca é apagado —
arquivo do dono no diretório é intocável.

Segurança: o `.env` vai dentro do tar, então arquivo `0600` e diretório
`0700` — backup local que vaza segredo não é backup. O tar é
determinístico no contêiner (gzip com mtime 0, uid/gid 0, membros
ordenados): mesmo conteúdo ⇒ mesmo sha256.

Visibilidade: um check NÃO crítico por perfil no `/health` (`backup` e
`backup_capturas`) — degrada quando o snapshot da janela não aconteceu —,
bloco `backup` (um por perfil) no `/dashboard/stats` e cards no `/admin`.
Falha de execução avisa no celular do dono via PushService (best-effort,
com espera de 6 h entre avisos para um erro persistente não virar spam).

Baseado em:
  - core/auto_update.py (Parte E — avaliar puro + executor + estado atômico)
  - core/nomad_tools.py (registro de check não-crítico no /health)
  - TODO.md §3.6 (ordem do dono, 2026-10-16)

Decisões registradas (ver CHANGELOG):
  - Perfil `estado`: `.env` + `data/` SEM `captures/` e SEM
    `vector_memory/` (escolha do dono: "só o essencial irrecuperável")
  - Perfil `capturas` (ordem do dono, 16/10): as fotos/vídeos entram num
    snapshot SEMANAL separado, para o HD externo
  - Local-only: sem S3/MinIO/rclone — o dono copia para o HD externo
  - 03:00 diário (3+8) e 04:00 semanal (4), com catch-up no primeiro tick
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.backup")

# --- Constantes (defaults; tudo sobrescrevível por env) --------------------

HORA_PADRAO = "03:00"                 # horário LOCAL do snapshot diário
INTERVALO_PADRAO_S = 900.0            # tick a cada 15 min (decisão barata)
DIARIOS_PADRAO = 3                    # retenção: mais recentes
SEMANAIS_PADRAO = 8                   # retenção: 1 por semana ISO
# Estimativa usada só quando ainda não há snapshot medido (primeira
# rodada): o tamanho real passa a valer no estado depois do 1º sucesso.
ESTIMATIVA_PADRAO_BYTES = 32 * 1024 ** 2
MARGEM_DISCO = 1.10                   # 10% de folga no guardrail de disco
ALERTA_FALHA_COOLDOWN_S = 6 * 3600.0  # 1 aviso de falha a cada 6 h
MENSAGEM_MAX = 200                    # limite do motivo/detalhe gravado
FONTES_PADRAO: tuple[str, ...] = (".env", "data")
# Caminhos EXCLUÍDOS, relativos à raiz do repo (decisão do dono, 16/10):
# capturas (fotos/vídeos de 43 dias) e o índice do RAG (reconstruível).
EXCLUIDOS_PADRAO: tuple[str, ...] = (
    "data/captures",
    "data/vector_memory",
)
# Nunca entram no tar: lixo de build e transferências em andamento.
IGNORAR_DIRS: tuple[str, ...] = ("__pycache__",)
IGNORAR_SUFIXOS: tuple[str, ...] = (".pyc", ".pyo", ".part", ".tmp")
ESTADO_PADRAO = Path("data/backup_estado.json")
RAIZ_PADRAO = Path("backups/auto")
SUFIXO_TMP = ".tmp"
HORA_RE = re.compile(r"^\d{1,2}:\d{2}$")
PREFIXO_PADRAO = "od"
CADENCIA_PADRAO_DIAS = 1
# Perfil das CAPTURAS (ordem do dono, 16/10): as fotos/vídeos (`data/
# captures`, 316 MB que o gzip NÃO reduz — mídia já comprimida) ganham um
# snapshot PRÓPRIO, semanal, para ele levar no HD externo. Separado do
# diário de propósito: 316 MB todo dia seria desperdício (o arquivo é
# append-only) e a retenção semanal mantém 4 semanas (~1,3 GB dos 86 GB
# livres medidos em 16/10). O índice do RAG continua fora (reconstruível).
CAPTURAS_EXCLUIDOS: tuple[str, ...] = ("data/vector_memory",)
CAPTURAS_SEMANAIS_PADRAO = 4
CAPTURAS_RAIZ_PADRAO = Path("backups/auto-capturas")
CAPTURAS_ESTADO_PADRAO = Path("data/backup_capturas_estado.json")
CAPTURAS_HORA_PADRAO = "04:00"
CAPTURAS_PREFIXO = "od-capturas"
CAPTURAS_CADENCIA_DIAS = 7
# Nome canônico por perfil (prefixo distingue estado × capturas no disco).
_NOME_RE_CACHE: dict[tuple[str, str], re.Pattern[str]] = {}


def _nome_re(prefixo: str, sufixo: str = r"\.tar\.gz$") -> re.Pattern[str]:
    """Regex do nome canônico — `sufixo` vazia vale para diretórios (HD)."""
    chave = (prefixo, sufixo)
    padrao = _NOME_RE_CACHE.get(chave)
    if padrao is None:
        padrao = re.compile(
            rf"^{re.escape(prefixo)}-(\d{{4}})-(\d{{2}})-(\d{{2}})_"
            rf"(\d{{2}})(\d{{2}}){sufixo}$"
        )
        _NOME_RE_CACHE[chave] = padrao
    return padrao

# Ações do pipeline
RODAR = "rodar"
AGUARDAR = "aguardar"
PULAR = "pular"


def _curto(texto: Any) -> str:
    """Recorta mensagem para caber em log/estado sem virar ensaio."""
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= MENSAGEM_MAX else texto[: MENSAGEM_MAX - 1] + "…"


def _hhmm(texto: str) -> tuple[int, int]:
    """'HH:MM' → (hora, minuto) validados (ConfigBackup garante o formato)."""
    hora, minuto = texto.split(":")
    return int(hora), int(minuto)


def proxima_janela(
    ultimo_sucesso: Optional[float],
    *, cadencia_dias: int, hora: str, agora_wall: float,
) -> float:
    """Quando o PRÓXIMO snapshot é devido (epoch, hora local).

    Sem sucesso anterior: é hoje no HH:MM. Com sucesso anterior: é o dia
    do sucesso + `cadencia_dias` no HH:MM — cadência 1 reproduz o
    comportamento diário (inclusive o catch-up de quem estava desligado
    na hora) e cadência 7 dá o semanal das capturas.
    """
    if ultimo_sucesso is None:
        return agendado_no_dia(agora_wall, hora)
    h, m = _hhmm(hora)
    dia = datetime.fromtimestamp(ultimo_sucesso).date() + timedelta(
        days=max(1, int(cadencia_dias))
    )
    return datetime(dia.year, dia.month, dia.day, h, m).timestamp()


def agendado_no_dia(agora_wall: float, hora: str) -> float:
    """Epoch do HH:MM LOCAL do dia de `agora_wall` (relógio de parede).

    A agenda é hora de parede (03:00 para o dono é 03:00), não monotônica
    — por isso o snapshot usa `time.time()` enquanto o anti-spam dos
    outros serviços usa monotônico.
    """
    h, m = _hhmm(hora)
    dt = datetime.fromtimestamp(agora_wall)
    return dt.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


def nome_snapshot(quando_wall: float,
                  prefixo: str = PREFIXO_PADRAO) -> str:
    """Nome canônico do snapshot (hora local): `PREFIXO-AAAA-MM-DD_HHMM.tar.gz`."""
    return datetime.fromtimestamp(quando_wall).strftime(
        f"{prefixo}-%Y-%m-%d_%H%M.tar.gz"
    )


def timestamp_do_nome(nome: str,
                      prefixo: str = PREFIXO_PADRAO,
                      sufixo: str = r"\.tar\.gz$") -> Optional[float]:
    """Epoch do nome canônico; None para nome fora do padrão/perfil.

    `sufixo` vazia ("" ) serve diretórios — usada pelo snapshot de HD
    (core/hd_backup.py); o default continua o tar, byte a byte.
    """
    m = _nome_re(prefixo, sufixo).match(nome)
    if not m:
        return None
    ano, mes, dia, hora, minuto = (int(g) for g in m.groups())
    try:
        return datetime(ano, mes, dia, hora, minuto).timestamp()
    except ValueError:  # data impossível (ex: 2026-13-45)
        return None


def semana_iso(ts: float) -> tuple[int, int]:
    """(ano, semana) ISO do snapshot — agrupamento da retenção semanal."""
    iso = datetime.fromtimestamp(ts).isocalendar()
    return int(iso[0]), int(iso[1])


# --- Configuração ----------------------------------------------------------

# Defaults por PERFIL — um mesmo código, dois trabalhos com propósitos
# diferentes (o diário pequeno do estado e o semanal grande das capturas).
# `env_prefixo` é o prefixo dos knobs no `.env` (ex: OD_BACKUP_CAPTURAS_HORA).
PERFIS: dict[str, dict[str, Any]] = {
    "estado": {
        "nome": "estado",
        "rotulo": "Backup do estado",
        "check_nome": "backup",
        "env_prefixo": "OD_BACKUP",
        "prefixo": PREFIXO_PADRAO,
        "raiz": RAIZ_PADRAO,
        "estado": ESTADO_PADRAO,
        "hora": HORA_PADRAO,
        "cadencia_dias": CADENCIA_PADRAO_DIAS,
        "diarios": DIARIOS_PADRAO,
        "semanais": SEMANAIS_PADRAO,
        "excluidos": EXCLUIDOS_PADRAO,
    },
    "capturas": {
        "nome": "capturas",
        "rotulo": "Backup das capturas",
        "check_nome": "backup_capturas",
        "env_prefixo": "OD_BACKUP_CAPTURAS",
        "prefixo": CAPTURAS_PREFIXO,
        "raiz": CAPTURAS_RAIZ_PADRAO,
        "estado": CAPTURAS_ESTADO_PADRAO,
        "hora": CAPTURAS_HORA_PADRAO,
        "cadencia_dias": CAPTURAS_CADENCIA_DIAS,
        "diarios": 0,  # semanal: 1 arquivo por semana (4 semanas)
        "semanais": CAPTURAS_SEMANAIS_PADRAO,
        "excluidos": CAPTURAS_EXCLUIDOS,
    },
}


@dataclass
class ConfigBackup:
    """Configuração de UM perfil de backup (env `<PREFIXO>_*`)."""

    habilitado: bool = True
    nome: str = "estado"
    rotulo: str = "Backup do estado"
    check_nome: str = "backup"
    prefixo: str = PREFIXO_PADRAO
    hora: str = HORA_PADRAO
    cadencia_dias: int = CADENCIA_PADRAO_DIAS
    intervalo_s: float = INTERVALO_PADRAO_S
    diarios: int = DIARIOS_PADRAO
    semanais: int = SEMANAIS_PADRAO
    fontes: tuple[str, ...] = FONTES_PADRAO
    excluidos: tuple[str, ...] = EXCLUIDOS_PADRAO
    estimativa_bytes: int = ESTIMATIVA_PADRAO_BYTES
    raiz: Path = RAIZ_PADRAO
    estado_path: Path = ESTADO_PADRAO

    @classmethod
    def de_env(
        cls, env: Callable[[str, str], str], perfil: str = "estado",
    ) -> "ConfigBackup":
        """Lê o `.env` no padrão do launcher (`env(nome, default)`).

        `perfil` escolhe o conjunto de defaults (`PERFIS`) e o prefixo dos
        knobs; os nomes do perfil `estado` continuam exatamente os de
        antes (OD_BACKUP_HORA, OD_BACKUP_DIARIOS...).
        """
        base = PERFIS.get(perfil) or PERFIS["estado"]
        chave = str(base["env_prefixo"])
        hora = env(f"{chave}_HORA", str(base["hora"])).strip()
        valido = HORA_RE.match(hora)
        if valido:
            h, m = _hhmm(hora)
            valido = h <= 23 and m <= 59
        if not valido:
            log.warn("Horário de backup inválido — usando default",
                     valor=hora, default=base["hora"])
            hora = str(base["hora"])
        excluidos = tuple(
            item.strip().strip("/")
            for item in env(
                f"{chave}_EXCLUIR", ",".join(base["excluidos"])
            ).split(",")
            if item.strip()
        )
        return cls(
            habilitado=env(chave, "1") != "0",
            nome=str(base["nome"]),
            rotulo=str(base["rotulo"]),
            check_nome=str(base["check_nome"]),
            prefixo=str(base["prefixo"]),
            hora=hora,
            cadencia_dias=max(
                1, int(env(f"{chave}_CADENCIA_DIAS",
                           str(base["cadencia_dias"])))
            ),
            intervalo_s=float(env(f"{chave}_INTERVALO_MIN", "15")) * 60.0,
            diarios=max(
                0, int(env(f"{chave}_DIARIOS", str(base["diarios"])))
            ),
            semanais=max(
                0, int(env(f"{chave}_SEMANAIS", str(base["semanais"])))
            ),
            excluidos=excluidos,
            raiz=Path(env(f"{chave}_DIR", str(base["raiz"]))),
            estado_path=Path(
                env(f"{chave}_ESTADO", str(base["estado"]))
            ),
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
        }


# --- Modelo de dados -------------------------------------------------------

@dataclass
class DecisaoBackup:
    """O que fazer neste tick — sempre com motivo (padrão da casa)."""

    acao: str                 # rodar | aguardar | pular
    motivo: str
    agendado_wall: float = 0.0
    proximo_em_s: float = 0.0
    precisa_bytes: int = 0
    espaco_livre: Optional[int] = None

    def para_dict(self) -> dict[str, Any]:
        return {
            "acao": self.acao,
            "motivo": self.motivo,
            "agendado_wall": round(self.agendado_wall, 3),
            "proximo_em_s": round(self.proximo_em_s, 1),
            "precisa_bytes": self.precisa_bytes,
            "espaco_livre": self.espaco_livre,
        }


@dataclass
class Retencao:
    """Separação pura entre o que fica e o que sai."""

    manter: list[str] = field(default_factory=list)
    remover: list[str] = field(default_factory=list)

    def para_dict(self) -> dict[str, Any]:
        return {
            "manter": list(self.manter),
            "remover": list(self.remover),
            "total_apos": len(self.manter),
        }


@dataclass
class ResultadoBackup:
    """Resultado de um tick (executado ou não)."""

    acao: str
    motivo: str
    executado: bool = False
    arquivo: str = ""
    membros: int = 0
    bytes: int = 0
    sha256: str = ""
    removidos: list[str] = field(default_factory=list)
    erro: str = ""
    duracao_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.erro

    def para_dict(self) -> dict[str, Any]:
        return {
            "acao": self.acao,
            "motivo": self.motivo,
            "executado": self.executado,
            "ok": self.ok,
            "arquivo": self.arquivo,
            "membros": self.membros,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "removidos": list(self.removidos),
            "erro": self.erro,
            "duracao_s": round(self.duracao_s, 3),
        }


# --- Pipeline de decisão (puro) -------------------------------------------

def avaliar(
    cfg: ConfigBackup,
    estado: dict[str, Any],
    *,
    agora_wall: float,
    espaco_livre: Optional[int] = None,
) -> DecisaoBackup:
    """Decide se é hora do snapshot diário — SEM tocar em disco.

    `espaco_livre` em bytes (None = não avaliar disco, ex.: teste puro).
    A janela vem da CADÊNCIA (`cfg.cadencia_dias`): 1 = diário (é o perfil
    do estado) e 7 = semanal (perfil das capturas). Catch-up embutido: se o
    servidor estava desligado no horário, o primeiro tick depois dele roda.
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
        # Já houve sucesso HOJE e a próxima janela é amanhã/na próxima
        # semana: é "já feito" (o snapshot anterior ainda cobre a janela),
        # não "antes da hora" (janela do dia ainda fechada).
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


def calcular_retencao(
    nomes: list[str],
    *,
    diarios: int = DIARIOS_PADRAO,
    semanais: int = SEMANAIS_PADRAO,
    prefixo: str = PREFIXO_PADRAO,
    sufixo: str = r"\.tar\.gz$",
) -> Retencao:
    """Quais snapshots ficam: os `diarios` mais recentes + 1 por semana.

    Regra do dono (16/10): 3 diários + 8 semanais. As semanas são contadas
    sobre a lista INTEIRA (o mais novo de cada semana é o representante
    dela): assim cada uma das 8 semanas mais recentes tem um snapshot — o
    diário de hoje representa a semana corrente e não gasta um slot
    semanal extra. Nome fora do padrão (ou do dono) NUNCA entra na lista
    de remoção — o diretório é dele.
    """
    validos = [
        (nome, ts)
        for nome in nomes
        if (ts := timestamp_do_nome(nome, prefixo, sufixo)) is not None
    ]
    validos.sort(key=lambda item: item[1], reverse=True)
    diarios_escolhidos = {
        nome for nome, _ in validos[: max(0, diarios)]
    }
    semanas: list[tuple[int, int]] = []
    semanais_escolhidos: set[str] = set()
    for nome, ts in validos:
        semana = semana_iso(ts)
        if semana in semanas:
            continue
        semanas.append(semana)
        if len(semanas) <= max(0, semanais):
            semanais_escolhidos.add(nome)
    ficam = diarios_escolhidos | semanais_escolhidos
    return Retencao(
        manter=[nome for nome, _ in validos if nome in ficam],
        remover=[nome for nome, _ in validos if nome not in ficam],
    )


def _ignorar(rel: str) -> bool:
    """Lixo de build e transferências em andamento não entram no tar."""
    partes = rel.split("/")
    if any(parte in IGNORAR_DIRS for parte in partes):
        return True
    return rel.lower().endswith(IGNORAR_SUFIXOS)


def plano_de_conteudo(
    repo_root: Path,
    *,
    fontes: tuple[str, ...] = FONTES_PADRAO,
    excluidos: tuple[str, ...] = EXCLUIDOS_PADRAO,
) -> list[tuple[Path, str]]:
    """Lista (caminho absoluto, nome no tar) — ordenada e sem surpresa.

    `excluidos` são caminhos RELATIVOS à raiz do repo: um diretório
    excluído leva junto todo o conteúdo dele (`data/captures`).
    """
    raiz = Path(repo_root)
    excl = {str(item).strip("/") for item in excluidos}
    plano: list[tuple[Path, str]] = []
    for fonte in fontes:
        caminho = raiz / fonte
        if not caminho.exists():
            continue
        if caminho.is_file():
            plano.append((caminho, fonte))
            continue
        for atual in sorted(caminho.rglob("*")):
            if not atual.is_file():
                continue
            rel = atual.relative_to(raiz).as_posix()
            if any(rel == e or rel.startswith(e + "/") for e in excl):
                continue
            if _ignorar(rel):
                continue
            plano.append((atual, rel))
    plano.sort(key=lambda item: item[1])
    return plano


# --- Executor --------------------------------------------------------------


def _espaco_livre_padrao(caminho: Path) -> Optional[int]:
    """Espaço livre no volume de `caminho` (sobe até um ancestral real)."""
    alvo = Path(caminho)
    while not alvo.exists() and alvo != alvo.parent:
        alvo = alvo.parent
    try:
        return int(shutil.disk_usage(alvo).free)
    except OSError:  # pragma: no cover — disco ilegível
        return None


class BackupService:
    """Executor do snapshot diário: tar atômico + estado + retenção.

    `clock` é `time.time()` (hora de parede: a agenda é 03:00 do dono);
    `espaco_livre_fn` e `push` são injetáveis para teste.
    """

    def __init__(
        self,
        *,
        cfg: ConfigBackup,
        repo_root: Path,
        push: Any = None,
        clock: Callable[[], float] = time.time,
        espaco_livre_fn: Optional[Callable[[Path], Optional[int]]] = None,
    ) -> None:
        self.cfg = cfg
        self.repo_root = Path(repo_root)
        self._push = push
        self._clock = clock
        self._espaco_livre_fn = espaco_livre_fn or _espaco_livre_padrao
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
            log.warn("Estado do backup não gravado", error=_curto(exc))

    # -- Snapshots em disco --------------------------------------------------

    def lista(self) -> list[dict[str, Any]]:
        """Snapshots presentes (mais novo primeiro) — leitura para o painel."""
        raiz = self.cfg.raiz
        if not raiz.exists():
            return []
        itens: list[dict[str, Any]] = []
        for caminho in sorted(raiz.iterdir()):
            if not caminho.is_file():
                continue
            quando = timestamp_do_nome(caminho.name, self.cfg.prefixo)
            if quando is None:
                continue
            try:
                tamanho = caminho.stat().st_size
            except OSError:  # pragma: no cover — corrida com a remoção
                continue
            itens.append({
                "arquivo": caminho.name,
                "bytes": int(tamanho),
                "criado_wall": round(quando, 3),
                "criado": datetime.fromtimestamp(quando).strftime(
                    "%d/%m/%Y %H:%M"
                ),
            })
        itens.sort(key=lambda item: item["criado_wall"], reverse=True)
        return itens

    def snapshot(self) -> dict[str, Any]:
        """Estado + config + arquivos — base do /dashboard/stats e do painel."""
        estado = self.carregar_estado()
        agora = self._clock()
        agendado = proxima_janela(
            float(estado.get("ultimo_sucesso") or 0.0) or None,
            cadencia_dias=self.cfg.cadencia_dias, hora=self.cfg.hora,
            agora_wall=agora,
        )
        ultimo = float(estado.get("ultimo_sucesso") or 0.0)
        return {
            "nome": self.cfg.nome,
            "rotulo": self.cfg.rotulo,
            "config": self.cfg.para_dict(),
            "ultimo_sucesso": round(ultimo, 3) if ultimo else 0.0,
            "ultimo_sucesso_em": (
                datetime.fromtimestamp(ultimo).strftime("%d/%m/%Y %H:%M")
                if ultimo else ""
            ),
            "ultimo_arquivo": estado.get("ultimo_arquivo", ""),
            "ultimo_bytes": int(estado.get("ultimo_bytes") or 0),
            "ultimo_sha256": estado.get("ultimo_sha256", ""),
            "rodadas": int(estado.get("rodadas") or 0),
            "falhas": int(estado.get("falhas") or 0),
            "ultimo_erro": estado.get("ultimo_erro", ""),
            "pendente_hoje": bool(agora >= agendado and ultimo < agendado),
            "arquivos": self.lista(),
        }

    # -- Saúde ---------------------------------------------------------------

    def check_saude(self) -> dict[str, Any]:
        """Check não-crítico do /health: o snapshot DESTA janela saiu?"""
        agora = self._clock()
        estado = self.carregar_estado()
        ultimo = float(estado.get("ultimo_sucesso") or 0.0)
        agendado = proxima_janela(
            ultimo or None, cadencia_dias=self.cfg.cadencia_dias,
            hora=self.cfg.hora, agora_wall=agora,
        )
        arquivo = str(estado.get("ultimo_arquivo") or "")
        if ultimo and agora < agendado:
            horas = (agora - ultimo) / 3600.0
            tamanho = int(estado.get("ultimo_bytes") or 0) / 1024 ** 2
            janela = "de hoje" if self.cfg.cadencia_dias <= 1 else "da semana"
            return {
                "ok": True,
                "status": "up",
                "detail": (
                    f"{self.cfg.rotulo} ok {janela} ({arquivo}, "
                    f"{tamanho:.2f} MB, há {horas:.1f} h)."
                ),
            }
        if agora < agendado:
            faltam = (agendado - agora) / 60.0
            return {
                "ok": True,
                "status": "up",
                "detail": (
                    f"{self.cfg.rotulo} agendado para {self.cfg.hora} "
                    f"(em {faltam:.0f} min)."
                ),
            }
        erro = str(estado.get("ultimo_erro") or "")
        sufixo = f" — último erro: {erro}" if erro else ""
        return {
            "ok": False,
            "status": "degraded",
            "detail": (
                f"{self.cfg.rotulo} PENDENTE (agendado {self.cfg.hora}, "
                f"falhas={int(estado.get('falhas') or 0)}){sufixo}"
            ),
        }

    def registrar_no_health(self, health: Any) -> Optional[str]:
        """Registra o check deste perfil (não-crítico) no HealthMonitor."""
        if health is None:
            return None
        health.register(self.cfg.check_nome,
                        lambda _monitor: self.check_saude(),
                        critical=False)
        return self.cfg.check_nome

    # -- Ciclo ---------------------------------------------------------------

    def avaliar(self) -> DecisaoBackup:
        """Decisão do tick (com leitura real de disco)."""
        return avaliar(
            self.cfg,
            self.carregar_estado(),
            agora_wall=self._clock(),
            espaco_livre=self._espaco_livre_fn(self.cfg.raiz),
        )

    def tick(self, *, forcar: bool = False) -> ResultadoBackup:
        """Um ciclo: avalia e, se for hora (ou `forcar`), executa."""
        with self._lock:
            decisao = self.avaliar()
            if not forcar and decisao.acao != RODAR:
                log.debug("Backup: nada a fazer",
                          motivo=decisao.motivo)
                return ResultadoBackup(
                    acao=decisao.acao, motivo=decisao.motivo
                )
            return self._executar(
                motivo="manual" if forcar else decisao.motivo
            )

    def rodar_agora(self) -> ResultadoBackup:
        """Snapshot fora da agenda (botão do painel / operação do dono)."""
        return self.tick(forcar=True)

    def _executar(self, *, motivo: str) -> ResultadoBackup:
        inicio = self._clock()
        estado = self.carregar_estado()
        try:
            raiz = self.cfg.raiz
            raiz.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(raiz, 0o700)
            except OSError:  # pragma: no cover — FS sem permissão
                pass
            plano = plano_de_conteudo(
                self.repo_root,
                fontes=self.cfg.fontes,
                excluidos=self.cfg.excluidos,
            )
            quando = self._clock()
            nome = nome_snapshot(quando, self.cfg.prefixo)
            destino = raiz / nome
            tmp = raiz / f"{nome}{SUFIXO_TMP}"
            self._empacotar(plano, tmp)
            try:
                os.chmod(tmp, 0o600)
            except OSError:  # pragma: no cover — FS sem permissão
                pass
            sha = self._sha256(tmp)
            tamanho = tmp.stat().st_size
            os.replace(tmp, destino)

            estado.update({
                "ultimo_sucesso": quando,
                "ultimo_arquivo": nome,
                "ultimo_bytes": int(tamanho),
                "ultimo_sha256": sha,
                "membros": len(plano),
                "rodadas": int(estado.get("rodadas") or 0) + 1,
                "falhas": 0,
                "ultimo_erro": "",
            })
            removidos = self._aplicar_retencao()
            self.gravar_estado(estado)
            duracao = self._clock() - inicio
            log.info(
                "Backup concluído",
                perfil=self.cfg.nome,
                arquivo=nome,
                membros=len(plano),
                bytes=int(tamanho),
                sha256=sha[:12],
                removidos=len(removidos),
                duracao_s=round(duracao, 2),
            )
            return ResultadoBackup(
                acao=RODAR, motivo=motivo, executado=True, arquivo=nome,
                membros=len(plano), bytes=int(tamanho), sha256=sha,
                removidos=removidos, duracao_s=duracao,
            )
        except Exception as exc:
            duracao = self._clock() - inicio
            erro = _curto(f"{type(exc).__name__}: {exc}")
            estado.update({
                "falhas": int(estado.get("falhas") or 0) + 1,
                "ultima_falha": self._clock(),
                "ultimo_erro": erro,
            })
            self.gravar_estado(estado)
            log.error("Backup falhou", perfil=self.cfg.nome, motivo=motivo,
                      error=erro)
            self._alertar_falha(estado, erro)
            return ResultadoBackup(
                acao=RODAR, motivo=motivo, executado=True, erro=erro,
                duracao_s=duracao,
            )

    def _empacotar(
        self, plano: list[tuple[Path, str]], destino_tmp: Path
    ) -> None:
        """Escreve o tar.gz determinístico (gzip mtime 0, dono raiz)."""
        with open(destino_tmp, "wb") as bruto:
            # filename="" tira o FNAME do cabeçalho gzip (senão o nome do
            # arquivo — que carrega a hora — entraria no hash e o mesmo
            # conteúdo geraria sha diferente a cada rodada).
            with gzip.GzipFile(fileobj=bruto, mode="wb", mtime=0,
                               filename="") as gz:
                with tarfile.open(fileobj=gz, mode="w",
                                  format=tarfile.GNU_FORMAT) as tar:
                    for caminho, nome in plano:
                        info = tar.gettarinfo(str(caminho), arcname=nome)
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        with open(caminho, "rb") as origem:
                            tar.addfile(info, origem)

    @staticmethod
    def _sha256(caminho: Path) -> str:
        hasher = hashlib.sha256()
        with open(caminho, "rb") as fh:
            for bloco in iter(lambda: fh.read(1024 * 1024), b""):
                hasher.update(bloco)
        return hasher.hexdigest()

    def _aplicar_retencao(self) -> list[str]:
        """Apaga o que passa da retenção (e temporários órfãos)."""
        raiz = self.cfg.raiz
        if not raiz.exists():  # pragma: no cover — acabou de ser criada
            return []
        nomes = [
            caminho.name
            for caminho in raiz.iterdir()
            if caminho.is_file() and not caminho.name.endswith(SUFIXO_TMP)
        ]
        retencao = calcular_retencao(
            nomes, diarios=self.cfg.diarios, semanais=self.cfg.semanais,
            prefixo=self.cfg.prefixo,
        )
        removidos: list[str] = []
        for nome in retencao.remover:
            try:
                (raiz / nome).unlink()
                removidos.append(nome)
            except OSError as exc:  # pragma: no cover — permissão
                log.warn("Snapshot não removido", arquivo=nome,
                         error=_curto(exc))
        for caminho in raiz.iterdir():
            if caminho.is_file() and caminho.name.endswith(SUFIXO_TMP):
                try:
                    caminho.unlink()
                except OSError:  # pragma: no cover — permissão
                    pass
        if removidos:
            log.info("Retenção aplicada", perfil=self.cfg.nome,
                     removidos=len(removidos), diarios=self.cfg.diarios,
                     semanais=self.cfg.semanais)
        return removidos

    def _alertar_falha(self, estado: dict[str, Any], erro: str) -> None:
        """Avisa o dono no celular — no máximo 1 push a cada 6 h.

        Best-effort (mesma linha do notifier/auto-update): o ciclo nunca
        morre por causa de um aviso. Backup que falha em silêncio é o
        pior modo de falha deste item — por isso falha grita e sucesso
        não (o dono vê o sucesso no painel e no /health).
        """
        if self._push is None:
            return
        agora = self._clock()
        ultimo = float(estado.get("ultimo_alerta_falha") or 0.0)
        if ultimo and (agora - ultimo) < ALERTA_FALHA_COOLDOWN_S:
            log.info("Aviso de falha do backup em espera (cooldown)",
                     faltam_s=round(ALERTA_FALHA_COOLDOWN_S - (agora - ultimo)))
            return
        estado["ultimo_alerta_falha"] = agora
        self.gravar_estado(estado)
        try:
            self._push.notify(
                f"{self.cfg.rotulo} falhou",
                f"O snapshot não foi criado: {erro}",
                data={"origem": f"backup-{self.cfg.nome}"},
            )
        except Exception as exc:  # pragma: no cover — push degrada sozinho
            log.warn("Backup: aviso de push falhou", error=_curto(exc))


def build_services(
    *,
    repo_root: Path,
    env: Optional[Callable[[str, str], str]] = None,
    push: Any = None,
    clock: Callable[[], float] = time.time,
    espaco_livre_fn: Optional[Callable[[Path], Optional[int]]] = None,
    perfis: tuple[str, ...] = ("estado", "capturas"),
) -> list[BackupService]:
    """Monta os serviços ligados no env — [] quando todos desligados.

    Ponto ÚNICO de construção (launcher e teste usam o mesmo caminho):
    perfil `estado` (diário, `OD_BACKUP=0` desliga) e perfil `capturas`
    (semanal, `OD_BACKUP_CAPTURAS=0` desliga). Um perfil desligado não
    ganha loop, nem check no /health, nem bloco no /dashboard/stats.
    """
    leitor = env or (lambda _nome, padrao: padrao)
    servicos: list[BackupService] = []
    for perfil in perfis:
        config = ConfigBackup.de_env(leitor, perfil)
        if not config.habilitado:
            continue
        servicos.append(BackupService(
            cfg=config, repo_root=repo_root, push=push, clock=clock,
            espaco_livre_fn=espaco_livre_fn,
        ))
    return servicos
