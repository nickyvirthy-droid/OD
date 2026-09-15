2026-09-15 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu, nesta ordem: iniciar/README.md, iniciar/RULES.md,
  iniciar/session.json (521 linhas), iniciar/2026-09-13_conversa_omegadrakon.md e
  iniciar/2026-09-14_conversa_omegadrakon.md (íntegra, rodadas 1 a 11).

Estado conferido por evidência (não por memória), em 2026-09-15 ~09:34:

Git:
- `git log --oneline -6` → HEAD **f53ca72** ("docs: registra a publicação do
  registro de push no checkpoint"); antes dele bf25a12 (docs da ativação do
  push), 19afdde, 40d2bb0 (correções de 09-14), 8455493, 0dbd04a.
- `git status --short` → **dois arquivos modificados e não commitados**:
  iniciar/2026-09-14_conversa_omegadrakon.md (+49) e iniciar/session.json (+25).
  Ou seja: a **rodada 11** (remover a cópia da credencial, varrer o disco e
  gerar o zip de referência) foi escrita, mas NÃO foi publicada — o f53ca72
  cobre só até a rodada 10. Nada untracked (`--untracked-files=all` vazio).

Push FCM — ATIVO e em produção:
- `systemctl --user is-active od-core` → active; ActiveEnterTimestamp
  **2026-09-15 05:10:40** (PID 293371) — o serviço subiu sozinho de madrugada
  (não foi restart meu).
- journal 05:10:41 → "Push FCM inicializado | **enabled=True** | motivo= |
  credencial=config/firebase-service-account.json | dispositivos=1".
- `GET /push/devices` → `{ok:true, enabled:true, reason:"",
  project_id:"nicky-e4f99", devices:1}` e o aparelho com `sent:1, failed:0`
  (token d8Xhaf…Vj_0, android).
- `GET /` → version **1.2.0**, 26 endpoints, orchestrator true.
- `config/`: `firebase-service-account.json` (600, 2.373 B) e
  `iot_credentials.json` agora em **600** (a limpeza da rodada 11 persistiu).

Correções de 09-14 seguem provadas em produção:
- `dead_letter=0`, `handler_error=0`, `no_fix=0` no journal desde o restart.
- Face detector ativo: várias "Presença facial confirmada/encerrada" entre
  07:07 e 07:20 de hoje, cada uma com "Event published | topic=face.presence",
  sem nenhum "Handler error"/"dead letter" (antes da correção, todo
  face.presence gerava 3 WARN + 1 CRIT).
- `.od_repair_backups/` → **5 arquivos, 116 KB** (era 557 / 8,8 MB).

DIVERGÊNCIA com o registro da rodada 11 (não assumida, reportada):
- `ls -la 000` → **No such file or directory**: a pasta não existe mais no
  repositório.
- `/home/alex/000-omegadrakon-referencia-2026-09-14.zip` → **não existe mais**.
- A regra `000/` continua no .gitignore (linha 139) e nada untracked aparece →
  nenhum arquivo da pasta entrou no repositório em momento nenhum.
- A rodada 11 registrava `000/` intacta com 6 arquivos + zip de 462 KB. Não sei
  se a remoção foi limpeza do usuário ou de outra origem — **perguntar antes de
  qualquer ação** (regra 9: legado só sai depois do zip pronto e da confirmação
  do usuário).

Achado incidental no journal (madrugada de 09-15):
- Às **05:10:29** o processo ANTIGO (PID 271319) morreu com traceback: a task do
  Telegram (`runtime/launcher.py::_run_telegram_forever` → `bot.run()` →
  `integrations/telegram/transport.py::_call("getUpdates")` → `urllib`) lançou
  exceção de rede e o `asyncio.gather` de `_all()` propagou → `SystemExit` → o
  systemd reiniciou o serviço às 05:10:40.
- Depois do restart o transporte respondeu com o aviso tratado "Transporte
  indisponível — aguardando..." (722 ocorrências, a última às 05:14:23) e o
  serviço seguiu normal; parece ter sido a janela de rede no boot da máquina.
