# ARQUITETURA OMEGA DRAKON v2 — 2026-11-13

> Documento vivo da arquitetura alvo. Reflete o estado **após** as entregas de 10-13/11/2026 e o roadmap do `docs/ANALISE_SISTEMA_TODO.md`.

---

## 1. VISÃO GERAL

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OMEGA DRAKON v2                              │
├─────────────────────────────────────────────────────────────────────┤
│  ORCHESTRATOR (grafo)                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │  Classify   │→ │ Select Tools│→ │  Execute    │→ │ Generate  │  │
│  │  Intent     │  │             │  │  Parallel   │  │           │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │
│        │                │                │                 │        │
│        ▼                ▼                ▼                 ▼        │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │              SECURITY LAYER (Scope + Policy + Approval)      │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                │                │                 │        │
│        ▼                ▼                ▼                 ▼        │
│   ACTION REGISTRY (125 actions, permission = action name)          │
│        │                │                │                 │        │
│        ▼                ▼                ▼                 ▼        │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │                    CORE SERVICES                              │  │
│   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │  │
│   │  │ Memory  │ │  RAG    │ │  LLM    │ │ Telemetry│          │  │
│   │  │ Graph   │ │ Pipeline│ │ Chain   │ │ (OTel)  │          │  │
│   │  └─────────┘ └─────────┘ └─────────┘ └─────────┘          │  │
│   └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. COMPONENTES PRINCIPAIS

### 2.1 Orchestrator como Grafo (F1 — ENTREGUE 10-11/11)

**Arquivo:** `core/orchestrator.py` + `core/orchestrator_graph.py`

- **Estado tipado** (`OrchestratorState`): `TypedDict` com reducers (`add_messages`, etc.)
- **Nós atômicos**: `classify` → `select_tools` → `execute_parallel` → `generate` → `human_loop`
- **Fan-out paralelo**: até `max_paralelo` actions simultâneas (timeout por ferramenta)
- **Checkpointing**: `SqliteSaver` em `data/checkpoints.db` (superstep), `thread_id` determinístico
- **Retomada**: `concluido` no checkpoint + retomada automática após restart (não repete LLM)
- **Feature flag**: `OD_ORCHESTRATOR_GRAPH=1` (produção), fallback para caminho direto

### 2.2 Memory Layer (F4 — Fases 1-4 ENTREGUES 10/11)

| Fase | Arquivo | Entregue |
|------|---------|----------|
| 1. Grafo temporal | `core/memory_layer.py` | ✅ |
| 2. Injeção no prompt | `core/orchestrator.py:_bloco_memoria` | ✅ (recall@5 0%→90%) |
| 3. Consolidação semanal | `tools/monitor/memory_consolidate.py` + timer | ✅ (dedupe + expiração efêmero 7d) |
| 4. Busca semântica sob demanda | `core/memory_embeddings.py` (Gemini 768d) | ✅ (recall@5 9/10→10/10, 0 FP) |
| 4b. Cache resultado | L1 memória + L2 SQLite (`memory_semantic_cache`) | ✅ (repetição 440ms→0.7ms, persiste restart) |

**Isolamento**: todo nó tem `user_id`; leitura sempre filtra por usuário.

### 2.3 RAG Pipeline (I1, I2 — MÓDULOS PRONTOS, NÃO LIGADOS 13/11)

| Item | Arquivo | Status |
|------|---------|--------|
| I1 Semantic Cache | `memory/semantic_cache.py` | ✅ Módulo + testes (threshold 0.95, sem Redis) |
| I2 Hybrid Search | `core/hybrid_search.py` | ✅ BM25 + cross-encoder + testes |
| I4 Query Router | `core/query_router.py` | ✅ Entregue (integrado no grafo + intenções) |
| I5 Streaming SSE | `integrations/api/server.py` | ✅ `GET /api/v1/chat/stream` |

**Decisão pendente**: ligar I1/I2 na produção — `memory/rag.py` não usa hybrid; orquestrador passa `semantic_cache=None`. Risco: resposta parecida em ≥0.95.

### 2.4 LLM Chain (Regra 19 — ENTREGUE 11/11)

`core/llm.py` — cadeia configurável via `OD_CHAT_PROVIDERS` (padrão `gemini,groq,local`):

