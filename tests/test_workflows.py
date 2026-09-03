"""
OMEGA DRAKON • TESTS
Módulo: tests/test_workflows.py
Descrição: Testes do Workflow Engine (core/workflows.py) — Fase 3, item 3.1:
           linear, branching, nested, retries, timeouts, cancelamento,
           segurança, persistência, event bus, métricas e validação.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/workflows/
  - ROADMAP_ABSORCAO.md Fase 3, item 3.1
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from core.event_bus import EventBus
from core.security import SecurityManager
from core.workflows import (
    WorkflowEngine,
    WorkflowExecution,
    WorkflowNotFoundError,
    WorkflowSpec,
    WorkflowStep,
    WorkflowValidationError,
)

# ===========================================================================
# Workflow Engine — validação de specs (registro)
# ===========================================================================


class TestWorkflowSpecValidation:
    """Validação de definições de workflow no momento do registro."""

    def _engine(self) -> WorkflowEngine:
        return WorkflowEngine()

    def test_register_valid_spec(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="ok",
            steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
        )
        engine.register(spec)
        assert engine.has("ok")

    def test_register_replaces_existing(self) -> None:
        engine = self._engine()
        engine.register(WorkflowSpec(id="w", steps=[WorkflowStep(id="a", action=lambda ctx: 1)]))
        engine.register(WorkflowSpec(id="w", steps=[WorkflowStep(id="b", action=lambda ctx: 2)]))
        assert [s["id"] for s in engine.list()] == ["w"]
        assert engine.list()[0]["steps"] == 1

    def test_empty_id_raises(self) -> None:
        engine = self._engine()
        with pytest.raises(WorkflowValidationError):
            engine.register(WorkflowSpec(id="  ", steps=[WorkflowStep(id="a", action=lambda ctx: 1)]))

    def test_empty_steps_raises(self) -> None:
        engine = self._engine()
        with pytest.raises(WorkflowValidationError):
            engine.register(WorkflowSpec(id="w", steps=[]))

    def test_duplicate_step_id_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[
                WorkflowStep(id="a", action=lambda ctx: 1),
                WorkflowStep(id="a", action=lambda ctx: 2),
            ],
        )
        with pytest.raises(WorkflowValidationError, match="duplicado"):
            engine.register(spec)

    def test_unknown_kind_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="a", kind="teleport", action=lambda ctx: 1)],
        )
        with pytest.raises(WorkflowValidationError, match="Kind"):
            engine.register(spec)

    def test_condition_without_callable_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="c", kind="condition")],
        )
        with pytest.raises(WorkflowValidationError, match="condition"):
            engine.register(spec)

    def test_nested_without_workflow_target_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="n", kind="workflow")],
        )
        with pytest.raises(WorkflowValidationError, match="workflow"):
            engine.register(spec)

    def test_negative_retries_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="a", action=lambda ctx: 1, retries=-1)],
        )
        with pytest.raises(WorkflowValidationError, match="retries"):
            engine.register(spec)

    def test_invalid_timeout_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="a", action=lambda ctx: 1, timeout=0)],
        )
        with pytest.raises(WorkflowValidationError, match="timeout"):
            engine.register(spec)

    def test_invalid_on_error_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="a", action=lambda ctx: 1, on_error="explode")],
        )
        with pytest.raises(WorkflowValidationError, match="on_error"):
            engine.register(spec)

    def test_invalid_default_on_error_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            default_on_error="explode",
        )
        with pytest.raises(WorkflowValidationError, match="default_on_error"):
            engine.register(spec)

    def test_next_target_unknown_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[
                WorkflowStep(id="a", action=lambda ctx: 1, next="ghost"),
            ],
        )
        with pytest.raises(WorkflowValidationError, match="next desconhecido"):
            engine.register(spec)

    def test_branch_target_unknown_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[
                WorkflowStep(
                    id="c",
                    kind="condition",
                    condition=lambda ctx: True,
                    if_true_next="ghost",
                ),
                WorkflowStep(id="b", action=lambda ctx: 1),
            ],
        )
        with pytest.raises(WorkflowValidationError, match="branch desconhecido"):
            engine.register(spec)

    def test_entry_step_unknown_raises(self) -> None:
        engine = self._engine()
        spec = WorkflowSpec(
            id="w",
            steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            entry_step="ghost",
        )
        with pytest.raises(WorkflowValidationError, match="entry_step"):
            engine.register(spec)

    def test_unregister(self) -> None:
        engine = self._engine()
        engine.register(WorkflowSpec(id="w", steps=[WorkflowStep(id="a", action=lambda ctx: 1)]))
        assert engine.unregister("w") is True
        assert engine.unregister("w") is False
        assert not engine.has("w")

    def test_list_snapshot(self) -> None:
        engine = self._engine()
        engine.register(
            WorkflowSpec(
                id="w",
                name="Demo",
                version="2.0.0",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        listing = engine.list()
        assert listing[0]["id"] == "w"
        assert listing[0]["name"] == "Demo"
        assert listing[0]["version"] == "2.0.0"
        assert listing[0]["entry_step"] == "a"

    def test_list_empty(self) -> None:
        assert self._engine().list() == []

    @pytest.mark.asyncio
    async def test_execute_unknown_workflow_raises(self) -> None:
        engine = self._engine()
        with pytest.raises(WorkflowNotFoundError, match="não registrado"):
            await engine.execute("ghost")


# ===========================================================================
# Workflow Engine — execução linear
# ===========================================================================


class _Recorder:
    """Registra a ordem de execução e valores para asserts."""

    def __init__(self) -> None:
        self.order: list[str] = []

    def action(self, step_id: str, value: Any = None):
        def handler(ctx: Any) -> Any:
            self.order.append(step_id)
            return value
        return handler


@pytest.mark.asyncio
class TestWorkflowLinearExecution:
    """Execução sequencial básica de steps."""

    async def test_sequential_order(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="seq",
                steps=[
                    WorkflowStep(id="a", action=rec.action("a", 1)),
                    WorkflowStep(id="b", action=rec.action("b", 2)),
                    WorkflowStep(id="c", action=rec.action("c", 3)),
                ],
            )
        )
        run = await engine.execute("seq")
        assert run.status == "succeeded"
        assert rec.order == ["a", "b", "c"]
        assert len(run.steps) == 3
        assert all(s["status"] == "succeeded" for s in run.steps)
        assert run.output["a"] == 1
        assert run.output["c"] == 3

    async def test_async_action(self) -> None:
        engine = WorkflowEngine()

        async def async_add(ctx: Any) -> int:
            await asyncio.sleep(0.01)
            return ctx.get("x", 0) + 1

        engine.register(
            WorkflowSpec(
                id="async",
                steps=[
                    WorkflowStep(id="add", action=async_add),
                ],
            )
        )
        run = await engine.execute("async", input={"x": 41})
        assert run.status == "succeeded"
        assert run.output["add"] == 42

    async def test_input_accessible_via_get(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="echo",
                steps=[
                    WorkflowStep(
                        id="echo",
                        action=lambda ctx: ctx.get("msg", ""),
                    ),
                ],
            )
        )
        run = await engine.execute("echo", input={"msg": "olá"})
        assert run.status == "succeeded"
        assert run.output["echo"] == "olá"

    async def test_ctx_set_and_output(self) -> None:
        engine = WorkflowEngine()

        def step_one(ctx: Any) -> None:
            ctx.set("first", 1)
            ctx.set_output("visible", True)

        engine.register(
            WorkflowSpec(
                id="ctx",
                steps=[WorkflowStep(id="one", action=step_one)],
            )
        )
        run = await engine.execute("ctx")
        assert run.status == "succeeded"
        assert run.output["first"] == 1
        assert run.output["visible"] is True

    async def test_explicit_next_overrides_sequence(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="jump",
                steps=[
                    WorkflowStep(id="a", action=rec.action("a"), next="c"),
                    WorkflowStep(id="b", action=rec.action("b")),
                    WorkflowStep(id="c", action=rec.action("c")),
                ],
            )
        )
        run = await engine.execute("jump")
        assert run.status == "succeeded"
        assert rec.order == ["a", "c"]

    async def test_entry_step_override(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="entry",
                entry_step="b",
                steps=[
                    WorkflowStep(id="a", action=rec.action("a")),
                    WorkflowStep(id="b", action=rec.action("b")),
                    WorkflowStep(id="c", action=rec.action("c")),
                ],
            )
        )
        run = await engine.execute("entry")
        assert run.status == "succeeded"
        assert rec.order == ["b", "c"]

    async def test_action_raising_fails_run(self) -> None:
        engine = WorkflowEngine()

        def boom(ctx: Any) -> None:
            raise ValueError("explodiu")

        engine.register(
            WorkflowSpec(
                id="boom",
                steps=[
                    WorkflowStep(id="boom", action=boom),
                    WorkflowStep(id="never", action=lambda ctx: 1),
                ],
            )
        )
        run = await engine.execute("boom")
        assert run.status == "failed"
        assert "ValueError: explodiu" in run.error
        assert run.error_step == "boom"
        assert len(run.steps) == 1
        assert run.steps[0]["status"] == "failed"
        assert run.steps[0]["attempts"] == 1

    async def test_duration_and_timestamps_set(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="fast",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("fast")
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.duration >= 0
        assert run.steps[0]["duration"] >= 0


# ===========================================================================
# Workflow Engine — branching condicional
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowBranching:
    """Desvios condicionais (if_true_next / if_false_next)."""

    async def test_condition_true_branch(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="branch",
                steps=[
                    WorkflowStep(id="start", action=rec.action("start")),
                    WorkflowStep(
                        id="check",
                        kind="condition",
                        condition=lambda ctx: ctx.get("value") == 1,
                        if_true_next="yes",
                        if_false_next="no",
                    ),
                    WorkflowStep(id="yes", action=rec.action("yes")),
                    WorkflowStep(id="no", action=rec.action("no")),
                ],
            )
        )
        run = await engine.execute("branch", input={"value": 1})
        assert run.status == "succeeded"
        assert rec.order == ["start", "yes"]

    async def test_condition_false_branch(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="branch2",
                steps=[
                    WorkflowStep(
                        id="check",
                        kind="condition",
                        condition=lambda ctx: ctx.get("value") == 1,
                        if_true_next="yes",
                        if_false_next="no",
                    ),
                    WorkflowStep(id="yes", action=rec.action("yes")),
                    WorkflowStep(id="no", action=rec.action("no")),
                ],
            )
        )
        run = await engine.execute("branch2", input={"value": 0})
        assert run.status == "succeeded"
        assert rec.order == ["no"]

    async def test_condition_falls_back_to_sequential(self) -> None:
        """Sem branch para o resultado, o fluxo linear segue para a frente."""
        engine = WorkflowEngine()
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="fallback",
                entry_step="check",
                steps=[
                    WorkflowStep(id="yes", action=rec.action("yes")),
                    WorkflowStep(
                        id="check",
                        kind="condition",
                        condition=lambda ctx: ctx.get("value") == 1,
                        if_true_next="yes",
                    ),
                    WorkflowStep(id="tail1", action=rec.action("tail1")),
                    WorkflowStep(id="tail2", action=rec.action("tail2")),
                ],
            )
        )
        run = await engine.execute("fallback", input={"value": 0})
        assert run.status == "succeeded"
        # False sem if_false_next: cai para o próximo step da lista e segue
        assert rec.order == ["tail1", "tail2"]

        run_true = await engine.execute("fallback", input={"value": 1})
        assert run_true.status == "succeeded"
        assert rec.order == ["tail1", "tail2", "yes"]

    async def test_condition_branch_backwards_allowed(self) -> None:
        """Loops controlados (branch para step anterior) são permitidos."""
        engine = WorkflowEngine(max_steps=100)

        def counter(ctx: Any) -> int:
            n = ctx.get("n", 0) + 1
            ctx.set("n", n)
            return n

        engine.register(
            WorkflowSpec(
                id="loop",
                steps=[
                    WorkflowStep(id="inc", action=counter, next="check"),
                    WorkflowStep(
                        id="check",
                        kind="condition",
                        condition=lambda ctx: ctx.get("n") < 3,
                        if_true_next="inc",
                    ),
                ],
            )
        )
        run = await engine.execute("loop")
        assert run.status == "succeeded"
        assert run.output["n"] == 3

    async def test_async_condition(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()

        async def check(ctx: Any) -> bool:
            await asyncio.sleep(0.01)
            return ctx.get("value") > 10

        engine.register(
            WorkflowSpec(
                id="asynccond",
                steps=[
                    WorkflowStep(
                        id="check",
                        kind="condition",
                        condition=check,
                        if_true_next="big",
                        if_false_next="small",
                    ),
                    WorkflowStep(id="big", action=rec.action("big")),
                    WorkflowStep(id="small", action=rec.action("small")),
                ],
            )
        )
        run = await engine.execute("asynccond", input={"value": 42})
        assert run.status == "succeeded"
        assert rec.order == ["big"]

    async def test_step_limit_guards_infinite_cycle(self) -> None:
        engine = WorkflowEngine(max_steps=6)
        engine.register(
            WorkflowSpec(
                id="cycle",
                steps=[
                    WorkflowStep(id="a", action=lambda ctx: 1, next="b"),
                    WorkflowStep(id="b", action=lambda ctx: 2, next="a"),
                ],
            )
        )
        run = await engine.execute("cycle")
        assert run.status == "failed"
        assert "step limit" in run.error
        assert len(run.steps) == 6


# ===========================================================================
# Workflow Engine — sub-workflows (nested)
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowNested:
    """Execução de workflows dentro de workflows."""

    async def test_nested_subworkflow_runs_and_merges_output(self) -> None:
        engine = WorkflowEngine()

        engine.register(
            WorkflowSpec(
                id="inner",
                steps=[
                    WorkflowStep(
                        id="compute",
                        action=lambda ctx: ctx.get("base", 0) * 2,
                    ),
                ],
            )
        )
        rec = _Recorder()
        engine.register(
            WorkflowSpec(
                id="outer",
                steps=[
                    WorkflowStep(id="prepare", action=rec.action("prepare")),
                    WorkflowStep(
                        id="sub",
                        kind="workflow",
                        workflow="inner",
                    ),
                    WorkflowStep(id="finish", action=rec.action("finish")),
                ],
            )
        )
        run = await engine.execute("outer", input={"base": 21})
        assert run.status == "succeeded"
        assert rec.order == ["prepare", "finish"]
        # Saída do sub-workflow (compute=42) propagada para o pai
        assert run.output["compute"] == 42
        # Duas execuções: pai + filha
        assert engine.metrics.snapshot()["executions"] == 2

    async def test_nested_parent_execution_id(self) -> None:
        engine = WorkflowEngine()
        child_ids: list[str] = []
        engine.register(
            WorkflowSpec(
                id="inner",
                steps=[
                    WorkflowStep(
                        id="who",
                        action=lambda ctx: child_ids.append(ctx.parent_execution_id),
                    ),
                ],
            )
        )
        engine.register(
            WorkflowSpec(
                id="outer",
                steps=[WorkflowStep(id="sub", kind="workflow", workflow="inner")],
            )
        )
        run = await engine.execute("outer")
        assert run.status == "succeeded"
        assert child_ids == [run.execution_id]

    async def test_nested_missing_workflow_fails(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="outer",
                steps=[WorkflowStep(id="sub", kind="workflow", workflow="ghost")],
            )
        )
        run = await engine.execute("outer")
        assert run.status == "failed"
        assert "Sub-workflow não registrado" in run.error or "ghost" in run.error
        assert run.error_step == "sub"

    async def test_nested_failure_propagates(self) -> None:
        engine = WorkflowEngine()

        def boom(ctx: Any) -> None:
            raise RuntimeError("inner failure")

        engine.register(
            WorkflowSpec(
                id="inner",
                steps=[WorkflowStep(id="boom", action=boom)],
            )
        )
        engine.register(
            WorkflowSpec(
                id="outer",
                steps=[WorkflowStep(id="sub", kind="workflow", workflow="inner")],
            )
        )
        run = await engine.execute("outer")
        assert run.status == "failed"
        assert "inner failure" in run.error
        assert run.error_step == "sub"

    async def test_nested_failure_continue_keeps_parent_alive(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()

        def boom(ctx: Any) -> None:
            raise RuntimeError("inner failure")

        engine.register(
            WorkflowSpec(
                id="inner",
                steps=[WorkflowStep(id="boom", action=boom)],
            )
        )
        engine.register(
            WorkflowSpec(
                id="outer",
                steps=[
                    WorkflowStep(
                        id="sub",
                        kind="workflow",
                        workflow="inner",
                        on_error="continue",
                    ),
                    WorkflowStep(id="after", action=rec.action("after")),
                ],
            )
        )
        run = await engine.execute("outer")
        assert run.status == "succeeded"
        assert rec.order == ["after"]
        assert run.steps[0]["status"] == "failed"


# ===========================================================================
# Workflow Engine — retries
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowRetries:
    """Retries automáticos com delay configurável."""

    async def test_retry_succeeds_after_failures(self) -> None:
        engine = WorkflowEngine()
        attempts: list[int] = []

        def flaky(ctx: Any) -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("transient")
            return "ok"

        engine.register(
            WorkflowSpec(
                id="flaky",
                steps=[
                    WorkflowStep(id="f", action=flaky, retries=2, retry_delay=0.0),
                ],
            )
        )
        run = await engine.execute("flaky")
        assert run.status == "succeeded"
        assert run.steps[0]["attempts"] == 3
        assert run.steps[0]["status"] == "succeeded"
        assert run.output["f"] == "ok"

    async def test_retry_exhausted_fails(self) -> None:
        engine = WorkflowEngine()
        attempts: list[int] = []

        def always_fail(ctx: Any) -> None:
            attempts.append(1)
            raise ValueError("always")

        engine.register(
            WorkflowSpec(
                id="nope",
                steps=[
                    WorkflowStep(id="f", action=always_fail, retries=2, retry_delay=0.0),
                ],
            )
        )
        run = await engine.execute("nope")
        assert run.status == "failed"
        assert run.steps[0]["attempts"] == 3
        assert "ValueError: always" in run.steps[0]["error"]

    async def test_no_retry_configured_single_attempt(self) -> None:
        engine = WorkflowEngine()
        attempts: list[int] = []

        def fail(ctx: Any) -> None:
            attempts.append(1)
            raise ValueError("once")

        engine.register(
            WorkflowSpec(
                id="once",
                steps=[WorkflowStep(id="f", action=fail)],
            )
        )
        run = await engine.execute("once")
        assert run.status == "failed"
        assert len(attempts) == 1
        assert run.steps[0]["attempts"] == 1

    async def test_retry_delay_is_respected(self) -> None:
        engine = WorkflowEngine()
        attempts: list[int] = []
        import time as _time

        def flaky(ctx: Any) -> str:
            attempts.append(_time.monotonic())
            if len(attempts) < 2:
                raise ConnectionError("transient")
            return "ok"

        engine.register(
            WorkflowSpec(
                id="delay",
                steps=[
                    WorkflowStep(id="f", action=flaky, retries=1, retry_delay=0.05),
                ],
            )
        )
        run = await engine.execute("delay")
        assert run.status == "succeeded"
        elapsed = attempts[1] - attempts[0]
        assert elapsed >= 0.04, f"delay não respeitado: {elapsed:.3f}s"


# ===========================================================================
# Workflow Engine — timeouts
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowTimeouts:
    """Timeout individual por step."""

    async def test_timeout_fails_step(self) -> None:
        engine = WorkflowEngine()

        async def slow(ctx: Any) -> str:
            await asyncio.sleep(1.0)
            return "tarde demais"

        engine.register(
            WorkflowSpec(
                id="slow",
                steps=[WorkflowStep(id="s", action=slow, timeout=0.05)],
            )
        )
        run = await engine.execute("slow")
        assert run.status == "failed"
        assert "timeout" in run.error
        assert run.steps[0]["status"] == "failed"

    async def test_timeout_retry_then_success(self) -> None:
        engine = WorkflowEngine()
        counter = {"n": 0}

        async def flaky_slow(ctx: Any) -> str:
            counter["n"] += 1
            if counter["n"] == 1:
                await asyncio.sleep(1.0)  # estoura o timeout
            return "rápido na segunda"

        engine.register(
            WorkflowSpec(
                id="slowflaky",
                steps=[
                    WorkflowStep(id="s", action=flaky_slow, timeout=0.05, retries=1),
                ],
            )
        )
        run = await engine.execute("slowflaky")
        assert run.status == "succeeded"
        assert run.steps[0]["attempts"] == 2
        assert run.output["s"] == "rápido na segunda"

    async def test_action_within_timeout_succeeds(self) -> None:
        engine = WorkflowEngine()

        async def quick(ctx: Any) -> str:
            await asyncio.sleep(0.01)
            return "no prazo"

        engine.register(
            WorkflowSpec(
                id="quick",
                steps=[WorkflowStep(id="q", action=quick, timeout=1.0)],
            )
        )
        run = await engine.execute("quick")
        assert run.status == "succeeded"
        assert run.output["q"] == "no prazo"


# ===========================================================================
# Workflow Engine — on_error (fail / continue)
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowOnError:
    """Política de erro por step e por workflow."""

    async def test_default_is_fail(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()

        def boom(ctx: Any) -> None:
            raise ValueError("x")

        engine.register(
            WorkflowSpec(
                id="dflt",
                steps=[
                    WorkflowStep(id="boom", action=boom),
                    WorkflowStep(id="after", action=rec.action("after")),
                ],
            )
        )
        run = await engine.execute("dflt")
        assert run.status == "failed"
        assert rec.order == []

    async def test_step_on_error_continue(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()

        def boom(ctx: Any) -> None:
            raise ValueError("x")

        engine.register(
            WorkflowSpec(
                id="cont",
                steps=[
                    WorkflowStep(id="boom", action=boom, on_error="continue"),
                    WorkflowStep(id="after", action=rec.action("after")),
                ],
            )
        )
        run = await engine.execute("cont")
        assert run.status == "succeeded"
        assert rec.order == ["after"]
        assert run.steps[0]["status"] == "failed"
        assert "ValueError: x" in run.steps[0]["error"]

    async def test_spec_default_on_error_continue(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()

        def boom(ctx: Any) -> None:
            raise ValueError("x")

        engine.register(
            WorkflowSpec(
                id="speccont",
                default_on_error="continue",
                steps=[
                    WorkflowStep(id="boom", action=boom),
                    WorkflowStep(id="after", action=rec.action("after")),
                ],
            )
        )
        run = await engine.execute("speccont")
        assert run.status == "succeeded"
        assert rec.order == ["after"]

    async def test_continue_on_last_step_succeeds(self) -> None:
        engine = WorkflowEngine()

        def boom(ctx: Any) -> None:
            raise ValueError("x")

        engine.register(
            WorkflowSpec(
                id="last",
                steps=[WorkflowStep(id="boom", action=boom, on_error="continue")],
            )
        )
        run = await engine.execute("last")
        assert run.status == "succeeded"


# ===========================================================================
# Workflow Engine — cancelamento cooperativo
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowCancellation:
    """Cancelamento de execuções em andamento."""

    async def test_cancel_running_execution(self) -> None:
        engine = WorkflowEngine()
        rec = _Recorder()
        started: list[str] = []

        async def slow_first(ctx: Any) -> str:
            started.append(ctx.execution_id)
            await asyncio.sleep(3600)
            return "nunca"

        engine.register(
            WorkflowSpec(
                id="slow",
                steps=[
                    WorkflowStep(id="first", action=slow_first),
                    WorkflowStep(id="second", action=rec.action("second")),
                ],
            )
        )
        task = asyncio.create_task(engine.execute("slow"))
        # Aguarda o primeiro step iniciar
        for _ in range(100):
            if started:
                break
            await asyncio.sleep(0.01)
        assert started, "primeiro step não iniciou"

        execution_id = started[0]
        assert await engine.cancel(execution_id) is True
        run = await asyncio.wait_for(task, timeout=5.0)

        assert run.status == "cancelled"
        assert len(run.steps) == 1
        assert run.steps[0]["status"] == "cancelled"
        assert rec.order == []  # segundo step nunca roda

    async def test_cancel_unknown_execution(self) -> None:
        engine = WorkflowEngine()
        assert await engine.cancel("ghost") is False

    async def test_cancel_finished_execution(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="fast",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("fast")
        assert run.status == "succeeded"
        assert await engine.cancel(run.execution_id) is False

    async def test_metrics_count_cancelled(self) -> None:
        engine = WorkflowEngine()
        started: list[str] = []

        async def slow(ctx: Any) -> None:
            started.append(ctx.execution_id)
            await asyncio.sleep(3600)

        engine.register(
            WorkflowSpec(
                id="slow2",
                steps=[WorkflowStep(id="first", action=slow)],
            )
        )
        task = asyncio.create_task(engine.execute("slow2"))
        for _ in range(100):
            if started:
                break
            await asyncio.sleep(0.01)
        assert await engine.cancel(started[0]) is True
        await asyncio.wait_for(task, timeout=5.0)
        snap = engine.metrics.snapshot()
        assert snap["cancelled"] == 1
        assert snap["running"] == 0


# ===========================================================================
# Workflow Engine — integração com Security Layer
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowSecurity:
    """Steps com `requires` validados pelo Security Layer."""

    async def test_denied_in_strict_fails_run(self) -> None:
        security = SecurityManager(mode="strict")
        engine = WorkflowEngine(security=security, default_role="ghost")

        engine.register(
            WorkflowSpec(
                id="guarded",
                steps=[
                    WorkflowStep(
                        id="read",
                        action=lambda ctx: "dados",
                        requires="filesystem.read",
                    ),
                ],
            )
        )
        run = await engine.execute("guarded")
        assert run.status == "failed"
        assert "negada" in run.error
        assert run.steps[0]["attempts"] == 0
        assert run.steps[0]["status"] == "failed"

    async def test_allowed_for_admin_role(self) -> None:
        security = SecurityManager(mode="strict")
        engine = WorkflowEngine(security=security, default_role="admin")

        engine.register(
            WorkflowSpec(
                id="adminwf",
                steps=[
                    WorkflowStep(
                        id="del",
                        action=lambda ctx: "removido",
                        requires="filesystem.delete",
                    ),
                ],
            )
        )
        run = await engine.execute("adminwf")
        assert run.status == "succeeded"
        assert run.output["del"] == "removido"

    async def test_no_security_engine_ignores_requires(self) -> None:
        engine = WorkflowEngine()  # sem SecurityManager
        engine.register(
            WorkflowSpec(
                id="naked",
                steps=[
                    WorkflowStep(
                        id="x",
                        action=lambda ctx: "ok",
                        requires="qualquer.acao",
                    ),
                ],
            )
        )
        run = await engine.execute("naked")
        assert run.status == "succeeded"
        assert run.output["x"] == "ok"


# ===========================================================================
# Workflow Engine — persistência
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowPersistence:
    """Persistência JSON das execuções."""

    async def test_execution_persisted_to_disk(self, tmp_path: Path) -> None:
        base = tmp_path / "workflows"
        engine = WorkflowEngine(base_dir=base)
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: "valor")],
            )
        )
        run = await engine.execute("wf")
        path = base / f"{run.execution_id}.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["status"] == "succeeded"
        assert data["workflow_id"] == "wf"
        assert data["output"]["a"] == "valor"
        assert len(data["steps"]) == 1

    async def test_load_from_disk_in_new_engine(self, tmp_path: Path) -> None:
        base = tmp_path / "workflows"
        engine = WorkflowEngine(base_dir=base)
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("wf")

        engine2 = WorkflowEngine(base_dir=base)
        loaded = engine2.load_execution(run.execution_id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert loaded.workflow_id == "wf"
        assert len(loaded.steps) == 1

    async def test_load_from_memory(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("wf")
        assert engine.load_execution(run.execution_id) is run
        assert engine.get_execution(run.execution_id) is run

    async def test_load_unknown_returns_none(self, tmp_path: Path) -> None:
        engine = WorkflowEngine(base_dir=tmp_path / "wfs")
        assert engine.load_execution("ghost") is None

    async def test_list_executions(self, tmp_path: Path) -> None:
        base = tmp_path / "wfs"
        engine = WorkflowEngine(base_dir=base)
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("wf")
        assert run.execution_id in engine.list_executions()

    async def test_persist_disabled(self, tmp_path: Path) -> None:
        base = tmp_path / "wfs"
        engine = WorkflowEngine(base_dir=base, persist=False)
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("wf")
        assert not (base / f"{run.execution_id}.json").exists()


# ===========================================================================
# Workflow Engine — Event Bus
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowEventBus:
    """Publicação de eventos workflow.started / workflow.finished."""

    async def test_publishes_started_and_finished(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Any] = []

        async def on_event(event: Any) -> None:
            received.append(event)

        bus.subscribe_handler("workflow.**", on_event)

        engine = WorkflowEngine(event_bus=bus)
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("wf")

        topics = [e.topic for e in received]
        assert "workflow.started" in topics
        assert "workflow.finished" in topics

        finished = [e for e in received if e.topic == "workflow.finished"]
        assert len(finished) == 1
        assert finished[0].data["execution_id"] == run.execution_id
        assert finished[0].data["workflow_id"] == "wf"
        assert finished[0].data["status"] == "succeeded"

    async def test_no_events_without_bus(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="wf",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        run = await engine.execute("wf")  # não deve levantar
        assert run.status == "succeeded"


# ===========================================================================
# Workflow Engine — métricas e diagnóstico
# ===========================================================================

class TestWorkflowDump:
    """dump() e registro sem execução."""

    def test_dump_empty(self) -> None:
        engine = WorkflowEngine()
        dump = engine.dump()
        assert dump["workflows"] == 0
        assert dump["running"] == 0
        assert dump["persist_dir"] is None
        assert dump["metrics"]["executions"] == 0

    def test_dump_after_registration(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="wf",
                name="Demo",
                steps=[WorkflowStep(id="a", action=lambda ctx: 1)],
            )
        )
        engine.register(
            WorkflowSpec(
                id="wf2",
                steps=[WorkflowStep(id="b", action=lambda ctx: 2)],
            )
        )
        dump = engine.dump()
        assert dump["workflows"] == 2
        assert len(dump["registered"]) == 2


@pytest.mark.asyncio
class TestWorkflowMetrics:
    """Contadores de execuções e steps."""

    async def test_metrics_after_success_and_failure(self) -> None:
        engine = WorkflowEngine()

        def boom(ctx: Any) -> None:
            raise ValueError("x")

        engine.register(
            WorkflowSpec(
                id="ok",
                steps=[
                    WorkflowStep(id="a", action=lambda ctx: 1),
                    WorkflowStep(id="b", action=lambda ctx: 2),
                ],
            )
        )
        engine.register(
            WorkflowSpec(
                id="bad",
                steps=[WorkflowStep(id="x", action=boom)],
            )
        )
        ok_run = await engine.execute("ok")
        bad_run = await engine.execute("bad")

        snap = engine.metrics.snapshot()
        assert snap["executions"] == 2
        assert snap["succeeded"] == 1
        assert snap["failed"] == 1
        assert snap["running"] == 0
        # steps: 2 do ok + 1 do bad
        assert snap["steps_executed"] == 3
        assert engine.metrics.avg_duration_ms >= 0
        assert ok_run.status == "succeeded"
        assert bad_run.status == "failed"

    async def test_running_counter_during_execution(self) -> None:
        engine = WorkflowEngine()
        gate = asyncio.Event()
        started = asyncio.Event()

        async def blocked(ctx: Any) -> None:
            started.set()
            await gate.wait()
            return "liberado"

        engine.register(
            WorkflowSpec(
                id="blocked",
                steps=[WorkflowStep(id="b", action=blocked)],
            )
        )
        task = asyncio.create_task(engine.execute("blocked"))
        await started.wait()
        assert engine.metrics.snapshot()["running"] == 1
        gate.set()
        run = await asyncio.wait_for(task, timeout=5.0)
        assert run.status == "succeeded"
        assert engine.metrics.snapshot()["running"] == 0


# ===========================================================================
# Workflow Engine — cenário integrado
# ===========================================================================

@pytest.mark.asyncio
class TestWorkflowIntegration:
    """Pipeline completo: normalizar → validar → processar → responder."""

    async def test_message_processing_pipeline(self) -> None:
        """Simula um pipeline de processamento com branching e nested."""
        engine = WorkflowEngine()

        # Sub-workflow: valida o comprimento da mensagem
        engine.register(
            WorkflowSpec(
                id="validate",
                steps=[
                    WorkflowStep(
                        id="check_len",
                        kind="condition",
                        condition=lambda ctx: len(ctx.get("text", "")) >= 3,
                        if_true_next="valid",
                        if_false_next="invalid",
                    ),
                    WorkflowStep(id="valid", action=lambda ctx: "valid"),
                    WorkflowStep(
                        id="invalid",
                        action=lambda ctx: ctx.set_output("reason", "muito curta"),
                    ),
                ],
            )
        )

        # Workflow principal
        engine.register(
            WorkflowSpec(
                id="chat",
                steps=[
                    WorkflowStep(
                        id="normalize",
                        action=lambda ctx: ctx.get("text", "").strip().lower(),
                    ),
                    WorkflowStep(
                        id="validate",
                        kind="workflow",
                        workflow="validate",
                        on_error="fail",
                    ),
                    WorkflowStep(
                        id="answer",
                        action=lambda ctx: f"eco: {ctx.get('normalize')}",
                    ),
                ],
            )
        )

        # Entrada válida
        ok = await engine.execute("chat", input={"text": "  Olá Mundo  "})
        assert ok.status == "succeeded"
        assert ok.output["normalize"] == "olá mundo"
        assert ok.output["answer"] == "eco: olá mundo"

        # Entrada curta: sub-workflow conclui pela rota invalid, mas a
        # saída reason fica disponível e o fluxo principal continua
        short = await engine.execute("chat", input={"text": "oi"})
        assert short.status == "succeeded"
        assert short.output["normalize"] == "oi"
        assert short.output["answer"] == "eco: oi"
        assert "reason" in short.output

    async def test_full_report_includes_step_trail(self) -> None:
        engine = WorkflowEngine()
        engine.register(
            WorkflowSpec(
                id="trail",
                steps=[
                    WorkflowStep(id="a", action=lambda ctx: 1, description="passo a"),
                    WorkflowStep(id="b", action=lambda ctx: 2, description="passo b"),
                ],
            )
        )
        run = await engine.execute("trail")
        report = run.to_dict()
        assert report["status"] == "succeeded"
        assert [s["id"] for s in report["steps"]] == ["a", "b"]
        assert all(s["status"] == "succeeded" for s in report["steps"])
        # round-trip via from_dict preserva o relatório
        rebuilt = WorkflowExecution.from_dict(report)
        assert rebuilt.status == "succeeded"
        assert rebuilt.execution_id == run.execution_id
        assert [s["id"] for s in rebuilt.steps] == ["a", "b"]
