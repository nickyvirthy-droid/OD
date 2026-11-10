# ANÁLISE GERAL DO SISTEMA OMEGA DRAKON — 10/11/2026

> **Objetivo:** Identificar gargalos, modernizar arquitetura, incorporar estado-da-arte (2024-2025), tornar o sistema **mais rápido, mais inteligente, mais observável, mais resiliente**.
> **Metodologia:** Análise do código atual (60 módulos core/tools, ~18k LOC) + pesquisa de melhores práticas 2024-2025 (LangGraph, Mem0/Zep, OpenTelemetry, Harmonia/RAGO, semantic caching, checkpointing, human-in-the-loop).
> **Resultado:** TODO priorizado para execução incremental ("devagar").

---

## 1. RESUMO EXECUTIVO DO ESTADO ATUAL

| Dimensão | Estado Atual | Gap Principal |
|----------|--------------|---------------|
| **Orquestração** | `orchestrator.py` monolítico (2285 linhas), loop síncrono, sem checkpointing | Sem durabilidade, sem resumo pós-falha, sem paralelismo controlado |
| **Memória** | **F4 completo (fases 1–4):** grafo temporal de fatos/entidades em `data/memory.db` (substituição sem apagar), ações `salvar_fato`/`buscar_memoria`, captura automática no chat, bloco no prompt (recall 90% → 100% com vetor), consolidação semanal e expiração de efêmero; resultado semântico cacheado por consulta normalizada | Histórico de chat segue em 20 mensagens por perfil; a primeira consulta sem match lexical ainda paga ~0,4 s (repetição: ~0,7 ms) |
| **RAG** | Embedding local + busca vetorial simples, cache LLM básico | Sem semantic caching, sem hybrid search, sem otimização KV-cache, latência não medida |
| **Observabilidade** | **F2 entregue:** `core/telemetry.py` (OTel spans + métricas), log com `trace_id`/`span_id`, checks `telemetria` e `latencia` no `/health` | Sem coletor OTel/Grafana (infra) nem alertas — o código já exporta para o endpoint que for configurado |
| **Resiliência** | **R2 entregue:** `core/resilience.py` com disjuntor por provider de LLM e degradação via fallback | Sem task queue (R1) nem retry policy declarativo; bulkhead dispensado por falta de pool saturado medido |
| **Performance** | **F3 encerrado:** gargalos reais medidos e corrigidos (cache do APK, fila de listen); sonda contínua de p50/p95 | Sem async I/O — descartado com medição (thread-por-requisição); connection pooling sem demanda medida |
| **Segurança** | Security Layer (scope, permissions, approval) | Sem sandbox real para plugins, sem supply chain verification além Ed25519 |
| **Developer Experience** | Canal de dev on-demand, testes 4241 passed | Sem hot-reload de código, sem time-travel debugging, sem eval framework |

---

## 2. TODO PRIORIZADO (MATRIZ IMPACTO × ESFORÇO)

### 🔴 CRÍTICO — Fundação (fazer primeiro, habilita o resto)

| ID | Item | Esforço | Impacto | Referência |
|----|------|---------|---------|------------|
| **F1** | **Migrar orquestrador para grafo de execução (LangGraph-style)** | Alto | 🔥🔥🔥 | LangGraph blog 2024-2025: checkpointing, parallelization, streaming, human-in-the-loop, task queue, tracing nativo |
| **F2** | ~~Implementar OpenTelemetry distribuído (traces + metrics + logs correlacionados)~~ **ENTREGUE (10/11)**: SDK + spans + métricas + log correlacionado + check no `/health`; falta só o coletor/Grafana (infra) — ver §3 | Médio | 🔥🔥🔥 | python-observability.com, structlog + OTel + BatchSpanProcessor |
| **F3** | ~~Substituir I/O síncrono por async em todo o core~~ **ENCERRADO (10/11)** com escopo revisado por medição: o problema real era trabalho de CPU no handler e backlog de socket — ver §3 | Alto → Baixo | 🔥🔥 | `aiohttp`, `asyncpg`, `asyncio.to_thread` para bloqueantes |
| **F4** | **Memory Layer estruturada (Mem0/Zep-style: grafo temporal + consolidação)** — **fases 1–4 ENTREGUES (10/11)**: grafo temporal em SQLite, extração determinística, 2 actions, bloco de memória no prompt (recall@5 0% → 90%), consolidação semanal com expiração de efêmero e busca semântica sob demanda (**recall@5 9/10 → 10/10**, 0 falsos positivos) (§3) | Alto → Médio | 🔥🔥🔥 | Mem0 (arXiv 2504.19413), Zep (arXiv 2501.13956), LOCOMO/LongMemEval |

### 🟡 ALTO — Inteligência & Performance

| ID | Item | Esforço | Impacto | Referência |
|----|------|---------|---------|------------|
| **I1** | **Semantic Caching no RAG (Redis + vector similarity ≥0.95)** | Médio | 🔥🔥 | Vector DB optimization blog (60% latency reduction), RAGO/Harmonia |
| **I2** | **Hybrid Search (BM25 + dense + reranker) + metadata filtering** | Médio | 🔥🔥 | AWS Generative AI Atlas, RAG performance tuning |
| **I3** | **KV-Cache optimization para geração (prefix reuse, cross-layer sharing)** | Alto | 🔥 | CacheGen, FastCache, MiniCache (arXiv 2024-2025) |
| **I4** | **Query Routing / Classificação de intenção antes do RAG** | Baixo | 🔥🔥 | RAG in Production: router decide strategy per query type |
| **I5** | **Streaming de tokens (SSE/WebSocket) para chat** | Médio | 🔥🔥 | LangGraph 6 stream modes, perceived latency reduction |
| **I6** | **Batch/async embedding generation (sentence-transformers + ONNX)** | Médio | 🔥 | BGE embeddings faster than OpenAI, connection pooling |

