#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_memory_layer.py
Descrição: Memória longa (F4 fase 1) — extração determinística, grafo temporal
           em SQLite (substituição sem apagar), escopo por usuário, busca e as
           actions `salvar_fato`/`buscar_memoria` do catálogo.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F4 e core/memory_layer.py
  - tools/actions/actions.py (CATALOG) e core/security/permissions.py
"""

from __future__ import annotations

import pytest

from core.memory_layer import (
    MAX_FATOS_POR_USUARIO,
    REL_SUBSTITUI,
    MemoryGraph,
    MemoryLayerError,
    extrair_fatos,
    normalizar,
    obter_memoria,
    resetar_memoria,
    slug,
)
from tools.actions import actions


@pytest.fixture()
def grafo(tmp_path):
    g = MemoryGraph(tmp_path / "mem.db")
    yield g
    g.fechar()


class TestExtracao:
    @pytest.mark.parametrize(
        "texto,entidade,trecho",
        [
            ("meu nome é Alex", "nome", "nome é alex"),
            ("me chamo Alex Projeti", "nome", "nome é alex projeti"),
            ("moro em Curitiba", "cidade", "mora em curitiba"),
            ("minha cidade é Recife", "cidade", "mora em recife"),
            ("trabalho com suporte técnico", "trabalho", "trabalha com suporte tecnico"),
            ("prefiro respostas curtas", "preferencia", "prefere respostas curtas"),
            ("gosto de café forte", "gosto", "gosta de cafe forte"),
            ("não gosto de barulho", "nao_gosto", "não gosta de barulho"),
            ("meu e-mail é alex@exemplo.com", "email", "e-mail é alex@exemplo.com"),
        ],
    )
    def test_padroes_reconhecem(self, texto, entidade, trecho):
        fatos = extrair_fatos(texto)
        assert any(f["entidade"] == entidade and trecho in f["conteudo"] for f in fatos)

    def test_lembre_que_usa_primeira_palavra_como_entidade(self):
        fatos = extrair_fatos("lembre que o aluguel vence dia 10")
        assert fatos and fatos[0]["entidade"] == "aluguel"

    def test_posse_concreta_e_guardada(self):
        fatos = extrair_fatos("tenho um cachorro chamado Rex")
        assert any(f["entidade"] == "possui" for f in fatos)

    def test_posse_abstrata_e_ignorada(self):
        assert extrair_fatos("tenho uma dúvida sobre isso") == []

    def test_texto_sem_fato_nao_inventa(self):
        assert extrair_fatos("qual é a previsão do tempo?") == []

    def test_texto_vazio_ou_invalido(self):
        assert extrair_fatos("") == []
        assert extrair_fatos(None) == []  # type: ignore[arg-type]

    def test_normalizar_e_slug(self):
        assert normalizar("  São   PAULO ") == "sao paulo"
        assert slug("São Paulo") == "sao_paulo"


class TestGrafo:
    def test_grava_e_devolve_no(self, grafo):
        node = grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        assert node.id and node.user_id == "alex"
        assert [n.conteudo for n in grafo.ativos("alex")] == ["cidade é Curitiba"]

    def test_mesmo_fato_nao_duplica(self, grafo):
        a = grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        b = grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        assert a.id == b.id
        assert len(grafo.ativos("alex")) == 1

    def test_fato_novo_substitui_sem_apagar(self, grafo):
        velho = grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        novo = grafo.adicionar_fato("alex", "cidade é Recife", entidade="cidade")

        ativos = grafo.ativos("alex")
        assert [n.conteudo for n in ativos] == ["cidade é Recife"]
        assert velho.id not in [n.id for n in ativos]

        # histórico continua auditável, com aresta temporal
        historico = grafo.historico("alex", "cidade")
        assert {n.conteudo for n in historico} == {"cidade é Curitiba", "cidade é Recife"}
        arestas = grafo.vizinhos(novo.id, relacao=REL_SUBSTITUI)
        assert [e.target for e in arestas] == [velho.id]

    def test_substituicao_so_na_mesma_entidade(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        grafo.adicionar_fato("alex", "trabalho com suporte", entidade="trabalho")
        assert len(grafo.ativos("alex")) == 2

    def test_entidade_e_criada_uma_vez(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        stats = grafo.stats("alex")
        assert stats["entidades"] == 1
        assert stats["fatos"] == 1

    def test_isolamento_entre_usuarios(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        assert grafo.ativos("maria") == []
        assert grafo.buscar("maria", "cidade") == []
        assert grafo.stats("maria")["fatos"] == 0

    def test_mesma_entidade_em_usuarios_diferentes_nao_colide(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        grafo.adicionar_fato("maria", "cidade é Recife", entidade="cidade")
        assert [n.conteudo for n in grafo.ativos("alex")] == ["cidade é Curitiba"]
        assert [n.conteudo for n in grafo.ativos("maria")] == ["cidade é Recife"]

    def test_exige_user_id(self, grafo):
        with pytest.raises(MemoryLayerError):
            grafo.adicionar_fato("", "cidade é Curitiba", entidade="cidade")

    def test_fato_vazio_e_rejeitado(self, grafo):
        with pytest.raises(MemoryLayerError):
            grafo.adicionar_fato("alex", "   ", entidade="cidade")

    def test_salvar_extrai_e_grava(self, grafo):
        salvos = grafo.salvar("meu nome é Alex e moro em Curitiba", user_id="alex")
        assert {n.entidade for n in salvos} == {"nome", "cidade"}
        assert len(grafo.ativos("alex")) == 2

    def test_salvar_sem_fato_nao_grava(self, grafo):
        assert grafo.salvar("bom dia, tudo bem?", user_id="alex") == []
        assert grafo.ativos("alex") == []

    def test_persistencia_em_disco(self, tmp_path):
        caminho = tmp_path / "mem.db"
        g1 = MemoryGraph(caminho)
        g1.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        g1.fechar()

        g2 = MemoryGraph(caminho)
        try:
            assert [n.conteudo for n in g2.ativos("alex")] == ["cidade é Curitiba"]
        finally:
            g2.fechar()

    def test_arquivo_corrompido_falha_alto(self, tmp_path):
        ruim = tmp_path / "mem.db"
        ruim.write_bytes(b"isto nao e um sqlite")
        with pytest.raises(MemoryLayerError):
            MemoryGraph(ruim)

    def test_stats(self, grafo):
        grafo.salvar("meu nome é Alex e moro em Curitiba", user_id="alex")
        stats = grafo.stats()
        assert stats["fatos"] == 2 and stats["usuarios"] == 1
        assert stats["entidades"] == 2 and stats["substituidos"] == 0


class TestBusca:
    def test_busca_por_entidade(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        grafo.adicionar_fato("alex", "trabalho com suporte", entidade="trabalho")
        achados = grafo.buscar("alex", "onde eu moro? cidade")
        assert achados and achados[0].entidade == "cidade"

    def test_busca_sem_termo_devolve_recentes(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        grafo.adicionar_fato("alex", "trabalho com suporte", entidade="trabalho")
        assert len(grafo.buscar("alex", "")) == 2

    def test_busca_sem_correspondencia_devolve_vazio(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        assert grafo.buscar("alex", "futebol") == []

    def test_busca_respeita_limite(self, grafo):
        # entidades distintas: mesma entidade + conteúdo novo = substituição
        for i in range(5):
            grafo.adicionar_fato("alex", f"gosto de item {i}", entidade=f"assunto{i}")
        assert len(grafo.buscar("alex", "item", limite=2)) == 2

    def test_busca_nao_devolve_fato_substituido(self, grafo):
        grafo.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
        grafo.adicionar_fato("alex", "cidade é Recife", entidade="cidade")
        assert [n.conteudo for n in grafo.buscar("alex", "cidade")] == ["cidade é Recife"]

    def test_teto_de_fatos_por_usuario(self, grafo, monkeypatch):
        import core.memory_layer as ml

        monkeypatch.setattr(ml, "MAX_FATOS_POR_USUARIO", 3)
        for i in range(6):
            grafo.adicionar_fato("alex", f"gosto de item {i}", entidade=f"assunto{i}")
        assert len(grafo.ativos("alex")) == 3
        assert grafo.stats("alex")["substituidos"] == 3
        assert MAX_FATOS_POR_USUARIO >= 3


class TestActions:
    @pytest.fixture()
    def memoria_isolada(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_PATH", str(tmp_path / "mem.db"))
        resetar_memoria()
        yield
        resetar_memoria()

    def test_salvar_e_buscar_pelo_catalogo(self, memoria_isolada):
        salvou = actions.salvar_fato("meu nome é Alex e moro em Curitiba", user_id="alex")
        assert salvou["ok"] is True and salvou["count"] == 2

        achou = actions.buscar_memoria("onde eu moro", user_id="alex")
        assert achou["ok"] is True
        assert achou["count"] >= 1
        assert "curitiba" in achou["memorias"][0]["conteudo"]

    def test_buscar_sem_memoria_nao_quebra(self, memoria_isolada):
        r = actions.buscar_memoria("qualquer coisa", user_id="ninguem")
        assert r["ok"] is True and r["count"] == 0 and r["memorias"] == []

    def test_texto_sem_fato_nao_e_erro(self, memoria_isolada):
        r = actions.salvar_fato("bom dia", user_id="alex")
        assert r["ok"] is True and r["count"] == 0

    def test_user_id_ausente_vira_erro_tratado(self, memoria_isolada):
        r = actions.salvar_fato("meu nome é Alex", user_id="")
        assert r["ok"] is False and "user_id" in r["error"]

    def test_actions_estao_no_catalogo(self):
        nomes = {a["name"] for a in actions.CATALOG}
        assert {"salvar_fato", "buscar_memoria"} <= nomes
        for nome in ("salvar_fato", "buscar_memoria"):
            spec = next(a for a in actions.CATALOG if a["name"] == nome)
            assert spec["category"] == "memoria"
            assert spec["params"]["required"] == ["texto", "user_id"] or spec["params"]["required"] == ["consulta", "user_id"]

    def test_papel_user_pode_usar_a_propria_memoria(self):
        from core.security.permissions import DEFAULT_ROLE_PERMISSIONS

        user = DEFAULT_ROLE_PERMISSIONS["user"]
        assert "salvar_fato" in user and "buscar_memoria" in user

    def test_singleton_reaproveita_instancia(self, memoria_isolada):
        assert obter_memoria() is obter_memoria()


class TestMemoriaNoPrompt:
    """F4 fase 2: os fatos do usuário entram no prompt antes do LLM."""

    def _orch(self, tmp_path, **config):
        from core.orchestrator import Orchestrator, OrchestratorConfig, RecordingProvider
        from memory.history import ConversationHistory

        provider = RecordingProvider("qwen", "resposta")
        return (
            Orchestrator(
                providers=[provider],
                history=ConversationHistory(base_dir=tmp_path / "conversas"),
                config=OrchestratorConfig(**config) if config else None,
            ),
            provider,
        )

    @pytest.mark.asyncio
    async def test_fato_do_usuario_entra_no_prompt(self, tmp_path):
        obter_memoria().adicionar_fato(
            "alex", "mora em curitiba", entidade="cidade"
        )
        orch, provider = self._orch(tmp_path)
        await orch.process("alex", "guardian", "onde eu moro?")
        assert "mora em curitiba" in provider.prompts[-1]
        assert "Memória do usuário" in provider.prompts[-1]

    @pytest.mark.asyncio
    async def test_sem_memoria_o_prompt_nao_ganha_bloco(self, tmp_path):
        orch, provider = self._orch(tmp_path)
        await orch.process("alex", "guardian", "qual a capital do brasil?")
        assert "Memória do usuário" not in provider.prompts[-1]

    @pytest.mark.asyncio
    async def test_memoria_de_outro_usuario_nao_vaza(self, tmp_path):
        obter_memoria().adicionar_fato("maria", "mora em recife", entidade="cidade")
        orch, provider = self._orch(tmp_path)
        await orch.process("alex", "guardian", "onde eu moro?")
        assert "recife" not in provider.prompts[-1]

    @pytest.mark.asyncio
    async def test_desligavel_na_config(self, tmp_path):
        obter_memoria().adicionar_fato("alex", "mora em curitiba", entidade="cidade")
        orch, provider = self._orch(tmp_path, memoria_no_prompt=False)
        await orch.process("alex", "guardian", "onde eu moro?")
        assert "mora em curitiba" not in provider.prompts[-1]

    @pytest.mark.asyncio
    async def test_respeita_o_limite_de_fatos(self, tmp_path):
        memoria = obter_memoria()
        for i in range(8):
            memoria.adicionar_fato("alex", f"gosta de item {i}", entidade="gosto")
        orch, provider = self._orch(tmp_path, memoria_max_fatos=2)
        await orch.process("alex", "guardian", "do que eu gosto?")
        prompt = provider.prompts[-1]
        assert prompt.count("- gosta de item") <= 2

    @pytest.mark.asyncio
    async def test_bloco_respeita_orcamento_de_chars(self, tmp_path):
        memoria = obter_memoria()
        for i in range(5):
            memoria.adicionar_fato(
                "alex", f"gosta de coisa{i} " + "detalhe " * 40, entidade=f"a{i}"
            )
        orch, provider = self._orch(tmp_path, memoria_max_chars=200)
        await orch.process("alex", "guardian", "do que eu gosto?")
        bloco = provider.prompts[-1].split("Memória do usuário")[-1]
        assert bloco.count("detalhe") <= 20

    @pytest.mark.asyncio
    async def test_recall_do_bloco_injetado(self, tmp_path):
        """Recall@5 do bloco injetado — medido, não presumido.

        Baseline sem a fase 2: 0/10 (os fatos não existem no prompt).
        Medido hoje: 9/10. O único furo é "tenho algum animal?" → fato
        "tem um cachorro chamado Rex": sinônimo (animal≈cachorro) exige
        embedding, que é a fase 3 — não é bug do termo.
        """
        casos = [
            ("mora em Curitiba", "cidade", "onde eu moro?"),
            ("nome é Alex", "nome", "qual é o meu nome?"),
            ("trabalha com suporte", "trabalho", "com o que eu trabalho?"),
            ("prefere respostas curtas", "preferencia", "como eu gosto das respostas?"),
            ("não gosta de barulho", "nao_gosto", "do que eu não gosto?"),
            ("tem um cachorro chamado Rex", "possui", "tenho algum animal?"),
            ("aniversário é 3 de maio", "aniversario", "quando é meu aniversário?"),
            ("e-mail é alex@exemplo.com", "email", "qual é o meu e-mail?"),
            ("estuda engenharia", "estudo", "o que eu estudo?"),
            ("projeto é Omega", "projeto", "qual é o meu projeto?"),
        ]
        memoria = obter_memoria()
        for conteudo, entidade, _pergunta in casos:
            memoria.adicionar_fato("alex", conteudo, entidade=entidade)
        orch, provider = self._orch(tmp_path)
        acertos = 0
        for conteudo, _entidade, pergunta in casos:
            await orch.process("alex", "guardian", pergunta)
            if conteudo in provider.prompts[-1]:
                acertos += 1
        assert acertos >= 9  # 10/10 só com busca semântica (fase 3)


class TestOrquestrador:
    """O chat alimenta a memória sem o usuário pedir (melhor esforço)."""

    def _orch(self, tmp_path):
        from core.orchestrator import Orchestrator, StaticProvider
        from memory.history import ConversationHistory

        return Orchestrator(
            providers=[StaticProvider("qwen", "ok")],
            history=ConversationHistory(base_dir=tmp_path / "conversas"),
        )

    @pytest.mark.asyncio
    async def test_mensagem_do_usuario_vira_memoria(self, tmp_path):
        orch = self._orch(tmp_path)
        await orch.process("alex", "guardian", "meu nome é Alex e moro em Curitiba")
        entidades = {n.entidade for n in obter_memoria().ativos("alex")}
        assert entidades == {"nome", "cidade"}

    @pytest.mark.asyncio
    async def test_resposta_do_modelo_nao_vira_memoria(self, tmp_path):
        orch = self._orch(tmp_path)
        await orch.process("alex", "guardian", "que horas são?")
        assert obter_memoria().ativos("alex") == []

    @pytest.mark.asyncio
    async def test_conversa_anonima_nao_grava(self, tmp_path):
        orch = self._orch(tmp_path)
        await orch.process("visitante", "guardian", "meu nome é Fulano", persist=False)
        assert obter_memoria().ativos("visitante") == []

    @pytest.mark.asyncio
    async def test_desligavel_por_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_AUTO", "0")
        orch = self._orch(tmp_path)
        await orch.process("alex", "guardian", "meu nome é Alex")
        assert obter_memoria().ativos("alex") == []

    @pytest.mark.asyncio
    async def test_falha_da_memoria_nao_quebra_a_resposta(self, tmp_path, monkeypatch):
        import core.memory_layer as ml

        def explode(*_a, **_k):
            raise RuntimeError("disco cheio")

        monkeypatch.setattr(ml, "obter_memoria", explode)
        orch = self._orch(tmp_path)
        result = await orch.process("alex", "guardian", "meu nome é Alex")
        assert result.message == "ok" and result.ok
