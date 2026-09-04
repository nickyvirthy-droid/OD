"""
OMEGA DRAKON • OBSERVABILITY
Tecnologia que respira.
Pacote: observability/
Descrição: Infraestrutura e observabilidade (Fase 7) — Audit System (7.1)
           com trilha persistente JSONL das decisões do sistema (spec §7.3).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - audit.py → AuditSystem (trilha persistente + sink de decisões de
               segurança + Event Bus + métricas/health)
"""

from observability.audit import (
    AUDIT_TOPIC,
    DEFAULT_KEEP,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_IN_MEMORY,
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    OUTCOME_ERROR,
    OUTCOME_INFO,
    SEVERITY_CRIT,
    SEVERITY_INFO,
    SEVERITY_WARN,
    AuditEntry,
    AuditMetrics,
    AuditSystem,
)

__signature__ = "OD // CORE"
__all__ = [
    "AuditSystem",
    "AuditEntry",
    "AuditMetrics",
    "AUDIT_TOPIC",
    "SEVERITY_INFO",
    "SEVERITY_WARN",
    "SEVERITY_CRIT",
    "OUTCOME_INFO",
    "OUTCOME_ALLOWED",
    "OUTCOME_DENIED",
    "OUTCOME_ERROR",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_KEEP",
    "DEFAULT_MAX_IN_MEMORY",
]