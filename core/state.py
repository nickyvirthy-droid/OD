#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Module: state
Description: System-wide state manager — versioned, observable, rollback-capable.
             Tracks hierarchical keys, publishes changes through the Event Bus,
             supports watchers, atomic compare-and-swap, and disk persistence.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Architecture:
    The State Manager is the single source of truth for runtime state across
    all OmegaDrakon components. Every mutation is versioned, timestamped, and
    published as an event on the bus, enabling reactive patterns without
    tight coupling.

    State keys use dot-separated hierarchical paths (like topics in the bus):
        "system.status"
        "agent.nicky.heartbeat.last_seen"
        "runtime.bridge.health"

    The State Manager does NOT replace the memory/ layer — it tracks mutable
    runtime state (health, status, config flags), while memory/ handles
    persistent knowledge, embeddings, and episodic records.

Protocol:
    All mutations emit events on the bus:
        state.changed   — when a key is set or updated
        state.removed   — when a key is deleted
        state.rollback  — when a rollback occurs
    Watchers receive granular notifications for specific key patterns.

Usage:
    from core.state import StateManager
    from core.event_bus import EventBus

    bus = EventBus()
    sm = StateManager(event_bus=bus)

    await sm.start()
    await sm.set("system.status", "running")
    print(await sm.get("system.status"))  # "running"

    # Watch for changes
    async def on_status_change(event):
        print(f"Status changed to: {event.data['value']}")

    sm.watch("system.*", on_status_change)
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional, Union

from core.event_bus import Event, EventBus, Priority

logger = logging.getLogger("omega.core.state")

NICKY_PREFIX = "[NICKY][{level}]"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_HISTORY = 500
PERSIST_DEBOUNCE = 0.5  # seconds to debounce disk writes


# ---------------------------------------------------------------------------
# StateValue — versioned value wrapper
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StateValue:
    """A versioned, timestamped state value.

    Attributes:
        value:   The current value (any JSON-serializable type).
        version: Monotonically increasing version number.
        ts:      Unix timestamp of last modification.
        source:  Identifier of the component that last set this value.
    """
    value: Any
    version: int = 1
    ts: float = field(default_factory=time.time)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "version": self.version,
            "ts": self.ts,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateValue:
        return cls(
            value=data["value"],
            version=data.get("version", 1),
            ts=data.get("ts", time.time()),
            source=data.get("source", ""),
        )


# ---------------------------------------------------------------------------
# StateHistory — snapshot of a point-in-time state
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StateSnapshot:
    """A point-in-time snapshot of the entire state tree."""
    version: int
    ts: float
    data: dict[str, Any]  # key → serialized StateValue

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ts": self.ts,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateSnapshot:
        return cls(
            version=data["version"],
            ts=data["ts"],
            data=data["data"],
        )


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

# Watcher handler type
SyncWatcher = Callable[[str, Any, Any], None]
AsyncWatcher = Callable[[str, Any, Any], Coroutine[Any, Any, None]]
WatcherHandler = Union[SyncWatcher, AsyncWatcher]


@dataclass(slots=True)
class Watcher:
    """A watcher registration — watches a key pattern for changes."""
    pattern: str
    handler: WatcherHandler
    handler_name: str
    active: bool = True


# ---------------------------------------------------------------------------
# Audit Logger (NICKY Protocol)
# ---------------------------------------------------------------------------

