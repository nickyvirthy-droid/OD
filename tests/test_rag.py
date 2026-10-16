#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_rag.py
Descrição: Parte B do NOMAD — pipeline RAG (memory/rag.py) + etapa 4.5 do
           orquestrador. Cobre reescrita com histórico, floor duplo
           medido, visibilidade por papel, orçamento com métrica do
           descartado, calibração por modelo e a GATE de calibração com as
           16 queries medidas no corpus real (2026-10-14).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from memory.rag import (
    JANELA_PADRAO,
    PISO_OVERLAP,
    PISO_SCORE,
    Fonte,
    ProviderSemStopwords,
    RAGPipeline,
    chunkizar_markdown,
    combinado,
    fontes_padrao,
    janela_do_modelo,
    reescrever,
    termos,
    termos_da_consulta,
)
from memory.vector import HashEmbeddingProvider, VectorStore

REPO = Path(__file__).resolve().parent.parent


# ===========================================================================
# Funções puras — termos, reescrita, chunking, calibração de modelo
# ===========================================================================

class TestTermos:
    def test_remove_stopwords_e_pontuacao(self):
        assert termos("Quais são as regras da casa?") == ["regras", "casa"]

    def test_texto_vazio_devolve_lista_vazia(self):
        assert termos("") == []
        assert termos("   ") == []

    def test_mantem_termos_de_conteudo_raros(self):
        assert "nômade" in termos("projeto nômade do Nômade") or "nomade" in [
            t.replace("ô", "o") for t in termos("projeto nômade")
        ]

    def test_case_e_acentos_normalizados(self):
        assert termos("REGISTRO Mestre") == ["registro", "mestre"]


class TestTermosDaConsulta:
    """Prefixo de instrução não conta no floor (incidente 2026-10-14).

    "responda curto: ..." — dois termos raríssimos inflavam a soma_idf e
    derrubavam consulta certa (overlap 0.211 < 0.22 → 0 trechos → o LLM
    respondeu inventando as "regras" em vez de citar o doc).
    """

    def test_prefixo_curto_de_instrucao_sai(self):
        bruto = termos("responda curto: quais regras de trabalho valem")
        assert "responda" in bruto and "curto" in bruto
        limpo = termos_da_consulta("responda curto: quais regras de trabalho valem")
        assert "responda" not in limpo
        assert "curto" not in limpo
        # o TÓPICO continua inteiro
        assert "regras" in limpo and "trabalho" in limpo and "valem" in limpo

    def test_consulta_sem_dois_pontos_intacta(self):
        p = "quais são as regras de trabalho da casa"
        assert termos_da_consulta(p) == termos(p)

    def test_prefixo_longo_nao_e_removido(self):
        # >5 palavras antes de ":" é conteúdo, não instrução — nada sai.
        p = "sobre o orçamento de contexto do pipeline: respostas"
        assert termos_da_consulta(p) == termos(p)

    def test_dois_pontos_sozinho_nao_muda(self):
        assert termos_da_consulta("regras: casa") == termos("casa")


