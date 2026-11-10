"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/memory_layer.py
Descrição: Memória longa estruturada (F4, fase 1 — Zep-style simplificado):
           grafo temporal de fatos e entidades em SQLite, com extração
           determinística (sem LLM) e busca por sobreposição de termos.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F4 (Memory Layer: core / archival / graph)
  - Mem0 (arXiv 2504.19413) e Zep (arXiv 2501.13956) — grafo temporal + fatos
  - memory/history.py (histórico de 20 mensagens por perfil, sem entidade)

Architecture:
    O `MemoryGraph` guarda dois tipos de nós no MESMO SQLite (data/memory.db):

      - fato        — "nome é Alex", "cidade é São Paulo" (o que sabemos);
      - entidade    — chave estável ("nome", "cidade", "projeto:omega") que
                      agrupa fatos e permite busca por assunto.

    Cada fato aponta para a sua entidade por uma aresta `menciona`. Quando um
    fato novo contradiz um antigo do mesmo (user, tipo, entidade), o antigo
    NÃO é apagado: nasce a aresta `substitui` (novo → antigo) e ele sai das
    buscas. Assim o histórico continua auditáveL ("mudei de cidade em
    outubro") sem que a resposta use o dado velho.

    Escopo: todo nó carrega `user_id` e TODA leitura filtra por ele — memória
    de um usuário nunca aparece para outro. O id do nó é aleatório (uuid4),
    não derivado do conteúdo, para não vazar nada por id.

    Extração é determinística: regex PT-BR sobre o texto do usuário. Nada de
    LLM — o que mantém a escrita barata e testável.

    Busca: sobreposição de termos (sempre) e, SÓ quando ela volta vazia,
    fallback semântico opcional via `core/memory_embeddings` (sinônimo:
    "animal" ≈ "cachorro"). Sem chave/rede o fallback simplesmente não existe.

Usage:
    from core.memory_layer import MemoryGraph

    memoria = MemoryGraph("data/memory.db")
    memoria.adicionar_fato("alex", "cidade é Curitiba", entidade="cidade")
    memoria.buscar("alex", "onde eu moro")     # [MemoryNode(cidade é Curitiba)]
    memoria.salvar("meu nome é Alex", user_id="alex")
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

_log = get_logger("omega.core.memory_layer")

# Teto de fatos por usuário: memória longa não pode virar despejo infinito.
MAX_FATOS_POR_USUARIO = 500
# Tamanho máximo de um fato (o resto é cortado, não rejeitado).
MAX_CHARS_FATO = 400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_nodes (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    conteudo    TEXT NOT NULL,
    entidade    TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}',
    origem      TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    expira_em   REAL
);
CREATE INDEX IF NOT EXISTS idx_mem_user_tipo ON memory_nodes(user_id, tipo);
CREATE INDEX IF NOT EXISTS idx_mem_entidade  ON memory_nodes(user_id, entidade);

CREATE TABLE IF NOT EXISTS memory_edges (
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    relacao    TEXT NOT NULL,
    peso       REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL,
    PRIMARY KEY (source, target, relacao)
);
CREATE INDEX IF NOT EXISTS idx_mem_edge_target ON memory_edges(target, relacao);

