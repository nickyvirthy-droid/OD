# OMEGA DRAKON — README DE VERSÃO

> **Finalidade:** persistir o relatório do protocolo §2.1 (REGRAS_DE_TRABALHO.md)
> de **cada versão/fase entregue** — para que nenhum trabalho, decisão ou
> pendência se perca, mesmo entre sessões.
> **Regra:** a versão mais recente fica no topo. Toda fase concluída adiciona
> uma seção aqui ANTES de ser publicada no GitHub.
> **Assinatura:** `OD // CORE`

---

## [0.27.5] — Fast Path de Intenções + Action de Rede ⚡ (2026-09-04)

### 1. O que foi feito

Resposta às três perguntas: (1) o OD sabe quantas pessoas estão na rede?
→ **agora sabe**; (2) perguntas simples demorando → **fast path sem LLM**;
(3) MariaDB → **não, é SQLite** (ver §3).

| Entrega | Detalhe |
|---|---|
| **Action `network_hosts`** | Lê `/proc/net/arp` (stdlib, sem rede ativa): IP + MAC + interface + estado de cada vizinho. Catálogo 56 → **57** (complementar OD). Nível 0 (público) no `/executa` |
| **Fast path (`core/intents.py`)** | Etapa 3.5 do pipeline (antes do cache/LLM): "quantas pessoas/dispositivos na rede?" → `network_hosts`; processos/memória/CPU/disco/uptime/sistema → actions de leitura; **matemática segura** (ast, nós numéricos apenas — "quanto é 2+2*3?" → 8). Allowlist só de LEITURA; falha/negação cai para o LLM (nunca responde vazio) |
| **Rota/métrica novas** | `action_intent` no Orchestrator + métrica `intents` + config `enable_action_intents` (default True) |
| **Quick Responses ampliadas** | Novos padrões (quem é você, o que é você, seu nome, quem te criou, você está aí, tudo bem, teste) + lookup ignora pontuação final ("Quem é você?" casa na etapa 3) |

### 2. Evidência

```
pytest tests/ -q         → 1453 passed, 0 falhas  (1413 + 40 novos)
Smoke ao vivo            → "quantas pessoas estão conectadas na rede?"
                           → action_intent · 1.4ms · 6 dispositivos REAIS
                           (192.168.0.x via ARP, com MAC/interface)
                           "quanto é 2+2*3?" → 0.11ms
                           "me escreva um poema" → LLM (fallback correto)
Manifesto                → actions: 57 · OD_VERSION 0.27.5
```

### 3. MariaDB — resposta honesta

**Não.** O OD usa **SQLite** (`storage/database.py`, Fase 7.5 — decisão
registrada "preferir stdlib; isolar em adapters"). O MariaDB aparece no
servidor apenas como **legado parado** (do NV/nexus, citado no CHANGELOG
v0.16.0) — nunca foi ativado no OD. A camada é isolada em adapters, então
migrar para MariaDB/Postgres é possível se você quiser — mas é trabalho
decisão de arquitetura (ver próximo passo).

### 4. O que NÃO foi feito

- Fast path cobre um conjunto determinístico de intenções — perguntas
  operacionais fora da lista seguem para o LLM (por design)
- `network_hosts` mostra vizinhos da tabela ARP (quem trafegou/foi
  consultado recentemente) — não é um scan ativo da sub-rede (decisão de
  segurança; scan ativo exigiria sonda por host)
- Migração para MariaDB/Postgres não iniciada

### 5. Próximo passo

- Publicação: commit v0.27.5 + push (regra §2.1.2)
- **Decisão sua:** quer migrar a Database Layer para **MariaDB** (o
  servidor já tem o serviço parado) ou manter SQLite? Se sim, é uma
  entrega própria (adapter + testes + migração do `data/od.db`)

---

## [0.27.4] — LOOP DE AUTO-RECUPERAÇÃO FECHADO 🔄 (2026-09-04)

### 1. O que foi feito

**O ciclo perceber → decidir → agir → verificar agora roda no runtime.** Os 4
motores que o manifesto [0.27.3] apontava como dormentes foram ativados:

| Componente | Antes | Agora (v0.27.4) |
|---|---|---|
| **Self Repair** (4.2) | ⚪ dormente | 🟢 **RecoveryLoop** roda em ciclo (default 300s, `OD_RECOVERY_INTERVAL_S`): varre os `.py` do projeto, detecta falhas (compile determinístico) e repara mediado pelo Coder Engine (sandbox→testes→backup→promoção, rollback automático) |
| **Perception** (4.3) | ⚪ dormente | 🟢 `Telemetry.collect()` periódica → check `perception` no Health Monitor (não-crítico) + evento `perception.snapshot` no audit |
| **Auto Extension** (6.6) | ⚪ dormente | 🟢 trigger exposto: comando `/gerar <nome> <descrição>` (admin) — gera via LLM, valida e registra com permission `auto_extension.generated` (gate do Security Layer) |
| **ProactiveNotifier** (5.3) | ⚪ dormente | 🟢 iniciado no launcher (modo `all`) com sink Telegram + estado persistido em `data/notifier_state.json` (`OD_NOTIFIER_ENABLED=0` desliga) |
| **Ciclo** | — | 🟢 `core/recovery.py` novo — `RecoveryLoop` com métricas, `recovery.tick` no Event Bus e modo `recovery` no launcher (`OD_SELF_REPAIR_ENABLED=0` desliga) |

**Bug corrigido de quebra:** `/executa` respondia `RuntimeError:
asyncio.run()` em runtime (handler usava `asyncio.run()` dentro do loop do
bot desde a v0.27.0, sem teste via bot). `_run_command` agora aguarda
coroutines e os handlers `/executa` e `/gerar` são async puros.

**Manifesto:** `core/capabilities.py` — `loop_fechado` agora **true**, zero
dormentes, componentes do loop marcados `active`, `OD_VERSION` → 0.27.4.

### 2. Evidência

```
pytest tests/ -q         → 1413 passed, 0 falhas  (1393 + 20)
                           (12 de test_recovery + 8 de /executa e /gerar
                           via bot em test_telegram)
CLI capabilities          → loop_fechado: true · dormant: []
python -m runtime.launcher recovery   → ciclo periódico ativo
```

### 3. O que NÃO foi feito

- Correções de código gerado por LLM (auto-reparo LLM assistido) — o
  RecoveryLoop aplica **apenas estratégias determinísticas** (ex:
  AddMissingColon) mediadas pelo Coder; providers LLM seguem como ponto de
  extensão (decisão conservadora por construção)
- `/codigo` no bot segue somente leitura (status/arvore) — patch completo
  via bot segue pendente
- Control Bridge segue sem cliente interno no OD

### 4. Próximo passo

- Reiniciar o `od-core` (systemd) para o loop subir em produção e observar
  o journal (RecoveryLoop + ProactiveNotifier ativos)
- Publicação: commit v0.27.4 + push (regra §2.1.2)

---

## [0.27.3] — Manifesto de Capacidades 📋 (2026-09-04)

### 1. O que foi feito

O sistema passou a reportar **todas as suas capacidades** — resposta direta
à pergunta "o que o OD consegue fazer?" (e, de quebra, ao objetivo de
auto-recuperação e análise do ambiente):

| Canal | Entrega |
|---|---|
| **Módulo** | `core/capabilities.py` — manifesto com **39 componentes** (core/memória/orquestração/execução/integrações/sensorial/observabilidade/runtime), cada um com status de ativação no runtime (`active`/`available`/`partial`/`dormant`), origem legada, fase do roadmap e caminho |
| **CLI** | `.venv/bin/python -m runtime.launcher capabilities` → manifesto JSON |
| **API** | `GET /capabilities` (X-API-Key) — 18ª rota |
| **Bot** | `/capacidades` (admin) no Telegram |
| **Documento** | `docs/CAPACIDADES.md` — visão humana do manifesto |

