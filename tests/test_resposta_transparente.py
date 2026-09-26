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


class TestAntiRecusaAdmin:
    """O modelo às vezes recusa dados operacionais mesmo com o prompt de
    dono — _refusal_reason é o gatilho do retry/roteamento pela action real.
    """

    def test_recusas_tipicas_do_gemma_sao_detectadas(self) -> None:
        recusas = [
            "Desculpe, mas não posso fornecer informações sobre IPs.",
            "Não tenho acesso físico a um servidor.",
            "Por razões de segurança, não revelo portas abertas.",
            "Não posso fornecer essas informações.",
        ]
        for resposta in recusas:
            motivo = Orchestrator._refusal_reason(resposta, "admin")
            assert motivo, f"recusa não detectada: {resposta}"

    def test_etiqueta_de_log_e_recusa_para_admin(self) -> None:
        assert Orchestrator._refusal_reason(
            "[CRIT][ERROR] Não há informação disponível.", "admin"
        )

    def test_resposta_normal_nao_e_recusa(self) -> None:
        assert Orchestrator._refusal_reason(
            "O IP local do servidor é 192.168.0.250.", "admin"
        ) == ""

    def test_para_o_user_a_mesma_resposta_e_aceita(self) -> None:
        # O papel user NÃO aciona o anti-recusa (a vedação é dele de direito).
        assert Orchestrator._refusal_reason(
            "Não posso fornecer informações sobre IPs.", "user"
        ) == ""

    def test_vazia_nao_e_recusa(self) -> None:
        assert Orchestrator._refusal_reason("", "admin") == ""


class TestIntencaoIpEPortas:
    """"ip do servidor" e "portas abertas" vão para a ACTION real (dado do
    sistema), não para o LLM — é o que impede a recusa/alucinação."""

    def test_pergunta_de_ip_cai_na_action(self) -> None:
        from core.intents import detect_action_intent
        for pergunta in (
            "qual o ip do servidor?",
            "qual é o ip local da máquina",
            "meu ip externo",
        ):
            assert detect_action_intent(pergunta) == ("ip_address", {}), pergunta

    def test_pergunta_de_portas_cai_na_action(self) -> None:
        from core.intents import detect_action_intent
        for pergunta in (
            "quais portas estão abertas?",
            "porta 8000 está em uso?",
            "portas escutando agora",
        ):
            assert detect_action_intent(pergunta) == (
                "listening_ports", {}
            ), pergunta

    def test_palavra_com_ip_no_meio_nao_e_intencao(self) -> None:
        from core.intents import detect_action_intent
        assert detect_action_intent("qual o melhor roteador do mercado") is None

    def test_processos_continuam_process_list(self) -> None:
        from core.intents import detect_action_intent
        assert detect_action_intent("quantos processos estão rodando?") == (
            "process_list", {}
        )
