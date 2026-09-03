"""
OMEGA DRAKON • TESTS
Módulo: tests/test_tool_loader.py
Descrição: Testes do Tool Loader (tools/loader.py) — Fase 3, item 3.2:
           contratos de plugin, descoberta, hot-reload, validação de
           parâmetros, escopo estrito e métricas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/tool_loader.py
  - ROADMAP_ABSORCAO.md Fase 3, item 3.2
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tools.loader import (
    Tool,
    ToolLoader,
    ToolNotFoundError,
    ToolScopeError,
    ToolValidationError,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ===========================================================================
# ToolLoader — contrato PLUGIN
# ===========================================================================

class TestToolLoaderPluginContract:
    """Plugin declara PLUGIN = {..., "tools": [...]}."""

    def test_plugin_dict_contract(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "plugin_a.py",
            '''
PLUGIN = {
    "name": "plugin_a",
    "version": "1.0.0",
    "tools": [
        {
            "name": "say_hello",
            "description": "Diz olá",
            "category": "greetings",
            "fn": lambda ctx: "olá " + str(ctx),
            "params": {"name": {"type": "str", "required": True}},
        },
    ],
}
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        added = loader.load_all()
        assert added == 1
        tool = loader.get("say_hello")
        assert tool.category == "greetings"
        assert tool.description == "Diz olá"
        assert tool.version == "1.0.0"
        assert tool.source.endswith("plugin_a.py")
        assert tool.active

    def test_plugin_docstring_fallback(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "plugin_doc.py",
            '''
def double(x):
    """Multiplica por dois."""
    return x * 2

TOOLS = [double]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        tool = loader.get("double")
        assert tool.description == "Multiplica por dois."
        assert tool.active

    def test_plugin_requires_field(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "plugin_req.py",
            '''
def delete(path):
    """Remove arquivo."""
    return True

TOOLS = [{"name": "delete_file", "fn": delete, "requires": "filesystem.delete"}]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.get("delete_file").requires == "filesystem.delete"


# ===========================================================================
# ToolLoader — contratos TOOLS e load_tools
# ===========================================================================

class TestToolLoaderOtherContracts:
    """Contratos alternativos: TOOLS simples e função load_tools()."""

    def test_tools_list_of_callables(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "plugin_b.py",
            '''
def add(a, b):
    """Soma dois números."""
    return a + b

TOOLS = [add]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        tool = loader.get("add")
        assert tool.name == "add"
        assert tool.is_async is False

    def test_load_tools_function(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "plugin_c.py",
            '''
def ping():
    return "pong"

def load_tools():
    return [{"name": "ping", "fn": ping, "category": "network"}]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        tool = loader.get("ping")
        assert tool.category == "network"

    def test_priority_plugin_over_tools(self, tmp_path: Path) -> None:
        """PLUGIN tem prioridade sobre TOOLS no mesmo módulo."""
        _write(
            tmp_path,
            "plugin_d.py",
            '''
def first():
    return "plugin"

def second():
    return "tools"

PLUGIN = {"tools": [{"name": "choose", "fn": first}]}
TOOLS = [{"name": "choose", "fn": second}]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.get("choose").source.endswith("plugin_d.py")
        assert not loader.has("second")


# ===========================================================================
# ToolLoader — descoberta e robustez
# ===========================================================================

class TestToolLoaderDiscovery:
    """Descoberta de módulos e isolamento de falhas."""

    def test_ignores_non_py_and_underscore(self, tmp_path: Path) -> None:
        _write(tmp_path, "real_tool.py", 'TOOLS = [{"name": "real_tool", "fn": lambda: 1}]\n')
        _write(tmp_path, "README.md", "not python")
        _write(tmp_path, "_helper.py", 'TOOLS = [lambda: 2]\n')
        loader = ToolLoader(dirs=[tmp_path])
        assert loader.load_all() == 1
        assert loader.has("real_tool")

    def test_non_recursive_skips_subdirs(self, tmp_path: Path) -> None:
        sub = tmp_path / "nested"
        sub.mkdir()
        _write(sub, "deep_tool.py", 'TOOLS = [{"name": "tool_one", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[tmp_path], recursive=False)
        assert loader.load_all() == 0
        loader2 = ToolLoader(dirs=[tmp_path], recursive=True)
        assert loader2.load_all() == 1

    def test_missing_contract_module_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "no_contract.py", "x = 42\n")
        _write(tmp_path, "good.py", 'TOOLS = [{"name": "good", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[tmp_path])
        assert loader.load_all() == 1
        assert loader.metrics.modules_skipped == 1
        assert loader.has("good")

    def test_failing_import_does_not_break_others(self, tmp_path: Path) -> None:
        _write(tmp_path, "broken.py", "raise RuntimeError('import exploded')\n")
        _write(tmp_path, "fine.py", 'TOOLS = [{"name": "fine", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[tmp_path])
        assert loader.load_all() == 1
        assert loader.metrics.modules_failed == 1
        assert len(loader.errors) == 1
        assert "import exploded" in loader.errors[0]["error"]
        assert loader.has("fine")

    def test_invalid_tool_entry_recorded(self, tmp_path: Path) -> None:
        _write(tmp_path, "bad_tool.py", "TOOLS = [{'name': 'sem_fn'}]\n")
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        # registro da ferramenta falha silenciosamente (módulo conta como carregado)
        assert loader.metrics.modules_loaded == 1
        assert not loader.has("sem_fn")

    def test_load_dir_missing_raises(self, tmp_path: Path) -> None:
        loader = ToolLoader(dirs=[tmp_path])
        with pytest.raises(ToolNotFoundError):
            loader.load_dir(tmp_path / "nao_existe")

    def test_load_source_single_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "solo.py", 'TOOLS = [{"name": "tool_one", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[])
        assert loader.load_source(path) == 1
        assert len(loader.list_tools()) == 1


# ===========================================================================
# ToolLoader — escopo estrito
# ===========================================================================

class TestToolLoaderScope:
    """Arquivos fora dos diretórios-base são recusados."""

    def test_out_of_scope_dir_rejected(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        outside = tmp_path / "outside"
        base.mkdir()
        outside.mkdir()
        loader = ToolLoader(dirs=[base])
        with pytest.raises(ToolScopeError):
            loader.load_dir(outside)

    def test_out_of_scope_file_rejected(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        outside = tmp_path / "outside"
        base.mkdir()
        outside.mkdir()
        path = _write(outside, "evil.py", 'TOOLS = [{"name": "tool_one", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[base])
        with pytest.raises(ToolScopeError):
            loader.load_source(path)

    def test_in_scope_file_allowed(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        path = _write(base, "ok.py", 'TOOLS = [{"name": "tool_one", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[base])
        assert loader.load_source(path) == 1

    def test_no_dirs_means_unrestricted(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "free.py", 'TOOLS = [{"name": "tool_one", "fn": lambda: 1}]\n')
        loader = ToolLoader()
        assert loader.load_source(path) == 1


# ===========================================================================
# ToolLoader — registro manual, consulta e remoção
# ===========================================================================

class TestToolLoaderRegistry:
    """Registro explícito de ferramentas."""

    def test_register_tool_instance(self) -> None:
        loader = ToolLoader()
        tool = Tool(name="manual", fn=lambda x: x, description="manual")
        assert loader.register(tool) is True
        assert loader.has("manual")
        assert loader.get("manual") is tool

    def test_duplicate_name_skipped_by_default(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.py", "TOOLS = [{'name': 'dup', 'fn': lambda: 'a'}]\n")
        _write(tmp_path, "b.py", "TOOLS = [{'name': 'dup', 'fn': lambda: 'b'}]\n")
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.metrics.tools_loaded == 1
        assert loader.metrics.tools_skipped == 1
        assert loader.get("dup").source.endswith("a.py")

    def test_allow_overwrite_replaces(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.py", "TOOLS = [{'name': 'dup', 'fn': lambda: 'a'}]\n")
        _write(tmp_path, "b.py", "TOOLS = [{'name': 'dup', 'fn': lambda: 'b'}]\n")
        loader = ToolLoader(dirs=[tmp_path], allow_overwrite=True)
        loader.load_all()
        assert loader.metrics.tools_loaded == 2
        assert loader.get("dup").source.endswith("b.py")

    def test_get_unknown_raises(self) -> None:
        loader = ToolLoader()
        with pytest.raises(ToolNotFoundError):
            loader.get("ghost")

    def test_find_by_category(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "cat.py",
            '''
TOOLS = [
    {"name": "read", "fn": lambda: 1, "category": "filesystem"},
    {"name": "write", "fn": lambda: 2, "category": "filesystem"},
    {"name": "ping", "fn": lambda: 3, "category": "network"},
]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert [t.name for t in loader.find("filesystem")] == ["read", "write"]
        assert [t.name for t in loader.find("network")] == ["ping"]
        assert len(loader.find()) == 3

    def test_unload_and_clear(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "multi.py",
            '''
TOOLS = [
    {"name": "t1", "fn": lambda: 1},
    {"name": "t2", "fn": lambda: 2},
]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.unload("t1") is True
        assert loader.unload("t1") is False
        assert not loader.has("t1")
        assert loader.clear() == 1
        assert len(loader.list_tools()) == 0


# ===========================================================================
# ToolLoader — hot reload
# ===========================================================================

class TestToolLoaderReload:
    """Reload de ferramentas a partir do disco."""

    def test_reload_reflects_new_content(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "editable.py",
            '''
def greet(name="mundo"):
    """Saudação v1."""
    return f"olá, {name}!"

TOOLS = [{"name": "greet", "fn": greet, "description": "v1"}]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.get("greet").description == "v1"

        _write(
            tmp_path,
            "editable.py",
            '''
def greet(name="mundo"):
    """Saudação v2."""
    return f"oi, {name}!"

TOOLS = [{"name": "greet", "fn": greet, "description": "v2"}]
''',
        )
        assert loader.reload("greet") is True
        tool = loader.get("greet")
        assert tool.description == "v2"
        assert tool.source == str(path)

    def test_reload_failure_keeps_old_version(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "stable.py",
            '''
def stable():
    """Versão boa."""
    return "ok"

TOOLS = [{"name": "stable", "fn": stable}]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.get("stable").description == "Versão boa."

        # Quebra o arquivo: reload deve falhar SEM perder a ferramenta atual
        _write(tmp_path, "stable.py", "def stable(:\n    return broken\n")
        assert loader.reload("stable") is False
        assert loader.get("stable").description == "Versão boa."
        assert loader.metrics.modules_failed == 1

    def test_reload_all(self, tmp_path: Path) -> None:
        _write(tmp_path, "x.py", 'TOOLS = [{"name": "x", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        assert loader.reload_all() == 1
        assert loader.has("x")


# ===========================================================================
# Tool — invocação e validação de parâmetros
# ===========================================================================

class TestToolInvocation:
    """Invoke de ferramentas sync e async."""

    @pytest.mark.asyncio
    async def test_invoke_sync_tool(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "sync_tool.py",
            'TOOLS = [{"name": "soma", "fn": lambda a, b: a + b}]\n',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        tool = loader.get("soma")
        assert await tool.invoke(a=2, b=3) == 5

    @pytest.mark.asyncio
    async def test_invoke_async_tool(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "async_tool.py",
            '''
import asyncio

async def esperar(x):
    await asyncio.sleep(0.01)
    return x * 2

TOOLS = [esperar]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        tool = loader.get("esperar")
        assert tool.is_async is True
        assert await tool.invoke(21) == 42

    @pytest.mark.asyncio
    async def test_invoke_without_callable_raises(self) -> None:
        tool = Tool(name="vazia", fn=None)
        assert tool.active is False
        with pytest.raises(ToolValidationError):
            await tool.invoke()


class TestToolParamValidation:
    """Validação de parâmetros contra o schema da ferramenta."""

    def _tool_with_schema(self) -> Tool:
        return Tool(
            name="write",
            fn=lambda **kw: kw,
            params={
                "required": ["path", "mode"],
                "properties": {
                    "path": {"type": "str", "description": "caminho"},
                    "mode": {"type": "str", "description": "modo"},
                    "size": {"type": "int", "default": 0},
                },
            },
        )

    def test_valid_params(self) -> None:
        tool = self._tool_with_schema()
        ok, errors = tool.validate({"path": "/tmp/x.txt", "mode": "w"})
        assert ok is True
        assert errors == []

    def test_missing_required(self) -> None:
        tool = self._tool_with_schema()
        ok, errors = tool.validate({"path": "/tmp/x.txt"})
        assert ok is False
        assert any("mode" in e for e in errors)

    def test_wrong_type(self) -> None:
        tool = self._tool_with_schema()
        ok, errors = tool.validate({"path": "/tmp/x.txt", "size": "grande"})
        assert ok is False
        assert any("size" in e for e in errors)

    def test_none_params_valid_if_no_required(self) -> None:
        tool = Tool(name="ping", fn=lambda: "pong", params={"properties": {}})
        ok, errors = tool.validate()
        assert ok is True
        assert errors == []

    def test_flat_schema_with_defaults(self) -> None:
        tool = Tool(
            name="flat",
            fn=lambda **kw: kw,
            params={"count": {"type": "int", "default": 10, "required": True}},
        )
        # default aplicado -> não é erro de obrigatório
        ok, errors = tool.validate({})
        assert ok is True
        assert errors == []

    def test_bool_is_not_int(self) -> None:
        tool = Tool(name="flag", fn=lambda **kw: kw, params={"f": {"type": "int"}})
        ok, errors = tool.validate({"f": True})
        assert ok is False

    def test_unknown_type_in_schema_reports(self) -> None:
        tool = Tool(name="x", fn=lambda: 1, params={"p": {"type": "weird"}})
        ok, errors = tool.validate({"p": 1})
        assert ok is False
        assert any("tipo desconhecido" in e for e in errors)


# ===========================================================================
# ToolLoader — métricas e dump
# ===========================================================================

class TestToolLoaderMetrics:
    """Métricas e snapshot de diagnóstico."""

    def test_metrics_snapshot(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.py", 'TOOLS = [{"name": "a", "fn": lambda: 1}]\n')
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        snap = loader.metrics.snapshot()
        assert snap["scans"] == 1
        assert snap["modules_loaded"] == 1
        assert snap["tools_loaded"] == 1

    def test_dump(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "a.py",
            'TOOLS = [{"name": "a", "fn": lambda: 1, "category": "demo"}]\n',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        dump = loader.dump()
        assert dump["tools"] == 1
        assert dump["modules"] == 1
        assert dump["metrics"]["tools_loaded"] == 1
        assert dump["catalog"][0]["name"] == "a"
        assert dump["catalog"][0]["category"] == "demo"
        assert dump["catalog"][0]["active"] is True

    def test_tool_to_dict(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "a.py",
            '''
def fn(x):
    """Descrição."""
    return x

TOOLS = [{"name": "a", "fn": fn, "tags": ["util"], "version": "2.0.0"}]
''',
        )
        loader = ToolLoader(dirs=[tmp_path])
        loader.load_all()
        data = loader.get("a").to_dict()
        assert data["version"] == "2.0.0"
        assert data["tags"] == ["util"]
        assert data["description"] == "Descrição."
