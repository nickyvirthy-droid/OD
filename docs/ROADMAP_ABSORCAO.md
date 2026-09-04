# OMEGADRAKON — ROADMAP DE ABSORÇÃO LEGADA

> **Status:** Documento de Planejamento
> **Data:** 2026-09-02
> **Origem:** Análise consolidada de Nicky v0.7.0, NV Runtime v1.11.0, Nexus v1.9.2
> **Versão:** 1.0.0
> **Assinatura:** `OD // CORE`

---

## 1. Visão Geral

Este roadmap define a ordem de implementação das capacidades legadas no OmegaDrakon, priorizando por:
- **Dependências** — o que bloqueia o quê
- **Valor** — capacidade máxima entregue por esforço
- **Risco** — o que é perigoso se não for feito antes
- **Esforço** — quick wins vs projetos longos

### 1.1 Legado a Absorver

| Sistema | Capacidades | Prioridade Geral |
|---|---|---|
| **Nicky v0.7.0** | Config, Cache, History, RAG, Vision, Audio, TTS, Profiles, Notifier, Telegram, API | Alta |
| **NV Runtime v1.11.0** | Security, 56 Actions, Workflows, Coder, Memory, DB Layer, Plugins | Alta |
| **Nexus v1.9.2** | Perception, IoT, Self Repair, Auto Extension, Tool Loader, Auditor | Média-Baixa |

### 1.2 Já Implementado

| Componente | Arquivo | Testes |
|---|---|---|
| Event Bus | `core/event_bus.py` | 56 ✅ |
| State Manager | `core/state.py` | 68 ✅ |
| Message Router | `core/router.py` | 55 ✅ |
| Config Manager | `configs/manager.py` | 46 ✅ |
| Security Layer | `core/security/` | 95 ✅ |
| Logger | `core/logger.py` | 43 ✅ |
| **Conv. History** | `memory/history.py` | 37 ✅ |
| **Cache LLM** | `memory/cache.py` | 34 ✅ |
| **Quick Responses** | `memory/quick_responses.py` | 28 ✅ |
| **Vector Memory** | `memory/vector.py` | 36 ✅ |
| **Context Manager** | `memory/context.py` | 28 ✅ |
| **Workflow Engine** | `core/workflows.py` | 70 ✅ |
| **Tool Loader** | `tools/loader.py` | 39 ✅ |
| **Action Registry** | `tools/registry.py` | 33 ✅ |
| **Orchestrator Pipeline** | `core/orchestrator.py` | 29 ✅ |
| **Coder Engine** | `core/coder.py` | 59 ✅ |
| **Self Repair** | `core/self_repair.py` | 41 ✅ |
| **Perception Syncer** | `tools/telemetry.py` | 21 ✅ |
| **56 Actions** | `tools/actions/` | 31 ✅ |
| **Telegram Bot** | `integrations/telegram/` | 55 ✅ |
| **API REST** | `integrations/api/` | 46 ✅ |
| **ProactiveNotifier** | `integrations/notifier.py` | 42 ✅ |
| **IoT Manager** | `integrations/homeassistant/` | 45 ✅ |
| **MQTT Bridge** | `integrations/mqtt/` | 54 ✅ |
| **Presence Monitor** | `integrations/homeassistant/presence.py` | 26 ✅ |
| **LLM Provider** | `core/llm.py` | 17 ✅ |
| Agent Nicky | `agents/nicky_virthy/` | 10 ✅ |
| **Audit System** | `observability/audit.py` | 36 ✅ |
| **Metrics Collector** | `observability/metrics.py` | 24 ✅ |
| **Health Check** | `observability/health.py` | 17 ✅ |
| **Plugin System** | `plugins/` | 20 ✅ |
| **Database Layer** | `storage/database.py` | 24 ✅ |
| **Total** | **32 componentes** | **1359 testes** |

---

## 2. Fases de Implementação

### FASE 1 — Fundação (Sem dependências externas)
> *Executar primeiro. Desbloqueia todas as outras fases.*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 1.1 | **Config Manager** | Nicky `config/settings.py` | `configs/manager.py` | Baixo | Nenhuma |
| 1.2 | **Security Layer** | NV `core/security/` | `core/security/` | Médio | Config Manager |
| 1.3 | **Logger Padronizado** | NV `observability/logging/` | `core/logger.py` | Baixo | Config Manager |

**Justificativa:**
- Config Manager é a base para todos os outros componentes (portas, thresholds, secrets)
- Security Layer é obrigatório antes de qualquer execução de código externo (spec §7)
- Logger padronizado permite observabilidade desde o início

**Saída esperada:**
- `configs/manager.py` — configuração centralizada com YAML + env vars
- `core/security/policy.py` — pipeline de validação (policy → permission → scope → audit)
- `core/logger.py` — logging estruturado com protocolo NICKY

---

