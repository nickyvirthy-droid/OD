# OMEGA DRAKON — CHANGELOG

 Registro de implementações e mudanças significativas do sistema.

---

## [0.12.0] — 2026-09-03

### Adicionado

#### Integrações — Telegram Bot (`integrations/telegram/`) — Fase 5, item 5.1 ✅

**FASE 5 INICIADA — 1/5 itens.** Bot do Telegram sobre o Orchestrator com os
**14 recursos do legado Nicky** (13 comandos de texto + voz/STT), desacoplado
em 4 camadas e 100% testável sem rede:

- `models.py` — `User`/`Voice`/`Message`/`Update` (tipos desacoplados do
  transporte; mesmos formatos em memória e HTTP)
- `transport.py` — protocolo `TelegramTransport` + 2 implementações:
  `InMemoryTransport` (fila com watermark estilo servidor — polls
  sucessivos nunca reprocessam; testes/dev sem rede nem token) e
  `HTTPTransport` (Telegram Bot API via urllib **stdlib** — token
  obrigatório, getUpdates/sendMessage/getFile, erros HTTP/rede mapeados
  para `TransportError`)
- `commands.py` — os **13 comandos do legado**: `start`, `help` (alias
  `ajuda`), `perfil`, `limpar`, `status`, `uptime`, `stats`, `dashboard`,
  `historico`, `cache`, `presenca`, `codigo`, `rotacionar_key` — com
  `admin_only` por comando e o 14º recurso: **voz**
- `bot.py` — `TelegramBot`: resolve comandos (alias + `@botname`, admin
  gate) ou encaminha texto livre ao `Orchestrator.process()` com **perfil
  por chat** (guardian/regulus/luma/vox/athenae/nyx/auto, auto → default) ·
  **voz → STT plugável** (decoder injetável; fallback utf-8; sem STT
  reporta com segurança) → pipeline normal · hooks de histórico/cache do
  Orchestrator (`/historico`, `/limpar`, `/cache` reais) · métricas
  (messages/commands/replies/voices/errors) · **polling com offset
  persistente** e resiliência a falhas de transporte · `dump()` · NICKY

- **Sem rede nem dependências novas**: comandos locais funcionam mesmo sem
  Orchestrator conectado; segredos só no transporte HTTP (`TELEGRAM_BOT_TOKEN`)

### Infraestrutura
- **55 testes novos** em `tests/test_telegram.py` (modelos, transportes,
  parsing da Bot API com rede stubada, catálogo/admin gate, voz/STT com
  decoder plugável, mensagens sobre o Orchestrator com memória real,
  polling/offset, resiliência a erros)
- Suíte completa: **904 testes, 0 falhas** (849 + 55)
- **ROADMAP: 21/32 capacidades absorvidas** — Fase 5 iniciada (1/5)

---

## [0.11.0] — 2026-09-03

### Adicionado

#### Tools — Catálogo de 56 Actions (`tools/actions/`) — Fase 4, item 4.4 ✅

**FASE 4 COMPLETA — 4/4 itens.** Catálogo de **56 actions operacionais**
registradas no Action Registry com `permission` própria (gate do Security
Layer na execução):

- **Origem:** 54 ações enumeradas na análise legada do NV (§3.3 — sistema,
  processos, docker, serviços, arquivos, git, banco de dados, introspecção)
  + **2 complementares documentadas**: `process_tree` (processos) e
  `action_list` (introspecção)
- **Por categoria:** system 13 · process 4 · docker 4 · service 3 ·
  filesystem 15 · git 10 · database 3 · introspection 4
- `CATALOG` (metadados tipados: name/category/description/handler/params) e
  `build_registry(security=...)`/`register_all()` → ActionRegistry
- **Segurança por design**: nenhum handler usa caminho padrão (parâmetros
  de arquivo/git sempre explícitos); `process_kill` protege pid < 2;
  `system_env` sem `keys` retorna apenas NOMES (anti-vazamento de segredos);
  `system_ping` é sonda TCP (ICMP exigiria root); escopo estrito §7.1
  aplicado pelo Security Layer no Registry (path fora da raiz → denied)
- **Degradação graciosa**: docker/systemd/journald sem binário/daemon e
  banco de dados (camada é da Fase 7.5) retornam dados `{ok: False, error}`
  em vez de exceção — catálogo executável em qualquer ambiente
- Git 100% via `git -C <repo>` com repositório sempre explícito
  (branch/status/add/commit/log/diff/checkout/fetch/pull/push);
  filesystem completo (search/read/write/delete/exists/info/list/mkdir/
  move/copy/touch/tree/hash/archive/extract)
- Zero dependências externas novas (stdlib)

### Infraestrutura
- **31 testes novos** em `tests/test_actions_catalog.py` (catálogo e
  categorias, registro idempotente, execução funcional de sistema/arquivos/
  processos/git/introspecção, degradação de docker/serviços/db, gate de
  Security Layer — role desconhecida, path fora do escopo, deny pattern)
- Suíte completa: **849 testes, 0 falhas** (818 + 31)
- **FASE 4 CONCLUÍDA (4/4)** — **ROADMAP: 20/32 capacidades absorvidas**

---

## [0.10.0] — 2026-09-03

### Adicionado

#### Tools — Perception Syncer (`tools/telemetry.py`) — Fase 4, item 4.3 ✅

**FASE 4 — 3/4 itens.** Telemetria de hardware/serviços 100% stdlib
(leitura de `/proc`, `socket`, `shutil`), resiliente — falha de uma sonda
nunca derruba o snapshot:

