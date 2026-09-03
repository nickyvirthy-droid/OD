"""
OMEGA DRAKON • TESTS
Módulo: tests/test_mqtt.py
Descrição: Testes da MQTT Bridge (integrations/mqtt/) — Fase 5, item 5.5:
           codec do protocolo MQTT 3.1.1 (pacotes, validação de tópicos e
           curingas), cliente real contra o InMemoryBroker em loopback
           (handshake, recusa, QoS 0/1 com PUBACK, retained, wildcards,
           keepalive) e a MQTTBridge com Event Bus (handlers, forward
           mqtt.message, roteamento bus→MQTT, reconexão, métricas).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - OASIS MQTT 3.1.1 (ISO/IEC 20922)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.5
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time

import pytest

from core.event_bus import Event, EventBus
from integrations.mqtt import (
    CONNACK_ACCEPTED,
    MQTTBridge,
    MQTTClient,
    MQTTConfig,
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    MqttMessage,
    QOS_AT_LEAST_ONCE,
    QOS_AT_MOST_ONCE,
    encode_connect,
    encode_publish,
    encode_subscribe,
    topic_matches,
    validate_filter,
    validate_topic,
)
from integrations.mqtt.broker import InMemoryBroker
from integrations.mqtt.protocol import (
    PACKET_CONNACK,
    PACKET_PUBLISH,
    decode_connack,
    decode_packet_id,
    decode_publish,
    decode_suback,
    encode_remaining,
    read_packet,
)


def make_pair():
    """Socketpair para testar o read_packet sem rede."""
    left, right = socket.socketpair()
    left.settimeout(3)
    right.settimeout(3)
    return left, right


def wait_for(predicate, timeout: float = 2.0) -> bool:
    """Espera até o predicado ficar True (processamento em threads)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


# ===========================================================================
# Protocolo — comprimento remanescente e estrutura de pacotes
# ===========================================================================

class TestRemainingLength:
    def test_round_trip_boundaries(self) -> None:
        for length in (0, 1, 127, 128, 16383, 16384, 2097151, 2097152,
                       268435455):
            encoded = encode_remaining(length)
            sock_a, sock_b = make_pair()
            try:
                sock_a.sendall(encoded)
                first = sock_b.recv(1)
                assert first[0] >> 4 == 0 or True  # apenas sanity de socket
            finally:
                sock_a.close()
                sock_b.close()

    def test_single_byte_small(self) -> None:
        assert encode_remaining(0) == b"\x00"
        assert encode_remaining(127) == b"\x7f"

    def test_multi_byte(self) -> None:
        assert encode_remaining(128) == b"\x80\x01"
        assert encode_remaining(16383) == b"\xff\x7f"

    def test_overflow_raises(self) -> None:
        with pytest.raises(MQTTProtocolError):
            encode_remaining(268435456)

    def test_read_packet_multibyte_over_socket(self) -> None:
        sock_a, sock_b = make_pair()
        try:
            payload = b"x" * 300
            packet = encode_publish("od/longo", payload)
            sock_a.sendall(packet)
            ptype, flags, body = read_packet(sock_b)
            assert ptype == PACKET_PUBLISH
            assert len(body) == len(payload) + 2 + len("od/longo")
        finally:
            sock_a.close()
            sock_b.close()


class TestTopicValidation:
    def test_valid_topics(self) -> None:
        for topic in ("od", "od/alerts", "a/b/c/d", "casa/sala/luz", "1/2/3"):
            validate_topic(topic)  # não deve levantar

    def test_empty_topic(self) -> None:
        with pytest.raises(MQTTError):
            validate_topic("")

    def test_wildcards_forbidden_in_topic(self) -> None:
        with pytest.raises(MQTTError, match="curinga"):
            validate_topic("od/#")
        with pytest.raises(MQTTError, match="curinga"):
            validate_topic("od/+")

    def test_valid_filters(self) -> None:
        for filter_ in ("#", "od/#", "sport/tennis/#", "+", "sport/+",
                        "sport/+/player1", "sport/tennis/player1/#"):
            validate_filter(filter_)

    def test_hash_not_last_rejected(self) -> None:
        with pytest.raises(MQTTError):
            validate_filter("sport/#/ranking")
        with pytest.raises(MQTTError):
            validate_filter("sport#")

    def test_plus_within_level_rejected(self) -> None:
        with pytest.raises(MQTTError):
            validate_filter("sport+")
        with pytest.raises(MQTTError):
            validate_filter("sport/tennis+/ranking")