### FASE 2 — Memória (Persistência de dados)
> *Depende de: Fase 1 (Config Manager)*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 2.1 | **Conversation History** | Nicky `storage/conversation_history.py` | `memory/history.py` | Baixo | Config |
| 2.2 | **Cache LLM** | Nicky `storage/llm_cache.py` | `memory/cache.py` | Médio | Config |
| 2.3 | **Quick Responses** | Nicky `storage/quick_response_db.py` | `memory/quick_responses.py` | Baixo | Config |
| 2.4 | **Vector Memory (RAG)** | Nicky `core/vector_memory.py` | `memory/vector.py` | Alto | Config, ChromaDB |
| 2.5 | **Context Manager** | Nexus `src/context_manager.py` | `memory/context.py` | Médio | Config |

**Justificativa:**
- History + Cache são usados por todo pipeline de conversação
- Quick Responses dá respostas instantâneas sem LLM (performance)
- RAG habilita conhecimento persistente
- Context Manager previne estouro de tokens

**Saída esperada:**
- `memory/history.py` — histórico por usuário/perfil com ChatML format
- `memory/cache.py` — cache SHA-256 com deduplicação e métricas
- `memory/quick_responses.py` — respostas rápidas com alternância e analytics
- `memory/vector.py` — ChromaDB + sentence-transformers para RAG
- `memory/context.py` — truncamento inteligente de contexto

---

### FASE 3 — Orquestração (Fluxo de trabalho)
> *Depende de: Fase 1 (Security Layer), Fase 2 (Memory)*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 3.1 | **Workflow Engine** | NV `core/workflows/` | `core/workflows.py` | Alto | Security, Memory |
| 3.2 | **Tool Loader** | Nexus `src/tool_loader.py` | `tools/loader.py` | Médio | Config |
| 3.3 | **Action Registry** | NV `core/actions/` | `tools/registry.py` | Médio | Security, Loader |
| 3.4 | **Orchestrator Pipeline** | Nicky `core/orchestrator.py` | `core/orchestrator.py` | Alto | Todos acima |

**Justificativa:**
- Workflow Engine habilita pipelines complexos (branching, retries, timeouts)
- Tool Loader permite carregamento dinâmico de ferramentas
- Action Registry cataloga todas as 56 actions do NV
- Orchestrator integra tudo no pipeline de 8 etapas do Nicky

**Saída esperada:**
- `core/workflows.py` — engine com branching, nested, retries, timeouts, persistência
- `tools/loader.py` — carregamento dinâmico de plugins
- `tools/registry.py` — registro tipado de 56 actions
- `core/orchestrator.py` — pipeline 8 etapas: rate limit → datetime → AIML → cache → history → LLM → fallback → post-processing

---

### FASE 4 — Capacidades de Execução
> *Depende de: Fase 3 (Orquestração)*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 4.1 | **Coder Engine** | NV `core/coder.py` | `core/coder.py` | Alto | Security, Workflows |
| 4.2 | **Self Repair** | Nexus `src/self_repair.py` | `core/self_repair.py` | Médio | Coder, Perception |
| 4.3 | **Perception Syncer** | Nexus `src/perception.py` | `tools/telemetry.py` | Médio | Config |
| 4.4 | **56 Actions** | NV `core/actions/` | `tools/actions/` | Alto | Registry, Security |

**Justificativa:**
- Coder Engine permite modificação segura de código (sandbox → testes → promoção)
- Self Repair usa Coder para auto-correção
- Perception dá visibilidade do estado do hardware/serviços
- 56 Actions são a base de todas as operações

**Saída esperada:**
- `core/coder.py` — pipeline: sandbox → patch → validação → backup → promoção
- `core/self_repair.py` — detecção de falhas + geração de correção
- `tools/telemetry.py` — CPU, RAM, Docker, portas, rede
- `tools/actions/` — 56 actions organizadas por categoria (sistema, fs, git, docker, db)

---

### FASE 5 — Integrações Externas
> *Depende de: Fase 3 (Orquestração), Fase 4 (Actions)*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 5.1 | **Telegram Bot** | Nicky `interfaces/telegram_bot.py` | `integrations/telegram/` | Alto | Orchestrator, Memory |
| 5.2 | **API REST** | Nicky `interfaces/api.py` | `integrations/api/` | Médio | Orchestrator |
| 5.3 | **ProactiveNotifier** | Nicky `interfaces/notifier.py` | `integrations/notifier.py` | Baixo | Config |
| 5.4 | **IoT Manager** | Nexus `src/iot.py` | `integrations/homeassistant/` | Médio | Config, Actions |
| 5.5 | **MQTT Bridge** | Nexus Mosquitto | `integrations/mqtt/` | Médio | Config |

**Justificativa:**
- Telegram é a interface principal do usuário
- API REST expõe o sistema para clientes externos
- Notificador dá visibilidade proativa
- IoT/MQTT habilitam automação residencial

