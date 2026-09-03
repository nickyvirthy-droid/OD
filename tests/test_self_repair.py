"""
OMEGA DRAKON • TESTS
Módulo: tests/test_self_repair.py
Descrição: Testes do Self Repair Engine (core/self_repair.py) — Fase 4,
           item 4.2: detecção de falhas, geração de correções mediada pelo
           Coder Engine, verificação pós-promoção, rollback automático,
           estratégias/providers plugáveis, métricas e eventos.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/self_repair.py (auto-cura)
  - OMEGADRAKON_SPEC.md §7
  - ROADMAP_ABSORCAO.md Fase 4, item 4.2
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import core.self_repair as sr
from core.coder import CoderEngine
from core.event_bus import EventBus
from core.self_repair import (
    CATEGORY_CHECK,
    CATEGORY_IMPORT,
    CATEGORY_RUNTIME,
    CATEGORY_SYNTAX,
    AddMissingColonStrategy,
    Detection,
    RepairReport,
    SelfRepairEngine,
    SelfRepairScopeError,
    STATUS_ERROR,
    STATUS_HEALTHY,
    STATUS_NO_FIX,
    STATUS_REPAIRED,
)


def _broken_module() -> str:
    """Módulo .py com def sem ':' (falha syntax na linha 1)."""
    return "def saudacao()\n    return 'oi'\n"


def _fixed_module() -> str:
    return "def saudacao():\n    return 'oi'\n"


# ===========================================================================
# Detecção de falhas
# ===========================================================================

class TestSelfRepairDetect:
    """Detection: compile, import probe e arquivos saudáveis."""

    def _engine(self, tmp_path: Path) -> SelfRepairEngine:
        return SelfRepairEngine(coder=CoderEngine(root=tmp_path))

    def test_healthy_py_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        engine = self._engine(tmp_path)
        assert engine.detect("ok.py") is None
        assert engine.detect("ok.py", import_probe=True) is None

    def test_syntax_error_detected(self, tmp_path: Path) -> None:
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)
        failure = engine.detect("bro.py")
        assert isinstance(failure, Detection)
        assert failure.category == CATEGORY_SYNTAX
        assert failure.source == "compile"
        assert failure.line == 1
        assert failure.file == "bro.py"

    def test_import_probe_detects_missing_dependency(self, tmp_path: Path) -> None:
        (tmp_path / "dep.py").write_text(
            "import pacote_que_nao_existe_odxyz\n", encoding="utf-8"
        )
        engine = self._engine(tmp_path)
        failure = engine.detect("dep.py", import_probe=True)
        assert failure is not None
        assert failure.category == CATEGORY_IMPORT
        assert failure.source == "import"
        # sem import_probe, um módulo sintaticamente ok não falha
        assert engine.detect("dep.py") is None

    def test_import_probe_detects_runtime_error(self, tmp_path: Path) -> None:
        (tmp_path / "run.py").write_text(
            "print(nome_nao_definido_xyz)\n", encoding="utf-8"
        )
        engine = self._engine(tmp_path)
        failure = engine.detect("run.py", import_probe=True)
        assert failure is not None
        assert failure.category == CATEGORY_RUNTIME
        assert failure.source == "import"
        assert "nome_nao_definido_xyz" in failure.message

    def test_non_py_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "dados.txt").write_text("apenas texto", encoding="utf-8")
        engine = self._engine(tmp_path)
        assert engine.detect("dados.txt") is None
        assert engine.detect("dados.txt", import_probe=True) is None

    def test_missing_file_raises_scope_error(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        with pytest.raises(SelfRepairScopeError):
            engine.detect("sumido.py")

    def test_outside_root_raises(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        with pytest.raises(SelfRepairScopeError):
            engine.detect(tmp_path.parent / "fora.py")

    def test_detection_to_dict(self, tmp_path: Path) -> None:
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)
        data = engine.detect("bro.py").to_dict()
        assert data["category"] == CATEGORY_SYNTAX
        assert data["line"] == 1


# ===========================================================================
# AddMissingColonStrategy
# ===========================================================================

class TestAddMissingColonStrategy:
    """Estratégia determinística de header sem ':'."""

    def _failure(self, line: int = 1, message: str = "expected ':'") -> Detection:
        return Detection(
            file="mod.py",
            category=CATEGORY_SYNTAX,
            message=message,
            line=line,
        )

    def test_def_header_fixed(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        strategy = AddMissingColonStrategy()
        candidates = strategy.generate(
            target, self._failure(), "def f()\n    return 1\n"
        )
        assert candidates == ["def f():\n    return 1\n"]

    def test_if_header_fixed_with_indent(self, tmp_path: Path) -> None:
        strategy = AddMissingColonStrategy()
        content = "if x > 0\n    print(x)\n"
        candidates = strategy.generate(target=tmp_path / "m.py", failure=self._failure(line=1), content=content)
        assert candidates == ["if x > 0:\n    print(x)\n"]

    def test_line_already_with_colon_no_candidate(self, tmp_path: Path) -> None:
        strategy = AddMissingColonStrategy()
        candidates = strategy.generate(
            tmp_path / "m.py", self._failure(), "if x:\n    print(x)\n"
        )
        assert candidates == []

    def test_non_header_line_no_candidate(self, tmp_path: Path) -> None:
        # erro de indentação (linha 2 não é header) — estratégia não aplica
        strategy = AddMissingColonStrategy()
        failure = self._failure(line=2, message="expected an indented block")
        candidates = strategy.generate(
            tmp_path / "m.py", failure, "def f():\n    pass\n"
        )
        assert candidates == []

    def test_candidate_equal_content_rejected(self, tmp_path: Path) -> None:
        strategy = AddMissingColonStrategy()
        failure = self._failure(line=1)
        content = "if x:\n    pass\n"
        # estratégia retorna vazio para linha que já termina com ':'
        assert strategy.generate(tmp_path / "m.py", failure, content) == []


# ===========================================================================
# SelfRepairEngine — ciclo completo
# ===========================================================================

@pytest.mark.asyncio
class TestSelfRepairRepair:
    """Ciclos healthy / repaired / no_fix / error."""

    def _engine(self, tmp_path: Path) -> SelfRepairEngine:
        return SelfRepairEngine(coder=CoderEngine(root=tmp_path))

    async def test_healthy_report(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("ok.py")
        assert report.status == STATUS_HEALTHY
        assert report.ok is False
        assert report.failure is None
        assert report.attempts == []
        assert "saudável" in report.summary

    async def test_syntax_repaired_via_coder(self, tmp_path: Path) -> None:
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("bro.py")
        assert report.status == STATUS_REPAIRED
        assert report.ok is True
        assert report.failure.category == CATEGORY_SYNTAX
        assert len(report.attempts) == 1
        attempt = report.attempts[0]
        assert attempt.strategy == "add_missing_colon"
        assert attempt.status == "applied"
        assert attempt.coder_status == "ok"
        assert attempt.change_id
        # arquivo corrigido
        assert target.read_text(encoding="utf-8") == _fixed_module()
        # snapshot pré-reparo existe (estado doente preservado)
        snapshot = Path(report.snapshot_path)
        assert snapshot.exists()
        assert snapshot.read_text(encoding="utf-8") == _broken_module()

    async def test_no_fix_when_no_strategy_covers(self, tmp_path: Path) -> None:
        target = tmp_path / "weird.py"
        target.write_text("x = = 1\n", encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("weird.py")
        assert report.status == STATUS_NO_FIX
        assert report.failure.category == CATEGORY_SYNTAX
        assert report.attempts == []
        assert target.read_text(encoding="utf-8") == "x = = 1\n"  # intacto

    async def test_import_failure_no_fix(self, tmp_path: Path) -> None:
        target = tmp_path / "dep.py"
        target.write_text("import pacote_que_nao_existe_odxyz\n", encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("dep.py", import_probe=True)
        assert report.status == STATUS_NO_FIX
        assert report.failure.category == CATEGORY_IMPORT
        # sem estratégia para imports — arquivo intacto
        assert target.read_text(encoding="utf-8").startswith("import pacote_que")

    async def test_check_oracle_detects_regression(self, tmp_path: Path) -> None:
        # sintaxe OK, mas o componente está doente no oracle
        (tmp_path / "svc.py").write_text("ESTADO = 'ruim'\n", encoding="utf-8")
        engine = self._engine(tmp_path)

        def oracle() -> bool:
            return (tmp_path / "svc.py").read_text(encoding="utf-8") == "ESTADO = 'bom'\n"

        report = await engine.repair("svc.py", check=oracle)
        assert report.status == STATUS_NO_FIX
        assert report.failure.category == CATEGORY_CHECK

    async def test_check_passes_after_repair(self, tmp_path: Path) -> None:
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)

        def oracle() -> bool:
            return "def saudacao():" in target.read_text(encoding="utf-8")

        report = await engine.repair("bro.py", check=oracle)
        assert report.status == STATUS_REPAIRED
        assert report.attempts[0].verification == "check ok"

    async def test_async_check_oracle(self, tmp_path: Path) -> None:
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)

        async def oracle() -> bool:
            await asyncio.sleep(0.01)
            return "def saudacao():" in target.read_text(encoding="utf-8")

        report = await engine.repair("bro.py", check=oracle)
        assert report.status == STATUS_REPAIRED

    async def test_scope_error_report(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        report = await engine.repair(str(tmp_path.parent / "fora.py"))
        assert report.status == STATUS_ERROR
        assert any("escopo" in e for e in report.errors)

    async def test_missing_file_error_report(self, tmp_path: Path) -> None:
        engine = self._engine(tmp_path)
        report = await engine.repair("sumido.py")
        assert report.status == STATUS_ERROR

    async def test_report_is_typed_and_timed(self, tmp_path: Path) -> None:
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("bro.py")
        assert isinstance(report, RepairReport)
        assert report.finished_at is not None
        assert report.duration >= 0
        assert report.report_id
        data = report.to_dict()
        assert data["status"] == STATUS_REPAIRED
        assert data["attempts"][0]["strategy"] == "add_missing_colon"


# ===========================================================================
# Rollback automático e restore
# ===========================================================================

@pytest.mark.asyncio
class TestSelfRepairRollback:
    """Correção promovida que reprova na verificação → rollback."""

    def _engine(self, tmp_path: Path) -> SelfRepairEngine:
        return SelfRepairEngine(coder=CoderEngine(root=tmp_path))

    async def test_verification_failure_rolls_back(self, tmp_path: Path) -> None:
        target = tmp_path / "roll.py"
        broken = "def g()\n    pass\n"
        target.write_text(broken, encoding="utf-8")
        engine = self._engine(tmp_path)

        def always_bad() -> bool:
            return False

        report = await engine.repair("roll.py", check=always_bad)
        assert report.status == STATUS_NO_FIX
        assert report.rolled_back is True
        attempt = report.attempts[0]
        assert attempt.status == "rolled_back"
        assert attempt.coder_status == "ok"  # promoção aconteceu
        assert "check" in attempt.verification
        # bytes exatos do estado original restaurados (mesmo doente)
        assert target.read_text(encoding="utf-8") == broken

    async def test_rollback_preserves_snapshot(self, tmp_path: Path) -> None:
        target = tmp_path / "roll.py"
        target.write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("roll.py", check=lambda: False)
        assert report.rolled_back is True
        # snapshot ainda disponível para restore manual
        snapshot = Path(report.snapshot_path)
        assert snapshot.exists()
        assert snapshot.read_text(encoding="utf-8") == _broken_module()

    async def test_manual_restore(self, tmp_path: Path) -> None:
        target = tmp_path / "bro.py"
        broken = _broken_module()
        target.write_text(broken, encoding="utf-8")
        engine = self._engine(tmp_path)
        report = await engine.repair("bro.py")
        assert report.status == STATUS_REPAIRED
        assert target.read_text(encoding="utf-8") == _fixed_module()
        # restore manual volta ao snapshot pré-reparo
        assert engine.restore("bro.py") is True
        assert target.read_text(encoding="utf-8") == broken

    async def test_restore_without_snapshot_fails(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        engine = self._engine(tmp_path)
        await engine.repair("ok.py")  # saudável — sem snapshot
        assert engine.restore("ok.py") is False

    async def test_runner_gate_blocks_repair(self, tmp_path: Path) -> None:
        """Qualquer correção passa pelo Coder Engine — runner reprovando
        impede a promoção (mediação obrigatória)."""
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")
        engine = self._engine(tmp_path)

        def recusa(**_: object) -> bool:
            return False

        report = await engine.repair("bro.py", runner=recusa)
        assert report.status == STATUS_NO_FIX
        assert report.attempts[0].status == "rejected"
        assert report.attempts[0].coder_status == "test_failed"
        assert target.read_text(encoding="utf-8") == _broken_module()

    async def test_security_denied_blocks_repair(self, tmp_path: Path) -> None:
        from core.security import ScopeEngine, SecurityManager

        scope = ScopeEngine(allowed_roots=[tmp_path])
        security = SecurityManager(mode="strict", scope_engine=scope)
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")
        coder = CoderEngine(root=tmp_path, security=security)
        engine = SelfRepairEngine(coder=coder)
        report = await engine.repair("bro.py", role="ghost")
        assert report.status == STATUS_NO_FIX
        assert report.attempts[0].coder_status == "denied"
        assert target.read_text(encoding="utf-8") == _broken_module()


# ===========================================================================
# Estratégias e providers plugáveis
# ===========================================================================

@pytest.mark.asyncio
class TestSelfRepairStrategies:
    """Extensibilidade: estratégias e providers geram candidatos seguros."""

    def _engine(self, tmp_path: Path, **kwargs: object) -> SelfRepairEngine:
        return SelfRepairEngine(coder=CoderEngine(root=tmp_path), **kwargs)

    class ReplaceAllStrategy:
        """Estratégia de teste: substitui conteúdo por código fixo."""

        name = "replace_all"
        categories = (CATEGORY_SYNTAX,)

        def generate(
            self, target: Path, failure: Detection, content: str
        ) -> list[str]:
            if "x = = 1" not in content:
                return []
            return ["x = 1\n"]

    class FailingStrategy:
        """Estratégia que falha ao gerar — deve ser tolerada."""

        name = "failing"
        categories = (CATEGORY_SYNTAX,)

        def generate(
            self, target: Path, failure: Detection, content: str
        ) -> list[str]:
            raise RuntimeError("estratégia quebrada")

    class FixProviderStub:
        name = "provider_stub"

        def propose(
            self, target: Path, failure: Detection, content: str
        ) -> list[str]:
            return ["VALOR = 42\n"]

    async def test_custom_strategy_repairs(self, tmp_path: Path) -> None:
        target = tmp_path / "weird.py"
        target.write_text("x = = 1\n", encoding="utf-8")
        engine = self._engine(
            tmp_path, strategies=[self.ReplaceAllStrategy()]
        )
        report = await engine.repair("weird.py")
        assert report.status == STATUS_REPAIRED
        assert report.attempts[0].strategy == "replace_all"
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_provider_suggests_when_builtins_dont(self, tmp_path: Path) -> None:
        target = tmp_path / "weird.py"
        target.write_text("x = = 1\n", encoding="utf-8")
        engine = self._engine(
            tmp_path, providers=[self.FixProviderStub()]
        )
        report = await engine.repair("weird.py")
        assert report.status == STATUS_REPAIRED
        assert report.attempts[0].strategy == "provider_stub"
        assert target.read_text(encoding="utf-8") == "VALOR = 42\n"

    async def test_failing_strategy_tolerated(self, tmp_path: Path) -> None:
        target = tmp_path / "weird.py"
        target.write_text("x = = 1\n", encoding="utf-8")
        engine = self._engine(
            tmp_path, strategies=[self.FailingStrategy(), self.ReplaceAllStrategy()]
        )
        report = await engine.repair("weird.py")
        assert report.status == STATUS_REPAIRED
        assert report.attempts[0].strategy == "replace_all"

    async def test_duplicate_candidates_deduplicated(self, tmp_path: Path) -> None:
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")

        def make_dupe(name: str) -> type:
            """Estratégia com nome próprio que delega ao AddMissingColon."""

            class _Dupe:
                categories = (CATEGORY_SYNTAX,)

                def generate(
                    self, target: Path, failure: Detection, content: str
                ) -> list[str]:
                    return AddMissingColonStrategy().generate(
                        target, failure, content
                    )

            _Dupe.name = name
            return _Dupe

        Dupe1, Dupe2 = make_dupe("dupe1"), make_dupe("dupe2")
        engine = self._engine(tmp_path, strategies=[Dupe1(), Dupe2()])
        report = await engine.repair("bro.py")
        assert report.status == STATUS_REPAIRED
        assert len(report.attempts) == 1  # mesmo candidato tentado 1x
        assert report.attempts[0].strategy == "dupe1"

    async def test_max_attempts_respected(self, tmp_path: Path) -> None:
        target = tmp_path / "bro.py"
        target.write_text(_broken_module(), encoding="utf-8")

        def make_dupe(name: str) -> type:
            class _Dupe:
                categories = (CATEGORY_SYNTAX,)

                def generate(
                    self, target: Path, failure: Detection, content: str
                ) -> list[str]:
                    return AddMissingColonStrategy().generate(
                        target, failure, content
                    )

            _Dupe.name = name
            return _Dupe

        Dupe1, Dupe2 = make_dupe("dupe1"), make_dupe("dupe2")
        # com runner recusando, max_attempts=1 encerra após 1 candidato
        engine = self._engine(
            tmp_path,
            strategies=[Dupe1(), Dupe2()],
            max_attempts=1,
        )
        report = await engine.repair(
            "bro.py", runner=lambda **_: False
        )
        assert report.status == STATUS_NO_FIX
        assert len(report.attempts) == 1
        assert report.summary


# ===========================================================================
# Event Bus, métricas, trilha e dump
# ===========================================================================

@pytest.mark.asyncio
class TestSelfRepairObservability:
    """Eventos, métricas, trilha de relatórios e dump."""

    async def _engine_with_bus(
        self, tmp_path: Path
    ) -> tuple[SelfRepairEngine, EventBus, list]:
        bus = EventBus()
        await bus.start()
        seen: list[dict[str, object]] = []

        async def handler(event: object) -> None:
            seen.append(
                {"topic": getattr(event, "topic"), "data": getattr(event, "data")}
            )

        bus.subscribe_handler("self_repair.*", handler)
        engine = SelfRepairEngine(coder=CoderEngine(root=tmp_path), event_bus=bus)
        return engine, bus, seen

    async def test_healthy_publishes_completed_only(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        engine, bus, seen = await self._engine_with_bus(tmp_path)
        try:
            await engine.repair("ok.py")
            assert [e["topic"] for e in seen] == ["self_repair.completed"]
            assert seen[0]["data"]["status"] == STATUS_HEALTHY
        finally:
            await bus.stop()

    async def test_repaired_publishes_detected_and_completed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        engine, bus, seen = await self._engine_with_bus(tmp_path)
        try:
            await engine.repair("bro.py")
            topics = [e["topic"] for e in seen]
            assert topics == ["self_repair.detected", "self_repair.completed"]
            assert seen[0]["data"]["category"] == CATEGORY_SYNTAX
            assert seen[1]["data"]["status"] == STATUS_REPAIRED
        finally:
            await bus.stop()

    async def test_no_fix_publishes_completed(self, tmp_path: Path) -> None:
        (tmp_path / "weird.py").write_text("x = = 1\n", encoding="utf-8")
        engine, bus, seen = await self._engine_with_bus(tmp_path)
        try:
            await engine.repair("weird.py")
            assert seen[-1]["topic"] == "self_repair.completed"
            assert seen[-1]["data"]["status"] == STATUS_NO_FIX
        finally:
            await bus.stop()

    async def test_bus_not_running_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        bus = EventBus()  # nunca iniciado
        engine = SelfRepairEngine(coder=CoderEngine(root=tmp_path), event_bus=bus)
        report = await engine.repair("bro.py")
        assert report.status == STATUS_REPAIRED

    async def test_metrics_after_mixed_cycles(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        (tmp_path / "weird.py").write_text("x = = 1\n", encoding="utf-8")
        engine = SelfRepairEngine(coder=CoderEngine(root=tmp_path))
        await engine.repair("ok.py")                                   # healthy
        await engine.repair("bro.py")                                  # repaired
        await engine.repair("weird.py")                                # no_fix
        await engine.repair("sumido.py")                               # error
        snap = engine.metrics.snapshot()
        assert snap["cycles"] == 4
        assert snap["healthy"] == 1
        assert snap["repaired"] == 1
        assert snap["no_fix"] == 1
        assert snap["errors"] == 1
        assert snap["attempts"] == 1
        assert snap["avg_duration_ms"] >= 0

    async def test_history_recent_first_trimmed(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("x = 2\n", encoding="utf-8")
        engine = SelfRepairEngine(
            coder=CoderEngine(root=tmp_path), history_size=2
        )
        await engine.repair("a.py")
        await engine.repair("b.py")
        report_a = await engine.repair("a.py")
        history = engine.history
        assert len(history) == 2
        assert history[0]["report_id"] == report_a.report_id
        assert history[0]["status"] == STATUS_HEALTHY

    async def test_dump_shape(self, tmp_path: Path) -> None:
        (tmp_path / "bro.py").write_text(_broken_module(), encoding="utf-8")
        engine = SelfRepairEngine(coder=CoderEngine(root=tmp_path))
        await engine.repair("bro.py")
        dump = engine.dump()
        assert dump["coder_root"] == str(tmp_path.resolve())
        assert "add_missing_colon" in dump["strategies"]
        assert dump["metrics"]["repaired"] == 1
        assert len(dump["history"]) == 1
        assert dump["snapshots_kept"] == 1
