"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/supervision.py
Descrição: Registro de supervisão dos loops do núcleo. O modo `all` roda
           vários loops no MESMO processo (API, Telegram, recovery, MQTT,
           presença, visão) e, até 2026-09-15, qualquer exceção de qualquer
           um deles subia pelo `asyncio.gather` e derrubava o core inteiro —
           89 restarts silenciosos do od-core em três dias.

           O launcher passou a isolar cada loop em `_supervise()` (contém a
           exceção e reinicia com espera). Este módulo guarda o rastro dessas
           quedas para que elas deixem de ser invisíveis:

             - `HealthMonitor` → check não-crítico "loops" no /health;
             - `ProactiveNotifier` → alerta no Telegram/push (com o anti-spam
               do notifier).

           Queda recente = "degradado"; passada a janela, o loop volta a ok
           sozinho (sem intervenção manual).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - runtime/launcher.py (_supervise)
  - observability/health.py (registro de checks)
  - integrations/notifier.py (sondas de saúde + anti-spam)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

__signature__ = "OD // CORE"

# Janela em que uma queda ainda conta como "degradado" (5 minutos — o mesmo
# tempo que o notifier espera para problemas persistentes de LLM).
DEFAULT_DEGRADED_WINDOW_S = 300.0

# A partir de quantos reinícios o loop é considerado em laço de falha.
CRASH_LOOP_RESTARTS = 3

# Tamanho máximo do detalhe do erro guardado (não inflar estado/log).
_ERROR_DETAIL_LIMIT = 300


@dataclass(slots=True)
class LoopSupervision:
    """Estado de supervisão de um loop do núcleo.

    Attributes:
        name:          Rótulo do loop (api, telegram, recovery, mqtt...).
        failures:      Quantas vezes o loop caiu (ou retornou) desde o boot.
        restarts:      Quantas vezes foi reiniciado pelo supervisor.
        last_drop_ts:  `time.time()` da última queda (0 = nunca caiu).
        last_kind:     Tipo da última falha (ex: "TimeoutError") ou "Returned".
        last_error:    Detalhe da última falha (truncado).
    """

    name: str
    failures: int = 0
    restarts: int = 0
    last_drop_ts: float = 0.0
    last_kind: str = ""
    last_error: str = ""

    def age_s(self, now: Optional[float] = None) -> Optional[float]:
        """Segundos desde a última queda (None quando nunca caiu)."""
        if not self.last_drop_ts:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.last_drop_ts)

    def to_dict(self, now: Optional[float] = None) -> dict[str, Any]:
        age = self.age_s(now)
        return {
            "name": self.name,
            "failures": self.failures,
            "restarts": self.restarts,
            "last_drop_ts": self.last_drop_ts,
            "last_kind": self.last_kind,
            "last_error": self.last_error,
            "age_s": None if age is None else round(age, 3),
        }


class SupervisionRegistry:
    """Registro thread-safe das quedas/restarts dos loops supervisionados.

    Escreve o launcher (thread do asyncio) e leem o Health Monitor (API) e o
    ProactiveNotifier (thread própria) — daí o lock.
    """

    def __init__(
        self,
        *,
        degraded_window_s: float = DEFAULT_DEGRADED_WINDOW_S,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._loops: dict[str, LoopSupervision] = {}
        self.degraded_window_s = degraded_window_s
        self._clock = clock or time.time

    # -- Escrita --------------------------------------------------------------

    def record_drop(
        self,
        name: str,
        *,
        kind: str = "",
        detail: str = "",
    ) -> LoopSupervision:
        """Registra que o loop caiu (exceção) ou retornou sozinho."""
        with self._lock:
            entry = self._entry(name)
            entry.failures += 1
            entry.last_drop_ts = self._clock()
            entry.last_kind = kind or "Unknown"
            entry.last_error = (detail or "")[:_ERROR_DETAIL_LIMIT]
            return entry

    def record_restart(self, name: str) -> int:
        """Registra um reinício do loop; devolve o total acumulado."""
        with self._lock:
            entry = self._entry(name)
            entry.restarts += 1
            return entry.restarts

    def reset(self, name: Optional[str] = None) -> None:
        """Zera o histórico de um loop (ou de todos) — usado nos testes."""
        with self._lock:
            if name is None:
                self._loops.clear()
            else:
                self._loops.pop(name, None)

    # -- Leitura --------------------------------------------------------------

    def get(self, name: str) -> Optional[LoopSupervision]:
        with self._lock:
            return self._loops.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._loops)

    def evaluate(self) -> list[dict[str, Any]]:
        """Estado de cada loop conhecido (degradado x estável).

        `degraded` é True quando a última queda caiu dentro da janela — depois
        disso o loop volta a ok sozinho.
        """
        now = self._clock()
        with self._lock:
            entradas = list(self._loops.values())
        out: list[dict[str, Any]] = []
        for entry in entradas:
            age = entry.age_s(now)
            degraded = age is not None and age <= self.degraded_window_s
            item = entry.to_dict(now)
            item["degraded"] = degraded
            item["crash_loop"] = entry.restarts >= CRASH_LOOP_RESTARTS
            out.append(item)
        return out

    def snapshot(self) -> dict[str, Any]:
        """Visão completa para logs/introspecção (sem julgar degradação)."""
        now = self._clock()
        with self._lock:
            return {
                name: entry.to_dict(now) for name, entry in self._loops.items()
            }

    def health(self) -> dict[str, Any]:
        """Contrato do Health Monitor: ok/status/detail.

        Não-crítico por natureza: um loop reiniciado degrada o /health em vez
        de derrubá-lo (o core continua de pé — é justamente o objetivo da
        supervisão).
        """
        estados = self.evaluate()
        degradados = [e for e in estados if e["degraded"]]
        if not estados:
            return {
                "ok": True,
                "status": "up",
                "detail": "nenhum loop supervisionado registrado",
            }
        if not degradados:
            return {
                "ok": True,
                "status": "up",
                "detail": (
                    f"{len(estados)} loop(s) supervisionado(s), sem quedas "
                    f"nos últimos {int(self.degraded_window_s)}s"
                ),
            }
        detalhes = "; ".join(
            f"{e['name']} {_describe(e)}" for e in degradados
        )
        return {
            "ok": False,
            "status": "degraded",
            "detail": f"loop(s) reiniciado(s): {detalhes}",
        }

    # -- Interno --------------------------------------------------------------

    def _entry(self, name: str) -> LoopSupervision:
        entry = self._loops.get(name)
        if entry is None:
            entry = LoopSupervision(name=name)
            self._loops[name] = entry
        return entry


def _describe(item: dict[str, Any]) -> str:
    """Texto curto de uma queda: tipo, idade e contagem de reinícios."""
    age = item.get("age_s")
    idade = f"há {int(age)}s" if age is not None else "sem carimbo"
    erro = item.get("last_error") or ""
    erro = f" — {erro}" if erro else ""
    return (
        f"({item.get('last_kind') or '?'}, {idade}, "
        f"{item.get('failures')} queda(s)/{item.get('restarts')} reinício(s))"
        f"{erro}"
    )


# Instância única do processo (od-core): o launcher escreve, o health e o
# notifier leem. Testes criam a própria SupervisionRegistry.
SUPERVISION = SupervisionRegistry()


def get_supervision() -> SupervisionRegistry:
    """Registro de supervisão do processo atual."""
    return SUPERVISION