- **CPU** — % de uso por delta entre amostras de `/proc/stat` (0.0 na
  primeira, baseline por instância), load average 1/5/15, núcleos
- **Memória** — `/proc/meminfo` em bytes: total/available/used/percent + swap
- **Disco** — `shutil.disk_usage` por caminho configurável (`disk_paths`)
- **Rede** — bytes rx/tx por interface (`/proc/net/dev`)
- **Portas** — sonda TCP (`socket` connect com timeout); resultados por porta
- **Docker** — daemon acessível? probe de socket unix (sem SDK externo)
- **Processos** — contagem por nome (`/proc/*/comm`), totais por snapshot
- **Host** — hostname, sistema, release, uptime (`/proc/uptime`), python
- `Telemetry.collect()` → `TelemetrySnapshot` tipado com seções + `errors`
  parciais; `dump()`; `proc_root`/`docker_socket` injetáveis (testes usam
  `/proc` fictício para determinismo)
- Seções independentes reportam `ok=False` + `error` sem levantar exceção;
  erros de seções também acumulados em `snapshot.errors` (observável)
- Logging via `core/logger.py` (protocolo NICKY); zero dependências novas

### Infraestrutura
- **21 testes novos** em `tests/test_telemetry.py` (/proc fictício: CPU delta,
  memória em bytes, load, rede, processos, uptime, disco; sondas reais de
  porta TCP aberta/fechada e socket unix do Docker; snapshot completo e
  resiliência a falhas parciais)
- Suíte completa: **818 testes, 0 falhas** (797 + 21)
- Smoke real executado: coleta contra `/proc` da máquina — mem 14.7%, disco
  27.8%, interfaces com bytes reais, Docker up, 0 erros
- **ROADMAP: 19/32 capacidades absorvidas — Fase 4 com 3/4 itens (4.1 ✅, 4.2 ✅, 4.3 ✅)**

---

## [0.9.0] — 2026-09-03

### Adicionado

#### Core — Self Repair Engine (`core/self_repair.py`) — Fase 4, item 4.2 ✅

**FASE 4 — 2/4 itens.** Auto-reparo com ciclo **detectar → gerar → reparar →
verificar → (rollback)**, com TODA correção mediada pelo Coder Engine (4.1):

1. **Detectar** — determinístico e sem efeitos colaterais: syntax check
   (`compile`) para `.py` + import probe opcional (executa módulo isolado,
   captura `ModuleNotFoundError`/falhas runtime) + oracle `check` injetado
   (componente íntegro?) — `Detection` tipada (category syntax/import/
   runtime/check, linha, coluna, mensagem)
2. **Gerar** — estratégias determinísticas embutidas (`AddMissingColon`:
   headers `def/class/if/elif/else/for/while/try/except/finally/with` sem
   `:`), estratégias customizáveis e **providers plugáveis** (`FixProvider` —
   ponto de extensão para auto-extensão via LLM no futuro, item 6.6)
3. **Reparar** — cada candidato passa pelo `CoderEngine.apply_change()`
   (sandbox → testes → backup → promoção + runner/test_command + Security
   Layer) — promoção só ocorre com o pipeline do Coder aprovando
4. **Verificar** — pós-promoção: oracle `check` (sync/async) e/ou
   re-detecção do arquivo
5. **Rollback automático** — se a verificação reprovar, snapshot pré-reparo
   (bytes exatos, `.od_repair_backups/`) é restaurado e o próximo candidato
   é tentado; `restore()` manual também disponível

- `SelfRepairEngine` (`async repair`) + `detect()` público; escopo estrito
  §7.1 (root, proteção de `.git`/áreas internas) — `SelfRepairScopeError`
- Snapshots pré-reparo SEMPRE antes da primeira mudança (rollback devolve o
  último estado conhecido, inclusive doente — fail-safe, documentado)
- Eventos `self_repair.detected` / `self_repair.completed` (best-effort)
- `Detection`/`RepairAttempt`/`RepairReport`/`RepairMetrics`: relatórios
  padronizados com attempts (rejected/applied/rolled_back), trilha recente
  e `dump()`; logging via `core/logger.py` (NICKY + audit)
- Zero dependências externas novas (stdlib puro)

### Infraestrutura
- **41 testes novos** em `tests/test_self_repair.py` (detecção, estratégia de
  colon, ciclos healthy/repaired/no_fix/error, oracle check sync/async,
  rollback e restore, mediação do Coder (runner/security), providers e
  dedupe/max_attempts, eventos, métricas/trilha/dump)
- Suíte completa: **797 testes, 0 falhas** (756 + 41)
- **ROADMAP: 18/32 capacidades absorvidas — Fase 4 com 2/4 itens (4.1 ✅, 4.2 ✅)**

---

## [0.8.0] — 2026-09-03

### Adicionado

#### Core — Coder Engine (`core/coder.py`) — Fase 4, item 4.1 ✅

**FASE 4 INICIADA** — modificação segura de código com pipeline
**sandbox → testes → backup → promoção** (NV `core/coder.py`), sem nunca
tocar o arquivo real antes da validação:

1. **Sandbox** — o conteúdo patcheado é materializado em área isolada
   (`<root>/.od_sandbox/<change_id>/<relpath>`) — o original permanece intocado
2. **Testes** — syntax check (`compile`) para `.py` + runner injetado
   (sync/async) ou `test_command` (subprocess com tokens `{file}`/`{sandbox}`/
   `{root}`/`{relpath}`, cwd=sandbox, timeout) — falha aqui NUNCA promove
3. **Backup** — o original é copiado para `<root>/.od_backups/`
   (`<arquivo>.<change_id>.bak`) antes de qualquer escrita