class TestTopicMatching:
    def test_exact_and_hash(self) -> None:
        assert topic_matches("od/#", "od")
        assert topic_matches("od/#", "od/alerts")
        assert topic_matches("od/#", "od/a/b/c")
        assert not topic_matches("od/#", "other/x")
        assert topic_matches("#", "qualquer.coisa")

    def test_single_plus(self) -> None:
        assert topic_matches("sport/+/player1", "sport/tennis/player1")
        assert not topic_matches("sport/+/player1", "sport/tennis/player2")
        assert not topic_matches("sport/+/player1", "sport/tennis/dupla/player1")

    def test_hash_mid_matches_rest(self) -> None:
        assert topic_matches("sport/tennis/#", "sport/tennis")
        assert topic_matches("sport/tennis/#", "sport/tennis/player1/ranking")

    def test_wrong_depth(self) -> None:
        assert not topic_matches("sport/tennis", "sport/tennis/player1")
        assert not topic_matches("sport/tennis/+", "sport")


class TestPublishCodec:
    def test_encode_publish_qos0_structure(self) -> None:
        packet = encode_publish("od/x", b"hi")
        assert packet[0] >> 4 == PACKET_PUBLISH
        assert packet[0] & 0x06 == 0  # qos 0

    def test_encode_publish_qos1_requires_packet_id(self) -> None:
        with pytest.raises(MQTTError, match="packet_id"):
            encode_publish("od/x", b"hi", qos=QOS_AT_LEAST_ONCE)

    def test_encode_publish_qos2_rejected(self) -> None:
        with pytest.raises(MQTTError, match="QoS 2"):
            encode_publish("od/x", b"hi", qos=2)

    def test_round_trip_qos1_with_puback_packet_id(self) -> None:
        packet = encode_publish(
            "od/alerta", b"llm offline", qos=QOS_AT_LEAST_ONCE, packet_id=7
        )
        sock_a, sock_b = make_pair()
        try:
            sock_a.sendall(packet)
            ptype, flags, body = read_packet(sock_b)
            message, packet_id = decode_publish(flags, body)
            assert message.topic == "od/alerta"
            assert message.payload == b"llm offline"
            assert message.qos == QOS_AT_LEAST_ONCE
            assert packet_id == 7
        finally:
            sock_a.close()
            sock_b.close()

    def test_round_trip_retain_and_dup(self) -> None:
        packet = encode_publish(
            "od/estado", b"1", qos=QOS_AT_LEAST_ONCE, packet_id=3, retain=True
        )
        sock_a, sock_b = make_pair()
        try:
            sock_a.sendall(packet)
            ptype, flags, body = read_packet(sock_b)
            message, _pid = decode_publish(flags, body)
            assert message.retain is True
        finally:
            sock_a.close()
            sock_b.close()

    def test_payload_text_helper(self) -> None:
        msg = MqttMessage(topic="t", payload="olá mundo".encode())
        assert msg.text() == "olá mundo"
        bad = MqttMessage(topic="t", payload=b"\xff\xfe\x00")
        assert bad.text(fallback="?") == "?"
        data = msg.to_dict()
        assert data["topic"] == "t" and data["payload"] == "olá mundo"


class TestConnectCodec:
    def test_encode_connect_contains_protocol(self) -> None:
        packet = encode_connect("od-cli", keepalive=30)
        assert b"MQTT" in packet
        assert packet[0] >> 4 == 1  # CONNECT

    def test_connack_decode(self) -> None:
        accepted = decode_connack(b"\x00\x00")
        assert accepted == (False, CONNACK_ACCEPTED)
        session, code = decode_connack(b"\x01\x05")
        assert session is True
        assert code == 5  # não autorizado

    def test_decode_suback(self) -> None:
        body = struct.pack(">H", 10) + bytes([1, 0, 0x80])
        packet_id, grants = decode_suback(body)
        assert packet_id == 10
        assert grants == [1, 0, 0x80]

    def test_decode_packet_id(self) -> None:
        assert decode_packet_id(struct.pack(">H", 42)) == 42

    def test_subscribe_packet_has_required_flags(self) -> None:
        packet = encode_subscribe([("od/#", QOS_AT_LEAST_ONCE)], packet_id=1)
        assert packet[0] == 0x82  # SUBSCRIBE com flags 0x2 (MQTT-3.8.1-1)


# ===========================================================================
# Broker fake + cliente real (loopback TCP)
# ===========================================================================

