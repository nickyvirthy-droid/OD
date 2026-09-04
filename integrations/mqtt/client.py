"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/mqtt/client.py
Descrição: MQTT Bridge (Fase 5, item 5.5) — MQTTClient: cliente MQTT 3.1.1
           em stdlib puro (socket), sem paho-mqtt. Conecta em qualquer
           broker MQTT 3.1.1 (Mosquitto, etc.): CONNECT/CONNACK validado,
           PUBLISH QoS 0 e 1 com PUBACK síncrono, SUBSCRIBE/SUBACK com
           grant por filtro, UNSUBSCRIBE, keepalive (PINGREQ) em thread,
           thread de leitura com fila de mensagens + callbacks e detecção
           de desconexão. Timeouts configuráveis para determinismo.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - OASIS MQTT 3.1.1 (ISO/IEC 20922)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.5
"""

from __future__ import annotations

import os
import queue
import random
import socket
import struct
import threading
from typing import Callable, Optional, Union

from integrations.mqtt import protocol as p

__signature__ = "OD // CORE"

DEFAULT_KEEPALIVE = 60
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_ACK_TIMEOUT = 10.0

MessageCallback = Callable[[p.MqttMessage], None]


class MQTTClient:
    """Cliente MQTT 3.1.1 síncrono (bloqueante) sobre socket stdlib.

    Uso típico:
        client = MQTTClient("127.0.0.1", 1883, client_id="od-bridge")
        client.connect()
        client.subscribe([("od/#", 1)])
        client.publish("od/teste", b"ola")
        msg = client.wait_message(timeout=5.0)
        client.disconnect()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        *,
        client_id: Optional[str] = None,
        keepalive: int = DEFAULT_KEEPALIVE,
        clean_session: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id or (
            f"od-{os.getpid()}-{random.randrange(1 << 20):05x}"
        )
        self.keepalive = max(0, int(keepalive))
        self.clean_session = clean_session
        self.username = username
        self.password = password
        self._connect_timeout = connect_timeout
        self._ack_timeout = ack_timeout
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._reader: Optional[threading.Thread] = None
        self._pinger: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._inbox: "queue.Queue[p.MqttMessage]" = queue.Queue()
        self._pending: dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self._next_pid = 1
        self._pid_lock = threading.Lock()
        self.on_message: list[MessageCallback] = []
        self.on_disconnect: list[Callable[[], None]] = []

    # -- Conexão -------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected and self._sock is not None

    def connect(self) -> None:
        """Abre o socket, faz o handshake e sobe reader + keepalive."""
        if self.is_connected:
            return
        sock = socket.create_connection(
            (self.host, self.port), timeout=self._connect_timeout
        )
        sock.settimeout(None)
        # Registra o sock ANTES do handshake: se disconnect() rodar durante
        # a conexão, ele fecha este sock e o handshake aborta (sem isso, um
        # disconnect durante o connect deixava _connected=True para sempre)
        self._sock = sock
        packet = p.encode_connect(
            self.client_id,
            keepalive=self.keepalive,
            clean_session=self.clean_session,
            username=self.username,
            password=self.password,
        )
        sock.sendall(packet)
        try:
            ptype, _flags, body = p.read_packet(sock)
        except p.MQTTProtocolError:
            self._sock = None
            sock.close()
            raise p.MQTTError("broker fechou durante o handshake")
        if ptype != p.PACKET_CONNACK:
            self._sock = None
            sock.close()
            raise p.MQTTError("broker não respondeu CONNACK")
        _session_present, code = p.decode_connack(body)
        if code != p.CONNACK_ACCEPTED:
            self._sock = None
            sock.close()
            raise p.MQTTConnectError(code)
        self._connected = True
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if self.keepalive > 0:
            self._pinger = threading.Thread(target=self._ping_loop, daemon=True)
            self._pinger.start()

    def disconnect(self) -> None:
        """Envia DISCONNECT (best-effort) e fecha a conexão."""
        self._stop.set()
        sock, self._sock = self._sock, None
        was_connected = self._connected
        self._connected = False
        if sock is not None:
            try:
                sock.sendall(p.encode_disconnect())
            except OSError:
                pass
            try:
                # shutdown antes do close acorda recv bloqueado do reader
                # (e do lado do broker) — sem isso a thread pode travar
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if was_connected:
            for cb in list(self.on_disconnect):
                try:
                    cb()
                except Exception:  # pragma: no cover — callback quebrou
                    pass

    def close(self) -> None:
        self.disconnect()

    # -- Leitura -------------------------------------------------------------

    def _read_loop(self) -> None:
        sock = self._sock
        while not self._stop.is_set() and sock is not None:
            try:
                ptype, flags, body = p.read_packet(sock)
            except (OSError, p.MQTTProtocolError):
                break
            try:
                self._handle_packet(ptype, flags, body)
            except Exception:  # pragma: no cover — dispatch nunca quebra o loop
                pass
        # Conexão caiu sem DISCONNECT explícito
        if not self._stop.is_set():
            self._connected = False
            for cb in list(self.on_disconnect):
                try:
                    cb()
                except Exception:  # pragma: no cover
                    pass

    def _handle_packet(self, ptype: int, flags: int, body: bytes) -> None:
        if ptype == p.PACKET_PUBLISH:
            message, packet_id = p.decode_publish(flags, body)
            if message.qos == p.QOS_AT_LEAST_ONCE and packet_id is not None:
                self._send_raw(p.encode_puback(packet_id))
            self._inbox.put(message)
            for cb in list(self.on_message):
                try:
                    cb(message)
                except Exception:  # pragma: no cover — callback quebrou
                    pass
        elif ptype in (p.PACKET_SUBACK, p.PACKET_PUBACK, p.PACKET_UNSUBACK):
            packet_id = p.decode_packet_id(body)
            with self._pending_lock:
                waiter = self._pending.pop(packet_id, None)
            if waiter is not None:
                if ptype == p.PACKET_SUBACK:
                    waiter["result"] = p.decode_suback(body)[1]
                waiter["event"].set()
        elif ptype == p.PACKET_PINGRESP:
            pass  # broker vivo — nada a fazer

    def _send_raw(self, data: bytes) -> None:
        sock = self._sock
        if sock is None:
            raise p.MQTTError("cliente desconectado")
        sock.sendall(data)

    def _next_packet_id(self) -> int:
        with self._pid_lock:
            packet_id = self._next_pid
            self._next_pid = (self._next_pid % 0xFFFF) + 1
            return packet_id

    # -- Keepalive -----------------------------------------------------------

    def _ping_loop(self) -> None:
        interval = max(1, self.keepalive // 2)
        while not self._stop.wait(interval):
            try:
                self._send_raw(p.encode_pingreq())
            except (OSError, p.MQTTError):
                break

    # -- Mensagens recebidas -------------------------------------------------

    def wait_message(self, timeout: Optional[float] = None) -> Optional[p.MqttMessage]:
        """Bloqueia até chegar uma mensagem (None em timeout)."""
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    # -- Publicação ----------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: Union[bytes, str] = b"",
        *,
        qos: int = p.QOS_AT_MOST_ONCE,
        retain: bool = False,
    ) -> bool:
        """Publica uma mensagem. QoS 1 aguarda o PUBACK do broker.

        Returns:
            True se enviado (QoS 1: confirmado). Raises em erro.
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if qos == p.QOS_AT_MOST_ONCE:
            self._send_raw(
                p.encode_publish(topic, payload, qos=qos, retain=retain)
            )
            return True
        packet_id = self._next_packet_id()
        waiter: dict = {"event": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[packet_id] = waiter
        self._send_raw(
            p.encode_publish(
                topic, payload, qos=qos, retain=retain, packet_id=packet_id
            )
        )
        if not waiter["event"].wait(self._ack_timeout):
            with self._pending_lock:
                self._pending.pop(packet_id, None)
            raise p.MQTTError("PUBACK não recebido (timeout)")
        return True

    # -- Assinatura ----------------------------------------------------------

    def subscribe(
        self, filters: Union[str, list[tuple[str, int]]], qos: int = p.QOS_AT_LEAST_ONCE
    ) -> list[int]:
        """Assina filtros e aguarda o SUBACK.

        Args:
            filters: Um filtro "od/#" (com qos do argumento) ou lista de
                     tuplas (filtro, qos).

        Returns:
            Códigos concedidos pelo broker, na ordem dos filtros.
        """
        if isinstance(filters, str):
            spec: list[tuple[str, int]] = [(filters, qos)]
        else:
            spec = list(filters)
        if not spec:
            return []
        packet_id = self._next_packet_id()
        waiter: dict = {"event": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[packet_id] = waiter
        self._send_raw(p.encode_subscribe(spec, packet_id))
        if not waiter["event"].wait(self._ack_timeout):
            with self._pending_lock:
                self._pending.pop(packet_id, None)
            raise p.MQTTError("SUBACK não recebido (timeout)")
        return list(waiter["result"] or [])

    def unsubscribe(self, filters: Union[str, list[str]]) -> bool:
        """Cancela assinaturas e aguarda o UNSUBACK."""
        if isinstance(filters, str):
            spec = [filters]
        else:
            spec = list(filters)
        if not spec:
            return True
        packet_id = self._next_packet_id()
        waiter: dict = {"event": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[packet_id] = waiter
        self._send_raw(p.encode_unsubscribe(spec, packet_id))
        if not waiter["event"].wait(self._ack_timeout):
            with self._pending_lock:
                self._pending.pop(packet_id, None)
            raise p.MQTTError("UNSUBACK não recebido (timeout)")
        return True

    # -- Inspeção ------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "connected": self.is_connected,
            "keepalive": self.keepalive,
            "pending_acks": len(self._pending),
            "inbox_size": self._inbox.qsize(),
        }
