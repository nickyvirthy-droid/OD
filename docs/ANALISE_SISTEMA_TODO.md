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

### 📍 Revisão de 17/11/2026 — o que está aberto e a ordem das próximas entregas

> Pedido do dono: "Revisar as checkboxes abertas do TODO e priorizar as
> próximas entregas". Cada item foi conferido **no código e nos commits**, não
> de memória. Resultado da auditoria: **38 abertas** → **32 abertas / 78
> fechadas**; toda prioridade abaixo tem evidência (arquivo, commit ou
> medição) e nenhum item foi inventado.

**Higiene feita nesta revisão** (não são entregas novas — são dívidas de
registro):

1. Fechados com evidência: "fechar o lote de 13/11" (gate 4656 e commits de
   14/11), "remover a duplicata de `_task_queue_or_503` + teste da fila"
   (duplicata = 1, `tests/test_task_queue.py` 35 KB), "decisão do
   `semantic_cache=` no boot" (`f2c784a`, desligado por padrão),
   "`docs/ARCHITECTURE_v2.md`" (300 linhas, commit `93aadd7`) e "fila de
   download resumable" (`core/downloads.py` com `Range` + SSE, já usada pelo
   app).
2. Removida a **duplicata** de "Task Queue (Redis/RQ)" (existia em dois
   lugares do roadmap) e reescopada a que ficou.
3. Corrigido o texto órfão que sobrou embaixo do item de `web_search`.
4. Reescopado "enxugar o prompt do Gemini": a cota é por **requisição**
   (20/dia), não por byte — o item agora fala do ganho real (latência e
   contexto útil).

**Higiene de 28/11/2026** (auditoria pedida pelo dono, conferida no código):
**28 abertas → 24 abertas / 135 fechadas**. Quatro checkboxes estavam
contradizendo o próprio texto do documento e foram fechados:

- **Teste ZIM ↔ compose** — entregue em 18/11 (`tests/test_zim_compose.py`,
  **11 passed** em 28/11).
- **I2 Hybrid Search** — ligado em produção desde 25/11 (`OD_RAG_HIBRIDO`
  padrão `1`); fica fora só o reranker neural, por decisão (a RAG tem reranker
  próprio).
- **R1 fila distribuída** — reescopado em 17/11; a fila própria em produção
  cobre o caso.
- **`llm_cache` de modelo local** — testado e descartado em 17/11.

Continuam abertos 20 itens (R5, crédito real do OpenAI, cache de embedding e
`upsc` foram fechados no mesmo dia): código (enxugar prompt, reranker neural),
decisão do dono (I1, quarentena de `revisar/`, app por papel, connection
pools, VRAM no comparador), compra/físico (nobreak, segundo nó, mídia
off-site, reteste 7B, PIN do Bluetooth, Homebox, WhatsApp Cloud API) e infra
externa (OTel/Grafana/alertas, `xdg-desktop-portal`).

#### P0 — esta semana (barato, risco real, evidência na mão)

| # | Entrega | Por que agora | Esforço |
|---|---------|---------------|---------|
| 1 | ~~**Guarda do `llm_cache` para conversa comum**~~ **ENTREGUE 17/11 + 18/11** — `_resposta_do_cache()` valida na LEITURA e apaga a entrada envenenada (vira MISS); 18/11 ampliou o anti-falso-sucesso para rádio/volume/luzes: **3 entradas inventadas** no cache vivo recusadas, 0 legítimas | Hoje o cache pode devolver resposta **inventada** de conversa (o guarda só barra comando de action). É a classe de defeito que faz o OD "parecer menos inteligente" e agora fica gravada em cache. | Baixo–médio |
| 2 | ~~**Corpus de frases reais do dono**~~ **ENTREGUE 18/11** — `tests/test_corpus_frases_dono.py`, 32 testes, 13 frases verbatim com origem conferida | Os buracos de casamento só aparecem em uso (disco, papéis, rádio) e cada um custou um turno de conserto. Custo: nenhum — as frases já existem. | Baixo |
| 3 | ~~**Teste ZIM ↔ compose**~~ **ENTREGUE 18/11** — `tests/test_zim_compose.py` (11 testes) + `tools/checar_zim_compose.py` (guarda nas duas direções, rodável no CI). Acervo real: **14 ZIMs alinhados** com o `command`. | Um ZIM novo só entra na busca se alguém lembrar do `command`; 14 ZIMs/40,3 GB já hoje sem guarda. | Baixo |
| 4 | ~~**Espelho: `.gguf` 3B + binário do llama.cpp com MANIFEST**~~ **ENTREGUE 18/11** — `od-mirror/models/` + `od-mirror/runtimes/llama/`, MANIFEST 133 entradas (51 novas, 51/51 OK) e **prova real**: o `llama-server` do espelho subiu de `/tmp` sem `LD_LIBRARY_PATH`, carregou o `.gguf` do espelho e respondeu `/v1/models`. | O "offline" do OD dependia de `/home/alex/llama.cpp` sobreviver; o resto do espelho já está pronto em `od-mirror`. | Baixo |

#### P1 — próximas duas semanas (valor alto, escopo médio)

| # | Entrega | Por que agora | Esforço |
|---|---------|---------------|---------|
| 5 | ~~**Ligar o I2 (Hybrid Search) no RAG com medição antes/depois**~~ **ENTREGUE E LIGADO 25/11** — fiação de 18/11 + recalibração medida: nenhum par (score, overlap) do piso denso separa (os 2 falsos positivos são **as nossas transcrições** citando a pergunta do gate, comb 0,439/0,447 acima do relevante mais fraco 0,410), então entrou um piso **só-lexical** `PISO_SCORE_LEXICAL = 0,47` (pior irrelevante + 0,023), com o piso denso **intocado**. Gate nos dois modos: **8/8 relevantes · 0/8 irrelevantes · 6/6 paráfrases · 2/2 estruturais**; resgates reais mantidos (eval 0,636, Registro Mestre 0,628). `OD_RAG_HIBRIDO` agora **ON** por padrão; medidor reprodutível em `tools/recalibrar_piso_hibrido.py`. | Médio |
| 6 | **Modo colapso declarado** | Hoje, sem nuvem, a resposta cai no 3B **em silêncio**. Trocar para a cadeia local e avisar no chat/UI é barato e é a diferença entre degradar e parecer quebrado. | Médio |
| 7 | **Backup fora da máquina + teste de restauração real** — **restauração PROVADA 19/11** e **offsite PROVADO 25/11**: o dump do dia está, com sha256 idêntico (`3bfaff1c…`), no snapshot das duas HDs (Mídias e Arquivos) e dentro do tar enviado ao canal do Telegram; a **cópia do HD** restaura (14 tabelas/604 linhas, 0,17 s) e `tools/checar_offsite_pg.py` confere isso a qualquer momento. Pendente só a **mídia física fora do local** (pendrive/SSD criptografado = ação do dono). | É o DoD do plano de continuidade: o dump do Postgres e o snapshot já existem, mas **nunca foram restaurados**. | Médio |
| 8 | **Comparador de modelos lado a lado + monitor de hardware** | Ideia do GSN Offline (17/11) e o dono já pediu para "usar a melhor IA": hoje a escolha é por log, não por comparação ao vivo. | Médio |

#### P2 — depende de decisão ou compra do dono

| # | Entrega | O que trava |
|---|---------|-------------|
| 9 | **Nobreak 1200–1500 VA com USB** + monitor de UPS no `readiness_report` | Compra. `readiness_report` mede **6/9** e energia é o buraco nº 1 — sem ela nada mais sobrevive ao apagão. |
| 10 | **Segundo nó na LAN / rádios LoRa** | Compra/arquitetura. Hoje o Telegram é o único canal externo. |
| 11 | **App por papel (abas escondidas por papel)** | Decisão do dono; recomendação escrita (1 app, recorte no `role`, aba "Casa" data-driven). |
| 12 | **OpenAI com crédito real** / **I1 definitivamente desligado** | Saldo do dono / decisão. I1: recomendação medida é manter desligado (0 acerto extra). |
| 13 | **Projeti** (lixo do `google-services.json`, APK órfão, ferramentas Windows, dados do Orion) | Regra 7: apagar/mover é só com aprovação; os `.exe` já estão só no zip da HD. |

#### P3 — infra e "quando houver demanda"

| # | Entrega | Nota |
|---|---------|------|
| 14 | OTel Collector + Grafana + alertas | SDK já exporta; falta só a infra e onde hospedar. |
| 15 | R5 Eval framework no CI | Ganha valor junto do item 5 (comparar antes/depois sem palpite). |
| 16 | RAG: cache de embedding de documento | Ganho local, sem risco. |
| 17 | Mapas: rótulos não-latinos e zoom 15 urbano | Rótulos não-latinos **embutidos 26/11** (hebraico, árabe, siríaco, devanagari, tailandês, vietnamita, pontuação; CJK/hangul não existem na fonte Protomaps). z15: só com demanda medida. |
| 18 | IA local: reteste do 7B Q3_K_M / `-c 4096` | Depende de RAM livre; 60 s × 16 s hoje. |
| 19 | Espelho: restauração real (venv limpo + container) | **Feito 26/11** — venv limpo offline rodou o gate (5807/17/2) e o Postgres subiu do tar com `--network none`; MANIFEST 134/134. Ver `docs/ESPELHO_RESTAURACAO.md`. |
| 20 | NV (DAG/scheduler, security layer) e dados do Orion | Referência arquivada; **sem demanda medida** — não portar. |

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

### Fila de prioridades combinada com o dono (26/11) — do primeiro ao último

Ordem de execução acordada: primeiro o que evita falha silenciosa ou some do
radar, depois o que precisa de execução real, por fim o que depende de decisão
do dono. Marcar aqui a medida que cada item fecha.

| # | Item | Estado |
|---|------|--------|
| 1 | Aviso de ciclo que morre antes do fim (`OnFailure`) | ✅ 26/11 02:2x |
| 2 | Verificador de units repo × systemd no `/health` | ✅ 26/11 02:3x |
| 3 | Relatório de simulação completa do ciclo (`--relatorio`) | ✅ 26/11 02:4x |
| 4 | Guarda de offsite junto do verificador semanal | ✅ 26/11 03:3x |
| 5 | Comparador de modelos lado a lado (P1 nº 8) | ✅ 26/11 08:5x — `/admin/comparador/*` + seção no painel; provado ao vivo em 3 modelos (0,56 s / 2,63 s / 18,6 s, parede = o mais lento) |
| 6 | NV: referência de DAG/scheduler + `SECURITY_LAYER_ARCHITECTURE.md` | ✅ 26/11 — `docs/NV_DAG_SCHEDULER_REFERENCE.md` (13/11) + `docs/SECURITY_LAYER_ARCHITECTURE.md` novo, com o mapeamento de cada camada no OD |
| 7 | Projeti: `google-services.json`, APK de 51 MB × backups, leitura do Orion | ✅ 26/11 — originais já fora do servidor (zip na HD); leitura do Orion documentada em `docs/PROJETI_REFERENCIA.md`; trilha de backups do APK medida, 1.47.0 arquivado e passo de `aapt` no checklist |
| 8 | Mapas offline (próximo do inventário) | ✅ 26/11 — 8 faixas de glifos não-latinos embutidas (+648 KB, 11 testes); CJK/hangul e z15 medidos e fechados por falta de demanda (`docs/MAPAS_OFFLINE.md`) |
| 9 | Modo colapso declarado | ✅ 21/11 (entregue) e **provado ao vivo 26/11**: ligar → groq/gemini bloqueados, resposta local com prefixo "⚡ modo colapso", `/health` degraded; desligar → up. 17 testes |
| 10 | Espelho com restauração real (precisa execução e prova) | ✅ 26/11 — venv limpo com os wheels do espelho (60 pacotes, 18 s, `PIP_NO_INDEX=1`) + **gate completo 5807/17/2 (as 2 falhas pré-existentes) em 249 s**; `postgres:16-alpine` carregado do tar e bootado com `--network none` (só `lo`), `pg_isready` + `select` OK; MANIFEST **134/134**. Achado corrigido: `requirements-dev.txt` não estava no espelho — copiado e registrado |
| 11 | Janela de aplicação do SO com prova de retorno | ✅ 26/11 02:36 — 67 pacotes + 51 firmwares aplicados 02:13, reboot feito 02:36, `od-pos-reboot` avisou no Telegram, kernel 6.8.0-151, `reboot pendente: não` |

