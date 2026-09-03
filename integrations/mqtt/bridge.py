"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/mqtt/bridge.py
Descrição: MQTT Bridge (Fase 5, item 5.5) — ponte entre o broker MQTT e o
           núcleo do Omega Drakon: assina filtros com handlers, repassa
           mensagens recebidas ao Event Bus (`mqtt.message`), publica
           eventos do bus em tópicos MQTT (roteamento configurável),
           mantém reconexão com re-assinatura, métricas e introspecção.
           Transporte plugável (MQTTClient real ou fake determinístico).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus: integração IoT via MQTT (config/mosquitto, paho-mqtt)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.5 (publica/assina tópicos)

Decisões registradas (ver CHANGELOG):
  - Ponte de EVENTOS: mensagens MQTT entram no Event Bus como
    `mqtt.message`; eventos do bus podem ser roteados para tópicos
    (default: `od/<tópico-do-bus com . → />`) — desacoplamento total
  - Processamento inbound acontece no loop async da ponte (poll), nunca
    na thread de leitura do socket — determinístico e sem corrida com o
    Event Bus (que é async)
  - Reconexão com re-assinatura automática dos filtros desejados
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Union

from core.event_bus import Event
from core.logger import get_logger
from integrations.mqtt import protocol as p

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.mqtt")

DEFAULT_POLL_TIMEOUT_S = 1.0
DEFAULT_RECONNECT_DELAY_S = 2.0
INBOUND_BUS_TOPIC = "mqtt.message"
DEFAULT_OUT_PREFIX = "od"


@dataclass(slots=True)
class MQTTConfig:
    """Configuração da ponte MQTT."""

    poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S
    reconnect_delay_s: float = DEFAULT_RECONNECT_DELAY_S
    inbound_bus_topic: str = INBOUND_BUS_TOPIC
    bus_forward: bool = True  # mensagem recebida → Event Bus
    out_prefix: str = DEFAULT_OUT_PREFIX  # default: od/<bus topic>


@dataclass(slots=True)
class MQTTMetrics:
    """Métricas acumuladas da ponte."""

    connects: int = 0
    reconnects: int = 0
    published: int = 0
    received: int = 0
    handlers_called: int = 0
    bus_forwarded: int = 0
    bus_routed: int = 0
    errors: int = 0

    def snapshot(self) -> dict:
        return {
            "connects": self.connects,
            "reconnects": self.reconnects,
            "published": self.published,
            "received": self.received,
            "handlers_called": self.handlers_called,
            "bus_forwarded": self.bus_forwarded,
            "bus_routed": self.bus_routed,
            "errors": self.errors,
        }


MessageHandler = Callable[[p.MqttMessage], Union[Any, Awaitable[Any]]]


