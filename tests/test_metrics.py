"""
OMEGA DRAKON • TESTS
Módulo: tests/test_metrics.py
Descrição: Testes do Metrics Collector (observability/metrics.py) — Fase 7,
           item 7.2: Metric (counter/gauge, labels, valores, amostras),
           MetricsCollector (registro idempotente, conflito de tipo, nomes
           inválidos, render no Prometheus text format com HELP/TYPE/samples
           e fontes vivas, resiliência de fonte quebrada, snapshot/health/
           dump) e integração com a API REST (GET /metrics renderiza o
           coletor com od_api_* quando config.metrics presente).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky /metrics (Prometheus metrics — NICKY_LEGACY_ANALYSIS §9)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.2
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from integrations.api import APIConfig, APIServer
from observability.metrics import (
    TYPE_COUNTER,
    TYPE_GAUGE,
    Metric,
    MetricsCollector,
)


def _request(port, path, method="GET", body=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture()
def serve():
    """Sobe APIServers sob demanda e derruba todos no fim do teste."""
    servers: list[APIServer] = []

    def _start(orch=None, *, config=None):
        cfg = config or APIConfig(port=0, rate_limit_max=0)
        srv = APIServer(orch, config=cfg)
        srv.serve_background()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        try:
            srv.stop()
        except Exception:  # pragma: no cover — teardown defensivo
            pass


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------

class TestMetric:
    """Counter/Gauge: valores, labels e amostras."""

    def test_counter_inc_and_value(self):
        metric = Metric(name="od_test_total", type=TYPE_COUNTER)
        assert metric.value() == 0.0
        metric.inc()
        metric.inc(2)
        assert metric.value() == 3.0

    def test_counter_cannot_dec(self):
        metric = Metric(name="od_test_total", type=TYPE_COUNTER)
        with pytest.raises(ValueError):
            metric.dec()

    def test_gauge_set_inc_dec(self):
        metric = Metric(name="od_temp", type=TYPE_GAUGE)
        metric.set(10)
        assert metric.value() == 10.0
        metric.inc(5)
        assert metric.value() == 15.0
        metric.dec(3)
        assert metric.value() == 12.0

    def test_gauge_cannot_be_set_by_counter(self):
        metric = Metric(name="od_test_total", type=TYPE_COUNTER)
        with pytest.raises(ValueError):
            metric.set(5)

    def test_labels_validation(self):
        metric = Metric(name="od_by_profile", type=TYPE_COUNTER, labels=("profile",))
        metric.inc(profile="guardian")
        with pytest.raises(ValueError):
            metric.inc()  # label faltando
        with pytest.raises(ValueError):
            metric.inc(profile="x", extra="y")  # label extra

    def test_labeled_values_isolated_per_combination(self):
        metric = Metric(name="od_by_profile", type=TYPE_COUNTER, labels=("profile",))
        metric.inc(profile="guardian")
        metric.inc(profile="nyx")
        metric.inc(profile="guardian")
        assert metric.value(profile="guardian") == 2.0
        assert metric.value(profile="nyx") == 1.0
        assert metric.value(profile="regulus") == 0.0

    def test_snapshot_simple_and_labeled(self):
        simple = Metric(name="od_simple", type=TYPE_GAUGE)
        simple.set(7)
        assert simple.snapshot() == 7.0
        labeled = Metric(name="od_by_profile", type=TYPE_COUNTER, labels=("profile",))
        labeled.inc(profile="guardian")
        assert labeled.snapshot() == {"profile=guardian": 1.0}

    def test_sample_lines_escaping(self):
        metric = Metric(name="od_by_label", type=TYPE_COUNTER, labels=("k",))
        metric.inc(k='va"lor\\x')
        lines = metric.sample_lines()
        assert lines == ['od_by_label{k="va\\"lor\\\\x"} 1']


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------

class TestMetricsCollector:
    """Registro, render Prometheus, fontes vivas e introspecção."""

    def test_counter_and_gauge_registration(self):
        collector = MetricsCollector()
        c = collector.counter("od_a_total", "A.")
        g = collector.gauge("od_b", "B.")
        assert c.type == TYPE_COUNTER
        assert g.type == TYPE_GAUGE
        assert collector.get("od_a_total") is c
        assert collector.health()["metrics"] == 2

    def test_registration_idempotent_same_type(self):
        collector = MetricsCollector()
        first = collector.counter("od_x_total", "help 1")
        second = collector.counter("od_x_total", "help 2")
        assert first is second
        assert collector.health()["metrics"] == 1

    def test_type_conflict_raises(self):
        collector = MetricsCollector()
        collector.counter("od_x_total")
        with pytest.raises(ValueError):
            collector.gauge("od_x_total")

    def test_invalid_names_rejected(self):
        collector = MetricsCollector()
        with pytest.raises(ValueError):
            collector.counter("nome com espaço")
        with pytest.raises(ValueError):
            collector.counter("1começa_com_numero")
        with pytest.raises(ValueError):
            collector.counter("od_x_total", labels=("label inválido",))

    def test_render_prometheus_text(self):
        collector = MetricsCollector()
        c = collector.counter("od_processed_total", "Mensagens processadas.")
        c.inc(3)
        g = collector.gauge("od_temp", "Temperatura.")
        g.set(21.5)
        text = collector.render()
        lines = text.strip().splitlines()
        assert "# HELP od_processed_total Mensagens processadas." in lines
        assert "# TYPE od_processed_total counter" in lines
        assert "od_processed_total 3" in lines
        assert "# TYPE od_temp gauge" in lines
        assert "od_temp 21.5" in lines

    def test_render_escapes_help(self):
        collector = MetricsCollector()
        collector.counter("od_a_total", 'Help com "aspas".')
        assert '# HELP od_a_total Help com "aspas".' in collector.render()

    def test_sources_contribute_lines(self):
        collector = MetricsCollector()
        collector.add_source(lambda: ["od_uptime_seconds 42"])
        text = collector.render()
        assert "od_uptime_seconds 42" in text
        assert collector.health()["sources"] == 1

    def test_broken_source_never_breaks_render(self):
        collector = MetricsCollector()
        collector.counter("od_ok_total").inc()

        def broken():
            raise RuntimeError("fonte quebrou")

        collector.add_source(broken)
        text = collector.render()
        assert "od_ok_total 1" in text  # resto intacto
        assert collector.health()["errors"] == 1

    def test_snapshot_and_dump(self):
        collector = MetricsCollector()
        collector.counter("od_a_total").inc(2)
        collector.gauge("od_b").set(1)
        snap = collector.snapshot()
        assert snap == {"od_a_total": 2.0, "od_b": 1.0}
        dump = collector.dump()
        assert dump["metrics"] == 2
        assert dump["values"]["od_a_total"] == 2.0

    def test_labeled_metric_in_render(self):
        collector = MetricsCollector()
        m = collector.counter(
            "od_by_profile_total", "Por perfil.", labels=("profile",)
        )
        m.inc(profile="guardian")
        m.inc(profile="nyx")
        text = collector.render()
        assert 'od_by_profile_total{profile="guardian"} 1' in text
        assert 'od_by_profile_total{profile="nyx"} 1' in text

    def test_health(self):
        collector = MetricsCollector()
        assert collector.health()["ok"] is True
        assert collector.health()["errors"] == 0


# ---------------------------------------------------------------------------
# Integração com a API REST (GET /metrics)
# ---------------------------------------------------------------------------

class TestAPIMetricsIntegration:
    """Fase 7.2: /metrics renderiza o coletor quando config.metrics existe."""

    def test_metrics_endpoint_renders_collector(self, serve):
        collector = MetricsCollector()
        collector.counter("od_custom_total").inc(5)
        srv = serve(config=APIConfig(port=0, rate_limit_max=0, metrics=collector))
        status, body = _request(srv.bound_port, "/metrics")
        assert status == 200
        text = body.decode("utf-8")
        assert "od_custom_total 5" in text
        # O contador da API foi registrado no coletor
        assert "# TYPE od_api_requests_total counter" in text

    def test_metrics_counts_api_requests(self, serve):
        collector = MetricsCollector()
        srv = serve(config=APIConfig(port=0, rate_limit_max=0, metrics=collector))
        _request(srv.bound_port, "/health")
        _request(srv.bound_port, "/")
        status, body = _request(srv.bound_port, "/metrics")
        assert status == 200
        text = body.decode("utf-8")
        # 3 requisições: /health, / e /metrics
        assert "od_api_requests_total 3" in text

    def test_metrics_counts_api_errors(self, serve):
        collector = MetricsCollector()
        srv = serve(config=APIConfig(port=0, rate_limit_max=0, metrics=collector))
        # POST /message sem user_id -> APIError(400) -> count_error()
        _request(srv.bound_port, "/message", method="POST", body={})
        status, body = _request(srv.bound_port, "/metrics")
        assert status == 200
        text = body.decode("utf-8")
        assert "od_api_errors_total 1" in text

    def test_without_collector_keeps_legacy_behavior(self, serve):
        # Retrocompatibilidade: sem config.metrics, /metrics segue inline
        srv = serve(config=APIConfig(port=0, rate_limit_max=0))
        status, body = _request(srv.bound_port, "/metrics")
        assert status == 200
        text = body.decode("utf-8")
        assert "od_uptime_seconds" in text
        assert "# TYPE od_api_requests_total counter" in text

    def test_shared_collector_merges_external_metric(self, serve):
        collector = MetricsCollector()
        collector.add_source(lambda: ["od_external_gauge 9"])
        srv = serve(config=APIConfig(port=0, rate_limit_max=0, metrics=collector))
        status, body = _request(srv.bound_port, "/metrics")
        assert status == 200
        assert "od_external_gauge 9" in body.decode("utf-8")