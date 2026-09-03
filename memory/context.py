"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/context.py
Descrição: Gerenciador de contexto — estimativa de tokens, encaixe do
           histórico no orçamento do LLM e prevenção de estouro.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/context_manager.py
  - ROADMAP_ABSORCAO.md Fase 2, item 2.5

Architecture:
    Sem tokenizador nativo disponível, a estimativa usa heurística de
    caracteres por token (padrão ~4 chars/token, comum para modelos
    Byte-Pair Encoding). O ContextManager encaixa o máximo de mensagens
    RECENTES do histórico dentro do orçamento, descartando as mais antigas,
    e pode truncar textos longos. A saída pode ser ChatML direto.

Usage:
    from memory.context import ContextManager

    ctx = ContextManager(max_tokens=2048, reserved_tokens=256)
    messages = history.get_history("alex", "guardian")
    fit = ctx.fit(messages)                     # lista enxuta
    chatml = ctx.fit_chatml(messages, "Você é Nicky.")  # string ChatML
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from memory.history import build_chatml

logger = logging.getLogger("omega.memory.context")

NICKY_PREFIX = "[NICKY][{level}]"

__signature__ = "OD // CORE"


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# Estimativa de tokens
# ---------------------------------------------------------------------------

DEFAULT_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str, *, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> int:
    """Estima o número de tokens de um texto.

    Heurística: tokens ≈ caracteres / chars_per_token (arredondado para cima).
    Texto vazio → 0.
    """
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token) + 1)


def _message_text(msg: Any) -> str:
    """Extrai o texto de uma mensagem (Message ou dict)."""
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    content = getattr(msg, "content", "")
    return str(content if content is not None else "")


def _message_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", "user"))
    return str(getattr(msg, "role", "user"))


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------

class ContextManager:
    """Gerenciador de contexto com prevenção de estouro de tokens.

    Attributes:
        max_tokens:      Orçamento total de tokens da janela.
        reserved_tokens: Reserva para a resposta do modelo (output).
        chars_per_token: Heurística da estimativa.
        estimator:       Função de estimativa (padrão: estimate_tokens).
    """

    def __init__(
        self,
        *,
        max_tokens: int = 2048,
        reserved_tokens: int = 256,
        chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
        estimator: Optional[Callable[[str], int]] = None,
    ) -> None:
        if max_tokens < 16:
            raise ValueError("max_tokens deve ser >= 16")
        self._max_tokens = max_tokens
        self._reserved_tokens = max(0, reserved_tokens)
        self._chars_per_token = chars_per_token
        self._estimator: Callable[[str], int] = estimator or (
            lambda text: estimate_tokens(text, chars_per_token=chars_per_token)
        )
        self._stats = {"calls": 0, "trimmed": 0, "tokens_saved": 0}

    # -- Propriedades --------------------------------------------------------

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def reserved_tokens(self) -> int:
        return self._reserved_tokens

    @property
    def budget(self) -> int:
        """Tokens disponíveis para o histórico (max - reserva)."""
        return max(0, self._max_tokens - self._reserved_tokens)

    def estimate(self, text: str) -> int:
        """Estima tokens de um texto."""
        return self._estimator(text)

    def can_fit(self, text: str) -> bool:
        """Verifica se um texto cabe no orçamento do histórico."""
        return self.estimate(text) <= self.budget

    # -- Encaixe -------------------------------------------------------------

    def fit(self, messages: list[Any]) -> list[Any]:
        """Encaixa o máximo de mensagens RECENTES dentro do orçamento.

        As mensagens mais antigas são descartadas primeiro. A ordem final
        preserva a ordem original (cronológica).

        Returns:
            Lista reduzida de mensagens que cabem no orçamento.
        """
        self._stats["calls"] += 1
        if not messages:
            return []

        # Greedy reverso: acumula a partir do fim (mais recentes)
        total = 0
        keep: list[Any] = []
        for msg in reversed(messages):
            tokens = self.estimate(_message_text(msg))
            if total + tokens > self.budget:
                break
            total += tokens
            keep.append(msg)

        result = list(reversed(keep))
        dropped = len(messages) - len(result)
        if dropped > 0:
            saved = sum(self.estimate(_message_text(m)) for m in messages[:dropped])
            self._stats["trimmed"] += 1
            self._stats["tokens_saved"] += saved
            _audit_nicky(
                "INFO",
                "Context trimmed",
                dropped=dropped,
                tokens_saved=saved,
                kept=len(result),
            )
        return result

    def fit_chatml(
        self,
        messages: list[Any],
        system_prompt: str = "",
    ) -> str:
        """Encaixa o histórico e retorna em formato ChatML.

        O system_prompt é sempre incluído (se fornecido) e conta no orçamento.
        """
        self._stats["calls"] += 1
        system_tokens = self.estimate(system_prompt) if system_prompt else 0
        budget = self.budget
        if system_tokens >= budget:
            # Sem espaço nem para o system prompt: retorna só ele truncado?
            # Melhor: retorna vazio se nem o system cabe.
            if self._max_tokens < system_tokens:
                return ""
            return build_chatml([], system_prompt=system_prompt)

        available = budget - system_tokens
        total = 0
        keep: list[Any] = []
        for msg in reversed(messages):
            tokens = self.estimate(_message_text(msg))
            if total + tokens > available:
                break
            total += tokens
            keep.append(msg)

        result = list(reversed(keep))
        if len(result) < len(messages):
            self._stats["trimmed"] += 1
            self._stats["tokens_saved"] += sum(
                self.estimate(_message_text(m)) for m in messages[: len(messages) - len(result)]
            )
        return build_chatml(result, system_prompt=system_prompt)

    def truncate(self, text: str, max_tokens: Optional[int] = None) -> str:
        """Trunca um texto para caber em max_tokens (padrão: orçamento).

        Returns:
            O texto truncado (mantém o início? não — mantém o fim do texto,
            preservando a informação mais recente da mensagem).
        """
        limit = max_tokens if max_tokens is not None else self.budget
        if self.estimate(text) <= limit:
            return text
        chars = int(limit * self._chars_per_token)
        truncated = text[-chars:]
        # Recorta no limite de caracteres até caber (heurística simples)
        while self.estimate(truncated) > limit and len(truncated) > 0:
            truncated = truncated[1:]
        self._stats["trimmed"] += 1
        self._stats["tokens_saved"] += self.estimate(text) - self.estimate(truncated)
        return truncated

    # -- Métricas ------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def dump(self) -> dict[str, Any]:
        return {
            "max_tokens": self._max_tokens,
            "reserved_tokens": self._reserved_tokens,
            "budget": self.budget,
            "chars_per_token": self._chars_per_token,
            "stats": self.stats(),
        }