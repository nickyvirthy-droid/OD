"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/policy.py
Descrição: Policy Engine — regras globais de allow/deny por padrão de nome
           de ação e detecção de tokens destrutivos em parâmetros.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (camada 1: Policy Engine)
  - OMEGADRAKON_SPEC.md §7.2 (comandos destrutivos proibidos)
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from core.security.models import ActionRequest, CheckResult

logger = logging.getLogger("omega.core.security.policy")

NICKY_PREFIX = "[NICKY][{level}]"


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# Defaults (spec §7.2 — comandos destrutivos proibidos para agentes)
# ---------------------------------------------------------------------------

DEFAULT_DENY_PATTERNS: list[str] = [
    "system.shutdown",
    "system.reboot",
    "system.halt",
    "process.killall",
    "database.drop_table",
    "database.drop_database",
    "database.truncate",
    "filesystem.wipe",
    "filesystem.format",
    "security.disable",
    "security.disable_layer",
]

# Tokens destrutivos procurados (case-insensitive) na serialização dos params
DEFAULT_DESTRUCTIVE_TOKENS: list[str] = [
    "rm -rf",
    "rm -fr",
    "rm --recursive --force",
    "rm -r -f",
    "DROP TABLE",
    "DROP DATABASE",
    "TRUNCATE TABLE",
    "mkfs",
    "format c:",
    "dd if=/dev/zero",
    "chmod -R 777",
    ":(){ :|:& };:",
    "shutdown -h",
    "reboot -f",
    "git push --force",
]


# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PolicyEngine:
    """Camada 1 — Policy Engine: regras globais da organização.

    Avalia:
      1. Padrões de deny no nome da ação (sempre bloqueiam).
      2. Padrões de allow no nome da ação (quando allowlist ativa).
      3. Tokens destrutivos nos parâmetros serializados (sempre bloqueiam).

    Attributes:
        allowlist_enabled: Se True, ações sem match em allow são negadas.
        deny_patterns:   Padrões fnmatch de ações proibidas.
        allow_patterns:  Padrões fnmatch de ações permitidas.
        destructive_tokens: Substrings proibidas nos parâmetros.
    """

    allowlist_enabled: bool = False
    deny_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_DENY_PATTERNS))
    allow_patterns: list[str] = field(default_factory=list)
    destructive_tokens: list[str] = field(
        default_factory=lambda: list(DEFAULT_DESTRUCTIVE_TOKENS)
    )

    # -- Regras --------------------------------------------------------------

    def add_deny(self, pattern: str) -> None:
        """Adiciona padrão de ação proibida (fnmatch)."""
        if pattern not in self.deny_patterns:
            self.deny_patterns.append(pattern)

    def remove_deny(self, pattern: str) -> bool:
        """Remove padrão de deny. Retorna True se existia."""
        if pattern in self.deny_patterns:
            self.deny_patterns.remove(pattern)
            return True
        return False

    def add_allow(self, pattern: str) -> None:
        """Adiciona padrão de ação permitida (fnmatch)."""
        if pattern not in self.allow_patterns:
            self.allow_patterns.append(pattern)

    def remove_allow(self, pattern: str) -> bool:
        """Remove padrão de allow. Retorna True se existia."""
        if pattern in self.allow_patterns:
            self.allow_patterns.remove(pattern)
            return True
        return False

    def add_destructive_token(self, token: str) -> None:
        """Adiciona substring proibida em parâmetros."""
        if token not in self.destructive_tokens:
            self.destructive_tokens.append(token)

    def remove_destructive_token(self, token: str) -> bool:
        """Remove token destrutivo. Retorna True se existia."""
        if token in self.destructive_tokens:
            self.destructive_tokens.remove(token)
            return True
        return False

    def set_allowlist(self, enabled: bool) -> None:
        """Liga/desliga o modo allowlist (deny-by-default para ações)."""
        self.allowlist_enabled = enabled

    def clear(self) -> None:
        """Limpa todas as regras customizadas (mantém defaults)."""
        self.deny_patterns = list(DEFAULT_DENY_PATTERNS)
        self.allow_patterns = []
        self.destructive_tokens = list(DEFAULT_DESTRUCTIVE_TOKENS)
        self.allowlist_enabled = False

    # -- Avaliação -----------------------------------------------------------

    def evaluate(self, request: ActionRequest) -> CheckResult:
        """Avalia a requisição contra as regras globais.

        Retorna CheckResult com layer="policy".
        """
        # 1. Deny patterns no nome da ação
        if self._matches_any(request.action, self.deny_patterns):
            _audit_nicky(
                "WARN",
                "Policy deny match",
                action=request.action,
                request_id=request.request_id,
            )
            return CheckResult(
                layer="policy",
                allowed=False,
                reason=f"Action '{request.action}' is denied by policy",
            )

        # 2. Allowlist (deny-by-default)
        if self.allowlist_enabled and not self._matches_any(request.action, self.allow_patterns):
            _audit_nicky(
                "WARN",
                "Policy allowlist miss",
                action=request.action,
                request_id=request.request_id,
            )
            return CheckResult(
                layer="policy",
                allowed=False,
                reason=f"Action '{request.action}' is not in the allowlist",
            )

        # 3. Tokens destrutivos nos parâmetros
        token = self._find_destructive_token(request)
        if token is not None:
            _audit_nicky(
                "CRIT",
                "Destructive token detected",
                action=request.action,
                token=token,
                request_id=request.request_id,
            )
            return CheckResult(
                layer="policy",
                allowed=False,
                reason=f"Destructive token detected in params: '{token}'",
            )

        return CheckResult(layer="policy", allowed=True)

    # -- Helpers -------------------------------------------------------------

    def _matches_any(self, value: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            if fnmatch.fnmatchcase(value, pattern):
                return True
        return False

    def _find_destructive_token(self, request: ActionRequest) -> Optional[str]:
        if not request.params:
            return None
        serialized = repr(request.params).lower()
        for token in self.destructive_tokens:
            if token.lower() in serialized:
                return token
        return None

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "allowlist_enabled": self.allowlist_enabled,
            "deny_patterns": list(self.deny_patterns),
            "allow_patterns": list(self.allow_patterns),
            "destructive_tokens": list(self.destructive_tokens),
        }