O manifesto declara explicitamente `auto_recovery.loop_fechado: false` e
lista os 4 componentes dormentes (self-repair, auto-extension, perception,
notifier) com o caminho de ativação. Também corrigiu a versão fixa do
`GET /` (`/info`) que reportava "0.19.0" → `OD_VERSION` (0.27.3).

### 2. Evidência

```
pytest tests/ -q        → 1393 passed, 0 falhas  (1382 + 11 novos)
python -m runtime.launcher capabilities
                        → JSON: 39 capacidades · 56 actions ·
                          by_status {active: 28, available: 5, partial: 2,
                          dormant: 4} · loop_fechado: false
```

### 3. O que NÃO foi feito

- **Loop de auto-recuperação segue dormente**: self-repair, auto-extension,
  perception e notifier estão implementados e testados, mas sem trigger no
  runtime (o manifesto reporta isso por construção)
- `/codigo` continua só leitura (status/arvore) — patch completo do Coder
  Engine via bot segue pendente
- Control Bridge ativa como serviço, mas sem cliente interno no OD ainda

### 4. Próximo passo

- **Fechar o loop de auto-recuperação (P2)**: coletar `Telemetry.collect()`
  periódica → alimentar Health Monitor e oracles do Self Repair; iniciar o
  `SelfRepairEngine` com ciclo; expor trigger de Auto Extension;
  iniciar o ProactiveNotifier com sink Telegram
- Publicação: commit v0.27.3 + push (regra §2.1.2)

---

## [0.27.2] — Correspondência de Actions NV → OD 📋 (2026-09-04)

### 1. O que foi feito

Tabela de correspondência completa entre o catálogo OD (56 actions) e o
legado NV (58 módulos em `plugins/actions/`) — nova
`docs/ACTIONS_CORRESPONDENCIA.md`:

- **54 portadas** com o mesmo nome · **1 renomeada** (`list_actions` →
  `action_list`)
- **3 excluídas com justificativa**: `system_exec` (execução arbitrária,
  `dangerous=True` no legado — coberta por Control Bridge/Coder/Auto
  Extension), `database_backup` e `database_stats` (**stubs vazios de 0
  bytes**, nunca implementados no NV)
- **1 complementar**: `process_tree` (não existia no NV)
- Conta conferida: 58 − 3 + 1 = **56** ✅
- Corrigida a §3.3 do `docs/NV_LEGACY_ANALYSIS.md` (56 → 58 módulos, com
  `system_exec`/`database_backup`/`database_stats`/`list_actions`)
- **Correção histórica**: o CHANGELOG v0.11.0 dizia "2 complementares"
  (process_tree e action_list) — `action_list` é renomeação, não complemento

### 2. Evidência

```
pytest tests/ -q   → 1382 passed, 0 falhas  (mudanças apenas de documentação)
```

### 3. O que NÃO foi feito

- As 3 ações excluídas não foram portadas (decisões registradas no
documento; `system_exec` exige autorização arquitetural antes de entrar)

### 4. Próximo passo

- Fechar o loop de auto-recuperação (P2 — ver [0.27.3])

---

## [0.27.0] — Pós-Fase 7: Orchestrator × ActionRegistry ⚙️ (2026-09-04)

### 1. O que foi feito

**Integração pós-roadmap** — o Orchestrator passou a executar ações do
catálogo via ActionRegistry, com controle de acesso do Security Layer:

| Item | Entrega | Testes |
|---|---|---|
| `execute_action()` | `core/orchestrator.py` — executa ação via ActionRegistry (ou callable injetado via `add_action()`), gate de role (admin/agent) + Security Layer | 9 (`TestOrchestratorActionRegistry` em `test_orchestrator.py`) |
| `set_action_registry()` / `add_action()` / property `action_registry` | injeção do registry após a construção | — |
| Testes dedicados | `tests/test_orchestrator_action_registry.py` | 14 (`TestOrchestratorActionIntegration`) |
| Launcher | `build_action_registry()` + `orchestrator.set_action_registry()` no modo telegram; bot com `action_registry` | — |
| Comando `/executa` | `integrations/telegram/commands.py` — classificação de risco (3 níveis) + controle de acesso | — |

### 2. Evidência

```
pytest tests/ -q  →  1382 passed, 0 falhas  (1359 da v0.26.0 + 23 novos)
```

### 3. O que NÃO foi feito

- Ações do legado NV **não portadas** no catálogo: `system_exec`
  (exclusão deliberada — execução arbitrária sem gate), `database_backup`
  e `database_stats` — pendência P1: tabela de correspondência das 56
  actions NV→OD com justificativas
- Control Bridge sem testes no repo (pendência P1:
  `tests/test_control_bridge.py` + versionar a unit em `runtime/systemd/`)
- Publicação desta entrada: o commit v0.27.0 (`6ca5374`) já está no
  GitHub; o protocolo §2.1.1 é que não foi cumprido na época — corrigido
  nesta entrada retroativa

### 4. Próximo passo

- **P1 — fidelidade de integração**: tabela de correspondência das actions
  NV→OD, unit do Control Bridge no repo, testes do Control Bridge, limpeza
  do legado (HA duplicado em `~/nexus/infra/ha/config` com `.storage`,
  resíduos de comandos quebrados em `~/nicky` e `~/nexus`)
- **P2 — evolução**: WebSocket `/ws/chat` real, auditoria de integridade do
  Nexus, health checks de serviços externos (HA/MQTT), plugins reais, CI

---

## [0.26.0] — FASE 7 COMPLETA: Infraestrutura e Observabilidade 🏗️ (2026-09-04)

### 1. O que foi feito

**Fase 7 encerrada com 5/5 itens — 37/37 capacidades do roadmap.**

| Item | Entrega | Testes |
|---|---|---|
| 7.1 Audit System | `observability/audit.py` — trilha JSONL persistente com rotação, sink no AuditEngine do Security Layer, Event Bus `audit.record` | 36 |
| 7.2 Metrics Collector | `observability/metrics.py` — Counter/Gauge com labels + fontes vivas, Prometheus text format; /metrics da API renderiza o coletor | 24 |
| 7.3 Health Check | `observability/health.py` — checks por componente (up/degraded/down), latência, métricas; /health responde o agregado | 17 |
| 7.4 Plugin System | `plugins/manager.py` — 3 contratos de plugin, registro de actions/workflows, hot-reload, escopo estrito §7.1 | 20 |
| 7.5 Database Layer | `storage/database.py` — pool SQLite stdlib, transações com afinidade de conexão, Repository CRUD, actions de banco plugadas | 24 |

O launcher integra tudo: `build_audit_system()`, `build_metrics()`, `build_health()` (5 checks), `build_plugins()` e `build_database()` (injeta no catálogo de actions).

### 2. Evidência

```
pytest tests/ -q  → 1359 passed, 0 falhas  (1238 na Fase 6 + 121 novos da Fase 7)
Smoke ao vivo     → actions database_tables ok · health com 5 checks
                    · Audit System/Metrics/Health/Plugins/Database ativos
GitHub            → push de origin/master com os 5 commits da Fase 7
```

### 3. O que NÃO foi feito

- Todos os itens do roadmap (Fases 1–7, 37 capacidades) estão implementados
- Evoluções possíveis (fora do roadmap): histogramas Prometheus,
  integridade de arquivos do legado Nexus, health checks de serviços
  externos (HA/MQTT), migrations de schema versionadas, plugins reais em
  `plugins/actions/`, streaming WebSocket
- Validações ao vivo pendentes: reiniciar o `od-core` e conferir o journal
  com os 5 componentes novos ativos + um GET /health na LAN

