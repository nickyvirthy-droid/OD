"""
OMEGA DRAKON • TESTS
Módulo: tests/test_homeassistant.py
Descrição: Testes do IoT Manager (integrations/homeassistant/) — Fase 5,
           item 5.4: taxonomia de entidades (atuadores/móveis/sensores/
           infra), EntityState/HACredentials, HAClient REST com rede
           stubada (Bearer token, erros), InMemoryHAServer fake, e o
           IoTManager (leitura, controle liga/desliga/toggle, gate de
           segurança com guard + domínios permitidos, Event Bus, métricas
           e introspecção).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/iot.py (mapeamento ambiental, leitura, controle)
  - Home Assistant REST API
  - ROADMAP_ABSORCAO.md Fase 5, item 5.4
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from core.event_bus import EventBus
from integrations.homeassistant import (
    ACTION_OFF,
    ACTION_ON,
    ACTION_TOGGLE,
    HAClient,
    HACredentials,
    HAError,
    EntityState,
    EntityType,
    InMemoryHAServer,
    IoTManager,
    IoTManagerConfig,
    classify_entity,
)


def fake_urlopen(monkeypatch, *, status: int = 200, body: bytes = b"[]",
                 raise_error=None):
    """Stub de urllib.request.urlopen com resposta fixa."""

    def fake(*args, **kwargs):
        if raise_error is not None:
            raise raise_error

        class FakeResponse:
            def __init__(self) -> None:
                self.status = status

            def read(self) -> bytes:
                return body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake)


# ===========================================================================
# Taxonomia
# ===========================================================================

class TestTaxonomy:
    """Mapeamento de domínios do HA para as 4 categorias do legado."""

    def test_actuator_domains(self) -> None:
        for entity in ("light.sala", "switch.cozinha", "fan.quarto",
                       "cover.janela", "climate.ar", "lock.porta",
                       "media_player.tv", "vacuum.robo",
                       "input_boolean.modo"):
            assert classify_entity(entity) is EntityType.ACTUATOR, entity

    def test_sensor_domains(self) -> None:
        for entity in ("sensor.temperatura", "binary_sensor.janela",
                       "number.volume", "select.modo", "input_number.alvo"):
            assert classify_entity(entity) is EntityType.SENSOR, entity

    def test_mobile_domains(self) -> None:
        assert classify_entity("person.alex") is EntityType.MOBILE
        assert classify_entity("device_tracker.celular") is EntityType.MOBILE

    def test_infra_domains(self) -> None:
        for entity in ("camera.entrada", "automation.alarme",
                       "script.cena", "scene.noite", "weather.atual",
                       "group.sala"):
            assert classify_entity(entity) is EntityType.INFRA, entity

    def test_unknown_domain(self) -> None:
        assert classify_entity("foo.bar") is EntityType.UNKNOWN
        assert classify_entity("coisa_sem_ponto") is EntityType.UNKNOWN

    def test_manager_classify_delegates(self) -> None:
        manager = IoTManager(InMemoryHAServer())
        assert manager.classify("light.sala") is EntityType.ACTUATOR


# ===========================================================================
# EntityState
# ===========================================================================

class TestEntityState:
    """Propriedades derivadas e serialização."""

    def test_domain_and_type(self) -> None:
        entity = EntityState(entity_id="light.sala", state="on")
        assert entity.domain == "light"
        assert entity.entity_type is EntityType.ACTUATOR

    def test_is_on(self) -> None:
        for state in ("on", "open", "unlocked", "home", "playing"):
            assert EntityState(entity_id="x.y", state=state).is_on()
        for state in ("off", "closed", "locked", "not_home", "idle", "unknown"):
            assert not EntityState(entity_id="x.y", state=state).is_on()

    def test_to_dict_and_from_dict_round_trip(self) -> None:
        entity = EntityState(
            entity_id="sensor.temp",
            state="21.5",
            attributes={"unit_of_measurement": "°C"},
            last_changed="2026-01-01T00:00:00Z",
        )
        data = entity.to_dict()
        assert data["domain"] == "sensor"
        assert data["type"] == "sensor"
        assert data["attributes"]["unit_of_measurement"] == "°C"
        restored = EntityState.from_dict(data)
        assert restored.entity_id == "sensor.temp"
        assert restored.state == "21.5"
        assert restored.attributes == {"unit_of_measurement": "°C"}


# ===========================================================================
# Credenciais
# ===========================================================================

class TestHACredentials:
    """Validação, normalização e carregamento de arquivo."""

    def test_validate_and_normalize(self) -> None:
        creds = HACredentials("http://ha:8123/", "token")
        creds.validate()
        assert creds.normalized_url == "http://ha:8123"

    def test_missing_base_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            HACredentials("").validate()

    def test_non_http_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="http"):
            HACredentials("ftp://ha").validate()

    def test_from_dict(self) -> None:
        creds = HACredentials.from_dict(
            {"base_url": "https://ha.local:8123", "token": "abc"}
        )
        assert creds.normalized_url == "https://ha.local:8123"
        assert creds.token == "abc"

    def test_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "iot_credentials.json"
        path.write_text(
            json.dumps({"base_url": "http://ha:8123/", "token": "segredo"})
        )
        creds = HACredentials.from_file(path)
        assert creds.normalized_url == "http://ha:8123"
        assert creds.token == "segredo"

    def test_from_file_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "iot_credentials.json"
        path.write_text("não é json")
        with pytest.raises(Exception):
            HACredentials.from_file(path)


# ===========================================================================
# HAClient (REST com rede stubada)
# ===========================================================================

class TestHAClient:
    """Parse, headers, erros HTTP/rede e service_available."""

    def _client(self) -> HAClient:
        return HAClient(HACredentials("http://ha:8123", "tok123"))

    def test_get_state_parses(self, monkeypatch) -> None:
        fake_urlopen(
            monkeypatch,
            body=json.dumps(
                {"entity_id": "light.sala", "state": "on",
                 "attributes": {"brightness": 200}}
            ).encode(),
        )
        client = self._client()
        state = client.get_state("light.sala")
        assert state is not None
        assert state.entity_id == "light.sala" and state.state == "on"
        assert state.attributes["brightness"] == 200

    def test_get_state_404_returns_none(self, monkeypatch) -> None:
        from urllib.error import HTTPError

        fake_urlopen(
            monkeypatch,
            raise_error=HTTPError(
                "url", 404, "not found", {}, io.BytesIO(b'{"message":"x"}')
            ),
        )
        assert self._client().get_state("light.sumiu") is None

    def test_get_state_other_http_error_raises(self, monkeypatch) -> None:
        from urllib.error import HTTPError

        fake_urlopen(
            monkeypatch,
            raise_error=HTTPError(
                "url", 401, "unauthorized", {}, io.BytesIO(b"nope")
            ),
        )
        with pytest.raises(HAError, match="401"):
            self._client().get_state("light.sala")

    def test_list_states(self, monkeypatch) -> None:
        body = json.dumps(
            [
                {"entity_id": "light.a", "state": "on"},
                {"entity_id": "sensor.b", "state": "10"},
            ]
        ).encode()
        fake_urlopen(monkeypatch, body=body)
        states = self._client().list_states()
        assert [s.entity_id for s in states] == ["light.a", "sensor.b"]

    def test_call_service_sends_payload_and_bearer(self, monkeypatch) -> None:
        seen: dict = {}

        def fake(request, timeout):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode())

            class Resp:
                def read(self) -> bytes:
                    return json.dumps(
                        [{"entity_id": "light.sala", "state": "on"}]
                    ).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return None

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake)
        result = self._client().call_service(
            "light", "turn_on", entity_id="light.sala"
        )
        assert seen["url"] == "http://ha:8123/api/services/light/turn_on"
        assert seen["method"] == "POST"
        assert seen["auth"] == "Bearer tok123"
        assert seen["body"] == {"entity_id": "light.sala"}
        assert result[0].state == "on"

    def test_network_error_raises(self, monkeypatch) -> None:
        from urllib.error import URLError

        fake_urlopen(
            monkeypatch, raise_error=URLError("connection refused")
        )
        with pytest.raises(HAError, match="indispon"):
            self._client().list_states()

    def test_invalid_json_raises(self, monkeypatch) -> None:
        fake_urlopen(monkeypatch, body=b"{quebrado")
        with pytest.raises(HAError, match="JSON"):
            self._client().list_states()

    def test_empty_body_returns_empty(self, monkeypatch) -> None:
        fake_urlopen(monkeypatch, body=b"")
        assert self._client().list_states() == []

    def test_service_available_400_true_404_false(self, monkeypatch) -> None:
        from urllib.error import HTTPError

        fake_urlopen(
            monkeypatch,
            raise_error=HTTPError(
                "url", 400, "bad request", {}, io.BytesIO(b"x")
            ),
        )
        assert self._client().service_available("light", "turn_on") is True
        fake_urlopen(
            monkeypatch,
            raise_error=HTTPError(
                "url", 404, "not found", {}, io.BytesIO(b"x")
            ),
        )
        assert self._client().service_available("light", "zzz") is False


# ===========================================================================
# InMemoryHAServer (fake determinístico)
# ===========================================================================

class TestInMemoryHAServer:
    """Seed, leitura e aplicação de serviços no fake."""

    def test_seed_get_list(self) -> None:
        server = InMemoryHAServer()
        server.seed("light.sala", "off")
        server.seed("sensor.temp", "20.0")
        assert server.get_state("light.sala").state == "off"
        assert server.get_state("sensor.temp").state == "20.0"
        assert server.get_state("light.x") is None
        assert len(server.list_states()) == 2

    def test_call_service_on_off_toggle(self) -> None:
        server = InMemoryHAServer()
        server.seed("light.sala", "off")
        server.call_service("light", "turn_on", entity_id="light.sala")
        assert server.get_state("light.sala").state == "on"
        server.call_service("light", "turn_off", entity_id="light.sala")
        assert server.get_state("light.sala").state == "off"
        server.call_service("light", "toggle", entity_id="light.sala")
        assert server.get_state("light.sala").state == "on"

    def test_call_service_without_target_applies_to_domain(self) -> None:
        server = InMemoryHAServer()
        server.seed("light.a", "off")
        server.seed("light.b", "off")
        server.seed("switch.c", "off")
        affected = server.call_service("light", "turn_on")
        assert len(affected) == 2
        assert server.get_state("switch.c").state == "off"

    def test_unknown_entity_raises(self) -> None:
        server = InMemoryHAServer()
        with pytest.raises(HAError, match="404"):
            server.call_service("light", "turn_on", entity_id="light.x")

    def test_service_calls_recorded(self) -> None:
        server = InMemoryHAServer()
        server.seed("light.sala", "off")
        server.call_service("light", "toggle", entity_id="light.sala")
        assert server.service_calls == [
            {"domain": "light", "service": "toggle",
             "entity_id": "light.sala", "data": {}}
        ]


# ===========================================================================
# IoTManager — leitura
# ===========================================================================

class TestIoTManagerReads:
    """get_entity, list_entities, sensor_reading e snapshot."""

    def _manager(self) -> IoTManager:
        server = InMemoryHAServer()
        server.seed("light.sala", "off")
        server.seed("light.cozinha", "on")
        server.seed("sensor.temperatura", "21.5")
        server.seed("person.alex", "home")
        server.seed("camera.entrada", "idle")
        return IoTManager(server)

    def test_get_entity_existing_and_missing(self) -> None:
        manager = self._manager()
        entity = manager.get_entity("light.sala")
        assert entity is not None and entity.state == "off"
        assert manager.get_entity("light.inexistente") is None

    def test_list_entities_filtered_by_type(self) -> None:
        manager = self._manager()
        actuators = manager.list_entities(EntityType.ACTUATOR)
        assert {e.entity_id for e in actuators} == {
            "light.sala", "light.cozinha"
        }
        sensors = manager.list_entities(EntityType.SENSOR)
        assert [e.entity_id for e in sensors] == ["sensor.temperatura"]
        assert manager.list_entities() == manager.backend.list_states()

    def test_sensor_reading(self) -> None:
        manager = self._manager()
        assert manager.sensor_reading("sensor.temperatura") == "21.5"
        assert manager.sensor_reading("sensor.ausente") is None

    def test_snapshot_grouped_by_type(self) -> None:
        manager = self._manager()
        snap = manager.snapshot()
        assert snap["total"] == 5
        assert len(snap["entities"]["actuator"]) == 2
        assert len(snap["entities"]["sensor"]) == 1
        assert len(snap["entities"]["mobile"]) == 1
        assert len(snap["entities"]["infra"]) == 1
        assert snap["entities"]["unknown"] == []

    def test_list_types_counts(self) -> None:
        manager = self._manager()
        counts = manager.list_types()
        assert counts["actuator"] == 2
        assert counts["unknown"] == 0


# ===========================================================================
# IoTManager — controle, segurança e eventos
# ===========================================================================

class TestIoTManagerControl:
    """set_power/toggle, gates (guard/domínios) e métricas."""

    @pytest.fixture()
    def server(self) -> InMemoryHAServer:
        srv = InMemoryHAServer()
        srv.seed("light.sala", "off")
        srv.seed("switch.garagem", "off")
        return srv

    @pytest.mark.asyncio
    async def test_set_power_on_and_off(self, server) -> None:
        manager = IoTManager(server)
        assert await manager.set_power("light.sala", on=True)
        assert server.get_state("light.sala").state == "on"
        assert await manager.set_power("light.sala", on=False)
        assert server.get_state("light.sala").state == "off"
        assert server.service_calls[0]["service"] == "turn_on"
        assert server.service_calls[1]["service"] == "turn_off"

    @pytest.mark.asyncio
    async def test_toggle(self, server) -> None:
        manager = IoTManager(server)
        assert await manager.toggle("switch.garagem")
        assert server.get_state("switch.garagem").state == "on"
        assert await manager.toggle("switch.garagem")
        assert server.get_state("switch.garagem").state == "off"

    @pytest.mark.asyncio
    async def test_sensor_not_controllable(self, server) -> None:
        server.seed("sensor.temp", "20")
        manager = IoTManager(server)
        assert await manager.set_power("sensor.temp", on=True) is False
        assert manager.metrics.snapshot()["denied"] == 1
        assert server.get_state("sensor.temp").state == "20"

    @pytest.mark.asyncio
    async def test_unknown_entity_error_not_crash(self, server) -> None:
        manager = IoTManager(server)
        assert await manager.set_power("light.naoexiste", on=True) is False
        assert manager.metrics.snapshot()["errors"] == 1
        assert manager.metrics.snapshot()["commands_ok"] == 0

    @pytest.mark.asyncio
    async def test_guard_can_deny(self, server) -> None:
        calls: list[tuple[str, str]] = []

        def guard(entity_id: str, action: str) -> bool:
            calls.append((entity_id, action))
            return entity_id != "light.sala"

        manager = IoTManager(server, guard=guard)
        assert await manager.set_power("light.sala", on=True) is False
        assert manager.metrics.snapshot()["denied"] == 1
        assert await manager.set_power("switch.garagem", on=True)
        assert manager.metrics.snapshot()["commands_ok"] == 1
        assert ("switch.garagem", ACTION_ON) in calls

    @pytest.mark.asyncio
    async def test_allowed_domains_restricts(self, server) -> None:
        manager = IoTManager(
            server,
            config=IoTManagerConfig(allowed_domains=frozenset({"switch"})),
        )
        assert await manager.set_power("light.sala", on=True) is False
        assert manager.metrics.snapshot()["denied"] == 1
        assert await manager.set_power("switch.garagem", on=True)
        assert server.get_state("switch.garagem").state == "on"

    @pytest.mark.asyncio
    async def test_metrics_counters(self, server) -> None:
        manager = IoTManager(server)
        await manager.set_power("light.sala", on=True)
        await manager.toggle("switch.garagem")
        manager.get_entity("light.sala")
        metrics = manager.metrics.snapshot()
        assert metrics["commands"] == 2
        assert metrics["commands_ok"] == 2
        assert metrics["reads"] == 1
        assert metrics["denied"] == 0 and metrics["errors"] == 0

    @pytest.mark.asyncio
    async def test_event_bus_receives_command(self, server) -> None:
        bus = EventBus()
        received: list[dict] = []

        async def handler(event) -> None:
            received.append(event.data)

        bus.subscribe_handler("iot.command", handler)
        manager = IoTManager(server, event_bus=bus)
        await manager.set_power("light.sala", on=True)
        assert len(received) == 1
        assert received[0] == {
            "entity_id": "light.sala", "action": ACTION_ON, "ok": True
        }

    @pytest.mark.asyncio
    async def test_event_bus_not_required(self, server) -> None:
        manager = IoTManager(server)
        assert await manager.set_power("light.sala", on=True)

    def test_dump_shape(self, server) -> None:
        manager = IoTManager(server)
        data = manager.dump()
        assert data["backend"] == "InMemoryHAServer"
        assert data["guard"] is False
        assert data["event_bus"] is False
        assert data["config"]["allowed_domains"] is None
        assert "metrics" in data

    def test_controllable_flag(self, server) -> None:
        manager = IoTManager(server)
        assert manager.is_controllable("light.sala") is True
        assert manager.is_controllable("sensor.temp") is False
        restricted = IoTManager(
            server, config=IoTManagerConfig(allowed_domains=frozenset({"switch"}))
        )
        assert restricted.is_controllable("light.sala") is False
        assert restricted.is_controllable("switch.garagem") is True