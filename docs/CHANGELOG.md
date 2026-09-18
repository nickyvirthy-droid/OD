# OMEGA DRAKON — CHANGELOG

> **Finalidade:** registro das mudanças por versão, conforme item 4 da
> Definition of Done (`docs/REGRAS_DE_TRABALHO.md` §2) — toda capacidade
> entregue entra aqui com data, contagem de testes e fase/versão.
> **Regra:** a versão mais recente fica no topo.
> **Assinatura:** `OD // CORE`

> **Nota histórica (2026-09-12):** este arquivo foi criado em 2026-09-12 na
> auditoria de alinhamento de versão — até então o projeto não tinha
> `docs/CHANGELOG.md` e o histórico da série 0.x está em
> `docs/README_VERSAO.md` (§0.1.0 → §0.28.4). A partir daqui, toda entrega
> passa a registrar entrada neste CHANGELOG **além** do README de Versão.

---

## [1.2.0] — App Android 📱 (2026-09-08 · correções em 2026-09-12, 2026-09-14, 2026-09-15 e 2026-09-18)

### Adicionado

- **App Flutter** em `app/` — telas de chat, ações (catálogo de 57 actions
  via `GET /actions` + `POST /executa`), status (`/health` + manifesto de
  capacidades) e configuração; auth por `OD_API_KEY` no header `X-API-Key`.
- **Push FCM** — `firebase_core` + `firebase_messaging`, com documentação em
  `docs/FIREBASE_SETUP.md`.
- **Compatibilidade de API para o app** — `POST /message` aceita
  `{"message": ...}` além do payload do bot (`tests/test_api.py`).
- **APK release publicado na landing** — `site/OmegaDrakon.apk`
  (build via `app/build_apk.sh`, Flutter 3.47.2 / JDK 17 / Android SDK 36).

### Infraestrutura

- Fonte de verdade da versão do sistema: `OD_VERSION` no `.env`
  (`core/capabilities.py` agora resolve `os.environ` → `OD_VERSION` do `.env`
  → fallback congelado `1.2.0`, o que faz o valor chegar ao manifesto, à API
  e ao bot mesmo em entrypoints que não usam o carregador do launcher).
- `app/pubspec.yaml` alinhado para `1.2.0+3` (antes `1.0.0+1`, o que fazia o
  APK reportar `versionName 1.0.0` enquanto a landing anunciava v1.2.0).
- `docs/CHANGELOG.md` criado; seções v1.0.0/v1.1.0/v1.2.0 do
  `docs/README_VERSAO.md` reconstruídas retroativamente.

### Testes

- `app/`: **36 testes** Flutter (`flutter test`) + `flutter analyze` limpo
  (2026-09-12; 27 na entrega original).
- `tests/` (servidor): **1610 passed, 16 skipped** (suíte completa, auditoria
  de 2026-09-12); marco da v1.0.0 registrado com **1594 passed**.

### Corrigido (2026-09-12)

- **Tela Status quebrava com o manifesto real** — `status_screen.dart` fazia
  `_capabilities['system'] as Map<String, dynamic>?`, mas o servidor devolve
  `"system": "Omega Drakon"` (string), com `version`, `counts` e `runtime` no
  topo do manifesto. O cast estourava `_TypeError: type 'String' is not a
  subtype of type 'Map<String, dynamic>?'` e derrubava a seção "Sistema" da
  aba Status. A leitura agora usa `is` + fallback `'?'` (sem cast) e o card
  mostra versão, nº de modos de runtime, capacidades e actions.
- Publicação: commit **`e2f4960`** — _feat(app): publica o código do app v1.2.0
  e corrige a aba Status_ — em `origin/master` (`f42e5c5..e2f4960`). O commit
  levou junto o código do app que gerou o APK (push FCM, resiliência de rede,
  telas ligadas a `/actions` e `/executa`, projeto Android e testes), que
  nunca tinha sido commitado.

- **Contrato testado com payload real** —
  `app/test/fixtures/capabilities_manifest.json` (manifesto capturado do
  servidor em produção) + teste de regressão em `app/test/widget_test.dart`.
  O mock anterior usava um `system` aninhado que o servidor nunca devolveu —
  o teste passava enquanto a tela quebrava no celular.

### APK republicado (2026-09-12)

Dois builds no mesmo dia:

| Build | `versionName` / `versionCode` | sha256 (full) |
|---|---|---|
| 1º — alinhamento de versão | `1.2.0` / 1003·2003·4003 | `3b800c87…d978ff` |
| 2º — com a correção da tela Status | `1.2.0` / **1004·2004·4004** | `6d3c73a5…b616ade` |

- Publicados em `site/OmegaDrakon.apk` (51.9 MB) e
  `site/OmegaDrakon-arm64.apk` (18.5 MB), com sha256 conferido origem↔site
  e download servido pela API (`GET /site/OmegaDrakon.apk`) verificado.
