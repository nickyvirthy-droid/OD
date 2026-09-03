"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/homeassistant/manager.py
Descrição: IoTManager (Fase 5, item 5.4) — gerencia dispositivos do Home
           Assistant sobre qualquer HABackend (HAClient REST ou
           InMemoryHAServer): taxonomia ambiental (atuadores/móveis/
           sensores/infra), leitura de estado e sensores, controle
           liga/desliga/toggle com GATE de segurança (guard + domínios
           permitidos), eventos no Event Bus e métricas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/iot.py (mapeamento ambiental, leitura, controle)
  - docs/NEXUS_LEGACY_ANALYSIS.md §3.6
  - OMEGADRAKON_SPEC.md §7 (segurança: escopo estrito em comandos)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.4
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from core.logger import get_logger
from integrations.homeassistant.client import HABackend, HAError
from integrations.homeassistant.models import (
    EntityState,
    EntityType,
    classify_entity,
)

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.homeassistant.manager")

# Ações de controle suportadas (mapeadas para serviços do HA).
ACTION_ON = "on"
ACTION_OFF = "off"
ACTION_TOGGLE = "toggle"
POWER_ACTIONS = (ACTION_ON, ACTION_OFF, ACTION_TOGGLE)

# Serviço por ação no Home Assistant.
_SERVICE_BY_ACTION = {
    ACTION_ON: "turn_on",
    ACTION_OFF: "turn_off",
    ACTION_TOGGLE: "toggle",
}


@dataclass(slots=True)
class IoTManagerConfig:
    """Configuração do IoTManager.

    Attributes:
        allowed_domains: Domínios de atuador que PODEM ser controlados.
                         None = todos os domínios de atuador (default).
        log_commands:    Audit log NICKY para cada comando (default True).
    """

    allowed_domains: Optional[frozenset[str]] = None
    log_commands: bool = True


@dataclass(slots=True)
class IoTMetrics:
    """Métricas acumuladas do gerenciador."""

    reads: int = 0
    commands: int = 0
    commands_ok: int = 0
    denied: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "reads": self.reads,
            "commands": self.commands,
            "commands_ok": self.commands_ok,
            "denied": self.denied,
            "errors": self.errors,
        }


GuardFn = Callable[[str, str], bool]  # (entity_id, action) -> permitido?


