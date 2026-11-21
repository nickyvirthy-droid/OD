"""
OMEGA DRAKON • CORE
Módulo: core/queda_energia.py
Descrição: Reconhece que a máquina ACABOU de voltar de uma queda de energia.

O journal do boot anterior termina com ``Journal stopped`` quando o
desligamento foi limpo (``shutdown``/``reboot``). Se a última linha não for
esse encerramento, o sistema caiu sem despedida — energia cortada, travamento
ou reset. É o sinal que o alerta de boot usa para não tratar uma queda como
"mais um restart do od-core".

Decisões (21/11/2026):
  - Só vale para boot RECENTE (``LIMITE_ALERTA_S``): o mesmo boot anterior
    continua no journal por dias, e um ``systemctl restart od-core`` dias
    depois não pode ser anunciado como queda de energia.
  - Marca queda quando o desligamento NÃO foi registrado — não quando o
    sistema "sabe" a causa. O texto do alerta diz exatamente isso, em vez de
    afirmar uma causa que o Linux não registra.
  - Falha de leitura (journalctl ausente, permissão, saída estranha) devolve
    ``None``: alerta de boot não pode derrubar o notificador.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from typing import Any, Callable, Optional

__signature__ = "OD // CORE"

# Um boot mais velho que isso não é "acabou de voltar" — evita anunciar
# queda de energia num restart do serviço dias depois do boot.
LIMITE_ALERTA_S = 30 * 60.0

_TIMEOUT_S = 15
_ENCERRAMENTO_LIMPO = "Journal stopped"


def _executar(args: list[str], timeout: float = _TIMEOUT_S) -> Optional[str]:
    """Roda um comando de leitura e devolve stdout (None se falhar)."""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _json(texto: Optional[str]) -> Any:
    if not texto:
        return None
    try:
        return json.loads(texto)
    except (TypeError, json.JSONDecodeError):
        return None


def uptime_s(caminho: str = "/proc/uptime") -> float:
    """Segundos desde o boot da máquina (0.0 se não der para ler)."""
    try:
        with open(caminho, encoding="ascii") as fh:
            return float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def detectar_queda(
    executar: Callable[[list[str]], Optional[str]] = _executar,
    uptime_fn: Callable[[], float] = uptime_s,
    limite_s: float = LIMITE_ALERTA_S,
) -> Optional[dict[str, Any]]:
    """Descreve a queda, se o boot atual acabou de vir de uma.

    Returns:
        ``None`` quando não houve queda (ou não dá para saber); senão
        ``{"fora_s": float, "desligado_em": iso, "voltou_em": iso}``.
    """
    if uptime_fn() > limite_s:
        return None

    boots = _json(executar(["journalctl", "--list-boots", "--no-pager", "-o", "json"]))
    if not isinstance(boots, list) or len(boots) < 2:
        return None
    anterior, atual = boots[-2], boots[-1]
    try:
        inicio_atual = float(atual["first_entry"]) / 1_000_000
        fim_anterior = float(anterior["last_entry"]) / 1_000_000
    except (KeyError, TypeError, ValueError):
        return None

    ultima = _json(
        executar(["journalctl", "-b", "-1", "-n", "1", "-o", "json", "--no-pager"])
    )
    if not isinstance(ultima, dict):
        return None
    if _ENCERRAMENTO_LIMPO in str(ultima.get("MESSAGE", "")):
        return None  # desligamento limpo: shutdown/reboot, não queda

    # Relógio pode andar para trás (RTC sem bateria); não anuncia duração
    # negativa nem "fora por -3 h".
    fora_s = max(0.0, inicio_atual - fim_anterior)
    return {
        "fora_s": fora_s,
        "desligado_em": _iso(fim_anterior),
        "voltou_em": _iso(inicio_atual),
    }


def _iso(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch).astimezone().isoformat(
            timespec="seconds"
        )
    except (OverflowError, OSError, ValueError):
        return ""


def formatar_duracao(segundos: float) -> str:
    """Duração curta em pt-BR: '43 s', '12 min', '2 h 10 min', '3 dias'."""
    if segundos < 60:
        return f"{max(0, int(segundos))} s"
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    resto = minutos % 60
    if horas < 24:
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    dias = horas // 24
    resto_h = horas % 24
    return f"{dias} dia(s) {resto_h} h" if resto_h else f"{dias} dia(s)"


def resumo_queda(info: dict[str, Any]) -> str:
    """Frase do alerta de boot (sem afirmar causa que o journal não diz)."""
    fora = formatar_duracao(float(info.get("fora_s") or 0.0))
    return (
        f"Sistema voltou após queda de energia — ficou fora cerca de {fora}. "
        "O desligamento anterior não foi registrado (energia cortada, "
        "travamento ou reset)."
    )
