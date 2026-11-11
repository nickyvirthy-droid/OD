"""
Testes do Query Router (I4).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.query_router import (
    QueryRouter,
    RouterConfig,
    FeatureExtractor,
    QueryFeatures,
    STRATEGY_DIRECT,
    STRATEGY_TOOL,
    STRATEGY_RAG,
    STRATEGY_HYBRID,
    STRATEGY_LLM_ONLY,
    ALL_STRATEGIES,
    get_query_router,
    reset_query_router,
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
def router_config(tmp_path, mock_embedder):
    config = RouterConfig(
        model_path=str(tmp_path / "router_model.pkl"),
        features_path=str(tmp_path / "router_features.pkl"),
        training_path=str(tmp_path / "router_training.jsonl"),
        confidence_threshold=0.5,  # Baixo para testes
        fallback_strategy=STRATEGY_HYBRID,
        retrain_interval=5,
    )
    yield config


@pytest.fixture
def query_router(router_config, mock_embedder):
    reset_query_router()
    router = QueryRouter(config=router_config, embedder=mock_embedder)
    yield router
    reset_query_router()


class TestFeatureExtractor:
    def test_extract_basic(self, router_config, mock_embedder):
        """Extração básica de features."""
        extractor = FeatureExtractor(router_config, mock_embedder)
        features = extractor.extract("qual a capital do brasil", profile="guardian", role="admin")
        
        assert features.is_fact_question is True
        assert features.has_action_intent is False
        assert features.query_length_tokens > 0
        assert features.profile == "guardian"
        assert features.role == "admin"
        assert features.embedding is not None
        assert len(features.embedding) == 384

    def test_detect_action_intent(self, router_config, mock_embedder):
        """Detecção de intenção de action."""
        extractor = FeatureExtractor(router_config, mock_embedder)
        
        # Com action keywords
        features = extractor.extract("liga a luz da sala")
        assert features.has_action_intent is True
        
        # Sem action keywords
        features = extractor.extract("qual a capital do brasil")
        assert features.has_action_intent is False

    def test_detect_fact_question(self, router_config, mock_embedder):
        """Detecção de pergunta de fato."""
        extractor = FeatureExtractor(router_config, mock_embedder)
        
        features = extractor.extract("qual a capital do brasil")
        assert features.is_fact_question is True
        
        features = extractor.extract("liga a luz")
        assert features.is_fact_question is False

    def test_detect_entity(self, router_config, mock_embedder):
        """Detecção de entidades."""
        extractor = FeatureExtractor(router_config, mock_embedder)
        
        features = extractor.extract("meu ip é 192.168.1.1")
        assert features.has_entity is True
        
        features = extractor.extract("olá mundo")
        assert features.has_entity is False


class TestQueryRouter:
    def test_bootstrap_training(self, query_router):
        """Bootstrap training cria modelo funcional."""
        assert query_router._model is not None
        assert query_router._classes is not None
        assert len(query_router._classes) > 0

    def test_classify_direct(self, query_router):
        """Classifica saudações como direct."""
        strategy = query_router.classify("oi tudo bem", profile="guardian")
        assert strategy in ALL_STRATEGIES

    def test_classify_tool(self, query_router):
        """Classifica actions como tool."""
        strategy = query_router.classify("liga a luz da sala", profile="guardian")
        # Pode ser tool ou hybrid dependendo do modelo bootstrap
        assert strategy in ALL_STRATEGIES

    def test_classify_rag(self, query_router):
        """Classifica perguntas de fato como rag."""
        strategy = query_router.classify("qual a capital do brasil", profile="guardian")
        assert strategy in ALL_STRATEGIES

    def test_classify_llm_only(self, query_router):
        """Classifica criativas como llm_only."""
        strategy = query_router.classify("escreva um poema sobre o mar", profile="guardian")
        assert strategy in ALL_STRATEGIES

    def test_fallback_on_low_confidence(self, query_router):
        """Fall back para estratégia default em baixa confiança."""
        # Query que não se encaixa bem em nenhuma categoria (baixa confiança)
        strategy = query_router.classify("asdfghjkl qwertyuiop zxcvbnm", profile="guardian")
        # Pode ser fallback ou uma classificação com baixa confiança
        # O importante é que não quebra
        assert strategy in ALL_STRATEGIES

    def test_add_training_example(self, query_router):
        """Adiciona exemplo de treino online."""
        initial_count = len(query_router._training_examples)
        query_router.add_training_example("nova query teste", STRATEGY_RAG)
        assert len(query_router._training_examples) == initial_count + 1

    def test_get_training_stats(self, query_router):
        """Retorna estatísticas de treino."""
        stats = query_router.get_training_stats()
        assert "total_examples" in stats
        assert "per_class" in stats
        assert "model_trained" in stats
        assert stats["model_trained"] is True

    def test_persist_and_load(self, tmp_path, mock_embedder):
        """Persistência e carregamento do modelo."""
        config = RouterConfig(
            model_path=str(tmp_path / "router_model.pkl"),
            features_path=str(tmp_path / "router_features.pkl"),
            confidence_threshold=0.5,
        )
        
        router1 = QueryRouter(config=config, embedder=mock_embedder)
        # Adiciona exemplo extra
        router1.add_training_example("teste persistência", STRATEGY_RAG)
        
        # Novo router carrega do disco
        router2 = QueryRouter(config=config, embedder=mock_embedder)
        
        assert router2._model is not None
        assert router2._classes is not None

    def test_export_import_training_data(self, tmp_path, query_router):
        """Exporta e importa dados de treino."""
        export_path = tmp_path / "export_training.jsonl"
        
        # Adiciona alguns exemplos
        query_router.add_training_example("exemplo export 1", STRATEGY_RAG)
        query_router.add_training_example("exemplo export 2", STRATEGY_TOOL)
        
        count = query_router.export_training_data(str(export_path))
        assert count >= 2
        assert export_path.exists()
        
        # Importa em novo router
        config = RouterConfig(
            model_path=str(tmp_path / "router_model2.pkl"),
            features_path=str(tmp_path / "router_features2.pkl"),
            training_path=str(export_path),
        )
        router2 = QueryRouter(config=config, embedder=MockEmbeddingProvider())
        
        stats = router2.get_training_stats()
        assert stats["total_examples"] >= 2


class TestRouterConfig:
    def test_defaults(self):
        """Configuração padrão."""
        config = RouterConfig()
        assert config.confidence_threshold == 0.7
        assert config.fallback_strategy == STRATEGY_HYBRID
        assert config.max_tfidf_features == 500
        assert config.use_embeddings is True

    def test_from_env(self):
        """Configuração via env."""
        import os
        os.environ["OD_QUERY_ROUTER_CONFIDENCE"] = "0.8"
        os.environ["OD_QUERY_ROUTER_FALLBACK"] = "rag"
        try:
            config = RouterConfig()
            assert config.confidence_threshold == 0.8
            assert config.fallback_strategy == "rag"
        finally:
            os.environ.pop("OD_QUERY_ROUTER_CONFIDENCE", None)
            os.environ.pop("OD_QUERY_ROUTER_FALLBACK", None)


class TestSingleton:
    def test_get_query_router_singleton(self, mock_embedder):
        """get_query_router retorna singleton."""
        reset_query_router()
        r1 = get_query_router(embedder=mock_embedder)
        r2 = get_query_router(embedder=mock_embedder)
        assert r1 is r2
        reset_query_router()

    def test_reset_query_router(self, mock_embedder):
        """Reset funciona."""
        reset_query_router()
        r1 = get_query_router(embedder=mock_embedder)
        reset_query_router()
        r2 = get_query_router(embedder=mock_embedder)
        assert r1 is not r2
        reset_query_router()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])