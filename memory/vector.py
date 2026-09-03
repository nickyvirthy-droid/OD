"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/vector.py
Descrição: Memória vetorial (RAG) — armazenamento de textos com embeddings,
           busca por similaridade de cosseno, thread safety e persistência.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky core/vector_memory.py (ChromaDB + sentence-transformers)
  - ROADMAP_ABSORCAO.md Fase 2, item 2.4
  - Mitigação de risco do roadmap: "Dependências externas → preferir stdlib;
    isolar em adapters"

Architecture:
    A integração ChromaDB do legado é substituída por uma camada com
    provider de embeddings plugável. O provider padrão (HashEmbeddingProvider)
    é 100% stdlib: vetores determinísticos via hash de n-grams, suficientes
    para similaridade semântica aproximada. Um provider real (ChromaDB,
    sentence-transformers) pode ser injetado depois sem alterar o restante.

    Os embeddings são persistidos junto com os textos (evita re-embedding).
    A busca é feita por similaridade de cosseno com os vetores em memória.

Usage:
    from memory.vector import VectorStore

    store = VectorStore(store_dir="data/vector_memory", top_k=3)
    store.add("knowledge", "O OmegaDrakon roda em /home/alex/OmegaDrakon")

    results = store.search("onde roda o OmegaDrakon?")
    print(results[0].text, results[0].score)
