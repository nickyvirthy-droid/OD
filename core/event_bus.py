#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Module: event_bus
Description: Central event bus — backbone of OmegaDrakon architecture.
             Publish/subscribe with typed events, wildcard routing, priorities,
             dead-letter queue, metrics, and structured audit logging.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Architecture:
    This module is the primary communication mechanism between OmegaDrakon
    components. It enforces strict separation between orchestration (thinking)
    and execution (action) by routing structured intents through a validation
    layer before any handler executes.

    Every component publishes and subscribes through this bus. No direct
    coupling between components.

Protocol:
    All events carry a topic (dot-separated path), a timestamp, a UUID,
    and an optional priority. Handlers are invoked in priority order.
    Failed handlers are routed to the dead-letter queue for inspection.

Usage:
    from core.event_bus import EventBus, Event, HandlerError

    bus = EventBus()

    @bus.subscribe("system.startup")
    async def on_startup(event: Event) -> None:
        print(f"System started: {event.data}")

    await bus.publish(Event(topic="system.startup", data={"version": "0.2.0"}))
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Coroutine, Optional, Union

logger = logging.getLogger("omega.core.event_bus")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 0.1  # seconds
MAX_METRICS_WINDOW = 1000  # retain last N metric snapshots
NICKY_PREFIX = "[NICKY][{level}]"


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------

class Priority(IntEnum):
    """Event priority — lower value = higher priority."""
    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 90
    BACKGROUND = 100


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Event:
    """Immutable, typed event that flows through the bus.

    Attributes:
        topic:    Dot-separated routing path (e.g. "system.startup").
        data:     Arbitrary payload dictionary.
        priority: Execution priority — lower number runs first.
        source:   Identifier of the originating component.
        event_id: Unique UUID (auto-generated).
        ts:       Unix timestamp of creation (auto-set).
        ttl:      Time-to-live in seconds. 0 = no expiry.
    """
    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    source: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)
    ttl: float = 0.0

    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return (time.time() - self.ts) > self.ttl

    def matches(self, pattern: str) -> bool:
        """Check if this event matches a subscription pattern.

        Supports:
            - Exact match:    "system.startup"
            - Single wildcard: "system.*"  (one level)
            - Multi wildcard:  "system.**" (one or more levels)
        """
        event_parts = self.topic.split(".")
        pattern_parts = pattern.split(".")

        ei, pi = 0, 0
        while ei < len(event_parts) and pi < len(pattern_parts):
            if pattern_parts[pi] == "**":
                # ** matches zero or more remaining levels
                return True
            if pattern_parts[pi] == "*":
                # * matches exactly one level
                ei += 1
                pi += 1
            elif pattern_parts[pi] == event_parts[ei]:
                ei += 1
                pi += 1
            else:
                return False

        return ei == len(event_parts) and pi == len(pattern_parts)


# ---------------------------------------------------------------------------
# Dead Letter
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DeadLetter:
    """A failed event + handler info, stored for inspection."""
    event: Event
    handler_name: str
    error: Exception
    attempts: int
    ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Handler wrapper
# ---------------------------------------------------------------------------

# Handler can be sync or async
SyncHandler = Callable[[Event], None]
AsyncHandler = Callable[[Event], Coroutine[Any, Any, None]]
Handler = Union[SyncHandler, AsyncHandler]


@dataclass(slots=True)
class Subscription:
    """Internal record of a subscription."""
    pattern: str
    handler: Handler
    handler_name: str
    priority: Priority
    max_retries: int
    retry_delay: float
    active: bool = True


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BusMetrics:
    """Rolling metrics for the event bus."""
    published: int = 0
    delivered: int = 0
    failed: int = 0
    dropped: int = 0  # expired TTL or no subscribers
    dead_letters: int = 0
    handler_count: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "published": self.published,
            "delivered": self.delivered,
            "failed": self.failed,
            "dropped": self.dropped,
            "dead_letters": self.dead_letters,
            "handler_count": self.handler_count,
        }


# ---------------------------------------------------------------------------
# Audit Logger (NICKY Protocol)
# ---------------------------------------------------------------------------

