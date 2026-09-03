"""
OMEGA DRAKON • TESTS
Módulo: tests/test_registry.py
Descrição: Testes do Action Registry (tools/registry.py) — Fase 3, item 3.3:
           registro tipado, aliases, execução com validação de schema e
           Security Layer, integração com Tool Loader, métricas e trilha.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/actions/
  - OMEGADRAKON_SPEC.md §7
  - ROADMAP_ABSORCAO.md Fase 3, item 3.3
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from core.security import SecurityManager
from tools.loader import ToolLoader
from tools.registry import (
    Action,
    ActionNotFoundError,
    ActionRegistry,
    ActionValidationError,
)


# ===========================================================================
# ActionRegistry — registro
# ===========================================================================

class TestActionRegistryRegistration:
    """Registro de ações tipadas."""

    def test_register_and_get(self) -> None:
        registry = ActionRegistry()
        registry.register_action(
            "system.ping",
            handler=lambda: "pong",
            description="Responde pong",
            category="system",
            permission="system.ping",
        )
        assert registry.has("system.ping")
        action = registry.get("system.ping")
        assert action.description == "Responde pong"
        assert action.category == "system"
        assert action.permission == "system.ping"
        assert action.active

    def test_register_action_instance(self) -> None:
        registry = ActionRegistry()
        action = Action(name="demo.echo", handler=lambda x: x, params={"x": {"type": "str"}})
        assert registry.register(action) is True
        assert registry.get("demo.echo") is action

    def test_duplicate_skipped_by_default(self) -> None:
        registry = ActionRegistry()
        assert registry.register_action("a.b", handler=lambda: 1) is not None
        assert registry.register_action("a.b", handler=lambda: 2) is not None  # skip
        # registro duplicado retorna False via register()
        action = Action(name="a.b", handler=lambda: 3)
        assert registry.register(action) is False
        assert registry.list_actions()[0]["description"] == ""
        assert len(registry.list_actions()) == 1

    def test_allow_overwrite(self) -> None:
        registry = ActionRegistry(allow_overwrite=True)
        registry.register_action("a.b", handler=lambda: 1, description="v1")
        registry.register_action("a.b", handler=lambda: 2, description="v2")
        assert registry.get("a.b").description == "v2"

    def test_empty_name_raises(self) -> None:
        registry = ActionRegistry()
        with pytest.raises(ActionValidationError):
            registry.register(Action(name="  ", handler=lambda: 1))

    def test_missing_handler_raises(self) -> None:
        registry = ActionRegistry()
        with pytest.raises(ActionValidationError):
            registry.register(Action(name="x.y"))

    def test_get_unknown_raises(self) -> None:
        registry = ActionRegistry()
        with pytest.raises(ActionNotFoundError):
            registry.get("ghost.action")

    def test_unregister_and_clear(self) -> None:
        registry = ActionRegistry()
        registry.register_action("a.b", handler=lambda: 1)
        registry.register_action("c.d", handler=lambda: 2)
        assert registry.unregister("a.b") is True
        assert registry.unregister("a.b") is False
        assert not registry.has("a.b")
        assert registry.clear() == 1
        assert len(registry.list_actions()) == 0

    def test_find_by_category(self) -> None:
        registry = ActionRegistry()
        registry.register_action("fs.read", handler=lambda: 1, category="filesystem")
        registry.register_action("fs.write", handler=lambda: 2, category="filesystem")
        registry.register_action("net.ping", handler=lambda: 3, category="network")
        assert [a.name for a in registry.find("filesystem")] == ["fs.read", "fs.write"]
        assert [a.name for a in registry.find("network")] == ["net.ping"]
        assert len(registry.find()) == 3


# ===========================================================================
# ActionRegistry — aliases
# ===========================================================================

class TestActionAliases:
    """Resolução por nomes alternativos."""

    def test_execute_via_alias_resolves(self) -> None:
        registry = ActionRegistry()
        registry.register_action(
            "filesystem.read",
            handler=lambda path: f"lido:{path}",
            aliases=["fs.read", "ler"],
        )
        assert registry.get("fs.read").name == "filesystem.read"
        assert registry.get("ler").name == "filesystem.read"

    def test_alias_to_dict_and_has(self) -> None:
        registry = ActionRegistry()
        registry.register_action("x.y", handler=lambda: 1, aliases=["yy"])
        assert registry.has("yy") is True
        assert registry.has("x.y") is True
        assert registry.get("yy").to_dict()["aliases"] == ["yy"]

    def test_unregister_removes_aliases(self) -> None:
        registry = ActionRegistry()
        registry.register_action("x.y", handler=lambda: 1, aliases=["yy"])
        registry.unregister("x.y")
        assert registry.has("yy") is False


# ===========================================================================
# ActionRegistry — execução
# ===========================================================================

@pytest.mark.asyncio
class TestActionExecution:
    """Pipeline de execução: schema → segurança → handler."""

    async def test_execute_ok_with_defaults(self) -> None:
        registry = ActionRegistry()

        def read(path: str, encoding: str = "utf-8") -> str:
            return f"{path}@{encoding}"

        registry.register_action(
            "filesystem.read",
            handler=read,
            params={
                "required": ["path"],
                "properties": {
                    "path": {"type": "str"},
                    "encoding": {"type": "str", "default": "utf-8"},
                },
            },
        )
        result = await registry.execute("filesystem.read", params={"path": "/tmp/a"})
        assert result.status == "ok"
        assert result.data == "/tmp/a@utf-8"
        assert result.params["encoding"] == "utf-8"

    async def test_execute_invalid_params(self) -> None:
        registry = ActionRegistry()
        registry.register_action(
            "filesystem.read",
            handler=lambda path: path,
            params={
                "required": ["path"],
                "properties": {"path": {"type": "str"}},
            },
        )
        result = await registry.execute("filesystem.read", params={})
        assert result.status == "invalid"
        assert any("path" in e for e in result.errors)
        assert result.data is None

    async def test_execute_unknown_action(self) -> None:
        registry = ActionRegistry()
        result = await registry.execute("ghost.action")
        assert result.status == "not_found"

    async def test_handler_error(self) -> None:
        registry = ActionRegistry()

        def boom() -> None:
            raise RuntimeError("explodiu")

        registry.register_action("demo.boom", handler=boom)
        result = await registry.execute("demo.boom")
        assert result.status == "error"
        assert "RuntimeError: explodiu" in result.error

    async def test_execute_async_handler(self) -> None:
        registry = ActionRegistry()

        async def soma(a: int, b: int) -> int:
            await asyncio.sleep(0.01)
            return a + b

        registry.register_action(
            "math.sum",
            handler=soma,
            params={
                "required": ["a", "b"],
                "properties": {
                    "a": {"type": "int"},
                    "b": {"type": "int"},
                },
            },
        )
        result = await registry.execute("math.sum", params={"a": 2, "b": 3})
        assert result.status == "ok"
        assert result.data == 5
        assert registry.get("math.sum").is_async is True

    async def test_execute_with_defaults_fills_params(self) -> None:
        registry = ActionRegistry()
        registry.register_action(
            "demo.flat",
            handler=lambda count=0: count,
            params={"count": {"type": "int", "default": 7, "required": True}},
        )
        result = await registry.execute("demo.flat", params={})
        assert result.status == "ok"
        assert result.data == 7

    async def test_duration_recorded(self) -> None:
        registry = ActionRegistry()
        registry.register_action("demo.wait", handler=lambda: None)
        result = await registry.execute("demo.wait")
        assert result.finished_at is not None
        assert result.duration >= 0


# ===========================================================================
# ActionRegistry — gate de segurança
# ===========================================================================

@pytest.mark.asyncio
class TestActionSecurity:
    """Execução validada pelo Security Layer (spec §7)."""

    def _registry(self, mode: str) -> ActionRegistry:
        return ActionRegistry(security=SecurityManager(mode=mode))

    async def test_denied_in_strict_for_unknown_role(self) -> None:
        registry = self._registry("strict")
        registry.register_action(
            "filesystem.delete",
            handler=lambda path: f"deletado:{path}",
            permission="filesystem.delete",
            params={"path": {"type": "str", "required": True}},
        )
        result = await registry.execute(
            "filesystem.delete", params={"path": "/tmp/x"}, role="ghost"
        )
        assert result.status == "denied"
        assert result.denied_by == "permission"
        assert result.data is None

    async def test_allowed_for_admin(self) -> None:
        registry = self._registry("strict")
        registry.register_action(
            "system.ping",
            handler=lambda: "pong",
            permission="system.ping",
        )
        result = await registry.execute("system.ping", role="admin")
        assert result.status == "ok"
        assert result.data == "pong"

    async def test_no_security_manager_ignores_permission(self) -> None:
        registry = ActionRegistry()  # sem SecurityManager
        registry.register_action(
            "filesystem.delete",
            handler=lambda: "ok",
            permission="filesystem.delete",
        )
        result = await registry.execute("filesystem.delete")
        assert result.status == "ok"

    async def test_action_without_permission_has_no_gate(self) -> None:
        registry = self._registry("strict")
        registry.register_action("demo.open", handler=lambda: "ok")  # sem permission
        result = await registry.execute("demo.open", role="ghost")
        assert result.status == "ok"

    async def test_denied_recorded_in_metrics(self) -> None:
        registry = self._registry("strict")
        registry.register_action(
            "secret.read",
            handler=lambda: "segredo",
            permission="secret.read",
        )
        await registry.execute("secret.read", role="ghost")
        assert registry.metrics.snapshot()["denied"] == 1
        assert registry.metrics.snapshot()["ok"] == 0


# ===========================================================================
# ActionRegistry — integração com Tool Loader (3.2)
# ===========================================================================

class TestActionRegistryLoader:
    """Importação de ferramentas do ToolLoader como ações."""

    def _loader(self, tmp_path: Path) -> ToolLoader:
        (tmp_path / "greet_plugin.py").write_text(
            '''
def greet(name="mundo"):
    """Saudação."""
    return f"olá {name}!"

TOOLS = [{
    "name": "greet",
    "category": "text",
    "fn": greet,
    "requires": "text.greet",
    "params": {
        "required": ["name"],
        "properties": {"name": {"type": "str", "default": "mundo"}},
    },
}]
''',
            encoding="utf-8",
        )
        return ToolLoader(dirs=[tmp_path])

    def test_import_loader_actions(self, tmp_path: Path) -> None:
        loader = self._loader(tmp_path)
        loader.load_all()
        registry = ActionRegistry()
        imported = registry.import_loader(loader)
        assert imported == 1
        action = registry.get("greet")
        assert action.category == "text"
        assert action.permission == "text.greet"
        assert action.source.endswith("greet_plugin.py")
        # schema preservado
        ok, errors = action.validate({"name": "Alex"})
        assert ok is True and errors == []

    def test_import_loader_twice_skips_duplicates(self, tmp_path: Path) -> None:
        loader = self._loader(tmp_path)
        loader.load_all()
        registry = ActionRegistry()
        assert registry.import_loader(loader) == 1
        assert registry.import_loader(loader) == 0

    def test_import_loader_category_prefix(self, tmp_path: Path) -> None:
        loader = self._loader(tmp_path)
        loader.load_all()
        registry = ActionRegistry()
        registry.import_loader(loader, category_prefix="tools")
        assert registry.has("tools.greet")
        assert not registry.has("greet")

    @pytest.mark.asyncio
    async def test_execute_imported_tool(self, tmp_path: Path) -> None:
        loader = self._loader(tmp_path)
        loader.load_all()
        registry = ActionRegistry()
        registry.import_loader(loader)
        result = await registry.execute("greet")
        assert result.status == "ok"
        assert result.data == "olá mundo!"
        result2 = await registry.execute("greet", params={"name": "Alex"})
        assert result2.data == "olá Alex!"

    @pytest.mark.asyncio
    async def test_imported_tool_denied_by_security(self, tmp_path: Path) -> None:
        loader = self._loader(tmp_path)
        loader.load_all()
        registry = ActionRegistry(security=SecurityManager(mode="strict"))
        registry.import_loader(loader)
        result = await registry.execute("greet", role="ghost")
        assert result.status == "denied"
        assert result.denied_by == "permission"


# ===========================================================================
# ActionRegistry — métricas, trilha e dump
# ===========================================================================

class TestActionMetrics:
    """Métricas, trilha recente e diagnóstico."""

    @pytest.mark.asyncio
    async def test_metrics_after_runs(self) -> None:
        registry = ActionRegistry()
        registry.register_action("ok.one", handler=lambda: 1)
        registry.register_action("err.one", handler=lambda: (_ for _ in ()).throw(ValueError("x")))
        await registry.execute("ok.one")
        await registry.execute("err.one")
        await registry.execute("not.registered")
        snap = registry.metrics.snapshot()
        assert snap["executed"] == 3
        assert snap["ok"] == 1
        assert snap["errors"] == 1
        assert snap["not_found"] == 1
        assert snap["actions"] == 2

    @pytest.mark.asyncio
    async def test_history_recent_first(self) -> None:
        registry = ActionRegistry()
        registry.register_action("ok.one", handler=lambda: 1)
        await registry.execute("ok.one")
        await registry.execute("ok.one")
        history = registry.history
        assert len(history) == 2
        assert history[0]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_history_trimmed(self) -> None:
        registry = ActionRegistry(history_size=3)
        registry.register_action("ok.one", handler=lambda: 1)
        for _ in range(5):
            await registry.execute("ok.one")
        assert len(registry.history) == 3

    def test_dump(self) -> None:
        registry = ActionRegistry()
        registry.register_action("a.b", handler=lambda: 1)
        dump = registry.dump()
        assert dump["actions"] == 1
        assert dump["security_enabled"] is False
        assert dump["catalog"][0]["name"] == "a.b"
