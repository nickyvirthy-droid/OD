# OMEGA DRAKON — README DE VERSÃO

> **Finalidade:** persistir o relatório do protocolo §2.1 (REGRAS_DE_TRABALHO.md)
> de **cada versão/fase entregue** — para que nenhum trabalho, decisão ou
> pendência se perca, mesmo entre sessões.
> **Regra:** a versão mais recente fica no topo. Toda fase concluída adiciona
> uma seção aqui ANTES de ser publicada no GitHub.
> **Assinatura:** `OD // CORE`

---

## [0.7.0] — Fase 3 (item 3.4) — Orchestrator Pipeline ✅ (2026-09-03)

> **FASE 3 COMPLETA — 4/4 itens (Workflow Engine, Tool Loader, Action
> Registry, Orchestrator Pipeline).** 16/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **3.4 Orchestrator Pipeline** | `core/orchestrator.py` | Pipeline de **8 etapas**: rate limit (10 msg/60s, janela deslizante) → datetime PT-BR (detecção + injeção no system prompt) → quick responses (AIML) → cache LLM (SHA-256 + perfil) → histórico (ChatML, N turns) → LLM (providers plugáveis) → fallback (próximo provider; esgotados → `llm_unavailable`) → pós-processamento (grava cache/histórico + métricas) · `Orchestrator`/`OrchestratorConfig`/`OrchestrationResult` · sem dependência externa de LLM (sem providers, rotas curtas funcionam) · componentes de memória opcionais (ausentes → etapas puladas) · evento `orchestrator.responded` no Event Bus · métricas por rota + `dump()` · logging via `core/logger.py` |
| — | `tests/test_orchestrator.py` | **29 testes** (rate limit, datetime PT-BR, quick, cache, histórico, fallback de providers, métricas, event bus) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_orchestrator.py -q   → 29 passed
.venv/bin/python -m pytest tests/ -q                       → 697 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 4 — Execução**: Coder Engine, Self Repair, Perception, 56 Actions
- Refatoração cosmética dos call sites `_audit_nicky` (mantidos como alias)
- Sandbox de execução de plugins (tema do `runtime/`, fases futuras)

### 4. Próximo passo

**Fase 4, item 4.1 — Coder Engine** (`core/coder_engine.py`) — sandbox →
testes → backup → promoção.

---

## [0.6.1] — Refatoração: Logger unificado ✅ (2026-09-03)

### 1. O que foi feito

- `core/logger.py` — nova fábrica canônica **`make_audit_nicky(name)`**:
  resolução de níveis (INFO/WARN/CRIT/ERROR/DEBUG/ONLINE) e emissão NICKY
  centralizadas em um único ponto.
- 13 módulos migrados (cada um agora com uma linha de assinatura, removendo
  ~10 linhas de boilerplate idêntico por arquivo, ~155 no total):
  - `core/event_bus.py`, `core/router.py`, `core/state.py`
  - `core/security/`: `manager`, `policy`, `permissions`, `scope`,
    `approval`, `audit`
  - `memory/`: `history`, `cache`, `quick_responses`, `vector`, `context`
- Chamadas `_audit_nicky("INFO"|...` preservadas (assinatura idêntica) —
  comportamento inalterado; logs agora fluem pelo `core/logger.py`
  (NickyLogger, protocolo NICKY).

### 2. Evidência

```
.venv/bin/python -m pytest tests/ -q
→ 668 passed, 0 falhas   (inalterado — refatoração sem mudança funcional)

git diff --stat
→ 15 arquivos, 70 inserções, 155 remoções
```

### 3. O que NÃO foi feito

- Conversão dos call sites para `log.info(...)` direto — as chamadas mantêm
  o nome `_audit_nicky` (agora um alias de `make_audit_nicky`), evitando
  alteração em dezenas de pontos; a implementação duplicada foi removida.
- Item 3.4 (Orchestrator Pipeline) — último da Fase 3 (próximo).

### 4. Próximo passo

**Fase 3, item 3.4 — Orchestrator Pipeline** (`core/orchestrator.py`).

---

## [0.6.0] — Fase 3 (item 3.3) — Action Registry ✅ (2026-09-03)

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| 3.3 Action Registry | `tools/registry.py` | `Action` tipada (name, handler sync/async, params schema, permission, aliases); `ActionResult` padronizado (`ok/invalid/denied/error/not_found`); `ActionRegistry` com pipeline registro → validação de schema (defaults) → gate Security Layer (spec §7) → handler; `register`/`register_action`; **`import_loader()`** (Tool Loader → Actions, schema/requires reaproveitados); aliases; duplicados skip/overwrite; métricas, trilha recente e `dump()`; logging via `core/logger.py` |
| — | `tools/loader.py` (refactor) | Validação de schema extraída para `validate_params()` compartilhada com o Registry |

