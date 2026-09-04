"""
OMEGA DRAKON • OBSERVABILITY
Tecnologia que respira.
Módulo: observability/audit.py
Descrição: Audit System (Fase 7, item 7.1) — trilha de auditoria contínua e
           PERSISTENTE de todas as decisões do sistema (spec §7.3): registros
           tipados (AuditEntry), persistência JSONL append-only com rotação
           automática e retenção, sink plugável no AuditEngine do Security
           Layer (registra TODA decisão de segurança), Event Bus
           (audit.record), métricas, consultas (history/search/since/
           by_action/counts) e health().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/auditor.py (Auditor — auditoria de integridade)
  - NV Runtime observability/audit/ (trilhas de auditoria)
  - OMEGADRAKON_SPEC.md §7.3 (auditoria contínua com timestamp e sessão)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.1

Decisões registradas (ver CHANGELOG):
  - Trilha PERSISTENTE em JSONL append-only (logs/audit.jsonl), com rotação
    por tamanho e retenção configurável — o ring buffer em memória é apenas
    cache de consulta; a fonte de verdade é o arquivo (sobrevive a reinícios)
  - O AuditEngine do Security Layer (core/security/audit.py) permanece como
    camada de pipeline; o AuditSystem é o serviço de observabilidade que
    consome os registros via sink (make_sink) e os persiste
  - Entrega de sinks (encaminhamento externo) e Event Bus acontecem no
    caminho async (record_async), espelhando o padrão do ProactiveNotifier:
    o caminho sync (record) é a trilha em si (memória + persistência) e
    nunca depende de um event loop
  - Zerar dependências externas: stdlib puro
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.observability.audit")

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_CRIT = "crit"

OUTCOME_INFO = "info"
OUTCOME_ALLOWED = "allowed"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

AUDIT_TOPIC = "audit.record"

DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5MB por arquivo
DEFAULT_KEEP = 3  # backups rotacionados (.1, .2, .3)
DEFAULT_MAX_IN_MEMORY = 2000  # ring buffer de consulta

# Campos pesquisáveis pelo search()
_SEARCHABLE = ("action", "source", "detail", "actor", "session_id")


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Um registro imutável da trilha de auditoria (spec §7.3).

    Attributes:
        ts:         Timestamp (epoch) do evento (auto-definido quando 0.0).
        id:         Identificador único do registro (auto-gerado).
        source:     Componente de origem (ex: "security", "launcher").
        action:     Ação auditada (ex: "filesystem.delete", "system.startup").
        outcome:    Resultado (info/allowed/denied/error).
        severity:   info/warn/crit (derivável de outcome, mas explícito).
        actor:      Ator (papel/usuário) que solicitou a ação.
        session_id: Identificador de sessão (auditoria contínua).
        detail:     Texto legível do evento.
        data:       Metadados extras (mode, denied_by, reasons, ...).
    """

    ts: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = "audit"
    action: str = ""
    outcome: str = OUTCOME_INFO
    severity: str = SEVERITY_INFO
    actor: str = ""
    session_id: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 6),
            "id": self.id,
            "source": self.source,
            "action": self.action,
            "outcome": self.outcome,
            "severity": self.severity,
            "actor": self.actor,
            "session_id": self.session_id,
            "detail": self.detail,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        return cls(
            ts=float(data.get("ts", 0.0)),
            id=str(data.get("id", "")),
            source=str(data.get("source", "audit")),
            action=str(data.get("action", "")),
            outcome=str(data.get("outcome", OUTCOME_INFO)),
            severity=str(data.get("severity", SEVERITY_INFO)),
            actor=str(data.get("actor", "")),
            session_id=str(data.get("session_id", "")),
            detail=str(data.get("detail", "")),
            data=dict(data.get("data") or {}),
        )


# ---------------------------------------------------------------------------
# AuditMetrics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AuditMetrics:
    """Métricas acumuladas do Audit System."""

    total: int = 0
    persisted: int = 0
    failed: int = 0
    allowed: int = 0
    denied: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "total": self.total,
            "persisted": self.persisted,
            "failed": self.failed,
            "allowed": self.allowed,
            "denied": self.denied,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# AuditSystem
# ---------------------------------------------------------------------------

