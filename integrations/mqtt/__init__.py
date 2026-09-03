"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: integrations/mqtt/
Descrição: MQTT Bridge (Fase 5, item 5.5) — ponte para broker MQTT 3.1.1
           (Mosquitto) em stdlib puro, sem paho-mqtt: codec do protocolo
           wire, cliente real sobre socket, broker fake em processo
           (testes determinísticos) e a ponte com Event Bus, handlers,
           métricas e reconexão.

Módulos:
  - protocol.py → codec MQTT 3.1.1 (pacotes, validação, curingas)
  - client.py   → MQTTClient real (socket, QoS 0/1, keepalive, fila)
  - broker.py   → InMemoryBroker (broker fake em processo)
  - bridge.py   → MQTTBridge (Event Bus ↔ tópicos, handlers, métricas)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus: integração IoT via MQTT (Mosquitto) — paho-mqtt substituído
    por protocolo wire próprio (projeto é 100% stdlib)
  - OASIS MQTT 3.1.1 (ISO/IEC 20922)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.5
"""

from integrations.mqtt.bridge import (
    MQTTBridge,
    MQTTConfig,
    MQTTMetrics,
)
from integrations.mqtt.broker import BrokerStats, InMemoryBroker
from integrations.mqtt.client import MQTTClient
from integrations.mqtt.protocol import (
    CONNACK_ACCEPTED,
    MQTTConnectError,
    MQTTError,
    MQTTProtocolError,
    MqttMessage,
    QOS_AT_LEAST_ONCE,
    QOS_AT_MOST_ONCE,
    encode_connect,
    encode_disconnect,
    encode_pingreq,
    encode_publish,
    encode_subscribe,
    encode_unsubscribe,
    topic_matches,
    validate_filter,
    validate_topic,
)

__signature__ = "OD // CORE"
__all__ = [
    "MQTTError",
    "MQTTConnectError",
    "MQTTProtocolError",
    "MqttMessage",
    "QOS_AT_MOST_ONCE",
    "QOS_AT_LEAST_ONCE",
    "CONNACK_ACCEPTED",
    "encode_connect",
    "encode_publish",
    "encode_subscribe",
    "encode_unsubscribe",
    "encode_pingreq",
    "encode_disconnect",
    "topic_matches",
    "validate_topic",
    "validate_filter",
    "MQTTClient",
    "InMemoryBroker",
    "BrokerStats",
    "MQTTBridge",
    "MQTTConfig",
    "MQTTMetrics",
]
