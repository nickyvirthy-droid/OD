"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/recovery.py
Descrição: RecoveryLoop — fecha o LOOP DE AUTO-RECUPERAÇÃO do OmegaDrakon:
           perceber → decidir → agir → verificar, rodando em ciclo periódico
           no runtime:

             1. PERCEPÇÃO   — Telemetry.collect() periódica (snapshot de
                              CPU/memória/disco/rede/portas/docker/processos)
                              → check "perception" no Health Monitor + evento
                              no audit (perception.snapshot);
             2. AUTO-REPARO — varre os .py do projeto, detecta falhas
                              (compile determinístico) e repara via
                              SelfRepairEngine — TODA correção passa pelo
                              Coder Engine (sandbox → testes → backup →
                              promoção) e re-detecção pós-reparo (rollback
                              automático se reprovar);
             3. VERIFICAÇÃO — relatório por ciclo (files_scanned,
                              detections, repairs_applied/failed) publicado
                              no Event Bus (recovery.tick).

           Conservador por construção: apenas estratégias determinísticas
           (ex: AddMissingColon) são aplicadas; nada de código gerado por
           LLM entra sem o pipeline do Coder; falhas em qualquer etapa nunca
           derrubam o ciclo (isolamento por try/except + métricas).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/main_cycle.py (ciclo operacional autônomo a cada 5min)
  - core/self_repair.py (Fase 4.2) e core/coder.py (Fase 4.1)
  - tools/telemetry.py (Fase 4.3) e observability/health.py (Fase 7.3)
  - docs/CAPACIDADES.md §4 (fechamento do loop)
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.recovery")

# Diretórios/arquivos fora da varredura de auto-reparo (nunca tocar).
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
        ".mypy_cache", ".od_sandbox", ".od_backups", ".od_repair_backups",
        "backups", "data", "logs", "archive", "workspace", "imports",
        "node_modules",
    }
)

DEFAULT_INTERVAL_S = 300.0  # ciclo a cada 5min (espelho do main_cycle do Nexus)
DEFAULT_MAX_FILES_PER_TICK = 300
DEFAULT_MAX_REPAIRS_PER_TICK = 3
REPORT_TRACE_LIMIT = 50


def iter_py_files(
    root: Union[str, Path],
    *,
    exclude: frozenset[str] = EXCLUDED_DIR_NAMES,
) -> list[Path]:
    """Lista os .py do projeto (ordenado), fora de dirs excluídos/áreas internas."""
    root = Path(root)
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        try:
            rel = path.relative_to(root)
        except ValueError:  # pragma: no cover — fora do root
            continue
        if set(rel.parts) & exclude:
            continue
        files.append(path)
    return files


@dataclass(slots=True)
class RecoveryMetrics:
    """Métricas acumuladas do ciclo de auto-recuperação."""

    ticks: int = 0
    files_scanned: int = 0
    detections: int = 0
    repairs_attempted: int = 0
    repairs_applied: int = 0
    repairs_failed: int = 0
    perception_ok: int = 0
    perception_errors: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "ticks": self.ticks,
            "files_scanned": self.files_scanned,
            "detections": self.detections,
            "repairs_attempted": self.repairs_attempted,
            "repairs_applied": self.repairs_applied,
            "repairs_failed": self.repairs_failed,
            "perception_ok": self.perception_ok,
            "perception_errors": self.perception_errors,
            "errors": self.errors,
        }


