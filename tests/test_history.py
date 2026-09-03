#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_history
Description: Unit tests for memory/history.py — per-user/profile conversation
             history with ChatML formatting (Fase 2, item 2.1).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.history import ConversationHistory, Message, build_chatml


@pytest.fixture
def history(tmp_path: Path) -> ConversationHistory:
    return ConversationHistory(base_dir=tmp_path / "conversations")


# ===========================================================================
# Message
# ===========================================================================

class TestMessage:
    """Tests for the Message dataclass."""

    def test_creation(self) -> None:
        msg = Message(role="user", content="Olá")
        assert msg.role == "user"
        assert msg.content == "Olá"
        assert msg.llm_used == ""
        assert isinstance(msg.ts, float)

    def test_to_dict(self) -> None:
        msg = Message(role="assistant", content="Oi!", llm_used="qwen")
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "Oi!"
        assert d["llm_used"] == "qwen"

    def test_from_dict(self) -> None:
        msg = Message.from_dict({"role": "user", "content": "x", "ts": 1.0, "llm_used": "q"})
        assert msg.role == "user"
        assert msg.content == "x"
        assert msg.ts == 1.0
        assert msg.llm_used == "q"

    def test_from_dict_defaults(self) -> None:
        msg = Message.from_dict({"role": "user", "content": "x"})
        assert msg.llm_used == ""
        assert isinstance(msg.ts, float)


# ===========================================================================
# ChatML
# ===========================================================================

class TestChatML:
    """Tests for ChatML formatting."""

    def test_build_with_objects(self) -> None:
        msgs = [
            Message(role="user", content="Oi"),
            Message(role="assistant", content="Olá!"),
        ]
        chatml = build_chatml(msgs)
        assert chatml == "<|im_start|>user\nOi<|im_end|>\n<|im_start|>assistant\nOlá!<|im_end|>"

    def test_build_with_dicts(self) -> None:
        msgs = [{"role": "user", "content": "teste"}]
        assert "<|im_start|>user\nteste<|im_end|>" in build_chatml(msgs)

    def test_build_with_system_prompt(self) -> None:
        msgs = [Message(role="user", content="oi")]
        chatml = build_chatml(msgs, system_prompt="Você é Nicky.")
        assert chatml.startswith("<|im_start|>system\nVocê é Nicky.<|im_end|>")

    def test_build_empty(self) -> None:
        assert build_chatml([]) == ""

    def test_build_system_only(self) -> None:
        assert build_chatml([], system_prompt="sys") == "<|im_start|>system\nsys<|im_end|>"


# ===========================================================================
# ConversationHistory — escrita
# ===========================================================================