**Fora da fila (decisão do dono):** quarentena do acervo (38 arquivos), app
por papel, energia/religar, backup fora da máquina, reteste de IA local,
ferramentas Windows no desktop, foto da peça → Homebox, ouvir a música, token
da Meta. **Infra externa:** OTel Collector/Grafana e alertas; connection pools
(sem demanda medida — fechar = decidir descartar).


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
- [x] **`versionCode` divergente no APK arm64 da 1.45.1** (achado 28/11, na
      deduplicação dos APKs) — **RESOLVIDO 28/11.** Causa medida: 4082 = 2082 +
      1000×ABI (arm64 = 2); o arm64 foi gerado 05:18:39 e o completo 05:20:18,
      ordem inversa do `app/build_apk.sh`, ou seja o par saiu de um
      `flutter build apk --split-per-abi` **manual sem**
      `-Pforce-version-code-ignoring-abi=true`. Correção: `tools/verificar_apk_versao.py`
      (novo, 9 testes) lê o `pubspec`, roda `aapt dump badging` e falha com a
      dica do offset; o `app/build_apk.sh` chama o verificador **antes** de
      publicar em `site/`. Prova viva: site 1.47.0+2085 passa (exit 0); arm64
      da 1.45.1 contra pubspec 1.45.1+2082 sai `exit 1` com `diferença +2000`.
- [x] **Aviso de ciclo que morre antes do fim** — **FEITO 26/11 02:2x:**
      `OnFailure=od-os-updater-falha.service` nas duas units do ciclo;
      `core.os_updater.avisar_falha()` (`--avisar-falha`) manda no Telegram o
      estado/resultado do systemd, as 3 últimas seções e as 6 últimas linhas do
      journal, e devolve `ok=false` se o canal cair. Fica em `/etc/systemd/system`.
      4 casos novos em `test_os_updater` (61 no arquivo).
- [x] **Log do último ciclo no painel do atualizador de SO** (sugestão de
      26/11) — **FEITO 26/11 02:10:** tabela "Quando · Seção · Resultado ·
      Detalhe" com as 5 últimas seções (`apt_update`, `apt_upgrade`,
      `fwupdmgr`, `reboot`), mais recente primeiro, detalhe escapado; render
      na função pura `soSecoesHtml` testada no node. Prova viva: status 200 com
      5 seções, `/admin` com `id="so-secoes"`, journal `-p err` 0.
- [x] **Publicar build do app com o card do atualizador de SO** (sugestão de
      26/11) — **FEITO 26/11 01:20:** release **1.47.0 / 2085** publicado em
      `site/` (aapt confirma versionName/versionCode, `/app/version` anuncia o
      mesmo sha256); gate completo 5767 passed / 16 skipped / 0 falha.
- [x] **Instalar os timers/units restantes que só existem no repositório**
      — **FEITO 26/11 02:3x:** as 12 units de `systemd/` estão instaladas (system
      + user) e agora há o verificador: `core/systemd_units.py` compara
      `systemd/*.service|timer` com `systemctl list-unit-files` (system e user),
      com cache de 5 min, e o check **não-crítico** `units_instaladas` foi para o
      `/health` (`12 unit(s) do repo instaladas`). Sem `systemctl` o check diz
      "indisponível" em vez de acusar o dono. 6 casos em `tests/test_systemd_units.py`.
- [x] **Botão "Aplicar atualizações" no painel do SO** (sugestão de 26/11) —
      **FEITO 26/11 01:47:** seção "Atualizador de SO" no `/admin` com resumo ao
      vivo e botão com **dupla confirmação** (a segunda avisa o reboot em +5 min).
      A aplicação vai pela unit root `od-os-updater-forcar.service` via
      `sudo -n` restrito a esse comando (`/etc/sudoers.d/od-os-updater`,
      `visudo -c` OK); a rota responde 202 e as 3 rotas deixaram de dar 503.
      Prova viva: status 200 (67 pacotes/51 firmwares), dry-run 200, unit
      `inactive` (nada aplicado por mim). `tests/test_painel_os_updater.py` 9 casos.
- [x] **Relatório de simulação completa do ciclo do SO** — **FEITO 26/11:**
      `python -m core.os_updater --relatorio` roda o `dry_run` e imprime resumo
      legível (pacotes e firmwares **por nome**, reboot previsto, erros) usando
      estado temporário — a simulação não polui as seções do painel. 2 casos
      novos em `test_os_updater`.
- [x] **Janela de aplicação do SO com prova de retorno** (sugestão de 26/11) —
      **FEITO 26/11:** `tools/validar_pos_reboot.py` + `systemd/od-pos-reboot.service`
      (oneshot no boot) conferem uptime, `/health`, 5 serviços, 2 timers,
      `/var/run/reboot-required`, kernel e 5 checks obrigatórios, gravam
      `data/pos_reboot.json` e mandam o veredito no Telegram. **Prova no reboot
      real de 02:36:** unit `enabled`, rodou 20 s após o boot, esperou 6,1 s o
      `od-core`, 5/5 serviços e 2/2 timers `active`, kernel 6.8.0-151,
      `reboot pendente: não`, Telegram enviado, `exit=0`. `/health` depois:
      ok=true com 34 checks. 5 casos em `tests/test_validar_pos_reboot.py`.
- [x] **`/health`: container subindo vira `starting`, não falha** — **FEITO
      26/11:** `HealthMonitor` ganhou janela de boot (padrão 300 s no launcher,
      `OD_HEALTH_JANELA_BOOT_S=0` desliga): `tool_*`/`mqtt` falhando dentro dela
      saem com `status: "starting"`, `transitorio: true` e não derrubam o
      agregado (lista `transitorios` no `/health`); o notifier ignora esses
      itens. Falha real continua derrubando na hora. 10 casos novos; restart
      26/11 com MainPID 61637 e `-p err` 0.
