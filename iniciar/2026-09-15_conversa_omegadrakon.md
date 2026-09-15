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