class TestReescrever:
    def test_consulta_longa_autossuficiente_intacta(self):
        pergunta = "como funciona a política de versionamento do app hoje"
        consulta, reescrita = reescrever(pergunta, [
            {"role": "user", "content": "outro assunto qualquer"}
        ])
        assert consulta == pergunta
        assert reescrita is False

    def test_consulta_curta_agrega_historico(self):
        consulta, reescrita = reescrever("e as regras?", [
            {"role": "user", "content": "commit e push do projeto"},
        ])
        assert reescrita is True
        assert "regras" in consulta
        assert "commit" in consulta
        assert "push" in consulta

    def test_marcador_anafórico_dispara_reescrita(self):
        consulta, reescrita = reescrever(
            "e o preço dele tem desconto disponível aqui agora",
            [{"role": "assistant", "content": "anél abissal custa 280"}],
        )
        # > 4 termos, mas marcador " dele" força a reescrita
        assert reescrita is True
        assert "anél" in consulta or "abissal" in consulta

    def test_sem_historico_retorna_original(self):
        consulta, reescrita = reescrever("e as regras?", [])
        assert consulta == "e as regras?"
        assert reescrita is False

    def test_ignora_papeis_fora_de_user_assistant(self):
        consulta, reescrita = reescrever("e as regras?", [
            {"role": "system", "content": "segredo do sistema"},
        ])
        assert reescrita is False
        assert "segredo" not in consulta

    def test_nao_repete_termos_ja_na_consulta(self):
        consulta, _ = reescrever("regras?", [
            {"role": "user", "content": "regras regras regras"},
        ])
        # extras nunca duplicam a própria consulta
        assert consulta.count("regras") == 1

    def test_limite_de_extras(self):
        conteudo = " ".join(f"termo{i}" for i in range(20))
        consulta, reescrita = reescrever("e o que mais?", [
            {"role": "user", "content": conteudo}
        ])
        assert reescrita is True
        # no máximo MAX_EXTRAS_REESCRITA extras, na ordem de aparecimento
        extras = [t for t in consulta.split() if t.startswith("termo")]
        assert extras == ["termo0", "termo1", "termo2", "termo3", "termo4", "termo5"]

    def test_aceita_mensagens_como_objeto_message(self):
        class Msg:
            role = "user"
            content = "registro mestre das peças"

        consulta, reescrita = reescrever("e aquilo?", [Msg()])
        assert reescrita is True
        assert "registro" in consulta


class TestChunkizar:
    TITULO = (
        "# Guia\nCorpo inicial do guia com mais de sessenta caracteres "
        "para não ser descartado pelo mínimo.\n"
        "## Seção Um\nConteúdo da seção um com mais de sessenta "
        "caracteres também para virar chunk de verdade.\n"
        "## Seção Dois\nConteúdo da seção dois com mais de sessenta "
        "caracteres para virar chunk de verdade também.\n"
    )

    def test_divide_por_titulos_com_metadata(self):
        blocos = chunkizar_markdown(self.TITULO, "docs/guia.md")
        assert len(blocos) >= 3
        for texto, meta in blocos:
            assert meta["source"] == "docs/guia.md"
            assert meta["titulo"]
            assert len(texto) >= 60

    def test_respeita_teto_de_tamanho(self):
        texto = "linha de conteúdo com mais de vinte caracteres.\n" * 200
        blocos = chunkizar_markdown(texto, "docs/gigante.md", max_chars=500)
        assert len(blocos) > 1
        for corpo, _ in blocos:
            assert len(corpo) <= 600  # cabeçalho + teto com folga

    def test_descarta_trecho_minimo(self):
        blocos = chunkizar_markdown("# Só título\n", "docs/curto.md")
        assert blocos == []

    def test_sem_titulo_usa_o_nome_da_fonte(self):
        blocos = chunkizar_markdown(
            "texto corrido com mais de sessenta caracteres para formar "
            "um chunk válido sem nenhum título markdown no meio.\n",
            "docs/sem_titulo.md",
        )
        assert blocos[0][1]["titulo"] == "docs/sem_titulo.md"


class TestFontesEModelo:
    def test_fontes_padrao_cobre_docs_knowledge_e_iniciar(self):
        fontes = fontes_padrao(REPO)
        assert fontes, "corpus padrão vazio"
        alvos = {f.caminho.parts[-2] for f in fontes}
        assert {"docs", "knowledge", "iniciar"} <= alvos
        assert all(f.caminho.suffix == ".md" for f in fontes)
        assert all(f.visibilidade == "interna" for f in fontes)

    def test_fontes_padrao_ignora_diretorio_ausente(self, tmp_path):
        assert fontes_padrao(tmp_path) == []

    def test_janela_do_modelo_conhecida(self):
        assert janela_do_modelo("qwen2.5-coder-3b") == 8192

    def test_janela_do_modelo_desconhecida_usa_fallback(self):
        assert janela_do_modelo("modelo_inventado") == JANELA_PADRAO
        assert janela_do_modelo("") == JANELA_PADRAO

    def test_janela_case_insensitive(self):
        assert janela_do_modelo("Qwen2.5-Coder-3B-Instruct") == 8192


