# OMEGA DRAKON — CHANGELOG

 Registro de implementações e mudanças significativas do sistema.

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
