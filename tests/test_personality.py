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
    VOICE_BLOCKS,
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
        """Caso real §14 (30/09): 'qual o LLM que está usando' → o modelo
        respondeu 'OpenAI GPT-4' (falso). O prompt DEVE declarar o motor
        local em TODOS os papéis (identidade não é segredo — o
        /capabilities publica o modelo servido).

        v1.17.1 (decisão do dono): o motor servido é QWEN
        (qwen2.5-coder-3b) — o gemma-4-E4B foi provado em sandbox (01/10)
        e não cabe com latência útil na máquina (7,7 GB RAM). Declarar
        'gemma' era mentira técnica; o teste fixa a verdade."""
        for role in ("admin", "user", "anon"):
            prompt = get_system_prompt("guardian", role=role)
            assert "qwen" in prompt.lower(), f"motor real (qwen) ausente no papel {role}"
            assert "llama-server" in prompt.lower(), f"llama-server ausente no papel {role}"
            # a mentira antiga NÃO pode voltar
            assert "gemma-4-e4b" not in prompt.lower(), f"declaração falsa de gemma no papel {role}"
            # proibição explícita de assumir identidade de serviço de nuvem
            assert "Nunca afirme ser" in prompt, f"proibição ausente no papel {role}"

    def test_motor_real_em_todos_os_perfis(self) -> None:
        prompt_por_perfil = {
            perfil: get_system_prompt(perfil).lower() for perfil in PROFILES
        }
        for perfil, prompt in prompt_por_perfil.items():
            assert "qwen" in prompt, f"motor real (qwen) ausente no perfil {perfil}"
            assert "gemma-4-e4b" not in prompt, f"declaração falsa de gemma no perfil {perfil}"

    def test_google_declarado_em_todos_os_papeis(self) -> None:
        """Caso real §14 (30/09): 'sou o dono adm' → o gemma INVENTOU 3
        tarefas falsas de agenda. Em 02/10 o Google (Drive/Agenda/Gmail)
        passou a existir em LEITURA: o prompt DEVE declarar a existência
        condicional e seguir proibindo inventar conteúdo, em TODOS os papéis
        (o dono também merece a verdade)."""
        for role in ("admin", "user", "anon"):
            prompt = get_system_prompt("guardian", role=role)
            assert "Google" in prompt, f"declaração do Google ausente no papel {role}"
            assert "LEITURA" in prompt, f"escopo (leitura) ausente no papel {role}"
            assert "NUNCA invente" in prompt, f"proibição de inventar ausente no papel {role}"


