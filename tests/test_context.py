#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_context
Description: Unit tests for memory/context.py — token estimation and
             context overflow prevention (Fase 2, item 2.5).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import pytest

from memory.context import ContextManager, estimate_tokens
from memory.history import Message


# ===========================================================================
# Estimativa de tokens
# ===========================================================================

class TestEstimateTokens:
    """Tests for the token estimation heuristic."""

    def test_empty(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_text(self) -> None:
        assert estimate_tokens("oi") >= 1

    def test_longer_text_more_tokens(self) -> None:
        assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)

    def test_approx_chars_per_token(self) -> None:
        # 1000 chars / 4 = ~250 tokens
        tokens = estimate_tokens("a" * 1000)
        assert 240 <= tokens <= 260

    def test_custom_chars_per_token(self) -> None:
        tokens = estimate_tokens("a" * 100, chars_per_token=10)
        assert tokens == 11  # 100/10 + 1


# ===========================================================================
# ContextManager — propriedades
# ===========================================================================

class TestContextManagerProps:
    """Tests for basic properties."""

    def test_defaults(self) -> None:
        ctx = ContextManager()
        assert ctx.max_tokens == 2048
        assert ctx.reserved_tokens == 256
        assert ctx.budget == 1792

    def test_budget_is_max_minus_reserved(self) -> None:
        ctx = ContextManager(max_tokens=1000, reserved_tokens=200)
        assert ctx.budget == 800

    def test_invalid_max_tokens(self) -> None:
        with pytest.raises(ValueError):
            ContextManager(max_tokens=8)

    def test_can_fit(self) -> None:
        ctx = ContextManager(max_tokens=100, reserved_tokens=0)
        assert ctx.can_fit("texto curto") is True
        assert ctx.can_fit("x" * 1000) is False

    def test_estimate_method(self) -> None:
        ctx = ContextManager()
        assert ctx.estimate("oi") >= 1


# ===========================================================================
# ContextManager — fit
# ===========================================================================

class TestContextFit:
    """Tests for fitting messages into the budget."""

    def test_fit_keeps_all_when_small(self) -> None:
        ctx = ContextManager(max_tokens=1000, reserved_tokens=0)
        msgs = [Message(role="user", content="oi"), Message(role="assistant", content="olá")]
        assert ctx.fit(msgs) == msgs

    def test_fit_empty(self) -> None:
        ctx = ContextManager()
        assert ctx.fit([]) == []

    def test_fit_keeps_most_recent(self) -> None:
        ctx = ContextManager(max_tokens=60, reserved_tokens=0)
        msgs = [
            Message(role="user", content="mensagem antiga que não deve caber"),
            Message(role="user", content="nova"),
        ]
        fit = ctx.fit(msgs)
        assert "nova" in [m.content for m in fit]
        assert "mensagem antiga" not in [m.content for m in fit]

    def test_fit_preserves_order(self) -> None:
        ctx = ContextManager(max_tokens=1000, reserved_tokens=0)
        msgs = [Message(role="user", content=f"m{i}") for i in range(5)]
        fit = ctx.fit(msgs)
        assert [m.content for m in fit] == [f"m{i}" for i in range(5)]

    def test_fit_respects_budget(self) -> None:
        ctx = ContextManager(max_tokens=40, reserved_tokens=0)
        msgs = [Message(role="user", content="x" * 30) for _ in range(10)]
        fit = ctx.fit(msgs)
        # Cada mensagem tem ~8 tokens; orçamento 40 → até ~4 mensagens
        assert len(fit) < len(msgs)
        total = sum(ctx.estimate(m.content) for m in fit)
        assert total <= ctx.budget

    def test_fit_drops_everything_when_none_fits(self) -> None:
        ctx = ContextManager(max_tokens=20, reserved_tokens=0)
        msgs = [Message(role="user", content="x" * 200)]
        assert ctx.fit(msgs) == []

    def test_fit_stats(self) -> None:
        ctx = ContextManager(max_tokens=40, reserved_tokens=0)
        msgs = [Message(role="user", content="x" * 30) for _ in range(10)]
        ctx.fit(msgs)
        stats = ctx.stats()
        assert stats["calls"] == 1
        assert stats["trimmed"] == 1
        assert stats["tokens_saved"] > 0


