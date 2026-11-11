"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/query_router.py
Descrição: Query Router (I4) — classificador leve que roteia a query para
           a estratégia ótima (direct, tool, rag, hybrid, llm_only).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - I4 do roadmap: Query Router (classificador leve → estratégia)
  - ROADMAP_ABSORCAO.md Fase 9-10 item I4
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from core.logger import get_logger
from core.embeddings import EmbeddingProvider, get_embedding_provider

__signature__ = "OD // CORE"

_log = get_logger("omega.core.query_router")

# Estratégias disponíveis
STRATEGY_DIRECT = "direct"
STRATEGY_TOOL = "tool"
STRATEGY_RAG = "rag"
STRATEGY_HYBRID = "hybrid"
STRATEGY_LLM_ONLY = "llm_only"

ALL_STRATEGIES = [
    STRATEGY_DIRECT,
    STRATEGY_TOOL,
    STRATEGY_RAG,
    STRATEGY_HYBRID,
    STRATEGY_LLM_ONLY,
]

# Configuração via env (lidos no __post_init__)
DEFAULT_MODEL_PATH = "data/query_router/model.pkl"
DEFAULT_FEATURES_PATH = "data/query_router/features.pkl"
DEFAULT_TRAINING_PATH = "data/query_router/training.jsonl"
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_FALLBACK_STRATEGY = STRATEGY_HYBRID


@dataclass(slots=True)
class RouterConfig:
    """Configuração do Query Router."""
    model_path: str = DEFAULT_MODEL_PATH
    features_path: str = DEFAULT_FEATURES_PATH
    training_path: str = DEFAULT_TRAINING_PATH
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    fallback_strategy: str = DEFAULT_FALLBACK_STRATEGY
    max_tfidf_features: int = 500
    use_embeddings: bool = True
    retrain_interval: int = 100  # re-treina a cada N exemplos novos

    def __post_init__(self):
        # Override via env vars (lidos no momento da instanciação)
        self.model_path = os.getenv("OD_QUERY_ROUTER_MODEL", self.model_path)
        self.features_path = os.getenv("OD_QUERY_ROUTER_FEATURES", self.features_path)
        self.training_path = os.getenv("OD_QUERY_ROUTER_TRAINING", self.training_path)
        self.confidence_threshold = float(os.getenv("OD_QUERY_ROUTER_CONFIDENCE", str(self.confidence_threshold)))
        self.fallback_strategy = os.getenv("OD_QUERY_ROUTER_FALLBACK", self.fallback_strategy)


@dataclass(slots=True)
class QueryFeatures:
    """Features extraídas de uma query."""
    # Heurísticas (bool/int)
    has_action_intent: bool = False
    is_fact_question: bool = False
    has_entity: bool = False
    query_length_tokens: int = 0
    recent_tool_use: bool = False
    
    # Categóricos (one-hot via dict)
    profile: str = ""
    role: str = ""
    
    # Vetoriais
    tfidf_vector: Optional[np.ndarray] = None
    embedding: Optional[np.ndarray] = None
    
    # Metadata
    extracted_at: float = field(default_factory=time.time)


