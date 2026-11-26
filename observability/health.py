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
  - Check de container/broker que ainda está subindo nos primeiros minutos
    do boot não é falha (2026-11-26): vira `status="starting"` com
    `transitorio: true` e NÃO derruba o agregado — o boot de 26/11 mostrou
    `mqtt`/`tool_*` em `degraded` aos 22 s de uptime com os containers ainda
    começando (gêmeo do que `tools/validar_pos_reboot.py` faz no veredito).
    A janela é LIGADA pelo launcher; o padrão do monitor é desligada para
    nenhum teste depender do uptime da máquina.
  - Zerar dependências externas: stdlib puro
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.observability.health")

STATUS_UP = "up"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"
STATUS_STARTING = "starting"

# Checks que dependem de container/broker e por isso sobem DEPOIS do od-core
# (mesma régua de `tools/validar_pos_reboot.py`, duplicada de propósito: a
# ferramenta de boot roda só com stdlib).
CHECKS_TRANSITORIOS = frozenset({"mqtt"})
PREFIXO_TRANSITORIO = "tool_"
# Janela padrão usada pelo launcher: 5 min depois do boot.
JANELA_BOOT_PADRAO_S = 300.0


def eh_check_transitorio(nome: str) -> bool:
    """Check de container/broker (pode estar apenas começando no boot)."""
    return nome in CHECKS_TRANSITORIOS or nome.startswith(PREFIXO_TRANSITORIO)


def segundos_desde_boot() -> Optional[float]:
    """Uptime em segundos, ou None quando não dá para medir (nunca levanta)."""
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


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
        boot_window_s: float = 0.0,
        boot_age: Optional[Callable[[], Optional[float]]] = None,
    ) -> None:
        self._clock = clock or time.monotonic
        # 0 = desligado (padrão: nenhum teste depende do uptime da máquina).
        self._boot_window_s = float(boot_window_s)
        self._boot_age = boot_age or segundos_desde_boot
        self._checks: dict[str, tuple[HealthCheckFn, bool]] = {}
        self._metrics = HealthMetrics()
        self._last: Optional[dict[str, Any]] = None
        self._lock = threading.RLock()

    @property
    def metrics(self) -> HealthMetrics:
        return self._metrics

    @property
    def boot_window_s(self) -> float:
        """Janela de carência de container/broker após o boot (0 = desligada)."""
        return self._boot_window_s

    def na_janela_de_boot(self) -> bool:
        """True quando ainda é cedo o bastante para container estar subindo."""
        if self._boot_window_s <= 0:
            return False
        try:
            idade = self._boot_age()
        except Exception:  # sonda de uptime quebrada nunca muda o agregado
            return False
        return idade is not None and idade < self._boot_window_s

    def em_transitorio(self, nome: str) -> bool:
        """Check de container/broker falhando dentro da janela de boot."""
        return eh_check_transitorio(nome) and self.na_janela_de_boot()

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
        transitorios: list[str] = []
        degraded = False
        down = False
        for name, (check_fn, critical) in checks:
            result = await self._run_one(name, check_fn, critical)
            item = result.to_dict()
            results[name] = item
            if result.ok:
                continue
            if self.em_transitorio(name):
                # Container/broker ainda subindo: registra a verdade, mas não
                # pinta o /health de vermelho por isso.
                item["status"] = STATUS_STARTING
                item["transitorio"] = True
                item["detail"] = (
                    (result.detail + "; " if result.detail else "")
                    + "transitório: container/broker subindo após o boot"
                )
                transitorios.append(name)
                continue
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
            "transitorios": transitorios,
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
        # A severidade registrada (critical/não-crítico) é carimbada no
        # resultado: checks que devolvem dict não carregam o flag e o
        # ComponentHealth default seria critical=True (v1.0.0 item 1.4).
        result.critical = critical
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