### 🟢 MÉDIO — Resiliência & DX

| ID | Item | Esforço | Impacto | Referência |
|----|------|---------|---------|------------|
| **R1** | **Task Queue durável (Redis/RQ ou Celery) + RetryPolicy declarativo** | Médio | 🔥🔥 | LangGraph Platform, circuit breaker pattern |
| **R2** | ~~Circuit Breaker + Bulkhead + Graceful Degradation~~ **ENTREGUE (10/11)**: disjuntor por provider de LLM, degradação graciosa pelo fallback existente; bulkhead não aplicável hoje — ver §3 | Baixo | 🔥 | Resilience4j patterns, AWS Well-Architected |
| **R3** | **Hot-reload de ferramentas/plugins sem reiniciar od-core** | Médio | 🔥 | PluginManager já tem reload, integrar com watchdog |
| **R4** | **Time-travel debugging (checkpoint replay) para orquestrador** | Alto | 🔥 | LangGraph checkpointing + time travel |
| **R5** | **Eval Framework automatizado (LOCOMO/LongMemEval + custom)** | Médio | 🔥🔥 | Letta Leaderboard, Zep benchmarks, benchmarking contínuo |

### 🔵 BAIXO — Polimento & Futuro

| ID | Item | Esforço | Impacto |
|----|------|---------|---------|
| **P1** | Multi-tenancy real (isolamento por `OD_ACCOUNT_ALIASES` + vector DB namespaces) | Alto | 🔥 |
| **P2** | Plugin sandbox real (gVisor/Firecracker/WASM) | Muito Alto | 🔥 |
| **P3** | Auto-scaling horizontal (K8s HPA + metrics customizadas) | Alto | 🔥 |
| **P4** | Supply chain security (SBOM, cosign, SLSA) | Médio | 🔥 |
| **P5** | UI/UX: painel admin em React/Next.js (substituir HTML servido) | Alto | 🔥 |

---

## 3. DETALHAMENTO DOS ITENS CRÍTICOS

### F1 — Orquestrador como Grafo (LangGraph-style)
**Por que:** Orchestrator atual (2285 linhas) é um loop monolítico, sem checkpointing, sem paralelismo seguro, sem resumo pós-falha, sem human-in-the-loop.

**Arquitetura alvo:**
```python
# Estado compartilhado tipado
class OrchestratorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    active_tools: list[str]
    pending_human_input: Optional[HumanInput]
    checkpoints: list[Checkpoint]

# Nós = unidades de trabalho atômicas
def node_intent_classification(state): ...
def node_tool_selection(state): ...
def node_tool_execution(state): ...
def node_response_generation(state): ...
def node_human_in_the_loop(state): ...

# Grafo com edges condicionais + paralelos
builder = StateGraph(OrchestratorState)
builder.add_node("classify", node_intent_classification)
builder.add_node("select_tools", node_tool_selection)
builder.add_node("execute_parallel", parallel_tool_execution)  # fan-out
builder.add_node("generate", node_response_generation)
builder.add_node("human_loop", node_human_in_the_loop)
builder.add_edge(START, "classify")
builder.add_conditional_edges("classify", route_by_intent)
builder.add_edge("execute_parallel", "generate")
builder.add_edge("generate", "human_loop")
builder.add_conditional_edges("human_loop", route_after_human)

# Checkpointing automático (MsgPack, encriptado opcional)
checkpointer = SqliteSaver("data/checkpoints.db")
graph = builder.compile(checkpointer=checkpointer)
```

**Benefícios mensuráveis:**
- Paralelização segura de tool calls independentes (até 3-5x speedup)
- Resumo exato do ponto de falha (checkpoint a cada nó)
- Human-in-the-loop nativo (aprovar/rejeitar/editar ação)
- Streaming nativo (tokens, node updates, custom events)
- Tracing automático (cada nó = span OTel)

### F2 — OpenTelemetry Completo
**Stack:** `opentelemetry-sdk` + `opentelemetry-instrument` + `structlog` + `prometheus-client` (multiprocess) + OTel Collector → Grafana (Tempo + Loki + Prometheus)

**Instrumentação mínima:**
```python
# core/telemetry.py
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# Provider global
provider = TracerProvider(resource=Resource.create({
    "service.name": "omega-drakon",
    "service.version": "1.44.0",
    "deployment.environment": "production",
}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)

# Auto-instrumentação
AsyncioInstrumentor().instrument()
AioHttpClientInstrumentor().instrument()
RequestsInstrumentor().instrument()

# Structlog com trace correlation
import structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

# Uso: logger.info("evento", trace_id=trace.get_current_span().get_span_context().trace_id)
```

#### F2 — FECHAMENTO (2026-11-10)

**Status: entregue a fatia de software; resta a infraestrutura** (coletor +
Grafana), que depende de decisão de hospedagem e não de código.

| Peça | O que entrou |
|---|---|
| `core/telemetry.py` | `configurar()` idempotente, `span()`, `cronometrar()`, `contar()`, `atribuir()`, `trace_id()`/`span_id()`, `status()`, `desligar()`. Providers no estado do módulo — os globais do OTel aceitam só a primeira configuração do processo, o que quebraria testes e hot-reload. |
| `core/logger.py` | `trace_id`/`span_id` do span ativo anexados à linha (texto ou JSON); nada inventado fora de span. |
| `integrations/api/server.py` | Span `http.request` + `od.http_request.seconds` + `od.http_requests` por chamada. |
| `memory/rag.py` | `RAGPipeline.consult` → span `rag.consult` + histograma `od.rag_retrieval.seconds`. |
| `runtime/launcher.py` | `telemetry.configurar()` no `main()` e check não-crítico `telemetria` (desligada = ok; SDK ausente = degraded). |
| `tests/test_telemetry.py` | +15 testes, incluindo exportador em memória e no-op sem SDK. |
| Commit / gate | `c65223e`; **4212 passed / 16 skipped / 0 falha** (189,29 s). |

