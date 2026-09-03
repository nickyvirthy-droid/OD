"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/mqtt/broker.py
Descrição: MQTT Bridge (Fase 5, item 5.5) — InMemoryBroker: broker MQTT
           3.1.1 mínimo em processo (threads + TCP loopback) que fala o
           mesmo protocolo wire de integrations/mqtt/protocol.py. Usado
           para testes determinísticos e desenvolvimento sem broker
           externo (mesmo papel do InMemoryHAServer no Home Assistant):
           CONNECT/CONNACK, SUBSCRIBE/SUBACK com curingas (+/#), QoS 0 e 1
           com PUBACK, UNSUBSCRIBE/UNSUBACK, retenção (retained), PING e
           roteamento entre múltiplos clientes.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - OASIS MQTT 3.1.1 (ISO/IEC 20922)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.5

Decisões registradas (ver CHANGELOG):
  - QoS 2 não suportado: SUBACK devolve 0x80 (falha) para o filtro
  - Sem sessões persistentes entre conexões (clean session sempre)
  - Roteamento entrega no QoS mínimo entre o da publicação e o concedido
    ao assinante (regra MQTT-3.3.5-1)
"""

from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional

from integrations.mqtt import protocol as p

__signature__ = "OD // CORE"


@dataclass(slots=True)
class BrokerStats:
    """Contadores do broker fake (assertivas de teste)."""

    connections: int = 0
    subscriptions: int = 0
    messages_routed: int = 0
    pingreq: int = 0

    def snapshot(self) -> dict:
        return {
            "connections": self.connections,
            "subscriptions": self.subscriptions,
            "messages_routed": self.messages_routed,
            "pingreq": self.pingreq,
        }


class _ClientSession:
    """Estado de uma conexão de cliente no broker."""

    def __init__(self, client_id: str, sock: socket.socket) -> None:
        self.client_id = client_id
        self.sock = sock
        self.filters: list[tuple[str, int]] = []
        self.write_lock = threading.Lock()
        self.next_pid = 1

    def subscribe(self, filter_: str, qos: int) -> None:
        self.filters.append((filter_, qos))

    def unsubscribe(self, filter_: str) -> None:
        self.filters = [
            (f, q) for (f, q) in self.filters if f != filter_
        ]

    def matches(self, topic: str) -> Optional[int]:
        """QoS concedido se algum filtro casa com o tópico."""
        granted: Optional[int] = None
        for filter_, qos in self.filters:
            if p.topic_matches(filter_, topic):
                if granted is None or qos > granted:
                    granted = qos
        return granted

    def send(self, data: bytes) -> None:
        with self.write_lock:
            self.sock.sendall(data)


class InMemoryBroker:
    """Broker MQTT 3.1.1 em processo para testes/dev offline.

    Uso típico:
        broker = InMemoryBroker()
        broker.start()
        client = MQTTClient("127.0.0.1", broker.port, client_id="c1")
        client.connect()
        ...
        broker.stop()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        allow: Optional[callable] = None,
    ) -> None:
        self.host = host
        self._port = port
        # allow(client_id) -> bool: recusa conexão (CONNACK 5) se False
        self._allow = allow
        self.stats = BrokerStats()
        self.retained: dict[str, tuple[bytes, int]] = {}
        self._sessions: dict[int, _ClientSession] = {}
        self._sessions_lock = threading.Lock()
        self._server: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._closed = True

    # -- Lifecycle -----------------------------------------------------------

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("broker não iniciado")
        return self._server.getsockname()[1]

    @property
    def connected_clients(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)

    def start(self) -> "InMemoryBroker":
        if not self._closed:
            return self
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self._port))
        self._server.listen(16)
        self._server.settimeout(0.5)
        self._closed = False
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True
        )
        self._accept_thread.start()
        return self

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                session.sock.close()
            except OSError:
                pass
        self._server = None

    def close(self) -> None:
        self.stop()

    # -- Accept loop ---------------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._closed:
            try:
                sock, _addr = self._server.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(None)
            threading.Thread(
                target=self._handle_client, args=(sock,), daemon=True
            ).start()

    def _handle_client(self, sock: socket.socket) -> None:
        session: Optional[_ClientSession] = None
        try:
            ptype, _flags, body = p.read_packet(sock)
            if ptype != p.PACKET_CONNECT:
                return  # primeira mensagem precisa ser CONNECT (MQTT-3.1.0-1)
            session = self._establish(sock, body)
            if session is None:
                return
            while True:
                ptype, flags, body = p.read_packet(sock)
                if not self._dispatch(session, ptype, flags, body):
                    break
        except (OSError, p.MQTTProtocolError):
            pass
        finally:
            self._drop(session, sock)

    def _establish(
        self, sock: socket.socket, body: bytes
    ) -> Optional[_ClientSession]:
        """Processa CONNECT e devolve a sessão (ou None se recusado)."""
        # Variável: nome "MQTT"(6) + level(1) + flags(1) + keepalive(2)
        offset = len(p.PROTOCOL_NAME) + 1
        if offset + 3 > len(body):
            return None
        flags = body[offset]
        offset += 3
        client_id, offset = p._decode_utf8(body, offset)  # noqa: SLF001
        if flags & p.FLAG_USERNAME:
            _username, offset = p._decode_utf8(body, offset)
        if flags & p.FLAG_PASSWORD:
            if offset + 2 > len(body):
                return None
            (size,) = struct.unpack(">H", body[offset:offset + 2])
            offset += 2 + size
        del offset
        if self._allow is not None and not self._allow(client_id):
            sock.sendall(
                bytes([p.PACKET_CONNACK << 4, 2, 0, p.CONNACK_REFUSED_UNAUTHORIZED])
            )
            return None
        sock.sendall(bytes([p.PACKET_CONNACK << 4, 2, 0, p.CONNACK_ACCEPTED]))
        session = _ClientSession(client_id, sock)
        with self._sessions_lock:
            self._sessions[id(sock)] = session
        self.stats.connections += 1
        return session

    def _drop(self, session: Optional[_ClientSession], sock: socket.socket) -> None:
        with self._sessions_lock:
            self._sessions.pop(id(sock), None)
        if session is not None:
            try:
                session.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                session.sock.close()
            except OSError:
                pass

    # -- Dispatch por tipo ---------------------------------------------------

    def _dispatch(self, session: _ClientSession, ptype: int, flags: int,
                  body: bytes) -> bool:
        if ptype == p.PACKET_PUBLISH:
            self._route_publish(session, flags, body)
        elif ptype == p.PACKET_SUBSCRIBE:
            self._handle_subscribe(session, body)
        elif ptype == p.PACKET_UNSUBSCRIBE:
            self._handle_unsubscribe(session, body)
        elif ptype == p.PACKET_PUBACK:
            pass  # QoS 1 entregue e confirmado — nada a fazer
        elif ptype == p.PACKET_PINGREQ:
            self.stats.pingreq += 1
            session.send(p.encode_pingreq())
        elif ptype == p.PACKET_DISCONNECT:
            return False
        # Tipos desconhecidos: ignora (permissivo)
        return True

    # -- SUBSCRIBE / UNSUBSCRIBE ---------------------------------------------

    def _handle_subscribe(self, session: _ClientSession, body: bytes) -> None:
        if len(body) < 2:
            return
        packet_id = struct.unpack(">H", body[:2])[0]
        offset = 2
        grants: list[int] = []
        while offset < len(body):
            try:
                filter_, offset = p._decode_utf8(body, offset)  # noqa: SLF001
                if offset >= len(body):
                    return
                requested = body[offset]
                offset += 1
            except (p.MQTTProtocolError, UnicodeDecodeError):
                return
            if requested == p.QOS_EXACTLY_ONCE:
                grants.append(p.SUBACK_FAILURE)  # QoS 2 não suportado
                continue
            session.subscribe(filter_, requested)
            grants.append(requested)
            self.stats.subscriptions += 1
            # Retained: entrega mensagens guardadas que casam (MQTT-3.8.4-3)
            for topic, (payload, qos) in list(self.retained.items()):
                if p.topic_matches(filter_, topic):
                    self._deliver(
                        session, topic, payload,
                        qos=min(qos, requested),
                        retain=True,
                    )
        session.send(
            bytes([p.PACKET_SUBACK << 4, 2 + len(grants)])
            + struct.pack(">H", packet_id)
            + bytes(grants)
        )

    def _handle_unsubscribe(self, session: _ClientSession, body: bytes) -> None:
        if len(body) < 2:
            return
        packet_id = struct.unpack(">H", body[:2])[0]
        offset = 2
        removed = 0
        while offset < len(body):
            try:
                filter_, offset = p._decode_utf8(body, offset)  # noqa: SLF001
            except (p.MQTTProtocolError, UnicodeDecodeError):
                break
            before = len(session.filters)
            session.unsubscribe(filter_)
            removed += before - len(session.filters)
        self.stats.subscriptions -= removed
        session.send(
            bytes([p.PACKET_UNSUBACK << 4, 2])
            + struct.pack(">H", packet_id)
        )

    # -- PUBLISH / roteamento -------------------------------------------------

    def _route_publish(self, session: _ClientSession, flags: int,
                       body: bytes) -> None:
        qos = (flags >> 1) & 0x03
        retain = bool(flags & 0x01)
        try:
            topic, offset = p._decode_utf8(body, 0)  # noqa: SLF001
            packet_id = None
            if qos > 0:
                if offset + 2 > len(body):
                    return
                packet_id = struct.unpack(">H", body[offset:offset + 2])[0]
                offset += 2
            payload = body[offset:]
        except (p.MQTTProtocolError, UnicodeDecodeError):
            return
        if qos == p.QOS_AT_LEAST_ONCE and packet_id is not None:
            session.send(p.encode_puback(packet_id))
        if retain:
            if payload:
                self.retained[topic] = (payload, qos)
            else:
                self.retained.pop(topic, None)  # retenção limpa (MQTT-3.3.1-6)
        self.stats.messages_routed += 1
        with self._sessions_lock:
            targets = list(self._sessions.values())
        for target in targets:
            granted = target.matches(topic)
            if granted is None:
                continue
            deliver_qos = min(qos, granted)
            self._deliver(
                target, topic, payload, qos=deliver_qos, retain=retain
            )

    def _deliver(
        self, session: _ClientSession, topic: str, payload: bytes,
        *, qos: int, retain: bool,
    ) -> None:
        packet_id = None
        if qos > 0:
            packet_id = session.next_pid
            session.next_pid += 1
        try:
            session.send(
                p.encode_publish(
                    topic, payload, qos=qos, retain=retain,
                    packet_id=packet_id,
                )
            )
        except OSError:
            return  # assinante desconectou — roteamento segue

    def drop_client(self, client_id: str) -> bool:
        """Derruba a sessão de um cliente (simula queda de conexão)."""
        with self._sessions_lock:
            target = next(
                (
                    s for s in self._sessions.values()
                    if s.client_id == client_id
                ),
                None,
            )
            if target is None:
                return False
            self._sessions.pop(id(target.sock), None)
        try:
            target.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            target.sock.close()
        except OSError:
            pass
        return True

    # -- Inspeção ------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._sessions_lock:
            sessions = [
                {
                    "client_id": s.client_id,
                    "filters": [f for f, _ in s.filters],
                }
                for s in self._sessions.values()
            ]
        return {
            "host": self.host,
            "port": self.port if self._server else None,
            "connected": self.connected_clients,
            "clients": sessions,
            "stats": self.stats.snapshot(),
            "retained_topics": sorted(self.retained),
        }

    @property
    def retained_count(self) -> int:
        return len(self.retained)
