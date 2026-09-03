# OMEGA DRAKON — README DE VERSÃO

> **Finalidade:** persistir o relatório do protocolo §2.1 (REGRAS_DE_TRABALHO.md)
> de **cada versão/fase entregue** — para que nenhum trabalho, decisão ou
> pendência se perca, mesmo entre sessões.
> **Regra:** a versão mais recente fica no topo. Toda fase concluída adiciona
> uma seção aqui ANTES de ser publicada no GitHub.
> **Assinatura:** `OD // CORE`

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
| 0.5.0 | Fase 3 (3.1) — Workflow Engine | 2026-09-03 (esta publicação) | commit desta entrega |

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
