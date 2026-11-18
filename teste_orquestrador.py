"""Módulo de orquestração de tarefas genérico."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class TaskStatus(Enum):
    """Estados possíveis de uma tarefa."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult(Generic[R]):
    """Resultado da execução de uma tarefa."""
    task_id: str
    status: TaskStatus
    result: R | None = None
    error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Task(ABC, Generic[T, R]):
    """Classe base abstrata para tarefas executáveis."""

    def __init__(self, task_id: str, name: str, payload: T) -> None:
        self.task_id = task_id
        self.name = name
        self.payload = payload
        self.status = TaskStatus.PENDING

    @abstractmethod
    async def execute(self) -> R:
        """Executa a lógica da tarefa."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Reverte alterações em caso de falha."""
        pass


class Orchestrator:
    """Orquestrador de tarefas com suporte a execução paralela e sequencial."""

    def __init__(self, max_concurrent: int = 5) -> None:
        self.max_concurrent = max_concurrent
        self._tasks: dict[str, Task[Any, Any]] = {}
        self._results: dict[str, TaskResult[Any]] = {}
        self._semaphore: asyncio.Semaphore | None = None

    async def add_task(self, task: Task[Any, Any]) -> None:
        """Adiciona uma tarefa ao orquestrador."""
        if task.task_id in self._tasks:
            raise ValueError(f"Task with id {task.task_id} already exists")
        self._tasks[task.task_id] = task

    async def execute_all(self) -> dict[str, TaskResult[Any]]:
        """Executa todas as tarefas registradas."""
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        coroutines = [self._execute_task(task) for task in self._tasks.values()]
        await asyncio.gather(*coroutines, return_exceptions=True)
        return self._results

    async def _execute_task(self, task: Task[Any, Any]) -> None:
        async with self._semaphore:
            task.status = TaskStatus.RUNNING
            logger.info("Starting task %s", task.task_id)
            try:
                result = await task.execute()
                task.status = TaskStatus.COMPLETED
                self._results[task.task_id] = TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    result=result,
                )
                logger.info("Task %s completed", task.task_id)
            except Exception as e:
                task.status = TaskStatus.FAILED
                await task.rollback()
                self._results[task.task_id] = TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    error=e,
                )
                logger.error("Task %s failed: %s", task.task_id, e)

    def get_result(self, task_id: str) -> TaskResult[Any] | None:
        """Retorna o resultado de uma tarefa específica."""
        return self._results.get(task_id)

    def get_all_results(self) -> dict[str, TaskResult[Any]]:
        """Retorna todos os resultados."""
        return self._results.copy()


class SimpleTask(Task[T, R]):
    """Implementação simples de tarefa com função callable."""

    def __init__(
        self,
        task_id: str,
        name: str,
        payload: T,
        executor: Callable[[T], R],
        rollback_fn: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(task_id, name, payload)
        self._executor = executor
        self._rollback_fn = rollback_fn

    async def execute(self) -> R:
        return self._executor(self.payload)

    async def rollback(self) -> None:
        if self._rollback_fn:
            self._rollback_fn()


async def main() -> None:
    """Exemplo de uso do orquestrador."""
    logging.basicConfig(level=logging.INFO)

    orchestrator = Orchestrator(max_concurrent=3)

    def process_data(data: dict[str, int]) -> dict[str, int]:
        return {k: v * 2 for k, v in data.items()}

    def rollback_data() -> None:
        logger.info("Rolling back data changes")

    task1 = SimpleTask("task-1", "Process Batch 1", {"a": 1, "b": 2}, process_data, rollback_data)
    task2 = SimpleTask("task-2", "Process Batch 2", {"c": 3, "d": 4}, process_data, rollback_data)

    await orchestrator.add_task(task1)
    await orchestrator.add_task(task2)

    results = await orchestrator.execute_all()

    for task_id, result in results.items():
        print(f"{task_id}: {result.status.value} - {result.result}")


if __name__ == "__main__":
    asyncio.run(main())