```
GeminiProvider (gemini-3-flash-preview, Bearer, /chat/completions)
    ↓ 429/quota → CircuitBreaker.abre(recuperacao_s=retryDelay)
GroqProvider (openai/gpt-oss-120b, User-Agent browser, piso 2048 tokens)
    ↓ falha
OpenAIProvider (gpt-4o-mini, OD_OPENAI_AUTO=1 testa crédito no boot)
    ↓ falha
OpenAICompatProvider (llama.cpp local qwen2.5-coder-3b, :8081)
```

**Disjuntor por provider** (`core/resilience.py`): `OD_CIRCUIT_FAILURES=5`, `OD_CIRCUIT_RECOVERY_S=30`. 429 abre na hora com janela do `retryDelay` (teto 6h).

### 2.5 Security Layer (ENTREGUE — 1.742 linhas em `core/security/`)

| Camada | Arquivo | Função |
|--------|---------|--------|
| Scope | `core/security/scope.py` | Raízes permitidas (`/tmp` incluído p/ STT/FileBrowser), paths protegidos (`.git`), operações destrutivas negadas |
| Policy | `core/security/policy.py` | Allow/deny patterns por role, `UNKNOWN_ROLE_POLICY=deny` |
| Permission | `core/security/models.py` | Permission = action name (gate no Registry) |
| Approval | `core/security/approval.py` | Human-in-the-loop para ações sensíveis (`OD_HUMAN_APPROVAL_ACTIONS`) |
| Audit | `core/security/audit.py` | Trilha JSONL assinada Ed25519 |

**Auditoria 12/11**: 122 actions × 3 roles — única negação indevida era `disk_usage` (corrigida com `SCOPE_EXEMPT_ACTIONS`). `stt_transcrever`/`filebrowser_envia` usavam params `caminho`/`origem` fora de `_PATH_PARAM_KEYS` — corrigido 13/11.

### 2.6 Observabilidade (F2 — SOFTWARE ENTREGUE 10/11)

`core/telemetry.py` — OTel SDK import tardio + no-op:
- Spans: `http.request`, `rag.consult`, `llm.generate`
- Métricas: `od.http_request.seconds`, `od.rag_retrieval.seconds`
- Log correlação: `trace_id`/`span_id` no logger NICKY
- `/health` check `telemetria` (não-crítico)

**Falta (infra)**: OTel Collector + Grafana (Tempo/Loki/Prometheus) + alertas.

### 2.7 Resiliência (R2 — ENTREGUE 10/11)

`core/resilience.py` — CircuitBreaker thread-safe (fechado→aberto→meia-aberto), relógio injetável para testes. Integrado em `LLMProvider._falhar()` (429 abre na hora).

---

## 3. ACTION REGISTRY (125 actions)

`tools/actions/actions.py` + `tools/registry.py`

| Categoria | Count | Exemplos |
|-----------|-------|----------|
| system | 19 | `system_info`, `disk_usage`, `exchange_rate`, `web_search`, `readiness_report` |
| iot | 9 | `ha_weather`, `radio_play`, `ha_device_control` |
| process | 4 | `process_list`, `process_kill`, `process_tree` |
| docker | 4 | `docker_list`, `docker_status` |
| service | 3 | `service_status`, `service_logs` |
| filesystem | 15 | `filesystem_read`, `filesystem_write`, `filesystem_search` |
| git | 10 | `git_status`, `git_commit`, `git_push` |
| database | 3 | `database_tables`, `database_query` |
| introspection | 4 | `action_list`, `action_schema` |
| google | 13 | `google_drive_list`, `google_calendar_create` |
| nomad | 8 | `nomad_tools_up`, `nomad_wikipedia_zim_download` |
| vault | 4 | `vault_status`, `vault_get`, `vault_set` |
| stirling | 4 | `stirling_merge`, `stirling_compress` |
| kiwix | 3 | `kiwix_status`, `kiwix_busca`, `kiwix_leitura` |
| homebox | 6 | `homebox_busca`, `homebox_criar` |
| flatnotes | 3 | `flatnotes_anota`, `flatnotes_busca` |
| filebrowser | 3 | `filebrowser_lista`, `filebrowser_envia` |
| calibre | 3 | `calibre_status`, `calibre_busca` |
| stt | 1 | `stt_transcrever` |
| saude | 3 | `saude_condicao`, `saude_interacoes` |
| memoria | 2 | `salvar_fato`, `buscar_memoria` |

**Gate**: Security Layer consulta antes de executar (fail-closed em `mode="strict"`). Permission = action name.

---

## 4. INFRAESTRUTURA & OPERAÇÃO

### 4.1 Systemd Units (user)

