"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/homeassistant/presence.py
Descrição: Presence Monitor (Fase 6, item 6.2) — monitora presença em casa
           através do Home Assistant: lê entidades person.*/device_tracker.*
           periodicamente, detecta transições (chegou/saiu), publica eventos
           no Event Bus (`presence.changed`) e notifica sinks plugáveis
           (ex: Telegram). Estado persistido em arquivo — reinícios não
           disparam transições falsas nem mensagens duplicadas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky vision/presence_monitor.py (monitor de presença, Event Bus)
  - Home Assistant (person.* / device_tracker.*)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.2

Decisões registradas (ver CHANGELOG):
  - Presença via entidades do Home Assistant (person/device_tracker) em vez
    de câmera/visão: a Face Detection (6.1) continua separada e alimenta o
    MESMO barramento de eventos futuramente
  - Estado 'unknown' é tratado como ausente (away): chegada só é anunciada
    quando o estado vira 'home' — evita falso positivo no boot do HA
  - Primeira observação vira baseline (sem evento) — reinício silencioso;
    transições reais (away→home / home→away) é que geram eventos
  - Backend plugável: qualquer objeto com list_states() (HAClient real ou
    InMemoryHAServer nos testes) — sem rede para testar
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.homeassistant.presence")

PRESENCE_TOPIC = "presence.changed"
DEFAULT_HOME_STATES = frozenset({"home"})
AWAY_STATES = frozenset({"not_home", "unknown", "unavailable", ""})
ENTITY_PREFIXES = ("person.", "device_tracker.")
TRACE_LIMIT = 200

STATE_HOME = "home"
STATE_AWAY = "away"
STATE_UNKNOWN = "unknown"


@dataclass(slots=True)
class PresenceConfig:
    """Configuração do monitor de presença.

    Attributes:
        poll_interval_s: Pausa entre leituras do HA.
        entity_ids:      Entidades a vigiar. Vazio = todas person.* e
                         device_tracker.* descobertas.
        home_states:     Estados que contam como "em casa".
        names:           Nome legível por entity_id (ex: person.alex →
                         "Alex Projeti"). Sem mapeamento, deriva do id.
        state_file:      Persistência JSON do último estado por entidade
                         (evita transição falsa/duplicada em reinícios).
    """

    poll_interval_s: float = 30.0
    entity_ids: tuple[str, ...] = ()
    home_states: frozenset[str] = DEFAULT_HOME_STATES
    names: dict[str, str] = field(default_factory=dict)
    state_file: Optional[Union[str, Path]] = None


@dataclass(slots=True)
class PresenceChange:
    """Uma transição de presença observada."""

    entity_id: str
    name: str
    state: str  # "home" | "away"
    previous: str  # "home" | "away"
    ts: float = 0.0

    @property
    def arrival(self) -> bool:
        return self.state == STATE_HOME

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "state": self.state,
            "previous": self.previous,
            "arrival": self.arrival,
            "ts": self.ts,
        }


@dataclass(slots=True)
class PresenceMetrics:
    """Métricas acumuladas do monitor."""

    polls: int = 0
    states_read: int = 0
    transitions: int = 0
    arrivals: int = 0
    departures: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "polls": self.polls,
            "states_read": self.states_read,
            "transitions": self.transitions,
            "arrivals": self.arrivals,
            "departures": self.departures,
            "errors": self.errors,
        }


ChangeSink = Callable[[PresenceChange], Union[Any, Awaitable[Any]]]


def prettify_name(entity_id: str) -> str:
    """Deriva nome legível do entity_id (person.alex_projeti → Alex Projeti)."""
    raw = entity_id
    for prefix in ENTITY_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return raw.replace("_", " ").replace(".", " ").strip().title() or entity_id


def classify(state: str, home_states: frozenset[str]) -> str:
    """Normaliza o estado HA para home/away (unknown conta como away)."""
    if state in home_states:
        return STATE_HOME
    return STATE_AWAY


