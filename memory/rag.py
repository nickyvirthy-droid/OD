"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/rag.py
Descrição: Pipeline RAG de qualidade (Parte B da absorção do Project NOMAD)
           — reescrita de consulta com histórico, floor de relevância duplo,
           reranker e orçamento de contexto com métrica do descartado.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_PROJECT_NOMAD.md §3 (Parte B)
  - Padrões do Nômade traduzidos para o nosso Python (sem copiar código)

Arquitetura (tudo determinístico — NENHUMA chamada de LLM aqui):

    pergunta ─┬─ reescrever(pergunta, histórico)   # anafórico/elíptico →
              │                                    # agrega termos recentes
              ├─ VectorStore.search(namespace, …)  # embedding sem stopwords
              ├─ floor DUPLO medido no corpus real:
              │    score = 0.8·cosseno + 0.2·overlap_IDF  ≥ 0.36
              │    overlap_IDF                          ≥ 0.22
              ├─ visibilidade por papel (corpus interno só para admin)
              └─ orçamento por tokens (janela do modelo − system −
                 histórico − resposta) → o que NÃO coube vira MÉTRICA

Calibração (2026-10-14, corpus real de docs/ + knowledge/ — 842 chunks na
primeira medição, 850 no boot do serviço; 16 queries medidas — 8
relevantes × 8 irrelevantes, com o código FINAL: top_k=24 +
termos_da_consulta()): score vetorial PURO não separava (irrelevante
0.496 > relevante 0.444) porque stopwords inflam o cosseno. A regra de
duas chaves acima, com as stopwords filtradas dos DOIS lados, passa
**8/8 relevantes e bloqueia 8/8 irrelevantes** — a suíte de calibração
em tests/test_rag.py mantém essas 16 medições como gate (falhou =
recalibrar com evidência).

Prova de fogo no serviço vivo (2026-10-14) — 2 bordas medidas e
corrigidas, com testes:
  1. prefixo de instrução antes de ":" ("responda curto: ...") entrava
     na soma_idf com idf de palavra rara de comando e derrubava consulta
     certa (overlap 0.211 < 0.22 → 0 trechos no prompt → o LLM respondeu
     INVENTANDO as "regras" em vez de citar o doc). termos_da_consulta()
     tira só o prefixo curto (≤5 palavras) do FLOOR; a busca vetorial
     continua vendo a frase crua.
  2. top_k=12 deixava o chunk certo do doc na posição 15 da busca, fora
     do pool do floor. top_k → 24 (o reranker reordena depois).

Usage:
    from memory.rag import RAGPipeline, fontes_padrao

    store = VectorStore(store_dir="data/vector_memory")
    rag = RAGPipeline(store, fontes=fontes_padrao(raiz))
    rag.sync()                        # ingere docs/ + knowledge/ (idempotente)
    resultado = rag.consult("e as regras?", historico=msgs, papel="admin")
    prompt = f"{system}\\n{resultado.block}"
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from core.logger import make_audit_nicky

_audit_nicky = make_audit_nicky("omega.memory.rag")

__signature__ = "OD // CORE"


# ---------------------------------------------------------------------------
# Tokens e termos
# ---------------------------------------------------------------------------

DEFAULT_CHARS_PER_TOKEN = 4.0

# Stopwords PT-BR/EN da casa: filtradas ANTES do embedding (o HashEmbedding
# conta cada token — "de/a/em" dominavam o cosseno e tornavam o floor
# inútil; medição em 2026-10-14) e na extração de termos de consulta.
STOPWORDS_PT: frozenset[str] = frozenset(
    """
    a o as os e é são era foi de do da dos das em no na nos nas ao aos à às
    por para com sem sob sobre que qual quais quando onde como porque pois
    se ou um uma uns umas este esta esse essa estes estas esses essas isto
    isso aquilo aquele aquela aqueles aquelas mais menos muito muita muitos
    muitas já não nem sim mas se então também ainda tanto tanta tantos tantas
    meu minha meus minhas seu sua seus suas nosso nossa nossos nossas dele
    dela deles delas lhe lhes eu tu ele ela eles elas nós vos me te nos vos
    ser estar ter haver vai vão foi foram sendo tinha tem têm havia farei
    fazer feito feita faz fazem tipo entre até desde após contra perante
    aqui ali lá acima abaixo dentro fora perto longe depois antes durante
    coisa coisas vez vezes ninguém alguém todo toda todos todas cada outro
    outra outros outras mesmo mesma coisa qualquer tal tais bem mal
    the of and to in for is are was were be can will would could should
    this that with from into over under about after before not no yes
    """.split()
)

