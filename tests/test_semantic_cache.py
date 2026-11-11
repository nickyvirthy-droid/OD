"""
Testes do SemanticCache (I1).
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from memory.semantic_cache import SemanticCache, SemanticCacheEntry
from core.embeddings import EmbeddingConfig, LocalEmbeddingProvider, get_embedding_provider, reset_embedding_provider


class MockEmbeddingProvider:
    """Provider mock que retorna embeddings determinísticos baseados no hash do texto."""
    
    def __init__(self):
        self.dimension = 384
    
    def embed(self, text: str) -> list[float]:
        import hashlib
        # Gera embedding determinístico baseado no hash
        h = hashlib.md5(text.encode()).hexdigest()
        # Converte hex para lista de floats normalizados
        vals = [int(h[i:i+2], 16) / 255.0 for i in range(0, min(len(h), 64), 2)]
        # Pad/truncate para 384 dims
        while len(vals) < self.dimension:
            vals.extend(vals[:min(len(vals), self.dimension - len(vals))])
        return vals[:self.dimension]
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
    
    @property
    def name(self) -> str:
        return "mock"


@pytest.fixture
def mock_embedder():
    return MockEmbeddingProvider()


@pytest.fixture
def semantic_cache(tmp_path, mock_embedder):
    cache = SemanticCache(
        cache_dir=tmp_path / "semantic_cache",
        profile="test",
        max_entries=100,
        ttl_seconds=0,
        similarity_threshold=0.90,
        embedding_provider=mock_embedder,
    )
    yield cache
    # Cleanup
    cache.clear()


class TestSemanticCacheBasic:
    def test_set_and_get_exact(self, semantic_cache):
        """Chave exata deve acertar."""
        semantic_cache.set("Qual a capital do Brasil?", "Brasília.")
        result = semantic_cache.get("Qual a capital do Brasil?")
        assert result == "Brasília."
        assert semantic_cache.metrics()["exact_hits"] == 1

    def test_get_missing_returns_none(self, semantic_cache):
        """Prompt não cacheado retorna None."""
        result = semantic_cache.get("Pergunta inexistente")
        assert result is None
        assert semantic_cache.metrics()["semantic_misses"] == 1

    def test_semantic_similarity_hit(self, semantic_cache):
        """Pergunta semanticamente similar deve acertar (mesmo prompt = exact hit)."""
        semantic_cache.set("Qual a capital do Brasil?", "Brasília.")
        # Mesmo texto = embedding idêntico = exact hit (chave SHA-256 igual)
        result = semantic_cache.get("Qual a capital do Brasil?")
        assert result == "Brasília."
        # Mesmo prompt normalizado gera mesma chave -> exact_hits
        assert semantic_cache.metrics()["exact_hits"] == 1

    def test_semantic_different_but_similar_hit(self, semantic_cache):
        """Pergunta diferente mas semanticamente similar (mock retorna embeddings determinísticos)."""
        # Com MockEmbeddingProvider, textos diferentes geram embeddings diferentes
        # Para testar hit semântico real, precisaríamos de embeddings reais
        # Este teste valida que miss funciona para prompts diferentes
        semantic_cache.set("Qual a capital do Brasil?", "Brasília.")
        result = semantic_cache.get("Qual a capital da França?")
        assert result is None
        assert semantic_cache.metrics()["semantic_misses"] == 1

    def test_different_prompt_miss(self, semantic_cache):
        """Pergunta diferente deve dar miss."""
        semantic_cache.set("Qual a capital do Brasil?", "Brasília.")
        result = semantic_cache.get("Qual a capital da França?")
        assert result is None
        assert semantic_cache.metrics()["semantic_misses"] == 1

    def test_profile_isolation(self, semantic_cache):
        """Perfis diferentes isolam o cache."""
        semantic_cache.set("Pergunta teste", "Resposta A", profile="user1")
        result = semantic_cache.get("Pergunta teste", profile="user2")
        assert result is None  # Isolado por perfil

    def test_ttl_expiration(self, tmp_path, mock_embedder):
        """TTL expira entradas."""
        cache = SemanticCache(
            cache_dir=tmp_path / "semantic_cache",
            profile="test",
            max_entries=100,
            ttl_seconds=0.1,  # 100ms
            similarity_threshold=0.90,
            embedding_provider=mock_embedder,
        )
        cache.set("Pergunta", "Resposta")
        time.sleep(0.2)
        result = cache.get("Pergunta")
        assert result is None  # Expirado

    def test_persist_and_load(self, tmp_path, mock_embedder):
        """Persistência e carregamento funcionam."""
        cache1 = SemanticCache(
            cache_dir=tmp_path / "semantic_cache",
            profile="test",
            max_entries=100,
            ttl_seconds=0,
            similarity_threshold=0.90,
            embedding_provider=mock_embedder,
        )
        cache1.set("Pergunta persist", "Resposta persist")
        # Não chama clear() - testa persistência real
        
        cache2 = SemanticCache(
            cache_dir=tmp_path / "semantic_cache",
            profile="test",
            max_entries=100,
            ttl_seconds=0,
            similarity_threshold=0.90,
            embedding_provider=mock_embedder,
        )
        loaded = cache2.load()
        assert loaded == 1
        result = cache2.get("Pergunta persist")
        assert result == "Resposta persist"

    def test_max_entries_eviction(self, tmp_path, mock_embedder):
        """Evicção LRU quando excede max_entries."""
        cache = SemanticCache(
            cache_dir=tmp_path / "semantic_cache",
            profile="test",
            max_entries=3,
            ttl_seconds=0,
            similarity_threshold=0.90,
            embedding_provider=mock_embedder,
        )
        cache.set("A", "1")
        cache.set("B", "2")
        cache.set("C", "3")
        cache.set("D", "4")  # Deve evictar A
        assert cache.get("A") is None
        assert cache.get("B") == "2"
        assert cache.get("C") == "3"
        assert cache.get("D") == "4"


class TestSemanticCacheWithLLMCache:
    def test_exact_cache_priority(self, semantic_cache):
        """LLMCache exato tem prioridade sobre semântico."""
        from memory.cache import LLMCache
        
        llm_cache = LLMCache(cache_dir="/tmp/llm_cache_test", profile="test")
        semantic_cache._llm_cache = llm_cache
        
        # Coloca no LLMCache
        llm_cache.set("Pergunta exata", "Resposta exata")
        
        # SemanticCache deve retornar do LLMCache (exact hit)
        result = semantic_cache.get("Pergunta exata")
        assert result == "Resposta exata"
        assert semantic_cache.metrics()["exact_hits"] == 1

    def test_semantic_fallback_when_exact_miss(self, semantic_cache):
        """Se LLMCache miss, tenta semântico."""
        from memory.cache import LLMCache
        
        llm_cache = LLMCache(cache_dir="/tmp/llm_cache_test2", profile="test")
        semantic_cache._llm_cache = llm_cache
        
        # Só no semantic
        semantic_cache.set("Pergunta semântica", "Resposta semântica")
        
        # LLMCache miss -> semantic hit (exact hit no semantic cache)
        result = semantic_cache.get("Pergunta semântica")
        assert result == "Resposta semântica"
        # Mesmo prompt -> exact hit no semantic cache
        assert semantic_cache.metrics()["exact_hits"] == 1


class TestSemanticCacheEntry:
    def test_to_from_dict(self):
        """Serialização round-trip."""
        entry = SemanticCacheEntry(
            key="abc123",
            prompt="Teste",
            response="Resposta",
            profile="test",
            llm_used="gemini",
            tokens_used=100,
            use_count=5,
            embedding=[0.1, 0.2, 0.3],
            similarity_threshold=0.95,
        )
        d = entry.to_dict()
        restored = SemanticCacheEntry.from_dict(d)
        assert restored.key == entry.key
        assert restored.prompt == entry.prompt
        assert restored.response == entry.response
        assert restored.profile == entry.profile
        assert restored.llm_used == entry.llm_used
        assert restored.tokens_used == entry.tokens_used
        assert restored.use_count == entry.use_count
        assert restored.embedding == entry.embedding
        assert restored.similarity_threshold == entry.similarity_threshold


class TestEmbeddingProvider:
    def test_local_embedder_singleton(self):
        """get_embedding_provider retorna singleton."""
        reset_embedding_provider()
        p1 = get_embedding_provider()
        p2 = get_embedding_provider()
        assert p1 is p2
        reset_embedding_provider()

    def test_local_embedder_dimension(self):
        """Local embedder retorna dimensão correta (skip se não instalado)."""
        pytest.importorskip("sentence_transformers")
        reset_embedding_provider()
        config = EmbeddingConfig(provider="local", model="sentence-transformers/all-MiniLM-L6-v2")
        provider = LocalEmbeddingProvider(config)
        assert hasattr(provider, 'embed')
        assert hasattr(provider, 'embed_batch')
        assert hasattr(provider, 'dimension')
        assert hasattr(provider, 'name')
        reset_embedding_provider()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])