- O build number subiu para `+4` de propósito: com o mesmo `versionCode`
  (1003) o Android recusaria instalar por cima do APK anterior.
- APKs antigos preservados: `backups/apk-v1.0.0/` e
  `backups/apk-v1.2.0-1003/`.
- `OD_VERSION=1.2.0` gravado no `.env`.

### Publicação

- Commit **`ffeab4f`** — _fix(version): alinha OD_VERSION, pubspec e docs na
  v1.2.0_ — publicado em `origin/master` (`3768bcb..ffeab4f`).
- Binários fora do repo por decisão desta entrega: `site/*.apk`,
  `backups/apk-*/` e `.od_repair_backups/` no `.gitignore`.

### Adicionado — push FCM de ponta a ponta (2026-09-12)

Fecha a pendência do push da v1.2.0: até aqui o app só **recebia** (console),
agora o **OD também envia** para o aparelho.

- **`core/push.py`** — `DeviceRegistry` (tokens em `data/push_devices.json`,
  upsert por token, escrita atômica, tolerante a arquivo corrompido),
  `FcmSender` (FCM HTTP v1: OAuth2 da service account + `messages:send`) e
  `PushService` (fachada `notify`/`sink`/`status`, tokens mascarados em
  log/API). Tokens que o FCM declara mortos (`UNREGISTERED`, `INVALID_ARGUMENT`,
  `SENDER_ID_MISMATCH`) saem do registro sozinhos.
- **API** — `POST /push/register`, `POST /push/unregister`, `POST /push/test` e
  `GET /push/devices` (todos com `X-API-Key`); tabela de rotas 22 → **26**.
- **Runtime** — `build_push()` no launcher; a API e o `ProactiveNotifier`
  recebem o serviço, então os alertas proativos (LLM offline, disco, restart)
  também saem como notificação no celular.
- **App** — `OdApi.registerPushToken`/`unregisterPushToken`,
  `PushService.attach(api)` (registra o token no boot, ao salvar as
  Configurações e a cada rotação de token) e `main.dart` ligando os dois.
- **Dependência nova:** `google-auth` (OAuth2/JWT RS256 da service account) —
  justificativa no `requirements.txt`; o HTTP continua em urllib do stdlib
  (adaptador `UrllibRequest`), então não entrou cliente HTTP novo.
- **Dormente por padrão:** sem a credencial (`OD_FCM_CREDENTIALS` ou
  `config/firebase-service-account.json`) o serviço sobe desligado e
  `/push/test` responde **503** — o registro de tokens continua funcionando.
  Ver `docs/FIREBASE_SETUP.md` (passos 6 e 7).

### Validado no aparelho (2026-09-12) ✅

Redmi Note 14 (`redmi-note-14-1`, Tailscale `100.80.224.73`) com o APK
`1.2.0+4`: **Chat, Ações e Status funcionando sem erro**. Evidência do journal
do `od-core` (processo novo, pós-restart de 11:14:52):

```
11:25:58  Message processed | route=cache | user=app | profile=guardian
          llm=- | latency_ms=32.325          → chat do app respondido
11:27:58  Security decision | action=cpu_info | allowed=True | session_id=api:app
          Action executed    | action=cpu_info | role=admin | duration_ms=5.608
                                            → action real executada pelo app
sem "[NICKY][WARN] API erro" depois do restart → zero 4xx vindos do app
```

A tela Status e a instalação do APK não deixam rastro no servidor (GETs não são
registrados e `/site` não tem log de acesso) — essas partes se apoiam no relato
do usuário.

### Corrigido (2026-09-14) — achados do journal do `od-core`

Dois achados levantados no journal, cada um com teste de regressão novo:

- **`face.presence` ia para dead letter a cada evento** —
  `runtime/launcher.py::_run_vision_forever` registrava o handler como
  `on_change(data)` e chamava `data.get("confirmed")`, mas o Event Bus entrega
  o **`Event`** (o payload vive em `event.data`, como no resto do projeto) →
  `AttributeError: 'Event' object has no attribute 'get'` em todas as 3
  tentativas, seguido de _dead letter_ (09-14: 09:29:55, 09:31:17, 10:27:10 e
  10:27:39). O handler passou a ler `event.data` com guarda de tipo — o bus
  grava apenas o **nome** da exceção no journal, por isso o motivo só apareceu
  na leitura do código.
  - Regressão: `tests/test_launcher_vision.py` (novo, **4 testes**, bus real +
    detector fake) — com o handler anterior restaurado, os 4 falham
    reproduzindo as linhas exatas do journal.
  - Prova em produção: depois do restart de 13:24:40, o `face.presence` real
    das 13:25:09 (`Event published | topic=face.presence | subscribers=1`)
    **não** gerou nenhum `Handler error` nem `dead letter`.
