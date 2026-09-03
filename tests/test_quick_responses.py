#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_quick_responses
Description: Unit tests for memory/quick_responses.py — quick responses with
             alternation and analytics (Fase 2, item 2.3).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.quick_responses import DEFAULT_RESPONSES, QuickResponse, QuickResponses


@pytest.fixture
def qr(tmp_path: Path) -> QuickResponses:
    return QuickResponses(data_dir=tmp_path / "qr", profile="guardian", seed_defaults=False)


# ===========================================================================
# Gestão de padrões
# ===========================================================================

class TestQuickResponsesManage:
    """Tests for adding/removing patterns."""

    def test_add_and_get(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!", "Olá!"])
        assert qr.has("oi") is True
        assert qr.get("oi") == "Oi!"

    def test_add_single_string(self, qr: QuickResponses) -> None:
        qr.add("tchau", "Até logo!")
        assert qr.get("tchau") == "Até logo!"

    def test_add_updates_existing(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        qr.add("oi", ["Nova!"])
        assert qr.get("oi") == "Nova!"

    def test_add_empty_responses_raises(self, qr: QuickResponses) -> None:
        with pytest.raises(ValueError):
            qr.add("vazio", [])

    def test_pattern_case_insensitive(self, qr: QuickResponses) -> None:
        qr.add("Bom Dia", ["Bom dia!"])
        assert qr.has("bom dia") is True
        assert qr.get("BOM DIA") == "Bom dia!"

    def test_add_response(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        assert qr.add_response("oi", "Olá!") is True
        assert qr.add_response("inexistente", "x") is False

    def test_remove(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        assert qr.remove("oi") is True
        assert qr.remove("oi") is False
        assert qr.get("oi") is None

    def test_remove_response(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!", "Olá!"])
        assert qr.remove_response("oi", "Oi!") is True
        assert qr.get("oi") == "Olá!"

    def test_remove_last_response_removes_pattern(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        qr.remove_response("oi", "Oi!")
        assert qr.has("oi") is False

    def test_get_missing(self, qr: QuickResponses) -> None:
        assert qr.get("nada") is None
        assert qr.peek("nada") is None

    def test_list_patterns(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        qr.add("tchau", ["Até!"])
        assert qr.list_patterns() == ["oi", "tchau"]


# ===========================================================================
# Alternância
# ===========================================================================

class TestQuickResponsesAlternation:
    """Tests for round-robin alternation."""

    def test_round_robin(self, qr: QuickResponses) -> None:
        qr.add("oi", ["A", "B", "C"])
        assert qr.get("oi") == "A"
        assert qr.get("oi") == "B"
        assert qr.get("oi") == "C"
        assert qr.get("oi") == "A"  # volta ao início

    def test_peek_does_not_advance(self, qr: QuickResponses) -> None:
        qr.add("oi", ["A", "B"])
        assert qr.peek("oi") == "A"
        assert qr.peek("oi") == "A"
        assert qr.get("oi") == "A"

    def test_single_response_always_same(self, qr: QuickResponses) -> None:
        qr.add("ok", ["Certo"])
        assert qr.get("ok") == "Certo"
        assert qr.get("ok") == "Certo"


# ===========================================================================
# Analytics
# ===========================================================================

class TestQuickResponsesAnalytics:
    """Tests for usage analytics."""

    def test_use_count(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        qr.get("oi")
        qr.get("oi")
        a = qr.analytics("oi")
        assert a["use_count"] == 2
        assert a["last_used_ts"] is not None

    def test_analytics_aggregate(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        qr.add("tchau", ["Até!"])
        qr.get("oi")
        qr.get("oi")
        qr.get("tchau")
        a = qr.analytics()
        assert a["patterns"] == 2
        assert a["total_uses"] == 3
        assert a["per_pattern"]["oi"]["use_count"] == 2

    def test_analytics_missing_pattern(self, qr: QuickResponses) -> None:
        assert qr.analytics("nada") == {}

    def test_avg_response_time(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!"])
        qr.get("oi", response_time_ms=100.0)
        qr.get("oi", response_time_ms=200.0)
        a = qr.analytics("oi")
        assert a["avg_response_time_ms"] == 150.0

    def test_get_entry_returns_copy(self, qr: QuickResponses) -> None:
        qr.add("oi", ["Oi!", "Olá!"])
        entry = qr.get_entry("oi")
        assert entry is not None
        assert len(entry.responses) == 2
        assert qr.get_entry("nada") is None


# ===========================================================================
# Defaults
# ===========================================================================

class TestQuickResponsesDefaults:
    """Tests for seeded defaults."""

    def test_defaults_seeded(self, tmp_path: Path) -> None:
        qr = QuickResponses(data_dir=tmp_path / "qr")
        assert qr.has("oi") is True
        assert qr.get("oi") in DEFAULT_RESPONSES["oi"]

    def test_no_defaults_when_disabled(self, qr: QuickResponses) -> None:
        assert qr.list_patterns() == []

    def test_defaults_alternate(self, tmp_path: Path) -> None:
        qr = QuickResponses(data_dir=tmp_path / "qr")
        first = qr.get("oi")
        second = qr.get("oi")
        assert first != second


# ===========================================================================
# Persistência
# ===========================================================================

class TestQuickResponsesPersistence:
    """Tests for disk persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        q1 = QuickResponses(data_dir=tmp_path / "qr", seed_defaults=False)
        q1.add("oi", ["Oi!", "Olá!"])
        q1.get("oi")  # avança o índice e conta uso

        q2 = QuickResponses(data_dir=tmp_path / "qr", seed_defaults=False)
        assert q2.load() == 1
        assert q2.get("oi") == "Olá!"  # índice persistido
        assert q2.analytics("oi")["use_count"] == 2

    def test_writes_json(self, qr: QuickResponses, tmp_path: Path) -> None:
        qr.add("oi", ["Oi!"])
        path = tmp_path / "qr" / "quick_responses.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["profile"] == "guardian"
        assert data["responses"][0]["pattern"] == "oi"

    def test_atomic_no_tmp_left(self, qr: QuickResponses, tmp_path: Path) -> None:
        qr.add("oi", ["Oi!"])
        assert not (tmp_path / "qr" / "quick_responses.tmp").exists()

    def test_load_missing(self, qr: QuickResponses) -> None:
        assert qr.load() == 0


# ===========================================================================
# QuickResponse model
# ===========================================================================

class TestQuickResponseModel:
    """Tests for QuickResponse dataclass."""

    def test_roundtrip_dict(self) -> None:
        q = QuickResponse(pattern="oi", responses=["A", "B"], use_count=3, current_index=1)
        restored = QuickResponse.from_dict(q.to_dict())
        assert restored.pattern == "oi"
        assert restored.responses == ["A", "B"]
        assert restored.use_count == 3
        assert restored.current_index == 1

    def test_defaults(self) -> None:
        q = QuickResponse(pattern="oi", responses=["A"])
        assert q.priority == 0
        assert q.use_count == 0
        assert q.last_used_ts is None