class FeatureExtractor:
    """Extrator de features para o Query Router."""
    
    def __init__(self, config: RouterConfig, embedder: Optional[EmbeddingProvider] = None):
        self.config = config
        self._embedder = embedder or get_embedding_provider()
        self._tfidf_vectorizer = None
        self._tfidf_fitted = False
        self._lock = threading.Lock()
        
        # Stopwords PT para tokenização
        self._stopwords = {
            'a', 'o', 'as', 'os', 'de', 'da', 'do', 'das', 'dos',
            'e', 'em', 'na', 'no', 'nas', 'nos', 'um', 'uma',
            'para', 'com', 'por', 'que', 'qual', 'quais',
            'é', 'são', 'foi', 'era', 'tem', 'têm', 'ter',
            'se', 'não', 'mais', 'muito', 'bem', 'mal',
            'o', 'a', 'os', 'as', 'um', 'uma', 'uns', 'umas',
        }
    
    def _tokenize(self, text: str) -> list[str]:
        """Tokenização simples PT."""
        import re
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = [t for t in text.split() if t not in self._stopwords and len(t) > 2]
        return tokens
    
    def _detect_action_intent(self, text: str) -> bool:
        """Detecta intenção de action (heurística simples)."""
        action_keywords = {
            'liga', 'desliga', 'acende', 'apaga', 'abre', 'fecha',
            'cria', 'adiciona', 'remove', 'deleta', 'apaga',
            'agenda', 'marca', 'lembra', 'notifica',
            'executa', 'roda', 'inicia', 'para', 'reinicia',
            'define', 'configura', 'ajusta', 'muda', 'altera',
        }
        tokens = self._tokenize(text)
        return any(tok in action_keywords for tok in tokens)
    
    def _detect_fact_question(self, text: str) -> bool:
        """Detecta pergunta de fato (heurística)."""
        fact_starters = {
            'qual', 'quais', 'quem', 'onde', 'quando', 'quanto',
            'como', 'por que', 'porque', 'o que', 'qual é',
            'capital', 'população', 'área', 'distância',
        }
        tokens = self._tokenize(text)
        if not tokens:
            return False
        first = tokens[0]
        return first in fact_starters or any(t in fact_starters for t in tokens[:3])
    
    def _detect_entity(self, text: str) -> bool:
        """Detecta entidades conhecidas (heurística simples)."""
        import re
        # IPs, URLs, emails, códigos, capitais conhecidas
        patterns = [
            r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',  # IP
            r'\b[A-Z]{2,}\d{3,}\b',  # Códigos (SKU, etc)
            r'\b(brasília|paris|londres|tokyo|nova york|berlim)\b',  # Capitais
        ]
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False
    
    def fit_tfidf(self, texts: list[str]) -> None:
        """Ajusta TF-IDF vectorizer nos textos de treino."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        with self._lock:
            self._tfidf_vectorizer = TfidfVectorizer(
                max_features=self.config.max_tfidf_features,
                tokenizer=self._tokenize,
                lowercase=True,
                ngram_range=(1, 2),
            )
            self._tfidf_vectorizer.fit(texts)
            self._tfidf_fitted = True
    
    def extract(
        self,
        text: str,
        profile: str = "",
        role: str = "",
        recent_history: Optional[list[dict]] = None,
    ) -> QueryFeatures:
        """Extrai todas as features de uma query."""
        tokens = self._tokenize(text)
        
        features = QueryFeatures(
            has_action_intent=self._detect_action_intent(text),
            is_fact_question=self._detect_fact_question(text),
            has_entity=self._detect_entity(text),
            query_length_tokens=len(tokens),
            profile=profile,
            role=role,
        )
        
        # Recent tool use
        if recent_history:
            for msg in recent_history[-3:]:
                if msg.get("route", "").startswith("tool") or msg.get("route") == STRATEGY_TOOL:
                    features.recent_tool_use = True
                    break
        
        # TF-IDF
        if self._tfidf_fitted and self._tfidf_vectorizer is not None:
            try:
                tfidf = self._tfidf_vectorizer.transform([text])
                features.tfidf_vector = tfidf.toarray()[0]
            except Exception:
                pass
        
        # Embedding
        if self.config.use_embeddings:
            try:
                features.embedding = self._embedder.embed(text)
            except Exception as exc:
                _log.debug("Embedding extraction failed", error=str(exc))
        
        return features


class QueryRouter:
    """
    Query Router (I4) — classifica query e retorna estratégia ótima.
    
    Usa Logistic Regression (sklearn) com features:
    - Heurísticas booleanas (action_intent, fact_question, entity)
    - TF-IDF (500 features, unigrams+bigrams)
    - Embeddings (384-dim, sentence-transformers)
    - Categóricos (profile, role)
    """
    
    def __init__(
        self,
        config: Optional[RouterConfig] = None,
        embedder: Optional[EmbeddingProvider] = None,
    ):
        self.config = config or RouterConfig()
        self._extractor = FeatureExtractor(self.config, embedder)
        self._model = None
        self._classes = None
        self._lock = threading.RLock()
        self._training_examples: list[tuple[str, str]] = []
        self._examples_since_retrain = 0
        
        # Tenta carregar modelo existente
        if not self._load_model():
            # Se não tem modelo salvo, faz bootstrap training
            _bootstrap_training(self)
    
    def _load_model(self) -> bool:
        """Carrega modelo e vectorizer do disco."""
        model_path = Path(self.config.model_path)
        features_path = Path(self.config.features_path)
        
        if not model_path.exists() or not features_path.exists():
            return False
        
        try:
            with open(model_path, "rb") as f:
                data = pickle.load(f)
                self._model = data["model"]
                self._classes = data["classes"]
            
            with open(features_path, "rb") as f:
                feat_data = pickle.load(f)
                self._extractor._tfidf_vectorizer = feat_data["tfidf_vectorizer"]
                self._extractor._tfidf_fitted = feat_data["tfidf_fitted"]
            
            _log.info("Query Router model loaded", model=str(model_path))
            return True
        except Exception as exc:
            _log.warn("Failed to load Query Router model", error=str(exc))
            return False
    
    def _save_model(self) -> None:
        """Salva modelo e vectorizer no disco."""
        model_path = Path(self.config.model_path)
        features_path = Path(self.config.features_path)
        
        try:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(model_path, "wb") as f:
                pickle.dump({
                    "model": self._model,
                    "classes": self._classes,
                    "saved_at": time.time(),
                }, f)
            
            with open(features_path, "wb") as f:
                pickle.dump({
                    "tfidf_vectorizer": self._extractor._tfidf_vectorizer,
                    "tfidf_fitted": self._extractor._tfidf_fitted,
                }, f)
            
            _log.info("Query Router model saved", model=str(model_path))
        except Exception as exc:
            _log.error("Failed to save Query Router model", error=str(exc))
    
    def _prepare_training_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Prepara matriz de features X e labels y para treino."""
        if not self._training_examples:
            return np.array([]), np.array([])
        
        feature_vectors = []
        labels = []
        
        for text, label in self._training_examples:
            features = self._extractor.extract(text)
            vec = self._features_to_vector(features)
            if vec is not None:
                feature_vectors.append(vec)
                labels.append(label)
        
        if not feature_vectors:
            return np.array([]), np.array([])
        
        return np.vstack(feature_vectors), np.array(labels)
    
    def _features_to_vector(self, features: QueryFeatures) -> Optional[np.ndarray]:
        """Converte QueryFeatures em vetor numérico."""
        parts = []
        
        # Booleanas (0/1)
        parts.append([
            float(features.has_action_intent),
            float(features.is_fact_question),
            float(features.has_entity),
            float(features.recent_tool_use),
            float(features.query_length_tokens) / 100.0,  # normalizado
        ])
        
        # Profile one-hot (simplificado: hash)
        profile_hash = hash(features.profile) % 10 / 10.0
        parts.append([profile_hash])
        
        # TF-IDF
        if features.tfidf_vector is not None:
            parts.append(features.tfidf_vector)
        
        # Embedding
        if features.embedding is not None:
            parts.append(features.embedding)
        
        if not parts:
            return None
        
        return np.concatenate(parts)
    
    def train(self, examples: Optional[list[tuple[str, str]]] = None) -> bool:
        """
        Treina o classificador.
        
        Args:
            examples: Lista de (query, strategy_label). Se None, usa exemplos acumulados.
        
        Returns:
            True se treinou com sucesso.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        
        with self._lock:
            # Armazena exemplos como (text, label) para re-extrair features depois do TF-IDF fit
            if examples:
                for query, label in examples:
                    if label not in ALL_STRATEGIES:
                        continue
                    self._training_examples.append((query, label))
            
            if len(self._training_examples) < 10:
                _log.warn("Query Router: insufficient training examples", count=len(self._training_examples))
                return False
            
            # Fit TF-IDF vectorizer em todos os textos de treino
            texts = [q for q, _ in self._training_examples]
            self._extractor.fit_tfidf(texts)
            
            # Prepara dados (re-extrai features com TF-IDF já fitted)
            X, y = self._prepare_training_data()
            if X.size == 0:
                return False
            
            # Treina Logistic Regression com pipeline (scaler + classifier)
            self._model = Pipeline([
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    solver="lbfgs",
                    n_jobs=None,
                )),
            ])
            
            self._model.fit(X, y)
            self._classes = self._model.classes_
            self._examples_since_retrain = 0
            
            # Salva
            self._save_model()
            
            _log.info("Query Router trained", examples=len(self._training_examples), classes=list(self._classes))
            return True
    
    def classify(
        self,
        query: str,
        profile: str = "",
        role: str = "",
        recent_history: Optional[list[dict]] = None,
    ) -> str:
        """
        Classifica uma query e retorna a estratégia.
        
        Args:
            query: Texto da query.
            profile: Perfil do usuário.
            role: Papel (admin/user/anonymous).
            recent_history: Últimas mensagens (para feature recent_tool_use).
        
        Returns:
            Estratégia: direct, tool, rag, hybrid, llm_only.
        """
        with self._lock:
            if self._model is None:
                return self.config.fallback_strategy
            
            features = self._extractor.extract(query, profile, role, recent_history)
            vec = self._features_to_vector(features)
            
            if vec is None:
                return self.config.fallback_strategy
            
            try:
                # Predição com probabilidades
                proba = self._model.predict_proba([vec])[0]
                pred_idx = np.argmax(proba)
                confidence = proba[pred_idx]
                predicted = self._classes[pred_idx]
                
                # Threshold de confiança
                if confidence < self.config.confidence_threshold:
                    _log.debug(
                        "Query Router: low confidence, using fallback",
                        confidence=round(confidence, 3),
                        threshold=self.config.confidence_threshold,
                        predicted=predicted,
                    )
                    return self.config.fallback_strategy
                
                return str(predicted)
            except Exception as exc:
                _log.warn("Query Router prediction failed", error=str(exc))
                return self.config.fallback_strategy
    
    def add_training_example(self, query: str, strategy: str) -> None:
        """Adiciona exemplo de treino (para aprendizado online)."""
        with self._lock:
            if strategy not in ALL_STRATEGIES:
                return
            self._training_examples.append((query, strategy))
            self._examples_since_retrain += 1
            
            # Auto-retrain periódico
            if self._examples_since_retrain >= self.config.retrain_interval:
                self.train()
    
    def get_training_stats(self) -> dict[str, Any]:
        """Retorna estatísticas do dataset de treino."""
        with self._lock:
            labels = [lbl for _, lbl in self._training_examples]
            counter = Counter(labels)
            return {
                "total_examples": len(self._training_examples),
                "per_class": dict(counter),
                "classes": list(self._classes) if self._classes is not None else [],
                "model_trained": self._model is not None,
                "examples_since_retrain": self._examples_since_retrain,
            }
    
    def export_training_data(self, path: Optional[str] = None) -> int:
        """Exporta dados de treino para JSONL."""
        export_path = path or self.config.training_path
        Path(export_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(export_path, "w", encoding="utf-8") as f:
            for text, label in self._training_examples:
                f.write(json.dumps({
                    "query": text,
                    "label": label,
                }, ensure_ascii=False) + "\n")
        
        return len(self._training_examples)
    
    def load_training_data(self, path: Optional[str] = None) -> int:
        """Carrega dados de treino de JSONL."""
        load_path = path or self.config.training_path
        if not Path(load_path).exists():
            return 0
        
        count = 0
        with open(load_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    self._training_examples.append((data["query"], data["label"]))
                    count += 1
                except Exception:
                    continue
        
        if count > 0:
            self.train()  # Re-treina com dados carregados
        
        return count


# Singleton global
_query_router: Optional[QueryRouter] = None
_router_lock = threading.Lock()


def get_query_router(config: Optional[RouterConfig] = None, embedder: Optional[EmbeddingProvider] = None) -> QueryRouter:
    """Retorna o Query Router global (singleton)."""
    global _query_router
    
    if _query_router is not None:
        return _query_router
    
    with _router_lock:
        if _query_router is not None:
            return _query_router
        
        _query_router = QueryRouter(config, embedder)
        
        # Tenta carregar dados de treino existentes
        _query_router.load_training_data()
        
        # Se não tem modelo, treina com heurísticas bootstrap
        if _query_router._model is None:
            _bootstrap_training(_query_router)
        
        return _query_router


def _bootstrap_training(router: QueryRouter) -> None:
    """Treino bootstrap com exemplos heurísticos (sem dados históricos)."""
    bootstrap_examples = [
        # Direct
        ("oi", STRATEGY_DIRECT),
        ("olá", STRATEGY_DIRECT),
        ("bom dia", STRATEGY_DIRECT),
        ("tchau", STRATEGY_DIRECT),
        ("obrigado", STRATEGY_DIRECT),
        ("qual a data de hoje", STRATEGY_DIRECT),
        ("que horas são", STRATEGY_DIRECT),
        
        # Tool
        ("liga a luz da sala", STRATEGY_TOOL),
        ("desliga o ar condicionado", STRATEGY_TOOL),
        ("abre a porta", STRATEGY_TOOL),
        ("cria compromisso amanhã 15h", STRATEGY_TOOL),
        ("adiciona evento na agenda", STRATEGY_TOOL),
        ("2 + 2", STRATEGY_TOOL),
        ("quanto é 10 * 5", STRATEGY_TOOL),
        
        # RAG
        ("qual a capital do brasil", STRATEGY_RAG),
        ("quem foi albert einstein", STRATEGY_RAG),
        ("população do japão", STRATEGY_RAG),
        ("distância terra lua", STRATEGY_RAG),
        ("como funciona o motor diesel", STRATEGY_RAG),
        
        # Hybrid
        ("comparar iphone 15 vs samsung s24", STRATEGY_HYBRID),
        ("melhor notebook para programação 2024", STRATEGY_HYBRID),
        ("prós e contras de carro elétrico", STRATEGY_HYBRID),
        
        # LLM Only
        ("escreva um poema sobre o mar", STRATEGY_LLM_ONLY),
        ("me dê uma ideia de presente", STRATEGY_LLM_ONLY),
        ("conte uma piada", STRATEGY_LLM_ONLY),
        ("qual sua opinião sobre IA", STRATEGY_LLM_ONLY),
    ]
    
    router.train(bootstrap_examples)
    _log.info("Query Router bootstrap training completed", examples=len(bootstrap_examples))


def reset_query_router() -> None:
    """Reseta o router global (útil para testes)."""
    global _query_router
    with _router_lock:
        _query_router = None