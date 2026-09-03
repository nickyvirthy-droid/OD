"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/audit.py
Descrição: Audit Engine — registro contínuo de todas as decisões de segurança
           (spec §7.3), com ring buffer em memória e sink opcional.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (camada 5: Audit Engine)
  - OMEGADRAKON_SPEC.md §7.3 (auditoria contínua com timestamp e sessão)
"""

from __future__ import annotations

__signature__ = "OD // CORE"

from core.logger import make_audit_nicky
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.security.models import AuditRecord, SecurityDecision

_audit_nicky = make_audit_nicky("omega.core.security.audit")





# Callback de sink: recebe o AuditRecord para persistência externa
AuditSink = Callable[[AuditRecord], None]


@dataclass(slots=True)
class AuditMetrics:
    """Métricas de auditoria."""
    total: int = 0
    allowed: int = 0
    denied: int = 0
    approval_required: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "total": self.total,
            "allowed": self.allowed,
            "denied": self.denied,
            "approval_required": self.approval_required,
        }


# ---------------------------------------------------------------------------
# AuditEngine
# ---------------------------------------------------------------------------

class AuditEngine:
    """Camada 5 — Audit Engine: trilha de auditoria contínua.

    Registra toda decisão de segurança com timestamp e identificador de
    sessão (spec §7.3). Mantém um ring buffer em memória e pode encaminhar
    cada registro para sinks externos (logger, Event Bus, banco).

    Attributes:
        max_records: Tamanho do ring buffer em memória.
        metrics:     Contadores de auditoria.
    """

    def __init__(
        self,
        *,
        max_records: int = 1000,
        sinks: Optional[list[AuditSink]] = None,
    ) -> None:
        self._max_records = max_records
        self._records: list[AuditRecord] = []
        self._sinks: list[AuditSink] = list(sinks or [])
        self._metrics = AuditMetrics()

    @property
    def metrics(self) -> AuditMetrics:
        return self._metrics

    # -- Sinks ---------------------------------------------------------------

    def add_sink(self, sink: AuditSink) -> None:
        """Adiciona um callback que recebe cada AuditRecord."""
        if sink not in self._sinks:
            self._sinks.append(sink)

    def remove_sink(self, sink: AuditSink) -> bool:
        """Remove um sink. Retorna True se existia."""
        if sink in self._sinks:
            self._sinks.remove(sink)
            return True
        return False

    # -- Registro ------------------------------------------------------------

    def record(self, decision: SecurityDecision) -> AuditRecord:
        """Registra uma decisão e notifica os sinks."""
        record = AuditRecord.from_decision(decision)

        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

        self._metrics.total += 1
        if decision.allowed:
            self._metrics.allowed += 1
        else:
            self._metrics.denied += 1
        if decision.approval_required:
            self._metrics.approval_required += 1

        for sink in self._sinks:
            try:
                sink(record)
            except Exception as exc:  # sink nunca pode quebrar a auditoria
                _audit_nicky(
                    "WARN",
                    "Audit sink error",
                    error=type(exc).__name__,
                )

        level = "INFO" if decision.allowed else "CRIT"
        _audit_nicky(
            level,
            "Security decision",
            action=decision.request.action,
            allowed=decision.allowed,
            denied_by=decision.denied_by or "",
            request_id=decision.request.request_id,
            session_id=decision.request.session_id or "",
        )
        return record

    # -- Consulta ------------------------------------------------------------

    @property
    def records(self) -> list[AuditRecord]:
        return list(self._records)

    def export(self) -> list[dict[str, Any]]:
        """Exporta os registros como lista de dicts serializáveis."""
        return [r.to_dict() for r in self._records]

    def clear(self) -> int:
        """Limpa o ring buffer. Retorna quantidade removida."""
        count = len(self._records)
        self._records.clear()
        self._metrics = AuditMetrics()
        return count

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "records": len(self._records),
            "max_records": self._max_records,
            "sinks": len(self._sinks),
            "metrics": self._metrics.snapshot(),
        }