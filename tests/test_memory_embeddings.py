#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_memory_embeddings.py
Descrição: Busca semântica da memória longa (F4 fase 4) — provider opcional
           via Gemini, cache de vetores em SQLite e o fallback que só dispara
           quando a busca lexical volta vazia. Nenhum teste fala com a rede.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F4 fase 4
  - core/memory_embeddings.py e core/memory_layer.py
"""

from __future__ import annotations

import urllib.error

import pytest

from core import memory_embeddings as emb
from core.memory_layer import MemoryGraph

# Embedding falso: 4 dimensões, uma por assunto. Reproduz o que importa para o
# fallback (sinônimo aproxima, assunto aleatório fica em cima da mediana) sem
# rede, sem cota e sem ruído de modelo.
_GRUPOS = (
    ("animal", "cachorro", "rex"),
    ("mora", "cidade", "curitiba"),
    ("nome", "alex"),
    ("trabalho", "trabalha", "suporte"),
)


def _falso_embed(textos):
    saida = []
    for texto in textos:
        vetor = [0.1, 0.1, 0.1, 0.1]
        baixo = texto.lower()
        for i, palavras in enumerate(_GRUPOS):
            if any(p in baixo for p in palavras):
                vetor[i] = 1.0
        saida.append(vetor)
    return saida


@pytest.fixture()
def semantica_ligada(monkeypatch):
    """Liga o fallback com o embedder falso e conta as chamadas."""
    chamadas: list[list[str]] = []

    def embed(textos):
        chamadas.append(list(textos))
        return _falso_embed(textos)

    monkeypatch.setattr(emb, "provedor_ativo", lambda: "gemini")
    monkeypatch.setattr(emb, "embed_textos", embed)
    return chamadas


@pytest.fixture()
def grafo(tmp_path):
    g = MemoryGraph(tmp_path / "mem.db")
    yield g
    g.fechar()


def _semear(g: MemoryGraph, user: str = "alex") -> None:
    for conteudo, entidade in (
        ("mora em curitiba", "cidade"),
        ("nome é alex", "nome"),
        ("trabalha com suporte", "trabalho"),
        ("prefere respostas curtas", "preferencia"),
        ("não gosta de barulho", "nao_gosto"),
        ("tem um cachorro chamado rex", "possui"),
        ("aniversário é 3 de maio", "aniversario"),
        ("e-mail é alex@exemplo.com", "email"),
        ("estuda engenharia", "estudo"),
        ("projeto é omega", "projeto"),
    ):
        g.adicionar_fato(user, conteudo, entidade=entidade)


class TestProvedor:
    """Configuração do provider — nunca liga sozinho sem chave."""

    def test_desligado_por_env(self, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_EMBEDDING", "off")
        monkeypatch.setenv("GEMINI_API_KEY", "chave")
        assert emb.provedor_ativo() == ""

    def test_auto_sem_chave_nao_liga(self, monkeypatch):
        monkeypatch.delenv("OD_MEMORY_EMBEDDING", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert emb.provedor_ativo() == ""

    def test_auto_com_chave_usa_gemini(self, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_EMBEDDING", "auto")
        monkeypatch.setenv("GEMINI_API_KEY", "chave")
        assert emb.provedor_ativo() == "gemini"

    def test_embed_sem_provider_devolve_none(self, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_EMBEDDING", "off")
        assert emb.embed_textos(["qualquer coisa"]) is None

    def test_falha_de_rede_devolve_none(self, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_EMBEDDING", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "chave")

        def explode(*_a, **_k):
            raise urllib.error.URLError("sem rede")

        monkeypatch.setattr(emb.urllib.request, "urlopen", explode)
        assert emb.embed_textos(["qualquer coisa"]) is None

    def test_texto_vazio_nao_chama_api(self, monkeypatch):
        monkeypatch.setenv("OD_MEMORY_EMBEDDING", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "chave")

        def explode(*_a, **_k):
            raise AssertionError("não deveria chamar a API")

        monkeypatch.setattr(emb.urllib.request, "urlopen", explode)
        assert emb.embed_textos([" ", ""]) == []

    def test_cosseno(self):
        assert emb.cosseno([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert emb.cosseno([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        assert emb.cosseno([], [1.0]) == 0.0


class TestFallbackSemantico:
    """O caso que a busca por termos não resolve: animal ≈ cachorro."""

    def test_sinonimo_entra_quando_lexical_falha(self, grafo, semantica_ligada):
        _semear(grafo)
        assert grafo.buscar("alex", "tenho algum animal?", semantica=False) == []
        achados = [n.conteudo for n in grafo.buscar("alex", "tenho algum animal?")]
        assert any("cachorro" in c for c in achados)

    def test_assunto_aleatorio_nao_puxa_fato(self, grafo, semantica_ligada):
        _semear(grafo)
        assert grafo.buscar("alex", "qual a capital do brasil?") == []
        assert grafo.buscar("alex", "me conta uma piada") == []

    def test_hit_lexical_nao_paga_embedding(self, grafo, semantica_ligada):
        _semear(grafo)
        achados = grafo.buscar("alex", "onde eu moro?")
        assert achados and achados[0].conteudo == "mora em curitiba"
        assert semantica_ligada == []

    def test_vetores_ficam_no_cache(self, grafo, semantica_ligada):
        _semear(grafo)
        assert grafo.stats()["vetores"] == 0
        grafo.buscar("alex", "tenho algum animal?")
        assert grafo.stats()["vetores"] >= 10

    def test_segunda_busca_reaproveita_vetores(self, grafo, semantica_ligada):
        _semear(grafo)
        grafo.buscar("alex", "tenho algum animal?")
        chamadas_fatos = [len(c) for c in semantica_ligada]
        assert chamadas_fatos[0] >= 10
        grafo.buscar("alex", "tenho algum bicho?")
        # só a consulta nova é embedada; os fatos vêm do cache
        assert semantica_ligada[-1] == ["tenho algum bicho?"]

    def test_poucos_fatos_nao_chamam_provider(self, grafo, semantica_ligada):
        grafo.adicionar_fato("alex", "tem um cachorro chamado rex", entidade="possui")
        assert grafo.buscar("alex", "tenho algum animal?") == []
        assert semantica_ligada == []

    def test_provider_off_mantem_busca_lexical(self, grafo):
        _semear(grafo)
        assert grafo.buscar("alex", "tenho algum animal?") == []
        assert grafo.buscar("alex", "onde eu moro?")[0].conteudo == "mora em curitiba"

    def test_pode_ser_desligado_por_chamada(self, grafo, semantica_ligada):
        _semear(grafo)
        assert grafo.buscar("alex", "tenho algum animal?", semantica=False) == []
        assert semantica_ligada == []

    def test_isolamento_entre_usuarios(self, grafo, semantica_ligada):
        _semear(grafo, "alex")
        _semear(grafo, "maria")
        grafo.adicionar_fato("maria", "tem um gato chamado mia", entidade="possui")
        achados = grafo.buscar("alex", "tenho algum animal?")
        assert achados and all("mia" not in n.conteudo for n in achados)

    # -- cache de resultados (fase 4b) -------------------------------------

    def test_repeticao_nao_chama_provider(self, grafo, semantica_ligada):
        _semear(grafo)
        grafo.buscar("alex", "tenho algum animal?")
        chamadas = len(semantica_ligada)
        grafo.buscar("alex", "tenho algum animal?")
        assert len(semantica_ligada) == chamadas
        assert grafo.stats()["semantica_cache"]["hits"] == 1

    def test_variacao_de_caixa_e_pontuacao_usa_cache(self, grafo, semantica_ligada):
        _semear(grafo)
        grafo.buscar("alex", "tenho algum animal?")
        chamadas = len(semantica_ligada)
        achados = grafo.buscar("alex", "  TENHO   algum animal!! ")
        assert len(semantica_ligada) == chamadas
        assert any("cachorro" in n.conteudo for n in achados)

    def test_resultado_vazio_tambem_entra_no_cache(self, grafo, semantica_ligada):
        _semear(grafo)
        assert grafo.buscar("alex", "qual a capital do brasil?") == []
        chamadas = len(semantica_ligada)
        assert grafo.buscar("alex", "qual a capital do brasil?") == []
        assert len(semantica_ligada) == chamadas

    def test_fato_novo_invalida_resultado_cacheado(self, grafo, semantica_ligada):
        _semear(grafo)
        assert grafo.buscar("alex", "tenho algum animal?") != []
        chamadas = len(semantica_ligada)
        grafo.adicionar_fato("alex", "tem um gato chamado mia", entidade="bicho")
        grafo.buscar("alex", "tenho algum animal?")
        assert len(semantica_ligada) > chamadas

    def test_fato_substituido_sai_do_resultado(self, grafo, semantica_ligada):
        grafo.adicionar_fato("alex", "tem um cachorro chamado rex", entidade="possui")
        for conteudo, entidade in (
            ("mora em curitiba", "cidade"),
            ("nome é alex", "nome"),
            ("trabalha com suporte", "trabalho"),
        ):
            grafo.adicionar_fato("alex", conteudo, entidade=entidade)
        antes = grafo.buscar("alex", "tenho algum animal?")
        assert any("rex" in n.conteudo for n in antes)
        grafo.adicionar_fato("alex", "tem um cachorro chamado bob", entidade="possui")
        depois = grafo.buscar("alex", "tenho algum animal?")
        assert all("rex" not in n.conteudo for n in depois)
        assert any("bob" in n.conteudo for n in depois)

    def test_cache_pode_ser_desligado(self, grafo, semantica_ligada, monkeypatch):
        _semear(grafo)
        monkeypatch.setenv("OD_MEMORY_SEMANTICA_CACHE_S", "0")
        grafo.buscar("alex", "tenho algum animal?")
        chamadas = len(semantica_ligada)
        grafo.buscar("alex", "tenho algum animal?")
        assert len(semantica_ligada) > chamadas
        assert grafo.stats()["semantica_cache"]["entradas"] == 0

    def test_cache_expira_por_ttl(self, tmp_path, semantica_ligada, monkeypatch):
        agora = [1_800_000_000.0]
        g = MemoryGraph(tmp_path / "ttl.db", clock=lambda: agora[0])
        try:
            _semear(g)
            monkeypatch.setenv("OD_MEMORY_SEMANTICA_CACHE_S", "60")
            g.buscar("alex", "tenho algum animal?")
            chamadas = len(semantica_ligada)
            agora[0] += 61
            g.buscar("alex", "tenho algum animal?")
            assert len(semantica_ligada) > chamadas
        finally:
            g.fechar()

    def test_falha_do_provider_nao_quebra_busca(self, grafo, monkeypatch):
        _semear(grafo)

        def explode(_textos):
            raise RuntimeError("provider caiu")

        monkeypatch.setattr(emb, "provedor_ativo", lambda: "gemini")
        monkeypatch.setattr(emb, "embed_textos", explode)
        monkeypatch.setattr(emb, "margem", lambda: 0.05)
        monkeypatch.setattr(emb, "minimo", lambda: 0.78)
        assert grafo.buscar("alex", "tenho algum animal?") == []
