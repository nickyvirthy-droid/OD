# OMEGA DRAKON — CHANGELOG

 Registro de implementações e mudanças significativas do sistema.

---

## [0.27.0] — 2026-09-04

### Adicionado

#### Orchestrator — Execução de Ações via ActionRegistry (`core/orchestrator.py`) — Fase 7.4 ✅

**FASE 7.4 — Integração do Orchestrator com o Catálogo de Ações.** O
Orchestrator agora suporta `execute_action()` para executar ações do catálogo
via ActionRegistry, com controle de acesso via Security Layer:

- **`Orchestrator.execute_action(action_name, params, user_id, role)`** —
  executa uma ação via ActionRegistry (ou callable injetado via `add_action()`)
- **`Orchestrator.set_action_registry(registry)`** — define o ActionRegistry
- **`Orchestrator.add_action(name, handler)`** — adiciona uma ação injetável
- **Controle de acesso**: role "admin" para ações restritas, "agent" para
  públicas; Security Layer gate nas execuções

### Testes

- `tests/test_orchestrator.py` — 9 novos testes de integração (`TestOrchestratorActionRegistry`):
  - `test_execute_action_with_registry` — registro conectado
  - `test_execute_action_success` — system_info executado
  - `test_execute_action_datetime` — datetime executado
  - `test_execute_action_with_params` — action_info com params
  - `test_execute_action_action_list` — listagem de 56 actions
  - `test_execute_action_without_registry_raises` — RuntimeError sem registry
  - `test_execute_action_denied_role` — role "agent" sem permissão
  - `test_set_action_registry` — set_registry funciona
  - `test_execute_action_after_set_registry` — execução após set
- Suíte completa: **1344 passed, 0 falhas** (1335 + 9)

### Corrigido

- Documentação: SOUL.md e IDENTITY.md atualizados com catálogo de 56 actions
  e níveis de acesso (§8 do SOUL.md)
- Launcher: integração do ActionRegistry com o Orchestrator no telegram mode

### Infraestrutura

- `core/orchestrator.py` — propriedades `action_registry` e métodos
  `set_action_registry()`, `add_action()`, `execute_action()`
- `runtime/launcher.py` — `build_action_registry()` + integração com bot e
  orchestrator no modo telegram
- `integrations/telegram/commands.py` — comando `/executa` com classificação
  de risco (3 níveis) e controle de acesso
- `integrations/telegram/bot.py` — suporte a `action_registry` no construtor

---

## [0.26.0] — 2026-09-04

### Adicionado

#### Storage — Database Layer (`storage/database.py`) — Fase 7, item 7.5 ✅

**FASE 7 COMPLETA — 5/5 itens · 37/37 capacidades do roadmap.** Camada de
persistência relacional em **SQLite stdlib** (sem SQLAlchemy — decisão do
roadmap "preferir stdlib; isolar em adapters"):

- **`ConnectionPool`** — pool de conexões thread-safe por fila
  (`queue.Queue`, criação sob demanda até `size`; acquire bloqueia quando
  esgotado — sem estouro de conexões); **`:memory:` com URI única por
  pool** (`file:od_mem_<uuid>?mode=memory&cache=shared`) — cada conexão
  enxerga o MESMO banco (senão transações/queries entre conexões
  quebrariam); WAL para banco em arquivo; `close()` limpo
- **`Database`** — execução com pool:
  - `execute`/`executemany` (commita, rowcount) · `query` (linhas como
    dicts, `limit`) · `scalar`
  - **`transaction()`** com **afinidade de conexão por thread**
    (thread-local): operações dentro do bloco usam a MESMA conexão da
    transação — commit no sucesso, **rollback total em erro** (corrigido
    no desenvolvimento: sem afinidade, cada execute commitava fora da tx)
  - `create_table(schema declarativo)`/`tables()`/`table_info()`
  - Métricas (queries, writes, transactions, commits, rollbacks, errors,
    avg_latency_ms) · `health()`/`snapshot()`/`dump()` · NICKY
- **`Repository`** — repositório CRUD genérico (`insert`/`get`/`update`/
  `delete`/`all`/`find(**filters)`/`count`/`exists`) com schema que
  auto-cria a tabela e pk configurável
- **Catálogo de actions plugado** — `configure_database(db)` liga as 3
  actions de banco (`database_tables`/`database_schema`/`database_query`)
  à camada real; sem injeção, continuam degradando graciosamente
  (mensagem "Fase 7.5" preservada — testes antigos intactos)
- **Launcher** — `build_database()` cria `data/od.db` e injeta no
  catálogo; o Health Monitor ganhou o check `database` (não-crítico)

### Infraestrutura

- `tests/test_database.py` — 24 testes: Database (execução/schema/métricas/
  health), transações (commit/rollback com afinidade de conexão), pool
  (roundtrip/close), persistência em arquivo entre instâncias, isolamento
  de `:memory:`, Repository (CRUD completo) e integração das actions de
  banco (degradação sem DB + funcionamento com configure_database)
- Suíte completa: **1359 passed, 0 falhas** (1335 + 24)
- **FASE 7 FECHADA (5/5)**: Audit System (7.1), Metrics Collector (7.2),
  Health Check (7.3), Plugin System (7.4), Database Layer (7.5) —
  **37/37 capacidades do roadmap**

### Corrigido

#### MQTT — race de shutdown: disconnect durante o handshake deixava `_connected` preso 🐛

- **Sintoma:** `test_start_stop_thread` falhava de forma intermitente sob
  carga (suíte completa): o thread do bridge morria, mas
  `bridge.is_connected` seguia True
