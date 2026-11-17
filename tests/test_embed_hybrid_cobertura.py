"""
Testes de cobertura — core/embeddings.py e core/hybrid_search.py.

Objetivo: atacar a dívida de cobertura dos módulos de memória/RAG
(provider de embeddings unificado + Hybrid Search BM25/Dense/RRF)
sem tocar em produção, docs ou configuração.

Segurança (regra da tarefa — NENHUMA rede / NENHUM provedor real):
  - `openai`, `google.generativeai` e `sentence_transformers` são
    substituídos por módulos falsos via `monkeypatch.setitem(sys.modules, ...)`.
  - BM25, Dense, RRF e persistência são Python puro.
  - Todo arquivo é gravado apenas em `tmp_path`.
  - Variáveis de ambiente (chaves, OD_EMBEDDING_REMOTE, OD_HYBRID_*)
    são controladas pelo `monkeypatch` e restauradas ao final de cada teste.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import hashlib
import json
import sys
import types

import pytest

from core import embeddings as emb
from core import hybrid_search as hs
from core.embeddings import (
    EmbeddingConfig,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from core.hybrid_search import (
    BM25Index,
    CrossEncoderReranker,
    DenseIndex,
    Document,
    HybridRetriever,
    HybridSearchConfig,
)


# ---------------------------------------------------------------------------
# Falsos locais (sem rede, sem pacote remoto instalado)
# ---------------------------------------------------------------------------


class _ArrayFalso(list):
    """Lista com `.tolist()` imitando o retorno de `SentenceTransformer.encode`."""

    def tolist(self) -> list:
        return [list(item) if isinstance(item, list) else item for item in self]


class _ModeloLocalFalso:
    """Modelo local falso: devolve sempre vetores de dimensão 4."""

    def __init__(self, nome_modelo: str):
        self.nome_modelo = nome_modelo

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            return _ArrayFalso([0.25, 0.5, 0.75, 1.0])
        return _ArrayFalso([_ArrayFalso([0.25, 0.5, 0.75, 1.0]) for _ in texts])


class _ModeloLocalQuebrado:
    """Modelo local cuja construção explode (caminho de erro genérico)."""

    def __init__(self, nome_modelo: str):
        raise ValueError("modelo indisponível")


def _modulo_st_falso(classe_modelo) -> types.ModuleType:
    """Módulo `sentence_transformers` falso com uma classe de modelo."""
    modulo = types.ModuleType("sentence_transformers")
    modulo.SentenceTransformer = classe_modelo
    return modulo


class _ApiEmbeddingsFalsa:
    """`client.embeddings` falso da OpenAI."""

    def __init__(self, vetores=None):
        self._vetores = vetores
        self.chamadas: list[dict] = []

    def create(self, model, input, encoding_format):
        self.chamadas.append(
            {"model": model, "input": list(input), "encoding_format": encoding_format}
        )
        if self._vetores is not None:
            dados = [types.SimpleNamespace(embedding=list(v)) for v in self._vetores]
        else:
            # Um vetor por texto de entrada, norma 5 (3-4-5) para testar normalização.
            dados = [types.SimpleNamespace(embedding=[3.0, 4.0]) for _ in input]
        return types.SimpleNamespace(data=dados)


def _modulo_openai_falso(vetores=None) -> types.ModuleType:
    """Módulo `openai` falso: `OpenAI(api_key=...)` nunca sai da máquina."""
    api = _ApiEmbeddingsFalsa(vetores)
    modulo = types.ModuleType("openai")
    modulo.api_falsa = api

    class OpenAI:  # noqa: N801 - nome igual ao pacote real
        def __init__(self, api_key: str):
            self.api_key = api_key
            self.embeddings = api

    modulo.OpenAI = OpenAI
    return modulo


def _modulo_gemini_falso(vetores=None) -> types.ModuleType:
    """Módulo `google.generativeai` falso (configure + embed_content)."""
    registro = {"api_key": None, "chamadas": []}
    modulo = types.ModuleType("google.generativeai")
    modulo.registro = registro

    def configure(api_key: str) -> None:
        registro["api_key"] = api_key

    def embed_content(model, content, task_type):
        registro["chamadas"].append(
            {"model": model, "content": content, "task_type": task_type}
        )
        return {"embedding": list(vetores) if vetores is not None else [3.0, 4.0]}

    modulo.configure = configure
    modulo.embed_content = embed_content
    return modulo


class _ModeloCrossEncoderFalso:
    """CrossEncoder falso: `__init__` simples, sem download."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def predict(self, pairs, show_progress_bar=False):
        return [float(len(par[1])) for par in pairs]


