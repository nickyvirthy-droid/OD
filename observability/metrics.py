"""
OMEGA DRAKON • OBSERVABILITY
Tecnologia que respira.
Módulo: observability/metrics.py
Descrição: Metrics Collector (Fase 7, item 7.2) — registro central de
           métricas operacionais com exposição no formato de texto
           Prometheus (stdlib puro): contadores e gauges com labels,
           HELP/TYPE, fontes vivas (sources) para snapshots externos
           (orchestrator, audit, uptime), render()/text(), snapshot(),
           dump() e health().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky /metrics (Prometheus metrics — NICKY_LEGACY_ANALYSIS §9)
  - NV Runtime observability/metrics/ (métricas operacionais)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.2

Decisões registradas (ver CHANGELOG):
  - Coletor central em stdlib puro: Counter/Gauge tipados com labels e
    exposição no Prometheus text exposition format (não há client
    prometheus_client no ambiente — mesma linha das demais integrações)
  - 'sources' (fontes vivas) contribuem linhas no render: componentes
    existentes (orchestrator, audit, uptime) expõem seus snapshots SEM
    precisar registrar métrica por métrica no coletor — integração aditiva
  - Registro idempotente por nome (mesmo tipo devolve a métrica existente;
    tipo diferente levanta ValueError) — evita duplicação em reinícios
  - A API REST passa a renderizar o coletor quando recebe config.metrics;
    sem coletor, mantém o comportamento legado (retrocompatível)
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.observability.metrics")

TYPE_COUNTER = "counter"
TYPE_GAUGE = "gauge"

_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Contrato de fonte viva: recebe nada, devolve linhas completas do formato
# Prometheus (ex: ["# TYPE od_uptime_seconds gauge", "od_uptime_seconds 42"])
MetricSource = Callable[[], list[str]]


def _escape_label_value(value: Any) -> str:
    text = str(value)
    return (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    )


def _format_value(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Metric:
    """Uma métrica registrada no coletor (counter ou gauge).

    Attributes:
        name:   Nome Prometheus (ex: "od_processed_total").
        type:   TYPE_COUNTER ou TYPE_GAUGE.
        help:   Texto de ajuda (emitido como # HELP).
        labels: Nomes dos labels (tupla). Vazio = métrica simples.
    """

    name: str
    type: str
    help: str = ""
    labels: tuple[str, ...] = ()

    # label-values (tupla) -> valor; () para métrica sem labels
    _values: dict[tuple[str, ...], float] = field(
        default_factory=dict, repr=False
    )

    def _check_labels(self, labels: dict[str, Any]) -> tuple[str, ...]:
        given = set(labels)
        declared = set(self.labels)
        if given != declared:
            missing = declared - given
            extra = given - declared
            raise ValueError(
                f"labels de {self.name}: faltando {sorted(missing)}, "
                f"extras {sorted(extra)} (declarados: {list(self.labels)})"
            )
        return tuple(str(labels[name]) for name in self.labels)

    def inc(self, amount: float = 1.0, **labels: Any) -> None:
        """Incrementa (counter e gauge)."""
        key = self._check_labels(labels)
        self._values[key] = self._values.get(key, 0.0) + float(amount)

    def dec(self, amount: float = 1.0, **labels: Any) -> None:
        """Decrementa (apenas gauge)."""
        if self.type != TYPE_GAUGE:
            raise ValueError(f"dec() só é válido para gauge: {self.name}")
        key = self._check_labels(labels)
        self._values[key] = self._values.get(key, 0.0) - float(amount)

    def set(self, value: float, **labels: Any) -> None:
        """Define o valor (apenas gauge)."""
        if self.type != TYPE_GAUGE:
            raise ValueError(f"set() só é válido para gauge: {self.name}")
        key = self._check_labels(labels)
        self._values[key] = float(value)

    def value(self, **labels: Any) -> float:
        """Valor atual (0.0 se nunca observado)."""
        key = self._check_labels(labels)
        return self._values.get(key, 0.0)

    def snapshot(self) -> Any:
        """Valores serializáveis: float simples ou dict por combinação."""
        if not self.labels:
            return self.value()
        return {
            ", ".join(f"{k}={v}" for k, v in zip(self.labels, key)): value
            for key, value in self._values.items()
        }

    def sample_lines(self) -> list[str]:
        """Linhas de amostra do Prometheus text format."""
        lines: list[str] = []
        for key, value in self._values.items():
            if self.labels:
                pairs = ", ".join(
                    f'{label}="{_escape_label_value(v)}"'
                    for label, v in zip(self.labels, key)
                )
                lines.append(f"{self.name}{{{pairs}}} {_format_value(value)}")
            else:
                lines.append(f"{self.name} {_format_value(value)}")
        return lines


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Registro central de métricas com exposição Prometheus (Fase 7.2).

    Uso típico:
        collector = MetricsCollector()
        collector.counter("od_processed_total", "Mensagens processadas.")
        collector.counter("od_processed_total").inc()  # idempotente

        collector.add_source(lambda: ["od_uptime_seconds 42"])
        print(collector.render())  # texto Prometheus completo
    """

    def __init__(self) -> None:
        self._metrics: list[Metric] = []
        self._by_name: dict[str, Metric] = {}
        self._sources: list[MetricSource] = []
        self._errors = 0
        self._lock = threading.RLock()

    # -- Registro -------------------------------------------------------------

    def counter(
        self, name: str, help: str = "", labels: tuple[str, ...] = ()
    ) -> Metric:
        return self._register(name, TYPE_COUNTER, help, labels)

    def gauge(
        self, name: str, help: str = "", labels: tuple[str, ...] = ()
    ) -> Metric:
        return self._register(name, TYPE_GAUGE, help, labels)

    def _register(
        self, name: str, type: str, help: str, labels: tuple[str, ...]
    ) -> Metric:
        if not _NAME_RE.match(name):
            raise ValueError(f"nome de métrica inválido: {name!r}")
        for label in labels:
            if not _LABEL_RE.match(label):
                raise ValueError(f"nome de label inválido: {label!r}")
        with self._lock:
            existing = self._by_name.get(name)
            if existing is not None:
                if existing.type != type:
                    raise ValueError(
                        f"{name} já registrada como {existing.type}, "
                        f"não como {type}"
                    )
                return existing
            metric = Metric(
                name=name, type=type, help=help, labels=tuple(labels)
            )
            self._metrics.append(metric)
            self._by_name[name] = metric
            return metric

    def get(self, name: str) -> Optional[Metric]:
        with self._lock:
            return self._by_name.get(name)

    def add_source(self, source: MetricSource) -> None:
        """Fonte viva: contribui linhas completas no render()."""
        with self._lock:
            if source not in self._sources:
                self._sources.append(source)

    # -- Exposição ------------------------------------------------------------

    def render(self) -> str:
        """Texto completo no Prometheus text exposition format."""
        with self._lock:
            lines: list[str] = []
            for metric in self._metrics:
                if metric.help:
                    lines.append(f"# HELP {metric.name} {metric.help}")
                lines.append(f"# TYPE {metric.name} {metric.type}")
                lines.extend(metric.sample_lines())
            sources = list(self._sources)
            source_lines: list[str] = []
            for fn in sources:
                try:
                    out = fn()
                    if out:
                        source_lines.extend(list(out))
                except Exception as exc:  # fonte nunca quebra o render
                    self._errors += 1
                    log.warn(
                        "Fonte de métricas falhou",
                        error=type(exc).__name__,
                        source=getattr(fn, "__name__", repr(fn)),
                    )
        if source_lines:
            if lines:
                lines.append("")
            lines.extend(source_lines)
        return "\n".join(lines) + "\n"

    def text(self) -> str:
        return self.render()

    # -- Introspecção ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Nome -> valor(es) serializáveis (sem HELP/TYPE)."""
        with self._lock:
            return {
                metric.name: metric.snapshot() for metric in self._metrics
            }

    @property
    def metrics(self) -> list[Metric]:
        with self._lock:
            return list(self._metrics)

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "status": "ok",
                "metrics": len(self._metrics),
                "sources": len(self._sources),
                "errors": self._errors,
            }

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {
                "metrics": len(self._metrics),
                "sources": len(self._sources),
                "errors": self._errors,
                "values": self.snapshot(),
            }