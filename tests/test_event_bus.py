#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_event_bus
Description: Unit tests for core/event_bus.py — the central event bus.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import (
    BusMetrics,
    DeadLetter,
    EventBus,
    Event,
    Priority,
    Subscription,
)


# ===========================================================================
# Event — immutable event model
# ===========================================================================

class TestEvent:
    """Tests for the Event dataclass."""

    def test_creation_with_defaults(self) -> None:
        event = Event(topic="test.event")
        assert event.topic == "test.event"
        assert event.data == {}
        assert event.priority == Priority.NORMAL
        assert event.source == ""
        assert len(event.event_id) == 12
        assert event.ttl == 0.0
        assert isinstance(event.ts, float)

    def test_immutable(self) -> None:
        event = Event(topic="test")
        with pytest.raises(AttributeError):
            event.topic = "changed"  # type: ignore[misc]

    def test_creation_with_custom_values(self) -> None:
        event = Event(
            topic="custom.topic",
            data={"key": "value"},
            priority=Priority.HIGH,
            source="test-component",
            event_id="abc123",
            ts=1000.0,
            ttl=60.0,
        )
        assert event.topic == "custom.topic"
        assert event.data == {"key": "value"}
        assert event.priority == Priority.HIGH
        assert event.source == "test-component"
        assert event.event_id == "abc123"
        assert event.ts == 1000.0
        assert event.ttl == 60.0

    def test_is_expired_no_ttl(self) -> None:
        event = Event(topic="test", ttl=0.0)
        assert not event.is_expired()

    def test_is_expired_not_yet(self) -> None:
        event = Event(topic="test", ts=time.time(), ttl=60.0)
        assert not event.is_expired()

    def test_is_expired_yes(self) -> None:
        event = Event(topic="test", ts=time.time() - 120.0, ttl=60.0)
        assert event.is_expired()


# ===========================================================================
# Event.matches — wildcard topic routing
# ===========================================================================

class TestEventMatches:
    """Tests for topic pattern matching."""

    def test_exact_match(self) -> None:
        event = Event(topic="system.startup")
        assert event.matches("system.startup")

    def test_exact_no_match(self) -> None:
        event = Event(topic="system.startup")
        assert not event.matches("system.shutdown")

    def test_single_wildcard(self) -> None:
        event = Event(topic="system.startup")
        assert event.matches("system.*")

    def test_single_wildcard_no_match_wrong_level(self) -> None:
        event = Event(topic="system.sub.startup")
        assert not event.matches("system.*")

    def test_single_wildcard_deep_event(self) -> None:
        event = Event(topic="system.sub.startup")
        assert event.matches("system.sub.*")

    def test_multi_wildcard(self) -> None:
        event = Event(topic="system.sub.startup")
        assert event.matches("system.**")

    def test_multi_wildcard_single_level(self) -> None:
        event = Event(topic="system.startup")
        assert event.matches("system.**")

    def test_multi_wildcard_at_end(self) -> None:
        event = Event(topic="a.b.c.d")
        assert event.matches("a.b.**")

    def test_wildcard_no_match(self) -> None:
        event = Event(topic="other.startup")
        assert not event.matches("system.**")

    def test_leading_wildcard(self) -> None:
        event = Event(topic="a.b.c")
        assert event.matches("**.c")

    def test_single_level_only(self) -> None:
        event = Event(topic="a")
        assert event.matches("*")

    def test_empty_pattern(self) -> None:
        event = Event(topic="")
        assert event.matches("")

    def test_complex_pattern(self) -> None:
        event = Event(topic="core.event.published")
        assert event.matches("core.event.*")
        assert event.matches("core.**")
        assert event.matches("core.event.published")
        assert not event.matches("core.event.*.*")


# ===========================================================================
# Priority
# ===========================================================================

class TestPriority:
    """Tests for the Priority enum."""

    def test_ordering(self) -> None:
        assert Priority.CRITICAL < Priority.HIGH < Priority.NORMAL < Priority.LOW < Priority.BACKGROUND

    def test_values(self) -> None:
        assert Priority.CRITICAL == 0
        assert Priority.HIGH == 10
        assert Priority.NORMAL == 50
        assert Priority.LOW == 90
        assert Priority.BACKGROUND == 100


# ===========================================================================
# BusMetrics
# ===========================================================================

