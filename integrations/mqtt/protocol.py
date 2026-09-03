"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/mqtt/protocol.py
Descrição: MQTT Bridge (Fase 5, item 5.5) — codec do protocolo MQTT 3.1.1
           em stdlib puro (sem paho-mqtt): codificação/decodificação dos
           pacotes CONNECT/CONNACK, PUBLISH (QoS 0 e 1), SUBSCRIBE/SUBACK,
           UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP e DISCONNECT, com
           validação de tópicos e matching de filtros com curingas
           (MQTT-3.3.5: '+' nível único, '#' multi-nível final).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus config/mosquitto + uso de MQTT via paho-mqtt (substituído por
    protocolo wire próprio — projeto é 100% stdlib)
  - OASIS MQTT 3.1.1 (ISO/IEC 20922)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.5

Decisões registradas (ver CHANGELOG):
  - Suporte a QoS 0 e QoS 1 (PUBACK). QoS 2 → MQTTError (fora do escopo;
    o broker Mosquitto degrada publicações QoS 2 para o máximo suportado
    pelo assinante em QoS 0/1)
  - Sem Last Will/TESTAMENTO na primeira versão (aditivo futuro)
  - Payload tratado como bytes; decodificação utf-8 é helper opcional
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

__signature__ = "OD // CORE"

# ---------------------------------------------------------------------------
# Constantes MQTT 3.1.1
# ---------------------------------------------------------------------------

PROTOCOL_NAME = b"\x00\x04MQTT"
PROTOCOL_LEVEL = 4

# Tipos de pacote (nibble alto do primeiro byte)
PACKET_CONNECT = 1
PACKET_CONNACK = 2
PACKET_PUBLISH = 3
PACKET_PUBACK = 4
PACKET_SUBSCRIBE = 8
PACKET_SUBACK = 9
PACKET_UNSUBSCRIBE = 10
PACKET_UNSUBACK = 11
PACKET_PINGREQ = 12
PACKET_PINGRESP = 13
PACKET_DISCONNECT = 14

QOS_AT_MOST_ONCE = 0
QOS_AT_LEAST_ONCE = 1
QOS_EXACTLY_ONCE = 2

# Códigos de retorno do CONNACK (MQTT-3.2.2.3)
CONNACK_ACCEPTED = 0
CONNACK_REFUSED_PROTOCOL = 1
CONNACK_REFUSED_IDENTIFIER = 2
CONNACK_REFUSED_SERVER = 3
CONNACK_REFUSED_CREDENTIALS = 4
CONNACK_REFUSED_UNAUTHORIZED = 5

CONNACK_REASONS = {
    CONNACK_ACCEPTED: "conexão aceita",
    CONNACK_REFUSED_PROTOCOL: "versão de protocolo inaceitável",
    CONNACK_REFUSED_IDENTIFIER: "identificador de cliente rejeitado",
    CONNACK_REFUSED_SERVER: "servidor indisponível",
    CONNACK_REFUSED_CREDENTIALS: "usuário/senha inválidos",
    CONNACK_REFUSED_UNAUTHORIZED: "não autorizado",
}

# Flags de CONNECT
FLAG_CLEAN_SESSION = 0x02
FLAG_WILL = 0x04
FLAG_WILL_QOS = 0x18
FLAG_WILL_RETAIN = 0x20
FLAG_PASSWORD = 0x40
FLAG_USERNAME = 0x80

SUBACK_FAILURE = 0x80
MAX_TOPIC_LENGTH = 65535
MAX_REMAINING_LENGTH = 268435455  # 256 MB (4 bytes de comprimento)


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------

class MQTTError(Exception):
    """Erro base do protocolo/cliente MQTT."""


class MQTTConnectError(MQTTError):
    """Conexão recusada pelo broker (CONNACK com código != 0)."""

    def __init__(self, code: int, message: str = "") -> None:
        self.code = code
        self.reason = CONNACK_REASONS.get(code, f"código {code}")
        super().__init__(message or f"broker recusou a conexão: {self.reason}")