class MQTTBridge:
    """Ponte MQTT ↔ núcleo (Event Bus), sobre um transporte MQTT.

    Uso típico:
        client = MQTTClient("127.0.0.1", 1883)
        bridge = MQTTBridge(client, event_bus=bus)
        bridge.connect()
        bridge.subscribe("od/#", handler)
        bridge.run(max_polls=...)     # ou start()/stop() em thread
    """

    def __init__(
        self,
        transport: Any,
        *,
        event_bus: Any = None,
        config: Optional[MQTTConfig] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.transport = transport
        self.event_bus = event_bus
        self.config = config or MQTTConfig()
        self._clock = clock or time.time
        self.metrics = MQTTMetrics()
        self._handlers: list[tuple[str, MessageHandler]] = []
        self._desired_filters: list[str] = []
        self._bus_routes: list[dict] = []
        self._was_connected = False
        self._closed = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._last_error: Optional[str] = None
        self._connected_at: Optional[float] = None

    # -- Conexão -------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return bool(getattr(self.transport, "is_connected", False))

    def connect(self) -> bool:
        """Conecta o transporte (e re-assina os filtros desejados)."""
        if self.is_connected:
            return True
        try:
            self.transport.connect()
        except Exception as exc:  # broker fora do ar etc.
            self._last_error = str(exc)
            self.metrics.errors += 1
            log.warn(
                "Falha ao conectar no broker MQTT",
                error=str(exc), host=self._host(),
            )
            return False
        self.metrics.connects += 1
        if self._was_connected:
            self.metrics.reconnects += 1
            log.warn("MQTT reconectado", host=self._host())
        self._was_connected = True
        self._connected_at = self._clock()
        self._last_error = None
        if self._desired_filters:
            try:
                self.transport.subscribe(
                    [(f, p.QOS_AT_LEAST_ONCE) for f in self._desired_filters]
                )
            except Exception as exc:  # pragma: no cover
                self._last_error = f"re-assinatura: {exc}"
                self.metrics.errors += 1
        log.info(
            "MQTT conectado", host=self._host(), client_id=self._client_id()
        )
        return True

    def disconnect(self) -> None:
        """Desconecta o transporte."""
        self._closed = True
        try:
            self.transport.disconnect()
        except Exception:  # pragma: no cover
            pass

    def close(self) -> None:
        self.disconnect()

    def _host(self) -> str:
        host = getattr(self.transport, "host", "?")
        port = getattr(self.transport, "port", "?")
        return f"{host}:{port}"

    def _client_id(self) -> str:
        return str(getattr(self.transport, "client_id", "?"))

    # -- Assinaturas e handlers ----------------------------------------------

    def subscribe(
        self,
        filters: Union[str, list[str]],
        handler: Optional[MessageHandler] = None,
    ) -> None:
        """Assina filtros no broker e registra handler (opcional).

        Filtros assinados são re-aplicados automaticamente na reconexão.
        """
        if isinstance(filters, str):
            spec = [filters]
        else:
            spec = list(filters)
        for filter_ in spec:
            p.validate_filter(filter_)
            if filter_ not in self._desired_filters:
                self._desired_filters.append(filter_)
            if handler is not None:
                self._handlers.append((filter_, handler))
        if self.is_connected:
            try:
                self.transport.subscribe(
                    [(f, p.QOS_AT_LEAST_ONCE) for f in spec]
                )
            except Exception as exc:
                self._last_error = f"subscribe: {exc}"
                self.metrics.errors += 1
                log.warn("Falha ao assinar", filters=spec, error=str(exc))

    def unsubscribe(self, filters: Union[str, list[str]]) -> None:
        """Cancela assinaturas (broker) e remove handlers dos filtros."""
        if isinstance(filters, str):
            spec = [filters]
        else:
            spec = list(filters)
        self._desired_filters = [
            f for f in self._desired_filters if f not in spec
        ]
        self._handlers = [
            (f, h) for (f, h) in self._handlers if f not in spec
        ]
        if self.is_connected and spec:
            try:
                self.transport.unsubscribe(spec)
            except Exception as exc:  # pragma: no cover
                self._last_error = f"unsubscribe: {exc}"
                self.metrics.errors += 1

    # -- Publicação ----------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: Union[bytes, str] = b"",
        *,
        qos: int = p.QOS_AT_MOST_ONCE,
        retain: bool = False,
    ) -> bool:
        """Publica no broker (conecta antes se necessário)."""
        if not self.connect():
            return False
        try:
            self.transport.publish(topic, payload, qos=qos, retain=retain)
        except Exception as exc:
            self._last_error = f"publish: {exc}"
            self.metrics.errors += 1
            log.warn("Falha ao publicar", topic=topic, error=str(exc))
            return False
        self.metrics.published += 1
        return True

    # -- Roteamento Event Bus → MQTT -----------------------------------------

    def route_bus(
        self,
        pattern: str,
        to_topic: Optional[str] = None,
    ) -> Any:
        """Roteia eventos do Event Bus para tópicos MQTT.

        Args:
            pattern:  Padrão de tópico do bus (ex: "notifier.**").
            to_topic: Tópico MQTT fixo, ou None para mapear o tópico do
                      bus (default: `od/<tópico com . → />`).

        Returns:
            Assinatura do bus (para unsubscribe se preciso).
        """
        if self.event_bus is None:
            raise RuntimeError("route_bus exige event_bus na ponte")

        def default_topic(event_topic: str) -> str:
            return f"{self.config.out_prefix}/{event_topic.replace('.', '/')}"

        async def handler(event: Event) -> None:
            topic = to_topic or default_topic(event.topic)
            ok = self.publish(topic, _payload_from_event(event))
            if ok:
                self.metrics.bus_routed += 1

        sub = self.event_bus.subscribe_handler(pattern, handler)
        self._bus_routes.append(
            {
                "pattern": pattern,
                "to_topic": to_topic,
                "handler": handler,
                "subscription": sub,
            }
        )
        log.info("Rota bus→MQTT registrada", pattern=pattern, to_topic=to_topic)
        return sub

    # -- Inbound -------------------------------------------------------------

    async def poll_once(self, timeout: Optional[float] = None) -> Optional[p.MqttMessage]:
        """Aguarda UMA mensagem (timeout opcional) e processa handlers/bus.

        Unidade determinística do loop — usada pelos testes e pelo run().
        """
        wait = self.config.poll_timeout_s if timeout is None else timeout
        message = await asyncio.to_thread(
            self.transport.wait_message, wait
        )
        if message is not None:
            await self._handle_inbound(message)
        return message

    async def _handle_inbound(self, message: p.MqttMessage) -> None:
        self.metrics.received += 1
        log.info(
            "Mensagem MQTT recebida",
            topic=message.topic,
            qos=message.qos,
            size=len(message.payload),
        )
        for filter_, handler in list(self._handlers):
            if p.topic_matches(filter_, message.topic):
                try:
                    out = handler(message)
                    if isinstance(out, Awaitable):
                        await out
                    self.metrics.handlers_called += 1
                except Exception as exc:  # pragma: no cover — handler quebrou
                    self._last_error = f"handler: {exc}"
                    self.metrics.errors += 1
                    log.error("Handler MQTT falhou", error=str(exc))
        if self.config.bus_forward and self.event_bus is not None:
            try:
                data = message.to_dict()
                data["client_id"] = self._client_id()
                data["ts"] = self._clock()
                await self.event_bus.publish(
                    Event(
                        topic=self.config.inbound_bus_topic,
                        data=data,
                        source="mqtt",
                    )
                )
                self.metrics.bus_forwarded += 1
            except Exception as exc:  # pragma: no cover
                self._last_error = f"bus: {exc}"
                self.metrics.errors += 1

    # -- Loop ----------------------------------------------------------------

    async def run(self, max_polls: Optional[int] = None) -> int:
        """Loop da ponte: reconecta quando preciso e processa mensagens.

        Returns:
            Número de polls executados.
        """
        polls = 0
        while not self._closed:
            if not self.connect():
                await asyncio.sleep(self.config.reconnect_delay_s)
                continue
            await self.poll_once()
            polls += 1
            if max_polls is not None and polls >= max_polls:
                break
        return polls

    def start(self) -> threading.Thread:
        """Sobe o loop da ponte em thread daemon (runtime)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._closed = False
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True
            )
            self._thread.start()
            return self._thread

    def _run_loop(self) -> None:
        try:
            asyncio.run(self.run())
        except Exception as exc:  # pragma: no cover — loop interno
            self.metrics.errors += 1
            log.error("Loop da ponte MQTT encerrado", error=type(exc).__name__)

    def stop(self) -> None:
        """Encerra o loop e desconecta (chamada thread-safe)."""
        with self._lock:
            self._closed = True
        try:
            self.transport.disconnect()
        except Exception:  # pragma: no cover
            pass

    # -- Introspecção --------------------------------------------------------

    def health(self) -> dict:
        return {
            "ok": self.is_connected,
            "connected": self.is_connected,
            "host": self._host(),
            "client_id": self._client_id(),
            "metrics": self.metrics.snapshot(),
            "ts": self._clock(),
        }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "connected": self.is_connected,
                "host": self._host(),
                "client_id": self._client_id(),
                "subscriptions": list(self._desired_filters),
                "handlers": len(self._handlers),
                "bus_routes": [
                    {"pattern": r["pattern"], "to_topic": r["to_topic"]}
                    for r in self._bus_routes
                ],
                "metrics": self.metrics.snapshot(),
                "last_error": self._last_error,
                "connected_at": self._connected_at,
            }

    def dump(self) -> dict:
        data = self.snapshot()
        return data


def _payload_from_event(event: Event) -> bytes:
    """Serializa o payload de um evento do bus para o MQTT (JSON)."""
    import json

    data = event.data
    if not isinstance(data, dict):
        data = {"value": data}
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