- Fica como **defeito latente a investigar** (não corrigido nesta retomada):
  uma falha de rede do Telegram derruba o processo inteiro do core em vez de
  ser contida na task — mesma família do bug de handler que corrigimos em
  09-14. Só vale abrir se o usuário quiser priorizar.

Nada foi alterado no servidor nesta retomada além do registro da sessão
(nenhum restart, nenhuma escrita fora de iniciar/). Aguardando a escolha do
usuário sobre por onde seguir.

Rodada 1 (09-15): a divergência da 000/ foi resolvida pelo usuário

- Relato: **o usuário apagou a pasta 000/ de propósito e fez uma cópia em HD
  externo**, e autorizou prosseguir.
- Leitura: a regra 9 foi satisfeita — o backup existe (fora do servidor) e a
  remoção foi confirmada por quem decidiu. Nada foi perdido: a cópia de
  referência deixou de viver na `/home/alex/`.
- Efeito no repositório: **nenhum** — a regra `000/` segue no `.gitignore:139`
  (útil se a pasta voltar) e nada untracked apareceu; nada da pasta entrou no
  histórico em momento algum.
- Ação: publicar as notas que ficaram pendentes (rodada 11 de 09-14 + esta
  retomada), que era o item "pendente de autorização" do checkpoint.
- Publicação: **commit `875be8d`** — _docs: registra a limpeza de credenciais e a
  retomada de 2026-09-15_ (3 arquivos, +171/-2) → **`origin/master
  f53ca72..875be8d`**. Verificação: suíte completa 1655 passed/16 skipped
  (nenhum código alterado) e varredura do staged por padrões de credencial sem
  material real (só nomes de campo e caminhos, texto descritivo).

Rodada 2: o defeito latente do Telegram — 89 quedas do core, corrigido em

**O achado era muito maior do que o caso das 05:10.** Contagem no journal desde
2026-09-13: **89 quedas e 89 restarts**, TODAS com
`TimeoutError: The read operation timed out`:

- 09-13, entre 02:53 e 07:25: **85 quedas** — crash loop de ~4,5 h, uma a cada
  2–3 min (restart counter chegou a **99**);
- 09-14: 14:56, 15:40 e 16:06 (3 quedas);
- 09-15: 05:10:29 (1 queda).

Cada queda derruba o **core inteiro** (API REST, RecoveryLoop, Presence Monitor,
Face Detector, MQTT, push) por ~10 s até o systemd reiniciar. O processo atual
está de pé desde 05:10:40 só porque a janela de rede ruim passou.

CAUSA RAIZ (confirmada no código, não deduzida):
`integrations/telegram/transport.py::HTTPTransport` — as três chamadas de rede
(`_call`, `send_voice`, `fetch_file`) só envolviam `HTTPError`/`URLError`.
`TimeoutError`/`ConnectionResetError`/`ssl.SSLError` que estouram na **leitura da
resposta** não passam pelo `URLError` (o urllib só envolve falhas de conexão),
então subiam cruas por: `bot.run()` (que só tolera `TransportError`) →
`_run_telegram_forever` → `asyncio.gather` do `launcher._all` (sem
`return_exceptions`) → `SystemExit` → systemd reinicia.

CORREÇÃO: captura de `OSError` (cobre `TimeoutError`, `ConnectionResetError` e
`ssl.SSLError`) nos três pontos, convertendo em `TransportError` — a camada de
transporte volta a cumprir o contrato que o bot já trata com backoff
("Transporte indisponível — aguardando..."). A ordem das cláusulas foi mantida
(`HTTPError` → `URLError` → `OSError`, que é a hierarquia correta).

TESTES (`tests/test_telegram.py`, +3):
- `test_call_read_timeout_becomes_transport_error`;
- `test_fetch_file_read_timeout_becomes_transport_error`;
- `test_run_survives_read_timeout` — polling com `HTTPTransport` REAL: o 1º
  `getUpdates` estoura timeout e o bot segue e processa o update seguinte.