- **Causa raiz:** `MQTTClient.connect()` só atribuía `self._sock` DEPOIS
  do handshake. Se `disconnect()` rodasse durante o handshake, não
  encontrava sock para fechar; o connect em andamento completava em
  seguida e setava `_connected = True` — para sempre (o disconnect já
  tinha passado)
- **Correção:** o sock é registrado em `self._sock` IMEDIATAMENTE após
  `create_connection` (antes do handshake) e limpo nos caminhos de erro —
  um disconnect durante o connect fecha o sock e aborta o handshake
- **Verificação:** suíte completa **1359 passed** em 4 execuções seguidas
  (antes: falha em ~2 de 3); 54 testes de MQTT verdes

---

## [0.25.0] — 2026-09-04

### Adicionado

#### Plugin System (`plugins/`) — Fase 7, item 7.4 ✅

**FASE 7 — 4/5 itens.** Carregamento dinâmico de plugins Python com
registro de actions no Action Registry e de workflows no Workflow Engine
(espelho do PluginLoader legado NV: subdiretórios `actions/`, `providers/`,
`workflows/`, `integrations/`):

- **Contratos de plugin** (avaliados nesta ordem):
  1. `PLUGIN = {"name", "version", "description", "actions": [...],
     "workflows": [...]}`
  2. `ACTIONS = [...]` e/ou `WORKFLOWS = [...]`
  3. `register_actions(registry)` e/ou `register_workflows(engine)` —
     nomes rastreados por diferença antes/depois da chamada
- **`PluginManager`** (`plugins/manager.py`):
  - Descoberta na raiz + subdiretórios do legado NV; `load_all()`/
    `load_source()` — falha de import de um plugin NUNCA impede os demais
    (isolamento por módulo, CRIT + contador failed)
  - **Registro**: actions no `ActionRegistry` com `permission="plugin.<nome>"`
    (gate do Security Layer na execução — padrão da auto_extension) e
    `source="plugin:<nome>"`; workflows no `WorkflowEngine.register`
  - **Hot-reload**: `reload(name)`/`reload_all()` desregistram os artefatos
    ANTES de recarregar do disco; `unload(name)` remove actions
    (`registry.unregister`) e workflows (`engine.unregister`)
  - **Escopo estrito §7.1**: arquivo fora do root → `PluginScopeError`;
    `__init__.py`/`manager.py` são internos e ignorados
  - Event Bus best-effort (`plugin.loaded`/`failed`/`unloaded` — publica
    só com loop ativo, nunca quebra a carga) · métricas (discovered,
    loaded, failed, actions/workflows_registered, errors) · `health()`/
    `snapshot()`/`dump()` · `list_plugins()`/`get()`/`has()` · NICKY
- **Launcher** — `build_plugins()`: ActionRegistry + WorkflowEngine +
  PluginManager sobre `plugins/` do repo (hoje 0 plugins — pronto para
  receber plugins reais em `plugins/actions/` etc.)

### Infraestrutura

- `tests/test_plugins.py` — 20 testes: contratos (PLUGIN dict, vars,
  register_*), registro/execução de actions + workflows, permission
  namespaced, descoberta em subdiretórios, plugin quebrado isolado,
  módulo sem contrato pulado, escopo estrito, arquivos internos ignorados,
  unload/reload/reload_all, sem registry (0 artefatos) e introspecção
- Suíte completa: **1335 passed, 0 falhas** (1315 + 20)

---

## [0.24.0] — 2026-09-04

### Adicionado

#### Observabilidade — Health Check (`observability/health.py`) — Fase 7, item 7.3 ✅

**FASE 7 — 3/5 itens.** Verificação de status dos componentes do
OmegaDrakon em módulo dedicado, 100% stdlib:

- **`ComponentHealth`** — resultado tipado por componente (name, ok,
  status up/degraded/down, detail, latency_ms, critical) com `to_dict()`
- **`HealthMonitor`** — checks registráveis por componente (`register`/`unregister`,
  sync OU async — inspeção de awaitable, padrão do ProactiveNotifier):
  - **Agregação em 3 níveis**: check **crítico** falho → status geral `down`;
    não-crítico falho → `degraded`; todos ok → `up`
  - `check(name)` individual · `health()` agregado (ok/status/checks/ts) ·
    métricas (runs, checks_run, ok/failed, errors, avg_latency_ms com
    relógio injetável) · `snapshot()`/`dump()` · thread-safe
  - **Resiliência**: check que levanta exceção vira falha do componente
    (detail "check quebrado"), nunca derruba o monitor
- **API REST integrada** — `APIConfig.health` (opcional): quando presente,
  o GET /health responde o agregado do monitor (inclui `uptime_s`); sem
  monitor, o comportamento legado (orchestrator/llms) é preservado
- **Launcher** — `build_health(orchestrator, audit, metrics)` com 4 checks:
  `orchestrator` e `llm` **críticos** (derrubam para down), `audit` e
  `metrics` não-críticos (degradam); o monitor é passado à API em todos os
  modos (`api`/`all`)

### Infraestrutura

- `tests/test_health.py` — 17 testes: ComponentHealth (defaults/to_dict),
  HealthMonitor (registro, check individual, agregação up/degraded/down,
  ComponentHealth direto, check async, check quebrado resiliente, latência,
  unregister, snapshot/dump) e integração API (agregado no /health, status
  down propagado, retrocompatibilidade sem monitor)
- Suíte completa: **1315 passed, 0 falhas** (1298 + 17)

---

## [0.23.0] — 2026-09-04

### Adicionado

#### Observabilidade — Metrics Collector (`observability/metrics.py`) — Fase 7, item 7.2 ✅

