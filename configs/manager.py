"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: configs/manager.py
Descrição: Gerenciador de configurações centralizado do OmegaDrakon.
           Suporta YAML, env vars, validação Pydantic, chaves hierárquicas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky config/settings.py (Pydantic v2, env vars, aliases)
  - NV Runtime config (YAML, service container)
  - OMEGADRAKON_SPEC.md §2 (responsabilidades de configs/)
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger("od.configs")

__signature__ = "OD // CORE"


# ─── Config Schema (Pydantic) ──────────────────────────────────────────────

try:
    from pydantic import BaseModel, Field, field_validator

    class ConfigSchema(BaseModel):
        """Schema padrão de configuração do OmegaDrakon.
        
        Cada seção representa um subsistema. Validação automática
        via Pydantic com defaults sensatos.
        """
        
        # ── Sistema ────────────────────────────────────────────────────────
        app_name: str = "OmegaDrakon"
        version: str = "0.2.0"
        debug: bool = False
        log_level: str = "INFO"
        
        # ── Servidor ───────────────────────────────────────────────────────
        server_host: str = "127.0.0.1"
        server_port: int = 8765
        
        # ── LLM Local ──────────────────────────────────────────────────────
        llama_server_host: str = "127.0.0.1"
        llama_server_port: int = 8081
        default_llm: str = "qwen"
        llm_timeout_seconds: int = 120
        
        # ── Banco de Dados ─────────────────────────────────────────────────
        db_host: str = "127.0.0.1"
        db_port: int = 3306
        db_user: str = "omegadrakon"
        db_password: str = ""
        db_name: str = "omegadrakon_db"
        
        # ── Segurança ──────────────────────────────────────────────────────
        api_key: str = ""
        api_key_enabled: bool = False
        cors_origins: str = "*"
        max_execution_time_seconds: int = 30
        
        # ── Rate Limiting ──────────────────────────────────────────────────
        rate_limit_max: int = 10
        rate_limit_window_seconds: int = 60
        
        # ── Memória ────────────────────────────────────────────────────────
        memory_dir: str = "memory"
        cache_enabled: bool = True
        cache_ttl_seconds: int = 300
        
        # ── Persistência ───────────────────────────────────────────────────
        state_persist_path: str = "data/state.json"
        state_persist_debounce_seconds: float = 2.0
        
        # ── Notificações ───────────────────────────────────────────────────
        notify_on_restart: bool = True
        notify_llm_timeout_minutes: int = 5
        notify_disk_threshold_percent: int = 85
        
        # ── STT (Speech-to-Text) ───────────────────────────────────────────
        transcribe_enabled: bool = False
        whisper_binary_path: str = "/usr/local/bin/whisper-cli"
        whisper_model_path: str = "models/ggml-base.bin"
        whisper_n_threads: int = 4
        transcribe_language: str = "pt"
        
        # ── TTS (Text-to-Speech) ───────────────────────────────────────────
        tts_enabled: bool = False
        piper_binary_path: str = "/usr/local/bin/piper"
        piper_model_path: str = "voices/dii_pt-BR.onnx"
        
        # ── RAG (Vector Memory) ────────────────────────────────────────────
        vector_memory_enabled: bool = False
        vector_memory_dir: str = "data/vector_memory"
        vector_memory_top_k: int = 3
        
        # ── Telegram ───────────────────────────────────────────────────────
        telegram_bot_token: str = ""
        telegram_admin_ids: str = ""
        
        # ── Home Assistant ─────────────────────────────────────────────────
        ha_url: str = ""
        ha_token: str = ""
        
        # ── MQTT ───────────────────────────────────────────────────────────
        mqtt_broker: str = "127.0.0.1"
        mqtt_port: int = 1883
        
        # ── APIs Externas ──────────────────────────────────────────────────
        openai_api_key: str = ""
        google_api_key: str = ""
        anthropic_api_key: str = ""
        
        # ── Validadores ────────────────────────────────────────────────────
        
        @field_validator("log_level")
        @classmethod
        def validate_log_level(cls, v: str) -> str:
            valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            if v.upper() not in valid_levels:
                raise ValueError(f"Invalid log level: {v}. Must be one of: {valid_levels}")
            return v.upper()
        
        @field_validator("server_port", "db_port", "mqtt_port")
        @classmethod
        def validate_port(cls, v: int) -> int:
            if not 1 <= v <= 65535:
                raise ValueError(f"Invalid port: {v}. Must be 1-65535")
            return v
        
        @field_validator("rate_limit_max")
        @classmethod
        def validate_rate_limit(cls, v: int) -> int:
            if v < 1:
                raise ValueError("rate_limit_max must be >= 1")
            return v
        
        @field_validator("max_execution_time_seconds")
        @classmethod
        def validate_execution_time(cls, v: int) -> int:
            if v < 1:
                raise ValueError("max_execution_time_seconds must be >= 1")
            return v
        
        model_config = {"extra": "ignore"}
    
    PYDANTIC_AVAILABLE = True

