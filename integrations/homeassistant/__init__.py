"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: integrations/homeassistant/
Descrição: IoT Manager (Fase 5, item 5.4) — integração com Home Assistant
           via REST (stdlib) com taxonomia ambiental do legado Nexus
           (atuadores/móveis/sensores/infra), leitura de estado e controle
           liga/desliga/toggle com gate de segurança, eventos e métricas.

Módulos:
  - models.py  → EntityType (taxonomia), EntityState, HACredentials
  - client.py  → HAClient (REST stdlib, Bearer token) + InMemoryHAServer
  - manager.py → IoTManager (leitura, controle, guard, Event Bus, métricas)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/iot.py (mapeamento ambiental, leitura, controle)
  - Home Assistant REST API
  - ROADMAP_ABSORCAO.md Fase 5, item 5.4
"""

from integrations.homeassistant.client import HAClient, HAError, InMemoryHAServer
from integrations.homeassistant.manager import (
    ACTION_OFF,
    ACTION_ON,
    ACTION_TOGGLE,
    IoTManager,
    IoTManagerConfig,
    IoTMetrics,
)
from integrations.homeassistant.models import (
    ACTUATOR_DOMAINS,
    HACredentials,
    EntityState,
    EntityType,
    classify_entity,
)
from integrations.homeassistant.presence import (
    PRESENCE_TOPIC,
    PresenceChange,
    PresenceConfig,
    PresenceMetrics,
    PresenceMonitor,
    classify,
    prettify_name,
)

__signature__ = "OD // CORE"
__all__ = [
    "HACredentials",
    "EntityState",
    "EntityType",
    "classify_entity",
    "ACTUATOR_DOMAINS",
    "HAClient",
    "HAError",
    "InMemoryHAServer",
    "IoTManager",
    "IoTManagerConfig",
    "IoTMetrics",
    "ACTION_ON",
    "ACTION_OFF",
    "ACTION_TOGGLE",
    "PRESENCE_TOPIC",
    "PresenceMonitor",
    "PresenceConfig",
    "PresenceChange",
    "PresenceMetrics",
    "prettify_name",
    "classify",
]