- Testes novos: `tests/test_registry.py` (33) — registro, aliases, execução
  (ok/invalid/not_found/error), gate de segurança (strict/denied/admin),
  integração com Tool Loader, métricas, trilha e dump.
- Documentação atualizada: `docs/CHANGELOG.md` (0.6.0),
  `docs/ROADMAP_ABSORCAO.md` (3.3 ✅, 15/32 capacidades).

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_registry.py -q
→ 33 passed

.venv/bin/python -m pytest tests/ -q
→ 668 passed, 0 falhas   (635 anteriores + 33 novos)
```

### 3. O que NÃO foi feito

- Item 3.4 (Orchestrator Pipeline) — último da Fase 3.
- As 56 actions concretas do NV (Fase 4.4, `tools/actions/`) — o Registry de
  3.3 é a infraestrutura tipada que vai catalogá-las.
- Refatoração do `_audit_nicky` duplicado para o `core/logger.py` — pendente.
- Nenhuma dependência externa adicionada (MariaDB/Docker não necessários
  nesta fase; serão acionados quando a Fase 7.5 — Database Layer — exigir).

### 4. Próximo passo

**Fase 3, item 3.4 — Orchestrator Pipeline** (`core/orchestrator.py`):
pipeline de 8 etapas (rate limit → datetime → AIML → cache → history → LLM
→ fallback → post-processing). Com ele, a Fase 3 fecha.

---

## [0.5.1] — Fase 3 (item 3.2) — Tool Loader ✅ (2026-09-03)

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| 3.2 Tool Loader | `tools/loader.py` | `Tool` (metadados + callable, async/sync); `ToolLoader` com contratos de plugin `PLUGIN`/`TOOLS`/`load_tools()`; descoberta recursiva (ignora não-.py e `_`); escopo estrito (`ToolScopeError`, spec §7.1); falha de import isolada com erro registrado; módulo sem contrato pulado com WARN; duplicados (skip ou `allow_overwrite`); hot-reload `reload()`/`reload_all()` preservando versão anterior em falha; `validate(params)` por schema (required + tipos com distinção bool/int + defaults); `invoke()` sync/async; `get/find/has/unload/clear/dump`; métricas `LoaderMetrics`; logging via `core/logger.py` |
| — | `tools/__init__.py` | Pacote com docstring canônico `OD // CORE` |

- Testes novos: `tests/test_tool_loader.py` (39) — contratos, descoberta,
  robustez (falhas isoladas), escopo, registro/remoção, hot-reload,
  invocação e validação de parâmetros, métricas/dump.
- Documentação atualizada: `docs/CHANGELOG.md` (0.5.1),
  `docs/ROADMAP_ABSORCAO.md` (3.2 ✅, 14/32 capacidades).

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_tool_loader.py -q
→ 39 passed

.venv/bin/python -m pytest tests/ -q
→ 635 passed, 0 falhas   (596 anteriores + 39 novos)
```

### 3. O que NÃO foi feito

- Itens 3.3 (Action Registry) e 3.4 (Orchestrator Pipeline) — próximos da
  Fase 3. O Registry (3.3) vai consumir o loader e aplicar o Security Layer
  na execução das ferramentas.
- Execução de ferramentas com validação de segurança (3.3) — fora do escopo
  do loader, que apenas carrega/cataloga.
- Refatoração do `_audit_nicky` duplicado para o `core/logger.py` — pendente.
- Sandbox de execução de plugins (código Python confiável executado no
  import) — tema do `runtime/`/Fase 7, registrado aqui como decisão.

### 4. Próximo passo

**Fase 3, item 3.3 — Action Registry** (`tools/registry.py`): registro
TIPADO de ações consumindo o Tool Loader e validando execução pelo Security
Layer; depois Orchestrator Pipeline (3.4).

---

## [0.5.0] — Fase 3 (item 3.1) — Workflow Engine ✅ (2026-09-03)

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| 3.1 Workflow Engine | `core/workflows.py` | Execução linear com `entry_step`/`next`; branching condicional (`if_true_next`/`if_false_next`); sub-workflows nested com herança de input+variáveis; retries com `retry_delay`; timeout por step; `on_error` fail/continue; cancelamento cooperativo (`engine.cancel()`); persistência JSON atômica; integração Security Layer (`requires`, fail-closed) e Event Bus (`workflow.started`/`workflow.finished`); métricas + `dump()`; guarda anti-loop; logging via `core/logger.py` |

- Testes novos: `tests/test_workflows.py` (70) — validação de specs, linear,
  branching, fallback, loops, nested, retries, timeouts, cancelamento,
  segurança, persistência, event bus, métricas, cenário integrado.
- Documentação atualizada: `docs/CHANGELOG.md` (0.5.0),
  `docs/ROADMAP_ABSORCAO.md` (3.1 ✅, 13/32 capacidades).

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_workflows.py -q
→ 70 passed

.venv/bin/python -m pytest tests/ -q
→ 596 passed, 0 falhas   (526 anteriores + 70 novos)
```

