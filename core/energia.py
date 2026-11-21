"""
OMEGA DRAKON • CORE
Módulo: core/energia.py
Descrição: vigia de queda de energia por INFERÊNCIA — sem USB, sem nobreak
           monitorável. A ideia nasceu do no-break Intelbras Attiv 1500 VA
           do dono: ele segura a Nicky por alguns minutos, mas não tem porta
           de dados (nem USB, nem serial), então não existe ``upsc`` para
           ler. O que existe de verdade é a rede da casa: quando a energia
           cai, os aparelhos ligados na tomada somem do ARP ao mesmo tempo,
           enquanto a Nicky (no no-break) continua viva e vendo o sumiço.

           O vigia observa o ARP a cada ``intervalo_s``, mantém um conjunto
           de âncoras (quem estava presente enquanto havia energia) e
           classifica o estado em normal → suspeita → confirmada →
           desligando. Antes de desligar, avisa no Telegram e dá uma carência
           para o dono cancelar (``energia_cancelar``).

           Limite declarado: isto infere a queda, não mede a bateria. Um
           reinício do roteador produz o mesmo sumiço; por isso há confirmação
           de vários ciclos + carência, e o aviso sai antes de qualquer
           desligamento.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - /proc/net/arp e /proc/net/route (Linux, sem dependência nova)
  - pkcheck (org.freedesktop.login1.power-off) para saber se o desligamento
    é permitido SEM prompt — o serviço roda como usuário comum
  - runtime/systemd/od-energia-polkit.rules (regra opcional, instalada pelo
    dono com sudo)
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.core.energia")

ARQUIVO_ESTADO = Path("data/energia_estado.json")
ARQUIVO_CANCELAR = Path("data/energia_cancelar.flag")

# Estados possíveis (ordem de gravidade)
NORMAL = "normal"
SUSPEITA = "suspeita"
CONFIRMADA = "confirmada"
DESLIGANDO = "desligando"
ESTADOS = (NORMAL, SUSPEITA, CONFIRMADA, DESLIGANDO)

ACAO_POLKIT = "org.freedesktop.login1.power-off"


def _bool_env(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None or valor == "":
        return padrao
    return valor.strip().lower() not in ("0", "false", "nao", "não", "off")


def _float_env(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, "") or padrao)
    except ValueError:
        return padrao


@dataclass
class ConfigEnergia:
    """Régua do vigia (tudo ajustável por ambiente, sem tocar no código)."""

    intervalo_s: float = 20.0
    min_ancoras: int = 3            # com menos que isso não dá para julgar
    quorum: float = 0.6             # fração de âncoras que precisa sumir
    ciclos_suspeita: int = 3        # ~1 min de sumiço seguido
    segundos_confirmar: float = 180.0
    carencia_s: float = 480.0       # tempo para cancelar antes de desligar
    esquecer_s: float = 1800.0      # âncora não vista há 30 min sai da conta
    desligar: bool = True
    comando: str = "systemctl poweroff"

    @classmethod
    def do_ambiente(cls) -> "ConfigEnergia":
        return cls(
            intervalo_s=max(5.0, _float_env("OD_ENERGIA_INTERVALO_S", 20.0)),
            min_ancoras=max(1, int(_float_env("OD_ENERGIA_MIN_ANCORAS", 3))),
            quorum=min(1.0, max(0.1, _float_env("OD_ENERGIA_QUORUM", 0.6))),
            ciclos_suspeita=max(1, int(_float_env("OD_ENERGIA_CICLOS_SUSPEITA", 3))),
            segundos_confirmar=max(0.0, _float_env("OD_ENERGIA_CONFIRMAR_S", 180.0)),
            carencia_s=max(0.0, _float_env("OD_ENERGIA_CARENCIA_S", 480.0)),
            esquecer_s=max(60.0, _float_env("OD_ENERGIA_ESQUECER_S", 1800.0)),
            desligar=_bool_env("OD_ENERGIA_DESLIGAR", True),
            comando=os.getenv("OD_ENERGIA_COMANDO", "systemctl poweroff"),
        )


@dataclass
class Sinais:
    """Uma leitura do mundo: quem está na rede e se o gateway foi visto."""

    ancoras: set[str] = field(default_factory=set)
    visiveis: set[str] = field(default_factory=set)
    gateway_visto: bool = False

    @property
    def faltando(self) -> set[str]:
        return set(self.ancoras) - set(self.visiveis)

    @property
    def razao_faltando(self) -> float:
        if not self.ancoras:
            return 0.0
        return len(self.faltando) / len(self.ancoras)


class Detector:
    """Máquina de estados pura (sem IO) — testável com relógio injetado."""

    def __init__(self, cfg: ConfigEnergia, agora: Optional[Callable[[], float]] = None) -> None:
        self.cfg = cfg
        self._agora = agora or time.monotonic
        self.estado = NORMAL
        self.desde = self._agora()
        self._sumicos = 0
        self.cancelado = False
        self.motivo_cancelamento = ""

    def cancelar(self, motivo: str = "cancelado pelo dono") -> bool:
        """Aborta o episódio; o vigia só volta a julgar depois de normalizar."""
        if self.estado == NORMAL:
            return False
        self.estado = NORMAL
        self.desde = self._agora()
        self._sumicos = 0
        self.cancelado = True
        self.motivo_cancelamento = motivo
        log.warn("Vigia de energia cancelado", motivo=motivo)
        return True

    def avaliar(self, sinais: Sinais) -> str:
        """Aplica um ciclo e devolve o estado resultante."""
        agora = self._agora()
        julga = len(sinais.ancoras) >= self.cfg.min_ancoras
        sumiu = julga and sinais.razao_faltando >= self.cfg.quorum

        if self.estado == NORMAL:
            if sumiu:
                self._sumicos += 1
                if self._sumicos >= self.cfg.ciclos_suspeita:
                    self._mudar(SUSPEITA, agora)
            else:
                self._sumicos = 0
                self.cancelado = False
                return self.estado
        elif self.estado in (SUSPEITA, CONFIRMADA):
            if not sumiu:
                self._mudar(NORMAL, agora)
                return self.estado
            alvo = self.cfg.segundos_confirmar if self.estado == SUSPEITA else self.cfg.carencia_s
            if agora - self.desde >= alvo:
                self._mudar(CONFIRMADA if self.estado == SUSPEITA else DESLIGANDO, agora)
        return self.estado

    def _mudar(self, novo: str, agora: float) -> None:
        antigo = self.estado
        self.estado = novo
        self.desde = agora
        self._sumicos = 0 if novo == NORMAL else self._sumicos
        log.warn("Vigia de energia mudou de estado", de=antigo, para=novo)


# ---------------------------------------------------------------------------
# Leitura do mundo (Linux, sem dependência nova)
# ---------------------------------------------------------------------------

def ler_arp(caminho: str = "/proc/net/arp") -> set[str]:
    """IPs com MAC resolvido e flags válidas (0x2) — presença real na LAN."""
    presentes: set[str] = set()
    try:
        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            linhas = f.read().splitlines()[1:]
    except OSError:
        return presentes
    for linha in linhas:
        partes = linha.split()
        if len(partes) < 4:
            continue
        ip, _tipo, flags, mac = partes[0], partes[1], partes[2], partes[3]
        if mac == "00:00:00:00:00:00":
            continue
        try:
            if int(flags, 16) & 0x2:
                presentes.add(ip)
        except ValueError:
            continue
    return presentes


def ler_gateway(caminho: str = "/proc/net/route") -> str:
    """IP do gateway padrão (Destination 00000000) ou '' se não houver."""
    try:
        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            linhas = f.read().splitlines()[1:]
    except OSError:
        return ""
    for linha in linhas:
        partes = linha.split()
        if len(partes) < 3 or partes[1] != "00000000":
            continue
        try:
            numero = int(partes[2], 16)
        except ValueError:
            continue
        return ".".join(str((numero >> (8 * i)) & 0xFF) for i in range(4))
    return ""


def desligamento_autorizado(acao: str = ACAO_POLKIT) -> dict[str, Any]:
    """O serviço pode desligar SEM prompt? (pkcheck com o próprio PID)."""
    exe = shutil.which("pkcheck")
    if not exe:
        return {"autorizado": False, "motivo": "pkcheck ausente"}
    try:
        r = subprocess.run(
            [exe, "--action-id", acao, "--process", str(os.getpid())],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"autorizado": False, "motivo": f"pkcheck falhou: {exc}"}
    if r.returncode == 0:
        return {"autorizado": True, "motivo": ""}
    motivo = (r.stderr or r.stdout or "").strip()[:200]
    return {"autorizado": False, "motivo": motivo or f"pkcheck rc={r.returncode}"}


# ---------------------------------------------------------------------------
# Vigia (IO + estado persistido)
# ---------------------------------------------------------------------------

class VigiaEnergia:
    """Loop do vigia: lê ARP, mantém âncoras, avisa e desliga."""

    def __init__(
        self,
        cfg: Optional[ConfigEnergia] = None,
        *,
        agora: Optional[Callable[[], float]] = None,
        ler_presentes: Callable[[], set[str]] = ler_arp,
        ler_gateway_fn: Callable[[], str] = ler_gateway,
        sink: Optional[Callable[[str], Any]] = None,
        desligar_fn: Optional[Callable[[], Any]] = None,
        autorizado_fn: Optional[Callable[[], dict[str, Any]]] = None,
        arquivo_estado: Path = ARQUIVO_ESTADO,
        arquivo_cancelar: Path = ARQUIVO_CANCELAR,
    ) -> None:
        self.cfg = cfg or ConfigEnergia.do_ambiente()
        self.detector = Detector(self.cfg, agora=agora)
        self._ler_presentes = ler_presentes
        self._ler_gateway = ler_gateway_fn
        self._sink = sink
        self._desligar = desligar_fn or self._desligar_padrao
        self._autorizado_fn = autorizado_fn or desligamento_autorizado
        self.arquivo_estado = arquivo_estado
        self.arquivo_cancelar = arquivo_cancelar
        self.ancoras: set[str] = set()
        self._vistos: dict[str, float] = {}
        self.gateway = ""
        self.ultima_leitura: dict[str, Any] = {}
        self._desligou = False
        self._autorizacao: Optional[dict[str, Any]] = None
        self._avisos: set[str] = set()

    # -- utilidades -------------------------------------------------------

    def autorizacao(self) -> dict[str, Any]:
        if self._autorizacao is None:
            self._autorizacao = self._autorizado_fn()
        return self._autorizacao

    def _notificar(self, texto: str) -> None:
        if self._sink is None:
            return
        try:
            resultado = self._sink(texto)
            if hasattr(resultado, "__await__"):
                # sink assíncrono: agenda no loop quando houver um rodando
                import asyncio

                try:
                    asyncio.get_running_loop().create_task(resultado)  # type: ignore[arg-type]
                except RuntimeError:
                    asyncio.run(resultado)  # type: ignore[arg-type]
        except Exception as exc:  # aviso nunca derruba o vigia
            log.error("Falha ao avisar sobre energia", error=str(exc))

    def _cancelado_por_arquivo(self) -> bool:
        try:
            if self.arquivo_cancelar.exists():
                self.arquivo_cancelar.unlink()
                return True
        except OSError:
            return False
        return False

    def _desligar_padrao(self) -> Any:
        comando = shlex.split(self.cfg.comando)
        log.warn("Desligando por falta de energia", comando=self.cfg.comando)
        return subprocess.run(comando, capture_output=True, text=True, timeout=60)

    # -- ciclo ------------------------------------------------------------

    def tick(self) -> dict[str, Any]:
        presentes = set(self._ler_presentes())
        self.gateway = self._ler_gateway() or self.gateway
        gateway_visto = bool(self.gateway) and self.gateway in presentes

        if self._cancelado_por_arquivo():
            self.detector.cancelar("pedido pelo dono (arquivo)")

        agora = self.detector._agora()
        for ip in presentes:
            self._vistos[ip] = agora
        if gateway_visto and self.gateway:
            self._vistos[self.gateway] = agora
        # Âncora que não aparece há `esquecer_s` sai da conta: celular que
        # saiu de casa não pode virar "aparelho sumido" para sempre.
        limite = agora - self.cfg.esquecer_s
        self._vistos = {ip: t for ip, t in self._vistos.items() if t >= limite}
        self.ancoras = set(self._vistos)

        estado_antes = self.detector.estado
        sinais = Sinais(ancoras=set(self.ancoras), visiveis=presentes, gateway_visto=gateway_visto)
        estado = self.detector.avaliar(sinais)

        if estado != estado_antes:
            self._avisar_transicao(estado, sinais)
        if estado == DESLIGANDO and not self._desligou:
            self._desligou = True
            self._executar_desligamento()

        self.ultima_leitura = {
            "estado": estado,
            "desde": _iso(self.detector.desde, self.detector),
            "ancoras": len(self.ancoras),
            "presentes": len(presentes),
            "faltando": sorted(sinais.faltando),
            "gateway": self.gateway,
            "gateway_visto": gateway_visto,
            "cancelado": self.detector.cancelado,
            "autorizado": self.autorizacao(),
            "desligar": self.cfg.desligar,
            "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._persistir()
        return self.ultima_leitura

    def _executar_desligamento(self) -> None:
        if not self.cfg.desligar:
            self._notificar(
                "🔌 Queda de energia confirmada. O desligamento automático está "
                "DESARMADO (OD_ENERGIA_DESLIGAR=0) — a Nicky vai rodar até a "
                "bateria acabar."
            )
            return
        autorizacao = self.autorizacao()
        if not autorizacao.get("autorizado"):
            self._notificar(
                "⚠️ Queda de energia confirmada, mas NÃO consigo desligar: falta "
                "permissão (polkit). Rode uma vez, com sudo, "
                "`bash runtime/setup/energia_polkit.sh` — ou desligue à mão.\n"
                f"Detalhe: {autorizacao.get('motivo', 'sem permissão')}"
            )
            log.error("Desligamento negado pelo polkit",
                      motivo=autorizacao.get("motivo", ""))
            return
        self._notificar("🔴 Queda de energia confirmada. Desligando a Nicky agora, de forma graciosa.")
        try:
            self._desligar()
        except Exception as exc:
            log.error("Falha ao desligar", error=str(exc))
            self._notificar(f"⚠️ Falha ao desligar: {exc}")

    def _avisar_transicao(self, estado: str, sinais: Sinais) -> None:
        faltando = len(sinais.faltando)
        total = len(sinais.ancoras)
        if estado == SUSPEITA:
            self._notificar(
                f"⚠️ Possível queda de energia: {faltando} de {total} aparelhos "
                "sumiram da rede. Confirmo em alguns minutos."
            )
        elif estado == CONFIRMADA:
            minutos = int(round(self.cfg.carencia_s / 60))
            self._notificar(
                "🔋 Queda de energia CONFIRMADA — estou no no-break. "
                f"Desligo em ~{minutos} min se nada voltar.\n"
                "Para cancelar: /executa energia_cancelar"
            )
        elif estado == NORMAL:
            if self.detector.cancelado:
                self.detector.cancelado = False
                self._notificar("✅ Energia de volta — desligamento cancelado.")
            else:
                self._notificar("✅ Energia de volta — aparelhos reapareceram na rede.")
        elif estado == DESLIGANDO:
            log.warn("Vigia de energia: entrando em desligamento", faltando=faltando)

    def cancelar(self, motivo: str = "cancelado pelo dono") -> bool:
        feito = self.detector.cancelar(motivo)
        if feito:
            self._desligou = False
            self._notificar(f"🛑 Desligamento por energia cancelado ({motivo}).")
            self._persistir()
        return feito

    def _persistir(self) -> None:
        try:
            self.arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo_estado.write_text(
                json.dumps(self.ultima_leitura, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warn("Não consegui gravar o estado da energia", error=str(exc))


def _iso(instante: float, detector: Detector) -> str:
    """Converte o relógio monotônico em idade legível (sem inventar data)."""
    idade = max(0.0, detector._agora() - instante)
    return f"há {int(idade)}s"


# ---------------------------------------------------------------------------
# Fábrica + estado compartilhado com actions/health (mesmo processo)
# ---------------------------------------------------------------------------

_VIGIA: Optional[VigiaEnergia] = None


def configurar(vigia: VigiaEnergia) -> None:
    global _VIGIA
    _VIGIA = vigia


def vigia() -> Optional[VigiaEnergia]:
    return _VIGIA


def estado_atual() -> dict[str, Any]:
    """Snapshot para health/actions: do vigia vivo ou do arquivo."""
    if _VIGIA is not None and _VIGIA.ultima_leitura:
        return dict(_VIGIA.ultima_leitura)
    try:
        return json.loads(ARQUIVO_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "estado": NORMAL, "ancoras": 0, "presentes": 0, "faltando": [],
            "autorizado": {"autorizado": False, "motivo": "vigia ainda não rodou"},
            "desligar": True, "atualizado_em": "",
        }


def cancelar(motivo: str = "cancelado pelo dono") -> bool:
    """Cancela pelo vigia vivo; sem vigia, deixa o pedido no arquivo."""
    if _VIGIA is not None:
        return _VIGIA.cancelar(motivo)
    try:
        ARQUIVO_CANCELAR.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO_CANCELAR.write_text(motivo, encoding="utf-8")
        return True
    except OSError:
        return False