| Unit | Schedule | Função |
|------|----------|--------|
| `od-core.service` | — | Servidor principal (ThreadingHTTPServer) |
| `od-backup.service` | 03:00 diário | Tar `.env` + `data/` (exceto captures/vector_memory) |
| `od-backup-capturas.service` | 04:00 domingos | Tar `.env` + `data/` + `captures` |
| `od-pg-dump.service` | 02:50 diário | `pg_dump` banco `od` → `data/pg_dumps/` (retenção 14) |
| `od-memory-consolidate.service` | 04:20 domingos | Dedupe + expiração efêmero memória longa |
| `od-io-probe.service` | 5 min | Sonda p50/p95 → `data/io_monitor.json` |
| `od-vigia-mensagens.service` | 04:30 diário | Auditoria chat + relatórios → `data/relatorios/` |
| `od-os-updater.service` | 06:00 diário | `apt update && apt upgrade -y` (auto) |
| `od-kiwix.service` | — | Kiwix (14 ZIMs, 40 GB, quente SSD + frio HD USB) |

### 4.2 Backups & Continuidade

- **Tar diário** (03:00): `.env` + `data/` (exceto `captures/`, `vector_memory/`) → `backups/auto/` (ret 3d+8s)
- **Tar semanal capturas** (04:00 dom): inclui `data/captures/` → `backups/auto-capturas/` (ret 4s)
- **pg_dump** (02:50): banco `od` → `data/pg_dumps/` (ret 14, entra no tar diário + offsite)
- **Offsite** (Telegram): tars diário/semanal + pg_dump → canal do dono (sha256 em `data/offsite_state.json`)
- **Snapshots HDs** (03:44): `rsync --link-dest` → `/home/alex/dados/od_snapshots` + `/mnt/Arquivos/od_snapshots` (exclui `backups/`)
- **Espelho offline** (12/11): `/home/alex/dados/od-mirror` (3.7 GB: 57 wheels + 17 docker tars + 12 configs + MANIFEST sha256)

### 4.3 Acervo Offline (12/11)

- **14 ZIMs** (40.3 GB): Wikipédia PT, WikiMed, WikiHow, iFixit/Appropedia — Kiwix serve quente (SSD 25 GB) + frio (HD USB 15 GB)
- **Mapa offline**: `site/maps/brasil.pmtiles` (2.9 GB, zoom 0-14, bbox Brasil, MVT gzip, libs em `site/vendor/`)
- **Detecção offline**: HEAD `Range: bytes=0-0` → fallback raster OSM

### 4.4 Bluetooth (PENDENTE — investigação)

**Problema**: Pareamento celular → servidor falha com `AuthenticationFailed` usando PIN `0000`. O agent D-Bus registra o dispositivo mas a autenticação falha.

**Hipóteses**:
1. PIN padrão do adaptador não é `0000` (alguns adaptadores usam PIN fixo de fábrica ou exigem confirmação no dispositivo)
2. `bluetoothctl` agent não configurado corretamente para `NoInputNoOutput` / `KeyboardOnly`
3. BlueZ versão do servidor exige método de pareamento diferente (Just Works vs Passkey)

**Próximos passos** (quando houver janela):
```bash
# Ver adaptador e versão
bluetoothctl show
# Tentar com agent explícito
bluetoothctl --agent
# Ou testar com bluez-test-device
bluez-test-device create <MAC>
# Ver logs do kernel
dmesg -T | grep -i bluetooth
```

**Status**: Documentado no backlog (regra 21: sugestão não escolhida → checkbox no TODO). Não bloqueia nenhuma funcionalidade atual.

---

## 5. DECISÕES ARQUITETURAIS REGISTRADAS

| Data | Decisão | Referência |
|------|---------|------------|
| 10/11 | F2: OTel SDK no software; Collector/Grafana = infra | `docs/ANALISE_SISTEMA_TODO.md §F2` |
| 10/11 | F3: Async I/O descartado por medição; ganhos reais = cache APK + backlog listen | `docs/ANALISE_SISTEMA_TODO.md §F3` |
| 10/11 | F4: Memória = grafo temporal SQLite (sem embedding fase 1); extração regex 13 padrões PT-BR | `docs/ANALISE_SISTEMA_TODO.md §F4` |
| 11/11 | LLM Chain: Gemini→Groq→Local (OpenAI fora até ter crédito); disjuntor por provider | `docs/IAS_DISPONIVEIS.md` |
| 11/11 | Cache não serve comando de action (`detect_action_intent != None`) | `core/orchestrator.py` |
| 12/11 | `disk_usage` isenta de escopo (`SCOPE_EXEMPT_ACTIONS`) | `core/security/scope.py` |
| 13/11 | `/tmp` em `allowed_roots` padrão (STT/FileBrowser); `caminho`/`origem` em `_PATH_PARAM_KEYS` | `core/security/scope.py` |
| 13/11 | pg_dump diário em `data/pg_dumps/` (entra no tar + offsite + HDs) | `runtime/pg_dump_diario.py` |

