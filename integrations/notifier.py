"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/notifier.py
Descrição: ProactiveNotifier (Fase 5, item 5.3) — notificações proativas do
           legado Nicky reimplementadas em stdlib (sem httpx): health check
           periódico, alertas de restart, LLM offline >threshold e disco
           acima do limite, com ANTI-SPAM (cooldown por alerta, padrão 1/h),
           sinks plugáveis (Telegram, log, stdout), Event Bus e estado
           persistido em arquivo (cooldowns e detecção de restart entre
           reinícios).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/notifier.py (ProactiveNotifier)
  - docs/NICKY_LEGACY_ANALYSIS.md §4.3 (health 60s, restart, LLM offline
    >5min, disco >85% 1 alerta/hora, anti-spam)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.3

Decisões registradas (ver CHANGELOG):
  - Canal de envio plugável (sink) em vez de httpx acoplado ao Telegram:
    o ProactiveNotifier não conhece transporte; sinks recebem o texto
    formatado (ex: TelegramBot, log, stdout)
  - 'emit_after_s' por check: problemas persistentes (ex: LLM offline)
    só viram alerta depois de N segundos, como no legado (>5min)
  - Cooldown por chave de alerta (anti-spam): repetição respeita o
    intervalo configurado (padrão 3600s — 1 alerta/hora)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, Union

from core.logger import get_logger
from core.orchestrator import Orchestrator

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.notifier")

SEVERITY_OK = "ok"
SEVERITY_WARN = "warn"
SEVERITY_CRIT = "crit"

SEVERITY_EMOJI = {
    SEVERITY_OK: "🟢",
    SEVERITY_WARN: "🟡",
    SEVERITY_CRIT: "🔴",
}

DEFAULT_COOLDOWN_S = 3600.0  # 1 alerta/hora (anti-spam do legado)
DEFAULT_LLM_OFFLINE_S = 300.0  # 5 minutos
DEFAULT_DISK_THRESHOLD_PERCENT = 85.0
ALERT_TRACE_LIMIT = 100


@dataclass(slots=True)
class CheckResult:
    """Resultado de uma sonda (check) de saúde.

    Attributes:
        ok:          True quando tudo bem (nenhum alerta).
        detail:      Texto legível do estado atual.
        severity:    warn/crit quando `ok` é False.
        source:      Nome estável da sonda (ex: "llm", "disk:/").
        key:         Chave estável do problema (anti-spam). Padrão: source.
        emit_after_s: Tempo mínimo de persistência do problema antes de
                      virar alerta (ex: LLM offline só alerta após 5min).
    """

    ok: bool
    detail: str = ""
    severity: str = SEVERITY_WARN
    source: str = ""
    key: str = ""
    emit_after_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.key:
            self.key = self.source

    def is_problem(self) -> bool:
        return not self.ok


@dataclass(slots=True)
class Alert:
    """Um alerta emitido (depois do anti-spam)."""

    key: str
    severity: str
    title: str
    detail: str = ""
    source: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "source": self.source,
            "ts": self.ts,
        }


@dataclass(slots=True)
class NotifierMetrics:
    """Métricas acumuladas do notificador."""

    ticks: int = 0
    checks_run: int = 0
    problems: int = 0
    alerts_emitted: int = 0
    alerts_blocked: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "ticks": self.ticks,
            "checks_run": self.checks_run,
            "problems": self.problems,
            "alerts_emitted": self.alerts_emitted,
            "alerts_blocked": self.alerts_blocked,
            "errors": self.errors,
        }


@dataclass(slots=True)
class NotifierConfig:
    """Configuração do ProactiveNotifier.

    Attributes:
        interval_s:             Pausa entre ticks do loop (health check).
        llm_offline_threshold_s: Tempo sem LLM até virar alerta (padrão 300).
        disk_threshold_percent: Percentual de disco que dispara alerta.
        disk_paths:             Caminhos monitorados (shutil.disk_usage).
        default_cooldown_s:     Anti-spam padrão entre alertas iguais.
        cooldowns:              Cooldown específico por chave de alerta.
        state_file:             Persistência JSON opcional (pid/started_at +
                                cooldowns) para restart e anti-spam entre
                                reinícios. None = tudo em memória.
    """

    interval_s: float = 60.0
    llm_offline_threshold_s: float = DEFAULT_LLM_OFFLINE_S
    disk_threshold_percent: float = DEFAULT_DISK_THRESHOLD_PERCENT
    disk_paths: tuple[str, ...] = ("/",)
    default_cooldown_s: float = DEFAULT_COOLDOWN_S
    cooldowns: dict[str, float] = field(default_factory=dict)
    state_file: Optional[Union[str, Path]] = None