### 4. Próximo passo

- **Publicação**: commit v0.26.0 + push para `origin/master` (regra
  §2.1.2 — fase concluída com suíte verde)
- **Validação ao vivo**: reiniciar o od-core (systemd) e confirmar no
  journal "Audit System ativo", "Metrics Collector ativo", "Health
  Monitor ativo", "Plugin System ativo" e "Database Layer ativo"
- Depois: manutenção/evolução contínua — roadmap 100% absorvido

---

## [0.25.0] — Fase 7, item 7.4: Plugin System 🔌 (2026-09-04)

### 1. O que foi feito

**Fase 7 com 4/5 itens.** Carregamento dinâmico de plugins em `plugins/`
(espelho do PluginLoader legado NV — subdiretórios actions/providers/
workflows/integrations):

| Contrato | Registro |
|---|---|
| `PLUGIN = {...}` dict | actions no ActionRegistry com permission `plugin.<nome>` + workflows no WorkflowEngine |
| `ACTIONS`/`WORKFLOWS` | idem (variáveis de módulo) |
| `register_actions`/`register_workflows` | funções de registro (nomes rastreados por diferença) |

Hot-reload (reload/unload/reload_all desregistram antes de recarregar),
escopo estrito §7.1 (PluginScopeError), falha de plugin isolada (não
derruba os demais), Event Bus best-effort, métricas e health(). Launcher
com `build_plugins()`.

### 2. Evidência

```
pytest tests/test_plugins.py -q    → 20 passed
pytest tests/ -q                   → 1335 passed, 0 falhas (1315 + 20)
Smoke ao vivo                      → Plugin System ativo, 0 plugins
                                    (plugins/ sem plugins reais ainda)
```

### 3. O que NÃO foi feito

- Fase 7 com 1/5 em aberto: **7.5 Database Layer**
- Nenhum plugin real no repo ainda — `plugins/` está pronto para receber
  (ex: um plugin de exemplo em `plugins/actions/`)
- Push no GitHub: pendente até o fechamento da Fase 7 (autorizado —
  commits locais até v0.25.0)

### 4. Próximo passo

- **Fase 7, item 7.5 — Database Layer** (`storage/database.py`): camada de
  persistência relacional (pool de conexões + repositórios) — ÚLTIMO item
  da Fase 7; ao concluir, fechamos a fase e fazemos o push

---

## [0.24.0] — Fase 7, item 7.3: Health Check 🩺 (2026-09-04)

### 1. O que foi feito

**Fase 7 com 3/5 itens.** Verificação de status dos componentes em
`observability/health.py` (stdlib puro):

| Camada | Entrega |
|---|---|
| **`ComponentHealth`** | resultado tipado por componente (ok, status up/degraded/down, detail, latency_ms, critical) |
| **`HealthMonitor`** | checks registráveis sync/async, severidade por check (crítico → down, não-crítico → degraded), latência, métricas, snapshot/dump, check quebrado resiliente |
| **API REST** | `APIConfig.health`: /health responde o agregado do monitor (com uptime_s); sem monitor, legado preservado |
| **Launcher** | `build_health()` — orchestrator/llm críticos + audit/metrics não-críticos |

### 2. Evidência

```
pytest tests/test_health.py -q    → 17 passed
pytest tests/ -q                  → 1315 passed, 0 falhas (1298 + 17)
Smoke ao vivo                     → agregado com 4 checks (orchestrator/llm/
                                    audit/metrics) + latência por check
```

### 3. O que NÃO foi feito

- Fase 7 com 2/5 em aberto: 7.4 Plugin System, 7.5 Database Layer
- Health checks de serviços externos (HA, MQTT, mosquitto) não registrados
  no launcher — ficam para a 7.5/evolução (os componentes já existem)
- Push no GitHub: pendente até o fechamento da Fase 7 (autorizado pelo
  Alex — commits locais: v0.22.0 `3ed11c1`, v0.23.0 `4cbf1b7`)

### 4. Próximo passo

- **Fase 7, item 7.4 — Plugin System** (`plugins/`): carregamento dinâmico
  de plugins sobre o Tool Loader + Action Registry (item mais pesado da
  fase — Alto)

---

## [0.23.0] — Fase 7, item 7.2: Metrics Collector 📊 (2026-09-04)

### 1. O que foi feito

**Fase 7 com 2/5 itens.** Coletor central de métricas em `observability/`
com exposição no **Prometheus text format** (stdlib puro):

| Camada | Entrega |
|---|---|
| **`Metric`** | counter/gauge com labels, `inc`/`dec`/`set`/`value`, validação rígida de labels, amostras com escape correto |
| **`MetricsCollector`** | registro idempotente por nome, fontes vivas (`add_source`), `render()` com HELP/TYPE + amostras, `snapshot()`/`health()`/`dump()`, thread-safe |
| **API REST** | `APIConfig.metrics`: /metrics renderiza o coletor com `od_api_requests_total`/`od_api_errors_total`; sem coletor, legado preservado |
| **Launcher** | `build_metrics()` — fontes vivas de uptime, Orchestrator e Audit em todos os modos |

### 2. Evidência

```
pytest tests/test_metrics.py -q    → 24 passed
pytest tests/ -q                   → 1298 passed, 0 falhas (1274 + 24)
Suíte 100% verde                   → falha ambiental pré-existente do
                                     ConfigManager corrigida (teste hermético)
```

### 3. O que NÃO foi feito

- Fase 7 com 3/5 em aberto: 7.3 Health Check, 7.4 Plugin System,
  7.5 Database Layer
- Histogramas/summary Prometheus (distribuições) não implementados — só
  counter e gauge, suficientes para as métricas atuais
- Push no GitHub pendente: §2.1.2 exige publicar ao fim da FASE; itens 7.1
  e 7.2 estão commitados localmente (v0.22.0 `3ed11c1` + v0.23.0 pendente)

### 4. Próximo passo

- **Fase 7, item 7.3 — Health Check** (`observability/health.py`): health
  checks por componente, consolidando `/health` da API e `health()` dos
  componentes num módulo dedicado

---

## [0.22.0] — Fase 7, item 7.1: Audit System 🛡️ (2026-09-04)

### 1. O que foi feito

**Fase 7 (Infraestrutura e Observabilidade) iniciada — 1/5 itens.**
Trilha de auditoria contínua e PERSISTENTE dedicada em `observability/`:

| Camada | Entrega |
|---|---|
| **Registro** | `AuditEntry` tipado e imutável (ts, id, source, action, outcome, severity, actor, session_id, detail, data) |
| **Persistência** | JSONL append-only (`logs/audit.jsonl` default) com rotação por tamanho (5MB) + retenção (3 backups) e recarga no startup — a trilha sobrevive a reinícios |
| **Segurança (critério da Fase 7)** | `record_decision()` + `make_sink()`: plugado no `AuditEngine` do Security Layer, TODA decisão (allow/deny/approval) cai na trilha persistente |
| **Observabilidade** | Event Bus `audit.record`, consultas (history/search/since/by_action/counts), métricas, `health()`, `snapshot()`/`dump()` |
| **Runtime** | `build_audit_system()` no launcher + `OD_AUDIT_FILE`; `system.startup` (modo + pid) registrado em todos os modos |

Resiliência por construção: sink quebrado, payload não serializável, arquivo
ilegível ou sem permissão nunca derrubam a trilha — `record()` não levanta
exceção (contadores `failed`/`errors` + WARN). Zero dependências novas.

### 2. Evidência

```
pytest tests/test_audit.py -q    → 36 passed
pytest tests/ -q                 → 1272 passed (1238 anteriores + 36 novos)
build_audit_system() ao vivo     → logs/audit.jsonl criado, health ok,
                                   system.startup persistido
```

