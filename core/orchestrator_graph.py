"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/orchestrator_graph.py
Descrição: Orquestrador como grafo (F1, fase 1) — estado tipado, nós atômicos,
           fan-out paralelo, checkpoint em SQLite e streaming de updates.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F1 (Orchestrator as Graph)
  - LangGraph (StateGraph + checkpointer + astream) — mesmo desenho de API,
    sem a dependência: o projeto não tem langgraph instalado e a suíte é
    stdlib-first.

Architecture:
    `OrchestratorState` é o estado compartilhado entre os nós. Campos de lista
    (messages, active_tools, tool_results, steps) usam reducer de concatenação
    — dois nós no mesmo superstep não perdem update um do outro; os demais
    campos são substituídos pelo último valor.

    Um superstep executa TODOS os nós pendentes com `asyncio.gather`: é o que
    permite fan-out paralelo de tool calls independentes. O resultado de cada
    nó é um dict parcial, mesclado na ordem determinística dos nós.

    `SqliteSaver` grava um checkpoint por superstep (estado + próximos nós) em
    `data/checkpoints.db`. Um restart retoma exatamente do nó pendente, e um
    `pending_human_input` sem decisão pausa o grafo (human-in-the-loop) em vez
    de gerar resposta.

Usage:
    from core.orchestrator_graph import construir_grafo, SqliteSaver

    grafo = construir_grafo(
        classificar=minha_classificacao,
        selecionar=minha_selecao,
        executar=minha_execucao,
        gerar=minha_geracao,
        checkpointer=SqliteSaver("data/checkpoints.db"),
    )
    async for update in grafo.astream(
        {"text": "onde eu moro?", "user_id": "alex"},
        {"configurable": {"thread_id": "sessao-1"}},
    ):
        ...
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Callable, Optional, TypedDict

from core.logger import get_logger

__signature__ = "OD // CORE"

_log = get_logger("omega.core.orchestrator_graph")

START = "__start__"
END = "__end__"
LIMITE_RECURSAO_PADRAO = 50
MAX_CHECKPOINTS_POR_THREAD = 200
VERDADEIROS = {"1", "true", "yes", "on", "sim"}


# ---------------------------------------------------------------------------
# RetryPolicy (F1 fase 5)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RetryPolicy:
    """Política de retentativa para execução de nós.

    Args:
        max_retries: Máximo de tentativas (padrão 2 = 1 original + 2 retries).
        backoff_base: Base do backoff exponencial em segundos (padrão 0.5s).
        backoff_max: Teto do backoff em segundos (padrão 5.0s).
        jitter: Adiciona aleatoriedade ao backoff (padrão True).
        retryable_exceptions: Tupla de tipos de exceção que disparam retry.
                              Padrão: (TimeoutError, ConnectionError, IOError).
        retry_on_timeout: Se True, trata asyncio.TimeoutError como retentável.
    """
    max_retries: int = 2
    backoff_base: float = 0.5
    backoff_max: float = 5.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = (
        TimeoutError,
        ConnectionError,
        IOError,
    )
    retry_on_timeout: bool = True

    def __post_init__(self) -> None:
        self.max_retries = max(0, self.max_retries)
        self.backoff_base = max(0.0, self.backoff_base)
        self.backoff_max = max(self.backoff_base, self.backoff_max)

    def calcular_backoff(self, tentativa: int) -> float:
        """Backoff exponencial com jitter opcional."""
        backoff = min(self.backoff_base * (2 ** tentativa), self.backoff_max)
        if self.jitter:
            backoff *= random.uniform(0.5, 1.5)
        return backoff

    def deve_retry(self, exc: Exception) -> bool:
        """True se a exceção é retentável segundo a política."""
        if self.retry_on_timeout and isinstance(exc, asyncio.TimeoutError):
            return True
        return isinstance(exc, self.retryable_exceptions)


