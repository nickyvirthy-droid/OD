"""
OMEGA DRAKON • TESTS
Módulo: tests/test_presence.py
Descrição: Testes do Presence Monitor (integrations/homeassistant/presence.py)
           — Fase 6, item 6.2: classificação de estados (home/away/unknown),
           nomes legíveis, transições de chegada/saída sobre o backend fake,
           eventos no Event Bus, sinks (sync/async), persistência entre
           reinícios sem transição falsa, baseline silencioso, métricas e
           introspecção.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - ROADMAP_ABSORCAO.md Fase 6, item 6.2
"""

from __future__ import annotations

import json

import pytest

from core.event_bus import EventBus
from integrations.homeassistant import (
    InMemoryHAServer,
    PresenceChange,
    PresenceConfig,
    PresenceMonitor,
    classify,
    prettify_name,
)
from integrations.homeassistant.presence import (
    STATE_AWAY,
    STATE_HOME,
)


def _monitor(server, **kwargs):
    config_obj = kwargs.pop("config", None)
    event_bus = kwargs.pop("event_bus", None)
    sinks = kwargs.pop("sinks", None)
    clock = kwargs.pop("clock", None)
    if isinstance(config_obj, PresenceConfig):
        config = config_obj
    else:
        config = PresenceConfig(**(config_obj or {}), **kwargs)
    return PresenceMonitor(
        server, event_bus=event_bus, sinks=sinks, clock=clock, config=config
    )


class TestClassify:
    def test_home_states(self) -> None:
        assert classify("home", frozenset({"home"})) == STATE_HOME
        assert classify("home", frozenset({"home", "on"})) == STATE_HOME

    def test_custom_home_state(self) -> None:
        assert classify("work", frozenset({"work"})) == STATE_HOME

    def test_away_and_unknown(self) -> None:
        assert classify("not_home", frozenset({"home"})) == STATE_AWAY
        assert classify("unknown", frozenset({"home"})) == STATE_AWAY
        assert classify("", frozenset({"home"})) == STATE_AWAY
        assert classify("unavailable", frozenset({"home"})) == STATE_AWAY


class TestPrettifyName:
    def test_person_prefix(self) -> None:
        assert prettify_name("person.alex_projeti") == "Alex Projeti"
        assert prettify_name("person.ana") == "Ana"

    def test_device_tracker_prefix(self) -> None:
        assert prettify_name("device_tracker.celular_alex") == "Celular Alex"

    def test_fallback_keeps_id(self) -> None:
        assert prettify_name("coisa_estranha") == "Coisa Estranha"

    def test_empty(self) -> None:
        assert prettify_name("person.") == "person."