**Desvios do plano original, com o motivo:**

| Plano | O que foi feito e por quê |
|---|---|
| `structlog` | Mantido o log NICKY (`core/logger.py`): já é JSON/texto estruturado e tem 4.200 testes em cima. Trocar a lib não daria observabilidade nova — a correlação foi feita no formato existente. |
| `opentelemetry-instrument` (auto) | Instrumentação manual nos 3 pontos que importam (HTTP, RAG, log). A auto-instrumentação de `requests`/`aiohttp`/`asyncio` pressupõe o stack async do F3, que foi descartado por medição. |
| `prometheus-client` multiprocess | Métricas via MeterProvider do próprio OTel; expor `/metrics` exigiria servidor separado ou promiscuidade na API. Fica junto com a decisão do coletor. |
| `opentelemetry-sdk` como dependência fixa | Import tardio + no-op: sem a dependência o core segue de pé, e o item é opcional em `requirements.txt`. |

**Falta (infra, não código):** OTel Collector configurado, dashboards
Tempo/Loki/Prometheus e os alertas de p95/error rate. Quando o coletor
existir, basta apontar `OD_OTEL_ENDPOINT` — nada de código muda.

**Métricas-chave (Prometheus):**
| Métrica | Tipo | Target |
|---------|------|--------|
| `orchestrator_cycle_duration_seconds` | Histogram | p95 < 2s |
| `rag_retrieval_latency_seconds` | Histogram | p95 < 500ms |
| `llm_generation_latency_seconds` | Histogram | p95 < 3s |
| `cache_hit_rate` | Gauge | > 30% |
| `active_sessions` | Gauge | — |
| `error_rate` | Counter | < 0.1% |

### F3 — Async I/O em Todo o Core

> **Auditoria de 2026-11-10 (antes de migrar):** o diagnóstico abaixo estava
> desatualizado. Medido no código e no serviço vivo:
>
> | Premissa | Realidade |
> |---|---|
> | `requests` bloqueante em `downloads.py` | Não existe: `downloads.py` usa `urllib` **dentro de um worker thread próprio** (fila + `Condition`); o loop nunca é tocado. |
> | `requests` bloqueante em `notifier.py` | Não existe: já usa `asyncio.to_thread` para `subprocess`. |
> | `requests` bloqueante em `auto_update.py` | Não existe: já é `asyncio`. `requests` segue no `requirements.txt` só para ferramentas locais. |
> | "bloquear o event loop" | Não há loop compartilhado: a API é `ThreadingHTTPServer` (thread por request) e cada handler faz seu `asyncio.run()`. I/O bloqueante atrasa **aquela** requisição, não o servidor. |
>
> Custo real medido: criar um loop novo por chamada = **~130 µs** (ruído frente
> a qualquer handler). O risco verdadeiro é **trabalho pesado dentro do
> handler** — e havia um: `/app/version` relia e re-hashava o APK de 72 MB a
> cada chamada. Linha de base (`tools/monitor/io_probe.py`, 8 threads):
> p50 **174,15 ms**, p95 183,19 ms, **20,0 req/s**; `/health` p50 7,75 ms.
> Depois do cache por (mtime, tamanho): p50 **0,81 ms**, p95 1,01 ms,
> **182,7 req/s** (215× e 9×).
>
> **Escopo revisado do F3:** em vez de trocar `requests`→`aiohttp` (não há o
> que trocar), caçar trabalho bloqueante/CPU no caminho de requisição com a
> sonda como régua, e só então decidir pooling/async onde houver ganho medido.
>
> **Fatia 2 (mesmo dia) — varredura dos suspeitos restantes:**
>
> | Alvo | Medido | Ação |
> |---|---|---|
> | `GET /site/` e `/site/logo.png` | p50 0,95 / 1,56 ms, mas **máx 1.031 ms** com 200 conexões | **Corrigido:** `request_queue_size` era o padrão do `socketserver` (**5**) — backlog de listen estourava e o kernel reenviava SYN. Subiu para 128: máx 1.031 → **20,16 ms**, vazão 186 → **995 req/s** (5,3×); com 400 conexões/32 threads, máx 35,93 ms e 1.127 req/s. |
> | `GET /health` (sem cache, TTL 8 s) | p50 **18,08 ms**, máx 46,44 ms para 26 checks | Sem ação — o cache de 8 s já protege os chips do herói e o limiter. |
> | `POST /auth/login` | **158,5 ms** por verificação (PBKDF2-SHA256, 260k iterações) | Sem ação — custo deliberado contra força-bruta, atrás do limiter de 30 req/min. Só trocar por Argon2id se um dia entrar dependência. |
>
> Nenhum dos três precisa de `async`: a API é thread-por-requisição e o custo
> real estava em configuração de socket e em trabalho de CPU no handler.

#### F3 — FECHAMENTO (2026-11-10)

**Status: encerrado.** O item foi executado como auditoria medida, não como
migração em massa, porque o diagnóstico original não sobreviveu à medição.
Entregas e seus números:

| # | Entrega | Antes → Depois (medido) | Commit |
|---|---|---|---|
| 1 | Cache de metadados do APK em `GET /app/version` (invalida por mtime+tamanho) | p50 **174,15 → 0,81 ms**; p95 183,19 → 1,01 ms; **20,0 → 182,7 req/s** (215× e 9×) | `8f6dae3` |
| 2 | `APIServer.request_queue_size` 5 → 128 (backlog de listen) | máx **1.031,64 → 20,16 ms**; **186,4 → 994,8 req/s** (5,3×); 400/32: 1.127 req/s | `4b39d65` |
| 3 | Sonda `io_probe` virou monitor periódico (timer 5 min) + check não-crítico `latencia` no `/health` | `/health` passou de 26 para **27 checks**, com p50/p95 ao vivo (`p50=8,03ms p95=44,58ms alvos=2 idade=134s`) | `0006eff` |
| 4 | Régua reutilizável `tools/monitor/io_probe.py` (série, concorrência, custo de `asyncio.run()`) | — | `8f6dae3`/`0006eff` |

**Descartes, com o número que os justificou:**

| Proposta original | Medição que a derrubou |
|---|---|
| `requests` → `aiohttp` em `auto_update`/`downloads`/`notifier` | Não há `requests` nesses módulos: `downloads` usa `urllib` em worker próprio, `notifier` já usa `asyncio.to_thread`, `auto_update` já é `asyncio`. |
| `sqlite3` → `aiosqlite` | SQLite é síncrono em thread de request/worker; não há loop compartilhado para bloquear. `aiosqlite` é só uma thread por baixo — custo sem ganho. |
| Loop compartilhado para a API | `asyncio.run()` novo custa **~130 µs**; tirar isso economizaria ruído e exigiria refatorar todos os handlers. |
| `subprocess.run` → `asyncio.subprocess` | Só rodam em contexto síncrono (timer/CLI) ou já em `to_thread`. |
| `/health` com TTL maior | Sem cache: **18,08 ms** para 26 checks; o TTL de 8 s já cobre os chips do painel. Ganho não paga a perda de frescor. |
| Afrouxar o login | **158,5 ms** de PBKDF2-SHA256 (260k iterações) é custo deliberado contra força-bruta, atrás do limiter de 30 req/min. |
| `sendfile`/async no `/site/*` | Vazão já em ~1.000 req/s após a fila de listen; o gargalo era o backlog, não o envio. |

**O que fica de herança:** a sonda como régua para qualquer mudança de
performance e o padrão "medir antes de migrar". Se um dia a API virar
ASGI/loop compartilhado (P5/React ou FastAPI), aí sim o pacote `async`
inteiro passa a fazer sentido — hoje não há item async pendente no core.

**Problemas originais (histórico):** `requests` bloqueante em `auto_update.py`, `downloads.py`, `integrations/notifier.py`; `subprocess.run` síncrono; `sqlite3` síncrono.

**Migração:**
```python
# ANTES (bloqueante)
import requests
resp = requests.post(url, json=data, timeout=10)

# DEPOIS (async)
import aiohttp
async with aiohttp.ClientSession() as session:
    async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        data = await resp.json()

# Subprocess → asyncio.subprocess
proc = await asyncio.create_subprocess_exec(
    "apt", "update", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
)
stdout, stderr = await proc.communicate()

# SQLite → aiosqlite
import aiosqlite
async with aiosqlite.connect("data.db") as db:
    await db.execute("SELECT ...")
```

**Connection Pooling:**
```python
# aiohttp connector pool
connector = aiohttp.TCPConnector(limit=100, limit_per_host=20, ttl_dns_cache=300)
session = aiohttp.ClientSession(connector=connector)
```

### F4 — Memory Layer (Mem0/Zep)
**Arquitetura híbrida recomendada:**
```
┌─────────────────────────────────────────────────────────────┐
│                    MEMORY LAYER                              │
├─────────────────┬─────────────────────┬─────────────────────┤
│  CORE MEMORY    │  ARCHIVAL MEMORY    │  GRAPH MEMORY       │
│  (context window)│  (vector DB + TTL)  │  (temporal KG)      │
├─────────────────┼─────────────────────┼─────────────────────┤
│ - User profile  │ - Conversation      │ - Entities (pessoas,│
│ - Preferences   │   history (chunks)  │   lugares, projetos)│
│ - Active tasks  │ - Documents (RAG)   │ - Relations         │
│ - Session state │ - Tool outputs      │ - Temporal edges    │
└─────────────────┴─────────────────────┴─────────────────────┘
```

**Implementação prática (fase 1 — Zep-style simplificado):**
```python
# core/memory_layer.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json

@dataclass
class MemoryNode:
    id: str
    type: str  # "entity" | "event" | "fact" | "preference"
    content: str
    metadata: dict
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None

@dataclass
class MemoryEdge:
    source: str
    target: str
    relation: str  # "mentioned_in", "related_to", "prefers", "owns"
    weight: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)

class MemoryGraph:
    def __init__(self, persist_path: Path):
        self.nodes: dict[str, MemoryNode] = {}
        self.edges: list[MemoryEdge] = []
        self.persist_path = persist_path
        self._load()

    def add_fact(self, user_id: str, fact: str, entities: list[str]) -> MemoryNode:
        # Extrai entidades com LLM leve (spaCy/GLiNER) ou regex
        # Cria nó + edges para entidades existentes
        pass

    def search(self, query: str, user_id: str, k: int = 10) -> list[MemoryNode]:
        # Hybrid: vector similarity (embeddings) + graph traversal
        # Filtra por user_id + TTL
        pass

    def consolidate(self) -> None:
        # Roda periodicamente: merge duplicatas, prune expirados, sumariza clusters
        pass
```

**Benchmarks alvo (LOCOMO/LongMemEval):**
| Métrica | Atual | Alvo (Zep/Mem0) |
|---------|-------|-----------------|
| Single-hop accuracy | ~60% | > 90% |
| Multi-hop accuracy | ~30% | > 70% |
| Temporal reasoning | ~20% | > 80% |
| Retrieval latency (p95) | ~2s | < 160ms |
| Context tokens/query | ~10k | < 5k |

