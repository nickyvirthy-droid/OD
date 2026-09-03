"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/approval.py
Descrição: Approval Engine — aprovação humana para ações sensíveis.
           Desativado por padrão (compatibility mode).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (camada 4: Approval Engine)
  - OMEGADRAKON_SPEC.md §7.2 (comandos destrutivos exigem aprovação humana)
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from core.security.models import ActionRequest, CheckResult

logger = logging.getLogger("omega.core.security.approval")

NICKY_PREFIX = "[NICKY][{level}]"


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# PendingApproval
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PendingApproval:
    """Uma aprovação pendente aguardando decisão humana."""

    token: str
    request_id: str
    action: str
    role: str
    source: str
    created_ts: float = field(default_factory=time.time)
    status: str = "pending"  # "pending" | "approved" | "rejected" | "expired"
    approved_ts: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "request_id": self.request_id,
            "action": self.action,
            "role": self.role,
            "source": self.source,
            "created_ts": self.created_ts,
            "status": self.status,
            "approved_ts": self.approved_ts,
        }


# ---------------------------------------------------------------------------
# ApprovalEngine
# ---------------------------------------------------------------------------

class ApprovalEngine:
    """Camada 4 — Approval Engine: aprovação humana opcional.

    Quando habilitada, ações que exigem aprovação geram um token pendente.
    O token deve ser apresentado em request.approval_token para a ação ser
    autorizada. Desativada por padrão (compatibilidade).

    Attributes:
        enabled:          Se a camada está ativa.
        require_approval_actions: Ações que exigem aprovação humana.
        approval_ttl:     Tempo de vida do token em segundos (0 = sem expiração).
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        approval_ttl: float = 300.0,
    ) -> None:
        self._enabled = enabled
        self._approval_ttl = approval_ttl
        self._require_approval: set[str] = set()
        self._pending: dict[str, PendingApproval] = {}

    # -- Configuração --------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Liga/desliga a camada de aprovação."""
        self._enabled = enabled

    def require_approval(self, action_pattern: str) -> None:
        """Marca um padrão de ação como exigindo aprovação humana."""
        self._require_approval.add(action_pattern)

    def remove_approval_requirement(self, action_pattern: str) -> bool:
        """Remove a exigência de aprovação. Retorna True se existia."""
        if action_pattern in self._require_approval:
            self._require_approval.remove(action_pattern)
            return True
        return False

    def requires_approval(self, action: str) -> bool:
        """Verifica se uma ação exige aprovação humana."""
        import fnmatch

        for pattern in self._require_approval:
            if fnmatch.fnmatchcase(action, pattern):
                return True
        return False

    # -- Ciclo de vida das aprovações ----------------------------------------

    def request_approval(self, request: ActionRequest) -> PendingApproval:
        """Cria uma aprovação pendente para a requisição.

        Returns:
            PendingApproval com token único.
        """
        token = secrets.token_hex(8)
        pending = PendingApproval(
            token=token,
            request_id=request.request_id,
            action=request.action,
            role=request.role,
            source=request.source,
        )
        self._pending[request.request_id] = pending
        _audit_nicky(
            "INFO",
            "Approval requested",
            request_id=request.request_id,
            action=request.action,
        )
        return pending

    def approve(self, token: str) -> bool:
        """Aprova uma aprovação pendente pelo token.

        Returns:
            True se o token existia e foi aprovado.
        """
        for request_id, pending in self._pending.items():
            if pending.token == token and pending.status == "pending":
                if self._is_expired(pending):
                    pending.status = "expired"
                    return False
                pending.status = "approved"
                pending.approved_ts = time.time()
                _audit_nicky(
                    "INFO",
                    "Approval granted",
                    request_id=request_id,
                    action=pending.action,
                )
                return True
        return False

    def reject(self, token: str) -> bool:
        """Rejeita uma aprovação pendente pelo token.

        Returns:
            True se o token existia e foi rejeitado.
        """
        for request_id, pending in self._pending.items():
            if pending.token == token and pending.status == "pending":
                pending.status = "rejected"
                _audit_nicky(
                    "WARN",
                    "Approval rejected",
                    request_id=request_id,
                    action=pending.action,
                )
                return True
        return False

    def is_approved(self, request: ActionRequest) -> bool:
        """Verifica se o token da requisição corresponde a uma aprovação válida.

        O token é um segredo aleatório único; a correspondência é feita apenas
        pelo token (o request_id é regenerado a cada chamada de check()).
        """
        if not request.approval_token:
            return False
        for pending in self._pending.values():
            if (
                pending.token == request.approval_token
                and pending.status == "approved"
            ):
                if self._is_expired(pending):
                    return False
                return True
        return False

    def get_pending(self, request_id: str) -> Optional[PendingApproval]:
        return self._pending.get(request_id)

    def list_pending(self) -> list[PendingApproval]:
        return list(self._pending.values())

    def _is_expired(self, pending: PendingApproval) -> bool:
        if self._approval_ttl <= 0:
            return False
        return (time.time() - pending.created_ts) > self._approval_ttl

    # -- Avaliação -----------------------------------------------------------

    def evaluate(self, request: ActionRequest) -> CheckResult:
        """Avalia se a requisição tem aprovação válida (se exigida).

        Se a camada está desativada, sempre permite.
        """
        if not self._enabled:
            return CheckResult(layer="approval", allowed=True)

        if not self.requires_approval(request.action):
            return CheckResult(layer="approval", allowed=True)

        if self.is_approved(request):
            return CheckResult(layer="approval", allowed=True)

        # Cria pendência se ainda não existe
        pending = self._pending.get(request.request_id)
        if pending is None:
            self.request_approval(request)

        _audit_nicky(
            "WARN",
            "Approval required but not provided",
            action=request.action,
            request_id=request.request_id,
        )
        return CheckResult(
            layer="approval",
            allowed=False,
            reason=f"Action '{request.action}' requires human approval",
        )

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "approval_ttl": self._approval_ttl,
            "require_approval": sorted(self._require_approval),
            "pending_count": len(self._pending),
            "pending": [p.to_dict() for p in self._pending.values()],
        }