4. **Promoção** — escrita atômica (tmp + `os.replace`) do artefato validado

- `CoderEngine` (`async apply_change`) — aceita `patch` (diff unificado) OU
  `content` completo; `create=True` para arquivos novos; parâmetros de
  message/role/session_id/metadata; `generate_patch()` para produzir diffs
  seguros (round-trip garantido)
- **Unified diff nativo (stdlib)**: `parse_unified_diff`/`apply_unified_diff`/
  `generate_unified_patch`/`diff_stats` — múltiplos hunks, inserção/remoção,
  arquivo vazio, sem newline final (marcador `\ No newline`), **relocation**
  (hunk aplica mesmo com o arquivo derivado, estilo `patch --fuzz`) e
  rejeição de diffs fora de ordem com erro descritivo
- **Escopo estrito (spec §7.1)**: todo caminho resolve dentro do `root`;
  `.git`, diretórios internos (`.od_sandbox`/`.od_backups`) e caminhos fora
  do root são rejeitados (`CoderScopeError`); root padrão = projeto
- **Security Layer (spec §7)**: gate opcional na promoção (action
  `coder.promote`, paths + role) — fail-closed em modo `strict`;
  compatibilidade/soft apenas sinalizam
- **Event Bus**: publica `coder.started` / `coder.completed` (best-effort)
- **TestOutcome/CoderResult/CoderMetrics**: resultados padronizados com
  steps executados, backup_path, summary (`+N -M`), métricas por status,
  trilha recente (com limite) e `dump()`
- Logging via `core/logger.py` (protocolo NICKY + `log.audit("coder.promote")`)
- Zero dependências externas novas (difflib/asyncio/subprocess/shutil stdlib)

### Infraestrutura
- **59 testes novos** em `tests/test_coder.py` (parse/aplicação de diffs,
  round-trips com casos extremos, escopo, pipeline completo, falhas com
  arquivo intacto, runner/command/timeout, Security Layer, Event Bus,
  métricas/histórico/dump)
- Suíte completa: **756 testes, 0 falhas** (697 + 59)
- **ROADMAP: 17/32 capacidades absorvidas — Fase 4 iniciada (item 4.1 ✅)**

---

## [0.7.0] — 2026-09-03

### Adicionado

#### Core — Orchestrator Pipeline (`core/orchestrator.py`) — Fase 3, item 3.4 ✅

**FASE 3 COMPLETA** — pipeline de 8 etapas para processamento de mensagens:

1. **Rate Limit** — janela deslizante por usuário (padrão 10 msg/60s), clock injetável
2. **Datetime PT-BR** — detecta "que horas/dia" e responde sem LLM; injeta data/hora no
   system prompt quando o caminho segue para o LLM
3. **Quick Responses** — respostas instantâneas (AIML legado) via rota `quick_response`
4. **Cache LLM** — consulta SHA-256 por prompt normalizado + perfil; hit responde sem LLM
5. **Histórico** — monta contexto ChatML com os últimos N turns (ConversationHistory)
6. **LLM** — providers plugáveis tentados em ordem (protocolo `LLMProvider`)
7. **Fallback** — provider com falha é substituído pelo próximo; esgotados → `llm_unavailable`
8. **Pós-processamento** — grava no cache + histórico e registra métricas

- `Orchestrator`, `OrchestratorConfig`, `OrchestrationResult` (to_dict) — sem dependência
  externa de LLM: sem providers, rotas curtas (datetime/quick) seguem funcionando
- Componentes de memória opcionais (history/cache/quick ausentes → etapas puladas)
- Publicação de evento `orchestrator.responded` no Event Bus (opcional)
- Métricas por rota (processed, datetime, quick, llm, cache_hits, errors, avg_latency_ms)
  + `dump()`; logging via `core/logger.py`

### Infraestrutura
- **29 testes novos** em `tests/test_orchestrator.py` (rate limit, datetime PT-BR,
  quick responses, cache, histórico, fallback de providers, métricas, event bus)
- Suíte completa: **697 testes, 0 falhas** (668 + 29)
- **ROADMAP: 16/32 capacidades absorvidas (Fase 3 concluída)**

---

## [0.6.1] — 2026-09-03

### Refatoração

#### Logger unificado — `_audit_nicky` → `core/logger.py` ✅
- Implementação canônica única do emissor NICKY: `core/logger.make_audit_nicky(name)`
  (resolução de níveis INFO/WARN/CRIT/ERROR/DEBUG/ONLINE + formatação do
  protocolo NICKY centralizadas em um único lugar)
- 13 módulos deixaram de duplicar o helper `_audit_nicky` (removidos ~155
  linhas de boilerplate idêntico) e agora fazem apenas:
  `_audit_nicky = make_audit_nicky("omega.<componente>")`
- Módulos migrados: `core/event_bus.py`, `core/router.py`, `core/state.py`,
  `core/security/` (manager, policy, permissions, scope, approval, audit) e
  `memory/` (history, cache, quick_responses, vector, context)
- Chamadas existentes (`_audit_nicky("INFO", ...)`) preservadas — zero
  mudança de comportamento; logs agora seguem o NickyLogger (protocolo NICKY
  em console/arquivo) via `core/logger.py`

### Infraestrutura
- Suíte completa mantida: **668 testes, 0 falhas** (sem mudança funcional)
- Pendência antiga do roadmap ("Integrar Logger nos componentes existentes")
  resolvida — resta apenas o item 3.4 (Orchestrator) para fechar a Fase 3

---

## [0.6.0] — 2026-09-03

### Adicionado