class IoTManager:
    """Gerencia dispositivos Home Assistant (taxonomia + leitura + controle).

    Uso típico:
        manager = IoTManager(HAClient(credentials), guard=meu_gate)
        manager.set_power("light.sala", on=True)
        snapshot = manager.snapshot()
    """

    def __init__(
        self,
        backend: HABackend,
        *,
        config: Optional[IoTManagerConfig] = None,
        guard: Optional[GuardFn] = None,
        event_bus: Any = None,
    ) -> None:
        self.backend = backend
        self.config = config or IoTManagerConfig()
        self.guard = guard
        self.event_bus = event_bus
        self.metrics = IoTMetrics()
        self._lock = threading.RLock()

    # -- Taxonomia -----------------------------------------------------------

    @staticmethod
    def classify(entity_id: str) -> EntityType:
        """Classifica um entity_id pela taxonomia do legado."""
        return classify_entity(entity_id)

    def is_controllable(self, entity_id: str) -> bool:
        """True se o entity é atuador e está dentro dos domínios permitidos."""
        if self.classify(entity_id) is not EntityType.ACTUATOR:
            return False
        allowed = self.config.allowed_domains
        if allowed is None:
            return True
        domain = entity_id.split(".", 1)[0].lower()
        return domain in allowed

    # -- Leitura -------------------------------------------------------------

    def get_entity(self, entity_id: str) -> Optional[EntityState]:
        """Estado de uma entidade (None se não existe)."""
        with self._lock:
            self.metrics.reads += 1
        try:
            return self.backend.get_state(entity_id)
        except HAError as exc:
            with self._lock:
                self.metrics.errors += 1
            log.error("Falha ao ler entidade", entity_id=entity_id,
                      error=str(exc))
            return None

    def list_entities(self, entity_type: Optional[EntityType] = None) -> list[EntityState]:
        """Todas as entidades (ou filtradas por tipo da taxonomia)."""
        with self._lock:
            self.metrics.reads += 1
        try:
            states = self.backend.list_states()
        except HAError as exc:
            with self._lock:
                self.metrics.errors += 1
            log.error("Falha ao listar entidades", error=str(exc))
            return []
        if entity_type is None:
            return states
        return [s for s in states if s.entity_type is entity_type]

    def sensor_reading(self, entity_id: str) -> Optional[str]:
        """Leitura bruta de um sensor (ex: temperatura '21.5')."""
        entity = self.get_entity(entity_id)
        if entity is None:
            return None
        return entity.state

    # -- Controle ------------------------------------------------------------

    async def set_power(self, entity_id: str, on: bool) -> bool:
        """Liga/desliga um atuador. Retorna False se negado/erro."""
        return await self._control(entity_id, ACTION_ON if on else ACTION_OFF)

    async def toggle(self, entity_id: str) -> bool:
        """Alterna o estado de um atuador."""
        return await self._control(entity_id, ACTION_TOGGLE)

    async def _control(self, entity_id: str, action: str) -> bool:
        if action not in POWER_ACTIONS:
            with self._lock:
                self.metrics.errors += 1
            return False
        with self._lock:
            self.metrics.commands += 1
        # Gate de segurança: guard injetado + escopo (atuador/permitido)
        if not self.is_controllable(entity_id):
            with self._lock:
                self.metrics.denied += 1
            log.warn("Comando IoT negado (escopo)", entity_id=entity_id,
                     action=action)
            return False
        if self.guard is not None and not self.guard(entity_id, action):
            with self._lock:
                self.metrics.denied += 1
            log.warn("Comando IoT negado (guard)", entity_id=entity_id,
                     action=action)
            return False
        domain = entity_id.split(".", 1)[0].lower()
        service = _SERVICE_BY_ACTION[action]
        try:
            self.backend.call_service(
                domain, service, entity_id=entity_id
            )
        except HAError as exc:
            with self._lock:
                self.metrics.errors += 1
            log.error("Comando IoT falhou", entity_id=entity_id,
                      service=service, error=str(exc))
            return False
        with self._lock:
            self.metrics.commands_ok += 1
        if self.config.log_commands:
            log.info("Comando IoT", entity_id=entity_id, service=service)
        await self._publish_command(entity_id, action, ok=True)
        return True

    async def _publish_command(self, entity_id: str, action: str, ok: bool) -> None:
        if self.event_bus is None:
            return
        try:
            from core.event_bus import Event

            await self.event_bus.publish(
                Event(
                    topic="iot.command",
                    data={
                        "entity_id": entity_id,
                        "action": action,
                        "ok": ok,
                    },
                    source="iot_manager",
                )
            )
        except (RuntimeError, Exception):  # pragma: no cover — sem loop
            log.warn("Event bus indisponível — comando só auditado.")

    # -- Introspecção --------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Estado de todas as entidades agrupado por tipo da taxonomia."""
        grouped: dict[str, list[dict[str, Any]]] = {t.value: [] for t in EntityType}
        for entity in self.list_entities():
            grouped[entity.entity_type.value].append(entity.to_dict())
        return {
            "total": sum(len(v) for v in grouped.values()),
            "entities": grouped,
        }

    def list_types(self) -> dict[str, int]:
        """Contagem de entidades por tipo da taxonomia."""
        counts: dict[str, int] = {t.value: 0 for t in EntityType}
        for entity in self.list_entities():
            counts[entity.entity_type.value] += 1
        return counts

    def dump(self) -> dict[str, Any]:
        return {
            "backend": type(self.backend).__name__,
            "config": {
                "allowed_domains": (
                    sorted(self.config.allowed_domains)
                    if self.config.allowed_domains else None
                ),
                "log_commands": self.config.log_commands,
            },
            "guard": self.guard is not None,
            "event_bus": self.event_bus is not None,
            "metrics": self.metrics.snapshot(),
        }