**Saída esperada:**
- `integrations/telegram/` — bot com 14 comandos, STT, TTS, perfis
- `integrations/api/` — FastAPI com 17 endpoints, WebSocket, métricas
- `integrations/notifier.py` — health check, alertas, anti-spam
- `integrations/homeassistant/` — REST + MQTT para controle de dispositivos
- `integrations/mqtt/` — bridge para broker Mosquitto

---

### FASE 6 — Sensorial e Inteligência
> *Depende de: Fase 4 (Perception), Fase 5 (Integrações)*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 6.1 | **Face Detection** | Nicky `vision/face_detector.py` | `tools/vision/face_detector.py` | Médio | Perception |
| 6.2 | **Presence Monitor** | Nicky `vision/presence_monitor.py` | `tools/vision/presence.py` | Médio | Face Detection, Event Bus |
| 6.3 | **Audio Capture (STT)** | Nicky `vision/audio_capture.py` | `tools/audio/stt.py` | Baixo | Config |
| 6.4 | **TTS (Piper)** | Nicky `interfaces/text_to_speech.py` | `tools/audio/tts.py` | Baixo | Config |
| 6.5 | **Profile Manager** | Nicky `profiles/profile_manager.py` | `agents/profiles.py` | Baixo | Config |
| 6.6 | **Auto Extension** | Nexus `src/nexus_core.py` | `tools/auto_extension/` | Alto | LLM, Security |

**Justificativa:**
- Vision dá presença sensorial ao sistema
- Audio/TTS habilitam interação por voz
- Profiles personalizam comportamento por contexto
- Auto Extension é capacidade avançada (geração de código via LLM)

**Saída esperada:**
- `tools/vision/face_detector.py` — Haar Cascade + CLAHE + buffer de confirmação
- `tools/vision/presence.py` — monitoramento 30s + Event Bus integration
- `tools/audio/stt.py` — whisper.cpp via subprocess
- `tools/audio/tts.py` — Piper TTS com vozes por perfil
- `agents/profiles.py` — 6 perfis com system prompts e detecção automática
- `tools/auto_extension/` — geração de ferramentas via LLM (mediada pelo Security Layer)

---

### FASE 7 — Infraestrutura e Observabilidade
> *Executar em paralelo com outras fases quando necessário*

| # | Capacidade | Origem | Destino | Esforço | Dependências |
|---|---|---|---|---|---|
| 7.1 | **Audit System** | Nexus `src/auditor.py` | `observability/audit.py` ✅ | Médio | Logger |
| 7.2 | **Metrics Collector** | Nicky `/metrics` | `observability/metrics.py` ✅ | Médio | Logger |
| 7.3 | **Health Check** | NV `observability/health/` | `observability/health.py` ✅ | Baixo | Config |
| 7.4 | **Plugin System** | NV `plugins/` | `plugins/` ✅ | Alto | Loader, Registry |
| 7.5 | **Database Layer** | NV `core/database/` | `storage/database.py` ✅ | Médio | Config |

**Justificativa:**
- Observabilidade é contínua (deve crescer com o sistema)
- Plugins habilitam extensibilidade dinâmica
- Database Layer dá persistência relacional

**Saída esperada:**
- `observability/audit.py` — trilhas de auditoria de segurança
- `observability/metrics.py` — métricas Prometheus
- `observability/health.py` — health checks de componentes
- `plugins/` — sistema de carregamento dinâmico
- `storage/database.py` — pool de conexões + repositórios

---

## 3. Mapa de Dependências

```
FASE 1 (Fundação)
  ├── 1.1 Config Manager ──────────────────────────┐
  ├── 1.2 Security Layer ←── Config                 │
  └── 1.3 Logger ←── Config                        │
                                                    │
FASE 2 (Memória) ←─────────────────────────────────┘
  ├── 2.1 Conversation History ←── Config
  ├── 2.2 Cache LLM ←── Config
  ├── 2.3 Quick Responses ←── Config
  ├── 2.4 Vector Memory (RAG) ←── Config
  └── 2.5 Context Manager ←── Config
                                                    │
FASE 3 (Orquestração) ←────────────────────────────┘
  ├── 3.1 Workflow Engine ←── Security, Memory
  ├── 3.2 Tool Loader ←── Config
  ├── 3.3 Action Registry ←── Security, Loader
  └── 3.4 Orchestrator Pipeline ←── Todos acima
                                    │
FASE 4 (Execução) ←────────────────┘
  ├── 4.1 Coder Engine ←── Security, Workflows
  ├── 4.2 Self Repair ←── Coder, Perception
  ├── 4.3 Perception Syncer ←── Config
  └── 4.4 56 Actions ←── Registry, Security
                          │
FASE 5 (Integrações) ←───┘
  ├── 5.1 Telegram Bot ←── Orchestrator, Memory
  ├── 5.2 API REST ←── Orchestrator
  ├── 5.3 ProactiveNotifier ←── Config
  ├── 5.4 IoT Manager ←── Config, Actions
  └── 5.5 MQTT Bridge ←── Config
                          │
FASE 6 (Sensorial) ←──────┘
  ├── 6.1 Face Detection ←── Perception
  ├── 6.2 Presence Monitor ←── Face Detection, Event Bus
  ├── 6.3 Audio STT ←── Config
  ├── 6.4 TTS Piper ←── Config
  ├── 6.5 Profile Manager ←── Config
  └── 6.6 Auto Extension ←── LLM, Security

FASE 7 (Infraestrutura) ←── paralela
  ├── 7.1 Audit System ←── Logger
  ├── 7.2 Metrics Collector ←── Logger
  ├── 7.3 Health Check ←── Config
  ├── 7.4 Plugin System ←── Loader, Registry
  └── 7.5 Database Layer ←── Config
```