# -- Contratos plugáveis ------------------------------------------------------

CheckOutcome = Union[CheckResult, list[CheckResult]]


class CheckFn(Protocol):
    """Sonda de saúde: sync ou async, resultado único ou múltiplo."""

    def __call__(
        self, notifier: "ProactiveNotifier",
    ) -> Union[CheckOutcome, Awaitable[CheckOutcome]]: ...


class SinkFn(Protocol):
    """Canal de envio: recebe o texto formatado do alerta (sync ou async)."""

    def __call__(self, text: str) -> Union[Any, Awaitable[Any]]: ...


# ---------------------------------------------------------------------------
# Sondas embutidas (assinatura CheckFn: recebem o notifier)
# ---------------------------------------------------------------------------

def _check_orchestrator(notifier: "ProactiveNotifier") -> CheckResult:
    if notifier.orchestrator is None:
        return CheckResult(
            ok=False,
            severity=SEVERITY_WARN,
            source="orchestrator",
            detail="Orchestrator não conectado ao notifier.",
        )
    return CheckResult(
        ok=True, source="orchestrator",
        detail="Orchestrator conectado.",
    )


def _check_llm(notifier: "ProactiveNotifier") -> CheckResult:
    if notifier.orchestrator is None:
        return CheckResult(
            ok=True, source="llm", detail="LLM não avaliável (sem orchestrator)."
        )
    available = [
        p for p in notifier.orchestrator.providers
        if ProactiveNotifier._provider_available(p)
    ]
    if available:
        notifier._problem_since.pop("llm:offline", None)
        return CheckResult(
            ok=True, source="llm",
            detail=f"{len(available)} provider(s) disponível(eis): "
                   f"{', '.join(ProactiveNotifier._provider_names(available))}.",
        )
    # Nenhum provider disponível — problema com latência (emit_after_s)
    return CheckResult(
        ok=False,
        severity=SEVERITY_CRIT,
        source="llm",
        key="llm:offline",
        detail="Nenhum provider de LLM disponível.",
        emit_after_s=notifier.config.llm_offline_threshold_s,
    )


def _check_disk(notifier: "ProactiveNotifier") -> list[CheckResult]:
    results: list[CheckResult] = []
    threshold = notifier.config.disk_threshold_percent
    for path in notifier.config.disk_paths:
        try:
            usage = shutil.disk_usage(path)
        except OSError as exc:  # path inexistente/sem permissão
            results.append(
                CheckResult(
                    ok=False, severity=SEVERITY_WARN, source=f"disk:{path}",
                    key="disk:unreadable",
                    detail=f"Falha ao medir disco de {path}: {exc}.",
                )
            )
            continue
        percent = (usage.used / usage.total) * 100.0 if usage.total else 0.0
        if percent >= threshold:
            severity = (
                SEVERITY_CRIT if percent >= threshold + 10.0 else SEVERITY_WARN
            )
            results.append(
                CheckResult(
                    ok=False, severity=severity, source=f"disk:{path}",
                    key=f"disk:high:{path}",
                    detail=(
                        f"Disco {path} em {percent:.1f}% "
                        f"(limite {threshold:.0f}%)."
                    ),
                )
            )
        else:
            results.append(
                CheckResult(
                    ok=True, source=f"disk:{path}",
                    detail=f"Disco {path} em {percent:.1f}%.",
                )
            )
    return results


def _check_restart(notifier: "ProactiveNotifier") -> CheckResult:
    if notifier._restart_detected and not notifier._restart_reported:
        return CheckResult(
            ok=False,
            severity=SEVERITY_WARN,
            source="restart",
            key="restart",
            detail="Sistema foi reiniciado (PID mudou desde o último estado).",
        )
    return CheckResult(
        ok=True, source="restart", detail="Sem reinício detectado."
    )


# ---------------------------------------------------------------------------
# ProactiveNotifier
# ---------------------------------------------------------------------------