# ===========================================================================
# ContextManager — fit_chatml
# ===========================================================================

class TestContextFitChatML:
    """Tests for ChatML fitting."""

    def test_fit_chatml_includes_system(self) -> None:
        ctx = ContextManager(max_tokens=1000, reserved_tokens=0)
        msgs = [Message(role="user", content="oi")]
        chatml = ctx.fit_chatml(msgs, system_prompt="Você é Nicky.")
        assert chatml.startswith("<|im_start|>system\nVocê é Nicky.<|im_end|>")
        assert "<|im_start|>user\noi<|im_end|>" in chatml

    def test_fit_chatml_trims_old(self) -> None:
        ctx = ContextManager(max_tokens=50, reserved_tokens=0)
        msgs = [Message(role="user", content="x" * 40) for _ in range(5)]
        chatml = ctx.fit_chatml(msgs)
        assert chatml.count("<|im_start|>") < len(msgs)

    def test_fit_chatml_empty(self) -> None:
        ctx = ContextManager(max_tokens=1000)
        assert ctx.fit_chatml([]) == ""

    def test_fit_chatml_system_too_big_returns_empty(self) -> None:
        ctx = ContextManager(max_tokens=40, reserved_tokens=0)
        assert ctx.fit_chatml([], system_prompt="x" * 1000) == ""


# ===========================================================================
# ContextManager — truncate
# ===========================================================================

class TestContextTruncate:
    """Tests for truncating a single text."""

    def test_no_truncation_when_fits(self) -> None:
        ctx = ContextManager(max_tokens=1000, reserved_tokens=0)
        text = "texto pequeno"
        assert ctx.truncate(text) == text

    def test_truncates_long_text(self) -> None:
        ctx = ContextManager(max_tokens=50, reserved_tokens=0)
        text = "y" * 1000
        truncated = ctx.truncate(text)
        assert len(truncated) < len(text)
        assert ctx.estimate(truncated) <= ctx.budget

    def test_truncate_custom_limit(self) -> None:
        ctx = ContextManager()
        text = "z" * 1000
        truncated = ctx.truncate(text, max_tokens=100)
        assert ctx.estimate(truncated) <= 100

    def test_truncate_stats(self) -> None:
        ctx = ContextManager(max_tokens=50, reserved_tokens=0)
        ctx.truncate("y" * 1000)
        assert ctx.stats()["trimmed"] == 1


# ===========================================================================
# ContextManager — integração com histórico
# ===========================================================================

class TestContextIntegration:
    """Integration with ConversationHistory messages."""

    def test_fit_history_messages(self) -> None:
        from memory.history import ConversationHistory

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            history = ConversationHistory(base_dir=Path(tmp) / "c")
            for i in range(10):
                history.add_interaction("alex", "guardian", f"pergunta {i}", f"resposta {i}")

            ctx = ContextManager(max_tokens=40, reserved_tokens=10)
            msgs = history.get_history("alex", "guardian")
            fit = ctx.fit(msgs)
            assert len(fit) < len(msgs)
            # Mantém as mais recentes
            assert fit[-1].content == "resposta 9"

    def test_fit_supports_dict_messages(self) -> None:
        ctx = ContextManager(max_tokens=1000, reserved_tokens=0)
        msgs = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}]
        assert ctx.fit(msgs) == msgs

    def test_dump(self) -> None:
        ctx = ContextManager(max_tokens=512, reserved_tokens=64)
        d = ctx.dump()
        assert d["max_tokens"] == 512
        assert d["budget"] == 448
        assert "stats" in d