class TestHistoryWrite:
    """Tests for adding messages."""

    def test_add_message(self, history: ConversationHistory) -> None:
        history.add_message("alex", "guardian", "user", "oi")
        msgs = history.get_history("alex", "guardian")
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "oi"

    def test_add_interaction(self, history: ConversationHistory) -> None:
        count = history.add_interaction("alex", "guardian", "Bom dia!", "Olá, Alex!")
        assert count == 2
        msgs = history.get_history("alex", "guardian")
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[0].content == "Bom dia!"
        assert msgs[1].content == "Olá, Alex!"

    def test_add_interaction_with_llm(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá", llm_used="qwen")
        msgs = history.get_history("alex", "guardian")
        assert msgs[1].llm_used == "qwen"

    def test_add_system(self, history: ConversationHistory) -> None:
        history.add_system("alex", "guardian", "Seja educado.")
        msgs = history.get_history("alex", "guardian")
        assert msgs[0].role == "system"

    def test_multiple_interactions_ordered(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "1", "r1")
        history.add_interaction("alex", "guardian", "2", "r2")
        msgs = history.get_history("alex", "guardian")
        assert [m.content for m in msgs] == ["1", "r1", "2", "r2"]


# ===========================================================================
# ConversationHistory — isolamento por usuário/perfil
# ===========================================================================

class TestHistoryIsolation:
    """Tests for per-user/per-profile isolation."""

    def test_users_isolated(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("bia", "guardian", "oi", "oi bia")
        assert len(history.get_history("alex", "guardian")) == 2
        assert len(history.get_history("bia", "guardian")) == 2
        assert history.get_history("alex", "guardian")[1].content == "olá"
        assert history.get_history("bia", "guardian")[1].content == "oi bia"

    def test_profiles_isolated(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("alex", "regulus", "oi", "saudações")
        assert len(history.get_history("alex", "guardian")) == 2
        assert len(history.get_history("alex", "regulus")) == 2

    def test_missing_conversation_returns_empty(self, history: ConversationHistory) -> None:
        assert history.get_history("ninguem", "guardian") == []


# ===========================================================================
# ConversationHistory — limite de entradas
# ===========================================================================

class TestHistoryLimit:
    """Tests for max_entries trimming."""

    def test_trims_oldest(self, tmp_path: Path) -> None:
        history = ConversationHistory(base_dir=tmp_path / "c", max_entries=4)
        for i in range(5):
            history.add_interaction("alex", "guardian", f"u{i}", f"a{i}")
        msgs = history.get_history("alex", "guardian")
        assert len(msgs) == 4
        # As mais antigas (u0/a0, u1/a1) foram descartadas
        assert msgs[0].content == "u3"
        assert msgs[-1].content == "a4"

    def test_max_entries_min_one(self) -> None:
        history = ConversationHistory(max_entries=0)
        assert history._max_entries == 1


# ===========================================================================
# ConversationHistory — persistência
# ===========================================================================

class TestHistoryPersistence:
    """Tests for JSON persistence."""

    def test_persists_to_disk(self, history: ConversationHistory, tmp_path: Path) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        path = tmp_path / "conversations" / "alex" / "guardian.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["user_id"] == "alex"
        assert data["profile"] == "guardian"
        assert len(data["messages"]) == 2

    def test_load_all(self, tmp_path: Path) -> None:
        h1 = ConversationHistory(base_dir=tmp_path / "c")
        h1.add_interaction("alex", "guardian", "oi", "olá")
        h1.add_interaction("alex", "nyx", "oi", "saudações")
        h1.add_interaction("bia", "guardian", "oi", "oi bia")

        h2 = ConversationHistory(base_dir=tmp_path / "c")
        loaded = h2.load_all()
        assert loaded == 3
        assert h2.get_history("alex", "guardian")[1].content == "olá"
        assert h2.get_history("alex", "nyx")[1].content == "saudações"
        assert h2.get_history("bia", "guardian")[1].content == "oi bia"

    def test_load_all_empty_dir(self, tmp_path: Path) -> None:
        history = ConversationHistory(base_dir=tmp_path / "nao-existe")
        assert history.load_all() == 0

    def test_atomic_write_no_tmp_left(self, history: ConversationHistory, tmp_path: Path) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        files = list((tmp_path / "conversations" / "alex").glob("*.tmp"))
        assert files == []

    def test_roundtrip_preserves_llm_used(self, tmp_path: Path) -> None:
        h1 = ConversationHistory(base_dir=tmp_path / "c")
        h1.add_interaction("alex", "guardian", "oi", "olá", llm_used="qwen")
        h2 = ConversationHistory(base_dir=tmp_path / "c")
        h2.load_all()
        assert h2.get_history("alex", "guardian")[1].llm_used == "qwen"


# ===========================================================================
# ConversationHistory — consulta
# ===========================================================================

class TestHistoryQuery:
    """Tests for query helpers."""

    def test_last_interaction(self, history: ConversationHistory) -> None:
        assert history.last_interaction("alex", "guardian") is None
        history.add_interaction("alex", "guardian", "oi", "olá")
        last = history.last_interaction("alex", "guardian")
        assert last is not None
        assert last.content == "olá"

    def test_list_users_profiles(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("alex", "nyx", "oi", "saudações")
        history.add_interaction("bia", "guardian", "oi", "oi bia")
        assert history.list_users() == ["alex", "bia"]
        assert history.list_profiles("alex") == ["guardian", "nyx"]

    def test_stats(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("alex", "nyx", "oi", "saudações")
        stats = history.stats()
        assert stats["users"] == 1
        assert stats["conversations"] == 2
        assert stats["messages"] == 4
        assert stats["per_user"]["alex"]["profiles"]["guardian"]["messages"] == 2

    def test_stats_filtered_by_user(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("bia", "guardian", "oi", "oi bia")
        stats = history.stats(user_id="bia")
        assert stats["conversations"] == 1
        assert list(stats["per_user"].keys()) == ["bia"]

    def test_get_chatml(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "Oi!", "Olá, Alex!")
        chatml = history.get_chatml("alex", "guardian", system_prompt="Você é Nicky.")
        assert chatml.startswith("<|im_start|>system\nVocê é Nicky.<|im_end|>")
        assert "<|im_start|>user\nOi!<|im_end|>" in chatml
        assert "<|im_start|>assistant\nOlá, Alex!<|im_end|>" in chatml

    def test_dump(self, history: ConversationHistory) -> None:
        d = history.dump()
        assert d["max_entries"] == 20
        assert "stats" in d


# ===========================================================================
# ConversationHistory — remoção
# ===========================================================================

class TestHistoryClear:
    """Tests for clearing history."""

    def test_clear_profile(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("alex", "nyx", "oi", "saudações")
        assert history.clear("alex", "guardian") == 2
        assert history.get_history("alex", "guardian") == []
        assert len(history.get_history("alex", "nyx")) == 2

    def test_clear_user(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("alex", "nyx", "oi", "saudações")
        assert history.clear("alex") == 4
        assert history.get_history("alex", "guardian") == []

    def test_clear_missing(self, history: ConversationHistory) -> None:
        assert history.clear("ninguem") == 0

    def test_clear_removes_file(self, history: ConversationHistory, tmp_path: Path) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.clear("alex", "guardian")
        path = tmp_path / "conversations" / "alex" / "guardian.json"
        assert not path.exists()

    def test_clear_all(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        history.add_interaction("bia", "guardian", "oi", "oi bia")
        assert history.clear_all() == 4
        assert history.list_users() == []


# ===========================================================================
# ConversationHistory — integração
# ===========================================================================

class TestHistoryIntegration:
    """End-to-end: escrever, persistir, recarregar, formatar ChatML."""

    def test_full_workflow(self, tmp_path: Path) -> None:
        h1 = ConversationHistory(base_dir=tmp_path / "c", max_entries=10)
        h1.add_interaction("alex", "guardian", "Qual a capital do Brasil?", "Brasília.")
        h1.add_interaction("alex", "guardian", "Obrigado!", "De nada!")

        h2 = ConversationHistory(base_dir=tmp_path / "c", max_entries=10)
        h2.load_all()
        chatml = h2.get_chatml("alex", "guardian", system_prompt="Você é Nicky.")
        assert "<|im_start|>user\nQual a capital do Brasil?<|im_end|>" in chatml
        assert "<|im_start|>assistant\nBrasília.<|im_end|>" in chatml

    def test_read_only_copies(self, history: ConversationHistory) -> None:
        history.add_interaction("alex", "guardian", "oi", "olá")
        msgs = history.get_history("alex", "guardian")
        msgs.append(Message(role="user", content="hack"))
        assert len(history.get_history("alex", "guardian")) == 2