TESTE DO TESTE: com o transporte antigo restaurado (`git stash` só da
correção), os **3 testes falham** — o de polling com exatamente
`TimeoutError: The read operation timed out` escapando do `bot.run()`, isto é,
a assinatura do journal reproduzida. Com a correção: 80 passed em
`tests/test_telegram.py`.

Suíte completa: **1658 passed, 16 skipped** (1655 + 3 novos).

Estado: **aplicado e verificado em sandbox (suíte); NÃO implantado no sistema
real e NÃO commitado** — aguarda autorização (regra 12: validar em sandbox,
só então ir ao sistema real).

Recomendação registrada para decisão futura (não executada):
`launcher._all` usa `asyncio.gather(*tasks)` **sem** `return_exceptions`, ou
seja, qualquer loop que morra derruba o core inteiro por design. O fix acima
fecha o caminho conhecido, mas o desenho continua frágil: o certo seria cada
loop ser uma task supervisionada, reiniciada sem levar o processo junto.

Rodada 3 (autorizada): publicar e implantar o fix

- Revisão do diff antes de commitar: só os três _except OSError_ acrescentados
  em `integrations/telegram/transport.py` (19 linhas), os 3 testes novos
  (74 linhas) e o registro da sessão; varredura do staged por AIza/PEM/ya29/sk-/
  padrão de token do Telegram → **nenhuma ocorrência**.
- **Commit `b215d07`** — _fix(telegram): converte timeouts de rede em
  TransportError_ (4 arquivos, +166/-2) → **`origin/master 875be8d..b215d07`**.
- **Deploy**: `systemctl --user restart od-core` → **active desde 2026-09-15
  09:40:29** (PID 303744).
- Verificação ao vivo (60 s de observação, mesmo PID — nenhum restart):
  - `/health` → `ok=true`, 8 checks;
  - `GET /push/devices` → `enabled=true, project_id=nicky-e4f99, devices=1`;
  - journal do restart: Push FCM `enabled=True`, API REST no ar, TelegramBot
    `transport=HTTPTransport`, Presence Monitor e Face Detector ativos;
  - contadores desde o restart: **tracebacks=0, TimeoutError=0,**
    "Transporte indisponível"=0**, Handler error=0, no_fix=0**;
  - 09:40:55 → "Presença facial confirmada" + "Event published |
    topic=face.presence" sem dead letter.
- Ressalva registrada (honestidade sobre o que a evidência cobre): o fix
  elimina o **caminho** de queda, mas a prova de que não haverá nova queda só
  vem na próxima janela de rede ruim (antes: 85 quedas em 4h30 no 13/09).
  A assinatura a procurar de agora em diante é "Transporte indisponível —
  aguardando..." (tratado) e **não** `TimeoutError` + "Main process exited".

Rodada 4 (pedido do usuário): auditar as outras integrações de rede

Método: o critério não é a integração em si, e sim **o que roda dentro do
`asyncio.gather` do `launcher._all`** — é o gather que transforma qualquer
exceção não tratada em queda do processo inteiro. Cada loop foi lido
procurando qual exceção escaparia dele.

| loop no gather | protegia-se? | risco |
|---|---|---|
| API REST (`_run_api_forever`) | servidor sobe em thread; o lado asyncio só dorme | seguro |
| Telegram (`bot.run`) | só `TransportError` | corrigido hoje (`b215d07`) |
| Recovery (`loop.run`) | `except Exception` no tick | já protegido |
| **MQTT (`bridge.run`)** | **`await self.poll_once()` sem try** | **derrubava o core** |
| **Presence (`monitor.run`)** | **`await self.tick()` sem try** — o tick só protege a leitura do HA; I/O do estado, sink e bus ficavam fora | **derrubava o core** |
| **Vision (`detector.run`)** | **`await self.tick()` sem try** — só a captura era protegida; detecção (cv2) e publish no bus ficavam fora | **derrubava o core** |
| Notifier | thread própria + `except Exception` no loop e nos sinks | seguro |
| FCM (`core/push.py`) | `http_request` **já** capturava `(URLError, OSError, ValueError)` → PushError; `notify` pega `PushError`; sinks do notifier pegam `Exception` | já correto |
| `HAClient._request` | só `HTTPError`/`URLError` | ⚠️ `TimeoutError` na leitura escapava cru |
| `launcher._all` | `asyncio.gather(*tasks)` **sem isolamento** | ⚠️ o mecanismo que converte qualquer linha acima em queda total |

