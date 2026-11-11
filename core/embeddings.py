"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/embeddings.py
Descrição: Provider de embeddings unificado — suporta local (sentence-transformers)
           e remoto (OpenAI, Gemini). Usado por SemanticCache e HybridSearch.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - I1/I2 roadmap: embeddings provider compartilhado
  - ROADMAP_ABSORCAO.md Fase 9-10
"""

from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

_log = get_logger("omega.core.embeddings")


# Configuração via env
DEFAULT_LOCAL_MODEL = os.getenv("OD_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DEFAULT_REMOTE_PROVIDER = os.getenv("OD_EMBEDDING_REMOTE", "").lower()  # openai, gemini
OPENAI_EMBEDDING_MODEL = os.getenv("OD_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
GEMINI_EMBEDDING_MODEL = os.getenv("OD_GEMINI_EMBEDDING_MODEL", "embedding-001")


@dataclass(slots=True)
class EmbeddingConfig:
    """Configuração do provider de embeddings."""
    provider: str = "local"  # local, openai, gemini
    model: str = DEFAULT_LOCAL_MODEL
    batch_size: int = 32
    normalize: bool = True
    timeout_seconds: float = 30.0


class EmbeddingProvider(ABC):
    """Interface base para providers de embeddings."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Gera embedding para um texto único."""
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Gera embeddings para múltiplos textos (batch)."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensão do embedding."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificador do provider."""
        pass


class LocalEmbeddingProvider(EmbeddingProvider):
    """Provider local usando sentence-transformers."""

    def __init__(self, config: EmbeddingConfig):
        self._config = config
        self._model = None
        self._lock = threading.Lock()
        self._dimension = None

    def _load_model(self) -> None:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                        self._model = SentenceTransformer(self._config.model)
                        self._dimension = self._model.get_sentence_embedding_dimension()
                        _log.info("Local embedding model loaded", model=self._config.model, dim=self._dimension)
                    except ImportError:
                        raise RuntimeError(
                            "sentence-transformers não instalado. "
                            "pip install sentence-transformers"
                        )
                    except Exception as exc:
                        raise RuntimeError(f"Falha ao carregar modelo local: {exc}")

    def embed(self, text: str) -> list[float]:
        self._load_model()
        embedding = self._model.encode(
            text,
            normalize_embeddings=self._config.normalize,
            convert_to_tensor=False,
        )
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=self._config.batch_size,
            normalize_embeddings=self._config.normalize,
            convert_to_tensor=False,
        )
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        return self._dimension

    @property
    def name(self) -> str:
        return f"local:{self._config.model}"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Provider remoto usando OpenAI embeddings API."""

    def __init__(self, config: EmbeddingConfig):
        self._config = config
        self._client = None
        self._dimension = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
                api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY2")
                if not api_key:
                    raise RuntimeError("OPENAI_API_KEY não configurada")
                self._client = openai.OpenAI(api_key=api_key)
            except ImportError:
                raise RuntimeError("openai não instalado. pip install openai")
        return self._client

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        model = self._config.model or OPENAI_EMBEDDING_MODEL
        response = client.embeddings.create(
            model=model,
            input=texts,
            encoding_format="float",
        )
        embeddings = [d.embedding for d in response.data]
        if self._config.normalize:
            # Normaliza L2
            for emb in embeddings:
                norm = sum(x * x for x in emb) ** 0.5
                if norm > 0:
                    for i in range(len(emb)):
                        emb[i] /= norm
        if self._dimension is None and embeddings:
            self._dimension = len(embeddings[0])
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Força uma chamada para descobrir dimensão
            self.embed("test")
        return self._dimension or 1536  # text-embedding-3-small default

    @property
    def name(self) -> str:
        return f"openai:{self._config.model or OPENAI_EMBEDDING_MODEL}"


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Provider remoto usando Gemini embeddings API."""

    def __init__(self, config: EmbeddingConfig):
        self._config = config
        self._dimension = None

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError("google-generativeai não instalado. pip install google-generativeai")

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não configurada")
        genai.configure(api_key=api_key)

        model = self._config.model or GEMINI_EMBEDDING_MODEL
        embeddings = []
        for text in texts:
            result = genai.embed_content(
                model=model,
                content=text,
                task_type="retrieval_document",
            )
            emb = result["embedding"]
            if self._config.normalize:
                norm = sum(x * x for x in emb) ** 0.5
                if norm > 0:
                    emb = [x / norm for x in emb]
            embeddings.append(emb)

        if self._dimension is None and embeddings:
            self._dimension = len(embeddings[0])
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self.embed("test")
        return self._dimension or 768  # embedding-001 default

    @property
    def name(self) -> str:
        return f"gemini:{self._config.model or GEMINI_EMBEDDING_MODEL}"


# Singleton global
_embedding_provider: Optional[EmbeddingProvider] = None
_provider_lock = threading.Lock()


def get_embedding_provider(config: Optional[EmbeddingConfig] = None) -> EmbeddingProvider:
    """
    Retorna o provider de embeddings global (singleton).
    
    Ordem de preferência (configurável via OD_EMBEDDING_REMOTE):
    1. remote (openai/gemini) se OD_EMBEDDING_REMOTE definido
    2. local (sentence-transformers) como fallback
    
    Args:
        config: Configuração opcional. Se None, usa config padrão/env.
    """
    global _embedding_provider

    if _embedding_provider is not None:
        return _embedding_provider

    with _provider_lock:
        if _embedding_provider is not None:
            return _embedding_provider

        if config is None:
            config = EmbeddingConfig()

        # Determina provider por env
        remote = DEFAULT_REMOTE_PROVIDER or os.getenv("OD_EMBEDDING_REMOTE", "").lower()
        if remote in ("openai", "gemini"):
            config.provider = remote
        else:
            config.provider = "local"

        if config.provider == "openai":
            _embedding_provider = OpenAIEmbeddingProvider(config)
        elif config.provider == "gemini":
            _embedding_provider = GeminiEmbeddingProvider(config)
        else:
            _embedding_provider = LocalEmbeddingProvider(config)

        _log.info("Embedding provider initialized", provider=_embedding_provider.name)
        return _embedding_provider


def reset_embedding_provider() -> None:
    """Reseta o provider global (útil para testes)."""
    global _embedding_provider
    with _provider_lock:
        _embedding_provider = None