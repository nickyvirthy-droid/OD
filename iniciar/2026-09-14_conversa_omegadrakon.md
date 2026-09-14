2026-09-14 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu, nesta ordem: iniciar/README.md, iniciar/RULES.md,
  iniciar/session.json, iniciar/2026-09-13_conversa_omegadrakon.md e
  iniciar/2026-09-12_conversa_omegadrakon.md.

Estado conferido por evidência (não por memória):

Git:
- `git log --oneline -5` → HEAD **8455493** ("chore(git): tira do repositório
  000/ e os arquivos de trabalho local"); antes dele 0dbd04a (checkpoint),
  3b5599c (entrega de push FCM), 8c58520, 68cf2e5.
- `git status --short` → **limpo** (nada pendente, nada untracked).
- Conclusão: o commit do .gitignore (000/ + arquivos soltos da raiz) que a
  rodada 5 de ontem deixou "publicado em seguida" está feito — não há trabalho
  de escrita pendente no repositório.

Credencial do FCM (bloqueio que segue aberto):
- `ls -la config/firebase-service-account.json` → No such file or directory.
- `config/` só tem iot_credentials.json e iot_credentials.example.json.
- A service account continua **ausente no servidor** (mesma situação das
  rodadas 3 e 4 de 2026-09-13). O upload reportado pelo usuário nunca chegou.

Push FCM em execução (ao vivo):
- `systemctl --user is-active od-core` → active; subiu em 2026-09-13 15:56:17
  (PID 191992 — o restart do fim do dia anterior).
- Journal: último "Push FCM inicializado | enabled=False |
  motivo=credencial_ausente | credencial=- | dispositivos=0" às 15:56:17,
  igual a todos os restarts desde 07:19: nada mudou.
- `GET /push/devices` (com a chave do `.env`, 127.0.0.1:8000) →
  `{ok:true, enabled:false, reason:"credencial_ausente", project_id:"",
  devices:0, devices_detail:[]}`.

Tailnet (`tailscale status`):
- nicky-server online (100.77.67.53).
- **redmi-note-14-1 (100.80.224.73) OFFLINE**, visto pela última vez há 7h.
  O aparelho precisa estar online/aberto para registrar o token.

Pontos abertos herdados (todos ainda válidos):
1. Service account do Firebase em config/firebase-service-account.json — só o
   usuário pode gerar no console (projeto nicky-e4f99). Sem ela /push/test
   responde 503 e o envio fica dormente.
2. Instalar/abrir o APK 1.2.0+5 (1005) no Redmi Note 14 para o token ser
   registrado (o aparelho está offline no tailnet).
3. Achados do journal: SelfRepair `no_fix` em agent.py (a cada ~5 min) e o
   handler face.presence com AttributeError → dead letter.

Nada foi alterado no servidor nesta retomada (nenhum restart, nenhuma escrita
fora do registro da sessão). Aguardando a escolha do usuário sobre por onde
seguir.

Rodada 1 (escolha do usuário): "Achados do journal (sem depender de você)"

=== ACHADO 1 — face.presence / AttributeError · BUG REAL · CORRIGIDO ===

Sintoma no journal (ativo hoje, não só em 09-12):
- 09:29:55, 09:31:17, 10:27:10 e 10:27:39 → em cada `face.presence`:
  "Handler error (attempt 1/3, 2/3, 3/3) |
  handler=_run_vision_forever.<locals>.on_change | error=AttributeError" e
  "Handler failed — dead letter".

CAUSA RAIZ (confirmada no código e reproduzida em teste):
- `core/event_bus.py:387` entrega o **Event** ao handler
  (`result = sub.handler(event)`); o payload fica em `event.data`. Convenção
  usada por todo o projeto (bridge MQTT `handler(event)`, testes com
  `lambda e: e.data`).
- `runtime/launcher.py` registrava `on_change(data)` e chamava
  `data.get("confirmed")` — `.get()` no próprio Event →
  `AttributeError: 'Event' object has no attribute 'get'`. O journal só mostra
  o NOME da exceção (o bus loga `error=type(exc).__name__`), por isso o motivo
  exigiu leitura do código.

CORREÇÃO (runtime/launcher.py, `_run_vision_forever`):
- handler passa a receber `event` e a ler `data = getattr(event, "data",
  None) or {}`, com guarda de tipo antes do `.get("confirmed")`; docstring
  ganhou a nota da correção v1.2.1.

TESTE DO TESTE (reprodução da assinatura exata do journal):
- `tests/test_launcher_vision.py` (novo, 4 testes): bus real + detector fake.
- Com o handler ANTIGO restaurado, os 4 testes FALHAM e imprimem exatamente as
  linhas do journal (Handler error 1/3, 2/3, 3/3 com AttributeError + dead
  letter). Com a correção: 4 passed.
- Suíte completa: **1651 passed, 16 skipped** (1647 + 4 novos).

=== ACHADO 2 — SelfRepair no_fix em agent.py · JÁ CESSOU · AMPLIFICAÇÃO SEGUE ===

O sintoma NÃO está acontecendo agora (evidência, não dedução):
- Último `SelfRepair no_fix` / snapshot: **2026-09-13 15:42:16**.
- O loop está VIVO: o audit registra `perception.snapshot` a cada ~5min, os
  três últimos às **13:06:11, 13:11:12 e 13:16:16 de HOJE (09-14)**;
  `/health` → check "perception" ok=true, "0 erros de sonda".
- `agent.py` (raiz) **foi substituído hoje às 02:17:47** por uma versão
  válida: `ast.parse` → OK. O `.bak` de 15:42 (13.217 B) ainda tinha o erro de
  sintaxe na linha 325 (`system_prompt = f"""`); o arquivo atual (12.809 B) é
  outra versão ("OmegaDrakon Agent - Versão estável") — 408 linhas de diff.
  Ou seja: o no_fix parou porque a origem (arquivo quebrado) deixou de existir.

CAUSA RAIZ do ruído (1.578 linhas de journal em ~2 dias):
- `core/recovery.py::iter_py_files` varre TODO .py do root fora dos diretórios
  excluídos — arquivos soltos na raiz entram no escopo. `agent.py` é o
  primeiro em ordem alfabética e é o par local do `sandbox_agent/` (declarado
  pelo usuário como "não é o sistema" e agora ignorado no git).
- Cada tick: `detect` acha o erro de sintaxe → `repair` (max_repairs_per_tick
  = 3) → `_take_snapshot` escreve um .bak novo com carimbo de tempo →
  nenhuma estratégia determinística resolve → `no_fix`.

AMPLIFICAÇÃO QUE PERMANECE (defeito latente):
- `.od_repair_backups/`: **557 arquivos, 8,8 MB, TODOS do mesmo digest
  (c3aa9f218ecd)** — um snapshot por tick, sem retenção/dedup. Enquanto o
  arquivo estava quebrado, cresceu ~13 KB a cada 5 min, indefinidamente.
- O laço continua gastando as 3 vagas de reparo do tick em arquivos alheios ao
  sistema quando algum deles volta a quebrar.

Nada foi alterado por causa do achado 2 — decisão pendente do usuário sobre
como tratar a amplificação (dedup/retenção de snapshots x escopo da varredura).

Rodada 2 (decisões do usuário): dedup + retenção de snapshots, e restart do od-core

Autorizado: (1) tratar a amplificação com dedup + retenção de snapshots
(sem mexer no escopo da varredura); (2) reiniciar o od-core para o fix do
face.presence entrar no ar.

=== CORREÇÃO NO SELF REPAIR (core/self_repair.py) — v1.2.1 ===

- Novo parâmetro `max_snapshots_per_file` (default
  `DEFAULT_MAX_SNAPSHOTS_PER_FILE = 5`).
- `_take_snapshot`: DELEGOU o nome ao novo `_next_snapshot_path` e agora
  (a) DEDUP — se já existe snapshot com os MESMOS bytes, ele é reutilizado
  (nenhum arquivo novo), via `_find_identical_snapshot`; (b) RETENÇÃO — após
  criar, `_prune_snapshots` mantém no máximo N por arquivo (por digest),
  nunca removendo o snapshot atual.
- Bug colateral corrigido no caminho: o nome usava `int(time.time())`, então
dois ciclos do MESMO arquivo no mesmo segundo gravavam o mesmo nome e o
snapshot anterior era SOBRESCRITO. `_next_snapshot_path` agora avança o
carimbo até o nome estar livre (o formato dos arquivos não mudou).
- `dump()` passou a expor `max_snapshots_per_file`.

Testes (tests/test_self_repair.py, classe `TestSnapshotDedupERetencao`, 4 novos):
- 5 ciclos com conteúdo inalterado reutilizam UM snapshot;
- conteúdo novo ainda gera snapshot novo (dedup só vale para bytes idênticos);
- retenção com cap=2 corta o excedente e o snapshot mais recente é o estado
  atual do arquivo;
- cap=0 é normalizado para 1.
TESTE DO TESTE: com o comportamento anterior restaurado (sem dedup, sem
retenção, sem bump de colisão), os 4 testes FALHAM; com a correção, os 4
passam. Suíte completa: **1655 passed, 16 skipped** (1647 + 8 novos).

LIMPEZA RETROATIVA (autorizada pelo item "mata o crescimento de 8,8 MB"):
os 557 snapshots foram conferidos antes — 3 conteúdos distintos (9.929,
13.217 e 13.228 B). Aplicado o próprio `_prune_snapshots` do engine
(digest c3aa9f218ecd, keep = o mais novo): **removidos 552, mantidos os 5 mais
novos** → `.od_repair_backups/` de **8,8 MB → 116 KB**. O mais novo (15:42 de
13/09) preserva a possibilidade de restaurar o estado anterior ao arquivo ser
trocado.

=== DEPLOY DO FIX DO FACE.PRESENCE + VERIFICAÇÃO AO VIVO ===

- `systemctl --user restart od-core` → **active desde 2026-09-14 13:24:40**
  (PID 264390); journal: Push FCM (enabled=False), RecoveryLoop,
  ProactiveNotifier, Presence Monitor e Face Detector todos habilitados.
- `/health` → ok=true, 8 checks.
- **PROVA AO VIVO**: às **13:25:09** o detector publicou um `face.presence`
  real ("Event published | topic=face.presence | subscribers=1") e, depois
dele, **NÃO há nenhuma linha de "Handler error" nem "dead letter"** — antes
da correção, TODO face.presence gerava 3 WARN + 1 CRIT. O handler corrigido
rodou limpo no processo em produção.
- RecoveryLoop pós-restart: "iniciando ciclo periódico | interval_s=300.0",
  nenhum snapshot/self-repair (nenhuma detecção — agent.py saudável).

Rodada 3 (autorizada): commit + push das duas correções

- Revisão antes de commitar: `git diff` dos quatro arquivos de código/teste +
  `git log` para seguir o estilo do repo.
- Ajuste de consistência de versão: as notas de código/teste diziam
  "v1.2.1", mas `OD_VERSION` segue **1.2.0** — troquei por **(2026-09-14)**
  (launcher, self_repair, os dois arquivos de teste) e registrei no
  `docs/CHANGELOG.md` como **"### Corrigido (2026-09-14)"** dentro da seção
  [1.2.0], em vez de inventar uma versão sem o bump correspondente.
- `docs/CHANGELOG.md`: nova subseção com o diagnóstico, a correção, a
  evidência de produção e a limpeza retroativa dos snapshots; cabeçalho da
  [1.2.0] atualizado para "correções em 2026-09-12 e 2026-09-14".
- Verificação: suíte completa **1655 passed, 16 skipped**; varredura do staged
  por `AIza`/`PRIVATE KEY`/`api_key`/`password`/`secret` sem ocorrências.
- **Commit `40d2bb0`** — _fix(core): corrige o handler de face.presence e
  limita snapshots do SelfRepair_ (7 arquivos, +603/-19).
- **Push**: `origin/master 8455493..40d2bb0`.

Estado final da sessão: as duas correções estão no ar E publicadas; o
checkpoint desta sessão foi atualizado com o hash (commit de docs separado,
como nas entregas anteriores).

Rodada 4 (autorizada): destravar o push FCM — estado e caminho de transferência

Estado reconferido no servidor (nada mudou desde 13/09):
- `config/` só tem `iot_credentials*` — **`config/firebase-service-account.json`
  não existe**; `.env` sem `OD_FCM_CREDENTIALS`/`OD_PUSH_ENABLED`/
  `OD_PUSH_PROJECT_ID`.
- od-core (PID 264390): `Push FCM inicializado | enabled=False |
  motivo=credencial_ausente | dispositivos=0`.
- tailnet: `redmi-note-14-1` **offline há 7h** → `/push/devices` com 0.

Descoberta útil sobre o LIGAR: não é preciso mexer no `.env`. Sem
`OD_PUSH_ENABLED`, o default é "ligado se houver credencial"
(`PushService.enabled` cai em `sender.available`; `core/push.py`,
`CREDENTIAL_CANDIDATES` = `config/firebase-service-account.json` →
`config/fcm-service-account.json` → `docs/firebase-service-account.json`).
Ou seja: arquivo + restart = push ligado.

Transferência: escolhido **Taildrop**, mas o `tailscale file get` exige root —
`getting WaitingFiles: Access denied: file access denied` e `sudo -n` pede
senha (não tenho). Caminhos oferecidos: (a) `sudo tailscale set --operator=alex`
uma vez (passa a funcionar para mim e nas próximas), (b) `sudo tailscale file get
/tmp/od_taildrop` só desta vez, (c) scp do desktop, (d) colar o JSON no chat.
O usuário já tem o arquivo baixado.

Rodada 5 (pedido do usuário): ler a pasta 000/ e o txt.txt

Conteúdo real (nada de credencial em nenhum deles):
- `txt.txt` (raiz, 13 KB) — dump de texto do console do Firebase: páginas
  **Geral / Integrações / Privacidade / Alertas** + registro do app Android
  (`com.omegadrakon.nicky`, app ID `1:582855984584:android:8fea63966ed40cdf`) e
  instruções de SDK. **Não** é a aba "Contas de serviço" — por isso não tem (e
  não pode ter) a chave privada.
- `000/app.txt` — dump parecido (project_id `nicky-e4f99`, número
  `582855984584`, e-mail de suporte `nickyvirthy@gmail.com`).
- `000/freebuff-intencoes.md` — intenções de produto do Freebuff; nada de FCM.
- `000/chatGPT.md` (53 KB) — conversa/pesquisa sobre agentes locais
  (Open Interpreter, OpenHands, OpenCode, Freebuff), estado do OD e prompt de
  continuidade. `grep` por conta de serviço/private_key/FCM/push/nicky-e4f99
  → **zero** ocorrências.
- `000/google-services.json` — config CLIENTE do Firebase (tem `api_key`, tem
  `project_id nicky-e4f99`; **não** tem `private_key` nem `client_email`).
  É o arquivo que vai no APK — não serve para o envio no servidor.
- `000/Ferramenta IA local erotikk.pdf` — sem menção a firebase/service account.

BUSCA EXAUSTIVA pela credencial (read-only):
- `find` por `*adminsdk*`/`*firebase-service-account*`/`*nicky-e4f99*` em
  `/home /tmp /srv /opt /mnt /media` → nada.
- `grep -rl --include=*.json "BEGIN PRIVATE KEY" /home/alex` (excluindo
  .venv/.git/.config/.aider/caches) → **nenhum arquivo**: não existe service
  account em nenhum JSON da home.
- `000/` segue fora do git (regra `.gitignore` de 13/09) → nada de lá entra no
  repositório, inclusive o `google-services.json`.

Conclusão: o bloqueio do push FCM não tem atalho na 000/ — a chave só sai do
console: Configurações do projeto → **Contas de serviço** → "Gerar nova chave
privada" (baixa um JSON com `type: service_account`, `private_key`,
`client_email`, `project_id: nicky-e4f99`).

