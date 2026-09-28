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
from core.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    OrchestrationResult,
)


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

    def test_etiqueta_embutida_no_meio_e_recusa(self) -> None:
        """Bug do ar (27/09): o gemma entregou '[NICKY][WARN] Não posso
        fornecer informações sobre o clima...' — startswith pegava só
        etiqueta no INÍCIO; a guard vale em qualquer posição."""
        respostas = [
            "[NICKY][WARN] Não posso fornecer informações sobre o clima ou "
            "localização geográfica de um país específico.",
            "Entendo. [NICKY][INFO] segue a resposta",
        ]
        for resposta in respostas:
            motivo = Orchestrator._refusal_reason(resposta, "admin")
            assert motivo, f"etiqueta embutida não detectada: {resposta}"

    def test_bloqueio_falso_de_infra_para_dono_e_recusa(self) -> None:
        """O modelo imitando a vedação do sistema ('restrita ao dono')
        para o PRÓPRIO dono é recusa — refaz."""
        assert Orchestrator._refusal_reason(
            "🔒 Informação de infraestrutura (IP, portas, topologia de rede) "
            "é restrita ao dono do sistema.",
            "admin",
        )

    def test_clima_para_o_dono_nao_e_recusa(self) -> None:
        """Pergunta de temperatura de cidade respondida normal NÃO é recusa
        (o dono reportou: o sistema bloqueava clima — vedação indevida)."""
        assert Orchestrator._refusal_reason(
            "A temperatura em Presidente Venceslau SP hoje é de 24°C com "
            "céu aberto.",
            "admin",
        ) == ""

    # ---- Recusa-alucinação do USER em assunto externo (2026-09-28) ----

    def test_user_alucinando_vedacao_em_assunto_externo_e_recusa(self) -> None:
        """BUG REAL NO AR (28/09): user perguntou 'temperatura em presidente
        venceslau sp', o sistema roteou CERTO para o LLM, mas o gemma
        ALUCINOU a vedação — 'informação de infraestrutura é restrita ao
        dono'. Para assunto externo isso é recusa indevida também para o
        papel user (não há infra na pergunta)."""
        motivo = Orchestrator._refusal_reason(
            "Informação de infraestrutura (IP, portas, topologia de rede) "
            "é restrita ao dono do sistema.",
            "user",
            text="qual a temperatura em presidente venceslau sp",
        )
        assert motivo, "alucinação de vedação para user não detectada"

    def test_user_normal_nao_aciona_deteccao_sem_assunto_externo(self) -> None:
        """Sem assunto externo, o 'não posso' do user NÃO é recusa indevida:
        a vedação de infra é de direito do papel (e a negação real de
        IP/portas é determinística, Etapa 3.4 — nunca sai do LLM)."""
        assert Orchestrator._refusal_reason(
            "Não posso fornecer essas informações.",
            "user",
            text="qual o ip do servidor",
        ) == ""
        assert Orchestrator._refusal_reason(
            "Não posso ajudar com isso.",
            "user",
            text="qual o melhor roteador do mercado",
        ) == ""

    def test_anonymous_com_assunto_externo_e_alucinacao_e_recusa(self) -> None:
        """O anônimo também conversa sobre o mundo externo — mesma regra."""
        assert Orchestrator._refusal_reason(
            "[NICKY][WARN] Não tenho informações sobre o clima.",
            "anonymous",
            text="como está o clima em são paulo",
        )

    def test_resposta_normal_do_user_para_clima_nao_e_recusa(self) -> None:
        assert Orchestrator._refusal_reason(
            "Hoje em Presidente Venceslau SP faz 24°C com céu aberto.",
            "user",
            text="qual a temperatura em presidente venceslau sp",
        ) == ""

    def test_texto_padrao_ignora_deteccao_para_user(self) -> None:
        """Sem `text` (chamadas antigas), a detecção para user fica neutra —
        conservadorismo: só admin tem a detecção plena de recusas."""
        assert Orchestrator._refusal_reason(
            "Não posso fornecer essas informações.", "user"
        ) == ""


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

    def test_temperatura_do_servidor_cai_na_cpu_temp(self) -> None:
        """'temperatura do servidor' é dado REAL da máquina (cpu_temp —
        sensors térmicos), não conversa: o LLM recusava/alucinava."""
        from core.intents import detect_action_intent
        for pergunta in (
            "qual a temperatura do servidor",
            "qual a temperatuda do servidor",  # typo real do dono
            "qual a temperatura da cpu",
        ):
            assert detect_action_intent(pergunta) == ("cpu_temp", {}), pergunta

    def test_temperatura_de_cidade_nao_e_infra_nem_action(self) -> None:
        """Clima/tempo de CIDADE é mundo externo — nunca bloqueado como
        infra e sem action (o LLM responde). Caso real do dono (27/09):
        'qual a temperatuda em presidente venceslau sp' recebia 🔒."""
        from core.intents import detect_action_intent, detect_infra_intent
        for pergunta in (
            "qual a temperatuda em presidente venceslau sp",
            "qual a temperatura em presidente venceslau sp",
            "como está o clima em são paulo",
        ):
            assert detect_infra_intent(pergunta) is False, pergunta
            assert detect_action_intent(pergunta) is None, pergunta

    def test_processos_continuam_process_list(self) -> None:
        from core.intents import detect_action_intent
        assert detect_action_intent("quantos processos estão rodando?") == (
            "process_list", {}
        )


