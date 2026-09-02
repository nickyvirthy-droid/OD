#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Module: router
Description: Inter-component message router — point-to-point with request/reply,
             named endpoints, validation, broadcast, and metrics.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Architecture:
    While the Event Bus handles fire-and-forget pub/sub (broadcasting), the
    Message Router handles directed communication between specific components.
    It provides request/reply semantics, message validation, and delivery
    guarantees.

    Components register as named endpoints. Messages are routed to specific
    endpoints by name, or broadcast to all. Request/reply uses futures for
    async response waiting with configurable timeouts.

    The Router is the "postal service" of OmegaDrakon — it delivers messages
    between components that need to talk to each other directly, without
    the coupling of direct method calls.

Protocol:
    Messages carry a source, destination, action, payload, and metadata.
    The router validates, routes, and tracks delivery. Failed deliveries
    go to the dead letter queue. All routing events are published on the
    Event Bus for observability.

Usage:
    from core.router import MessageRouter, Message

    router = MessageRouter(event_bus=bus)

    # Register endpoint
    async def handle_health(msg: Message) -> dict:
        return {"status": "ok"}

    router.register("bridge", handle_health)

    # Request/reply
    reply = await router.request("bridge", "health", timeout=5.0)

    # Fire-and-forget
    await router.send("bridge", "ping")
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Coroutine, Optional, Union

from core.event_bus import Event, EventBus, Priority

logger = logging.getLogger("omega.core.router")

NICKY_PREFIX = "[NICKY][{level}]"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REQUEST_TIMEOUT = 30.0  # seconds
MAX_MESSAGE_HISTORY = 1000
MAX_DEAD_LETTERS = 256


# ---------------------------------------------------------------------------
# Message Priority
# ---------------------------------------------------------------------------

class MessagePriority(IntEnum):
    """Message priority — lower value = higher priority."""
    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 90


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Message:
    """A directed message between components.

    Attributes:
        source:      Identifier of the sending component.
        destination: Target endpoint name ("*" for broadcast).
        action:      The action/command to invoke.
        payload:     Action-specific data dictionary.
        priority:    Delivery priority.
        msg_id:      Unique message identifier.
        ts:          Creation timestamp.
        reply_to:    Optional message ID this is replying to.
        timeout:     Request timeout in seconds (0 = fire-and-forget).
        metadata:    Extra key-value pairs for middleware/interceptors.
    """
    source: str
    destination: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)
    reply_to: Optional[str] = None
    timeout: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Message Reply
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MessageReply:
    """A reply to a message request.

    Attributes:
        reply_to:  The original message ID this replies to.
        source:    Identifier of the responding endpoint.
        status:    "ok", "error", or "timeout".
        data:      Response payload.
        error:     Error message if status is "error".
        msg_id:    Unique reply identifier.
        ts:        Creation timestamp.
    """
    reply_to: str
    source: str
    status: str  # "ok" | "error" | "timeout"
    data: Any = None
    error: Optional[str] = None
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Endpoint Handler
# ---------------------------------------------------------------------------

# Endpoint handler: receives Message, returns optional response data
SyncEndpoint = Callable[[Message], Any]
AsyncEndpoint = Callable[[Message], Coroutine[Any, Any, Any]]
EndpointHandler = Union[SyncEndpoint, AsyncEndpoint]


@dataclass(slots=True)
class Endpoint:
    """A registered message endpoint."""
    name: str
    handler: EndpointHandler
    handler_name: str
    active: bool = True


# ---------------------------------------------------------------------------
# Pending Request
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PendingRequest:
    """A pending request waiting for a reply."""
    msg_id: str
    source: str
    destination: str
    action: str
    future: asyncio.Future[Any]
    ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Routing Metrics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RouterMetrics:
    """Metrics for the message router."""
    sent: int = 0
    delivered: int = 0
    broadcast: int = 0
    failed: int = 0
    timeout: int = 0
    dead_letters: int = 0
    endpoint_count: int = 0
    pending_requests: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "sent": self.sent,
            "delivered": self.delivered,
            "broadcast": self.broadcast,
            "failed": self.failed,
            "timeout": self.timeout,
            "dead_letters": self.dead_letters,
            "endpoint_count": self.endpoint_count,
            "pending_requests": self.pending_requests,
        }


# ---------------------------------------------------------------------------
# Dead Letter
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DeadLetter:
    """A failed message delivery for inspection."""
    message: Message
    error: Exception
    attempts: int
    ts: float = field(default_factory=time.time)


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
# MessageRouter
# ---------------------------------------------------------------------------