---

## 4. Estimativas de Esforço

| Fase | Capacidades | Esforço Total | Testes Estimados | Prazo Estimado |
|---|---|---|---|---|
| **Fase 1** | 3 | Baixo-Médio | 40-60 | 1-2 dias |
| **Fase 2** | 5 | Médio | 80-100 | 2-3 dias |
| **Fase 3** | 4 | Alto | 60-80 | 3-4 dias |
| **Fase 4** | 4 | Alto | 50-70 | 3-4 dias |
| **Fase 5** | 5 | Alto | 40-60 | 3-4 dias |
| **Fase 6** | 6 | Médio-Alto | 30-50 | 2-3 dias |
| **Fase 7** | 5 | Médio | 30-40 | 2-3 dias |
| **Total** | **32** | — | **330-460** | **15-20 dias** |

---

## 5. Capacidades por Sistema de Origem

### 5.1 Nicky → OmegaDrakon (16 capacidades)

| Capacidade | Destino | Fase | Prioridade |
|---|---|---|---|
| Config Manager | `configs/manager.py` | 1 | 🔴 Crítica |
| Logger | `core/logger.py` | 1 | 🔴 Crítica |
| Conversation History | `memory/history.py` | 2 | 🟠 Alta |
| Cache LLM | `memory/cache.py` | 2 | 🟠 Alta |
| Quick Responses | `memory/quick_responses.py` | 2 | 🟡 Média |
| Vector Memory (RAG) | `memory/vector.py` | 2 | 🟡 Média |
| Orchestrator Pipeline | `core/orchestrator.py` | 3 | 🟠 Alta |
| Coder Engine | `core/coder.py` | 4 | 🟡 Média |
| Telegram Bot | `integrations/telegram/` | 5 | 🟠 Alta |
| API REST | `integrations/api/` | 5 | 🟠 Alta |
| ProactiveNotifier | `integrations/notifier.py` | 5 | 🟡 Média |
| Face Detection | `tools/vision/face_detector.py` | 6 | 🟢 Baixa |
| Presence Monitor | `tools/vision/presence.py` | 6 | 🟢 Baixa |
| Audio STT | `tools/audio/stt.py` | 6 | 🟡 Média |
| TTS Piper | `tools/audio/tts.py` | 6 | 🟡 Média |
| Profile Manager | `agents/profiles.py` | 6 | 🟡 Média |

### 5.2 NV Runtime → OmegaDrakon (10 capacidades)

| Capacidade | Destino | Fase | Prioridade |
|---|---|---|---|
| Security Layer | `core/security/` | 1 | 🔴 Crítica |
| Workflow Engine | `core/workflows.py` | 3 | 🟠 Alta |
| Action Registry | `tools/registry.py` | 3 | 🟠 Alta |
| 56 Actions | `tools/actions/` | 4 | 🟠 Alta |
| Coder Engine | `core/coder.py` | 4 | 🟡 Média |
| Memory Layer | `memory/` | 2 | 🟠 Alta |
| Database Layer | `storage/database.py` | 7 | 🟡 Média |
| Plugin System | `plugins/` | 7 | 🟢 Baixa |
| API Layer | `integrations/api/` | 5 | 🟠 Alta |
| Observability | `observability/` | 7 | 🟡 Média |

### 5.3 Nexus → OmegaDrakon (10 capacidades)

| Capacidade | Destino | Fase | Prioridade |
|---|---|---|---|
| Perception Syncer | `tools/telemetry.py` | 4 | 🟡 Média |
| IoT Manager | `integrations/homeassistant/` | 5 | 🟡 Média |
| Context Manager | `memory/context.py` | 2 | 🟠 Alta |
| Self Repair | `core/self_repair.py` | 4 | 🟢 Baixa |
| Auto Extension | `tools/auto_extension/` | 6 | 🟢 Baixa |
| Vox Messenger | `integrations/telegram/` | 5 | 🟡 Média |
| Tool Loader | `tools/loader.py` | 3 | 🟠 Alta |
| Auditor | `observability/audit.py` | 7 | 🟡 Média |
| Brain (LLM) | `core/llm.py` | 3 | 🟠 Alta |
| MQTT Bridge | `integrations/mqtt/` | 5 | 🟡 Média |