_TOKEN_PATTERN = re.compile(r"[a-zà-ú0-9]+")


def termos(texto: str) -> list[str]:
    """Termos de conteúdo do texto (minúsculos, sem stopwords, sem pontuação)."""
    if not texto:
        return []
    return [
        t
        for t in _TOKEN_PATTERN.findall(texto.casefold())
        if len(t) > 2 and t not in STOPWORDS_PT
    ]


def termos_da_consulta(pergunta: str) -> list[str]:
    """Termos de TÓPICO da consulta para o floor duplo.

    Prefixo de instrução antes de dois-pontos ("responda curto: quais
    regras de trabalho...") não é conteúdo — contá-lo inflava o
    denominador do overlap com idf de palavra rara de comando e derrubava
    consulta certa no serviço real (medido em 2026-10-14: soma_idf 33.6 →
    overlap 0.211 < 0.22, 0 trechos, e o LLM respondeu de inventar;
    com o prefixo fora: soma 22.1 → overlap 0.32 → o doc certo passa).
    Só o prefixo CURTO (≤5 palavras) é tratado como instrução — um trecho
    longo antes de ":" é conteúdo. A BUSCA vetorial usa a frase crua;
    só os termos do floor são limpos.
    """
    partes = pergunta.split(":", 1)
    if len(partes) == 2 and len(partes[0].split()) <= 5:
        return termos(partes[1])
    return termos(pergunta)


def _limpar(texto: str) -> str:
    """Texto sem stopwords — é o que o embedding vê (docs e consultas)."""
    return " ".join(termos(texto))


# ---------------------------------------------------------------------------
# Calibração por modelo (Parte B: "calibração de tokens por modelo")
# ---------------------------------------------------------------------------

# janela de contexto (n_ctx) por modelo servido. Valores medidos no host:
# od-llm roda `llama-server --ctx-size 8192` para qwen2.5-coder-3b
# (prova: linha de comando do processo, 2026-10-14).
JANELAS_MODELOS: dict[str, int] = {
    "qwen2.5-coder-3b": 8192,
    "qwen2.5-coder-7b": 32768,
    "gemma-4-e4b": 8192,
}
JANELA_PADRAO = 8192


def janela_do_modelo(nome: str) -> int:
    """Janela de tokens do modelo servido (fallback: JANELA_PADRAO)."""
    chave = (nome or "").casefold().strip()
    for modelo, janela in JANELAS_MODELOS.items():
        if modelo in chave or chave in modelo:
            return janela
    return JANELA_PADRAO


# ---------------------------------------------------------------------------
# Pisos medidos (ver docstring do módulo)
# ---------------------------------------------------------------------------

PESO_COSSENO = 0.8
PESO_OVERLAP = 0.2
# Recalibração medida em 2026-10-16 (corpus com iniciar/*.md — ver
# TestCalibracaoCorpusReal/TestRecallParafrases): grid ms [0.393..0.405] ×
# mo [0.001..0.071] mantém 8/8 rel. + 8/8 irr. bloqueadas e sobe o recall
# de parafrases de 1/8 (floor velho) para 6/8. Centro medido:
PISO_SCORE = 0.399       # score combinado mínimo (comb de 8/8 rel. ≥ este)
PISO_OVERLAP = 0.036     # overlap-IDF mínimo (ov=0 nunca injeta; teto 0.071:
                         # acima disso a parafrase "contêiner" cai)