#### Tools — Action Registry (`tools/registry.py`) — Fase 3, item 3.3 ✅
- `Action` — ação tipada: name, handler (sync/async), description, category,
  params (schema), permission (Security Layer), aliases, version, source
- `ActionResult` — resultado padronizado: `ok | invalid | denied | error | not_found`
  com data, error, errors, denied_by, role, params preenchidos e duração
- `ActionRegistry` — registro central de ações com execução validada:
  - Pipeline: resolução (nome/alias) → validação de schema (defaults aplicados)
    → gate de segurança (permission + SecurityManager, spec §7) → handler
  - Validação de params reutilizando o `validate_params` do Tool Loader
    (extraído em refactor compartilhado)
  - Registro por instância (`register`) ou conveniência (`register_action`)
  - **Importação de ferramentas do Tool Loader** (`import_loader`) — cada Tool
    vira Action reaproveitando schema, requires → permission e origem
  - Aliases resolvidos em `get()`/`execute()`; duplicados com skip ou
    `allow_overwrite=True`; `unregister` remove aliases
  - Métricas (`RegistryMetrics`: ok/invalid/denied/errors/not_found, duração),
    trilha recente com limite (`history`) e `dump()`
  - Logging via `core/logger.py` (protocolo NICKY); execução negada registra CRIT
- 33 testes unitários em `tests/test_registry.py`

### Infraestrutura
- Refactor: validação de schema extraída para `validate_params()` em
  `tools/loader.py` (reutilizada por Tool e Action)
- Suíte completa: **668 testes, 0 falhas** (635 anteriores + 33 novos)
- Fase 3 do ROADMAP_ABSORCAO.md: itens 3.1 ✅, 3.2 ✅ e 3.3 ✅ — falta 3.4 (Orchestrator)

---

## [0.5.1] — 2026-09-03

### Adicionado

#### Tools — Tool Loader (`tools/loader.py`) — Fase 3, item 3.2 ✅
- `Tool` — metadados + callable (name, description, category, params, requires, version, tags, source/module, async)
- `ToolLoader` — carregamento dinâmico de plugins Python:
  - Contratos de plugin: `PLUGIN` (dict com `tools`), `TOOLS` (lista) ou função `load_tools()`
  - Entrada de ferramenta aceita dict, `Tool` ou callable puro (nome/docstring derivados)
  - Descoberta recursiva em diretórios, ignora não-`.py` e arquivos `_`/`.`
  - Escopo estrito (`ToolScopeError`) — arquivos fora dos `dirs` são recusados (spec §7.1)
  - Falha de import isolada (não derruba os demais módulos; erros registrados com CRIT)
  - Módulo sem contrato é pulado com WARN; entrada inválida não derruba o módulo
  - Nome duplicado: skip por padrão ou `allow_overwrite=True`
  - Hot-reload: `reload(name)` / `reload_all()` — falha de reload preserva a versão anterior
  - `validate(params)` — validação de schema (required + tipos com distinção bool/int, defaults)
  - `invoke()` sync/async, `get/find/has/unload/clear/dump`, métricas (`LoaderMetrics`)
  - Logging via `core/logger.py` (protocolo NICKY)
- `tools/__init__.py` — pacote com docstring canônico `OD // CORE`
- 39 testes unitários em `tests/test_tool_loader.py`

### Infraestrutura
- Suíte completa: **635 testes, 0 falhas** (596 anteriores + 39 novos)
- Fase 3 do ROADMAP_ABSORCAO.md: itens 3.1 ✅ e 3.2 ✅ — próximos: 3.3 Action Registry, 3.4 Orchestrator

---

## [0.5.0] — 2026-09-03

### Adicionado

#### Core — Workflow Engine (`core/workflows.py`) — Fase 3, item 3.1 ✅
- `WorkflowStep` / `WorkflowSpec` / `WorkflowContext` / `WorkflowExecution` — modelos tipados
- **Execução linear** com entrada configurável (`entry_step`) e `next` explícito
- **Branching condicional** (`if_true_next` / `if_false_next`) com salto explícito: um alvo de salto sem `next` próprio encerra o workflow (branches irmãos não vazam)
- **Sub-workflows (nested)** — executa workflow registrado herdando input + variáveis do pai e propagando o output de volta
- **Retries** automáticos por step com `retry_delay` e **timeout** individual
- **on_error** por step ou `default_on_error` do workflow (`fail` | `continue`)
- **Cancelamento cooperativo** via `engine.cancel()` (corre contra o step em andamento)
- **Persistência** JSON atômica opcional em `data/workflows/executions/{execution_id}.json` + `load_execution()`/`list_executions()`
- **Integração Security Layer** — steps com `requires` são validados antes de executar (fail-closed em modo strict)
- **Integração Event Bus** — publica `workflow.started` / `workflow.finished`
- **Métricas** (`WorkflowMetrics`), `dump()` e guarda anti-loop (`max_steps`)
- Logging via `core/logger.py` (padrão-alvo da arquitetura, protocolo NICKY)
- 70 testes unitários em `tests/test_workflows.py`

### Infraestrutura
- Suíte completa: **596 testes, 0 falhas** (526 anteriores + 70 novos)
- Fase 3 do ROADMAP_ABSORCAO.md iniciada: item 3.1 (Workflow Engine) ✅ — próximos: 3.2 Tool Loader, 3.3 Action Registry, 3.4 Orchestrator

---

## [0.4.1] — 2026-09-03

### Documentado
- Criado `docs/README_VERSAO.md` — README de Versão com os relatórios do
  protocolo §2.1 persistidos por versão/fase entregue (Fases 1 e 2 registradas
  retroativamente; versão mais recente no topo; linha do tempo de publicações
  no GitHub)