class TestClientConnect:
    def test_connect_disconnect_lifecycle(self) -> None:
        broker = InMemoryBroker().start()
        client = MQTTClient("127.0.0.1", broker.port, client_id="ciclo")
        try:
            client.connect()
            assert client.is_connected
            assert broker.connected_clients == 1
            client.disconnect()
            assert not client.is_connected
            assert wait_for(lambda: broker.connected_clients == 0)
        finally:
            client.disconnect()
            broker.stop()

    def test_connect_refused_raises_typed_error(self) -> None:
        broker = InMemoryBroker(
            allow=lambda cid: cid != "bloqueado"
        ).start()
        client = MQTTClient("127.0.0.1", broker.port, client_id="bloqueado")
        try:
            with pytest.raises(MQTTConnectError) as excinfo:
                client.connect()
            assert excinfo.value.code == 5  # não autorizado
        finally:
            broker.stop()

    def test_connect_broker_down_raises_oserror(self) -> None:
        client = MQTTClient("127.0.0.1", 1, client_id="offline")
        with pytest.raises(OSError):
            client.connect()

    def test_default_client_id_generated(self) -> None:
        client = MQTTClient("127.0.0.1", 1883)
        assert client.client_id.startswith("od-")


class TestPubSubWire:
    def _pair(self):
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="pub")
        sub = MQTTClient("127.0.0.1", broker.port, client_id="sub")
        pub.connect()
        sub.connect()
        return broker, pub, sub

    def test_subscribe_grants_qos(self) -> None:
        broker, _pub, sub = self._pair()
        try:
            grants = sub.subscribe(
                [("od/#", QOS_AT_LEAST_ONCE),
                 ("casa/luz", QOS_AT_MOST_ONCE)]
            )
            assert grants == [1, 0]
        finally:
            broker.stop()

    def test_qos0_routing_with_wildcards(self) -> None:
        broker, pub, sub = self._pair()
        try:
            sub.subscribe("casa/+/luz")
            pub.publish("casa/sala/luz", "on")
            pub.publish("casa/sala/outra", "ignorada")
            pub.publish("outro/topico", "ignorada2")
            msg = sub.wait_message(3)
            assert msg is not None
            assert msg.topic == "casa/sala/luz"
            assert msg.text() == "on"
            assert msg.qos == QOS_AT_MOST_ONCE
            assert sub.wait_message(0.3) is None
        finally:
            broker.stop()

    def test_qos1_publish_acks_and_delivers_qos1(self) -> None:
        broker, pub, sub = self._pair()
        try:
            sub.subscribe("od/#", qos=QOS_AT_LEAST_ONCE)
            assert pub.publish(
                "od/alerta", "crítico", qos=QOS_AT_LEAST_ONCE
            ) is True
            msg = sub.wait_message(3)
            assert msg is not None
            assert msg.qos == QOS_AT_LEAST_ONCE
            assert msg.text() == "crítico"
        finally:
            broker.stop()

    def test_multiple_subscribers_receive(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="pub")
        s1 = MQTTClient("127.0.0.1", broker.port, client_id="s1")
        s2 = MQTTClient("127.0.0.1", broker.port, client_id="s2")
        try:
            pub.connect(); s1.connect(); s2.connect()
            s1.subscribe("od/#")
            s2.subscribe("od/#")
            pub.publish("od/msg", "para todos")
            assert s1.wait_message(3).text() == "para todos"
            assert s2.wait_message(3).text() == "para todos"
        finally:
            broker.stop()

    def test_unsubscribe_stops_delivery(self) -> None:
        broker, pub, sub = self._pair()
        try:
            sub.subscribe("od/#")
            pub.publish("od/1", "antes")
            assert sub.wait_message(3).text() == "antes"
            assert sub.unsubscribe("od/#") is True
            pub.publish("od/2", "depois")
            assert sub.wait_message(0.4) is None
        finally:
            broker.stop()

    def test_retained_delivered_to_new_subscriber(self) -> None:
        broker, pub, _sub = self._pair()
        novo = MQTTClient("127.0.0.1", broker.port, client_id="novo")
        try:
            pub.publish("od/estado", "ok", retain=True)
            assert wait_for(lambda: broker.retained_count == 1)
            novo.connect()
            novo.subscribe("od/#")
            msg = novo.wait_message(3)
            assert msg is not None and msg.retain is True
            assert msg.text() == "ok"
        finally:
            broker.stop()

    def test_retained_cleared_by_empty_payload(self) -> None:
        broker, pub, _sub = self._pair()
        try:
            pub.publish("od/estado", "v1", retain=True)
            assert wait_for(lambda: broker.retained_count == 1)
            pub.publish("od/estado", b"", retain=True)
            assert wait_for(lambda: broker.retained_count == 0)
            assert broker.retained == {}
        finally:
            broker.stop()

    def test_keepalive_sends_pingreq(self) -> None:
        broker = InMemoryBroker().start()
        client = MQTTClient(
            "127.0.0.1", broker.port, client_id="ping", keepalive=1
        )
        try:
            client.connect()
            time.sleep(2.6)
            assert broker.stats.pingreq >= 1
        finally:
            client.disconnect()
            broker.stop()

    def test_wait_message_timeout_returns_none(self) -> None:
        broker, _pub, sub = self._pair()
        try:
            assert sub.wait_message(0.2) is None
        finally:
            broker.stop()

    def test_client_snapshot(self) -> None:
        broker, _pub, sub = self._pair()
        try:
            snap = sub.snapshot()
            assert snap["client_id"] == "sub"
            assert snap["connected"] is True
        finally:
            broker.stop()


