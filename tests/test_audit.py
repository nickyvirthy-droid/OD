"""
OMEGA DRAKON • TESTS
Módulo: tests/test_audit.py
Descrição: Testes do Audit System (observability/audit.py) — Fase 7, item
           7.1: AuditEntry (round-trip), trilha em memória (history/search/
           since/by_action/counts/clear), persistência JSONL (arquivo,
           reload entre instâncias, linha corrompida, rotação por tamanho
           com retenção, clear truncando), sink de decisões de segurança
           (record_decision com SecurityDecision/AuditRecord e make_sink
           plugado no AuditEngine), Event Bus (audit.record) e health().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - ROADMAP_ABSORCAO.md Fase 7, item 7.1
  - OMEGADRAKON_SPEC.md §7.3 (auditoria contínua com timestamp e sessão)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.security import AuditEngine, EnforcementMode, AuditRecord
from core.security.models import ActionRequest, SecurityDecision
from observability.audit import (
    AUDIT_TOPIC,
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    OUTCOME_INFO,
    SEVERITY_CRIT,
    SEVERITY_INFO,
    AuditEntry,
    AuditSystem,
)

# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

class TestAuditEntry:
    """Tipos e round-trip do registro de auditoria."""

    def test_defaults(self):
        entry = AuditEntry()
        assert entry.ts == 0.0
        assert entry.id
        assert entry.source == "audit"
        assert entry.outcome == OUTCOME_INFO

    def test_to_dict_and_from_dict_roundtrip(self):
        entry = AuditEntry(
            ts=1234.5678,
            id="abc123",
            source="security",
            action="filesystem.delete",
            outcome=OUTCOME_DENIED,
            severity=SEVERITY_CRIT,
            actor="agent",
            session_id="sess-1",
            detail="negada por escopo",
            data={"denied_by": "scope", "reasons": ["fora da raiz"]},
        )
        restored = AuditEntry.from_dict(entry.to_dict())
        assert restored == entry

    def test_from_dict_survives_missing_fields(self):
        restored = AuditEntry.from_dict({"action": "x"})
        assert restored.action == "x"
        assert restored.source == "audit"
        assert restored.outcome == OUTCOME_INFO

    def test_to_dict_does_not_share_top_level_data(self):
        entry = AuditEntry(data={"k": 1})
        payload = entry.to_dict()
        payload["data"]["novo"] = True
        assert "novo" not in entry.data
        assert entry.data == {"k": 1}


# ---------------------------------------------------------------------------
# Trilha em memória
# ---------------------------------------------------------------------------

class TestAuditSystemInMemory:
    """Trilha sem arquivo: registro, consultas, métricas, clear."""

    def test_record_basic_and_metrics(self):
        audit = AuditSystem()
        entry = audit.record(
            source="launcher", action="system.startup",
            outcome="info", detail="no ar",
        )
        assert entry.ts > 0  # ts preenchido pelo relógio
        assert entry.action == "system.startup"
        assert audit.metrics.total == 1
        assert audit.metrics.persisted == 0  # sem arquivo
        assert audit.history() == [entry.to_dict()]

    def test_record_accepts_dict(self):
        audit = AuditSystem()
        entry = audit.record(
            {"source": "test", "action": "ping", "outcome": "info"}
        )
        assert entry.source == "test"
        assert audit.history(limit=1)[0]["action"] == "ping"

    def test_clock_injectable(self):
        fake = iter([100.0, 200.0])
        audit = AuditSystem(clock=lambda: next(fake))
        assert audit.record({"action": "a"}).ts == 100.0
        assert audit.record({"action": "b"}).ts == 200.0

    def test_history_most_recent_first_and_limit(self):
        audit = AuditSystem()
        for i in range(5):
            audit.record({"action": f"evt-{i}", "outcome": "info"})
        items = audit.history()
        assert [e["action"] for e in items] == [
            "evt-4", "evt-3", "evt-2", "evt-1", "evt-0",
        ]
        assert len(audit.history(limit=2)) == 2

    def test_ring_buffer_limited(self):
        audit = AuditSystem(max_in_memory=3)
        for i in range(5):
            audit.record({"action": f"evt-{i}"})
        assert len(audit.history()) == 3
        assert audit.history()[0]["action"] == "evt-4"

    def test_search_case_insensitive_in_fields_and_data(self):
        audit = AuditSystem()
        audit.record(
            {"source": "security", "action": "filesystem.DELETE",
             "detail": "fora da raiz", "data": {"denied_by": "Scope"}}
        )
        audit.record({"source": "launcher", "action": "system.startup"})
        assert len(audit.search("FILESYSTEM")) == 1
        assert len(audit.search("scope")) == 1  # data serializado
        assert len(audit.search("launcher")) == 1
        assert audit.search("") == []

    def test_since_filter(self):
        audit = AuditSystem(clock=lambda: time.time())
        first = audit.record({"action": "a"})
        second = audit.record({"action": "b"})
        assert [e["action"] for e in audit.since(second.ts)] == ["b"]
        assert [e["action"] for e in audit.since(first.ts)] == ["b", "a"]

    def test_by_action(self):
        audit = AuditSystem()
        audit.record({"action": "a"})
        audit.record({"action": "b"})
        audit.record({"action": "a"})
        assert [e["action"] for e in audit.by_action("a")] == ["a", "a"]
        assert audit.by_action("nada") == []

    def test_counts_by_outcome(self):
        audit = AuditSystem()
        audit.record({"outcome": OUTCOME_ALLOWED})
        audit.record({"outcome": OUTCOME_ALLOWED})
        audit.record({"outcome": OUTCOME_DENIED})
        assert audit.counts() == {OUTCOME_ALLOWED: 2, OUTCOME_DENIED: 1}

    def test_clear_resets_trail_and_metrics(self):
        audit = AuditSystem()
        audit.record({"action": "a"})
        audit.record({"action": "b"})
        assert audit.clear() == 2
        assert audit.history() == []
        assert audit.metrics.total == 0

    def test_snapshot_and_dump(self):
        audit = AuditSystem()
        audit.record({"action": "a"})
        snap = audit.snapshot()
        assert snap["entries"] == 1
        assert snap["metrics"]["total"] == 1
        assert snap["event_bus"] is False
        dump = audit.dump()
        assert dump["entries"] == 1
        assert len(dump["recent"]) == 1

    def test_health_without_file(self):
        audit = AuditSystem()
        health = audit.health()
        assert health["ok"] is True
        assert health["file"] is None


# ---------------------------------------------------------------------------
# Persistência JSONL
# ---------------------------------------------------------------------------

class TestAuditPersistence:
    """Trilha persistente: arquivo, reload, corrupção, rotação."""

    def test_persists_jsonl_lines(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        audit = AuditSystem(file_path=path)
        audit.record({"action": "a", "detail": "um"})
        audit.record({"action": "b", "detail": "dois"})
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["action"] == "a"
        assert audit.metrics.persisted == 2

    def test_reload_restores_trail_between_instances(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        AuditSystem(file_path=path).record(
            {"action": "a", "outcome": OUTCOME_DENIED}
        )
        AuditSystem(file_path=path).record(
            {"action": "b", "outcome": OUTCOME_ALLOWED}
        )
        reloaded = AuditSystem(file_path=path)
        actions = [e["action"] for e in reloaded.history()]
        assert actions == ["b", "a"]
        assert reloaded.metrics.persisted == 2
        assert reloaded.metrics.denied == 1
        assert reloaded.metrics.allowed == 1

    def test_corrupt_line_skipped_with_error_metric(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text(
            '{"action": "ok"}\nlinha corrompida\n{"action": "tambem"}\n',
            encoding="utf-8",
        )
        audit = AuditSystem(file_path=path)
        assert len(audit.history()) == 2
        assert audit.metrics.errors == 1

    def test_rotation_by_size(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        audit = AuditSystem(file_path=path, max_bytes=80, keep=1)
        for i in range(30):  # gera rotações suficientes
            audit.record({"action": f"evt-{i}", "detail": "x" * 20})
        assert path.exists()
        backup = Path(f"{path}.1")
        assert backup.exists()  # rotação aconteceu
        # keep=1: só existe o atual + 1 backup
        assert not Path(f"{path}.2").exists()

    def test_rotation_respects_keep(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        audit = AuditSystem(file_path=path, max_bytes=60, keep=2)
        for i in range(40):
            audit.record({"action": f"evt-{i}", "detail": "y" * 20})
        assert Path(f"{path}.1").exists()
        assert Path(f"{path}.2").exists()
        assert not Path(f"{path}.3").exists()

    def test_clear_truncates_file(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        audit = AuditSystem(file_path=path)
        audit.record({"action": "a"})
        assert audit.clear() == 1
        assert path.read_text(encoding="utf-8") == ""

    def test_unwritable_path_counts_failed(self, tmp_path):
        audit = AuditSystem(file_path=tmp_path / "sem" / "permissao" / "a.jsonl")
        # diretório inexistente sem permissão de criação
        audit._writable = False  # força o caminho de falha
        audit.record({"action": "a"})
        assert audit.metrics.failed == 1
        assert audit.health()["ok"] is False


# ---------------------------------------------------------------------------
# Integração com o Security Layer
# ---------------------------------------------------------------------------

class TestSecurityIntegration:
    """Decisões de segurança caem na trilha (criterio da Fase 7)."""

    def _decision(self, allowed: bool, **overrides):
        request = ActionRequest(
            action=overrides.get("action", "filesystem.delete"),
            role=overrides.get("role", "agent"),
            source=overrides.get("source", "security"),
            session_id=overrides.get("session_id", "sess-1"),
        )
        return SecurityDecision(
            request=request,
            allowed=allowed,
            mode=EnforcementMode.STRICT,
            denied_by=None if allowed else "scope",
            reasons=[] if allowed else ["fora da raiz"],
        )

    def test_record_decision_allowed(self):
        audit = AuditSystem()
        entry = audit.record_decision(self._decision(allowed=True))
        assert entry.outcome == OUTCOME_ALLOWED
        assert entry.severity == SEVERITY_INFO
        assert entry.source == "security"
        assert entry.actor == "agent"
        assert entry.session_id == "sess-1"
        assert entry.data["mode"] == "strict"

    def test_record_decision_denied_is_crit(self):
        audit = AuditSystem()
        entry = audit.record_decision(self._decision(allowed=False))
        assert entry.outcome == OUTCOME_DENIED
        assert entry.severity == SEVERITY_CRIT
        assert entry.data["denied_by"] == "scope"
        assert entry.data["reasons"] == ["fora da raiz"]
        assert audit.metrics.denied == 1

    def test_record_decision_accepts_audit_record(self):
        audit = AuditSystem()
        record = AuditRecord.from_decision(self._decision(allowed=True))
        entry = audit.record_decision(record)
        assert entry.outcome == OUTCOME_ALLOWED
        assert entry.action == "filesystem.delete"

    def test_record_decision_preserves_request_source(self):
        audit = AuditSystem()
        entry = audit.record_decision(
            self._decision(allowed=True, source="telegram")
        )
        assert entry.source == "telegram"  # origem real preservada

    def test_make_sink_plugs_into_audit_engine(self):
        """TODA decisão do Security Layer persiste via make_sink."""
        audit = AuditSystem()
        engine = AuditEngine(sinks=[audit.make_sink()])
        engine.record(self._decision(allowed=True))
        engine.record(self._decision(allowed=False, action="system.shutdown"))
        assert audit.metrics.total == 2
        assert audit.metrics.allowed == 1
        assert audit.metrics.denied == 1
        actions = [e["action"] for e in audit.by_action("system.shutdown")]
        assert actions == ["system.shutdown"]

    def test_decision_persisted_to_file(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        audit = AuditSystem(file_path=path)
        audit.record_decision(self._decision(allowed=False))
        reloaded = AuditSystem(file_path=path)
        assert reloaded.metrics.denied == 1
        assert reloaded.history()[0]["outcome"] == OUTCOME_DENIED

    @pytest.mark.asyncio
    async def test_sink_failure_never_breaks_trail(self):
        audit = AuditSystem()

        def bad_sink(payload):
            raise RuntimeError("quebrou")

        audit.add_sink(bad_sink)
        await audit.record_async({"action": "a"})
        assert audit.metrics.errors == 1
        assert audit.metrics.total == 1  # trilha intacta


# ---------------------------------------------------------------------------
# Event Bus + sinks async
# ---------------------------------------------------------------------------

class TestEventBusAndSinks:
    """Entrega async: Event Bus (audit.record) e sinks sync/async."""

    @pytest.mark.asyncio
    async def test_record_async_publishes_event(self):
        bus = EventBus()
        received = []
        bus.subscribe_handler(AUDIT_TOPIC, lambda event: received.append(event))
        audit = AuditSystem(event_bus=bus)
        entry = await audit.record_async(
            {"action": "system.startup", "source": "launcher"}
        )
        assert len(received) == 1
        assert received[0].topic == AUDIT_TOPIC
        assert received[0].data["action"] == "system.startup"
        assert received[0].source == "audit"
        assert entry.action == "system.startup"

    @pytest.mark.asyncio
    async def test_sync_sink_receives_payload(self):
        received = []
        audit = AuditSystem(sinks=[lambda payload: received.append(payload)])
        await audit.record_async({"action": "a"})
        assert len(received) == 1
        assert received[0]["action"] == "a"

    @pytest.mark.asyncio
    async def test_async_sink_is_awaited(self):
        calls = []

        async def async_sink(payload):
            calls.append(payload["action"])

        audit = AuditSystem(sinks=[async_sink])
        await audit.record_async({"action": "async-ok"})
        assert calls == ["async-ok"]

    @pytest.mark.asyncio
    async def test_record_async_delivers_sinks_once(self):
        calls = []

        async def async_sink(payload):
            calls.append(payload["action"])

        audit = AuditSystem(sinks=[async_sink])
        await audit.record_async({"action": "x"})
        await audit.record_async({"action": "y"})
        assert calls == ["x", "y"]  # sem duplicação

    @pytest.mark.asyncio
    async def test_async_sink_failure_tolerated(self):
        async def bad(payload):
            raise RuntimeError("boom")

        audit = AuditSystem(sinks=[bad])
        await audit.record_async({"action": "a"})
        assert audit.metrics.errors == 1
        assert audit.metrics.total == 1

    @pytest.mark.asyncio
    async def test_sync_record_does_not_deliver_sinks(self):
        """Caminho sync não depende de event loop (padrão notifier)."""
        calls = []
        audit = AuditSystem(sinks=[lambda payload: calls.append(payload)])
        audit.record({"action": "sync"})
        assert calls == []  # entrega só via record_async
        assert audit.metrics.total == 1