#### F4 — FASE 1 ENTREGUE (2026-11-10)

**Status: fase 1 entregue.** O que faltava não era “mais histórico” (o
`memory/history.py` já guarda 20 mensagens por perfil), e sim **memória entre
sessões/perfis**: hoje, ao trocar de perfil ou passar de 20 mensagens, o
usuário volta a ser um desconhecido. A fase 1 resolve isso com um grafo
temporal barato e determinístico.

| Peça | O que entrou |
|---|---|
| `core/memory_layer.py` | `MemoryNode`/`MemoryEdge`/`MemoryGraph` em SQLite (`data/memory.db`, WAL). Fatos substituídos **não são apagados**: nasce a aresta `substitui` (novo → antigo) e o antigo sai das buscas, mas continua no histórico auditável. |
| Extração | 13 padrões PT-BR por regex (nome, cidade, aniversário, e-mail, telefone, trabalho, estudo, projeto, preferência, gosto, não gosto, “lembre que ...”, posse concreta). Sem LLM, sem embedding: 58–341 µs por mensagem. |
| Escopo | Todo nó tem `user_id` e **toda** leitura filtra por ele — memória de um usuário não aparece para outro, nem por busca vazia. |
| Actions | `salvar_fato` e `buscar_memoria` no catálogo (categoria `memoria`, 116 → **118** actions), liberadas para o papel `user` porque só tocam o próprio grafo. |
| Captura automática | `Orchestrator._post_process` → `_memorizar`: grava o que o usuário disse, sem ele pedir. Melhor esforço (falha nunca quebra a resposta) e desligável com `OD_MEMORY_AUTO=0`. |
| Testes | `tests/test_memory_layer.py` **+47** (extração, idempotência, substituição, histórico, isolamento por usuário, persistência, arquivo corrompido, teto de 500 fatos, busca, actions, orquestrador). |
| Custo medido | Extração p50 **114 µs** (34 chars) / 341 µs (131 chars); gravação idempotente **0,026 ms**; fato novo com aresta **0,76 ms**; busca **3,4 ms** com 200 fatos. Irrelevante ao lado de ~3 s do LLM. |

**Decisões e descartes da fase 1:**

| Alternativa | Por que não |
|---|---|
| Extração por LLM | Cada mensagem viraria uma chamada extra; regex cobre o que o dono realmente diz e é testável sem rede. LLM entra na fase 2 só para o que sobrar. |
| Embeddings/`sentence-transformers` | Dependência pesada e sem baseline de recall medido; a busca por termos + entidade já resolve “onde eu moro”. Fase 2. |
| Apagar fato antigo | Perde auditoria e a resposta “quando eu mudei de cidade?”. A aresta `substitui` dá as duas coisas. |
| Guardar memória no histórico de chat | É exatamente o que não escala (20 mensagens, por perfil). Grafo separado, escopo por usuário. |
| `aiosqlite` | F3 já mostrou que thread-por-requisição não ganha com async; SQLite com lock é o padrão do projeto. |

#### F4 — FASE 2 (injeção no prompt) ENTREGUE (2026-11-10)

**Status: injeção entregue e medida; embeddings e consolidação continuam na
fase 3.**

Até aqui a memória só era alcançável por action — o LLM não a via. Agora
`Orchestrator._build_prompt` chama `_bloco_memoria(user_id, text)`: busca os
fatos do usuário que casam com a mensagem (até `memoria_max_fatos=5`,
cortados em `memoria_max_chars=600`) e injeta um bloco **depois** do
system/data-hora e do bloco RAG — o prefixo cacheado do llama-server
sobrevive melhor, e o que o usuário contou sobre si é mais estável que o
texto recuperado.

**Ganho medido (10 fatos × 10 perguntas, `RecordingProvider`, sem LLM real):**

| Métrica | Sem injeção | Com injeção |
|---|---|---|
| Recall@5 do fato certo no prompt | **0/10 (0%)** | **9/10 (90%)** |
| Tamanho médio do prompt | 3.332 chars | 3.451 chars (**+3,6%**) |
| Custo da recuperação | — | p50 **0,205 ms** |

O único furo é `"tenho algum animal?"` → fato `"tem um cachorro chamado
Rex"`: igualdade semântica (animal ≈ cachorro) exige embedding, que é a
fase 3. Nada disso foi escondido no teste — `test_recall_do_bloco_injetado`
mede os 10 casos e exige ≥ 9, com o furo documentado no docstring.

**Salvaguardas:** desligável por `memoria_no_prompt=False`; usuário vazio ou
sem memória não recebe bloco (prompt idêntico ao da fase 1); erro de leitura
devolve bloco vazio e loga — memória nunca derruba o chat. A busca ganhou
radical leve PT-BR (`moro`/`mora`/`morar` → `mor`), senão "onde eu moro?"
não achava "mora em Curitiba".

#### F4 — FASE 3 (consolidação semanal + efêmero) ENTREGUE (2026-11-10)

**Status: consolidação entregue.** A memória agora tem prazo e faxina — sem
isso o grafo só crescia e "hoje estou cansado" ficaria verdadeiro para
sempre.