class ProactiveNotifier:
    """Health check periódico + alertas proativos com anti-spam.

    Uso típico:
        notifier = ProactiveNotifier(orchestrator, config=..., sinks=[send])
        notifier.start()  # thread com loop próprio
        ...
        notifier.stop()
    """

    def __init__(
        self,
        orchestrator: Optional[Orchestrator] = None,
        *,
        config: Optional[NotifierConfig] = None,
        sinks: Optional[list[SinkFn]] = None,
        checks: Optional[list[CheckFn]] = None,
        event_bus: Any = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config or NotifierConfig()
        self.event_bus = event_bus
        self._clock = clock or time.monotonic
        self._sinks: list[SinkFn] = list(sinks or [])
        self._checks: list[CheckFn] = (
            list(checks) if checks is not None else self._default_checks()
        )
        self.metrics = NotifierMetrics()
        self._closed = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self.started_at = self._clock()
        self._last_alerts: dict[str, float] = {}  # key -> clock do envio
        self._problem_since: dict[str, float] = {}  # key -> clock do início
        self._alerts: deque[Alert] = deque(maxlen=ALERT_TRACE_LIMIT)
        # Estado persistido (restart + cooldowns entre processos)
        self._state: dict[str, Any] = self._load_state() or {}
        persisted_alerts = self._state.get("last_alerts") or {}
        self._last_alerts = {
            str(k): float(v) for k, v in persisted_alerts.items()
        }
        self._restart_detected = self._detect_restart()
        self._restart_reported = False
        if self.config.state_file is not None:
            self._save_state()

    # -- Lifecycle ------------------------------------------------------------

    def add_sink(self, sink: SinkFn) -> None:
        with self._lock:
            self._sinks.append(sink)

    def start(self) -> threading.Thread:
        """Sobe o loop de ticks em thread daemon (runtime)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._closed = False
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True
            )
            self._thread.start()
            return self._thread

    def _run_loop(self) -> None:
        try:
            asyncio.run(self.run())
        except Exception as exc:  # pragma: no cover — loop interno
            with self._lock:
                self.metrics.errors += 1
            log.error("Loop do notifier encerrado", error=type(exc).__name__)

    def stop(self) -> None:
        with self._lock:
            self._closed = True

    def close(self) -> None:
        self.stop()

    # -- Checks embutidos -----------------------------------------------------

    def _default_checks(self) -> list[CheckFn]:
        return [
            _check_orchestrator,
            _check_llm,
            _check_disk,
            _check_restart,
        ]

    # -- Pipeline do tick -----------------------------------------------------

    async def tick(self) -> list[Alert]:
        """Roda todas as sondas e emite alertas (com anti-spam).

        Returns:
            Alertas efetivamente emitidos neste tick.
        """
        with self._lock:
            self.metrics.ticks += 1
        emitted: list[Alert] = []
        for check in self._checks:
            try:
                outcome = check(self)
                if isinstance(outcome, Awaitable):
                    outcome = await outcome
                results = (
                    outcome if isinstance(outcome, list) else [outcome]
                )
            except Exception as exc:  # pragma: no cover — sonda quebrou
                with self._lock:
                    self.metrics.errors += 1
                log.error("Check falhou", check=repr(check), error=str(exc))
                continue
            with self._lock:
                self.metrics.checks_run += len(results)
            for result in results:
                await self._consume_result(result, emitted)
        return emitted

    async def _consume_result(
        self, result: CheckResult, emitted: list[Alert]
    ) -> None:
        with self._lock:
            if result.ok:
                self._problem_since.pop(result.key, None)
                return
            self.metrics.problems += 1
            now = self._clock()
            since = self._problem_since.setdefault(result.key, now)
            if result.emit_after_s > 0 and (now - since) < result.emit_after_s:
                return  # problema ainda abaixo do threshold de alerta
            # Anti-spam: respeita o cooldown por chave
            cooldown = self.config.cooldowns.get(
                result.key, self.config.default_cooldown_s
            )
            last = self._last_alerts.get(result.key)
            if last is not None and (now - last) < cooldown:
                self.metrics.alerts_blocked += 1
                return
            alert = Alert(
                key=result.key,
                severity=result.severity,
                title=result.source,
                detail=result.detail,
                source=result.source,
                ts=now,
            )
            await self._emit(alert, now)
            emitted.append(alert)

    async def _emit(self, alert: Alert, now: float) -> None:
        self._last_alerts[alert.key] = now
        self._alerts.append(alert)
        self.metrics.alerts_emitted += 1
        if alert.key == "restart":
            self._restart_reported = True
        text = self.format_alert(alert)
        log.warn(
            "Alerta proativo",
            key=alert.key,
            severity=alert.severity,
            detail=alert.detail,
        )
        for sink in self._sinks:
            try:
                out = sink(text)
                if isinstance(out, Awaitable):
                    await out
            except Exception as exc:  # pragma: no cover — sink quebrou
                self.metrics.errors += 1
                log.error("Sink falhou", error=str(exc))
        if self.event_bus is not None:
            try:
                await self.event_bus.publish(_make_event(alert))
            except RuntimeError:  # pragma: no cover — sem loop ativo
                log.warn("Event bus indisponível — alerta só logado.")
        if self.config.state_file is not None:
            self._save_state()

    # -- Loop de execução -----------------------------------------------------

    async def run(
        self,
        interval: Optional[float] = None,
        max_ticks: Optional[int] = None,
    ) -> int:
        """Loop de health check: tick a cada `interval` até stop()/limite.

        Returns:
            Número de ticks executados.
        """
        pause = interval if interval is not None else self.config.interval_s
        ticks = 0
        while not self._closed:
            await self.tick()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            await asyncio.sleep(pause)
        return ticks

    # -- Saúde e introspecção -------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Roda as sondas e devolve o estado atual (sem emitir alertas)."""
        checks: dict[str, Any] = {}
        for check in self._checks:
            try:
                outcome = check(self)
                if isinstance(outcome, Awaitable):
                    outcome = await outcome
                results = outcome if isinstance(outcome, list) else [outcome]
            except Exception as exc:  # pragma: no cover
                results = [
                    CheckResult(
                        ok=False, severity=SEVERITY_CRIT,
                        source=repr(check),
                        detail=f"erro na sonda: {exc}",
                    )
                ]
            for result in results:
                checks[result.key] = {
                    "ok": result.ok,
                    "severity": SEVERITY_OK if result.ok else result.severity,
                    "detail": result.detail,
                }
        overall = all(item["ok"] for item in checks.values())
        return {
            "ok": overall,
            "status": SEVERITY_OK if overall else SEVERITY_WARN,
            "checks": checks,
            "ts": self._clock(),
        }

    def snapshot(self) -> dict[str, Any]:
        """Estado acumulado (sem rodar sondas)."""
        with self._lock:
            return {
                "started_at": self.started_at,
                "pid": self._pid,
                "checks": [getattr(c, "__name__", repr(c)) for c in self._checks],
                "sinks": len(self._sinks),
                "metrics": self.metrics.snapshot(),
                "active_problems": sorted(self._problem_since),
                "last_alerts": {
                    k: round(v, 3) for k, v in self._last_alerts.items()
                },
            }

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in self._alerts]

    def dump(self) -> dict[str, Any]:
        data = self.snapshot()
        data["alerts"] = self.history()
        return data

    @staticmethod
    def format_alert(alert: Alert) -> str:
        emoji = SEVERITY_EMOJI.get(alert.severity, "•")
        when = time.strftime(
            "%d/%m %H:%M:%S", time.localtime(alert.ts)
        ) if alert.ts else "-"
        title = alert.title or alert.key
        detail = f" — {alert.detail}" if alert.detail else ""
        return f"{emoji} [{alert.severity.upper()}] {title}{detail} ({when})"

    # -- Estado persistido ----------------------------------------------------

    def _load_state(self) -> Optional[dict[str, Any]]:
        path = self._state_path()
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warn("State do notifier ilegível — ignorado.")
            return None

    def _save_state(self) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "pid": self._pid,
                "started_at": self.started_at,
                "last_alerts": {
                    k: round(v, 3) for k, v in self._last_alerts.items()
                },
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:  # pragma: no cover — sem permissão
            log.warn("State do notifier não pôde ser salvo", error=str(exc))

    def _state_path(self) -> Optional[Path]:
        if self.config.state_file is None:
            return None
        return Path(self.config.state_file)

    def _detect_restart(self) -> bool:
        if not self._state:
            return False  # primeira execução (baseline criado)
        previous_pid = self._state.get("pid")
        if previous_pid is not None:
            return int(previous_pid) != self._pid
        # Estado antigo sem pid: compara o timestamp de início
        previous_started = self._state.get("started_at")
        return bool(
            previous_started is not None
            and abs(float(previous_started) - self.started_at) > 1.0
        )

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _provider_available(provider: Any) -> bool:
        available = getattr(provider, "is_available", None)
        if available is None:
            return True  # sem sonda declarada, considera disponível
        try:
            return bool(available())
        except Exception:  # pragma: no cover — sonda quebrou
            return False

    @staticmethod
    def _provider_names(providers: list[Any]) -> list[str]:
        return [
            getattr(p, "name", "") or type(p).__name__ for p in providers
        ]


def _make_event(alert: Alert) -> Any:
    """Evento do bus (import tardio evita dependência pesada no módulo)."""
    from core.event_bus import Event

    return Event(
        topic="notifier.alert",
        data=alert.to_dict(),
        source="notifier",
    )