class RecoveryLoop:
    """Ciclo periódico de percepção + auto-reparo (thread daemon no runtime).

    Uso típico:
        from core.recovery import RecoveryLoop
        from core.self_repair import SelfRepairEngine
        from core.coder import CoderEngine
        from tools.telemetry import Telemetry

        loop = RecoveryLoop(root=".", repair=SelfRepairEngine(
            coder=CoderEngine(root=".")), telemetry=Telemetry())
        loop.start()   # thread com ciclo próprio (intervalo configurável)
        ...
        loop.stop()
    """

    def __init__(
        self,
        *,
        root: Union[str, Path],
        telemetry: Optional[Any] = None,
        repair: Optional[Any] = None,
        health: Optional[Any] = None,
        audit: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        interval_s: float = DEFAULT_INTERVAL_S,
        max_files_per_tick: int = DEFAULT_MAX_FILES_PER_TICK,
        max_repairs_per_tick: int = DEFAULT_MAX_REPAIRS_PER_TICK,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        from tools.telemetry import Telemetry

        self.root = Path(root).resolve()
        self.telemetry = telemetry if telemetry is not None else Telemetry()
        self.repair = repair  # SelfRepairEngine (ou fake nos testes)
        self.health = health  # HealthMonitor opcional (check "perception")
        self.audit = audit    # AuditSystem opcional (perception.snapshot)
        self.event_bus = event_bus
        self.interval_s = max(1.0, float(interval_s))
        self.max_files_per_tick = max(1, int(max_files_per_tick))
        self.max_repairs_per_tick = max(1, int(max_repairs_per_tick))
        self._clock = clock or time.monotonic

        # Estado observável
        self.last_telemetry: Optional[dict[str, Any]] = None
        self.last_perception_ok: bool = True
        self.last_tick_ts: float = 0.0
        self.last_tick_summary: dict[str, Any] = {}
        self._recent_reports: deque[dict[str, Any]] = deque(maxlen=REPORT_TRACE_LIMIT)

        self._metrics = RecoveryMetrics()
        self._closed = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    # -- Propriedades --------------------------------------------------------

    @property
    def metrics(self) -> RecoveryMetrics:
        return self._metrics

    # -- Percepção -----------------------------------------------------------

    def collect_perception(self) -> dict[str, Any]:
        """Coleta a telemetria e guarda o último snapshot (resiliente)."""
        snap = self.telemetry.collect()
        errors = [str(e) for e in (getattr(snap, "errors", None) or [])]
        cpu = getattr(snap, "cpu", None) or {}
        mem = getattr(snap, "memory", None) or {}
        disks = getattr(snap, "disk", None) or []
        disk = disks[0] if disks else {}
        data = {
            "ok": not errors,
            "errors": errors,
            "cpu_percent": float(cpu.get("percent", 0.0) or 0.0),
            "memory_percent": float(mem.get("percent", 0.0) or 0.0),
            "disk_percent": float(disk.get("percent", 0.0) or 0.0),
            "ts": self._clock(),
        }
        self.last_telemetry = data
        self.last_perception_ok = data["ok"]
        with self._lock:
            if data["ok"]:
                self._metrics.perception_ok += 1
            else:
                self._metrics.perception_errors += 1
        return data

    def perception_check(self, monitor: Any = None) -> dict[str, Any]:
        """Check do Health Monitor (não-crítico): percepção sem erros de sonda."""
        if self.last_telemetry is None:
            return {
                "ok": True,
                "status": "up",
                "detail": "percepção: sem amostra ainda (primeiro ciclo pendente)",
            }
        t = self.last_telemetry
        if t["ok"]:
            return {
                "ok": True,
                "status": "up",
                "detail": (
                    f"CPU {t['cpu_percent']:.0f}% · mem {t['memory_percent']:.0f}% "
                    f"· disco {t['disk_percent']:.0f}% · 0 erros de sonda"
                ),
            }
        return {
            "ok": False,
            "status": "degraded",
            "detail": f"percepção com erros: {t['errors'][:3]}",
        }

    def _record_perception(self, perception: dict[str, Any]) -> None:
        if self.audit is None:
            return
        try:
            self.audit.record(
                source="recovery",
                action="perception.snapshot",
                outcome="ok" if perception["ok"] else "degraded",
                detail=(
                    f"CPU {perception['cpu_percent']:.0f}% · mem "
                    f"{perception['memory_percent']:.0f}% · disco "
                    f"{perception['disk_percent']:.0f}%"
                ),
                data={
                    "errors": perception["errors"],
                    "ts": perception["ts"],
                },
            )
        except Exception as exc:  # pragma: no cover — audit nunca quebra o loop
            log.warn("Audit de percepção falhou", error=str(exc))

    # -- Auto-reparo ----------------------------------------------------------

    async def repair_project(self) -> list[Any]:
        """Varre os .py do projeto e repara falhas via SelfRepairEngine.

        Returns:
            Lista de RepairReport (status repaired/no_fix/...).
        """
        if self.repair is None:
            return []
        files = iter_py_files(self.root)[: self.max_files_per_tick]
        with self._lock:
            self._metrics.files_scanned += len(files)
        reports: list[Any] = []
        for path in files:
            if len(reports) >= self.max_repairs_per_tick:
                break
            try:
                rel = path.relative_to(self.root)
            except ValueError:  # pragma: no cover
                continue
            rel_str = str(rel)
            try:
                detection = self.repair.detect(rel_str)
            except Exception as exc:  # pragma: no cover — detect quebrou
                with self._lock:
                    self._metrics.errors += 1
                log.warn("Detecção falhou", file=rel_str, error=str(exc))
                continue
            if detection is None:
                continue
            with self._lock:
                self._metrics.detections += 1
                self._metrics.repairs_attempted += 1
            try:
                report = await self.repair.repair(rel_str, session_id="recovery")
            except Exception as exc:  # pragma: no cover — reparo quebrou
                with self._lock:
                    self._metrics.repairs_failed += 1
                    self._metrics.errors += 1
                log.error("Reparo falhou", file=rel_str, error=str(exc))
                continue
            reports.append(report)
            status = getattr(report, "status", "?")
            if status == "repaired":
                with self._lock:
                    self._metrics.repairs_applied += 1
                log.info("Auto-reparo aplicado", file=rel_str)
            else:
                with self._lock:
                    self._metrics.repairs_failed += 1
                log.warn("Auto-reparo sem correção", file=rel_str, status=status)
        return reports

    # -- Ciclo ----------------------------------------------------------------

    async def tick(self) -> dict[str, Any]:
        """Um ciclo: percepção + auto-reparo. Retorna o resumo do tick."""
        with self._lock:
            self._metrics.ticks += 1
        perception = self.collect_perception()
        self._record_perception(perception)
        reports = await self.repair_project()
        summaries = [
            {
                "file": getattr(r, "file", ""),
                "status": getattr(r, "status", "?"),
            }
            for r in reports
        ]
        summary = {
            "perception": {
                "ok": perception["ok"],
                "cpu_percent": perception["cpu_percent"],
                "memory_percent": perception["memory_percent"],
                "disk_percent": perception["disk_percent"],
                "errors": perception["errors"],
            },
            "repairs": summaries,
            "metrics": self.metrics.snapshot(),
            "ts": self._clock(),
        }
        for item in summaries:
            self._recent_reports.appendleft(
                {"ts": summary["ts"], **item}
            )
        self.last_tick_summary = summary
        self.last_tick_ts = summary["ts"]
        if self.event_bus is not None:
            await self._publish(summary)
        return summary

    async def _publish(self, summary: dict[str, Any]) -> None:
        try:
            from core.event_bus import Event

            await self.event_bus.publish(
                Event(topic="recovery.tick", data=summary, source="recovery")
            )
        except Exception as exc:  # pragma: no cover — bus sem loop ativo
            log.warn("Event bus indisponível — tick só registrado", error=str(exc))

    async def run(
        self,
        interval: Optional[float] = None,
        max_ticks: Optional[int] = None,
    ) -> int:
        """Loop de ciclos a cada `interval` até stop()/limite."""
        pause = interval if interval is not None else self.interval_s
        ticks = 0
        while not self._closed:
            try:
                await self.tick()
            except Exception as exc:  # pragma: no cover — ciclo nunca morre
                with self._lock:
                    self._metrics.errors += 1
                log.error("Ciclo de recuperação falhou", error=type(exc).__name__)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            await asyncio.sleep(pause)
        return ticks

    def start(self) -> threading.Thread:
        """Sobe o ciclo em thread daemon (runtime)."""
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
        except Exception as exc:  # pragma: no cover — thread morreu
            with self._lock:
                self._metrics.errors += 1
            log.error("Loop de recuperação encerrado", error=type(exc).__name__)

    def stop(self) -> None:
        with self._lock:
            self._closed = True

    # -- Introspecção ---------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Estado do loop para Health Monitor agregado (check não-crítico)."""
        return {
            "ok": self.last_perception_ok,
            "status": "up" if self.last_perception_ok else "degraded",
            "detail": "percepção ativa" if self.last_perception_ok
                      else "percepção com erros de sonda",
            "last_tick_ts": self.last_tick_ts,
            "metrics": self.metrics.snapshot(),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "root": str(self.root),
                "interval_s": self.interval_s,
                "last_perception": self.last_telemetry,
                "last_tick": self.last_tick_summary,
                "recent_reports": list(self._recent_reports),
                "metrics": self.metrics.snapshot(),
            }

    def dump(self) -> dict[str, Any]:
        return self.snapshot()


__all__ = [
    "EXCLUDED_DIR_NAMES",
    "DEFAULT_INTERVAL_S",
    "iter_py_files",
    "RecoveryLoop",
    "RecoveryMetrics",
]