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

import json

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

    def test_temperatura_de_cidade_nao_e_infra_e_clima_real(self) -> None:
        """v1.8.0: clima pega dado REAL, nunca inventado pelo LLM; nunca é
        infra (v1.7.1: 🔒 de cidade era vedação indevida).
        v1.12.0: CIDADE EXPLÍCITA → weather_city (Open-Meteo — o weather.*
        do HA é da região da CASA, não da cidade pedida); sem cidade →
        ha_weather (clima da casa)."""
        from core.intents import detect_action_intent, detect_infra_intent
        for pergunta, esperado in (
            ("qual a temperatuda em presidente venceslau sp",
             ("weather_city", {"city": "presidente venceslau"})),
            ("qual a temperatura em presidente venceslau sp",
             ("weather_city", {"city": "presidente venceslau"})),
            ("como está o clima em são paulo",
             ("weather_city", {"city": "são paulo"})),
            ("como está o clima hoje", ("ha_weather", {})),
            ("qual a temperatura agora", ("ha_weather", {})),
        ):
            assert detect_infra_intent(pergunta) is False, pergunta
            assert detect_action_intent(pergunta) == esperado, pergunta

    def test_tempo_de_duracao_nao_e_clima(self) -> None:
        """'tempo' ambíguo com duração NÃO é clima ('tempo em média',
        'quanto tempo de uptime')."""
        from core.intents import detect_action_intent
        for pergunta in (
            "qual o tempo em média de resposta",
            "quanto tempo em média demora o build",
        ):
            assert detect_action_intent(pergunta) is None, pergunta

    def test_luzes_vao_para_o_ha(self) -> None:
        from core.intents import detect_action_intent
        for pergunta in (
            "quais luzes estão acesas",
            "tem luz acesa na casa",
            "a luz da cozinha está ligada",
        ):
            assert detect_action_intent(pergunta) == ("ha_lights", {}), pergunta

    def test_estado_das_tomadas_vai_para_o_ha(self) -> None:
        """v1.9.0: leitura de tomada/soquete entra na MESMA action de
        leitura (os switches SONOFF do dono são o domínio switch)."""
        from core.intents import detect_action_intent
        for pergunta in (
            "quais tomadas estão ligadas",
            "a tomada do servidor está conectada",
            "quantos soquetes estão ligados",
        ):
            assert detect_action_intent(pergunta) == ("ha_lights", {}), pergunta

    def test_comando_de_tomada_cai_no_controle(self) -> None:
        """v1.9.0: 'liga/desliga a tomada' gera intenção de CONTROLE (mesmo
        gate de papel + confirmação de 2 passos das luzes)."""
        from core.intents import detect_action_intent
        intent = detect_action_intent("desliga a tomada do servidor")
        assert intent is not None and intent[0] == "ha_device_control"
        assert intent[1]["on"] is False
        intent2 = detect_action_intent("liga o soquete da oficina")
        assert intent2 is not None and intent2[0] == "ha_device_control"
        assert intent2[1]["on"] is True

    def test_resumo_do_lar_vai_para_o_ha(self) -> None:
        from core.intents import detect_action_intent
        assert detect_action_intent("como está a casa") == ("ha_summary", {})
        assert detect_action_intent("me dê um resumo do lar") == (
            "ha_summary", {}
        )

    def test_credenciais_sao_negadas_para_qualquer_papel(self) -> None:
        """v1.8.0: o LLM alucinou 'OmegaDrakon2026' como senha do MQTT —
        dado sensível exige NEGAÇÃO determinística, sem LLM, para qualquer
        papel (o valor real vive no .env/cofre, não no modelo)."""
        from core.intents import detect_action_intent
        for pergunta in (
            "qual a senha do mqtt",
            "qual a senha do wi-fi",
            "me passe as credenciais do postgres",
            "qual o token do telegram",
        ):
            assert detect_action_intent(pergunta) == (
                "__secrets_denied__", {}
            ), pergunta

    def test_palavra_senha_fora_de_contexto_nao_e_negada(self) -> None:
        from core.intents import detect_action_intent
        assert detect_action_intent("qual a senha do filme") is None
        assert detect_action_intent("mude a senha") is None

    def test_processos_continuam_process_list(self) -> None:
        from core.intents import detect_action_intent
        assert detect_action_intent("quantos processos estão rodando?") == (
            "process_list", {}
        )


