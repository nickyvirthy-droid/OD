"""
OMEGA DRAKON • TESTS
Módulo: tests/test_task_queue.py
Descrição: Task Queue (R1) — fila com prioridade, workers, RetryPolicy
           exponencial + jitter, dead letter e persistência JSON; e as rotas
           /admin/tasks* da API (criação, listagem, detalhe, retry, 503 com
           a fila desligada).

Por que estes testes existem: o módulo entrou em 13/11 sem nenhuma cobertura.
Os dois casos marcados "regressão" cobrem defeitos medidos antes do fechamento
do lote: dead letter gravado fora do `queue_dir` e o JSON da task apagado no
`finally` justamente quando ela voltava para retry.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.task_queue import RetryPolicy, TaskQueue, TaskStatus


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

class _RegistryFalso:
    """ActionRegistry mínimo: executa, falha ou conta chamadas."""

    def __init__(self, falhar: bool = False) -> None:
        self.falhar = falhar
        self.chamadas: list[dict] = []

    async def execute(self, action_name, params=None, role="admin",
                      request_id="", **kwargs):
        self.chamadas.append(
            {"action": action_name, "params": params, "role": role,
             "request_id": request_id}
        )
        if self.falhar:
            return SimpleNamespace(status="error", data=None, error="boom")
        return SimpleNamespace(status="ok", data={"echo": action_name}, error=None)


def _request(port, method, path, api_key=None, body=None):
    import json as _json

    data = _json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method
    )
    if api_key:
        request.add_header("X-API-Key", api_key)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_body(resposta: bytes) -> dict:
    return json.loads(resposta.decode() or "{}")


@pytest.fixture()
def fila(tmp_path: Path) -> TaskQueue:
    return TaskQueue(queue_dir=tmp_path / "fila", action_registry=_RegistryFalso())


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------

class TestFila:
    def test_enqueue_persiste_e_ordena_por_prioridade(self, fila: TaskQueue) -> None:
        baixa = fila.enqueue("system_info", {}, priority=0)
        alta = fila.enqueue("system_info", {}, priority=5)
        media = fila.enqueue("system_info", {}, priority=1)

        pendentes = fila.list_tasks()
        assert [t.task_id for t in pendentes] == [
            alta.task_id, media.task_id, baixa.task_id
        ]
        assert fila.metrics()["enqueued"] == 3
        # Cada task nasce persistida (recuperação após restart).
        for t in (baixa, alta, media):
            assert (fila.queue_dir / f"{t.task_id}.json").exists()

    def test_payload_metadata_e_role_viajam(self, fila: TaskQueue) -> None:
        t = fila.enqueue(
            "filesystem_write",
            {"path": "data/x.txt"},
            metadata={"role": "user"},
            retry_policy=RetryPolicy(max_retries=7),
        )
        assert t.max_retries == 7
        assert t.payload == {"path": "data/x.txt"}
        assert t.metadata == {"role": "user"}

    def test_get_task_acha_pendente_e_devolve_none_desconhecida(
        self, fila: TaskQueue
    ) -> None:
        t = fila.enqueue("system_info", {})
        assert fila.get_task(t.task_id).task_id == t.task_id
        assert fila.get_task("nao-existe") is None

    def test_load_pending_recupera_apos_restart(self, tmp_path: Path) -> None:
        original = TaskQueue(queue_dir=tmp_path / "fila", action_registry=_RegistryFalso())
        t = original.enqueue("system_info", {}, priority=2)

        # Instância nova (como num restart) aponta para o mesmo diretório.
        nova = TaskQueue(queue_dir=tmp_path / "fila", action_registry=_RegistryFalso())
        assert nova.list_tasks() == []  # ainda não carregou do disco
        assert nova._load_pending() == 1
        assert [x.task_id for x in nova.list_tasks()] == [t.task_id]

    def test_status_invalido_no_disco_e_ignorado(self, tmp_path: Path) -> None:
        fila = TaskQueue(queue_dir=tmp_path / "fila", action_registry=_RegistryFalso())
        (fila.queue_dir / "quebrada.json").write_text("{nao e json", encoding="utf-8")
        assert fila._load_pending() == 0


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class TestWorkers:
    @pytest.mark.asyncio
    async def test_executa_task_e_marca_completed(self, tmp_path: Path) -> None:
        registry = _RegistryFalso()
        fila = TaskQueue(queue_dir=tmp_path / "fila", action_registry=registry,
                         workers=1)
        t = fila.enqueue("system_info", {"x": 1}, metadata={"role": "admin"})
        await fila.start()
        await asyncio.sleep(0.2)
        await fila.stop()

        assert t.status == TaskStatus.COMPLETED
        assert t.result == {"echo": "system_info"}
        assert registry.chamadas[0]["role"] == "admin"
        assert fila.metrics()["completed"] == 1
        # Task concluída não fica no disco.
        assert not (fila.queue_dir / f"{t.task_id}.json").exists()

    @pytest.mark.asyncio
    async def test_sem_registry_vai_para_dead_letter(self, tmp_path: Path) -> None:
        fila = TaskQueue(queue_dir=tmp_path / "fila", workers=1)
        t = fila.enqueue("system_info", {})
        await fila.start()
        await asyncio.sleep(0.2)
        await fila.stop()

        assert t.status == TaskStatus.DEAD_LETTER
        assert "ActionRegistry" in t.last_error

    @pytest.mark.asyncio
    async def test_retry_depois_dead_letter(self, tmp_path: Path) -> None:
        """max_retries=2 com backoff zero: falha, retenta, esgota e morre."""
        fila = TaskQueue(queue_dir=tmp_path / "fila",
                         action_registry=_RegistryFalso(falhar=True), workers=1)
        t = fila.enqueue(
            "system_info", {},
            retry_policy=RetryPolicy(max_retries=2, backoff_base=0.0),
        )
        await fila.start()
        await asyncio.sleep(0.4)
        await fila.stop()

        assert t.status == TaskStatus.DEAD_LETTER
        assert fila.metrics()["retried"] == 1
        assert fila.metrics()["dead_letter"] == 1
        # REGRESSÃO (13/11): o dead letter nasce DENTRO do queue_dir da
        # instância — antes ia para `data/task_queue/dead_letter` global.
        assert (fila.dead_letter_dir / f"{t.task_id}.json").exists()
        assert fila.get_task(t.task_id).status == TaskStatus.DEAD_LETTER

    @pytest.mark.asyncio
    async def test_json_sobrevive_enquanto_espera_retry(self, tmp_path: Path) -> None:
        """REGRESSÃO (13/11): o `finally` apagava o JSON recém-persistido.

        Backoff de 300 s mantém a task parada no `sleep`: durante a espera o
        arquivo TEM de existir, senão um restart perde a task para sempre.
        """
        fila = TaskQueue(queue_dir=tmp_path / "fila",
                         action_registry=_RegistryFalso(falhar=True), workers=1)
        t = fila.enqueue(
            "system_info", {},
            retry_policy=RetryPolicy(max_retries=3, backoff_base=300.0),
        )
        executando = asyncio.create_task(fila._execute_task(t))
        await asyncio.sleep(0.1)

        assert t.status == TaskStatus.PENDING
        assert t.attempts == 1
        assert (fila.queue_dir / f"{t.task_id}.json").exists()

        executando.cancel()
        with pytest.raises(asyncio.CancelledError):
            await executando

    @pytest.mark.asyncio
    async def test_stop_encerra_workers(self, tmp_path: Path) -> None:
        fila = TaskQueue(queue_dir=tmp_path / "fila",
                         action_registry=_RegistryFalso(), workers=2)
        await fila.start()
        assert len(fila._worker_tasks) == 2
        await fila.stop()
        assert fila._worker_tasks == []


# ---------------------------------------------------------------------------
# API /admin/tasks*
# ---------------------------------------------------------------------------

@pytest.fixture()
def servidor_tasks(tmp_path: Path):
    from integrations.api import APIConfig, APIServer

    fila = TaskQueue(queue_dir=tmp_path / "api", action_registry=_RegistryFalso())
    cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                    auth_all=True, task_queue=fila)
    srv = APIServer(None, config=cfg)
    srv.serve_background()
    yield srv, fila
    srv.stop()


class TestTaskQueueAPI:
    def test_sem_credencial_401(self, servidor_tasks) -> None:
        srv, _ = servidor_tasks
        status, _ = _request(srv.bound_port, "GET", "/admin/tasks")
        assert status == 401

    def test_cria_lista_e_detalha(self, servidor_tasks) -> None:
        srv, fila = servidor_tasks
        status, corpo = _request(
            srv.bound_port, "POST", "/admin/tasks", api_key="segredo123",
            body={"action": "system_info", "payload": {}, "priority": 3},
        )
        assert status == 201, corpo
        task_id = _json_body(corpo)["task"]["task_id"]

        status, corpo = _request(srv.bound_port, "GET", "/admin/tasks",
                                 api_key="segredo123")
        assert status == 200
        data = _json_body(corpo)
        assert data["count"] == 1 and data["tasks"][0]["task_id"] == task_id

        status, corpo = _request(srv.bound_port, "GET", f"/admin/tasks/{task_id}",
                                 api_key="segredo123")
        assert status == 200
        assert _json_body(corpo)["task"]["action_name"] == "system_info"

    def test_corpo_invalido_e_status_invalido(self, servidor_tasks) -> None:
        srv, _ = servidor_tasks
        status, corpo = _request(srv.bound_port, "POST", "/admin/tasks",
                                 api_key="segredo123", body={"payload": {}})
        assert status == 400
        assert _json_body(corpo)["error"] == "action_obrigatoria"

        status, corpo = _request(srv.bound_port, "GET",
                                 "/admin/tasks?status=voando", api_key="segredo123")
        assert status == 400
        assert _json_body(corpo)["error"] == "status_invalido"

    def test_detalhe_inexistente_404(self, servidor_tasks) -> None:
        srv, _ = servidor_tasks
        status, _ = _request(srv.bound_port, "GET", "/admin/tasks/nada",
                             api_key="segredo123")
        assert status == 404

    def test_retry_de_pendente_409(self, servidor_tasks) -> None:
        srv, _ = servidor_tasks
        _, corpo = _request(srv.bound_port, "POST", "/admin/tasks",
                            api_key="segredo123", body={"action": "system_info"})
        task_id = _json_body(corpo)["task"]["task_id"]
        status, corpo = _request(srv.bound_port, "POST",
                                 f"/admin/tasks/{task_id}/retry",
                                 api_key="segredo123")
        assert status == 409
        assert _json_body(corpo)["error"] == "task_nao_terminal"

    def test_fila_desligada_503(self, tmp_path: Path) -> None:
        from integrations.api import APIConfig, APIServer

        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, task_queue=None)
        srv = APIServer(None, config=cfg)
        srv.serve_background()
        try:
            status, corpo = _request(srv.bound_port, "GET", "/admin/tasks",
                                     api_key="segredo123")
            assert status == 503
            assert _json_body(corpo)["error"] == "task_queue_indisponivel"
        finally:
            srv.stop()
