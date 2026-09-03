"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/cache.py
Descrição: Cache de respostas LLM — chave SHA-256 com normalização do prompt,
           deduplicação, TTL e métricas de uso.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky storage/llm_cache.py
  - ROADMAP_ABSORCAO.md Fase 2, item 2.2
  - Tabela legada llm_cache (query_hash, query_text, profile, response,
    llm_used, tokens_used, use_count, avg_response_time_ms)

Architecture:
    Cada prompt é normalizado (whitespace colapsado, trim) e reduzido a uma
    chave SHA-256, incluindo o perfil e parâmetros opcionais do LLM. A chave
    igual em armazenamento subsequente conta como duplicata (deduplicação),
    e acertos incrementam use_count. Persistência JSON com escrita atômica.

Usage:
    from memory.cache import LLMCache

    cache = LLMCache(cache_dir="data/llm_cache", profile="guardian")

    cache.set("Qual é a capital do Brasil?", "Brasília.")
    resposta = cache.get("Qual é a capital  do Brasil?")  # normalizado → hit
"""

from __future__ import annotations

import hashlib
import json
from core.logger import make_audit_nicky
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_audit_nicky = make_audit_nicky("omega.memory.cache")

__signature__ = "OD // CORE"





# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

_WS_PATTERN = re.compile(r"\s+")


def normalize_prompt(prompt: str) -> str:
    """Normaliza um prompt para comparação estável.

    - Colapsa toda sequência de whitespace em um espaço simples.
    - Aplica trim nas bordas.
    - Não altera maiúsculas/minúsculas (preserva semântica).
    """
    if not prompt:
        return ""
    return _WS_PATTERN.sub(" ", prompt).strip()


# ---------------------------------------------------------------------------
# CacheEntry
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CacheEntry:
    """Uma entrada do cache de respostas LLM."""

    key: str
    prompt: str            # prompt normalizado (query_text)
    response: str
    profile: str = ""
    llm_used: str = ""
    tokens_used: int = 0
    use_count: int = 1
    duplicates: int = 0
    created_ts: float = field(default_factory=time.time)
    last_used_ts: float = field(default_factory=time.time)
    avg_response_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "response": self.response,
            "profile": self.profile,
            "llm_used": self.llm_used,
            "tokens_used": self.tokens_used,
            "use_count": self.use_count,
            "duplicates": self.duplicates,
            "created_ts": self.created_ts,
            "last_used_ts": self.last_used_ts,
            "avg_response_time_ms": self.avg_response_time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheEntry":
        return cls(
            key=data["key"],
            prompt=data.get("prompt", ""),
            response=data.get("response", ""),
            profile=data.get("profile", ""),
            llm_used=data.get("llm_used", ""),
            tokens_used=data.get("tokens_used", 0),
            use_count=data.get("use_count", 1),
            duplicates=data.get("duplicates", 0),
            created_ts=data.get("created_ts", time.time()),
            last_used_ts=data.get("last_used_ts", time.time()),
            avg_response_time_ms=data.get("avg_response_time_ms", 0.0),
        )


# ---------------------------------------------------------------------------
# LLMCache
# ---------------------------------------------------------------------------

class LLMCache:
    """Cache de respostas LLM com chave SHA-256 normalizada.

    Attributes:
        cache_dir:   Diretório de persistência.
        profile:     Perfil do agente incluído na chave (isolamento).
        max_entries: Número máximo de entradas (evicção LRU aproximada).
        ttl_seconds: Expiração em segundos (0 = sem expiração).
        metrics:     Contadores de acerto/erro/duplicatas.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = "data/llm_cache",
        profile: str = "",
        max_entries: int = 10000,
        ttl_seconds: float = 0.0,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._profile = profile
        self._max_entries = max(1, max_entries)
        self._ttl = ttl_seconds
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._metrics = {"hits": 0, "misses": 0, "duplicates": 0, "evictions": 0}

    # -- Chave ---------------------------------------------------------------

    def make_key(self, prompt: str, **params: Any) -> str:
        """Gera a chave SHA-256 do prompt normalizado + perfil + params."""
        normalized = normalize_prompt(prompt)
        parts = [normalized, self._profile]
        for key in sorted(params):
            parts.append(f"{key}={params[key]}")
        raw = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def normalize(self, prompt: str) -> str:
        """Expõe a normalização aplicada aos prompts."""
        return normalize_prompt(prompt)

    # -- Leitura -------------------------------------------------------------

    def get(
        self,
        prompt: str,
        *,
        update_metrics: bool = True,
        **params: Any,
    ) -> Optional[str]:
        """Retorna a resposta cacheada, ou None em erro/ausência.

        Args:
            prompt: O prompt original (normalizado internamente).
            update_metrics: Incrementa contadores de hit/miss.
            **params: Parâmetros adicionais da chave (ex: temperature).

        Returns:
            A resposta cacheada ou None.
        """
        key = self.make_key(prompt, **params)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                if update_metrics:
                    self._metrics["misses"] += 1
                return None
            if self._is_expired(entry):
                self._entries.pop(key, None)
                if update_metrics:
                    self._metrics["misses"] += 1
                    self._metrics["evictions"] += 1
                return None
            entry.use_count += 1
            entry.last_used_ts = time.time()
            # Move para o fim (evicção LRU aproximada por ordem de inserção)
            self._entries.pop(key)
            self._entries[key] = entry
            if update_metrics:
                self._metrics["hits"] += 1
            self._persist()
            return entry.response

    def has(self, prompt: str, **params: Any) -> bool:
        key = self.make_key(prompt, **params)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or self._is_expired(entry):
                return False
            return True

    def get_entry(self, prompt: str, **params: Any) -> Optional[CacheEntry]:
        """Retorna a entrada completa (com métricas) sem contabilizar hit."""
        key = self.make_key(prompt, **params)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or self._is_expired(entry):
                return None
            return entry

    # -- Escrita -------------------------------------------------------------

    def set(
        self,
        prompt: str,
        response: str,
        *,
        llm_used: str = "",
        tokens_used: int = 0,
        response_time_ms: float = 0.0,
        **params: Any,
    ) -> CacheEntry:
        """Armazena a resposta para o prompt. Deduplica se a chave já existe.

        Returns:
            A entrada criada/atualizada.
        """
        key = self.make_key(prompt, **params)
        normalized = normalize_prompt(prompt)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                existing.duplicates += 1
                existing.use_count += 1
                existing.last_used_ts = time.time()
                existing.response = response
                existing.llm_used = llm_used or existing.llm_used
                self._entries.pop(key)
                self._entries[key] = existing
                self._metrics["duplicates"] += 1
                self._persist()
                return existing

            entry = CacheEntry(
                key=key,
                prompt=normalized,
                response=response,
                profile=self._profile,
                llm_used=llm_used,
                tokens_used=tokens_used,
                avg_response_time_ms=response_time_ms,
            )
            self._entries[key] = entry
            self._evict_if_needed()
            self._persist()
            return entry

    def delete(self, prompt: str, **params: Any) -> bool:
        """Remove uma entrada pela chave. Retorna True se existia."""
        key = self.make_key(prompt, **params)
        with self._lock:
            if self._entries.pop(key, None) is not None:
                self._persist()
                return True
            return False

    def clear(self) -> int:
        """Remove todas as entradas. Retorna quantidade removida."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._persist()
            return count

    # -- Persistência --------------------------------------------------------

    def load(self) -> int:
        """Carrega o cache do disco. Retorna número de entradas."""
        path = self._file_path()
        if not path.exists():
            return 0
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._entries.clear()
                for item in data.get("entries", []):
                    entry = CacheEntry.from_dict(item)
                    self._entries[entry.key] = entry
                self._metrics["hits"] = data.get("metrics", {}).get("hits", 0)
                self._metrics["misses"] = data.get("metrics", {}).get("misses", 0)
                return len(self._entries)
            except Exception as exc:
                _audit_nicky(
                    "WARN",
                    "Cache load failed",
                    error=type(exc).__name__,
                )
                return 0

    def _persist(self) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "profile": self._profile,
                "updated_at": time.time(),
                "metrics": dict(self._metrics),
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            path = self._file_path()
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as exc:
            _audit_nicky(
                "CRIT",
                "Cache persist failed",
                error=type(exc).__name__,
            )

    def _file_path(self) -> Path:
        return self._cache_dir / "cache.json"

    # -- Evicção -------------------------------------------------------------

    def _evict_if_needed(self) -> None:
        while len(self._entries) > self._max_entries:
            oldest_key = next(iter(self._entries))
            self._entries.pop(oldest_key)
            self._metrics["evictions"] += 1

    def _is_expired(self, entry: CacheEntry) -> bool:
        if self._ttl <= 0:
            return False
        return (time.time() - entry.created_ts) > self._ttl

    # -- Métricas ------------------------------------------------------------

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._metrics)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            entries = list(self._entries.values())
            total_uses = sum(e.use_count for e in entries)
            total_dups = sum(e.duplicates for e in entries)
            return {
                "entries": len(entries),
                "metrics": dict(self._metrics),
                "total_use_count": total_uses,
                "total_duplicates": total_dups,
                "profile": self._profile,
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl,
            }

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cache_dir": str(self._cache_dir),
                **self.stats(),
            }