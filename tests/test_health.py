"""
OMEGA DRAKON • TESTS
Módulo: tests/test_health.py
Descrição: Testes do Health Check (observability/health.py) — Fase 7, item
           7.3: ComponentHealth (status/dict), HealthMonitor (registro,
           check individual, agregação up/degraded/down com critical,
           checks async, check quebrado resiliente, check desconhecido,
           métricas de latência, snapshot/dump, unregister) e integração
           com a API REST (GET /health responde o agregado quando
           config.health presente; legado preservado sem monitor).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime observability/health/ (health checks)
  - Nicky /health (health check + LLMs — NICKY_LEGACY_ANALYSIS §9)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.3
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from integrations.api import APIConfig, APIServer
from observability.health import (
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_UP,
    ComponentHealth,
    HealthMonitor,
)


def _request(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


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
# ComponentHealth
# ---------------------------------------------------------------------------

class TestComponentHealth:
    """Resultado tipado de um check."""

    def test_defaults(self):
        result = ComponentHealth(name="audit", ok=True)
        assert result.status == STATUS_UP
        assert result.critical is True
        assert result.latency_ms == 0.0

    def test_to_dict(self):
        result = ComponentHealth(
            name="llm", ok=False, status=STATUS_DOWN,
            detail="sem provider", latency_ms=12.5,
        )
        data = result.to_dict()
        assert data["name"] == "llm"
        assert data["status"] == STATUS_DOWN
        assert data["latency_ms"] == 12.5


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------

class TestHealthMonitor:
    """Checks registráveis, agregação e métricas."""

    def _monitor(self):
        return HealthMonitor()

    def test_register_returns_component_list(self):
        monitor = self._monitor()

        def ok_check(mon):
            return {"ok": True, "status": "up", "detail": "tudo certo"}

        monitor.register("audit", ok_check, critical=False)
        assert monitor.components == ["audit"]

    @pytest.mark.asyncio
    async def test_check_individual_async(self):
        monitor = self._monitor()

        def ok_check(mon):
            return {"ok": True, "detail": "ok"}

        monitor.register("audit", ok_check)
        result = await monitor.check("audit")
        assert result.ok is True
        assert result.name == "audit"

    @pytest.mark.asyncio
    async def test_check_unknown_returns_none(self):
        monitor = self._monitor()
        assert await monitor.check("nao_existe") is None

    @pytest.mark.asyncio
    async def test_all_ok_is_up(self):
        monitor = self._monitor()

        def ok_check(mon):
            return {"ok": True}

        monitor.register("a", ok_check)
        monitor.register("b", ok_check, critical=False)
        result = await monitor.health()
        assert result["ok"] is True
        assert result["status"] == STATUS_UP
        assert set(result["checks"]) == {"a", "b"}
        assert monitor.metrics.runs == 1
        assert monitor.metrics.checks_run == 2
        assert monitor.metrics.ok_checks == 2

    @pytest.mark.asyncio
    async def test_critical_failure_is_down(self):
        monitor = self._monitor()

        def ok_check(mon):
            return {"ok": True}

        def fail_check(mon):
            return {"ok": False, "status": "down", "detail": "caiu"}

        monitor.register("a", ok_check)
        monitor.register("llm", fail_check, critical=True)
        result = await monitor.health()
        assert result["ok"] is False
        assert result["status"] == STATUS_DOWN
        assert result["checks"]["llm"]["detail"] == "caiu"
        assert monitor.metrics.failed_checks == 1

    @pytest.mark.asyncio
    async def test_non_critical_failure_is_degraded(self):
        monitor = self._monitor()

        def ok_check(mon):
            return {"ok": True}

        def warn_check(mon):
            return {"ok": False, "status": "degraded", "detail": "trilha lenta"}

        monitor.register("a", ok_check)
        monitor.register("audit", warn_check, critical=False)
        result = await monitor.health()
        assert result["ok"] is False
        assert result["status"] == STATUS_DEGRADED

    @pytest.mark.asyncio
    async def test_component_health_returned_directly(self):
        monitor = self._monitor()

        def check(mon):
            return ComponentHealth(name="x", ok=False, status=STATUS_DOWN)

        monitor.register("x", check)
        result = await monitor.health()
        assert result["status"] == STATUS_DOWN

    @pytest.mark.asyncio
    async def test_async_check(self):
        monitor = self._monitor()

        async def slow_check(mon):
            return {"ok": True, "detail": "async ok"}

        monitor.register("async_comp", slow_check)
        result = await monitor.health()
        assert result["ok"] is True
        assert result["checks"]["async_comp"]["ok"] is True

    @pytest.mark.asyncio
    async def test_broken_check_never_breaks_monitor(self):
        monitor = self._monitor()

        def broken(mon):
            raise RuntimeError("check quebrou")

        monitor.register("quebrado", broken)
        result = await monitor.health()
        assert result["ok"] is False
        assert result["status"] == STATUS_DOWN
        assert "check quebrado" in result["checks"]["quebrado"]["detail"]
        assert monitor.metrics.errors == 1

    @pytest.mark.asyncio
    async def test_latency_recorded(self):
        monitor = self._monitor()

        def check(mon):
            return {"ok": True}

        monitor.register("a", check)
        await monitor.health()
        metrics = monitor.metrics.snapshot()
        assert metrics["checks_run"] == 1
        assert metrics["avg_latency_ms"] >= 0.0
        assert monitor.metrics.total_latency_ms >= 0.0

    @pytest.mark.asyncio
    async def test_unregister(self):
        monitor = self._monitor()
        monitor.register("a", lambda mon: {"ok": True})
        assert monitor.unregister("a") is True
        assert monitor.unregister("a") is False
        assert monitor.components == []

    @pytest.mark.asyncio
    async def test_snapshot_and_dump(self):
        monitor = self._monitor()

        def ok_check(mon):
            return {"ok": True}

        monitor.register("a", ok_check)
        await monitor.health()
        snap = monitor.snapshot()
        assert snap["components"] == 1
        assert snap["last_status"] == STATUS_UP
        assert snap["metrics"]["runs"] == 1
        dump = monitor.dump()
        assert dump["last"]["status"] == STATUS_UP


# ---------------------------------------------------------------------------
# Integração com a API REST (GET /health)
# ---------------------------------------------------------------------------

class TestAPIHealthIntegration:
    """Fase 7.3: /health responde o agregado quando config.health existe."""

    def test_health_endpoint_returns_aggregate(self, serve):
        monitor = HealthMonitor()
        monitor.register(
            "audit", lambda mon: {"ok": True, "detail": "trilha ok"},
            critical=False,
        )
        srv = serve(config=APIConfig(port=0, rate_limit_max=0, health=monitor))
        status, body = _request(srv.bound_port, "/health")
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == STATUS_UP
        assert "audit" in body["checks"]
        assert body["uptime_s"] >= 0

    def test_health_endpoint_reports_down(self, serve):
        monitor = HealthMonitor()

        def fail(mon):
            return {"ok": False, "status": "down", "detail": "LLM offline"}

        monitor.register("llm", fail, critical=True)
        srv = serve(config=APIConfig(port=0, rate_limit_max=0, health=monitor))
        status, body = _request(srv.bound_port, "/health")
        assert status == 200
        assert body["ok"] is False
        assert body["status"] == STATUS_DOWN
        assert body["checks"]["llm"]["detail"] == "LLM offline"

    def test_without_monitor_keeps_legacy_behavior(self, serve):
        # Retrocompatibilidade: sem config.health, /health segue inline
        srv = serve(config=APIConfig(port=0, rate_limit_max=0))
        status, body = _request(srv.bound_port, "/health")
        assert status == 200
        assert "orchestrator" in body
        assert "llms" in body
        assert body["uptime_s"] >= 0