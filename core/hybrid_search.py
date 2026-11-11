"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/hybrid_search.py
Descrição: Hybrid Search (I2) — BM25 (lexical) + Dense (semântico) + 
           Cross-encoder Reranker. Recuperação híbrida para RAG.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - I2 do roadmap: Hybrid Search (BM25 + dense + cross-encoder reranker)
  - ROADMAP_ABSORCAO.md Fase 9-10 item I2
  - BEIR / MS MARCO benchmarks
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from storage.database import Database

from core.logger import get_logger
from core.embeddings import EmbeddingProvider, get_embedding_provider

__signature__ = "OD // CORE"

_log = get_logger("omega.core.hybrid_search")

# Configuração via env
DEFAULT_BM25_K1 = float(os.getenv("OD_HYBRID_BM25_K1", "1.5"))
DEFAULT_BM25_B = float(os.getenv("OD_HYBRID_BM25_B", "0.75"))
DEFAULT_RRF_K = int(os.getenv("OD_HYBRID_RRF_K", "60"))
DEFAULT_DENSE_TOP_K = int(os.getenv("OD_HYBRID_DENSE_TOP_K", "20"))
DEFAULT_BM25_TOP_K = int(os.getenv("OD_HYBRID_BM25_TOP_K", "20"))
DEFAULT_RERANK_TOP_K = int(os.getenv("OD_HYBRID_RERANK_TOP_K", "10"))
DEFAULT_FINAL_TOP_K = int(os.getenv("OD_HYBRID_FINAL_TOP_K", "3"))


@dataclass(slots=True)
class HybridSearchConfig:
    """Configuração do Hybrid Search."""
    bm25_k1: float = DEFAULT_BM25_K1
    bm25_b: float = DEFAULT_BM25_B
    rrf_k: int = DEFAULT_RRF_K
    dense_top_k: int = DEFAULT_DENSE_TOP_K
    bm25_top_k: int = DEFAULT_BM25_TOP_K
    rerank_top_k: int = DEFAULT_RERANK_TOP_K
    final_top_k: int = DEFAULT_FINAL_TOP_K
    enable_reranker: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __post_init__(self):
        # Override via env vars
        self.bm25_k1 = float(os.getenv("OD_HYBRID_BM25_K1", str(self.bm25_k1)))
        self.bm25_b = float(os.getenv("OD_HYBRID_BM25_B", str(self.bm25_b)))
        self.rrf_k = int(os.getenv("OD_HYBRID_RRF_K", str(self.rrf_k)))
        self.dense_top_k = int(os.getenv("OD_HYBRID_DENSE_TOP_K", str(self.dense_top_k)))
        self.bm25_top_k = int(os.getenv("OD_HYBRID_BM25_TOP_K", str(self.bm25_top_k)))
        self.rerank_top_k = int(os.getenv("OD_HYBRID_RERANK_TOP_K", str(self.rerank_top_k)))
        self.final_top_k = int(os.getenv("OD_HYBRID_FINAL_TOP_K", str(self.final_top_k)))
        self.enable_reranker = os.getenv("OD_HYBRID_ENABLE_RERANKER", str(self.enable_reranker)).lower() in ("1", "true", "yes", "on")
        self.reranker_model = os.getenv("OD_HYBRID_RERANKER_MODEL", self.reranker_model)


@dataclass(slots=True)
class Document:
    """Documento no índice híbrido."""
    doc_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    # BM25
    bm25_tokens: list[str] = field(default_factory=list)
    # Dense
    embedding: list[float] = field(default_factory=list)
    # Timestamps
    created_ts: float = field(default_factory=time.time)
    updated_ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "content": self.content,
            "metadata": self.metadata,
            "bm25_tokens": self.bm25_tokens,
            "embedding": self.embedding,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Document":
        return cls(
            doc_id=data["doc_id"],
            content=data["content"],
            metadata=data.get("metadata", {}),
            bm25_tokens=data.get("bm25_tokens", []),
            embedding=data.get("embedding", []),
            created_ts=data.get("created_ts", time.time()),
            updated_ts=data.get("updated_ts", time.time()),
        )


