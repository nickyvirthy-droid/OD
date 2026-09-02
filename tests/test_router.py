#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_router
Description: Unit tests for core/router.py — inter-component message router.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio

import pytest

from core.event_bus import EventBus
from core.router import (
    DeadLetter,
    Endpoint,
    Message,
    MessagePriority,
    MessageReply,
    MessageRouter,
    PendingRequest,
    RouterMetrics,
)


# ===========================================================================
# Message
# ===========================================================================

class TestMessage:
    """Tests for the Message dataclass."""

    def test_creation_with_defaults(self) -> None:
        msg = Message(source="a", destination="b", action="ping")
        assert msg.source == "a"
        assert msg.destination == "b"
        assert msg.action == "ping"
        assert msg.payload == {}
        assert msg.priority == MessagePriority.NORMAL
        assert len(msg.msg_id) == 12
        assert isinstance(msg.ts, float)
        assert msg.reply_to is None
        assert msg.timeout == 0.0
        assert msg.metadata == {}

    def test_immutable(self) -> None:
        msg = Message(source="a", destination="b", action="ping")
        with pytest.raises(AttributeError):
            msg.action = "changed"  # type: ignore[misc]

    def test_creation_with_options(self) -> None:
        msg = Message(
            source="nicky",
            destination="bridge",
            action="health",
            payload={"check": True},
            priority=MessagePriority.HIGH,
            msg_id="abc123",
            reply_to="xyz789",
            timeout=10.0,
            metadata={"trace": "abc"},
        )
        assert msg.source == "nicky"
        assert msg.destination == "bridge"
        assert msg.action == "health"
        assert msg.payload == {"check": True}
        assert msg.priority == MessagePriority.HIGH
        assert msg.msg_id == "abc123"
        assert msg.reply_to == "xyz789"
        assert msg.timeout == 10.0
        assert msg.metadata == {"trace": "abc"}


# ===========================================================================
# MessageReply
# ===========================================================================

class TestMessageReply:
    """Tests for MessageReply dataclass."""

    def test_creation(self) -> None:
        reply = MessageReply(reply_to="msg1", source="bridge", status="ok", data={"result": 42})
        assert reply.reply_to == "msg1"
        assert reply.source == "bridge"
        assert reply.status == "ok"
        assert reply.data == {"result": 42}
        assert reply.error is None
        assert len(reply.msg_id) == 12

    def test_error_reply(self) -> None:
        reply = MessageReply(
            reply_to="msg1", source="bridge", status="error", error="not found"
        )
        assert reply.status == "error"
        assert reply.error == "not found"
        assert reply.data is None

    def test_timeout_reply(self) -> None:
        reply = MessageReply(
            reply_to="msg1", source="bridge", status="timeout", error="Timeout after 5.0s"
        )
        assert reply.status == "timeout"


# ===========================================================================
# MessagePriority
# ===========================================================================

class TestMessagePriority:
    """Tests for MessagePriority enum."""

    def test_ordering(self) -> None:
        assert MessagePriority.CRITICAL < MessagePriority.HIGH < MessagePriority.NORMAL < MessagePriority.LOW

    def test_values(self) -> None:
        assert MessagePriority.CRITICAL == 0
        assert MessagePriority.HIGH == 10
        assert MessagePriority.NORMAL == 50
        assert MessagePriority.LOW == 90


# ===========================================================================
# RouterMetrics
# ===========================================================================

class TestRouterMetrics:
    """Tests for RouterMetrics dataclass."""

    def test_defaults(self) -> None:
        m = RouterMetrics()
        assert m.sent == 0
        assert m.delivered == 0
        assert m.broadcast == 0
        assert m.failed == 0
        assert m.timeout == 0
        assert m.dead_letters == 0

    def test_snapshot(self) -> None:
        m = RouterMetrics(sent=10, delivered=8, failed=2)
        snap = m.snapshot()
        assert snap["sent"] == 10
        assert snap["delivered"] == 8
        assert snap["failed"] == 2


# ===========================================================================
# MessageRouter — lifecycle
# ===========================================================================

class TestMessageRouterLifecycle:
    """Tests for MessageRouter start/stop."""

    def test_initial_state(self) -> None:
        router = MessageRouter()
        assert not router.running
        assert router.metrics.endpoint_count == 0

    @pytest.mark.asyncio
    async def test_start(self) -> None:
        router = MessageRouter()
        await router.start()
        assert router.running

    @pytest.mark.asyncio
    async def test_start_already_running(self) -> None:
        router = MessageRouter()
        await router.start()
        await router.start()  # should warn
        assert router.running

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        router = MessageRouter()
        await router.start()
        await router.stop()
        assert not router.running

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        router = MessageRouter()
        await router.stop()  # no-op
        assert not router.running


