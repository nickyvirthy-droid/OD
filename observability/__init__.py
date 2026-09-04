"""
OMEGA DRAKON • OBSERVABILITY
Tecnologia que respira.
Pacote: observability/
Descrição: Infraestrutura e observabilidade (Fase 7) — Audit System (7.1)
           com trilha persistente JSONL e Metrics Collector (7.2) com
           exposição Prometheus text format.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - audit.py → AuditSystem (trilha persistente + sink de decisões de
               segurança + Event Bus + métricas/health)
  - metrics.py → MetricsCollector (Counter/Gauge com labels + sources +
                 exposição Prometheus text format)
  - health.py → HealthMonitor (checks registráveis por componente +
                agregação up/degraded/down)
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
from observability.metrics import (
    TYPE_COUNTER,
    TYPE_GAUGE,
    Metric,
    MetricSource,
    MetricsCollector,
)
from observability.health import (
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_UP,
    ComponentHealth,
    HealthCheckFn,
    HealthMetrics,
    HealthMonitor,
)

__signature__ = "OD // CORE"
__all__ = [
    # Audit System (7.1)
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
    # Metrics Collector (7.2)
    "MetricsCollector",
    "Metric",
    "MetricSource",
    "TYPE_COUNTER",
    "TYPE_GAUGE",
    # Health Check (7.3)
    "HealthMonitor",
    "HealthCheckFn",
    "ComponentHealth",
    "HealthMetrics",
    "STATUS_UP",
    "STATUS_DEGRADED",
    "STATUS_DOWN",
]