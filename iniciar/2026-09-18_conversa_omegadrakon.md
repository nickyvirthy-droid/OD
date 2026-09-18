2026-09-18 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu: iniciar/README.md, iniciar/RULES.md, iniciar/session.json
  (680 linhas) e iniciar/2026-09-17_conversa_omegadrakon.md.

Estado conferido por evidência (não por memória):

Git:
- HEAD `5668b27` ("docs: registra o deploy do silenciamento do handle_error").
- `git status --short` → working tree **NÃO limpa**:
  - M core/llm.py (+94), core/orchestrator.py (+173), runtime/launcher.py (+33)
  - M iniciar/session.json (o update do checkpoint de 09-17)
  - ?? integrations/api/ws_server.py, tests/test_websocket.py, tools/monitor/ (4 arquivos)
- Nada disso estava em session.json nem em transcrição de 09-17 → **trabalho
  não persistido** (regra 4 violada até esta rodada).

od-core:
- `ExecMainStartTimestamp` 2026-09-15 10:43:54, PID 314992, NRestarts=0,
  ActiveState=active → **o processo em produção é o de 09-15**.
- `ss -ltnp` → só `0.0.0.0:8000` escutando (PID 314992); a **:8001 não existe**.

Rodada 1 (09-18): duas frentes achadas no working tree

Achado 1 — streaming WebSocket (rotulado v1.3.0 no código, não registrado)

- `core/llm.py`: `OpenAICompatProvider.generate_stream` + `_post_chat_stream`
  (parser de SSE do formato OpenAI, `data: {...}` / `data: [DONE]`).
- `core/orchestrator.py`: `process_stream` — espelha o pipeline do `process`
  (rate limit, datetime, quick, intents, cache, LLM com fallback para
  não-streaming, pós-processamento) emitindo dicts `token` / `done` / `error`.
- `integrations/api/ws_server.py`: `WebSocketServer` (porta padrão 8001,
  autenticação por `api_key`, protocolo `auth`/`message` → `processing`/`token`/`done`).
- `runtime/launcher.py`: `build_ws_server` + start no `_run_api_forever`
  (OD_WS_ENABLED default "1", OD_WS_PORT default 8001).
- `tests/test_websocket.py`: `.venv/bin/python -m pytest tests/test_websocket.py -q`
  → **14 passed em 0.08s**. Ressalva: em maioria asserções de formato de dict e
  de existência de método — não cobrem `start()`, auth real nem socket.

Problemas:

1. **`ws_server.start()` não sobe**: faz `import websockets.serve` →
   `ModuleNotFoundError: No module named 'websockets.serve'`
   (websockets **16.1.1** instalado na .venv; o correto é
   `from websockets.asyncio.server import serve`). Ou seja: a suíte passa e a
   funcionalidade não funciona — teste que não pina o caminho real.
2. **`websockets` está instalado e ausente do `requirements.txt`**
   (grep por "websocket" no requirements.txt → nenhuma linha).
3. **Nunca foi implantado** (nada de restart; :8001 fechada).

Achado 2 — monitor do roteador: untracked **e rodando em produção**

- `tools/monitor/router_monitor.sh`: ping no gateway + `operstate`/`carrier`/`speed`
  da interface + contagem de `LinkChange: major` do Tailscale; modos `--once`,
  `--report` e loop contínuo; log JSON-lines.
- `tools/monitor/router-monitor.service` (Type=oneshot, `--once`) e
  `tools/monitor/router-monitor.timer` (OnUnitActiveSec=1min).
- **Instalados e ativos**: `router-monitor.timer` LOADED/enabled/active (waiting)
  desde **2026-09-17 10:26:09** (17h), disparando a cada minuto;
  `logs/router_monitor.log` com **128.551 B** e última linha **04:19:39 de hoje**
  (`status":"up"`, latency 0.825ms).
- Leitura: é o único item em produção *não versionado* — o monitor roda desde
  ontem e não existe no repo nem no checkpoint.

Rodada 2 (09-18): streaming WebSocket — corrigido, testado e validado em sandbox