---

## 6. Capacidades Não Absorvidas (Descartadas)

| Capacidade | Sistema | Motivo da Exclusão |
|---|---|---|
| App Flutter | Nicky | Não alinhado com arquitetura (PWA é suficiente) |
| PWA Service Worker | Nicky | Mantido no Nicky legado, não迁移 |
| Gemini como fallback | Nicky | OmegaDrakon usa LLM local como primário |
| OpenAI/Anthropic/Ollama clients | Nicky | Múltiplos providers não são prioridade |
| Dashboard Chart.js | Nicky | Dashboard legado, não迁移 |
| Haar Cascade (OpenCV) | Nicky | Pode ser substituído por modelo mais moderno |
| MariaDB (3 pools) | Nicky | OmegaDrakon usa SQLite/JSON initially |
| Docker SDK | Nexus | Ações Docker via shell são suficientes |
| Nmap scanning | Nexus | Ferramenta de nicho, pode ser via action |
| Gemini auto-extension | Nexus | Capacidade perigosa sem Security Layer robusto |

---

## 7. Critérios de Aceite por Fase

### Fase 1 — Fundação ✅ (2026-09-03)
- [x] Config Manager lê YAML + env vars, suporta defaults
- [x] Security Layer valida actions via pipeline (policy → permission → scope → audit)
- [x] Logger produz logs estruturados com protocolo NICKY
- [x] Todos os componentes têm testes unitários (363 testes na suíte)
- [x] Zero dependências externas (apenas stdlib + pydantic/yaml opcionais)

### Fase 2 — Memória ✅ (2026-09-03)
- [x] History persiste por usuário/perfil, formato ChatML (`memory/history.py`, 37 testes)
- [x] Cache usa SHA-256 com normalização e deduplicação (`memory/cache.py`, 34 testes)
- [x] Quick Responses suporta alternância e analytics (`memory/quick_responses.py`, 28 testes)
- [x] Vector Memory com thread safety e provider plugável (`memory/vector.py`, 36 testes) — *ChromaDB substituído por HashEmbeddingProvider stdlib; interface adaptável (EmbeddingProvider protocol)*
- [x] Context Manager previne estouro de tokens (`memory/context.py`, 28 testes)

### Fase 3 — Orquestração ✅ (concluída — 2026-09-03)
- [x] Workflow Engine suporta branching, nested, retries, timeouts (`core/workflows.py`, 70 testes) — 2026-09-03
- [x] Tool Loader carrega plugins dinamicamente (`tools/loader.py`, 39 testes) — 2026-09-03
- [x] Action Registry registra actions tipadas com execução validada pelo Security Layer (`tools/registry.py`, 33 testes) — 2026-09-03
- [x] Orchestrator executa pipeline de 8 etapas com fallbacks (`core/orchestrator.py`, 29 testes) — 2026-09-03

### Fase 4 — Execução ✅ CONCLUÍDA (2026-09-03)
- [x] Coder Engine executa sandbox → testes → backup → promoção (`core/coder.py`, 59 testes) — 2026-09-03
- [x] Self Repair detecta falhas e gera correções mediadas pelo Coder Engine (`core/self_repair.py`, 41 testes) — 2026-09-03
- [x] Perception coleta telemetria de hardware/serviços (`tools/telemetry.py`, 21 testes) — 2026-09-03
- [x] 56 Actions executam com validação de Security Layer (`tools/actions/`, 31 testes) — 2026-09-03
- [ ] Self Repair detecta falhas e gera correções
- [ ] Perception coleta telemetria de hardware/serviços
- [ ] 56 Actions executam com validação de Security Layer

### Fase 5 — Integrações ✅ CONCLUÍDA (2026-09-03)
- [x] Telegram Bot suporta 14 comandos, STT, TTS, perfis
- [x] API REST expõe 17 endpoints com auth
- [x] Notificador envia alertas proativos com anti-spam
- [x] IoT Manager controla dispositivos via Home Assistant
- [x] MQTT Bridge publica/assina tópicos

### Fase 6 — Sensorial ✅ CONCLUÍDA (2026-09-03)
- [x] Face Detection usa CLAHE + buffer de confirmação
- [x] Presence Monitor publica eventos no Event Bus
- [x] STT transcreve áudio via whisper.cpp
- [x] TTS sintetiza voz via Piper com vozes por perfil
- [x] Profile Manager detecta perfil automaticamente
- [x] Auto Extension gera ferramentas mediada pelo Security Layer

### Fase 7 — Infraestrutura ✅ CONCLUÍDA (2026-09-04)
- [x] Audit System registra todas as decisões de segurança (v0.22.0)
- [x] Metrics Collector expõe Prometheus metrics (v0.23.0)
- [x] Health Check verifica status de componentes (v0.24.0)
- [x] Plugin System carrega e registra plugins (v0.25.0)
- [x] Database Layer gerencia conexões e repositórios (v0.26.0)

