"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/models.py
Descrição: Modelos de dados compartilhados do Security Layer — ActionRequest,
           EnforcementMode, CheckResult, SecurityDecision, AuditRecord.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enforcement Mode
# ---------------------------------------------------------------------------

class EnforcementMode(str, Enum):
    """Modo de enforcement do Security Layer.

    - COMPATIBILITY: apenas audita, nunca bloqueia (padrão)
    - SOFT: audita + registra warning, mas permite
    - STRICT: fail-closed — bloqueia se qualquer camada rejeitar
    """

    COMPATIBILITY = "compatibility"
    SOFT = "soft"
    STRICT = "strict"

    @classmethod
    def parse(cls, value: str | "EnforcementMode") -> "EnforcementMode":
        if isinstance(value, EnforcementMode):
            return value
        return cls(value.lower())


# ---------------------------------------------------------------------------
# ActionRequest
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ActionRequest:
    """Uma requisição de execução de ação a ser validada pelo Security Layer.

    Attributes:
        action:      Nome da ação (ex: "filesystem.delete", "system.shutdown").
        params:      Parâmetros da ação (validados contra tokens destrutivos
                     e caminhos no Scope Engine).
        role:        Papel do solicitante (ex: "agent", "admin").
        source:      Identificador do componente de origem.
        session_id:  Identificador de sessão para auditoria contínua.
        paths:       Caminhos de recursos afetados (escopo filesystem).
        destructive: Flag explícita de operação destrutiva.
        requires_root: True se a ação exige privilégios de superusuário.
        approval_token: Token de aprovação humana (se exigida).
        metadata:    Metadados extras (ex: operation="read"|"write").
        request_id:  Identificador único da requisição (auto-gerado).
        ts:          Timestamp de criação (auto-definido).
    """

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    role: str = "agent"
    source: str = ""
    session_id: str = ""
    paths: list[str] = field(default_factory=list)
    destructive: bool = False
    requires_root: bool = False
    approval_token: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CheckResult:
    """Resultado de uma camada individual do pipeline.

    Attributes:
        layer:   Nome da camada ("policy", "permission", "scope", "approval").
        allowed: True se a camada permitiu.
        reason:  Motivo da decisão (quando negada).
    """

    layer: str
    allowed: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# SecurityDecision
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SecurityDecision:
    """Decisão final do Security Layer sobre uma requisição.

    Attributes:
        request:          A requisição original.
        allowed:          True se a ação pode ser executada.
        mode:             Modo de enforcement utilizado.
        denied_by:        Nome da camada que negou (None se permitida).
        reasons:          Lista de motivos (negativas e warnings).
        approval_required: True se a ação exige aprovação humana.
        approval_pending:  True se a aprovação está pendente.
    """

    request: ActionRequest
    allowed: bool
    mode: EnforcementMode
    denied_by: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    approval_required: bool = False
    approval_pending: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request.request_id,
            "action": self.request.action,
            "role": self.request.role,
            "source": self.request.source,
            "session_id": self.request.session_id,
            "allowed": self.allowed,
            "mode": self.mode.value,
            "denied_by": self.denied_by,
            "reasons": list(self.reasons),
            "approval_required": self.approval_required,
            "approval_pending": self.approval_pending,
            "ts": self.request.ts,
        }


# ---------------------------------------------------------------------------
# AuditRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Registro de auditoria de uma decisão de segurança (spec §7.3)."""

    ts: float
    mode: EnforcementMode
    request_id: str
    action: str
    role: str
    source: str
    session_id: str
    allowed: bool
    denied_by: Optional[str]
    reasons: tuple[str, ...]
    approval_required: bool = False
    approval_pending: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 6),
            "mode": self.mode.value,
            "request_id": self.request_id,
            "action": self.action,
            "role": self.role,
            "source": self.source,
            "session_id": self.session_id,
            "allowed": self.allowed,
            "denied_by": self.denied_by,
            "reasons": list(self.reasons),
            "approval_required": self.approval_required,
            "approval_pending": self.approval_pending,
        }

    @classmethod
    def from_decision(cls, decision: SecurityDecision) -> "AuditRecord":
        return cls(
            ts=decision.request.ts,
            mode=decision.mode,
            request_id=decision.request.request_id,
            action=decision.request.action,
            role=decision.request.role,
            source=decision.request.source,
            session_id=decision.request.session_id,
            allowed=decision.allowed,
            denied_by=decision.denied_by,
            reasons=tuple(decision.reasons),
            approval_required=decision.approval_required,
            approval_pending=decision.approval_pending,
        )