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
| Agent Nicky | `agents/nicky_virthy/` | — ✅ |
| **Total** | **4 componentes** | **179 testes** |

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
| 7.1 | **Audit System** | Nexus `src/auditor.py` | `observability/audit.py` | Médio | Logger |
| 7.2 | **Metrics Collector** | Nicky `/metrics` | `observability/metrics.py` | Médio | Logger |
| 7.3 | **Health Check** | NV `observability/health/` | `observability/health.py` | Baixo | Config |
| 7.4 | **Plugin System** | NV `plugins/` | `plugins/` | Alto | Loader, Registry |
| 7.5 | **Database Layer** | NV `core/database/` | `storage/database.py` | Médio | Config |

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

### Fase 1 — Fundação
- [ ] Config Manager lê YAML + env vars, suporta defaults
- [ ] Security Layer valida actions via pipeline (policy → permission → scope → audit)
- [ ] Logger produz logs estruturados com protocolo NICKY
- [ ] Todos os componentes têm testes unitários (>90% coverage)
- [ ] Zero dependências externas (apenas stdlib + pydantic)

### Fase 2 — Memória
- [ ] History persiste por usuário/perfil, formato ChatML
- [ ] Cache usa SHA-256 com normalização e deduplicação
- [ ] Quick Responses suporta alternância e analytics
- [ ] Vector Memory integra ChromaDB com thread safety
- [ ] Context Manager previne estouro de tokens

### Fase 3 — Orquestração
- [ ] Workflow Engine suporta branching, nested, retries, timeouts
- [ ] Tool Loader carrega plugins dinamicamente
- [ ] Action Registry registra 56 actions tipadas
- [ ] Orchestrator executa pipeline de 8 etapas com fallbacks

### Fase 4 — Execução
- [ ] Coder Engine executa sandbox → testes → backup → promoção
- [ ] Self Repair detecta falhas e gera correções
- [ ] Perception coleta telemetria de hardware/serviços
- [ ] 56 Actions executam com validação de Security Layer

### Fase 5 — Integrações
- [ ] Telegram Bot suporta 14 comandos, STT, TTS, perfis
- [ ] API REST expõe 17 endpoints com auth
- [ ] Notificador envia alertas proativos com anti-spam
- [ ] IoT Manager controla dispositivos via Home Assistant
- [ ] MQTT Bridge publica/assina tópicos

### Fase 6 — Sensorial
- [ ] Face Detection usa CLAHE + buffer de confirmação
- [ ] Presence Monitor publica eventos no Event Bus
- [ ] STT transcreve áudio via whisper.cpp
- [ ] TTS sintetiza voz via Piper com vozes por perfil
- [ ] Profile Manager detecta perfil automaticamente
- [ ] Auto Extension gera ferramentas mediada pelo Security Layer

### Fase 7 — Infraestrutura
- [ ] Audit System registra todas as decisões de segurança
- [ ] Metrics Collector expõe Prometheus metrics
- [ ] Health Check verifica status de componentes
- [ ] Plugin System carrega e registra plugins
- [ ] Database Layer gerencia conexões e repositórios

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

1. **Implementar Config Manager** (`configs/manager.py`) — desbloqueia Fase 1
2. **Implementar Security Layer** (`core/security/`) — obrigatório antes de qualquer execução
3. **Implementar Logger** (`core/logger.py`) — observabilidade desde o início
4. **Criar testes para Fase 1** — garantir base sólida
5. **Atualizar CHANGELOG.md** — registrar início da Fase 1

---

## 10. Métricas de Progressão

| Métrica | Atual | Meta Final |
|---|---|---|
| Capacidades implementadas | 4/32 | 32/32 |
| Testes totais | 179 | ~600 |
| Módulos core | 3 | ~15 |
| Integrações | 0 | ~8 |
| Actions | 0 | 56 |
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
