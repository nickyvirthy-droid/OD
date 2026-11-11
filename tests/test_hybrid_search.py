"""
Testes do Hybrid Search (I2).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.hybrid_search import (
    HybridRetriever,
    HybridSearchConfig,
    BM25Index,
    DenseIndex,
    Document,
)
from core.embeddings import EmbeddingProvider


class MockEmbeddingProvider:
    """Provider mock para testes."""
    
    def __init__(self, dim: int = 384):
        self.dimension = dim
        self._cache = {}
    
    def embed(self, text: str) -> list[float]:
        if text in self._cache:
            return self._cache[text]
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        vals = [int(h[i:i+2], 16) / 255.0 for i in range(0, min(len(h), 64), 2)]
        while len(vals) < self.dimension:
            vals.extend(vals[:min(len(vals), self.dimension - len(vals))])
        result = vals[:self.dimension]
        self._cache[text] = result
        return result
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
    
    @property
    def name(self) -> str:
        return "mock"


@pytest.fixture
def mock_embedder():
    return MockEmbeddingProvider()


@pytest.fixture
def hybrid_retriever(tmp_path, mock_embedder):
    config = HybridSearchConfig(
        dense_top_k=10,
        bm25_top_k=10,
        rerank_top_k=5,
        final_top_k=3,
        enable_reranker=False,  # Desabilita reranker nos testes
    )
    retriever = HybridRetriever(
        config=config,
        embedder=mock_embedder,
        index_dir=tmp_path / "hybrid_index",
    )
    yield retriever


class TestBM25Index:
    def test_add_and_search(self, mock_embedder):
        """BM25 básico: adiciona e busca."""
        bm25 = BM25Index()
        
        doc1 = Document(doc_id="1", content="a capital do brasil é brasília", bm25_tokens=["capital", "brasil", "brasília"])
        doc2 = Document(doc_id="2", content="a cidade da frança é paris", bm25_tokens=["cidade", "frança", "paris"])
        
        bm25.add(doc1)
        bm25.add(doc2)
        
        results = bm25.search(["capital", "brasil"], top_k=5)
        assert len(results) == 1
        assert results[0][0] == "1"
        assert results[0][1] > 0

    def test_multiple_matches(self, mock_embedder):
        """Múltiplos matches ordenados por score."""
        bm25 = BM25Index()
        
        for i in range(5):
            doc = Document(doc_id=str(i), content=f"documento {i} texto", bm25_tokens=["documento", str(i), "texto"])
            bm25.add(doc)
        
        results = bm25.search(["documento", "texto"], top_k=10)
        assert len(results) == 5
        # Todos devem ter score > 0
        assert all(score > 0 for _, score in results)


class TestDenseIndex:
    def test_add_and_search(self, mock_embedder):
        """Dense index básico."""
        dense = DenseIndex(mock_embedder)
        
        doc1 = Document(doc_id="1", content="texto um", embedding=mock_embedder.embed("texto um"))
        doc2 = Document(doc_id="2", content="texto dois", embedding=mock_embedder.embed("texto dois"))
        
        dense.add(doc1)
        dense.add(doc2)
        
        query_emb = mock_embedder.embed("texto um")
        results = dense.search(query_emb, top_k=5)
        
        assert len(results) >= 1
        assert results[0][0] == "1"  # Mesmo texto = maior similaridade
        assert results[0][1] > 0.99  # Quase 1.0 para texto idêntico


class TestHybridRetriever:
    def test_add_document(self, hybrid_retriever):
        """Adiciona documento ao retriever."""
        doc = hybrid_retriever.add_document("doc1", "A capital do Brasil é Brasília.")
        assert doc.doc_id == "doc1"
        assert doc.content == "A capital do Brasil é Brasília."
        assert len(doc.bm25_tokens) > 0
        assert len(doc.embedding) > 0

    def test_search_bm25_only(self, hybrid_retriever, mock_embedder):
        """Busca com termos exatos (BM25)."""
        hybrid_retriever.add_document("1", "A capital do Brasil é Brasília.")
        hybrid_retriever.add_document("2", "A capital da França é Paris.")
        hybrid_retriever.add_document("3", "O Brasil é um país da América do Sul.")
        
        results = hybrid_retriever.search("capital do Brasil")
        assert len(results) >= 1
        # Doc 1 deve vir primeiro (contém "capital" e "Brasil")
        assert results[0].doc_id == "1"

    def test_search_semantic(self, hybrid_retriever, mock_embedder):
        """Busca semântica (embedding)."""
        hybrid_retriever.add_document("1", "A capital do Brasil é Brasília.")
        hybrid_retriever.add_document("2", "Paris é a capital da França.")
        hybrid_retriever.add_document("3", "Brasília é a capital federal brasileira.")
        
        # Query semanticamente similar ao doc 3
        results = hybrid_retriever.search("qual a capital do brasil")
        assert len(results) >= 1

    def test_rrf_merge(self, hybrid_retriever, mock_embedder):
        """RRF merge combina BM25 + Dense."""
        hybrid_retriever.add_document("1", "capital do brasil brasília")
        hybrid_retriever.add_document("2", "capital da frança paris")
        hybrid_retriever.add_document("3", "brasil país américa sul")
        
        results = hybrid_retriever.search("capital brasil")
        assert len(results) >= 1

    def test_persist_and_load(self, tmp_path, mock_embedder):
        """Persistência e carregamento."""
        config = HybridSearchConfig(
            enable_reranker=False,
        )
        retriever1 = HybridRetriever(config=config, embedder=mock_embedder, index_dir=tmp_path / "idx")
        retriever1.add_document("1", "Documento de teste persistência")
        
        # Novo retriever carrega do disco
        retriever2 = HybridRetriever(config=config, embedder=mock_embedder, index_dir=tmp_path / "idx")
        loaded = retriever2.load()
        
        assert loaded == 1
        results = retriever2.search("documento teste")
        assert len(results) == 1
        assert results[0].doc_id == "1"

    def test_remove_document(self, hybrid_retriever):
        """Remove documento."""
        hybrid_retriever.add_document("1", "Para remover")
        hybrid_retriever.add_document("2", "Para ficar")
        
        assert hybrid_retriever.remove_document("1") is True
        assert hybrid_retriever.remove_document("999") is False
        
        # Doc 1 removido - não deve aparecer nos resultados
        results = hybrid_retriever.search("remover")
        assert all(r.doc_id != "1" for r in results)
        # Doc 2 ainda existe
        results = hybrid_retriever.search("ficar")
        assert len(results) == 1
        assert results[0].doc_id == "2"

    def test_filter_metadata(self, hybrid_retriever):
        """Filtro por metadata."""
        hybrid_retriever.add_document("1", "Doc tipo A", metadata={"tipo": "A"})
        hybrid_retriever.add_document("2", "Doc tipo B", metadata={"tipo": "B"})
        
        results = hybrid_retriever.search("doc", filter_metadata={"tipo": "A"})
        assert len(results) == 1
        assert results[0].doc_id == "1"


class TestHybridRetrieverConfig:
    def test_config_defaults(self):
        """Configuração padrão."""
        config = HybridSearchConfig()
        assert config.bm25_k1 == 1.5
        assert config.bm25_b == 0.75
        assert config.rrf_k == 60
        assert config.dense_top_k == 20
        assert config.bm25_top_k == 20
        assert config.rerank_top_k == 10
        assert config.final_top_k == 3
        assert config.enable_reranker is True

    def test_config_from_env(self):
        """Configuração via env (já testado no HybridSearchConfig)."""
        import os
        os.environ["OD_HYBRID_BM25_K1"] = "2.0"
        os.environ["OD_HYBRID_FINAL_TOP_K"] = "5"
        try:
            config = HybridSearchConfig()
            assert config.bm25_k1 == 2.0
            assert config.final_top_k == 5
        finally:
            os.environ.pop("OD_HYBRID_BM25_K1", None)
            os.environ.pop("OD_HYBRID_FINAL_TOP_K", None)


class TestDocument:
    def test_to_from_dict(self):
        """Serialização round-trip."""
        doc = Document(
            doc_id="test123",
            content="Conteúdo de teste",
            metadata={"categoria": "teste"},
            bm25_tokens=["conteúdo", "teste"],
            embedding=[0.1, 0.2, 0.3],
        )
        d = doc.to_dict()
        restored = Document.from_dict(d)
        assert restored.doc_id == doc.doc_id
        assert restored.content == doc.content
        assert restored.metadata == doc.metadata
        assert restored.bm25_tokens == doc.bm25_tokens
        assert restored.embedding == doc.embedding


if __name__ == "__main__":
    pytest.main([__file__, "-v"])