class _CrossEncoderComScores:
    """CrossEncoder falso com pontuação pré-definida por candidato."""

    def __init__(self, scores: list[float]):
        self._scores = scores

    def predict(self, pairs, show_progress_bar=False):
        assert len(pairs) == len(self._scores)
        return list(self._scores)


class _CrossEncoderQuebrado:
    """CrossEncoder cuja predição explode (fallback de ordem original)."""

    def predict(self, pairs, show_progress_bar=False):
        raise RuntimeError("predição do cross-encoder falhou")


def _modulo_cross_encoder_falso(classe_modelo) -> types.ModuleType:
    modulo = types.ModuleType("sentence_transformers")
    modulo.CrossEncoder = classe_modelo
    return modulo


class _EmbedderHash:
    """Provider local baseado em hash md5 — determinístico e sem rede."""

    def __init__(self, dim: int = 8):
        self.dimension = dim
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        if text in self._cache:
            return self._cache[text]
        digest = hashlib.md5(text.encode()).hexdigest()
        valores = [int(digest[i : i + 2], 16) / 255.0 for i in range(0, 32, 2)]
        while len(valores) < self.dimension:
            valores.extend(valores[: min(len(valores), self.dimension - len(valores))])
        resultado = valores[: self.dimension]
        self._cache[text] = resultado
        return resultado

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    @property
    def name(self) -> str:
        return "hash-local"


class _EmbedderQuebrado:
    """Provider que explode em qualquer chamada (fallback de add_document)."""

    dimension = 4
    name = "quebrado"

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("falha simulada ao gerar embedding")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("falha simulada ao gerar embeddings")


class _EmbedderFalhaNaConsulta(_EmbedderHash):
    """Provider hash que só explode na consulta (add_document funciona)."""

    def __init__(self):
        super().__init__(dim=8)
        self.falha_na_consulta = False

    def embed(self, text: str) -> list[float]:
        if self.falha_na_consulta:
            raise RuntimeError("falha simulada na consulta")
        return super().embed(text)


# ---------------------------------------------------------------------------
# core/embeddings.py
# ---------------------------------------------------------------------------


class TestLocalEmbeddingProvider:
    """Provider local (sentence-transformers) — tudo com módulo falso."""

    def test_carrega_modelo_e_gera_embeddings(self, monkeypatch):
        """Carrega modelo falso, gera embedding simples/batch e expõe metadados."""
        monkeypatch.setitem(
            sys.modules, "sentence_transformers", _modulo_st_falso(_ModeloLocalFalso)
        )
        provider = LocalEmbeddingProvider(EmbeddingConfig())

        assert provider.dimension == 4
        assert provider.embed("olá mundo") == [0.25, 0.5, 0.75, 1.0]

        lote = provider.embed_batch(["alpha", "beta"])
        assert lote == [[0.25, 0.5, 0.75, 1.0], [0.25, 0.5, 0.75, 1.0]]
        assert provider.name.startswith("local:")

    def test_pacote_ausente_levanta_runtimeerror(self, monkeypatch):
        """Sem sentence-transformers instalado o provider falha com mensagem clara."""
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        provider = LocalEmbeddingProvider(EmbeddingConfig())

        with pytest.raises(RuntimeError, match="sentence-transformers não instalado"):
            provider.embed("texto")

    def test_erro_generico_no_modelo_levanta_runtimeerror(self, monkeypatch):
        """Erro inesperado na carga vira RuntimeError com o original no texto."""
        monkeypatch.setitem(
            sys.modules, "sentence_transformers", _modulo_st_falso(_ModeloLocalQuebrado)
        )
        provider = LocalEmbeddingProvider(EmbeddingConfig())

        with pytest.raises(RuntimeError, match="Falha ao carregar modelo local"):
            provider.embed_batch(["texto"])