### 3. O que NÃO foi feito

- Itens 3.2 (Tool Loader), 3.3 (Action Registry) e 3.4 (Orchestrator
  Pipeline) — próximos da Fase 3.
- Refatoração do `_audit_nicky` duplicado (`event_bus`, `router`, `state`,
  `memory`) para o `core/logger.py` — pendente (o Workflow Engine já nasce
  usando `core/logger.py`, padrão-alvo).
- Persistência em `data/workflows/` não exercitada em produção (camada grava
  sob demanda quando `base_dir` é informado).

### 4. Próximo passo

**Fase 3, item 3.2 — Tool Loader** (`tools/loader.py`): carregamento
dinâmico de ferramentas/plugins, depois Action Registry (3.3) e
Orchestrator Pipeline (3.4).

---

## [0.4.0] — Fase 2 — Memória ✅ (2026-09-03)

### 1. O que foi feito

5 capacidades implementadas em `memory/`, seguindo o mapeamento do legado
(NV Runtime Memory subsystem + Nicky `storage/`):

| Item | Arquivo | Destaques |
|---|---|---|
| 2.1 Conversation History | `memory/history.py` | `Message` imutável; histórico por usuário/perfil em `data/conversations/{user_id}/{profile}.json`; escrita atômica; `load_all()` no startup; `add_interaction()`, `add_system()`; `get_chatml()` (ChatML `<\|im_start\|>/<\|im_end\|>`); limite `max_entries` (padrão 20, como no legado); `clear()`, `stats()`, `list_users()`; thread-safe; audit NICKY |
| 2.2 Cache LLM | `memory/cache.py` | `LLMCache` com chave SHA-256 do prompt normalizado (whitespace colapsado + trim) + perfil + params; deduplicação; `use_count`, `avg_response_time_ms`, TTL; evicção LRU aproximada; persistência atômica em `data/llm_cache/cache.json` |
| 2.3 Quick Responses | `memory/quick_responses.py` | Alternância round-robin entre variações (`response`/`response_alt` do legado); analytics (`use_count`, `last_used_ts`, `avg_response_time_ms`); defaults PT-BR; persistência atômica em `data/quick_responses/quick_responses.json` |
| 2.4 Vector Memory (RAG) | `memory/vector.py` | `VectorStore` com similaridade de cosseno; namespaces; provider plugável (`EmbeddingProvider` protocol); `HashEmbeddingProvider` 100% stdlib; `add()`, `add_many()`, `search()` com `top_k`/`min_score`; persistência JSON com embeddings |
| 2.5 Context Manager | `memory/context.py` | `estimate_tokens()` (~4 chars/token); `fit()` mantém mensagens RECENTES no orçamento; `fit_chatml()`; `truncate()` mantendo o fim; `reserved_tokens`; stats (`trimmed`, `tokens_saved`) |

- Testes novos: `tests/test_history.py` (37), `tests/test_cache.py` (34),
  `tests/test_quick_responses.py` (28), `tests/test_vector.py` (36),
  `tests/test_context.py` (28).
- Documentação atualizada: `docs/CHANGELOG.md` (0.4.0),
  `docs/ROADMAP_ABSORCAO.md` (Fase 2 ✅, 12/32 capacidades),
  `docs/REGRAS_DE_TRABALHO.md` (§6).

### 2. Evidência

```
.venv/bin/python -m pytest tests/ -q
→ 526 passed, 0 falhas   (363 da Fase 1 + 163 novos da Fase 2)
```

- Contagem por suíte: history 37 ✅ · cache 34 ✅ · quick_responses 28 ✅ ·
  vector 36 ✅ · context 28 ✅
- Smoke test real executado: ChatML gerado corretamente, cache com hit por
  normalização, alternância de respostas funcionando, busca vetorial com score
  0.627, contexto encaixado no orçamento.

### 3. O que NÃO foi feito

- Refatoração do `_audit_nicky` duplicado (`core/event_bus.py`, `core/router.py`,
  `core/state.py`) para o `core/logger.py` — pendente, listada como próximo passo.
- Integração ChromaDB real (item 2.4): **decisão registrada** — ChromaDB
  indisponível no ambiente; implementado com provider stdlib
  (`HashEmbeddingProvider`) e interface `EmbeddingProvider` adaptável para
  troca futura (mitigação do roadmap: "preferir stdlib; isolar em adapters").