- `docs/REGRAS_DE_TRABALHO.md` — novas regras normativas:
  - §2.1.1 — relatório §2.1 DEVE ser salvo em `docs/README_VERSAO.md` ao
    concluir cada fase (sem a entrada, a fase não é considerada concluída)
  - §2.1.2 — publicação DEVE ser feita no GitHub (commit + push para
    `origin/master`) ao concluir cada fase, sempre com a suíte verde e sem
    forçar push em caso de divergência
  - Ciclo de trabalho (§3) ampliado: passos 6–8 (registrar relatório,
    publicar, reportar com hash do commit)
  - Checklist do revisor (§5) ampliado: itens 7–8 (README_VERSAO e GitHub)

### Infraestrutura
- Publicação da Fase 1 completa + Fase 2 no GitHub (`origin/master`) para
  que nenhum artefato fique apenas em disco local
- Suíte completa mantida: **526 testes, 0 falhas**

---

## [0.4.0] — 2026-09-03

### Adicionado

#### Memory — Camada de Memória (Fase 2 do ROADMAP_ABSORCAO.md) ✅

#### Memory — Conversation History (`memory/history.py`) — item 2.1
- `Message` — mensagem imutável com role, content, ts, llm_used
- `ConversationHistory` — histórico por usuário/perfil:
  - Persistência JSON em `data/conversations/{user_id}/{profile}.json` com escrita atômica
  - `load_all()` no startup, carga sob demanda por conversa
  - `add_interaction()` (turno usuário+assistente), `add_message()`, `add_system()`
  - `get_history()` e `get_chatml()` (formato ChatML `<|im_start|>`/`<|im_end|>`)
  - Limite de `max_entries` por conversa (padrão 20, como no legado) — descarta as mais antigas
  - Isolamento estrito por usuário/perfil; `clear()`/`clear_all()` com remoção de arquivo
  - `stats()`, `list_users()`, `list_profiles()`, `last_interaction()`
  - Thread-safe, audit logging via protocolo NICKY
- `build_chatml()` — formatador reutilizável (aceita `Message` ou dicts)
- 37 testes unitários em `tests/test_history.py`

#### Memory — Cache LLM (`memory/cache.py`) — item 2.2
- `LLMCache` — cache de respostas do LLM:
  - Chave SHA-256 do prompt normalizado (whitespace colapsado + trim) + perfil + params
  - Normalização e deduplicação (set repetido conta duplicata, atualiza resposta)
  - `use_count`, `avg_response_time_ms`, TTL configurável, evicção LRU aproximada
  - Persistência JSON atômica em `data/llm_cache/cache.json`, com métricas
  - Thread-safe, audit logging via protocolo NICKY
- 34 testes unitários em `tests/test_cache.py`

#### Memory — Quick Responses (`memory/quick_responses.py`) — item 2.3
- `QuickResponses` — respostas rápidas sem LLM:
  - Alternância round-robin entre variações (`response`/`response_alt` do legado)
  - Analytics por padrão: `use_count`, `last_used_ts`, `avg_response_time_ms`
  - Defaults PT-BR (oi, bom dia, obrigado, etc.), perfil isolado
  - Persistência JSON atômica em `data/quick_responses/quick_responses.json`
  - Thread-safe, audit logging via protocolo NICKY
- 28 testes unitários em `tests/test_quick_responses.py`

#### Memory — Vector Memory (RAG) (`memory/vector.py`) — item 2.4
- `VectorStore` — memória vetorial com busca por similaridade de cosseno:
  - Provider de embeddings plugável (`EmbeddingProvider` protocol) — adapter-ready para ChromaDB/sentence-transformers
  - `HashEmbeddingProvider` (stdlib puro): vetores determinísticos por hash de tokens e bigramas — zero dependências externas
  - `add()`/`add_many()`/`search()` com `top_k` e `min_score`; namespaces isolados
  - Persistência JSON com embeddings (evita re-embedding), escrita atômica
  - Thread-safe, audit logging via protocolo NICKY
- `cosine_similarity()` — similaridade de cosseno stdlib puro
- 36 testes unitários em `tests/test_vector.py`

#### Memory — Context Manager (`memory/context.py`) — item 2.5
- `ContextManager` — prevenção de estouro de tokens:
  - `estimate_tokens()` — heurística ~4 chars/token (BPE aproximado)
  - `fit()` — encaixa o máximo de mensagens RECENTES no orçamento (descarta antigas)
  - `fit_chatml()` — histórico + system prompt em ChatML dentro do orçamento
  - `truncate()` — trunca texto único mantendo o fim (informação mais recente)
  - `reserved_tokens` para a resposta do modelo; stats (trimmed, tokens_saved)
  - Integra com `Message` do history e dicts
- 28 testes unitários em `tests/test_context.py`

### Infraestrutura
- Suíte completa: **526 testes, 0 falhas** (363 anteriores + 163 novos)
- Fase 2 do ROADMAP_ABSORCAO.md concluída: 2.1 ✅ 2.2 ✅ 2.3 ✅ 2.4 ✅ 2.5 ✅
- **Decisão registrada:** item 2.4 (Vector Memory) implementado SEM ChromaDB (não disponível no ambiente), com provider de embeddings stdlib e interface adaptável para ChromaDB/sentence-transformers no futuro (mitigação do roadmap: "preferir stdlib; isolar em adapters")

---

## [0.3.0] — 2026-09-03

### Adicionado