class TestProviderSemStopwords:
    def test_limpa_antes_de_delegar(self):
        capturado = {}

        class Espiao:
            dimension = 8

            def embed(self, texts):
                capturado["texts"] = texts
                return [[0.0] * 8 for _ in texts]

        prov = ProviderSemStopwords(Espiao())
        prov.embed(["A casa de Pedro da praça"])
        assert capturado["texts"] == ["casa pedro praça"]

    def test_dimension_delegada(self):
        prov = ProviderSemStopwords(HashEmbeddingProvider())
        assert prov.dimension == 256
        assert prov.base.__class__.__name__ == "HashEmbeddingProvider"

    def test_embedding_sem_stopwords_separa_mais(self):
        # Sem stopwords o cosseno entre afim e genérico é maior (porque
        # "de/a" deixa de pontuar igual para todos) — a base do floor.
        prov = ProviderSemStopwords(HashEmbeddingProvider())
        v1, v2, v3 = prov.embed([
            "registro mestre peças",
            "registro mestre peças",
            "casa praça rua",
        ])
        from memory.vector import cosine_similarity

        assert cosine_similarity(v1, v2) == pytest.approx(1.0)
        assert cosine_similarity(v1, v3) < 0.5


class TestFormulaCombinada:
    def test_peso_dos_dois_sinais(self):
        assert combinado(1.0, 0.0) == pytest.approx(0.8)
        assert combinado(0.0, 1.0) == pytest.approx(0.2)
        assert combinado(0.5, 0.5) == pytest.approx(0.5)

    def test_cosseno_alto_sem_overlap_nao_garante_piso(self):
        # 0.44 de cosseno parece alto, mas sem termo raro o combinado
        # cai abaixo do PISO_SCORE (a segunda chave do floor).
        assert combinado(0.44, 0.0) < PISO_SCORE

    def test_overlap_perfeito_com_cosseno_baixo_tambem_cai(self):
        assert combinado(0.10, 1.0) < PISO_SCORE


# ===========================================================================
# RAGPipeline — ingestão, consulta, floor, visibilidade, orçamento
# ===========================================================================

def _fonte(tmp_path: Path, nome: str, corpo: str, **kwargs) -> Fonte:
    arq = tmp_path / nome
    arq.write_text(corpo, encoding="utf-8")
    return Fonte(caminho=arq, **kwargs)


def _pipeline(tmp_path: Path, **kwargs) -> RAGPipeline:
    store = VectorStore(
        store_dir=tmp_path / "store",
        provider=ProviderSemStopwords(HashEmbeddingProvider()),
        top_k=24,  # coerente com TOP_K_CANDIDATOS (medição real: alvo em 15º)
    )
    fontes = [
        _fonte(
            tmp_path,
            "alvo.md",
            "# Orçamento de contexto\n"
            "O orçamento de contexto descarta o que não cabe e o descartado "
            "vira métrica obrigatória no pipeline do assistente.\n"
            "## Registro mestre\n"
            "O Registro Mestre indexa peças físicas com código gravado.\n",
        ),
        _fonte(
            tmp_path,
            "genérico.md",
            "# Receitas da vovó\n"
            "Receita de bolo de cenoura com cobertura de chocolate "
            "para a tarde do fim de semana com a família toda.\n",
        ),
    ]
    kwargs.setdefault("fontes", fontes)
    return RAGPipeline(store, **kwargs)