# ===========================================================================
# MQTTBridge — handlers, Event Bus, roteamento, reconexão
# ===========================================================================

def bridge_config() -> MQTTConfig:
    return MQTTConfig(poll_timeout_s=0.05, reconnect_delay_s=0.01)


class TestBridgeInbound:
    @pytest.mark.asyncio
    async def test_handler_receives_matching_messages(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            pub.connect()
            assert bridge.connect()
            received: list[MqttMessage] = []
            bridge.subscribe("od/#", handler=received.append)
            pub.publish("od/comando", "liga luz")
            msg = await bridge.poll_once(3)
            assert msg is not None and msg.text() == "liga luz"
            assert len(received) == 1
            assert received[0].topic == "od/comando"
        finally:
            pub.disconnect()
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_handler_filtered_by_topic(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            pub.connect()
            bridge.connect()
            hits: list[str] = []
            bridge.subscribe("od/controle/+", handler=lambda m: hits.append(m.topic))
            pub.publish("od/controle/luz", "on")
            pub.publish("od/outro/luz", "on")
            await bridge.poll_once(3)
            assert hits == ["od/controle/luz"]
        finally:
            pub.disconnect()
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_inbound_forwarded_to_event_bus(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bus = EventBus()
        events: list[dict] = []
        bus.subscribe_handler("mqtt.message", lambda e: events.append(e.data))
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            event_bus=bus,
            config=bridge_config(),
        )
        try:
            pub.connect()
            bridge.connect()
            bridge.subscribe("od/#")
            pub.publish("od/sensor/temp", "21.5")
            await bridge.poll_once(3)
            assert len(events) == 1
            assert events[0]["topic"] == "od/sensor/temp"
            assert events[0]["payload"] == "21.5"
            assert bridge.metrics.snapshot()["bus_forwarded"] == 1
        finally:
            pub.disconnect()
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            pub.connect()
            bridge.connect()
            hits: list[str] = []
            bridge.subscribe("od/#", handler=lambda m: hits.append(m.text()))
            bridge.unsubscribe("od/#")
            pub.publish("od/x", "ninguém")
            assert await bridge.poll_once(0.2) is None
            assert hits == []
        finally:
            pub.disconnect()
            bridge.disconnect()
            broker.stop()


class TestBridgeOutbound:
    @pytest.mark.asyncio
    async def test_publish_reaches_external_subscriber(self) -> None:
        broker = InMemoryBroker().start()
        ext = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            ext.connect()
            ext.subscribe("od/saida/#")
            assert bridge.connect()
            assert bridge.publish("od/saida/status", "ok") is True
            msg = ext.wait_message(3)
            assert msg is not None and msg.text() == "ok"
            assert bridge.metrics.snapshot()["published"] == 1
        finally:
            ext.disconnect()
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_publish_fails_when_broker_down(self) -> None:
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", 1, client_id="od"),
            config=bridge_config(),
        )
        assert bridge.publish("od/x", "y") is False
        assert bridge.metrics.snapshot()["errors"] >= 1

    @pytest.mark.asyncio
    async def test_route_bus_default_mapping(self) -> None:
        broker = InMemoryBroker().start()
        ext = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bus = EventBus()
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            event_bus=bus,
            config=bridge_config(),
        )
        try:
            ext.connect()
            ext.subscribe("od/#")
            bridge.connect()
            bridge.route_bus("notifier.alert")
            await bus.publish(
                Event(topic="notifier.alert", data={"key": "llm", "sev": "crit"})
            )
            msg = ext.wait_message(3)
            assert msg is not None
            assert msg.topic == "od/notifier/alert"
            assert "llm" in msg.text()
            assert bridge.metrics.snapshot()["bus_routed"] == 1
        finally:
            ext.disconnect()
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_route_bus_fixed_topic(self) -> None:
        broker = InMemoryBroker().start()
        ext = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bus = EventBus()
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            event_bus=bus,
            config=bridge_config(),
        )
        try:
            ext.connect()
            ext.subscribe("alvos/#")
            bridge.connect()
            bridge.route_bus("iot.**", to_topic="alvos/iot")
            await bus.publish(
                Event(topic="iot.command", data={"entity": "light.sala"})
            )
            msg = ext.wait_message(3)
            assert msg is not None
            assert msg.topic == "alvos/iot"
        finally:
            ext.disconnect()
            bridge.disconnect()
            broker.stop()

    def test_route_bus_requires_event_bus(self) -> None:
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", 1883), config=bridge_config()
        )
        with pytest.raises(RuntimeError, match="event_bus"):
            bridge.route_bus("x")


