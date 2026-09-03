# OMEGA DRAKON — CHANGELOG

 Registro de implementações e mudanças significativas do sistema.

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