**FASE 7 — 2/5 itens.** Coletor central de métricas operacionais com
exposição no **Prometheus text exposition format**, 100% stdlib (sem
prometheus_client — mesma linha das demais integrações):

- **`Metric`** — métrica tipada counter/gauge com **labels** (`inc`/`dec`/
  `set`/`value`), validação rígida de labels (faltando/extra → ValueError),
  valores isolados por combinação de labels, `snapshot()` e `sample_lines()`
  com escape correto de valores de label (`\`, `"`, `\n`)
- **`MetricsCollector`** — registro central:
  - `counter()`/`gauge()` com **registro idempotente por nome** (mesmo tipo
    devolve a métrica existente; tipo diferente → ValueError) e validação de
    nomes Prometheus (`od_*`); `get()`
  - **Fontes vivas (`add_source`)** — componentes externos contribuem
    linhas completas no `render()` sem registrar métrica por métrica
    (uptime, Orchestrator, Audit); fonte quebrada NUNCA quebra o render
    (contador `errors` + WARN)
  - `render()`/`text()` — `# HELP` + `# TYPE` + amostras + fontes, ordem
    determinística de registro · `snapshot()` · `health()` · `dump()`
    · thread-safe
- **API REST integrada** — `APIConfig.metrics` (opcional): quando presente,
  o servidor registra `od_api_requests_total`/`od_api_errors_total` no
  coletor (`count_request`/`count_error`) e o **GET /metrics renderiza o
  coletor** (que inclui as fontes do launcher); sem coletor, o
  comportamento inline legado é preservado (retrocompatível — testes
  antigos intactos)
- **Launcher** — `build_metrics(orchestrator, audit)` com fontes vivas de
  uptime, Orchestrator (od_processed/llm/fallback/cache/quick/datetime/
  rate_limited/errors) e Audit (od_audit_total/persisted/allowed/denied/
  failed/errors); o coletor é passado à API em todos os modos
  (`api`/`all`)

### Infraestrutura

- **Correção de teste pré-existente** (`tests/test_config_manager.py`):
  `test_init_without_yaml` assumia ambiente sem vars `OD_*` — o servidor
  define 5 (API key, admins, vision...). Teste agora isola o ambiente
  (monkeypatch `OD_*`) — hermético em qualquer máquina. Alinha a suíte com
  o §8 (nenhuma fase é promovida com testes vermelhos)
- `tests/test_metrics.py` — 24 testes: Metric (counter/gauge, labels,
  valores, amostras com escape), MetricsCollector (registro idempotente,
  conflito de tipo, nomes inválidos, render Prometheus, fontes vivas,
  resiliência, snapshot/health/dump) e integração API (GET /metrics
  renderiza o coletor com od_api_*, contagem de requests e erros,
  retrocompatibilidade sem coletor, fonte externa no mesmo render)
- Suíte completa: **1298 passed, 0 falhas** (1274 + 24) — primeira suíte
  100% verde desde a ativação (a falha ambiental pré-existente foi
  corrigida)

---

## [0.22.0] — 2026-09-04

### Adicionado

#### Observabilidade — Audit System (`observability/audit.py`) — Fase 7, item 7.1 ✅

**FASE 7 INICIADA — 1/5 itens.** Trilha de auditoria contínua e PERSISTENTE
de todas as decisões do sistema (spec §7.3), dedicada em `observability/`:

- **`AuditEntry`** — registro tipado e imutável (ts, id, source, action,
  outcome, severity, actor, session_id, detail, data) com round-trip
  `to_dict`/`from_dict`
- **`AuditSystem`** — serviço de auditoria:
  - **Persistência JSONL append-only** (`file_path`, default `logs/`
    audit.jsonl): rotação automática por tamanho (`max_bytes`, 5MB) com
    retenção de backups (`keep`, 3) e recarga da trilha existente no
    startup — a fonte de verdade é o arquivo, o ring buffer em memória é
    só cache de consulta; sobrevive a reinícios
  - **Registra TODA decisão de segurança**: `record_decision()` aceita
    `SecurityDecision`/`AuditRecord` (outcome allowed/denied, CRIT para
    negada, origem/modo/denied_by/reasons preservados) e `make_sink()`
    pluga o AuditSystem direto no `AuditEngine` do Security Layer — toda
    decisão do pipeline cai na trilha persistente
  - **Event Bus** (`audit.record`) + sinks de encaminhamento (sync/async)
    entregues no caminho `record_async` (padrão ProactiveNotifier — o
    caminho sync `record()` nunca depende de event loop)
  - Consultas: `history`/`search` (case-insensitive, inclui data
    serializada)/`since`/`by_action`/`counts` · métricas (total, persisted,
    failed, allowed, denied, errors) · `health()` (trilha gravável?) ·
    `snapshot()`/`dump()`/`clear()` · clock injetável
  - **Resiliente por construção**: sink quebrado, payload não serializável,
    arquivo ilegível ou sem permissão NUNCA derrubam a trilha (contadores
    `failed`/`errors` + log WARN) — `record()` nunca levanta exceção
- **Launcher**: `build_audit_system()` + env `OD_AUDIT_FILE` (default
  `logs/audit.jsonl` na raiz); o `od-core` registra `system.startup`
  (modo + pid) em todos os modos

### Testes

- `tests/test_audit.py` — 36 testes: AuditEntry (round-trip, isolamento),
  trilha em memória (ordem/limite/ring, busca, filtros, counts, clear),
  persistência (JSONL, reload entre instâncias, linha corrompida, rotação
  com keep, clear truncando, caminho sem permissão), integração Security
  Layer (record_decision com SecurityDecision/AuditRecord, make_sink no
  AuditEngine E2E, decisão persistida em arquivo, sink quebrado) e Event
  Bus/sinks async (publicação `audit.record`, sync/async, sem duplicação,
  sync não entrega fora de loop)
- Suíte completa: **1272 passed** (1238 anteriores + 36 novos)

### Observações de suíte

- `test_config_manager.py::test_init_without_yaml` falha no ambiente por
  variáveis `OD_*` presentes (`.env`/env do servidor) — falha PRÉ-EXISTENTE,
  confirmada com as mudanças da 7.1 stashed (sem relação com esta entrega)
- `test_mqtt.py::test_start_stop_thread` é flaky (timing de thread) — passa
  consistentemente em execuções isoladas

---

## [0.21.0] — 2026-09-03

### Adicionado — Voz real no Telegram 🎤🔊

#### STT real no bot (`integrations/telegram/voice.py`)

- `TelegramVoiceSTT` — adaptador async que liga o pipeline de voz do bot
  (14º recurso) ao `WhisperSTT` real (6.3): bytes do áudio recebido (ogg)
  gravados em temp e transcritos via ffmpeg + whisper-cli
- `TelegramBot._decode_voice` agora é async e aceita decoders **sync OU
  async** (inspect.isawaitable) — testes antigos continuam válidos

#### TTS real no bot

- `TelegramVoiceTTS` — adaptador async sobre o `PiperTTS` real (6.4),
  com voz por perfil (dii default / faber regulus)
- `TelegramBot` ganhou `tts` plugável + `_send_voice_reply`: recebeu voz →
  transcreve → pipeline → **responde por voz** (sendVoice multipart); se a
  síntese falhar, cai para texto (nunca silencia)

#### Transporte

- `send_voice(chat_id, audio, duration_s)` nos dois transportes:
  `HTTPTransport` com **multipart/form-data em stdlib puro**
  (`build_multipart`, sem dependências) via sendVoice; `InMemoryTransport`
  registra em `sent_voices`
- `sent_texts` filtra entradas de voz (não quebra mais)

#### Launcher

- `build_telegram_bot` conecta STT+TTS reais quando os binários existem
  (envs: `OD_VOICE_STT`, `OD_VOICE_TTS`, `OD_VOICE_PROFILE`) — validado
  ao vivo no od-core (journal: "Voz STT habilitada" + "Voz TTS habilitada")

### Testes

- `TestSendVoice` (multipart stdlib, InMemory, HTTP ok/vazio) +
  `TestTelegramBotVoiceReply` (STT async, resposta por voz, fallback texto,
  TTS sync) — 9 novos, total **1238 passed**

### Validação real

- **sendVoice E2E contra a Bot API**: voz sintetizada pelo Piper enviada
  ao chat do admin (342KB, `ok: true`) — mensagem de voz de teste recebida
  no Telegram

---

## [0.20.0] — 2026-09-03

### Adicionado — Fase 6 COMPLETA (6/6 itens) 🧠

#### 6.1 — Face Detection (`tools/vision/face_detector.py`)

- Haar Cascade + CLAHE + ROI guard (10% bordas) + **buffer de confirmação**
  3/2 (espelho do legado Nicky) — presença facial estável, sem alarme falso
- Webcam **real do servidor** encontrada (/dev/video0, Alcor Micro 1080P) e
  validada: frame 1280×720 capturado, cascade carregado, 0 rostos (correto)
- **OpenCV 4.14.0 fixado** (pip install opencv-python-headless==4.14.0.88):
  o OpenCV 5.0 removeu o `CascadeClassifier` (Haar) — decisão registrada
- Capture plugável (testes sem webcam), Event Bus (`face.presence`),
  métricas, salvamento de frames com limite diário

#### 6.3 — Audio STT (`tools/audio/stt.py`)

- `WhisperSTT`: whisper.cpp via subprocess assíncrono + ffmpeg (WAV 16kHz
  mono) — padrão do legado `vision/audio_capture.py`, sem estado (modelo
  não fica residente em RAM)
- Binário e modelo **reais do legado reaproveitados** (whisper-cli
  compilado + ggml-base.bin, 148MB) — nenhum download novo

#### 6.4 — TTS Piper (`tools/audio/tts.py`)

- `PiperTTS`: síntese por subprocess com **vozes por perfil** — `dii`
  feminina (default) / `faber` masculina (regulus)
- Binário e vozes pt-BR reais do legado (piper + 2 modelos .onnx)
- **E2E real validado**: Piper sintetizou → whisper transcreveu de volta
  (3.2s total) — o loop voz completo funciona no servidor

#### 6.5 — Profile Manager (`agents/profiles.py`)

- Os 6 perfis oficiais: Guardian 🛡️, Regulus ⚖️, Luma 🌟, Vox 📢,
  Athenae 🏛️, Nyx 🌙 — com system prompts, domínios e prioridade
- **Detecção automática por domínio**: tokenização + radical (≥4 letras),
  stopwords curtas ignoradas — "aprender" casa com "aprendizado",
  "monitore" com "monitoramento"
- Plugada no bot: perfil `auto` agora detecta pelo texto da mensagem
  (`_resolve_auto(profile, text)`) — antes caía sempre no default
- `resolve(requested, context)`: explícito > detecção > default + perfis
  customizados via `add_custom_profile`

#### 6.6 — Auto Extension (`tools/auto_extension/`)

- `AutoExtension`: geração de ferramentas via **LLM** (prompt com assinatura
  fixa + allowlist) — extrai código dos fences, valida em 2 estágios
  (**compile** sintático + **allowlist de imports** stdlib, sem executar o
  corpo) e registra no Action Registry como Action com
  `permission="auto_extension.generated"` — **toda execução futura é
  mediada pelo Security Layer** (spec §7)

#### Runtime

- Launcher: modo `vision` + `OD_VISION_ENABLED` (default 0) — FaceDetector
  com notificação Telegram na confirmação de presença; docs de env atualizados

### Testes

- `tests/test_audio.py` (16: STT + TTS com subprocess mockado),
  `tests/test_profiles.py` (13), `tests/test_auto_extension.py` (13),
  `tests/test_face_detector.py` (24) e `TestResolveAutoProfile` no bot (3)
  — **1229 passed** (1153 + 76)

---

## [0.19.0] — 2026-09-03

### Adicionado

#### Web — Chat funcional + política de shells públicos (decisão do usuário) 💬

Com o `auth_all` (0.17.2) o GET `/chat` passou a exigir `X-API-Key` — e
navegador não envia header custom, então a página pedia chave e não abria.
Correção com a arquitetura certa:

- **Shells de página públicos (sem dados):** `APIConfig.page_shells_public`
  (default True) — com `auth_all`, o GET de `/chat` e `/dashboard` (HTML
  estático) continua aberto para o navegador carregar a UI; **toda** chamada
  de dados/API (incluindo `POST /message`) segue exigindo a chave
- **`/chat` funcional** (`_CHAT_PAGE_HTML`): página HTML+JS vanilla (sem
  dependência) com gate da chave — informada **uma vez**, fica na
  `sessionStorage` da aba (nunca na URL) — e conversa real com o OD via
  `POST /message` (perfil selecionável, bolhas, erros tratados, 401 limpa a
  chave e volta ao gate)
- **`/dashboard` estático**: shell sem números vivos — métricas só via
  `GET /dashboard/stats` (chave)
- `page_shells_public=False` fecha também os shells (modo estrito)

### Infraestrutura
- **2 testes novos** (shells abrem sem chave mas sem dados + flag False
  fecha; asserts no HTML do chat/dashboard)
- Suíte completa: **1153 testes, 0 falhas** (1151 + 2)
- **Regra nova** no `docs/REGRAS_DE_TRABALHO.md` §10: autorização
  permanente do Alex para instalar ferramentas necessárias + shells web
  nunca pedem chave manual (dados sempre com chave)
- E2E ao vivo: `/chat` 200 sem chave · `/health`/`/llms` 401 sem chave ·
  `/llms` 200 com chave · `POST /message` com chave → resposta real do gemma

---

## [0.18.0] — 2026-09-03

### Adicionado

#### Sensorial — Presence Monitor (`integrations/homeassistant/presence.py`) — Fase 6, item 6.2 ✅

**FASE 6 — 1/6 itens.** Monitor de presença que o OD não tinha — por isso
nada era detectado quando o usuário aparecia no Home Assistant:

- `PresenceMonitor` sobre o HA real: lê `person.*`/`device_tracker.*`
  periodicamente (back-end plugável com `list_states()` — HAClient real ou
  InMemoryHAServer nos testes), classifica home/away (**unknown conta como
  away** — evita falso positivo no boot do HA) e detecta transições de
  **chegada/saída**
- Transição → **Event Bus** (`presence.changed`) + **sinks plugáveis**
  (sync/async, Telegram no launcher) com texto formatado 🏠/🚶 · métricas
  (polls/states_read/transitions/arrivals/departures/errors) · `history()`/
  `snapshot()`/`dump()`/`health()` · NICKY
- **Baseline silencioso + estado persistido** (`state_file` JSON): a
  primeira observação registra sem evento e reinícios não disparam
  transições falsas nem mensagens duplicadas
- **Rodando no `od-core`**: launcher lê `config/iot_credentials.json`
  (envs `OD_PRESENCE_ENABLED`/`OD_PRESENCE_POLL_S`/`OD_HA_CREDENTIALS`),
  monitora o HA real (34 entidades) e **notifica o admin no Telegram**
  quando alguém chega/sai · aviso único de ativação persistido (flag) —
  sem spam em reinícios
- **Decisão registrada:** presença via entidades do HA (person/device_tracker)
  em vez de câmera — entregue antes da Face Detection (6.1), que continua
  e alimentará o mesmo barramento

### Infraestrutura
- **26 testes novos** em `tests/test_presence.py` (classificação, nomes,
  transições, filtros, Event Bus, sinks, persistência/restart, introspecção)
- Suíte completa: **1151 testes, 0 falhas** (1125 + 26)
- **ROADMAP: 26/32 capacidades** — Fase 6 com 1/6 itens
- Validado ao vivo: leitura real do HA (34 estados, baseline silencioso) e
  aviso de ativação enviado ao Telegram do admin

---

## [0.17.2] — 2026-09-03

### Alterado

#### API REST — X-API-Key exigida em TODOS os endpoints (`auth_all`) 🔒

Com o bind exposto na LAN (0.0.0.0, v0.17.1), os endpoints públicos
(`/`, `/health`, `/profiles`, `/dashboard`, `/chat`, `/metrics`, ...)
ficaram acessíveis sem chave de qualquer máquina da rede — agora exigem a
chave também:

- `APIConfig.auth_all` (default False): quando True, o gate de auth cobre
  TODAS as rotas (públicas e protegidas) — header `X-API-Key` obrigatório
- `auth_all=True` sem `api_key` configurada **nega tudo** com 401 + log de
  erro (força o operador a definir `OD_API_KEY` antes de expor na LAN)
- Launcher: `OD_API_AUTH_ALL` (default **1**) — o `od-core` em produção
  roda com a chave exigida em todos os endpoints
- CORS preflight (OPTIONS) permanece aberto por construção (o navegador
  manda a chave na requisição real, não no preflight)

### Infraestrutura
- **5 testes novos** em `tests/test_api.py` (`TestAuthAll`: públicos negam
  sem chave, protegidos idem, chave errada, auth_all sem chave nega tudo,
  auth_all off preserva o comportamento dev/local)
- Suíte completa: **1125 testes, 0 falhas** (1120 + 5)
- Verificado ao vivo na LAN: sem `X-API-Key` → 401 em `/health`, `/metrics`,
  `/llms`; com chave → 200 (inclusive `/dashboard`)

---

## [0.17.1] — 2026-09-03

### Corrigido

#### Telegram — loop infinito de reprocessamento (offset) 🐛

**Sintoma em produção:** o bot respondia/apitava sem parar, reprocessando a
mesma mensagem a cada poll.

- **Causa raiz:** `TelegramBot.run()` confirmava com `offset = update_id` em
  vez de `update_id + 1`. O Telegram só confirma updates com `update_id <
  offset` — sem o `+1`, o servidor **reentrega o mesmo update para sempre**
  e o bot respondia em loop (agravado por respostas longas do LLM local). O
  `InMemoryTransport` mascarava o bug (watermark avançava mesmo com offset
  errado) — por isso os testes não pegaram
- **Correção:** `self._offset = update.update_id + 1` (semântica real do
  servidor) + **offset persistido em arquivo** (`offset_file`, default em
  `data/telegram_offset.json`) — reinícios nunca reprocessam updates já
  confirmados
- **Testes alinhados:** `InMemoryTransport` agora imita o servidor real
  (`getUpdates(offset=N)` confirma `update_id < N` e devolve `>= N`) — a
  regressão do loop passa a ser detectável em teste; +2 testes novos
  (offset avança para último+1 e persistência entre bots)
- **Verificado ao vivo:** bot respondeu o backlog preso (1x via LLM + 1x
  cache) e ficou **ocioso** — mensagens novas são respondidas uma única vez

#### API REST — acesso pela LAN (site) 🐛

- **Sintoma:** `http://192.168.0.250:8000` não abria de outro dispositivo
- **Causa:** a API bindava só em `127.0.0.1` (hardcoded no launcher)
- **Correção:** bind via `OD_API_HOST` (default **0.0.0.0** — LAN/site);
  `OD_API_KEY` gerada e gravada no `.env` (endpoints protegidos seguem
  exigindo `X-API-Key`; páginas públicas continuam abertas)

### Infraestrutura
- `runtime/launcher.py`: `offset_file` do bot + `OD_API_HOST` no docstring
- Suíte: **1120 testes** (1118 + 2 de regressão)

---

## [0.17.0] — 2026-09-03

### Adicionado

#### Integrações — MQTT Bridge (`integrations/mqtt/`) — Fase 5, item 5.5 ✅

**FASE 5 — 5/5 COMPLETA.** Ponte para broker MQTT 3.1.1 (Mosquitto) em
**stdlib puro** (sem paho-mqtt — protocolo wire implementado):

- `protocol.py` — codec MQTT 3.1.1: CONNECT/CONNACK (códigos tipados),
  PUBLISH QoS 0 e 1 (PUBACK), SUBSCRIBE/SUBACK com grant por filtro,
  UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP, DISCONNECT, retained ·
  validação de tópicos e filtros (MQTT-4.7: '+' nível único, '#' final) ·
  `topic_matches` com curingas · `MqttMessage` (bytes + helper `.text()`)
- `client.py` — `MQTTClient` real sobre socket stdlib: handshake validado,
  thread de leitura com fila + callbacks, **PUBACK síncrono (QoS 1)**,
  SUBACK aguardado, keepalive (PINGREQ) em thread, `shutdown()` antes do
  close (acorda recv bloqueado — sem thread presa), detecção de queda
- `broker.py` — `InMemoryBroker`: broker fake em processo (TCP loopback)
  com o MESMO wire protocol — CONNECT/CONNACK (com recusa configurável),
  assinaturas com curingas, roteamento QoS mínimo entre publicação e
  grant, retained (entrega a novos assinantes, limpeza por payload vazio),
  drop de sessão, stats — testes determinísticos sem broker externo
- `bridge.py` — `MQTTBridge`: assina filtros com handlers · mensagens
  recebidas → **Event Bus** (`mqtt.message`) · roteamento **bus→MQTT**
  (`route_bus`, default `od/<tópico do bus com . → />`) · reconexão com
  re-assinatura automática · `poll_once`/`run`/`start`/`stop` (thread) ·
  métricas (connects/reconnects/published/received/handlers/bus) ·
  `health()`/`snapshot()`/`dump()` · NICKY
- **Integração real**: `runtime/launcher.py` ganhou o modo `mqtt` e a
  ponte no `all` (env `OD_MQTT_*`: host/port/client_id/subscribe,
  `OD_MQTT_ENABLED=0` desliga) — o `od-core` em produção agora assina
  `od/in/#` e repassa ao Event Bus

### Infraestrutura
- **54 testes novos** em `tests/test_mqtt.py` (codec, validação/curingas,
  cliente real ↔ InMemoryBroker em loopback, QoS 0/1, retained, keepalive,
  bridge com Event Bus, roteamento, reconexão, ciclo de vida)
- Suíte completa: **1118 testes, 0 falhas** (1064 + 54)
- **ROADMAP: 25/32 capacidades** — **Fase 5 FECHADA (5/5)**: Telegram
  (5.1), API REST (5.2), Notifier (5.3), IoT Manager (5.4), MQTT (5.5)
- **E2E ao vivo**: validação contra o Mosquitto real (127.0.0.1:1883,
  anônimo): CONNECT ok, pub/sub com self-delivery, rota bus→MQTT→bus

---

## [0.16.0] — 2026-09-03

### Adicionado

#### Ativação Real — Omega Drakon NO AR (LLM + API + Bot + HA) 🟢

**Primeira entrega operacional.** O sistema saiu do código e foi colocado para
funcionar de verdade no servidor (`nicky-server`, usuário `alex`):

- **`core/llm.py`** — `OpenAICompatProvider`: o elo que faltava entre o
  Orchestrator e um LLM real. Fala com servidores OpenAI-compat em **stdlib**
  (urllib): converte o ChatML do Orchestrator em `messages` nativas,
  `chat()` sync/async, `is_available()` (usado pelo ProactiveNotifier),
  timeout configurável, erros tipados (`LLMError`/`LLMUnavailableError`)
- **LLM local no ar** — llama.cpp atualizado (release b10786, com suporte à
  arquitetura gemma4) instalado em `/opt/omegadrakon/ai/runtimes/llama` e
  **gemma-4-E4B-it-Q4_K_M.gguf** (o que já estava baixado) servindo em
  `127.0.0.1:8081` (OpenAI-compat, ctx 16k, 4 threads) — resposta real com
  raciocínio em ~17s em CPU
- **`agents/nicky_virthy/personality.py`** — monta o system prompt da Nicky
  (SOUL/IDENTITY + hierarquia da Tríade) por perfil (default/guardian/creator/
  analyst/fantasma→guardian) · injeção via
  `OrchestratorConfig.default_system_prompt` (aditivo, default vazio). O gemma
  agora responde como **Nicky Virthy, Interface Viva do Omega Drakon**
- **`runtime/launcher.py`** — sobe o sistema real: Orchestrator com provider
  `gemma-local` + identidade + API REST (8000) + Telegram Bot (polling); logs
  em `runtime/logs/`
- **Segredos** — `.env` do OD com o token legado do Telegram (validado via
  getMe: **@Nicky_Virthy_bot**) e admin `660518870`; `.gitignore` protege
  `.env`, `config/iot_credentials.json` e `data/`; template commitável
  `config/iot_credentials.example.json`
- **Home Assistant migrado e no ar** — config saiu de dentro do nexus
  (`nexus/infra/ha/config`) para `/srv/omegadrakon/homeassistant` (byte a
  byte, incluindo `.storage/` de auth via container root) e o container foi
  recriado apontando para o novo caminho — **OD autossuficiente** (nexus pode
  ser apagado sem levar o HA). Token legado validado contra a API real:
  **IoTManager lendo 29 entidades reais**
- **`runtime/systemd/`** — units de usuário `od-llm.service` (llama-server) e
  `od-core.service` (launcher) + `install-user.sh` (instala, habilita e ativa
  linger). **Instaladas e ATIVAS** sob systemd com auto-start no boot

### Infraestrutura
- **27 testes novos** (`tests/test_llm.py` 17 + `tests/test_personality.py` 10)
- Suíte completa: **1064 testes, 0 falhas** (1037 + 27)
- E2E real: HTTP → Orchestrator → gemma respondendo com identidade Nicky

---

## [0.15.0] — 2026-09-03

### Adicionado

#### Integrações — IoT Manager (`integrations/homeassistant/`) — Fase 5, item 5.4 ✅

**FASE 5 — 4/5 itens.** Integração com Home Assistant do legado Nexus
(`src/iot.py`) em **stdlib** (urllib, sem requests):

- `models.py` — **taxonomia ambiental** (mapeamento por domínio do
  entity_id): atuadores (light/switch/fan/cover/climate/lock/media_player/
  vacuum/input_boolean/humidifier/...), sensores (sensor/binary_sensor/
  number/select/input_number/...), móveis (person/device_tracker), infra
  (camera/automation/script/scene/weather/group/...) e `unknown` ·
  `EntityState` (espelho do `/api/states`; `is_on()`; to/from dict) ·
  `HACredentials` (`base_url`+`token`, validação http(s), carregamento de
  `config/iot_credentials.json` — spec §7: segredos fora do código)
- `client.py` — `HAClient` REST: `GET /api/states` (lista e individual,
  404→None), `POST /api/services/<domínio>/<serviço>` com **Bearer token**,
  `service_available()` (probe), erros HTTP/rede/JSON mapeados para
  `HAError` · **`InMemoryHAServer`** — fake determinístico com a MESMA
  interface (`HABackend`) para testes/dev offline (seed, turn_on/off/toggle
  por domínio, registro de service_calls)
- `manager.py` — `IoTManager` sobre qualquer `HABackend`: `get_entity`/
  `list_entities(filtro por tipo)`/`sensor_reading` (leitura) ·
  `set_power`/`toggle` (controle; domínio do entity define o serviço) ·
  **gate de segurança**: `is_controllable` (só atuadores + `allowed_domains`
  configurável) e `guard(entity_id, action)` injetável — recusa → `denied`
  sem exceção · `snapshot()` agrupado por tipo, `list_types()`, métricas
  (reads/commands/commands_ok/denied/errors), **Event Bus** (`iot.command`)
  e `dump()`

### Infraestrutura
- **45 testes novos** em `tests/test_homeassistant.py` (taxonomia completa,
  EntityState/credenciais, HAClient com rede stubada — headers/erros,
  InMemoryHAServer, controle com gates, Event Bus e métricas)
- Suíte completa: **1037 testes, 0 falhas** (992 + 45)
- **ROADMAP: 24/32 capacidades absorvidas** — Fase 5 com 4/5

---

## [0.14.0] — 2026-09-03

### Adicionado

#### Integrações — ProactiveNotifier (`integrations/notifier.py`) — Fase 5, item 5.3 ✅

**FASE 5 — 3/5 itens.** Notificações proativas do legado Nicky reimplementadas
**100% stdlib** (sem httpx), com health check periódico e alertas com
anti-spam:

- **Sondas embutidas** (contrato `CheckFn`: sync ou async, resultado único
  ou múltiplo):
  - `orchestrator` — conectado ou não (warn)
  - `llm` — providers do Orchestrator com `is_available()` (provider sem
    sonda = disponível); nenhum disponível → **CRIT após `emit_after_s`**
    (padrão 300s — o "LLM offline >5min" do legado); health() acusa
    imediatamente
  - `disk` — `shutil.disk_usage` por path; ≥85% warn, ≥95% crit (padrão
    do legado); path ilegível → `disk:unreadable` sem exceção
  - `restart` — detecção por estado persistido (PID) entre reinícios
- **Anti-spam**: cooldown por chave de alerta (padrão **3600s — 1
  alerta/hora**, igual ao legado), override por chave (`cooldowns`),
  persistido no `state_file` JSON (cooldowns e detecção de restart
  sobrevivem a reinícios); `alerts_blocked` nas métricas
- **Sinks plugáveis** (em vez de httpx acoplado ao Telegram): canais sync
  ou async recebem o texto formatado 🟢🟡🔴 (ex: TelegramBot, log, stdout)
- **Event Bus**: publica `notifier.alert` (payload tipado) quando conectado
- `tick()` (sondas → threshold → anti-spam → sinks → bus → estado),
  `run(interval, max_ticks)` (loop), `start()`/`stop()` (thread daemon),
  `health()` (sondas sem emitir), `snapshot()`/`history()`/`dump()`,
  `NotifierMetrics` (ticks/checks_run/problems/alerts_emitted/
  alerts_blocked/errors) e relógio injetável (testes determinísticos)

### Infraestrutura
- **42 testes novos** em `tests/test_notifier.py` (tipos/formatação,
  sondas com fakes — disco com monkeypatch e restart por estado,
  threshold de LLM, anti-spam/cooldown por chave e persistido, sinks
  sync/async e quebrados, Event Bus, checks customizados sync/lista/async,
  loop e introspecção)
- Suíte completa: **992 testes, 0 falhas** (950 + 42)
- **ROADMAP: 23/32 capacidades absorvidas** — Fase 5 com 3/5

---

## [0.13.0] — 2026-09-03

### Adicionado

#### Integrações — API REST (`integrations/api/`) — Fase 5, item 5.2 ✅

**FASE 5 — 2/5 itens.** Os **17 endpoints do legado Nicky** (interfaces/api.py)
reimplementados **100% stdlib** (http.server `ThreadingHTTPServer` — sem
FastAPI/uvicorn), expondo o Orchestrator via HTTP:

- **Endpoints (mesma tabela do legado §9):** `GET /` (info), `/health`
  (status + LLMs), `/profiles`, `/profiles/{name}`, `/presence/today`,
  `/dashboard` e `/chat` (HTML placeholder), `/metrics` (texto
  Prometheus-style: od_processed_total, od_llm_total, od_api_requests...),
  `/dashboard/stats` (JSON), `/llms` — **POST** `/message` (pipeline:
  user_id/profile/text/system_prompt → `Orchestrator.process()`, perfil
  auto→default, validação 400), `/transcribe` e `/tts` — **DELETE**
  `/history/{user_id}` — `GET /history/{user_id}/stats` e
  `/memory/{user_id}/search` (RAG via `VectorStore`, namespace por user,
  `q` + `top_k` clampado)
- **Segurança:** API key via header `X-API-Key` nos mesmos endpoints
  protegidos do legado (`compare_digest`, 401), **rate limit por IP**
  (janela deslizante, 429 + retry_after, buckets por instância) e CORS
  (preflight OPTIONS 204). Bind padrão `127.0.0.1` (nunca expor sem auth)
- **Camada de áudio plugável**: `config.stt`/`config.tts` injetáveis
  (transcribe/tts funcionais com handler; sem handler → 501 apontando a
  Fase 6.3/6.4)
- `/ws/chat` → **501 registrado** (WebSocket streaming token-a-token exige
  servidor assíncrono dedicado — decisão documentada)
- Roteamento declarativo (`ROUTES` — method/path/auth), erros JSON
  consistentes (400/401/404/405 com Allow/413/429/500/501/502), corpo
  limitado (`max_body_bytes`), `snapshot()` + NICKY
- **Core (aditivo):** `Orchestrator.providers` — propriedade pública
  read-only da lista de providers (usada por `/llms` e `/health`)

### Infraestrutura
- **46 testes novos** em `tests/test_api.py` (tabela de rotas, servidor
  real em loopback por teste, auth, rate limit por IP e por instância,
  message/pipeline com memória real, history/RAG, áudio plugável,
  HTTP behavior 404/405/CORS/413/JSON inválido)
- Ajuste de runtime: `poll_interval` 0.05 no `serve_forever` (shutdown
  rápido de servidores em testes)
- Suíte completa: **950 testes, 0 falhas** (904 + 46)
- **ROADMAP: 22/32 capacidades absorvidas** — Fase 5 com 2/5

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