- [x] **2 testes de `test_websocket` falham na suíte completa por ordem** —
      **FEITO 26/11: gate em 0.** Causa raiz medida com um plugin que comparava
      o ambiente antes/depois de cada teste: `test_producao_passa_a_guarda_no_main`
      (em `tests/test_verificar_restauracao_pg.py`) roda
      `runtime.verificar_restauracao_pg.main()` em processo e, sem `TELEGRAM_*`
      no ambiente, esse `main()` chama `load_dotenv(.env)` — derramando
      `OD_ORCHESTRATOR_GRAPH=1`, `OD_CHAT_PROVIDERS` e `OD_IA_ORDEM` no
      `os.environ` da suíte. Com o grafo ligado, `process_stream` sai pelo
      `_process_stream_grafo`, que rende o rate limit como `done` e a resposta
      em um token só: exatamente o que os 2 testes (caminho direto) negavam.
      Corrigido nos **testes**: `load_dotenv` neutralizado no teste vazador +
      fixture autouse `_runtime_sempre_limpo` no `tests/conftest.py` que apaga
      o trio a cada teste. Gate **5772 passed / 19 skipped / 0 falha** (antes
      5770/19/**2**) e **0 vazamentos** com o mesmo plugin. Ver
      `docs/CHANGELOG.md`.
- [x] **Caminho do grafo e caminho direto divergem no protocolo de streaming** —
      **FEITO 26/11:** `_process_stream_grafo` e o caminho direto de
      `process_stream` em `core/orchestrator.py` agora compartilham
      `_executar_stream_llm()` (async generator com `provider.generate_stream`,
      fallback para `_generate_one`, anti-recusa e anti-falso-sucesso) e
      `_estado_de_tool_results()`:
      (1) tokens reais do LLM são encaminhados por `asyncio.Queue` em tempo
      real (em vez de resposta inteira em um `token`);
      (2) `rate_limited` e `llm_unavailable` no grafo emitem `{"type": "error",
      "message": "rate_limited" | "providers_indisponiveis" | ...}` e chamam
      `_finish()`, casando com o `case 'error'` de `app/lib/services/od_ws.dart`;
      (3) encerradas a dupla contagem de `_metrics.llm`/`fallback` e a dupla
      chamada de `_post_process` no grafo, além da ausência de `_record_terminal`/
      `_finish` nas rotas terminais (`datetime`, `quick`, `cache`, `action_intent`).
      7 novos casos em `tests/test_orchestrator_graph_integration.py`
      (`TestStreamingGrafoParidade`) cobrem os dois caminhos (`0` e `1`).
- [ ] **`xdg-desktop-portal[-gtk]` falhando na sessão do usuário** — achado na
      retomada de 26/11 11:0x: `journalctl --user -p err` mostra os dois units
      `Failed to start` a cada poucos minutos desde 10:32 (portal de desktop
      da sessão gráfica). **Fora do alcance do `od-core`** (unit dele com 0
      entradas de err e `/health` ok=true), mas é erro recorrente do sistema:
      investigar dependência do portal (flatpak/snap/portal sem desktop
      completo) e decidir se desabilita os units ou arruma a sessão.
- [x] **Pós-reboot: não soar alarme com container ainda subindo** — **FEITO
      26/11:** `tools/validar_pos_reboot.py` ganhou carência própria para os
      checks de container/broker (`tool_*`, `mqtt`): depois de o `od-core`
      responder, relê o `/health` a cada 5 s por até **60 s** e só então fecha o
      veredito; se subiram, o relatório diz `containers: subiram em ~Ns` e o
      boot fica **🟢**. Falha real (banco, orchestrator, backup…) continua
      alarmando **na hora**, sem carência, e container que não sobe no prazo
      vira pendência explícita (`containers/broker ainda falhando: …`).
      `TimeoutStartSec` da unit 300 → 360 s. 4 casos novos (9 no arquivo).
      Contexto original: no boot de
      26/11 a checagem rodou 22 s depois do uptime e reportou `/health
      degraded` com 6 checks falhando (`mqtt`, `tool_kiwix`, `tool_flatnotes`,
      `tool_stirling_pdf`, `tool_calibre_web`, `tool_homebox`); os containers
      subiram em seguida e tudo ficou `up`. Resolve: esperar os containers
      (ou marcar esses checks como transitórios na primeira janela) para o
      veredito do boot separar "ainda subindo" de "quebrou".
- [x] **Estado do atualizador de SO no `/health`** (sugestão de 26/11) —
      **FEITO 26/11:** check não-crítico `os_updater` via
      `register_os_updater_health()`; lê o JSON de estado + reboot e conta
      pacotes/firmwares com cache de 30 min (apt list = 0,55 s medidos).
      Falhas → `ok=false`; reboot pendente → `degraded` com motivo. Prova viva:
      `/health` 200 com 33 checks e `os_updater` em 3,7 ms
      (`pacotes=67 firmwares=51 falhas=0 reboot_pendente=sim
      kernel=6.8.0-147-generic`).
- [x] **Restart do `od-core` para ativar o reconhecimento de segurança pelo chat**
      (sugestão de 25/11) — **FEITO 25/11 14:27:** MainPID 1768401, `NRestarts=0`,
      `/health` ok com 32 checks, journal `-p err` 0; prova viva `POST /message`
      "reconhece a segurança" → `fastpath:network_conhecer` em **29,1 ms**
      ("nada a reconhecer", fila vazia). Lote afetado 444 passed antes do
      restart.
- [x] **Instalar e ativar o timer do `od-os-updater` nesta máquina** (achado de
      25/11, pedido do dono no `txt`) — **FEITO 26/11 com `sudo` liberado:**
      units copiadas, `daemon-reload`, `od-os-updater.timer` **enabled +
      active** (próxima execução domingo 29/11 ~03:16). A instalação revelou
      dois defeitos corrigidos no mesmo passo: (a) a unit como estava
      (`User=alex` + `ProtectSystem=strict`) não escrevia em
      `/var/lib/apt`, `/var/lib/dpkg`, `/var/cache/apt`, `/var/log/apt` nem
      `/var/lib/fwupd` — 5/5 FALHA medidos numa unidade transitória; passou a
      rodar como root com `PrivateTmp` e devolve o estado ao `alex` no fim;
      (b) o `main()` não passava o notificador, então o ciclo das 03:00 rodaria
      em silêncio — `notificar_telegram()` + `EnvironmentFile=.env` entraram e
      o canal foi provado nos dois contextos. A ativação disparou o serviço
      uma vez (`Persistent=true`): respondeu `acao: aguardar`, nada instalado,
      nenhum reboot agendado. Continua aberto só isto: **aplicar agora**
      (67 pacotes + 51 firmwares, agenda reboot +5 min) é decisão do dono.
- [x] **Rodar a guarda de offsite junto do verificador semanal** — **FEITO
      26/11 03:4x:** o runner do `od-pg-restore.timer` agora chama
      `tools/checar_offsite_pg.py --json` na mesma rodada do restore
      (`verificar_offsite()` em `runtime/verificar_restauracao_pg.py`) e avisa
      no Telegram só quando é **DIVERGÊNCIA** (sha256 diferente, truncado,
      ausente). HD desplugada / snapshot pendente (`aguardando`/`ausente`)
      continuam sem alarme — ficam registrados como `provado: false`. Falha
      do próprio checador (sem JSON, timeout) também é divergência. Prova
      viva: dump `od-2026-11-25_0250.sql.gz` com sha256 idêntico no canal e
      nas 2 HDs (`offsite_ok: true`, sem mensagem). 7 casos novos no arquivo.
- [x] **Comparador de modelos lado a lado (P1 nº 8)** — **FEITO 26/11:**
      `core/comparador_modelos.py` manda o MESMO prompt em 2–4 modelos da
      cadeia do chat em paralelo (`asyncio.gather`) e devolve resposta +
      latência medida por modelo; falha/timeout de um vira campo `erro` sem
      derrubar os outros (teto por modelo, 90 s padrão). Rotas
      `GET /admin/comparador/modelos` e `POST /admin/comparador/comparar`
      (admin), seção "Comparador de modelos" no painel com cartões lado a
      lado e render puro testado no node. 19 casos novos; prova viva com
      groq 564 ms / gemini 2.625 ms / gemma-local 18.585 ms e parede de
      18,6 s (= o mais lento, não a soma) — o paralelo é medido, não suposto.
- [x] **Fechar o offsite físico do backup** (sugestão de 25/11) — **FEITO 25/11:**
      o dump `od-2026-11-25_0250.sql.gz` está com sha256 idêntico (`3bfaff1c…`) no
      snapshot das **duas** HDs (`snapshot_od-2026-11-25_0346/0347`) e dentro do
      tar `od-2026-11-25_0301.tar.gz` que o canal do Telegram recebeu; a **cópia
      do HD restaura** (`testar_restauracao_pg.py`: 14 tabelas/604 linhas, 0,17 s)
      e a guarda `tools/checar_offsite_pg.py` (14 testes) confere isso por sha256
      — `OFFSITE OK`, exit 0. Resta a mídia física fora do local (dono).
- [x] **Recalibrar o piso do RAG híbrido para poder ligar o I2 com evidência**
      (sugestão de 25/11) — **FEITO 25/11:** `tools/recalibrar_piso_hibrido.py`
      provou que nenhum par (score, overlap) separa (os falsos positivos são as
      nossas transcrições citando a pergunta do gate; comb 0,439/0,447 >
      relevante mais fraco 0,410) e mediu o piso **só-lexical 0,47** (pior
      irrelevante 0,447 + 0,023). Gate nos dois modos **8/8 · 0/8 · 6/6 · 2/2**
      (`TestCalibracaoHibrida`), resgates reais intactos (eval 0,636) — I2
      **ligado por padrão**, piso denso intocado.
- [x] **Hook de pré-commit com a trava de reescrita maciça** — **FEITO 18/11:**
      `tools/trava_reescrita.py` virou a fonte única da régua (o orquestrador
      passou a delegar nele) e `tools/instalar_hooks.sh` instala o hook
      `pre-commit` (caminho absoluto da ferramenta, fallback relativo, escape
      `OD_TRAVA_OFF=1`/`--no-verify`). 13 testes, inclusive commit real
      bloqueado e commit normal passando. Instalado neste repositório.
- [x] **Painel/`/health`: “IA trabalhando agora” e lote órfão visível** —
      **FEITO 18/11** no `/admin`: seção “IAs no projeto” + rota owner-only
      `GET /admin/estado-ia` (versão/HEAD × origin, checkpoint vigente, árvore
      suja, idade do último registro e P0/P1). Registro parado há > 6 h com
      árvore suja aparece em vermelho — o lote órfão de 15:19 teria aparecido.
- [x] **Testar a cascata até concluir com CLI real** — **FEITO 18/11:**
      `executar_sessao` com as CLIs reais Interpreter → OpenClaude e
      `executar_cli` de verdade: Interpreter falhou em **11,4 s** (exit=1, sem
      saldo OpenAI) e OpenClaude respondeu **OK em 9,4 s**; estado final
      `concluido/implantado`, `cli_usada=OpenClaude`, **20,9 s** no total e
      árvore sem alteração feita pelas CLIs. Falta medir quanto do brief a CLI
      usa de fato (prompt real + diff) — checkbox abaixo.
- [x] **Medir quanto do brief a CLI realmente usa** — **FEITO 18/11:** OpenClaude
      com o prompt real: brief = **2624 chars de 5083 (51,6%)**; só-leitura
      **4/4 campos corretos em 7,8 s** e **0 arquivo tocado**; com diff real
      **3/3 corretos em 35,2 s**, **1 arquivo novo/0 existente alterado**.
      Resultado no histórico de `docs/IAS_DISPONIVEIS.md`.
- [x] **Reverter o lote órfão que regrediu o `orquestrador.py`** — **FEITO
      18/11** com a ordem do dono ("faça"): `git checkout -- orquestrador.py`
      (de volta a 1654 linhas) + `rm soma.py`; `tests/test_orquestrador.py`
      voltou a **116 passed**. A trava `_reescritas_em_massa` (regra 24) passa
      a impedir a repetição dentro do orquestrador.
- [x] **Acompanhar o download da playlist do Raul Seixas até o fim** —
      **FECHADO 21/11:** a unidade `od-radio-lista-raul` terminou em 18/11
      23:38 com **19/19 lotes `codigo=0`, 0 falha, acervo 502 (+5 no último)**
      (`logs/radio_link_lista_raul_seixas.log`). Conferência de hoje: **502
      mp3 em `acervo/` = 502 linhas no `acervo.db`**, **0 caminho ausente**,
      **0 duplicata exata** (sha256 de todas as 502), `.m3u` regerados e
      **AzuraCast 504 = 502 faixas + 2 locuções** (`/api/station/nicky/files`).
      Raul Seixas: **1 → 141 faixas** no acervo. Sobra só a pilha de
      quarentena do pipeline (38 arquivos em `revisar/`+`reprovadas/`,
      **nenhum idêntico ao acervo**): 25 gravações "Ao Vivo" que o dedupe
      endurecido marcou como parecidas com a versão de estúdio, 4 cópias
      exatas antigas em `revisar/duplicadas/`, 6 reprovadas por qualidade/
      duração e 3 ambíguas — por desenho o pipeline não apaga nem adivinha,
      então isso é decisão do dono (checkbox abaixo).
- [ ] **Dono decide a quarentena do acervo (38 arquivos)** — `revisar/`:
      aceitar como faixa própria as 25 "Ao Vivo" do Raul (são gravações
      distintas, hoje fora da rádio) ou manter fora; `revisar/duplicadas/`:
      4 cópias exatas que o pipeline manda o dono limpar; `reprovadas/`:
      6 arquivos <60 s ou bitrate baixo. Nada é apagado sem ordem.
- [x] **Auto-registro de restart do `od-core`** — **FEITO 21/11:**
      `core/registro_restart.py` roda no boot do modo `all` e acrescenta uma
      entrada em `iniciar/session.json` (chave `restarts_od_core`, últimos
      **30**): PID, commit, branch, horário, host, modo, usuário e motivo
      quando `OD_RESTART_MOTIVO` está definido. Escrita com `flock` no próprio
      arquivo (append-only, atômica), idempotente por PID, nunca derruba o
      boot e não sobrescreve JSON ilegível. `OD_REGISTRAR_RESTART=0` desliga.
      7 testes em `tests/test_registro_restart.py`.
- [x] **Limpar os resíduos do lote da madrugada de 18/11 (Cline)** — fechado
      em 18/11 ~10:50 com **ordem do dono** ("encerrou por falta de crédito,
      cota diária acabou"): removidos **171 `gerado_*.py`** (7 commitados +
      164 não-rastreados; conteúdo medido antes: só marcadores `pronto` /
      `[AUTORIZACAO]`, gerados 09:08–10:30) e **`teste_orquestrador.py`
      (raiz)** (158 linhas, 0 `test_*`). Árvore medida depois: **0 não
      rastreados**; gate completo = **5382 passed / 19 skipped / 0 falha**.
- [ ] **App por papel: 1 app com abas escondidas vs vários apps** — ideia do
      dono (15/11): "o APP está ficando complicado para os usuários… um
      usuário comum não precisa da aba admin; um familiar seria bom ter uma
      aba de botões para ligar as luzes, outra coisa que o comum não pode
      ter; o admin terá tudo". Recomendação do agente: **um só app com abas
      por papel** — o recorte já é do servidor (`user` = só leitura;
      `familia` = herda + a única escrita do lar `ha_device_control`;
      `admin` = `*`; `/auth/me` já devolve `role`), separar em vários apps
      triplicaria build/versionamento/política 9/9 sem ganho de segurança;
      entrega nova: aba **"Casa"** com botões data-driven (luzes/tomadas via
      `ha_device_control`) e filtro de abas no `OdHome` por `role`.
      **Aguardando decisão do dono.**
- [x] **Rádio: excluir música e liberar músicas de cantores bloqueados**
      (pedidos 2 e 3 do `txt.txt`, 17/11) — **ENTREGUE 17/11:**
      `integrations/radio_cantores.py` (listas `data/musicas_bloqueadas.txt` e
      `data/cantores_excecoes.txt`, `excluir_musica_do_acervo`, `eh_excecao`,
      `indesejado()` consultando a exceção antes do bloqueio) **mais** as 6
      rotas (`GET /api/radio/musicas`, `POST …/excluir`, `POST|DELETE
      …/bloqueadas`, `POST|DELETE …/excecoes`), a seção "Rádio — acervo e
      cantores" no painel `/admin` e o card "Curadoria do acervo" no
      `/radio-pro` (só o dono vê; 403 para conta comum). Gate 5347 passed e
      sandbox contra o acervo real sem alterar nenhuma faixa.
      **Sobrou um passo:** o `radio_link.py` ainda não recusa o download de
      faixa bloqueada — hoje o bloqueio impede o retorno pelo painel/página,
      não o pedido por link do YouTube (checkbox abaixo).
- [x] **`radio_link.py`: bloqueio de música vale no pedido por link**
      — **ENTREGUE 17/11 (regra corrigida no mesmo dia):** em **lista**,
      `_bloqueada_no_link()` analisa antes do download (título "Artista -
      Título" + pistas de canal/uploader, sem caixa/acento e com sufixo) e
      `_baixar_resto()` filtra o resto; lista toda bloqueada vira `rejeitada /
      musica_bloqueada`. Pedido **avulso** de faixa bloqueada baixa e entra na
      janela de decisão — o único bloqueio de download é o limite de
      tamanho/duração.
- [x] **Janela de decisão de 24 h (cantor ou música bloqueada)** —
      **ENTREGUE 17/11:** ao entrar faixa de cantor bloqueado **ou** de música
      bloqueada, o dono é avisado e tem `HORAS_DECISAO` (24 h) para permitir;
      permitiu → fica e vira exceção; sem decisão → `limpar_tocados()` apaga
      ao vencer o prazo (tocar não apaga mais). API `POST
      /api/radio/musicas/decisao`, bloco no painel e no `/radio-pro`. Gate
      5370 passed; +14 testes.
- [x] **Resumo diário das apagadas pela janela** — **ENTREGUE 17/11:**
      `resumo_diario()` lista só `motivo_fim=prazo` das últimas 24 h;
      `enviar_resumo_se_devido()` manda uma vez por dia após
      `OD_RADIO_RESUMO_HORA` (9 h) pelo timer; gate 5388 passed.
- [x] **Timer próprio da janela de decisão** — **ENTREGUE 17/11:**
      loop `radio-decisoes` no launcher checa a cada 60 s
      (`OD_RADIO_DECISOES_INTERVALO_S`) e roda vencimentos/lembretes em
      `to_thread`; gate 5382 passed.
- [x] **Lembrete de push 2 h antes do prazo** — **ENTREGUE 17/11:**
      `limpar_tocados()` manda "Faltam 2 h para decidir — rádio" uma vez
      por faixa (`lembrete_em`, env `OD_CANTORES_HORAS_LEMBRETE`); gate
      5379 passed.
- [x] **Push FCM ao entrar na decisão de 24 h** — **ENTREGUE 17/11:**
      `registrar_para_apagar()` avisa no celular na primeira marcação
      (data `origem=radio-decisao`); subprocesso do link monta o
      serviço sozinho; gate 5375 passed.
- [x] **Decisões da rádio no app Android** — **ENTREGUE 17/11 (1.45.1+2082):**
      card "Decisões pendentes (24 h)" no Painel (só admin) com prazo,
      quem pediu e os botões Permitir / Apagar já; `flutter test` 237
      passed / 2 skipped, APK publicado em `site/`.
- [x] **Excluir do acervo não bloqueia** — **ENTREGUE 17/11:**
      `excluir_musica_do_acervo(bloquear=False)` e a rota de exclusão só
      gravam em `musicas_bloqueadas.txt` com `bloquear: true` explícito;
      apagar para depois baixar uma versão melhor voltou a ser possível.
- [x] **Fechar o lote órfão da árvore (17/11)** — **ENTREGUE 17/11:** gate
      completo **5319 passed / 16 skipped / 0 falha** (210,60 s, exit 0) e
      `flutter analyze` 0 issues + `flutter test` **228 passed / 2 skipped**
      (antes do lote eram 223); commits por assunto publicados em
      `origin/master` e `od-core` reiniciado com prova viva. O lote era
      `radio_cantores.py`, `server.py` (reboot via `updater._reboot()`),
      `supply_depot.py` (staging), `tasks_screen.dart` (`{}` válido),
      `test_task_queue.py` e **10 arquivos de cobertura** — autor de origem
      não identificada (regra 23), registro completo no CHANGELOG.
- [x] **Curadoria do acervo também no app Android** — **ENTREGUE 17/11
      (1.46.0+2083):** tela "Curadoria do acervo"
      (`app/lib/screens/curadoria_screen.dart`) aberta pelo card novo do
      Painel (só admin, via `Navigator.push` — sem nona aba): busca no acervo,
      selo `bloqueada`/`cantor bloqueado`, excluir (com e sem bloquear),
      bloquear/desbloquear e liberar/tirar exceção de cantor bloqueado, tudo
      nas rotas `/api/radio/musicas*`. `OdApi` ganhou `OdMusicaAcervo`,
      `OdParMusica`, `OdCuradoria` e 6 métodos. 20 testes novos de app;
      `flutter analyze` 0 issues e `flutter test` **257 passed / 2 skipped**;
      APK publicado em `site/`.
- [x] **`/radio-pro` volta a mostrar a curiosidade da música** — **ENTREGUE
      17/11:** `site/radio-pro.html` ganhou `<div id="agoraCurio">` no card
      "Tocando agora" e `desenhaAgora()` pinta `t.curiosidade` (vazio quando a
      faixa não tem, sem placeholder). Teste novo em `tests/test_radio_pro.py`
      (58 passed) e rádio completo 216 passed. Sem restart (o HTML é servido
      do disco a cada requisição). Pedido do dono no `txt.txt` (17/11).
      Diagnóstico medido antes da correção: `grep -i curiosidade
      site/radio-pro.html` = **0 ocorrências**, enquanto `GET /api/radio/agora`
      já devolvia `tocando.curiosidade` por `integrations/radio_agora.py::
      curiosidade_da_musica()` (lê o `acervo.db` em modo ro e filtra o
      placeholder "curiosidade pendente") — o dado existia na API e a página
      nova não o exibia.
- [x] **Letra com tradução lado a lado para música internacional** —
      **ENTREGUE 17/11:** `integrations/radio_traducao.py` traduz pela cadeia
      de LLM do OD (Gemini → Groq → local) com cache em
      `data/radio_traducao.json` chaveado por artista|título + hash da letra
      (letra em português vira `JA_PT` e não mostra coluna); rota nova
      `GET /api/radio/pro/traducao` (rotas 137 → 138) e o card "Letra" do
      `/radio-pro` em duas colunas (empilha no celular). 25 testes novos em
      `tests/test_radio_traducao.py`; prova viva com "The Sound of Silence"
      → "Olá, escuridão, minha velha amiga". Pedido do dono no `txt.txt`
      (17/11: "letra de musica internacional poderia ter uma lista paralela
      com a tradução").
- [x] **Comparador de modelos lado a lado** — ideia trazida do GSN Offline
      (17/11): mesmo prompt no Gemini, Groq e Local ao mesmo tempo. **ENTREGUE
      26/11** (fila item 5): `core/comparador_modelos.py`, `GET
      /admin/comparador/modelos` + `POST /admin/comparador/comparar` e seção no
      `/admin`; timeout e falha por modelo isolados; prova viva com groq
      564,5 ms / gemini 2.625,4 ms / gemma-local 18.584,5 ms. Sem persistir
      comparações.
- [x] **Monitor de hardware do comparador (CPU/RAM)** — **FEITO 26/11:**
      `_ColetorHardware` em `core/comparador_modelos.py` amostra
      `/proc/stat` + `/proc/meminfo` a cada 250 ms durante cada chamada; o
      resultado leva média/pico de CPU, RAM usada, `ram_delta_mb_pico` e
      porcentagem da RAM do servidor, e o cartão do painel mostra embaixo do
      nome. Prova viva: groq 441,8 ms · CPU 10,9% (pico 11,2%) · RAM +0 MB;
      gemini 1.017,4 ms · CPU 12,4% (pico 20,2%) · RAM +8,1 MB; numa segunda
      rodada com o local: CPU média 33,7–36,4%, pico 52–56%, RAM +55,9 MB.
      **Ressalva documentada:** as chamadas rodam em paralelo, então o número
      é do servidor inteiro (como a máquina é compartilhada com o od-core,
      ele não isola o modelo).
- [ ] **VRAM por modelo no comparador** — não medido e hoje imensurável:
      o LLM local roda em CPU e não há contador de GPU exposto
      (`nvidia-smi` ausente). Reabrir quando entrar GPU; o lugar é
      `_snapshot()`.
- [x] Task Queue: manter as tasks **concluídas visíveis** na API com retenção
      limitada — **ENTREGUE 14/11** (histórico em `completed/`, poda automática,
      `OD_TASK_QUEUE_KEEP_COMPLETED=200`)
- [x] Task Queue: expor `queue_depth`, `workers`, `dead_letter` e as métricas
      no `/health`/painel — **ENTREGUE 14/11: bloco `task_queue` no `GET
      /health` (fila, executando, workers, dead letter em disco, retenção
      `concluidas/keep` e contador `pruned`), fora do cache de 8 s, mais check
      `task_queue` não-crítico no HealthMonitor (degradado com workers parados
      ou dead letter); 5 testes novos em `tests/test_task_queue.py`**
- [x] Task Queue: avaliar ligar em produção com **1 worker** e medir o custo
      real (CPU/RAM) — **ENTREGUE 14/11: `OD_TASK_QUEUE_ENABLED=1` e
      `WORKERS=1` no `.env`; ocioso ligado 3,20% CPU / 231 MB vs 3,65% /
      226 MB desligado (+5,1 MB), rajada de 50 tasks 14% CPU / 68 ms por
      task, retry real com dead letter em 6 s, e action de LLM longa
      (105 s) custando 0,23% de core na fila — o custo é do modelo. A
      "por uma semana" virou contínuo: fila ligada desde 14/11**
- [x] Task Queue: mostrar o **histórico de concluídas no painel/app** — **ENTREGUE
      14/11: bloco "Tarefas (Task Queue)" no `/admin` e aba "Tarefas" no app,
      com status, tentativas, duração, resultado/erro, filtro, retry e apagar;
      Python 4678 e flutter 223 verdes**
- [x] App: **publicar o APK com a aba Tarefas** — **JÁ ENTREGUE; verificado e
      fechado em 14/11 ~17:50 a pedido do dono.** O item nasceu desatualizado:
      o release `a1f362a` (14/11 13:22) já tinha bump + `app/build_apk.sh` +
      publicação. Prova: os 2 APKs de `site/` (build 13:07) são
      **1.45.0+2081** (aapt2), a aba está **dentro do binário** (`Tarefas`×3,
      `listTasks`, `tasks_screen` em `libapp.so`), o `sha256` do
      `GET /app/version` bate com o arquivo, não há mudança em `app/` depois
      do build e `flutter analyze` 0 issues + 223 testes verdes reexecutados
      em 14/11.
- [x] Task Queue: **criar tarefa pelo painel/app** — **ENTREGUE 14/11:
      painel `/admin` (HTML/JS `tqCriar` + select de actions do catálogo +
      payload JSON + botão Enfileirar) + app aba Tarefas (botão ＋ chama
      `OdApi.createTask`) + endpoint `POST /admin/tasks` valida action/payload
      e responde 201 com task em `pending`; SSE `task_created` repete o id;
      fila desligada = 503 legível. Commit `da19eb3`, testes: task_queue 27
      + api 202 verdes**
- [x] App: usar **SSE** (`/admin/tasks/events`) na aba Tarefas em vez do polling
      de 5 s — **ENTREGUE 14/11:** `streamTasks()` + `OdTaskEvent` no `OdApi` +
      `TasksScreen` com `_assinar()`/`_sseCaiu()`/`_aplicar()` (mesmo contrato do
      Downloads); indicador `📡 ao vivo (SSE)` / `↻ consultando (5 s)`; fallback
      polling 5 s + reconexão 15 s; testes flutter 223 verdes. Painel `/admin`
      JÁ USAVA SSE (`tqSse` emite `task_created`/`task_started`/
      `task_completed`/`task_failed`/`task_retried`/`task_dead_letter`).
- [x] Task Queue: **filtro/paginação por data no histórico de concluídas** — **ENTREGUE
      14/11:** `list_tasks(sort_by_finished=True)` no `TaskQueue` + `?sort_by_finished=1`
      no `GET /admin/tasks` e SSE; app `TasksScreen` com toggle
      `Ordenar por conclusão` (ícone 🕒/⏱️) que recarrega a lista; concluídas/falhas/
      dead_letter ordenadas por `finished_ts` desc, pendentes/rodando por prioridade/
      `created_ts`. Testes: flutter 223 + Python 229 verdes. Commit `ce643a2`.
- [x] Task Queue: métricas de retenção no `/health` (quantas concluídas em
      disco, quantas podadas por ciclo) — **ENTREGUE 14/11 (§15): bloco
      `task_queue` traz `completed_on_disk/keep_completed` e o contador
      `pruned` acumulado, fora do cache de 8 s**
- [x] Detector de recusa "etiqueta de log" refazendo quase toda resposta do
      dono — **11 em 14/11** (5 em 13/11, 4 em 12/11; 7 seguidas às
      15:28–15:32), cada uma com 2 chamadas de LLM e 4–8 s: medir falso
      positivo do gatilho v1.15.0 (caça a etiqueta em qualquer posição) e
      relaxar (14/11, §18) — **ENTREGUE 14/11 (§20): etiqueta só NO INÍCIO
      refaz; no meio sem frase de recusa só limpa (`limpa_etiquetas_resposta`,
      7 pontos); em recusa a resposta fica crua p/ o cache banir; prompt
      proíbe a etiqueta na resposta — prova pós-restart com 0 refazs**
- [x] Query Router não persiste: load falhou (`Ran out of input` = pickle
      vazio), re-treina com **26 exemplos** e o save falhou
      (`cannot pickle '_thread.lock'`) → recomeça do zero a cada boot —
      consertar ou desligar (14/11, §18) — **ENTREGUE 14/11 (§20): causa
      raiz reproduzida (tokenizer era método vinculado → pickla o extrator
      com `threading.Lock`); `tokenizar_pt` de módulo + `_dump_atomic`;
      teste de persistência real (boot sem re-treinar) e prova viva
      `Query Router model loaded` sem bootstrap**
- [x] Autoconhecimento fastpath: pergunta sobre os **próprios papéis e
      capacidades do OD** deve responder do CÓDIGO
      (`core/security/permissions.py` / `capabilities.py`), não do LLM
      frio — em 14/11 15:42 o OD respondeu "operator/developer/auditor/
      service account/guest", papéis que **não existem**, e ainda declarou
      "Estado verificado" (14/11, §19) — **ENTREGUE 14/11 (§20): action
      `role_list` (126) + intenção com menção obrigatória ao OD + permissão
      user/familia; prova viva `fastpath:role_list` em 28,9 ms com os 5
      papéis reais**
- [x] F1: fazer o `execute_parallel` executar as actions reais do registry, com
      timeout por ferramenta (hoje o `process()` responde actions pelo fast
      path e o grafo só orquestra conversa) — **ENTREGUE 10/11: nós `select_tools` e `execute_parallel` no grafo usam `execute_action` do orchestrator**
- [x] F1: `RetryPolicy` por nó para falha transitória de LLM/action, sem
      reexecutar o pipeline inteiro — **ENTREGUE 10/11: políticas padrão + `OD_RETRY_<NÓ>` no motor do grafo; ver §21 da transcrição**
- [x] F1: consumir `pending_human_input` de verdade no chat (pausa + aprovação
      do dono) usando `retomar()`, hoje só testado no motor — **ENTREGUE 10/11: `retomar_turno_humano` no orchestrator + `_pending_human_loop` + `_handle_human_loop_decision` no Telegram bot; 11/11: duplicata que sombreava o método foi removida, a retomada roda `human_loop` + `post_process` e a **origem foi ligada** — `select_tools` pausa ações sensíveis (`OD_HUMAN_APPROVAL_ACTIONS`, padrão: escritas no Google) com `pending_human_input`, e o `sim` executa a action no resume; 4 testes em `test_orchestrator_graph_integration.py`. 11/11: `ha_device_control` e `google_calendar_create` foram unificados no mesmo human_loop (com alvo/`quando`), pulando a confirmação de 2 passos interna via contextvar — +3 testes**
- [x] RAG: avaliar cache de embedding de documento (evitar reembeddar o mesmo
      texto após restart) — **FEITO 28/11:** já existia (o store persiste
      `vector_json` e o `sync()` compara o sha do conteúdo), faltava PROVA e
      sobrava desperdício. Provado em `tests/test_rag.py::TestCacheDeEmbedding`
      (3 casos, contando chamadas do provider): sync sem mudança e **restart**
      com store novo no mesmo diretório não embedam nada; só o chunk alterado
      reembeda. Corrigidos no caminho dois desperdícios reais: **(a)** o bloco
      de `add_many` do `sync()` estava **duplicado** (gravava duas vezes por
      sync); **(b)** `_listar_namespace()` listava órfãos com
      `search(ns, "")`, pagando **um embedding por sync** — agora usa
      `VectorStore.list_docs()` (leitura pura, 2 testes em `test_vector.py`)
- [x] Rádio: testar de verdade pelo chat (entregue em 10/11, nunca exercitada
      no chat real) — **FEITO 11/11 14:20: "ligar a radio" → `route=action_intent`,
      `fastpath:radio_play`, 1,49 s, stream no ar (`status=tocando`)**
- [x] Rádio: **formatador próprio para `radio_play`/`radio_stop`** — **JÁ EXISTE:**
      `_formata_radio` (intents.py:1616) trata `radio_play`, `radio_stop`,
      `radio_volume`, `radio_status` com respostas PT-BR amigáveis (emoji,
      volume, PID, hint). O roteamento via `format_intent_result` já direciona
      para este formatador. Testado ao vivo 11/11.
- [ ] Bluetooth: pareamento falha com `AuthenticationFailed` usando PIN `0000`
      (o adaptador recusa o PIN padrão; investigar e documentar o PIN real)
- [x] Chat: o core só tinha `gemma-local` (qwen2.5-coder-3b) na cadeia de LLM
      — **ENTREGUE 11/11: cadeia `gemini,groq,local` via `OD_CHAT_PROVIDERS`,
      `GeminiProvider`/`GroqProvider` em `core/llm.py`; local por último**
- [ ] Chat: enxugar o prompt/contexto para o Gemini caber na cota gratuita —
      **premissa revista 17/11:** a cota gratuita é **20 requisições/dia** (não
      é bytes): enxugar o prompt economiza token, não requisição. A cadeia do
      chat já é `groq,gemini,local` desde 14/11 e o `/health` alerta em 80% da
      cota. O ganho real deste item virou **menos latência e mais contexto útil**
      (o prompt medido é ~3,3 mil caracteres por mensagem no log).
- [x] Chat: incluir OpenAI na cadeia automaticamente quando as chaves tiverem
      saldo (hoje as duas dão `429 no credits remaining`; teste de crédito no boot)
      — **FEITO 28/11:** `runtime.launcher.openai_com_credito()` faz uma sonda
      de 1 token (`OD_OPENAI_CREDITO_TIMEOUT_S`, padrão 8 s) e só inclui o
      provider se a chamada voltar; 429, rede fora, timeout ou resposta vazia
      = fora da cadeia, com warn (nunca derruba o boot).
      `tests/test_launcher_openai_credito.py`: **8 testes** (sonda + cadeia)
- [x] Chat: cota do Groq visível/alertada no `/health` — **ENTREGUE 14/11:
      check não-crítico `llm_quota` no `/health` (30º check) lista TODOS os
      providers com `pct_used` e degrada quando algum passa de
      `OD_QUOTA_ALERTA_PCT` (padrão 80%) ou esgota; limite do Groq provisório
      500 ajustável sem código via `OD_QUOTA_GROQ_LIMIT` (quando um 429 real
      bloquear, ajustamos para o valor verdadeiro medido); prova viva no
      serviço reiniciado: `llm_quota: gemini 0% (0/20); groq 0% (0/500);
      openai 0% (0/100)`**
- [x] Pesquisa web: criar action de busca ("pesquise na internet …" hoje cai
      no LLM e ele recusa alegando não ter internet) — é a queixa literal do dono
      em 11/11: "não está pesquisando" — **ENTREGUE 14/11: `web_search`
      (DuckDuckGo lite) no catálogo E ligada à intenção do chat (`core/intents`
      reconhece pesquise/busque/procure + veículo + conector); prova viva
      1,05 s / 0,74 s com 5 resultados reais; sem fonte, degradação honesta**
- [x] Pesquisa web nos papéis `user`/`família` — **FEITO 14/11 (commit
      13ac90d): `web_search` na lista do papel user (família herda); prova viva
      com conta comum: 1,00 s no papel user e 0,68 s no família, resultados
      reais; `mapa_forca_consulta` segue só do dono**

> Turno de 11/11 14:25 (registro da regra 21): sugestões mostradas e não
> escolhidas → "colocar o Gemini como 1º provider do chat", "criar action de
> pesquisa web" e "formatador de radio_play/radio_stop" — todas já estão como
> checkbox acima; nenhuma perdida.

> Turno de 14/11 10:05 (registro da regra 21): sugestões mostradas e não
> escolhidas → "liberar a pesquisa para família/user" (feita neste turno),
> "provar account comum no chat" e "medir o acerto do cache exato" (checkbox
> do cache exato já aberto). Nenhuma perdida.

> Turno de 14/11 09:45 (registro da regra 21): sugestões mostradas e não
> escolhidas → "expor a pesquisa web para família/user" (checkbox novo de
> `web_search` nos papéis), "provar a fila com um job real" (checkbox da Task
> Queue) e "medir o acerto do LLMCache exato" (novo checkbox abaixo). Nenhuma
> perdida.

- [x] Cache exato: medir o hit rate do `LLMCache` no uso real — **MEDIDO
      14/11: 12/113 = 10,6% (30 dias; 13,6% nos últimos 7); cada hit custa
      10,4 ms contra 33,5 s do LLM (p50). Potencial do semântico no tráfego
      real: 0 acertos extras em 0,95, 0,90 e 0,85 (24 mensagens elegíveis;
      70% do tráfego é comando e nunca deve ser cacheado). Conclusão: manter o
      exato; semântico não paga o investimento com a amostra atual**

> Turno de 14/11 16:10 (registro da regra 21): sugestões mostradas e não
> escolhidas → "ligar a fila em produção com 1 worker", "criar tarefa pelo
> painel/app" e "SSE na aba Tarefas do app" — as três já têm checkbox neste
> backlog/bloco da fila. Nenhuma duplicada, nenhuma perdida.

> Turno de 14/11 09:15 (registro da regra 21): sugestões mostradas e não
> escolhidas → "ligar a `web_search` à intenção de pesquisa" (já no bloco do
> lote / checkbox de pesquisa web), "decidir e ligar o I1 medindo o impacto"
> (checkbox I1 da Semana 9-10) e "provar a Task Queue com um job real" (novo
> checkbox abaixo). Nenhuma perdida.

- [x] Task Queue: **ligar em produção** — **LIGADA em 14/11** com
      `OD_TASK_QUEUE_WORKERS=1`: custo medido com `/proc` (ocioso 3,20% CPU /
      231 MB; rajada de 50 tasks reais 14,03% CPU, +0,1 MB, 68 ms/task, p50 de
      execução 0,7 ms; retry real com dead letter em 6,01 s). Achado e
      corrigido no caminho: o `task_queue` nunca chegava ao `APIConfig`
      (503 permanente). 52 registros de teste removidos no fim. Custo com action
      de LLM longa (fila sandbox + llama-server real): task de 600 tokens levou
      105 s, com **312% de 1 core no llama-server** e **0,23% no processo da
      fila**; com 1 worker, task curta atrás de uma LLM de 14,9 s esperou
      14,5 s — action longa serializa a fila (avaliar 2 workers para LLM). O gate também
      acusou o pool do RAG no limite (alvo na 24ª posição): `TOP_K_CANDIDATOS`
      24 → **32**, medido com grid (600 células válidas, 8/8 + 8/8 + 6/6)
- [x] Task Queue: **task concluída some da API** (achado de 14/11) — **ENTREGUE
      14/11: histórico em `queue_dir/completed/`, visível no `GET`/lista, com
      `OD_TASK_QUEUE_KEEP_COMPLETED` (200) e poda automática das mais antigas;
      prova em sandbox e gate 4677**

> Turno de 14/11 08:30 (registro da regra 21): sugestões mostradas e não
> escolhidas → "fechar o lote pendente (gate, commits, push, restart)",
> "remover a duplicata de `_task_queue_or_503` e testar a Task Queue" e
> "ligar a `web_search` à intenção de pesquisa" — as três já estão no bloco
> "Lote de 13/11 fora do registro" e nos checkboxes de R1/pesquisa web.
> Nenhuma duplicada.

> Turno de 11/11 15:35 (registro da regra 21): o texto exato das 3 sugestões
> não foi persistido (são cartões efêmeros) — o que ficou registrado é o que o
> próprio turno declarou em aberto, virando os checkboxes abaixo.

- [x] Chat: **reservar 20 req/dia do Gemini** — **ENTREGUE 14/11:** `QuotaTracker`
      em `core/resilience.py` rastreia uso diário por provider (padrão: gemini=20,
      groq=1000, openai=100, demais=ilimitado); persiste em `data/llm_quota.json`;
      `_provider_tem_quota()` no Orchestrator pula provider sem cota antes de
      tentar; `record_usage()` registra sucesso; `reserve()` permite reservar
      para rotas prioritárias; providers desconhecidos têm cota ilimitada (não
      quebram testes). Commit `ddf7b88`.
- [x] Chat: expor o **status dos disjuntores** (aberto/fechado + reativação) no
      `/health` — **JÁ ENTREGUE:** check `circuit_breakers` no HealthMonitor
      (14/11, §15) mostra `llm:groq/gemini/gemma-local` com estado, falhas,
      limite e tempo de recuperação. Exemplo: `3 fechados — llm:groq:fechado
      (falhas=0/5,rec=30s); llm:gemini:fechado...` (não-crítico, degrada se
      algum aberto).
- [x] Chat: `llm_cache` ainda pode servir resposta inventada de **conversa
      comum** (o guarda atual só bloqueia comando de action) — **ENTREGUE 17/11:**
      `_resposta_do_cache()` valida na LEITURA com as guardas atuais e apaga a
      entrada inválida (vira MISS), no cache exato e no semântico; o aviso
      "⚠️ Não executei nada" saiu do cache; 7 testes novos
      (`TestCacheDeConversa`), gate verde, sem bump. Medido no cache vivo: 4 de
      144 entradas passaram a ser recusadas (1 invenção de agenda + 3 avisos).
- [x] Anti-falso-sucesso: `_FAKE_ACTION_RES` só cobria agenda/compromisso —
      **ENTREGUE 18/11:** conhecendo a saída real da rota de ação
      (`intents._formata_radio`: `📻 Rádio tocando (volume 50%).`,
      `🔊 Volume da rádio: 20%.`, `📻 Rádio parada.` — nunca "com sucesso"),
      a regex ganhou (a) participíos de mídia/casa na construção "… com
      sucesso" e (b) `volume definido/ajustado para N%`. Medido no cache vivo
      (145 entradas): **3 novas recusadas**, todas invenções de fato
      ("Radio ligada com sucesso", "Volume definido para 20%"); nenhuma
      resposta legítima da rota foi recusada (teste cobre os formatos reais).
      Fica de fora, por falta de evidência: afirmação de estado sem "com
      sucesso" ("Radio ligada.") — pode ser leitura verdadeira.
- [x] Chat: `llm_cache` não guarda resposta de modelo local — **testado e
      descartado em 17/11:** sem evidência de erro (as invenções reais foram
      de nuvem) e derruba o cache normal (`test_second_identical_message_hits_cache`).
      **DESCARTADO 28/11:** paredes de cache para modelo local prejudicam mais
      do que protegem; reabrir só com caso real de palpite do 3B cacheado.

> Turno de 12/11 09:35 (higiene de 11/11 publicada): sugestões mostradas e não
> escolhidas → "tapar os buracos de intenção" e "resolver o `Saída:
> desconhecido` do `radio_status`" entraram como checkbox abaixo; "implantar a
> stack OTel" já existe como item de infra na Semana 1-2 (não duplicado).

- [x] Intenções: tapar os buracos de casamento ("qual o uso de disco" → `None`,
      enquanto "quanto de espaço livre no disco" → `disk_usage`) — **FEITO 12/11:
      disco/memória/cpu aceitam uso/ocupa/cheio/disponível/quantos; e a action
      de disco deixou de ser NEGADA pelo escopo (`SCOPE_EXEMPT_ACTIONS`)**
- [x] Rádio: `radio_status` responde "Saída: desconhecido" — **JÁ CORRIGIDO:**
      `_formata_radio` (intents.py:1647-1659) só mostra "Saída:" se
      `volume_sink` existir no retorno da action; `radio_status` (actions.py:1738)
      só inclui `volume_sink` se `pactl get-sink-volume` funcionar — caso
      contrário omite a linha. Teste: `test_intents.py` cobre radio_status
      parado/tocando.

> Turno de 12/11 10:00 (intenções de disco/memória/cpu): sugestões não
> escolhidas → "auditar as demais actions contra o gate de escopo" e "corpus de
> frases reais do dono na suíte de intenções" entraram como checkbox abaixo;
> "sink do radio_status" já estava registrado, não duplicado.

- [x] Segurança: auditar as demais actions de leitura contra o gate de escopo —
      **FEITO 12/11: as 122 actions × 3 papéis; a do disco era a única negação
      indevida. `tests/test_scope_audit.py` virou rede de regressão**
- [x] Segurança: **política de `/tmp` e fechar o bypass** — **JÁ IMPLEMENTADO:**
      `caminho` e `origem` em `_PATH_PARAM_KEYS` (scope.py:81) + `/tmp` em
      `allowed_roots` por padrão no `ScopeEngine` (scope.py:145-148) quando
      usa raiz padrão do projeto. `stt_transcrever` e `filebrowser_envia` agora
      passam pelo gate de escopo; `/tmp` permitido automaticamente. Se caller
      passar `allowed_roots` explícito, `/tmp` NÃO é adicionado (política
      restritiva). Testes: `test_scope_audit.py` inclui as duas actions.
- [x] Intenções: **corpus com frases reais do dono** — **ENTREGUE 18/11:**
      `tests/test_corpus_frases_dono.py` (32 testes): 13 frases verbatim, cada
      uma com o arquivo de `iniciar/` onde está registrada (o próprio teste
      confere que a frase está lá — corpus não vira invenção), params
      semânticos (`city`, `moeda`, `volume`), 2 frases de conversa que o fast
      path não pode sequestrar e as etapas de `datetime`. Crescer = acrescentar
      a frase nova + a origem.

> Turno de 12/11 10:22 (auditoria de escopo): sugestões não escolhidas →
> "decidir a política de /tmp e fechar o bypass do escopo" virou checkbox
> abaixo; "sink do radio_status" e "cota/disjuntores no /health" já estavam
> registrados.

- [x] Segurança: **decidir a política de `/tmp` e fechar o bypass** — **DECIDIDO/
      IMPLEMENTADO 14/11:** `/tmp` permitido por padrão no `ScopeEngine` (raiz
      padrão do projeto); `caminho`/`origem` em `_PATH_PARAM_KEYS`. Se
      `allowed_roots` explícito, `/tmp` não é adicionado (restritivo). STT e
      FileBrowser funcionam com `/tmp` por padrão; política restritiva sob
      controle do caller.

> Turno de 19/11 14:55 (retomada "leia iniciar", lote do Vigia da Rede):
> sugestões não escolhidas → as três abaixo (regra 21).

- [x] **Fechar o lote do Vigia da Rede que está na árvore** — **FEITO 19/11**
      com a ordem do dono ("assuma e feche"): diff revisado (papéis, formatadores,
      rotas com `_require_admin`, bloqueio como escrita sensível), CHANGELOG +
      este TODO + `iniciar/`, **gate completo 5510 passed / 19 skipped / 0
      falha**, commit e restart verde com prova viva (`/admin/vigia` 200,
      `/health` ok=true, fast path "reconhece o dispositivo" sem LLM). O alerta
      agora diz se o aparelho está conectado, quando foi visto e onde responder.
      Implementação de origem desconhecida (achada pronta na árvore); fechamento
      por Freebuff (Buffy).
- [x] **App reexibia notificação antiga ("Decisão de 24 h" de prazo vencido)** —
      **FEITO 19/11:** o servidor estava limpo (loja vazia, nenhum push do
      título desde 18/11); quem republicava era o app
      (`onMessageOpenedApp.listen(show)` e `getInitialMessage()` → `show`).
      Só o foreground (`onMessage`) exibe localmente agora; toque/abertura
      consomem o evento sem reexibir. `flutter analyze` 0 issues e
      `flutter test` **257 passed / 2 skipped**. Falta só o próximo APK.
- [x] **Cascata de CLIs em ordem de melhor resultado (ordem do dono 19/11)** —
      **FEITO 19/11:** `tools/medir_cascata_ias.py` mediu as 13 CLIs com o
      mesmo prompt (`logs/medicao_cascata_ias.json`): Kilo (modelo novo
      `kilo-auto/free`) e Agy no topo, depois OpenClaude, Cline e as falhas
      por fail-fast. Freebuff segue fora **por modo** (só `login`/`doctor`;
      TUI no stdin) e entra em 1º assim que tiver headless. Também corrigidos
      o conflito de flags do Codex e o `--skip-trust` do Gemini.
- [x] **Provar a restauração do backup do Postgres** — **FEITO 19/11:**
      `tools/testar_restauracao_pg.py` sobe um cluster temporário (sem
      superusuário, sem tocar no `od`), restaura o dump de 19/11 02:50 e compara
      as linhas com os blocos `COPY` do próprio dump: **14 tabelas, 589 linhas,
      0,17 s**;      `tests/test_restauracao_pg.py` 4 passed. O offsite físico
      continua pendente (é outra perna da entrega).
- [x] **Verificação semanal da restauração com aviso no Telegram** — **FEITO
      19/11:** `runtime/verificar_restauracao_pg.py` + `systemd/od-pg-restore.
      {service,timer}` (domingo 03:30, `Persistent`), silêncio no sucesso e
      aviso com a saída do restore na falha; estado em
      `data/pg_restore_verificacao.json`. Prova viva: unit **success/0** em
      3,5 s, 14 tabelas/589 linhas, 0 temporário residual; 6 testes novos.
- [x] **Vigia da Rede na aba do app (Flutter)** — **FEITO 19/11:** card do
      Vigia no Painel (admin-only, best-effort) com os pendentes e os botões
      **Reconhecer** e **Bloquear** na própria tela do alerta; usa as MESMAS
      rotas `/admin/vigia*` do painel/chat (`_require_admin`), bloqueio com
      diálogo de confirmação e recarga do card após a ação. Modelo mostra
      estado (conectado/fora/sem informação), "visto há…" e desde quando está
      pendente. `flutter analyze` 0 issues, `flutter test` **264 passed /
      2 skipped** (7 novos em `app/test/vigia_rede_test.dart`), gate Python
      **5523 passed**. APK **1.46.1+2084** gerado e publicado em 19/11 e
      **instalado pelo dono em 21/11** — lote encerrado.
- [x] **P1 nº 6 — modo colapso declarado** — **FEITO 21/11:** última P1
      aberta da revisão de 17/11. `core/colapso.py` conta falhas seguidas de
      nuvem (3 por padrão) e declara o colapso; o orquestrador tira a nuvem da
      cadeia nos dois caminhos (normal e streaming), a resposta ganha o prefixo
      "⚡ modo colapso — respondendo só com a IA local" e o `/health` degrada com
      o motivo. Declaração manual (`colapso acao=ligar`) sobrevive à volta da
      nuvem; a automática é revogada após 2 sondas TCP OK. Action `colapso`
      (catálogo 131 → 132); 17 testes novos em `tests/test_colapso.py`.

- [x] **Homebox em uso: inventário físico real** — **FEITO 21/11** (pedido do
      dono: *"o que temos guarde no homebox"*): o cliente ganhou `local`,
      `fabricante`, `modelo`, `serie` (local vira entidade de tipo Location;
      modelo/série pelo PUT completo) e a action nova `homebox_locais`
      (catálogo **129**). Cadastradas **9 peças em 2 locais**:
      **Nicky — Servidor** (OptiPlex 3040 i5-6500, SSD 256 GB, dois Seagate
      Expansion 1 TB por série, Raspberry Pi 4, ESP-01S+DHT22) e
      **Energia — Fase 1** (Felicity FLA12100 comprada, Attiv 1500 VA BI por
      série, PWM 30 A), com as regras de ouro do plano solar nas notas. Fonte
      do plano: `txt.txt` (21/11) + medição da máquina (`hostnamectl`,
      `lsblk`, `lscpu`, `free`).
- [ ] **Inventário, próximo passo:** acrescentar o que entra da Fase Nicky
      (cabos 16 mm/fusível/terminais em dez/26, inversor 12 V→127 V 600 W em
      jan/27, painel 100 W DIY em fev/27) e a casa 24 V quando forem
      comprados — hoje o Homebox só guarda o que o dono já tem.

### Continuidade (plano de 12/11 — `docs/CONTINUIDADE.md`)

> A `readiness_report` mediu **6/9**: reprovam energia, conhecimento e
> comunicação. Estas são as tarefas que fecham os buracos, em ordem de risco.

- [x] Medir a prontidão no sistema (`readiness_report` + `docs/CONTINUIDADE.md`)
- [ ] **Energia:** nobreak 1200–1500 VA **com USB** (shutdown gracioso) — é a
      compra nº 1; sem ela nenhum outro ganho sobrevive ao apagão.
      **21/11 — o que já existe (lido de `analise/No Break/`):** há um
      **Intelbras Attiv 1500 VA Bivolt** em uso (etiqueta HS BI.A0008555344,
      fabricado 26/11/25, 1500 VA / 750 W, 2 baterias 12 V 7 Ah, 8 tomadas).
      Ele **não tem porta USB/serial** — a linha Attiv não comunica, o software
      de gerenciamento da Intelbras só vale para as linhas com USB —, então
      `upsc`/shutdown gracioso **não é possível com ele**. O datasheet ainda
      desaconselha fontes com PFC ativo, que é o caso de servidor: o Attiv
      segura a queda e o religamento, mas não substitui a compra do USB.
      Os prints de 11/04 mostram o Attiv 1200 VA como referência de preço
      (R$ 792–860).
- [ ] **Comunicação:** segundo nó na LAN (ntfy/Matrix local + PWA offline) ou
      2 rádios LoRa Meshtastic — hoje o Telegram é o único canal externo
- [x] **Acervo:** baixar ~25 GB de ZIMs (Wikipédia PT completa, WikiMed,
      WikiHow, iFixit/Appropedia) — **FEITO 12/11: 14 ZIMs, 40,3 GB (25,3 GiB
      quentes no SSD + 15,0 GiB frios no HD USB); Kiwix recriado com os 14 caminhos e
      `readiness_report` somando os dois diretórios**
- [x] **Mapas offline:** extrair o recorte regional em `.pmtiles` (Brasil:
      1–3 GB, medir antes) e colocar em `site/maps/brasil.pmtiles` — **FEITO
      12/11: 2,9 GB, zoom 0–14, bbox do Brasil; libs e glifos latinos em
      `site/vendor/`, detecção por Range (HEAD responde 501). Fora do git.**
- [x] **Mapas offline (próximo)** — **FEITO 26/11:** 8 faixas de glifos
      embutidas (+648 KB): hebraico, árabe, siríaco, devanagari, tailandês,
      vietnamita (latim ext. add.), pontuação geral e pontuação CJK. A amostra
      de 200 MB dos tiles (25.675 tiles) provou os scripts presentes; CJK e
      hangul **não existem** na fonte Noto Sans Regular da Protomaps (PBF de
      29 B) e precisariam de outra fontstack — documentado, sem demanda.
      Zoom 15: o arquivo é z0–14 e acima disso o MapLibre faz overzoom; ir a
      15 exige nova extração (~4× os tiles do último zoom, ordem de +2,5–3 GB)
      e não há uso medido. Números, limites e critério para reabrir em
      `docs/MAPAS_OFFLINE.md`; `tests/test_mapa_glyphs.py` 11 casos.
- [ ] **Backup fora da máquina:** SSD/pendrive criptografado com snapshot do
      Postgres + `data/` + cofre exportado; testar a restauração
- [x] **Backup do Postgres (dump automático):** hoje **nenhum** `pg_dump`
      roda em lugar algum — medido 13/11: sem crontab/timer, o tar diário
      cobre `.env` + `data/` (SQLite) e o snapshot das HDs não inclui
      `/var/lib/postgresql`; o único dump era manual (16/10). Criar job
      diário `pg_dump` para `backups/auto/` com retenção + offsite
      (enquanto isso há um dump pontual de 13/11 — 32 KB, 14 tabelas —
      que viajou para a HD do dono junto com o resto de `backups/`)
      — **FEITO 13/11 e VERIFICADO VIVO em 14/11: `runtime/pg_dump_diario.py`
      + `systemd/od-pg-dump.{service,timer}` (02:50, 10 min antes do tar);
      timer instalado e rodando: dumps de 13/11 17:32/17:33 e 14/11 02:50 em
      `data/pg_dumps/` (33 KB, 14 tabelas), journal `OD // PG DUMP OK`.**
      **Falta:** commit do código da unit (hoje está só na árvore)
- [x] **Modo colapso declarado:** trocar para a cadeia local e avisar no chat/UI
      quando a nuvem falhar N vezes (ou por ordem do dono) — **FEITO 21/11**
      (`core/colapso.py`, action `colapso`, prefixo no chat, check no `/health`);
      **provado ao vivo 26/11**: com o colapso ligado, groq e gemini foram
      bloqueados no journal e a resposta veio de `gemma-local` com o prefixo
      "⚡ modo colapso — respondendo só com a IA local"; `/health` degraded com
      "ATIVO (manual)"; ao desligar, voltou a `up`. **Limite:** não há card
      próprio no painel — o estado aparece no check `colapso` do `/health`.
- [x] **IA local melhor:** medir Qwen2.5-7B q4_K_M contra o 3B atual (mesmo
      benchmark de 11/11) e só então trocar — **MEDIDO 12/11: 7B 5/6 × 3B 3/6,
      mas 60,15 s × 16,26 s de p50 e só 2,3 GB livres com ele no ar. NÃO trocado;
      números em `docs/IAS_DISPONIVEIS.md` §5**
- [ ] **IA local (reteste):** 7B em quant menor (Q3_K_M) ou `-c 4096` quando
      houver mais RAM; repetir este mesmo benchmark e só promover se o p50
      ficar perto de 2× o do 3B
- [x] **Espelho de pacotes:** `pip download` + `docker save` das 11 imagens
      — **FEITO 12/11: `/home/alex/dados/od-mirror`, 3,3 GB (47 wheels +
      12 imagens + README/MANIFEST com sha256); pip offline validado com
      `--no-index --dry-run`**
- [x] **Espelho (restauração real):** criar um venv limpo e subir um container
      a partir de `od-mirror` sem rede — **FEITO 26/11:** venv em `/tmp` com
      `PIP_NO_INDEX=1` (60 pacotes, 18 s) rodou o gate completo nele
      (**5807 passed / 17 skipped / 2 failed** — as 2 de `test_websocket.py`
      que já falham no HEAD) e o `postgres:16-alpine` saiu do tar espelhado e
      respondeu `pg_isready`/`select` com `--network none` (só `lo`).
      MANIFEST **134/134 OK**. Achado: `requirements-dev.txt` era citado no
      README mas **não estava** no espelho — copiado, no MANIFEST e README
      atualizado. Dossiê: `docs/ESPELHO_RESTAURACAO.md`
- [x] **Espelho (modelos):** `.gguf` do 3B + runtime do llama.cpp no acervo —
      **FEITO 18/11:** `models/qwen2.5-coder-3b-instruct-q4_k_m.gguf` (2,0 GB,
      sha256 idêntico ao original) + `runtimes/llama/` (build 10786, 41 MB,
      **com as `.so`**), MANIFEST 133 entradas (51 novas, 51/51 conferidas).
      Prova real: servidor **do espelho** rodou de `/tmp` com
      `LD_LIBRARY_PATH` limpo, carregou o `.gguf` do espelho e respondeu
      `/v1/models`. Espelho agora 5,7 GB; README com "Restaurar o LLM local".
- [x] **Fila de download resumable** de acervo (padrão NOMAD, progresso por
      SSE) — **JÁ EXISTE desde a Parte D:** `core/downloads.py` retoma com
      `Range: bytes=N-` a partir do `.part`, confere sha256 e publica por SSE
      (`/admin/downloads/events`); é o que alimenta a aba **Downloads** do app
      e a auto-atualização do APK.

> Turno de 12/11 10:35 (plano de continuidade): as sugestões não escolhidas
> (baixar o acervo, modo colapso e medir o 7B) já estão como checkbox acima —
> nenhuma duplicada.

> Turno de 12/11 13:05 (acervo/mapa): sugestões não escolhidas → "baixar o
> .pmtiles do Brasil" já é o checkbox de mapas offline; "monitor de UPS" e
> "teste que amarra o compose ao readiness" entraram abaixo.

- [x] **Energia: vigia de queda por inferência** — **FEITO 21/11:** o Attiv
      1500 VA não tem USB, então a queda é deduzida pelo sumiço simultâneo
      dos aparelhos da LAN (`/proc/net/arp`): 15 âncoras reais, quorum de 60%,
      3 ciclos para suspeita, 3 min para confirmar e 8 min de carência com
      aviso no Telegram antes do desligamento; `energia_status` e
      `energia_cancelar` no catálogo (129 → 131) e check `energia` no
      `/health`. Testes: 21 em `tests/test_energia.py`.
- [x] **Energia: liberar o desligamento (uma vez, com sudo)** — **FEITO
      21/11:** regra instalada em `/etc/polkit-1/rules.d/49-od-energia.rules`
      (com o `SUDO_PASSWORD` do `.env`) e
      `pkcheck org.freedesktop.login1.power-off` → **rc=0**. Depois do restart
      o `energia_status` mostra `autorizado: true` e o desligamento gracioso
      passa a valer de verdade.
- [x] **Energia:** monitor de UPS no `readiness_report` — ler `upsc`/`/sys`
      quando um no-break com USB entrar (o Attiv atual nunca vai aparecer);
      a telemetria real da Fase Nicky é o **BMS RS485/CAN da Felicity**
      (precisa de adaptador USB-RS485). — **CÓDIGO PRONTO 28/11:**
      `_upsc_status()` lê `upsc -l` + `upsc <nome>` e o readiness mostra
      `status`, `carga` e `autonomia` em minutos; sem binário/NUT/energia ele
      devolve `None` e o relatório segue igual (8/9 hoje). Falta **só o
      hardware**: `tests/test_readiness.py::TestUpscDoNoBreak` (5 testes)
- [x] **Acervo:** teste que compara os ZIMs listados em
      `docker/tools-compose.yaml` com os arquivos presentes nos dois diretórios
      — hoje um ZIM novo só entra na busca se alguém lembrar do `command`.
      **FECHADO 28/11:** já entregue em 18/11 — `tests/test_zim_compose.py`
      (**11 passed** em 28/11) + `tools/checar_zim_compose.py`, guarda nas duas
      direções, 14 ZIMs alinhados; o checkbox tinha ficado aberto por engano.

### Análise de `analise/` — NV e Projeti (13/11, regra 22)

> Análise completa das duas pastas que restaram em `analise/` após a limpeza
> dos relatórios. Inventário medido, serventia, duplicação vs. Legado/OD,
> pros/contras e destinos. Itens que pedem ação ficam aqui.

**`analise/NV/` — 1,2 GB, 19.915 arquivos: o projeto predecessor Nicky
Virthy Runtime, 11 versões (v0.1.0 → v1.9.X).** É o que gerou o esqueleto
do OD (tool runtime, security layer, workflows — linha do tempo do Legado,
§2). Comparação medida: o `Legado/NV/docs/` (84 KB) tem os docs **canônicos
mais novos** (v1.11.0-security-enforcement, homologação de agosto); o
`analise/NV` tem os mesmos docs em versões antigas (v1.7.0) **mais o código
das 11 versões, que não existe em mais lugar nenhum**.

- [x] **NV → referência de DAG/scheduler para o grafo** — **FEITO 13/11 e
      confirmado 26/11:** o
      `nested-workflows.tar.gz` (v1.9.2) traz `dag_engine.py` (347 linhas,
      execução em grafo com paralelismo), `scheduler_engine.py` (413 linhas,
      cron/interval com persistência) e **8 testes** de scheduler — o
      `core/workflows.py` atual do OD é só sequencial. Candidato a inspirar
      a Semana 9-10/R1 quando um workflow real do OD precisar de
      dependência entre passos ou agendamento interno (hoje os timers
      systemd cobrem). **Não portar agora: sem demanda medida.**
- [x] **NV → decidir destino dos 1,2 GB:** **DECIDIDO/EXECUTADO 13/11
      (opção b, ordem sua):** zipado em `backups/analise_NV_20261113.zip`
      (822 MB, 19.915 entradas, testzip OK) e levado para a sua HD; a
      `analise/` foi esvaziada. O código das 11 versões agora existe **só
      na HD** — o que este TODO precisa daqui ficou em `data/refs_todo/NV/`
      (`nested-workflows.tar.gz`, bootstrap v1.9.2 e
      `SECURITY_LAYER_ARCHITECTURE.md`). Docs duplicados com o Legado não
      foram tocados (mapa: camadas geológicas).
- [x] **NV → `SECURITY_LAYER_ARCHITECTURE.md` (v1.7.0)** — **FEITO 26/11:**
      resumo executivo da security layer (fluxo Action→SecurityManager→Policy→
      Permission→Scope→Approval→Execute→Audit) no original, camada por
      camada apontando o código vivo do OD (`core/security/policy.py`,
      `permissions.py`, `scope.py`, `approval.py`, `audit.py`, `models.py`,
      `manager.py`), a tabela de diferenças (papéis, policies em código em vez
      de YAML, `CheckResult`/`SecurityDecision` em vez de exceção, auditoria
      antes do handler, modos de enforcement) e as 4 lacunas reais (policies
      só por código; nomes ponto × underscore; `dump()` não exposto; aprovação
      humana desligada). Doc novo: `docs/SECURITY_LAYER_ARCHITECTURE.md`.
      Nenhum código portado — a decisão de 13/11 continua: referência de
      intenção, não incorporação.

**`analise/Projeti/` — 235 MB, 953 arquivos: material de trabalho seu
(PMESP — 42.BPM/I) + ferramentas Windows.** Notebooks `pyautogui` que
automatizam o preenchimento do mapa de força no site Orion
(`orion.intranet.policiamilitar.sp.gov.br`) — 124 chamadas de `pyautogui`
no `mapa.ipynb`. Dados de 2024 (turnos de julho/setembro).

- [x] **Projeti → automatizar o mapa de força como action do OD (ou
      referência)** — **DECIDIDO 26/11: referência, não portar**
      (`docs/PROJETI_REFERENCIA.md` §3: tabulação cega é frágil e o ganho
      não foi medido; se um dia, fonte autorizada + somente leitura +
      fixtures sintéticas). Os notebooks são RPA puro (abrir site, tabular,
      inserir data/turno). O OD já tem a action engine, o CoderEngine
      sandbox e o RAG — um fluxo "cadastrar turno no Orion" poderia virar
      action/workflow. **Uso hoje: referência de padrão RPA** (o jeito
      `pyautogui` tabula é frágil; se algum dia automatizar de verdade, o
      caminho é API/scraping autorizado, não tabulação cega). Nota: os
      arquivos contêm **dados pessoais de policiais** (nomes, matrículas,
      viaturas) — não publicar em lugar nenhum, não entrar no git. Refs
      extraídas 13/11 (só no gitignored) em `data/refs_todo/Projeti/Cod/`:
      5 notebooks + `efetivo.txt`/`Mapa*` (266 KB no total da extração).
- [x] **Projeti → instalar as ferramentas Windows no desktop** —
      **RESOLVIDO 26/11:** os `.exe` (`FileZillaPortable`, `PuTTYPortable`,
      `MQTT-Explorer-0.4.0-beta.6.exe`, `tailscale-setup-1.92.5.exe`) só
      existem no zip da HD do dono desde a limpeza de 13/11; instalar é
      trazer de lá. O desktop Windows (`desktop-4icaj6f`) está ativo na
      tailnet. Nada pendente no servidor.
- [x] **Projeti → `google-services.json` é IDÊNTICO ao do app** —
      **FECHADO 26/11:** era byte a byte igual (sha256 `5e64634c…`, projeto
      `nicky-e4f99`, `com.omegadrakon.nicky`) e a cópia de Projeti saiu do
      servidor no zip de 13/11; a oficial em `app/android/app/` foi conferida
      hoje com o mesmo sha256. Nada a apagar. O `app.txt` (export do console
      Firebase) também está só no zip — referência, não fonte.
- [x] **Projeti → `OmegaDrakon.apk` (51 MB) não bate com nenhum backup** —
      **FECHADO 26/11:** o órfão (sha256 `b845c044…`) está só no zip da HD e
      segue sem versão conhecida (rodar `aapt dump badging` ao abrir o zip).
      A conferência da trilha `backups/apk-*` com `aapt` achou furo real:
      `apk-v1.44.0-2080/` guarda **1.45.0/2081** (duplicado de
      `apk-v1.45.0-2081/`), 1.44.0 não existe arquivado e faltavam
      1.46.0/1.46.1/1.47.0; o 1.47.0/2085 foi arquivado e conferido hoje, e
      o passo entrou no checklist (§5 item 9 de `docs/VERSIONAMENTO.md`).
      Detalhe em `docs/PROJETI_REFERENCIA.md` §4. Renomear/apagar pasta de
      backup continua sendo ação do dono.
- [x] **Projeti → dados do Orion viram action de leitura (opcional)** —
      **DOCUMENTADO 26/11, sem action:** o formato real está em
      `docs/PROJETI_REFERENCIA.md` §2 — 14 colunas da escala
      (`inicio,final,cmd,municipio,setor,sub,local,vtr,escala,mod,re,func,
      re2,func2`), blocos por unidade no `MapaForcaTudo.txt`, e as duas
      armadilhas medidas (CSV com o cabeçalho inteiro entre aspas; CRLF e
      linha em branco no `Mapa.txt`). Exemplos sintéticos, nunca dado real.
      Continua sem demanda; fontes em `data/refs_todo/Projeti/Cod/`.

### Lote de 13/11 fora do registro (levantado na retomada de 14/11)

> Trabalho feito depois do checkpoint das 14:45 de 13/11: 8 modificados
> (+716/−27) + 8 novos, **sem commit, sem registro e sem gate**. Detalhe em
> `iniciar/2026-11-14_conversa_omegadrakon.md` §1. Só o `pg_dump` está vivo.

- [x] Fechar o lote: gate completo, commits por assunto, push e restart verde
      com prova viva — **FECHADO 14/11:** gate **4656 passed / 16 skipped / 0
      falha**, commits por assunto (`f9949b2`, `8229a5d`, `81ea83f`, `93aadd7`,
      `85b2177` + docs), `origin/master` atualizado e `od-core` reiniciado com
      prova viva (MainPID 2424782, `/health` 28 itens, journal sem erro).
- [x] R1: remover a duplicata de `_task_queue_or_503` e cobrir a Task Queue com
      teste próprio — **FEITO 14/11:** `grep -c 'def _task_queue_or_503'` = 1 e
      `tests/test_task_queue.py` existe (35 KB, 28 testes: prioridade,
      persistência, retry→dead letter, SSE, rotas e snapshot da fila).
- [x] Resolver a decisão do `semantic_cache=` no boot — **DECIDIDO 14/11
      (commit `f2c784a`):** o launcher só monta o cache com
      `OD_SEMANTIC_CACHE_ENABLED=1`; padrão **desligado** e o boot loga
      `Semantic Cache desligado`. Ligar continua sendo decisão do dono (item
      I1 abaixo).

### Semana 9-10: RAG Otimizado
- [ ] I1: Semantic Cache (Redis + embedding similarity ≥0.95) — **módulo e
      testes PRONTOS (conferido 13/11): `memory/semantic_cache.py`,
      threshold 0.95 (`OD_SEMANTIC_CACHE_THRESHOLD`), em processo (sem
      Redis); `tests/test_semantic_cache.py`. FALTA LIGAR: nenhum ponto da
      produção passa `semantic_cache=` — o orquestrador roda com `None`.
      Ligar é decisão do dono (risco: servir resposta parecida na ≥0.95)** —
      **MEDIDO 14/11 (decisão recomendada: DESLIGADO):** com MiniLM local,
      só "quem foi Alan Turing" × "…?" passa de 0,95 (0,979); "uso de disco" ×
      "uso do disco" fica em 0,921 e "python" × "python 3.13" em 0,913 —
      abaixo do corte. Baixar para 0,85–0,90 acertaria mais, mas "liga a luz
      da cozinha" × "… da sala" = 0,887 acenderia o cômodo errado. Custo do
      embedding ~17 ms/mensagem. Fica desligado até decisão; para ganhar
      latência o `LLMCache` exato já resolve. **17/11: recomendação mantida —
      desligado (0 acerto adicional no tráfego real medido)**
- [x] I2: Hybrid Search (BM25 via `rank-bm25` + dense + cross-encoder
      reranker) — **módulo e testes PRONTOS (conferido 13/11):
      `core/hybrid_search.py` (BM25Index + `cross-encoder/ms-marco-MiniLM-L-6-v2`);
      `tests/test_hybrid_search.py`. FALTA LIGAR: a `memory/rag.py` de
      produção não o usa** — **FECHADO 28/11:** está ligado em produção desde
      25/11 (`OD_RAG_HIBRIDO` padrão `1`, `memory/rag.py:676` monta o
      `BM25Index`; gate 8/8 · 0/8 · 6/6 · 2/2). Única parte que segue fora: o
      `CrossEncoderReranker` neural (`core/hybrid_search.py:296`) não está
      plugado — a RAG usa reranker próprio (cosseno + overlap IDF), decisão
      registrada no §4
- [x] I4: Query Router (classificador leve → estratégia: direct, rag, tool,
      hybrid) — **ENTREGUE (conferido 13/11): `core/query_router.py`,
      integrado na etapa de intenções e no grafo (CHANGELOG com prova
      viva); `tests/test_query_router.py`**
- [x] I5: Streaming SSE para chat (`text/event-stream`) — **ENTREGUE
      (conferido 13/11): `GET /api/v1/chat/stream` (SSE) +
      `process_stream_sse()`; `tests/test_sse.py`; prova viva no CHANGELOG**

### Semana 11-12: Resiliência + Eval
- [x] R1: Task Queue **durável em Redis/RQ (ou Celery)** — **reescopado 17/11:**
      a fila própria já está **em produção desde 14/11** (`core/task_queue.py`
      com `RetryPolicy`, backoff, dead letter, persistência JSON, poda de
      concluídas, rotas `/admin/tasks*`, SSE e aba no app; 1 worker, custo
      medido de +5,1 MB e 0,23% de core por task de LLM). O que sobra do item
      original é só **fila distribuída/multi-processo** — desnecessária para
      este servidor enquanto houver um processo. Reabrir se aparecer segundo
      nó ou volume que a fila de arquivo não dê conta. **FECHADO 28/11:**
      fila própria em produção cobre o caso; nenhuma fila distribuída a fazer.
- [x] R2: Circuit Breaker em chamadas externas — feito sem `pybreaker`, por
      provider de LLM (`core/resilience.py`); bulkhead dispensado (ver §3)
- [x] R5: Eval Framework (LOCOMO subset + custom benchmarks) rodando no CI —
      **ENTREGUE 28/11:** `evals/locomo.py` + `evals/locomo_subset.jsonl`
      (3 conversas, **69 turnos**, **27 perguntas**: single-hop, multi-hop,
      temporal e adversarial) e `evals/benchmarks.py`, que junta isso ao eval
      de respostas já existente. Medido: **produção recall@5 93% / MRR 0,889 /
      0 falsos positivos**; **turnos recall@5 100%**. Gate = piso publicado +
      baseline (`evals/baseline-locomo.json`) e roda no CI (`python -m
      evals.benchmarks`). Dois furos reais apareceram na primeira medição:
      **(1)** posses se substituem entre si ("tenho um gato" some quando
      depois entra "tenho uma bicicleta", mesma entidade `possui`); **(2)**
      radical `prefir-` da pergunta não casa com `prefer-` do fato. Ambos
      ficam no exame (falha visível) até consertar. `tests/test_eval_locomo.py`:
      **27 testes**
- [x] Documentação de arquitetura atualizada (`docs/ARCHITECTURE_v2.md`) —
      **FEITO 13/11:** arquivo com 300 linhas (grafo, memória, fila, segurança,
      observabilidade) publicado em `origin/master` no lote `93aadd7`.

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
6. **Bluetooth pairing:** celular emparelha mas falha na autenticação (PIN 0000) — agent D-Bus registra mas `AuthenticationFailed`; tentar outro dia com `bluetoothctl --agent` ou `bluez-test-device`

---

## 9. IDEIAS DO DONO — `txt.txt` de 21/11/2026

Anotadas como vieram, sem inventar escopo; a ordem e o tamanho ficam com o
dono. O que já existe e o que falta está em cada item.

- [ ] **APK: foto da peça → identificar → cadastrar no Homebox.**
      Escopo: tirar foto pelo app, mandar para o OD, a visão propor
      nome/tipo/marca e o cadastro cair no Homebox com a foto anexada.
      Já existe: `tools/vision/` (detector de faces — serve de base, não de
      identificador de peça), action `homebox_criar` com local/fabricante/
      modelo/série e `registry` com foto. Falta: modelo de reconhecimento de
      peça (ou consulta à cadeia de LLM com visão), confirmação do dono antes
      de gravar e o vínculo foto ↔ entidade do Homebox.
- [ ] **Abrir o Homebox pelo site.** Hoje ele só responde em
      `127.0.0.1:8470` / LAN `192.168.0.205:8470` e o site não tem link.
      Escopo: rota/atalho no `/site` (ou proxy autenticado) — decidir se é
      link direto na LAN ou túnel, já que o Funnel não expõe 8470.
- [ ] **Ouvir a música antes de decidir o que fazer com ela.** O acervo tem
      `revisar/` + `reprovadas/` (38 arquivos) e a curadoria decide às cegas.
      Escopo: pré-escuta no `/radio-pro` (streaming da faixa em quarentena,
      sem entrar na programação) para o dono aprovar/reprovar ouvindo.
- [ ] **Religar quando a energia volta.** O vigia desliga com segurança, mas
      ninguém religa. Escopo de software: o desligamento é da máquina — quem
      liga é a BIOS (restore on AC power loss). Plano: conferir/ajustar
      "AC Recovery = Power On" no OptiPlex, e do lado do OD deixar o boot
      idempotente (o auto-registro de restart já anota o retorno) + aviso no
      Telegram quando voltar. Sem hardware novo.
- [ ] **Conexão com a Meta (WhatsApp Cloud API).** Preparada em 21/11:
      `integrations/meta.py` + rotas `GET/POST /webhook/meta` (verificação
      `hub.challenge`, assinatura `X-Hub-Signature-256`, texto → orquestrador
      → resposta pelo Graph API). Falta só o dono criar o app no Meta for
      Developers e preencher `OD_META_TOKEN`, `OD_META_PHONE_ID` e
      `OD_META_APP_SECRET` no `.env`. O `OD_META_VERIFY_TOKEN` já foi gerado
      em 21/11 e a verificação do webhook já responde 200 pelo Funnel; sem os
      outros três o POST responde 503 e nada mais do sistema muda. Relatório
      técnico exato (linguagem, portas, rotas, auth, Funnel, Homebox) em
      `docs/META_CONEXAO.md`.

---

> **Nota:** Este TODO é vivo. Itens podem ser reordenados, divididos ou descartados conforme aprendizado durante a execução. A filosofia é **"entregar valor incremental a cada 2 semanas"** — não reescrita big-bang.
