# NV DAG Engine + Scheduler Engine — Referência para R1 (Task Queue)

> Extraído de `data/refs_todo/NV/NV v1.9.X/workflows/` (nested-workflows.tar.gz, v1.9.2)
> Data: 2026-11-13

---

## 1. WorkflowDAGEngine (dag_engine.py — 347 linhas)

### Responsabilidade
Executa workflows definidos como DAG (Directed Acyclic Graph) com:
- **Paralelismo por estágios** (`asyncio.gather` em `_execute_stage`)
- **Retry por step** (configurável `retry_count`, `retry_delay`)
- **Timeout por step** (`step.timeout` via `asyncio.wait_for`)
- **Contexto de execução** (`WorkflowContext`) com passagem de resultados entre steps (`_inputs` = resultados de dependências)
- **Eventos** emitidos via `kernel.events` (STARTED, STAGE_STARTED, PARALLEL_STARTED, STEP_STARTED, STEP_FINISHED, etc.)
- **Persistência** via `kernel.workflow_repo.save(execution)`

### Fluxo Principal
```
execute(workflow, execution, kernel)
  → WorkflowScheduler.build_stages()  # ordenação topológica
  → para cada stage (lista de step_ids):
      → _execute_stage(stage_nodes)
          → asyncio.gather(_execute_step para cada step_id)
              → _execute_step(step)
                  → monta payload + _inputs (resultados de dependências)
                  → retry loop (até retry_count)
                      → kernel.actions.execute(action_name, payload) com timeout
                  → context.set_result(step_id, result)
                  → execution.results[step_id] = result
  → execution.status = COMPLETED/FAILED
  → kernel.workflow_repo.save(execution)
```

### Integração com Kernel
- `kernel.actions.execute(action_name, payload)` — executa action registrada
- `kernel.events.emit(event_name, data)` — bus de eventos
- `kernel.workflow_repo` — persistência de Execution
- `WorkflowScheduler(workflow).validate()` + `build_stages()` — validação + ordenação topológica

---

## 2. WorkflowSchedulerEngine (scheduler_engine.py — 413 linhas)

### Responsabilidade
Agenda execuções futuras de workflows com suporte a:
- **Once** (única execução em `run_at`)
- **Interval** (recorrência em segundos via `interval_seconds`)
- **Cron** (expressão cron via `croniter`)

### API
```python
schedule(workflow_id, run_at=None, metadata=None, interval_seconds=None, trigger_type="once", cron=None)
cancel(schedule_id)
start()  # inicia loop asyncio (1s sleep)
stop()   # cancela task
```

### Loop (`_loop`)
```python
while self._running:
    await self.execute_due()  # lista schedules enabled, filtra _is_due, executa
    await asyncio.sleep(1)
```

### Execução de Schedule (`_execute_schedule`)
```
→ kernel.events.emit(WORKFLOW_SCHEDULE_TRIGGERED)
→ kernel.workflows.execute(workflow_id)  # dispara DAG engine
→ schedule.last_run = now
→ _update_after_execution(schedule)
    → once: enabled=False, next_run=None
    → interval/cron: next_run = _compute_next_run(schedule)
→ repository.save_schedule(schedule)
```

### Persistência
- `WorkflowScheduleRepository` (interface): `save_schedule`, `list_schedules(enabled_only)`, `disable_schedule`
- Modelo: `WorkflowSchedule` (schedule_id, workflow_id, trigger_type, interval_seconds, cron, run_at, next_run, last_run, enabled, metadata)

---

## 3. Modelos de Dados (schedule_models.py)

```python
@dataclass
class WorkflowSchedule:
    schedule_id: str
    workflow_id: str
    trigger_type: str  # "once" | "interval" | "cron"
    interval_seconds: int | None
    cron: str | None
    run_at: datetime | None
    next_run: datetime | None
    last_run: datetime | None
    enabled: bool = True
    metadata: dict = field(default_factory=dict)
```

---