| Peça | O que entrou |
|---|---|
| **Efêmero** | Fato extraído com marcador de tempo relativo ("hoje", "amanhã", "no momento", "daqui a") nasce com `expira_em = agora + OD_MEMORY_EFEMERO_DIAS` (padrão **7**) e sai da busca ao vencer — a linha **continua no banco** para auditoria. |
| **`MemoryGraph.consolidar()`** | Duas operações idempotentes: (1) **dedupe** por conteúdo normalizado — fatos ativos com os mesmos tokens viram um só, o mais recente fica e os outros ganham aresta `substitui` (pega duplicado de caminhos diferentes: action com entidade fixa vs captura automática); (2) **expiração** dos efêmeros vencidos. Roda por usuário ou para todos. |
| **Leitura** | `ativos`, `buscar`, `stats` e o bloco do prompt ignoram fato vencido, então a expiração vale na hora, sem job de limpeza. |
| **`tools/monitor/memory_consolidate.py`** | CLI (`--user`, `--dry-run`, `--json`) que imprime antes/depois e é o que o timer executa. |
| **`systemd/od-memory-consolidate.{service,timer}`** | Oneshot semanal: `OnCalendar=Sun 04:20`, `Persistent=true` (roda na próxima subida se a máquina estava desligada). Instalado e habilitado em `~/.config/systemd/user/`. |
| **Testes** | `tests/test_memory_layer.py` **+11** (marcador efêmero, expiração saindo da busca sem apagar, fato expirado não bloqueia repetição, TTL por env, dedupe por entidades diferentes, idempotência, isolamento entre usuários, contagem de expirados, stats, CLI). |

**Decisão que mudou no meio do caminho:** o dedupe começou por
(user, tipo, entidade) — e isso nunca dispararia, porque `adicionar_fato` já
substitui fato novo da mesma entidade. Foi refeito para **conteúdo
normalizado**, que é exatamente o duplicado que dois caminhos diferentes
geram. Fica registrado porque o primeiro desenho teria virado código morto.

#### F4 — FASE 4 (busca semântica sob demanda) ENTREGUE (2026-11-10)

**Status: o furo de sinonímia fechou.** A busca por termos acertava 9/10; o
caso que sobrava ("tenho algum animal?" → "tem um cachorro chamado Rex")
precisa de vetor, não de regex.

| Peça | O que entrou |
|---|---|
| **`core/memory_embeddings.py`** | Provider opcional via `urllib` (sem SDK): Gemini `gemini-embedding-001` a 768 dims. `OD_MEMORY_EMBEDDING=auto` liga se houver `GEMINI_API_KEY`; `off` desliga; `gemini` força. Qualquer falha (sem chave, sem rede, 429, timeout de 3 s) devolve `None` e a busca lexical segue sozinha. |
| **Fallback, não substituto** | `buscar()` só chama embedding quando **nenhum** fato casa por termos. Acerto lexical continua em **0,26 ms**; só o caso sem match paga a API. `semantica=False` desliga por chamada. |
| **Cache de vetores** | Tabela `memory_vectors` no mesmo `memory.db`, com o nome do modelo na chave — trocar de modelo re-embeda em vez de misturar espaços vetoriais. Fatos são embedados em lote (1 chamada) na primeira busca sem match. |
| **Regra de aceitação** | Cosseno do Gemini já fica ~0,75 até em par sem relação, então limiar absoluto não decide: exige piso **0,78** (`OD_MEMORY_SEMANTICA_MIN`) **e** margem de **0,05** sobre a mediana dos fatos (`OD_MEMORY_SEMANTICA_MARGEM`). |
| **Cache de resultados (fase 4b)** | O resultado do fallback — inclusive o vazio — fica em cache pela consulta normalizada (caixa, acento e pontuação fora), TTL de 5 min (`OD_MEMORY_SEMANTICA_CACHE_S`, `0` desliga) e teto de 256 entradas. L1 em memória (LRU) e **L2 em SQLite** (`memory_semantic_cache`), sobrevivendo a restart. A chave (hash SHA-256 de consulta + modelo + assinatura `id`+`updated_at` dos fatos ativos) faz fato novo, substituído ou expirado invalidar sozinho; limpeza oportunista remove vencidos e excedentes. Falha do provider não cacheia o vazio. |
| **Testes** | `tests/test_memory_embeddings.py` **+28** (provider liga/desliga, falha de rede, texto vazio, cosseno, sinônimo entra, assunto aleatório rejeitado, hit lexical não paga embedding, cache de vetores, <3 fatos não chama API, isolamento, falha não quebra busca; cache de resultado: repetição, normalização, vazio, fato novo, fato substituído, desligável, TTL; persistência: sobrevive a restart, TTL em disco, invalidação por fato novo pós-restart, desligado não grava). `conftest` força `OD_MEMORY_EMBEDDING=off`: a suíte nunca fala com a rede. |

**Medido (provider real, 10 fatos × 10 perguntas + 10 perguntas fora):**
recall@5 **9/10 → 10/10**, falsos positivos **0/10**, margem in-domain
0,063–0,159 contra 0,010–0,041 fora de assunto (por isso 0,05). Custo: miss
semântico **431 ms p50** (embedding da consulta), primeira busca com vetores
frios de 10 fatos **1,27 s**, cache quente sem custo de fatos.

**Custo depois do cache de resultados (fase 4b, medido com o provider real):**
consulta repetida **439,8 ms → 0,67 ms**, variante de caixa/pontuação **0,70 ms**,
consulta fora de assunto repetida **0,33 ms** no embedder instrumentado.
Com a persistência: nova instância no mesmo banco (equivalente a restart)
responde em **1,19 ms** contra **1.326 ms** fria. O primeiro acerto semântico
continua pagando a consulta (~0,4 s); o cache só remove a repetição. Em
produção, consulta inédita no fio da conversa segue nesse custo — o que muda é
a segunda pergunta igual, inclusive depois de reiniciar o `od-core`.

**Trade-off declarado:** mensagem que não casa com nenhuma memória paga ~0,4 s
na **primeira** consulta daquele texto (dentro de 5 min); repetição custa
~1 ms. Quem não quiser nada disso, `OD_MEMORY_EMBEDDING=off` (ou
`semantica=False`) volta ao lexical puro sem tocar em nenhum outro caminho.

### R2 — Circuit Breaker (detalhe)