class MQTTProtocolError(MQTTError):
    """Pacote inválido ou violação de protocolo."""


# ---------------------------------------------------------------------------
# Mensagem
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MqttMessage:
    """Mensagem PUBLISH decodificada.

    Attributes:
        topic:   Tópico da mensagem.
        payload: Conteúdo bruto (bytes).
        qos:     Nível de QoS com que foi recebida (0 ou 1).
        retain:  Flag de retenção.
        dup:     Flag de reentrega.
    """

    topic: str
    payload: bytes
    qos: int = QOS_AT_MOST_ONCE
    retain: bool = False
    dup: bool = False

    def text(self, fallback: str = "") -> str:
        """Payload como texto utf-8 (fallback quando indecodificável)."""
        try:
            return self.payload.decode("utf-8")
        except UnicodeDecodeError:
            return fallback

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "payload": self.text(),
            "qos": self.qos,
            "retain": self.retain,
            "dup": self.dup,
        }


# ---------------------------------------------------------------------------
# Validação de tópicos e filtros
# ---------------------------------------------------------------------------

def validate_topic(topic: str) -> None:
    """Valida um tópico de publicação (MQTT-4.7.3 / MQTT-3.3.2)."""
    if not topic or len(topic) > MAX_TOPIC_LENGTH:
        raise MQTTError("tópico deve ter entre 1 e 65535 bytes")
    if "#" in topic or "+" in topic:
        raise MQTTError("tópico de publicação não pode conter curingas")
    if any(ord(ch) in (0x00,) for ch in topic):
        raise MQTTError("tópico contém caractere nulo")


def validate_filter(filter_: str) -> None:
    """Valida um filtro de assinatura com curingas (MQTT-4.7.1)."""
    if not filter_ or len(filter_) > MAX_TOPIC_LENGTH:
        raise MQTTError("filtro deve ter entre 1 e 65535 bytes")
    levels = filter_.split("/")
    for index, level in enumerate(levels):
        if "#" in level:
            # '#' só é permitido como último nível e sozinho
            if level != "#" or index != len(levels) - 1:
                raise MQTTError("'#' deve ser o último nível e isolado")
        if "+" in level and level != "+":
            raise MQTTError("'+' deve ocupar um nível inteiro")


def topic_matches(filter_: str, topic: str) -> bool:
    """Verifica se um tópico casa com um filtro de assinatura.

    Regras MQTT-4.7.1/4.7.2:
      - '+' casa exatamente um nível
      - '#' casa zero ou mais níveis e deve ser o último
    """
    filter_levels = filter_.split("/")
    topic_levels = topic.split("/")
    fi, ti = 0, 0
    while fi < len(filter_levels):
        f = filter_levels[fi]
        if f == "#":
            return True  # casa o resto (inclusive vazio)
        if ti >= len(topic_levels):
            return False
        if f != "+" and f != topic_levels[ti]:
            return False
        fi += 1
        ti += 1
    return ti == len(topic_levels)


# ---------------------------------------------------------------------------
# Comprimento remanescente (MQTT-2.2.3)
# ---------------------------------------------------------------------------

def encode_remaining(length: int) -> bytes:
    """Codifica o comprimento remanescente em 1-4 bytes."""
    if not 0 <= length <= MAX_REMAINING_LENGTH:
        raise MQTTProtocolError("comprimento remanescente fora do limite")
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            out.append(digit | 0x80)
        else:
            out.append(digit)
            return bytes(out)