- **Snapshots do SelfRepair cresciam sem limite** — `core/self_repair.py`
  criava um `.bak` por tentativa mesmo sem mudança no arquivo: um arquivo
  doente no escopo do `RecoveryLoop` (ciclo de 5 min) rendeu **557 snapshots,
  8,8 MB** em ~2 dias. Agora `_take_snapshot` faz **dedup** (bytes idênticos
  reutilizam o snapshot existente) e **retenção** por arquivo
  (`max_snapshots_per_file`, default `5`) via `_prune_snapshots`;
  `_next_snapshot_path` evita a colisão de nome dentro do mesmo segundo (antes
  o snapshot anterior era sobrescrito).
  - Regressão: `TestSnapshotDedupERetencao` em `tests/test_self_repair.py`
    (**4 testes**) — com o comportamento anterior restaurado, os 4 falham.
  - Limpeza retroativa: dos 557 snapshots (3 conteúdos distintos), 552 saíram
    e os 5 mais novos ficaram → `8,8 MB → 116 KB`.
- `od-core` reiniciado às 13:24:40 para subir as correções; `/health` ok (8
  checks) e o `RecoveryLoop` rodando sem detecções.

### Ativado (2026-09-14) — push FCM em produção 🔔

A service account chegou e o envio saiu do modo dormente **sem nenhuma mudança
de código** (o que faltava era só a credencial):

- Credencial instalada em `config/firebase-service-account.json`
  (`chmod 600`), coberta pelo `.gitignore` — nada de credencial no repositório.
- **Validação antes do restart**: o `FcmSender` do próprio `core/push.py`
  (`available=True`, `project_id=nicky-e4f99`) emitiu um **access token OAuth2
  real** — a chave é válida e tem permissão no FCM (nenhuma mensagem enviada
  nessa etapa).
- `od-core` reiniciado às 14:06:53: `Push FCM inicializado | enabled=True |
  motivo= | credencial=config/firebase-service-account.json | dispositivos=1`
  (todos os restarts desde 13/09 registravam `enabled=False |
  credencial_ausente`).
- **Teste de ponta a ponta**: `POST /push/test` → **HTTP 200**
  `{ok:true, sent:1, failed:0, skipped:0, errors:[]}`; journal
  `Push enviado | enviados=1 | falhas=0 | titulo=OmegaDrakon`; e o aparelho
  registrado (Redmi Note 14) foi para `sent=1, failed=0` no
  `GET /push/devices`. O token foi registrado pelo **próprio app**, sem ação
  manual no servidor.
- Nenhuma variável nova no `.env`: sem `OD_PUSH_ENABLED` o default é "ligado
  se houver credencial" (`PushService.enabled` cai em `sender.available`).

> ⚠️ **Achado de segurança desta rodada:** um dos dumps de tela guardados na
> pasta local `000/` (fora do git) contém a **chave legada do servidor FCM**
> (API legada, descontinuada em 2024) e um par de chaves de push da Web. A
> chave legada **não** é usada pelo OD (o envio é HTTP v1 com service account) e
> deve ser excluída no console — *Cloud Messaging → chave do servidor*.

### Corrigido (2026-09-15) — resiliência do core

- **Timeout de rede do Telegram derrubava o core.** O `HTTPTransport` só
  envolvia `HTTPError`/`URLError`; um `TimeoutError` estourando na **leitura da
  resposta** não passa pelo `URLError` e escapava do `bot.run()` (que tolera
  apenas `TransportError`) até o `asyncio.gather` do launcher, matando o
  **processo inteiro**: 89 quedas e 89 restarts do `od-core` entre 2026-09-13 e
  2026-09-15, uma delas num **crash loop de 4h30** (85 quedas a cada 2–3 min).
  As três chamadas de rede do transporte passaram a capturar `OSError` (cobre
  `TimeoutError`, `ConnectionResetError` e `ssl.SSLError`). Commit **`b215d07`**
  (regressão em `tests/test_telegram.py`, 3 testes).
- **Loops do core sem rede de segurança.** Os laços de **MQTT**, **presença** e
  **visão** chamavam `poll_once()`/`tick()` sem proteção, e o `HAClient` deixava
  `TimeoutError` de leitura escapar cru (mesma classe do bug acima). Cada loop
  ganhou o try/except do "ciclo nunca morre" — a disciplina que o
  `RecoveryLoop` já tinha — e o `launcher._all` passou a **supervisionar** cada
  loop (`_supervise`: contém a exceção, registra e reinicia com espera em vez de
  derrubar o processo; a API entra com `restart=False`, porque recriar o
  servidor conflita na porta 8000). Commit **`0c5b9d8`**;
  `tests/test_launcher_supervisor.py` é novo.
- **Traceback de cliente desconectado poluía o journal.** O `handle_error`
  herdado do `socketserver` imprime o traceback inteiro no stderr do processo
  quando um cliente aborta a conexão no meio do request — e isso é rotina (app
  Android perdendo rede, navegador fechando a aba, health check com timeout):
  em 2026-09-15 10:14:41 o journal ganhou dois `ConnectionResetError` de um peer
  do tailnet, ruído que esconde erro de verdade. O `APIServer` passou a
  sobrescrever `handle_error`: **desconexão** vira uma linha de **DEBUG** sem
  stack, e erro que **não** é desconexão continua aparecendo em **WARN**. Nada
  de diagnóstico se perde — os erros dos handlers já são tratados em
  `APIHandler._handle` (`APIError` → status próprio; `Exception` → 500 +
  `log.error`), então o que chega ali é falha de socket. +3 testes em
  `tests/test_api.py` (um deles aborta um socket com RST de verdade).