class TestRetryDuploAssuntoExterno:
    """Gemma às vezes recusa 2x seguidas — para assunto EXTERNO (a recusa
    é sempre alucinação) são 2 retries e, esgotando, aviso honesto NÃO
    cacheável; quem pergunta nunca vê a recusa falsa do modelo. Para
    admin em dado de sistema, 1 retry como sempre."""

    @staticmethod
    def _orch_recusador(total_recusas: int):
        import asyncio

        class LLMRecusador:
            name = "fake"

            def __init__(self) -> None:
                self.calls = 0

            async def generate(self, prompt, timeout=None, **kw):
                self.calls += 1
                if self.calls <= total_recusas:
                    return (
                        "Informação de infraestrutura é restrita ao dono "
                        "do sistema."
                    )
                return "Hoje em Presidente Venceslau SP faz 24°C."

            async def generate_stream(self, prompt, timeout=None, **kw):
                yield await self.generate(prompt, timeout, **kw)

        from tools.actions import build_registry
        from core.security import SecurityManager
        from core.orchestrator import Orchestrator, OrchestratorConfig
        llm = LLMRecusador()
        orch = Orchestrator(
            providers=[llm],
            config=OrchestratorConfig(default_system_prompt="x"),
        )
        orch.set_action_registry(
            build_registry(security=SecurityManager(mode="strict"))
        )
        return orch, llm

    def test_recusa_unica_no_retry_segunda_tentativa_responde(self) -> None:
        import asyncio
        orch, llm = self._orch_recusador(total_recusas=1)
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian",
            "qual a temperatura em presidente venceslau sp",
            role="user",
        ))
        assert llm.calls == 2  # original + 1 retry
        assert "24°C" in r.message

    def test_recusa_dupla_segundo_retry_responde(self) -> None:
        import asyncio
        orch, llm = self._orch_recusador(total_recusas=2)
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian",
            "qual a temperatura em presidente venceslau sp",
            role="user",
        ))
        assert llm.calls == 3  # original + 2 retries
        assert "24°C" in r.message

    def test_recusa_tripla_recebe_aviso_honesto_nao_a_recusa(self) -> None:
        import asyncio
        from core.orchestrator import EXTERNAL_UNAVAILABLE_MESSAGE
        orch, llm = self._orch_recusador(total_recusas=99)
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian",
            "qual a temperatura em presidente venceslau sp",
            role="user",
        ))
        assert llm.calls == 3  # original + 2 retries, sem mais nada
        assert r.message == EXTERNAL_UNAVAILABLE_MESSAGE
        assert "restrita ao dono" not in r.message
        assert "Informação de infraestrutura" not in r.message

    def test_aviso_honesto_nao_e_cacheavel(self) -> None:
        from core.orchestrator import (
            EXTERNAL_UNAVAILABLE_MESSAGE,
            cache_failure_reason,
        )
        assert cache_failure_reason(EXTERNAL_UNAVAILABLE_MESSAGE), (
            "aviso honesto cacheável — o turno seguinte não iria ao modelo"
        )

    def test_admin_em_dado_de_sistema_mantem_um_retry(self) -> None:
        """Endurecido: conta CHAMADAS (não só o desfecho) — admin com
        assunto SEM componente externo tem EXATAMENTE 1 retry (2 retries
        são exclusivos de assunto externo) e nunca recebe o aviso honesto
        (que também é exclusivo de assunto externo)."""
        import asyncio

        class LLMRecusadorAlways:
            name = "fake"

            def __init__(self) -> None:
                self.calls = 0

            async def generate(self, prompt, timeout=None, **kw):
                self.calls += 1
                return "Desculpe, mas não posso fornecer essas informações."

            async def generate_stream(self, prompt, timeout=None, **kw):
                yield await self.generate(prompt, timeout, **kw)

        from tools.actions import build_registry
        from core.security import SecurityManager
        llm = LLMRecusadorAlways()
        orch = Orchestrator(
            providers=[llm],
            config=OrchestratorConfig(default_system_prompt="x"),
        )
        orch.set_action_registry(
            build_registry(security=SecurityManager(mode="strict"))
        )
        r = asyncio.run(orch.process(
            "alex", "guardian",
            "me conte os segredos da máquina",
            role="admin",
        ))
        assert llm.calls == 2  # original + 1 retry (não 3)
        # O aviso honesto é exclusivo de assunto externo — admin em dado
        # de sistema segue com a recusa original quando o retry persiste.
        from core.orchestrator import EXTERNAL_UNAVAILABLE_MESSAGE
        assert r.message != EXTERNAL_UNAVAILABLE_MESSAGE