CORREÇÕES:
1. **Redes de segurança nos 3 loops** (`integrations/mqtt/bridge.py`,
   `integrations/homeassistant/presence.py`, `tools/vision/face_detector.py`):
   `try/except Exception` em volta de `poll_once()`/`tick()` — a mesma
   disciplina que o `RecoveryLoop` já tinha ("ciclo nunca morre"), contando o
   erro na métrica e logando sem encerrar o loop.
2. **`integrations/homeassistant/client.py`**: `except OSError` → `HAError` no
   `_request` (contrato do cliente é levantar `HAError`).
3. **`runtime/launcher.py`**: novo `_supervise(name, factory, restart=True,
   delay_s=5.0)` — contém a exceção, registra "Loop do núcleo caiu" e reinicia
   com espera; a API entra com `restart=False` (recriar o servidor conflita na
   porta 8000). O `_all` agora monta todos os loops supervisionados.

TESTES (+8): `tests/test_launcher_supervisor.py` (novo, 4) e 1 em cada de
`test_mqtt.py`, `test_presence.py`, `test_face_detector.py` e
`test_homeassistant.py`.

TESTE DO TESTE:
- com as 4 redes de segurança revertidas (`git stash`), os **4 testes de loop
  falham** com `TimeoutError` escapando do ciclo;
- demo do gather com o código novo: `sem_supervisao` →
  `TimeoutError: The read operation timed out` sobe (a assinatura do journal);
  `com_supervisao` → o gather **conclui sem exceção** e o log mostra
  `[NICKY][ERROR] Loop do núcleo caiu | loop=telegram | error=TimeoutError`.

Suíte completa: **1666 passed, 16 skipped** (1658 + 8 novos).

Estado: aplicado e verificado em sandbox; **NÃO implantado e NÃO commitado** —
aguarda autorização (regra 12).

Rodada 5 (autorizada): publicar e implantar a auditoria

- Revisão do diff antes de commitar (10 arquivos, +283/-12) e varredura do
  staged por AIza/PEM/ya29/sk-/token do Telegram → **nenhuma ocorrência**.
- **Commit `0c5b9d8`** — _fix(runtime): isola os loops do core para uma falha
  não derrubar o processo_ → **`origin/master ec246ac..0c5b9d8`** (o
  `tests/test_launcher_supervisor.py` é novo no repo).
- **Deploy**: `systemctl --user restart od-core` → **active desde 2026-09-15
  09:48:05** (PID 305298).
- Verificação ao vivo (~75 s, mesmo PID — nenhum restart):
  - `/health` → `ok=true` com os **8 checks ok** (orchestrator, llm, audit,
    metrics, database, homeassistant, mqtt, perception);
  - `GET /push/devices` → `enabled=true, project_id=nicky-e4f99, devices=1`;
  - journal: RecoveryLoop, ProactiveNotifier, Presence Monitor, Face Detector,
    API REST e TelegramBot habilitados; "Ponte MQTT habilitada" →
    "MQTT conectado | host=127.0.0.1:1883 | client_id=od-core";
  - contadores desde o restart: **tracebacks=0, TimeoutError=0,
    "Loop do núcleo caiu"=0**.
- Nota de método: o deploy não pode forçar uma falha de rede para ver a
  supervisão agir ao vivo — a garantia vem dos testes (teste do teste já
  registrado na rodada 4) e do código em execução; a assinatura a observar daqui
  em diante é `Loop do núcleo caiu | loop=...` (contido e reiniciado) em vez de
  `Traceback` + "Main process exited" (processo morto).