# ===========================================================================
# MessageRouter — endpoint registration
# ===========================================================================

class TestEndpointRegistration:
    """Tests for endpoint registration."""

    def test_register_endpoint(self) -> None:
        router = MessageRouter()

        async def handler(msg: Message) -> dict:
            return {"status": "ok"}

        ep = router.register("bridge", handler)
        assert isinstance(ep, Endpoint)
        assert ep.name == "bridge"
        assert ep.active is True
        assert router.has_endpoint("bridge")

    def test_register_multiple(self) -> None:
        router = MessageRouter()

        async def h1(msg: Message) -> None:
            pass

        async def h2(msg: Message) -> None:
            pass

        router.register("bridge", h1)
        router.register("agent", h2)
        assert router.metrics.endpoint_count == 2

    def test_unregister(self) -> None:
        router = MessageRouter()

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        result = router.unregister("bridge")
        assert result is True
        assert not router.has_endpoint("bridge")
        assert router.metrics.endpoint_count == 0

    def test_unregister_nonexistent(self) -> None:
        router = MessageRouter()
        result = router.unregister("nope")
        assert result is False

    def test_has_endpoint(self) -> None:
        router = MessageRouter()
        assert not router.has_endpoint("bridge")

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        assert router.has_endpoint("bridge")

    def test_list_endpoints(self) -> None:
        router = MessageRouter()

        async def h1(msg: Message) -> None:
            pass

        async def h2(msg: Message) -> None:
            pass

        router.register("bridge", h1)
        router.register("agent", h2)
        listing = router.list_endpoints()
        assert len(listing) == 2
        names = {ep["name"] for ep in listing}
        assert names == {"bridge", "agent"}


