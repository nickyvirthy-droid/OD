"""
OMEGA DRAKON • CORE
Testes: tests/test_mcp_od.py — protocolo MCP do runtime/mcp_od.py.

Cobertura (guardas da casa — estado real, sem teclado):
   - handshake initialize / notifications/initialized / ping
   - tools/list com o catálogo REAL (123 actions) e inputSchema convertido
   - conversão de schema da casa (str/int/...) → JSON Schema
   - tools/call: execução real (datetime), unknown -32602, denied/error
     mapeados como isError, exceção do handler contida
   - método desconhecido -32601; notificação sem method ignorada
   - carregar_env não sobrescreve env existente
   - loop stdio: parse error → resposta honesta; notificação não gera linha
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from runtime import mcp_od
from tools.registry import ActionResult


class _RegFalso:
    """Registry falso: lista/resultado/exceção configuráveis."""

    def __init__(self, acoes=None, resultado=None, exc=None):
        self._acoes = acoes or []
        self._resultado = resultado
        self._exc = exc
        self.chamadas: list[dict] = []

    def list_actions(self):
        return list(self._acoes)

    def has(self, nome: str) -> bool:
        return any(a["name"] == nome for a in self._acoes)

    async def execute(self, nome, *, params=None, role="", session_id=""):
        self.chamadas.append({"nome": nome, "params": params or {},
                              "role": role, "session_id": session_id})
        if self._exc is not None:
            raise self._exc
        return self._resultado or ActionResult(action=nome, status="ok")


# -- Schema ------------------------------------------------------------------

class TestConversaoDeSchema:
    def test_tipos_da_casa_viram_json_schema(self) -> None:
        schema = mcp_od.params_para_json_schema({
            "required": ["termo"],
            "properties": {"termo": {"type": "str"},
                           "limite": {"type": "int", "default": 10},
                           "forca": {"type": "bool", "default": False},
                           "ratio": {"type": "float", "default": 0.5}},
        })
        assert schema["type"] == "object"
        assert schema["required"] == ["termo"]
        assert schema["properties"]["termo"]["type"] == "string"
        assert schema["properties"]["limite"]["type"] == "integer"
        assert schema["properties"]["limite"]["default"] == 10
        assert schema["properties"]["forca"]["type"] == "boolean"
        assert schema["properties"]["ratio"]["type"] == "number"

    def test_tipo_desconhecido_cai_em_string(self) -> None:
        schema = mcp_od.params_para_json_schema(
            {"properties": {"x": {"type": "coisa_rara"}}})
        assert schema["properties"]["x"]["type"] == "string"

    def test_params_vazio_vira_objeto_sem_props(self) -> None:
        assert mcp_od.params_para_json_schema({}) == {
            "type": "object", "properties": {}}


# -- tools/list --------------------------------------------------------------

class TestToolsList:
    def test_catalogo_real_completo_e_convertido(self) -> None:
        from tools.actions import build_registry
        tools = mcp_od.ferramentas_do_registry(build_registry())
        assert len(tools) == 123
        for t in tools:
            assert t["name"] and t["inputSchema"]["type"] == "object"
        busca = next(t for t in tools if t["name"] == "flatnotes_busca")
        assert busca["inputSchema"]["required"] == ["termo"]
        assert busca["inputSchema"]["properties"]["termo"]["type"] == "string"
        assert "[flatnotes]" in busca["description"]

    def test_inativas_fora_da_lista(self) -> None:
        reg = _RegFalso(acoes=[
            {"name": "viva", "active": True, "params": {}},
            {"name": "morta", "active": False, "params": {}},
        ])
        tools = mcp_od.ferramentas_do_registry(reg)
        assert [t["name"] for t in tools] == ["viva"]


# -- Protocolo ---------------------------------------------------------------

class TestProtocolo:
    def test_initialize_handshake(self) -> None:
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}}, _RegFalso(), {})
        assert resp["id"] == 1
        r = resp["result"]
        assert r["protocolVersion"] == "2024-11-05"
        assert r["serverInfo"]["name"] == "omega-drakon"
        assert "tools" in r["capabilities"]

    def test_notificacao_inicializada_sem_resposta(self) -> None:
        assert mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _RegFalso(), {}) is None

    def test_ping(self) -> None:
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 9, "method": "ping"}, _RegFalso(), {})
        assert resp == {"jsonrpc": "2.0", "id": 9, "result": {}}

    def test_metodo_desconhecido_32601(self) -> None:
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
            _RegFalso(), {})
        assert resp["error"]["code"] == -32601

    def test_sem_method_ignora(self) -> None:
        assert mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 1, "result": {}}, _RegFalso(), {}) is None


class TestToolsCall:
    def test_executa_acao_real_de_ponta_a_ponta(self) -> None:
        """datetime via registry REAL — prova o caminho inteiro."""
        from tools.actions import build_registry
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "datetime", "arguments": {}}},
            build_registry(), {})
        conteudo = json.loads(resp["result"]["content"][0]["text"])
        assert resp["result"]["isError"] is False
        assert conteudo["status"] == "ok"
        assert conteudo["data"]  # tem data/hora

    def test_ferramenta_desconhecida_32602(self) -> None:
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "nao_existe", "arguments": {}}},
            _RegFalso(acoes=[{"name": "outra", "active": True}]), {})
        assert resp["error"]["code"] == -32602

    def test_denied_vira_iserror_como_resposta(self) -> None:
        reg = _RegFalso(
            acoes=[{"name": "x", "active": True, "params": {}}],
            resultado=ActionResult(action="x", status="denied",
                                   denied_by="policy"))
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": "x", "arguments": {}}}, reg, {})
        assert resp["result"]["isError"] is True
        assert "denied" in resp["result"]["content"][0]["text"]

    def test_excecao_no_handler_contida(self) -> None:
        reg = _RegFalso(
            acoes=[{"name": "boom", "active": True, "params": {}}],
            exc=RuntimeError("explodiu"))
        resp = mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
             "params": {"name": "boom", "arguments": {}}}, reg, {})
        assert resp["result"]["isError"] is True
        assert "explodiu" in resp["result"]["content"][0]["text"]

    def test_role_admin_e_sessao_mcp(self) -> None:
        reg = _RegFalso(
            acoes=[{"name": "x", "active": True, "params": {}}])
        mcp_od.tratar_mensagem(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
             "params": {"name": "x", "arguments": {"k": 1}}}, reg, {})
        assert reg.chamadas[0]["role"] == "admin"
        assert reg.chamadas[0]["session_id"] == "mcp"
        assert reg.chamadas[0]["params"] == {"k": 1}


# -- Env ---------------------------------------------------------------------

class TestCarregarEnv:
    def test_nao_sobrescreve_existente(self, tmp_path: Path,
                                       monkeypatch) -> None:
        alvo = tmp_path / ".env"
        alvo.write_text("# comentario\nNOVO=abc\nEXISTE=deveria_ignorar\n")
        monkeypatch.setenv("EXISTE", "do_ambiente")
        monkeypatch.delenv("NOVO", raising=False)
        mcp_od.carregar_env(alvo)
        assert os.environ["NOVO"] == "abc"
        assert os.environ["EXISTE"] == "do_ambiente"

    def test_arquivo_ausente_nao_quebra(self, tmp_path: Path) -> None:
        mcp_od.carregar_env(tmp_path / "nao_existe.env")  # sem exceção


# -- Loop stdio --------------------------------------------------------------

class TestLoopStdio:
    @pytest.fixture(autouse=True)
    def _nao_carrega_env_real(self, monkeypatch, tmp_path: Path) -> None:
        # `principal()` chama carregar_env() no .env real; num teste isso
        # derramaria OD_ORCHESTRATOR_GRAPH/OD_QUERY_ROUTER_* no os.environ
        # global e mudaria a rota dos módulos seguintes da suíte.
        monkeypatch.setenv("OD_MCP_ENV", str(tmp_path / "sem.env"))

    def test_parse_error_responde_e_notificacao_nao(self) -> None:
        entrada = io.StringIO(
            '{invalido\n'
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        saida = io.StringIO()
        rc = mcp_od.principal(entrada=entrada, saida=saida)
        assert rc == 0
        linhas = [json.loads(l) for l in saida.getvalue().splitlines()]
        # parse error + initialize (a notificação não gera linha)
        assert len(linhas) == 2
        assert linhas[0]["error"]["code"] == -32700
        assert linhas[1]["result"]["serverInfo"]["name"] == "omega-drakon"