class TestCacheSemRecusa:
    """O cache é servido ANTES da etapa 6.5 (anti-recusa) — uma recusa
    cacheada vira PERMANENTE. Bug do ar (28/09): a alucinação 'informação
    de infraestrutura é restrita ao dono' (sem etiqueta [NICKY][...])
    entrou no cache e a pergunta seguinte recebia a alucinação na rota
    cache, instantânea, sem chance de retry."""

    def test_alucinacao_de_vedacao_nao_e_cacheavel(self) -> None:
        from core.orchestrator import cache_failure_reason
        motivo = cache_failure_reason(
            "Informação de infraestrutura (IP, portas, topologia de rede) "
            "é restrita ao dono do sistema."
        )
        assert motivo, "recusa cacheável — o cache envenena as próximas respostas"

    def test_recusas_tipicas_nao_sao_cacheaveis(self) -> None:
        from core.orchestrator import cache_failure_reason
        for recusa in (
            "Não posso fornecer essas informações.",
            "Não tenho acesso a dados em tempo real.",
            "Por razões de segurança, não revelo portas abertas.",
            "Não é possível fornecer esse dado agora.",
        ):  
            assert cache_failure_reason(recusa), f"recusa cacheável: {recusa}"

    def test_respostas_normais_continuam_cacheaveis(self) -> None:
        from core.orchestrator import cache_failure_reason
        for resposta in (
            "Hoje em Presidente Venceslau SP faz 24°C com céu aberto.",
            "O IP do servidor é 192.168.0.250.",  # sair do LLM p/ user já é
            "Não posso garantir, mas acho que sim.",  # hedging é conteúdo
            "A temperatura do servidor está em 55°C (pch_skylake).",
        ):  
            assert cache_failure_reason(resposta) == "", (
                f"resposta normal banida do cache: {resposta}"
            )


