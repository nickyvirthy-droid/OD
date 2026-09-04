"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: plugins/manager.py
Descrição: Plugin System (Fase 7, item 7.4) — PluginManager: descoberta e
           carregamento dinâmico de plugins Python com registro de actions
           no Action Registry e de workflows no Workflow Engine, hot-reload
           (reload/unload), escopo estrito (spec §7.1), Event Bus
           (plugin.loaded/failed/unloaded), métricas, health() e dump().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime plugins/ (PluginLoader: actions/, providers/, workflows/,
    integrations/ — register_actions/register_workflows)
  - tools/loader.py (ToolLoader — contratos PLUGIN/TOOLS/load_tools e
    escopo estrito)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.4

Contrato de um plugin (módulo .py dentro do root), avaliado nesta ordem:
    1. PLUGIN = {"name", "version", "description",
                 "actions": [...], "workflows": [...]}
    2. ACTIONS = [...]  e/ou  WORKFLOWS = [...]
    3. register_actions(registry)  e/ou  register_workflows(engine)

Entrada de action (dict, mesmas chaves do registry.register_action):
    name, handler|fn|function, description, category, params,
    permission, aliases, version

Decisões registradas (ver CHANGELOG):
  - Actions de plugin são registradas com permission "plugin.<nome>"
    (gate do Security Layer na execução — padrão auto_extension)
  - Falha de import de um plugin nunca impede o carregamento dos demais
    (isolamento por módulo, CRIT log + contador failed)
  - Hot-reload desregistra os artefatos do plugin ANTES de recarregar —
    registry.unregister/workflow_engine.unregister são a fonte de verdade
  - Escopo estrito §7.1: arquivos fora do root são recusados
    (PluginScopeError); __init__.py/manager.py são internos e ignorados
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.plugins")

TOPIC_LOADED = "plugin.loaded"
TOPIC_FAILED = "plugin.failed"
TOPIC_UNLOADED = "plugin.unloaded"

# Subdiretórios do legado NV onde plugins são procurados (além da raiz)
_PLUGIN_SUBDIRS = ("actions", "providers", "workflows", "integrations")

# Arquivos internos do framework — nunca tratados como plugin
_SKIP_FILES = {"__init__.py", "manager.py"}


class PluginScopeError(Exception):
    """Arquivo de plugin fora do root (spec §7.1)."""