except ImportError:
    # Fallback if Pydantic is not available
    PYDANTIC_AVAILABLE = False
    ConfigSchema = None  # type: ignore


# ─── Config Entry ──────────────────────────────────────────────────────────

@dataclass
class ConfigEntry:
    """Entrada individual de configuração com metadados."""
    
    key: str
    value: Any
    source: str  # "default", "yaml", "env", "override"
    timestamp: datetime = field(default_factory=datetime.now)
    description: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
        }


# ─── Config Manager ────────────────────────────────────────────────────────

class ConfigManager:
    """Gerenciador de configurações centralizado do OmegaDrakon.
    
    Características:
      - Carregamento de YAML + env vars com prioridade
      - Validação via Pydantic (quando disponível)
      - Chaves hierárquicas com dots (ex: "system.bridge.host")
      - Defaults configuráveis
      - Override programático
      - Export/Import
      - Audit logging via protocolo NICKY
    """
    
    def __init__(
        self,
        yaml_path: str | Path | None = None,
        env_prefix: str = "OD_",
        validate: bool = True,
    ) -> None:
        """Inicializa o ConfigManager.
        
        Args:
            yaml_path: Caminho para arquivo YAML de configuração
            env_prefix: Prefixo para variáveis de ambiente (padrão: "OD_")
            validate: Se True, valida com Pydantic (quando disponível)
        """
        self._env_prefix = env_prefix
        self._validate = validate and PYDANTIC_AVAILABLE
        self._config: dict[str, Any] = {}
        self._entries: dict[str, ConfigEntry] = {}
        self._watchers: list[Callable[[str, Any, Any], None]] = []
        self._schema: Any = None
        self._yaml_path: Path | None = Path(yaml_path) if yaml_path else None
        
        # Carrega configuração
        self._load_defaults()
        if self._yaml_path and self._yaml_path.exists():
            self._load_yaml(self._yaml_path)
        self._load_env_vars()
        
        # Valida se habilitado
        if self._validate:
            self._validate_config()
        
        logger.info(f"[NICKY][INFO] ConfigManager initialized with {len(self._config)} keys")
    
    # ─── Loading ───────────────────────────────────────────────────────────
    
    def _load_defaults(self) -> None:
        """Carrega defaults do schema Pydantic."""
        if self._validate and ConfigSchema:
            schema = ConfigSchema()
            defaults = schema.model_dump()
            for key, value in defaults.items():
                self._set_value(key, value, source="default", description="Default value")
    
    def _load_yaml(self, path: Path) -> None:
        """Carrega configuração de arquivo YAML."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            if isinstance(data, dict):
                flat = self._flatten_dict(data)
                for key, value in flat.items():
                    self._set_value(key, value, source="yaml", description=f"From {path.name}")
                
                logger.info(f"[NICKY][INFO] Loaded YAML config from {path}")
            else:
                logger.warning(f"[NICKY][WARN] YAML config is not a dict: {path}")
        
        except Exception as e:
            logger.error(f"[NICKY][CRIT] Failed to load YAML config: {e}")
            raise
    
    def _load_env_vars(self) -> None:
        """Carrega configuração de variáveis de ambiente."""
        loaded = 0
        for key, value in os.environ.items():
            if key.startswith(self._env_prefix):
                config_key = key[len(self._env_prefix):].lower()
                # Converte tipos
                converted = self._convert_env_value(value)
                self._set_value(config_key, converted, source="env", description=f"Env: {key}")
                loaded += 1
        
        if loaded > 0:
            logger.info(f"[NICKY][INFO] Loaded {loaded} env vars with prefix '{self._env_prefix}'")
    
    def _convert_env_value(self, value: str) -> Any:
        """Converte string de env var para tipo Python."""
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value
    
    def _flatten_dict(self, d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Achata dicionário aninhado com dots."""
        items: dict[str, Any] = {}
        for k, v in d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(self._flatten_dict(v, new_key))
            else:
                items[new_key] = v
        return items
    
    # ─── Validation ────────────────────────────────────────────────────────
    
    def _validate_config(self) -> None:
        """Valida configuração atual contra o schema Pydantic."""
        if not ConfigSchema:
            return
        
        try:
            self._schema = ConfigSchema(**self._config)
            logger.info("[NICKY][INFO] Config validation passed")
        except Exception as e:
            logger.error(f"[NICKY][CRIT] Config validation failed: {e}")
            raise ValueError(f"Config validation failed: {e}") from e
    
    # ─── Get/Set ───────────────────────────────────────────────────────────
    
    def get(self, key: str, default: Any = None) -> Any:
        """Obtém valor de configuração por chave.
        
        Suporta chaves hierárquicas com dots:
          config.get("system.bridge.host")
        
        Args:
            key: Chave de configuração (pode conter dots)
            default: Valor padrão se chave não existir
            
        Returns:
            Valor da configuração ou default
        """
        return self._config.get(key, default)
    
    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Obtém múltiplos valores de configuração.
        
        Args:
            keys: Lista de chaves
            
        Returns:
            Dict com chaves e valores (usa default=None para inexistentes)
        """
        return {key: self.get(key) for key in keys}
    
    def set(self, key: str, value: Any, source: str = "override") -> None:
        """Define valor de configuração.
        
        Args:
            key: Chave de configuração
            value: Valor a definir
            source: Fonte da alteração (para audit)
        """
        old_value = self._config.get(key)
        self._set_value(key, value, source=source, description="Programmatic override")
        
        # Notifica watchers
        for watcher in self._watchers:
            try:
                watcher(key, old_value, value)
            except Exception as e:
                logger.warning(f"[NICKY][WARN] Watcher error for key {key}: {e}")
        
        logger.debug(f"[NICKY][INFO] Config set: {key} = {value} (source={source})")
    
    def _set_value(self, key: str, value: Any, source: str, description: str = "") -> None:
        """Define valor interno com metadados."""
        self._config[key] = value
        self._entries[key] = ConfigEntry(
            key=key,
            value=copy.deepcopy(value),
            source=source,
            description=description,
        )
    
    def delete(self, key: str) -> bool:
        """Remove chave de configuração.
        
        Args:
            key: Chave a remover
            
        Returns:
            True se removido, False se não existia
        """
        if key in self._config:
            del self._config[key]
            if key in self._entries:
                del self._entries[key]
            logger.debug(f"[NICKY][INFO] Config deleted: {key}")
            return True
        return False
    
    def has(self, key: str) -> bool:
        """Verifica se chave existe."""
        return key in self._config
    
    def keys(self, prefix: str = "") -> list[str]:
        """Lista chaves de configuração.
        
        Args:
            prefix: Filtrar por prefixo (opcional)
            
        Returns:
            Lista de chaves
        """
        if prefix:
            return [k for k in self._config if k.startswith(prefix)]
        return list(self._config.keys())
    
    # ─── Watchers ──────────────────────────────────────────────────────────
    
    def watch(self, callback: Callable[[str, Any, Any], None]) -> None:
        """Registra callback para mudanças de configuração.
        
        Args:
            callback: Função chamada com (key, old_value, new_value)
        """
        self._watchers.append(callback)
    
    def unwatch(self, callback: Callable[[str, Any, Any], None]) -> None:
        """Remove callback de watchers."""
        if callback in self._watchers:
            self._watchers.remove(callback)
    
    # ─── Export/Import ─────────────────────────────────────────────────────
    
    def export_dict(self) -> dict[str, Any]:
        """Exporta configuração como dict."""
        return copy.deepcopy(self._config)
    
    def export_yaml(self, path: str | Path) -> None:
        """Exporta configuração para arquivo YAML."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Reorganiza em estrutura aninhada
        nested = self._nest_dict(self._config)
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(nested, f, default_flow_style=False, allow_unicode=True)
        
        logger.info(f"[NICKY][INFO] Config exported to {path}")
    
    def export_json(self, path: str | Path) -> None:
        """Exporta configuração para arquivo JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, default=str)
        
        logger.info(f"[NICKY][INFO] Config exported to {path}")
    
    def _nest_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        """Recria estrutura aninhada a partir de chaves com dots."""
        result: dict[str, Any] = {}
        for key, value in d.items():
            parts = key.split(".")
            current = result
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        return result
    
    # ─── Inspection ────────────────────────────────────────────────────────
    
    def get_entry(self, key: str) -> ConfigEntry | None:
        """Obtém entrada completa com metadados."""
        return self._entries.get(key)
    
    def dump(self) -> dict[str, Any]:
        """Retorna snapshot completo da configuração."""
        return {
            "config": copy.deepcopy(self._config),
            "entries": {
                k: v.to_dict() for k, v in self._entries.items()
            },
            "total_keys": len(self._config),
            "sources": self._count_by_source(),
        }
    
    def _count_by_source(self) -> dict[str, int]:
        """Conta chaves por fonte."""
        counts: dict[str, int] = {}
        for entry in self._entries.values():
            counts[entry.source] = counts.get(entry.source, 0) + 1
        return counts
    
    # ─── Lifecycle ─────────────────────────────────────────────────────────
    
    def reload(self) -> None:
        """Recarrega configuração do YAML e env vars."""
        self._config.clear()
        self._entries.clear()
        
        self._load_defaults()
        if self._yaml_path and self._yaml_path.exists():
            self._load_yaml(self._yaml_path)
        self._load_env_vars()
        
        if self._validate:
            self._validate_config()
        
        logger.info("[NICKY][INFO] Config reloaded")
    
    def reset(self) -> None:
        """Reseta configuração para defaults."""
        self._config.clear()
        self._entries.clear()
        
        self._load_defaults()
        
        logger.info("[NICKY][INFO] Config reset to defaults")


# ─── Global Instance ───────────────────────────────────────────────────────

_manager: ConfigManager | None = None


def get_config_manager(
    yaml_path: str | Path | None = None,
    env_prefix: str = "OD_",
    validate: bool = True,
) -> ConfigManager:
    """Obtém instância global do ConfigManager (singleton).
    
    Args:
        yaml_path: Caminho para YAML (usado apenas na primeira chamada)
        env_prefix: Prefixo env vars
        validate: Habilitar validação Pydantic
        
    Returns:
        Instância do ConfigManager
    """
    global _manager
    if _manager is None:
        _manager = ConfigManager(yaml_path=yaml_path, env_prefix=env_prefix, validate=validate)
    return _manager


def reset_config_manager() -> None:
    """Reseta instância global (para testes)."""
    global _manager
    _manager = None
