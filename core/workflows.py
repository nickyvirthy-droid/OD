"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/workflows.py
Descrição: Workflow Engine — execução orquestrada de workflows com steps
           lineares, branching condicional, sub-workflows (nested), retries,
           timeouts, contexto isolado por execução e persistência JSON.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/workflows/ (WorkflowManager, WorkflowContext)
  - OMEGADRAKON_SPEC.md §7 (execução validada pelo Security Layer)
  - ROADMAP_ABSORCAO.md Fase 3, item 3.1

Architecture:
    Um WorkflowSpec é uma lista ordenada de WorkflowSteps. Cada step pode
    ser:
      - "action":    executa um callable (sync ou async) que recebe o
                     WorkflowContext da execução;
      - "condition": avalia um callable que retorna bool e desvia o fluxo
                     para if_true_next ou if_false_next (branching);
      - "workflow":  executa outro workflow registrado (sub-workflow /
                     nested), herdando as variáveis do pai.

    Cada execução roda com contexto isolado (WorkflowContext): input,
    variables e output próprios. Steps suportam retries automáticos (com
    delay) e timeout individual. O cancelamento é cooperativo:
    engine.cancel() sinaliza a execução, que interrompe o step em andamento
    e marca o run como "cancelled".

    A persistência (opcional) grava cada execução em
    data/workflows/executions/{execution_id}.json com escrita atômica.
    Ações síncronas longas bloqueiam o event loop: para timeout/cancelamento
    efetivos, steps devem ser async (ou retornar rápido).

Usage:
    from core.workflows import WorkflowEngine, WorkflowSpec, WorkflowStep

    engine = WorkflowEngine()

    def upper_step(ctx):
        name = ctx.get("name", "")
        return name.upper()

    async def async_step(ctx):
        await asyncio.sleep(0.01)
        return ctx.get("name", "").lower()

    engine.register(WorkflowSpec(
        id="demo",
        steps=[
            WorkflowStep(id="upper", action=upper_step),
            WorkflowStep(id="lower", action=async_step),
            WorkflowStep(
                id="check",
                kind="condition",
                condition=lambda ctx: ctx.get("upper") == "OD",
                if_true_next="ok",
                if_false_next="fail",
            ),
            WorkflowStep(id="ok", action=lambda ctx: "tudo certo"),
            WorkflowStep(id="fail", action=lambda ctx: "não conferiu"),
        ],
    ))

    run = await engine.execute("demo", input={"name": "od"})
    run.status          # "succeeded"
    run.output          # variáveis finais
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING, Union

from core.logger import get_logger

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.security.manager import SecurityManager

__signature__ = "OD // CORE"

log = get_logger("omega.core.workflows")

# ---------------------------------------------------------------------------
# Constantes e aliases
# ---------------------------------------------------------------------------

STEP_KINDS = ("action", "condition", "workflow")
ON_ERROR_OPTIONS = ("fail", "continue")
DEFAULT_MAX_STEPS = 500  # guarda contra ciclos infinitos em branching

ActionFn = Callable[["WorkflowContext"], Any]
ConditionFn = Callable[["WorkflowContext"], bool]


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class WorkflowStep:
    """Um passo de workflow.

    Attributes:
        id:             Identificador único dentro do workflow.
        action:         Callable(ctx) — sync ou async. Retorno não-None é
                        armazenado em variables[step.id].
        kind:           "action" (padrão), "condition" ou "workflow".
        workflow:       Id do sub-workflow (obrigatório quando kind="workflow").
        condition:      Callable(ctx) -> bool (obrigatório quando kind="condition").
        if_true_next:   Próximo step quando condition retorna True.
        if_false_next:  Próximo step quando condition retorna False.
        next:           Próximo step (override da ordem sequencial).
        retries:        Tentativas adicionais após erro/timeout (0 = sem retry).
        retry_delay:    Segundos de espera entre tentativas.
        timeout:        Timeout em segundos do step (None = sem limite).
        on_error:       "fail" (padrão) ou "continue".
        requires:       Ação validada pelo Security Layer antes de executar
                        (ex: "filesystem.read"). Vazio = sem check.
        description:    Descrição livre do passo.
    """

    id: str
    action: Optional[ActionFn] = None
    kind: str = "action"
    workflow: Optional[str] = None
    condition: Optional[ConditionFn] = None
    if_true_next: Optional[str] = None
    if_false_next: Optional[str] = None
    next: Optional[str] = None
    retries: int = 0
    retry_delay: float = 0.0
    timeout: Optional[float] = None
    on_error: str = ""
    requires: str = ""
    description: str = ""