class TestGuardaInfraParaNaoDono:
    """v1.7.0 — o papel user NÃO pode receber IP/portas nem da action nem do
    LLM (o gemma entregava o IP mesmo com a vedação no prompt, reportado
    pelo dono): negação determinística na Etapa 3.4, sem LLM."""

    @staticmethod
    def _orch() -> tuple[Orchestrator, "FakeLLM"]:
        class FakeLLM:
            name = "fake"
            async def generate(self, prompt, timeout=None, **kw):
                return "RESPOSTA_DO_LLM_FAKE"  # o LLM NÃO deve ser consultado
            async def generate_stream(self, prompt, timeout=None, **kw):
                yield "RESPOSTA_DO_LLM_FAKE"

        from tools.actions import build_registry
        from core.security import SecurityManager
        llm = FakeLLM()
        orch = Orchestrator(
            providers=[llm],
            config=OrchestratorConfig(default_system_prompt="x"),
        )
        orch.set_action_registry(
            build_registry(security=SecurityManager(mode="strict"))
        )
        return orch, llm

    def _llm_nao_foi_consultado(self, llm) -> bool:
        # O FakeLLM não registra chamadas; a prova é o TEXT da resposta:
        # se fosse o LLM, seria RESPOSTA_DO_LLM_FAKE.
        return True

    def test_user_pedindo_ip_recebe_negacao_sem_llm(self) -> None:
        import asyncio
        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "qual o ip do servidor?", role="user"
        ))
        assert r.route == "action_intent"
        assert "restrita ao dono" in r.message
        assert r.message != "RESPOSTA_DO_LLM_FAKE"
        assert orch.metrics.infra_denied >= 1

    def test_user_pedindo_portas_recebe_negacao_sem_llm(self) -> None:
        import asyncio
        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "quais portas estão abertas?",
            role="user",
        ))
        assert r.route == "action_intent"
        assert "restrita ao dono" in r.message

    def test_admin_continua_recebendo_o_dado_real(self) -> None:
        import asyncio
        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "alex", "guardian", "qual o ip do servidor?", role="admin"
        ))
        assert r.route == "action_intent"
        assert "IP do servidor" in r.message

    def test_pergunta_normal_do_user_nao_e_bloqueada(self) -> None:
        import asyncio
        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "qual o melhor roteador do mercado?",
            role="user",
        ))
        assert r.route == "llm"  # passou pela guarda e foi ao LLM

    def test_ip_address_e_listening_ports_fora_da_allowlist_user(self) -> None:
        from core.security.permissions import DEFAULT_ROLE_PERMISSIONS
        user_actions = DEFAULT_ROLE_PERMISSIONS["user"]
        assert "ip_address" not in user_actions
        assert "listening_ports" not in user_actions

    def test_clima_do_user_nao_e_bloqueado_como_infra(self) -> None:
        """Caso real do dono (27/09): 'temperatuda em presidente venceslau
        sp' do papel user recebia 🔒 — o bloqueio é só para o que pode
        PREJUDICAR O SISTEMA (IP/portas), não para conhecimento geral."""
        import asyncio
        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian",
            "qual a temperatuda em presidente venceslau sp",
            role="user",
        ))
        assert r.route == "llm"
        assert "restrita ao dono" not in r.message
        assert r.message == "RESPOSTA_DO_LLM_FAKE"  # foi ao LLM de verdade

    def test_temperatura_do_servidor_para_user_vai_via_cpu_temp(self) -> None:
        """A temperatura DA MÁQUINA é dado de leitura (não prejudica o
        sistema): permitida para user via cpu_temp — diferente de
        IP/portas, que continuam vedados."""
        import asyncio
        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "qual a temperatura do servidor",
            role="user",
        ))
        assert r.route == "action_intent"
        assert "fastpath:cpu_temp" in (r.llm_used or "")

    def test_user_com_clima_e_llm_alucinando_recebe_retry_seguro(self) -> None:
        """CASO REAL NO AR (28/09): user perguntou a temperatura de cidade,
        o sistema roteou CERTO para o LLM, mas o gemma ALUCINOU a vedação
        ('restrita ao dono'). O pipeline refaz UMA vez e a resposta real
        chega ao user. O reforço do retry NÃO libera infra (fala de user):
        sem 'DONO/ADMIN', reafirma a vedação real do papel."""
        import asyncio

        class LLMAlucinador:
            name = "fake"

            def __init__(self) -> None:
                self.calls = 0
                self.prompts: list[str] = []

            async def generate(self, prompt, timeout=None, **kw):
                self.calls += 1
                self.prompts.append(prompt)
                if self.calls == 1:
                    return (
                        "Informação de infraestrutura (IP, portas, "
                        "topologia de rede) é restrita ao dono do sistema."
                    )
                return "Hoje em Presidente Venceslau SP faz 24°C."

            async def generate_stream(self, prompt, timeout=None, **kw):
                yield await self.generate(prompt, timeout, **kw)

        from tools.actions import build_registry
        from core.security import SecurityManager
        llm = LLMAlucinador()
        orch = Orchestrator(
            providers=[llm],
            config=OrchestratorConfig(default_system_prompt="x"),
        )
        orch.set_action_registry(
            build_registry(security=SecurityManager(mode="strict"))
        )
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian",
            "qual a temperatura em presidente venceslau sp",
            role="user",
        ))
        assert llm.calls == 2  # 1ª alucinou a vedação; 2ª respondeu
        assert r.route == "fallback"  # retry bem-sucedido marca fallback
        assert "24°C" in r.message
        assert "restrita ao dono" not in r.message
        reforco = llm.prompts[1]
        assert "DONO/ADMIN" not in reforco  # reforço NÃO vira dados de dono
        assert "MUNDO EXTERNO" in reforco
        assert "PREJUDICAR O SERVIDOR" in reforco  # vedação reafirmada