**Status: entregue** (commit `7d8b958`; `tests/test_resilience.py` +16; gate
**4226 passed / 16 skipped / 0 falha**).

O cenário: provider de LLM fora do ar fazia cada mensagem gastar o timeout
inteiro nele antes de cair para o próximo da cadeia.

| Peça | O que entrou |
|---|---|
| `core/resilience.py` | `CircuitBreaker` thread-safe (fechado → aberto → meia-aberto) com relógio injetável, `permitir()`/`registrar_sucesso()`/`registrar_falha()`/`executar()`/`status()`; registro global por nome e desligável por `OD_CIRCUIT_BREAKER=0`. |
| `core/llm.py` | Um disjuntor por provider (`llm:<nome>`): com o circuito aberto, `generate`/`generate_stream` recusam **sem tocar a rede** e `is_available()` não sonda. A recusa é `LLMError`, que a cadeia de fallback já conhece. |
| Parâmetros | `OD_CIRCUIT_FAILURES` (padrão 5) e `OD_CIRCUIT_RECOVERY_S` (padrão 30 s); passada a janela, uma tentativa libera (meia-aberta): sucesso fecha, falha reabre. |

**Descartes:**

| Plano | Motivo |
|---|---|
| `pybreaker` | A regra é 80 linhas de stdlib e precisa de relógio injetável para testar sem `sleep`; dependência não pagaria. |
| Bulkhead (limite de concorrência por recurso) | A API é thread-por-requisição com fila de listen de 128 e o limiter de 30 req/min já contém a entrada. Não há pool saturado medido para isolar. |
| Retry próprio dentro do breaker | Já existe cadeia de fallback no Orchestrator; dois mecanismos de retry multiplicariam tentativas. |
| Estado do disjuntor no Redis | Um processo só; estado local é coerente e não adiciona rede ao caminho de falha. Se I1/R1 trouxer Redis e mais workers, aí sim. |

**O que fica:** o circuito é por nome de provider e o registro é global —
openar um provider novo não exige tocar no `llm.py`. Ganho visível: no
circuito aberto, a resposta de fallback sai em milissegundos em vez de
esperar o timeout.

---

## 4. IMPLEMENTAÇÃO INCREMENTAL (ROADMAP 12 SEMANAS)

### Semana 1-2: Fundação Observabilidade — **F2 ENTREGUE em 10/11**
- [x] F2: OTel SDK + spans + métricas + log correlacionado + check no `/health`
- [x] F2: `BatchSpanProcessor` com exportador OTLP/HTTP ou console (em `core/telemetry.py`)
- [ ] OTel Collector config + Dashboards Grafana (Tempo/Loki/Prometheus) — **infra**, não código
- [ ] Alertas: p95 latency, error rate, cache hit rate, disk/memory (depende do coletor)

### Semana 3-4: Async I/O + Connection Pooling — **F3 ENCERRADO em 10/11**
- [x] F3: `requests` → `aiohttp` — **não aplicável**: não há `requests` nesses
      módulos (ver §3); substituído por auditoria medida
- [x] F3: `sqlite3` → `aiosqlite`, `subprocess` → `asyncio.subprocess` — **descartado**
      com medição (thread-por-requisição; `to_thread` onde já é async)
- [x] F3: ganhos reais encontrados e medidos: cache do APK em `/app/version`
      (215× no p50) e `request_queue_size` 5→128 (máx 1,03 s → 20 ms)
- [x] F3: monitor contínuo de p50/p95 (timer 5 min + check `latencia` no `/health`)
- [ ] Connection pools globais (HTTP, DB, Redis) — **sem demanda medida**;
      reabrir quando existir cliente HTTP de alto volume ou Redis (I1/R1)

### Semana 5-6: Memory Layer (Fase 1) — **F4 FASE 1 ENTREGUE em 10/11**
- [x] F4: `core/memory_layer.py` com MemoryGraph em SQLite — **sem embeddings**
      na fase 1 (extração determinística + busca por termos)
- [x] F4: integração no Orchestrator (`salvar_fato`/`buscar_memoria` no catálogo
      + captura automática no `_post_process`)
- [x] F4 fase 2: injeção do bloco de memória no prompt — recall@5 de 0% para
      **90%**, +3,6% de prompt, 0,2 ms de recuperação
- [x] F4 fase 3: consolidação semanal (dedupe + expiração de efêmero) no
      timer `od-memory-consolidate`
- [x] F4 fase 4: busca semântica sob demanda (`core/memory_embeddings.py`,
      Gemini 768 dims, cache em SQLite) — recall@5 9/10 → **10/10**, 0 falsos
      positivos, +0,4 s só no caso sem match lexical
- [x] F4 fase 4b: cache do resultado semântico por consulta normalizada —
      repetição cai de ~440 ms para **0,7 ms**; invalidado por mudança nos fatos
- [x] F4 fase 4b (L2): cache persistido em `memory_semantic_cache` —
      repetição após restart do `od-core` em **1,2 ms** (antes: ~1,3 s fria)

### Semana 7-8: Orquestrador como Grafo
- [x] F1 fase 1: `OrchestratorState` (TypedDict + reducers) e motor de grafo
      próprio em `core/orchestrator_graph.py` (sem `langgraph` instalado)
- [x] F1 fase 1: nós atômicos (classify, select, execute, generate, human) com
      fan-out paralelo e teto `max_paralelo`
- [x] F1 fase 1: `SqliteSaver` (`od_graph_checkpoints`, checkpoint por
      superstep) + `astream()` com `resume`, `recursion_limit` e pausa humana
- [x] F1 fase 2: fatia 4.5–6.7 do `process()` (RAG, prompt, LLM, anti-recusa,
      anti-falso-sucesso) roda no grafo com `{"recursion_limit": 50}` atrás de
      `OD_ORCHESTRATOR_GRAPH=1`; falha do grafo cai no caminho direto
