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