class TestOpenAIEmbeddingProvider:
    """Provider OpenAI — cliente e resposta 100% falsos (zero rede)."""

    def test_sem_chave_de_api_levanta_runtimeerror(self, monkeypatch):
        """Sem OPENAI_API_KEY(_2) o cliente nem é criado."""
        monkeypatch.setitem(sys.modules, "openai", _modulo_openai_falso())
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY2", raising=False)
        provider = OpenAIEmbeddingProvider(EmbeddingConfig())

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY não configurada"):
            provider.embed("texto")

    def test_pacote_ausente_levanta_runtimeerror(self, monkeypatch):
        """Pacote openai ausente → RuntimeError orientando a instalação."""
        monkeypatch.setitem(sys.modules, "openai", None)
        provider = OpenAIEmbeddingProvider(EmbeddingConfig())

        with pytest.raises(RuntimeError, match="openai não instalado"):
            provider.embed("texto")

    def test_embed_normaliza_l2_e_descobre_dimensao(self, monkeypatch):
        """Batch normaliza para norma 1, grava dimensão e usa o model padrão."""
        modulo = _modulo_openai_falso()
        monkeypatch.setitem(sys.modules, "openai", modulo)
        monkeypatch.setenv("OPENAI_API_KEY", "chave-falsa")
        provider = OpenAIEmbeddingProvider(EmbeddingConfig(normalize=True))

        lote = provider.embed_batch(["alpha", "beta"])
        assert lote == [pytest.approx([0.6, 0.8]), pytest.approx([0.6, 0.8])]
        assert provider.dimension == 2
        assert provider.name.startswith("openai:")
        assert modulo.api_falsa.chamadas[0]["input"] == ["alpha", "beta"]
        assert modulo.api_falsa.chamadas[0]["encoding_format"] == "float"

        # embed() de texto único delega ao batch (1 chamada → 1 vetor)
        assert provider.embed("gama") == pytest.approx([0.6, 0.8])

    def test_embed_sem_normalizar_preserva_vetor(self, monkeypatch):
        """normalize=False devolve o vetor cru da API."""
        monkeypatch.setitem(sys.modules, "openai", _modulo_openai_falso())
        monkeypatch.setenv("OPENAI_API_KEY", "chave-falsa")
        provider = OpenAIEmbeddingProvider(EmbeddingConfig(normalize=False))

        assert provider.embed("texto") == [3.0, 4.0]

    def test_vetor_nulo_nao_divide_por_zero(self, monkeypatch):
        """Vetor de norma 0 não é dividido (nenhuma dimensão vira NaN/inf)."""
        monkeypatch.setitem(
            sys.modules, "openai", _modulo_openai_falso(vetores=[[0.0, 0.0]])
        )
        monkeypatch.setenv("OPENAI_API_KEY", "chave-falsa")
        provider = OpenAIEmbeddingProvider(EmbeddingConfig(normalize=True))

        assert provider.embed("texto") == [0.0, 0.0]

    def test_dimensao_descoberta_na_primeira_chamada(self, monkeypatch):
        """Dimensão desconhecida força um embed('test') que a descobre."""
        monkeypatch.setitem(sys.modules, "openai", _modulo_openai_falso())
        monkeypatch.setenv("OPENAI_API_KEY", "chave-falsa")
        provider = OpenAIEmbeddingProvider(EmbeddingConfig(normalize=True))

        assert provider.dimension == 2  # descoberta via embed("test")

    def test_dimensao_ja_conhecida_nao_chama_api(self, monkeypatch):
        """Com dimensão conhecida o property não força nova chamada."""
        provider = OpenAIEmbeddingProvider(EmbeddingConfig())
        provider._dimension = 7
        assert provider.dimension == 7


