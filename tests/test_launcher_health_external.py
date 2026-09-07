"""
OMEGA DRAKON • TESTS
Módulo: tests/test_launcher_health_external.py
Descrição: Testes dos checks EXTERNOS de HA e MQTT registrados no Health
           Monitor pelo launcher (runtime/launcher.py) — v1.0.0, item 1.4.
           Cobre: placeholders "não configurado (ok)" presentes no
           build_health; registro/substituição pelos checks reais via
           register_external_health_checks(); delegação ao health() do
           PresenceMonitor (HA) e da MQTTBridge (Mosquitto); e o estado
           não-crítico (degraded, nunca down).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - ROADMAP_V1.md item 1.4 (health checks externos) e item 1.5
  - observability/health.py (HealthMonitor, critical=False)
  - integrations/homeassistant/presence.py · integrations/mqtt/bridge.py
"""

from __future__ import annotations

import pytest

from observability.health import (
    STATUS_DEGRADED,
    STATUS_UP,
    HealthMonitor,
)
from runtime.launcher import (
    _homeassistant_check,
    _mqtt_check,
    build_health,
    register_external_health_checks,
)


class _FakeHealth:
    """Componente fake com health() controlável (contrato do launcher)."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def health(self) -> dict:
        return dict(self._payload)


# ---------------------------------------------------------------------------
# Placeholders no build_health — sempre presentes, não-críticos
# ---------------------------------------------------------------------------

class TestBuildHealthPlaceholders:
    """/health expõe homeassistant e mqtt mesmo antes dos componentes reais."""

    def test_placeholders_registrados(self) -> None:
        monitor = build_health()
        componentes = set(monitor.components)
        assert {"orchestrator", "llm", "audit", "metrics", "database",
                "homeassistant", "mqtt"} <= componentes

    @pytest.mark.asyncio
    async def test_placeholder_sem_componente_e_ok(self) -> None:
        monitor = build_health()
        result = await monitor.health()
        assert result["checks"]["homeassistant"]["ok"] is True
        assert result["checks"]["homeassistant"]["critical"] is False
        assert result["checks"]["mqtt"]["ok"] is True
        assert result["checks"]["mqtt"]["critical"] is False


# ---------------------------------------------------------------------------
# register_external_health_checks — substitui placeholders por checks reais
# ---------------------------------------------------------------------------

class TestRegisterExternal:
    """Checks reais entram quando os componentes existem no runtime."""

    @pytest.mark.asyncio
    async def test_ha_ok_quando_presence_saudavel(self) -> None:
        monitor = HealthMonitor()
        register_external_health_checks(
            monitor,
            homeassistant=_FakeHealth(
                {"ok": True, "connected": True, "reachable": True,
                 "detail": "HA alcançável"}
            ),
        )
        result = await monitor.health()
        check = result["checks"]["homeassistant"]
        assert check["ok"] is True
        assert check["status"] == STATUS_UP
        assert check["critical"] is False

    @pytest.mark.asyncio
    async def test_ha_degradado_quando_inacessivel(self) -> None:
        monitor = HealthMonitor()
        register_external_health_checks(
            monitor,
            homeassistant=_FakeHealth(
                {"ok": False, "connected": False, "reachable": False,
                 "detail": "HA inacessível no último poll"}
            ),
        )
        result = await monitor.health()
        check = result["checks"]["homeassistant"]
        assert check["ok"] is False
        assert check["status"] == STATUS_DEGRADED  # nunca down (não-crítico)

    @pytest.mark.asyncio
    async def test_mqtt_ok_quando_conectado(self) -> None:
        monitor = HealthMonitor()
        register_external_health_checks(
            monitor,
            mqtt=_FakeHealth(
                {"ok": True, "connected": True, "host": "127.0.0.1:1883"}
            ),
        )
        result = await monitor.health()
        check = result["checks"]["mqtt"]
        assert check["ok"] is True
        assert check["status"] == STATUS_UP
        assert "broker" in check["detail"]

    @pytest.mark.asyncio
    async def test_mqtt_degradado_quando_desconectado(self) -> None:
        monitor = HealthMonitor()
        register_external_health_checks(
            monitor,
            mqtt=_FakeHealth(
                {"ok": False, "connected": False, "host": "127.0.0.1:1883"}
            ),
        )
        result = await monitor.health()
        check = result["checks"]["mqtt"]
        assert check["ok"] is False
        assert check["status"] == STATUS_DEGRADED

    @pytest.mark.asyncio
    async def test_none_mantem_placeholder(self) -> None:
        monitor = HealthMonitor()
        register_external_health_checks(monitor, homeassistant=None, mqtt=None)
        assert "homeassistant" not in monitor.components
        assert "mqtt" not in monitor.components

    def test_health_none_e_seguro(self) -> None:
        register_external_health_checks(None, homeassistant=object())
        register_external_health_checks(None, mqtt=object())

    @pytest.mark.asyncio
    async def test_substituicao_no_build_health(self) -> None:
        # Simula o launcher: build_health com placeholders + registro real
        monitor = build_health()
        register_external_health_checks(
            monitor,
            homeassistant=_FakeHealth(
                {"ok": True, "connected": True, "reachable": True,
                 "detail": "HA alcançável"}
            ),
            mqtt=_FakeHealth(
                {"ok": True, "connected": True, "host": "127.0.0.1:1883"}
            ),
        )
        result = await monitor.health()
        assert "homeassistant" in result["checks"]
        assert "mqtt" in result["checks"]
        assert result["checks"]["homeassistant"]["ok"] is True
        assert result["checks"]["mqtt"]["ok"] is True


# ---------------------------------------------------------------------------
# Delegados diretos — contrato do check com o componente real
# ---------------------------------------------------------------------------

class TestCheckDelegates:
    """As closures _homeassistant_check/_mqtt_check traduzem health()."""

    def test_homeassistant_check_delega(self) -> None:
        fake = _FakeHealth({"ok": False, "detail": "HA fora"})
        resultado = _homeassistant_check(fake)(None)
        assert resultado["ok"] is False
        assert resultado["detail"] == "HA fora"

    def test_mqtt_check_delega(self) -> None:
        fake = _FakeHealth({"ok": True, "host": "localhost:1883"})
        resultado = _mqtt_check(fake)(None)
        assert resultado["ok"] is True
        assert "localhost" in resultado["detail"]