- Persistência real em disco não exercitada em produção (sem `data/` criado no
  ambiente de desenvolvimento; camadas escrevem sob demanda).

### 4. Próximo passo

**Fase 3 — Orquestração** (roadmap): `core/workflows.py` (Workflow Engine),
depois Tool Loader, Action Registry e Orchestrator Pipeline.

---

## [0.3.0] — Fase 1 — Fundação ✅ (2026-09-03)

### 1. O que foi feito

3 capacidades de fundação que desbloqueiam todas as demais fases:

| Componente | Arquivo | Destaques |
|---|---|---|
| Logger | `core/logger.py` | `NickyLogger` com protocolo NICKY (`[NICKY][NÍVEL]`); níveis `DEBUG/INFO/ONLINE/WARN/ERROR/CRIT`; saída texto ou JSON; sinks console + arquivo com rotação; contexto estruturado `key=value`; `.bind()`; `.audit(event, session_id=...)` (spec §7.3); `get_logger(name)`; thread-safe; stdlib puro |
| Security Layer | `core/security/` | Pipeline de 5 camadas (spec §7): `PolicyEngine` (allow/deny + allowlist deny-by-default + tokens destrutivos §7.2), `PermissionEngine` (role→ação, menor privilégio, fail-closed), `ScopeEngine` (escopo estrito §7.1, caminhos protegidos, proibição root/destrutivas §7.2), `ApprovalEngine` (aprovação humana com token + TTL, off por padrão), `AuditEngine` (trilha contínua §7.3 com ring buffer, métricas, sinks). `SecurityManager` orquestra com modos `compatibility`/`soft`/`strict`; `check()` e `dump()`; modelos tipados (`ActionRequest`, `SecurityDecision`, `AuditRecord`) |
| Config Manager | `configs/manager.py` | (já commitado em `ab96952` — Phase 1.1) |

- Testes novos: `tests/test_logger.py` (43), `tests/test_security.py` (95).
- Documentação atualizada: `docs/CHANGELOG.md` (0.3.0),
  `docs/ROADMAP_ABSORCAO.md` (Fase 1 ✅).

### 2. Evidência

```
.venv/bin/python -m pytest tests/ -q
→ 363 passed, 0 falhas   (225 anteriores + 138 novos)
```

### 3. O que NÃO foi feito

- Refatoração do `_audit_nicky` duplicado para o `core/logger.py` — já
  identificada na época; segue pendente até hoje (próximos passos).
- Fases 2 em diante do roadmap (Memória, Orquestração, Execução, Integrações,
  Sensorial, Infraestrutura).

### 4. Próximo passo

**Fase 2 — Memória**: Conversation History, Cache LLM, Quick Responses,
Vector Memory (RAG), Context Manager. → Concluída em [0.4.0].

---

## Linha do tempo de publicações no GitHub

| Versão | Fase | Publicada em | Commit |
|---|---|---|---|
| 0.1.0 | Especificação + OD Control Bridge | 2026-08-25 (histórico) | `c02b9ec` |
| 0.2.0 | Core infra + análises legadas | 2026-09-02 (histórico) | `c02b9ec` |
| 0.3.0 | Fase 1 — Fundação | 2026-09-02 (histórico parcial) | `ab96952` (Config Manager) |
| 0.4.0 | Fase 1 completa + Fase 2 — Memória | 2026-09-03 (publicado) | `a604f7f`, `ebc7f04` |
| 0.5.0 | Fase 3 (3.1) — Workflow Engine | 2026-09-03 (publicado) | `7008035` |
| 0.5.1 | Fase 3 (3.2) — Tool Loader | 2026-09-03 (publicado) | `3ee9616` |
| 0.6.0 | Fase 3 (3.3) — Action Registry | 2026-09-03 (publicado) | `b37765f` |
| 0.6.1 | Refatoração — Logger unificado | 2026-09-03 (publicado) | `6b54de5` |
| 0.7.0 | **Fase 3 completa (3.4)** — Orchestrator Pipeline | 2026-09-03 (esta publicação) | commit desta entrega |

> **Nota de transparência:** os relatórios §2.1 das Fases 1 e 2 foram
> registrados retroativamente neste documento (2026-09-03) a partir dos
> relatórios entregues nas sessões, para que o histórico completo fique
> persistido em um único lugar. As versões 0.1.0–0.2.0 são anteriores à
> criação das REGRAS_DE_TRABALHO e não possuem relatório §2.1 formal.

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/README_VERSAO.md
Descrição: Relatórios §2.1 persistidos por versão/fase entregue.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