class TestGeminiEmbeddingProvider:
    """Provider Gemini — módulo `google.generativeai` falso."""

    def test_pacote_ausente_levanta_runtimeerror(self, monkeypatch):
        """google.generativeai ausente → RuntimeError com instrução de instalação."""
        monkeypatch.setitem(sys.modules, "google.generativeai", None)
        provider = GeminiEmbeddingProvider(EmbeddingConfig())

        with pytest.raises(RuntimeError, match="google-generativeai não instalado"):
            provider.embed("texto")

    def test_sem_chave_de_api_levanta_runtimeerror(self, monkeypatch):
        """Sem GEMINI_API_KEY o embed falha antes de qualquer chamada."""
        monkeypatch.setitem(sys.modules, "google.generativeai", _modulo_gemini_falso())
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiEmbeddingProvider(EmbeddingConfig())

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY não configurada"):
            provider.embed("texto")

    def test_embed_normaliza_e_usa_task_type_de_busca(self, monkeypatch):
        """Normaliza para L2, configura a chave e usa retrieval_document."""
        modulo = _modulo_gemini_falso(vetores=[3.0, 4.0])
        monkeypatch.setitem(sys.modules, "google.generativeai", modulo)
        monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
        provider = GeminiEmbeddingProvider(EmbeddingConfig(normalize=True))

        assert provider.embed("documento") == pytest.approx([0.6, 0.8])
        assert modulo.registro["api_key"] == "chave-falsa"
        assert modulo.registro["chamadas"][0]["task_type"] == "retrieval_document"

        lote = provider.embed_batch(["a", "b", "c"])
        assert len(lote) == 3
        assert provider.dimension == 2
        assert provider.name.startswith("gemini:")

    def test_embed_sem_normalizar_preserva_vetor(self, monkeypatch):
        """normalize=False devolve o vetor cru do Gemini."""
        monkeypatch.setitem(
            sys.modules, "google.generativeai", _modulo_gemini_falso(vetores=[3.0, 4.0])
        )
        monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
        provider = GeminiEmbeddingProvider(EmbeddingConfig(normalize=False))

        assert provider.embed("texto") == [3.0, 4.0]

    def test_dimensao_dispara_embed_de_descoberta(self, monkeypatch):
        """Dimensão desconhecida força um embed('test') para descobrir."""
        modulo = _modulo_gemini_falso()
        monkeypatch.setitem(sys.modules, "google.generativeai", modulo)
        monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
        provider = GeminiEmbeddingProvider(EmbeddingConfig())

        assert provider.dimension == 2
        assert modulo.registro["chamadas"][0]["content"] == "test"

    def test_dimensao_ja_conhecida_nao_chama_embed(self, monkeypatch):
        """Com dimensão conhecida o property não gera novo embed."""
        provider = GeminiEmbeddingProvider(EmbeddingConfig())
        provider._dimension = 5
        assert provider.dimension == 5


class TestSingletonDoProvider:
    """`get_embedding_provider` (singleton) — sem tocar em rede real."""

    def test_fallback_local_sem_remote_configurado(self, monkeypatch):
        """Sem OD_EMBEDDING_REMOTE o provider é o local e é reutilizado."""
        monkeypatch.setattr(emb, "_embedding_provider", None)
        monkeypatch.setattr(emb, "DEFAULT_REMOTE_PROVIDER", "")
        monkeypatch.delenv("OD_EMBEDDING_REMOTE", raising=False)

        provider = get_embedding_provider()
        assert isinstance(provider, LocalEmbeddingProvider)
        assert get_embedding_provider() is provider

    def test_remote_openai_via_env(self, monkeypatch):
        """OD_EMBEDDING_REMOTE=openai instancia o provider OpenAI (lazy)."""
        monkeypatch.setattr(emb, "_embedding_provider", None)
        monkeypatch.setattr(emb, "DEFAULT_REMOTE_PROVIDER", "")
        monkeypatch.setenv("OD_EMBEDDING_REMOTE", "openai")

        provider = get_embedding_provider()
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider.name.startswith("openai:")

    def test_remote_gemini_via_env(self, monkeypatch):
        """OD_EMBEDDING_REMOTE=gemini instancia o provider Gemini (lazy)."""
        monkeypatch.setattr(emb, "_embedding_provider", None)
        monkeypatch.setattr(emb, "DEFAULT_REMOTE_PROVIDER", "")
        monkeypatch.setenv("OD_EMBEDDING_REMOTE", "gemini")

        provider = get_embedding_provider()
        assert isinstance(provider, GeminiEmbeddingProvider)
        assert provider.name.startswith("gemini:")

    def test_lock_eh_double_checked_quando_outro_thread_termina_primeiro(
        self, monkeypatch
    ):
        """Simula a corrida do double-checked locking.

        No mundo real outro thread cria o provider enquanto este aguarda a
        trava; ao adquiri-la, a linha interna do `if` enxerga o provider já
        pronto e devolve sem recriar. A trava falsa reproduz esse instante
        de forma determinística (sem sleeps, sem threads soltas).
        """
        sentinela = object()
        trava_real = emb._provider_lock

        class _TravaQueAntecipa:
            def __enter__(self):
                emb._embedding_provider = sentinela
                return trava_real.__enter__()

            def __exit__(self, *args):
                return trava_real.__exit__(*args)

        monkeypatch.setattr(emb, "_embedding_provider", None)
        monkeypatch.setattr(emb, "_provider_lock", _TravaQueAntecipa())

        assert get_embedding_provider() is sentinela

    def test_reset_embedding_provider_zera_o_singleton(self, monkeypatch):
        """reset_embedding_provider() limpa o provider global sob a trava."""
        monkeypatch.setattr(
            emb,
            "_embedding_provider",
            LocalEmbeddingProvider(EmbeddingConfig()),
        )

        emb.reset_embedding_provider()

        assert emb._embedding_provider is None