#### Core — Logger (`core/logger.py`)
- `NickyLogger` — logger estruturado com protocolo NICKY (`[NICKY][NÍVEL]`):
  - Níveis: `DEBUG`, `INFO`, `ONLINE`, `WARN`, `ERROR`, `CRIT` (ONLINE para presença/heartbeat)
  - Saída texto (padrão) ou JSON estruturado (`json_output=True`)
  - Sinks simultâneos: console + arquivo (append-only com rotação por tamanho e backups)
  - Contexto estruturado por chamada (`key=value`) e ring buffer em memória
  - Context binding via `.bind()` para loggers filhos com contexto fixo
  - `.audit(event, session_id=...)` para auditoria contínua (spec §7.3)
  - Thread-safe (lock interno), registro global via `get_logger(name)`
- Implementação com apenas stdlib Python (zero dependências externas)
- 43 testes unitários em `tests/test_logger.py`

#### Core — Security Layer (`core/security/`)
- **Pipeline de 5 camadas** (policy → permission → scope → approval → audit):
  - `PolicyEngine` — regras globais allow/deny por padrão de ação (fnmatch), allowlist (deny-by-default) e detecção de tokens destrutivos em params (`rm -rf`, `DROP TABLE`, `mkfs`, etc.) com defaults da spec §7.2
  - `PermissionEngine` — papéis (roles) mapeados para padrões de ações, menor privilégio por padrão, papéis desconhecidos negados (fail-safe), admin com wildcard `*`
  - `ScopeEngine` — escopo estrito do projeto (spec §7.1): raízes permitidas, caminhos protegidos (`.git` read-only), proibição de execução root e de operações destrutivas (spec §7.2), heurística read/write
  - `ApprovalEngine` — aprovação humana para ações sensíveis com token secreto, TTL e ciclo approve/reject (desativado por padrão)
  - `AuditEngine` — trilha de auditoria contínua (spec §7.3) com ring buffer, métricas e sinks externos
- `SecurityManager` — orquestra o pipeline com modos de enforcement:
  - `compatibility` (padrão): apenas audita, nunca bloqueia
  - `soft`: audita + registra warning, mas permite
  - `strict`: fail-closed — bloqueia se qualquer camada rejeitar
- `ActionRequest` / `SecurityDecision` / `AuditRecord` — modelos tipados e imutáveis
- Conveniência `security.check(action, role=..., paths=..., ...)` sem montar ActionRequest
- Implementação com apenas stdlib Python (zero dependências externas)
- 95 testes unitários em `tests/test_security.py`

### Infraestrutura
- Suíte completa: **363 testes, 0 falhas** (225 anteriores + 138 novos)
- Fase 1 do ROADMAP_ABSORCAO.md concluída: Config Manager ✅, Security Layer ✅, Logger ✅

---

## [0.2.0] — 2026-09-02

### Adicionado

#### Core — Config Manager (`configs/manager.py`)
- `ConfigManager` — gerenciador de configurações centralizado com:
  - Carregamento de YAML + env vars com prioridade
  - Validação via Pydantic (quando disponível)
  - Chaves hierárquicas com dots (ex: `system.bridge.host`)
  - Defaults configuráveis
  - Override programático
  - Watchers para notificação de mudanças
  - Export/Import (YAML, JSON, dict)
  - Reload/Reset lifecycle
  - Audit logging via protocolo NICKY
- `ConfigEntry` — dataclass com metadados (key, value, source, timestamp)
- `ConfigSchema` — schema Pydantic com validação (50+ campos)
- Singleton pattern via `get_config_manager()`
- Configurações suportadas: sistema, servidor, LLM, database, segurança, rate limiting, memória, persistência, notificações, STT, TTS, RAG, Telegram, Home Assistant, MQTT, APIs externas
- 46 testes unitários em `tests/test_config_manager.py`

#### Core — Event Bus (`core/event_bus.py`)
- `Event` — dataclass imutável com topic, data, priority, source, event_id, ts, ttl
- `Event.matches()` — routing por padrão com `*` (single-level) e `**` (multi-level) wildcards
- `Priority` — enum com CRITICAL(0), HIGH(10), NORMAL(50), LOW(90), BACKGROUND(100)
- `EventBus` — pub/subscribe central com:
  - Decorator `@bus.subscribe("topic")` e programático `bus.subscribe_handler()`
  - Handlers sync e async
  - Ordem de execução por prioridade
  - Retry configurável com dead-letter queue
  - TTL em eventos (expiração automática)
  - Métricas em tempo real (published, delivered, failed, dropped)
  - Audit logging via protocolo NICKY (`[NICKY][INFO|WARN|CRIT]`)
  - Lifecycle (start/stop) com proteção contra duplo-start
- Implementação com apenas stdlib Python (zero dependências externas)
- 56 testes unitários em `tests/test_event_bus.py`

#### Core — State Manager (`core/state.py`)
- `StateValue` — wrapper versionado com value, version, ts, source
- `StateSnapshot` — snapshot pontual para suporte a rollback
- `StateManager` — gerenciador de estado com:
  - Chaves hierárquicas com paths dot-separated (`system.bridge.health`)
  - `get/set/delete` — CRUD com proteção por deep copy
  - `get_many/set_many` — operações batch atômicas
  - `compare_and_set` — CAS atômico para padrões de concorrência
  - `keys(prefix)` — consultas por namespace
  - `clear` — reset completo do estado
  - Versionamento — contador global monotonico crescente
  - Rollback — `rollback(steps)` e `rollback_to_version(version)`
  - Watchers — inscrição em mudanças de padrões de chaves (wildcards `*` e `**`)
  - Integração com Event Bus — publica `state.changed`, `state.removed`, `state.cleared`, `state.rollback`
  - Persistência em disco — escritas JSON atômicas com agendamento debounced
  - Export/Import — estado serializável para backup e migração
  - Dump — snapshot diagnóstico completo
