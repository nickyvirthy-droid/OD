"""
OMEGA DRAKON • TESTS
Módulo: tests/test_recovery.py
Descrição: Testes do RecoveryLoop (core/recovery.py, v0.27.4) — o ciclo
           periódico que fecha o loop de auto-recuperação: percepção
           (Telemetry) + auto-reparo (SelfRepair via Coder) + verificação.
           Cobre a varredura de arquivos (exclusões), o tick com fakes
           (percepção ok/erro, reparo aplicado/sem detecção), reparo REAL
           de um .py quebrado em tmp root (AddMissingColon mediado pelo
           Coder), integração com Health Monitor (check "perception"),
           auditoria (perception.snapshot) e o loop run/max_ticks.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/recovery.py (RecoveryLoop)
  - core/self_repair.py (Fase 4.2) e core/coder.py (Fase 4.1)
  - tools/telemetry.py (Fase 4.3)
  - observability/health.py (Fase 7.3)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.coder import CoderEngine
from core.recovery import (
    EXCLUDED_DIR_NAMES,
    RecoveryLoop,
    iter_py_files,
)
from core.self_repair import SelfRepairEngine
from observability.health import HealthMonitor


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeTelemetry:
    """Telemetry fake: collect() devolve snapshot com erros configuráveis."""

    def __init__(self, errors: tuple = ()) -> None:
        self._errors = list(errors)
        self.calls = 0

    def collect(self):
        self.calls += 1
        return SimpleNamespace(
            errors=list(self._errors),
            cpu={"percent": 20.0},
            memory={"percent": 40.0},
            disk=[{"path": "/", "percent": 60.0}],
            host={"hostname": "fake"},
        )


class FakeRepair:
    """SelfRepairEngine fake: detect/repair determinísticos."""

    def __init__(self, detection=None, status: str = "repaired") -> None:
        self._detection = detection  # None = saudável
        self._status = status
        self.detect_calls: list[str] = []
        self.repair_calls: list[str] = []

    def detect(self, rel: str):
        self.detect_calls.append(rel)
        return self._detection

    async def repair(self, rel: str, session_id: str = ""):
        self.repair_calls.append(rel)
        return SimpleNamespace(status=self._status, file=rel)


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, **kwargs) -> None:
        self.records.append(kwargs)


# ---------------------------------------------------------------------------
# Varredura de arquivos
# ---------------------------------------------------------------------------

class TestIterPyFiles:
    def test_exclui_areas_internas_e_venv(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
        for bad in (".venv", ".git", "__pycache__", ".od_sandbox",
                    ".od_backups", "data", "logs", "backups"):
            (tmp_path / bad).mkdir(parents=True, exist_ok=True)
            (tmp_path / bad / "z.py").write_text("z = 3\n", encoding="utf-8")

        files = iter_py_files(tmp_path)
        rels = {str(p.relative_to(tmp_path)) for p in files}
        assert rels == {"a.py", "sub/b.py"}

    def test_ordenado(self, tmp_path: Path) -> None:
        for name in ("b.py", "a.py", "c.py"):
            (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
        files = iter_py_files(tmp_path)
        assert [p.name for p in files] == ["a.py", "b.py", "c.py"]


# ---------------------------------------------------------------------------
# Tick com fakes
# ---------------------------------------------------------------------------

class TestRecoveryTick:
    def _loop(self, tmp_path: Path, telemetry=None, repair=None,
              audit=None, health=None) -> RecoveryLoop:
        return RecoveryLoop(
            root=tmp_path,
            telemetry=telemetry or FakeTelemetry(),
            repair=repair,
            audit=audit,
            health=health,
            interval_s=1.0,
        )

    @pytest.mark.asyncio
    async def test_tick_percepcao_ok(self, tmp_path: Path) -> None:
        loop = self._loop(tmp_path)
        summary = await loop.tick()
        assert summary["perception"]["ok"] is True
        assert summary["perception"]["cpu_percent"] == 20.0
        assert loop.last_perception_ok is True
        assert loop.metrics.perception_ok == 1
        assert loop.metrics.ticks == 1
        assert loop.last_telemetry is not None

    @pytest.mark.asyncio
    async def test_tick_percepcao_com_erro_degrada(self, tmp_path: Path) -> None:
        telemetry = FakeTelemetry(errors=("network: unreadable",))
        loop = self._loop(tmp_path, telemetry=telemetry)
        await loop.tick()
        assert loop.last_perception_ok is False
        assert loop.metrics.perception_errors == 1
        summary = loop.last_tick_summary
        assert summary["perception"]["ok"] is False
        assert summary["perception"]["errors"] == ["network: unreadable"]

    @pytest.mark.asyncio
    async def test_tick_repara_arquivo_detectado(self, tmp_path: Path) -> None:
        (tmp_path / "algum.py").write_text("x = 1\n", encoding="utf-8")
        repair = FakeRepair(detection={"category": "syntax"})
        loop = self._loop(tmp_path, repair=repair)
        summary = await loop.tick()
        assert summary["repairs"] == [
            {"file": "algum.py", "status": "repaired"}
        ]
        assert loop.metrics.detections == 1
        assert loop.metrics.repairs_attempted == 1
        assert loop.metrics.repairs_applied == 1

    @pytest.mark.asyncio
    async def test_tick_sem_deteccao_nao_repara(self, tmp_path: Path) -> None:
        repair = FakeRepair(detection=None)
        loop = self._loop(tmp_path, repair=repair)
        await loop.tick()
        assert loop.metrics.detections == 0
        assert loop.metrics.repairs_applied == 0
        assert repair.repair_calls == []

    @pytest.mark.asyncio
    async def test_tick_audita_percepcao(self, tmp_path: Path) -> None:
        audit = FakeAudit()
        loop = self._loop(tmp_path, audit=audit)
        await loop.tick()
        assert len(audit.records) == 1
        rec = audit.records[0]
        assert rec["action"] == "perception.snapshot"
        assert rec["outcome"] == "ok"

    @pytest.mark.asyncio
    async def test_perception_check_no_health_monitor(
        self, tmp_path: Path
    ) -> None:
        """Check 'perception' registrado no HealthMonitor (não-crítico)."""
        monitor = HealthMonitor()
        loop = self._loop(tmp_path, health=monitor)
        # antes da primeira amostra: up
        monitor.register("perception", loop.perception_check, critical=False)
        result = await monitor.health()
        assert result["checks"]["perception"]["ok"] is True
        assert result["status"] == "up"
        # após amostra com erro: degraded (não derruba para down)
        loop = self._loop(
            tmp_path, telemetry=FakeTelemetry(errors=("docker: down",)),
            health=monitor,
        )
        monitor.register("perception", loop.perception_check, critical=False)
        await loop.tick()
        result = await monitor.health()
        assert result["checks"]["perception"]["ok"] is False
        assert result["checks"]["perception"]["status"] == "degraded"
        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_run_max_ticks(self, tmp_path: Path) -> None:
        loop = self._loop(tmp_path)
        ticks = await loop.run(interval=0.01, max_ticks=2)
        assert ticks == 2
        assert loop.metrics.ticks == 2

    @pytest.mark.asyncio
    async def test_snapshot_dump(self, tmp_path: Path) -> None:
        loop = self._loop(tmp_path)
        await loop.tick()
        snap = loop.snapshot()
        assert snap["root"] == str(tmp_path)
        assert snap["metrics"]["ticks"] == 1
        assert snap["last_perception"]["ok"] is True
        assert loop.dump()["recent_reports"] == []  # sem reparos


# ---------------------------------------------------------------------------
# Reparo REAL (arquivo .py quebrado em tmp root)
# ---------------------------------------------------------------------------

class TestRecoveryRealRepair:
    @pytest.mark.asyncio
    async def test_repairs_broken_py_via_coder(self, tmp_path: Path) -> None:
        """Header sem ':' é detectado e corrigido (AddMissingColon)."""
        broken = tmp_path / "broken.py"
        broken.write_text("def foo()\n    return 1\n", encoding="utf-8")

        coder = CoderEngine(root=tmp_path)
        repair = SelfRepairEngine(coder=coder)
        loop = RecoveryLoop(
            root=tmp_path,
            telemetry=FakeTelemetry(),
            repair=repair,
            interval_s=1.0,
        )
        summary = await loop.tick()
        assert summary["repairs"], "esperava ao menos um reparo"
        assert summary["repairs"][0]["status"] == "repaired"
        assert broken.read_text(encoding="utf-8") == (
            "def foo():\n    return 1\n"
        )
        assert loop.metrics.repairs_applied == 1
        # segundo tick: saudável — nenhuma nova detecção
        await loop.tick()
        assert loop.metrics.detections == 1  # só a primeira vez

    @pytest.mark.asyncio
    async def test_healthy_project_no_repairs(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text(
            "def bar() -> int:\n    return 42\n", encoding="utf-8"
        )
        coder = CoderEngine(root=tmp_path)
        repair = SelfRepairEngine(coder=coder)
        loop = RecoveryLoop(
            root=tmp_path,
            telemetry=FakeTelemetry(),
            repair=repair,
            interval_s=1.0,
        )
        summary = await loop.tick()
        assert summary["repairs"] == []
        assert loop.metrics.repairs_attempted == 0