# ---------------------------------------------------------------------------
# core/hybrid_search.py
# ---------------------------------------------------------------------------


@pytest.fixture
def embedder():
    """Embedder hash local (padrão dos testes existentes — sem rede)."""
    return _EmbedderHash()


@pytest.fixture
def retriever(tmp_path, embedder):
    """Retriever híbrido com reranker desabilitado e índice em tmp_path."""
    config = HybridSearchConfig(
        dense_top_k=10,
        bm25_top_k=10,
        rerank_top_k=5,
        final_top_k=3,
        enable_reranker=False,
    )
    return HybridRetriever(
        config=config, embedder=embedder, index_dir=tmp_path / "indice"
    )


class TestBM25Bordas:
    """Bordas do índice BM25: remoção, readição e buscas vazias."""

    def test_readicao_do_mesmo_id_substitui_documento(self):
        """Readicionar o mesmo id remove o documento antigo do índice."""
        bm25 = BM25Index()
        bm25.add(Document("1", "alpha beta", bm25_tokens=["alpha", "beta"]))
        bm25.add(Document("1", "alpha gama", bm25_tokens=["alpha", "gama"]))

        assert len(bm25) == 1
        assert [doc_id for doc_id, _ in bm25.search(["gama"])] == ["1"]
        # O token antigo ("beta") saiu das frequências junto com o doc velho.
        assert bm25.search(["beta"]) == []

    def test_remove_id_inexistente_retorna_false(self):
        """Remover id que não existe é um no-op com False."""
        bm25 = BM25Index()
        assert bm25.remove("nao-existe") is False

    def test_remove_doc_interno_com_id_ausente_e_defensivo(self):
        """Caminho defensivo de `_remove_doc` (só alcançável por chamada interna)."""
        bm25 = BM25Index()
        bm25._remove_doc("fantasma")
        assert len(bm25) == 0

    def test_recalc_media_zerada_sem_documentos(self):
        """Sem documentos a média de comprimento volta a 0.0 (caminho defensivo)."""
        bm25 = BM25Index()
        bm25.add(Document("1", "abc", bm25_tokens=["abc"]))
        bm25.clear()
        bm25._recalc_avg_length()
        assert bm25._avg_doc_length == 0.0

    def test_busca_sem_documentos_ou_sem_tokens_retorna_vazio(self):
        """Índice vazio ou consulta sem tokens não devolve nada."""
        bm25 = BM25Index()
        assert bm25.search(["qualquer"]) == []

        bm25.add(Document("1", "abc", bm25_tokens=["abc"]))
        assert bm25.search([]) == []

    def test_remove_existente_retorna_true_e_limpa_frequencias(self):
        """Remover doc existente devolve True e apaga token do índice."""
        bm25 = BM25Index()
        bm25.add(Document("1", "abc", bm25_tokens=["abc"]))

        assert bm25.remove("1") is True
        assert len(bm25) == 0
        assert bm25.search(["abc"]) == []

    def test_token_presente_em_outro_doc_pula_documento_sem_ele(self):
        """Doc que não contém o token é pulado no laço de scoring."""
        bm25 = BM25Index()
        bm25.add(Document("1", "alpha", bm25_tokens=["alpha"]))
        bm25.add(Document("2", "beta", bm25_tokens=["beta"]))

        resultados = bm25.search(["alpha"])

        assert [doc_id for doc_id, _ in resultados] == ["1"]


