"""
OMEGA DRAKON • CORE
Módulo: core/task_queue.py
Descrição: Task Queue (R1) — fila de tarefas assíncronas com RetryPolicy declarativo.
           Baseado no DAG Engine do NV (dag_engine.py) e Scheduler Engine (scheduler_engine.py).

Arquitetura:
- Task: unidade de trabalho (action_name + payload + metadata)
- Queue: fila FIFO com prioridade (priority queue)
- Worker: processa tasks, executa via ActionRegistry
- RetryPolicy: por task/action (max_retries, backoff, retry_on)
- Dead Letter: tasks que falham após max_retries → dead_letter queue
- Persistência: JSON (data/task_queue/) — pode migrar para Redis/RQ

Integração:
- Orchestrator pode enfileirar tasks longas (download, treino, etc.)
- API REST: POST /api/v1/tasks, GET /api/v1/tasks/{id}
- Health check: queue_depth, workers, dead_letter_count

Configuração via env:
- OD_TASK_QUEUE_ENABLED=1 (default 0)
- OD_TASK_QUEUE_WORKERS=2
- OD_TASK_QUEUE_MAX_RETRIES=3
- OD_TASK_QUEUE_BACKOFF_BASE=5 (seconds)
- OD_TASK_QUEUE_KEEP_COMPLETED=200 (histórico de concluídas em disco; poda
  automática das mais antigas ao concluir e no start)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.registry import ActionRegistry

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.task_queue")

# Config via env
ENABLED = os.getenv("OD_TASK_QUEUE_ENABLED", "0") != "0"
DEFAULT_WORKERS = int(os.getenv("OD_TASK_QUEUE_WORKERS", "2"))
DEFAULT_MAX_RETRIES = int(os.getenv("OD_TASK_QUEUE_MAX_RETRIES", "3"))
DEFAULT_BACKOFF_BASE = float(os.getenv("OD_TASK_QUEUE_BACKOFF_BASE", "5.0"))
DEFAULT_KEEP_COMPLETED = int(os.getenv("OD_TASK_QUEUE_KEEP_COMPLETED", "200"))
QUEUE_DIR = Path(os.getenv("OD_TASK_QUEUE_DIR", "data/task_queue"))


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class RetryPolicy:
    """Política de retry declarativa por action ou global."""

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_max: float = 300.0,
        retry_on: Optional[tuple[type[Exception], ...]] = None,
        timeout_seconds: float = 0.0,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.retry_on = retry_on or (Exception,)
        self.timeout_seconds = timeout_seconds

    def should_retry(self, attempt: int, exc: Exception) -> bool:
        if attempt >= self.max_retries:
            return False
        return isinstance(exc, self.retry_on)

    def backoff(self, attempt: int) -> float:
        """Exponential backoff com jitter."""
        import random
        base = min(self.backoff_base * (2 ** attempt), self.backoff_max)
        return base * (0.5 + random.random())  # jitter 50-100%


@dataclass(slots=True)
class Task:
    """Tarefa a ser executada."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action_name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # maior = mais prioritário
    status: TaskStatus = TaskStatus.PENDING
    created_ts: float = field(default_factory=time.time)
    started_ts: float = 0.0
    finished_ts: float = 0.0
    attempts: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    last_error: str = ""
    result: Optional[dict[str, Any]] = None
    retry_policy: Optional[RetryPolicy] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "action_name": self.action_name,
            "payload": self.payload,
            "metadata": self.metadata,
            "priority": self.priority,
            "status": self.status.value,
            "created_ts": self.created_ts,
            "started_ts": self.started_ts,
            "finished_ts": self.finished_ts,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "last_error": self.last_error,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        task = cls(
            task_id=data["task_id"],
            action_name=data["action_name"],
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            priority=data.get("priority", 0),
            status=TaskStatus(data.get("status", "pending")),
            created_ts=data.get("created_ts", time.time()),
            started_ts=data.get("started_ts", 0.0),
            finished_ts=data.get("finished_ts", 0.0),
            attempts=data.get("attempts", 0),
            max_retries=data.get("max_retries", DEFAULT_MAX_RETRIES),
            last_error=data.get("last_error", ""),
            result=data.get("result"),
        )
        if data.get("retry_policy"):
            rp = data["retry_policy"]
            task.retry_policy = RetryPolicy(
                max_retries=rp.get("max_retries", DEFAULT_MAX_RETRIES),
                backoff_base=rp.get("backoff_base", DEFAULT_BACKOFF_BASE),
            )
        return task