### 3. O que NÃO foi feito

- Fase 7 ainda tem 4/5 itens em aberto: 7.2 Metrics Collector,
  7.3 Health Check, 7.4 Plugin System, 7.5 Database Layer
- Auditoria de integridade do legado Nexus (verificação de arquivos/serviços
  e relatórios de conformidade) fica como evolução futura — o critério da
  Fase 7 (registrar todas as decisões de segurança) está atendido
- `test_config_manager.py::test_init_without_yaml` segue falhando no
  ambiente (variáveis `OD_*` presentes) — PRÉ-EXISTENTE, sem relação com
  esta entrega; `test_mqtt` é flaky (timing), verde isolado

### 4. Próximo passo

- **Fase 7, item 7.2 — Metrics Collector** (`observability/metrics.py`):
  coletor Prometheus dedicado consolidando as métricas que hoje vivem
  espalhadas (API `/metrics`, telemetria, audit)

---

## [0.21.0] — Voz real no Telegram: STT + TTS 🎤🔊 (2026-09-03)

### 1. O que foi feito

O 14º recurso do bot (voz) deixou de ser stub e agora usa os binários
reais da Fase 6:

| Fluxo | Como | Binário real |
|---|---|---|
| **Você envia áudio** | `fetch_file` baixa → `TelegramVoiceSTT` grava em temp → ffmpeg converte (WAV 16kHz) → whisper-cli transcreve | whisper.cpp (ggml-base) |
| **OD responde falando** | texto da resposta → `TelegramVoiceTTS` → Piper sintetiza → `send_voice` (multipart stdlib) | Piper (dii/faber) |

- Decoder do bot aceita callables sync **ou async**; se a síntese falhar,
  cai para texto (nunca silencia)
- Launcher conecta STT+TTS automaticamente (envs `OD_VOICE_STT/TTS/PROFILE`);
  od-core reiniciado com **"Voz STT habilitada (whisper.cpp)"** e
  **"Voz TTS habilitada (Piper)"** no journal

### 2. Evidência

```
pytest tests/ -q                          → 1238 passed, 0 falhas  (1229 + 9)
sendVoice E2E contra a Bot API real        → ok: true · 342KB de voz Piper enviados
                                            (mensagem de voz recebida no Telegram)
journal od-core (produção)                 → Voz STT habilitada · Voz TTS habilitada
                                            · Presence Monitor · Face Detector
```

### 3. O que NÃO foi feito

- Transcrição de voz ao vivo ainda não observada (nenhum áudio real
  recebido após o deploy — envie um áudio ao @Nicky_Virthy_bot para
  validar o caminho completo)
- Streaming token-a-token (WebSocket) segue como evolução futura

### 4. Próximo passo

- **Validar ao vivo**: envie um áudio ao bot e eu confiro a transcrição no
  journal + a resposta por voz
- Ou **Fase 7 — Infraestrutura e Observabilidade**

---

## [0.20.0] — Fase 6 COMPLETA: Sensorial e Inteligência 🧠 (2026-09-03)

### 1. O que foi feito

**Fase 6 encerrada com 6/6 itens — 32/32 capacidades do roadmap.**

| Item | Entrega | Validação real |
|---|---|---|
| **6.1 Face Detection** | `tools/vision/face_detector.py` — Haar + CLAHE + ROI guard + buffer 3/2 (espelho do legado) | **Webcam real do servidor** (/dev/video0, Alcor 1080P): frame capturado, cascade ok, 0 rostos (ninguém na frente — correto). OpenCV 4.14 fixado (5.0 removeu o Haar) |
| **6.2 Presence Monitor** | (0.18.0) HA person/device_tracker → Event Bus → Telegram | 34 entidades reais lidas no od-core |
| **6.3 STT** | `tools/audio/stt.py` — whisper.cpp via subprocess + ffmpeg | Binários reais do legado: whisper-cli + ggml-base.bin (148MB) |
| **6.4 TTS** | `tools/audio/tts.py` — Piper com vozes por perfil (dii/faber) | **E2E completo**: Piper sintetizou → whisper transcreveu de volta em 3.2s |
| **6.5 Profile Manager** | `agents/profiles.py` — 6 perfis + detecção automática por domínio (radical ≥4 letras) | Plugado no bot: perfil `auto` detecta pelo texto |
| **6.6 Auto Extension** | `tools/auto_extension/` — geração de ferramentas via LLM, compile + allowlist de imports, registro com permission mediada pelo Security Layer | 13 testes de pipeline (incl. código com `import os` barrado) |

### 2. Evidência

```
pytest tests/ -q                          → 1229 passed, 0 falhas  (1153 + 76)
E2E voz real (Piper → whisper)            → 3.2s: "Olá Alex, o OmegaDracom está funcionando de verdade."
Webcam real /dev/video0                   → frame 1280×720, cascade ok, capturas_failed=0
ROADMAP                                   → 32/32 capacidades · Fase 6 ✅ 6/6
```

### 3. O que NÃO foi feito

- **Vision ativo no od-core**: `OD_VISION_ENABLED` existe mas fica **0**
  (default) — câmera só liga quando você ativar (economiza CPU; sem gente
  na frente não há evento). Comando: `OD_VISION_ENABLED=1` no `.env`
- Face Detection sem validação de presença humana real (câmera sem gente)
  — quando alguém ficar na frente, o buffer 3/2 confirma e notifica
- Fase 7 (Infraestrutura e Observabilidade) ainda não iniciada

### 4. Próximo passo

**Fase 7 — Infraestrutura e Observabilidade** (paralela): dashboards de
métricas, health checks centralizados, alertas de resiliência. Ou o que
você quiser priorizar — o roadmap está com **todas as 32 capacidades
entregues**.

---

## [0.19.0] — Web: Chat funcional + shells públicos (sem chave manual) 💬 (2026-09-03)

### 1. O que foi feito

| Item | O que | Destaques |
|---|---|---|
| **Chat funcional** | `integrations/api/server.py` | `/chat` vira uma página real (HTML+JS vanilla): pede a `OD_API_KEY` **uma vez** (sessionStorage, nunca na URL), conversa com o OD via `POST /message` (perfil selecionável, bolhas, 401 → volta ao gate) |
| **Shells públicos** | `APIConfig.page_shells_public` | Com `auth_all`, `/chat` e `/dashboard` (HTML estático sem dados) carregam sem chave; **dados** (`/message`, `/llms`, `/dashboard/stats`…) seguem exigindo `X-API-Key` |
| **Dashboard** | estático | Sem números vivos no shell — métricas só via `/dashboard/stats` (chave) |
| — | `docs/REGRAS_DE_TRABALHO.md` | §10: autorização permanente p/ instalar ferramentas + shells web sem chave manual (regra do usuário) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_api.py -q   → 53 passed
.venv/bin/python -m pytest tests/ -q                → 1153 passed, 0 falhas
GET /chat sem chave                                 → 200 (HTML com gate sessionStorage)
GET /health, /llms, POST /message sem chave         → 401
POST /message com chave                             → ok, rota llm, resposta do gemma
```

### 3. O que NÃO foi feito

- WebSocket streaming (`/ws/chat` segue 501) — o chat usa request/response
  no `POST /message`; streaming exige servidor async dedicado
- Chat do Telegram e web compartilhando o mesmo histórico por usuário
  (user `web` é separado) — possível evolução futura

---

## [0.18.0] — Fase 6 (item 6.2) — Presence Monitor ✅ (2026-09-03)

> **FASE 6 — 1/6 itens.** 26/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **6.2 Presence Monitor** | `integrations/homeassistant/presence.py` | Monitora `person.*`/`device_tracker.*` do HA (back-end plugável): classifica home/away (unknown → away), detecta chegada/saída, publica **Event Bus** `presence.changed`, sinks plugáveis (Telegram) com 🏠/🚶, **baseline silencioso + estado persistido** (reinício sem eventos falsos), métricas, `history()`/`dump()`/`health()` · **decisão:** presença via HA em vez de câmera — Face Detection (6.1) segue depois |
| — | `tests/test_presence.py` | **26 testes** (classificação, nomes legíveis, transições, filtros, Event Bus, sinks sync/async, persistência/restart, introspecção) |
| — | `runtime/launcher.py` | Presence no `od-core`: lê `config/iot_credentials.json` (envs `OD_PRESENCE_*`), notifica admin no Telegram + aviso único de ativação (flag persistida) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_presence.py -q   → 26 passed
.venv/bin/python -m pytest tests/ -q                     → 1151 passed, 0 falhas
HA real: 34 entidades lidas · baseline: person/device_tracker = away
od-core: "Presence Monitor habilitado" + aviso de ativação enviado
```