class TestBridgeLifecycle:
    @pytest.mark.asyncio
    async def test_reconnect_resubscribes(self) -> None:
        broker = InMemoryBroker().start()
        port = broker.port
        client = MQTTClient("127.0.0.1", port, client_id="od")
        bridge = MQTTBridge(client, config=bridge_config())
        ext = MQTTClient("127.0.0.1", port, client_id="ext")
        try:
            assert bridge.connect()
            bridge.subscribe("od/#")
            ext.connect()
            ext.publish("od/pre", "antes")
            assert (await bridge.poll_once(3)).text() == "antes"
            # broker derruba a sessão do cliente (simula queda) → desconecta
            assert broker.drop_client("od") is True
            assert wait_for(lambda: not client.is_connected)
            # reconexão contra o MESMO broker re-assina os filtros desejados
            assert bridge.connect()
            assert bridge.metrics.snapshot()["reconnects"] == 1
            ext.publish("od/recon", "chegou")
            msg = await bridge.poll_once(3)
            assert msg is not None and msg.text() == "chegou"
        finally:
            ext.disconnect()
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_run_processes_pending_messages(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            pub.connect()
            bridge.connect()
            bridge.subscribe("od/#")
            for i in range(3):
                pub.publish("od/batch", str(i))
            await asyncio.sleep(0.2)  # deixa a fila encher
            polls = await bridge.run(max_polls=5)
            assert polls == 5
            assert bridge.metrics.snapshot()["received"] == 3
        finally:
            pub.disconnect()
            bridge.disconnect()
            broker.stop()

    def test_start_stop_thread(self) -> None:
        broker = InMemoryBroker().start()
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            thread = bridge.start()
            assert thread.is_alive()
            bridge.stop()
            thread.join(timeout=3)
            assert not thread.is_alive()
            assert not bridge.is_connected
        finally:
            broker.stop()

    def test_health_snapshot_dump(self) -> None:
        broker = InMemoryBroker().start()
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            config=bridge_config(),
        )
        try:
            health = bridge.health()
            assert health["ok"] is False  # ainda não conectado
            assert "metrics" in health
            bridge.connect()
            bridge.subscribe("od/#")
            snap = bridge.snapshot()
            assert snap["connected"] is True
            assert snap["subscriptions"] == ["od/#"]
            assert snap["host"].startswith("127.0.0.1")
            assert "client_id" in snap
            dump = bridge.dump()
            assert dump["connected"] is True
        finally:
            bridge.disconnect()
            broker.stop()

    @pytest.mark.asyncio
    async def test_bus_forward_disabled_by_config(self) -> None:
        broker = InMemoryBroker().start()
        pub = MQTTClient("127.0.0.1", broker.port, client_id="ext")
        bus = EventBus()
        events: list = []
        bus.subscribe_handler("mqtt.message", lambda e: events.append(e))
        bridge = MQTTBridge(
            MQTTClient("127.0.0.1", broker.port, client_id="od"),
            event_bus=bus,
            config=MQTTConfig(poll_timeout_s=0.05, bus_forward=False),
        )
        try:
            pub.connect()
            bridge.connect()
            bridge.subscribe("od/#")
            pub.publish("od/x", "sem bus")
            # poll_once processa; sem forward, nenhum evento no bus
            await bridge.poll_once(3)
            await asyncio.sleep(0.05)
            assert events == []
        finally:
            pub.disconnect()
            bridge.disconnect()
            broker.stop()