class MessageRouter:
    """Inter-component message router with request/reply semantics.

    Components register as named endpoints. Messages are routed by
    destination name, or broadcast to all endpoints.

    Attributes:
        event_bus: Optional EventBus for publishing routing events.
        metrics:   Live metrics counters.
    """

    def __init__(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        max_dead_letters: int = MAX_DEAD_LETTERS,
    ) -> None:
        self._endpoints: dict[str, Endpoint] = {}
        self._pending: dict[str, PendingRequest] = {}
        self._event_bus = event_bus
        self._request_timeout = request_timeout
        self._max_dead_letters = max_dead_letters
        self._dead_letters: list[DeadLetter] = []
        self._history: list[dict[str, Any]] = []
        self._metrics = RouterMetrics()
        self._lock = asyncio.Lock()
        self._running = False

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def metrics(self) -> RouterMetrics:
        return self._metrics

    async def start(self) -> None:
        """Start the message router."""
        if self._running:
            _audit_nicky("WARN", "MessageRouter already running")
            return
        self._running = True
        _audit_nicky(
            "INFO",
            "MessageRouter started",
            endpoints=len(self._endpoints),
        )

    async def stop(self) -> None:
        """Stop the message router and cancel pending requests."""
        if not self._running:
            return
        self._running = False

        # Cancel all pending requests
        for req_id, pending in self._pending.items():
            if not pending.future.done():
                pending.future.set_exception(
                    RuntimeError("MessageRouter shutting down")
                )
        self._pending.clear()
        self._metrics.pending_requests = 0

        _audit_nicky(
            "INFO",
            "MessageRouter stopped",
            endpoints=len(self._endpoints),
            cancelled_requests=len(self._pending),
        )

    # -- Endpoint Registration -----------------------------------------------

    def register(
        self,
        name: str,
        handler: EndpointHandler,
    ) -> Endpoint:
        """Register a named message endpoint.

        Args:
            name:    Unique endpoint name (e.g. "bridge", "agent.nicky").
            handler: Sync or async callable that receives a Message.

        Returns:
            The Endpoint registration.
        """
        handler_name = getattr(
            handler, "__qualname__", getattr(handler, "__name__", "anonymous")
        )
        ep = Endpoint(name=name, handler=handler, handler_name=handler_name)
        self._endpoints[name] = ep
        self._metrics.endpoint_count = len(
            [e for e in self._endpoints.values() if e.active]
        )
        _audit_nicky(
            "INFO",
            f"Endpoint registered: {name}",
            handler=handler_name,
        )
        return ep

    def unregister(self, name: str) -> bool:
        """Unregister an endpoint by name. Returns True if found."""
        ep = self._endpoints.pop(name, None)
        if ep is None:
            return False
        ep.active = False
        self._metrics.endpoint_count = len(
            [e for e in self._endpoints.values() if e.active]
        )
        _audit_nicky("INFO", f"Endpoint unregistered: {name}")
        return True

    def has_endpoint(self, name: str) -> bool:
        """Check if an endpoint is registered and active."""
        ep = self._endpoints.get(name)
        return ep is not None and ep.active

    def list_endpoints(self) -> list[dict[str, Any]]:
        """Return a snapshot of all registered endpoints."""
        return [
            {
                "name": ep.name,
                "handler": ep.handler_name,
                "active": ep.active,
            }
            for ep in self._endpoints.values()
        ]

    # -- Sending (fire-and-forget) -------------------------------------------

    async def send(self, destination: str, action: str, **payload: Any) -> bool:
        """Send a fire-and-forget message to an endpoint.

        Args:
            destination: Target endpoint name.
            action:      The action/command name.
            **payload:   Keyword arguments passed as the message payload.

        Returns:
            True if delivered successfully, False otherwise.
        """
        msg = Message(
            source="router",
            destination=destination,
            action=action,
            payload=dict(payload) if payload else {},
        )
        return await self._route_message(msg)

    async def send_message(self, msg: Message) -> bool:
        """Send a pre-built Message object.

        Returns:
            True if delivered successfully, False otherwise.
        """
        return await self._route_message(msg)

    # -- Request/Reply -------------------------------------------------------

    async def request(
        self,
        destination: str,
        action: str,
        *,
        payload: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
        source: str = "router",
    ) -> MessageReply:
        """Send a request and wait for a reply.

        Args:
            destination: Target endpoint name.
            action:      The action/command name.
            payload:     Optional request data.
            timeout:     Seconds to wait for reply (default: 30s).
            source:      Identifier of the requesting component.

        Returns:
            MessageReply with status "ok", "error", or "timeout".
        """
        timeout = timeout or self._request_timeout

        msg = Message(
            source=source,
            destination=destination,
            action=action,
            payload=payload or {},
            timeout=timeout,
        )

        # Create future for reply
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        pending = PendingRequest(
            msg_id=msg.msg_id,
            source=source,
            destination=destination,
            action=action,
            future=future,
        )

        async with self._lock:
            self._pending[msg.msg_id] = pending
            self._metrics.pending_requests = len(self._pending)

        # Publish request event
        if self._event_bus:
            await self._event_bus.publish(Event(
                topic="router.request",
                data={
                    "msg_id": msg.msg_id,
                    "source": source,
                    "destination": destination,
                    "action": action,
                },
                source="message_router",
            ))

        # Route the message
        delivered = await self._route_message(msg)

        if not delivered:
            # Remove from pending
            async with self._lock:
                self._pending.pop(msg.msg_id, None)
                self._metrics.pending_requests = len(self._pending)
            return MessageReply(
                reply_to=msg.msg_id,
                source=destination,
                status="error",
                error=f"Endpoint not found: {destination}",
            )

        # Wait for reply with timeout
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return MessageReply(
                reply_to=msg.msg_id,
                source=destination,
                status="ok",
                data=result,
            )
        except asyncio.TimeoutError:
            self._metrics.timeout += 1
            _audit_nicky(
                "WARN",
                "Request timed out",
                msg_id=msg.msg_id,
                destination=destination,
                action=action,
                timeout=timeout,
            )
            return MessageReply(
                reply_to=msg.msg_id,
                source=destination,
                status="timeout",
                error=f"Timeout after {timeout}s",
            )
        except Exception as exc:
            # If handler already set the future result/exception, the
            # exception here is from the handler itself
            return MessageReply(
                reply_to=msg.msg_id,
                source=destination,
                status="error",
                error=str(exc),
            )
        finally:
            async with self._lock:
                self._pending.pop(msg.msg_id, None)
                self._metrics.pending_requests = len(self._pending)

    async def reply(
        self,
        original: Message,
        data: Any = None,
        *,
        error: Optional[str] = None,
    ) -> None:
        """Send a reply to a pending request.

        Args:
            original: The original message being replied to.
            data:     Response data.
            error:    Error message (sets status to "error").
        """
        pending = self._pending.get(original.msg_id)
        if pending is None or pending.future.done():
            _audit_nicky(
                "WARN",
                "Reply to unknown request",
                reply_to=original.msg_id,
            )
            return

        if error:
            pending.future.set_exception(RuntimeError(error))
        else:
            pending.future.set_result(data)

        _audit_nicky(
            "INFO",
            "Reply sent",
            reply_to=original.msg_id,
            source=original.destination,
        )

    # -- Broadcast -----------------------------------------------------------

    async def broadcast(self, action: str, **payload: Any) -> int:
        """Broadcast a message to all active endpoints.

        Args:
            action:   The action/command name.
            **payload: Keyword arguments passed as the message payload.

        Returns:
            Number of endpoints that received the message.
        """
        msg = Message(
            source="router",
            destination="*",
            action=action,
            payload=dict(payload) if payload else {},
        )

        delivered = 0
        for name, ep in self._endpoints.items():
            if not ep.active:
                continue
            try:
                result = ep.handler(msg)
                if asyncio.iscoroutine(result):
                    await result
                delivered += 1
                self._metrics.delivered += 1
            except Exception as exc:
                _audit_nicky(
                    "WARN",
                    f"Broadcast handler error",
                    endpoint=name,
                    action=action,
                    error=type(exc).__name__,
                )
                self._metrics.failed += 1

        self._metrics.broadcast += 1

        if self._event_bus:
            await self._event_bus.publish(Event(
                topic="router.broadcast",
                data={"action": action, "delivered": delivered},
                source="message_router",
            ))

        _audit_nicky(
            "INFO",
            "Broadcast sent",
            action=action,
            delivered=delivered,
        )
        return delivered

    # -- Internal Routing ----------------------------------------------------

    async def _route_message(self, msg: Message) -> bool:
        """Route a message to its destination endpoint."""
        if not self._running:
            return False

        self._metrics.sent += 1
        destination = msg.destination

        # Record in history
        self._record_history(msg)

        if destination == "*":
            # Broadcast
            count = await self._broadcast_to_all(msg)
            self._metrics.delivered += count
            return count > 0

        # Point-to-point
        ep = self._endpoints.get(destination)
        if ep is None or not ep.active:
            self._metrics.failed += 1
            self._add_dead_letter(
                DeadLetter(message=msg, error=ValueError(f"Endpoint not found: {destination}"), attempts=1)
            )
            _audit_nicky(
                "WARN",
                "Message delivery failed",
                msg_id=msg.msg_id,
                destination=destination,
                action=msg.action,
            )
            return False

        # For requests (pending future), run handler in background task
        # so the caller can await the future with a timeout
        pending = self._pending.get(msg.msg_id)
        if pending and not pending.future.done():
            asyncio.ensure_future(self._execute_handler(ep, msg, pending))
            return True

        # Fire-and-forget: run handler inline
        try:
            result = ep.handler(msg)
            if asyncio.iscoroutine(result):
                await result

            self._metrics.delivered += 1
            _audit_nicky(
                "INFO",
                "Message delivered",
                msg_id=msg.msg_id,
                destination=destination,
                action=msg.action,
            )
            return True
        except Exception as exc:
            self._metrics.failed += 1
            self._add_dead_letter(
                DeadLetter(message=msg, error=exc, attempts=1)
            )
            _audit_nicky(
                "CRIT",
                "Message handler error",
                msg_id=msg.msg_id,
                destination=destination,
                action=msg.action,
                error=type(exc).__name__,
            )
            return False

    async def _execute_handler(
        self,
        ep: Endpoint,
        msg: Message,
        pending: PendingRequest,
    ) -> None:
        """Execute a handler in a background task and resolve the pending future."""
        try:
            result = ep.handler(msg)
            if asyncio.iscoroutine(result):
                result = await result

            if not pending.future.done():
                pending.future.set_result(result)

            self._metrics.delivered += 1
            _audit_nicky(
                "INFO",
                "Request handler completed",
                msg_id=msg.msg_id,
                destination=ep.name,
                action=msg.action,
            )
        except Exception as exc:
            if not pending.future.done():
                pending.future.set_exception(exc)

            self._metrics.failed += 1
            self._add_dead_letter(
                DeadLetter(message=msg, error=exc, attempts=1)
            )
            _audit_nicky(
                "CRIT",
                "Request handler error",
                msg_id=msg.msg_id,
                destination=ep.name,
                action=msg.action,
                error=type(exc).__name__,
            )

    async def _broadcast_to_all(self, msg: Message) -> int:
        """Send a message to all active endpoints. Returns count of successful deliveries."""
        count = 0
        for name, ep in self._endpoints.items():
            if not ep.active:
                continue
            try:
                result = ep.handler(msg)
                if asyncio.iscoroutine(result):
                    await result
                count += 1
            except Exception as exc:
                _audit_nicky(
                    "WARN",
                    f"Broadcast handler error",
                    endpoint=name,
                    action=msg.action,
                    error=type(exc).__name__,
                )
                self._metrics.failed += 1
        return count

    # -- Dead Letters --------------------------------------------------------

    def _add_dead_letter(self, letter: DeadLetter) -> None:
        self._dead_letters.append(letter)
        self._metrics.dead_letters = len(self._dead_letters)
        if len(self._dead_letters) > self._max_dead_letters:
            self._dead_letters = self._dead_letters[-self._max_dead_letters:]
            self._metrics.dead_letters = len(self._dead_letters)

    @property
    def dead_letters(self) -> list[DeadLetter]:
        return list(self._dead_letters)

    def clear_dead_letters(self) -> int:
        """Clear the dead letter queue. Returns count cleared."""
        count = len(self._dead_letters)
        self._dead_letters.clear()
        self._metrics.dead_letters = 0
        return count

    # -- History -------------------------------------------------------------

    def _record_history(self, msg: Message) -> None:
        """Record a message in the routing history."""
        self._history.append({
            "msg_id": msg.msg_id,
            "source": msg.source,
            "destination": msg.destination,
            "action": msg.action,
            "ts": msg.ts,
        })
        if len(self._history) > MAX_MESSAGE_HISTORY:
            self._history = self._history[-MAX_MESSAGE_HISTORY:]

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    # -- Inspection ----------------------------------------------------------

    async def dump(self) -> dict[str, Any]:
        """Return a full diagnostic dump of the router."""
        return {
            "running": self._running,
            "endpoint_count": self._metrics.endpoint_count,
            "pending_requests": self._metrics.pending_requests,
            "metrics": self._metrics.snapshot(),
            "endpoints": self.list_endpoints(),
            "history_length": len(self._history),
        }
