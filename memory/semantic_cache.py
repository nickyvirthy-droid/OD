"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/semantic_cache.py
Descrição: Semantic Cache para RAG — cache de respostas LLM baseado em
           similaridade de embeddings (cosine ≥ threshold). Reduz chamadas
           LLM para perguntas semanticamente equivalentes.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - I1 do roadmap: Semantic Cache (Redis + embedding similarity ≥0.95)
  - Cache existente: memory/cache.py (LLMCache — exato)
  - ROADMAP_ABSORCAO.md Fase 9-10 item I1
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from storage.database import Database

from core.logger import get_logger
from core.embeddings import EmbeddingProvider, get_embedding_provider

__signature__ = "OD // CORE"

_log = get_logger("omega.memory.semantic_cache")

# Threshold padrão de similaridade (configurável via env)
DEFAULT_SIMILARITY_THRESHOLD = float(os.getenv("OD_SEMANTIC_CACHE_THRESHOLD", "0.95"))
DEFAULT_MAX_ENTRIES = int(os.getenv("OD_SEMANTIC_CACHE_MAX_ENTRIES", "5000"))
DEFAULT_TTL_SECONDS = float(os.getenv("OD_SEMANTIC_CACHE_TTL", "86400"))  # 24h


@dataclass(slots=True)
class SemanticCacheEntry:
    """Entrada do cache semântico com embedding."""
    key: str
    prompt: str
    response: str
    profile: str = ""
    llm_used: str = ""
    tokens_used: int = 0
    use_count: int = 1
    created_ts: float = field(default_factory=time.time)
    last_used_ts: float = field(default_factory=time.time)
    embedding: list[float] = field(default_factory=list)
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "response": self.response,
            "profile": self.profile,
            "llm_used": self.llm_used,
            "tokens_used": self.tokens_used,
            "use_count": self.use_count,
            "created_ts": self.created_ts,
            "last_used_ts": self.last_used_ts,
            "embedding": self.embedding,
            "similarity_threshold": self.similarity_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticCacheEntry":
        return cls(
            key=data["key"],
            prompt=data.get("prompt", ""),
            response=data.get("response", ""),
            profile=data.get("profile", ""),
            llm_used=data.get("llm_used", ""),
            tokens_used=data.get("tokens_used", 0),
            use_count=data.get("use_count", 1),
            created_ts=data.get("created_ts", time.time()),
            last_used_ts=data.get("last_used_ts", time.time()),
            embedding=data.get("embedding", []),
            similarity_threshold=data.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        )