Rodada 6: "validar e instalar a service account que já chegou" — ELA NÃO CHEGOU

Verificação (read-only) antes de qualquer instalação:
- `config/` → só `iot_credentials*`; `config/firebase-service-account.json`
  continua inexistente.
- `/tmp/od_taildrop` → vazio.
- `find /home/alex /tmp -newermt "-70 minutes" -type f` → só o trabalho de
  hoje (código, checkpoint, `__pycache__`, `/tmp/pytest-of-alex`).
- `find` por `*adminsdk*`/`*firebase-service-account*`/`*nicky-e4f99*`/
  `*service-account*` em `/home/alex /tmp /root` → nada.
- Sinais REAIS de credencial em toda a home — `private_key_id`, base64
  `MIIE…`, `"type": "service_account"`, `client_email @*.iam.gserviceaccount.com`
  → **zero ocorrências**. Os "hits" de `private_key_id` no log do chat são
  texto meu (o comando de validação e a lista de campos que eu escrevi
  justamente para instruir) — nenhum material de chave existe na máquina.
- `/home/alex/OD` (o outro checkout, com `venv`): sem JSON de credencial e
  `.env` sem `OD_FCM*`/`OD_PUSH*`.

Hipótese principal: o arquivo ficou na **caixa de entrada do Taildrop**, que é
propriedade do root — `ls /var/lib/tailscale` → **Permission denied** e
`sudo -n` pede senha (não tenho). Se o envio pelo app do Tailscale concluiu, o
arquivo está lá esperando um `sudo tailscale file get <dir>`. A sessão SSH do
usuário está ativa (logins de 192.168.0.111 às 13:16:55 e 13:33:21), então o
comando é de um segundo.

