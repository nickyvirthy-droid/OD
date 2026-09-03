#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_vector
Description: Unit tests for memory/vector.py — stdlib vector memory with
             cosine similarity (Fase 2, item 2.4).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.vector import (
    HashEmbeddingProvider,
    SearchResult,
    VectorStore,
    cosine_similarity,
)


# ===========================================================================
# HashEmbeddingProvider
# ===========================================================================

class TestHashEmbeddingProvider:
    """Tests for the stdlib embedding provider."""

    def test_dimension(self) -> None:
        p = HashEmbeddingProvider(dimension=128)
        assert p.dimension == 128

    def test_embed_dimension(self) -> None:
        p = HashEmbeddingProvider(dimension=64)
        vecs = p.embed(["oi"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 64

    def test_deterministic(self) -> None:
        p = HashEmbeddingProvider()
        assert p.embed(["mesmo texto"]) == p.embed(["mesmo texto"])

    def test_similar_texts_similar_vectors(self) -> None:
        p = HashEmbeddingProvider()
        a = p.embed(["O OmegaDrakon roda em casa"])[0]
        b = p.embed(["OmegaDrakon roda em casa"])[0]
        c = p.embed(["receita de bolo de chocolate"])[0]
        assert cosine_similarity(a, b) > cosine_similarity(a, c)

    def test_empty_text_zero_vector(self) -> None:
        p = HashEmbeddingProvider()
        vec = p.embed([""])[0]
        assert vec == [0.0] * p.dimension

    def test_invalid_dimension(self) -> None:
        with pytest.raises(ValueError):
            HashEmbeddingProvider(dimension=4)

    def test_embed_batch(self) -> None:
        p = HashEmbeddingProvider()
        vecs = p.embed(["a", "b", "c"])
        assert len(vecs) == 3


# ===========================================================================
# Cosine similarity
# ===========================================================================

class TestCosineSimilarity:
    """Tests for cosine similarity."""

    def test_identical_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_partial(self) -> None:
        assert abs(cosine_similarity([1.0, 1.0], [2.0, 0.0]) - 0.7071) < 0.001

    def test_zero_vector(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_mismatched_dimensions(self) -> None:
        with pytest.raises(ValueError):
            cosine_similarity([1.0], [1.0, 2.0])


# ===========================================================================
# VectorStore — escrita
# ===========================================================================

class TestVectorStoreAdd:
    """Tests for adding documents."""

    def test_add_returns_id(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        doc_id = store.add("k", "texto")
        assert len(doc_id) == 16

    def test_add_with_custom_id(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        assert store.add("k", "texto", doc_id="abc123") == "abc123"

    def test_add_empty_raises(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        with pytest.raises(ValueError):
            store.add("k", "   ")

    def test_add_many(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        ids = store.add_many("k", ["um", "dois", "três"])
        assert len(ids) == 3
        assert store.count("k") == 3

    def test_add_many_empty(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        assert store.add_many("k", []) == []

    def test_metadata_stored(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        doc_id = store.add("k", "texto", metadata={"fonte": "manual"})
        doc = store.get(doc_id)
        assert doc is not None
        assert doc["metadata"] == {"fonte": "manual"}


# ===========================================================================
# VectorStore — busca
# ===========================================================================

class TestVectorStoreSearch:
    """Tests for similarity search."""

    def test_search_finds_most_similar(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("k", "O OmegaDrakon orquestra agentes de IA em casa")
        store.add("k", "Receita de pão de queijo mineiro")
        results = store.search("k", "onde roda o OmegaDrakon?", top_k=1)
        assert len(results) == 1
        assert "OmegaDrakon" in results[0].text
        assert results[0].score > 0

    def test_search_returns_searchresult(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("k", "texto qualquer")
        results = store.search("k", "texto", top_k=5)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_respects_top_k(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add_many("k", ["um um um", "dois dois", "tres", "quatro"])
        results = store.search("k", "um um um", top_k=2)
        assert len(results) == 2

    def test_search_default_top_k(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v", top_k=1)
        store.add_many("k", ["um um um", "dois dois", "tres", "quatro"])
        results = store.search("k", "um um um")
        assert len(results) == 1

    def test_search_min_score_filter(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("k", "abc xyz")
        store.add("k", "abc xyz completamente igual")
        results = store.search("k", "abc xyz completamente igual", min_score=0.99)
        assert len(results) == 1

    def test_search_namespace_isolation(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("a", "conteúdo do namespace a")
        store.add("b", "conteúdo do namespace b")
        results = store.search("a", "a", top_k=5)
        assert all(r.namespace == "a" for r in results)

    def test_search_empty_store(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        assert store.search("k", "qualquer") == []

    def test_scores_ordered_desc(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("k", "banana banana banana banana")
        store.add("k", "banana banana banana")
        store.add("k", "banana")
        results = store.search("k", "banana", top_k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


# ===========================================================================
# VectorStore — gestão e persistência
# ===========================================================================

class TestVectorStoreManage:
    """Tests for delete/clear/count and persistence."""

    def test_delete(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        doc_id = store.add("k", "texto")
        assert store.delete(doc_id) is True
        assert store.delete(doc_id) is False
        assert store.count() == 0

    def test_clear_namespace(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("a", "x")
        store.add("a", "y")
        store.add("b", "z")
        assert store.clear("a") == 2
        assert store.count("a") == 0
        assert store.count("b") == 1

    def test_clear_all(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("a", "x")
        store.add("b", "y")
        assert store.clear() == 2
        assert store.count() == 0

    def test_list_namespaces(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("b", "x")
        store.add("a", "y")
        assert store.list_namespaces() == ["a", "b"]

    def test_roundtrip_persistence(self, tmp_path: Path) -> None:
        s1 = VectorStore(store_dir=tmp_path / "v")
        s1.add("k", "O OmegaDrakon roda localmente")
        s2 = VectorStore(store_dir=tmp_path / "v")
        assert s2.load() == 1
        results = s2.search("k", "OmegaDrakon local", top_k=1)
        assert len(results) == 1
        assert "OmegaDrakon" in results[0].text

    def test_writes_json(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("k", "texto")
        path = tmp_path / "v" / "vector_store.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["dimension"] == 256
        assert len(data["documents"]) == 1

    def test_atomic_no_tmp_left(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        store.add("k", "texto")
        assert not (tmp_path / "v" / "vector_store.tmp").exists()

    def test_load_missing(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v")
        assert store.load() == 0

    def test_dump(self, tmp_path: Path) -> None:
        store = VectorStore(store_dir=tmp_path / "v", top_k=5)
        store.add("k", "texto")
        d = store.dump()
        assert d["documents"] == 1
        assert d["top_k"] == 5
        assert d["provider"] == "HashEmbeddingProvider"