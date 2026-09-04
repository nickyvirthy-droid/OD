"""
OMEGA DRAKON • TESTS
Módulo: tests/test_orchestrator.py
Descrição: Testes do Orchestrator Pipeline (core/orchestrator.py) — Fase 3,
           item 3.4: as 8 etapas (rate limit → datetime → quick → cache →
           history → LLM → fallback → pós-processamento), atalhos e métricas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky core/orchestrator.py (pipeline de 8 etapas)
  - NICKY_LEGACY_ANALYSIS.md §4.2
  - ROADMAP_ABSORCAO.md Fase 3, item 3.4
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    OrchestrationResult,
    RateLimiter,
    RecordingProvider,
    StaticProvider,
    detect_datetime_question,
    build_datetime_line,
)
from memory.cache import LLMCache
from memory.history import ConversationHistory
from memory.quick_responses import QuickResponses


def _history(tmp_path: Path) -> ConversationHistory:
    return ConversationHistory(base_dir=tmp_path / "conversations")


def _cache(tmp_path: Path) -> LLMCache:
    return LLMCache(cache_dir=tmp_path / "llm_cache")


def _quick(tmp_path: Path) -> QuickResponses:
    return QuickResponses(data_dir=tmp_path / "quick", seed_defaults=False)


# ===========================================================================
# Rate Limiter
# ===========================================================================

class TestRateLimiter:
    """Janela deslizante por usuário."""

    def test_allows_until_limit(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.allow("u1") is True
        assert limiter.allow("u1") is True
        assert limiter.allow("u1") is False
        # usuários independentes
        assert limiter.allow("u2") is True

    def test_window_resets_after_time(self) -> None:
        ticks = iter([0.0, 1.0, 2.0, 61.0])
        limiter = RateLimiter(
            max_requests=2,
            window_seconds=60.0,
            clock=lambda: next(ticks),
        )
        assert limiter.allow("u1") is True
        assert limiter.allow("u1") is True
        assert limiter.allow("u1") is False  # t=2
        assert limiter.allow("u1") is True   # t=61 -> janela nova

    def test_remaining_and_clear(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60.0)
        assert limiter.remaining("u1") == 3
        limiter.allow("u1")
        assert limiter.remaining("u1") == 2
        assert limiter.clear("u1") == 1
        assert limiter.remaining("u1") == 3


# ===========================================================================
# Datetime PT-BR (etapa 2)
# ===========================================================================

class TestDatetimeDetection:
    """Detecção de perguntas de data/hora."""

    def _now(self) -> time.struct_time:
        return time.struct_time(
            (2026, 9, 3, 14, 5, 0, 3, 246, -1)  # quinta, 3/9/2026 14:05
        )

    def test_time_question(self) -> None:
        for text in ["que horas são?", "me diz a hora agora", "HORA ATUAL"]:
            answer = detect_datetime_question(text, now=self._now())
            assert answer == "Agora são 14:05."

    def test_date_question(self) -> None:
        for text in ["que dia é hoje?", "qual a data de hoje", "data atual"]:
            answer = detect_datetime_question(text, now=self._now())
            assert answer == (
                "Hoje é quinta-feira, 3 de setembro de 2026."
            )

    def test_regular_message_not_datetime(self) -> None:
        assert detect_datetime_question("como você está?", now=self._now()) is None

    def test_build_datetime_line(self) -> None:
        line = build_datetime_line(now=self._now())
        assert "quinta-feira, 3 de setembro de 2026" in line
        assert "14:05" in line


# ===========================================================================
# Orchestrator — atalhos (sem LLM)
# ===========================================================================

@pytest.mark.asyncio
class TestOrchestratorShortCircuits:
    """Etapas que respondem sem chamar o LLM."""

    async def test_datetime_route(self, tmp_path: Path) -> None:
        provider = RecordingProvider("qwen", "nunca")
        orch = Orchestrator(
            providers=[provider],
            history=_history(tmp_path),
        )
        result = await orch.process("alex", "guardian", "que horas são?")
        assert result.route == "datetime"
        assert result.message.startswith("Agora são")
        assert result.ok
        assert provider.prompts == []  # LLM não foi chamado

    async def test_quick_response_route(self, tmp_path: Path) -> None:
        quick = _quick(tmp_path)
        quick.add("oi", "Olá! 😊")
        provider = RecordingProvider("qwen", "nunca")
        orch = Orchestrator(providers=[provider], quick=quick)
        result = await orch.process("alex", "guardian", "Oi")
        assert result.route == "quick_response"
        assert result.message == "Olá! 😊"
        assert provider.prompts == []

    async def test_cache_route(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        provider = RecordingProvider("qwen", "resposta cacheada")
        orch = Orchestrator(providers=[provider], cache=cache, history=_history(tmp_path))
        first = await orch.process("alex", "guardian", "qual a capital do brasil?")
        assert first.route == "llm"
        # segunda chamada idêntica vem do cache
        second = await orch.process("alex", "guardian", "qual a capital do brasil?")
        assert second.route == "cache"
        assert second.message == "resposta cacheada"
        assert second.cached
        assert len(provider.prompts) == 1  # LLM chamado apenas uma vez

    async def test_cache_scoped_by_profile(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        provider = RecordingProvider("qwen", "resposta")
        orch = Orchestrator(providers=[provider], cache=cache)
        await orch.process("alex", "guardian", "olá mundo")
        second = await orch.process("alex", "luma", "olá mundo")
        assert second.route == "llm"  # perfil diferente = cache diferente

    async def test_short_circuit_does_not_persist_history(self, tmp_path: Path) -> None:
        history = _history(tmp_path)
        orch = Orchestrator(
            providers=[RecordingProvider("qwen", "x")],
            history=history,
        )
        await orch.process("alex", "guardian", "que dia é hoje?")
        assert len(history.get_history("alex", "guardian")) == 0


# ===========================================================================
# Orchestrator — caminho LLM completo
# ===========================================================================

@pytest.mark.asyncio
class TestOrchestratorLLM:
    """Etapas 5–8: histórico, LLM, fallback e pós-processamento."""

    async def test_llm_route_and_persistence(self, tmp_path: Path) -> None:
        history = _history(tmp_path)
        cache = _cache(tmp_path)
        provider = RecordingProvider("qwen", "resposta do llm")
        orch = Orchestrator(
            providers=[provider],
            history=history,
            cache=cache,
        )
        result = await orch.process("alex", "guardian", "fale sobre o OD")
        assert result.route == "llm"
        assert result.llm_used == "qwen"
        assert result.message == "resposta do llm"

        # pós-processamento: histórico gravado com turno completo
        msgs = history.get_history("alex", "guardian")
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[-1].llm_used == "qwen"

    async def test_prompt_contains_chatml_and_context(self, tmp_path: Path) -> None:
        history = _history(tmp_path)
        history.add_interaction("alex", "guardian", "pergunta antiga", "resposta antiga")
        provider = RecordingProvider("qwen", "ok")
        orch = Orchestrator(providers=[provider], history=history)
        await orch.process(
            "alex", "guardian", "pergunta nova",
            system_prompt="Você é o Nicky.",
        )
        prompt = provider.prompts[0]
        assert "<|im_start|>system" in prompt
        assert "Você é o Nicky." in prompt
        assert "pergunta antiga" in prompt and "resposta antiga" in prompt
        assert "pergunta nova" in prompt
        # datetime injetado no system context
        assert "Hoje é" in prompt

    async def test_inject_datetime_disabled(self, tmp_path: Path) -> None:
        provider = RecordingProvider("qwen", "ok")
        orch = Orchestrator(
            providers=[provider],
            history=_history(tmp_path),
            config=OrchestratorConfig(inject_datetime=False),
        )
        await orch.process("alex", "guardian", "oi")
        assert "Hoje é" not in provider.prompts[0]

    async def test_max_history_turns_limits_context(self, tmp_path: Path) -> None:
        history = _history(tmp_path)
        for i in range(4):
            history.add_interaction("alex", "guardian", f"p{i}", f"r{i}")
        provider = RecordingProvider("qwen", "ok")
        orch = Orchestrator(
            providers=[provider],
            history=history,
            config=OrchestratorConfig(max_history_turns=1),
        )
        await orch.process("alex", "guardian", "nova")
        prompt = provider.prompts[0]
        assert "p0" not in prompt and "r0" not in prompt
        assert "p1" not in prompt and "r1" not in prompt
        assert "p3" in prompt and "r3" in prompt  # último turno preservado

    async def test_async_provider_supported(self, tmp_path: Path) -> None:
        orch = Orchestrator(
            providers=[RecordingProvider("async_llm", "async ok")],
            history=_history(tmp_path),
        )
        result = await orch.process("alex", "guardian", "teste")
        assert result.route == "llm"
        assert result.message == "async ok"


# ===========================================================================
# Orchestrator — fallback (etapa 7)
# ===========================================================================

@pytest.mark.asyncio
class TestOrchestratorFallback:
    """Providers em ordem com fallback."""

    async def test_fallback_when_primary_fails(self, tmp_path: Path) -> None:
        primary = RecordingProvider("qwen", fail=True)
        backup = RecordingProvider("gemini", "resposta do fallback")
        orch = Orchestrator(
            providers=[primary, backup],
            history=_history(tmp_path),
        )
        result = await orch.process("alex", "guardian", "tarefa")
        assert result.route == "fallback"
        assert result.llm_used == "gemini"
        assert result.fallback_used is True
        assert result.message == "resposta do fallback"
        assert orch.metrics.snapshot()["fallback"] == 1

    async def test_all_providers_fail(self, tmp_path: Path) -> None:
        orch = Orchestrator(
            providers=[RecordingProvider("a", fail=True), RecordingProvider("b", fail=True)],
        )
        result = await orch.process("alex", "guardian", "tarefa")
        assert result.route == "llm_unavailable"
        assert not result.ok
        assert result.message == "Nenhum LLM disponível no momento."

    async def test_no_providers(self, tmp_path: Path) -> None:
        orch = Orchestrator()
        result = await orch.process("alex", "guardian", "tarefa")
        assert result.route == "llm_unavailable"

    async def test_unavailable_message_custom(self, tmp_path: Path) -> None:
        orch = Orchestrator(
            config=OrchestratorConfig(unavailable_message="sem LLM agora"),
        )
        result = await orch.process("alex", "guardian", "tarefa")
        assert result.message == "sem LLM agora"


# ===========================================================================
# Orchestrator — rate limit (etapa 1)
# ===========================================================================

@pytest.mark.asyncio
class TestOrchestratorRateLimit:
    """Limite de mensagens por usuário."""

    async def test_rate_limited_after_limit(self, tmp_path: Path) -> None:
        orch = Orchestrator(
            providers=[StaticProvider("qwen", "ok")],
            config=OrchestratorConfig(rate_limit_max=2),
        )
        assert (await orch.process("alex", "guardian", "m1")).route == "llm"
        assert (await orch.process("alex", "guardian", "m2")).route == "llm"
        third = await orch.process("alex", "guardian", "m3")
        assert third.route == "rate_limited"
        assert not third.ok
        # outro usuário não é afetado
        assert (await orch.process("bia", "guardian", "m1")).route == "llm"

    async def test_rate_limited_metrics(self, tmp_path: Path) -> None:
        orch = Orchestrator(
            providers=[StaticProvider("qwen", "ok")],
            config=OrchestratorConfig(rate_limit_max=1),
        )
        await orch.process("alex", "guardian", "m1")
        await orch.process("alex", "guardian", "m2")
        snap = orch.metrics.snapshot()
        assert snap["rate_limited"] == 1
        assert snap["processed"] == 2


# ===========================================================================
# Orchestrator — Event Bus
# ===========================================================================

@pytest.mark.asyncio
class TestOrchestratorEventBus:
    """Publicação do evento orchestrator.responded."""

    async def test_publishes_responded(self, tmp_path: Path) -> None:
        bus = EventBus()
        await bus.start()
        received: list[Any] = []

        async def on_event(e: Any) -> None:
            received.append(e)

        bus.subscribe_handler("orchestrator.responded", on_event)
        orch = Orchestrator(
            providers=[StaticProvider("qwen", "oi")],
            event_bus=bus,
        )
        result = await orch.process("alex", "guardian", "olá")
        assert len(received) == 1
        event = received[0]
        assert event.data["route"] == "llm"
        assert event.data["message"] == "oi"
        assert event.data["user_id"] == "alex"

    async def test_no_event_without_bus(self, tmp_path: Path) -> None:
        orch = Orchestrator(providers=[StaticProvider("qwen", "oi")])
        result = await orch.process("alex", "guardian", "olá")  # não deve quebrar
        assert result.route == "llm"


# ===========================================================================
# Orchestrator — métricas e dump
# ===========================================================================

class TestOrchestratorMetrics:
    """Métricas e diagnóstico."""

    @pytest.mark.asyncio
    async def test_metrics_by_route(self, tmp_path: Path) -> None:
        quick = _quick(tmp_path)
        quick.add("oi", "olá")
        cache = _cache(tmp_path)
        orch = Orchestrator(
            providers=[RecordingProvider("qwen", "x")],
            history=_history(tmp_path),
            cache=cache,
            quick=quick,
            config=OrchestratorConfig(rate_limit_max=100),
        )
        await orch.process("alex", "guardian", "oi")                    # quick
        await orch.process("alex", "guardian", "que horas são?")        # datetime
        await orch.process("alex", "guardian", "mensagem llm")          # llm
        await orch.process("alex", "guardian", "mensagem llm")          # cache
        snap = orch.metrics.snapshot()
        assert snap["processed"] == 4
        assert snap["quick"] == 1
        assert snap["datetime"] == 1
        assert snap["llm"] == 1
        assert snap["cache_hits"] == 1
        assert snap["errors"] == 0
        assert snap["avg_latency_ms"] >= 0

    def test_dump(self) -> None:
        orch = Orchestrator(providers=[StaticProvider("qwen", "x")])
        dump = orch.dump()
        assert dump["providers"] == ["qwen"]
        assert len(dump["stages"]) == 8
        assert dump["config"]["rate_limit_max"] == 10
        assert dump["metrics"]["processed"] == 0

    def test_add_provider(self) -> None:
        orch = Orchestrator()
        assert orch.dump()["providers"] == []
        orch.add_provider(StaticProvider("qwen", "x"))
        orch.add_provider(StaticProvider("gemini", "y"))
        assert orch.dump()["providers"] == ["qwen", "gemini"]

    def test_result_to_dict(self) -> None:
        result = OrchestrationResult(user_id="a", profile="p", text="t", route="llm", message="m")
        data = result.to_dict()
        assert data["route"] == "llm"
        assert data["ok"] is True
        assert data["message"] == "m"


# ===========================================================================
# Orchestrator — ActionRegistry integration (Fase 7.4)
# ===========================================================================

@pytest.mark.asyncio
class TestOrchestratorActionRegistry:
    """Integração do Orchestrator com ActionRegistry para execução de ações.

    O Orchestrator agora suporta execute_action() para executar ações do
    catálogo via ActionRegistry, com controle de acesso via Security Layer.
    """

    async def test_execute_action_with_registry(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        assert orch.action_registry is not None
        assert orch.action_registry.metrics.actions == 56

    async def test_execute_action_success(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        result = await orch.execute_action("system_info", role="admin")
        assert result is not None
        assert "system" in result
        assert "node" in result

    async def test_execute_action_datetime(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        result = await orch.execute_action("datetime", role="admin")
        assert result is not None
        assert "date" in result
        assert "time" in result

    async def test_execute_action_with_params(self, tmp_path: Path) -> None:
        """Testa execução de ação com parâmetros válidos.

        action_info com name via params.
        """
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        result = await orch.execute_action(
            "action_info",
            params={"name": "system_info"},
            role="admin",
        )
        assert result is not None
        assert "name" in result
        assert result["name"] == "system_info"

    async def test_execute_action_action_list(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        result = await orch.execute_action("action_list", role="admin")
        assert result is not None
        assert "actions" in result
        assert len(result["actions"]) == 56

    async def test_execute_action_without_registry_raises(self, tmp_path: Path) -> None:
        orch = Orchestrator(providers=[StaticProvider("test", "ok")])
        with pytest.raises(RuntimeError, match="ActionRegistry não disponível"):
            await orch.execute_action("system_info", role="admin")

    async def test_execute_action_denied_role(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        # Role "agent" sem permissão deve retornar None
        result = await orch.execute_action("system_info", role="agent")
        assert result is None

    async def test_set_action_registry(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(providers=[StaticProvider("test", "ok")])
        assert orch.action_registry is None
        orch.set_action_registry(registry)
        assert orch.action_registry is not None
        assert orch.action_registry.metrics.actions == 56

    async def test_execute_action_after_set_registry(self, tmp_path: Path) -> None:
        from tools.registry import ActionRegistry
        from core.security import SecurityManager
        from tools.actions import build_registry

        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(providers=[StaticProvider("test", "ok")])
        orch.set_action_registry(registry)
        result = await orch.execute_action("system_info", role="admin")
        assert result is not None
        assert "system" in result