class PresenceMonitor:
    """Monitor de presença sobre o Home Assistant.

    Uso típico:
        monitor = PresenceMonitor(ha_client, event_bus=bus, sinks=[notify])
        monitor.start()  # thread com loop próprio
        ...
        monitor.stop()
    """

    def __init__(
        self,
        backend: Any,
        *,
        event_bus: Any = None,
        config: Optional[PresenceConfig] = None,
        sinks: Optional[list[ChangeSink]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.backend = backend
        self.event_bus = event_bus
        self.config = config or PresenceConfig()
        self._clock = clock or time.time
        self._sinks: list[ChangeSink] = list(sinks or [])
        self.metrics = PresenceMetrics()
        self._closed = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        # entity_id -> último estado normalizado ("home"/"away")
        self._last: dict[str, str] = self._load_state()
        self._trace: deque[PresenceChange] = deque(maxlen=TRACE_LIMIT)

    # -- Ciclo de vida -------------------------------------------------------

    def add_sink(self, sink: ChangeSink) -> None:
        with self._lock:
            self._sinks.append(sink)

    def start(self) -> threading.Thread:
        """Sobe o loop de polling em thread daemon (runtime)."""
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
            with self._lock:
                self.metrics.errors += 1
            log.error("Loop do presence encerrado", error=type(exc).__name__)

    def stop(self) -> None:
        with self._lock:
            self._closed = True

    def close(self) -> None:
        self.stop()

    # -- Polling -------------------------------------------------------------

    async def tick(self) -> list[PresenceChange]:
        """Lê o HA e devolve as transições detectadas neste ciclo."""
        with self._lock:
            self.metrics.polls += 1
        try:
            states = self.backend.list_states()
        except Exception as exc:
            with self._lock:
                self.metrics.errors += 1
            log.warn("Falha ao ler presença do HA", error=str(exc))
            return []
        wanted = self._watched_ids()
        changes: list[PresenceChange] = []
        with self._lock:
            self.metrics.states_read += len(states)
        for state in states:
            entity_id = state.entity_id
            if wanted and entity_id not in wanted:
                continue
            if not wanted and not entity_id.startswith(ENTITY_PREFIXES):
                continue
            current = classify(str(state.state or ""), self.config.home_states)
            previous = self._last.get(entity_id)
            if previous is None:
                # baseline: registra sem evento (silêncio no primeiro boot)
                self._last[entity_id] = current
                continue
            if current != previous:
                change = PresenceChange(
                    entity_id=entity_id,
                    name=self.config.names.get(entity_id) or prettify_name(entity_id),
                    state=current,
                    previous=previous,
                    ts=self._clock(),
                )
                await self._apply_change(change)
                changes.append(change)
        if changes:
            self._save_state()
        return changes

    def _watched_ids(self) -> set[str]:
        return {e for e in self.config.entity_ids if e}

    async def _apply_change(self, change: PresenceChange) -> None:
        with self._lock:
            self._last[change.entity_id] = change.state
            self._trace.append(change)
            self.metrics.transitions += 1
            if change.arrival:
                self.metrics.arrivals += 1
            else:
                self.metrics.departures += 1
        text = self.format_change(change)
        log.info("Presença mudou", entity=change.entity_id, state=change.state)
        for sink in self._sinks:
            try:
                out = sink(change)
                if isinstance(out, Awaitable):
                    await out
            except Exception as exc:  # pragma: no cover — sink quebrou
                self.metrics.errors += 1
                log.error("Sink de presença falhou", error=str(exc))
        if self.event_bus is not None:
            try:
                await self.event_bus.publish(_make_event(change))
            except RuntimeError:  # pragma: no cover — sem loop ativo
                log.warn("Event bus indisponível — presença só logada.")
        if change.arrival:
            log.info("Chegada detectada", name=change.name, detail=text)

    # -- Loop ----------------------------------------------------------------

    async def run(
        self,
        interval: Optional[float] = None,
        max_ticks: Optional[int] = None,
    ) -> int:
        """Loop: tick a cada `interval` até stop()/limite."""
        pause = interval if interval is not None else self.config.poll_interval_s
        ticks = 0
        while not self._closed:
            await self.tick()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            await asyncio.sleep(pause)
        return ticks

    # -- Introspecção --------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "metrics": self.metrics.snapshot(),
                "watched": sorted(self._last),
                "presence": {
                    eid: state for eid, state in self._last.items()
                },
                "entity_ids": list(self.config.entity_ids),
                "poll_interval_s": self.config.poll_interval_s,
            }

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [c.to_dict() for c in self._trace]

    def dump(self) -> dict[str, Any]:
        data = self.snapshot()
        data["changes"] = self.history()
        return data

    def health(self) -> dict[str, Any]:
        present = [
            eid for eid, state in self._last.items() if state == STATE_HOME
        ]
        return {
            "ok": True,
            "connected": True,
            "home_now": sorted(present),
            "ts": self._clock(),
        }

    @staticmethod
    def format_change(change: PresenceChange) -> str:
        emoji = "🏠" if change.arrival else "🚶"
        verb = "chegou em casa" if change.arrival else "saiu de casa"
        when = time.strftime(
            "%d/%m %H:%M:%S", time.localtime(change.ts)
        ) if change.ts else "-"
        return f"{emoji} {change.name} {verb} ({when})"

    # -- Estado persistido ---------------------------------------------------

    def _state_path(self) -> Optional[Path]:
        if self.config.state_file is None:
            return None
        return Path(self.config.state_file)

    def _load_state(self) -> dict[str, str]:
        path = self._state_path()
        if path is None or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()}
        except (OSError, json.JSONDecodeError):
            log.warn("State do presence ilegível — ignorado.")
            return {}

    def _save_state(self) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._last, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:  # pragma: no cover
            log.warn("State do presence não pôde ser salvo", error=str(exc))


def _make_event(change: PresenceChange) -> Any:
    """Evento do bus (import tardio evita acoplamento pesado)."""
    from core.event_bus import Event

    return Event(
        topic=PRESENCE_TOPIC,
        data=change.to_dict(),
        source="presence",
    )