### Adicionado (2026-09-15) — supervisão dos loops visível 🔍

- **`core/supervision.py`** (novo) — registro thread-safe das quedas e
  reinícios de cada loop do modo `all` (`failures`, `restarts`, `last_kind`,
  `last_error`, `age_s`). "Degradado" = queda dentro da **janela de 300 s**;
  passada a janela o estado volta a ok sozinho, sem intervenção. O objetivo é
  direto: a supervisão da rodada anterior continha a queda, mas ela ficava
  silenciosa — e foi esse silêncio que deixou as 89 quedas passarem até a
  leitura do journal.
- **Check `loops` no `/health`** — não-crítico (`critical=False`): loop
  reiniciado **degrada** o agregado em vez de derrubá-lo, com o nome do loop e
  o erro no detalhe.
- **Alerta pelo notifier** — nova sonda `_check_loops` nas sondas padrão
  (`integrations/notifier.py`): alerta **WARN** por loop reiniciado, escalando
  para **CRIT** com 3+ reinícios (laço de falha) e limpando o problema quando o
  loop estabiliza; o anti-spam continua o do notifier (1 alerta/hora por loop).
  Commit **`fc2abe0`**.
- **`GET /supervision`** (novo endpoint com `X-API-Key`) — expõe o mesmo estado
  para o app: `{ok, status, window_s, degraded[], restarts, loops[], ts}`.
  `ok=false` + `status=degraded` significam "loop caiu dentro da janela" (o core
  segue de pé, HTTP 200); passada a janela volta a ok. A raiz (`GET /`) passou a
  reportar **27 endpoints**.
- **Testes:** **1689 passed, 16 skipped**, com teste do teste nas três rodadas —
  15 de 18 testes-alvo falharam com as mutações da observabilidade, 2 falharam
  com as mutações da rota (flag de auth e sinal de degradação) e 3 falharam com
  as mutações do `handle_error` (delegar ao `socketserver` e renomear o método).

### App republicado (2026-09-15) — supervisão na aba Status 📱

- **Aba Status** ganhou o card **"Supervisão dos loops"**: mostra se há loop
  reiniciado (`degraded`), a janela considerada, o total de reinícios e, por
  loop, o nome, quantos reinícios e o tipo do último erro (`TimeoutError`…).
  Até aqui o app só sabia de um loop caído pelo Telegram/push.
- **`OdApi.getSupervision()`** consome o `GET /supervision`; `ok=false` +
  `status=degraded` são tratados como **resposta válida** (HTTP 200) — o core
  está de pé, e a tela mostra o loop caído em vez de erro de rede.
- **Best-effort:** falha na rota não derruba a aba — o card avisa "Supervisão
  dos loops indisponível" e o resto da tela continua (a lição do bug do
  `system` aninhado no APK 1.2.0).
- **APK 1.2.0+6** (versionCode 1006/2006/4006) publicado em
  `site/OmegaDrakon.apk` (51.935.427 B) e `site/OmegaDrakon-arm64.apk`
  (18.518.770 B), com sha256 origem == site (`b325ad23…` full · `f3f86059…`
  arm64); o build anterior (**1.2.0+5**) foi preservado em
  `backups/apk-v1.2.0-1005/`. O `versionCode` subiu de propósito: com o mesmo
  código o Android recusa instalar por cima do anterior.
- **Testes do app:** `flutter analyze` sem issues · `flutter test` →
  **48 passed** (42 na entrega anterior; +6: 3 do cliente de API e 3 de
  widget). Teste do teste: tratando `degraded` como erro e omitindo a chamada
  na `_refresh()`, **4 testes falham**.
- **Verificação do binário:** a string `supervision` aparece **2x** no APK novo
  e **0x** no anterior, e `Nenhum loop reiniciado` **1x** contra **0x** —
  diferencial que confirma que o código novo está no binário (a string de
  controle `OmegaDrakon Online` aparece 1x nos dois). A API serviu o arquivo
  novo em `GET /site/OmegaDrakon.apk` (HTTP 200, mesmo tamanho e sha256).

### Adicionado (2026-09-18) — streaming do chat por WebSocket 🌊

- **Novo `integrations/api/ws_server.py`** — servidor WebSocket
  (`websockets.asyncio.server.serve`, porta `OD_WS_PORT` padrão **8001**,
  ligado por `OD_WS_ENABLED`) que fala com o **mesmo `Orchestrator`** da API
  REST. Protocolo: `auth`/`message` do cliente → `authenticated`,
  `processing`, `token`… e `done` (`route`, `llm_used`, `latency_ms`); auth
  pela mesma `OD_API_KEY` (`api_key` inválida → close **4001**).