def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """System-wide state manager with versioning, rollback, and observability.

    Attributes:
        event_bus:    Optional EventBus for publishing state changes.
        persist_path: Optional file path for disk persistence.
    """

    def __init__(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        persist_path: Optional[Path] = None,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self._state: dict[str, StateValue] = {}
        self._global_version: int = 0
        self._history: list[StateSnapshot] = []
        self._max_history = max_history
        self._watchers: list[Watcher] = []
        self._event_bus = event_bus
        self._persist_path = persist_path
        self._running = False
        self._lock = asyncio.Lock()
        self._persist_task: Optional[asyncio.Task[None]] = None
        self._persist_dirty = False

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def global_version(self) -> int:
        return self._global_version

    async def start(self) -> None:
        """Start the state manager and load persisted state if available."""
        if self._running:
            _audit_nicky("WARN", "StateManager already running")
            return

        # Load persisted state
        if self._persist_path and self._persist_path.exists():
            await self._load_from_disk()

        self._running = True
        _audit_nicky(
            "INFO",
            "StateManager started",
            keys=len(self._state),
            global_version=self._global_version,
        )

    async def stop(self) -> None:
        """Stop the state manager and persist final state."""
        if not self._running:
            return
        self._running = False

        # Final persist
        if self._persist_dirty and self._persist_path:
            await self._save_to_disk()

        # Cancel pending persist task
        if self._persist_task is not None and not self._persist_task.cancelled():
            self._persist_task.cancel()

        _audit_nicky(
            "INFO",
            "StateManager stopped",
            keys=len(self._state),
            global_version=self._global_version,
        )

    # -- Core Operations -----------------------------------------------------

    async def get(self, key: str, *, default: Any = None) -> Any:
        """Get the value for a state key.

        Args:
            key:     Dot-separated state key.
            default: Value to return if key doesn't exist.

        Returns:
            The current value, or default if not set.
        """
        sv = self._state.get(key)
        if sv is None:
            return default
        return sv.value

    async def get_state(self, key: str) -> Optional[StateValue]:
        """Get the full StateValue (with version, ts, source) for a key.

        Returns None if key doesn't exist.
        """
        return self._state.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        source: str = "",
    ) -> StateValue:
        """Set a state value. Increments global version and publishes event.

        Args:
            key:    Dot-separated state key.
            value:  Any JSON-serializable value.
            source: Identifier of the component setting the value.

        Returns:
            The new StateValue with updated version and timestamp.
        """
        async with self._lock:
            old_value = None
            old_sv = self._state.get(key)
            if old_sv is not None:
                old_value = old_sv.value

            self._global_version += 1
            sv = StateValue(
                value=copy.deepcopy(value),
                version=self._global_version,
                ts=time.time(),
                source=source,
            )
            self._state[key] = sv

            # Snapshot for rollback
            self._record_snapshot()

            # Notify watchers
            await self._notify_watchers(key, old_value, value)

            # Publish bus event
            if self._event_bus:
                await self._event_bus.publish(Event(
                    topic="state.changed",
                    data={"key": key, "value": value, "old_value": old_value, "version": sv.version},
                    source=source or "state_manager",
                ))

            # Schedule persist
            self._schedule_persist()

            _audit_nicky(
                "INFO",
                "State set",
                key=key,
                version=sv.version,
                source=source,
            )
            return sv

    async def delete(self, key: str, *, source: str = "") -> bool:
        """Delete a state key. Returns True if the key existed.

        Publishes state.removed event if key existed.
        """
        async with self._lock:
            old_sv = self._state.pop(key, None)
            if old_sv is None:
                return False

            self._global_version += 1

            # Snapshot for rollback
            self._record_snapshot()

            # Notify watchers
            await self._notify_watchers(key, old_sv.value, None)

            # Publish bus event
            if self._event_bus:
                await self._event_bus.publish(Event(
                    topic="state.removed",
                    data={"key": key, "old_value": old_sv.value, "version": self._global_version},
                    source=source or "state_manager",
                ))

            # Schedule persist
            self._schedule_persist()

            _audit_nicky(
                "INFO",
                "State deleted",
                key=key,
                version=self._global_version,
                source=source,
            )
            return True

    async def compare_and_set(
        self,
        key: str,
        expected: Any,
        new_value: Any,
        *,
        source: str = "",
    ) -> bool:
        """Atomic compare-and-swap. Sets new_value only if current == expected.

        Returns True if the swap succeeded, False otherwise.
        """
        async with self._lock:
            current_sv = self._state.get(key)
            current = current_sv.value if current_sv is not None else None

            if current != expected:
                _audit_nicky(
                    "INFO",
                    "CAS failed",
                    key=key,
                    expected=expected,
                    actual=current,
                )
                return False

        # Release lock before set to avoid deadlock (set acquires lock)
        await self.set(key, new_value, source=source)
        return True

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Get multiple values at once. Returns dict of key → value.

        Keys that don't exist are omitted from the result.
        """
        result: dict[str, Any] = {}
        for key in keys:
            sv = self._state.get(key)
            if sv is not None:
                result[key] = sv.value
        return result

    async def set_many(
        self,
        updates: dict[str, Any],
        *,
        source: str = "",
    ) -> int:
        """Set multiple values atomically. Returns number of keys set.

        All updates are applied under a single lock, and a single snapshot
        is recorded.
        """
        count = 0
        async with self._lock:
            for key, value in updates.items():
                old_sv = self._state.get(key)
                old_value = old_sv.value if old_sv is not None else None

                self._global_version += 1
                sv = StateValue(
                    value=copy.deepcopy(value),
                    version=self._global_version,
                    ts=time.time(),
                    source=source,
                )
                self._state[key] = sv

                await self._notify_watchers(key, old_value, value)
                count += 1

            self._record_snapshot()
            self._schedule_persist()

        # Publish events after lock release
        if self._event_bus:
            for key, value in updates.items():
                await self._event_bus.publish(Event(
                    topic="state.changed",
                    data={"key": key, "value": value, "version": self._global_version},
                    source=source or "state_manager",
                ))

        _audit_nicky(
            "INFO",
            "State set_many",
            count=count,
            version=self._global_version,
            source=source,
        )
        return count

    async def keys(self, prefix: str = "") -> list[str]:
        """List all state keys, optionally filtered by prefix.

        Args:
            prefix: If provided, only return keys starting with this prefix.
        """
        if prefix:
            return [k for k in sorted(self._state.keys()) if k.startswith(prefix)]
        return sorted(self._state.keys())

    async def clear(self, *, source: str = "") -> int:
        """Clear all state. Returns number of keys removed.

        Records a snapshot before clearing for rollback support.
        """
        async with self._lock:
            count = len(self._state)
            if count == 0:
                return 0

            self._record_snapshot()
            self._state.clear()
            self._global_version += 1
            self._schedule_persist()

        if self._event_bus:
            await self._event_bus.publish(Event(
                topic="state.cleared",
                data={"count": count, "version": self._global_version},
                source=source or "state_manager",
            ))

        _audit_nicky(
            "INFO",
            "State cleared",
            count=count,
            version=self._global_version,
            source=source,
        )
        return count

    # -- Rollback ------------------------------------------------------------

    async def rollback(self, steps: int = 1, *, source: str = "") -> bool:
        """Rollback state by N historical snapshots.

        Args:
            steps: Number of snapshots to roll back. Must be >= 1.

        Returns:
            True if rollback succeeded, False if insufficient history.
        """
        if steps < 1:
            _audit_nicky("WARN", "Rollback with invalid steps", steps=steps)
            return False

        async with self._lock:
            if len(self._history) < steps + 1:
                # +1 because the current state is also in history
                _audit_nicky(
                    "WARN",
                    "Insufficient history for rollback",
                    requested=steps,
                    available=len(self._history) - 1,
                )
                return False

            # The target snapshot is (current_index - steps)
            target_index = len(self._history) - 1 - steps
            target = self._history[target_index]

            # Rebuild state from snapshot
            new_state: dict[str, StateValue] = {}
            for key, sv_dict in target.data.items():
                new_state[key] = StateValue.from_dict(sv_dict)

            self._state = new_state
            self._global_version += 1
            self._record_snapshot()
            self._schedule_persist()

        # Publish rollback event
        if self._event_bus:
            await self._event_bus.publish(Event(
                topic="state.rollback",
                data={
                    "steps": steps,
                    "target_version": target.version,
                    "new_version": self._global_version,
                },
                source=source or "state_manager",
            ))

        _audit_nicky(
            "INFO",
            "State rolled back",
            steps=steps,
            target_version=target.version,
            new_version=self._global_version,
        )
        return True

    async def rollback_to_version(
        self,
        target_version: int,
        *,
        source: str = "",
    ) -> bool:
        """Rollback to a specific version number.

        Finds the closest snapshot <= target_version and restores it.

        Returns True if rollback succeeded, False if version not found.
        """
        async with self._lock:
            # Find the snapshot with version <= target_version
            target_snapshot: Optional[StateSnapshot] = None
            for snap in self._history:
                if snap.version <= target_version:
                    target_snapshot = snap

            if target_snapshot is None:
                _audit_nicky(
                    "WARN",
                    "Version not found in history",
                    target_version=target_version,
                )
                return False

            # Rebuild state from snapshot
            new_state: dict[str, StateValue] = {}
            for key, sv_dict in target_snapshot.data.items():
                new_state[key] = StateValue.from_dict(sv_dict)

            self._state = new_state
            self._global_version += 1
            self._record_snapshot()
            self._schedule_persist()

        if self._event_bus:
            await self._event_bus.publish(Event(
                topic="state.rollback",
                data={
                    "target_version": target_version,
                    "restored_version": target_snapshot.version,
                    "new_version": self._global_version,
                },
                source=source or "state_manager",
            ))

        _audit_nicky(
            "INFO",
            "State rolled back to version",
            target_version=target_version,
            restored_version=target_snapshot.version,
        )
        return True

    # -- Watchers ------------------------------------------------------------

    def watch(
        self,
        pattern: str,
        handler: WatcherHandler,
    ) -> Watcher:
        """Register a watcher for state changes matching a key pattern.

        Handler signature:
            async def on_change(key: str, old_value: Any, new_value: Any) -> None

        Args:
            pattern: Dot-separated key pattern (supports * and ** wildcards).
            handler: Sync or async callable.

        Returns:
            The Watcher registration (for unwatch).
        """
        name = getattr(handler, "__qualname__", getattr(handler, "__name__", "anonymous"))
        w = Watcher(pattern=pattern, handler=handler, handler_name=name)
        self._watchers.append(w)
        _audit_nicky(
            "INFO",
            f"Watcher registered: {name}",
            pattern=pattern,
        )
        return w

    def unwatch(self, watcher: Watcher) -> None:
        """Remove a watcher."""
        watcher.active = False
        if watcher in self._watchers:
            self._watchers.remove(watcher)

    async def _notify_watchers(
        self,
        key: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Notify all matching watchers of a state change."""
        for w in self._watchers:
            if not w.active:
                continue
            if self._key_matches_pattern(key, w.pattern):
                try:
                    result = w.handler(key, old_value, new_value)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    _audit_nicky(
                        "WARN",
                        f"Watcher error",
                        handler=w.handler_name,
                        key=key,
                        error=type(exc).__name__,
                    )

    @staticmethod
    def _key_matches_pattern(key: str, pattern: str) -> bool:
        """Check if a key matches a watcher pattern (same logic as Event.matches)."""
        key_parts = key.split(".")
        pattern_parts = pattern.split(".")

        ei, pi = 0, 0
        while ei < len(key_parts) and pi < len(pattern_parts):
            if pattern_parts[pi] == "**":
                return True
            if pattern_parts[pi] == "*":
                ei += 1
                pi += 1
            elif pattern_parts[pi] == key_parts[ei]:
                ei += 1
                pi += 1
            else:
                return False

        return ei == len(key_parts) and pi == len(pattern_parts)

    # -- Snapshots & History -------------------------------------------------

    def _record_snapshot(self) -> None:
        """Record current state as a snapshot (called under lock)."""
        data: dict[str, Any] = {}
        for key, sv in self._state.items():
            data[key] = sv.to_dict()

        snap = StateSnapshot(
            version=self._global_version,
            ts=time.time(),
            data=data,
        )
        self._history.append(snap)

        # Trim history
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    @property
    def history(self) -> list[StateSnapshot]:
        return list(self._history)

    def history_length(self) -> int:
        return len(self._history)

    # -- Export / Import ------------------------------------------------------

    async def export_state(self) -> dict[str, Any]:
        """Export the current state as a serializable dictionary."""
        return {
            "global_version": self._global_version,
            "keys": {
                key: sv.to_dict()
                for key, sv in sorted(self._state.items())
            },
        }

    async def import_state(
        self,
        data: dict[str, Any],
        *,
        source: str = "",
    ) -> int:
        """Import state from a dictionary. Returns number of keys imported.

        Merges into existing state (overwrites existing keys).
        """
        count = 0
        keys_data = data.get("keys", {})
        for key, sv_dict in keys_data.items():
            await self.set(key, sv_dict["value"], source=source or "import")
            count += 1

        _audit_nicky(
            "INFO",
            "State imported",
            count=count,
            source=source,
        )
        return count

    # -- Disk Persistence ----------------------------------------------------

    def _schedule_persist(self) -> None:
        """Schedule a debounced disk write."""
        self._persist_dirty = True
        if self._persist_path is None:
            return
        if self._persist_task is not None and not self._persist_task.cancelled():
            return  # already scheduled
        self._persist_task = asyncio.get_event_loop().call_later(
            PERSIST_DEBOUNCE,
            lambda: asyncio.ensure_future(self._persist_now()),
        )  # type: ignore[assignment]

    async def _persist_now(self) -> None:
        """Immediately persist state to disk."""
        if not self._persist_dirty or not self._persist_path:
            return
        await self._save_to_disk()
        self._persist_dirty = False

    async def _save_to_disk(self) -> None:
        """Write current state to disk as JSON."""
        if not self._persist_path:
            return

        data = await self.export_state()
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            # Write atomically via temp file
            tmp_path = self._persist_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._persist_path)
            _audit_nicky(
                "INFO",
                "State persisted to disk",
                path=str(self._persist_path),
                keys=len(data.get("keys", {})),
            )
        except Exception as exc:
            _audit_nicky(
                "CRIT",
                "State persist failed",
                error=type(exc).__name__,
                message=str(exc),
            )

    async def _load_from_disk(self) -> None:
        """Load state from disk."""
        if not self._persist_path or not self._persist_path.exists():
            return

        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as exc:
            _audit_nicky(
                "WARN",
                "State load failed",
                error=type(exc).__name__,
                message=str(exc),
            )
            return

        self._global_version = data.get("global_version", 0)
        for key, sv_dict in data.get("keys", {}).items():
            self._state[key] = StateValue.from_dict(sv_dict)

        self._record_snapshot()

        _audit_nicky(
            "INFO",
            "State loaded from disk",
            path=str(self._persist_path),
            keys=len(self._state),
            global_version=self._global_version,
        )

    # -- Inspection ----------------------------------------------------------

    async def dump(self) -> dict[str, Any]:
        """Return a full diagnostic dump of the state manager."""
        return {
            "running": self._running,
            "global_version": self._global_version,
            "key_count": len(self._state),
            "history_length": len(self._history),
            "watcher_count": len([w for w in self._watchers if w.active]),
            "persist_path": str(self._persist_path) if self._persist_path else None,
            "state": {
                key: sv.to_dict()
                for key, sv in sorted(self._state.items())
            },
        }