Nada foi instalado nesta rodada: sem credencial não há o que validar —
reiniciar o od-core agora subiria igual (enabled=False, credencial_ausente).

Decisão do usuário: rodar `sudo tailscale set --operator=alex` e avisar.
Checagem às 13:41: o `--operator` ainda não estava aplicado
(`tailscale file get` continua em "Access denied: file access denied" e
`/tmp/od_taildrop` vazio). Próximo passo, na mesma ordem de sempre: fetch →
validar com google-auth → `chmod 600` em config/firebase-service-account.json
→ restart do od-core → `GET /push/devices`. Se o fetch voltar "moved 0/0
files" depois do operator, a inbox está vazia: o envio não concluiu e o
caminho passa a ser scp ou colar o JSON.

Desfecho do Taildrop (13:42-13:49):
- Usuário rodou o `--operator=alex` → **confirmado**: o fetch deixou de dar
  `Access denied`.
- `tailscale file get` → **`moved 0/0 files`**: a caixa de entrada está VAZIA,
  o arquivo nunca chegou. Receptor aberto com `--wait` por 4 min → nada.
- Busca nova por conteúdo (`service_account`/`BEGIN PRIVATE KEY`/
  `firebase-adminsdk`) em /home/alex e /tmp → nenhuma ocorrência; sem
  Downloads/Documentos/Desktop no servidor; nada novo fora do repo além dos
  arquivos do Home Assistant em /srv.