- **`core/llm.py`** — `OpenAICompatProvider.generate_stream` +
  `_post_chat_stream`: parser de SSE do formato OpenAI (`data: {...}` /
  `data: [DONE]`) com import tardio do `websockets` (sem ele o core sobe
  normal e só o streaming fica indisponível, como o push sem google-auth).
- **`core/orchestrator.py`** — `process_stream`: o mesmo pipeline de etapas
  (rate limit → datetime → quick → intents → cache → LLM com fallback para
  `generate`) emitindo `token`/`done`/`error`; pós-processamento (cache +
  histórico) preservado.
- **`runtime/launcher.py`** — `build_ws_server` + subida no `_run_api_forever`
  com a falha **contida** em `try/except`: WS que não sobe (porta ocupada,
  dependência ausente) é logado e o REST + o resto do núcleo seguem de pé.
- **`requirements.txt`** — `websockets>=14.0` declarado (item 3), com
  justificativa: é o único servidor não-stdlib do projeto.
- **Ruído no journal:** o `websockets` loga `opening handshake failed` com
  `exc_info=True` — um TCP cru que abre e fecha (sonda de porta, health check)
  despejava **traceback inteiro no stderr**, o mesmo defeito que o
  `handle_error` do `http.server` tinha (correção de 2026-09-15). Agora um
  `_LibraryLogger` (LoggerAdapter) leva o log da biblioteca para o log do OD
  em **UMA linha de debug**; cliente que cai no meio do stream também saiu de
  `log.error` para debug.
- **Testes:** `tests/test_websocket.py` **reescrito (14 → 28)**. Os 14
  anteriores só conferiam formato de dict e existência de método — a suíte
  passava enquanto `start()` quebrava com `import websockets.serve`
  (`ModuleNotFoundError`). Agora há ciclo de vida real (sobe e escuta,
  `bound_port`, `stop` libera a porta, porta ocupada → `RuntimeError` sem
  derrubar o primeiro), protocolo com **cliente WebSocket real**, queda no
  meio do stream, sonda TCP crua sem traceback, SSE do provider, `process_stream`
  e fiação do launcher. **Teste do teste (4 mutações, todas revertidas):**
  import quebrado → *5 failed + 6 errors*; checagem de `api_key` removida →
  falha (revelou que o teste **pendurava** — daí o teto de 10s por fluxo);
  `stop()` sem fechar o servidor → 2 falhas; launcher sem o `try/except` →
  falha a contenção; `serve()` sem o `_LibraryLogger` e handler sem o
  tratamento de desconexão → 1 falha cada.
- **Corrigido no caminho (2026-09-18):** o `POST /message` **valida o perfil**
  e resolve `auto` → `guardian` (`DEFAULT_PROFILE`), mas o WebSocket mandava
  `auto` cru — como o app manda `profile: auto` por padrão, a MESMA conversa
  cairia em baldes diferentes de cache/histórico conforme o transporte (e
  perfil inválido era aceito no WS e recusado no REST). O `ws_server` agora
  importa `DEFAULT_PROFILE`/`DEFAULT_PROFILES` de `integrations.api.server`
  (mesma fonte, sem duplicar a lista), resolve `auto` e recusa perfil
  desconhecido com o mesmo texto do REST. **+2 testes** (`perfil auto vira o
  padrão`, `perfil desconhecido é recusado sem processar`); mutações G/H
  (aceitar perfil inválido e não resolver `auto`) → os 2 falham. Prova ao vivo
  após o deploy: `profile: auto` pelo WebSocket registra
  `Interaction recorded | profile=guardian`.
- **Suíte:** **1719 passed, 16 skipped** (17,29s).
- **Sandbox (antes do sistema real):** `sandbox_agent/ws_sandbox.py` (pasta
  ignorada pelo git) contra o **llama-server real** em `127.0.0.1:8081` →
  **11/11 checagens OK e stderr com 0 bytes**: 35 frames de token com
  espalhamento de **2,67s** (1º em 2,04s, último em 4,71s) — streaming
  incremental de verdade, não um bloco no fim; tokens concatenados ==
  `content` do `done` (`route=llm`); reuso da conexão; chave inválida →
  close 4001; desconexão abrupta sem derrubar o servidor; sonda TCP crua sem
  traceback. Foi o sandbox que expôs os dois ruídos acima.
- **Deploy:** `od-core` reiniciado em **2026-09-18 04:35:09** (PID 395579,
  `NRestarts=0`) — `[NICKY][INFO] WebSocket server no ar | host=0.0.0.0 |
  port=8001 | auth=True`, `:8001` escutando e `/health` com os 9 checks `up`.
  **Prova ao vivo:** mensagem real pelo WebSocket em produção → 7 frames de
  token, `tokens == content do done`, `route=llm`; chave errada → close 4001;
  3 sondas TCP cruas → journal com **0** `Traceback`, **0**
  `opening handshake failed`, **0** `WebSocket processing error`.