# Políticas padrão por tipo de nó
RETRY_POLITICAS_PADRAO: dict[str, RetryPolicy] = {
    "generate": RetryPolicy(max_retries=2, backoff_base=1.0, backoff_max=10.0),
    "execute_parallel": RetryPolicy(max_retries=1, backoff_base=0.5, backoff_max=3.0),
    "select_tools": RetryPolicy(max_retries=1, backoff_base=0.2, backoff_max=1.0),
    "classify": RetryPolicy(max_retries=1, backoff_base=0.1, backoff_max=0.5),
    "cache_terminal": RetryPolicy(max_retries=0),  # sem retry no cache
    "rate_limit": RetryPolicy(max_retries=0),
    "datetime": RetryPolicy(max_retries=0),
    "quick": RetryPolicy(max_retries=0),
    "infra_guard": RetryPolicy(max_retries=0),
    "post_process": RetryPolicy(max_retries=2, backoff_base=0.5, backoff_max=3.0),
    "human_loop": RetryPolicy(max_retries=0),
}


def _obter_politica_no(nome: str) -> RetryPolicy:
    """Retorna a política de retry para um nó (padrão conservador).

    Suporta override por variável de ambiente:
    `OD_RETRY_<NOME_DONO>=max_retries,backoff_base,backoff_max,jitter`
    Ex: `OD_RETRY_GENERATE=3,2.0,20.0,true`
    """
    base = RETRY_POLITICAS_PADRAO.get(nome, RetryPolicy(max_retries=1))

    # Override por env: OD_RETRY_GENERATE=max_retries,backoff_base,backoff_max,jitter
    env_key = f"OD_RETRY_{nome.upper()}"
    env_val = os.getenv(env_key, "").strip()
    if not env_val:
        return base

    try:
        partes = [p.strip() for p in env_val.split(",")]
        max_retries = int(partes[0]) if len(partes) > 0 and partes[0] else base.max_retries
        backoff_base = float(partes[1]) if len(partes) > 1 and partes[1] else base.backoff_base
        backoff_max = float(partes[2]) if len(partes) > 2 and partes[2] else base.backoff_max
        jitter = partes[3].lower() in VERDADEIROS if len(partes) > 3 and partes[3] else base.jitter
        return RetryPolicy(
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
            jitter=jitter,
            retryable_exceptions=base.retryable_exceptions,
            retry_on_timeout=base.retry_on_timeout,
        )
    except Exception:
        _log.warn("RetryPolicy inválida no env, usando padrão", env=env_key, valor=env_val)
        return base


def habilitado_por_env(variavel: str = "OD_ORCHESTRATOR_GRAPH") -> bool:
    """Flag do grafo: desligada por padrão, sem exigir restart de código."""
    return str(os.getenv(variavel, "")).strip().lower() in VERDADEIROS


class GraphRecursionError(RuntimeError):
    """O grafo passou do `recursion_limit` sem chegar ao END."""


class GraphStateError(RuntimeError):
    """Estado incompatível com o nó (campo obrigatório ausente)."""


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

def somar_listas(a: Optional[list], b: Optional[list]) -> list:
    """Reducer de concatenação: nó paralelo não sobrescreve o vizinho."""
    return [*(a or []), *(b or [])]


class OrchestratorState(TypedDict, total=False):
    """Estado compartilhado do orquestrador (F1).

    `messages` guarda a conversa como dicts (`{"role", "content"}`) para não
    amarrar o núcleo a uma lib de mensagens. Os demais campos são o suficiente
    para as rotas atuais: intenção, ferramentas, resultados, resposta e o
    ponto de pausa para aprovação humana.
    """

    messages: Annotated[list[dict[str, str]], somar_listas]
    user_id: str
    session_id: str
    profile: str
    role: str
    text: str
    intent: str
    active_tools: Annotated[list[str], somar_listas]
    tool_results: Annotated[list[dict[str, Any]], somar_listas]
    steps: Annotated[list[str], somar_listas]
    response: str
    route: str
    pending_human_input: Optional[dict[str, Any]]
    human_decision: Optional[str]
    error: str
    # Pipeline completo (F1 fase 3): rotas terminais e pós-processamento.
    terminal: bool
    registrar: Optional[bool]
    cached: bool
    fallback_used: bool
    llm_used: str
    prompt: str
    pos_processado: bool