def _read_remaining_length(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decodifica o comprimento remanescente; devolve (valor, bytes_lidos)."""
    multiplier = 1
    value = 0
    pos = offset
    while True:
        if pos >= len(data):
            raise MQTTProtocolError("pacote truncado no comprimento")
        digit = data[pos]
        pos += 1
        value += (digit & 0x7F) * multiplier
        if digit & 0x80 == 0:
            return value, pos - offset
        multiplier *= 128
        if multiplier > 128 ** 4:
            raise MQTTProtocolError("comprimento remanescente malformado")


# ---------------------------------------------------------------------------
# Utilitários de payload
# ---------------------------------------------------------------------------

def _encode_utf8(text: str) -> bytes:
    """String utf-8 com prefixo de 2 bytes (MQTT-1.5.3)."""
    raw = text.encode("utf-8")
    if len(raw) > MAX_TOPIC_LENGTH:
        raise MQTTError("string excede 65535 bytes")
    return struct.pack(">H", len(raw)) + raw


def _decode_utf8(data: bytes, offset: int = 0) -> tuple[str, int]:
    """Lê string utf-8 prefixada; devolve (valor, próximo_offset)."""
    if offset + 2 > len(data):
        raise MQTTProtocolError("string truncada")
    (size,) = struct.unpack(">H", data[offset:offset + 2])
    offset += 2
    if offset + size > len(data):
        raise MQTTProtocolError("string truncada no conteúdo")
    return data[offset:offset + size].decode("utf-8"), offset + size


def read_packet(sock) -> tuple[int, int, bytes]:
    """Lê um pacote completo do socket.

    Returns:
        Tupla (tipo, flags, corpo) — corpo = variável + payload.
    """
    first = _recv_exact(sock, 1)[0]
    ptype = first >> 4
    flags = first & 0x0F
    # Comprimento remanescente (varint, até 4 bytes)
    multiplier = 1
    length = 0
    for _ in range(4):
        digit = _recv_exact(sock, 1)[0]
        length += (digit & 0x7F) * multiplier
        if digit & 0x80 == 0:
            break
        multiplier *= 128
    else:
        raise MQTTProtocolError("comprimento remanescente malformado")
    body = _recv_exact(sock, length) if length else b""
    return ptype, flags, body


def _recv_exact(sock, size: int) -> bytes:
    """Recebe exatamente `size` bytes (loop até completar)."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise MQTTProtocolError("conexão fechada durante leitura")
        chunks.extend(chunk)
    return bytes(chunks)


# ---------------------------------------------------------------------------
# Codificação de pacotes (cliente → broker)
# ---------------------------------------------------------------------------

def encode_connect(
    client_id: str,
    *,
    keepalive: int = 60,
    clean_session: bool = True,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> bytes:
    """Monta o pacote CONNECT (MQTT-3.1)."""
    flags = FLAG_CLEAN_SESSION if clean_session else 0
    if username is not None:
        flags |= FLAG_USERNAME
    if password is not None:
        flags |= FLAG_PASSWORD
    variable = (
        PROTOCOL_NAME
        + bytes([PROTOCOL_LEVEL, flags])
        + struct.pack(">H", int(keepalive))
    )
    payload = _encode_utf8(client_id)
    if username is not None:
        payload += _encode_utf8(username)
    if password is not None:
        raw = password.encode("utf-8")
        payload += struct.pack(">H", len(raw)) + raw
    body = variable + payload
    return bytes([PACKET_CONNECT << 4]) + encode_remaining(len(body)) + body


def encode_publish(
    topic: str,
    payload: bytes,
    *,
    qos: int = QOS_AT_MOST_ONCE,
    retain: bool = False,
    packet_id: Optional[int] = None,
    dup: bool = False,
) -> bytes:
    """Monta o pacote PUBLISH (MQTT-3.3)."""
    validate_topic(topic)
    if qos not in (QOS_AT_MOST_ONCE, QOS_AT_LEAST_ONCE):
        raise MQTTError("QoS 2 não suportado — use QoS 0 ou 1")
    if qos == QOS_AT_MOST_ONCE:
        dup = False  # dup só se aplica a QoS > 0 (MQTT-3.3.1-2)
    flags = (1 if dup else 0) << 3 | qos << 1 | (1 if retain else 0)
    body = _encode_utf8(topic)
    if qos > QOS_AT_MOST_ONCE:
        if packet_id is None:
            raise MQTTError("QoS 1 exige packet_id")
        body += struct.pack(">H", packet_id)
    body += payload
    return bytes([PACKET_PUBLISH << 4 | flags]) + encode_remaining(len(body)) + body


def encode_subscribe(
    filters: list[tuple[str, int]], packet_id: int
) -> bytes:
    """Monta o pacote SUBSCRIBE (MQTT-3.8) com flags obrigatórias 0x2."""
    body = struct.pack(">H", packet_id)
    for filter_, qos in filters:
        validate_filter(filter_)
        if qos not in (QOS_AT_MOST_ONCE, QOS_AT_LEAST_ONCE):
            raise MQTTError("QoS 2 não suportado em assinatura")
        body += _encode_utf8(filter_) + bytes([qos])
    return (
        bytes([PACKET_SUBSCRIBE << 4 | 0x02])
        + encode_remaining(len(body))
        + body
    )


def encode_unsubscribe(filters: list[str], packet_id: int) -> bytes:
    """Monta o pacote UNSUBSCRIBE (MQTT-3.10) com flags obrigatórias 0x2."""
    body = struct.pack(">H", packet_id)
    for filter_ in filters:
        validate_filter(filter_)
        body += _encode_utf8(filter_)
    return (
        bytes([PACKET_UNSUBSCRIBE << 4 | 0x02])
        + encode_remaining(len(body))
        + body
    )


def encode_puback(packet_id: int) -> bytes:
    return bytes([PACKET_PUBACK << 4, 2]) + struct.pack(">H", packet_id)


def encode_pingreq() -> bytes:
    return bytes([PACKET_PINGREQ << 4, 0])


def encode_disconnect() -> bytes:
    return bytes([PACKET_DISCONNECT << 4, 0])


# ---------------------------------------------------------------------------
# Decodificação de pacotes (broker → cliente)
# ---------------------------------------------------------------------------

def decode_connack(body: bytes) -> tuple[bool, int]:
    """Decodifica CONNACK → (session_present, return_code)."""
    if len(body) != 2:
        raise MQTTProtocolError("CONNACK com corpo inválido")
    return bool(body[0] & 0x01), body[1]


def decode_publish(ptype_flags: int, body: bytes) -> tuple[MqttMessage, Optional[int]]:
    """Decodifica um PUBLISH → (mensagem, packet_id ou None p/ QoS 0)."""
    flags = ptype_flags & 0x0F
    qos = (flags >> 1) & 0x03
    retain = bool(flags & 0x01)
    dup = bool(flags & 0x08)
    topic, offset = _decode_utf8(body, 0)
    packet_id: Optional[int] = None
    if qos > QOS_AT_MOST_ONCE:
        if offset + 2 > len(body):
            raise MQTTProtocolError("PUBLISH QoS>0 sem packet_id")
        (packet_id,) = struct.unpack(">H", body[offset:offset + 2])
        offset += 2
    message = MqttMessage(
        topic=topic, payload=body[offset:], qos=qos,
        retain=retain, dup=dup,
    )
    return message, packet_id


def decode_packet_id(body: bytes, kind: str = "pacote") -> int:
    """Lê o packet_id dos pacotes PUBACK/SUBACK/UNSUBACK."""
    if len(body) < 2:
        raise MQTTProtocolError(f"{kind} sem packet_id")
    (packet_id,) = struct.unpack(">H", body[:2])
    return packet_id


def decode_suback(body: bytes) -> tuple[int, list[int]]:
    """Decodifica SUBACK → (packet_id, códigos de retorno por filtro)."""
    if len(body) < 3:
        raise MQTTProtocolError("SUBACK malformado")
    (packet_id,) = struct.unpack(">H", body[:2])
    return packet_id, list(body[2:])


def parse_publish_topic(body: bytes) -> str:
    """Extrai só o tópico de um corpo PUBLISH (uso interno do broker)."""
    topic, _ = _decode_utf8(body, 0)
    return topic