# oversample: o reranker reordena depois do floor. Era 12; a prova de fogo
# no serviço (2026-10-14) mostrou o chunk certo do doc na posição 15 da
# busca — fora do pool — com 0 trechos no prompt. 24 cobre o alvo medido.
TOP_K_CANDIDATOS = 24
MAX_TRECHOS = 4          # trechos que podem entrar no bloco
MAX_TOKENS_BLOCO = 768   # teto do bloco de referência dentro da janela
FOLGA_DATETIME = 64      # tokens da linha de data/hora + margem
MIN_TOKENS_PARA_BLOCO = 40  # menos que isso = não há espaço honesto


def combinado(cosseno: float, overlap: float) -> float:
    """Score combinado do reranker: cosseno vetorial + overlap IDF.

    Função pura (testável sem store): o cosseno sozinho não separa
    relevante de irrelevante neste corpus; o overlap IDF dá o peso da
    raridade dos termos. Os dois pisos (PISO_SCORE e PISO_OVERLAP)
    trabalham JUNTOS nesta fórmula.
    """
    return PESO_COSSENO * cosseno + PESO_OVERLAP * overlap

HISTORICO_REESCRITA = 6   # mensagens olhadas na reescrita
MAX_EXTRAS_REESCRITA = 6  # termos agregados no máximo

# Marcadores anafóricos/elípticos: a consulta sozinha não nomeia o assunto.
MARCADORES_ANAFORA: tuple[str, ...] = (
    " e o ", " e a ", " e os ", " e as ", " e agora", " e ai", " e daí",
    " dele", " dela", " deles", " delas", " disso", " nisso", " isso",
    " aquilo", " aquele", " aquela", " aqueles", " aquelas", " a mesma",
    " o mesmo", " as mesmas", " os mesmos", " também", " de novo",
    " igual", " certeza", " ainda",
)


# ---------------------------------------------------------------------------
# Reescrita de consulta com histórico (determinística, sem LLM)
# ---------------------------------------------------------------------------

def _anafórica(pergunta: str) -> bool:
    """True quando a consulta referencia algo por contexto (anáfora/elipse)."""
    bruto = f" {pergunta.casefold().strip()} "
    bruto = re.sub(r"\s+", " ", bruto)
    return any(m in bruto for m in MARCADORES_ANAFORA)


def reescrever(
    pergunta: str, historico: Iterable[Any] = ()
) -> tuple[str, bool]:
    """Reescreve a consulta incorporando termos do histórico recente.

    Só reescreve quando a consulta (a) é curta/elíptica (≤4 termos de
    conteúdo) OU (b) contém marcador anafórico ("e o preço dele?", "isso").
    Consultas autossuficientes passam intactas — reescrever tudo bagunça o
    score medido no floor.

    Args:
        pergunta:  Texto da mensagem atual.
        historico: Turnos recentes ({"role", "content"} ou Message).

    Returns:
        (consulta_final, reescrita?)
    """
    # Consulta sem termo de conteúdo NEM anáfora → nada a agregar. Uma
    # consulta 100% elíptica ("e aquilo?") SEM termos mas COM marcador
    # anafórico ainda reescreve — é o caso clássico de elipse (bug de
    # borda pego pela suíte: "aquilo" é stopword e zerava os termos).
    anafórica = _anafórica(pergunta)
    base = termos(pergunta)
    if not base and not anafórica:
        return pergunta, False
    if len(base) > 4 and not anafórica:
        return pergunta, False

    extras: list[str] = []
    vistos = set(base)
    mensagens = list(historico)[-HISTORICO_REESCRITA:]
    for msg in mensagens:
        if isinstance(msg, dict):
            papel = str(msg.get("role") or "")
            conteudo = str(msg.get("content") or "")
        else:
            papel = str(getattr(msg, "role", "") or "")
            conteudo = str(getattr(msg, "content", "") or "")
        if papel not in ("user", "assistant") or not conteudo:
            continue
        for t in termos(conteudo):
            if t not in vistos:
                vistos.add(t)
                extras.append(t)
                if len(extras) >= MAX_EXTRAS_REESCRITA:
                    break
        if len(extras) >= MAX_EXTRAS_REESCRITA:
            break
    if not extras:
        return pergunta, False
    consulta = f"{pergunta.strip()} {' '.join(extras)}"
    return consulta, True


