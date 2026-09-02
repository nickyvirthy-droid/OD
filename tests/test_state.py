#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_state
Description: Unit tests for core/state.py — system-wide state manager.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from core.event_bus import EventBus, Event
from core.state import StateManager, StateSnapshot, StateValue, Watcher


# ===========================================================================
# StateValue
# ===========================================================================

class TestStateValue:
    """Tests for the StateValue dataclass."""

    def test_creation(self) -> None:
        sv = StateValue(value="hello")
        assert sv.value == "hello"
        assert sv.version == 1
        assert sv.source == ""
        assert isinstance(sv.ts, float)

    def test_creation_with_options(self) -> None:
        sv = StateValue(value=42, version=5, ts=1000.0, source="test")
        assert sv.value == 42
        assert sv.version == 5
        assert sv.ts == 1000.0
        assert sv.source == "test"

    def test_to_dict(self) -> None:
        sv = StateValue(value={"key": "val"}, version=3, ts=100.0, source="api")
        d = sv.to_dict()
        assert d["value"] == {"key": "val"}
        assert d["version"] == 3
        assert d["ts"] == 100.0
        assert d["source"] == "api"

    def test_from_dict(self) -> None:
        d = {"value": [1, 2, 3], "version": 2, "ts": 200.0, "source": "import"}
        sv = StateValue.from_dict(d)
        assert sv.value == [1, 2, 3]
        assert sv.version == 2
        assert sv.ts == 200.0
        assert sv.source == "import"

    def test_from_dict_defaults(self) -> None:
        sv = StateValue.from_dict({"value": "x"})
        assert sv.version == 1
        assert isinstance(sv.ts, float)
        assert sv.source == ""


# ===========================================================================
# StateSnapshot
# ===========================================================================

class TestStateSnapshot:
    """Tests for StateSnapshot dataclass."""

    def test_creation(self) -> None:
        snap = StateSnapshot(version=1, ts=100.0, data={"k": {"value": "v"}})
        assert snap.version == 1
        assert snap.ts == 100.0
        assert snap.data["k"]["value"] == "v"

    def test_to_dict(self) -> None:
        snap = StateSnapshot(version=1, ts=100.0, data={})
        d = snap.to_dict()
        assert d["version"] == 1
        assert d["ts"] == 100.0
        assert d["data"] == {}

    def test_from_dict(self) -> None:
        d = {"version": 5, "ts": 500.0, "data": {"a": {"value": 1}}}
        snap = StateSnapshot.from_dict(d)
        assert snap.version == 5
        assert snap.ts == 500.0
        assert snap.data == {"a": {"value": 1}}


# ===========================================================================
# StateManager — lifecycle
# ===========================================================================

