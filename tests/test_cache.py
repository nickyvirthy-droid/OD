#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_cache
Description: Unit tests for memory/cache.py — SHA-256 LLM cache with
             normalization and deduplication (Fase 2, item 2.2).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.cache import CacheEntry, LLMCache, normalize_prompt


@pytest.fixture
def cache(tmp_path: Path) -> LLMCache:
    return LLMCache(cache_dir=tmp_path / "cache", profile="guardian")


# ===========================================================================
# Normalização
# ===========================================================================

class TestNormalization:
    """Tests for prompt normalization."""

    def test_collapses_whitespace(self) -> None:
        assert normalize_prompt("oi    tudo   bem") == "oi tudo bem"

    def test_strips_edges(self) -> None:
        assert normalize_prompt("  oi  ") == "oi"

    def test_newlines_collapsed(self) -> None:
        assert normalize_prompt("linha1\n\nlinha2") == "linha1 linha2"

    def test_preserves_case(self) -> None:
        assert normalize_prompt("Olá Mundo") == "Olá Mundo"

    def test_empty(self) -> None:
        assert normalize_prompt("") == ""


# ===========================================================================
# Chave SHA-256
# ===========================================================================

class TestCacheKey:
    """Tests for SHA-256 key generation."""

    def test_key_is_sha256_hex(self, cache: LLMCache) -> None:
        key = cache.make_key("oi")
        assert len(key) == 64
        int(key, 16)  # não levanta

    def test_same_prompt_same_key(self, cache: LLMCache) -> None:
        assert cache.make_key("oi tudo bem") == cache.make_key("oi tudo bem")

    def test_normalized_equivalence(self, cache: LLMCache) -> None:
        assert cache.make_key("oi   tudo") == cache.make_key("oi tudo")

    def test_different_prompt_different_key(self, cache: LLMCache) -> None:
        assert cache.make_key("oi") != cache.make_key("tchau")

    def test_profile_isolates_key(self, tmp_path: Path) -> None:
        c1 = LLMCache(cache_dir=tmp_path / "c", profile="guardian")
        c2 = LLMCache(cache_dir=tmp_path / "c", profile="nyx")
        assert c1.make_key("oi") != c2.make_key("oi")

    def test_params_affect_key(self, cache: LLMCache) -> None:
        assert cache.make_key("oi", temperature=0.1) != cache.make_key("oi", temperature=0.9)


# ===========================================================================
# Get/Set
# ===========================================================================