class TestDenseBordas:
    """Bordas do índice denso: overwrite, docs sem embedding e cosseno."""

    def test_readicao_do_mesmo_id_substitui_embedding(self):
        """Readicionar sobrescreve o embedding sem duplicar o doc."""
        dense = DenseIndex(_EmbedderHash())
        dense.add(Document("1", "a", embedding=[1.0, 0.0]))
        dense.add(Document("1", "b", embedding=[0.0, 1.0]))

        assert len(dense) == 1
        assert dense.search([0.0, 1.0])[0] == ("1", pytest.approx(1.0))

    def test_busca_em_indice_vazio_ou_com_query_vazia(self):
        """Índice vazio ou query vazia → lista vazia."""
        dense = DenseIndex(_EmbedderHash())
        assert dense.search([0.1, 0.2]) == []

        dense.add(Document("1", "a", embedding=[1.0, 0.0]))
        assert dense.search([]) == []

    def test_doc_sem_embedding_e_ignorado_na_busca(self):
        """Doc sem embedding não entra na lista de scores."""
        embedder = _EmbedderHash()
        dense = DenseIndex(embedder)
        dense.add(Document("sem", "x", embedding=[]))
        dense.add(Document("com", "y", embedding=embedder.embed("y")))

        resultados = dense.search(embedder.embed("y"), top_k=5)
        assert [doc_id for doc_id, _ in resultados] == ["com"]

    def test_cosine_similarity_bordas(self):
        """Vetores vazios, de tamanhos diferentes ou nulos devolvem 0.0."""
        cosine = DenseIndex._cosine_similarity
        assert cosine([], [1.0]) == 0.0
        assert cosine([1.0], [1.0, 2.0]) == 0.0
        assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_len_do_indice(self):
        """`len(dense)` reflete o número de documentos indexados."""
        dense = DenseIndex(_EmbedderHash())
        dense.add(Document("1", "a", embedding=[1.0]))
        assert len(dense) == 1
        dense.remove("1")
        assert len(dense) == 0

    def test_clear_zera_o_indice(self):
        """clear() esvazia o índice denso por completo."""
        dense = DenseIndex(_EmbedderHash())
        dense.add(Document("1", "a", embedding=[1.0]))
        dense.clear()
        assert len(dense) == 0
        assert dense.search([1.0]) == []


class TestCrossEncoderReranker:
    """Cross-encoder: carga do modelo (falso), rerank e fallbacks."""

    def test_init_guarda_nome_do_modelo(self):
        """Construtor guarda o nome e ainda não carrega nada."""
        reranker = CrossEncoderReranker("modelo/qualquer")
        assert reranker._model is None

    def test_load_model_sucesso_com_modulo_falso(self, monkeypatch):
        """Carrega um CrossEncoder falso quando o pacote existe."""
        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            _modulo_cross_encoder_falso(_ModeloCrossEncoderFalso),
        )
        reranker = CrossEncoderReranker("cross-encoder/falso")
        reranker._load_model()

        assert isinstance(reranker._model, _ModeloCrossEncoderFalso)
        # Segunda chamada é no-op (double-checked locking já coberto).
        reranker._load_model()
        assert isinstance(reranker._model, _ModeloCrossEncoderFalso)

    def test_load_model_sem_pacote(self, monkeypatch):
        """sentence-transformers ausente → RuntimeError orientando a instalação."""
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        reranker = CrossEncoderReranker()

        with pytest.raises(RuntimeError, match="sentence-transformers não instalado"):
            reranker._load_model()

    def test_load_model_erro_generico(self, monkeypatch):
        """Falha inesperada na carga vira RuntimeError com o original no texto."""
        class _CrossEncoderQueExplode:
            def __init__(self, model_name):
                raise ValueError("download bloqueado")

        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            _modulo_cross_encoder_falso(_CrossEncoderQueExplode),
        )
        reranker = CrossEncoderReranker()

        with pytest.raises(RuntimeError, match="Falha ao carregar reranker"):
            reranker._load_model()

    def test_rerank_sem_candidatos_retorna_vazio(self):
        """Sem candidatos não há o que reordenar (nem modelo é carregado)."""
        reranker = CrossEncoderReranker()
        assert reranker.rerank("consulta", [], top_k=3) == []

    def test_rerank_ordenacao_por_score_decrescente(self):
        """Scores do cross-encoder reordenam os candidatos e sobrescrevem score."""
        reranker = CrossEncoderReranker()
        reranker._model = _CrossEncoderComScores([0.1, 0.9, 0.5])
        candidatos = [
            ("a", 5.0, Document("a", "conteudo a")),
            ("b", 5.0, Document("b", "conteudo b")),
            ("c", 5.0, Document("c", "conteudo c")),
        ]

        saida = reranker.rerank("consulta", candidatos, top_k=2)

        assert [doc_id for doc_id, _, _ in saida] == ["b", "c"]
        assert saida[0][1] == pytest.approx(0.9)

    def test_rerank_com_predicao_falha_preserva_ordem_original(self):
        """Se o predict explodir, a ordem original (recorte top_k) é mantida."""
        reranker = CrossEncoderReranker()
        reranker._model = _CrossEncoderQuebrado()
        candidatos = [
            ("a", 5.0, Document("a", "conteudo a")),
            ("b", 5.0, Document("b", "conteudo b")),
        ]

        assert reranker.rerank("consulta", candidatos, top_k=3) == candidatos