class BM25Index:
    """Índice BM25 (Okapi BM25) para busca lexical."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: dict[str, Document] = {}
        self._doc_freqs: dict[str, int] = defaultdict(int)  # token -> num docs
        self._doc_lengths: dict[str, int] = {}  # doc_id -> num tokens
        self._avg_doc_length: float = 0.0
        self._lock = threading.RLock()

    def add(self, doc: Document) -> None:
        with self._lock:
            # Remove old if exists
            if doc.doc_id in self._docs:
                self._remove_doc(doc.doc_id)

            self._docs[doc.doc_id] = doc
            self._doc_lengths[doc.doc_id] = len(doc.bm25_tokens)

            # Update doc frequencies
            unique_tokens = set(doc.bm25_tokens)
            for token in unique_tokens:
                self._doc_freqs[token] += 1

            self._recalc_avg_length()

    def _remove_doc(self, doc_id: str) -> None:
        if doc_id not in self._docs:
            return
        doc = self._docs[doc_id]
        unique_tokens = set(doc.bm25_tokens)
        for token in unique_tokens:
            self._doc_freqs[token] -= 1
            if self._doc_freqs[token] <= 0:
                del self._doc_freqs[token]
        del self._docs[doc_id]
        del self._doc_lengths[doc_id]

    def remove(self, doc_id: str) -> bool:
        """Remove documento do índice BM25."""
        with self._lock:
            if doc_id not in self._docs:
                return False
            self._remove_doc(doc_id)
            return True

    def _recalc_avg_length(self) -> None:
        if self._doc_lengths:
            self._avg_doc_length = sum(self._doc_lengths.values()) / len(self._doc_lengths)
        else:
            self._avg_doc_length = 0.0

    def search(self, query_tokens: list[str], top_k: int = 20) -> list[tuple[str, float]]:
        """Retorna [(doc_id, score), ...] ordenado por score BM25 desc."""
        if not self._docs or not query_tokens:
            return []

        with self._lock:
            N = len(self._docs)
            scores = defaultdict(float)

            for token in query_tokens:
                if token not in self._doc_freqs:
                    continue
                df = self._doc_freqs[token]
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

                # Para cada doc que contém o token
                for doc_id, doc in self._docs.items():
                    tf = doc.bm25_tokens.count(token)
                    if tf == 0:
                        continue
                    dl = self._doc_lengths[doc_id]
                    # BM25 formula
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avg_doc_length, 1))
                    scores[doc_id] += idf * numerator / denominator

            # Top-k
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return sorted_scores[:top_k]

    def __len__(self) -> int:
        return len(self._docs)

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()
            self._doc_freqs.clear()
            self._doc_lengths.clear()
            self._avg_doc_length = 0.0


class DenseIndex:
    """Índice denso (embeddings) para busca semântica."""

    def __init__(self, embedder: EmbeddingProvider):
        self._embedder = embedder
        self._docs: dict[str, Document] = {}
        self._lock = threading.RLock()

    def add(self, doc: Document) -> None:
        with self._lock:
            if doc.doc_id in self._docs:
                # Remove old embedding from search (just overwrite)
                pass
            self._docs[doc.doc_id] = doc

    def remove(self, doc_id: str) -> None:
        with self._lock:
            self._docs.pop(doc_id, None)

    def search(self, query_embedding: list[float], top_k: int = 20) -> list[tuple[str, float]]:
        """Busca por similaridade de cosseno. Retorna [(doc_id, score), ...]."""
        if not self._docs or not query_embedding:
            return []

        with self._lock:
            scores = []
            for doc_id, doc in self._docs.items():
                if not doc.embedding:
                    continue
                score = self._cosine_similarity(query_embedding, doc.embedding)
                scores.append((doc_id, score))

            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def __len__(self) -> int:
        return len(self._docs)

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()


class CrossEncoderReranker:
    """Cross-encoder reranker para reordenar resultados."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load_model(self) -> None:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import CrossEncoder
                        self._model = CrossEncoder(self._model_name)
                        _log.info("Cross-encoder reranker loaded", model=self._model_name)
                    except ImportError:
                        raise RuntimeError(
                            "sentence-transformers não instalado. "
                            "pip install sentence-transformers"
                        )
                    except Exception as exc:
                        raise RuntimeError(f"Falha ao carregar reranker: {exc}")

    def rerank(
        self,
        query: str,
        candidates: list[tuple[str, float, Document]],
        top_k: int = 10,
    ) -> list[tuple[str, float, Document]]:
        """Reordena candidatos usando cross-encoder."""
        if not candidates:
            return []

        self._load_model()

        # Prepara pares (query, doc_content)
        pairs = [(query, doc.content) for _, _, doc in candidates]

        try:
            scores = self._model.predict(pairs, show_progress_bar=False)
        except Exception as exc:
            _log.warn("Reranker failed, returning original order", error=str(exc))
            return candidates[:top_k]

        # Combina scores
        reranked = list(zip(candidates, scores))
        reranked.sort(key=lambda x: x[1], reverse=True)

        return [(doc_id, float(score), doc) for (doc_id, _, doc), score in reranked[:top_k]]