class TaskQueue:
    """Fila de tarefas com persistência em JSON + workers assíncronos."""

    def __init__(
        self,
        queue_dir: Path = QUEUE_DIR,
        action_registry: Optional["ActionRegistry"] = None,
        workers: int = DEFAULT_WORKERS,
        default_retry_policy: Optional[RetryPolicy] = None,
        keep_completed: int = DEFAULT_KEEP_COMPLETED,
    ) -> None:
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        # Fica DENTRO do queue_dir: com o diretório global do módulo, um
        # teste (ou uma instância com outro diretório) gravava dead letters
        # em `data/task_queue/dead_letter` mesmo usando tmp_path.
        self.dead_letter_dir = self.queue_dir / "dead_letter"
        self.dead_letter_dir.mkdir(parents=True, exist_ok=True)
        # Histórico de concluídas em subdiretório próprio: `_load_pending`
        # faz glob de `queue_dir/*.json` e não pode ver concluídas como
        # pendentes. A poda mantém só as `keep_completed` mais recentes.
        self.completed_dir = self.queue_dir / "completed"
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        self._keep_completed = max(0, keep_completed)

        self._action_registry = action_registry
        self._workers = max(1, workers)
        self._default_retry_policy = default_retry_policy or RetryPolicy()

        self._pending: list[Task] = []  # priority queue (manual sort)
        self._running: dict[str, Task] = {}
        self._lock = threading.RLock()
        self._worker_tasks: list[asyncio.Task] = []
        self._running_flag = False
        self._shutdown_event = asyncio.Event()

        # Métricas
        self._metrics = {
            "enqueued": 0,
            "completed": 0,
            "failed": 0,
            "dead_letter": 0,
            "retried": 0,
        }

    def set_action_registry(self, registry: "ActionRegistry") -> None:
        with self._lock:
            self._action_registry = registry

    def enqueue(
        self,
        action_name: str,
        payload: dict[str, Any],
        *,
        priority: int = 0,
        metadata: Optional[dict[str, Any]] = None,
        retry_policy: Optional[RetryPolicy] = None,
        task_id: Optional[str] = None,
    ) -> Task:
        """Adiciona task à fila (thread-safe)."""
        task = Task(
            task_id=task_id or str(uuid.uuid4()),
            action_name=action_name,
            payload=payload,
            metadata=metadata or {},
            priority=priority,
            retry_policy=retry_policy,
            max_retries=retry_policy.max_retries if retry_policy else DEFAULT_MAX_RETRIES,
        )

        with self._lock:
            self._pending.append(task)
            self._pending.sort(key=lambda t: (-t.priority, t.created_ts))
            self._metrics["enqueued"] += 1
            self._persist_task(task)

        log.debug("Task enfileirada", task_id=task.task_id, action=action_name, priority=priority)
        return task

    def _persist_task(self, task: Task) -> None:
        """Persiste task individual (para recuperação após restart)."""
        try:
            path = self.queue_dir / f"{task.task_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            log.warn("TaskQueue: falha ao persistir task", task_id=task.task_id, error=str(exc))

    def _load_pending(self) -> int:
        """Carrega tasks pendentes do disco (recuperação após restart)."""
        loaded = 0
        with self._lock:
            # O enqueue já persiste e mantém a task em memória: sem este
            # conjunto a mesma task entrava duas vezes e rodava duas vezes
            # no primeiro `start()` (medido: métrica `completed` = 2 para 1).
            conhecidas = {t.task_id for t in self._pending}
            conhecidas.update(self._running)
            for path in self.queue_dir.glob("*.json"):
                if path.name.startswith("dead_letter"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    task = Task.from_dict(data)
                    if task.task_id in conhecidas:
                        continue
                    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                        task.status = TaskStatus.PENDING
                        task.attempts = 0
                        self._pending.append(task)
                        loaded += 1
                    elif task.status == TaskStatus.FAILED and task.attempts < task.max_retries:
                        task.status = TaskStatus.PENDING
                        self._pending.append(task)
                        loaded += 1
                except Exception as exc:
                    log.warn("TaskQueue: falha ao carregar task", file=path.name, error=str(exc))
            self._pending.sort(key=lambda t: (-t.priority, t.created_ts))
        return loaded

    async def start(self) -> None:
        """Inicia workers."""
        if self._running_flag:
            return

        loaded = self._load_pending()
        if loaded:
            log.info("TaskQueue: tasks recuperadas do disco", count=loaded)
        podadas = self._prune_completed()
        if podadas:
            log.info("TaskQueue: histórico de concluídas podado", removidas=podadas)

        self._running_flag = True
        self._shutdown_event.clear()

        for i in range(self._workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"task-queue-worker-{i}")
            self._worker_tasks.append(task)

        log.info("TaskQueue iniciado", workers=self._workers, pending=len(self._pending))

    async def stop(self, timeout: float = 30.0) -> None:
        """Para workers graciosamente."""
        if not self._running_flag:
            return

        self._running_flag = False
        self._shutdown_event.set()

        # Aguarda workers finalizarem task atual
        if self._worker_tasks:
            done, pending = await asyncio.wait(
                self._worker_tasks,
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        self._worker_tasks.clear()
        log.info("TaskQueue parado", metrics=self._metrics)

    async def _worker_loop(self, worker_id: int) -> None:
        """Loop do worker: pega task, executa, trata retry/falha."""
        while self._running_flag:
            task = None
            with self._lock:
                if self._pending:
                    task = self._pending.pop(0)

            if task is None:
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                continue

            if not self._running_flag:
                # Recoloca na fila se parando
                with self._lock:
                    self._pending.insert(0, task)
                break

            await self._execute_task(task)

    async def _execute_task(self, task: Task) -> None:
        """Executa uma task com retry policy."""
        if self._action_registry is None:
            task.status = TaskStatus.FAILED
            task.last_error = "ActionRegistry não configurado"
            await self._handle_failure(task)
            return

        task.status = TaskStatus.RUNNING
        task.started_ts = time.time()
        task.attempts += 1
        self._running[task.task_id] = task
        self._persist_task(task)

        retry_policy = task.retry_policy or self._default_retry_policy

        try:
            if retry_policy.timeout_seconds > 0:
                result = await asyncio.wait_for(
                    self._action_registry.execute(
                        task.action_name,
                        params=task.payload,
                        role=task.metadata.get("role", "admin"),
                        # ActionRegistry.execute usa `session_id` (era
                        # `request_id`: TypeError em TODA task real — o teste
                        # antigo passava porque o registry falso aceita
                        # **kwargs).
                        session_id=task.task_id,
                    ),
                    timeout=retry_policy.timeout_seconds,
                )
            else:
                result = await self._action_registry.execute(
                    task.action_name,
                    params=task.payload,
                    role=task.metadata.get("role", "admin"),
                    session_id=task.task_id,
                )

            if result.status == "ok":
                task.status = TaskStatus.COMPLETED
                task.result = result.data
                task.finished_ts = time.time()
                with self._lock:
                    self._metrics["completed"] += 1
                # Histórico: fica visível em GET/lista até a poda (antes o
                # registro era apagado e a task recém-concluída virava 404).
                self._persist_completed(task)
            else:
                raise RuntimeError(f"Action falhou: {result.error} ({result.status})")

        except Exception as exc:
            task.last_error = str(exc)
            if retry_policy.should_retry(task.attempts, exc):
                task.status = TaskStatus.PENDING
                task.finished_ts = 0.0
                backoff = retry_policy.backoff(task.attempts)
                log.info("Task agendada para retry", task_id=task.task_id, attempt=task.attempts, backoff=round(backoff, 1))
                await asyncio.sleep(backoff)
                with self._lock:
                    self._pending.append(task)
                    self._pending.sort(key=lambda t: (-t.priority, t.created_ts))
                    self._metrics["retried"] += 1
                self._persist_task(task)
            else:
                await self._handle_failure(task)
        finally:
            self._running.pop(task.task_id, None)
            # Remove o arquivo da fila SÓ quando a task terminou: em retry ela
            # volta para a fila e o JSON é a garantia de sobreviver a um
            # restart (antes o finally apagava o arquivo recém-persistido).
            # A concluída é preservada em `completed/`; o dead letter é
            # preservado em `dead_letter/`.
            if task.status in (TaskStatus.COMPLETED, TaskStatus.DEAD_LETTER):
                try:
                    (self.queue_dir / f"{task.task_id}.json").unlink(missing_ok=True)
                except Exception:
                    pass
            if task.status == TaskStatus.COMPLETED:
                self._prune_completed()

    def _persist_completed(self, task: Task) -> None:
        """Grava o registro da task concluída no histórico (best-effort)."""
        try:
            path = self.completed_dir / f"{task.task_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            log.warn("TaskQueue: falha ao arquivar task concluída",
                     task_id=task.task_id, error=str(exc))

    def _prune_completed(self) -> int:
        """Mantém só as `_keep_completed` concluídas mais recentes (por
        `finished_ts`; mtime do arquivo como reserva). Devolve quantas saíram."""
        limite = self._keep_completed
        try:
            caminhos = list(self.completed_dir.glob("*.json"))
        except OSError:
            return 0
        if len(caminhos) <= limite:
            return 0

        def ordem(path: Path) -> float:
            try:
                return float(json.loads(path.read_text(encoding="utf-8"))
                             .get("finished_ts") or path.stat().st_mtime)
            except Exception:
                try:
                    return path.stat().st_mtime
                except OSError:
                    return 0.0

        caminhos.sort(key=ordem)
        removidas = 0
        for path in caminhos[: len(caminhos) - limite]:
            try:
                path.unlink(missing_ok=True)
                removidas += 1
            except OSError:
                pass
        return removidas

    async def _handle_failure(self, task: Task) -> None:
        """Move task para dead letter após esgotar retries."""
        task.status = TaskStatus.DEAD_LETTER
        task.finished_ts = time.time()
        with self._lock:
            self._metrics["failed"] += 1
            self._metrics["dead_letter"] += 1
        try:
            path = self.dead_letter_dir / f"{task.task_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            log.error("TaskQueue: falha ao salvar dead letter", task_id=task.task_id, error=str(exc))
        log.error("Task movida para dead letter", task_id=task.task_id, error=task.last_error)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Busca task por ID (running, pending, concluída ou dead letter)."""
        with self._lock:
            if task_id in self._running:
                return self._running[task_id]
            for t in self._pending:
                if t.task_id == task_id:
                    return t
        # Tenta carregar do disco
        for path in [
            self.queue_dir / f"{task_id}.json",
            self.completed_dir / f"{task_id}.json",
            self.dead_letter_dir / f"{task_id}.json",
        ]:
            if path.exists():
                try:
                    return Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except Exception:
                    pass
        return None

    def list_tasks(self, status: Optional[TaskStatus] = None, limit: int = 100) -> list[Task]:
        """Lista tasks por status."""
        tasks = []
        with self._lock:
            for t in self._running.values():
                if status is None or t.status == status:
                    tasks.append(t)
            for t in self._pending:
                if status is None or t.status == status:
                    tasks.append(t)
        # Histórico de concluídas + dead letter do disco (mais recente no
        # arquivo; a ordenação final é prioridade/created_ts como o resto).
        for pasta in (self.completed_dir, self.dead_letter_dir):
            for path in pasta.glob("*.json"):
                try:
                    task = Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
                    if status is None or task.status == status:
                        tasks.append(task)
                except Exception:
                    pass
        tasks.sort(key=lambda t: (-t.priority, t.created_ts))
        return tasks[:limit]

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._metrics)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pending": len(self._pending),
                "running": len(self._running),
                "workers": self._workers,
                "metrics": dict(self._metrics),
            }


# Instância global (lazy init)
_global_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Retorna instância global da TaskQueue (cria se necessário)."""
    global _global_queue
    if _global_queue is None:
        _global_queue = TaskQueue()
    return _global_queue


def build_task_queue(action_registry: Optional["ActionRegistry"] = None) -> Optional[TaskQueue]:
    """Factory para integração no launcher (habilitada via OD_TASK_QUEUE_ENABLED=1)."""
    if not ENABLED:
        log.info("TaskQueue desabilitado (OD_TASK_QUEUE_ENABLED=0)")
        return None

    try:
        queue = TaskQueue(
            workers=DEFAULT_WORKERS,
            default_retry_policy=RetryPolicy(
                max_retries=DEFAULT_MAX_RETRIES,
                backoff_base=DEFAULT_BACKOFF_BASE,
            ),
            keep_completed=DEFAULT_KEEP_COMPLETED,
        )
        if action_registry:
            queue.set_action_registry(action_registry)
        log.info("TaskQueue construído", workers=DEFAULT_WORKERS)
        return queue
    except Exception as exc:
        log.warn("TaskQueue: falha ao construir", error=str(exc))
        return None