REDUTORES: dict[str, Callable[[Any, Any], Any]] = {
    "messages": somar_listas,
    "active_tools": somar_listas,
    "tool_results": somar_listas,
    "steps": somar_listas,
}


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

@dataclass
class Checkpoint:
    """Um passo persistido do grafo."""

    thread_id: str
    passo: int
    estado: dict[str, Any]
    proximos: list[str]
    created_at: float
    concluido: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "passo": self.passo,
            "estado": dict(self.estado),
            "proximos": list(self.proximos),
            "concluido": self.concluido,
            "created_at": self.created_at,
        }


_SCHEMA_CHECKPOINT = """
CREATE TABLE IF NOT EXISTS od_graph_checkpoints (
    thread_id  TEXT NOT NULL,
    passo      INTEGER NOT NULL,
    estado     TEXT NOT NULL,
    proximos   TEXT NOT NULL,
    created_at REAL NOT NULL,
    concluido  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (thread_id, passo)
);
CREATE INDEX IF NOT EXISTS idx_od_graph_thread ON od_graph_checkpoints(thread_id, passo);
"""


class SqliteSaver:
    """Checkpointer em SQLite — retoma o grafo do último superstep."""

    def __init__(self, caminho: str | Path = "data/checkpoints.db") -> None:
        self._caminho = Path(caminho)
        self._lock = threading.RLock()
        if str(self._caminho) != ":memory:":
            self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._caminho), check_same_thread=False, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        # Checkpoint não é dado de negócio: WAL + NORMAL troca fsync por
        # sobrevivência a crash do processo (perder o último passo num crash
        # de SO só custa retomar do anterior).
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA_CHECKPOINT)
        # Bancos criados antes da fase 4 não têm `concluido`: migra sem perder
        # histórico (o passo antigo fica marcado como incompleto e é retomado).
        colunas = {
            str(linha["name"])
            for linha in self._conn.execute(
                "PRAGMA table_info(od_graph_checkpoints)"
            ).fetchall()
        }
        if "concluido" not in colunas:
            self._conn.execute(
                "ALTER TABLE od_graph_checkpoints ADD COLUMN "
                "concluido INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()

    def put(
        self,
        thread_id: str,
        passo: int,
        estado: dict[str, Any],
        proximos: list[str],
        *,
        concluido: bool = False,
    ) -> None:
        """Grava (ou substitui) o checkpoint de um passo."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO od_graph_checkpoints "
                "(thread_id, passo, estado, proximos, created_at, concluido) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    int(passo),
                    json.dumps(estado, ensure_ascii=False, default=str),
                    json.dumps(list(proximos), ensure_ascii=False),
                    time.time(),
                    1 if concluido else 0,
                ),
            )
            # Teto por thread: histórico de auditoria, não despejo infinito.
            self._conn.execute(
                "DELETE FROM od_graph_checkpoints WHERE thread_id = ? AND passo NOT IN ("
                "SELECT passo FROM od_graph_checkpoints WHERE thread_id = ? "
                "ORDER BY passo DESC LIMIT ?)",
                (thread_id, thread_id, MAX_CHECKPOINTS_POR_THREAD),
            )
            self._conn.commit()

    def ultimo(self, thread_id: str) -> Optional[Checkpoint]:
        """Último checkpoint da thread, ou `None`."""
        with self._lock:
            linha = self._conn.execute(
                "SELECT * FROM od_graph_checkpoints WHERE thread_id = ? "
                "ORDER BY passo DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self._linha(linha) if linha is not None else None

    def historico(self, thread_id: str) -> list[Checkpoint]:
        """Checkpoints da thread em ordem crescente de passo."""
        with self._lock:
            linhas = self._conn.execute(
                "SELECT * FROM od_graph_checkpoints WHERE thread_id = ? ORDER BY passo",
                (thread_id,),
            ).fetchall()
        return [self._linha(l) for l in linhas]

    @staticmethod
    def _linha(linha: sqlite3.Row) -> Checkpoint:
        try:
            estado = json.loads(linha["estado"])
            proximos = json.loads(linha["proximos"])
        except (TypeError, ValueError):  # pragma: no cover — banco corrompido
            estado, proximos = {}, []
        return Checkpoint(
            thread_id=str(linha["thread_id"]),
            passo=int(linha["passo"]),
            estado=dict(estado or {}),
            proximos=[str(n) for n in (proximos or [])],
            created_at=float(linha["created_at"]),
            concluido=bool(linha["concluido"]),
        )

    def fechar(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover — já fechado
                pass

    def __enter__(self) -> "SqliteSaver":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.fechar()


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------

NoFn = Callable[[dict[str, Any]], Any]
RoteadorFn = Callable[[dict[str, Any]], Any]


class StateGraph:
    """Builder mínimo no estilo LangGraph (nós, edges, rotas condicionais)."""

    def __init__(
        self,
        state_type: type = OrchestratorState,
        *,
        reducers: Optional[dict[str, Callable[[Any, Any], Any]]] = None,
    ) -> None:
        self.state_type = state_type
        self.reducers = dict(REDUTORES if reducers is None else reducers)
        self.nodes: dict[str, NoFn] = {}
        self.edges: dict[str, list[str]] = {}
        self.conditional: list[tuple[str, RoteadorFn, dict[str, str]]] = []
        self.entry: Optional[str] = None

    def add_node(self, nome: str, fn: NoFn) -> "StateGraph":
        if nome in {START, END}:
            raise ValueError(f"nome de nó reservado: {nome}")
        self.nodes[nome] = fn
        return self

    def add_edge(self, origem: str, destino: str) -> "StateGraph":
        self.edges.setdefault(origem, []).append(destino)
        if origem == START:
            self.entry = destino
        return self

    def add_conditional_edges(
        self,
        origem: str,
        roteador: RoteadorFn,
        mapa: Optional[dict[str, str]] = None,
    ) -> "StateGraph":
        if origem != START and origem not in self.nodes:
            raise ValueError(f"origem desconhecida: {origem}")
        self.conditional.append((origem, roteador, dict(mapa or {})))
        return self

    def compile(self, checkpointer: Optional[SqliteSaver] = None) -> "CompiledGraph":
        if self.entry is None:
            raise ValueError("grafo sem entrada: use add_edge(START, '<nó>')")
        return CompiledGraph(
            nodes=dict(self.nodes),
            edges={k: list(v) for k, v in self.edges.items()},
            conditional=list(self.conditional),
            entry=self.entry,
            reducers=dict(self.reducers),
            checkpointer=checkpointer,
        )


class CompiledGraph:
    """Executa supersteps; cada nó devolve um update parcial do estado."""

    def __init__(
        self,
        *,
        nodes: dict[str, NoFn],
        edges: dict[str, list[str]],
        conditional: list[tuple[str, RoteadorFn, dict[str, str]]],
        entry: str,
        reducers: dict[str, Callable[[Any, Any], Any]],
        checkpointer: Optional[SqliteSaver],
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.conditional = conditional
        self.entry = entry
        self.reducers = reducers
        self.checkpointer = checkpointer

    # -- estado ------------------------------------------------------------

    def _mesclar(self, estado: dict[str, Any], update: Any, nome: str) -> None:
        if update is None:
            return
        if not isinstance(update, dict):
            raise GraphStateError(f"nó {nome} devolveu {type(update).__name__}, esperado dict")
        for chave, valor in update.items():
            redutor = self.reducers.get(chave)
            if redutor is not None:
                estado[chave] = redutor(estado.get(chave), valor)
            else:
                estado[chave] = valor

    def _proximos(self, estado: dict[str, Any], nos: list[str]) -> list[str]:
        destino: list[str] = []
        for nome in nos:
            destino.extend(e for e in self.edges.get(nome, []) if e != END)
        for origem, roteador, mapa in self.conditional:
            if origem not in nos:
                continue
            saida = roteador(dict(estado))
            opcoes = saida if isinstance(saida, (list, tuple, set)) else [saida]
            for opcao in opcoes:
                alvo = mapa.get(str(opcao), str(opcao))
                if alvo in {END, ""}:
                    continue
                if alvo not in self.nodes:
                    raise GraphStateError(f"rota {opcao!r} aponta para nó inexistente: {alvo}")
                destino.append(alvo)
        vistos: list[str] = []
        for nome in destino:
            if nome not in vistos:
                vistos.append(nome)
        return vistos

    # -- execução ----------------------------------------------------------

    async def _executar_no(self, nome: str, estado: dict[str, Any]) -> Any:
        """Executa um nó com política de retry.

        Aplica RetryPolicy específica do nó: retry exponencial com jitter
        para exceções transient (timeout, conexão, I/O). Loga cada retry.
        """
        fn = self.nodes[nome]
        politica = _obter_politica_no(nome)

        for tentativa in range(politica.max_retries + 1):
            try:
                retorno = fn(estado)
                if inspect.isawaitable(retorno):
                    return await retorno
                return retorno
            except Exception as exc:
                if tentativa >= politica.max_retries:
                    _log.error(
                        "Nó falhou após retries",
                        no=nome,
                        tentativas=tentativa + 1,
                        erro=f"{type(exc).__name__}: {exc}",
                    )
                    raise
                if not politica.deve_retry(exc):
                    _log.warn(
                        "Nó falhou com exceção não retentável",
                        no=nome,
                        erro=f"{type(exc).__name__}: {exc}",
                    )
                    raise
                backoff = politica.calcular_backoff(tentativa)
                _log.warn(
                    "Retry no nó",
                    no=nome,
                    tentativa=tentativa + 1,
                    max_retries=politica.max_retries,
                    backoff_s=round(backoff, 3),
                    erro=f"{type(exc).__name__}: {exc}",
                )
                await asyncio.sleep(backoff)
        # Não deveria chegar aqui
        raise RuntimeError(f"Retry logic falhou para nó {nome}")

    async def astream(
        self,
        entrada: Optional[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
        *,
        resume: bool = False,
    ):
        """Executa o grafo e rende um update por superstep.

        `config["configurable"]["thread_id"]` liga o checkpoint. Com
        `resume=True`, o estado e os nós pendentes vêm do último checkpoint
        (é o que permite retomar depois de restart ou aprovação humana).
        """
        cfg = dict(config or {})
        thread_id = str((cfg.get("configurable") or {}).get("thread_id") or "")
        limite = int(cfg.get("recursion_limit") or LIMITE_RECURSAO_PADRAO)
        estado: dict[str, Any] = {}
        passo = 0
        proximos: list[str] = [self.entry]
        carregado = False

        if resume and self.checkpointer is not None and thread_id:
            salvo = self.checkpointer.ultimo(thread_id)
            if salvo is not None:
                estado = dict(salvo.estado)
                proximos = list(salvo.proximos)
                passo = salvo.passo
                carregado = True
        elif entrada is not None:
            estado = dict(entrada)

        # Retomar thread já concluída não deve reescrevê-la como incompleta.
        if self.checkpointer is not None and thread_id and not (carregado and not proximos):
            self.checkpointer.put(thread_id, passo, estado, proximos)

        if not proximos:
            # Thread já concluída: `resume` devolve o estado final salvo.
            yield {
                "passo": passo,
                "nos": [],
                "proximos": [],
                "estado": dict(estado),
            }
            return

        while proximos:
            if passo >= limite:
                raise GraphRecursionError(
                    f"grafo excedeu recursion_limit={limite} na thread {thread_id or '-'}"
                )
            executados = list(proximos)
            saidas = await asyncio.gather(
                *(self._executar_no(nome, dict(estado)) for nome in executados)
            )
            for nome, saida in zip(executados, saidas):
                self._mesclar(estado, saida, nome)

            proximos = self._proximos(estado, executados)
            passo += 1
            pendente = estado.get("pending_human_input")
            interrompido = bool(pendente) and not estado.get("human_decision")
            if interrompido:
                # Pausa ANTES de consumir a decisão humana: o checkpoint aponta
                # para o nó de human_loop, então retomar não perde o ponto.
                if "human_loop" in self.nodes:
                    proximos = ["human_loop"]
                if self.checkpointer is not None and thread_id:
                    self.checkpointer.put(thread_id, passo, estado, proximos)
                yield {
                    "__interrupt__": {
                        "thread_id": thread_id,
                        "passo": passo,
                        "pendente": pendente,
                    },
                    "estado": dict(estado),
                }
                return

            if self.checkpointer is not None and thread_id:
                self.checkpointer.put(
                    thread_id,
                    passo,
                    estado,
                    proximos,
                    concluido=not proximos,
                )
            yield {
                "passo": passo,
                "nos": executados,
                "proximos": list(proximos),
                "estado": dict(estado),
            }
            if not proximos:
                return

    async def ainvoke(
        self,
        entrada: Optional[dict[str, Any]],
        config: Optional[dict[str, Any]] = None,
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Roda até o fim (ou até a pausa humana) e devolve o estado final."""
        estado: dict[str, Any] = dict(entrada or {})
        async for evento in self.astream(entrada, config, resume=resume):
            estado = dict(evento.get("estado") or estado)
        return estado

    def retomar(self, thread_id: str, atualizacoes: dict[str, Any]) -> dict[str, Any]:
        """Aplica a decisão humana no último checkpoint e devolve o estado."""
        if self.checkpointer is None:
            raise GraphStateError("retomar exige checkpointer")
        salvo = self.checkpointer.ultimo(thread_id)
        if salvo is None:
            raise GraphStateError(f"thread sem checkpoint: {thread_id}")
        estado = dict(salvo.estado)
        estado.update(atualizacoes)
        self.checkpointer.put(thread_id, salvo.passo, estado, list(salvo.proximos))
        return estado


# ---------------------------------------------------------------------------
# Nós atômicos do orquestrador (F1)
# ---------------------------------------------------------------------------

def criar_nos(
    *,
    classificar: Callable[[dict[str, Any]], Any],
    selecionar: Callable[[dict[str, Any]], Any],
    executar: Callable[[str, dict[str, Any]], Any],
    gerar: Callable[[dict[str, Any]], Any],
    humano: Optional[Callable[[dict[str, Any]], Any]] = None,
    max_paralelo: int = 4,
) -> dict[str, NoFn]:
    """Monta os cinco nós da §F1 em cima de funções injetadas.

    `executar` recebe (ferramenta, estado); as ferramentas do mesmo superstep
    rodam em paralelo com teto `max_paralelo`. Nenhuma função é chamada aqui:
    só no `astream`, o que mantém a montagem testável.
    """

    async def no_classify(estado: dict[str, Any]) -> dict[str, Any]:
        intencao = classificar(dict(estado))
        if inspect.isawaitable(intencao):
            intencao = await intencao
        return {"intent": str(intencao or ""), "steps": ["classify"]}

    async def no_select(estado: dict[str, Any]) -> dict[str, Any]:
        ferramentas = selecionar(dict(estado))
        if inspect.isawaitable(ferramentas):
            ferramentas = await ferramentas
        if isinstance(ferramentas, dict):
            # O seletor pode pausar o turno (ex.: ação sensível aguardando
            # aprovação humana) devolvendo o próprio update de estado.
            update = dict(ferramentas)
            update["steps"] = ["select_tools"]
            return update
        return {"active_tools": list(ferramentas or []), "steps": ["select_tools"]}

    async def no_execute(estado: dict[str, Any]) -> dict[str, Any]:
        ferramentas = list(estado.get("active_tools") or [])
        if not ferramentas:
            return {"steps": ["execute_parallel"]}
        limite = asyncio.Semaphore(max(1, int(max_paralelo)))

        async def rodar(ferramenta: str) -> dict[str, Any]:
            async with limite:
                if inspect.iscoroutinefunction(executar):
                    saida = await executar(ferramenta, dict(estado))
                else:
                    # Função síncrona vai para thread: o gather só paraleliza
                    # de verdade se ninguém bloquear o event loop.
                    saida = await asyncio.to_thread(executar, ferramenta, dict(estado))
                    if inspect.isawaitable(saida):
                        saida = await saida
            return {"tool": ferramenta, "output": saida}

        resultados = await asyncio.gather(*(rodar(f) for f in ferramentas))
        return {"tool_results": list(resultados), "steps": ["execute_parallel"]}

    async def no_generate(estado: dict[str, Any]) -> dict[str, Any]:
        resposta = gerar(dict(estado))
        if inspect.isawaitable(resposta):
            resposta = await resposta
        if isinstance(resposta, dict):
            # Permite o gerador pedir aprovação humana no mesmo passo.
            update = dict(resposta)
            update["steps"] = ["generate", *(update.get("steps") or [])]
            return update
        return {"response": str(resposta or ""), "steps": ["generate"]}

    async def no_human(estado: dict[str, Any]) -> dict[str, Any]:
        if estado.get("pending_human_input") and estado.get("human_decision"):
            # Decisão já aplicada por `retomar`: só fecha a pausa.
            return {"pending_human_input": None, "steps": ["human_loop"]}
        if humano is not None and estado.get("pending_human_input"):
            decisao = humano(dict(estado))
            if inspect.isawaitable(decisao):
                decisao = await decisao
            if decisao is not None:
                return {
                    "human_decision": str(decisao),
                    "pending_human_input": None,
                    "steps": ["human_loop"],
                }
        return {"steps": ["human_loop"]}

    return {
        "classify": no_classify,
        "select_tools": no_select,
        "execute_parallel": no_execute,
        "generate": no_generate,
        "human_loop": no_human,
    }


def rota_por_intencao(estado: dict[str, Any]) -> str:
    """Intenção com ferramenta vai para a seleção; o resto gera direto.

    Aceita `tools` (fallback da casa) e `tool` (STRATEGY_TOOL do Query
    Router) — o classificador devolve a estratégia e ela caía em `generate`.
    """
    intent = estado.get("intent", "chat")
    if intent in ("tools", "tool"):
        return "select_tools"
    return "generate"


def construir_grafo(
    *,
    classificar: Callable[[dict[str, Any]], Any],
    selecionar: Callable[[dict[str, Any]], Any],
    executar: Callable[[str, dict[str, Any]], Any],
    gerar: Callable[[dict[str, Any]], Any],
    humano: Optional[Callable[[dict[str, Any]], Any]] = None,
    checkpointer: Optional[SqliteSaver] = None,
    max_paralelo: int = 4,
) -> CompiledGraph:
    """Compila o grafo da §F1: classify → tools → generate → human_loop."""
    builder = StateGraph(OrchestratorState, reducers=REDUTORES)
    for nome, fn in criar_nos(
        classificar=classificar,
        selecionar=selecionar,
        executar=executar,
        gerar=gerar,
        humano=humano,
        max_paralelo=max_paralelo,
    ).items():
        builder.add_node(nome, fn)
    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        rota_por_intencao,
        {"select_tools": "select_tools", "generate": "generate"},
    )
    builder.add_edge("select_tools", "execute_parallel")
    builder.add_edge("execute_parallel", "generate")
    builder.add_edge("generate", "human_loop")
    builder.add_conditional_edges("human_loop", lambda _estado: END)
    return builder.compile(checkpointer=checkpointer)