---

## 8. Riscos e Mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| **Complexidade do Security Layer** | Alto | Implementar em camadas; compatibility mode primeiro |
| **Acoplamento entre fases** | Alto | Interfaces claras; testes de contrato |
| **Dívida técnica legada** | Médio | Nunca copiar código; sempre reescrever nos padrões OD |
| **Dependências externas** | Médio | Preferir stdlib; isolar em adapters |
| **Testes insuficientes** | Alto | Meta >90% coverage; CI obrigatório |
| **Escopo creep** | Médio | Seguir roadmap; não implementar fora de fase |

---

## 9. Próximos Passos Imediatos

✅ Concluído: Config Manager, Security Layer, Logger, testes da Fase 1, CHANGELOG.

✅ Concluído: Fase 2 completa (5 capacidades, 163 testes novos, total 526).

✅ Concluído: Fase 3 item 3.1 — Workflow Engine (`core/workflows.py`, 70 testes novos, total 596).

✅ Concluído: Fase 3 item 3.2 — Tool Loader (`tools/loader.py`, 39 testes novos, total 635).

✅ Concluído: Fase 3 item 3.3 — Action Registry (`tools/registry.py`, 33 testes novos, total 668).

✅ Concluído: v0.6.1 — Logger unificado: `_audit_nicky` duplicado substituído por
`core/logger.make_audit_nicky()` em event_bus, router, state, security/* e
memory/* (~155 linhas de boilerplate removidas; suíte mantida em 668 testes).

✅ Concluído: **Fase 3 COMPLETA** — item 3.4 Orchestrator Pipeline
(`core/orchestrator.py`, 29 testes novos, total **697**). Fase 3 encerrada com
4/4 itens (Workflow Engine, Tool Loader, Action Registry, Orchestrator).

✅ Concluído: **Fase 4, item 4.1 — Coder Engine** (`core/coder.py`, 59 testes
novos, total **756**). Pipeline sandbox → testes → backup → promoção com
patches unificados nativos (stdlib), escopo estrito §7.1, gate Security Layer
na promoção e eventos coder.started/coder.completed. Fase 4 iniciada (1/4).

✅ Concluído: **Fase 4, item 4.2 — Self Repair** (`core/self_repair.py`, 41
testes novos, total **797**). Ciclo detectar → gerar → reparar → verificar →
(rollback) com correções SEMPRE mediadas pelo Coder Engine (4.1): detecção
por compile/import probe/oracle `check`, estratégias determinísticas
(header sem ":") + providers plugáveis (futura auto-extensão), verificação
pós-promoção e rollback automático via snapshot pré-reparo. Fase 4 com 2/4.

✅ Concluído: **Fase 4, item 4.3 — Perception Syncer** (`tools/telemetry.py`,
21 testes novos, total **818**). Telemetria stdlib de CPU (delta + load),
memória, disco, rede, portas TCP, Docker (socket unix) e processos;
snapshot resiliente com seções independentes e erros parciais; proc_root
injetável. Fase 4 com 3/4 itens.

✅ Concluído: **Fase 4 COMPLETA** — item 4.4 Catálogo de 56 Actions
(`tools/actions/`, 31 testes novos, total **849**). 54 ações do legado NV
(sistema, processos, docker, serviços, arquivos, git, db, introspecção)
+ 2 complementares (process_tree, action_list), todas com permission própria
(gate Security Layer na execução) e degradação graciosa sem infra externa.
Fase 4 encerrada com 4/4 itens (Coder, Self Repair, Perception, Actions).

✅ Concluído: **Fase 5, item 5.1 — Telegram Bot** (`integrations/telegram/`,
55 testes novos, total **904**). Bot sobre o Orchestrator com os 13 comandos
de texto do legado + voz/STT (14º recurso): transportes plugáveis
(InMemoryTransport sem rede / HTTPTransport Bot API via urllib), admin gate,
perfis por chat, STT plugável, polling com offset persistente e métricas.
Fase 5 iniciada (1/5 itens).

✅ Concluído: **Fase 5, item 5.2 — API REST** (`integrations/api/`, 46
 testes novos, total **950**). Os 17 endpoints do legado Nicky em http.server
stdlib (sem FastAPI): /health, /profiles, /presence/today, /dashboard,
/chat, /metrics, /dashboard/stats, /llms, POST /message (pipeline), transcribe/tts (handlers plugáveis),
/history/{uid} e stats, RAG via
VectorStore, ws/chat 501 registrado — API key X-API-Key + rate limit por IP
+ CORS. Fase 5 com 2/5 itens.

✅ Concluído: **Fase 5, item 5.3 — ProactiveNotifier**
(`integrations/notifier.py`, 42 testes novos, total **992**). Notificações
proativas do legado em stdlib: sondas embutidas (orchestrator, LLM offline
com threshold de 300s, disco ≥85% warn/≥95% crit, restart por PID
persistido), anti-spam com cooldown por chave (padrão 1/hora, persistido em
state_file), sinks plugáveis sync/async, Event Bus (notifier.alert), loop
run/start/stop, health(), métricas e relógio injetável. Fase 5 com 3/5.

✅ Concluído: **Fase 5, item 5.4 — IoT Manager**
(`integrations/homeassistant/`, 45 testes novos, total **1037**). Integração
Home Assistant em stdlib: taxonomia ambiental do legado Nexus (atuadores/
móveis/sensores/infra por domínio), EntityState/HACredentials (arquivo JSON,
segregios fora do código), HAClient REST com Bearer token + InMemoryHAServer
fake (mesma interface), e IoTManager com controle set_power/toggle, gate de
segurança (allowed_domains + guard), eventos iot.command e métricas.
Fase 5 com 4/5 itens.

✅ Concluído: **v0.16.0 — ATIVAÇÃO REAL** (`core/llm.py` + `runtime/` +
27 testes novos, total **1064**). O sistema saiu do código e foi colocado
no ar de verdade no servidor: **LLM local gemma-4-E4B** rodando via llama.cpp
(b10786, OpenAI-compat em 127.0.0.1:8081) com o `OpenAICompatProvider`
conectando o Orchestrator a ele; **identidade da Nicky injetada**
(`agents/nicky_virthy/personality.py` + `OrchestratorConfig.
default_system_prompt`); **launcher real** (`runtime/launcher.py`: API 8000 +
Telegram Bot em polling com o token legado @Nicky_Virthy_bot); **Home
Assistant migrado** de dentro do nexus para `/srv/omegadrakon/homeassistant`
(container recriado, OD autossuficiente) com o IoTManager validado contra
**29 entidades reais**; segredos protegidos no `.gitignore`; **units systemd
de usuário `od-llm`/`od-core` instaladas, habilitadas e ativas** (auto-start
no boot). Capacidades do roadmap: 24/32 (ativação não adiciona item).

✅ Concluído: **Fase 5 COMPLETA** — item 5.5 MQTT Bridge
(`integrations/mqtt/`, 54 testes novos, total **1118**). Ponte MQTT 3.1.1
em **stdlib puro** (sem paho-mqtt): codec do protocolo wire (CONNECT/
CONNACK, PUBLISH QoS 0/1 com PUBACK, SUBSCRIBE/SUBACK, retained,
validação de tópicos e curingas +/#), `MQTTClient` real sobre socket com
reader/keepalive, `InMemoryBroker` fake em processo (testes determinísticos
sem broker externo) e `MQTTBridge` sobre o Event Bus: mensagens recebidas
→ `mqtt.message`, handlers por filtro, roteamento bus→MQTT (`od/<tópico>`),
reconexão com re-assinatura, métricas. **Fase 5 encerrada com 5/5 itens**
(Telegram, API REST, Notifier, IoT Manager, MQTT Bridge) — 25/32
capacidades. Validado ao vivo contra o **Mosquitto real** (127.0.0.1:1883)
e integrado ao launcher/od-core (subscrição `od/in/#`).

✅ Concluído: **Fase 6, item 6.2 — Presence Monitor**
(`integrations/homeassistant/presence.py`, 26 testes novos, total **1151**).
Monitor de presença sobre o Home Assistant (em vez de câmera — decisão
registrada): lê person.*/device_tracker.* periodicamente, classifica
home/away (unknown conta como away), detecta transições de chegada/saída,
publica **Event Bus** (`presence.changed`), notifica sinks plugáveis
(Telegram do admin no launcher), baseline silencioso + estado persistido
(reinícios não disparam eventos falsos), métricas e introspecção. Rodando
no od-core contra o HA real (34 entidades lidas). Fase 6 com 1/6 itens —
**26/32** capacidades.