- Implementação com apenas stdlib Python (zero dependências externas)
- Audit logging via protocolo NICKY
- 68 testes unitários em `tests/test_state.py`

#### Agent — Nicky Virthy (`agents/nicky_virthy/`)
- `IDENTITY.md` — identidade canônica: nome, creature (Interface Viva), vibe, emoji, aparência, vedações, tríade, axiomas, protocolo de voz, 6 perfis operacionais
- `SOUL.md` — alma e diretrizes comportamentais: verdades fundamentais, como se comporta, limites inegociáveis, tom de voz por perfil, continuidade, o que não é
- Basado inteiramente no legado consolidado (`knowledge/NICKY_VIRTHY_KNOWLEDGE.md` e `knowledge/OMEGA_DRAKON_SOURCE_MAP.md`)
- Tríade canônica documentada: Alex Projeti → OmegaDrakon → Nicky Virthy
- Protocolo NICKY de logs: `[NICKY][INFO|WARN|CRIT|ONLINE]`
- 6 perfis: guardian (padrão), regulus, luma, vox, athenae, nyx

#### Core — Message Router (`core/router.py`)
- `Message` — dataclass imutável com source, destination, action, payload, priority, msg_id, ts, reply_to, timeout, metadata
- `MessageReply` — reply com status (ok/error/timeout), data, error
- `MessagePriority` — enum com CRITICAL(0), HIGH(10), NORMAL(50), LOW(90)
- `MessageRouter` — roteador de mensagens inter-componentes com:
  - Endpoints nomeados — registro `router.register("bridge", handler)`
  - Send (fire-and-forget) — `router.send("bridge", "ping")`
  - Request/Reply — `router.request("bridge", "health", timeout=5.0)` com futures assíncronos
  - Broadcast — `router.broadcast("status")` para todos os endpoints ativos
  - Handlers sync e async
  - Background task para handlers de request (não bloqueia o caller)
  - Timeout configurável em requests
  - Dead-letter queue para entregas falhas
  - Métricas em tempo real (sent, delivered, broadcast, failed, timeout)
  - Histórico de roteamento com trim automático
  - Lifecycle (start/stop) com cancelamento de pending requests
  - Integração com Event Bus — publica `router.request`, `router.broadcast`
- Implementação com apenas stdlib Python (zero dependências externas)
- Audit logging via protocolo NICKY
- 55 testes unitários em `tests/test_router.py`

#### Documentação — Análise do Sistema Legado Nicky (`docs/NICKY_LEGACY_ANALYSIS.md`) — Revisão Completa
- **Reescrita total** da análise do sistema Nicky v0.7.0 em `/home/alex/nicky`
- Leitura direta de todos os módulos: main.py, config, core, interfaces, llm, vision, storage, profiles, knowledge, scripts, static, tests, docs
- Arquitetura geral: monólito com interfaces (Telegram, API, WebSocket), orquestrador, LLM, vision
- Pipeline de 8 etapas documentado: rate limiting → datetime → AIML → cache → history → Qwen → Gemini → post-processing
- 6 perfis de personalidade analisados: guardian, regulus, luma, vox, athenae, nyx
- Módulos detalhados: core (orchestrator, event_bus, db, personality, conversation_history, vector_memory), interfaces (api, telegram, notifier, text_to_speech), LLM (base.py, llama_server_client, 6 providers), storage (cache, history, quick_responses), vision (face_detector, presence_monitor, audio_capture)
- Tabelas MariaDB mapeadas: llm_cache, quick_responses, response_analytics, conversation_messages, presence_log
- 17 endpoints da API documentados com detalhes de cada rota
- 14 comandos Telegram documentados com parâmetros e exemplos
- Profile Manager analisado: 6 perfis com system prompts específicos por contexto
- Knowledge Processor analisado: processamento híbrido AIML + detecção de intenção
- TTS integrado: pyttsx3 fallback, ElevenLabs primary
- Scripts operacionais documentados: healthcheck.sh, deploy, generate_icons.py
- Testes: 80+ unitários + 10+ integração mapeados
- Pontos fortes identificados: soberania local, pipeline definido, event bus desacoplado, rate limiting duplo, cache SHA-256, 80+ testes, profiles separados
- Dívida técnica mapeada: monólito concorrente, 3 pools de conexão, bare excepts, f-strings em logs, senhas hardcoded, arquivos .bak, vetores de embedding ineficientes
- Mapeamento de absorção para OmegaDrakon: 8 capacidades com prioridades definidas
- Recomendação: absorver feature-by-feature, não copiar o monólito
- Arquitetura geral: monólito com interfaces (Telegram, API, WebSocket), orquestrador, LLM, vision
- Pipeline de 8 etapas documentado: rate limiting → datetime → AIML → cache → history → Qwen → Gemini → post-processing
- 6 perfis de personalidade analisados: guardian, regulus, luma, vox, athenae, nyx
- Módulos detalhados: core (orchestrator, event_bus, db, personality), interfaces (api, telegram, notifier), LLM (6 providers), storage (cache, history, quick_responses), vision (face_detector, presence_monitor)
- Tabelas MariaDB mapeadas: llm_cache, quick_responses, response_analytics, conversation_messages, presence_log
- 17 endpoints da API documentados
- 14 comandos Telegram documentados
- Pontos fortes identificados: soberania local, pipeline definido, event bus desacoplado, rate limiting duplo, cache SHA-256, 80+ testes
- Dívida técnica mapeada: monólito concorrente, 3 pools de conexão, bare excepts, f-strings em logs, senhas hardcoded, arquivos .bak
- Mapeamento de absorção para OmegaDrakon: 8 capacidades com prioridades definidas
- Recomendação: absorver feature-by-feature, não copiar o monólito

