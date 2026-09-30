"""
OMEGA DRAKON • TESTS
Módulo: tests/test_personality.py
Descrição: Testes da personalidade da Interface Viva (agents/nicky_virthy/
           personality.py) e da injeção de default_system_prompt no
           Orchestrator (core/orchestrator.py): identidade Nicky Virthy,
           tom por perfil, protocolo NICKY e fallback do prompt.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - agents/nicky_virthy/IDENTITY.md e SOUL.md (canônicos)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.5
"""

from __future__ import annotations

import pytest

from agents.nicky_virthy.personality import (
    DEFAULT_PROFILE,
    PROFILES,
    _read_canonical,
    build_identity_prompt,
    get_system_prompt,
    profile_names,
)


class TestPersonality:
    """Estrutura e conteúdo do system prompt da Nicky."""

    def test_default_profile_is_guardian(self) -> None:
        assert DEFAULT_PROFILE == "guardian"
        assert "guardian" in PROFILES
        assert len(PROFILES) == 7  # guardian/regulus/luma/vox/athenae/nyx/nexus

    def test_identity_core_present(self) -> None:
        prompt = get_system_prompt("guardian")
        assert "Nicky Virthy" in prompt
        assert "Omega Drakon" in prompt
        assert "Alex Projeti" in prompt
        assert "Tecnologia que respira" in prompt
        assert "OD // CORE" in prompt
        assert "português do Brasil" in prompt

    def test_not_a_generic_chatbot(self) -> None:
        prompt = get_system_prompt()
        assert "NÃO é um chatbot genérico" in prompt
        assert "modelo de linguagem base" in prompt

    def test_nicky_protocol_included(self) -> None:
        prompt = get_system_prompt()
        assert "[NICKY][INFO|WARN|CRIT|ONLINE]" in prompt

    def test_profile_tone_changes(self) -> None:
        guardian = get_system_prompt("guardian")
        luma = get_system_prompt("luma")
        assert "Perfil ativo: guardian" in guardian
        assert "Perfil ativo: luma" in luma
        assert "explicações didáticas" in luma

    def test_unknown_profile_falls_back_to_guardian(self) -> None:
        prompt = build_identity_prompt("fantasma")
        assert "Perfil ativo: guardian" in prompt

    def test_profile_names(self) -> None:
        assert set(profile_names()) == set(PROFILES)

    def test_read_canonical_existente(self) -> None:
        """Identidade canônica lida do disco (IDENTITY.md)."""
        content = _read_canonical("IDENTITY.md")
        assert content is not None
        assert "Nicky Virthy" in content or "Omega Drakon" in content

    def test_read_canonical_ausente_retorna_none(self) -> None:
        """Arquivo inexistente degrada para None (best-effort)."""
        assert _read_canonical("NAO_EXISTE.md") is None

    def test_motor_real_declarado_em_todos_os_papeis(self) -> None:
        """Caso real §14 (30/09): 'qual o LLM que está usando' → o gemma
        respondeu 'OpenAI GPT-4' (falso). O prompt DEVE declarar o motor
        local em TODOS os papéis (identidade não é segredo — o
        /capabilities já publica 'gemma-4-E4B via llama-server')."""
        for role in ("admin", "user", "anon"):
            prompt = get_system_prompt("guardian", role=role)
            assert "gemma" in prompt.lower(), f"motor real ausente no papel {role}"
            assert "llama-server" in prompt.lower(), f"llama-server ausente no papel {role}"
            # proibição explícita de assumir identidade de serviço de nuvem
            assert "Nunca afirme ser" in prompt, f"proibição ausente no papel {role}"

    def test_motor_real_em_todos_os_perfis(self) -> None:
        prompt_por_perfil = {
            perfil: get_system_prompt(perfil).lower() for perfil in PROFILES
        }
        for perfil, prompt in prompt_por_perfil.items():
            assert "gemma" in prompt, f"motor real ausente no perfil {perfil}"

    def test_agenda_inexistente_declarada_em_todos_os_papeis(self) -> None:
        """Caso real §14 (30/09): 'sou o dono adm' → o gemma INVENTOU 3
        tarefas falsas de agenda. O prompt DEVE dizer que agenda/calendário
        não existem e proibir inventar conteúdo para preencher a lacuna, em
        TODOS os papéis (o dono também merece a verdade)."""
        for role in ("admin", "user", "anon"):
            prompt = get_system_prompt("guardian", role=role)
            assert "NÃO tem agenda" in prompt, f"agenda inexistente ausente no papel {role}"
            assert "NUNCA invente" in prompt, f"proibição de inventar ausente no papel {role}"


# ===========================================================================
# Injeção no Orchestrator (default_system_prompt)
# ===========================================================================

class TestOrchestratorSystemPrompt:
    """default_system_prompt do config é usado quando não há explícito."""

    @pytest.mark.asyncio
    async def test_default_prompt_used_when_empty(self, monkeypatch) -> None:
        from core.llm import OpenAICompatProvider
        from core.orchestrator import Orchestrator, OrchestratorConfig

        captured: dict = {}

        async def fake_generate(prompt: str, **options):
            captured["prompt"] = prompt
            return "resposta"

        provider = OpenAICompatProvider(name="fake")
        monkeypatch.setattr(provider, "generate", fake_generate)
        orch = Orchestrator(
            providers=[provider],
            config=OrchestratorConfig(default_system_prompt="IDENTIDADE-OD"),
        )
        await orch.process("alex", "guardian", "oi")
        assert "IDENTIDADE-OD" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_explicit_prompt_overrides_default(self, monkeypatch) -> None:
        from core.llm import OpenAICompatProvider
        from core.orchestrator import Orchestrator, OrchestratorConfig

        captured: dict = {}

        async def fake_generate(prompt: str, **options):
            captured["prompt"] = prompt
            return "resposta"

        provider = OpenAICompatProvider(name="fake")
        monkeypatch.setattr(provider, "generate", fake_generate)
        orch = Orchestrator(
            providers=[provider],
            config=OrchestratorConfig(default_system_prompt="IDENTIDADE-OD"),
        )
        await orch.process(
            "alex", "guardian", "oi", system_prompt="PROMPT-EXPLICITO"
        )
        assert "PROMPT-EXPLICITO" in captured["prompt"]
        assert "IDENTIDADE-OD" not in captured["prompt"]

    @pytest.mark.asyncio
    async def test_default_empty_keeps_old_behaviour(self, monkeypatch) -> None:
        from core.llm import OpenAICompatProvider
        from core.orchestrator import Orchestrator, OrchestratorConfig

        captured: dict = {}

        async def fake_generate(prompt: str, **options):
            captured["prompt"] = prompt
            return "resposta"

        provider = OpenAICompatProvider(name="fake")
        monkeypatch.setattr(provider, "generate", fake_generate)
        orch = Orchestrator(
            providers=[provider], config=OrchestratorConfig()
        )
        await orch.process("alex", "guardian", "oi")
        assert "IDENTIDADE" not in captured["prompt"]  # sem default