class TestHybridRetrieverBordas:
    """Bordas do retriever: reranker, falhas de embedding, persistência e load."""

    def test_init_com_reranker_ativo(self, tmp_path, embedder):
        """enable_reranker=True instancia o cross-encoder (sem carregar modelo)."""
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=True),
            embedder=embedder,
            index_dir=tmp_path / "com_reranker",
        )
        assert isinstance(retriever._reranker, CrossEncoderReranker)

    def test_init_com_reranker_indisponivel(self, tmp_path, embedder, monkeypatch):
        """Se o reranker não puder ser criado, o retriever segue sem ele."""
        class _RerankerQuebrado:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("cross-encoder indisponível")

        monkeypatch.setattr(hs, "CrossEncoderReranker", _RerankerQuebrado)
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=True),
            embedder=embedder,
            index_dir=tmp_path / "sem_reranker",
        )

        assert retriever._reranker is None
        # Continua funcionando: add + busca seguem o caminho normal.
        retriever.add_document("1", "alpha beta")
        assert [d.doc_id for d in retriever.search("alpha")] == ["1"]

    def test_add_document_com_embedding_falhando(self, tmp_path):
        """Falha ao embutir o doc não derruba a indexação (fica sem embedding)."""
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False),
            embedder=_EmbedderQuebrado(),
            index_dir=tmp_path / "sem_embed",
        )

        doc = retriever.add_document("1", "conteudo qualquer")

        assert doc.doc_id == "1"
        assert doc.embedding == []
        assert retriever.stats()["total_docs"] == 1

    def test_search_com_query_sem_tokens_uteis(self, retriever):
        """Consulta só de stopwords/curta tokeniza vazia → resultado vazio."""
        retriever.add_document("1", "alpha beta gama")
        assert retriever.search("a o de") == []

    def test_search_com_falha_no_embedding_da_query(self, tmp_path):
        """Falha no embed da consulta cai no caminho BM25-only sem quebrar."""
        embedder = _EmbedderFalhaNaConsulta()
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False, final_top_k=3),
            embedder=embedder,
            index_dir=tmp_path / "falha_query",
        )
        retriever.add_document("1", "alpha beta gama")
        retriever.add_document("2", "alpha delta")
        embedder.falha_na_consulta = True

        resultados = retriever.search("alpha")

        assert len(resultados) >= 1
        assert {d.doc_id for d in resultados} <= {"1", "2"}

    def test_search_aplica_reranker_quando_disponivel(self, retriever):
        """Com reranker injetado a ordem final vem dele (não do RRF)."""
        retriever.add_document("alvo", "alpha beta gama")
        retriever.add_document("outro", "alpha beta")

        class _RerankerQueDevolveSoAlvo:
            def __init__(self):
                self.vistos: list[str] = []

            def rerank(self, query, candidates, top_k=10):
                self.vistos = [doc_id for doc_id, _, _ in candidates]
                return [c for c in candidates if c[0] == "alvo"][:top_k]

        reranker = _RerankerQueDevolveSoAlvo()
        retriever._reranker = reranker

        resultados = retriever.search("alpha", top_k=3)

        # Sem o reranker o fallback devolveria os dois docs; com ele, só "alvo".
        assert [d.doc_id for d in resultados] == ["alvo"]
        assert reranker.vistos  # o reranker recebeu os candidatos do RRF

    def test_search_filtro_metadata_sem_correspondencia(self, retriever):
        """Filtro de metadata que não casa nenhum candidato devolve vazio."""
        retriever.add_document("1", "alpha beta", metadata={"tipo": "A"})
        retriever.add_document("2", "alpha gama", metadata={"tipo": "B"})

        resultados = retriever.search("alpha", filter_metadata={"tipo": "C"})

        assert resultados == []

    def test_search_com_reranker_falho_usa_ordem_rrf(self, retriever):
        """Rerank que explode cai no fallback de ordem RRF sem exceção."""
        retriever.add_document("1", "alpha beta gama")
        retriever.add_document("2", "alpha delta")

        class _RerankerQueExplode:
            def rerank(self, query, candidates, top_k=10):
                raise RuntimeError("rerank explodiu")

        retriever._reranker = _RerankerQueExplode()
        resultados = retriever.search("alpha", top_k=2)

        assert len(resultados) >= 1
        assert {d.doc_id for d in resultados} <= {"1", "2"}

    def test_persist_e_load_sem_diretorio_de_indice(self, embedder):
        """Sem index_dir o _persist e o load são no-ops determinísticos."""
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False),
            embedder=embedder,
            index_dir=None,
        )

        assert retriever.add_document("1", "alpha beta").doc_id == "1"
        assert retriever.load() == 0

    def test_persist_com_falha_de_escrita_e_engolida(self, tmp_path, embedder):
        """Erro de escrita do índice é logado e não derruba o add_document."""
        index_dir = tmp_path / "indice_quebrado"
        index_dir.mkdir()
        # Arquivo virou diretório → rename final do persist falha.
        (index_dir / "hybrid_index.json").mkdir()

        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False),
            embedder=embedder,
            index_dir=index_dir,
        )

        assert retriever.add_document("1", "alpha beta").doc_id == "1"

    def test_load_sem_arquivo_de_indice(self, tmp_path, embedder):
        """Diretório existe mas o JSON não → load devolve 0."""
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False),
            embedder=embedder,
            index_dir=tmp_path / "vazio",
        )
        assert retriever.load() == 0

    def test_load_com_json_corrompido(self, tmp_path, embedder):
        """JSON inválido é logado e o load devolve 0 (índice fica vazio)."""
        index_dir = tmp_path / "corrompido"
        index_dir.mkdir()
        (index_dir / "hybrid_index.json").write_text("{ não é json", encoding="utf-8")

        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False),
            embedder=embedder,
            index_dir=index_dir,
        )

        assert retriever.load() == 0
        assert retriever.stats()["total_docs"] == 0

    def test_stats_reflete_indices_e_config(self, retriever):
        """stats() devolve contagens dos dois índices e a config efetiva."""
        retriever.add_document("1", "alpha beta gama")
        retriever.add_document("2", "alpha delta")

        stats = retriever.stats()

        assert stats["total_docs"] == 2
        assert stats["bm25_docs"] == 2
        assert stats["dense_docs"] == 2
        assert stats["config"]["enable_reranker"] is False
        assert stats["config"]["final_top_k"] == 3
        assert stats["config"]["rrf_k"] == 60


