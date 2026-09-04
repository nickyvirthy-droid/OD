"""
OMEGA DRAKON • OBSERVABILITY
Tecnologia que respira.
Módulo: observability/health.py
Descrição: Health Check (Fase 7, item 7.3) — verificação de status dos
           componentes do OmegaDrakon: checks registráveis por componente
           (sync ou async), severidade por check (crítico -> down,
           não-crítico -> degraded), latência por check, agregação com
           status geral (up/degraded/down), métricas, snapshot()/dump() e
           integração com o /health da API REST (APIConfig.health).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime observability/health/ (health checks)
  - Nicky /health (health check + LLMs disponíveis — NICKY_LEGACY_ANALYSIS §9)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.3

Decisões registradas (ver CHANGELOG):
  - HealthMonitor genérico com checks plugáveis (mesma linha do
    ProactiveNotifier): cada componente expõe um check; o monitor agrega
    e não conhece os componentes
  - Status em 3 níveis: up / degraded / down — check marcado como crítico
    que falha derruba o status geral para down; não-crítico degrada
  - Check quebrado (exceção) conta como falha do componente, nunca derruba
    o monitor (resiliência — padrão do projeto)
  - A API REST passa a responder o agregado do monitor quando recebe
    config.health; sem monitor, mantém o comportamento legado
  - Zerar dependências externas: stdlib puro
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.observability.health")

STATUS_UP = "up"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"


@dataclass(slots=True)
class ComponentHealth:
    """Resultado do health check de um componente.

    Attributes:
        name:       Nome estável do componente (ex: "orchestrator").
        ok:         True quando o componente está saudável.
        status:     up/degraded/down.
        detail:     Texto legível do estado.
        latency_ms: Latência do check em milissegundos.
        critical:   Se True, falha derruba o status geral para down.
    """

    name: str
    ok: bool
    status: str = STATUS_UP
    detail: str = ""
    latency_ms: float = 0.0
    critical: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 3),
            "critical": self.critical,
        }


@dataclass(slots=True)
class HealthMetrics:
    """Métricas acumuladas do HealthMonitor."""

    runs: int = 0
    checks_run: int = 0
    ok_checks: int = 0
    failed_checks: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        avg = (
            self.total_latency_ms / self.checks_run
            if self.checks_run
            else 0.0
        )
        return {
            "runs": self.runs,
            "checks_run": self.checks_run,
            "ok_checks": self.ok_checks,
            "failed_checks": self.failed_checks,
            "errors": self.errors,
            "avg_latency_ms": round(avg, 3),
        }


# Contrato de check: sync ou async, devolve dict (ok/status/detail) ou
# ComponentHealth. Recebe o HealthMonitor (padrão ProactiveNotifier).
HealthCheckFn = Callable[["HealthMonitor"], Union[dict[str, Any], ComponentHealth, Awaitable[Any]]]


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """Verificação de status dos componentes (Fase 7, item 7.3).

    Uso típico:
        monitor = HealthMonitor()
        monitor.register("orchestrator", check_orchestrator, critical=True)
        result = monitor.health()  # dict agregado (ok/status/checks)
    """

    def __init__(
        self,
        *,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._checks: dict[str, tuple[HealthCheckFn, bool]] = {}
        self._metrics = HealthMetrics()
        self._last: Optional[dict[str, Any]] = None
        self._lock = threading.RLock()

    @property
    def metrics(self) -> HealthMetrics:
        return self._metrics

    # -- Registro -------------------------------------------------------------

    def register(
        self,
        name: str,
        check: HealthCheckFn,
        *,
        critical: bool = True,
    ) -> None:
        """Registra (ou substitui) o check de um componente."""
        with self._lock:
            self._checks[name] = (check, critical)

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._checks.pop(name, None) is not None

    @property
    def components(self) -> list[str]:
        with self._lock:
            return list(self._checks)

    # -- Execução -------------------------------------------------------------

    async def check(self, name: str) -> Optional[ComponentHealth]:
        """Roda o check de um componente específico."""
        with self._lock:
            entry = self._checks.get(name)
        if entry is None:
            return None
        check_fn, critical = entry
        return await self._run_one(name, check_fn, critical)

    async def health(self) -> dict[str, Any]:
        """Roda todos os checks e agrega (up/degraded/down)."""
        with self._lock:
            checks = list(self._checks.items())
            self._metrics.runs += 1
        results: dict[str, Any] = {}
        degraded = False
        down = False
        for name, (check_fn, critical) in checks:
            result = await self._run_one(name, check_fn, critical)
            results[name] = result.to_dict()
            if not result.ok:
                if critical:
                    down = True
                else:
                    degraded = True
        if down:
            status = STATUS_DOWN
        elif degraded:
            status = STATUS_DEGRADED
        else:
            status = STATUS_UP
        aggregate = {
            "ok": status == STATUS_UP,
            "status": status,
            "checks": results,
            "ts": self._clock(),
        }
        with self._lock:
            self._last = aggregate
        return aggregate

    async def _run_one(
        self, name: str, check_fn: HealthCheckFn, critical: bool
    ) -> ComponentHealth:
        started = self._clock()
        try:
            outcome = check_fn(self)
            if isinstance(outcome, Awaitable):
                outcome = await outcome
            if isinstance(outcome, ComponentHealth):
                result = outcome
            else:
                result = ComponentHealth(
                    name=name,
                    ok=bool(outcome.get("ok", True)),
                    status=str(outcome.get("status", STATUS_UP)),
                    detail=str(outcome.get("detail", "")),
                )
        except Exception as exc:  # check quebrado nunca derruba o monitor
            with self._lock:
                self._metrics.errors += 1
                self._metrics.failed_checks += 1
            log.warn(
                "Health check falhou com exceção",
                component=name,
                error=type(exc).__name__,
            )
            result = ComponentHealth(
                name=name,
                ok=False,
                status=STATUS_DOWN,
                detail=f"check quebrado: {type(exc).__name__}",
            )
        latency_ms = (self._clock() - started) * 1000.0
        result.latency_ms = latency_ms
        with self._lock:
            self._metrics.checks_run += 1
            if result.ok:
                self._metrics.ok_checks += 1
            else:
                self._metrics.failed_checks += 1
            self._metrics.total_latency_ms += latency_ms
        level = STATUS_UP if result.ok else (
            STATUS_DOWN if critical else STATUS_DEGRADED
        )
        log.debug(
            "Health check",
            component=name,
            status=level,
            latency_ms=round(latency_ms, 1),
        )
        return result

    # -- Introspecção ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "components": len(self._checks),
                "last_status": (
                    self._last["status"] if self._last else None
                ),
                "metrics": self._metrics.snapshot(),
            }

    def dump(self) -> dict[str, Any]:
        data = self.snapshot()
        data["last"] = self._last
        return data