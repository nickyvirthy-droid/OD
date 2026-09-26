"""
OMEGA DRAKON • TESTS
Módulo: tests/test_resposta_transparente.py
Descrição: Verificações do pacote "resposta transparente" (2026-09-26):
  1. O system prompt adapta os limites ao PAPEL: o dono (admin) tem acesso
     pleno aos dados do SISTEMA (IPs, portas, serviços) — o papel user
     mantém a vedação de infraestrutura.
  2. profile_display_name devolve o nome canônico da Plêiade
     ('regulus' → 'Regulus — O Conselheiro').
  3. O frame `done` do streaming e o to_dict() do OrchestrationResult
     expõem `profile_name` (quem respondeu).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import pytest

from agents.nicky_virthy.personality import get_system_prompt
from agents.profiles import profile_display_name
from core.orchestrator import Orchestrator, OrchestrationResult


class TestSystemPromptPorPapel:
    """O prompt adapta os limites ao papel de quem fala."""

    def test_admin_tem_acesso_pleno_aos_dados_do_sistema(self) -> None:
        prompt = get_system_prompt("guardian", "admin")
        assert "dono/admin" in prompt
        assert "IPs" in prompt and "portas" in prompt
        assert "Não esconda" in prompt

    def test_user_mantem_vedacao_de_infraestrutura(self) -> None:
        prompt = get_system_prompt("guardian", "user")
        assert "ficam privados" in prompt
        # A vedação do user CITA o que fica privado (não é uma liberação).
        assert "exigem aprovação do dono" in prompt

    def test_role_padrao_e_admin(self) -> None:
        # Compatibilidade: get_system_prompt sem role segue liberando o dono.
        assert "dono/admin" in get_system_prompt("guardian")

    def test_perfis_diferentes_tem_tom_diferente_mesmo_papel(self) -> None:
        admin_guardian = get_system_prompt("guardian", "admin")
        admin_nyx = get_system_prompt("nyx", "admin")
        assert "Perfil ativo: guardian" in admin_guardian
        assert "Perfil ativo: nyx" in admin_nyx


class TestProfileDisplayName:
    """Nome canônico da Plêiade para exibição (chips/bolha do app)."""

    @pytest.mark.parametrize(
        ("key", "esperado"),
        [
            ("guardian", "Nicky Virthy"),
            ("regulus", "Regulus"),
            ("nyx", "Nyx"),
            ("nexus", "Nexus"),
        ],
    )
    def test_nome_canonico(self, key: str, esperado: str) -> None:
        display = profile_display_name(key)
        assert display.startswith(esperado), display

    def test_desconhecido_devolve_a_proprio_chave(self) -> None:
        assert profile_display_name("perfil-fantasma") == "perfil-fantasma"

    def test_vazio_devolve_vazio(self) -> None:
        assert profile_display_name("") == ""


class TestProfileNameNaResposta:
    """to_dict expõe quem respondeu (REST e frame done do WS herdam)."""

    def test_to_dict_traz_profile_name(self) -> None:
        result = OrchestrationResult(
            user_id="alex",
            profile="regulus",
            text="pergunta",
            route="llm",
            message="resposta",
            llm_used="gemma-local",
        )
        data = result.to_dict()
        assert data["profile_name"].startswith("Regulus")
        assert data["profile"] == "regulus"

    def test_resolver_system_usa_identidade_por_perfil_e_papel(self) -> None:
        orch = Orchestrator.__new__(Orchestrator)  # só o helper, sem infra
        resolved = Orchestrator._resolve_system(orch, "", "nyx", "admin")
        assert "Perfil ativo: nyx" in resolved
        assert "dono/admin" in resolved

    def test_resolver_system_prefere_o_prompt_explcito(self) -> None:
        orch = Orchestrator.__new__(Orchestrator)
        explicit = "PROMPT_EXPLICITO_DO_CLIENTE"
        assert (
            Orchestrator._resolve_system(orch, explicit, "nyx", "admin")
            == explicit
        )