- [x] F1 fase 3: pipeline completo no grafo — etapas 1–4 (rate limit,
      datetime, quick, infra, intenções, cache) como nós terminais e etapa 8
      (cache + histórico) como nó final, comuns ao caminho direto
- [x] F1 fase 4: `thread_id` determinístico por sessão+mensagem (hash de
      texto/perfil/papel), `concluido` no checkpoint e retomada automática do
      turno interrompido após restart — sem repetir o LLM

#### Backlog de sugestões de acompanhamento
> As 3 sugestões mostradas ao fim de cada turno são efêmeras: só a clicada vira
> pedido, as outras desaparecem do cliente. A partir de 10/11/2026, toda
> sugestão não escolhida é anotada aqui para não perder a melhoria.
- [ ] F1: fazer o `execute_parallel` executar as actions reais do registry, com
      timeout por ferramenta (hoje o `process()` responde actions pelo fast
      path e o grafo só orquestra conversa)
- [ ] F1: `RetryPolicy` por nó para falha transitória de LLM/action, sem
      reexecutar o pipeline inteiro
- [ ] F1: consumir `pending_human_input` de verdade no chat (pausa + aprovação
      do dono) usando `retomar()`, hoje só testado no motor
- [ ] RAG: avaliar cache de embedding de documento (evitar reembeddar o mesmo
      texto após restart)

### Semana 9-10: RAG Otimizado
- [ ] I1: Semantic Cache (Redis + embedding similarity ≥0.95)
- [ ] I2: Hybrid Search (BM25 via `rank-bm25` + dense + cross-encoder reranker)
- [ ] I4: Query Router (classificador leve → estratégia: direct, rag, tool, hybrid)
- [ ] I5: Streaming SSE para chat (`text/event-stream`)

### Semana 11-12: Resiliência + Eval
- [ ] R1: Task Queue (Redis/RQ) + RetryPolicy por nó
- [x] R2: Circuit Breaker em chamadas externas — feito sem `pybreaker`, por
      provider de LLM (`core/resilience.py`); bulkhead dispensado (ver §3)
- [ ] R5: Eval Framework (LOCOMO subset + custom benchmarks) rodando no CI
- [ ] Documentação de arquitetura atualizada (`docs/ARCHITECTURE_v2.md`)

---

## 5. MÉTRICAS DE SUCESSO (KPIs)

| KPI | Baseline (atual) | Target (12 sem) | Medição |
|-----|------------------|-----------------|---------|
| **Orchestrator p95 latency** | ~3-5s | < 1.5s | OTel histogram |
| **RAG retrieval p95** | ~1.5s | < 400ms | OTel histogram |
| **Cache hit rate (RAG)** | ~15% | > 40% | Prometheus gauge |
| **Memory recall (LOCOMO)** | ~60% | > 85% | Eval framework |
| **Error rate** | ~0.5% | < 0.1% | Counter |
| **Cold start (import do core)** | ~2.3s | < 800ms | `python -X importtime -c "import core"` |
| **Duração da suíte de testes** | 190s | < 120s | `pytest -q` |
| **Duração do hot-reload de ferramentas** | N/A | < 2s | Teste manual |

---

## 6. RECURSOS NECESSÁRIOS

| Recurso | Estimativa | Notas |
|---------|------------|-------|
| **Tempo desenvolvedor** | 12 semanas (1 dev full-time) | Pode ser paralelizado em 2-3 tracks |
| **Infra observabilidade** | Grafana Cloud (free tier) ou self-hosted | ~$0-50/mês |
| **Redis** | Já existe (cache LLM) | Upgrade para Redis Stack (RediSearch + JSON) |
| **Vector DB** | Chroma/FAISS local | Considerar Qdrant ou Milvus se escalar |
| **LLM para eval** | GPT-4o-mini / Gemini 2.5 Flash | ~$5-10/mês para eval contínuo |

---

## 7. RISCOS E MITIGAÇÕES

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Migração orquestrador quebra fluxos existentes | Alta | Alto | Feature flag: `ORCHESTRATOR_V2=1`, rodar em shadow mode 2 semanas |
| OTel adiciona overhead de latência | Baixa | Médio | `BatchSpanProcessor` + `max_queue_size=2048`, sampling 10% em produção |
| Memory graph cresce sem controle | Média | Médio | TTL padrão 90d, consolidação semanal, `max_nodes=100k` por user |
| Async migration introduz race conditions | Média | Alto | Testes de carga (locust) + property-based testing (hypothesis) |
| Eval framework não correlaciona com UX real | Média | Médio | Incluir feedback do dono (thumbs up/down no chat) como sinal |

---

## 8. PRÓXIMOS PASSOS IMEDIATOS (ESTA SEMANA)

1. ~~Criar branch `feat/arch-v2`~~ — trabalho segue em `master` com gate verde por item
2. ~~Implementar F2 (OTel)~~ — **entregue em 10/11** (`core/telemetry.py`); resta infra do coletor
3. **Adicionar `pyproject.toml` dependências:** `opentelemetry-sdk` (já em `requirements.txt`, import tardio), `redis`, `rank-bm25`, `sentence-transformers` — `aiohttp`/`aiosqlite`/`pybreaker` **descartados** com medição (F3/R2)
4. **Criar `docs/ARCHITECTURE_v2.md`** com diagramas Mermaid do novo grafo
5. **Agendar sync semanal** com dono para revisar progresso e ajustar prioridades

---

> **Nota:** Este TODO é vivo. Itens podem ser reordenados, divididos ou descartados conforme aprendizado durante a execução. A filosofia é **"entregar valor incremental a cada 2 semanas"** — não reescrita big-bang.