- **Nota de escopo:** o **app Flutter ainda usa `POST /message`** — não há
  cliente WebSocket no app; esta entrega é o lado servidor. `process_stream`
  também **não publica** `orchestrator.responded` no EventBus (o `process`
  publica); hoje ninguém assina esse tópico em produção.

### App — chat em streaming com fallback (2026-09-18) 📱

- **`app/lib/services/od_ws.dart` (novo)** — `OdStreamingChat`: fala o
  protocolo do `ws_server` (`auth`/`message` → `authenticated`, `processing`,
  `token`… `done`) e entrega a resposta em `OdChatDelta`s. Deriva a porta do
  streaming da URL já configurada (`http://host:8000` → `ws://host:8001`,
  `https` → `wss`; `wsPort` configurável). Usa `dart:io WebSocket` — **nenhum
  pacote novo no pubspec** (mesmo caminho de rede do `OdApi`).
- **Fallback automático para `POST /message`** quando o WebSocket não estiver
  disponível (core antigo, porta fechada, chave recusada, rede trocando de
  rota) — e **cooldown de 2 min** depois de uma falha, senão toda mensagem
  pagaria o timeout de conexão antes de cair para o REST (o chat ficaria mais
  lento que antes da entrega).
- **Interrupção no meio do stream não repete a mensagem**: se já apareceu
  texto, o app NÃO refaz a chamada pelo REST (duplicaria a resposta e faria
  uma segunda inferência no servidor) — mostra o parcial e avisa na mesma
  bolha (`OdStreamingError`).
- **`chat_screen.dart`** — a bolha do assistente nasce no primeiro token e é
  reescrita a cada frame; o "Digitando..." só aparece enquanto nada chegou; e
  há um selo discreto do transporte da última resposta (⚡ **Streaming ativo**
  ou ↔ **Resposta via REST**), que é o que permite conferir no celular se o
  streaming está de pé.
- **Encerramento best-effort do canal**: nem o `cancel()` do iterador nem o
  `close()` do socket podem segurar a resposta — esperar por eles travava a
  tela com o texto já pronto (bug pego por teste de widget e depois pinado em
  teste unitário com um canal que nunca fecha).
- **`OdApi(apiKey:)`** — chave só em memória, para verificações vivas e testes
  que rodam sem o binding do Flutter (o binding troca o `HttpClient` por um
  dublê que responde 400 e não haveria socket real para exercitar).
- **Testes do app:** `flutter analyze` sem issues · `flutter test` →
  **67 passed, 2 skipped** (49 → 67). Novos: `test/od_ws_test.dart` (12:
  derivação da URL, protocolo com canal roteirizado, frames desconhecidos,
  fallback, interrupção sem duplicar, cooldown, 401) e 3 de widget em
  `test/widget_test.dart` (render incremental token-a-token, fallback com
  selo do transporte, corte no meio mantendo o texto). `test/ws_live_test.dart`
  (2, **opt-in por `OD_LIVE_WS=1`**) fala com o core REAL pelo conector de
  produção.
- **Teste do teste (3 mutações, revertidas):** sem a guarda de texto parcial →
  2 falhas (fallback indevido depois do parcial); com o encerramento aguardado
  (`await cancel` + `await close`) → 3 falhas (unitário do canal que não fecha
  e os 2 de widget, que ficam com o spinner preso); sem o cooldown → 1 falha.
- **Validação viva (sandbox, antes de publicar):** no nicky-server, contra o
  `od-core` em produção → **36 deltas pelo WebSocket** (`transport=webSocket`,
  35 frames de token) respondendo "1 a 15" em ~8s; e chave errada → o
  streaming recusa e o app cai para o REST, que devolve **401**
  (`OdAuthError`).
- **APK 1.2.0+7 publicado** — `site/OmegaDrakon.apk` **52.230.399 B** (sha256
  `c69f2ccd…`, `versionCode 7`) e `site/OmegaDrakon-arm64.apk` **18.649.902 B**
  (sha256 `a5015cd7…`, `versionCode 2007`), com `versionName 1.2.0` conferido
  no `aapt dump badging`; origem == `site/` (sha256 idêntico). O `versionCode`
  subiu de propósito (o Android recusa instalar por cima com o mesmo código) e
  o build anterior (**1.2.0+6**, 51.935.427 B em `b325ad23…` e 18.518.770 B
  em `f3f86059…`) ficou em `backups/apk-v1.2.0-1006/`. Servido pela API: `GET /site/OmegaDrakon.apk` →
  HTTP 200 com o mesmo tamanho e sha256.
- **Prova no binário:** `Streaming ativo` **1x** no APK novo contra **0x** no
  anterior e `Resposta via REST` **1x** contra **0x** (controle
  `OmegaDrakon Online` **1x** nos dois).