class TestPresenceTransitions:
    @pytest.fixture()
    def server(self) -> InMemoryHAServer:
        srv = InMemoryHAServer()
        srv.seed("person.alex_projeti", "not_home")
        return srv

    @pytest.mark.asyncio
    async def test_baseline_silent_first_tick(self, server) -> None:
        monitor = _monitor(server)
        changes = await monitor.tick()
        assert changes == []
        # baseline gravado, sem evento
        assert monitor.snapshot()["presence"] == {
            "person.alex_projeti": STATE_AWAY
        }

    @pytest.mark.asyncio
    async def test_arrival_detected(self, server) -> None:
        monitor = _monitor(server)
        await monitor.tick()  # baseline: away
        server.seed("person.alex_projeti", "home")
        changes = await monitor.tick()
        assert len(changes) == 1
        change = changes[0]
        assert change.arrival is True
        assert change.name == "Alex Projeti"
        assert change.previous == STATE_AWAY
        assert monitor.metrics.snapshot()["arrivals"] == 1
        assert monitor.metrics.snapshot()["transitions"] == 1

    @pytest.mark.asyncio
    async def test_departure_detected(self, server) -> None:
        server.seed("person.alex_projeti", "home")
        monitor = _monitor(server)
        await monitor.tick()  # baseline: home
        server.seed("person.alex_projeti", "not_home")
        changes = await monitor.tick()
        assert len(changes) == 1
        assert changes[0].arrival is False
        assert changes[0].previous == STATE_HOME
        assert monitor.metrics.snapshot()["departures"] == 1

    @pytest.mark.asyncio
    async def test_no_duplicate_while_state_stable(self, server) -> None:
        monitor = _monitor(server)
        await monitor.tick()  # baseline away
        server.seed("person.alex_projeti", "home")
        await monitor.tick()  # chegada
        await monitor.tick()  # continua home → nada
        assert monitor.metrics.snapshot()["transitions"] == 1
        assert len(monitor.history()) == 1  # só a chegada, sem duplicata

    @pytest.mark.asyncio
    async def test_unknown_after_home_is_departure(self, server) -> None:
        server.seed("person.alex_projeti", "home")
        monitor = _monitor(server)
        await monitor.tick()
        server.seed("person.alex_projeti", "unknown")
        changes = await monitor.tick()
        assert len(changes) == 1
        assert changes[0].state == STATE_AWAY

    @pytest.mark.asyncio
    async def test_watched_ids_filter(self, server) -> None:
        server.seed("person.outra", "home")
        monitor = _monitor(
            server,
            config=PresenceConfig(entity_ids=("person.alex_projeti",)),
        )
        changes = await monitor.tick()
        assert changes == []
        assert monitor.snapshot()["presence"] == {
            "person.alex_projeti": STATE_AWAY
        }
        assert "person.outra" not in monitor.snapshot()["presence"]

    @pytest.mark.asyncio
    async def test_custom_names_mapping(self, server) -> None:
        server.seed("device_tracker.celular", "home")
        monitor = _monitor(
            server,
            config=PresenceConfig(
                entity_ids=("device_tracker.celular",),
                names={"device_tracker.celular": "Celular do Alex"},
            ),
        )
        await monitor.tick()
        server.seed("device_tracker.celular", "not_home")
        changes = await monitor.tick()
        assert changes[0].name == "Celular do Alex"