Rodada 6 (pedido do usuário): alertar quando um loop é reiniciado

**O problema do fix da rodada 5:** a supervisão continha a queda, mas ela virava
**silenciosa** — e foi exatamente esse silêncio que deixou as 89 quedas de 13/09
a 15/09 passarem até eu ler o journal. Agora a queda fica visível nos dois
canais que o usuário já acompanha.

DESENHO:

1. **`core/supervision.py` (novo)** — `LoopSupervision` (failures, restarts,
   last_drop_ts, last_kind, last_error) e `SupervisionRegistry` thread-safe
   (o launcher escreve na thread do asyncio; o health/notifier leem de outras),
   com `evaluate()` (degradado = queda dentro da janela de 300s), `health()` no
   contrato do Health Monitor, `snapshot()` e `reset()`. Instância única do
   processo em `SUPERVISION` / `get_supervision()`.
2. **`runtime/launcher.py`** — `_supervise` passa a registrar `record_drop`
   (tipo + detalhe truncado em 300 chars) e `record_restart`; loop que
   **retorna sozinho** também conta como queda (`kind=Returned`).
   `build_health` registra o check **`loops`** (critical=False): queda recente
   **degrada** o /health em vez de derrubá-lo, e passada a janela ele volta a ok
   sozinho.
3. **`integrations/notifier.py`** — `_check_loops` entra em `_default_checks()`:
   um `CheckResult` por loop conhecido — `ok=False` com key `loop:<nome>` quando
   degradado (**WARN**) e **CRIT** se o loop já reiniciou 3+ vezes
   (`CRASH_LOOP_RESTARTS`); quando estável devolve `ok=True`, o que **limpa** o
   problema dentro do notifier. O anti-spam continua sendo o do notifier
   (1 alerta/hora por loop).

TESTES (+17): `tests/test_supervision.py` (novo, 12), `TestLoopsCheck` em
`tests/test_launcher_health_external.py` (3) e 2 em
`tests/test_launcher_supervisor.py` (queda e retorno entrando no registro).
`tests/test_notifier.py::test_dump_shape` passou a pinar as 5 sondas padrão em
vez do número 4.

TESTE DO TESTE (3 mutações, revertidas depois):
- tirar `_check_loops` de `_default_checks()` → `test_dump_shape` **falha**;
- tirar o `register("loops", ...)` do `build_health` →
  `TestLoopsCheck::test_check_registrado` **falha**;
- `record_drop` sem registrar os dados → os testes de registro e de health
  **falham**.
Resultado: **15 dos 18 testes-alvo falharam**, incluindo os dois pinos de
fiação. Suíte completa: **1683 passed, 16 skipped** (1666 + 17 novos).

Estado: aplicado e verificado em sandbox; **NÃO implantado e NÃO commitado** —
aguarda autorização (regra 12).

Rodada 7 (autorizada): publicar e implantar o alerta

- **Commit `fc2abe0`** — _feat(observability): torna visível a queda de loop
  reiniciado pela supervisão_ (7 arquivos, +659/-7; `core/supervision.py` e
  `tests/test_supervision.py` são novos) → **`origin/master d06f44b..fc2abe0`**.
  Varredura do staged por padrões de credencial: nenhuma ocorrência.
- **Deploy**: `systemctl --user restart od-core` → **active desde 2026-09-15
  09:58:16** (PID 307723).
- Verificação ao vivo:
  - `/health` → `ok=true, status=up` com **9 checks**; o novo `loops` aparece
    como não-crítico e ok: `{ok: true, status: "up", detail: "nenhum loop
    supervisionado registrado", critical: false}` — o estado correto, já que
    nenhum loop caiu desde o boot;
  - PID estável, `tracebacks=0, TimeoutError=0, "Loop do núcleo caiu"=0`;
  - introspecção do código implantado: as sondas padrão do notifier são
    `[_check_orchestrator, _check_llm, _check_disk, _check_loops,
    _check_restart]` → o alerta de loop está ativo em produção.