class HybridRetriever:
    """
    Retriever híbrido: BM25 + Dense + RRF + Cross-encoder Reranker.
    
    Pipeline:
    1. Query → tokens (BM25) + embedding (Dense)
    2. BM25 search top-k + Dense search top-k
    3. Reciprocal Rank Fusion (RRF) merge
    4. Cross-encoder rerank top-k
    5. Retorna top-k final
    """

    def __init__(
        self,
        config: Optional[HybridSearchConfig] = None,
        embedder: Optional[EmbeddingProvider] = None,
        index_dir: Optional[str | Path] = None,
    ):
        self.config = config or HybridSearchConfig()
        self._embedder = embedder or get_embedding_provider()

        self._bm25 = BM25Index(k1=self.config.bm25_k1, b=self.config.bm25_b)
        self._dense = DenseIndex(self._embedder)
        self._reranker = None
        if self.config.enable_reranker:
            try:
                self._reranker = CrossEncoderReranker(self.config.reranker_model)
            except Exception as exc:
                _log.warn("Reranker não disponível", error=str(exc))
                self._reranker = None

        self._docs: dict[str, Document] = {}
        self._index_dir = Path(index_dir) if index_dir else None
        self._lock = threading.RLock()

        if self._index_dir:
            self._index_dir.mkdir(parents=True, exist_ok=True)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenização simples para BM25 (português)."""
        import re
        # Lowercase, remove pontuação, split
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()
        # Remove stopwords básicas PT
        stopwords = {
            'a', 'o', 'as', 'os', 'de', 'da', 'do', 'das', 'dos',
            'e', 'em', 'na', 'no', 'nas', 'nos', 'um', 'uma',
            'para', 'com', 'por', 'que', 'qual', 'quais',
            'é', 'são', 'foi', 'era', 'tem', 'têm', 'ter',
            'se', 'não', 'mais', 'muito', 'bem', 'mal',
        }
        return [t for t in tokens if t not in stopwords and len(t) > 2]

    def add_document(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Document:
        """Adiciona/atualiza documento nos índices."""
        tokens = self._tokenize(content)

        # Gera embedding
        try:
            embedding = self._embedder.embed(content)
        except Exception as exc:
            _log.warn("Embedding failed for doc", doc_id=doc_id, error=str(exc))
            embedding = []

        doc = Document(
            doc_id=doc_id,
            content=content,
            metadata=metadata or {},
            bm25_tokens=tokens,
            embedding=embedding,
        )

        with self._lock:
            self._bm25.add(doc)
            self._dense.add(doc)
            self._docs[doc_id] = doc

        self._persist()
        return doc

    def remove_document(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self._docs:
                return False
            self._bm25.remove(doc_id)
            self._dense.remove(doc_id)
            self._docs.pop(doc_id, None)
            self._persist()
            return True

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_metadata: Optional[dict[str, Any]] = None,
    ) -> list[Document]:
        """
        Busca híbrida completa.
        
        Returns:
            Lista de Documents ordenados por relevância final.
        """
        if top_k is None:
            top_k = self.config.final_top_k

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Embedding da query
        try:
            query_embedding = self._embedder.embed(query)
        except Exception as exc:
            _log.warn("Query embedding failed", error=str(exc))
            query_embedding = []

        # 1. BM25 search
        bm25_results = self._bm25.search(
            query_tokens, top_k=self.config.bm25_top_k
        )

        # 2. Dense search
        dense_results = []
        if query_embedding:
            dense_results = self._dense.search(
                query_embedding, top_k=self.config.dense_top_k
            )

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores = self._rrf_merge(bm25_results, dense_results)

        # Top-k para reranker
        rerank_k = min(self.config.rerank_top_k, len(rrf_scores))
        top_candidates = rrf_scores[:rerank_k]

        # Converte para candidatos com documentos
        candidates = []
        for doc_id, score in top_candidates:
            doc = self._docs.get(doc_id)
            if doc is not None:
                candidates.append((doc_id, score, doc))

        # Filtro por metadata se fornecido
        if filter_metadata:
            candidates = [
                c for c in candidates
                if all(c[2].metadata.get(k) == v for k, v in filter_metadata.items())
            ]

        # 4. Cross-encoder reranker
        if self._reranker and candidates:
            try:
                reranked = self._reranker.rerank(query, candidates, top_k=top_k)
                return [doc for _, _, doc in reranked]
            except Exception as exc:
                _log.warn("Rerank failed, using RRF order", error=str(exc))

        # Fallback: ordem RRF
        return [doc for _, _, doc in candidates[:top_k]]

    def _rrf_merge(
        self,
        bm25_results: list[tuple[str, float]],
        dense_results: list[tuple[str, float]],
    ) -> list[tuple[str, float]]:
        """Reciprocal Rank Fusion merge."""
        rrf_scores = defaultdict(float)
        k = self.config.rrf_k

        # BM25 ranks
        for rank, (doc_id, _) in enumerate(bm25_results):
            rrf_scores[doc_id] += 1.0 / (k + rank + 1)

        # Dense ranks
        for rank, (doc_id, _) in enumerate(dense_results):
            rrf_scores[doc_id] += 1.0 / (k + rank + 1)

        # Ordena por score RRF
        merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return merged

    def _persist(self) -> None:
        if not self._index_dir:
            return
        try:
            data = {
                "config": {
                    "bm25_k1": self.config.bm25_k1,
                    "bm25_b": self.config.bm25_b,
                    "rrf_k": self.config.rrf_k,
                    "dense_top_k": self.config.dense_top_k,
                    "bm25_top_k": self.config.bm25_top_k,
                    "rerank_top_k": self.config.rerank_top_k,
                    "final_top_k": self.config.final_top_k,
                    "enable_reranker": self.config.enable_reranker,
                    "reranker_model": self.config.reranker_model,
                },
                "docs": {doc_id: doc.to_dict() for doc_id, doc in self._docs.items()},
            }
            path = self._index_dir / "hybrid_index.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            _log.error("Hybrid index persist failed", error=str(exc))

    def load(self) -> int:
        """Carrega índice do disco."""
        if not self._index_dir:
            return 0
        path = self._index_dir / "hybrid_index.json"
        if not path.exists():
            return 0

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)

            with self._lock:
                self._docs.clear()
                self._bm25.clear()
                self._dense.clear()

                for doc_id, doc_data in data.get("docs", {}).items():
                    doc = Document.from_dict(doc_data)
                    self._docs[doc_id] = doc
                    self._bm25.add(doc)
                    self._dense.add(doc)

                return len(self._docs)
        except Exception as exc:
            _log.error("Hybrid index load failed", error=str(exc))
            return 0

    def stats(self) -> dict[str, Any]:
        return {
            "total_docs": len(self._docs),
            "bm25_docs": len(self._bm25),
            "dense_docs": len(self._dense),
            "config": {
                "bm25_k1": self.config.bm25_k1,
                "bm25_b": self.config.bm25_b,
                "rrf_k": self.config.rrf_k,
                "dense_top_k": self.config.dense_top_k,
                "bm25_top_k": self.config.bm25_top_k,
                "rerank_top_k": self.config.rerank_top_k,
                "final_top_k": self.config.final_top_k,
                "enable_reranker": self.config.enable_reranker and self._reranker is not None,
                "reranker_model": self.config.reranker_model,
            },
        }