class TestStateManagerLifecycle:
    """Tests for StateManager start/stop."""

    def test_initial_state(self) -> None:
        sm = StateManager()
        assert not sm.running
        assert sm.global_version == 0

    @pytest.mark.asyncio
    async def test_start(self) -> None:
        sm = StateManager()
        await sm.start()
        assert sm.running

    @pytest.mark.asyncio
    async def test_start_already_running(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.start()  # should warn, not crash
        assert sm.running

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.stop()
        assert not sm.running

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        sm = StateManager()
        await sm.stop()  # no-op
        assert not sm.running


# ===========================================================================
# StateManager — get/set/delete
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerGetSetDelete:
    """Tests for basic get/set/delete operations."""

    async def test_get_default(self) -> None:
        sm = StateManager()
        await sm.start()
        assert await sm.get("nonexistent") is None
        assert await sm.get("nonexistent", default="fallback") == "fallback"

    async def test_set_and_get(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("system.status", "running")
        assert await sm.get("system.status") == "running"

    async def test_set_returns_state_value(self) -> None:
        sm = StateManager()
        await sm.start()
        sv = await sm.set("test.key", "value")
        assert isinstance(sv, StateValue)
        assert sv.value == "value"
        assert sv.version == 1

    async def test_set_increments_version(self) -> None:
        sm = StateManager()
        await sm.start()
        sv1 = await sm.set("k", "v1")
        sv2 = await sm.set("k", "v2")
        assert sv2.version > sv1.version
        assert sm.global_version == 2

    async def test_set_source(self) -> None:
        sm = StateManager()
        await sm.start()
        sv = await sm.set("k", "v", source="nicky")
        assert sv.source == "nicky"

    async def test_set_deep_copies_value(self) -> None:
        sm = StateManager()
        await sm.start()
        data = {"nested": [1, 2, 3]}
        await sm.set("k", data)
        data["nested"].append(4)
        assert await sm.get("k") == {"nested": [1, 2, 3]}

    async def test_overwrite(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "old")
        await sm.set("k", "new")
        assert await sm.get("k") == "new"

    async def test_get_state(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v", source="test")
        sv = await sm.get_state("k")
        assert sv is not None
        assert sv.value == "v"
        assert sv.source == "test"

    async def test_get_state_nonexistent(self) -> None:
        sm = StateManager()
        await sm.start()
        assert await sm.get_state("nope") is None

    async def test_delete_existing(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v")
        result = await sm.delete("k")
        assert result is True
        assert await sm.get("k") is None

    async def test_delete_nonexistent(self) -> None:
        sm = StateManager()
        await sm.start()
        result = await sm.delete("nope")
        assert result is False

    async def test_get_many(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a", 1)
        await sm.set("b", 2)
        result = await sm.get_many(["a", "b", "c"])
        assert result == {"a": 1, "b": 2}

    async def test_set_many(self) -> None:
        sm = StateManager()
        await sm.start()
        count = await sm.set_many({"a": 1, "b": 2, "c": 3})
        assert count == 3
        assert await sm.get("a") == 1
        assert await sm.get("b") == 2
        assert await sm.get("c") == 3

    async def test_keys(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a.x", 1)
        await sm.set("a.y", 2)
        await sm.set("b.z", 3)
        all_keys = await sm.keys()
        assert all_keys == ["a.x", "a.y", "b.z"]

    async def test_keys_with_prefix(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a.x", 1)
        await sm.set("a.y", 2)
        await sm.set("b.z", 3)
        a_keys = await sm.keys(prefix="a.")
        assert a_keys == ["a.x", "a.y"]

    async def test_clear(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a", 1)
        await sm.set("b", 2)
        count = await sm.clear()
        assert count == 2
        assert await sm.get("a") is None
        assert await sm.get("b") is None

    async def test_clear_empty(self) -> None:
        sm = StateManager()
        await sm.start()
        count = await sm.clear()
        assert count == 0


# ===========================================================================
# StateManager — compare_and_set
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerCAS:
    """Tests for atomic compare-and-swap."""

    async def test_cas_success(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "old")
        result = await sm.compare_and_set("k", "old", "new")
        assert result is True
        assert await sm.get("k") == "new"

    async def test_cas_failure(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "actual")
        result = await sm.compare_and_set("k", "wrong", "new")
        assert result is False
        assert await sm.get("k") == "actual"

    async def test_cas_nonexistent_key(self) -> None:
        sm = StateManager()
        await sm.start()
        result = await sm.compare_and_set("nope", None, "value")
        assert result is True
        assert await sm.get("nope") == "value"


# ===========================================================================
# StateManager — watchers
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerWatchers:
    """Tests for state change watchers."""

    async def test_watcher_receives_change(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[tuple[str, Any, Any]] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append((key, old, new))

        sm.watch("system.*", on_change)
        await sm.set("system.status", "running")

        assert len(received) == 1
        assert received[0] == ("system.status", None, "running")

    async def test_watcher_receives_update(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[tuple[str, Any, Any]] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append((key, old, new))

        sm.watch("k", on_change)
        await sm.set("k", "v1")
        await sm.set("k", "v2")

        assert len(received) == 2
        assert received[0] == ("k", None, "v1")
        assert received[1] == ("k", "v1", "v2")

    async def test_watcher_receives_delete(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[tuple[str, Any, Any]] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append((key, old, new))

        sm.watch("k", on_change)
        await sm.set("k", "v")
        await sm.delete("k")

        assert len(received) == 2
        assert received[1] == ("k", "v", None)

    async def test_watcher_wildcard(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[str] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append(key)

        sm.watch("system.**", on_change)
        await sm.set("system.status", "ok")
        await sm.set("system.bridge.health", "up")
        await sm.set("other.key", "ignored")

        assert received == ["system.status", "system.bridge.health"]

    async def test_watcher_exact_match(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[str] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append(key)

        sm.watch("exact.key", on_change)
        await sm.set("exact.key", 1)
        await sm.set("exact.other", 2)

        assert received == ["exact.key"]

    async def test_unwatch(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[str] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append(key)

        w = sm.watch("k", on_change)
        await sm.set("k", "v1")
        sm.unwatch(w)
        await sm.set("k", "v2")

        assert received == ["k"]

    async def test_sync_watcher(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[str] = []

        def on_change(key: str, old: Any, new: Any) -> None:
            received.append(key)

        sm.watch("k", on_change)
        await sm.set("k", "v")

        assert received == ["k"]

    async def test_watcher_error_does_not_break_bus(self) -> None:
        sm = StateManager()
        await sm.start()

        async def bad_watcher(key: str, old: Any, new: Any) -> None:
            raise RuntimeError("watcher broke")

        sm.watch("k", bad_watcher)
        # Should not raise
        await sm.set("k", "v")
        assert await sm.get("k") == "v"

    async def test_watcher_set_many(self) -> None:
        sm = StateManager()
        await sm.start()
        received: list[str] = []

        async def on_change(key: str, old: Any, new: Any) -> None:
            received.append(key)

        sm.watch("**", on_change)
        await sm.set_many({"a": 1, "b": 2})

        assert "a" in received
        assert "b" in received


# ===========================================================================
# StateManager — Event Bus integration
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerEventBus:
    """Tests for Event Bus integration."""

    async def test_publishes_state_changed(self) -> None:
        bus = EventBus()
        await bus.start()
        sm = StateManager(event_bus=bus)
        await sm.start()

        received: list[Event] = []

        async def on_state(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("state.**", on_state)
        await sm.set("k", "v")

        assert len(received) >= 1
        assert received[0].topic == "state.changed"
        assert received[0].data["key"] == "k"
        assert received[0].data["value"] == "v"

    async def test_publishes_state_removed(self) -> None:
        bus = EventBus()
        await bus.start()
        sm = StateManager(event_bus=bus)
        await sm.start()

        received: list[Event] = []

        async def on_state(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("state.**", on_state)
        await sm.set("k", "v")
        await sm.delete("k")

        removed = [e for e in received if e.topic == "state.removed"]
        assert len(removed) == 1
        assert removed[0].data["key"] == "k"

    async def test_publishes_state_cleared(self) -> None:
        bus = EventBus()
        await bus.start()
        sm = StateManager(event_bus=bus)
        await sm.start()

        received: list[Event] = []

        async def on_state(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("state.**", on_state)
        await sm.set("k", "v")
        await sm.clear()

        cleared = [e for e in received if e.topic == "state.cleared"]
        assert len(cleared) == 1

    async def test_publishes_state_rollback(self) -> None:
        bus = EventBus()
        await bus.start()
        sm = StateManager(event_bus=bus)
        await sm.start()

        received: list[Event] = []

        async def on_state(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("state.**", on_state)
        await sm.set("k", "v1")
        await sm.set("k", "v2")
        await sm.rollback(steps=1)

        rollbacks = [e for e in received if e.topic == "state.rollback"]
        assert len(rollbacks) == 1
        assert rollbacks[0].data["steps"] == 1

    async def test_no_bus_no_crash(self) -> None:
        """StateManager works without an EventBus."""
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v")
        assert await sm.get("k") == "v"
        await sm.delete("k")
        assert await sm.get("k") is None


# ===========================================================================
# StateManager — rollback
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerRollback:
    """Tests for rollback functionality."""

    async def test_rollback_one_step(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v1")
        await sm.set("k", "v2")
        assert await sm.get("k") == "v2"

        result = await sm.rollback(steps=1)
        assert result is True
        assert await sm.get("k") == "v1"

    async def test_rollback_multiple_steps(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v1")
        await sm.set("k", "v2")
        await sm.set("k", "v3")

        result = await sm.rollback(steps=2)
        assert result is True
        assert await sm.get("k") == "v1"

    async def test_rollback_insufficient_history(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v1")

        result = await sm.rollback(steps=5)
        assert result is False
        assert await sm.get("k") == "v1"

    async def test_rollback_invalid_steps(self) -> None:
        sm = StateManager()
        await sm.start()
        result = await sm.rollback(steps=0)
        assert result is False

    async def test_rollback_restores_multiple_keys(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a", 1)
        await sm.set("b", 2)
        # Now clear
        await sm.clear()
        assert await sm.get("a") is None

        await sm.rollback(steps=1)
        assert await sm.get("a") == 1
        assert await sm.get("b") == 2

    async def test_rollback_to_version(self) -> None:
        sm = StateManager()
        await sm.start()
        sv1 = await sm.set("k", "v1")
        await sm.set("k", "v2")
        await sm.set("k", "v3")

        result = await sm.rollback_to_version(sv1.version)
        assert result is True
        assert await sm.get("k") == "v1"

    async def test_rollback_to_version_not_found(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("k", "v1")

        result = await sm.rollback_to_version(99999)
        assert result is True  # finds closest snapshot <= target
        assert await sm.get("k") == "v1"

    async def test_rollback_to_version_before_any(self) -> None:
        sm = StateManager()
        await sm.start()
        # No history at all
        result = await sm.rollback_to_version(0)
        assert result is False


# ===========================================================================
# StateManager — export/import
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerExportImport:
    """Tests for export and import."""

    async def test_export(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a", 1)
        await sm.set("b", "two")

        data = await sm.export_state()
        assert data["global_version"] == 2
        assert data["keys"]["a"]["value"] == 1
        assert data["keys"]["b"]["value"] == "two"

    async def test_import(self) -> None:
        sm = StateManager()
        await sm.start()

        data = {
            "global_version": 5,
            "keys": {
                "x": {"value": 10, "version": 1, "ts": 100.0, "source": "import"},
                "y": {"value": "hello", "version": 2, "ts": 200.0, "source": "import"},
            },
        }
        count = await sm.import_state(data)

        assert count == 2
        assert await sm.get("x") == 10
        assert await sm.get("y") == "hello"

    async def test_roundtrip(self) -> None:
        sm1 = StateManager()
        await sm1.start()
        await sm1.set("k", {"nested": [1, 2, 3]})
        data = await sm1.export_state()

        sm2 = StateManager()
        await sm2.start()
        await sm2.import_state(data)
        assert await sm2.get("k") == {"nested": [1, 2, 3]}


# ===========================================================================
# StateManager — disk persistence
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerPersistence:
    """Tests for disk persistence."""

    async def test_persist_and_load(self, tmp_path: Path) -> None:
        persist_file = tmp_path / "state.json"

        # Write state
        sm1 = StateManager(persist_path=persist_file)
        await sm1.start()
        await sm1.set("a", 1)
        await sm1.set("b", "two")
        # Force immediate persist
        await sm1._persist_now()
        await sm1.stop()

        # Verify file exists
        assert persist_file.exists()

        # Read state
        sm2 = StateManager(persist_path=persist_file)
        await sm2.start()
        assert await sm2.get("a") == 1
        assert await sm2.get("b") == "two"
        await sm2.stop()

    async def test_persist_atomic_write(self, tmp_path: Path) -> None:
        persist_file = tmp_path / "state.json"
        sm = StateManager(persist_path=persist_file)
        await sm.start()
        await sm.set("k", "v")
        await sm._persist_now()

        # No .tmp file should remain
        assert not (tmp_path / "state.tmp").exists()
        assert persist_file.exists()

    async def test_load_nonexistent(self, tmp_path: Path) -> None:
        persist_file = tmp_path / "nonexistent.json"
        sm = StateManager(persist_path=persist_file)
        await sm.start()
        assert await sm.get("k") is None
        await sm.stop()


# ===========================================================================
# StateManager — dump / inspection
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerDump:
    """Tests for diagnostic dump."""

    async def test_dump(self) -> None:
        sm = StateManager()
        await sm.start()
        await sm.set("a", 1)

        dump = await sm.dump()
        assert dump["running"] is True
        assert dump["global_version"] == 1
        assert dump["key_count"] == 1
        assert dump["state"]["a"]["value"] == 1

    async def test_dump_empty(self) -> None:
        sm = StateManager()
        await sm.start()
        dump = await sm.dump()
        assert dump["key_count"] == 0
        assert dump["state"] == {}


# ===========================================================================
# StateManager — integration patterns
# ===========================================================================

@pytest.mark.asyncio
class TestStateManagerIntegration:
    """Integration tests simulating real OmegaDrakon usage."""

    async def test_hierarchical_state(self) -> None:
        """Simulate hierarchical component state tracking."""
        sm = StateManager()
        await sm.start()

        await sm.set("system.status", "running")
        await sm.set("system.bridge.health", "up")
        await sm.set("system.bridge.port", 8765)
        await sm.set("agent.nicky.status", "active")

        # Query by prefix
        system_keys = await sm.keys(prefix="system.")
        assert len(system_keys) == 3
        assert "system.status" in system_keys

        agent_keys = await sm.keys(prefix="agent.")
        assert len(agent_keys) == 1

    async def test_status_machine_pattern(self) -> None:
        """Simulate a status machine with CAS."""
        sm = StateManager()
        await sm.start()
        await sm.set("job.status", "pending")

        # Try to claim the job
        claimed = await sm.compare_and_set("job.status", "pending", "running")
        assert claimed is True
        assert await sm.get("job.status") == "running"

        # Another component tries to claim — fails
        claimed2 = await sm.compare_and_set("job.status", "pending", "running")
        assert claimed2 is False

    async def test_rollback_on_error(self) -> None:
        """Simulate saving state before risky operation, rolling back on failure."""
        sm = StateManager()
        await sm.start()

        # Save good state
        await sm.set("config.debug", False)
        await sm.set("config.verbose", True)

        # Risky operation
        try:
            await sm.set("config.debug", True)  # risky change
            raise ValueError("operation failed")
        except ValueError:
            # Rollback the risky change
            await sm.rollback(steps=1)

        assert await sm.get("config.debug") is False
        assert await sm.get("config.verbose") is True

    async def test_watcher_reactive_pattern(self) -> None:
        """Watchers trigger side effects on state changes."""
        sm = StateManager()
        await sm.start()
        actions: list[str] = []

        async def on_health_change(key: str, old: Any, new: Any) -> None:
            if new == "down":
                actions.append("alert_sent")
            elif new == "up":
                actions.append("recovered")

        sm.watch("system.bridge.health", on_health_change)

        await sm.set("system.bridge.health", "down")
        await sm.set("system.bridge.health", "up")

        assert actions == ["alert_sent", "recovered"]

    async def test_multi_component_state(self) -> None:
        """Multiple components manage their own state namespace."""
        sm = StateManager()
        await sm.start()

        # Bridge component
        await sm.set("bridge.status", "listening")
        await sm.set("bridge.port", 8765)

        # Agent component
        await sm.set("agent.status", "idle")
        await sm.set("agent.model", "qwen2.5-3b")

        # Event Bus component
        await sm.set("bus.status", "active")
        await sm.set("bus.handlers", 5)

        # Each component reads only its own namespace
        bridge_status = await sm.get("bridge.status")
        assert bridge_status == "listening"

        agent_model = await sm.get("agent.model")
        assert agent_model == "qwen2.5-3b"

        bus_handlers = await sm.get("bus.handlers")
        assert bus_handlers == 5