class TestVoiceBlocks:
    """v1.17.0 — personalidades realmente distintas.

    Queixa real do dono: 'as personalidades são diferentes, porque todas
    respondem do mesmo jeito'. Causa provada: o prompt levava ~95% de
    texto idêntico entre perfis e a única linha variável era o resumo
    'Tom do perfil: ...'. Cada perfil agora carrega um bloco de voz
    completo (COMO VOCÊ FALA) injetado com precedência sobre o resumo.
    """

    def test_todo_perfil_tem_bloco_de_voz(self) -> None:
        """Cada perfil canônico tem bloco de voz — sem exceção silenciosa."""
        assert set(VOICE_BLOCKS) == set(PROFILES), (
            "perfil sem bloco de voz: "
            f"{set(PROFILES) - set(VOICE_BLOCKS)}"
        )

    def test_bloco_entrar_no_prompt_de_todos_os_perfis(self) -> None:
        """O bloco 'COMO VOCÊ FALA' entra no prompt de TODOS os perfis."""
        for perfil in PROFILES:
            prompt = get_system_prompt(perfil)
            assert "COMO VOCÊ FALA" in prompt, f"bloco de voz ausente no perfil {perfil}"

    def test_bloco_tem_estrutura_completa(self) -> None:
        """Estrutura mínima do bloco: identidade, registro, o que faz,
        o que NUNCA faz, frase-assinatura e micro-exemplo."""
        for perfil, bloco in VOICE_BLOCKS.items():
            assert "Identidade:" in bloco, f"identidade ausente no bloco {perfil}"
            assert "Registro:" in bloco, f"registro ausente no bloco {perfil}"
            assert "O que faz:" in bloco, f"'o que faz' ausente no bloco {perfil}"
            assert "O que NUNCA faz:" in bloco, f"'o que nunca faz' ausente no bloco {perfil}"
            assert "Frase-assinatura" in bloco, f"frase-assinatura ausente no bloco {perfil}"
            assert "Micro-exemplo" in bloco, f"micro-exemplo ausente no bloco {perfil}"

    def test_blocos_sao_distintos_entre_si(self) -> None:
        """Par a par: nenhum bloco é igual a outro (se fossem, a queixa
        do dono continuaria de pé)."""
        chaves = sorted(VOICE_BLOCKS)
        for i, a in enumerate(chaves):
            for b in chaves[i + 1 :]:
                assert VOICE_BLOCKS[a] != VOICE_BLOCKS[b], (
                    f"blocos idênticos: {a} == {b}"
                )

    def test_marcador_de_nome_no_bloco(self) -> None:
        """Cada bloco nomeia a si mesmo (o LLM local lê o nome no bloco)."""
        nomes = {
            "guardian": "Guardian",
            "regulus": "Regulus",
            "luma": "Luma",
            "vox": "Vox",
            "athenae": "Athenae",
            "nyx": "Nyx",
            "nexus": "Nexus",
        }
        for perfil, nome in nomes.items():
            assert nome in VOICE_BLOCKS[perfil], (
                f"o bloco {perfil} não se nomeia como {nome}"
            )

    def test_bloco_com_precedencia_sobre_o_resumo(self) -> None:
        """O bloco vem DEPOIS do resumo 'Tom do perfil' no prompt final —
        precedência de instrução e distância mínima da geração."""
        prompt = get_system_prompt("regulus")
        pos_resumo = prompt.index("Tom do perfil:")
        pos_bloco = prompt.index("COMO VOCÊ FALA")
        assert pos_bloco > pos_resumo, "bloco de voz antes do resumo do tom"

    def test_micro_exemplos_distintos_e_nao_vazios(self) -> None:
        """Micro-exemplo é a dica mais forte de TOM para um LLM pequeno —
        tem que existir, ter conteúdo e ser diferente par a par."""
        exemplos: dict[str, str] = {}
        for perfil, bloco in VOICE_BLOCKS.items():
            marcador = "Micro-exemplo (começo literal de resposta): '"
            idx = bloco.index(marcador)
            resto = bloco[idx + len(marcador) :]
            conteudo = resto.split("'")[0].strip()
            assert conteudo, f"micro-exemplo vazio no perfil {perfil}"
            exemplos[perfil] = conteudo
        assert len(set(exemplos.values())) == len(exemplos), "micro-exemplos repetidos"

    def test_prompt_completo_varia_mais_que_uma_linha(self) -> None:
        """Guarda da causa raiz: o prompt de dois perfis DIFERE em muito
        mais que a antiga linha única 'Tom do perfil' (mín. 40 chars de
        diferença comum — antes eram ~60)."""
        import difflib

        p1 = get_system_prompt("nyx")
        p2 = get_system_prompt("athenae")
        comum = "".join(
            linha[2:]
            for linha in difflib.ndiff(p1.splitlines(), p2.splitlines())
            if linha.startswith("  ")
        )
        diferenca = len(p1) + len(p2) - 2 * len(comum)
        assert diferenca > 400, (
            f"prompts parecidos demais entre nyx e athenae (diferença {diferenca} chars)"
        )

    def test_tom_generico_permanece_por_compatibilidade(self) -> None:
        """O resumo antigo não saiu — testes e quem lê o prompt continuam
        contando com 'explicações didáticas' etc."""
        assert "explicações didáticas" in get_system_prompt("luma")


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