-- Fase 4: vetores do fallback semântico (sinônimo). Ficam no mesmo banco e
-- são recalculados se o modelo mudar — o nome do modelo é parte da chave.
CREATE TABLE IF NOT EXISTS memory_vectors (
    node_id    TEXT PRIMARY KEY,
    modelo     TEXT NOT NULL,
    vetor      BLOB NOT NULL,
    created_at REAL NOT NULL
);
"""

# Relações do grafo.
REL_MENCIONA = "menciona"   # fato → entidade
REL_SUBSTITUI = "substitui"  # fato novo → fato antigo (contradição)

# TTL padrão de fato efêmero ("hoje estou cansado", "tenho reunião amanhã"):
# uma semana. Sobrescrevível por OD_MEMORY_EFEMERO_DIAS.
TTL_EFEMERO_DIAS = 7.0

# Cache de RESULTADOS do fallback semântico (F4, fase 4b). A chamada de
# embedding da consulta custa ~0,4 s; repetir a mesma pergunta no fio da
# conversa é comum, e o resultado só depende da consulta + dos fatos ativos.
# `OD_MEMORY_SEMANTICA_CACHE_S=0` desliga; a chave também carrega a assinatura
# dos fatos ativos, então fato novo/removido invalida sozinho.
CACHE_SEMANTICO_TTL_S = 300.0
CACHE_SEMANTICO_MAX = 256


def _env_float(nome: str, padrao: float) -> float:
    """Float do ambiente; valor inválido volta ao padrão sem levantar."""
    import os

    try:
        return float(os.environ.get(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def _normalizar_consulta(consulta: str) -> str:
    """Forma canônica da consulta para o cache: caixa, acento e pontuação fora."""
    texto = unicodedata.normalize("NFKD", consulta or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^\w\s]", " ", texto.casefold())
    return " ".join(texto.split())

# Marcadores de tempo relativo: o fato descreve um ESTADO passageiro.
_EFEMERO = re.compile(
    r"\b(hoje|amanha|amanhã|agora|esta semana|essa semana|nesta semana|neste mes|neste mês|"
    r"daqui a|por enquanto|no momento|esta noite|essa noite|hoje a noite)\b"
)


class MemoryLayerError(Exception):
    """Falha de armazenamento/consulta da memória longa."""


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@dataclass
class MemoryNode:
    """Um nó do grafo (fato, preferência ou entidade)."""

    id: str
    user_id: str
    tipo: str
    conteudo: str
    entidade: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    origem: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    expira_em: Optional[float] = None  # None = permanente

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tipo": self.tipo,
            "conteudo": self.conteudo,
            "entidade": self.entidade,
            "metadata": dict(self.metadata),
            "origem": self.origem,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expira_em": self.expira_em,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row | tuple[Any, ...]) -> "MemoryNode":
        dados = row if isinstance(row, sqlite3.Row) else None
        campos = dict(dados) if dados is not None else None

        def pegar(nome: str, indice: int, padrao: Any = None) -> Any:
            if campos is not None:
                return campos.get(nome, padrao)
            try:
                return row[indice]  # type: ignore[index]
            except IndexError:
                return padrao

        metadata = pegar("metadata", 5, "{}")
        try:
            meta = json.loads(metadata) if metadata else {}
        except ValueError:
            meta = {}
        expira = pegar("expira_em", 9, None)
        return cls(
            id=str(pegar("id", 0, "")),
            user_id=str(pegar("user_id", 1, "")),
            tipo=str(pegar("tipo", 2, "fato")),
            conteudo=str(pegar("conteudo", 3, "")),
            entidade=str(pegar("entidade", 4, "") or ""),
            metadata=meta if isinstance(meta, dict) else {},
            origem=str(pegar("origem", 6, "") or ""),
            created_at=float(pegar("created_at", 7, 0.0) or 0.0),
            updated_at=float(pegar("updated_at", 8, 0.0) or 0.0),
            expira_em=float(expira) if expira is not None else None,
        )


@dataclass
class MemoryEdge:
    """Uma aresta do grafo (fato → entidade, fato → fato)."""

    source: str
    target: str
    relacao: str
    peso: float = 1.0
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relacao": self.relacao,
            "peso": self.peso,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Normalização e extração (determinística, sem LLM)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "e", "ou", "que", "meu", "minha", "meus",
    "minhas", "eu", "sou", "é", "eh", "para", "pra", "por", "com", "ao",
    "se", "ja", "já", "me", "mim", "eu", "aqui", "ali", "onde", "como",
    "qual", "quais", "quem", "porque", "porquê", "tem", "tenho", "foi",
}


def _sem_acento(texto: str) -> str:
    """Remove acentos mantendo o comprimento (busca tolerante a acento)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados."""
    return re.sub(r"\s+", " ", _sem_acento(texto or "").lower()).strip()


def tokens(texto: str, *, com_stopwords: bool = False) -> list[str]:
    """Divide em tokens alfanuméricos, sem stopwords por padrão."""
    bruto = re.findall(r"[a-z0-9]+", normalizar(texto))
    if com_stopwords:
        return bruto
    return [t for t in bruto if t not in _STOPWORDS and len(t) > 1]


def radical(token: str) -> str:
    """Radical leve PT-BR: 'moro'/'mora'/'morar' → 'mor'.

    Não é stemming de verdade — é o mínimo para a busca não perder a mesma
    ideia escrita em flexão diferente (moro/mora, trabalho/trabalha).
    """
    t = token
    if len(t) > 3 and t.endswith("s"):
        t = t[:-1]
    if len(t) > 3 and t.endswith("r"):
        t = t[:-1]
    if len(t) > 3 and t[-1] in "aeo":
        t = t[:-1]
    return t


def tokens_busca(texto: str) -> set[str]:
    """Tokens para a busca: sem stopword e reduzidos ao radical."""
    return {radical(t) for t in tokens(texto)}


def slug(texto: str, *, limite: int = 48) -> str:
    """Chave estável de entidade: 'São Paulo' → 'sao_paulo'."""
    partes = re.findall(r"[a-z0-9]+", normalizar(texto))
    return "_".join(partes)[:limite].strip("_") or "geral"


# Padrões de extração: (regex, tipo, entidade fixa, rótulo do conteúdo).
# A ordem importa: o primeiro que casa define o fato.
_PADROES: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (re.compile(r"\b(?:meu nome (?:e|eh|é)|me chamo|pode me chamar de)\s+([^.,;!?\n]{2,60})"), "fato", "nome", "nome é"),
    (re.compile(r"\b(?:meu aniversario (?:e|eh|é)|nasci em|meu niver (?:e|eh|é))\s+([^.,;!?\n]{2,60})"), "fato", "aniversario", "aniversário é"),
    (re.compile(r"\b(?:meu telefone (?:e|eh|é)|meu celular (?:e|eh|é))\s+([^.,;!?\n]{3,30})"), "fato", "telefone", "telefone é"),
    (re.compile(r"\b(?:meu e-?mail (?:e|eh|é)|meu email (?:e|eh|é))\s+([^\s,;!?\n]{3,80})"), "fato", "email", "e-mail é"),
    (re.compile(r"\b(?:eu moro (?:em|no|na)|moro (?:em|no|na)|minha cidade (?:e|eh|é))\s+([^.,;!?\n]{2,60})"), "fato", "cidade", "mora em"),
    (re.compile(r"\b(?:eu trabalho (?:com|em|na|no)|trabalho (?:com|em|na|no))\s+([^.,;!?\n]{2,60})"), "fato", "trabalho", "trabalha com"),
    (re.compile(r"\b(?:eu estudo|estudo)\s+([^.,;!?\n]{2,60})"), "fato", "estudo", "estuda"),
    (re.compile(r"\b(?:o|a) (?:meu|minha) (?:projeto|projeto atual) (?:e|eh|é)\s+([^.,;!?\n]{2,60})"), "fato", "projeto", "projeto é"),
    (re.compile(r"\b(?:eu )?prefiro\s+([^.,;!?\n]{2,80})"), "preferencia", "preferencia", "prefere"),
    (re.compile(r"\b(?:eu )?nao gosto de\s+([^.,;!?\n]{2,80})"), "preferencia", "nao_gosto", "não gosta de"),
    (re.compile(r"\b(?:eu )?detesto\s+([^.,;!?\n]{2,80})"), "preferencia", "nao_gosto", "não gosta de"),
    (re.compile(r"\b(?:eu )?gosto (?:muito )?de\s+([^.,;!?\n]{2,80})"), "preferencia", "gosto", "gosta de"),
    (re.compile(r"\b(?:lembre(?:-se)? que|memorize que|guarde que|anote que)\s+([^.,;!?\n]{3,400})"), "fato", "", ""),
)

# "tenho uma dúvida" não é memória: só guarda posse com substantivo concreto.
_POSSE = re.compile(r"\b(?:eu )?tenho (?:um|uma)\s+([^.,;!?\n]{3,60})")
_POSSE_IGNORAR = {
    "duvida", "pergunta", "ideia", "sugestao", "noticia", "novidade",
    "problema", "coisa", "perguntinha", "curiosidade",
}


def extrair_fatos(texto: str) -> list[dict[str, str]]:
    """Extrai fatos de um texto em PT-BR por regex (determinístico).

    Retorna uma lista de `{"tipo", "entidade", "conteudo"}`. Texto vazio ou
    irrelevante devolve `[]` — nunca levanta exceção.
    """
    if not texto or not isinstance(texto, str):
        return []
    out: list[dict[str, str]] = []
    vistos: set[tuple[str, str]] = set()
    for padrao, tipo, entidade_fixa, rotulo in _PADROES:
        for m in padrao.finditer(normalizar(texto)):
            valor = m.group(1).strip(" .,;:!?-\t")
            if len(valor) < 2:
                continue
            entidade = entidade_fixa
            if not entidade:
                # "lembre que ..." — o assunto é a primeira palavra de conteúdo
                primeira = next(iter(tokens(valor)), "geral")
                entidade = primeira
                rotulo = ""
            conteudo = f"{rotulo} {valor}".strip()
            chave = (entidade, conteudo)
            if chave in vistos:
                continue
            vistos.add(chave)
            out.append(
                {
                    "tipo": tipo,
                    "entidade": entidade,
                    "conteudo": conteudo,
                    "efemero": bool(_EFEMERO.search(valor)),
                }
            )
    for m in _POSSE.finditer(normalizar(texto)):
        valor = m.group(1).strip(" .,;:!?-\t")
        if len(valor) < 3 or next(iter(tokens(valor)), "") in _POSSE_IGNORAR:
            continue
        chave = ("possui", f"tem {valor}")
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(
            {
                "tipo": "fato",
                "entidade": "possui",
                "conteudo": f"tem {valor}",
                "efemero": bool(_EFEMERO.search(valor)),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------

class MemoryGraph:
    """Grafo temporal de memória longa, escopo por usuário, em SQLite.

    Args:
        caminho: Arquivo SQLite; o diretório é criado se faltar.
        clock:   Função que devolve o timestamp atual (injetável em testes).
    """

    def __init__(
        self,
        caminho: str | Path = "data/memory.db",
        *,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._caminho = Path(caminho)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._cache_semantico: "OrderedDict[tuple, tuple[float, list[str]]]" = OrderedDict()
        self._cache_semantico_hits = 0
        self._cache_semantico_misses = 0
        if str(self._caminho) != ":memory:":
            self._caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(
                str(self._caminho), check_same_thread=False, timeout=10.0
            )
            self._conn.row_factory = sqlite3.Row
            if str(self._caminho) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._migrar()
            self._conn.commit()
        except sqlite3.DatabaseError as exc:
            raise MemoryLayerError(f"banco de memória inválido: {exc}") from exc

    # -- ciclo de vida -------------------------------------------------------

    def _migrar(self) -> None:
        """Ajusta bancos criados antes da fase 3 (coluna `expira_em`)."""
        colunas = {
            str(r["name"])
            for r in self._conn.execute("PRAGMA table_info(memory_nodes)")
        }
        if colunas and "expira_em" not in colunas:
            self._conn.execute("ALTER TABLE memory_nodes ADD COLUMN expira_em REAL")
            _log.info("memoria: migração aplicada (coluna expira_em)")

    def fechar(self) -> None:
        """Fecha a conexão (idempotente)."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover — já fechada
                pass

    def __enter__(self) -> "MemoryGraph":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.fechar()

    # -- escrita -------------------------------------------------------------

    def adicionar_fato(
        self,
        user_id: str,
        conteudo: str,
        *,
        tipo: str = "fato",
        entidade: str = "",
        metadata: Optional[dict[str, Any]] = None,
        origem: str = "",
        ttl_s: Optional[float] = None,
    ) -> MemoryNode:
        """Grava um fato (idempotente) e devolve o nó resultante.

        Regras:
          * mesmo conteúdo ativo do mesmo usuário/tipo/entidade → devolve o
            nó existente, sem duplicar;
          * fato novo com a mesma (user, tipo, entidade) e conteúdo diferente
            → aresta `substitui` do novo para os antigos, que saem da busca;
          * teto de `MAX_FATOS_POR_USUARIO` — os mais antigos são substituídos
            para não crescer sem limite;
          * `ttl_s` marca o fato como efêmero: sai da busca quando expira, sem
            ser apagado (continua no histórico).
        """
        user = (user_id or "").strip()
        if not user:
            raise MemoryLayerError("memória longa exige user_id")
        texto = re.sub(r"\s+", " ", (conteudo or "").strip())[:MAX_CHARS_FATO]
        if not texto:
            raise MemoryLayerError("fato vazio não é memória")
        ent = slug(entidade) if entidade else ""
        agora = float(self._clock())
        expira_em = agora + float(ttl_s) if ttl_s and ttl_s > 0 else None
        meta_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)

        with self._lock:
            try:
                cur = self._conn.execute(
                    """
                    SELECT * FROM memory_nodes AS n
                     WHERE n.user_id = ? AND n.tipo = ? AND n.entidade = ?
                       AND n.conteudo = ?
                       AND (n.expira_em IS NULL OR n.expira_em > ?)
                       AND NOT EXISTS (
                           SELECT 1 FROM memory_edges AS e
                            WHERE e.target = n.id AND e.relacao = ?
                       )
                     LIMIT 1
                    """,
                    (user, tipo, ent, texto, agora, REL_SUBSTITUI),
                )
                linha = cur.fetchone()
                if linha is not None:
                    return MemoryNode.from_row(linha)
                anteriores = self.ativos(
                    user, tipo=tipo, entidade=ent, excluir_conteudo=texto
                )
                node_id = uuid.uuid4().hex
                self._conn.execute(
                    """
                    INSERT INTO memory_nodes
                        (id, user_id, tipo, conteudo, entidade, metadata, origem,
                         created_at, updated_at, expira_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node_id, user, tipo, texto, ent, meta_json, origem or "",
                        agora, agora, expira_em,
                    ),
                )
                if ent:
                    ent_id = self._garantir_entidade(user, ent, agora)
                    self._conectar(node_id, ent_id, REL_MENCIONA, agora)
                for velho in anteriores:
                    self._conectar(node_id, velho.id, REL_SUBSTITUI, agora)
                self._aplicar_teto(user, agora)
                self._conn.commit()
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise MemoryLayerError(f"falha ao gravar memória: {exc}") from exc
        _log.debug(
            f"memoria: fato gravado user={user} tipo={tipo} "
            f"entidade={ent or '-'} substitui={len(anteriores)}"
        )
        return MemoryNode(
            id=node_id, user_id=user, tipo=tipo, conteudo=texto, entidade=ent,
            metadata=dict(metadata or {}), origem=origem or "",
            created_at=agora, updated_at=agora, expira_em=expira_em,
        )

    def salvar(
        self,
        texto: str,
        *,
        user_id: str,
        origem: str = "",
        tipo: str = "",
    ) -> list[MemoryNode]:
        """Extrai fatos de um texto livre e grava todos (escopo do usuário).

        Fato com marcador de tempo relativo ("hoje", "amanhã", "no momento")
        entra como efêmero com TTL de `OD_MEMORY_EFEMERO_DIAS` (padrão 7).
        """
        import os as _os

        try:
            dias = float(_os.environ.get("OD_MEMORY_EFEMERO_DIAS", TTL_EFEMERO_DIAS))
        except ValueError:
            dias = TTL_EFEMERO_DIAS
        salvos: list[MemoryNode] = []
        for fato in extrair_fatos(texto):
            if tipo and fato["tipo"] != tipo:
                continue
            salvos.append(
                self.adicionar_fato(
                    user_id,
                    fato["conteudo"],
                    tipo=fato["tipo"],
                    entidade=fato["entidade"],
                    origem=origem,
                    ttl_s=dias * 86400 if fato.get("efemero") else None,
                )
            )
        return salvos

    # -- leitura -------------------------------------------------------------

    def buscar(
        self,
        user_id: str,
        consulta: str,
        *,
        limite: int = 5,
        semantica: bool = True,
    ) -> list[MemoryNode]:
        """Busca fatos ativos do usuário por sobreposição de termos.

        Pontuação: fração dos termos da consulta presentes no fato/entidade,
        com desempate por recência. Consulta vazia devolve os mais recentes.

        Se NENHUM fato casar por termos e `semantica=True`, tenta o fallback
        por embedding (fase 4) — que é o único jeito de ligar "tenho algum
        animal?" a "tem um cachorro chamado Rex", e é pago: uma chamada de
        API por consulta sem match lexical. O resultado fica em cache pela
        consulta normalizada (fase 4b), inclusive o vazio.
        """
        user = (user_id or "").strip()
        if not user:
            return []
        limite = max(1, min(int(limite or 5), 50))
        ativos = self.ativos(user, limite=MAX_FATOS_POR_USUARIO)
        pedacos_radicais = tokens_busca(consulta)
        if not pedacos_radicais:
            return ativos[:limite]

        def pontuar(node: MemoryNode) -> float:
            texto = tokens_busca(f"{node.entidade} {node.conteudo}")
            if not texto:
                return 0.0
            comum = len(pedacos_radicais & texto)
            if not comum:
                return 0.0
            base = comum / max(1, len(pedacos_radicais))
            # entidade que casa inteira vale mais que palavra solta no conteúdo
            if tokens_busca(node.entidade) & pedacos_radicais:
                base += 0.25
            return base

        pontuados = [(pontuar(n), n) for n in ativos]
        pontuados = [(p, n) for p, n in pontuados if p > 0]
        if not pontuados and semantica:
            return self._busca_semantica(user, consulta, ativos, limite)
        pontuados.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [n for _, n in pontuados[:limite]]

    # -- fallback semântico (fase 4) -----------------------------------------

    def _vetores(
        self, ativos: list[MemoryNode]
    ) -> list[tuple[MemoryNode, list[float]]]:
        """Pares (fato, vetor) dos ativos, embedando e cacheando os que faltam."""
        from array import array

        from core import memory_embeddings as emb

        if not emb.provedor_ativo() or len(ativos) < 3:
            # Com 1-2 fatos a mediana não distingue assunto de ruído: nesse
            # caso o fallback só custaria latência.
            return []
        modelo = emb.modelo()
        ids = [n.id for n in ativos]
        marcadores = ",".join("?" for _ in ids)
        with self._lock:
            try:
                linhas = self._conn.execute(
                    f"SELECT node_id, vetor FROM memory_vectors "
                    f"WHERE modelo = ? AND node_id IN ({marcadores})",
                    (modelo, *ids),
                ).fetchall()
            except sqlite3.Error as exc:  # pragma: no cover — banco estranho
                raise MemoryLayerError(f"falha ao ler vetores: {exc}") from exc
        cache = {
            str(r["node_id"]): array("f", r["vetor"]).tolist() for r in linhas
        }
        faltam = [n for n in ativos if n.id not in cache]
        if faltam:
            vetores = emb.embed_textos([f"{n.entidade} {n.conteudo}" for n in faltam])
            if vetores is None:
                return []
            agora = float(self._clock())
            with self._lock:
                for node, vetor in zip(faltam, vetores):
                    cache[node.id] = vetor
                    self._conn.execute(
                        "INSERT OR REPLACE INTO memory_vectors "
                        "(node_id, modelo, vetor, created_at) VALUES (?, ?, ?, ?)",
                        (node.id, modelo, array("f", vetor).tobytes(), agora),
                    )
                self._conn.commit()
        return [(n, cache[n.id]) for n in ativos if n.id in cache]

    def _busca_semantica(
        self,
        user_id: str,
        consulta: str,
        ativos: list[MemoryNode],
        limite: int,
    ) -> list[MemoryNode]:
        """Top fatos por cosseno, aceitos só com piso E margem sobre a mediana.

        O Gemini devolve ~0,75 de cosseno até para pares sem relação, então
        limiar absoluto sozinho aceitaria qualquer coisa. A regra é: o melhor
        fato precisa estar acima do piso `OD_MEMORY_SEMANTICA_MIN` (0,78) e
        separado da mediana dos fatos por `OD_MEMORY_SEMANTICA_MARGEM` (0,05)
        — medido em 10 consultas do usuário (margem 0,063-0,159) contra 10
        fora de assunto (0,010-0,041).
        """
        try:
            from core import memory_embeddings as emb

            if not emb.provedor_ativo() or len(ativos) < 3:
                return []
            # A assinatura dos ativos entra na chave: fato novo, removido ou
            # atualizado muda a chave e o resultado velho nem é consultado.
            chave = (
                user_id.strip(),
                _normalizar_consulta(consulta),
                emb.modelo(),
                tuple((n.id, n.updated_at) for n in ativos),
            )
            guardados = self._cache_semantico_ler(chave)
            if guardados is not None:
                por_id = {n.id: n for n in ativos}
                return [por_id[i] for i in guardados if i in por_id]
            itens = self._vetores(ativos)
            if len(itens) < 3:
                return []
            vetor_consulta = emb.embed_textos([consulta])
            if not vetor_consulta:
                # Provider falhou: não cacheia o vazio para não envenenar o TTL.
                return []
            notas = sorted(
                ((emb.cosseno(vetor_consulta[0], v), n) for n, v in itens),
                key=lambda item: item[0],
                reverse=True,
            )
            topo = notas[0][0]
            mediana = sorted(n for n, _ in notas)[len(notas) // 2]
            resultado = (
                []
                if topo < emb.minimo() or topo - mediana < emb.margem()
                else [n for _, n in notas[:limite]]
            )
            self._cache_semantico_guardar(chave, [n.id for n in resultado])
            return resultado
        except MemoryLayerError:
            raise
        except Exception as exc:  # noqa: BLE001 — memória nunca derruba o chat
            _log.debug(f"memoria: fallback semântico falhou ({type(exc).__name__})")
            return []

    def _cache_semantico_ler(self, chave: tuple) -> Optional[list[str]]:
        """Ids cacheados para a consulta, ou `None` se ausente/vencido."""
        ttl = _env_float("OD_MEMORY_SEMANTICA_CACHE_S", CACHE_SEMANTICO_TTL_S)
        if ttl <= 0:
            return None
        with self._lock:
            item = self._cache_semantico.get(chave)
            if item is None:
                self._cache_semantico_misses += 1
                return None
            expira_em, ids = item
            if expira_em <= self._clock():
                self._cache_semantico.pop(chave, None)
                self._cache_semantico_misses += 1
                return None
            self._cache_semantico.move_to_end(chave)
            self._cache_semantico_hits += 1
            return list(ids)

    def _cache_semantico_guardar(self, chave: tuple, ids: list[str]) -> None:
        """Guarda o resultado (inclusive vazio) com TTL e teto de entradas."""
        ttl = _env_float("OD_MEMORY_SEMANTICA_CACHE_S", CACHE_SEMANTICO_TTL_S)
        if ttl <= 0:
            return
        with self._lock:
            self._cache_semantico[chave] = (self._clock() + ttl, list(ids))
            self._cache_semantico.move_to_end(chave)
            while len(self._cache_semantico) > CACHE_SEMANTICO_MAX:
                self._cache_semantico.popitem(last=False)

    def ativos(
        self,
        user_id: str,
        *,
        tipo: str = "",
        entidade: str = "",
        excluir_conteudo: str = "",
        limite: int = 100,
    ) -> list[MemoryNode]:
        """Nós vigentes do usuário (exclui entidades e fatos substituídos)."""
        user = (user_id or "").strip()
        if not user:
            return []
        sql = """
            SELECT n.* FROM memory_nodes AS n
             WHERE n.user_id = ? AND n.tipo != 'entidade'
               AND (n.expira_em IS NULL OR n.expira_em > ?)
               AND NOT EXISTS (
                   SELECT 1 FROM memory_edges AS e
                    WHERE e.target = n.id AND e.relacao = ?
               )
        """
        params: list[Any] = [user, float(self._clock()), REL_SUBSTITUI]
        if tipo:
            sql += " AND n.tipo = ?"
            params.append(tipo)
        if entidade:
            sql += " AND n.entidade = ?"
            params.append(slug(entidade))
        if excluir_conteudo:
            sql += " AND n.conteudo != ?"
            params.append(excluir_conteudo)
        sql += " ORDER BY n.created_at DESC, n.rowid DESC LIMIT ?"
        params.append(max(1, int(limite)))
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                return [MemoryNode.from_row(r) for r in cur.fetchall()]
            except sqlite3.Error as exc:
                raise MemoryLayerError(f"falha ao consultar memória: {exc}") from exc

    def historico(self, user_id: str, entidade: str) -> list[MemoryNode]:
        """Todos os fatos da entidade, inclusive substituídos (mais novos antes)."""
        user = (user_id or "").strip()
        ent = slug(entidade)
        if not user:
            return []
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM memory_nodes
                 WHERE user_id = ? AND entidade = ? AND tipo != 'entidade'
                 ORDER BY created_at DESC, rowid DESC
                """,
                (user, ent),
            )
            return [MemoryNode.from_row(r) for r in cur.fetchall()]

    def consolidar(self, user_id: Optional[str] = None) -> dict[str, Any]:
        """Consolidação periódica (F4 fase 3) — roda no timer semanal.

        Duas operações idempotentes:

        1. **Deduplicação:** fatos ativos cujo CONTEÚDO NORMALIZADO coincide
           (caixa/acento/espaço/radical) viram um só — o mais recente fica,
           os outros ganham aresta `substitui` e saem da busca, sem apagar
           nada. Ignora tipo/entidade de propósito: é aqui que entram os
           duplicados gravados por caminhos diferentes (action com entidade
           fixa vs captura automática pela extração).
        2. **Expiração:** fatos com `expira_em <= agora` saem da busca. Eles
           não recebem aresta (podem voltar a ser ditos e viram fato novo);
           a linha continua no banco para auditoria.

        Returns:
            `{"duplicados", "expirados", "usuarios", "agora"}`.
        """
        agora = float(self._clock())
        usuarios: set[str] = set()
        duplicados = 0
        expirados = 0
        with self._lock:
            try:
                if user_id:
                    alvo = [user_id]
                else:
                    alvo = [
                        str(r[0])
                        for r in self._conn.execute(
                            "SELECT DISTINCT user_id FROM memory_nodes"
                        )
                    ]
                for user in alvo:
                    usuarios.add(user)
                    # 1. deduplicação por conteúdo normalizado
                    grupos: dict[str, list[MemoryNode]] = {}
                    for node in self.ativos(user, limite=MAX_FATOS_POR_USUARIO * 2):
                        chave = " ".join(sorted(tokens_busca(node.conteudo)))
                        if not chave:
                            continue
                        grupos.setdefault(chave, []).append(node)
                    for nodes in grupos.values():
                        if len(nodes) < 2:
                            continue
                        nodes.sort(key=lambda n: (n.created_at, n.id))
                        fica = nodes[-1]
                        for velho in nodes[:-1]:
                            self._conectar(fica.id, velho.id, REL_SUBSTITUI, agora)
                            duplicados += 1
                    # 2. expiração dos efêmeros vencidos
                    expirados += self._conn.execute(
                        """
                        UPDATE memory_nodes
                           SET updated_at = ?
                         WHERE user_id = ? AND tipo != 'entidade'
                           AND expira_em IS NOT NULL AND expira_em <= ?
                        """,
                        (agora, user, agora),
                    ).rowcount or 0
                self._conn.commit()
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise MemoryLayerError(f"falha ao consolidar memória: {exc}") from exc
        _log.info(
            f"memoria: consolidação duplicados={duplicados} "
            f"expirados={expirados} usuarios={len(usuarios)}"
        )
        return {
            "duplicados": duplicados,
            "expirados": expirados,
            "usuarios": len(usuarios),
            "agora": agora,
        }

    def vizinhos(self, node_id: str, *, relacao: str = "") -> list[MemoryEdge]:
        """Arestas que saem do nó (opcionalmente filtradas por relação)."""
        sql = "SELECT * FROM memory_edges WHERE source = ?"
        params: list[Any] = [node_id]
        if relacao:
            sql += " AND relacao = ?"
            params.append(relacao)
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [
                MemoryEdge(
                    source=r["source"], target=r["target"], relacao=r["relacao"],
                    peso=float(r["peso"]), created_at=float(r["created_at"]),
                )
                for r in cur.fetchall()
            ]

    def stats(self, user_id: Optional[str] = None) -> dict[str, Any]:
        """Contagens do grafo (globais ou de um usuário)."""
        with self._lock:
            if user_id:
                fatos = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_nodes WHERE user_id = ? AND tipo != 'entidade'",
                    (user_id,),
                ).fetchone()[0]
                ativos = len(self.ativos(user_id, limite=MAX_FATOS_POR_USUARIO))
                entidades = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_nodes WHERE user_id = ? AND tipo = 'entidade'",
                    (user_id,),
                ).fetchone()[0]
                usuarios = 1
            else:
                fatos = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_nodes WHERE tipo != 'entidade'"
                ).fetchone()[0]
                ativos = self._conn.execute(
                    """
                    SELECT COUNT(*) FROM memory_nodes AS n
                     WHERE n.tipo != 'entidade'
                       AND (n.expira_em IS NULL OR n.expira_em > ?)
                       AND NOT EXISTS (
                           SELECT 1 FROM memory_edges AS e
                            WHERE e.target = n.id AND e.relacao = ?
                     )
                    """,
                    (float(self._clock()), REL_SUBSTITUI),
                ).fetchone()[0]
                entidades = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_nodes WHERE tipo = 'entidade'"
                ).fetchone()[0]
                usuarios = self._conn.execute(
                    "SELECT COUNT(DISTINCT user_id) FROM memory_nodes"
                ).fetchone()[0]
            arestas = self._conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
            filtro = "user_id = ? AND " if user_id else ""
            args = (user_id,) if user_id else ()
            agora = float(self._clock())
            efemeros = self._conn.execute(
                f"SELECT COUNT(*) FROM memory_nodes WHERE {filtro}expira_em IS NOT NULL",
                args,
            ).fetchone()[0]
            expirados = self._conn.execute(
                f"SELECT COUNT(*) FROM memory_nodes WHERE {filtro}expira_em IS NOT NULL AND expira_em <= ?",
                (*args, agora),
            ).fetchone()[0]
            vetores = self._conn.execute(
                "SELECT COUNT(*) FROM memory_vectors AS v "
                "JOIN memory_nodes AS n ON n.id = v.node_id"
                + (" WHERE n.user_id = ?" if user_id else ""),
                args,
            ).fetchone()[0]
        return {
            "fatos": int(fatos),
            "ativos": int(ativos),
            "substituidos": int(fatos) - int(ativos),
            "entidades": int(entidades),
            "arestas": int(arestas),
            "usuarios": int(usuarios),
            "efemeros": int(efemeros),
            "expirados": int(expirados),
            "vetores": int(vetores),
            "semantica_cache": {
                "entradas": len(self._cache_semantico),
                "hits": int(self._cache_semantico_hits),
                "misses": int(self._cache_semantico_misses),
            },
            "arquivo": str(self._caminho),
        }

    # -- internos ------------------------------------------------------------

    def _garantir_entidade(self, user_id: str, entidade: str, agora: float) -> str:
        """Cria (ou reaproveita) o nó de entidade do usuário."""
        ent = slug(entidade)
        cur = self._conn.execute(
            "SELECT id FROM memory_nodes WHERE user_id = ? AND tipo = 'entidade' AND entidade = ? LIMIT 1",
            (user_id, ent),
        )
        linha = cur.fetchone()
        if linha is not None:
            return str(linha["id"])
        node_id = uuid.uuid4().hex
        self._conn.execute(
            """
            INSERT INTO memory_nodes
                (id, user_id, tipo, conteudo, entidade, metadata, origem,
                 created_at, updated_at)
            VALUES (?, ?, 'entidade', ?, ?, '{}', '', ?, ?)
            """,
            (node_id, user_id, ent, ent, agora, agora),
        )
        return node_id

    def _conectar(self, source: str, target: str, relacao: str, agora: float) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO memory_edges (source, target, relacao, peso, created_at)
            VALUES (?, ?, ?, 1.0, ?)
            """,
            (source, target, relacao, agora),
        )

    def _aplicar_teto(self, user_id: str, agora: float) -> None:
        """Acima do teto, os fatos ativos mais antigos passam a substituídos."""
        ativos = self.ativos(user_id, limite=MAX_FATOS_POR_USUARIO + 50)
        excedente = len(ativos) - MAX_FATOS_POR_USUARIO
        if excedente <= 0:
            return
        for velho in ativos[-excedente:]:
            substituto = ativos[0].id if ativos else ""
            if substituto and substituto != velho.id:
                self._conectar(substituto, velho.id, REL_SUBSTITUI, agora)


# ---------------------------------------------------------------------------
# Instância compartilhada (usada pelas actions do catálogo)
# ---------------------------------------------------------------------------

_SINGLETON: Optional[MemoryGraph] = None
_SINGLETON_LOCK = threading.Lock()


def obter_memoria(caminho: Optional[str | Path] = None) -> MemoryGraph:
    """Devolve a instância compartilhada (cria no primeiro uso).

    Caminho: `OD_MEMORY_PATH` ou `data/memory.db` na raiz do projeto.
    """
    global _SINGLETON
    if _SINGLETON is not None:
        return _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            import os

            destino = caminho or os.environ.get("OD_MEMORY_PATH") or (
                Path(__file__).resolve().parents[1] / "data" / "memory.db"
            )
            _SINGLETON = MemoryGraph(destino)
    return _SINGLETON


def resetar_memoria() -> None:
    """Fecha e descarta a instância compartilhada (testes/hot-reload)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            _SINGLETON.fechar()
        _SINGLETON = None