### 3. O que NÃO foi feito

- **Fase 6 restante (5/6)**: Face Detection (6.1, câmera), STT (6.3), TTS
  (6.4), Profile Manager (6.5), Auto Extension (6.6)
- Detecção por câmera/visão — a presença atual vem das entidades do HA
  (person/device_tracker); para o OD avisar “chegou em casa”, o tracker do
  celular precisa reportar `home` ao HA (app companion/GPS)
- Aviso de “novo usuário” no Telegram (fluxo de onboarding do bot) — fora
  do escopo desta entrega

### 4. Próximo passo

**Fase 6, item 6.1 — Face Detection** (`tools/vision/face_detector.py`) —
Haar Cascade + CLAHE + buffer de confirmação, alimentando o mesmo
barramento de presença.

---

## [0.17.2] — API REST: X-API-Key em todos os endpoints 🔒 (2026-09-03)

### 1. O que foi feito

| Item | O que | Destaques |
|---|---|---|
| **auth_all** | `integrations/api/server.py` | `APIConfig.auth_all=True` exige a chave em TODAS as rotas (inclusive públicas) — para bind exposto na LAN · sem chave configurada + auth_all → nega tudo (401 + log) · launcher: `OD_API_AUTH_ALL` default 1 |
| — | `tests/test_api.py` | **5 testes novos** (`TestAuthAll`) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/ -q        → 1125 passed, 0 falhas
LAN sem X-API-Key: /health /metrics /llms   → 401 em todos
LAN com X-API-Key: /health /llms /dashboard → 200
```

### 3. O que NÃO foi feito

- Páginas HTML (`/dashboard`, `/chat`) agora exigem a chave via header —
  um navegador puro não envia header custom; se o site precisar abri-las
  direto no browser, o caminho é um proxy que injeta a chave (ou `curl`
  com `-H X-API-Key`)

---

## [0.17.1] — Correções de produção: Telegram loop + API na LAN 🐛 (2026-09-03)

### 1. O que foi feito

| Item | O que | Destaques |
|---|---|---|
| **Telegram loop** | `integrations/telegram/bot.py` | `offset = update_id + 1` (o servidor só confirma `update_id < offset` — sem o `+1` reentregava o mesmo update para sempre → bot respondia sem parar) · **offset persistido** em `data/telegram_offset.json` (reinícios não reprocessam) |
| **Testes alinhados** | `transport.py` + `tests/test_telegram.py` | `InMemoryTransport` imita o servidor real (confirma `< offset`) — a regressão do loop agora é detectável · +2 testes (offset avança p/ último+1, persistência entre bots) |
| **API na LAN** | `runtime/launcher.py` | Bind via `OD_API_HOST` (default `0.0.0.0`) — `http://192.168.0.250:8000` acessível · `OD_API_KEY` gerada no `.env` (endpoints protegidos com `X-API-Key`) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_telegram.py -q   → 57 passed
.venv/bin/python -m pytest tests/ -q                     → 1120 passed, 0 falhas
curl http://192.168.0.250:8000/health                    → 200 (LAN)
curl sem X-API-Key /llms                                 → 401 (protegido)
Bot: respondeu o backlog 1x e ficou ocioso; novas mensagens → 1 resposta
```

### 3. O que NÃO foi feito

- MQTT: por decisão do usuário, broker segue **anônimo (só LAN)** — sem
  usuário registrado; comandos sudo ficam prontos para quando quiser
- HA: usuário Alex Projeti (`alex`) já existia como owner/admin — nada a
  fazer; acesso em `http://192.168.0.250:8123`

---

## [0.17.0] — Fase 5 (item 5.5) — MQTT Bridge ✅ (2026-09-03)

