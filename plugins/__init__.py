"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: plugins/
Descrição: Plugin System (Fase 7, item 7.4) — carregamento dinâmico de
           plugins Python com registro de actions no Action Registry e de
           workflows no Workflow Engine, hot-reload e escopo estrito.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - manager.py → PluginManager (descoberta + carga + reload/unload)
"""

from plugins.manager import (
    TOPIC_FAILED,
    TOPIC_LOADED,
    TOPIC_UNLOADED,
    PluginInfo,
    PluginManager,
    PluginMetrics,
    PluginScopeError,
)

__signature__ = "OD // CORE"
__all__ = [
    "PluginManager",
    "PluginInfo",
    "PluginMetrics",
    "PluginScopeError",
    "TOPIC_LOADED",
    "TOPIC_FAILED",
    "TOPIC_UNLOADED",
]