@dataclass(slots=True)
class WorkflowSpec:
    """Definição declarativa de um workflow.

    Attributes:
        id:               Identificador único do workflow (registro).
        steps:            Steps na ordem padrão de execução.
        name:             Nome amigável.
        description:      Descrição.
        version:          Versão da definição.
        entry_step:       Id do primeiro step (padrão: steps[0].id).
        default_on_error: "fail" (padrão) ou "continue" para steps sem
                          on_error próprio.
    """

    id: str
    steps: list[WorkflowStep] = field(default_factory=list)
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    entry_step: Optional[str] = None
    default_on_error: str = "fail"


@dataclass(slots=True)
class WorkflowContext:
    """Contexto isolado de uma execução de workflow.

    Attributes:
        execution_id:         Id da execução corrente.
        workflow_id:          Id do workflow sendo executado.
        parent_execution_id:  Id da execução pai (quando nested).
        input:                Dados de entrada da execução.
        variables:            Variáveis de trabalho (lidas/escritas por steps).
        output:               Saídas declaradas (set_output).
        status:               Status corrente da execução.
        current_step:         Id do step em execução.
    """

    execution_id: str
    workflow_id: str
    parent_execution_id: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    current_step: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        """Lê uma variável (variables primeiro, depois input)."""
        if key in self.variables:
            return self.variables[key]
        return self.input.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Grava uma variável de trabalho."""
        self.variables[key] = value

    def set_output(self, key: str, value: Any) -> None:
        """Declara uma saída da execução."""
        self.output[key] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "parent_execution_id": self.parent_execution_id,
            "input": self.input,
            "variables": self.variables,
            "output": self.output,
            "status": self.status,
            "current_step": self.current_step,
        }


@dataclass(slots=True)
class WorkflowExecution:
    """Registro de uma execução (resultado + trilha de steps).

    Attributes:
        execution_id:         Identificador da execução.
        workflow_id:          Workflow executado.
        status:               pending | running | succeeded | failed | cancelled.
        input:                Entrada recebida.
        output:               Saída final ({**variables, **output}).
        error:                Mensagem de erro (quando failed).
        error_step:           Id do step que falhou.
        parent_execution_id:  Execução pai (nested).
        started_at:           Timestamp de início.
        finished_at:          Timestamp de fim.
        steps:                Resultados individuais dos steps executados.
    """

    execution_id: str
    workflow_id: str
    status: str = "pending"
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_step: str = ""
    parent_execution_id: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Duração em segundos (0 se incompleta)."""
        if self.started_at is None or self.finished_at is None:
            return 0.0
        return self.finished_at - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "error_step": self.error_step,
            "parent_execution_id": self.parent_execution_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": round(self.duration, 6),
            "steps": self.steps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowExecution":
        return cls(
            execution_id=data["execution_id"],
            workflow_id=data["workflow_id"],
            status=data.get("status", "pending"),
            input=dict(data.get("input", {})),
            output=dict(data.get("output", {})),
            error=data.get("error", ""),
            error_step=data.get("error_step", ""),
            parent_execution_id=data.get("parent_execution_id", ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            steps=list(data.get("steps", [])),
        )


@dataclass(slots=True)
class WorkflowMetrics:
    """Métricas acumuladas do engine."""

    executions: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    running: int = 0
    steps_executed: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.executions == 0:
            return 0.0
        return round(self.total_duration_ms / self.executions, 3)

    def snapshot(self) -> dict[str, Any]:
        return {
            "executions": self.executions,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "running": self.running,
            "steps_executed": self.steps_executed,
            "avg_duration_ms": self.avg_duration_ms,
        }


@dataclass(slots=True)
class _RunState:
    """Estado interno de uma execução em andamento."""

    execution: WorkflowExecution
    cancel_event: asyncio.Event


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------

class WorkflowError(Exception):
    """Erro base do Workflow Engine."""


class WorkflowValidationError(WorkflowError, ValueError):
    """Definição de workflow inválida (ids duplicados, referências etc.)."""


class WorkflowNotFoundError(WorkflowError, KeyError):
    """Workflow ou execução não encontrado(a)."""


class WorkflowSecurityError(WorkflowError):
    """Step bloqueado pelo Security Layer."""


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """Engine de orquestração de workflows.

    Attributes:
        security:   SecurityManager opcional — steps com `requires` são
                    validados antes de executar (fail-closed em modo strict).
        event_bus:  EventBus opcional — publica workflow.started e
                    workflow.finished.
        base_dir:   Diretório opcional de persistência das execuções.
        max_steps:  Guarda contra loops infinitos em branching.
    """

    def __init__(
        self,
        *,
        security: Optional[SecurityManager] = None,
        event_bus: Optional[EventBus] = None,
        base_dir: Optional[Union[str, Path]] = None,
        persist: bool = True,
        default_role: str = "agent",
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self._security = security
        self._event_bus = event_bus
        self._default_role = default_role
        self._max_steps = max_steps
        self._persist_enabled = persist
        self._base_dir = Path(base_dir) if base_dir else None

        self._specs: dict[str, WorkflowSpec] = {}
        self._executions: dict[str, WorkflowExecution] = {}
        self._runs: dict[str, _RunState] = {}
        self._metrics = WorkflowMetrics()

    # -- Registro de workflows ----------------------------------------------

    def register(self, spec: WorkflowSpec) -> WorkflowSpec:
        """Registra (ou substitui) uma definição de workflow (validada)."""
        self._validate_spec(spec)
        self._specs[spec.id] = spec
        log.info(
            "Workflow registered",
            workflow=spec.id,
            steps=len(spec.steps),
            version=spec.version,
        )
        return spec

    def unregister(self, workflow_id: str) -> bool:
        """Remove um workflow registrado. Retorna True se existia."""
        spec = self._specs.pop(workflow_id, None)
        if spec is not None:
            log.info("Workflow unregistered", workflow=workflow_id)
            return True
        return False

    def has(self, workflow_id: str) -> bool:
        return workflow_id in self._specs

    def list(self) -> list[dict[str, Any]]:
        """Lista os workflows registrados (snapshot declarativo)."""
        return [
            {
                "id": spec.id,
                "name": spec.name,
                "version": spec.version,
                "steps": len(spec.steps),
                "entry_step": spec.entry_step
                or (spec.steps[0].id if spec.steps else None),
                "default_on_error": spec.default_on_error,
            }
            for spec in self._specs.values()
        ]

    # -- Execução ------------------------------------------------------------

    async def execute(
        self,
        workflow_id: str,
        *,
        input: Optional[dict[str, Any]] = None,
        parent_execution_id: str = "",
        _cancel_event: Optional[asyncio.Event] = None,
    ) -> WorkflowExecution:
        """Executa um workflow registrado e aguarda a conclusão.

        Args:
            workflow_id:         Id do workflow (deve estar registrado).
            input:               Dados de entrada (ctx.get/ctx.input).
            parent_execution_id: Execução pai (nested workflows).
            _cancel_event:       Evento de cancelamento compartilhado
                                 (uso interno em sub-workflows).

        Returns:
            WorkflowExecution com status final, output e trilha de steps.
        """
        spec = self._specs.get(workflow_id)
        if spec is None:
            raise WorkflowNotFoundError(f"Workflow não registrado: {workflow_id}")

        execution = WorkflowExecution(
            execution_id=uuid.uuid4().hex[:12],
            workflow_id=workflow_id,
            status="pending",
            input=dict(input or {}),
            parent_execution_id=parent_execution_id,
        )
        cancel_event = _cancel_event or asyncio.Event()
        run_state = _RunState(execution=execution, cancel_event=cancel_event)

        self._executions[execution.execution_id] = execution
        self._runs[execution.execution_id] = run_state
        self._metrics.running += 1

        log.info(
            "Workflow execution started",
            execution=execution.execution_id,
            workflow=workflow_id,
            parent=parent_execution_id or "-",
        )
        await self._publish_event(
            "workflow.started",
            execution_id=execution.execution_id,
            workflow_id=workflow_id,
        )

        try:
            await self._run(spec, run_state)
        finally:
            self._runs.pop(execution.execution_id, None)
            self._metrics.running = max(0, self._metrics.running - 1)
            self._metrics.executions += 1
            self._metrics.steps_executed += len(execution.steps)
            if execution.duration > 0:
                self._metrics.total_duration_ms += execution.duration * 1000.0
            if self._persist_enabled and self._base_dir is not None:
                self._persist(execution)

        if execution.status == "succeeded":
            self._metrics.succeeded += 1
        elif execution.status == "failed":
            self._metrics.failed += 1
        elif execution.status == "cancelled":
            self._metrics.cancelled += 1

        if execution.status == "succeeded":
            log.info(
                "Workflow execution finished",
                execution=execution.execution_id,
                workflow=workflow_id,
                status=execution.status,
                steps=len(execution.steps),
            )
        else:
            log.warn(
                "Workflow execution finished",
                execution=execution.execution_id,
                workflow=workflow_id,
                status=execution.status,
                error=execution.error or "-",
                error_step=execution.error_step or "-",
            )

        await self._publish_event(
            "workflow.finished",
            execution_id=execution.execution_id,
            workflow_id=workflow_id,
            status=execution.status,
            error=execution.error or "",
        )
        return execution

    async def cancel(self, execution_id: str) -> bool:
        """Solicita o cancelamento cooperativo de uma execução.

        Retorna True se a execução estava em andamento e foi sinalizada.
        """
        run_state = self._runs.get(execution_id)
        if run_state is None:
            log.warn(
                "Cancel ignored",
                execution=execution_id,
                reason="not running",
            )
            return False
        run_state.cancel_event.set()
        log.info("Workflow cancellation requested", execution=execution_id)
        return True

    # -- Núcleo do run -------------------------------------------------------

    async def _run(self, spec: WorkflowSpec, run_state: _RunState) -> None:
        """Executa os steps do spec, resolvendo branching até o fim."""
        execution = run_state.execution
        ctx = WorkflowContext(
            execution_id=execution.execution_id,
            workflow_id=spec.id,
            parent_execution_id=execution.parent_execution_id,
            input=dict(execution.input),
        )
        execution.status = "running"
        execution.started_at = time.time()

        steps = spec.steps
        ids = {s.id: s for s in steps}
        order = {s.id: idx for idx, s in enumerate(steps)}
        if spec.entry_step and spec.entry_step in ids:
            current = spec.entry_step
        else:
            current = steps[0].id if steps else None

        executed = 0
        linear = True  # cadeia linear: avança para o próximo step da lista
        try:
            while current is not None:
                if run_state.cancel_event.is_set():
                    execution.status = "cancelled"
                    break
                if executed >= self._max_steps:
                    execution.status = "failed"
                    execution.error = (
                        f"step limit excedido ({self._max_steps}) — possível loop"
                    )
                    execution.error_step = current
                    break

                step = ids[current]
                executed += 1
                ctx.current_step = step.id
                ctx.status = execution.status

                step_result = await self._run_step(run_state, step, ctx)
                execution.steps.append(step_result)

                if step_result["status"] == "cancelled":
                    execution.status = "cancelled"
                    break

                if step_result["status"] == "failed":
                    error = step_result["error"]
                    on_error = step.on_error or spec.default_on_error or "fail"
                    if on_error == "fail":
                        execution.status = "failed"
                        execution.error = error
                        execution.error_step = step.id
                        break
                    log.warn(
                        "Workflow step failed (continue)",
                        workflow=spec.id,
                        step=step.id,
                        error=error,
                    )
                    current, linear = self._resolve_next(
                        spec, step, order, condition_result=None, linear=linear
                    )
                    continue

                # Step succeeded
                value = step_result.get("value")
                if step.kind == "condition":
                    current, linear = self._resolve_next(
                        spec,
                        step,
                        order,
                        condition_result=bool(value),
                        linear=linear,
                    )
                elif step.kind == "workflow":
                    if isinstance(value, dict) and value.get("output"):
                        ctx.variables.update(value["output"])
                    current, linear = self._resolve_next(
                        spec, step, order, condition_result=None, linear=linear
                    )
                else:
                    if value is not None:
                        ctx.variables[step.id] = value
                    current, linear = self._resolve_next(
                        spec, step, order, condition_result=None, linear=linear
                    )
        except Exception as exc:
            # Erro interno do engine/scheduling — nunca deixa status "running"
            execution.status = "failed"
            execution.error = f"{type(exc).__name__}: {exc}"
            execution.error_step = ctx.current_step
        finally:
            if execution.status == "running":
                # Saiu do while sem status definido => lista concluída
                execution.status = "succeeded"
            if execution.status == "succeeded":
                execution.output = {**ctx.variables, **ctx.output}
            execution.finished_at = time.time()
            ctx.status = execution.status

    def _resolve_next(
        self,
        spec: WorkflowSpec,
        step: WorkflowStep,
        order: dict[str, int],
        *,
        condition_result: Optional[bool],
        linear: bool,
    ) -> tuple[Optional[str], bool]:
        """Resolve o próximo step após um step concluído.

        Modelo de fluxo:
          - Um link explícito (branch da condition ou `step.next`) faz um
            SALTO: o alvo inicia um caminho novo (linear=False).
          - Sem link explícito, o fluxo só continua automaticamente para o
            próximo step da lista quando o step corrente foi alcançado em
            cadeia linear (linear=True).
          - Um alvo de salto sem `next` próprio encerra o workflow — assim,
            branches irmãos não "vazam" para o caminho não escolhido.

        Returns:
            (próximo id, linear) — linear=True quando o avanço é sequencial.
        """
        target: Optional[str] = None
        if step.kind == "condition" and condition_result is not None:
            target = step.if_true_next if condition_result else step.if_false_next
            if target is None:
                target = step.next
        elif step.next is not None:
            target = step.next

        if target is not None:
            return target, False

        if linear:
            idx = order[step.id]
            if idx + 1 < len(spec.steps):
                return spec.steps[idx + 1].id, True
        return None, False

    async def _run_step(
        self,
        run_state: _RunState,
        step: WorkflowStep,
        ctx: WorkflowContext,
    ) -> dict[str, Any]:
        """Executa um step com gate de segurança, retries, timeout e cancel.

        Returns:
            Dict com status ("succeeded"|"failed"|"cancelled"), attempts,
            error, duração e value (quando bem-sucedido).
        """
        result: dict[str, Any] = {
            "id": step.id,
            "kind": step.kind,
            "status": "failed",
            "attempts": 0,
            "error": "",
            "started_at": time.time(),
            "finished_at": None,
            "duration": 0.0,
        }

        # Gate de segurança (uma única checagem, sem retry)
        if step.requires and self._security is not None:
            decision = self._security.check(
                action=step.requires,
                role=self._default_role,
                source="workflow",
                metadata={"workflow_step": step.id},
            )
            if not decision.allowed:
                result["status"] = "failed"
                result["attempts"] = 0
                result["error"] = (
                    f"WorkflowSecurityError: ação {step.requires!r} negada "
                    f"(denied_by={decision.denied_by})"
                )
                result["finished_at"] = time.time()
                result["duration"] = round(
                    result["finished_at"] - result["started_at"], 6
                )
                log.warn(
                    "Workflow step denied by security",
                    step=step.id,
                    action=step.requires,
                    denied_by=decision.denied_by or "-",
                )
                return result

        attempts = 0
        last_error = ""
        value: Any = None
        while True:
            if run_state.cancel_event.is_set():
                result["status"] = "cancelled"
                break

            attempts += 1
            outcome = await self._attempt(run_state, step, ctx)

            if outcome[0] == "ok":
                result["status"] = "succeeded"
                result["value"] = outcome[1]
                break
            if outcome[0] == "cancelled":
                result["status"] = "cancelled"
                break

            last_error = outcome[1]  # "timeout: ..." ou "Tipo: mensagem"
            if attempts <= step.retries:
                log.warn(
                    "Workflow step retrying",
                    step=step.id,
                    attempt=attempts,
                    retries=step.retries,
                    error=last_error,
                )
                if step.retry_delay > 0:
                    await asyncio.sleep(step.retry_delay)
                continue
            break

        result["attempts"] = attempts
        result["error"] = last_error
        result["finished_at"] = time.time()
        result["duration"] = round(result["finished_at"] - result["started_at"], 6)
        if result["status"] == "failed":
            log.warn(
                "Workflow step failed",
                step=step.id,
                attempts=attempts,
                error=last_error or "erro desconhecido",
            )
        return result

    async def _attempt(
        self,
        run_state: _RunState,
        step: WorkflowStep,
        ctx: WorkflowContext,
    ) -> tuple[str, Any]:
        """Executa uma tentativa do step, correndo contra cancelamento/timeout.

        Returns:
            ("ok", valor) | ("error", msg) | ("timeout", msg) |
            ("cancelled", None)
        """
        cancel_event = run_state.cancel_event

        async def run_coro() -> Any:
            if step.kind == "condition":
                if step.condition is None:
                    raise WorkflowValidationError(
                        f"Step condicional sem condition: {step.id}"
                    )
                res = step.condition(ctx)
                if inspect.isawaitable(res):
                    res = await res
                return bool(res)
            if step.kind == "workflow":
                if step.workflow is None:
                    raise WorkflowValidationError(
                        f"Step nested sem workflow alvo: {step.id}"
                    )
                if step.workflow not in self._specs:
                    raise WorkflowNotFoundError(
                        f"Sub-workflow não registrado: {step.workflow!r}"
                    )
                return await self.execute(
                    step.workflow,
                    input={**ctx.input, **ctx.variables},
                    parent_execution_id=run_state.execution.execution_id,
                    _cancel_event=cancel_event,
                )
            # kind == "action"
            if step.action is None:
                raise WorkflowValidationError(
                    f"Step de ação sem callable: {step.id}"
                )
            res = step.action(ctx)
            if inspect.isawaitable(res):
                res = await res
            return res

        coro: Any = run_coro()
        if step.timeout is not None:
            coro = asyncio.wait_for(coro, timeout=step.timeout)

        task = asyncio.ensure_future(coro)
        cancel_waiter = asyncio.ensure_future(cancel_event.wait())
        done, _pending = await asyncio.wait(
            {task, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED
        )

        if cancel_waiter in done:
            cancel_waiter.cancel()
            task.cancel()
            await asyncio.gather(task, cancel_waiter, return_exceptions=True)
            return ("cancelled", None)

        cancel_waiter.cancel()
        await asyncio.gather(cancel_waiter, return_exceptions=True)

        try:
            value = task.result()
        except asyncio.TimeoutError:
            return ("timeout", f"timeout após {step.timeout}s")
        except asyncio.CancelledError:
            return ("cancelled", None)
        except Exception as exc:
            return ("error", f"{type(exc).__name__}: {exc}")

        # Sub-workflow: traduz o status da execução filha
        if step.kind == "workflow":
            sub: WorkflowExecution = value
            if sub.status == "cancelled":
                return ("cancelled", None)
            if sub.status != "succeeded":
                return (
                    "error",
                    f"sub-workflow {step.workflow} falhou: {sub.error or sub.status}",
                )
            return (
                "ok",
                {
                    "execution_id": sub.execution_id,
                    "status": sub.status,
                    "output": dict(sub.output),
                },
            )
        return ("ok", value)

    # -- Event Bus -----------------------------------------------------------

    async def _publish_event(self, topic: str, **data: Any) -> None:
        """Publica um evento no bus (best-effort; nunca quebra o run)."""
        if self._event_bus is None or not getattr(
            self._event_bus, "running", False
        ):
            return
        try:
            from core.event_bus import Event

            await self._event_bus.publish(
                Event(topic=topic, data=dict(data), source="workflow_engine")
            )
        except Exception as exc:
            log.warn(
                "Workflow event publish failed",
                topic=topic,
                error=type(exc).__name__,
            )

    # -- Persistência --------------------------------------------------------

    def _persist(self, execution: WorkflowExecution) -> None:
        """Grava a execução em disco (JSON atômico, best-effort)."""
        if self._base_dir is None:
            return
        try:
            path = self._base_dir / f"{execution.execution_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(
                    execution.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except Exception as exc:
            log.crit(
                "Workflow execution persist failed",
                execution=execution.execution_id,
                error=type(exc).__name__,
            )

    def load_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Carrega uma execução da memória ou do disco."""
        execution = self._executions.get(execution_id)
        if execution is not None:
            return execution
        if self._base_dir is None:
            return None
        path = self._base_dir / f"{execution_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WorkflowExecution.from_dict(data)
        except Exception as exc:
            log.warn(
                "Workflow execution load failed",
                execution=execution_id,
                error=type(exc).__name__,
            )
            return None

    def list_executions(self) -> list[str]:
        """Lista ids de execuções persistidas (disco + memória)."""
        ids: list[str] = []
        if self._base_dir is not None and self._base_dir.exists():
            ids.extend(
                p.stem for p in self._base_dir.glob("*.json") if p.is_file()
            )
        for exec_id in self._executions:
            if exec_id not in ids:
                ids.append(exec_id)
        return sorted(ids)

    def get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Execução em memória (ou None)."""
        return self._executions.get(execution_id)

    # -- Inspeção ------------------------------------------------------------

    @property
    def metrics(self) -> WorkflowMetrics:
        return self._metrics

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico do engine."""
        return {
            "workflows": len(self._specs),
            "registered": self.list(),
            "executions_in_memory": len(self._executions),
            "running": self._metrics.running,
            "persist_dir": str(self._base_dir) if self._base_dir else None,
            "metrics": self._metrics.snapshot(),
        }

    # -- Validação de specs --------------------------------------------------

    def _validate_spec(self, spec: WorkflowSpec) -> None:
        """Valida uma definição de workflow (eleva WorkflowValidationError)."""
        if not spec.id.strip():
            raise WorkflowValidationError("Workflow sem id")
        if not spec.steps:
            raise WorkflowValidationError(f"Workflow {spec.id!r} sem steps")

        ids: list[str] = []
        for step in spec.steps:
            if not step.id.strip():
                raise WorkflowValidationError(
                    f"Step sem id no workflow {spec.id!r}"
                )
            if step.id in ids:
                raise WorkflowValidationError(
                    f"Id de step duplicado no workflow {spec.id!r}: {step.id!r}"
                )
            ids.append(step.id)
            if step.kind not in STEP_KINDS:
                raise WorkflowValidationError(
                    f"Kind inválido {step.kind!r} no step {step.id!r}"
                )
            if step.kind == "condition" and step.condition is None:
                raise WorkflowValidationError(
                    f"Step condicional {step.id!r} sem condition"
                )
            if step.kind == "workflow" and not step.workflow:
                raise WorkflowValidationError(
                    f"Step nested {step.id!r} sem workflow alvo"
                )
            if step.retries < 0:
                raise WorkflowValidationError(
                    f"retries negativo no step {step.id!r}"
                )
            if step.retry_delay < 0:
                raise WorkflowValidationError(
                    f"retry_delay negativo no step {step.id!r}"
                )
            if step.timeout is not None and step.timeout <= 0:
                raise WorkflowValidationError(
                    f"timeout inválido no step {step.id!r}"
                )
            if step.on_error and step.on_error not in ON_ERROR_OPTIONS:
                raise WorkflowValidationError(
                    f"on_error inválido no step {step.id!r}: {step.on_error!r}"
                )

        if spec.default_on_error not in ON_ERROR_OPTIONS:
            raise WorkflowValidationError(
                f"default_on_error inválido em {spec.id!r}: "
                f"{spec.default_on_error!r}"
            )

        known = set(ids)
        for step in spec.steps:
            if step.next is not None and step.next not in known:
                raise WorkflowValidationError(
                    f"Step {step.id!r} aponta para next desconhecido {step.next!r}"
                )
            if step.kind == "condition":
                for target in (step.if_true_next, step.if_false_next):
                    if target is not None and target not in known:
                        raise WorkflowValidationError(
                            f"Step {step.id!r} aponta para branch desconhecido "
                            f"{target!r}"
                        )

        if spec.entry_step is not None and spec.entry_step not in known:
            raise WorkflowValidationError(
                f"entry_step desconhecido em {spec.id!r}: {spec.entry_step!r}"
            )