---

## 6. PRÓXIMOS PASSOS (ROADMAP)

### Semana 7-8: Orquestrador Grafo (F1) — CONCLUÍDO
- ✅ Fases 1-4 entregues (grafo + checkpointing + retomada + integração completa)

### Semana 9-10: RAG Otimizado
- [ ] **I1**: Ligar Semantic Cache na produção (decisão: risco ≥0.95)
- [ ] **I2**: Ligar Hybrid Search no `memory/rag.py`
- [ ] **I3**: KV-Cache optimization (prefix reuse) — opcional

### Semana 11-12: Resiliência + Eval
- [ ] **R1**: Task Queue (Redis/RQ) + RetryPolicy declarativo por nó
- [ ] **R5**: Eval Framework (LOCOMO subset + custom) no CI
- [ ] **Docs**: `docs/ARCHITECTURE_v2.md` (este documento), `pyproject.toml`

### Continuidade (paralelo, depende de decisão/compra)
- [ ] Nobreak com USB (shutdown gracioso) — compra nº 1
- [ ] 2º nó comunicação (LoRa Meshtastic / ntfy local)
- [ ] Modo colapso declarado (cadeia local + aviso)
- [ ] Fila download resumable (NOMAD + SSE)
- [ ] Mapas não-latinos (glifos além latin 0-1279)

---

## 7. MÉTRICAS-CHAVE (KPIs)

| KPI | Baseline | Target | Medição |
|-----|----------|--------|---------|
| Orchestrator p95 latency | ~3-5s | < 1.5s | OTel histogram |
| RAG retrieval p95 | ~1.5s | < 400ms | OTel histogram |
| Cache hit rate (RAG) | ~15% | > 40% | Prometheus gauge |
| Memory recall (LOCOMO) | ~60% | > 85% | Eval framework |
| Error rate | ~0.5% | < 0.1% | Counter |
| Cold start (import core) | ~2.3s | < 800ms | `python -X importtime` |
| Test suite duration | 190s | < 120s | `pytest -q` |

---

## 8. ARQUIVOS-CHAVE

```
core/
├── orchestrator.py           # Pipeline principal + grafo (F1)
├── orchestrator_graph.py     # Motor de grafo próprio (LangGraph-style)
├── llm.py                    # Providers + disjuntor (R2)
├── resilience.py             # CircuitBreaker
├── telemetry.py              # OTel SDK + spans/métricas (F2)
├── memory_layer.py           # Grafo temporal SQLite (F4)
├── memory_embeddings.py      # Busca semântica Gemini (F4 fase 4)
├── security/
│   ├── scope.py              # Raízes permitidas, /tmp, paths protegidos
│   ├── policy.py             # Allow/deny patterns
│   ├── models.py             # ActionRequest, CheckResult
│   └── approval.py           # Human-in-the-loop
├── intents.py                # Fast path determinístico (122 intenções)
tools/
├── actions/
│   ├── actions.py            # 125 actions (CATALOG)
│   └── __init__.py           # register_all, build_registry
├── registry.py               # ActionRegistry + métricas + security gate
├── monitor/
│   ├── pg_dump_diario.py     # Dump Postgres diário
│   ├── memory_consolidate.py # Consolidação semanal memória
│   └── io_probe.py           # Sonda p50/p95
runtime/
├── launcher.py               # build_orchestrator, build_llm_providers, build_health
├── pg_dump_diario.py         # pg_dump oneshot (timer od-pg-dump)
integrations/
├── api/server.py             # REST + SSE streaming + /health
systemd/                      # 10 units (serviços + timers)
docs/
├── ANALISE_SISTEMA_TODO.md   # Roadmap vivo (este documento referencia)
├── IAS_DISPONIVEIS.md        # Inventário IAs + benchmark medido
└── CONTINUIDADE.md           # Plano colapso + prontidão
```

---

*Documento gerado em 2026-11-13. Atualizar a cada entrega significativa.*