- Dado novo bom: **`redmi-note-14-1` voltou ao tailnet** (estado `idle`, não
  mais offline) → o teste de ponta a ponta voltou a ser possível.
- Próximos caminhos oferecidos: reenviar por Taildrop (agora eu busco sem
  sudo), scp direto para config/firebase-service-account.json, ou colar o JSON
  no chat (eu escrevo com chmod 600 sem exibir; rotacionar a chave depois).

Rodada 7: usuário reenviou (Taildrop) E abriu o app no celular

- Receptor com `--wait` aberto por 5 min → "waiting for file..." e nada:
  `/tmp/od_taildrop` vazio (`moved 0/0 files`). `journalctl -u tailscaled` do
  período só mostra ruído de magicsock/netcheck — **nenhum evento de
  transferência de arquivo chegou ao servidor**. `tailscale debug prefs`
  → `ShieldsUp: false` (não é bloqueio nosso).
- **MARCO: o app registrou o token!** `GET /push/devices` → `devices: 1`,
  `devices_detail[0] = {token: d8Xhaf…Vj_0, platform: android, sent: 0,
  failed: 0}` — o celular está online e alcançando a API. Push segue
  `enabled: false / credencial_ausente`: o registro funciona com o push
  desligado, exatamente como previsto.
- Caminhos de upload descartados depois de olhar o código: a API não tem rota
  de upload (só /message, /executa, /push/*, /transcribe, /tts); o Telegram
  bot só baixa **voice** (`message.voice.file_id`, sem documento); o control
  bridge só tem `POST /execute` (comando, com allowlist) — nenhum serve para
  subir um JSON.
- Alternativas que restam: scp direto, ou colar o JSON no chat (eu escrevo com
  `chmod 600` sem exibir; recomendado rotacionar a chave no console depois do
  teste).

Rodada 8: RESOLVIDO — push FCM de ponta a ponta funcionando (2026-09-14 14:07)

Solução: o usuário deixou o material na própria `000/` (pasta que eu já leio).
Arquivos novos: `000/nicky-e4f99-firebase-adminsdk-fh19o-ba704415d0.json`
(2.373 B, 14:01), `000/farebase.txt` (14:03) e `000/google-services .json`.

1. Conferência (sem imprimir segredo): `type=service_account`,
   `project_id=nicky-e4f99`, `client_email=firebase-adminsdk-fh19o@nicky-e4f99
   .iam.gserviceaccount.com`, `private_key` PEM íntegra (1.704 B).
2. Instalação: `cp` para `config/firebase-service-account.json` + `chmod 600`.
3. **Validação real com o próprio core**: `FcmSender(credentials_file=…)` →
   `available=True`, `reason=''`, `project_id=nicky-e4f99` e `_access_token()`
   devolveu um access token OAuth2 verdadeiro (1024 chars; valor não registrado
   aqui de propósito) — prova de
   que a chave é válida e tem permissão no FCM (nenhuma mensagem enviada).
4. `git check-ignore`: `config/firebase-service-account.json` →
   `.gitignore:134` e `000/*` → `.gitignore:139`; `git status` só mostra
   `iniciar/` — **nenhuma credencial entrou no repositório**.
5. Restart do `od-core` (14:06:53, PID 267461) →
   `Push FCM inicializado | enabled=True | motivo= |
   credencial=config/firebase-service-account.json | dispositivos=1`
   (em todos os restarts desde 13/09: `enabled=False | credencial_ausente`).
6. **TESTE DE PONTA A PONTA**: `POST /push/test` → **HTTP 200**
   `{ok:true, sent:1, failed:0, skipped:0, errors:[]}`; journal 14:07:20
   `Push enviado | enviados=1 | falhas=0 | titulo=OmegaDrakon`; e no
   `GET /push/devices` o aparelho foi para `sent=1, failed=0`.
   O token (`d8Xhaf…Vj_0`, android) foi registrado pelo próprio app às ~13:5x.
   Única parte que o servidor não atesta: a entrega no aparelho — isso é o
   usuário quem confirma.

Segurança a tratar (registrado, não executado):
- `000/farebase.txt` contém a **chave legada do servidor FCM**
  (fragmento omitido de propósito) e um par de chaves de push da Web. A API legada foi
  descontinuada em 2024 (não envia), mas é credencial exposta em arquivo de
  texto — recomendo excluir no console (Cloud Messaging → chave do servidor).
- A cópia da service account em `000/` pode ser apagada: a canônica é
  `config/firebase-service-account.json` (600).

Rodada 9 (autorizada): documentar a ativação e commitar

Os três documentos ainda descreviam o push como dormente. Ajustes:

- `docs/CHANGELOG.md` — nova subseção **"Ativado (2026-09-14) — push FCM em
  produção 🔔"** dentro da [1.2.0], com a cadeia de evidência (instalação +
  validação do OAuth2 + journal `enabled=True` + `POST /push/test` 200
  `sent=1/failed=0`) e a observação de que **nenhuma linha de código mudou**
  (o que faltava era a credencial). O item da seção **Pendente** foi riscado e
  aponta para a nova seção.
- `docs/README_VERSAO.md` — §2 ganhou nota de que `enabled=False`/`503` eram o
  estado NA ENTREGA; §3 teve o item da credencial riscado com "RESOLVIDO em
  2026-09-14" (e o item "publicação no GitHub" riscado, publicado no `3b5599c`);
  §4 virou "CONCLUÍDO em 2026-09-14"; e entrou a **§5 ATIVAÇÃO DO PUSH** com o
  bloco de evidência completa e a ressalva do que o servidor não atesta
  (entrega na tela do aparelho).
- `docs/FIREBASE_SETUP.md` — o cabeçalho passou a marcar "OD envia" como **ATIVO
  e validado (2026-09-14)**; o passo 6 ganhou a nota de que a credencial **já
  está instalada** (só refazer se rotacionar a chave) + aviso sobre a chave
  legada da aba Cloud Messaging; e o teste de ponta a ponta ganhou o resultado
  real.

Segurança: nenhum fragmento de segredo foi escrito nos documentos — a menção à
chave legada do FCM é descritiva, sem material de chave (o arquivo que a contém
está fora do git).

Verificação: suíte completa **1655 passed, 16 skipped** (nenhum código alterado,
confirmação de que só houve documentação).

Rodada 10 (autorizada): publicar

- **Commit `bf25a12`** — _docs: registra a ativação do push FCM em produção_
  (5 arquivos, +379/-10) → **`origin/master 19afdde..bf25a12`**.
- **Correção de rumo antes de publicar:** a varredura do staged pegou fragmentos
  de credencial nas MINHAS próprias notas (um pedaço da chave legada e o prefixo
  de um access token já expirado). O usuário autorizou **reescrever o commit
  ainda não publicado** em vez de deixar o fragmento no histórico:
  `f4518b9` → `858b072` → `bf25a12`, até `git grep -E "AAAAh7Tshcg|ya29\." HEAD`
  não retornar nada. O `f4518b9` nunca chegou ao origin (o push anterior estava
  em `19afdde`), então o histórico remoto ficou limpo.
- Lição registrada: as notas de sessão são arquivos versionados — fragmento de
  segredo citado em texto tem o mesmo peso de segredo em código.