class TestSync:
    def test_primeira_ingestao_cria_chunks_e_df(self, tmp_path):
        rag = _pipeline(tmp_path)
        stats = rag.sync()
        assert stats["novos"] >= 2
        assert stats["chunks"] == stats["novos"]
        assert rag.metricas()["consultas"] == 0

    def test_segunda_chamada_e_idempotente(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        stats = rag.sync()
        assert stats["novos"] == 0
        assert stats["atualizados"] == 0
        assert stats["iguais"] == stats["chunks"]

    def test_edicao_atualiza_o_chunk(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        arq = tmp_path / "alvo.md"
        arq.write_text(
            "# Novo título editado\n"
            "Conteúdo totalmente novo com mais de sessenta caracteres para "
            "formar um chunk válido após a edição do arquivo fonte.\n",
            encoding="utf-8",
        )
        stats = rag.sync()
        assert stats["atualizados"] >= 1
        assert stats["novos"] == 0

    def test_remocao_de_fonte_apaga_orfaos(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        antes = rag.store.count(rag.namespace)
        (tmp_path / "genérico.md").unlink()
        stats = rag.sync()
        assert stats["removidos"] >= 1
        assert rag.store.count(rag.namespace) < antes

    def test_sync_sem_fontes_nao_explode(self, tmp_path):
        store = VectorStore(store_dir=tmp_path / "vazio")
        rag = RAGPipeline(store, fontes=[])
        stats = rag.sync()
        assert stats["chunks"] == 0


class TestConsulta:
    def test_sem_corpus_retorna_vazio_sem_excecao(self, tmp_path):
        store = VectorStore(store_dir=tmp_path / "sem_sync")
        rag = RAGPipeline(store, fontes=[Fonte(caminho=tmp_path / "x.md")])
        r = rag.consult("orçamento de contexto", papel="admin")
        assert r.trechos == []
        assert r.block == ""
        assert rag.metricas()["consultas"] == 1

    def test_admin_recebe_bloco_com_source(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        r = rag.consult(
            "o que é o orçamento de contexto", papel="admin",
            system_prompt="Você é Nicky.",
        )
        assert r.trechos
        assert "alvo.md" in r.block
        assert "Acervo de referência" in r.block

    def test_user_nao_recebe_corpus_interno(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        r = rag.consult("o que é o orçamento de contexto", papel="user")
        assert r.trechos == []
        assert r.block == ""
        assert r.descartados_visibilidade >= 1

    def test_anonymous_tambem_nao_recebe(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        r = rag.consult("o que é o orçamento de contexto", papel="anonymous")
        assert r.block == ""

    def test_fonte_publica_vai_para_qualquer_papel(self, tmp_path):
        store = VectorStore(
            store_dir=tmp_path / "pub",
            provider=ProviderSemStopwords(HashEmbeddingProvider()),
            top_k=24,  # coerente com TOP_K_CANDIDATOS (medição real: alvo em 15º)
        )
        rag = RAGPipeline(store, fontes=[
            _fonte(
                tmp_path, "publico.md",
                "# Dúvidas frequentes do público\n"
                "Perguntas frequentes do público sobre o produto ficam "
                "respondidas nesta página de ajuda geral do site.\n",
                visibilidade="publica",
            )
        ])
        rag.sync()
        r = rag.consult("perguntas frequentes do público", papel="user")
        assert r.trechos
        assert "publico.md" in r.block

    def test_consulta_irrelevante_pega_o_floor(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        # A receita EXISTE no corpus e é relevante para a pergunta — o
        # floor não deve bloqueá-la (recall correto):
        r = rag.consult("me vende uma receita de bolo de cenoura", papel="admin")
        assert r.trechos
        # O gatilho contrário: consulta sem NENHUM termo do corpus →
        # floor rejeita tudo e o descarte fica registrado:
        r2 = rag.consult("xyzzy plugh quux", papel="admin")
        assert r2.trechos == []
        assert r2.descartados_floor >= 1

    def test_prefixo_de_instrucao_nao_derruba_consulta_certa(self, tmp_path):
        # Reproduz o incidente do serviço (2026-10-14): a frase crua
        # "responda curto: ..." diluía a soma_idf (idf de palavra rara de
        # comando) e a consulta certa voltava com 0 trechos — o LLM
        # respondia inventando em vez de citar o doc.
        store = VectorStore(
            store_dir=tmp_path / "instr",
            provider=ProviderSemStopwords(HashEmbeddingProvider()),
            top_k=24,
        )
        fontes = [
            # saturação de "commit/push/versão" (o CHANGELOG da vida real):
            _fonte(
                tmp_path, "log.md",
                "# Log\n"
                + "Push do commit novo na versão via CI. " * 40 + "\n",
            ),
            # o doc certo (o REGRAS_DE_TRABALHO.md da vida real):
            _fonte(
                tmp_path, "regras.md",
                "# REGRAS DE TRABALHO\n"
                "As regras de trabalho valem para todo commit e push "
                "feito no branch master com versão na mensagem.\n",
            ),
        ]
        rag = RAGPipeline(store, fontes=fontes)
        rag.sync()
        r = rag.consult(
            "responda curto: quais regras de trabalho valem para commit, "
            "push e versao?",
            papel="admin",
        )
        assert r.trechos, "prefixo de instrução não pode derrubar a consulta"
        assert any("regras.md" in t.source for t in r.trechos)

    def test_overlap_zero_e_rejeitado_mesmo_com_cosseno(self, tmp_path):
        # "casa" aparece em todo lugar (IDF baixo); "xylofone" em lugar
        # nenhum — a segunda chave do floor rejeita.
        rag = _pipeline(tmp_path)
        rag.sync()
        r = rag.consult("casa xylofone", papel="admin")
        assert r.trechos == []
        assert r.descartados_floor >= 1

    def test_reranker_ordena_por_score_combinado(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        r = rag.consult(
            "orçamento de contexto e registro mestre", papel="admin"
        )
        scores = [t.score for t in r.trechos]
        assert scores == sorted(scores, reverse=True)
        for t in r.trechos:
            assert t.score >= PISO_SCORE - 1e-9
            assert t.overlap >= PISO_OVERLAP - 1e-9

    def test_trecho_fonte_correta_do_alvo(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        r = rag.consult("o que é o Registro Mestre", papel="admin")
        assert r.trechos
        assert all("alvo.md" in t.source for t in r.trechos)


class TestOrcamento:
    def test_teto_intermediario_corta_com_metrica(self, tmp_path):
        # 3 trechos (~95 tokens juntos) com teto de 60: o primeiro entra,
        # o resto é DESCARTADO E CONTADO (a regra da casa: descarte =
        # métrica, nunca silêncio).
        rag = _pipeline(tmp_path, max_tokens_bloco=60)
        rag.sync()
        r = rag.consult("orçamento de contexto e registro mestre", papel="admin")
        assert 1 <= len(r.trechos) <= 2
        assert r.descartados_orcamento >= 1
        assert r.tokens_descartados >= 1
        assert r.block

    def test_sem_espaco_nao_injeta_nada(self, tmp_path):
        rag = _pipeline(tmp_path, janela=256, tokens_resposta=200)
        rag.sync()
        r = rag.consult(
            "orçamento de contexto", papel="admin",
            system_prompt="x" * 400,  # system já come a janela
        )
        assert r.block == ""
        assert r.trechos == []
        assert r.descartados_orcamento >= 1
        assert r.tokens_descartados >= 1

    def test_janela_generosa_entra_tudo(self, tmp_path):
        rag = _pipeline(tmp_path, janela=8192, tokens_resposta=512)
        rag.sync()
        r = rag.consult("orçamento de contexto e registro mestre", papel="admin")
        assert r.descartados_orcamento == 0
        assert len(r.trechos) >= 2

    def test_teto_maximo_do_bloco(self, tmp_path):
        rag = _pipeline(tmp_path, max_tokens_bloco=1)
        rag.sync()
        r = rag.consult("orçamento de contexto", papel="admin")
        assert r.block == ""


class TestMetricas:
    def test_acumula_entre_consultas(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        rag.consult("orçamento de contexto", papel="admin")
        rag.consult("orçamento de contexto", papel="user")
        m = rag.metricas()
        assert m["consultas"] == 2
        assert m["trechos"] >= 1
        assert m["descartados_visibilidade"] >= 1
        assert m["tokens_bloco"] >= 1

    def test_reescrita_contabilizada(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        rag.consult(
            "e o orçamento?",
            historico=[{"role": "user", "content": "métrica descartado"}],
            papel="admin",
        )
        assert rag.metricas()["reescritas"] == 1

    def test_dump_traz_o_estado(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        d = rag.dump()
        assert d["docs"] >= 2
        assert d["janela"] == JANELA_PADRAO
        assert d["min_score"] == PISO_SCORE
        assert "metricas" in d


# ===========================================================================
# Gate de calibração — as 16 queries medidas no corpus real
# ===========================================================================

RELEVANTES = [
    "o que é o projeto nômade e o que a gente absorveu dele",
    "como funciona a política de versionamento do app",
    "quais são as regras de trabalho da casa",
    "o que é o Registro Mestre das peças",
    "quais containers docker fazem parte do ecossistema",
    "quando o CI fica vermelho o que a suíte pega",
    "como é feito o eval do assistente com goldens",
    "qual é a identidade visual da Omega Drakon",
]
IRRELEVANTES = [
    "qual é a previsão do tempo em campo grande",
    "me vende uma receita de bolo de cenoura",
    "qual a distância da terra até marte",
    "quem venceu a copa do mundo de 1994",
    "preciso de um advogado para alugar imóvel",
    "me dá uma piada sobre gato",
    "qual o melhor time de basquete",
    "quanto é 15% de 380 reais",
]


@pytest.fixture(scope="module")
def rag_real(tmp_path_factory) -> RAGPipeline:
    """RAG sobre o corpus REAL (docs/ + knowledge/) em store temporário."""
    store_dir = tmp_path_factory.mktemp("rag_calibracao") / "store"
    store = VectorStore(
        store_dir=store_dir,
        provider=ProviderSemStopwords(HashEmbeddingProvider()),
        top_k=24,  # coerente com TOP_K_CANDIDATOS (medição real: alvo em 15º)
    )
    rag = RAGPipeline(store, fontes=fontes_padrao(REPO))
    rag.sync()
    return rag


class TestCalibracaoCorpusReal:
    """Regra medida em 2026-10-14 (recalibrada 2026-10-16): 8/8
    relevantes passam, 8/8 irrelevantes bloqueados. Falhou = o corpus ou
    a fórmula mudou → recalibrar com medição, nunca afrouxar no escuro.

    Recalibração 2026-10-16 (medição, não afrouxamento): o corpus ganhou
    `iniciar/*.md` (memória histórica) e o grid (ms 0.380..0.420 ×
    mo 0.000..0.060, passo 0.001) achou 780 células válidas — este gate
    8/8 + 8/8 COM 6/8 de parafrases (TestRecallParafrases) —; o centro
    medido é (0.399, 0.036). Fronteira: irrelevante "previsão do tempo"
    comb 0.3929 vs REL "projeto nômade" 0.4057 → margem ±0.006 no
    PISO_SCORE; as irr. de ov 0.000 (bolo, marte) caem no PISO_OVERLAP.
    """

    @pytest.mark.parametrize("pergunta", RELEVANTES)
    def test_relevante_passa_pelo_floor(self, rag_real, pergunta):
        r = rag_real.consult(pergunta, papel="admin")
        assert r.trechos, (
            f"relevante sem trecho: {pergunta!r} "
            f"(floor={r.descartados_floor}, candidatos={r.candidatos})"
        )

    @pytest.mark.parametrize("pergunta", IRRELEVANTES)
    def test_irrelevante_e_bloqueada(self, rag_real, pergunta):
        r = rag_real.consult(pergunta, papel="admin")
        assert r.trechos == [], (
            f"irrelevantes passaram: {pergunta!r} → "
            f"{[t.source for t in r.trechos]}"
        )
        assert r.descartados_floor >= 1

    def test_corpus_tem_massa_suficiente(self, rag_real):
        assert rag_real.dump()["docs"] >= 100


# ===========================================================================
# Recall de parafrases — a segunda metade do gate, medida em 2026-10-16
# ===========================================================================

PARAFRASES_PASSAM = [
    "do que trata o material do time nômade que a gente estudou",
    "quais passos sigo pra publicar uma versão nova do aplicativo",
    "como funciona o cadastro das peças artesanais que têm dono",
    "que programas rodam em contêiner aqui no servidor",
    "como vocês testam as respostas antes de liberar",
    "as cores e o estilo gráfico da marca",
]


class TestRecallParafrases:
    """Perguntas naturais sem termo raro em comum com a resposta.

    Medido em 2026-10-16 no corpus real: no floor antigo (0.36/0.22) com
    o corpus expandido só 1/8 passava; no floor recalibrado (0.399/0.036)
    estas 6/8 passam E o gate de calibração continua 8/8 + 8/8. As 2
    perdidas são ESTRUTURAIS (provado por medição): "combinado pra
    trabalhar" tem comb 0.3922 contra 0.3929 da irrelevante "previsão do
    tempo" — Δ0,0007, nenhum PISO_SCORE as separa — e "robô confere" fica
    em 0.3682 (abaixo de qualquer piso que segure a irrelevante).
    """

    @pytest.mark.parametrize("pergunta", PARAFRASES_PASSAM)
    def test_parafrase_passa_pelo_floor(self, rag_real, pergunta):
        r = rag_real.consult(pergunta, papel="admin")
        assert r.trechos, (
            f"parafrase sem trecho: {pergunta!r} "
            f"(floor={r.descartados_floor}, candidatos={r.candidatos})"
        )


# ===========================================================================
# Orquestrador — etapa 4.5 (REST e stream) + orçamento de histórico
# ===========================================================================

class _ProviderCaptura:
    """Provider que captura o prompt e responde fixo."""

    def __init__(self, reply: str = "resposta") -> None:
        self.name = "captura"
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kw):
        self.prompts.append(prompt)
        return "resposta do modelo"

    async def generate_stream(self, prompt: str, **kw):
        self.prompts.append(prompt)
        for parte in ("resposta ", "do modelo"):
            yield parte


def _orch(rag=None, **config):
    from core.orchestrator import Orchestrator, OrchestratorConfig

    return Orchestrator(
        providers=[_ProviderCaptura()],
        config=OrchestratorConfig(**config) if config else OrchestratorConfig(),
        rag=rag,
    )


class TestEtapa45Orquestrador:
    @pytest.mark.asyncio
    async def test_sem_rag_o_prompt_nao_muda(self):
        orch = _orch()
        r = await orch.process(
            "u1", "guardian", "conte uma história sobre dragões",
            role="admin", persist=False,
        )
        assert "Acervo de referência" not in r.prompt
        assert orch.metrics.rag_consultas == 0

    @pytest.mark.asyncio
    async def test_com_rag_o_bloco_entra_no_prompt_rest(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        orch = _orch(rag=rag)
        r = await orch.process(
            "u2", "guardian", "o que é o orçamento de contexto",
            role="admin", persist=False,
        )
        assert r.route == "llm"
        assert "Acervo de referência" in r.prompt
        assert "alvo.md" in r.prompt
        m = orch.metrics.snapshot()
        assert m["rag_consultas"] == 1
        assert m["rag_trechos"] >= 1

    @pytest.mark.asyncio
    async def test_ordem_no_prompt_preserva_cache_kv(self, tmp_path):
        # Ordem obrigatória: identidade (estática) → data/hora → acervo.
        # Trocar invalida o prefixo de KV cache do llama-server a cada
        # mensagem (~25s de CPU a mais por turno).
        rag = _pipeline(tmp_path)
        rag.sync()
        orch = _orch(rag=rag)
        r = await orch.process(
            "u2b", "guardian", "o que é o orçamento de contexto",
            role="admin", persist=False,
            system_prompt="identidade estatica aqui",
        )
        identidade = r.prompt.index("identidade estatica aqui")
        data_hora = r.prompt.index("Hoje é")   # linha de data/hora viva
        acervo = r.prompt.index("Acervo de referência")
        assert identidade < data_hora < acervo

    @pytest.mark.asyncio
    async def test_papel_user_nao_receve_bloco(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        orch = _orch(rag=rag)
        r = await orch.process(
            "u3", "guardian", "o que é o orçamento de contexto",
            role="user", persist=False,
        )
        assert r.route == "llm"
        assert "Acervo de referência" not in r.prompt
        assert orch.metrics.rag_descartados >= 1

    @pytest.mark.asyncio
    async def test_stream_usa_o_mesmo_contexto(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        orch = _orch(rag=rag)
        eventos = [
            e
            async for e in orch.process_stream(
                "u4", "guardian", "o que é o Registro Mestre", role="admin"
            )
        ]
        assert any(e.get("type") == "done" for e in eventos)
        assert "Acervo de referência" in orch.providers[0].prompts[-1]
        assert orch.metrics.rag_consultas == 1

    @pytest.mark.asyncio
    async def test_fastpath_nao_gasta_rag(self, tmp_path):
        # Etapa 2 (datetime) responde ANTES da 4.5 — hora não consulta o
        # acervo (nem deveria: fastpaths nunca pagam o custo do RAG).
        rag = _pipeline(tmp_path)
        rag.sync()
        orch = _orch(rag=rag)
        r = await orch.process(
            "u5", "guardian", "que horas são?", role="admin", persist=False,
        )
        assert r.route == "datetime"
        assert orch.metrics.rag_consultas == 0

    @pytest.mark.asyncio
    async def test_snapshot_traz_as_chaves_rag(self, tmp_path):
        rag = _pipeline(tmp_path)
        rag.sync()
        orch = _orch(rag=rag)
        await orch.process(
            "u6", "guardian", "o que é o orçamento de contexto",
            role="admin", persist=False,
        )
        snap = orch.metrics.snapshot()
        for chave in (
            "rag_consultas", "rag_trechos", "rag_descartados",
            "rag_tokens_descartados", "contexto_descartados",
        ):
            assert chave in snap, chave


class TestOrcamentoDeHistorico:
    HIST_DIR = Path("/tmp/od_hist_teste_rag")

    @pytest.mark.asyncio
    async def test_janela_pequena_descarta_turnos_antigos(self):
        from core.orchestrator import Orchestrator, OrchestratorConfig
        from memory.history import ConversationHistory

        import shutil

        shutil.rmtree(self.HIST_DIR, ignore_errors=True)
        hist = ConversationHistory(base_dir=self.HIST_DIR)
        for i in range(12):
            hist.add_message("u7", "guardian", "user", f"antiga {i} " + "x" * 300)
            hist.add_message("u7", "guardian", "assistant", f"resposta {i} " + "y" * 300)
        orch = Orchestrator(
            providers=[_ProviderCaptura()],
            history=hist,
            config=OrchestratorConfig(orcamento_janela=1024, orcamento_resposta=256),
        )
        try:
            r = await orch.process(
                "u7", "guardian", "e agora?", role="admin", persist=False,
            )
            assert orch.metrics.contexto_descartados >= 1
            # a pergunta atual NUNCA é descartada
            assert "e agora?" in r.prompt
        finally:
            shutil.rmtree(self.HIST_DIR, ignore_errors=True)

    def test_orcamento_desligado_nao_conta_descarte(self):
        from core.orchestrator import Orchestrator, OrchestratorConfig
        from memory.history import ConversationHistory

        import shutil

        shutil.rmtree(self.HIST_DIR, ignore_errors=True)
        hist = ConversationHistory(base_dir=self.HIST_DIR)
        hist.add_message("u8", "guardian", "user", "antiga " + "x" * 500)
        orch = Orchestrator(
            providers=[_ProviderCaptura()],
            history=hist,
            config=OrchestratorConfig(),  # orcamento_janela=0 (desligado)
        )
        try:
            asyncio.run(orch.process(
                "u8", "guardian", "oi", role="admin", persist=False,
            ))
            assert orch.metrics.contexto_descartados == 0
        finally:
            shutil.rmtree(self.HIST_DIR, ignore_errors=True)
