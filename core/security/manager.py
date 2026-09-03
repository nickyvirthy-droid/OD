"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/manager.py
Descrição: SecurityManager — orquestra o pipeline de validação em camadas:
           policy → permission → scope → approval → audit.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (pipeline de 5 camadas)
  - OMEGADRAKON_SPEC.md §7 (Security Boundaries)
  - ROADMAP_ABSORCAO.md Fase 1, item 1.2

Architecture:
    O SecurityManager é a única porta de entrada do Security Layer. Ele
    executa as camadas em ordem fixa, aplica o modo de enforcement e
    registra toda decisão na camada de auditoria.

    Modos de enforcement:
      - COMPATIBILITY: apenas audita, nunca bloqueia (padrão)
      - SOFT: audita + registra warning, mas permite
      - STRICT: fail-closed — bloqueia se qualquer camada rejeitar

Usage:
    from core.security import SecurityManager, ActionRequest

    security = SecurityManager(mode="strict")

    decision = security.check(
        "filesystem.delete",
        paths=["/home/alex/OmegaDrakon/tmp/file.txt"],
        role="agent",
    )
    if decision.allowed:
        # executar ação
        pass
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from core.security.approval import ApprovalEngine
from core.security.audit import AuditEngine
from core.security.models import (
    ActionRequest,
    CheckResult,
    EnforcementMode,
    SecurityDecision,
)
from core.security.permissions import PermissionEngine
from core.security.policy import PolicyEngine
from core.security.scope import ScopeEngine

logger = logging.getLogger("omega.core.security.manager")

NICKY_PREFIX = "[NICKY][{level}]"

PIPELINE_ORDER = ("policy", "permission", "scope", "approval")


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


@dataclass(slots=True)
class SecurityMetrics:
    """Métricas do Security Layer."""
    validated: int = 0
    allowed: int = 0
    denied: int = 0
    approvals_pending: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "validated": self.validated,
            "allowed": self.allowed,
            "denied": self.denied,
            "approvals_pending": self.approvals_pending,
        }


# ---------------------------------------------------------------------------
# SecurityManager
# ---------------------------------------------------------------------------