Escolha do usuário entre as frentes abertas: **corrigir e validar o streaming
WebSocket** (o deploy do od-core ficou fora do escopo da opção e continua
pendente de autorização).

Causa raiz (uma só, e que explica a suíte verde):

- `integrations/api/ws_server.py::start()` fazia `import websockets.serve` →
  `ModuleNotFoundError: No module named 'websockets.serve'`. Os 14 testes
  originais só conferiam formato de dict e existência de método: nenhum chamava
  `start()`. **A suíte passava e a funcionalidade não subia.**
- Somando: `asyncio.set_event_loop` era chamado na thread do caller (não na do
  loop); `stop()` fechava o loop por baixo da biblioteca; a dependência não
  estava no `requirements.txt`.

Correções (código):

- `ws_server.py`: import tardio e correto (`from websockets.asyncio.server import
  serve`); `start()` síncrono de verdade (espera o bind, prazo de 5s, levanta
  `RuntimeError` com o motivo); `set_event_loop` dentro da thread; `bound_port`
  (funciona com `port=0`); `stop()` idempotente usando
  `call_soon_threadsafe(server.close)` (`close` é síncrono no
  `websockets.asyncio`); `is_running` só é `True` sem `_start_error`.
- `ws_server.py`: `_LibraryLogger` (LoggerAdapter) leva o log da biblioteca para
  o log do OD. O padrão dela é `logger.error("opening handshake failed",
  exc_info=True)`: um TCP cru que abre e fecha despejava **traceback inteiro no
  stderr** — o mesmo ruído do `handle_error` de 2026-09-15. Agora é UMA linha de
  debug. Desconexão do cliente no meio do stream também saiu de `log.error`
  (`WebSocket processing error`) para debug.
- `core/llm.py::_post_chat_stream`: mesma tolerância do caminho não-streaming
  para `reasoning_content` (modelo que só manda raciocínio devolve o raciocínio
  em vez de stream vazio).
- `runtime/launcher.py`: `build_ws_server`/`start` dentro de `try/except` — WS
  que não sobe é logado e o REST/núcleo seguem de pé.
- `requirements.txt`: `websockets>=14.0` declarado como item 3, com justificativa.

Testes (`tests/test_websocket.py` reescrito, 14 → 28):

- ciclo de vida real (sobe e escuta, `bound_port`, `stop` libera a porta, start
  idempotente, porta ocupada → `RuntimeError` sem derrubar o primeiro);
- protocolo com cliente WebSocket real (auth, message, processing, tokens, done,
  chave inválida → close 4001, sem auth rejeitado, json inválido não mata a
  conexão, falha do orchestrator vira `error` e a conexão sobrevive);
- queda no meio do stream sem ERROR + servidor sobrevivendo;
- sonda TCP crua sem traceback;
- SSE do provider (chunks, linhas inválidas, reasoning fallback, stream vazio,
  erro de rede → LLMError);
- `process_stream` (rate limit, datetime, token-a-token com provider de
  streaming, fallback para `generate`);
- fiação do launcher (env/porta/chave, falha do WS não derruba a API, caminho
  feliz sobe e para o WS).

Teste do teste (4 mutações, todas revertidas):

- (A) `import websockets.serve` de volta → **5 failed + 6 errors**;
- (B) checagem de `api_key` removida → `test_chave_invalida` falha — e revelou
  que o teste **pendurava**: desde então todo fluxo de cliente tem teto
  (`FLOW_TIMEOUT_S = 10.0`);
- (C) `stop()` sem fechar o servidor → 2 falhas;
- (D) launcher sem o `try/except` → falha o teste de contenção;
- (E) `serve()` sem o `_LibraryLogger` → falha o teste da sonda TCP;
- (F) sem o tratamento de desconexão no handler → falha o teste da queda no
  meio do stream.

Nota de teste: E e F só ficaram confiáveis depois de trocar `capfd` pelo ring
buffer do `NickyLogger` + um coletor no `logging` da biblioteca. Com `capfd` os
dois passavam **por engano** conforme a ordem dos testes (o stream que o logger
capturou na criação fica obsoleto entre testes).

