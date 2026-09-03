"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/homeassistant/client.py
Descrição: Cliente REST do Home Assistant em stdlib (urllib, sem requests):
           GET /api/states (lista e individual) e POST /api/services/<domínio>
           /<serviço> com Bearer token — mais um servidor fake em memória
           (InMemoryHAServer) para testes e desenvolvimento offline com a
           MESMA interface (HABackend).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/iot.py (leitura de estado + controle)
  - Home Assistant REST API (Bearer token)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.4
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional, Protocol

from core.logger import get_logger
from integrations.homeassistant.models import (
    EntityState,
    HACredentials,
)

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.homeassistant.client")

API_STATES = "/api/states"
API_SERVICES = "/api/services"


class HAError(Exception):
    """Erro de comunicação/configuração com o Home Assistant."""


class HABackend(Protocol):
    """Contrato do endpoint HA usado pelo IoTManager (REST ou fake)."""

    def get_state(self, entity_id: str) -> Optional[EntityState]: ...

    def list_states(self) -> list[EntityState]: ...

    def call_service(
        self, domain: str, service: str, *, entity_id: str = "", **data: Any
    ) -> list[EntityState]: ...


# ---------------------------------------------------------------------------
# HAClient — REST real (stdlib)
# ---------------------------------------------------------------------------

class HAClient:
    """Cliente da Home Assistant REST API via urllib (Bearer token).

    Exemplo:
        client = HAClient(HACredentials("http://ha:8123", token="..."))
        state = client.get_state("light.sala")
        client.call_service("light", "turn_on", entity_id="light.sala")
    """

    def __init__(
        self,
        credentials: HACredentials,
        *,
        timeout: float = 10.0,
    ) -> None:
        credentials.validate()
        self.base_url = credentials.normalized_url
        self.token = credentials.token
        self.timeout = timeout

    # -- REST ----------------------------------------------------------------

    def _request(
        self, method: str, path: str, data: Optional[dict[str, Any]] = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = (
            json.dumps(data).encode("utf-8") if data is not None else None
        )
        request = urllib.request.Request(
            url, data=payload, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise HAError(
                f"Home Assistant {exc.code}: {body[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise HAError(f"Home Assistant indisponível: {exc}") from exc
        if not raw:
            return []
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HAError(f"Resposta JSON inválida: {exc}") from exc

    # -- API -----------------------------------------------------------------

    def get_state(self, entity_id: str) -> Optional[EntityState]:
        """Estado de uma entidade; None se não existir (404)."""
        try:
            data = self._request("GET", f"{API_STATES}/{entity_id}")
        except HAError as exc:
            if "404" in str(exc):
                return None
            raise
        if isinstance(data, dict) and data.get("entity_id"):
            return EntityState.from_dict(data)
        return None

    def list_states(self) -> list[EntityState]:
        """Todos os estados (GET /api/states)."""
        data = self._request("GET", API_STATES)
        if not isinstance(data, list):
            raise HAError(f"Resposta inesperada de {API_STATES}")
        return [EntityState.from_dict(item) for item in data]

    def call_service(
        self, domain: str, service: str, *, entity_id: str = "", **data: Any
    ) -> list[EntityState]:
        """Invoca um serviço (POST /api/services/<domain>/<service>).

        Retorna os estados afetados (payload da API HA).
        """
        payload: dict[str, Any] = dict(data)
        if entity_id:
            payload["entity_id"] = entity_id
        result = self._request(
            "POST", f"{API_SERVICES}/{domain}/{service}", payload
        )
        if not isinstance(result, list):
            return []
        return [EntityState.from_dict(item) for item in result]

    def service_available(self, domain: str, service: str) -> bool:
        """Probe leve: chama o serviço sem entity_id (HA responde 400/200)."""
        try:
            self._request("POST", f"{API_SERVICES}/{domain}/{service}", {})
            return True
        except HAError as exc:
            # 400 = serviço existe mas faltou entity_id; 404 = não existe
            return "400" in str(exc)


# ---------------------------------------------------------------------------
# InMemoryHAServer — fake determinístico (testes/dev offline)
# ---------------------------------------------------------------------------

class InMemoryHAServer:
    """Servidor HA em memória com a mesma interface do HAClient.

    Simula estados e serviços (turn_on/turn_off/toggle por domínio) para
    testes e desenvolvimento sem rede nem credenciais reais.
    """

    def __init__(self) -> None:
        self._states: dict[str, EntityState] = {}
        self.service_calls: list[dict[str, Any]] = []

    # -- Setup de teste ------------------------------------------------------

    def seed(
        self, entity_id: str, state: str = "off",
        attributes: Optional[dict[str, Any]] = None,
    ) -> EntityState:
        entity = EntityState(
            entity_id=entity_id,
            state=state,
            attributes=dict(attributes or {}),
        )
        self._states[entity_id] = entity
        return entity

    # -- Backend (mesma interface do HAClient) -------------------------------

    def get_state(self, entity_id: str) -> Optional[EntityState]:
        entity = self._states.get(entity_id)
        return EntityState(
            entity_id=entity.entity_id,
            state=entity.state,
            attributes=dict(entity.attributes),
            last_changed=entity.last_changed,
            last_updated=entity.last_updated,
        ) if entity else None

    def list_states(self) -> list[EntityState]:
        return [
            EntityState(
                entity_id=e.entity_id,
                state=e.state,
                attributes=dict(e.attributes),
                last_changed=e.last_changed,
                last_updated=e.last_updated,
            )
            for e in self._states.values()
        ]

    def call_service(
        self, domain: str, service: str, *, entity_id: str = "", **data: Any
    ) -> list[EntityState]:
        self.service_calls.append(
            {"domain": domain, "service": service,
             "entity_id": entity_id, "data": dict(data)}
        )
        target = entity_id or data.get("entity_id", "")
        affected: list[EntityState] = []
        if target:
            entity = self._states.get(target)
            if entity is None:
                raise HAError(f"Home Assistant 404: {target} não existe")
            self._apply(entity, service)
            affected.append(entity)
        else:
            # Sem alvo: aplica a todos do domínio (comportamento do HA)
            for entity in list(self._states.values()):
                if entity.domain == domain:
                    self._apply(entity, service)
                    affected.append(entity)
        return affected

    def _apply(self, entity: EntityState, service: str) -> None:
        if service == "turn_on":
            entity.state = "on"
        elif service == "turn_off":
            entity.state = "off"
        elif service == "toggle":
            entity.state = "off" if entity.is_on() else "on"