class SecurityManager:
    """Orquestrador do pipeline de validação de segurança.

    Attributes:
        policy_engine:     Camada 1 — Policy Engine.
        permission_engine: Camada 2 — Permission Engine.
        scope_engine:      Camada 3 — Scope Engine.
        approval_engine:   Camada 4 — Approval Engine.
        audit_engine:      Camada 5 — Audit Engine.
        mode:              Modo de enforcement ativo.
        metrics:           Contadores de validação.
    """

    def __init__(
        self,
        *,
        mode: EnforcementMode | str = EnforcementMode.COMPATIBILITY,
        policy_engine: Optional[PolicyEngine] = None,
        permission_engine: Optional[PermissionEngine] = None,
        scope_engine: Optional[ScopeEngine] = None,
        approval_engine: Optional[ApprovalEngine] = None,
        audit_engine: Optional[AuditEngine] = None,
        audit_sinks: Optional[list[Any]] = None,
    ) -> None:
        self._mode = EnforcementMode.parse(mode)
        self.policy_engine = policy_engine or PolicyEngine()
        self.permission_engine = permission_engine or PermissionEngine()
        self.scope_engine = scope_engine or ScopeEngine()
        self.approval_engine = approval_engine or ApprovalEngine()
        self.audit_engine = audit_engine or AuditEngine(sinks=audit_sinks)
        self._metrics = SecurityMetrics()
        self._running = False

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def mode(self) -> EnforcementMode:
        return self._mode

    @property
    def metrics(self) -> SecurityMetrics:
        return self._metrics

    def set_mode(self, mode: EnforcementMode | str) -> None:
        """Altera o modo de enforcement em tempo de execução."""
        self._mode = EnforcementMode.parse(mode)
        _audit_nicky("INFO", "Enforcement mode set", mode=self._mode.value)

    def start(self) -> None:
        """Inicializa o Security Layer (idempotente)."""
        if self._running:
            _audit_nicky("WARN", "SecurityManager already running")
            return
        self._running = True
        _audit_nicky(
            "INFO",
            "SecurityManager started",
            mode=self._mode.value,
        )

    def stop(self) -> None:
        """Finaliza o Security Layer."""
        if not self._running:
            return
        self._running = False
        _audit_nicky(
            "INFO",
            "SecurityManager stopped",
            decisions=self._metrics.validated,
        )

    # -- Validação -----------------------------------------------------------

    def validate(self, request: ActionRequest) -> SecurityDecision:
        """Valida uma requisição através do pipeline completo.

        Executa as camadas em ordem fixa (policy → permission → scope →
        approval), aplica o modo de enforcement e registra a decisão na
        auditoria.

        Args:
            request: A requisição de ação a validar.

        Returns:
            SecurityDecision com allowed, denied_by e reasons.
        """
        self._metrics.validated += 1

        checks: dict[str, CheckResult] = {}
        for layer in PIPELINE_ORDER:
            engine = getattr(self, f"{layer}_engine")
            checks[layer] = engine.evaluate(request)

        denied_checks = [
            c for c in checks.values() if not c.allowed
        ]

        decision = SecurityDecision(
            request=request,
            allowed=True,
            mode=self._mode,
        )

        if denied_checks:
            reasons = [c.reason for c in denied_checks if c.reason]
            decision.reasons.extend(reasons)
            first_denied = denied_checks[0]

            if self._mode == EnforcementMode.STRICT:
                decision.allowed = False
                decision.denied_by = first_denied.layer
            else:
                # SOFT/COMPATIBILITY: permite, mas registra os motivos
                decision.allowed = True
                decision.denied_by = None
                _audit_nicky(
                    "WARN" if self._mode == EnforcementMode.SOFT else "INFO",
                    "Security check flagged (non-blocking)",
                    action=request.action,
                    mode=self._mode.value,
                    denied_by=first_denied.layer,
                )

        # Aprovação: mesmo permitido, registrar exigência/pendência
        approval_result = checks["approval"]
        if not approval_result.allowed:
            decision.approval_required = True
            decision.approval_pending = True
            self._metrics.approvals_pending += 1
            if self._mode == EnforcementMode.STRICT:
                decision.allowed = False
                decision.denied_by = "approval"
        elif self.approval_engine.enabled and self.approval_engine.requires_approval(
            request.action
        ):
            decision.approval_required = True

        # Auditoria contínua (spec §7.3) — nunca é bloqueada
        self.audit_engine.record(decision)

        if decision.allowed:
            self._metrics.allowed += 1
        else:
            self._metrics.denied += 1

        return decision

    def check(
        self,
        action: str,
        *,
        params: Optional[dict[str, Any]] = None,
        role: str = "agent",
        source: str = "",
        session_id: str = "",
        paths: Optional[list[str]] = None,
        destructive: bool = False,
        requires_root: bool = False,
        approval_token: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SecurityDecision:
        """Conveniência para validar uma ação sem montar ActionRequest.

        Args:
            action: Nome da ação (ex: "filesystem.read").
            params: Parâmetros da ação.
            role:   Papel do solicitante (padrão: "agent").
            source: Componente de origem.
            session_id: Sessão para auditoria.
            paths:  Caminhos afetados pela ação.
            destructive: Marca a operação como destrutiva.
            requires_root: Marca a ação como exigindo root.
            approval_token: Token de aprovação humana.
            metadata: Metadados extras (ex: {"operation": "read"}).

        Returns:
            SecurityDecision com a decisão do pipeline.
        """
        request = ActionRequest(
            action=action,
            params=dict(params or {}),
            role=role,
            source=source,
            session_id=session_id,
            paths=list(paths or []),
            destructive=destructive,
            requires_root=requires_root,
            approval_token=approval_token,
            metadata=dict(metadata or {}),
        )
        return self.validate(request)

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico completo do Security Layer."""
        return {
            "running": self._running,
            "mode": self._mode.value,
            "pipeline": list(PIPELINE_ORDER),
            "metrics": self._metrics.snapshot(),
            "policy": self.policy_engine.dump(),
            "permissions": self.permission_engine.dump(),
            "scope": self.scope_engine.dump(),
            "approval": self.approval_engine.dump(),
            "audit": self.audit_engine.dump(),
        }