Sandbox (regra 12) — `sandbox_agent/ws_sandbox.py` (pasta ignorada pelo git):

- contra o **llama-server real** (127.0.0.1:8081, qwen2.5-coder-3b), porta 18001:
  **11/11 checagens OK e stderr com 0 bytes**;
- 35 frames de token com espalhamento de **2,67s** (1º em 2,04s, último em
  4,71s) → streaming incremental de verdade, não um bloco no fim;
- tokens concatenados == `content` do `done` (route=llm); reuso da conexão;
  chave inválida → close 4001; desconexão abrupta no meio do stream sem derrubar
  o servidor; sonda TCP crua sem traceback; `stop()` libera a porta.
- foi o sandbox que expôs os dois problemas acima (traceback da sonda TCP e o
  `WebSocket processing error` na desconexão) — os dois viraram teste;
- erro meu no sandbox: a checagem 2 comparava tempo absoluto com relativo e
  dava FALHA falsa; corrigida antes de concluir.

Suíte: **1717 passed, 16 skipped** em 17,50s.

Não escopo (registrado para decisão):

- o app Flutter ainda usa `POST /message`; não há cliente WebSocket no app;
- `process_stream` **não** publica `orchestrator.responded` no EventBus (o
  `process` publica) — hoje ninguém assina esse tópico em produção, mas é uma
  diferença;
- o deploy no sistema real (restart do od-core) **não foi feito**: aguarda
  autorização explícita. O od-core segue no PID 314992 (2026-09-15 10:43:54) e a
  :8001 não está escutando.

Rodada 3 (09-18): app Flutter — cliente WebSocket no chat, com fallback para o REST

Pedido: *"Adicione o cliente WebSocket no app Flutter e ligue o chat nele, com
fallback para POST /message"*.

Implementação:

- **`app/lib/services/od_ws.dart` (novo)** — `OdStreamingChat` fala o protocolo
  do `ws_server` (`auth`/`message` → `authenticated`, `processing`, `token`…
  `done`) e entrega `OdChatDelta`s. Deriva a porta do streaming da URL já
  configurada (`http://host:8000` → `ws://host:8001`; `https` → `wss`;
  `wsPort` configurável). Usa `dart:io WebSocket` — **nenhum pacote novo no
  pubspec**.
- **Fallback automático para `POST /message`** + **cooldown de 2 min** depois
  de uma falha: sem o cooldown, toda mensagem pagaria o timeout de conexão
  antes de cair para o REST e o chat ficaria mais lento do que antes.
- **Interrupção no meio do stream não repete a mensagem**: com texto já na
  tela, um novo POST duplicaria a resposta (e a inferência no servidor); o app
  mostra o parcial e avisa na mesma bolha (`OdStreamingError`).
- **`chat_screen.dart`** — bolha nasce no primeiro token e é reescrita a cada
  frame, "Digitando..." só enquanto nada chegou, e um selo discreto do
  transporte (⚡ Streaming ativo / ↔ Resposta via REST) para conferir no
  celular. O `OdStreamingChat` é mantido entre mensagens (guarda o cooldown).
- **`OdApi(apiKey:)`** — chave só em memória, para os testes vivos rodarem sem
  o binding do Flutter (o binding troca o `HttpClient` por um dublê 400 e não
  haveria socket real).

Bug pego pelo teste de widget (e que valeu a rodada): o `await` no
encerramento do canal (`frames.cancel()` + `channel.close()`) **segurava o
gerador** — a bolha já final aparecia, mas o spinner do app não destravava.
Agora o encerramento é best-effort e sem `await`, e há um teste unitário com um
canal que **nunca fecha** (que penduraria com o `await`).

Testes: `flutter analyze` sem issues · `flutter test` **67 passed, 2 skipped**
(49 → 67) — `test/od_ws_test.dart` (12) e 3 de widget (render incremental,
fallback com selo, corte no meio). `test/ws_live_test.dart` (2) é **opt-in**
(`OD_LIVE_WS=1`) e usa o conector de PRODUÇÃO.