### Infraestrutura — monitor do roteador versionado e corrigido (2026-09-18) 📡

- **Versionado o que já rodava solto em produção:**
  `tools/monitor/router_monitor.sh` (ping no gateway + estado da interface +
  link changes do Tailscale, em JSON-lines) e as units, que saíram de
  `tools/monitor/` para `runtime/systemd/router-monitor.{service,timer}` —
  junto das units do núcleo. O `install-user.sh` passa a copiar e a ligar o
  timer (`enable --now router-monitor.timer`), e `tools/monitor/README.md`
  documenta uso, variáveis (`OD_ROUTER_IP`, `OD_NETWORK_INTERFACE`,
  `OD_MONITOR_*`, `OD_LOG_DIR`) e limites.
- **Bug corrigido (o monitor era cego para o que existe para medir):** em 17h
  de operação havia **1086 registros `up` e ZERO `down`**. Causa raiz: `set -e`
  combinado com `x=$(comando que falha)` — o ping que falhava (roteador fora)
  derrubava o script **antes** do registro do `down`, e o `cat` de
  `/sys/class/net/<if>/carrier` com a interface ausente abortava antes da linha
  da interface. Correção na raiz: o script **não usa mais `set -e`** (monitor
  precisa sobreviver a falha transitória), todo comando externo tem fallback
  explícito, e `carrier`/`speed` são forçados a numérico (senão o JSON-lines
  sairia inválido). `--once` passa a sair **0 mesmo com o roteador fora** — o
  estado fica no log e um unit em falha a cada minuto durante a queda seria
  ruído pelo motivo errado.
- **Adicionado:** rotação do log (`OD_MONITOR_MAX_BYTES`, padrão 5 MiB,
  mantendo uma geração `<arquivo>.1`) — 1 linha/min ≈ 130 MB/ano sem teto —,
  `journalctl` opcional, e o relatório deixou de prometer "janelas >30s" que
  nunca calculou (agora descreve o que faz: incidentes por dia).
- **Testes:** `tests/test_router_monitor.py` (novo, **15**) roda o script de
  verdade em sandbox (diretório temporário + gateway de teste do RFC 5737) e
  pina os dois casos do bug, o contrato do log, a rotação e o `--report`;
  `tests/test_systemd_units.py` ganhou **10** asserções (units do monitor +
  instalador). **Suíte: 1743 passed, 16 skipped.**
- **Teste do teste:** reintroduzindo a forma original (`set -euo pipefail` +
  `ping_result=$(...)` + chamada sem guarda) → **6 falhas**, incluindo as três
  que pinam "o `down` é registrado"; revertido.
- **Prova no systemd:** o timer dispara de 1 em 1 minuto com
  `SyslogIdentifier=router-monitor` e registra `up` no log; e um `systemd-run`
  com `OD_ROUTER_IP=192.0.2.1` (inalcançável) **conclui com sucesso**
  enquanto grava `{"status":"down","detail":"ping_failed"}` — exatamente o
  que não acontecia antes. `od-core` não foi reiniciado (PID 399298 intacto).

### Corrigido (2026-09-18) — paridade do `orchestrator.responded` entre REST e WebSocket 🔔

- **A mesma conversa era registrada de dois jeitos.** `process` (REST) passa
  **todo** desfecho por `_finish` — métricas, evento e log `Message processed` —,
  enquanto `process_stream` (WebSocket) só contava `processed` no caminho do LLM
  e **nunca publicava** `orchestrator.responded` (havia até um comentário
  `# Publicar evento` órfão onde a publicação deveria estar). Atalhos (datetime,
  quick, cache, intents) e falhas (rate limit, indisponível) simplesmente não
  apareciam em quem observa o núcleo. Agora **toda saída terminal do stream
  passa pelo `_finish`**, com um `OrchestrationResult` montado por
  `_stream_result` — mesmas métricas, mesmo evento, mesmo log.
- **Provider sync voltou a responder no WebSocket.** O fallback não-streaming do
  stream fazia `await provider.generate(...)`; com um provider **sync** (ex.:
  `StaticProvider`) isso levantava `TypeError`, ninguém tratava e o resultado era
  `todos_providers_falharam` — o mesmo provider respondia no REST (que já usava
  `inspect.isawaitable`) e falhava no WebSocket. A chamada foi extraída para
  `_generate_one`, usada pelos dois caminhos.
- **Paridade de textos:** `RATE_LIMITED_MESSAGE` e `DEFAULT_UNAVAILABLE_ERROR`
  viraram constantes, em vez de literais repetidos — o evento/log do stream
  carrega exatamente o que o REST carregaria. O cliente continua recebendo o
  código curto no chunk de erro (`rate_limited`), que é contrato do protocolo.
- **Testes:** +6 em `tests/test_orchestrator.py` (classe `TestOrchestratorEventBus`),
  incluindo a comparação direta `evento do REST == evento do WebSocket` para o
  mesmo texto. **Suíte: 1749 passed, 16 skipped.**
