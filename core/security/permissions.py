"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/permissions.py
Descrição: Permission Engine — papéis (roles) mapeados para padrões de ações
           permitidas, com menor privilégio por padrão.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (camada 2: Permission Engine)
  - OMEGADRAKON_SPEC.md §7.2 (Least Privilege)
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from core.security.models import ActionRequest, CheckResult

logger = logging.getLogger("omega.core.security.permissions")

NICKY_PREFIX = "[NICKY][{level}]"


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# Defaults — menor privilégio
# ---------------------------------------------------------------------------

# Papéis padrão com permissões mínimas seguras (catálogo tools/ chega na Fase 4)
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "agent": [
        "system.status",
        "system.health",
        "system.info",
        "filesystem.read",
        "filesystem.list",
        "filesystem.info",
        "filesystem.search",
        "filesystem.exists",
        "memory.*",
        "knowledge.*",
        "config.read",
        "config.get",
    ],
    "admin": ["*"],
    "router": ["router.*"],
}

UNKNOWN_ROLE_POLICY = "deny"  # "deny" | "allow" — papéis desconhecidos


# ---------------------------------------------------------------------------
# PermissionEngine
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PermissionEngine:
    """Camada 2 — Permission Engine: permissões por papel.

    Cada papel possui um conjunto de padrões fnmatch de ações permitidas.
    O padrão "*" concede acesso total. Papéis desconhecidos são negados
    por padrão (fail-safe).

    Attributes:
        role_permissions: dict role -> lista de padrões de ações.
        unknown_role_policy: "deny" (padrão) ou "allow".
    """

    role_permissions: dict[str, list[str]] = field(
        default_factory=lambda: {
            role: list(patterns)
            for role, patterns in DEFAULT_ROLE_PERMISSIONS.items()
        }
    )
    unknown_role_policy: str = UNKNOWN_ROLE_POLICY

    # -- Regras --------------------------------------------------------------

    def grant(self, role: str, action_pattern: str) -> None:
        """Concede a um papel o padrão de ação (ex: "filesystem.*")."""
        if role not in self.role_permissions:
            self.role_permissions[role] = []
        if action_pattern not in self.role_permissions[role]:
            self.role_permissions[role].append(action_pattern)

    def revoke(self, role: str, action_pattern: str) -> bool:
        """Remove um padrão de ação de um papel. Retorna True se existia."""
        patterns = self.role_permissions.get(role)
        if not patterns or action_pattern not in patterns:
            return False
        patterns.remove(action_pattern)
        return True

    def revoke_role(self, role: str) -> bool:
        """Remove um papel inteiro. Retorna True se existia."""
        return self.role_permissions.pop(role, None) is not None

    def is_allowed(self, role: str, action: str) -> bool:
        """Verifica se um papel pode executar uma ação (sem audit)."""
        patterns = self.role_permissions.get(role)
        if patterns is None:
            return self.unknown_role_policy == "allow"
        for pattern in patterns:
            if fnmatch.fnmatchcase(action, pattern):
                return True
        return False

    def list_roles(self) -> list[str]:
        return sorted(self.role_permissions.keys())

    def permissions_for(self, role: str) -> list[str]:
        return list(self.role_permissions.get(role, []))

    # -- Avaliação -----------------------------------------------------------

    def evaluate(self, request: ActionRequest) -> CheckResult:
        """Avalia se o papel da requisição pode executar a ação."""
        patterns = self.role_permissions.get(request.role)

        if patterns is None:
            denied = self.unknown_role_policy == "deny"
            reason = (
                f"Unknown role '{request.role}' is denied by policy"
                if denied
                else ""
            )
            if denied:
                _audit_nicky(
                    "WARN",
                    "Unknown role denied",
                    role=request.role,
                    action=request.action,
                    request_id=request.request_id,
                )
            return CheckResult(
                layer="permission",
                allowed=not denied,
                reason=reason,
            )

        if self._matches_any(request.action, patterns):
            return CheckResult(layer="permission", allowed=True)

        _audit_nicky(
            "WARN",
            "Permission denied",
            role=request.role,
            action=request.action,
            request_id=request.request_id,
        )
        return CheckResult(
            layer="permission",
            allowed=False,
            reason=f"Role '{request.role}' has no permission for action '{request.action}'",
        )

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _matches_any(value: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            if fnmatch.fnmatchcase(value, pattern):
                return True
        return False

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "unknown_role_policy": self.unknown_role_policy,
            "roles": {
                role: list(patterns)
                for role, patterns in self.role_permissions.items()
            },
        }