- Limitação registrada com honestidade: a API não tem rota do notifier, então a
  lista de sondas dele não é observável pelo `/health`; a prova é a
  introspecção no código implantado + os testes. **O primeiro alerta real**
  aparecerá no Telegram/push quando (e se) um loop cair — e o `/health` ficará
  `degraded` por até 300 s com o nome do loop no detalhe.

Rodada 8 (pedido do usuário): rota da API para o app consultar

**`GET /supervision`** (com `X-API-Key`, como as demais rotas de dados):

```json
{ "ok": true, "status": "up", "window_s": 300.0, "degraded": [],
  "restarts": 0, "loops": [], "ts": 1773... }
```

Semântica alinhada à do `/health`: `ok=false` + `status=degraded` significam
"loop caiu dentro da janela" e a resposta continua **HTTP 200** (o core está de
pé — degradado não é erro de requisição). Cada item de `loops[]` traz `name`,
`failures`, `restarts`, `last_kind`, `last_error`, `age_s`, `degraded` e
`crash_loop`.

Implementação: entrada em `_ROUTE_SPECS` (depois de `/push/devices`) + handler
`supervision()` que delega a `get_supervision().evaluate()`. O `GET /` passou a
reportar **27 endpoints** (o `len(ROUTES)` é calculado, não fixo).

TESTES: tabela de rotas atualizada (26 → 27, com `/supervision` no conjunto
**autenticado**) + `TestAPISupervision` (3): sem quedas; loop caído degradando o
payload; e 401 sem chave / 200 com chave.

TESTE DO TESTE (2 mutações, revertidas): rota com `auth=False` →
`test_auth_flags_follow_legacy` **falha**; handler com `ok=True` fixo →
`test_loop_caido_degrada` **falha**. `tests/test_api.py` → 80 passed.

Suíte completa: **1686 passed, 16 skipped** (1683 + 3 novos).

DOCUMENTAÇÃO (item 4 da Definition of Done — `docs/REGRAS_DE_TRABALHO.md` §2):
`docs/CHANGELOG.md` ganhou as subseções **"Corrigido (2026-09-15)"** (timeout do
Telegram + isolamento dos loops, que ainda não estavam registrados no arquivo) e
**"Adicionado (2026-09-15) — supervisão dos loops visível"** (registro, check no
`/health`, alerta do notifier e a rota). O cabeçalho da `[1.2.0]` passou a citar
2026-09-15. As menções históricas a "26 endpoints" no `docs/README_VERSAO.md`
foram **mantidas** (são evidência da entrega 1.2.0, não estado atual); o número
corrente (27) está no CHANGELOG.

Rodada 9 (autorizada): publicar e implantar a rota e o CHANGELOG

- **Commit `05cc30e`** — _feat(api): expõe GET /supervision com o estado dos
  loops do núcleo_ (2 arquivos, +99/-2) → **`origin/master 454967f..05cc30e`**.
  Varredura do staged por padrões de credencial: nenhuma ocorrência.
- **Deploy**: `systemctl --user restart od-core` → **active desde 2026-09-15
  10:06:37** (PID 309583).
- Verificação ao vivo:
  - `GET /` → `version=1.2.0`, **`endpoints=27`**;
  - `GET /supervision` com a chave →
    `{ok:true, status:"up", window_s:300.0, degraded:[], restarts:0, loops:[],
    ts:...}` — lista vazia é o esperado (nenhum loop caiu desde o boot);
  - sem chave → **HTTP 401**;
  - PID estável após 60 s: `tracebacks=0, TimeoutError=0, "Loop do núcleo
    caiu"=0, "API erro"=0`.

Rodada 10 (pedido do usuário): supervisão na aba Status + republicar o APK