# ===========================================================================
# MessageRouter — send (fire-and-forget)
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterSend:
    """Tests for fire-and-forget sending."""

    async def test_send_to_endpoint(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        router.register("bridge", handler)
        result = await router.send("bridge", "ping")

        assert result is True
        assert len(received) == 1
        assert received[0].action == "ping"
        assert received[0].destination == "bridge"

    async def test_send_with_payload(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[dict] = []

        async def handler(msg: Message) -> None:
            received.append(msg.payload)

        router.register("bridge", handler)
        await router.send("bridge", "execute", command="pwd", timeout=10)

        assert received[0] == {"command": "pwd", "timeout": 10}

    async def test_send_to_nonexistent(self) -> None:
        router = MessageRouter()
        await router.start()
        result = await router.send("nope", "ping")
        assert result is False
        assert router.metrics.failed == 1

    async def test_send_message_object(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        router.register("bridge", handler)
        msg = Message(source="nicky", destination="bridge", action="health")
        result = await router.send_message(msg)

        assert result is True
        assert received[0].source == "nicky"

    async def test_sync_handler(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[str] = []

        def handler(msg: Message) -> None:
            received.append(msg.action)

        router.register("bridge", handler)
        await router.send("bridge", "ping")
        assert received == ["ping"]

    async def test_handler_error(self) -> None:
        router = MessageRouter()
        await router.start()

        async def broken(msg: Message) -> None:
            raise RuntimeError("broken")

        router.register("bridge", broken)
        result = await router.send("bridge", "ping")
        assert result is False
        assert router.metrics.failed == 1
        assert len(router.dead_letters) == 1

    async def test_send_after_stop(self) -> None:
        router = MessageRouter()
        await router.start()
        await router.stop()

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        result = await router.send("bridge", "ping")
        assert result is False


# ===========================================================================
# MessageRouter — request/reply
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterRequestReply:
    """Tests for request/reply pattern."""

    async def test_request_reply_success(self) -> None:
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> dict:
            return {"status": "ok", "data": 42}

        router.register("bridge", handler)
        reply = await router.request("bridge", "health", timeout=5.0)

        assert reply.status == "ok"
        assert reply.data == {"status": "ok", "data": 42}
        assert reply.source == "bridge"

    async def test_request_with_payload(self) -> None:
        router = MessageRouter()
        await router.start()
        received_payload: list[dict] = []

        async def handler(msg: Message) -> dict:
            received_payload.append(msg.payload)
            return {"received": True}

        router.register("bridge", handler)
        reply = await router.request(
            "bridge", "execute",
            payload={"command": "pwd"},
            timeout=5.0,
        )

        assert reply.status == "ok"
        assert received_payload[0] == {"command": "pwd"}

    async def test_request_timeout(self) -> None:
        router = MessageRouter()
        await router.start()

        async def slow_handler(msg: Message) -> None:
            await asyncio.sleep(10.0)

        router.register("bridge", slow_handler)
        reply = await router.request("bridge", "slow", timeout=0.1)

        assert reply.status == "timeout"
        assert "Timeout" in reply.error

    async def test_request_endpoint_not_found(self) -> None:
        router = MessageRouter()
        await router.start()

        reply = await router.request("nope", "ping", timeout=1.0)
        assert reply.status == "error"
        assert "not found" in reply.error

    async def test_request_handler_error(self) -> None:
        router = MessageRouter()
        await router.start()

        async def broken(msg: Message) -> None:
            raise ValueError("broken handler")

        router.register("bridge", broken)
        reply = await router.request("bridge", "ping", timeout=5.0)

        assert reply.status == "error"
        assert "broken handler" in reply.error

    async def test_request_source(self) -> None:
        router = MessageRouter()
        await router.start()
        received_source: list[str] = []

        async def handler(msg: Message) -> None:
            received_source.append(msg.source)

        router.register("bridge", handler)
        await router.request("bridge", "ping", source="nicky")

        assert received_source[0] == "nicky"


# ===========================================================================
# MessageRouter — broadcast
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterBroadcast:
    """Tests for broadcast to all endpoints."""

    async def test_broadcast(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[str] = []

        async def h1(msg: Message) -> None:
            received.append("h1")

        async def h2(msg: Message) -> None:
            received.append("h2")

        router.register("bridge", h1)
        router.register("agent", h2)

        count = await router.broadcast("system_status")
        assert count == 2
        assert set(received) == {"h1", "h2"}

    async def test_broadcast_with_payload(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[dict] = []

        async def handler(msg: Message) -> None:
            received.append(msg.payload)

        router.register("bridge", handler)
        router.register("agent", handler)

        await router.broadcast("config_update", key="debug", value=True)

        assert all(p == {"key": "debug", "value": True} for p in received)

    async def test_broadcast_skips_inactive(self) -> None:
        router = MessageRouter()
        await router.start()
        received: list[str] = []

        async def handler(msg: Message) -> None:
            received.append("ok")

        ep = router.register("bridge", handler)
        router.register("agent", handler)
        router.unregister("bridge")

        count = await router.broadcast("ping")
        assert count == 1
        assert received == ["ok"]

    async def test_broadcast_handler_error(self) -> None:
        router = MessageRouter()
        await router.start()

        async def broken(msg: Message) -> None:
            raise RuntimeError("broken")

        async def good(msg: Message) -> None:
            pass

        router.register("broken", broken)
        router.register("good", good)

        count = await router.broadcast("ping")
        assert count == 1  # only good was counted
        assert router.metrics.failed == 1


# ===========================================================================
# MessageRouter — dead letters
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterDeadLetters:
    """Tests for dead letter queue."""

    async def test_dead_letter_on_failed_delivery(self) -> None:
        router = MessageRouter()
        await router.start()
        await router.send("nope", "ping")

        assert len(router.dead_letters) == 1
        dl = router.dead_letters[0]
        assert dl.message.destination == "nope"
        assert isinstance(dl.error, ValueError)

    async def test_dead_letter_limit(self) -> None:
        router = MessageRouter(max_dead_letters=3)
        await router.start()

        for _ in range(5):
            await router.send("nope", "ping")

        assert len(router.dead_letters) == 3

    async def test_clear_dead_letters(self) -> None:
        router = MessageRouter()
        await router.start()
        await router.send("nope", "ping")

        cleared = router.clear_dead_letters()
        assert cleared == 1
        assert len(router.dead_letters) == 0


# ===========================================================================
# MessageRouter — Event Bus integration
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterEventBus:
    """Tests for Event Bus integration."""

    async def test_publishes_request_event(self) -> None:
        bus = EventBus()
        await bus.start()
        router = MessageRouter(event_bus=bus)
        await router.start()

        received: list[Event] = []

        async def on_event(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("router.**", on_event)

        async def handler(msg: Message) -> dict:
            return {"ok": True}

        router.register("bridge", handler)
        await router.request("bridge", "health", timeout=5.0)

        requests = [e for e in received if e.topic == "router.request"]
        assert len(requests) >= 1
        assert requests[0].data["destination"] == "bridge"

    async def test_publishes_broadcast_event(self) -> None:
        bus = EventBus()
        await bus.start()
        router = MessageRouter(event_bus=bus)
        await router.start()

        received: list[Event] = []

        async def on_event(e: Event) -> None:
            received.append(e)

        bus.subscribe_handler("router.**", on_event)

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        await router.broadcast("ping")

        broadcasts = [e for e in received if e.topic == "router.broadcast"]
        assert len(broadcasts) == 1
        assert broadcasts[0].data["delivered"] == 1

    async def test_no_bus_no_crash(self) -> None:
        """Router works without an EventBus."""
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> dict:
            return {"ok": True}

        router.register("bridge", handler)
        result = await router.send("bridge", "ping")
        assert result is True


# ===========================================================================
# MessageRouter — metrics
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterMetrics:
    """Tests for metrics tracking."""

    async def test_metrics_after_send(self) -> None:
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        await router.send("bridge", "ping")

        assert router.metrics.sent == 1
        assert router.metrics.delivered == 1
        assert router.metrics.failed == 0

    async def test_metrics_after_broadcast(self) -> None:
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> None:
            pass

        router.register("a", handler)
        router.register("b", handler)
        await router.broadcast("ping")

        assert router.metrics.broadcast == 1
        assert router.metrics.delivered == 2

    async def test_metrics_failed(self) -> None:
        router = MessageRouter()
        await router.start()
        await router.send("nope", "ping")

        assert router.metrics.failed == 1

    async def test_dump(self) -> None:
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        dump = await router.dump()

        assert dump["running"] is True
        assert dump["endpoint_count"] == 1
        assert dump["metrics"]["sent"] == 0


# ===========================================================================
# MessageRouter — history
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterHistory:
    """Tests for routing history."""

    async def test_history_recorded(self) -> None:
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)
        await router.send("bridge", "ping")

        assert len(router.history) == 1
        assert router.history[0]["action"] == "ping"
        assert router.history[0]["destination"] == "bridge"

    async def test_history_trimming(self) -> None:
        router = MessageRouter()
        await router.start()

        async def handler(msg: Message) -> None:
            pass

        router.register("bridge", handler)

        # Force many messages
        from core.router import MAX_MESSAGE_HISTORY
        for _ in range(MAX_MESSAGE_HISTORY + 10):
            await router.send("bridge", "ping")

        assert len(router.history) == MAX_MESSAGE_HISTORY


# ===========================================================================
# MessageRouter — integration patterns
# ===========================================================================

@pytest.mark.asyncio
class TestMessageRouterIntegration:
    """Integration tests simulating real OmegaDrakon usage patterns."""

    async def test_bridge_health_check(self) -> None:
        """Simulate checking bridge health via request/reply."""
        router = MessageRouter()
        await router.start()

        async def bridge_handler(msg: Message) -> dict:
            return {"status": "ok", "port": 8765, "uptime": 3600}

        router.register("bridge", bridge_handler)
        reply = await router.request("bridge", "health", timeout=5.0)

        assert reply.status == "ok"
        assert reply.data["port"] == 8765

    async def test_agent_command_execution(self) -> None:
        """Simulate sending a command to an agent and getting a result."""
        router = MessageRouter()
        await router.start()

        async def agent_handler(msg: Message) -> dict:
            cmd = msg.payload.get("command", "")
            return {"output": f"executed: {cmd}", "exit_code": 0}

        router.register("agent.nicky", agent_handler)
        reply = await router.request(
            "agent.nicky", "execute",
            payload={"command": "pwd"},
            timeout=5.0,
        )

        assert reply.status == "ok"
        assert reply.data["exit_code"] == 0
        assert "executed: pwd" in reply.data["output"]

    async def test_multi_component_communication(self) -> None:
        """Multiple components communicate through the router."""
        router = MessageRouter()
        await router.start()
        log: list[str] = []

        async def bridge_handler(msg: Message) -> dict:
            log.append(f"bridge:{msg.action}")
            return {"from": "bridge"}

        async def agent_handler(msg: Message) -> dict:
            log.append(f"agent:{msg.action}")
            return {"from": "agent"}

        async def memory_handler(msg: Message) -> dict:
            log.append(f"memory:{msg.action}")
            return {"from": "memory"}

        router.register("bridge", bridge_handler)
        router.register("agent.nicky", agent_handler)
        router.register("memory", memory_handler)

        # Request to each
        r1 = await router.request("bridge", "status")
        r2 = await router.request("agent.nicky", "heartbeat")
        r3 = await router.request("memory", "stats")

        assert r1.status == "ok"
        assert r2.status == "ok"
        assert r3.status == "ok"
        assert len(log) == 3

    async def test_broadcast_system_status(self) -> None:
        """Broadcast system status to all components."""
        router = MessageRouter()
        await router.start()
        statuses: list[dict] = []

        async def handler(msg: Message) -> None:
            statuses.append(msg.payload)

        router.register("bridge", handler)
        router.register("agent", handler)
        router.register("memory", handler)

        count = await router.broadcast("system_status", status="running")
        assert count == 3
        assert all(s["status"] == "running" for s in statuses)

    async def test_error_handling_pattern(self) -> None:
        """Simulate graceful error handling in request/reply."""
        router = MessageRouter()
        await router.start()

        async def failing_handler(msg: Message) -> None:
            raise ConnectionError("database unreachable")

        router.register("database", failing_handler)
        reply = await router.request("database", "query", timeout=5.0)

        assert reply.status == "error"
        assert "database unreachable" in reply.error
        # Router continues to work
        assert router.running