class TestPresenceEventsAndSinks:
    @pytest.mark.asyncio
    async def test_event_bus_receives_change(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")
        bus = EventBus()
        events: list[dict] = []
        bus.subscribe_handler("presence.changed", lambda e: events.append(e.data))
        monitor = _monitor(server, event_bus=bus)
        await monitor.tick()  # baseline
        server.seed("person.alex_projeti", "home")
        await monitor.tick()
        assert len(events) == 1
        assert events[0]["state"] == STATE_HOME
        assert events[0]["name"] == "Alex Projeti"

    @pytest.mark.asyncio
    async def test_sync_sink_called(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")
        calls: list[PresenceChange] = []
        monitor = _monitor(server, sinks=[calls.append])
        await monitor.tick()
        server.seed("person.alex_projeti", "home")
        await monitor.tick()
        assert len(calls) == 1
        assert calls[0].arrival is True

    @pytest.mark.asyncio
    async def test_async_sink_called(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")
        calls: list[str] = []

        async def sink(change: PresenceChange) -> None:
            calls.append(change.name)

        monitor = _monitor(server, sinks=[sink])
        await monitor.tick()
        server.seed("person.alex_projeti", "home")
        await monitor.tick()
        assert calls == ["Alex Projeti"]

    @pytest.mark.asyncio
    async def test_sink_error_counted_not_fatal(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")

        def broken(change) -> None:
            raise RuntimeError("sink explodiu")

        monitor = _monitor(server, sinks=[broken])
        await monitor.tick()
        server.seed("person.alex_projeti", "home")
        await monitor.tick()
        assert monitor.metrics.snapshot()["errors"] == 1
        assert monitor.snapshot()["presence"]["person.alex_projeti"] == STATE_HOME

    @pytest.mark.asyncio
    async def test_backend_error_counted_not_fatal(self) -> None:
        class BrokenBackend:
            def list_states(self):
                raise RuntimeError("HA fora do ar")

        monitor = PresenceMonitor(BrokenBackend())
        assert await monitor.tick() == []
        assert monitor.metrics.snapshot()["errors"] == 1

    def test_format_change(self) -> None:
        change = PresenceChange(
            entity_id="person.alex_projeti", name="Alex Projeti",
            state=STATE_HOME, previous=STATE_AWAY, ts=0.0,
        )
        text = PresenceMonitor.format_change(change)
        assert "🏠" in text and "Alex Projeti" in text and "chegou" in text


class TestPresencePersistence:
    @pytest.mark.asyncio
    async def test_state_persisted_and_restart_silent(self, tmp_path) -> None:
        state_file = tmp_path / "presence_state.json"
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")
        monitor = _monitor(server, config=PresenceConfig(state_file=state_file))
        await monitor.tick()  # baseline away (gravado? só em transição)
        server.seed("person.alex_projeti", "home")
        await monitor.tick()  # chegada → grava home
        data = json.loads(state_file.read_text())
        assert data["person.alex_projeti"] == STATE_HOME

        # "Reinício": novo monitor lê o arquivo — estado home persistido
        server.seed("person.alex_projeti", "home")
        monitor2 = _monitor(server, config=PresenceConfig(state_file=state_file))
        changes = await monitor2.tick()
        assert changes == []  # sem transição falsa no restart

    @pytest.mark.asyncio
    async def test_restart_then_arrival_still_fires(self, tmp_path) -> None:
        state_file = tmp_path / "presence_state.json"
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "home")
        monitor = _monitor(server, config=PresenceConfig(state_file=state_file))
        await monitor.tick()  # baseline home (sem evento, não grava)
        # reinício: arquivo sem entrada → baseline de novo (silencioso)
        monitor2 = _monitor(server, config=PresenceConfig(state_file=state_file))
        await monitor2.tick()
        server.seed("person.alex_projeti", "not_home")
        monitor3 = _monitor(server, config=PresenceConfig(state_file=state_file))
        await monitor3.tick()
        server.seed("person.alex_projeti", "home")
        changes = await monitor3.tick()
        assert len(changes) == 1
        assert changes[0].arrival is True

    def test_unreadable_state_ignored(self, tmp_path) -> None:
        state_file = tmp_path / "presence_state.json"
        state_file.write_text("{não é json")
        monitor = _monitor(
            InMemoryHAServer(),
            config=PresenceConfig(state_file=state_file),
        )
        assert monitor.snapshot()["presence"] == {}

    @pytest.mark.asyncio
    async def test_run_max_ticks(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "home")
        monitor = _monitor(server)
        ticks = await monitor.run(interval=0.001, max_ticks=3)
        assert ticks == 3
        assert monitor.metrics.snapshot()["polls"] == 3


class TestPresenceIntrospection:
    @pytest.mark.asyncio
    async def test_snapshot_and_dump(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")
        server.seed("device_tracker.celular", "home")
        monitor = _monitor(server)
        await monitor.tick()
        snap = monitor.snapshot()
        assert snap["presence"]["person.alex_projeti"] == STATE_AWAY
        assert snap["presence"]["device_tracker.celular"] == STATE_HOME
        dump = monitor.dump()
        assert dump["changes"] == []
        health = monitor.health()
        assert health["home_now"] == ["device_tracker.celular"]

    @pytest.mark.asyncio
    async def test_start_stop_thread(self) -> None:
        server = InMemoryHAServer()
        server.seed("person.alex_projeti", "not_home")
        monitor = _monitor(server, config=PresenceConfig(poll_interval_s=0.01))
        thread = monitor.start()
        import time
        time.sleep(0.15)
        monitor.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert monitor.metrics.snapshot()["polls"] >= 1
