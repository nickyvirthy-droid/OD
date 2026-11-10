# ANÁLISE GERAL DO SISTEMA OMEGA DRAKON — 10/11/2026

> **Objetivo:** Identificar gargalos, modernizar arquitetura, incorporar estado-da-arte (2024-2025), tornar o sistema **mais rápido, mais inteligente, mais observável, mais resiliente**.
> **Metodologia:** Análise do código atual (60 módulos core/tools, ~18k LOC) + pesquisa de melhores práticas 2024-2025 (LangGraph, Mem0/Zep, OpenTelemetry, Harmonia/RAGO, semantic caching, checkpointing, human-in-the-loop).
> **Resultado:** TODO priorizado para execução incremental ("devagar").

---

## 1. RESUMO EXECUTIVO DO ESTADO ATUAL

| Dimensão | Estado Atual | Gap Principal |
|----------|--------------|---------------|
| **Orquestração** | `orchestrator.py` monolítico (2285 linhas), loop síncrono, sem checkpointing | Sem durabilidade, sem resumo pós-falha, sem paralelismo controlado |
| **Memória** | Histórico de chat simples + RAG básico (chunks JSON diários) | Sem memória longa estruturada (Mem0/Zep), sem grafo temporal, sem recall multi-sessão |
| **RAG** | Embedding local + busca vetorial simples, cache LLM básico | Sem semantic caching, sem hybrid search, sem otimização KV-cache, latência não medida |
| **Observabilidade** | Logs estruturados básicos (`core/logger.py`), `/health`, `/metrics` | Sem distributed tracing (OTel), sem structured logging com trace correlation, sem dashboards |
| **Resiliência** | `SelfRepairEngine` + `RecoveryLoop` básicos | Sem task queue, sem retry policy declarativo, sem circuit breaker, sem graceful degradation |
| **Performance** | Single-threaded event loop, bloqueio em I/O síncrono (`requests`, `apt`, `fwupdmgr`) | Sem async I/O, sem connection pooling, sem batch processing, sem streaming |
| **Segurança** | Security Layer (scope, permissions, approval) | Sem sandbox real para plugins, sem supply chain verification além Ed25519 |
| **Developer Experience** | Canal de dev on-demand, testes 4193 passed | Sem hot-reload de código, sem time-travel debugging, sem eval framework |

---

## 2. TODO PRIORIZADO (MATRIZ IMPACTO × ESFORÇO)

### 🔴 CRÍTICO — Fundação (fazer primeiro, habilita o resto)

| ID | Item | Esforço | Impacto | Referência |
|----|------|---------|---------|------------|
| **F1** | **Migrar orquestrador para grafo de execução (LangGraph-style)** | Alto | 🔥🔥🔥 | LangGraph blog 2024-2025: checkpointing, parallelization, streaming, human-in-the-loop, task queue, tracing nativo |
| **F2** | **Implementar OpenTelemetry distribuído (traces + metrics + logs correlacionados)** | Médio | 🔥🔥🔥 | python-observability.com, structlog + OTel + BatchSpanProcessor |
| **F3** | **Substituir I/O síncrono por async em todo o core** | Alto | 🔥🔥 | `aiohttp`, `asyncpg`, `asyncio.to_thread` para bloqueantes |
| **F4** | **Memory Layer estruturada (Mem0/Zep-style: grafo temporal + consolidação)** | Alto | 🔥🔥🔥 | Mem0 (arXiv 2504.19413), Zep (arXiv 2501.13956), LOCOMO/LongMemEval |

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
| **R2** | **Circuit Breaker + Bulkhead + Graceful Degradation** | Baixo | 🔥 | Resilience4j patterns, AWS Well-Architected |
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

---

## 4. IMPLEMENTAÇÃO INCREMENTAL (ROADMAP 12 SEMANAS)

### Semana 1-2: Fundação Observabilidade
- [ ] F2: OTel SDK + structlog + BatchSpanProcessor + OTel Collector config
- [ ] Dashboards Grafana (Tempo traces, Loki logs, Prometheus metrics)
- [ ] Alertas: p95 latency, error rate, cache hit rate, disk/memory

### Semana 3-4: Async I/O + Connection Pooling
- [ ] F3: Migrar `requests` → `aiohttp` em `auto_update`, `downloads`, `notifier`
- [ ] F3: `sqlite3` → `aiosqlite`, `subprocess` → `asyncio.subprocess`
- [ ] Connection pools globais (HTTP, DB, Redis)

### Semana 5-6: Memory Layer (Fase 1)
- [ ] F4: `core/memory_layer.py` com MemoryGraph (SQLite + embeddings)
- [ ] Integração no orchestrator: `save_fact`, `search_memory` como tools
- [ ] Consolidação periódica (cron job semanal)

### Semana 7-8: Orquestrador como Grafo
- [ ] F1: Definir `OrchestratorState` (TypedDict + reducers)
- [ ] F1: Implementar nós atômicos (classify, select, execute, generate, human)
- [ ] F1: Compilar grafo com `SqliteSaver` checkpointing
- [ ] F1: Migrar loop atual para `graph.astream()` com config `{"recursion_limit": 50}`

### Semana 9-10: RAG Otimizado
- [ ] I1: Semantic Cache (Redis + embedding similarity ≥0.95)
- [ ] I2: Hybrid Search (BM25 via `rank-bm25` + dense + cross-encoder reranker)
- [ ] I4: Query Router (classificador leve → estratégia: direct, rag, tool, hybrid)
- [ ] I5: Streaming SSE para chat (`text/event-stream`)

### Semana 11-12: Resiliência + Eval
- [ ] R1: Task Queue (Redis/RQ) + RetryPolicy por nó
- [ ] R2: Circuit Breaker (pybreaker) em chamadas externas
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

1. **Criar branch `feat/arch-v2`** e configurar CI para rodar testes paralelos
2. **Implementar F2 (OTel)** — menor risco, maior visibilidade imediata
3. **Adicionar `pyproject.toml` dependências:** `opentelemetry-sdk`, `structlog`, `aiohttp`, `aiosqlite`, `redis`, `rank-bm25`, `sentence-transformers`, `pybreaker`
4. **Criar `docs/ARCHITECTURE_v2.md`** com diagramas Mermaid do novo grafo
5. **Agendar sync semanal** com dono para revisar progresso e ajustar prioridades

---

> **Nota:** Este TODO é vivo. Itens podem ser reordenados, divididos ou descartados conforme aprendizado durante a execução. A filosofia é **"entregar valor incremental a cada 2 semanas"** — não reescrita big-bang.