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
from core.supervision import get_supervision
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
# Check "loops" — supervisão dos loops do núcleo (2026-09-15)
# ---------------------------------------------------------------------------

class TestLoopsCheck:
    """/health expõe o estado da supervisão dos loops — sempre não-crítico."""

    def test_check_registrado(self) -> None:
        assert "loops" in build_health().components

    @pytest.mark.asyncio
    async def test_sem_quedas_e_ok(self) -> None:
        get_supervision().reset()
        monitor = build_health()
        result = await monitor.health()
        assert result["checks"]["loops"]["ok"] is True
        assert result["checks"]["loops"]["critical"] is False

    @pytest.mark.asyncio
    async def test_queda_degrada_mas_nao_derruba(self) -> None:
        """Loop reiniciado pela supervisão degrada o /health, não o derruba."""
        registro = get_supervision()
        registro.reset()
        registro.record_drop(
            "telegram", kind="TimeoutError", detail="The read operation timed out"
        )
        try:
            monitor = build_health()
            result = await monitor.health()
            check = result["checks"]["loops"]
            assert check["ok"] is False
            assert check["status"] == STATUS_DEGRADED
            assert check["critical"] is False  # degrada; não vira "down"
            assert "telegram" in check["detail"]
            assert "TimeoutError" in check["detail"]
        finally:
            registro.reset()


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


# ---------------------------------------------------------------------------
# Observabilidade / Alertas Telegram — TODO §3.6 (2026-10-16)
# ---------------------------------------------------------------------------

class TestBuildNotifierObservabilidade:
    """Ligações do notifier no build: ponte do /health, NRestarts, disco.

    Três alertas que o item 3.6 pedia e que agora existem:
    `/health` degraded → Telegram, NRestarts > 0 → Telegram e disco
    > 85% (limiar configurável por `OD_DISK_THRESHOLD_PERCENT`).
    """

    @pytest.fixture(autouse=True)
    def _data_dir_e_env_isolados(self, tmp_path, monkeypatch) -> None:
        """Estado isolado: build_notifier grava notifier_state.json.

        `launcher.env()` lê `_ENV_CACHE` (snapshot do ambiente) — só
        monkeypatch.setenv não basta; é o padrão do test_websocket e do
        test_voice_api. O cache é copiado com as chaves novas removidas
        para os testes começarem nos defaults da casa.
        """
        from runtime import launcher as launcher_module

        monkeypatch.setattr(launcher_module, "DATA_DIR", tmp_path)
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        cache = dict(launcher_module._ENV_CACHE or {})
        for chave in ("OD_SERVICE_UNIT", "OD_NOTIFIER_ENABLED",
                      "OD_NOTIFIER_HEALTH", "OD_NOTIFIER_NRESTARTS",
                      "OD_DISK_THRESHOLD_PERCENT"):
            cache.pop(chave, None)
        monkeypatch.setattr(launcher_module, "_ENV_CACHE", cache)

    def test_ponte_de_saude_ligada_por_padrao(self) -> None:
        from runtime.launcher import build_notifier

        monitor = build_health()
        notifier = build_notifier(None, health=monitor)
        assert notifier is not None
        assert notifier.health_monitor is monitor
        assert "_check_health" in notifier.snapshot()["checks"]
        # fora do systemd (sem INVOCATION_ID) a sonda NRestarts fica fora
        assert notifier.nrestarts_fn is None
        assert "_check_nrestarts" not in notifier.snapshot()["checks"]
        assert notifier.config.disk_threshold_percent == 85.0

    def test_ponte_de_saude_desligavel(self) -> None:
        from runtime import launcher
        from runtime.launcher import build_notifier

        launcher._ENV_CACHE["OD_NOTIFIER_HEALTH"] = "0"
        notifier = build_notifier(None, health=build_health())
        assert notifier.health_monitor is None
        assert "_check_health" not in notifier.snapshot()["checks"]

    def test_nrestarts_liga_com_service_unit(self) -> None:
        from runtime import launcher
        from runtime.launcher import build_notifier

        launcher._ENV_CACHE["OD_SERVICE_UNIT"] = "od-core.service"
        notifier = build_notifier(None)
        assert notifier.nrestarts_fn is not None
        assert notifier.unidade == "od-core.service"
        assert "_check_nrestarts" in notifier.snapshot()["checks"]

    def test_nrestarts_liga_com_invocation_id(self, monkeypatch) -> None:
        from runtime.launcher import build_notifier

        monkeypatch.setenv("INVOCATION_ID", "abc-123")
        notifier = build_notifier(None)
        assert notifier.nrestarts_fn is not None
        assert notifier.unidade == "od-core.service"

    def test_nrestarts_desligavel(self, monkeypatch) -> None:
        from runtime import launcher
        from runtime.launcher import build_notifier

        monkeypatch.setenv("INVOCATION_ID", "abc-123")
        launcher._ENV_CACHE["OD_NOTIFIER_NRESTARTS"] = "0"
        notifier = build_notifier(None)
        assert notifier.nrestarts_fn is None
        assert "_check_nrestarts" not in notifier.snapshot()["checks"]

    def test_limiar_de_disco_configuravel(self) -> None:
        from runtime import launcher
        from runtime.launcher import build_notifier

        launcher._ENV_CACHE["OD_DISK_THRESHOLD_PERCENT"] = "92.5"
        notifier = build_notifier(None)
        assert notifier.config.disk_threshold_percent == 92.5

    def test_notifier_inteiro_desligado(self) -> None:
        from runtime import launcher
        from runtime.launcher import build_notifier

        launcher._ENV_CACHE["OD_NOTIFIER_ENABLED"] = "0"
        assert build_notifier(None, health=build_health()) is None