✅ Concluído: **Fase 6 COMPLETA** — itens 6.1 (Face Detection), 6.3 (STT),
6.4 (TTS), 6.5 (Profile Manager) e 6.6 (Auto Extension) — 75 testes novos,
total **1229**. **6.1** `tools/vision/face_detector.py` — Haar Cascade +
CLAHE + ROI guard + buffer de confirmação 3/2 (espelho do legado Nicky),
validado ao vivo contra a **webcam real do servidor** (/dev/video0, Alcor
Micro 1080P); OpenCV 4.x fixado (o 5.0 removeu o CascadeClassifier).
**6.3** `tools/audio/stt.py` — whisper.cpp via subprocess + ffmpeg,
**6.4** `tools/audio/tts.py` — Piper com vozes por perfil (dii feminina /
faber masculina), ambos **validados E2E reais** (Piper sintetizou →
whisper transcreveu de volta em 3.2s). **6.5** `agents/profiles.py` — os 6
perfis oficiais (guardian/regulus/luma/vox/athenae/nyx) com detecção
automática por domínio (tokenização + radical), plugada no bot (perfil
"auto" agora detecta pelo texto). **6.6** `tools/auto_extension/` —
geração de ferramentas via LLM com validação (compile + allowlist de
imports stdlib) e registro no Action Registry com permission mediada pelo
Security Layer. Launcher ganhou o modo `vision` (OD_VISION_ENABLED).
**Fase 6 encerrada com 6/6 itens — 32/32 capacidades do roadmap.**