class TestCacheGetSet:
    """Tests for storing and retrieving responses."""

    def test_set_and_get(self, cache: LLMCache) -> None:
        cache.set("Qual a capital?", "Brasília.")
        assert cache.get("Qual a capital?") == "Brasília."

    def test_get_missing_returns_none(self, cache: LLMCache) -> None:
        assert cache.get("nunca visto") is None

    def test_get_with_whitespace_variation_hits(self, cache: LLMCache) -> None:
        cache.set("Qual  a capital?", "Brasília.")
        assert cache.get("Qual a capital?") == "Brasília."

    def test_has(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        assert cache.has("oi") is True
        assert cache.has("tchau") is False

    def test_get_entry(self, cache: LLMCache) -> None:
        cache.set("oi", "olá", llm_used="qwen", tokens_used=10)
        entry = cache.get_entry("oi")
        assert entry is not None
        assert entry.llm_used == "qwen"
        assert entry.tokens_used == 10

    def test_get_entry_missing(self, cache: LLMCache) -> None:
        assert cache.get_entry("nada") is None

    def test_delete(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        assert cache.delete("oi") is True
        assert cache.get("oi") is None
        assert cache.delete("oi") is False

    def test_clear(self, cache: LLMCache) -> None:
        cache.set("a", "1")
        cache.set("b", "2")
        assert cache.clear() == 2
        assert cache.get("a") is None


# ===========================================================================
# Métricas
# ===========================================================================

class TestCacheMetrics:
    """Tests for hit/miss/duplicate metrics."""

    def test_hits_and_misses(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        assert cache.get("oi") == "olá"      # hit
        assert cache.get("oi") == "olá"      # hit
        cache.get("desconhecido")            # miss
        m = cache.metrics()
        assert m["hits"] == 2
        assert m["misses"] == 1

    def test_use_count_increments(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        cache.get("oi")
        cache.get("oi")
        entry = cache.get_entry("oi")
        assert entry is not None
        assert entry.use_count == 3

    def test_set_same_prompt_counts_duplicate(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        cache.set("oi", "olá de novo")
        m = cache.metrics()
        assert m["duplicates"] == 1
        # Valor atualizado e persistido
        assert cache.get("oi") == "olá de novo"

    def test_stats(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        cache.get("oi")
        s = cache.stats()
        assert s["entries"] == 1
        assert s["total_use_count"] == 2
        assert s["total_duplicates"] == 0
        assert s["profile"] == "guardian"

    def test_metrics_survive_restart(self, tmp_path: Path) -> None:
        c1 = LLMCache(cache_dir=tmp_path / "c")
        c1.set("oi", "olá")
        c1.get("oi")
        c2 = LLMCache(cache_dir=tmp_path / "c")
        c2.load()
        assert c2.metrics()["hits"] == 1


# ===========================================================================
# Persistência
# ===========================================================================

class TestCachePersistence:
    """Tests for disk persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        c1 = LLMCache(cache_dir=tmp_path / "c")
        c1.set("Qual a capital?", "Brasília.")
        c2 = LLMCache(cache_dir=tmp_path / "c")
        assert c2.load() == 1
        assert c2.get("Qual a capital?") == "Brasília."

    def test_writes_json_file(self, cache: LLMCache, tmp_path: Path) -> None:
        cache.set("oi", "olá")
        path = tmp_path / "cache" / "cache.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["profile"] == "guardian"
        assert len(data["entries"]) == 1

    def test_atomic_no_tmp_left(self, cache: LLMCache, tmp_path: Path) -> None:
        cache.set("oi", "olá")
        assert not (tmp_path / "cache" / "cache.tmp").exists()

    def test_load_missing(self, cache: LLMCache) -> None:
        assert cache.load() == 0


# ===========================================================================
# TTL e evicção
# ===========================================================================

class TestCacheEviction:
    """Tests for TTL and max-entries eviction."""

    def test_ttl_expires(self, tmp_path: Path) -> None:
        cache = LLMCache(cache_dir=tmp_path / "c", ttl_seconds=0.01)
        cache.set("oi", "olá")
        import time

        time.sleep(0.02)
        assert cache.get("oi") is None

    def test_ttl_zero_no_expiry(self, cache: LLMCache) -> None:
        cache.set("oi", "olá")
        assert cache.get("oi") == "olá"

    def test_max_entries_evicts_oldest(self, tmp_path: Path) -> None:
        cache = LLMCache(cache_dir=tmp_path / "c", max_entries=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")
        m = cache.metrics()
        assert m["evictions"] == 1
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("c") == "3"

    def test_lru_approximation_keeps_used(self, tmp_path: Path) -> None:
        cache = LLMCache(cache_dir=tmp_path / "c", max_entries=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.get("a")  # a é tocado por último
        cache.set("c", "3")
        assert cache.get("b") is None  # b é o mais antigo agora
        assert cache.get("a") == "1"


# ===========================================================================
# CacheEntry
# ===========================================================================

class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_defaults(self) -> None:
        entry = CacheEntry(key="k", prompt="p", response="r")
        assert entry.use_count == 1
        assert entry.duplicates == 0
        assert entry.profile == ""

    def test_roundtrip_dict(self) -> None:
        entry = CacheEntry(key="k", prompt="p", response="r", use_count=5, duplicates=2)
        restored = CacheEntry.from_dict(entry.to_dict())
        assert restored.key == "k"
        assert restored.use_count == 5
        assert restored.duplicates == 2
        assert restored.response == "r"