class AuditSystem:
    """Trilha de auditoria contínua e persistente (Fase 7, item 7.1).

    Uso típico:
        audit = AuditSystem(file_path="logs/audit.jsonl")
        audit.record(
            source="launcher", action="system.startup",
            outcome="info", detail="od-core no ar",
        )

        # Registrar TODA decisão de segurança do Security Layer:
        engine = AuditEngine(sinks=[audit.make_sink()])
        # ... SecurityManager usa o engine ...
        # toda decisão (allow/deny/approval) cai na trilha persistente

    Sinks de encaminhamento e Event Bus são entregues no caminho async
    (record_async); o caminho sync (record) mantém a trilha sem depender de
    event loop.
    """

    def __init__(
        self,
        *,
        file_path: Optional[Union[str, Path]] = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        keep: int = DEFAULT_KEEP,
        max_in_memory: int = DEFAULT_MAX_IN_MEMORY,
        sinks: Optional[list[Callable[[dict[str, Any]], Any]]] = None,
        event_bus: Any = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._file_path = Path(file_path) if file_path else None
        self._max_bytes = max_bytes
        self._keep = max(0, int(keep))
        self._max_in_memory = max_in_memory
        self._sinks: list[Callable[[dict[str, Any]], Any]] = list(sinks or [])
        self._event_bus = event_bus
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._ring: deque[AuditEntry] = deque(maxlen=self._max_in_memory)
        self._metrics = AuditMetrics()
        self._writable = self._probe_writable()
        # Recarrega a trilha existente (fonte de verdade = arquivo)
        if self._file_path is not None:
            self._load_existing()

    # -- Configuração ---------------------------------------------------------

    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    @property
    def metrics(self) -> AuditMetrics:
        return self._metrics

    def add_sink(self, sink: Callable[[dict[str, Any]], Any]) -> None:
        """Adiciona um callback que recebe cada registro (dict serializável)."""
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

    # -- Registro -------------------------------------------------------------

    def record(
        self,
        entry: Union[AuditEntry, dict[str, Any], None] = None,
        **fields: Any,
    ) -> AuditEntry:
        """Registra um evento na trilha (sync). Nunca levanta exceção.

        Aceita um AuditEntry, um dict, ou campos nomeados:
            audit.record({"action": "x"})
            audit.record(action="x", source="launcher", outcome="info")

        Mantém a trilha em memória + persiste em JSONL (append-only com
        rotação) + métricas. Sinks e Event Bus são entregues apenas via
        `record_async` (caminho async, padrão do ProactiveNotifier).
        """
        if entry is None:
            entry = fields
        normalized = self._normalize(entry)
        with self._lock:
            self._ring.append(normalized)
            self._metrics.total += 1
            if normalized.outcome == OUTCOME_ALLOWED:
                self._metrics.allowed += 1
            elif normalized.outcome == OUTCOME_DENIED:
                self._metrics.denied += 1
            self._persist(normalized)
        self._log_entry(normalized)
        return normalized

    async def record_async(
        self,
        entry: Union[AuditEntry, dict[str, Any], None] = None,
        **fields: Any,
    ) -> AuditEntry:
        """Registra (sync) e então entrega sinks + Event Bus (async)."""
        if entry is None:
            entry = fields
        normalized = self.record(entry)
        await self._deliver(normalized)
        return normalized

    def record_decision(self, decision: Any) -> AuditEntry:
        """Registra uma decisão de segurança (SecurityDecision ou AuditRecord).

        Conveniência da Fase 7: a trilha aceita os modelos tipados do
        Security Layer sem adaptação manual.
        """
        record = self._to_audit_record(decision)
        allowed = bool(record.allowed)
        mode = getattr(record, "mode", "")
        if hasattr(mode, "value"):  # EnforcementMode -> string serializável
            mode = mode.value
        return self.record(
            AuditEntry(
                ts=float(record.ts),
                source=record.source or "security",
                action=record.action,
                outcome=OUTCOME_ALLOWED if allowed else OUTCOME_DENIED,
                severity=SEVERITY_INFO if allowed else SEVERITY_CRIT,
                actor=record.role,
                session_id=record.session_id,
                detail=(
                    f"Decisão de segurança: {record.action} "
                    f"{'permitida' if allowed else 'negada'}"
                    + (f" por {record.denied_by}" if record.denied_by else "")
                ),
                data={
                    "mode": mode,
                    "request_id": record.request_id,
                    "denied_by": record.denied_by or "",
                    "reasons": list(getattr(record, "reasons", ()) or ()),
                    "approval_required": bool(
                        getattr(record, "approval_required", False)
                    ),
                    "approval_pending": bool(
                        getattr(record, "approval_pending", False)
                    ),
                },
            )
        )

    def make_sink(self) -> Callable[[Any], None]:
        """Sink compatível com o AuditEngine do Security Layer.

        Uso:
            engine = AuditEngine(sinks=[audit.make_sink()])
        A partir daí TODA decisão de segurança registrada no engine cai na
        trilha persistente do AuditSystem.
        """
        return self.record_decision

    # -- Consulta -------------------------------------------------------------

    def history(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Registros recentes (mais recentes primeiro)."""
        with self._lock:
            items = list(self._ring)
        items.reverse()
        if limit is not None:
            items = items[: max(0, int(limit))]
        return [e.to_dict() for e in items]

    def search(
        self, text: str, limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Busca case-insensitive por texto em campos pesquisáveis + data."""
        needle = str(text).lower()
        if not needle:
            return []
        with self._lock:
            items = list(self._ring)
        items.reverse()
        found = [e for e in items if self._entry_matches(e, needle)]
        if limit is not None:
            found = found[: max(0, int(limit))]
        return [e.to_dict() for e in found]

    def since(
        self, ts: float, limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Registros com timestamp >= ts (mais recentes primeiro)."""
        with self._lock:
            items = [e for e in self._ring if e.ts >= ts]
        items.reverse()
        if limit is not None:
            items = items[: max(0, int(limit))]
        return [e.to_dict() for e in items]

    def by_action(
        self, action: str, limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Registros de uma ação específica (mais recentes primeiro)."""
        with self._lock:
            items = [e for e in self._ring if e.action == action]
        items.reverse()
        if limit is not None:
            items = items[: max(0, int(limit))]
        return [e.to_dict() for e in items]

    def counts(self) -> dict[str, int]:
        """Contagem de registros por outcome."""
        with self._lock:
            result: dict[str, int] = {}
            for e in self._ring:
                result[e.outcome] = result.get(e.outcome, 0) + 1
            return result

    # -- Saúde e introspecção -------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Estado de saúde: trilha gravável? quantos registros? erros?"""
        with self._lock:
            last_ts = self._ring[-1].ts if self._ring else None
            return {
                "ok": self._writable,
                "status": "ok" if self._writable else "crit",
                "file": str(self._file_path) if self._file_path else None,
                "entries": len(self._ring),
                "persisted": self._metrics.persisted,
                "last_ts": round(last_ts, 6) if last_ts else None,
                "errors": self._metrics.errors,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            last_ts = self._ring[-1].ts if self._ring else None
            return {
                "file": str(self._file_path) if self._file_path else None,
                "max_bytes": self._max_bytes,
                "keep": self._keep,
                "max_in_memory": self._max_in_memory,
                "entries": len(self._ring),
                "last_ts": round(last_ts, 6) if last_ts else None,
                "writable": self._writable,
                "sinks": len(self._sinks),
                "event_bus": self._event_bus is not None,
                "metrics": self._metrics.snapshot(),
            }

    def dump(self) -> dict[str, Any]:
        data = self.snapshot()
        data["recent"] = self.history(limit=50)
        return data

    def clear(self) -> int:
        """Limpa a trilha (memória + arquivo). Retorna quantos removidos."""
        with self._lock:
            count = len(self._ring)
            self._ring.clear()
            self._metrics = AuditMetrics()
            if self._file_path is not None:
                try:
                    self._file_path.write_text("", encoding="utf-8")
                    self._writable = True
                except OSError as exc:  # pragma: no cover — sem permissão
                    self._writable = False
                    self._metrics.errors += 1
                    log.warn("Audit clear falhou", error=str(exc))
            return count

    # -- Internos -------------------------------------------------------------

    def _normalize(self, entry: Union[AuditEntry, dict[str, Any]]) -> AuditEntry:
        if isinstance(entry, AuditEntry):
            normalized = entry
        else:
            normalized = AuditEntry.from_dict(entry)
        if normalized.ts <= 0.0:
            normalized = replace(normalized, ts=self._clock())
        if not normalized.id:
            normalized = replace(normalized, id=uuid.uuid4().hex[:12])
        if not normalized.action:
            normalized = replace(normalized, action=normalized.source)
        return normalized

    @staticmethod
    def _entry_matches(entry: AuditEntry, needle: str) -> bool:
        for field_name in _SEARCHABLE:
            value = getattr(entry, field_name, "")
            if value and needle in str(value).lower():
                return True
        return needle in json.dumps(entry.data, ensure_ascii=False).lower()

    def _log_entry(self, entry: AuditEntry) -> None:
        ctx = dict(entry.data)
        ctx["source"] = entry.source
        ctx["outcome"] = entry.outcome
        if entry.actor:
            ctx["actor"] = entry.actor
        if entry.session_id:
            ctx["session_id"] = entry.session_id
        if entry.severity == SEVERITY_CRIT:
            log.crit(f"AUDIT {entry.action}", **ctx)
        elif entry.severity == SEVERITY_WARN:
            log.warn(f"AUDIT {entry.action}", **ctx)
        else:
            log.debug(f"AUDIT {entry.action}", **ctx)

    def _persist(self, entry: AuditEntry) -> None:
        if self._file_path is None:
            return
        if not self._writable:
            with self._lock:
                self._metrics.failed += 1
            return
        line = json.dumps(
            entry.to_dict(), ensure_ascii=False, separators=(",", ":")
        )
        try:
            self._rotate_if_needed(len(line) + 1)
            with self._file_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            with self._lock:
                self._metrics.persisted += 1
        except (OSError, TypeError, ValueError) as exc:
            # sem permissão / disco cheio / payload não serializável
            with self._lock:
                self._writable = False
                self._metrics.failed += 1
                self._metrics.errors += 1
            log.warn(
                "Persistência de auditoria falhou",
                error=type(exc).__name__,
                path=str(self._file_path),
            )

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if self._max_bytes <= 0:
            return  # rotação desligada
        try:
            size = self._file_path.stat().st_size
        except OSError:
            size = 0
        if size + incoming_bytes <= self._max_bytes:
            return
        # Shift dos backups: .N -> .N+1, dropando além do keep
        for index in range(self._keep, 0, -1):
            source = Path(f"{self._file_path}.{index}")
            if index >= self._keep:
                source.unlink(missing_ok=True)
            else:
                target = Path(f"{self._file_path}.{index + 1}")
                if source.exists():
                    source.replace(target)
        if self._keep > 0:
            Path(f"{self._file_path}.1").unlink(missing_ok=True)
            self._file_path.replace(Path(f"{self._file_path}.1"))

    def _probe_writable(self) -> bool:
        if self._file_path is None:
            return True
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8"):
                pass
            return True
        except OSError:  # pragma: no cover — depende do ambiente
            return False

    def _load_existing(self) -> None:
        if self._file_path is None or not self._file_path.exists():
            return
        loaded = 0
        try:
            with self._file_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = AuditEntry.from_dict(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        with self._lock:
                            self._metrics.errors += 1
                        continue
                    self._ring.append(entry)
                    loaded += 1
        except OSError as exc:  # pragma: no cover — sem permissão
            with self._lock:
                self._writable = False
                self._metrics.errors += 1
            log.warn("Trilha de auditoria ilegível", error=str(exc))
        with self._lock:
            self._metrics.total += loaded
            self._metrics.persisted += loaded
            for e in self._ring:
                if e.outcome == OUTCOME_ALLOWED:
                    self._metrics.allowed += 1
                elif e.outcome == OUTCOME_DENIED:
                    self._metrics.denied += 1

    async def _deliver(self, entry: AuditEntry) -> None:
        """Entrega externa (caminho async): Event Bus + sinks sync/async."""
        if self._event_bus is not None:
            try:
                from core.event_bus import Event

                await self._event_bus.publish(
                    Event(
                        topic=AUDIT_TOPIC,
                        data=entry.to_dict(),
                        source="audit",
                    )
                )
            except RuntimeError:  # pragma: no cover — sem loop ativo
                log.warn("Event bus indisponível — registro só persistido.")
        payload = entry.to_dict()
        for sink in self._sinks:
            try:
                out = sink(payload)
                if inspect.isawaitable(out):
                    await out
            except Exception as exc:  # sink nunca pode quebrar a trilha
                with self._lock:
                    self._metrics.errors += 1
                log.warn("Audit sink falhou", error=type(exc).__name__)

    @staticmethod
    def _to_audit_record(decision: Any) -> Any:
        """Normaliza SecurityDecision/AuditRecord para AuditRecord."""
        if hasattr(decision, "allowed") and hasattr(decision, "request"):
            # SecurityDecision -> AuditRecord (mesma convenção do engine)
            from core.security.models import AuditRecord

            return AuditRecord.from_decision(decision)
        return decision  # já é AuditRecord (ou objeto compatível)