- **Teste do teste:** 4 mutações — tirar o `_finish` do atalho datetime → 1
  falha; exigir provider async outra vez → 1 falha; evento do rate limit com o
  código curto → 1 falha; voltar o caminho do LLM ao estado original (sem
  evento) → 2 falhas. Revertidas.
- **Validação em sandbox** (`sandbox_agent/event_parity_sandbox.py`, contra o
  llama-server real): **7/7 OK**, incluindo `evento do REST == evento do
  WebSocket` e o atalho datetime publicando. `od-core` **não** foi reiniciado —
  a mudança ainda não está em produção (PID 399298 de 04:49).

### Pendente

- ~~Gerar a **service account** no console do Firebase e gravá-la em
  `config/firebase-service-account.json` para o envio sair do modo dormente
  (o app já está registrando o token).~~ **Feito em 2026-09-14** — ver
  *Ativado (2026-09-14)* acima.

---

## [1.1.0] — Acesso Externo Seguro 🔐 (2026-09-07)

### Adicionado

- **Tailscale (VPN mesh WireGuard)** — IP `100.77.67.53`, tailnet
  `nickyvirthy`, interface `tailscale0`, versão 1.102.2; API acessível de fora
  da LAN em `http://100.77.67.53:8000` com `X-API-Key`.
- **Documentação** — `docs/TAILSCALE_SETUP.md`.

### Infraestrutura

- Segurança em camadas: VPN + `X-API-Key` + UFW (22/8000/8123) — **zero portas
  abertas no roteador**.
- Journal sem exposição de segredos (verificado no roadmap).

### Testes

- Sem suíte nova (item de infraestrutura/rede); critérios de aceite validados
  contra o servidor nicky-server — ver `docs/README_VERSAO.md` §[1.1.0].

---

## [1.0.0] — Fundação v1 (release-grade) 🏛️ (2026-09-07)

### Adicionado

- **7º perfil `nexus`** (Conector) em `agents/profiles.py` — a Plêiade fica
  completa (7 entidades), com detecção automática por domínio
  (conexão/integração/plêiade).
- **Health checks externos** — Home Assistant e MQTT/Mosquitto no Health
  Monitor; `/health` passa a expor 7 checks (5 internos + HA + MQTT).
- **Control Bridge no repositório** — `tests/test_control_bridge.py`
  (allowlist, tokens, escape de path, legados §7.1, auditoria, execute) e o
  unit systemd `runtime/systemd/od-control-bridge.service`.

### Infraestrutura

- **CI no GitHub Actions** — `.github/workflows/ci.yml` (Python 3.12, push +
  PR): `compileall` + `pytest -q` com gate de cobertura ≥ 90% (`.coveragerc`,
  `runtime/launcher.py` omitido).
- **Migração JSON → PostgreSQL** — `memory/adapters.py` (schemas +
  `migrate_all()` idempotente); `history.py`, `cache.py`, `quick_responses.py`
  e `vector.py` ganharam `database=None`; fallback JSON mantido.
- **Systemd `od-core`** — `runtime/systemd/od-core.service` (NoNewPrivileges,
  ProtectSystem=strict, ProtectKernel*, MemoryMax=6G, CPUQuota=200%,
  ReadWritePaths) + `install-user.sh` com verificação de linger.
- **SWAP 8 GB** (`/swapfile`) + `vm.swappiness=10` via
  `runtime/setup/setup-server.sh`.
- **UFW ativo** — 22 (SSH), 8000 (OD API), 8123 (HA) permitidos; resto
  bloqueado.
- **Variáveis de ambiente ausentes** — 6 configuradas no `.env`
  (`OD_PRESENCE_ENABLED`, `OD_PRESENCE_POLL_S`, `OD_RECOVERY_INTERVAL_S`,
  `OD_SELF_REPAIR_ENABLED`, `OD_NOTIFIER_ENABLED`).
- **Disco `sdb1` montado** em `/home/alex/dados` (801 GB livres) + automount
  via `/etc/fstab`.

### Testes

- Suíte local: **1594 passed**; cobertura **95%** (gate ≥ 90% no CI).
- Novos: 46 testes da migração JSON→DB; 29 de `tests/test_systemd_units.py`;
  26 de `tests/test_control_bridge.py`.

---

## Série 0.x — congelada em [0.28.1] ❄️ (2026-09-04)

A série 0.x está **congelada**: a v0.28.1 é o marco estável final (PostgreSQL
nativo no ar, loop de auto-recuperação fechado, fast path de intenções,
57 actions, 1453 testes verdes, tag git `v0.28.1` no commit `ba2f7c8`).
O histórico detalhado de cada versão 0.1.0–0.28.4 está em
`docs/README_VERSAO.md` e nas Fases 1–7 de `docs/ROADMAP_ABSORCAO.md`
(37/37 capacidades absorvidas).

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/CHANGELOG.md
Descrição: Registro de mudanças por versão (item 4 da Definition of Done).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