> **FASE 5 — 5/5 COMPLETA (Telegram, API, Notifier, IoT, MQTT).**
> 25/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **5.5 MQTT Bridge** | `integrations/mqtt/` | Ponte MQTT 3.1.1 em **stdlib puro** (sem paho-mqtt): `protocol.py` — codec wire completo (CONNECT/CONNACK, PUBLISH QoS 0/1 + PUBACK, SUBSCRIBE/SUBACK, retained, validação e curingas +/#) · `client.py` — `MQTTClient` real (socket, reader + keepalive em threads, PUBACK síncrono, shutdown correto) · `broker.py` — `InMemoryBroker` fake em processo (mesmo wire, recusa configurável, roteamento, retained, drop de sessão) · `bridge.py` — `MQTTBridge`: mensagens → **Event Bus** `mqtt.message`, handlers por filtro, roteamento **bus→MQTT** (`od/<tópico>`), reconexão com re-assinatura, `run`/`start`/`stop`, métricas e `health()` |
| — | `tests/test_mqtt.py` | **54 testes** (codec, cliente real ↔ broker fake em loopback, QoS 0/1, retained, bridge/Event Bus, roteamento, reconexão) |
| — | `runtime/launcher.py` | Modo `mqtt` + ponte no `all` (envs `OD_MQTT_*`) — **od-core em produção assina `od/in/#`** |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_mqtt.py -q   → 54 passed
.venv/bin/python -m pytest tests/ -q                 → 1118 passed, 0 falhas
E2E Mosquitto real (127.0.0.1:1883)                  → pub/sub + rota bus→MQTT→bus OK
journal od-core                                      → MQTT conectado, od/in/verificacao recebida
```

### 3. O que NÃO foi feito

- **Fase 5 FECHADA.** Próxima: **Fase 6 — Sensorial e Inteligência**
- QoS 2, Last Will e sessões persistentes no broker fake — fora do escopo
  (decisões registradas no módulo)
- Auth no broker (o Mosquitto local aceita anônimo; usuário/senha já são
  suportados pelo cliente via `username`/`password`)

### 4. Próximo passo

**Fase 6, item 6.1 — Face Detection** (`tools/vision/face_detector.py`) —
Haar Cascade + CLAHE + buffer de confirmação; depois Presence (6.2).

---

## [0.16.0] — Ativação Real — Omega Drakon NO AR 🟢 (2026-09-03)

> **Primeira entrega operacional**: LLM real + identidade + API + Telegram
> Bot + Home Assistant rodando no servidor. Capacidades do roadmap: 24/32.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **LLM Provider** | `core/llm.py` | `OpenAICompatProvider` — o elo que faltava entre o Orchestrator e um LLM real: OpenAI-compat em **stdlib** (urllib), ChatML→`messages`, `chat()` sync/async, `is_available()`, timeout, erros tipados |
| **LLM no ar** | `/opt/omegadrakon/ai/runtimes/llama` | llama.cpp b10786 (suporte a gemma4) + **gemma-4-E4B-it-Q4_K_M.gguf** servindo em `127.0.0.1:8081` — resposta real com raciocínio em ~17s (CPU, 4 núcleos) |
| **Identidade** | `agents/nicky_virthy/personality.py` | System prompt da Nicky (SOUL/IDENTITY + Tríade) por perfil; injetado via `OrchestratorConfig.default_system_prompt` — o gemma responde como Nicky Virthy |
| **Launcher** | `runtime/launcher.py` | Sobe o sistema real: Orchestrator + provider `gemma-local` + API REST (8000) + Telegram Bot em polling; logs em `runtime/logs/` |
| **Segredos** | `.env` + `.gitignore` + `config/` | Token legado validado (**@Nicky_Virthy_bot**), admin `660518870`; `.env`, `config/iot_credentials.json` e `data/` protegidos; template commitável `.example.json` |
| **Home Assistant** | `/srv/omegadrakon/homeassistant` | Config migrada de dentro do nexus (byte a byte, incl. auth) e container recriado — OD autossuficiente; IoTManager validado contra **29 entidades reais** |
| **Auto-start** | `runtime/systemd/` | Units de usuário `od-llm.service` + `od-core.service` + `install-user.sh` — instaladas, habilitadas e **ativas** (linger on, sobrevive a reboot) |
| — | `tests/test_llm.py` + `tests/test_personality.py` | **27 testes novos** (17 + 10) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/ -q        → 1064 passed, 0 falhas
curl http://127.0.0.1:8081/health            → {"status":"ok"}
curl http://127.0.0.1:8000/health            → ok, llms: [gemma-local]
curl :8000/llms (X-API-Key)                  → OpenAICompatProvider "gemma-local"
GET /api/ do HA + token legado                → 200 (29 entidades via IoTManager)
systemctl --user status od-llm od-core        → active (running), enabled
E2E: HTTP → Orchestrator → gemma             → responde como Nicky Virthy, OD
```

### 3. O que NÃO foi feito

- **Fase 5 (1/5 restante)**: MQTT Bridge (5.5) — o Mosquitto systemd já está
  ativo em 127.0.0.1:1883, aguardando a ponte
- STT/TTS reais (Fase 6) — a voz entra via decoder plugável no Telegram
- Units systemd de sistema (root): as atuais são de usuário (sem sudo
  disponível); `runtime/systemd/` documenta a promoção futura
- Docker/MariaDB legados parados permanecem como estão; nada do nexus é
  necessário para o OD rodar

### 4. Próximo passo

**Fase 5, item 5.5 — MQTT Bridge** (`integrations/mqtt/`) — ponte para o
broker Mosquitto já ativo, fechando a **Fase 5 (5/5)**.

---

## [0.15.0] — Fase 5 (item 5.4) — IoT Manager ✅ (2026-09-03)

> **FASE 5 — 4/5 itens (IoT Manager).** 24/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **5.4 IoT Manager** | `integrations/homeassistant/` | Integração Home Assistant do legado Nexus em **stdlib**: `models.py` — **taxonomia ambiental** (atuadores/sensores/móveis/infra/unknown por domínio do entity_id) · `EntityState` (espelho /api/states, `is_on()`, to/from dict) · `HACredentials` (base_url+token, validação, `from_file` — segredos fora do código, spec §7) · `client.py` — `HAClient` REST (GET /api/states + POST /api/services com Bearer token, 404→None, `service_available`, erros→`HAError`) + **`InMemoryHAServer`** fake com a MESMA interface (`HABackend`) para testes/dev offline · `manager.py` — `IoTManager`: leitura (`get_entity`/`list_entities` por tipo/`sensor_reading`), controle (`set_power`/`toggle` — serviço pelo domínio), **gate de segurança** (`allowed_domains` + `guard(entity, action)` injetável; recusa → denied sem exceção), `snapshot()` por tipo, `list_types()`, métricas (reads/commands/ok/denied/errors), Event Bus (`iot.command`), `dump()` · NICKY |
| — | `tests/test_homeassistant.py` | **45 testes** (taxonomia completa, EntityState/credenciais, HAClient com rede stubada — Bearer/payload/erros, InMemoryHAServer, controle com gates/guard, Event Bus, métricas, snapshot/dump) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_homeassistant.py -q   → 45 passed
.venv/bin/python -m pytest tests/ -q                          → 1037 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 5 (1/5 restante)**: MQTT Bridge (5.5) — com ele, a Fase 5 fecha
- MQTT no IoT Manager: o legado também controlava via MQTT — aqui o
  controle é REST; a ponte MQTT vem no item 5.5
- Automações/script de cena via HA e long-lived tokens de usuário (usar
  token de sistema HA) — detalhes de operação, fora da absorção

### 4. Próximo passo

**Fase 5, item 5.5 — MQTT Bridge** (`integrations/mqtt/`) — ponte para
broker Mosquitto, fechando a **Fase 5 (5/5)**.

---

## [0.14.0] — Fase 5 (item 5.3) — ProactiveNotifier ✅ (2026-09-03)

> **FASE 5 — 3/5 itens (ProactiveNotifier).** 23/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **5.3 ProactiveNotifier** | `integrations/notifier.py` | Notificações proativas do legado em **stdlib** (sem httpx): **sondas embutidas** (`CheckFn` sync/async, resultado único ou múltiplo) — `orchestrator` (conectado?), `llm` (providers com `is_available()`; sem sonda = disponível; nenhum → **CRIT após 300s** = o "LLM offline >5min" do legado; health() acusa na hora), `disk` (`shutil.disk_usage` por path; ≥85% warn, ≥95% crit; ilegível → `disk:unreadable`), `restart` (PID persistido em `state_file` JSON) · **anti-spam** por chave de alerta (padrão 3600s — 1/hora, igual ao legado; override `cooldowns`; persistido entre instâncias) · **sinks plugáveis** sync/async com texto formatado 🟢🟡🔴 (canal desacoplado do transporte — decisão registrada) · **Event Bus** (`notifier.alert`) · `tick()`/`run(interval, max_ticks)`/`start()`/`stop()` (thread daemon)/`health()`/`snapshot()`/`history()`/`dump()` · `NotifierMetrics` · relógio injetável · NICKY |
| — | `tests/test_notifier.py` | **42 testes** (tipos e formatação, sondas com fakes — disco monkeypatch e restart por estado, threshold de LLM, anti-spam/cooldown por chave e persistido, sinks sync/async e quebrados, Event Bus, checks customizados sync/lista/async, loop, dump/history limitada) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_notifier.py -q   → 42 passed
.venv/bin/python -m pytest tests/ -q                    → 992 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 5 (2/5 restantes)**: IoT Manager (5.4) e MQTT Bridge (5.5)
- Envio direto via Telegram (o legado usava httpx acoplado) — aqui o canal
  é um sink plugável; o TelegramBot da 5.1 pode ser o sink de produção
- Alertas de presença/visão (dependem da Fase 6 — sensorial)
- Dashboards/UI de alertas (observabilidade é a Fase 7)

### 4. Próximo passo

**Fase 5, item 5.4 — IoT Manager** (`integrations/homeassistant/`) —
controle de dispositivos; depois MQTT Bridge (5.5), que fecha a Fase 5.

---

## [0.13.0] — Fase 5 (item 5.2) — API REST ✅ (2026-09-03)

> **FASE 5 — 2/5 itens (API REST).** 22/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **5.2 API REST** | `integrations/api/` | Os **17 endpoints do legado Nicky** em **http.server stdlib** (ThreadingHTTPServer — sem FastAPI): `GET /` (info), `/health` (status + LLMs), `/profiles`, `/profiles/{name}`, `/presence/today`, `/dashboard` e `/chat` (HTML placeholder), `/metrics` (texto od_*), `/dashboard/stats` (JSON), `/llms`, `POST /message` (pipeline completo do Orchestrator: user_id/profile/text/system_prompt, perfil auto→default, validação 400), `POST /transcribe` e `/tts` (handlers plugáveis; sem handler 501 → Fase 6.3/6.4), `DELETE /history/{user_id}`, `GET /history/{user_id}/stats`, `GET /memory/{user_id}/search` (RAG via VectorStore, namespace por usuário, top_k clampado) · `GET /ws/chat` → **501 registrado** (WebSocket streaming exige servidor assíncrono dedicado) · **API key X-API-Key** nos mesmos endpoints protegidos do legado (compare_digest) · **rate limit por IP** (janela deslizante, 429+retry_after, buckets por instância) · CORS preflight · bind padrão 127.0.0.1 (sem auth nunca em 0.0.0.0) · roteamento declarativo `ROUTES` (method/path/auth) · erros JSON consistentes (400/401/404/405+Allow/413/429/500/501/502) · `max_body_bytes` · `snapshot()` · NICKY · **Core aditivo:** `Orchestrator.providers` público (usado por /llms e /health) |
| — | `tests/test_api.py` | **46 testes** (tabela 17 rotas + flags de auth, servidor real em loopback por teste, auth 401/chave certa/sem chave, rate limit por IP e por instância, message com memória real (llm/cache/perfis/isolamento), history stats/delete/501, RAG com isolamento por namespace, áudio plugável 501→funcional, HTTP behavior 404/405/CORS/413/JSON inválido) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_api.py -q   → 46 passed
.venv/bin/python -m pytest tests/ -q               → 950 passed, 0 falhas
```

Smoke real (servidor loopback): todos os 17 endpoints respondendo; rota
llm→cache no POST /message; RAG retornando só o namespace do usuário.

### 3. O que NÃO foi feito

- **Fase 5 (3/5 restantes)**: ProactiveNotifier (5.3), IoT Manager (5.4) e
  MQTT Bridge (5.5)
- WebSocket `/ws/chat` (streaming token-a-token) — 501 com decisão
  registrada; exige servidor assíncrono dedicado
- STT/TTS reais (whisper.cpp/Piper são 6.3/6.4) — endpoints prontos com
  handlers plugáveis
- Dashboard/chat HTML interativos (Chart.js/PWA) — placeholder mínimo
- Sem deploy de serviço (systemd) — camada de operação não faz parte da
  absorção de capacidade

### 4. Próximo passo

**Fase 5, item 5.3 — ProactiveNotifier** (`integrations/notifier.py`) —
health check, alertas e anti-spam; depois IoT Manager (5.4) e MQTT (5.5).

---

## [0.12.0] — Fase 5 (item 5.1) — Telegram Bot ✅ (2026-09-03)

> **FASE 5 INICIADA — 1/5 itens (Telegram Bot).** 21/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **5.1 Telegram Bot** | `integrations/telegram/` | Bot sobre o Orchestrator com os **14 recursos do legado** (13 comandos + voz/STT), em 4 camadas · `models.py`: User/Voice/Message/Update tipados (mesmo formato em memória e HTTP) · `transport.py`: protocolo `TelegramTransport` + `InMemoryTransport` (fila com watermark estilo servidor — polls nunca reprocessam; dev/testes sem rede) + `HTTPTransport` (Bot API via urllib stdlib, token obrigatório, getUpdates/sendMessage/getFile, erros mapeados) · `commands.py`: os 13 comandos do legado (start/help/perfil/limpar/status/uptime/stats/dashboard/historico/cache/presenca/codigo/rotacionar_key) com `admin_only` e aliases · `bot.py` — `TelegramBot`: admin gate, texto livre → `Orchestrator.process()` com perfil por chat (auto→default), voz → **STT plugável** (decoder injetável + fallback utf-8) → pipeline, hooks reais de histórico/cache (`/historico`, `/limpar`, `/cache`), métricas messages/commands/replies/voices/errors, **polling com offset persistente** + resiliência a falhas de transporte, `dump()` · comandos locais funcionam sem Orchestrator · NICKY · zero dependências novas |
| — | `tests/test_telegram.py` | **55 testes** (modelos, InMemory/HTTP transports com rede stubada, parsing Bot API, catálogo/admin gate, voz/STT com decoder plugável, mensagens sobre o Orchestrator com memória real em tmp, polling/offset, transporte com falha) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_telegram.py -q   → 55 passed
.venv/bin/python -m pytest tests/ -q                    → 904 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 5 (4/5 restantes)**: API REST (5.2), ProactiveNotifier (5.3),
  IoT Manager (5.4) e MQTT Bridge (5.5)
- STT real (whisper.cpp, item 6.3) e TTS (6.4) — a voz já entra no fluxo
  via decoder plugável, mas a transcrição em produção fica na Fase 6
- Perfis por chat em memória (persistência entre reinícios fica para o
  Profile Manager 6.5) — decisão registrada
- Deploy real contra o servidor do Telegram (token/config) — ambiente
  controlado; transporte HTTP pronto e testado com rede stubada

### 4. Próximo passo

**Fase 5, item 5.2 — API REST** (`integrations/api/`) — endpoints sobre o
Orchestrator; depois Notifier (5.3), IoT (5.4) e MQTT (5.5).

---

## [0.11.0] — Fase 4 (item 4.4) — 56 Actions ✅ (2026-09-03)

> **FASE 4 COMPLETA — 4/4 itens (Coder Engine, Self Repair, Perception,
> 56 Actions).** 20/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **4.4 56 Actions** | `tools/actions/` | Catálogo de **56 actions** registradas no Action Registry (`build_registry`/`register_all`) com `permission` própria (gate do Security Layer na execução): 54 ações enumeradas no legado NV (sistema 13, processos 4, docker 4, serviços 3, arquivos 15, git 10, banco 3, introspecção 3) + **2 complementares documentadas** (`process_tree`, `action_list`) · `CATALOG` tipado (name/category/description/handler/params) · segurança por design: sem path padrão, `process_kill` protege pid<2, `system_env` sem keys só retorna nomes (anti-vazamento), `system_ping` TCP (sem root), escopo estrito §7.1 via Registry · degradação graciosa de docker/systemd/journald/db (`{ok:False,error}` — camada db é da Fase 7.5) · git com repo explícito (`git -C`); filesystem completo (write/read/delete/copy/move/archive/extract/tree/hash/search/...) · zero dependências novas |
| — | `tests/test_actions_catalog.py` | **31 testes** (estrutura do catálogo, registro idempotente, execução funcional sistema/arquivos/processos/git/introspecção, degradação, Security Layer: role/escopo/deny, métricas) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_actions_catalog.py -q   → 31 passed
.venv/bin/python -m pytest tests/ -q                           → 849 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 5 — Integrações Externas** (Telegram, API, Notifier, IoT, MQTT)
- Ações com autenticação/credenciais e Docker SDK/contêineres detalhados
  (sonda por CLI degrada sem daemon) — decisões registradas no CHANGELOG
- Acoplamento das Actions ao Orchestrator (agente) — próximo passo natural
  da Fase 5 (interface principal)

### 4. Próximo passo

**Fase 5, item 5.1 — Telegram Bot** (`integrations/telegram/`) — bot com
comandos, STT/TTS e perfis sobre o Orchestrator; depois API REST (5.2),
Notifier (5.3), IoT (5.4) e MQTT (5.5).

---

## [0.10.0] — Fase 4 (item 4.3) — Perception Syncer ✅ (2026-09-03)

> **FASE 4 — 3/4 itens (Perception).** 19/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **4.3 Perception Syncer** | `tools/telemetry.py` | Telemetria de hardware/serviços 100% stdlib (leitura de `/proc`, `socket`, `shutil`): CPU (% por delta entre amostras de `/proc/stat` + load 1/5/15), memória (`/proc/meminfo` em bytes, +swap), disco (`shutil.disk_usage` por caminho), rede (`/proc/net/dev` rx/tx), portas TCP (socket connect com timeout), Docker (probe de socket unix, sem SDK), processos (`/proc/*/comm`), host/uptime · `Telemetry.collect()` → `TelemetrySnapshot` tipado com seções independentes (`ok=False` + `error` sem exceção) e erros parciais acumulados em `snapshot.errors` · `proc_root`/`docker_socket`/`disk_paths`/`port_timeout` injetáveis (testes com `/proc` fictício determinístico) · `dump()` · logging NICKY · zero dependências novas |
| — | `tests/test_telemetry.py` | **21 testes** (/proc fictício: CPU delta, memória bytes, load, rede, processos, uptime; sondas reais porta TCP aberta/fechada + socket unix Docker; snapshot completo; resiliência a falhas parciais) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_telemetry.py -q   → 21 passed
.venv/bin/python -m pytest tests/ -q                     → 818 passed, 0 falhas
```

Smoke real contra `/proc` da máquina: mem 14.7%, disco 27.8%, interfaces com
bytes reais (lo/enp2s0/wlx...), Docker up, 0 erros.

### 3. O que NÃO foi feito

- **Fase 4 (1/4 restante)**: item 4.4 — as 56 Actions operacionais
- Integração automática Perception → Self Repair (4.2): as seções de
  telemetria estão prontas para alimentar oracles `check` do Self Repair,
  mas o acoplamento por serviço fica para a fase de Actions/operação
- Contêineres Docker listados (sem SDK externo, a sonda reporta apenas
  daemon acessível/up) — decisão registrada
- Monitoramento de thresholds/alertas (Fase 7 — observabilidade)

### 4. Próximo passo

**Fase 4, item 4.4 — 56 Actions** (via `tools/registry.py` + Security Layer):
catálogo de ações operacionais por categoria. Com ele, a Fase 4 fecha.

---

## [0.9.0] — Fase 4 (item 4.2) — Self Repair Engine ✅ (2026-09-03)

> **FASE 4 — 2/4 itens (Self Repair).** 18/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **4.2 Self Repair** | `core/self_repair.py` | Ciclo **detectar → gerar → reparar → verificar → (rollback)** com toda correção mediada pelo Coder Engine (4.1): detecção determinística (syntax `compile` para `.py`, import probe isolado opcional para import/runtime, oracle `check` sync/async injetado) · geração por estratégias embutidas (`AddMissingColon` — headers de bloco sem `:`) + estratégias customizadas + **providers plugáveis** (`FixProvider`, futuro ponto de auto-extensão LLM 6.6) · candidatos submetidos ao `CoderEngine.apply_change()` (sandbox→testes→backup→promoção, runner/test_command, Security Layer) · verificação pós-promoção (check/re-detecção) · **rollback automático** para snapshot pré-reparo (bytes exatos em `.od_repair_backups/`) quando a verificação reprova · `restore()` manual · escopo estrito §7.1 · eventos `self_repair.detected`/`self_repair.completed` · `Detection`/`RepairAttempt`/`RepairReport`/`RepairMetrics` + trilha + `dump()` · NICKY · zero dependências novas |
| — | `tests/test_self_repair.py` | **41 testes** (detecção, estratégias, ciclos healthy/repaired/no_fix/error, check sync/async, rollback/restore, mediação do Coder, providers, dedupe/max_attempts, eventos, métricas) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_self_repair.py -q   → 41 passed
.venv/bin/python -m pytest tests/ -q                       → 797 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 4 (2/4 restantes)**: Perception (4.3) e 56 Actions (4.4)
- Correções assistidas por LLM (auto-extensão) — o `FixProvider` é o ponto de
  extensão preparado, mas nenhum provider LLM foi acoplado (não há
  `core/llm.py` ainda; decisão registrada)
- Telemetria/Perception alimentando a detecção automaticamente (4.3)
- Reparo de categorias runtime/import sem estratégia — reportadas como
  `no_fix` com a falha registrada (comportamento seguro por design)

### 4. Próximo passo

**Fase 4, item 4.3 — Perception Syncer** (`tools/telemetry.py`) — telemetria
de hardware/serviços para alimentar o Self Repair; depois as 56 Actions (4.4).

---

## [0.8.0] — Fase 4 (item 4.1) — Coder Engine ✅ (2026-09-03)

> **FASE 4 INICIADA — 1/4 itens (Coder Engine).** 17/32 capacidades no roadmap.

### 1. O que foi feito

| Item | Arquivo | Destaques |
|---|---|---|
| **4.1 Coder Engine** | `core/coder.py` | Pipeline **sandbox → testes → backup → promoção**: (1) conteúdo patcheado materializado em `<root>/.od_sandbox/<change_id>/` (original intocado); (2) testes = syntax check `compile` para `.py` + runner injetado sync/async OU `test_command` em subprocess (cwd=sandbox, tokens `{file}`/`{sandbox}`/`{root}`/`{relpath}`, timeout) — falha nunca promove; (3) backup versionado do original em `.od_backups/<arquivo>.<change_id>.bak` antes de qualquer escrita; (4) promoção por escrita atômica (tmp + `os.replace`) · diffs unificados nativos stdlib (`parse/apply/generate/diff_stats`): múltiplos hunks, arquivo vazio, sem-newline-final (marcador `\\ No newline`), **relocation** (arquivo derivado) e rejeição de diffs fora de ordem · escopo estrito §7.1 (root, proteção de `.git`/áreas internas, rejeição de caminhos fora do root) · gate Security Layer na promoção (`coder.promote`, fail-closed em strict) · eventos `coder.started`/`coder.completed` no Event Bus · `TestOutcome`/`CoderResult`/`CoderMetrics` + trilha + `dump()` · logging NICKY via `core/logger.py` · zero dependências novas |
| — | `tests/test_coder.py` | **59 testes** (diffs, round-trips extremos, escopo, pipeline, falhas com arquivo intacto, runner/command/timeout, security, event bus, métricas) |

### 2. Evidência

```
.venv/bin/python -m pytest tests/test_coder.py -q   → 59 passed
.venv/bin/python -m pytest tests/ -q               → 756 passed, 0 falhas
```

### 3. O que NÃO foi feito

- **Fase 4 (3/4 restantes)**: Self Repair (4.2), Perception (4.3), 56 Actions (4.4)
- Suporte a multi-arquivos por mudança (patch de diretório inteiro) — o
  Coder Engine opera por arquivo; sandbox de workspace completo é tema do
  Self Repair/evolução futura
- Mudanças exclusivas de quebra de linha final são tratadas como no-op
  (normalização do difflib) — registrado aqui como decisão

### 4. Próximo passo

**Fase 4, item 4.2 — Self Repair** (`core/self_repair.py`) — detecção de
falhas + geração de correção sobre o Coder Engine; depois Perception (4.3)
e 56 Actions (4.4).

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
| 0.7.0 | **Fase 3 completa (3.4)** — Orchestrator Pipeline | 2026-09-03 (publicado) | `cf4eefa` |
| 0.8.0 | **Fase 4 (4.1)** — Coder Engine | 2026-09-03 (publicado) | `a97f9f5` |
| 0.9.0 | **Fase 4 (4.2)** — Self Repair Engine | 2026-09-03 (publicado) | `8066ea4` |
| 0.10.0 | **Fase 4 (4.3)** — Perception Syncer | 2026-09-03 (publicado) | `8066ea4` |
| 0.11.0 | **Fase 4 COMPLETA (4.4)** — 56 Actions | 2026-09-03 (esta entrega) | commit desta entrega |

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