class SemanticCache:
    """
    Cache semântico de respostas LLM usando embeddings para similaridade.

    Diferente do LLMCache (chave exata SHA-256), este cache:
    - Gera embedding do prompt na escrita
    - Na leitura, busca por similaridade de cosseno ≥ threshold
    - Retorna a resposta mais similar se passar no threshold
    - Métricas separadas: semantic_hits, semantic_misses, exact_hits

    Pode ser usado sozinho ou em camada sobre o LLMCache:
        cache = SemanticCache(llm_cache=LLMCache(...))
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = "data/semantic_cache",
        profile: str = "",
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        embedding_provider: Optional[EmbeddingProvider] = None,
        llm_cache: Optional[Any] = None,  # LLMCache opcional para fallback exato
        database: Optional["Database"] = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._profile = profile
        self._max_entries = max(1, max_entries)
        self._ttl = ttl_seconds
        self._similarity_threshold = similarity_threshold
        self._llm_cache = llm_cache
        self._database = database

        self._entries: dict[str, SemanticCacheEntry] = {}
        self._lock = threading.RLock()
        self._metrics = {
            "semantic_hits": 0,
            "semantic_misses": 0,
            "exact_hits": 0,
            "evictions": 0,
            "embedding_errors": 0,
        }

        # Provider de embeddings (lazy init)
        self._embedding_provider = embedding_provider
        self._embedder: Optional[EmbeddingProvider] = None

    def _get_embedder(self) -> EmbeddingProvider:
        """Lazy init do provider de embeddings."""
        if self._embedder is None:
            if self._embedding_provider is not None:
                self._embedder = self._embedding_provider
            else:
                self._embedder = get_embedding_provider()
        return self._embedder

    def _make_key(self, prompt: str, **params: Any) -> str:
        """Gera chave SHA-256 do prompt normalizado + perfil + params."""
        from memory.cache import normalize_prompt
        normalized = normalize_prompt(prompt)
        parts = [normalized, self._profile]
        for key in sorted(params):
            parts.append(f"{key}={params[key]}")
        raw = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Similaridade de cosseno entre dois vetores."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _find_best_match(
        self, query_embedding: list[float], profile: str
    ) -> Optional[SemanticCacheEntry]:
        """Busca linear por melhor match (otimizar com índice vetorial futuramente)."""
        best_entry = None
        best_score = 0.0

        for entry in self._entries.values():
            if entry.profile != profile:
                continue
            if self._is_expired(entry):
                continue
            score = self._cosine_similarity(query_embedding, entry.embedding)
            if score >= entry.similarity_threshold and score > best_score:
                best_score = score
                best_entry = entry

        return best_entry

    def get(
        self,
        prompt: str,
        *,
        update_metrics: bool = True,
        **params: Any,
    ) -> Optional[str]:
        """
        Retorna resposta cacheada se similaridade ≥ threshold.

        Ordem de busca:
        1. Cache exato (LLMCache se injetado) — hit rápido
        2. Cache semântico (este) — hit por similaridade
        3. Miss
        """
        profile = str(params.get("profile") or self._profile)

        # 1. Cache exato primeiro (se disponível)
        if self._llm_cache is not None:
            exact = self._llm_cache.get(prompt, update_metrics=False, **params)
            if exact is not None:
                if update_metrics:
                    self._metrics["exact_hits"] += 1
                return exact

        # 2. Cache semântico
        key = self._make_key(prompt, **params)

        # Tenta buscar embedding da query
        try:
            embedder = self._get_embedder()
            query_embedding = embedder.embed(prompt)
        except Exception as exc:
            _log.warn("Semantic cache: embedding failed", error=str(exc))
            self._metrics["embedding_errors"] += 1
            if update_metrics:
                self._metrics["semantic_misses"] += 1
            return None

        with self._lock:
            # Busca exata por chave (mesmo prompt normalizado)
            if key in self._entries:
                entry = self._entries[key]
                if not self._is_expired(entry):
                    entry.use_count += 1
                    entry.last_used_ts = time.time()
                    self._entries.pop(key)
                    self._entries[key] = entry
                    if update_metrics:
                        self._metrics["exact_hits"] += 1
                    return entry.response

            # Busca por similaridade
            match = self._find_best_match(query_embedding, profile)
            if match is not None:
                match.use_count += 1
                match.last_used_ts = time.time()
                if update_metrics:
                    self._metrics["semantic_hits"] += 1
                _log.debug(
                    "Semantic cache hit",
                    prompt=prompt[:50],
                    matched_prompt=match.prompt[:50],
                    similarity=round(self._cosine_similarity(query_embedding, match.embedding), 4),
                )
                return match.response

            if update_metrics:
                self._metrics["semantic_misses"] += 1
            return None

    def set(
        self,
        prompt: str,
        response: str,
        *,
        llm_used: str = "",
        tokens_used: int = 0,
        response_time_ms: float = 0.0,
        **params: Any,
    ) -> SemanticCacheEntry:
        """Armazena resposta com embedding do prompt."""
        key = self._make_key(prompt, **params)
        profile = str(params.get("profile") or self._profile)
        normalized = prompt.strip()

        # Gera embedding
        try:
            embedder = self._get_embedder()
            embedding = embedder.embed(prompt)
        except Exception as exc:
            _log.warn("Semantic cache: embedding failed on set", error=str(exc))
            self._metrics["embedding_errors"] += 1
            embedding = []

        now = time.time()

        if self._database is not None:
            # TODO: persistência no DB quando Database Layer tiver schema
            pass

        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                existing.use_count += 1
                existing.last_used_ts = now
                existing.response = response
                existing.llm_used = llm_used or existing.llm_used
                if embedding:
                    existing.embedding = embedding
                self._entries.pop(key)
                self._entries[key] = existing
                self._persist()
                return existing

            entry = SemanticCacheEntry(
                key=key,
                prompt=normalized,
                response=response,
                profile=profile,
                llm_used=llm_used,
                tokens_used=tokens_used,
                embedding=embedding,
                similarity_threshold=self._similarity_threshold,
                created_ts=now,
                last_used_ts=now,
            )
            self._entries[key] = entry
            self._evict_if_needed()
            self._persist()
            return entry

    def _evict_if_needed(self) -> None:
        """Evict LRU quando excede max_entries."""
        while len(self._entries) > self._max_entries:
            oldest_key = next(iter(self._entries))
            self._entries.pop(oldest_key)
            self._metrics["evictions"] += 1

    def _is_expired(self, entry: SemanticCacheEntry) -> bool:
        if self._ttl <= 0:
            return False
        return (time.time() - entry.created_ts) > self._ttl

    def _persist(self) -> None:
        """Persiste em JSON (cache_dir/semantic_cache.json)."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "profile": self._profile,
                "updated_at": time.time(),
                "similarity_threshold": self._similarity_threshold,
                "metrics": dict(self._metrics),
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            path = self._cache_dir / "semantic_cache.json"
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as exc:
            _log.error("Semantic cache persist failed", error=str(exc))

    def load(self) -> int:
        """Carrega cache do disco."""
        path = self._cache_dir / "semantic_cache.json"
        if not path.exists():
            return 0
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._entries.clear()
                for item in data.get("entries", []):
                    entry = SemanticCacheEntry.from_dict(item)
                    if not self._is_expired(entry):
                        self._entries[entry.key] = entry
                self._metrics.update(data.get("metrics", {}))
                self._similarity_threshold = data.get("similarity_threshold", self._similarity_threshold)
                return len(self._entries)
            except Exception as exc:
                _log.error("Semantic cache load failed", error=str(exc))
                return 0

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._metrics)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            entries = list(self._entries.values())
            total_uses = sum(e.use_count for e in entries)
            return {
                "entries": len(entries),
                "metrics": dict(self._metrics),
                "total_use_count": total_uses,
                "profile": self._profile,
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl,
                "similarity_threshold": self._similarity_threshold,
            }

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._persist()
            return count