IMPLEMENTAÇÃO NO APP:
- **`app/lib/services/od_api.dart`** — novo `getSupervision()` (`GET
  /supervision`). Ponto importante: `ok=false` + `status=degraded` são tratados
  como **resposta válida** (HTTP 200); só `status != 200` vira erro. Degradado
  não é falha de requisição — o core está de pé.
- **`app/lib/screens/status_screen.dart`** — card **"Supervisão dos loops"**
  com estado, janela, total de reinícios e uma linha por loop
  (`name`, `restarts`, `last_kind`, `age_s`). O carregamento vive num
  `_loadSupervision()` com try/catch **próprio**: se a rota falhar (servidor
  antigo), o card avisa "Supervisão dos loops indisponível" e o resto da aba
  continua funcionando — a mesma lição do bug do `system` aninhado no APK
  1.2.0. Sem cast: só `is` + fallback.
- **`app/pubspec.yaml`** — `1.2.0+5 → 1.2.0+6`. O `versionCode` tinha de subir:
  com o mesmo código o Android recusaria instalar por cima do APK anterior.

TESTES DO APP (+6 → **48 passed**; era 42):
- `od_api_test.dart`: payload saudável; **degradado como sucesso**; `!= 200`
  lança `OdApiError`;
- `widget_test.dart`: supervisão sem quedas; **loop caído no card**; rota
  indisponível **sem derrubar a tela** (o `_mockApi()` ganhou a rota).
- `flutter analyze` → sem issues.
- TESTE DO TESTE (2 mutações, revertidas): tratando `ok=false` como erro no
  cliente e omitindo a chamada na `_refresh()` → **4 testes falham**.

APK (build 1.2.0+6):
- Backup antes de sobrescrever: o build anterior (1.2.0+5) foi para
  `backups/apk-v1.2.0-1005/` e o `sha256sum` bateu com o registrado na entrega
  de 1.2.0 (`00d72011…` full, `1c5771c4…` arm64) — confirmação de que o arquivo
  preservado é o mesmo que estava publicado.
- Build por `app/build_apk.sh` (PATH com `/home/alex/flutter/bin` e
  `/home/alex/jdk/bin`; `ANDROID_HOME=/home/alex/android-sdk`).
- `aapt dump badging`: **versionName 1.2.0 / versionCode 6** (completo) e
  **2006** (arm64).
- Publicado em `site/OmegaDrakon.apk` (51.935.427 B, sha256 `b325ad23…`) e
  `site/OmegaDrakon-arm64.apk` (18.518.770 B, sha256 `f3f86059…`) — origem ==
  site conferido nos dois.
- `GET /site/OmegaDrakon.apk` pela API → HTTP 200, **mesmo tamanho e mesmo
  sha256** do arquivo local (o celular baixa a build nova).
- PROVA NO BINÁRIO: o primeiro intento (`unzip -p ... | strings`) deu **0 até
  para a string de controle** `OmegaDrakon Online` — método errado, não APK
  errado. O correto foi `grep -ac` no APK cru:

  | string | APK anterior (1005) | APK novo (1006) |
  |---|---|---|
  | `OmegaDrakon Online` (controle) | 1 | 1 |
  | `supervision` | 0 | **2** |
  | `Nenhum loop reiniciado` | 0 | **1** |

  O diferencial confirma que o código novo está dentro do binário.
- `site/index.html` continua correto ("v1.2.0 • ~18 MB • Android 7.0+") — a
  versão não mudou, então a landing não precisou de ajuste.

Estado: app aplicado e verificado em sandbox; **APK já republicado em `site/`**
(pedido explícito do usuário); **código do app NÃO commitado** — aguarda
autorização para publicar.

Rodada 11 (autorizada): publicar o app

- **Commit `4be7af9`** — _feat(app): mostra a supervisão dos loops na aba
  Status_ (5 arquivos, +313/-1: `status_screen.dart`, `od_api.dart`,
  `pubspec.yaml` 1.2.0+6 e os dois arquivos de teste) →
  **`origin/master ca64d96..4be7af9`**. Varredura do staged por padrões de
  credencial: nenhuma ocorrência.
