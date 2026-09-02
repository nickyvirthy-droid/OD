from __future__ import annotations

"""
OMEGA DRAKON • TESTS
Tecnologia que respira.
Módulo: tests/test_config_manager.py
Descrição: Testes unitários do ConfigManager.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from configs.manager import ConfigEntry, ConfigManager, get_config_manager, reset_config_manager


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def cleanup_singleton():
    """Reseta singleton antes e depois de cada teste."""
    reset_config_manager()
    yield
    reset_config_manager()


@pytest.fixture
def tmp_yaml(tmp_path: Path) -> Path:
    """Cria arquivo YAML temporário para testes."""
    config = {
        "app_name": "TestOmegaDrakon",
        "debug": True,
        "server_port": 9999,
        "nested": {
            "key1": "value1",
            "key2": 42,
        },
    }
    yaml_path = tmp_path / "test_config.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    return yaml_path


@pytest.fixture
def manager(tmp_yaml: Path) -> ConfigManager:
    """Cria ConfigManager com YAML de teste."""
    return ConfigManager(yaml_path=tmp_yaml, validate=False)


# ─── ConfigEntry Tests ─────────────────────────────────────────────────────

class TestConfigEntry:
    """Testes para ConfigEntry."""
    
    def test_entry_creation(self) -> None:
        entry = ConfigEntry(key="test", value=42, source="default")
        assert entry.key == "test"
        assert entry.value == 42
        assert entry.source == "default"
        assert entry.timestamp is not None
    
    def test_entry_to_dict(self) -> None:
        entry = ConfigEntry(key="test", value="hello", source="yaml")
        d = entry.to_dict()
        assert d["key"] == "test"
        assert d["value"] == "hello"
        assert d["source"] == "yaml"
        assert "timestamp" in d
    
    def test_entry_with_description(self) -> None:
        entry = ConfigEntry(key="test", value=1, source="env", description="Test value")
        assert entry.description == "Test value"


# ─── Initialization Tests ──────────────────────────────────────────────────

class TestInitialization:
    """Testes para inicialização do ConfigManager."""
    
    def test_init_without_yaml(self) -> None:
        manager = ConfigManager(validate=False)
        assert manager is not None
        assert len(manager.keys()) == 0
    
    def test_init_with_yaml(self, tmp_yaml: Path) -> None:
        manager = ConfigManager(yaml_path=tmp_yaml, validate=False)
        assert manager.get("app_name") == "TestOmegaDrakon"
        assert manager.get("debug") is True
        assert manager.get("server_port") == 9999
    
    def test_init_with_nonexistent_yaml(self, tmp_path: Path) -> None:
        manager = ConfigManager(yaml_path=tmp_path / "nonexistent.yaml", validate=False)
        assert manager is not None
    
    def test_init_with_validation(self, tmp_yaml: Path) -> None:
        manager = ConfigManager(yaml_path=tmp_yaml, validate=True)
        assert manager.get("app_name") == "TestOmegaDrakon"
    
    def test_init_sets_env_prefix(self) -> None:
        manager = ConfigManager(env_prefix="TEST_", validate=False)
        assert manager._env_prefix == "TEST_"


# ─── Loading Tests ─────────────────────────────────────────────────────────

class TestLoading:
    """Testes para carregamento de configuração."""
    
    def test_load_yaml_flat_keys(self, tmp_path: Path) -> None:
        config = {"key1": "value1", "key2": 42, "key3": True}
        yaml_path = tmp_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        manager = ConfigManager(yaml_path=yaml_path, validate=False)
        assert manager.get("key1") == "value1"
        assert manager.get("key2") == 42
        assert manager.get("key3") is True
    
    def test_load_yaml_nested_keys(self, tmp_path: Path) -> None:
        config = {"system": {"bridge": {"host": "localhost", "port": 8080}}}
        yaml_path = tmp_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        manager = ConfigManager(yaml_path=yaml_path, validate=False)
        assert manager.get("system.bridge.host") == "localhost"
        assert manager.get("system.bridge.port") == 8080
    
    def test_load_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OD_TEST_KEY", "test_value")
        monkeypatch.setenv("OD_TEST_NUMBER", "42")
        monkeypatch.setenv("OD_TEST_BOOL", "true")
        
        manager = ConfigManager(env_prefix="OD_", validate=False)
        assert manager.get("test_key") == "test_value"
        assert manager.get("test_number") == 42
        assert manager.get("test_bool") is True
    
    def test_env_vars_override_yaml(self, tmp_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OD_APP_NAME", "EnvOverride")
        
        manager = ConfigManager(yaml_path=tmp_yaml, env_prefix="OD_", validate=False)
        assert manager.get("app_name") == "EnvOverride"
    
    def test_load_invalid_yaml_logs_error(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "invalid.yaml"
        with open(yaml_path, "w") as f:
            f.write("{{{{invalid yaml")
        
        with pytest.raises(Exception):
            ConfigManager(yaml_path=yaml_path, validate=False)


# ─── Get/Set Tests ─────────────────────────────────────────────────────────

class TestGetSet:
    """Testes para get/set de configuração."""
    
    def test_get_existing_key(self, manager: ConfigManager) -> None:
        assert manager.get("app_name") == "TestOmegaDrakon"
    
    def test_get_nonexistent_key(self, manager: ConfigManager) -> None:
        assert manager.get("nonexistent") is None
    
    def test_get_with_default(self, manager: ConfigManager) -> None:
        assert manager.get("nonexistent", "fallback") == "fallback"
    
    def test_set_new_key(self, manager: ConfigManager) -> None:
        manager.set("new_key", "new_value")
        assert manager.get("new_key") == "new_value"
    
    def test_set_existing_key(self, manager: ConfigManager) -> None:
        manager.set("app_name", "Modified")
        assert manager.get("app_name") == "Modified"
    
    def test_set_with_source(self, manager: ConfigManager) -> None:
        manager.set("test_key", "test_val", source="test")
        entry = manager.get_entry("test_key")
        assert entry is not None
        assert entry.source == "test"
    
    def test_get_many(self, manager: ConfigManager) -> None:
        result = manager.get_many(["app_name", "debug", "nonexistent"])
        assert result["app_name"] == "TestOmegaDrakon"
        assert result["debug"] is True
        assert result["nonexistent"] is None
    
    def test_delete_existing_key(self, manager: ConfigManager) -> None:
        assert manager.has("app_name") is True
        result = manager.delete("app_name")
        assert result is True
        assert manager.has("app_name") is False
    
    def test_delete_nonexistent_key(self, manager: ConfigManager) -> None:
        result = manager.delete("nonexistent")
        assert result is False
    
    def test_has_existing_key(self, manager: ConfigManager) -> None:
        assert manager.has("app_name") is True
    
    def test_has_nonexistent_key(self, manager: ConfigManager) -> None:
        assert manager.has("nonexistent") is False
    
    def test_keys_all(self, manager: ConfigManager) -> None:
        keys = manager.keys()
        assert "app_name" in keys
        assert "debug" in keys
    
    def test_keys_with_prefix(self, manager: ConfigManager) -> None:
        manager.set("test.alpha", 1)
        manager.set("test.beta", 2)
        manager.set("other.gamma", 3)
        
        keys = manager.keys(prefix="test.")
        assert "test.alpha" in keys
        assert "test.beta" in keys
        assert "other.gamma" not in keys


# ─── Watchers Tests ────────────────────────────────────────────────────────

class TestWatchers:
    """Testes para sistema de watchers."""
    
    def test_watch_receives_changes(self, manager: ConfigManager) -> None:
        callback = MagicMock()
        manager.watch(callback)
        
        manager.set("new_key", "new_val")
        callback.assert_called_once_with("new_key", None, "new_val")
    
    def test_watch_multiple_changes(self, manager: ConfigManager) -> None:
        callback = MagicMock()
        manager.watch(callback)
        
        manager.set("key1", "val1")
        manager.set("key2", "val2")
        assert callback.call_count == 2
    
    def test_unwatch(self, manager: ConfigManager) -> None:
        callback = MagicMock()
        manager.watch(callback)
        manager.unwatch(callback)
        
        manager.set("key", "val")
        callback.assert_not_called()
    
    def test_watcher_error_doesnt_crash(self, manager: ConfigManager) -> None:
        def bad_callback(key, old, new):
            raise RuntimeError("Watcher error")
        
        manager.watch(bad_callback)
        # Should not raise
        manager.set("key", "val")
        assert manager.get("key") == "val"


# ─── Export/Import Tests ───────────────────────────────────────────────────

class TestExportImport:
    """Testes para export/import de configuração."""
    
    def test_export_dict(self, manager: ConfigManager) -> None:
        exported = manager.export_dict()
        assert exported["app_name"] == "TestOmegaDrakon"
        assert exported["debug"] is True
    
    def test_export_dict_is_copy(self, manager: ConfigManager) -> None:
        exported = manager.export_dict()
        exported["app_name"] = "Modified"
        assert manager.get("app_name") == "TestOmegaDrakon"
    
    def test_export_yaml(self, manager: ConfigManager, tmp_path: Path) -> None:
        export_path = tmp_path / "exported.yaml"
        manager.export_yaml(export_path)
        
        assert export_path.exists()
        with open(export_path) as f:
            data = yaml.safe_load(f)
        assert data["app_name"] == "TestOmegaDrakon"
    
    def test_export_json(self, manager: ConfigManager, tmp_path: Path) -> None:
        export_path = tmp_path / "exported.json"
        manager.export_json(export_path)
        
        assert export_path.exists()
        with open(export_path) as f:
            data = json.load(f)
        assert data["app_name"] == "TestOmegaDrakon"
    
    def test_dump(self, manager: ConfigManager) -> None:
        dump = manager.dump()
        assert "config" in dump
        assert "entries" in dump
        assert "total_keys" in dump
        assert "sources" in dump
        assert dump["total_keys"] > 0


# ─── Lifecycle Tests ───────────────────────────────────────────────────────

class TestLifecycle:
    """Testes para lifecycle do ConfigManager."""
    
    def test_reload(self, manager: ConfigManager, tmp_yaml: Path) -> None:
        # Modifica em memória
        manager.set("app_name", "Modified")
        assert manager.get("app_name") == "Modified"
        
        # Recarrega do YAML
        manager.reload()
        assert manager.get("app_name") == "TestOmegaDrakon"
    
    def test_reset(self, manager: ConfigManager) -> None:
        manager.set("custom_key", "custom_val")
        assert manager.has("custom_key") is True
        
        manager.reset()
        assert manager.has("custom_key") is False
    
    def test_singleton_get_config_manager(self) -> None:
        m1 = get_config_manager()
        m2 = get_config_manager()
        assert m1 is m2
    
    def test_reset_config_manager(self) -> None:
        m1 = get_config_manager()
        reset_config_manager()
        m2 = get_config_manager()
        assert m1 is not m2


# ─── Inspection Tests ──────────────────────────────────────────────────────

class TestInspection:
    """Testes para inspeção de configuração."""
    
    def test_get_entry(self, manager: ConfigManager) -> None:
        entry = manager.get_entry("app_name")
        assert entry is not None
        assert entry.key == "app_name"
        assert entry.value == "TestOmegaDrakon"
    
    def test_get_entry_nonexistent(self, manager: ConfigManager) -> None:
        entry = manager.get_entry("nonexistent")
        assert entry is None
    
    def test_dump_sources(self, manager: ConfigManager) -> None:
        dump = manager.dump()
        sources = dump["sources"]
        assert "yaml" in sources
        assert sources["yaml"] >= 1


# ─── Integration Tests ─────────────────────────────────────────────────────

class TestIntegration:
    """Testes de integração."""
    
    def test_full_workflow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Testa fluxo completo: criar YAML, carregar, modificar, exportar."""
        # Cria YAML inicial
        config = {"app_name": "Initial", "debug": False}
        yaml_path = tmp_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        # Carrega
        manager = ConfigManager(yaml_path=yaml_path, validate=False)
        assert manager.get("app_name") == "Initial"
        
        # Modifica
        manager.set("app_name", "Modified")
        manager.set("new_key", "new_val")
        assert manager.get("app_name") == "Modified"
        
        # Exporta
        export_path = tmp_path / "exported.yaml"
        manager.export_yaml(export_path)
        
        # Recarrega do exportado
        manager2 = ConfigManager(yaml_path=export_path, validate=False)
        assert manager2.get("app_name") == "Modified"
        assert manager2.get("new_key") == "new_val"
    
    def test_env_var_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Testa que env vars têm prioridade sobre YAML."""
        config = {"app_name": "YAML Value"}
        yaml_path = tmp_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        monkeypatch.setenv("OD_APP_NAME", "ENV Value")
        
        manager = ConfigManager(yaml_path=yaml_path, env_prefix="OD_", validate=False)
        assert manager.get("app_name") == "ENV Value"
    
    def test_nested_config_access(self, tmp_path: Path) -> None:
        """Testa acesso a configurações aninhadas."""
        config = {
            "system": {
                "bridge": {
                    "host": "localhost",
                    "port": 8765,
                }
            }
        }
        yaml_path = tmp_path / "config.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        
        manager = ConfigManager(yaml_path=yaml_path, validate=False)
        assert manager.get("system.bridge.host") == "localhost"
        assert manager.get("system.bridge.port") == 8765
    
    def test_type_conversion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Testa conversão automática de tipos em env vars."""
        monkeypatch.setenv("OD_STRING_VAL", "hello")
        monkeypatch.setenv("OD_INT_VAL", "42")
        monkeypatch.setenv("OD_FLOAT_VAL", "3.14")
        monkeypatch.setenv("OD_BOOL_TRUE", "true")
        monkeypatch.setenv("OD_BOOL_FALSE", "false")
        
        manager = ConfigManager(env_prefix="OD_", validate=False)
        assert manager.get("string_val") == "hello"
        assert manager.get("int_val") == 42
        assert manager.get("float_val") == 3.14
        assert manager.get("bool_true") is True
        assert manager.get("bool_false") is False
