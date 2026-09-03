# OMEGA DRAKON — README DE VERSÃO

> **Finalidade:** persistir o relatório do protocolo §2.1 (REGRAS_DE_TRABALHO.md)
> de **cada versão/fase entregue** — para que nenhum trabalho, decisão ou
> pendência se perca, mesmo entre sessões.
> **Regra:** a versão mais recente fica no topo. Toda fase concluída adiciona
> uma seção aqui ANTES de ser publicada no GitHub.
> **Assinatura:** `OD // CORE`

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