- **Sem restart do `od-core`**: nada de servidor mudou nesta rodada — a rota
  `GET /supervision` já está no ar desde `05cc30e` (10:06:37). O que se distribui
  aqui é o binário do app, já republicado em `site/`.
- **Limpeza colateral**: minhas próprias verificações deixaram um diretório
  `classes.dex/` (20 MB, extração de APK) na raiz do repo — conferi que só tinha
  conteúdo de APK (`AndroidManifest.xml`, `res/`, `assets/`, `.properties`) e
  removi. `git status` voltou a mostrar só os arquivos da entrega, e `site/*.apk`
  e `backups/apk-*/` seguem cobertos pelo `.gitignore` (linhas 123 e 124), então
  nenhum binário entra no histórico.
- **O que o servidor NÃO atesta**: a instalação do APK 1.2.0+6 no Redmi Note 14
  e o card aparecendo na aba Status — isso é confirmação do usuário.

Rodada 12: instalar no aparelho e conferir o card na aba Status

- Primeiro tentei o caminho técnico: `adb` em
  `/home/alex/android-sdk/platform-tools/adb` não alcança o aparelho —
  `adb devices` vazio e timeout na conexão. Não há device anexado nem
  pareamento de depuração sem fio, e eu não tenho como instalar daqui. Em vez de
  dizer "não dá", fiz a verificação mais próxima possível: **renderizar a aba
  Status com os payloads REAIS do servidor**.
- Payloads capturados do próprio `od-core` v1.2.0+6: o `up` pelo IP do tailnet
  (o mesmo caminho que o celular usa) e o `degraded` do endpoint rodando em
  processo com um loop `telegram` caído.
- Primeira tentativa FALHOU — e a causa era do teste, não do app: com o
  `/health` real (8 checks) o card de supervisão fica **abaixo da dobra** e o
  `ListView` só constrói o que está visível. Precisei rolar até ele.
- O teste temporário virou **teste permanente**, no mesmo precedente do
  `capabilities_manifest.json`: fixture
  `app/test/fixtures/supervision_payloads.json` (payloads reais, com uma nota
  dizendo de onde vieram) + `renderiza os payloads REAIS de /supervision (up e
  degradado)` em `app/test/widget_test.dart`.
- Armadilha encontrada no caminho: o segundo `pumpWidget` **reaproveitava o
  `State`** (mesmo tipo, sem key), então o `initState` não rodava de novo e a
  segunda renderização continuava com o payload `up` — o teste falhou com
  `Found 0 widgets with text "1 reiniciado(s)"`. Resolvido com um pump de
  `SizedBox` no meio, comentado no próprio teste.
- TESTE DO TESTE: mutando a fixture (renomeando `last_kind` → `kind`, isto é,
  simulando uma mudança de contrato do servidor) o teste **FALHA** — a fixture
  é um pino real do contrato, não uma tautologia. Fixture restaurada e conferida
  idêntica ao original (diff de JSON canônico).
- Suíte do app: `flutter analyze` sem issues · `flutter test` → **49 passed**
  (48 → 49). Os arquivos temporários da verificação (teste e payload em /tmp)
  foram removidos.

Correção de um erro meu nesta rodada:

- Eu havia registrado o tamanho do arm64 como **18.518.638 B** — e esse número é
  o do **APK anterior**. Eu li o `ls -la` antes do build. O APK 1.2.0+6 tem
  **18.518.770 B** (`stat`, igual em `app/build/.../app-arm64-v8a-release.apk`,
  em `site/` e no download pelo tailnet). Corrigido em `docs/CHANGELOG.md`, no
  `session.json` e aqui; o `sha256` (`f3f86059…`) sempre esteve certo.

Estado: verificação forte do lado que consigo medir (payload real → renderização
comprovada por teste); **o que segue dependendo de você** é instalar o APK no
aparelho e ver o card na aba Status. `app/test/widget_test.dart` e a fixture
nova **não foram commitados** — aguardam autorização (regra 12).