"""

from __future__ import annotations

import hashlib
import json
from core.logger import make_audit_nicky
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

_audit_nicky = make_audit_nicky("omega.memory.vector")

__signature__ = "OD // CORE"





# ---------------------------------------------------------------------------
# EmbeddingProvider
# ---------------------------------------------------------------------------

class EmbeddingProvider(Protocol):
    """Contrato para providers de embeddings.

    Um provider real (ChromaDB, sentence-transformers, etc.) pode ser
    injetado no VectorStore desde que implemente `embed` e `dimension`.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Converte uma lista de textos em uma lista de vetores."""
        ...

    @property
    def dimension(self) -> int:
        """Dimensão dos vetores produzidos."""
        ...


# ---------------------------------------------------------------------------
# HashEmbeddingProvider (stdlib)
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"[a-zà-ú0-9]+")


class HashEmbeddingProvider:
    """Provider determinístico de embeddings baseado em hash (stdlib puro).

    Cada token (palavra minúscula) e seus bigramas de caracteres são
    hasheados em posições de um vetor de `dimension` posições. É uma
    aproximação bag-of-words com dispersão determinística — adequada para
    similaridade semântica grosseira sem dependências externas.
    """

    def __init__(self, *, dimension: int = 256) -> None:
        if dimension < 8:
            raise ValueError("dimension deve ser >= 8")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        lowered = text.lower()
        tokens = _TOKEN_PATTERN.findall(lowered)
        if not tokens:
            return vector
        features: list[str] = []
        for token in tokens:
            features.append(f"w:{token}")
            if len(token) >= 2:
                for i in range(len(token) - 1):
                    features.append(f"b:{token[i:i+2]}")
        for feature in features:
            h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(h[:4], "big") % self._dimension
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vector[index] += sign
        # Normaliza para vetor unitário (similaridade de cosseno = produto interno)
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SearchResult:
    """Resultado de uma busca na memória vetorial."""

    doc_id: str
    namespace: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

class VectorStore:
    """Memória vetorial com busca por similaridade de cosseno.

    Attributes:
        store_dir: Diretório de persistência.
        provider:  Provider de embeddings (padrão: HashEmbeddingProvider).
        top_k:     Número padrão de resultados por busca.
    """

    def __init__(
        self,
        *,
        store_dir: str | Path = "data/vector_memory",
        provider: Optional[EmbeddingProvider] = None,
        top_k: int = 3,
    ) -> None:
        self._store_dir = Path(store_dir)
        self._provider: EmbeddingProvider = provider or HashEmbeddingProvider()
        self._top_k = max(1, top_k)
        self._docs: dict[str, dict[str, Any]] = {}  # doc_id -> registro
        self._lock = threading.RLock()

    # -- Escrita -------------------------------------------------------------

    def add(
        self,
        namespace: str,
        text: str,
        *,
        metadata: Optional[dict[str, Any]] = None,
        doc_id: Optional[str] = None,
    ) -> str:
        """Adiciona um texto ao namespace, embedando e persistindo.

        Returns:
            O doc_id gerado/fornecido.
        """
        if not text or not text.strip():
            raise ValueError("text não pode ser vazio")
        doc_id = doc_id or uuid.uuid4().hex[:16]
        vector = self._provider.embed([text])[0]
        with self._lock:
            self._docs[doc_id] = {
                "doc_id": doc_id,
                "namespace": namespace,
                "text": text,
                "vector": vector,
                "metadata": dict(metadata or {}),
                "created_ts": time.time(),
            }
            self._persist()
        return doc_id

    def add_many(
        self,
        namespace: str,
        texts: list[str],
        *,
        metadata_list: Optional[list[Optional[dict[str, Any]]]] = None,
    ) -> list[str]:
        """Adiciona vários textos de uma vez (embedding em lote)."""
        if not texts:
            return []
        vectors = self._provider.embed(texts)
        ids: list[str] = []
        with self._lock:
            for i, text in enumerate(texts):
                doc_id = uuid.uuid4().hex[:16]
                meta = metadata_list[i] if metadata_list and i < len(metadata_list) else None
                self._docs[doc_id] = {
                    "doc_id": doc_id,
                    "namespace": namespace,
                    "text": text,
                    "vector": vectors[i],
                    "metadata": dict(meta or {}),
                    "created_ts": time.time(),
                }
                ids.append(doc_id)
            self._persist()
        return ids

    # -- Busca ---------------------------------------------------------------

    def search(
        self,
        namespace: str,
        query: str,
        *,
        top_k: Optional[int] = None,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """Busca os textos mais similares ao query dentro do namespace.

        Args:
            namespace: Namespace a pesquisar.
            query:     Texto de consulta.
            top_k:     Nº de resultados (padrão: definido no construtor).
            min_score: Filtro de similaridade mínima (0.0 = sem filtro).

        Returns:
            Lista de SearchResult ordenada por score decrescente.
        """
        k = top_k or self._top_k
        query_vector = self._provider.embed([query])[0]
        scored: list[tuple[float, dict[str, Any]]] = []
        with self._lock:
            for doc in self._docs.values():
                if doc["namespace"] != namespace:
                    continue
                score = cosine_similarity(query_vector, doc["vector"])
                if score >= min_score:
                    scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            SearchResult(
                doc_id=doc["doc_id"],
                namespace=doc["namespace"],
                text=doc["text"],
                score=score,
                metadata=dict(doc["metadata"]),
            )
            for score, doc in scored[:k]
        ]

    # -- Gestão --------------------------------------------------------------

    def delete(self, doc_id: str) -> bool:
        """Remove um documento. Retorna True se existia."""
        with self._lock:
            if self._docs.pop(doc_id, None) is not None:
                self._persist()
                return True
            return False

    def clear(self, namespace: Optional[str] = None) -> int:
        """Limpa um namespace (ou tudo). Retorna quantidade removida."""
        with self._lock:
            if namespace is None:
                count = len(self._docs)
                self._docs.clear()
                self._persist()
                return count
            to_remove = [did for did, doc in self._docs.items() if doc["namespace"] == namespace]
            for did in to_remove:
                self._docs.pop(did)
            self._persist()
            return len(to_remove)

    def get(self, doc_id: str) -> Optional[dict[str, Any]]:
        """Retorna um documento (sem vetor)."""
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc is None:
                return None
            return {
                "doc_id": doc["doc_id"],
                "namespace": doc["namespace"],
                "text": doc["text"],
                "metadata": dict(doc["metadata"]),
                "created_ts": doc["created_ts"],
            }

    def count(self, namespace: Optional[str] = None) -> int:
        with self._lock:
            if namespace is None:
                return len(self._docs)
            return sum(1 for doc in self._docs.values() if doc["namespace"] == namespace)

    def list_namespaces(self) -> list[str]:
        with self._lock:
            return sorted({doc["namespace"] for doc in self._docs.values()})

    # -- Persistência --------------------------------------------------------

    def load(self) -> int:
        """Carrega o armazenamento do disco. Retorna nº de documentos."""
        path = self._file_path()
        if not path.exists():
            return 0
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._docs.clear()
                for item in data.get("documents", []):
                    self._docs[item["doc_id"]] = item
                return len(self._docs)
            except Exception as exc:
                _audit_nicky("WARN", "VectorStore load failed", error=type(exc).__name__)
                return 0

    def _persist(self) -> None:
        try:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "provider": type(self._provider).__name__,
                "dimension": self._provider.dimension,
                "updated_at": time.time(),
                "documents": list(self._docs.values()),
            }
            path = self._file_path()
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as exc:
            _audit_nicky("CRIT", "VectorStore persist failed", error=type(exc).__name__)

    def _file_path(self) -> Path:
        return self._store_dir / "vector_store.json"

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {
                "store_dir": str(self._store_dir),
                "provider": type(self._provider).__name__,
                "dimension": self._provider.dimension,
                "top_k": self._top_k,
                "documents": len(self._docs),
                "namespaces": self.list_namespaces(),
            }


# ---------------------------------------------------------------------------
# Similaridade
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno entre dois vetores (stdlib puro)."""
    if len(a) != len(b):
        raise ValueError("Vetores com dimensões diferentes")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)