@dataclass(slots=True)
class PluginInfo:
    """Metadados de um plugin carregado."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    source: str = ""
    actions: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)
    loaded_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "actions": list(self.actions),
            "workflows": list(self.workflows),
            "loaded_ts": round(self.loaded_ts, 3),
        }


@dataclass(slots=True)
class PluginMetrics:
    """Métricas acumuladas do PluginManager."""

    discovered: int = 0
    loaded: int = 0
    failed: int = 0
    actions_registered: int = 0
    workflows_registered: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "loaded": self.loaded,
            "failed": self.failed,
            "actions_registered": self.actions_registered,
            "workflows_registered": self.workflows_registered,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------

class PluginManager:
    """Carrega plugins Python e registra actions/workflows (Fase 7.4).

    Uso típico:
        manager = PluginManager(
            root="plugins",
            registry=registry,            # ActionRegistry
            workflow_engine=engine,       # WorkflowEngine
            event_bus=bus,
        )
        manager.load_all()  # descobre plugins/ + subdiretórios

    Registro é aditivo: actions vão para o ActionRegistry com
    permission "plugin.<nome>" e workflows para o WorkflowEngine.
    """

    def __init__(
        self,
        *,
        root: Union[str, Path] = "plugins",
        registry: Any = None,
        workflow_engine: Any = None,
        event_bus: Any = None,
        allow_overwrite: bool = False,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._registry = registry
        self._engine = workflow_engine
        self._event_bus = event_bus
        self._allow_overwrite = allow_overwrite
        self._clock = clock or time.time
        self._plugins: dict[str, PluginInfo] = {}
        self._metrics = PluginMetrics()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def metrics(self) -> PluginMetrics:
        return self._metrics

    # -- Descoberta -----------------------------------------------------------

    def discover(self) -> list[Path]:
        """Lista os arquivos .py candidatos (raiz + subdiretórios NV)."""
        roots = [self._root] + [
            self._root / sub for sub in _PLUGIN_SUBDIRS
        ]
        files: list[Path] = []
        for base in roots:
            if not base.is_dir():
                continue
            for path in sorted(base.iterdir()):
                if not path.is_file() or path.suffix != ".py":
                    continue
                if path.name in _SKIP_FILES or path.name.startswith(("_", ".")):
                    continue
                files.append(path)
        return files

    def load_all(self) -> int:
        """Carrega todos os plugins descobertos. Retorna nº de plugins OK."""
        files = self.discover()
        with self._lock:
            self._metrics.discovered += len(files)
        loaded = 0
        for path in files:
            before = set(self._plugins)
            try:
                self._load_module_file(path)
                if len(self._plugins) > len(before):
                    loaded += 1
            except PluginScopeError as exc:
                with self._lock:
                    self._metrics.errors += 1
                log.crit("Plugin fora do escopo", error=str(exc))
            except Exception as exc:  # pragma: no cover — isolamento
                with self._lock:
                    self._metrics.failed += 1
                    self._metrics.errors += 1
                log.crit(
                    "Plugin falhou ao carregar",
                    file=str(path),
                    error=type(exc).__name__,
                )
        return loaded

    def load_source(self, source: Union[str, Path]) -> int:
        """Carrega um arquivo de plugin específico (retorna nº de artefatos)."""
        path = Path(source)
        self._check_scope(path)
        return self._load_module_file(path)

    # -- Carregamento ---------------------------------------------------------

    def _load_module_file(self, path: Path) -> int:
        self._check_scope(path)
        module = self._import_module(path)
        actions, workflows, reg_actions, reg_workflows = self._extract(
            module, path
        )
        if not (actions or workflows or reg_actions or reg_workflows):
            log.warn(
                "Plugin sem contrato (PLUGIN/ACTIONS/WORKFLOWS/register_*)",
                file=str(path),
            )
            return 0
        plugin_name = self._plugin_name(module, path)
        info = PluginInfo(
            name=plugin_name,
            version=self._plugin_version(module),
            description=self._plugin_description(module),
            source=str(path),
            loaded_ts=self._clock(),
        )
        registered = 0
        if actions and self._registry is not None:
            registered += self._register_actions(plugin_name, actions)
            info.actions = [self._action_name(a) for a in actions]
        if workflows and self._engine is not None:
            registered += self._register_workflows(plugin_name, workflows)
            info.workflows = [self._workflow_id(w) for w in workflows]
        # Contrato por funções de registro (register_actions/register_workflows)
        if reg_actions is not None and self._registry is not None:
            try:
                before = self._registry_names()
                reg_actions(self._registry)
                info.actions = sorted(self._registry_names() - before)
            except Exception as exc:
                log.warn(
                    "register_actions falhou",
                    plugin=plugin_name,
                    error=type(exc).__name__,
                )
        if reg_workflows is not None and self._engine is not None:
            try:
                before = self._engine_ids()
                reg_workflows(self._engine)
                info.workflows = sorted(self._engine_ids() - before)
            except Exception as exc:
                log.warn(
                    "register_workflows falhou",
                    plugin=plugin_name,
                    error=type(exc).__name__,
                )
        with self._lock:
            self._plugins[plugin_name] = info
            self._metrics.loaded += 1
            self._metrics.actions_registered += len(info.actions)
            self._metrics.workflows_registered += len(info.workflows)
        log.info(
            "Plugin carregado",
            name=plugin_name,
            version=info.version,
            actions=len(info.actions),
            workflows=len(info.workflows),
        )
        self._publish(TOPIC_LOADED, info.to_dict())
        return registered

    def _import_module(self, path: Path) -> Any:
        """Importa o módulo Python isolado (mesmo padrão do ToolLoader)."""
        module_name = (
            f"od_plugin_{self._safe_name(path.stem)}"
            f"_{abs(hash(str(path))) % 10**8}"
        )
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginScopeError(f"não foi possível criar spec para {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    @staticmethod
    def _extract(
        module: Any, path: Path
    ) -> tuple[list[Any], list[Any], Optional[Callable[[Any], None]], Optional[Callable[[Any], None]]]:
        """Extrai entradas de action/workflow e funções de registro."""
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, dict):
            actions = list(plugin.get("actions") or [])
            workflows = list(plugin.get("workflows") or [])
        else:
            actions = list(getattr(module, "ACTIONS", None) or [])
            workflows = list(getattr(module, "WORKFLOWS", None) or [])
        reg_actions = getattr(module, "register_actions", None)
        reg_workflows = getattr(module, "register_workflows", None)
        return (
            actions,
            workflows,
            reg_actions if callable(reg_actions) else None,
            reg_workflows if callable(reg_workflows) else None,
        )

    def _register_actions(self, plugin_name: str, actions: list[Any]) -> int:
        if self._registry is None:
            return 0
        count = 0
        for entry in actions:
            if hasattr(entry, "name"):  # já é Action
                self._registry.register(entry)
                count += 1
                continue
            name = self._action_name(entry)
            handler = (
                entry.get("handler")
                or entry.get("fn")
                or entry.get("function")
                or entry.get("func")
            )
            if not name or not callable(handler):
                log.warn("Action de plugin inválida", plugin=plugin_name)
                continue
            self._registry.register_action(
                name,
                handler,
                description=entry.get("description", ""),
                category=entry.get("category", "plugin"),
                params=entry.get("params"),
                permission=entry.get("permission") or f"plugin.{plugin_name}",
                aliases=entry.get("aliases"),
                version=entry.get("version", "1.0.0"),
                source=f"plugin:{plugin_name}",
            )
            count += 1
        return count

    def _register_workflows(self, plugin_name: str, workflows: list[Any]) -> int:
        if self._engine is None:
            return 0
        count = 0
        for spec in workflows:
            if not hasattr(spec, "id"):
                log.warn("Workflow de plugin inválido", plugin=plugin_name)
                continue
            self._engine.register(spec)
            count += 1
        return count

    # -- Hot-reload -----------------------------------------------------------

    def reload(self, name: str) -> bool:
        """Descarga e recarrega um plugin do disco. Retorna True se ok."""
        with self._lock:
            info = self._plugins.get(name)
        if info is None:
            return False
        source = Path(info.source)
        self.unload(name)
        try:
            self._load_module_file(source)
            return True
        except Exception as exc:  # recarga falhou — plugin fica fora
            with self._lock:
                self._metrics.failed += 1
                self._metrics.errors += 1
            log.crit(
                "Recarga de plugin falhou",
                name=name,
                error=type(exc).__name__,
            )
            return False

    def reload_all(self) -> int:
        """Recarrega todos os plugins carregados. Retorna nº de sucessos."""
        ok = 0
        for name in self.list_names():
            if self.reload(name):
                ok += 1
        return ok

    def unload(self, name: str) -> bool:
        """Desregistra actions/workflows e remove o plugin do índice."""
        with self._lock:
            info = self._plugins.pop(name, None)
        if info is None:
            return False
        if self._registry is not None:
            for action_name in info.actions:
                try:
                    self._registry.unregister(action_name)
                except Exception:  # pragma: no cover — registry interno
                    pass
        if self._engine is not None:
            for workflow_id in info.workflows:
                try:
                    self._engine.unregister(workflow_id)
                except Exception:  # pragma: no cover — engine interno
                    pass
        log.info("Plugin descarregado", name=name, actions=len(info.actions))
        self._publish(TOPIC_UNLOADED, info.to_dict())
        return True

    # -- Introspecção ---------------------------------------------------------

    def list_plugins(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                info.to_dict() for info in sorted(
                    self._plugins.values(), key=lambda i: i.name
                )
            ]

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._plugins)

    def get(self, name: str) -> Optional[PluginInfo]:
        with self._lock:
            info = self._plugins.get(name)
            return info

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._plugins

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "status": "ok",
                "plugins": len(self._plugins),
                "failed": self._metrics.failed,
                "errors": self._metrics.errors,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "root": str(self._root),
                "plugins": len(self._plugins),
                "metrics": self._metrics.snapshot(),
            }

    def dump(self) -> dict[str, Any]:
        data = self.snapshot()
        data["plugins"] = self.list_plugins()
        return data

    # -- Internos -------------------------------------------------------------

    def _check_scope(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise PluginScopeError(
                f"plugin fora do root {self._root}: {resolved}"
            )

    @staticmethod
    def _plugin_name(module: Any, path: Path) -> str:
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, dict) and plugin.get("name"):
            return str(plugin["name"])
        return path.stem

    @staticmethod
    def _plugin_version(module: Any) -> str:
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, dict) and plugin.get("version"):
            return str(plugin["version"])
        return getattr(module, "PLUGIN_VERSION", "1.0.0")

    @staticmethod
    def _plugin_description(module: Any) -> str:
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, dict) and plugin.get("description"):
            return str(plugin["description"])
        return getattr(module, "PLUGIN_DESCRIPTION", "")

    @staticmethod
    def _action_name(entry: Any) -> str:
        if isinstance(entry, dict):
            return str(
                entry.get("name") or entry.get("tool") or entry.get("id") or ""
            )
        return getattr(entry, "name", "")

    @staticmethod
    def _workflow_id(entry: Any) -> str:
        return str(getattr(entry, "id", ""))

    @staticmethod
    def _safe_name(stem: str) -> str:
        return "".join(ch for ch in stem if ch.isalnum() or ch == "_") or "p"

    def _publish(self, topic: str, data: dict[str, Any]) -> None:
        """Evento best-effort (publica se houver loop ativo — nunca quebra)."""
        if self._event_bus is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # sem loop ativo — evento só logado
            return
        try:
            from core.event_bus import Event

            loop.create_task(
                self._event_bus.publish(
                    Event(topic=topic, data=data, source="plugins")
                )
            )
        except Exception:  # pragma: no cover — nunca quebra a carga
            pass

    def _registry_names(self) -> set[str]:
        """Nomes de actions atualmente registradas no ActionRegistry."""
        if self._registry is None:
            return set()
        try:
            return {
                str(item["name"]) for item in self._registry.list_actions()
            }
        except Exception:  # pragma: no cover — registry sem list_actions
            return set()

    def _engine_ids(self) -> set[str]:
        """Ids de workflows atualmente registrados no WorkflowEngine."""
        if self._engine is None:
            return set()
        try:
            return {str(item["id"]) for item in self._engine.list()}
        except Exception:  # pragma: no cover — engine sem list
            return set()