## 4. Testes Relevantes (8 testes de scheduler)

| Teste | Cenário |
|-------|---------|
| `test_workflow_scheduler.py` | Básico: schedule once + execução |
| `test_workflow_scheduler_interval.py` | Intervalo recorrente |
| `test_workflow_scheduler_cron.py` | Cron expression |
| `test_workflow_scheduler_cron_execution.py` | Execução real via cron |
| `test_workflow_scheduler_cancel.py` | Cancelamento |
| `test_workflow_scheduler_persistence.py` | Persistência entre restarts |
| `test_workflow_parallel.py` | Paralelismo no DAG |
| `test_workflow_retry.py` | Retry por step |

---

## 5. Como Usar no OmegaDrakon (R1 Task Queue)

### Opção A: Portar Direto (maior esforço)
- Copiar `dag_engine.py`, `scheduler_engine.py`, `scheduler.py`, `schedule_models.py`, `schedule_repository.py`, `context.py`, `models.py`, `registry.py`, `subworkflow.py`, `workflow_stack.py`
- Adaptar `kernel.actions.execute` → `ActionRegistry.execute`
- Adaptar `kernel.events` → event bus simples (já existe em `core/orchestrator_graph.py`)
- Adaptar `kernel.workflow_repo` → persistência em SQLite/Postgres
- Adaptar `WorkflowScheduler` (topological sort) → usar `core/orchestrator_graph.py` ou reimplementar

### Opção B: Inspirar R1 com Redis/RQ (recomendado no TODO)
O TODO (§R1) prevê **Redis/RQ + RetryPolicy declarativo** — mais alinhado com:
- `core/resilience.py` (CircuitBreaker já existe)
- `core/orchestrator_graph.py` (RetryPolicy por nó já existe: `OD_RETRY_<NÓ>`)
- Infra Redis já existe (cache LLM)

**O que aproveitar do NV:**
1. **Modelo de schedule** (`WorkflowSchedule`) → mapear para job RQ com `meta={workflow_id, trigger_type, ...}`
2. **Retry por step** → `RetryPolicy` no grafo (já implementado)
3. **Timeout por step** → `OD_RETRY_<NÓ>` + timeout no `execute_action`
4. **Paralelismo por estágio** → `execute_parallel` no grafo (já implementado)
5. **Eventos** → logging estruturado + OTel spans (já existe)
6. **Persistência** → RQ armazena jobs no Redis; checkpoints no `data/checkpoints.db` (já existe)

### Gap Atual no OD
- Não há "workflow" como entidade de domínio (só orquestrador de chat)
- R1 Task Queue = fila de jobs genéricos (actions, workflows, tasks longas)
- Scheduler = systemd timers (já existem para backups, pg_dump, memory_consolidate, etc.)

**Próximo passo prático**: Implementar R1 com Redis/RQ usando o modelo de `WorkflowSchedule` como inspiração para job metadata, e o `RetryPolicy` do grafo como base para retry de jobs.

---

## 6. Arquivos de Referência (em `data/refs_todo/NV/NV v1.9.X/`)

```
workflows/
├── dag_engine.py           # 347 linhas — execução DAG paralela
├── scheduler_engine.py     # 413 linhas — agendamento once/interval/cron
├── scheduler.py            # WorkflowScheduler (validação + build_stages topológico)
├── schedule_models.py      # WorkflowSchedule dataclass
├── schedule_repository.py  # Interface persistência
├── context.py              # WorkflowContext (resultados entre steps)
├── models.py               # Workflow, Step, Execution models
├── registry.py             # Registry de workflows
├── subworkflow.py          # Suporte a sub-workflows
├── workflow_stack.py       # Stack de execução aninhada
tests/
├── test_workflow_scheduler*.py (8 testes)
├── test_workflow_parallel.py
├── test_workflow_retry.py
└── test_workflow_engine.py
```

---

*Referência para implementação de R1 Task Queue (Semanas 11-12 do roadmap).*