#### Documentação — Análise do Sistema Legado NV Runtime (`docs/NV_LEGACY_ANALYSIS.md`)
- Análise completa do NV Runtime v1.11.0 em `/home/alex/NV`
- Arquitetura modular: Runtime Kernel + 13 subsystems (Event, Action, Memory, Database, Session, Registry, Provider, Plugin, Tool Runtime, Coder, Security, Workflow, API)
- 56 actions operacionais documentadas: sistema, processos, docker, serviços, arquivos, git, banco de dados, introspecção
- Security Layer com pipeline de 5 camadas: policy → permission → scope → approval → audit
- Workflow Engine com branching, nested workflows, retries, timeouts, persistência
- Coder Engine com pipeline: sandbox → patch → validação → backup → promoção
- 100+ testes unitários mapeados
- API REST FastAPI na porta 7001
- Pontos fortes: modularidade extrema, security layer robusto, 56 actions, workflow engine completo
- Dívida técnica: acoplamento ao Nicky, approval desativado, API sem auth
- Mapeamento de absorção: 6 capacidades com prioridades definidas

#### Documentação — Análise do Sistema Legado Nexus (`docs/NEXUS_LEGACY_ANALYSIS.md`)
- Análise completa do Nexus v1.9.2 (Plêiade) em `/home/alex/nexus`
- Arquitetura: Nexus Core (auto-extensão via Gemini), Cognitive Router (FastAPI), Perception Syncer (telemetria), Brain (LLM local), Main Cycle (ciclo autônomo 5min), IoT Manager (Home Assistant), Self Repair, Context Manager, Vox Messenger, Tool Loader, Auditor
- Capacidade única: auto-extensão — gera novas ferramentas Python via Gemini em tempo real
- Auto-cura — detecta falhas e gera scripts de correção automaticamente
- Percepção holística: CPU/RAM, Docker, portas, rede (Nmap), IoT (Home Assistant)
- 3 serviços systemd: nexus.service, nexus-router.service, nexus-pulse.service
- Integração IoT: Home Assistant via REST + MQTT
- 10 testes documentados
- Pontos fortes: auto-extensão, auto-cura, percepção holística, soberania local
- Dívida técnica: Gemini API como dependência crítica, auto-cura sem sandbox robusto, crash-loop no serviço, sem autenticação
- Mapeamento de absorção: 10 capacidades com prioridades definidas
- Alerta: auto-extensão e auto-cura devem ser mediadas pelo Security Layer no OmegaDrakon

#### Documentação — Roadmap de Absorção Legada (`docs/ROADMAP_ABSORCAO.md`)
- Documento de planejamento com **32 capacidades** a absorver de 3 sistemas legados
- **7 fases** de implementação com dependências mapeadas
- Fase 1 (Fundação): Config Manager, Security Layer, Logger — desbloqueia todas as outras
- Fase 2 (Memória): History, Cache, Quick Responses, RAG, Context Manager
- Fase 3 (Orquestração): Workflow Engine, Tool Loader, Action Registry, Orchestrator
- Fase 4 (Execução): Coder Engine, Self Repair, Perception, 56 Actions
- Fase 5 (Integrações): Telegram, API REST, Notifier, IoT, MQTT
- Fase 6 (Sensorial): Face Detection, Presence, STT, TTS, Profiles, Auto Extension
- Fase 7 (Infraestrutura): Audit, Metrics, Health, Plugins, Database
- Mapa de dependências completo entre fases
- Estimativas de esforço: ~15-20 dias, ~330-460 testes
- Critérios de aceite por fase documentados
- Riscos e mitigações identificados
- Capacidades descartadas justificadas (App Flutter, Gemini fallback, etc.)
- Métricas de progressão definidas (4/32 → 32/32 capacidades)

### Infraestrutura
- Criado `core/__init__.py` com docstring canônico `OD // CORE`
- Criado `tests/__init__.py` para pacote de testes
- Criado `configs/__init__.py` com docstring canônico `OD // CORE`
- Configurado virtualenv em `.venv` com pytest, pytest-asyncio e pyyaml
- Suíte completa: **225 testes, 0 falhas**

---

## [0.1.0] — 2026-08-25

### Documentado
- Especificação técnica e arquitetural oficial (`docs/OMEGADRAKON_SPEC.md` v1.0.0)
- Documentação operacional do OD Control Bridge (`docs/CONTROL_BRIDGE.md`)
- Consolidação do legado Nicky Virthy (`knowledge/NICKY_VIRTHY_KNOWLEDGE.md`)
- Mapeamento de origem do Omega Drakon (`knowledge/OMEGA_DRAKON_SOURCE_MAP.md`)
- Snapshot do estado inicial do servidor (`archive/INITIAL_SYSTEM_STATE_SERVER_WIDE.txt`)

### Operacional
- OD Control Bridge v0.1 (`runtime/control_bridge/bridge.py`)
  - HTTP local em `127.0.0.1:8765`
  - Execução como `odrunner` (sem root)
  - Allowlist de comandos e bloqueio de tokens destrutivos
  - Restrição de filesystem ao diretório do OmegaDrakon
  - Audit logging em JSONL
  - Serviço systemd `od-control-bridge.service`