✅ Concluído: **Fase 7, item 7.1 — Audit System** (`observability/audit.py`,
36 testes novos, total **1272**). Trilha de auditoria contínua e PERSISTENTE
(spec §7.3): `AuditEntry` tipado, persistência JSONL append-only com rotação
por tamanho + retenção e recarga no startup, `record_decision()` +
`make_sink()` registrando TODA decisão de segurança do AuditEngine do
Security Layer, Event Bus (`audit.record`), consultas (history/search/since/
by_action/counts), métricas, `health()`, sink resiliente (nunca quebra a
trilha) e launcher com `OD_AUDIT_FILE` (evento system.startup). Fase 7
iniciada (1/5 itens) — **33/37** capacidades do roadmap.

✅ Concluído: **Fase 7, item 7.2 — Metrics Collector** (`observability/metrics.py`,
24 testes novos, total **1298**). Coletor central de métricas em stdlib com
exposição no Prometheus text format: `Metric` counter/gauge com labels e
validação rígida, `MetricsCollector` com registro idempotente por nome,
**fontes vivas** (uptime, Orchestrator, Audit contribuem linhas no render;
fonte quebrada nunca derruba), `render()`/`snapshot()`/`health()`/`dump()`
thread-safe. **API REST integrada** (`APIConfig.metrics`): /metrics renderiza
o coletor com `od_api_requests_total`/`od_api_errors_total`; sem coletor,
comportamento legado preservado. Launcher com `build_metrics()` em todos os
modos. Suíte **1298 passed, 0 falhas** — primeira 100% verde (falha
ambiental pré-existente do ConfigManager corrigida). Fase 7 com 2/5 —
**34/37** capacidades.

✅ Concluído: **Fase 7, item 7.3 — Health Check** (`observability/health.py`,
17 testes novos, total **1315**). Verificação de status dos componentes em
stdlib: `ComponentHealth` tipado, `HealthMonitor` com checks registráveis
(sync/async), severidade por check (crítico → down, não-crítico → degraded),
latência por check, métricas, snapshot/dump e resiliência (check quebrado
nunca derruba). **API REST integrada** (`APIConfig.health`): /health responde
o agregado do monitor com uptime_s; sem monitor, legado preservado. Launcher
com `build_health()` (orchestrator/llm críticos + audit/metrics
não-críticos). Suíte **1315 passed, 0 falhas**. Fase 7 com 3/5 —
**35/37** capacidades.

✅ Concluído: **Fase 7, item 7.4 — Plugin System** (`plugins/manager.py`,
20 testes novos, total **1335**). Carregamento dinâmico de plugins com 3
contratos (PLUGIN dict, ACTIONS/WORKFLOWS, register_actions/
register_workflows), registro de actions no ActionRegistry com
permission `plugin.<nome>` e workflows no WorkflowEngine, descoberta em
subdiretórios (actions/providers/workflows/integrations), hot-reload
(reload/unload/reload_all desregistram antes de recarregar), escopo
estrito §7.1 (PluginScopeError), isolamento de falha por módulo, Event
Bus best-effort e métricas. Launcher com `build_plugins()`. Suíte
**1335 passed, 0 falhas**. Fase 7 com 4/5 — **36/37** capacidades.

✅ Concluído: **Fase 7, item 7.5 — Database Layer** (`storage/database.py`,
24 testes novos, total **1359**). Camada de persistência relacional em SQLite
stdlib: `ConnectionPool` thread-safe por fila (com `:memory:` compartilhado
por pool via URI única), `Database` com execute/executemany/query/scalar,
**transações com afinidade de conexão por thread** (rollback total em erro),
`create_table`/`tables`/`table_info`, métricas, health/dump, e `Repository`
CRUD genérico (insert/get/update/delete/all/find/count/exists) com schema
declarativo. Catálogo de actions plugado (`configure_database` — as 3
actions de banco passam a funcionar) e launcher com `build_database()` +
check `database` no Health Monitor. **FASE 7 FECHADA (5/5)** — **37/37
capacidades do roadmap.**

---

## 10. Métricas de Progressão

| Métrica | Atual | Meta Final |
|---|---|---|
| Capacidades implementadas | 37/37 | 37/37 |
| Testes totais | 1359 | ~1400 |
| Módulos core | 10 | ~15 |
| Ferramentas (tools) | 7 | ~20 |
| Módulos memory | 5 | 5 |
| Integrações | 5 | ~8 |
| Actions | 56 | 56 |
| Cobertura de código | — | >90% |

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/ROADMAP_ABSORCAO.md
Descrição: Roadmap priorizado de absorção de capacidades legadas.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