def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    """Structured audit log following the NICKY protocol.

    Levels: INFO, WARN, CRIT
    """
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class EventBus:
    """Central publish/subscribe event bus for OmegaDrakon.

    Thread-safe (asyncio-compatible). All operations are awaitable.
    Handlers are invoked in priority order (lower = first).

    Attributes:
        metrics:      Live metrics counters.
        dead_letters: List of failed event deliveries.
    """

    def __init__(self, *, max_dead_letters: int = 256) -> None:
        self._subscriptions: list[Subscription] = []
        self._lock = asyncio.Lock()
        self.metrics = BusMetrics()
        self._max_dead_letters = max_dead_letters
        self._dead_letters: list[DeadLetter] = []
        self._running = False

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Mark the bus as operational."""
        if self._running:
            _audit_nicky("WARN", "EventBus already running")
            return
        self._running = True
        _audit_nicky("INFO", "EventBus started", subscriptions=len(self._subscriptions))

    async def stop(self) -> None:
        """Gracefully stop the bus and clear active subscriptions."""
        if not self._running:
            return
        self._running = False
        async with self._lock:
            count = len(self._subscriptions)
            self._subscriptions.clear()
        _audit_nicky("INFO", "EventBus stopped", cleared_handlers=count)

    # -- Subscription --------------------------------------------------------

    def subscribe(
        self,
        pattern: str,
        *,
        priority: Priority = Priority.NORMAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> Callable[[Handler], Handler]:
        """Decorator to subscribe a handler to a topic pattern.

        Can be used as a regular method too:
            bus.subscribe("topic", handler=my_func)

        Supports:
            - Exact:    "system.startup"
            - Single *: "system.*"
            - Multi **: "system.**"
        """
        def decorator(func: Handler) -> Handler:
            name = getattr(func, "__qualname__", getattr(func, "__name__", "anonymous"))
            sub = Subscription(
                pattern=pattern,
                handler=func,
                handler_name=name,
                priority=priority,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            self._subscriptions.append(sub)
            self.metrics.handler_count = len(
                [s for s in self._subscriptions if s.active]
            )
            _audit_nicky(
                "INFO",
                f"Handler registered: {name}",
                pattern=pattern,
                priority=int(priority),
            )
            return func

        return decorator

    def subscribe_handler(
        self,
        pattern: str,
        handler: Handler,
        *,
        priority: Priority = Priority.NORMAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> Subscription:
        """Programmatic subscription (non-decorator). Returns the Subscription."""
        name = getattr(handler, "__qualname__", getattr(handler, "__name__", "anonymous"))
        sub = Subscription(
            pattern=pattern,
            handler=handler,
            handler_name=name,
            priority=priority,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        self._subscriptions.append(sub)
        self.metrics.handler_count = len(
            [s for s in self._subscriptions if s.active]
        )
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        """Remove a subscription by reference."""
        subscription.active = False
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)
        self.metrics.handler_count = len(
            [s for s in self._subscriptions if s.active]
        )

    # -- Publishing ----------------------------------------------------------

    async def publish(self, event: Event) -> int:
        """Publish an event to all matching subscribers.

        Returns:
            Number of handlers successfully invoked.
        """
        self.metrics.published += 1

        # TTL check
        if event.is_expired():
            self.metrics.dropped += 1
            _audit_nicky(
                "WARN",
                "Event dropped (expired TTL)",
                event_id=event.event_id,
                topic=event.topic,
            )
            return 0

        # Find matching subscriptions
        matching = self._find_matching(event)

        if not matching:
            self.metrics.dropped += 1
            _audit_nicky(
                "INFO",
                "Event published (no subscribers)",
                event_id=event.event_id,
                topic=event.topic,
            )
            return 0

        _audit_nicky(
            "INFO",
            "Event published",
            event_id=event.event_id,
            topic=event.topic,
            subscribers=len(matching),
        )

        delivered = 0
        for sub in matching:
            success = await self._invoke_handler(event, sub)
            if success:
                delivered += 1

        self.metrics.delivered += delivered
        return delivered

    def _find_matching(self, event: Event) -> list[Subscription]:
        """Find all active subscriptions matching this event, sorted by priority."""
        matches = [
            sub for sub in self._subscriptions
            if sub.active and event.matches(sub.pattern)
        ]
        matches.sort(key=lambda s: s.priority)
        return matches

    async def _invoke_handler(self, event: Event, sub: Subscription) -> bool:
        """Invoke a handler with retry logic and dead-letter routing."""
        last_error: Optional[Exception] = None

        for attempt in range(1, sub.max_retries + 1):
            try:
                result = sub.handler(event)
                if asyncio.iscoroutine(result):
                    await result
                return True
            except Exception as exc:
                last_error = exc
                _audit_nicky(
                    "WARN",
                    f"Handler error (attempt {attempt}/{sub.max_retries})",
                    handler=sub.handler_name,
                    event_id=event.event_id,
                    error=type(exc).__name__,
                )
                if attempt < sub.max_retries and sub.retry_delay > 0:
                    await asyncio.sleep(sub.retry_delay)

        # All retries exhausted → dead letter
        self.metrics.failed += 1
        self._add_dead_letter(
            DeadLetter(
                event=event,
                handler_name=sub.handler_name,
                error=last_error,  # type: ignore[arg-type]
                attempts=sub.max_retries,
            )
        )
        _audit_nicky(
            "CRIT",
            "Handler failed — dead letter",
            handler=sub.handler_name,
            event_id=event.event_id,
            topic=event.topic,
            attempts=sub.max_retries,
        )
        return False

    # -- Dead Letters --------------------------------------------------------

    def _add_dead_letter(self, letter: DeadLetter) -> None:
        self._dead_letters.append(letter)
        self.metrics.dead_letters = len(self._dead_letters)
        # Trim if over limit
        if len(self._dead_letters) > self._max_dead_letters:
            self._dead_letters = self._dead_letters[-self._max_dead_letters:]
            self.metrics.dead_letters = len(self._dead_letters)

    @property
    def dead_letters(self) -> list[DeadLetter]:
        return list(self._dead_letters)

    def clear_dead_letters(self) -> int:
        """Clear the dead letter queue. Returns count cleared."""
        count = len(self._dead_letters)
        self._dead_letters.clear()
        self.metrics.dead_letters = 0
        return count

    # -- Inspection ----------------------------------------------------------

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """Return a snapshot of all active subscriptions."""
        return [
            {
                "pattern": sub.pattern,
                "handler": sub.handler_name,
                "priority": int(sub.priority),
                "active": sub.active,
                "max_retries": sub.max_retries,
            }
            for sub in self._subscriptions
        ]

    def reset_metrics(self) -> None:
        """Reset all metrics counters."""
        self.metrics = BusMetrics()
        self.metrics.handler_count = len(
            [s for s in self._subscriptions if s.active]
        )