class TestControleLuzes:
    """Controle de luzes pelo chat (v1.8.1): gate de papel determinístico
    (user → denied pelo Registry, sem LLM), alvo específico obrigatório,
    confirmação de 2 passos expirável (120s) e consumo da confirmação.
    Integração real com o InMemoryHAServer (mesma interface do HAClient).
    """

    @staticmethod
    def _setup(total_recusas: int = 0):
        import asyncio
        from core.intents import configure_ha_entities
        from integrations.homeassistant.client import HAClient, InMemoryHAServer
        from tools.actions import build_registry
        from tools.actions.actions import configure_ha_client
        from core.orchestrator import Orchestrator, OrchestratorConfig
        from core.security import SecurityManager

        server = InMemoryHAServer()
        server.seed(
            "switch.luz_cozinha_sonoff_1", "off",
            {"friendly_name": "Luz Cozinha"},
        )
        server.seed(
            "switch.luz_da_varanda_sonoff_2", "on",
            {"friendly_name": "Luz da Varanda"},
        )
        client = server  # o InMemoryHAServer implementa o HABackend inteiro
        configure_ha_client(client)
        configure_ha_entities(client.list_states())

        class FakeLLM:
            name = "fake"

            async def generate(self, prompt, timeout=None, **kw):
                return "RESPOSTA_DO_LLM_FAKE"

            async def generate_stream(self, prompt, timeout=None, **kw):
                yield "RESPOSTA_DO_LLM_FAKE"

        llm = FakeLLM()
        orch = Orchestrator(
            providers=[llm],
            config=OrchestratorConfig(default_system_prompt="x"),
        )
        orch.set_action_registry(
            build_registry(security=SecurityManager(mode="strict"))
        )
        return orch, llm, server, client

    def test_user_nao_controla_luz_denied_sem_llm(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "liga a luz da cozinha",
            role="user",
        ))
        assert r.route == "action_intent"
        assert "não pode" in r.message.lower()
        assert "só o dono" in r.message.lower()
        assert r.message != "RESPOSTA_DO_LLM_FAKE"  # zero LLM
        assert server.service_calls == []  # nada executado

    def test_admin_fluxo_completo_pedir_confirmar_executar(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r1 = asyncio.run(orch.process(
            "alex", "guardian", "liga a luz da cozinha", role="admin",
        ))
        assert "Confirmar" in r1.message and "sim" in r1.message.lower()
        assert server.service_calls == []  # 1º passo NÃO executa
        r2 = asyncio.run(orch.process(
            "alex", "guardian", "sim", role="admin",
        ))
        assert r2.route == "action_intent"
        assert "executado" in r2.message
        assert len(server.service_calls) == 1
        assert server.service_calls[0]["service"] == "turn_on"
        assert server.service_calls[0]["entity_id"] == "switch.luz_cozinha_sonoff_1"

    def test_comando_sem_alvo_pede_qual_luz(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r = asyncio.run(orch.process(
            "alex", "guardian", "liga as luzes", role="admin",
        ))
        assert "Qual luz" in r.message
        assert server.service_calls == []

    def test_entidade_inexistente_recebe_erro_amigavel(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r = asyncio.run(orch.process(
            "alex", "guardian", "liga a luz do quartinho", role="admin",
        ))
        assert "não existe no Home Assistant" in r.message
        assert server.service_calls == []

    def test_confirmacao_expira(self) -> None:
        import asyncio
        from tools.actions.actions import _LIGHT_CONFIRMATIONS
        orch, llm, server, client = self._setup()
        asyncio.run(orch.process(
            "alex", "guardian", "liga a luz da cozinha", role="admin",
        ))
        key = ("alex", "switch.luz_cozinha_sonoff_1", True)
        assert key in _LIGHT_CONFIRMATIONS
        # Envelhece a confirmação por 121s FIXOS (TTL do contrato: 120s) —
        # NÃO usa a constante: a mutação do TTL tem que ser pega pelo teste.
        _LIGHT_CONFIRMATIONS[key] = (_LIGHT_CONFIRMATIONS[key][0] - 121.0, "")
        r2 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        # O 'sim' recria a intenção (confirmação expirada) — NÃO executa.
        assert server.service_calls == []

    def test_confirmacao_e_consumida_um_uso(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        asyncio.run(orch.process("alex", "guardian", "liga a luz da cozinha", role="admin"))
        asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert len(server.service_calls) == 1
        # Repetir o 'sim' SEM intenção pendente: é só conversa — cai no
        # LLM (a confirmação não é reutilizável e nada executa).
        r3 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert len(server.service_calls) == 1
        assert r3.message == "RESPOSTA_DO_LLM_FAKE"

    def test_ws_tambem_injeta_user_id_e_executa(self) -> None:
        """O MESMO fluxo (pedir → confirmar → executar) no process_stream
        (WS): user_id injetado nos params e confirmação consumida — mutação
        no ramo do stream tem que ser pega por este teste."""
        import asyncio

        async def _run() -> tuple[object, object, list[dict]]:
            orch, llm, server, client = self._setup()
            chunks1 = [c async for c in orch.process_stream(
                "alex", "guardian", "liga a luz da cozinha", role="admin",
            )]
            chunks2 = [c async for c in orch.process_stream(
                "alex", "guardian", "sim", role="admin",
            )]
            return chunks1, chunks2, server.service_calls

        chunks1, chunks2, calls = asyncio.run(_run())
        done1 = [c for c in chunks1 if c.get("type") == "done"]
        assert done1 and "Confirmar" in done1[0]["content"]
        done2 = [c for c in chunks2 if c.get("type") == "done"]
        assert done2 and "executado" in done2[0]["content"]
        assert len(calls) == 1 and calls[0]["service"] == "turn_on"

    def test_sim_solto_sem_intencao_nao_executa_nada(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert server.service_calls == []
        # Sem intenção pendente, o 'sim' é só conversa — cai no LLM normal.
        assert r.message == "RESPOSTA_DO_LLM_FAKE"


class TestControleTomadas:
    """v1.9.0: o MESMO padrão de confirmação de 2 passos e gate de papel
    das luzes estendido a tomadas/soquetes (switch.* com nome de tomada).
    Caso real do dono: 'note servidor Socket 1' — a tomada que alimenta o
    servidor NÃO pode cair num desligar ambíguo nem num lote.
    """

    @staticmethod
    def _setup():
        # Mesma infra do TestControleLuzes + tomadas reais da casa.
        base = TestControleLuzes._setup()
        orch, llm, server, client = base
        server.seed(
            "switch.note_servidor_socket_1", "on",
            {"friendly_name": "note servidor Socket 1"},
        )
        server.seed(
            "switch.luz_oficina_socket_1", "off",
            {"friendly_name": "Luz Oficina Socket 1"},
        )
        from core.intents import configure_ha_entities
        configure_ha_entities(server.list_states())
        return orch, llm, server, client

    def test_tomada_fluxo_completo_pedir_confirmar_executar(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r1 = asyncio.run(orch.process(
            "alex", "guardian", "desliga a tomada do servidor", role="admin",
        ))
        # 1º passo: pedido de confirmação com o nome REAL da tomada — nada
        # executa ainda.
        assert "Confirmar" in r1.message
        assert "note servidor Socket 1" in r1.message
        assert "desligar" in r1.message.lower()
        assert server.service_calls == []
        r2 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert "executado" in r2.message
        assert len(server.service_calls) == 1
        assert server.service_calls[0]["service"] == "turn_off"
        assert server.service_calls[0]["entity_id"] == "switch.note_servidor_socket_1"

    def test_tomada_ligar_com_apelido_socket(self) -> None:
        """A fala usa 'socket'/'soquete' — resolução casa com a entidade
        cujo nome contém Socket."""
        import asyncio
        orch, llm, server, client = self._setup()
        r1 = asyncio.run(orch.process(
            "alex", "guardian", "liga o soquete da oficina", role="admin",
        ))
        assert "Confirmar" in r1.message
        assert "Luz Oficina Socket 1" in r1.message
        r2 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert "executado" in r2.message
        assert server.service_calls[0]["entity_id"] == "switch.luz_oficina_socket_1"
        assert server.service_calls[0]["service"] == "turn_on"

    def test_user_nao_controla_tomada(self) -> None:
        """O gate de papel vale para tomadas: user → negação determinística
        (a tomada do servidor é infraestrutura crítica)."""
        import asyncio
        orch, llm, server, client = self._setup()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "desliga a tomada do servidor",
            role="user",
        ))
        assert r.route == "action_intent"
        assert "só o dono" in r.message.lower()
        assert server.service_calls == []

    def test_tomada_inexistente_erro_amigavel(self) -> None:
        import asyncio
        orch, llm, server, client = self._setup()
        r = asyncio.run(orch.process(
            "alex", "guardian", "liga a tomada da garagem", role="admin",
        ))
        assert "não existe no Home Assistant" in r.message
        assert server.service_calls == []


class TestCoerenciaDoLar:
    """v1.9.1 — casos REAIS do dono (conversas de 29/09): o chat do lar
    nunca pode responder com dispositivo diferente do pedido nem inventar
    entidade a partir do próprio comando.

    BUG-A (09:36): pendente 'liga a luz do corredor' → 'sim' executou a
    'Luz da Varanda' (intenção velha de outro turno).
    BUG-B (09:41): 'luzes acessas' (pergunta/comando sem alvo) → 'Confirmar:
    ligar Luzes Acessas' (entidade inventada a partir do comando).
    """

    def test_estado_de_luzes_nunca_vira_confirmacao(self) -> None:
        """BUG-B: 'luzes acessas' tem que cair na LEITURA (ha_lights) —
        nunca gerar 'Confirmar: ligar Luzes Acessas'."""
        from core.intents import detect_action_intent
        for frase in (
            "luzes acessas",
            "luzes acesas",
            "quais as luzes acessas",
            "as luzes estão acesas",
        ):
            intent = detect_action_intent(frase)
            assert intent is not None, frase
            assert intent[0] == "ha_lights", (frase, intent)

    def test_comando_plural_sem_alvo_responde_generico(self) -> None:
        """'liga as luzes' (comando, sem alvo): resposta genérica honesta —
        NUNCA entidade inventada, NUNCA execução."""
        import asyncio
        orch, llm, server, client = TestControleLuzes._setup()
        r = asyncio.run(orch.process(
            "alex", "guardian", "liga as luzes", role="admin",
        ))
        # A resposta TEM que ser o pedido genérico de alvo — nunca
        # confirmação de entidade inventada nem erro de entidade inexistente
        # (o comando em plural não nomeia nada).
        assert "várias" in r.message.lower() or "qual luz" in r.message.lower()
        assert "Confirmar" not in r.message
        assert "não existe" not in r.message
        assert server.service_calls == []
        # Variação real do dono (09:41): 'luzes acessas' SEM verbo de
        # comando tem que ir para a LEITURA — nunca para o controle.
        from core.intents import detect_action_intent
        assert detect_action_intent("luzes acessas") == ("ha_lights", {})

    def test_estado_de_luzes_nunca_vira_confirmacao_e_plural_vai_ao_generico(self) -> None:
        """Endurecimento do M2: com o caminho do plural REMOVIDO, 'liga as
        luzes' precisa continuar com resposta determinística de alvo — e
        NUNCA virar entidade inventada nem LLM. Variação crítica: plural com
        lugar ('liga as luzes da sala') NÃO responde 'não existe' — é
        pedido plural, resposta genérica."""
        import asyncio
        from core.intents import detect_action_intent
        assert detect_action_intent("luzes acessas") == ("ha_lights", {})
        orch, llm, server, client = TestControleLuzes._setup()
        for frase in ("liga as luzes", "liga as luzes da sala"):
            r = asyncio.run(orch.process(
                "alex", "guardian", frase, role="admin",
            ))
            assert r.route == "action_intent", frase  # determinístico
            assert "várias" in r.message.lower() or "qual luz" in r.message.lower(), (
                frase, r.message,
            )
            assert "não existe" not in r.message.lower(), (frase, r.message)

    def test_sim_apos_pedido_executa_o_alvo_certo(self) -> None:
        """Fluxo normal preservado: 'liga a luz do corredor' + 'sim'
        executa o CORREDOR (não outra luz de turno anterior)."""
        import asyncio
        orch, llm, server, client = self._setup_com_corredor()
        asyncio.run(orch.process(
            "alex", "guardian", "liga a luz da cozinha", role="admin",
        ))
        asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        # Novo pedido + confirmação: executa o alvo do novo pedido.
        r1 = asyncio.run(orch.process(
            "alex", "guardian", "liga a luz do corredor", role="admin",
        ))
        assert "Corredor" in r1.message
        r2 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert "Corredor" in r2.message, r2.message
        assert "Varanda" not in r2.message
        ultima = server.service_calls[-1]
        assert ultima["entity_id"] == "switch.luz_corredor_sonoff_1"

    def test_sim_com_outro_dispositivo_nao_executa(self) -> None:
        """v1.9.1: 'sim, da sala' quando a pendente é a do corredor →
        recusa genérica honesta, sem LLM, sem executar NADA; a intenção
        velha é descartada (o próximo 'sim' puro não executa nada)."""
        import asyncio
        orch, llm, server, client = self._setup_com_corredor()
        r1 = asyncio.run(orch.process(
            "alex", "guardian", "liga a luz do corredor", role="admin",
        ))
        assert "Confirmar" in r1.message
        r2 = asyncio.run(orch.process(
            "alex", "guardian", "sim, da sala", role="admin",
        ))
        assert server.service_calls == []  # NADA executado
        assert r2.route == "action_intent"  # resposta determinística
        assert "não bate" in r2.message or "diga de novo" in r2.message.lower()
        assert r2.message != "RESPOSTA_DO_LLM_FAKE"  # zero LLM
        # Intenção velha descartada: 'sim' puro não executa nada agora.
        r3 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert server.service_calls == []
        assert r3.message == "RESPOSTA_DO_LLM_FAKE"

    @staticmethod
    def _setup_com_corredor():
        """Seed do TestControleLuzes + a Luz Corredor (a vítima do bug real
        de 09:36 — o dono pediu o corredor e o sistema executou a varanda)."""
        base = TestControleLuzes._setup()
        orch, llm, server, client = base
        server.seed(
            "switch.luz_corredor_sonoff_1", "off",
            {"friendly_name": "Luz Corredor"},
        )
        from core.intents import configure_ha_entities
        configure_ha_entities(server.list_states())
        return orch, llm, server, client

    def test_confirmacao_e_execucao_nao_vao_ao_cache(self) -> None:
        """v1.9.1: 'Confirmar:…' e '✅ … executado' são ESTADO DE CONVERSA —
        cacheados, viravam incoerência eterna ('luzes acesas' respondendo
        'Confirmar: ligar Luzes Acessas' — caso real de 09:41)."""
        from core.orchestrator import _cacheable
        assert not _cacheable(
            "💡 Confirmar: ligar 'Luz da Varanda' (agora: off)?\n"
            "Responda **sim** para executar — a confirmação vale por 2 minutos."
        )
        assert not _cacheable(
            "✅ Luz da Varanda: desligar executado (⚪ estado agora: off)."
        )
        # Leitura do lar continua cacheável (dado real, resposta estável).
        assert _cacheable(
            "💡 0 acesa(s) de 6 no Home Assistant: nenhuma acesa."
        )
        assert _cacheable(
            "🌤️ Clima na região da casa: 31.7°C, parcialmente nublado"
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


class TestCacheBansV115:
    """v1.15.0 (§15 de 30/09): auditoria das 39 entradas do cache expôs
    3 cegas no cache_failure_reason — as 4 entradas podadas à mão não
    deviam ter NASCIDO no cache:
    1. etiqueta [INFO]/[WARN]/… NO MEIO da resposta (o ban só-prefixo
       deixou passar a resposta de limpeza com '[INFO] …' embutido);
    2. frase SECA de execução do lar ('Acesse a luz do corredor!' — o
       ban da v1.9.1 só pegava '💡 Confirmar:'/'✅ ' com emoji);
    3. recusa falsa de 'código proprietário' (llama.cpp é open-source
       E do próprio dono — vedação alucinada de prompt interno);
    4. bônus: placeholder do sistema como resposta ('Em construção…').
    """

    @pytest.mark.parametrize("resposta", [
        # [14] real do cache — etiqueta NO MEIO:
        "Estou pronto para começar a limpeza. Por favor, me dê os "
        "detalhes do que você gostaria de ser limpo ou apagado.\n\n"
        "[INFO] Limpeza solicitada no dia 30/09.",
        # variante com [WARN]:
        "Feito! [WARN] cache parcial descartado durante a operação.",
        # variante [CRIT] minúscula no fim:
        "Serviço reiniciado com sucesso. [crit] fallback acionado antes.",
    ])
    def test_etiqueta_no_meio_nao_e_cacheavel(self, resposta: str) -> None:
        from core.orchestrator import cache_failure_reason
        motivo = cache_failure_reason(resposta)
        assert motivo, f"etiqueta embutida cacheável: {resposta!r}"
        assert "etiqueta" in motivo

    @pytest.mark.parametrize("resposta", [
        "Acesse a luz do corredor!",           # [29] real do cache
        "Ligue a tomada do servidor",           # imperativo sem emoji
        "Desligue tudo",                        # plural sem alvo
        "  acenda a luz da sala",               # espaço inicial
    ])
    def test_lar_seco_nao_e_cacheavel(self, resposta: str) -> None:
        from core.orchestrator import cache_failure_reason
        motivo = cache_failure_reason(resposta)
        assert motivo, f"execução seca do lar cacheável: {resposta!r}"
        assert "lar" in motivo

    @pytest.mark.parametrize("resposta", [
        # [36] real do cache — llama.cpp é open-source E do dono:
        "Não posso compartilhar detalhes específicos sobre configurações "
        "do llama.cpp ou qualquer outro código proprietário sem "
        "autorização expressa.",
        "Isso é código proprietário e não posso revelar.",
    ])
    def test_recusa_codigo_proprietario_nao_e_cacheavel(
        self, resposta: str,
    ) -> None:
        from core.orchestrator import cache_failure_reason
        motivo = cache_failure_reason(resposta)
        assert motivo, f"recusa de 'código proprietário' cacheável: {resposta!r}"
        assert "recusa" in motivo

    @pytest.mark.parametrize("resposta", [
        '"Em construção..."',   # [18] real do cache
        "Em construção…",       # reticência unicode
    ])
    def test_estado_de_pagina_nao_e_cacheavel(self, resposta: str) -> None:
        from core.orchestrator import cache_failure_reason
        motivo = cache_failure_reason(resposta)
        assert motivo, f"placeholder cacheável: {resposta!r}"
        assert "Em construção" in motivo

    def test_textos_legitimos_continuam_cacheaveis(self) -> None:
        """Nada de falso positivo: 'em construção' no MEIO é conteúdo
        (obra, projeto), e a leitura do lar com 💡 segue cacheável."""
        from core.orchestrator import cache_failure_reason
        for resposta in (
            "Estamos construindo a futura sede — obra em construção avança.",
            "O projeto segue em construção com prazo de março.",
            "💡 0 acesa(s) de 6 no Home Assistant: nenhuma acesa.",
            "Bom dia! Como posso ajudar você hoje?",
            "A capital do Brasil é Brasília.",
        ):
            assert cache_failure_reason(resposta) == "", (
                f"resposta legítima banida: {resposta!r}"
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

    def test_temperatura_do_servidor_para_user_vai_via_cpu_temp(
        self, monkeypatch, tmp_path
    ) -> None:
        """A temperatura DA MÁQUINA é dado de leitura (não prejudica o
        sistema): permitida para user via cpu_temp — diferente de
        IP/portas, que continuam vedados.

        O sysfs vem de fixture: o contrato vale em QUALQUER host (o runner
        do CI não tem zones térmicos — antes deste pino o teste só passava
        no servidor)."""
        import asyncio

        thermal = tmp_path / "sys" / "thermal"
        zone = thermal / "thermal_zone0"
        zone.mkdir(parents=True)
        (zone / "temp").write_text("53000\n", encoding="utf-8")
        (zone / "type").write_text("x86_pkg_temp", encoding="utf-8")
        monkeypatch.setattr("tools.actions.actions.THERMAL_DIR", str(thermal))

        orch, _ = self._orch()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "qual a temperatura do servidor",
            role="user",
        ))
        assert r.route == "action_intent"
        assert "fastpath:cpu_temp" in (r.llm_used or "")
        assert "53.0" in r.message  # dado REAL do sensor, zero LLM

    def test_cpu_temp_sem_sensor_degrada_sem_inventar(
        self, monkeypatch, tmp_path
    ) -> None:
        """Sem nenhum sensor legível → ok=False honesto com erro claro —
        o pipeline degrada em vez de inventar temperatura."""
        from tools.actions.actions import cpu_temp

        vazio = tmp_path / "sys" / "thermal"
        vazio.mkdir(parents=True)
        monkeypatch.setattr("tools.actions.actions.THERMAL_DIR", str(vazio))
        monkeypatch.setattr(
            "tools.actions.actions.HWMON_DIR", str(tmp_path / "sys" / "hwmon")
        )

        res = cpu_temp()
        assert res["ok"] is False
        assert "sensor" in res.get("error", "")

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


# ---------------------------------------------------------------------------
# Escrita Google no chat (lote 2, 2026-10-03) — gate de papel + confirmação
# ---------------------------------------------------------------------------

class _GoogleFakeTransport:
    """Transporte fake do GoogleClient para os testes de escrita."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, method, url, *, headers=None, data=None, timeout=30.0):
        self.calls.append({"method": method, "url": url, "data": data})
        if method == "GET" and "/files" in url:
            return 200, json.dumps({"files": [{
                "id": "f1", "name": "notas", "mimeType": "text/plain",
                "modifiedTime": "2026-10-01T00:00:00Z",
            }]}).encode()
        if method == "GET":
            return 200, b'{"messages": [], "items": [], "labels": []}'
        return 200, b'{"id": "f1", "name": "notas"}'


class TestEscritaGoogleNoChat:
    """O MESMO contrato do ha_device_control para o Drive/Agenda/Gmail:
    user → negação determinística (zero LLM, zero escrita); admin → 1ª
    menção pede 'sim' (nada executa) e o 'sim' executa; incoerência e TTL
    descartam a intenção."""

    @staticmethod
    def _setup():
        import time as _time

        from core.intents import configure_ha_entities
        from integrations.google import GoogleClient, GoogleCredentials, GoogleToken
        from tools.actions import build_registry
        from tools.actions.actions import (
            _WRITE_CONFIRMATIONS,
            configure_google_client,
        )
        from core.orchestrator import Orchestrator, OrchestratorConfig
        from core.security import SecurityManager

        _WRITE_CONFIRMATIONS.clear()
        transport = _GoogleFakeTransport()
        client = GoogleClient(
            GoogleCredentials(client_id="cid", client_secret="sec"),
            GoogleToken(access_token="at", refresh_token="rt",
                        expires_at=_time.time() + 3600),
            transport=transport,
        )
        configure_google_client(client)
        configure_ha_entities([])

        class FakeLLM:
            name = "fake"

            async def generate(self, prompt, timeout=None, **kw):
                return "RESPOSTA_DO_LLM_FAKE"

            async def generate_stream(self, prompt, timeout=None, **kw):
                yield "RESPOSTA_DO_LLM_FAKE"

        orch = Orchestrator(
            providers=[FakeLLM()],
            config=OrchestratorConfig(default_system_prompt="x"),
        )
        orch.set_action_registry(
            build_registry(security=SecurityManager(mode="strict"))
        )
        return orch, transport, _WRITE_CONFIRMATIONS

    @staticmethod
    def _writes(transport) -> list[dict[str, object]]:
        return [
            c for c in transport.calls
            if c["method"] in ("POST", "PUT", "DELETE")
        ]

    def test_user_e_negado_sem_llm_e_sem_escrita(self) -> None:
        import asyncio
        orch, transport, store = self._setup()
        r = asyncio.run(orch.process(
            "usuario-teste", "guardian", "apague o arquivo notas do drive",
            role="user",
        ))
        assert r.route == "action_intent"
        assert r.message != "RESPOSTA_DO_LLM_FAKE"  # zero LLM
        assert "dono" in r.message.lower()
        assert self._writes(transport) == []  # nada gravado
        assert store == {}  # nem confirmação registrada

    def test_admin_fluxo_completo_dois_passos(self) -> None:
        import asyncio
        orch, transport, store = self._setup()
        r1 = asyncio.run(orch.process(
            "alex", "guardian", "apague o arquivo notas do drive", role="admin",
        ))
        assert "Confirmar" in r1.message and "sim" in r1.message.lower()
        assert "notas" in r1.message
        assert self._writes(transport) == []  # 1º passo NÃO escreve
        assert store  # intenção pendente registrada

        r2 = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert r2.route == "action_intent"
        assert r2.message != "RESPOSTA_DO_LLM_FAKE"
        writes = self._writes(transport)
        assert len(writes) == 1 and writes[0]["method"] == "DELETE"
        assert "f1" in str(writes[0]["url"])

    def test_user_no_sim_tambem_e_negado(self) -> None:
        """O 'sim' de quem não é dono NÃO contorna o gate: a execução
        passa pelo Registry com o papel de quem falou."""
        import asyncio
        orch, transport, store = self._setup()
        asyncio.run(orch.process(
            "alex", "guardian", "apague o arquivo notas do drive", role="admin",
        ))
        assert store  # intenção pendente do 'alex'
        r = asyncio.run(orch.process(
            "alex", "guardian", "sim", role="user",
        ))
        assert self._writes(transport) == []
        assert "dono" in r.message.lower()
        assert r.message != "RESPOSTA_DO_LLM_FAKE"

    def test_incoerencia_descarta_a_intencao(self) -> None:
        """'sim' que menciona LUGAR fora do alvo pendente não executa —
        a intenção velha é descartada (espelho v1.9.1)."""
        import asyncio
        orch, transport, store = self._setup()
        asyncio.run(orch.process(
            "alex", "guardian", "apague o arquivo notas do drive", role="admin",
        ))
        r = asyncio.run(orch.process(
            "alex", "guardian", "sim, da cozinha", role="admin",
        ))
        assert self._writes(transport) == []
        assert store == {}  # descartada
        assert "não bate" in r.message or "não" in r.message.lower()

    def test_ttl_da_confirmacao_expira(self) -> None:
        import asyncio
        orch, transport, store = self._setup()
        asyncio.run(orch.process(
            "alex", "guardian", "apague o arquivo notas do drive", role="admin",
        ))
        assert store
        key = next(iter(store))
        stamp, alvo, params = store[key]
        # 121s FIXOS (TTL do contrato é 120s — mutação pega pelo teste)
        store[key] = (stamp - 121.0, alvo, params)
        asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        # expirado → o 'sim' NÃO executa a intenção velha
        assert self._writes(transport) == []

    def test_ws_stream_tambem_confirma_e_executa(self) -> None:
        import asyncio

        async def _run():
            orch, transport, store = self._setup()
            chunks1 = [c async for c in orch.process_stream(
                "alex", "guardian", "apague o arquivo notas do drive",
                role="admin",
            )]
            chunks2 = [c async for c in orch.process_stream(
                "alex", "guardian", "sim", role="admin",
            )]
            return chunks1, chunks2, transport

        chunks1, chunks2, transport = asyncio.run(_run())
        done1 = [c for c in chunks1 if c.get("type") == "done"]
        assert done1 and "Confirmar" in done1[0]["content"]
        done2 = [c for c in chunks2 if c.get("type") == "done"]
        assert done2 and done2[0]["content"] != "RESPOSTA_DO_LLM_FAKE"
        assert self._writes(transport) and \
            self._writes(transport)[0]["method"] == "DELETE"

    def test_ws_user_negado_sem_llm(self) -> None:
        import asyncio

        async def _run():
            orch, transport, store = self._setup()
            chunks = [c async for c in _stream(orch, "usuario-teste", "user")]
            return chunks, transport

        chunks, transport = asyncio.run(_run())
        done = [c for c in chunks if c.get("type") == "done"]
        assert done and "dono" in done[0]["content"].lower()
        assert done[0]["content"] != "RESPOSTA_DO_LLM_FAKE"
        assert self._writes(transport) == []

    def test_sim_solto_sem_intencao_vai_para_o_llm(self) -> None:
        import asyncio
        orch, transport, store = self._setup()
        r = asyncio.run(orch.process("alex", "guardian", "sim", role="admin"))
        assert r.message == "RESPOSTA_DO_LLM_FAKE"
        assert self._writes(transport) == []


async def _stream(orch, user_id: str, role: str):
    """Atalho: 'apague o arquivo notas do drive' no caminho WS."""
    async for chunk in orch.process_stream(
        user_id, "guardian", "apague o arquivo notas do drive", role=role
    ):
        yield chunk