# ---------------------------------------------------------------------------
# Fontes do corpus e chunking markdown
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fonte:
    """Uma fonte do corpus indexada pelo RAG.

    visibilidade: "interna" = só o papel admin recebe no prompt;
                  "publica" = todos os papéis.
    """

    caminho: Path
    namespace: str = "conhecimento"
    visibilidade: str = "interna"


def fontes_padrao(raiz: Path) -> list[Fonte]:
    """Corpus padrão: docs/*.md + knowledge/*.md + iniciar/*.md (interna).

    `iniciar/` é a memória histórica (transcrições das sessões + RULES) —
    é onde vivem as formulações naturais das perguntas do dono. Medição
    2026-10-16: com ela o recall de parafrases no floor recalibrado sobe
    de 1/8 para 6/8 (gate de calibração continua 8/8 + 8/8).
    """
    fontes: list[Fonte] = []
    for pasta in ("docs", "knowledge", "iniciar"):
        alvo = raiz / pasta
        if not alvo.is_dir():
            continue
        for arq in sorted(alvo.glob("*.md")):
            fontes.append(Fonte(caminho=arq))
    return fontes


def chunkizar_markdown(
    texto: str,
    fonte: str,
    *,
    max_chars: int = 1400,
    min_chars: int = 60,
) -> list[tuple[str, dict[str, Any]]]:
    """Divide um markdown por seções (títulos #/##/###) com teto de tamanho.

    Returns:
        Lista de (texto_do_chunk, metadata) — chunks < min_chars caem
        (títulos soltos e rodapés não viram documento).
    """
    blocos: list[tuple[str, dict[str, Any]]] = []
    titulo = fonte
    atual: list[str] = []

    def _fecha() -> None:
        corpo = "\n".join(atual).strip()
        if len(corpo) >= min_chars:
            blocos.append((corpo, {"source": fonte, "titulo": titulo}))

    for linha in texto.splitlines():
        if re.match(r"^#{1,3}\s+", linha):
            if atual:
                _fecha()
            titulo = re.sub(r"^#{1,3}\s+", "", linha).strip()
            atual = [linha]
            continue
        atual.append(linha)
        if len("\n".join(atual)) >= max_chars:
            _fecha()
            atual = []
    if atual:
        _fecha()
    return blocos


# ---------------------------------------------------------------------------
# Provider com stopwords filtradas
# ---------------------------------------------------------------------------

class ProviderSemStopwords:
    """Decorador de EmbeddingProvider: limpa stopwords antes de embedar.

    Docs e consultas passam por aqui (é o provider DO store) — os dois lados
    da similaridade falam a mesma língua sem "de/a/em" dominando o cosseno.
    """

    def __init__(self, base: Any) -> None:
        self._base = base

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._base.embed([_limpar(t) for t in texts])

    @property
    def dimension(self) -> int:
        return self._base.dimension

    @property
    def base(self) -> Any:
        return self._base


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Trecho:
    """Um trecho aprovado no floor e dentro do orçamento."""

    texto: str
    source: str
    titulo: str
    score: float      # score combinado (0.8·cosseno + 0.2·overlap_IDF)
    cosseno: float
    overlap: float    # overlap ponderado por IDF (0..1)


@dataclass(slots=True)
class ResultadoRAG:
    """Resultado de uma consulta — o block vai para o prompt (ou "")."""

    consulta_original: str = ""
    consulta_final: str = ""
    reescrita: bool = False
    trechos: list[Trecho] = field(default_factory=list)
    block: str = ""
    candidatos: int = 0
    descartados_floor: int = 0
    descartados_visibilidade: int = 0
    descartados_orcamento: int = 0
    tokens_bloco: int = 0
    tokens_descartados: int = 0

    @property
    def descartados(self) -> int:
        return (
            self.descartados_floor
            + self.descartados_visibilidade
            + self.descartados_orcamento
        )