class TestPersistenciaEDocumento:
    """Round-trip de persistência e defaults do `Document.from_dict`."""

    def test_load_com_chaves_ausentes_usa_defaults(self, tmp_path, embedder):
        """JSON mínimo (só doc_id/content) carrega com defaults do Document."""
        index_dir = tmp_path / "minimo"
        index_dir.mkdir()
        (index_dir / "hybrid_index.json").write_text(
            json.dumps({"docs": {"mini": {"doc_id": "mini", "content": "conteudo"}}}),
            encoding="utf-8",
        )
        retriever = HybridRetriever(
            config=HybridSearchConfig(enable_reranker=False),
            embedder=embedder,
            index_dir=index_dir,
        )

        assert retriever.load() == 1

        doc = retriever._docs["mini"]
        assert doc.content == "conteudo"
        assert doc.metadata == {}
        assert doc.bm25_tokens == []
        assert doc.embedding == []
        assert doc.created_ts > 0

    def test_remove_document_persiste_no_disco_e_recarrega(self, tmp_path, embedder):
        """Remoção regrava o índice e um retriever novo só enxerga o que sobrou."""
        config = HybridSearchConfig(enable_reranker=False)
        original = HybridRetriever(
            config=config, embedder=embedder, index_dir=tmp_path / "idx"
        )
        original.add_document("1", "alpha beta gama")
        original.add_document("2", "alpha delta")

        assert original.remove_document("1") is True
        assert original.remove_document("inexistente") is False

        recarregado = HybridRetriever(
            config=config, embedder=embedder, index_dir=tmp_path / "idx"
        )
        assert recarregado.load() == 1
        assert [d.doc_id for d in recarregado.search("alpha")] == ["2"]
        assert recarregado.stats()["bm25_docs"] == 1
