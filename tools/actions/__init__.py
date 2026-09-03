"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/actions
Descrição: Pacote do catálogo de Actions — 56 ações operacionais (sistema,
           processos, docker, serviços, arquivos, git, banco de dados,
           introspecção) registradas no Action Registry com permission
           própria (gate do Security Layer na execução).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/actions/ (56 actions operacionais)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.4
"""
__signature__ = "OD // CORE"

from typing import Any, Optional

from tools.actions.actions import CATALOG, CATEGORIES, ACTIONS_COUNT
from tools.registry import Action, ActionRegistry


def register_all(registry: ActionRegistry) -> int:
    """Registra as 56 ações do catálogo no registry (idempotente via skip)."""
    registered = 0
    for spec in CATALOG:
        action = Action(
            name=spec["name"],
            handler=spec["handler"],
            description=spec["description"],
            category=spec["category"],
            params=dict(spec["params"]),
            permission=spec["name"],
            version="1.0.0",
            source="tools/actions",
        )
        if registry.register(action):
            registered += 1
    return registered


def build_registry(
    *,
    security: Optional[Any] = None,
    allow_overwrite: bool = False,
) -> ActionRegistry:
    """Constrói um ActionRegistry já populado com as 56 ações do catálogo.

    Exemplo:
        from core.security import SecurityManager
        from tools.actions import build_registry

        registry = build_registry(security=SecurityManager(mode="strict"))
        result = await registry.execute("system_info", role="admin")
    """
    registry = ActionRegistry(
        security=security,
        allow_overwrite=allow_overwrite,
    )
    register_all(registry)
    return registry


__all__ = [
    "ACTIONS_COUNT",
    "CATALOG",
    "CATEGORIES",
    "ActionRegistry",
    "build_registry",
    "register_all",
]
