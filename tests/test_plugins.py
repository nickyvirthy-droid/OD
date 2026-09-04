"""
OMEGA DRAKON • TESTS
Módulo: tests/test_plugins.py
Descrição: Testes do Plugin System (plugins/manager.py) — Fase 7, item
           7.4: contratos de plugin (PLUGIN dict, ACTIONS/WORKFLOWS,
           register_actions/register_workflows), registro de actions no
           Action Registry (com permission plugin.<nome>) e workflows no
           Workflow Engine, descoberta em subdiretórios, escopo estrito
           (§7.1), isolamento de falha de import, hot-reload (reload/
           unload/reload_all), introspecção (list/get/has) e métricas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime plugins/ (PluginLoader — NV_LEGACY_ANALYSIS §3.10)
  - tools/loader.py (ToolLoader — contratos e escopo estrito)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.4
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.workflows import WorkflowEngine, WorkflowSpec, WorkflowStep
from plugins import PluginManager, PluginScopeError
from tools.registry import ActionRegistry


def _write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


PLUGIN_DICT = '''\
from core.workflows import WorkflowSpec, WorkflowStep


def hello(name="mundo"):
    return f"olá {name}"


def dobra(x):
    return x * 2


PLUGIN = {
    "name": "exemplo",
    "version": "1.2.0",
    "description": "Plugin de teste via PLUGIN dict",
    "actions": [
        {"name": "plugin_hello", "handler": hello,
         "description": "Sauda.", "category": "plugin"},
        {"name": "plugin_dobra", "handler": dobra,
         "params": {"x": {"type": "number", "required": True}}},
    ],
    "workflows": [
        WorkflowSpec(
            id="wf_exemplo", name="Exemplo",
            steps=[WorkflowStep(id="s1", action=lambda ctx: 1)],
        ),
    ],
}
'''

PLUGIN_VARS = '''\
def ping():
    return "pong"


ACTIONS = [{"name": "plugin_ping", "handler": ping, "description": "Ping."}]
'''

PLUGIN_FUNCS = '''\
def register_actions(registry):
    registry.register_action("plugin_funcao", lambda: "ok", source="plugin:func")


def register_workflows(engine):
    from core.workflows import WorkflowSpec, WorkflowStep

    engine.register(
        WorkflowSpec(
            id="wf_funcao", name="Funcs",
            steps=[WorkflowStep(id="s1", action=lambda ctx: 1)],
        )
    )
'''

PLUGIN_BROKEN = "def quebrado(:\n    pass\n"  # SyntaxError

PLUGIN_NO_CONTRACT = "VALOR = 42\n"


def _manager(root: Path, **kwargs):
    return PluginManager(root=root, **kwargs)


# ---------------------------------------------------------------------------
# Contratos de plugin
# ---------------------------------------------------------------------------

class TestPluginContracts:
    """PLUGIN dict, ACTIONS/WORKFLOWS e register_*()."""

    def test_plugin_dict_registers_actions_and_workflows(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        registry = ActionRegistry()
        engine = WorkflowEngine()
        manager = _manager(tmp_path, registry=registry, workflow_engine=engine)
        assert manager.load_all() == 1
        assert manager.has("exemplo")
        info = manager.get("exemplo")
        assert info.version == "1.2.0"
        assert info.actions == ["plugin_hello", "plugin_dobra"]
        assert info.workflows == ["wf_exemplo"]
        assert registry.has("plugin_hello")
        assert engine.has("wf_exemplo")
        assert manager.metrics.actions_registered == 2
        assert manager.metrics.workflows_registered == 1

    def test_plugin_actions_executable_through_registry(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        registry = ActionRegistry()
        manager = _manager(tmp_path, registry=registry)
        manager.load_all()
        result = registry.get("plugin_hello").handler("mundo")
        assert result == "olá mundo"

    def test_plugin_vars_contract(self, tmp_path):
        _write(tmp_path, "variaveis.py", PLUGIN_VARS)
        registry = ActionRegistry()
        manager = _manager(tmp_path, registry=registry)
        manager.load_all()
        action = registry.get("plugin_ping")
        assert action.handler() == "pong"

    def test_register_functions_contract(self, tmp_path):
        _write(tmp_path, "funcoes.py", PLUGIN_FUNCS)
        registry = ActionRegistry()
        engine = WorkflowEngine()
        manager = _manager(tmp_path, registry=registry, workflow_engine=engine)
        manager.load_all()
        assert registry.has("plugin_funcao")
        assert engine.has("wf_funcao")

    def test_plugin_permission_namespaced(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        registry = ActionRegistry()
        manager = _manager(tmp_path, registry=registry)
        manager.load_all()
        action = registry.get("plugin_hello")
        assert action.permission == "plugin.exemplo"


# ---------------------------------------------------------------------------
# Descoberta e escopo
# ---------------------------------------------------------------------------

class TestDiscoveryAndScope:
    """Subdiretórios, escopo estrito e isolamento de falhas."""

    def test_load_all_discovers_subdirectories(self, tmp_path):
        _write(tmp_path / "actions", "a.py", PLUGIN_VARS)
        _write(tmp_path / "workflows", "w.py", PLUGIN_FUNCS)
        registry = ActionRegistry()
        engine = WorkflowEngine()
        manager = _manager(
            tmp_path, registry=registry, workflow_engine=engine
        )
        assert manager.load_all() == 2
        assert registry.has("plugin_ping")
        assert engine.has("wf_funcao")

    def test_broken_plugin_does_not_break_others(self, tmp_path):
        _write(tmp_path, "quebrado.py", PLUGIN_BROKEN)
        _write(tmp_path, "ok.py", PLUGIN_VARS)
        registry = ActionRegistry()
        manager = _manager(tmp_path, registry=registry)
        assert manager.load_all() == 1  # só o ok
        assert registry.has("plugin_ping")
        assert manager.metrics.failed == 1
        assert manager.health()["errors"] >= 1

    def test_module_without_contract_skipped(self, tmp_path):
        _write(tmp_path, "sem_contrato.py", PLUGIN_NO_CONTRACT)
        manager = _manager(tmp_path)
        assert manager.load_all() == 0
        assert manager.metrics.loaded == 0

    def test_scope_strict_rejects_outside_file(self, tmp_path, tmp_path_factory):
        outside = tmp_path_factory.mktemp("fora")
        target = _write(outside, "fora.py", PLUGIN_VARS)
        manager = _manager(tmp_path)
        with pytest.raises(PluginScopeError):
            manager.load_source(target)

    def test_internal_files_ignored(self, tmp_path):
        # __init__.py e manager.py nunca são tratados como plugin
        _write(tmp_path, "__init__.py", "")
        _write(tmp_path, "manager.py", "X = 1\n")
        manager = _manager(tmp_path)
        files = manager.discover()
        assert all(f.name not in ("__init__.py", "manager.py") for f in files)


# ---------------------------------------------------------------------------
# Hot-reload e ciclo de vida
# ---------------------------------------------------------------------------

class TestLifecycle:
    """reload, unload e reload_all desregistram artefatos corretamente."""

    def test_unload_removes_actions_and_workflows(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        registry = ActionRegistry()
        engine = WorkflowEngine()
        manager = _manager(tmp_path, registry=registry, workflow_engine=engine)
        manager.load_all()
        assert manager.unload("exemplo") is True
        assert not registry.has("plugin_hello")
        assert not engine.has("wf_exemplo")
        assert manager.has("exemplo") is False

    def test_unload_unknown_returns_false(self, tmp_path):
        manager = _manager(tmp_path)
        assert manager.unload("nao_existe") is False

    def test_reload_keeps_artifacts(self, tmp_path):
        path = _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        registry = ActionRegistry()
        manager = _manager(tmp_path, registry=registry)
        manager.load_all()
        # edita o disco e recarrega
        path.write_text(PLUGIN_VARS, encoding="utf-8")
        assert manager.reload("exemplo") is True
        assert not registry.has("plugin_hello")  # antigo removido
        assert registry.has("plugin_ping")  # novo registrado

    def test_reload_unknown_returns_false(self, tmp_path):
        manager = _manager(tmp_path)
        assert manager.reload("nao_existe") is False

    def test_reload_all(self, tmp_path):
        _write(tmp_path, "a.py", PLUGIN_VARS)
        _write(tmp_path, "b.py", PLUGIN_DICT)
        registry = ActionRegistry()
        engine = WorkflowEngine()
        manager = _manager(tmp_path, registry=registry, workflow_engine=engine)
        manager.load_all()
        assert manager.reload_all() == 2
        assert registry.has("plugin_ping")
        assert registry.has("plugin_hello")

    def test_plugin_without_registry_counts_zero_artifacts(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        manager = _manager(tmp_path)  # sem registry nem engine
        manager.load_all()
        assert manager.has("exemplo")
        assert manager.metrics.actions_registered == 0
        assert manager.metrics.workflows_registered == 0


# ---------------------------------------------------------------------------
# Introspecção
# ---------------------------------------------------------------------------

class TestIntrospection:
    """list/get/has, métricas, snapshot/dump e health."""

    def test_list_and_get(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        manager = _manager(tmp_path)
        manager.load_all()
        assert manager.list_names() == ["exemplo"]
        plugins = manager.list_plugins()
        assert plugins[0]["name"] == "exemplo"
        assert plugins[0]["version"] == "1.2.0"
        assert manager.get("exemplo") is not None
        assert manager.get("nada") is None

    def test_snapshot_and_dump(self, tmp_path):
        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        manager = _manager(tmp_path)
        manager.load_all()
        snap = manager.snapshot()
        assert snap["plugins"] == 1
        assert snap["metrics"]["discovered"] == 1
        assert snap["metrics"]["loaded"] == 1
        dump = manager.dump()
        assert len(dump["plugins"]) == 1
        assert dump["plugins"][0]["name"] == "exemplo"

    def test_health(self, tmp_path):
        manager = _manager(tmp_path)
        health = manager.health()
        assert health["ok"] is True
        assert health["plugins"] == 0

    def test_event_bus_set_never_breaks(self, tmp_path):
        from core.event_bus import EventBus

        _write(tmp_path, "exemplo.py", PLUGIN_DICT)
        manager = _manager(tmp_path, event_bus=EventBus())
        manager.load_all()  # sem loop ativo: evento só logado
        assert manager.has("exemplo")