CABECALHO_BLOCO = (
    "Acervo de referência (interno; use apenas se for pertinente — "
    "se não for, responda normalmente):"
)


def _estimar(texto: str, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> int:
    if not texto:
        return 0
    return max(1, int(len(texto) / chars_per_token) + 1)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class RAGPipeline:
    """Pipeline RAG: reescrita → busca → floor duplo → visibilidade → orçamento.

    Attributes:
        store:  VectorStore (provider ProviderSemStopwords).
        fontes: Fontes indexadas por sync().
    """

    def __init__(
        self,
        store: Any,
        *,
        fontes: Optional[list[Fonte]] = None,
        namespace: str = "conhecimento",
        min_score: float = PISO_SCORE,
        min_overlap: float = PISO_OVERLAP,
        top_k: int = TOP_K_CANDIDATOS,
        max_trechos: int = MAX_TRECHOS,
        max_tokens_bloco: int = MAX_TOKENS_BLOCO,
        janela: int = JANELA_PADRAO,
        tokens_resposta: int = 512,
        chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
    ) -> None:
        self._store = store
        self._fontes = list(fontes or [])
        self._namespace = namespace
        self._min_score = min_score
        self._min_overlap = min_overlap
        self._top_k = max(1, top_k)
        self._max_trechos = max(1, max_trechos)
        self._max_tokens_bloco = max(0, max_tokens_bloco)
        self._janela = max(256, janela)
        self._tokens_resposta = max(0, tokens_resposta)
        self._chars_per_token = chars_per_token
        self._df: dict[str, int] = {}
        self._n_docs = 0
        self._metricas: dict[str, int] = {
            "consultas": 0,
            "reescritas": 0,
            "candidatos": 0,
            "trechos": 0,
            "descartados_floor": 0,
            "descartados_visibilidade": 0,
            "descartados_orcamento": 0,
            "tokens_bloco": 0,
            "tokens_descartados": 0,
        }
        self._lock = threading.RLock()
        # Estado da sincronização (v1.36.1): o boot pode servi-lo antes do
        # sync terminar — consultas sem _df já degradam para "" por desenho.
        self._sync_estado: str = "pendente"
        self._sync_stats: Optional[dict[str, int]] = None
        self._sync_ts: float = 0.0
        self._sync_thread: Optional[threading.Thread] = None

    # -- Propriedades --------------------------------------------------------

    @property
    def store(self) -> Any:
        return self._store

    @property
    def fontes(self) -> list[Fonte]:
        return list(self._fontes)

    @property
    def namespace(self) -> str:
        return self._namespace

    # -- Ingestão ------------------------------------------------------------

    def sync(self) -> dict[str, int]:
        """Sincroniza o store com as fontes (idempotente).

        doc_id determinístico (namespace+fonte+índice) + sha do conteúdo em
        metadata: arquivo igual → nada regrava; arquivo editado → o chunk é
        substituído; arquivo removido/renomeado → chunks órfãos são apagados.
        Recalcula o DF (document frequency) usado no overlap-IDF.

        Returns:
            Estatísticas da ingestão.
        """
        stats = {
            "arquivos": 0,
            "chunks": 0,
            "novos": 0,
            "atualizados": 0,
            "iguais": 0,
            "removidos": 0,
        }
        df: dict[str, int] = {}
        esperados: set[str] = set()
        n_docs = 0
        pendentes: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
        para_apagar: list[str] = []  # substituídos/órfãos — lote único (v1.36.1)
        with self._lock:
            self._sync_estado = "sincronizando"
            for fonte in self._fontes:
                try:
                    if not fonte.caminho.is_file():
                        continue
                    bruto = fonte.caminho.read_text(encoding="utf-8")
                except Exception as exc:
                    _audit_nicky(
                        "WARN", "RAG fonte ilegível",
                        fonte=str(fonte.caminho), error=type(exc).__name__,
                    )
                    continue
                stats["arquivos"] += 1
                try:
                    relativo = str(fonte.caminho.relative_to(Path.cwd()))
                except ValueError:
                    relativo = fonte.caminho.name
                for indice, (texto, meta) in enumerate(
                    chunkizar_markdown(bruto, relativo)
                ):
                    doc_id = hashlib.sha1(
                        f"{fonte.namespace}:{relativo}:{indice}".encode("utf-8")
                    ).hexdigest()[:16]
                    sha = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]
                    metadata = dict(meta)
                    metadata.update(
                        visibilidade=fonte.visibilidade,
                        indice=indice,
                        sha=sha,
                    )
                    esperados.add(doc_id)
                    stats["chunks"] += 1
                    n_docs += 1
                    existente = self._store.get(doc_id)
                    if (
                        existente is not None
                        and existente.get("metadata", {}).get("sha") == sha
                    ):
                        stats["iguais"] += 1
                    else:
                        if existente is not None:
                            para_apagar.append(doc_id)
                            stats["atualizados"] += 1
                        else:
                            stats["novos"] += 1
                        pendentes.setdefault(fonte.namespace, []).append(
                            (doc_id, texto, metadata)
                        )
                    for t in set(termos(texto)):
                        df[t] = df.get(t, 0) + 1
            # Persistência em LOTE por namespace: uma escrita só no fim.
            # (add() unitário persistiria o JSON inteiro a cada chunk —
            # O(n²) de I/O: 842 chunks custavam ~86s na ingestão inicial.)
            for ns, itens in pendentes.items():
                self._store.add_many(
                    ns,
                    [texto for _, texto, _ in itens],
                    metadata_list=[meta for _, _, meta in itens],
                    doc_ids=[doc_id for doc_id, _, _ in itens],
                )
            # Órfãos: docs DESTE namespace criados por ingestão (metadata
            # "source") que não existem mais nas fontes atuais.
            for doc in self._listar_namespace():
                if doc["doc_id"] in esperados:
                    continue
                if "source" in (doc.get("metadata") or {}):
                    para_apagar.append(doc["doc_id"])
                    stats["removidos"] += 1
            # Remoções em LOTE (v1.36.1): o delete unitário reescrevia o
            # JSON do store a cada chunk — a re-sincronia de 442 substituí-
            # dos custou ~179s de boot. Uma escrita só, como o add_many.
            if para_apagar:
                self._store.delete_many(para_apagar)
            # Persistência em LOTE por namespace: uma escrita só no fim.
            # (add() unitário persistiria o JSON inteiro a cada chunk —
            # O(n²) de I/O: 842 chunks custavam ~86s na ingestão inicial.)
            for ns, itens in pendentes.items():
                self._store.add_many(
                    ns,
                    [texto for _, texto, _ in itens],
                    metadata_list=[meta for _, _, meta in itens],
                    doc_ids=[doc_id for doc_id, _, _ in itens],
                )
            self._df = df
            self._n_docs = n_docs
            self._sync_stats = dict(stats)
            self._sync_ts = time.time()
            self._sync_estado = "pronto"
        if stats["chunks"]:
            _audit_nicky(
                "INFO", "RAG corpus sincronizado",
                chunks=stats["chunks"], novos=stats["novos"],
                atualizados=stats["atualizados"], iguais=stats["iguais"],
                removidos=stats["removidos"],
            )
        return stats

    def sync_em_background(self) -> threading.Thread:
        """Sincroniza o corpus em thread de fundo — o boot NÃO espera (v1.36.1).

        O índice persistido já foi carregado no boot (store.load) e atende
        consultas imediatamente; a re-sincronia completa em paralelo e
        passa a valer assim que termina. Janela de degradação honesta:
        consultas antes do fim do sync devolvem "" (sem _df) — o mesmo
        caminho de "sem corpus", sem nunca derrubar o core. Duplo start
        devolve a thread em curso.
        """
        with self._lock:
            if self._sync_thread is not None and self._sync_thread.is_alive():
                return self._sync_thread
            self._sync_estado = "sincronizando"
            thread = threading.Thread(
                target=self._sync_worker, name="rag-sync", daemon=True
            )
            self._sync_thread = thread
        thread.start()
        return thread

    def _sync_worker(self) -> None:
        """Corpo da thread de fundo: sync com falha honesta, nunca fatal."""
        try:
            self.sync()
        except Exception as exc:  # pragma: no cover — defesa de thread
            with self._lock:
                self._sync_estado = "falhou"
            _audit_nicky(
                "WARN", "RAG sync em background falhou", error=type(exc).__name__
            )

    def sync_status(self) -> dict[str, Any]:
        """Estado da sincronização para inspeção (dump/health/dashboard)."""
        with self._lock:
            stats = self._sync_stats or {}
            return {
                "estado": self._sync_estado,
                "chunks": stats.get("chunks", 0),
                "novos": stats.get("novos", 0),
                "atualizados": stats.get("atualizados", 0),
                "iguais": stats.get("iguais", 0),
                "removidos": stats.get("removidos", 0),
                "ultimo_sync_ts": self._sync_ts,
            }

    def _listar_namespace(self) -> list[dict[str, Any]]:
        """Docs do namespace RAG (busca com consulta vazia devolve todos)."""
        try:
            brutos = self._store.search(
                self._namespace, "", top_k=100000, min_score=0.0
            )
        except Exception:
            return []
        return [
            {"doc_id": r.doc_id, "metadata": dict(r.metadata or {})}
            for r in brutos
        ]

    def _idf(self, termo: str) -> float:
        # Suavização (N+2): sem ela, um termo presente em TODOS os docs
        # (df=N) de um corpus minúsculo tinha idf=ln(1)=0 e uma consulta
        # perfeita era rejeitada pelo floor — bug de borda da suíte. No
        # corpus real (842 chunks) o deslocamento é ~0.001 nos idfs, muito
        # abaixo da margem de separação medida na calibração.
        return math.log((self._n_docs + 2) / (1 + self._df.get(termo, 0)))

    # -- Consulta ------------------------------------------------------------

    def consult(
        self,
        pergunta: str,
        *,
        historico: Iterable[Any] = (),
        papel: str = "user",
        system_prompt: str = "",
    ) -> ResultadoRAG:
        """Consulta o corpus e monta o bloco de referência (ou "").

        Etapas: reescrita com histórico → busca → floor duplo (score
        combinado + overlap-IDF) → visibilidade do papel → reranker →
        orçamento de tokens (o que sobrou vira métrica).
        """
        resultado = ResultadoRAG(consulta_original=pergunta)
        historico = list(historico)
        with self._lock:
            self._metricas["consultas"] += 1
            if self._n_docs == 0 or not self._df:
                # Sem corpus sincronizado não há o que consultar (honesto,
                # sem exceção — o prompt segue normalmente).
                return resultado
            consulta, reescrita = reescrever(pergunta, historico)
            resultado.consulta_final = consulta
            resultado.reescrita = reescrita
            if reescrita:
                self._metricas["reescritas"] += 1
            qt = set(termos_da_consulta(consulta))
            if not qt:
                return resultado
            candidatos = self._store.search(
                self._namespace, consulta, top_k=self._top_k
            )
            resultado.candidatos = len(candidatos)
            self._metricas["candidatos"] += len(candidatos)

            soma_idf = sum(self._idf(t) for t in qt) or 1.0
            aprovados: list[Trecho] = []
            for cand in candidatos:
                vis = str((cand.metadata or {}).get("visibilidade") or "interna")
                if vis != "publica" and papel != "admin":
                    resultado.descartados_visibilidade += 1
                    continue
                dt = set(termos(cand.text))
                overlap = sum(self._idf(t) for t in (qt & dt)) / soma_idf
                combinado_score = combinado(float(cand.score), overlap)
                if (
                    combinado_score < self._min_score
                    or overlap < self._min_overlap
                ):
                    resultado.descartados_floor += 1
                    continue
                aprovados.append(
                    Trecho(
                        texto=cand.text,
                        source=str((cand.metadata or {}).get("source") or "?"),
                        titulo=str((cand.metadata or {}).get("titulo") or ""),
                        score=round(combinado_score, 4),
                        cosseno=round(float(cand.score), 4),
                        overlap=round(overlap, 4),
                    )
                )
            # Reranker: ordem final é o score COMBINADO (não o cosseno cru).
            aprovados.sort(key=lambda t: t.score, reverse=True)

            # Orçamento: janela − system − histórico − resposta − datetime.
            tokens_system = _estimar(system_prompt, self._chars_per_token)
            tokens_historico = _estimar(self._texto_historico(historico))
            disponivel = (
                self._janela
                - tokens_system
                - tokens_historico
                - self._tokens_resposta
                - FOLGA_DATETIME
            )
            teto = min(self._max_tokens_bloco, max(0, disponivel))
            if disponivel < MIN_TOKENS_PARA_BLOCO:
                # Sem espaço honesto: nada é injetado e o descarte fica
                # registrado (a regra da casa: descartado = métrica).
                resultado.descartados_orcamento += len(aprovados)
                resultado.tokens_descartados += sum(
                    _estimar(t.texto, self._chars_per_token) for t in aprovados
                )
            else:
                usados = 0
                for trecho in aprovados:
                    if len(resultado.trechos) >= self._max_trechos:
                        resultado.descartados_orcamento += 1
                        resultado.tokens_descartados += _estimar(
                            trecho.texto, self._chars_per_token
                        )
                        continue
                    linha = self._formatar(trecho)
                    tokens = _estimar(linha, self._chars_per_token)
                    if usados + tokens > teto and resultado.trechos:
                        resultado.descartados_orcamento += 1
                        resultado.tokens_descartados += _estimar(
                            trecho.texto, self._chars_per_token
                        )
                        continue
                    if not resultado.trechos and tokens > teto:
                        # Primeiro trecho sozinho não cabe no teto: corta o
                        # texto até caber (nunca injeta estouro).
                        resultado.descartados_orcamento += 1
                        resultado.tokens_descartados += _estimar(
                            trecho.texto, self._chars_per_token
                        )
                        continue
                    resultado.trechos.append(trecho)
                    usados += tokens

            if resultado.trechos:
                linhas = [CABECALHO_BLOCO]
                linhas.extend(self._formatar(t) for t in resultado.trechos)
                resultado.block = "\n".join(linhas)
            resultado.tokens_bloco = _estimar(
                resultado.block, self._chars_per_token
            )

            m = self._metricas
            m["trechos"] += len(resultado.trechos)
            m["descartados_floor"] += resultado.descartados_floor
            m["descartados_visibilidade"] += resultado.descartados_visibilidade
            m["descartados_orcamento"] += resultado.descartados_orcamento
            m["tokens_bloco"] += resultado.tokens_bloco
            m["tokens_descartados"] += resultado.tokens_descartados
            return resultado

    @staticmethod
    def _texto_historico(historico: Iterable[Any]) -> str:
        partes: list[str] = []
        for msg in historico:
            if isinstance(msg, dict):
                partes.append(str(msg.get("content") or ""))
            else:
                partes.append(str(getattr(msg, "content", "") or ""))
        return "\n".join(partes)

    @staticmethod
    def _formatar(trecho: Trecho) -> str:
        titulo = f" — {trecho.titulo}" if trecho.titulo else ""
        return f"- [{trecho.source}{titulo}] {trecho.texto}"

    # -- Métricas ------------------------------------------------------------

    def metricas(self) -> dict[str, int]:
        """Métricas acumuladas do pipeline (o que foi injetado e descartado)."""
        with self._lock:
            return dict(self._metricas)

    def dump(self) -> dict[str, Any]:
        return {
            "namespace": self._namespace,
            "fontes": len(self._fontes),
            "docs": self._n_docs,
            "termos_df": len(self._df),
            "janela": self._janela,
            "min_score": self._min_score,
            "min_overlap": self._min_overlap,
            "sync": self.sync_status(),
            "metricas": self.metricas(),
        }
