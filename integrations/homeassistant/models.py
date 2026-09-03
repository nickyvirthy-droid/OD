"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/homeassistant/models.py
Descrição: Modelos tipados da integração Home Assistant (Fase 5, item 5.4):
           taxonomia de entidades (atuadores, móveis, sensores, infra),
           EntityState (espelho do /api/states do HA) e credenciais
           (base_url + token, carregadas de arquivo ou dict).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/iot.py (mapeamento ambiental, leitura, controle)
  - docs/NEXUS_LEGACY_ANALYSIS.md §3.6
  - Home Assistant REST API (/api/states, /api/services)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.4
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

__signature__ = "OD // CORE"


class EntityType(str, Enum):
    """Taxonomia ambiental do legado (mapeamento por domínio do entity_id)."""

    ACTUATOR = "actuator"      # liga/desliga: light, switch, fan, cover...
    SENSOR = "sensor"          # leitura: sensor, binary_sensor, number...
    MOBILE = "mobile"          # rastreamento: person, device_tracker
    INFRA = "infra"            # infraestrutura: camera, automation, scene...
    UNKNOWN = "unknown"        # domínio não mapeado


# Domínios do Home Assistant por categoria (entity_id = "<domain>.<name>").
ACTUATOR_DOMAINS = frozenset(
    {"light", "switch", "fan", "cover", "climate", "lock",
     "media_player", "vacuum", "input_boolean", "humidifier", "water_heater"}
)
SENSOR_DOMAINS = frozenset(
    {"sensor", "binary_sensor", "number", "select",
     "input_number", "input_select", "counter", "datetime"}
)
MOBILE_DOMAINS = frozenset({"person", "device_tracker"})
INFRA_DOMAINS = frozenset(
    {"camera", "automation", "script", "scene", "group",
     "weather", "sun", "zone", "update", "timer", "calendar", "remote"}
)


def classify_entity(entity_id: str) -> EntityType:
    """Classifica um entity_id (ex: 'light.sala') pela taxonomia do legado."""
    domain = entity_id.split(".", 1)[0].lower()
    if domain in ACTUATOR_DOMAINS:
        return EntityType.ACTUATOR
    if domain in SENSOR_DOMAINS:
        return EntityType.SENSOR
    if domain in MOBILE_DOMAINS:
        return EntityType.MOBILE
    if domain in INFRA_DOMAINS:
        return EntityType.INFRA
    return EntityType.UNKNOWN


@dataclass(slots=True)
class EntityState:
    """Estado de uma entidade (payload do GET /api/states/<entity_id>)."""

    entity_id: str
    state: str = "unknown"
    attributes: dict[str, Any] = field(default_factory=dict)
    last_changed: str = ""
    last_updated: str = ""

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0].lower()

    @property
    def entity_type(self) -> EntityType:
        return classify_entity(self.entity_id)

    def is_on(self) -> bool:
        return self.state in ("on", "open", "unlocked", "home", "playing")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": dict(self.attributes),
            "last_changed": self.last_changed,
            "last_updated": self.last_updated,
            "domain": self.domain,
            "type": self.entity_type.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityState":
        return cls(
            entity_id=str(data.get("entity_id", "")),
            state=str(data.get("state", "unknown")),
            attributes=dict(data.get("attributes") or {}),
            last_changed=str(data.get("last_changed", "")),
            last_updated=str(data.get("last_updated", "")),
        )


@dataclass(slots=True)
class HACredentials:
    """Credenciais do Home Assistant (spec §7: segredos fora do código)."""

    base_url: str
    token: str = ""
    _base_url: str = ""  # url normalizada (sem barra final), setada em validate

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("base_url do Home Assistant ausente")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url deve ser http(s)://")
        self._base_url = self.base_url.rstrip("/")

    @property
    def normalized_url(self) -> str:
        return self._base_url or self.base_url.rstrip("/")

    @classmethod
    def from_file(cls, path: str | Path) -> "HACredentials":
        """Carrega de um arquivo JSON (ex: config/iot_credentials.json).

        Formato: {"base_url": "http://homeassistant:8123",
                  "token": "eyJ..."}
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        creds = cls(
            base_url=str(data.get("base_url") or ""),
            token=str(data.get("token") or ""),
        )
        creds.validate()
        return creds

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HACredentials":
        creds = cls(
            base_url=str(data.get("base_url") or ""),
            token=str(data.get("token") or ""),
        )
        creds.validate()
        return creds