class TestBusMetrics:
    """Tests for BusMetrics dataclass."""

    def test_defaults(self) -> None:
        m = BusMetrics()
        assert m.published == 0
        assert m.delivered == 0
        assert m.failed == 0
        assert m.dropped == 0
        assert m.dead_letters == 0
        assert m.handler_count == 0

    def test_snapshot(self) -> None:
        m = BusMetrics(published=5, delivered=3, failed=1)
        snap = m.snapshot()
        assert snap["published"] == 5
        assert snap["delivered"] == 3
        assert snap["failed"] == 1
        assert snap["dropped"] == 0


# ===========================================================================
# DeadLetter
# ===========================================================================

class TestDeadLetter:
    """Tests for DeadLetter dataclass."""

    def test_creation(self) -> None:
        event = Event(topic="test")
        error = ValueError("boom")
        letter = DeadLetter(
            event=event,
            handler_name="my_handler",
            error=error,
            attempts=3,
        )
        assert letter.event is event
        assert letter.handler_name == "my_handler"
        assert letter.error is error
        assert letter.attempts == 3
        assert isinstance(letter.ts, float)


# ===========================================================================
# EventBus — lifecycle
# ===========================================================================

class TestEventBusLifecycle:
    """Tests for EventBus start/stop."""

    def test_initial_state(self) -> None:
        bus = EventBus()
        assert not bus.running
        assert bus.metrics.handler_count == 0
        assert bus.dead_letters == []

    @pytest.mark.asyncio
    async def test_start(self) -> None:
        bus = EventBus()
        await bus.start()
        assert bus.running

    @pytest.mark.asyncio
    async def test_start_already_running(self) -> None:
        bus = EventBus()
        await bus.start()
        await bus.start()  # should warn, not crash
        assert bus.running

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        bus = EventBus()
        await bus.start()
        await bus.stop()
        assert not bus.running

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        bus = EventBus()
        await bus.stop()  # no-op
        assert not bus.running


# ===========================================================================
# EventBus — subscription
# ===========================================================================

class TestEventBusSubscription:
    """Tests for subscribing handlers."""

    def test_subscribe_decorator(self) -> None:
        bus = EventBus()

        @bus.subscribe("test.event")
        async def handler(e: Event) -> None:
            pass

        assert len(bus._subscriptions) == 1
        assert bus._subscriptions[0].pattern == "test.event"
        assert bus._subscriptions[0].handler_name.endswith("handler")

    def test_subscribe_programmatic(self) -> None:
        bus = EventBus()

        async def handler(e: Event) -> None:
            pass

        sub = bus.subscribe_handler("test.event", handler)
        assert isinstance(sub, Subscription)
        assert sub.pattern == "test.event"
        assert sub.active is True
        assert len(bus._subscriptions) == 1

    def test_subscribe_with_priority(self) -> None:
        bus = EventBus()

        async def handler(e: Event) -> None:
            pass

        bus.subscribe_handler("test.event", handler, priority=Priority.HIGH)
        assert bus._subscriptions[0].priority == Priority.HIGH

    def test_unsubscribe(self) -> None:
        bus = EventBus()

        async def handler(e: Event) -> None:
            pass

        sub = bus.subscribe_handler("test.event", handler)
        assert bus.metrics.handler_count == 1
        bus.unsubscribe(sub)
        assert bus.metrics.handler_count == 0
        assert sub.active is False

    def test_list_subscriptions(self) -> None:
        bus = EventBus()

        async def handler(e: Event) -> None:
            pass

        bus.subscribe_handler("test.event", handler, priority=Priority.HIGH)
        listing = bus.list_subscriptions()
        assert len(listing) == 1
        assert listing[0]["pattern"] == "test.event"
        assert listing[0]["priority"] == Priority.HIGH


# ===========================================================================
# EventBus — publishing
# ===========================================================================