Teste do teste (3 mutações, revertidas): sem a guarda de texto parcial → 2
falhas; com o encerramento aguardado → 3 falhas (unitário + os 2 de widget com
spinner preso); sem cooldown → 1 falha.

Validação viva (sandbox) no nicky-server, contra o `od-core` de produção:
**36 deltas pelo WebSocket** (`transport=webSocket`, 35 frames de token)
listando "1 a 15" em ~8,6s; e com chave errada o streaming recusa e o app cai
para o REST, que devolve **401** (`OdAuthError`).

Achado no caminho (correção no servidor): o REST (`POST /message`) **valida o
perfil** e resolve `auto` → `guardian` (`DEFAULT_PROFILE`); o WebSocket mandava
`auto` cru. Como o app manda `profile: auto` por padrão, a MESMA conversa
cairia em baldes diferentes de cache/histórico conforme o transporte — e perfil
inválido era aceito no WS e recusado no REST (400). Corrigido em
`ws_server.py`, que agora importa `DEFAULT_PROFILE`/`DEFAULT_PROFILES` de
`integrations.api.server` (mesma fonte, sem duplicar a lista), resolve `auto` e
recusa perfil desconhecido com o mesmo texto do REST. +2 testes (suíte
**1719 passed, 16 skipped**) e mutações G/H provando que os dois pinam.

O usuário autorizou **tudo**: restart + APK + commit.

Restart (04:49:39, PID 399298, `NRestarts=0`) — paridade de perfil no ar, com
prova ao vivo: `profile: auto` pelo WebSocket registra
`Interaction recorded | user=deploy-check-2 | profile=guardian`, e `frodo`
recebe `perfil_desconhecido: frodo` sem processar. Journal com 0 Traceback.

APK **1.2.0+7** (`app/pubspec.yaml` 1.2.0+6 → +7) buildado por
`app/build_apk.sh` (Gradle `assembleRelease` em 45s) e publicado:

- `site/OmegaDrakon.apk` **52.230.399 B** — sha256 `c69f2ccd…`,
  `versionCode 7`;
- `site/OmegaDrakon-arm64.apk` **18.649.902 B** — sha256 `a5015cd7…`,
  `versionCode 2007`; `versionName 1.2.0` no `aapt dump badging`;
- sha256 **origem == site** e `GET /site/OmegaDrakon.apk` → HTTP 200 com o
  mesmo tamanho e hash;
- **prova no binário:** `Streaming ativo` 1x no novo contra 0x no anterior e
  `Resposta via REST` 1x contra 0x (controle `OmegaDrakon Online` 1x nos dois);
- build anterior (**1.2.0+6**) preservado em `backups/apk-v1.2.0-1006/`.

Instalar no Redmi Note 14 é atestação do usuário (o `adb` daqui não alcança o
aparelho) — **pendente**.

Encaminhamento (fim da rodada 2)

- Checkpoint atualizado (session.json: `updated_at` = 2026-09-18T05:05:00-03:00,
  blocos `streaming_ws_2026_09_18`, `retomada_2026_09_18` e `last_turn`).
- Arquivos tocados na rodada 2: `integrations/api/ws_server.py` (reescrito o
  ciclo de vida + `_LibraryLogger`), `core/llm.py` (reasoning fallback no
  stream), `runtime/launcher.py` (contenção da falha), `requirements.txt`
  (websockets), `tests/test_websocket.py` (reescrito, 28 testes) e
  `sandbox_agent/ws_sandbox.py` (novo, ignorado pelo git).
- Streaming do core: **implantado** em produção (PID 395579, :8001 no ar) e
  **commitado** em `7f2c004` (ainda **não** empurrado para o `origin`).
- App: cliente WebSocket + fallback **implementado, testado e validado ao vivo**,
  mas **não commitado** e **sem APK novo** (o celular segue no 1.2.0+6).
- Monitor do roteador: segue untracked e **ativo** em produção (timer systemd
  desde 09-17 10:26) — aguardando decisão sobre versionar.
- Pendências de decisão do usuário: publicar/apontar o commit no `origin`;
  rebuildar o APK (subir `versionCode`); versionar o monitor.
