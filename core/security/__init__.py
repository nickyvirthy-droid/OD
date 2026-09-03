"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/__init__.py
Descrição: Security Layer do OmegaDrakon — pipeline de validação em camadas:
           policy → permission → scope → approval → audit.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/security/ (pipeline de 5 camadas)
  - OMEGADRAKON_SPEC.md §7 (Security Boundaries)
  - ROADMAP_ABSORCAO.md Fase 1 (1.2 Security Layer)
"""
__signature__ = "OD // CORE"

from core.security.models import (
    ActionRequest,
    AuditRecord,
    CheckResult,
    EnforcementMode,
    SecurityDecision,
)
from core.security.policy import PolicyEngine
from core.security.permissions import PermissionEngine
from core.security.scope import ScopeEngine
from core.security.approval import ApprovalEngine
from core.security.audit import AuditEngine
from core.security.manager import SecurityManager

__all__ = [
    "ActionRequest",
    "ApprovalEngine",
    "AuditEngine",
    "AuditRecord",
    "CheckResult",
    "EnforcementMode",
    "PermissionEngine",
    "PolicyEngine",
    "ScopeEngine",
    "SecurityDecision",
    "SecurityManager",
]