@pytest.mark.asyncio
class TestEventBusPublishing:
    """Tests for event publishing and delivery."""

    async def test_publish_no_subscribers(self) -> None:
        bus = EventBus()
        await bus.start()
        event = Event(topic="test.no.subs")
        delivered = await bus.publish(event)
        assert delivered == 0
        assert bus.metrics.dropped == 1
        assert bus.metrics.published == 1

    async def test_publish_with_subscriber(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("test.event", handler)
        event = Event(topic="test.event", data={"msg": "hello"})
        delivered = await bus.publish(event)

        assert delivered == 1
        assert len(received) == 1
        assert received[0].data == {"msg": "hello"}
        assert bus.metrics.delivered == 1

    async def test_publish_multiple_subscribers(self) -> None:
        bus = EventBus()
        await bus.start()
        received_a: list[Event] = []
        received_b: list[Event] = []

        async def handler_a(e: Event) -> None:
            received_a.append(e)

        async def handler_b(e: Event) -> None:
            received_b.append(e)

        bus.subscribe_handler("test.event", handler_a)
        bus.subscribe_handler("test.event", handler_b)
        await bus.publish(Event(topic="test.event"))

        assert len(received_a) == 1
        assert len(received_b) == 1

    async def test_publish_wildcard_match(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("system.*", handler)
        await bus.publish(Event(topic="system.startup"))

        assert len(received) == 1

    async def test_publish_wildcard_no_match(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("system.*", handler)
        await bus.publish(Event(topic="other.startup"))

        assert len(received) == 0

    async def test_publish_priority_ordering(self) -> None:
        bus = EventBus()
        await bus.start()
        order: list[str] = []

        async def handler_low(e: Event) -> None:
            order.append("low")

        async def handler_high(e: Event) -> None:
            order.append("high")

        async def handler_normal(e: Event) -> None:
            order.append("normal")

        # Subscribe in reverse priority order
        bus.subscribe_handler("test.event", handler_low, priority=Priority.LOW)
        bus.subscribe_handler("test.event", handler_high, priority=Priority.HIGH)
        bus.subscribe_handler("test.event", handler_normal, priority=Priority.NORMAL)

        await bus.publish(Event(topic="test.event"))

        assert order == ["high", "normal", "low"]

    async def test_publish_expired_event(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("test.event", handler)
        event = Event(topic="test.event", ts=time.time() - 120.0, ttl=60.0)
        delivered = await bus.publish(event)

        assert delivered == 0
        assert len(received) == 0
        assert bus.metrics.dropped == 1

    async def test_sync_handler(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Event] = []

        def sync_handler(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("test.sync", sync_handler)
        await bus.publish(Event(topic="test.sync"))

        assert len(received) == 1

    async def test_unsubscribed_handler_not_called(self) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        sub = bus.subscribe_handler("test.event", handler)
        bus.unsubscribe(sub)
        await bus.publish(Event(topic="test.event"))

        assert len(received) == 0


# ===========================================================================
# EventBus — retries and dead letters
# ===========================================================================

@pytest.mark.asyncio
class TestEventBusRetries:
    """Tests for handler retry logic and dead letter queue."""

    async def test_handler_retries_on_failure(self) -> None:
        bus = EventBus()
        await bus.start()
        call_count = 0

        async def failing_handler(e: Event) -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("transient error")

        bus.subscribe_handler(
            "test.event", failing_handler,
            max_retries=3, retry_delay=0.0,
        )
        await bus.publish(Event(topic="test.event"))

        assert call_count == 3
        assert bus.metrics.failed == 1
        assert len(bus.dead_letters) == 1

    async def test_handler_succeeds_on_retry(self) -> None:
        bus = EventBus()
        await bus.start()
        call_count = 0

        async def flaky_handler(e: Event) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("first call fails")

        bus.subscribe_handler(
            "test.event", flaky_handler,
            max_retries=3, retry_delay=0.0,
        )
        await bus.publish(Event(topic="test.event"))

        assert call_count == 2
        assert bus.metrics.failed == 0
        assert len(bus.dead_letters) == 0

    async def test_dead_letter_queue_limit(self) -> None:
        bus = EventBus(max_dead_letters=3)
        await bus.start()

        async def always_fails(e: Event) -> None:
            raise RuntimeError("always fails")

        bus.subscribe_handler("test.event", always_fails, max_retries=1, retry_delay=0.0)

        for _ in range(5):
            await bus.publish(Event(topic="test.event"))

        assert len(bus.dead_letters) == 3
        assert bus.metrics.dead_letters == 3

    async def test_clear_dead_letters(self) -> None:
        bus = EventBus()
        await bus.start()

        async def always_fails(e: Event) -> None:
            raise RuntimeError("fail")

        bus.subscribe_handler("test.event", always_fails, max_retries=1, retry_delay=0.0)
        await bus.publish(Event(topic="test.event"))

        assert len(bus.dead_letters) == 1
        cleared = bus.clear_dead_letters()
        assert cleared == 1
        assert len(bus.dead_letters) == 0

    async def test_dead_letter_contains_event(self) -> None:
        bus = EventBus()
        await bus.start()

        async def always_fails(e: Event) -> None:
            raise RuntimeError("fail")

        bus.subscribe_handler("test.event", always_fails, max_retries=1, retry_delay=0.0)
        event = Event(topic="test.event", data={"x": 1})
        await bus.publish(event)

        letter = bus.dead_letters[0]
        assert letter.event.event_id == event.event_id
        assert letter.handler_name.endswith("always_fails")
        assert isinstance(letter.error, RuntimeError)
        assert letter.attempts == 1


# ===========================================================================
# EventBus — metrics
# ===========================================================================

class TestEventBusMetrics:
    """Tests for metrics tracking."""

    def test_reset_metrics(self) -> None:
        bus = EventBus()
        bus.metrics.published = 10
        bus.metrics.delivered = 8
        bus.reset_metrics()
        assert bus.metrics.published == 0
        assert bus.metrics.delivered == 0


@pytest.mark.asyncio
class TestEventBusMetricsAsync:
    """Async tests for metrics tracking."""

    async def test_metrics_publish_and_deliver(self) -> None:
        bus = EventBus()
        await bus.start()

        async def handler(e: Event) -> None:
            pass

        bus.subscribe_handler("test.event", handler)
        await bus.publish(Event(topic="test.event"))

        assert bus.metrics.published == 1
        assert bus.metrics.delivered == 1
        assert bus.metrics.dropped == 0
        assert bus.metrics.failed == 0

    async def test_metrics_no_subscribers(self) -> None:
        bus = EventBus()
        await bus.start()
        await bus.publish(Event(topic="no.subs"))

        assert bus.metrics.published == 1
        assert bus.metrics.dropped == 1
        assert bus.metrics.delivered == 0

    async def test_metrics_after_failure(self) -> None:
        bus = EventBus()
        await bus.start()

        async def always_fails(e: Event) -> None:
            raise RuntimeError("fail")

        bus.subscribe_handler("test.event", always_fails, max_retries=1, retry_delay=0.0)
        await bus.publish(Event(topic="test.event"))

        assert bus.metrics.failed == 1
        assert bus.metrics.delivered == 0


# ===========================================================================
# EventBus — integration-style test
# ===========================================================================

@pytest.mark.asyncio
class TestEventBusIntegration:
    """Integration tests simulating real OmegaDrakon usage patterns."""

    async def test_multi_topic_isolation(self) -> None:
        """Different topics don't cross-talk."""
        bus = EventBus()
        await bus.start()
        startup_received: list[Event] = []
        shutdown_received: list[Event] = []

        async def on_startup(e: Event) -> None:
            startup_received.append(e)

        async def on_shutdown(e: Event) -> None:
            shutdown_received.append(e)

        bus.subscribe_handler("system.startup", on_startup)
        bus.subscribe_handler("system.shutdown", on_shutdown)

        await bus.publish(Event(topic="system.startup"))
        await bus.publish(Event(topic="system.shutdown"))

        assert len(startup_received) == 1
        assert len(shutdown_received) == 1
        assert startup_received[0].topic == "system.startup"
        assert shutdown_received[0].topic == "system.shutdown"

    async def test_event_carrying_data(self) -> None:
        """Events carry structured data between components."""
        bus = EventBus()
        await bus.start()
        results: list[dict] = []

        async def processor(e: Event) -> None:
            results.append(e.data)

        bus.subscribe_handler("data.process", processor)

        event = Event(
            topic="data.process",
            data={"items": [1, 2, 3], "action": "sum"},
        )
        await bus.publish(event)

        assert results[0]["items"] == [1, 2, 3]
        assert results[0]["action"] == "sum"

    async def test_cascade_events(self) -> None:
        """Handler publishes another event (cascade)."""
        bus = EventBus()
        await bus.start()
        cascade_received: list[str] = []

        async def trigger(e: Event) -> None:
            await bus.publish(Event(topic="cascade.step2"))

        async def final(e: Event) -> None:
            cascade_received.append("done")

        bus.subscribe_handler("cascade.step1", trigger)
        bus.subscribe_handler("cascade.step2", final)

        await bus.publish(Event(topic="cascade.step1"))
        assert cascade_received == ["done"]

    async def test_component_lifecycle_pattern(self) -> None:
        """Simulate start → operate → stop lifecycle."""
        bus = EventBus()
        lifecycle: list[str] = []

        async def on_startup(e: Event) -> None:
            lifecycle.append("started")

        async def on_work(e: Event) -> None:
            lifecycle.append("working")

        async def on_shutdown(e: Event) -> None:
            lifecycle.append("stopped")

        bus.subscribe_handler("system.startup", on_startup)
        bus.subscribe_handler("task.execute", on_work)
        bus.subscribe_handler("system.shutdown", on_shutdown)

        await bus.start()
        await bus.publish(Event(topic="system.startup"))
        await bus.publish(Event(topic="task.execute", data={"task": "build"}))
        await bus.publish(Event(topic="system.shutdown"))
        await bus.stop()

        assert lifecycle == ["started", "working", "stopped"]
        assert not bus.running
