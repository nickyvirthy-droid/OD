# Conversa OmegaDrakon — 2026-10-07

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar"**. Ambiente canônico: `.venv/bin/python` SEM
`OD_TEST_POSTGRES_DSN`.

## 1. Retomada — bump 1.19.0 encontrado pela metade

- Herdado da sessão de 03/10: código da escrita Google + site já
  commitados (`df20177`, `ced23cc`), porém:
  - **4 arquivos do bump sem commit** (pubspec, capabilities, server.py,
    CHANGELOG);
  - **od-core no ar ainda em 1.18.0** (PID 206597, desde 03/10 12:48 —
    `/app/version` {1.18.0, 2038, sha `d9dd74a3…`});
  - **`docs/README_VERSAO.md` sem a seção §1.19.0** (lacuna do checklist).
- APKs em `site/` já eram 1.19.0+2039 (aapt2 conferido) e `.env`
  `OD_VERSION=1.19.0`.

## 2. Achado: registro desonesto do escopo do token

- O CHANGELOG afirmava *"token com os 7 escopos"* — **falso**:
  - o **log do capturador** (`data/google_oauth_helper.log`, 03/10 13:38)
    prova que o callback veio com os **7 escopos**
    (gmail.send/gmail.modify/drive/calendar.events + os 3 readonly);
  - mas a **troca código→token não foi concluída**:
    `data/google_token.json` (mtime 06/10 05:08) carrega só os
    **3 readonly**; refresh OK (access expirou 06/10 e renova);
  - journal de 13:44 registra **syntax error em `drive.py`** na mesma
    rodada (SelfRepair `no_fix`) — a sessão de 03/10 morreu no meio da
    integração da escrita.
- **Correção do registro** (honestidade antes de tudo): CHANGELOG e
  README_VERSAO agora dizem a verdade — código veio com 7 escopos, token
  NÃO trocado, escrita degrada `ok=False` até a re-autorização.

## 3. Trabalho executado

1. `docs/README_VERSAO.md` — seção **§1.19.0** criada no formato da casa.
2. `docs/CHANGELOG.md` + README_VERSAO — parágrafo do escopo reescrito.
3. Guardas: `tests/test_version_policy.py` **9/9**.
4. Suíte completa: **2297 passed, 16 skipped** (77,9 s) — igual à
   evidência registrada.
5. Commit **`a7c3e1d`** + push (`origin/master`) — árvore limpa.

## 4. Deploy (autorizado via ask_user — "Reiniciar agora")

- `systemctl --user restart od-core` 13:21:22 → **PID 669019**, NRestarts=0.
- **Prova viva:** `/app/version` {1.19.0, 2039, sha256 `d9dd74a3…` ==
  `site/OmegaDrakon.apk`} · `/health` up (9 checks) · `/supervision`
  restarts 0 · journal **0** Traceback/ERROR/CRIT.
- **78 actions registradas** (journal "Action registered", únicas):
  **13 google** — 6 leitura + **7 escrita** (calendar_create/delete,
  drive_create/update/delete, gmail_send/delete).
- Escrita segue dormente na prática: token com 3 readonly → as 7
  actions de escrita degradam `ok=False` honestamente.

## 5. Estado e pendências

- **v1.19.0+2039 NO AR** (PID 669019) — bump, registro e deploy fechados.
- **Pendência do dono:** re-autorização do Google com os escopos de
  escrita (3 passos de 03/10: túnel `8766` + `/site/google_auth.html` +
  "codigo chegou"), para a troca código→token com os 7 escopos.

---
OD // CORE

## 6. Escrita no Google NO AR — re-autorização + 2 bugs da prova viva + v1.19.1

- **Autorização:** dono 'quero fazer agora' → capturador (8766, setsid -f)
  → túnel + clique → 'codigo chegou' → callback com os **7 escopos** →
  token trocado (refresh sim; backup do readonly em backups/, não
  commitado). Achar: capturador salva o callback na RAIZ
  (`google_auth_url.txt`), não em `data/` — lido do log do helper.
- **Bugs pegos pela 1ª prova viva (antes de tocar a agenda real):**
  1. 'com o título X' não virava título → marcador explícito vence
     (`_GOOGLE_W_TITULO_RE`, título depois do marcador, 'quando' antes);
  2. confirmação com UTC cru ('18:00' p/ 'às 15h') → `_quando_legivel()`
     converte ao fuso local na confirmação E no sucesso; dia inteiro
     intacto (regressão do 1º patch pega na mesma rodada).
- **v1.19.1 (PATCH):** 6 fontes de versão + APKs (aapt2 2040/1.19.1) +
  CHANGELOG/README §1.19.1. Suíte **2299 passed, 16 skipped** (+2
  regressões); guardas 9/9.
- **Prova viva FINAL (agenda real):** criar 2 compromissos (15h/16h, fuso
  certo, confirmação 2 passos) → leitura mostrou os 2 → apagar os 2 →
  'Nenhum compromisso nos próximos 7 dia(s)'. Journal 0 erros.
- **Estado: SISTEMA 100%** — escrita no Google viva de ponta a ponta.

---

OD // CORE

## 7. Retomada 23:12 — "leia iniciar" · verificação em VERDE

- **Git:** HEAD `b367701` == `origin/master`, árvore limpa.
- **Serviço:** od-core ativo desde 14:19:52, PID 677660, **NRestarts=0**.
- **Prova viva:** `/app/version` {1.19.1, 2040, sha256 `4c6a9723…` ==
  `site/OmegaDrakon.apk`} · `/health` up (orchestrator/llm ok) ·
  `/supervision` restarts 0, `degraded: []`.
- **Journal** desde o restart: 191 linhas, **0** Traceback/ERROR/CRIT
  (2× `[NICKY][WARN] Transporte indisponível` — WARN, auto-recuperado).
- **Canal do dono:** `txt.txt` e `pedido.txt` vazios (sem recado).
- **Estado:** nada pendente de deploy nem do dono — aguardando pedido.

## 8. Análise das conversas DO SISTEMA — inconsistências encontradas (23:xx)

Pedido: "leia as conversas do chat e encontre inconsistências" (as
conversas do sistema, não as transcrições de `iniciar/`).

**Amostra:** `conversation_messages` = **230 mensagens / 115 turnos**,
29/09 14:00 → 07/10 15:06, users `alex`+`teste`, 7 perfis
(guardian, regulus, luma, vox, athenae, nyx, nexus) + `llm_cache`
(71 entradas). Análise anterior registrada em
`session.json:analise_coerencia_2026_09_30` cobria 15 turnos (até
30/09 07:53) — os achados D1/D2/D3 dela **seguem valendo**; o que vem
abaixo é o que ela NÃO alcançou (30/09 21:14 em diante) + metadados.

### 8.1 Contradições diretas no mesmo assunto

| # | Turnos | Contradição |
|---|--------|-------------|
| C1 | [494] 30/09 "OpenAI GPT-4" · [498] 30/09 "gemma" · [592]/[594] 01/10 "Qwen / qwen2.5-coder-3b" | 4 identidades para a mesma pergunta, todas gravadas com `llm_used=gemma-local`. D2 do 30/09 é só 2 das 4. |
| C2 | [490] "agenda não está disponível" → [492] **inventa 3 tarefas** → [500] "não tenho capacidade de gerenciar agendas" → [666] 06/10 consulta real da Agenda → **[694] 07/10 "🚫 Não é possível criar novas agendamentos"** | A recusa vem **45 min depois** de [672]/[674] criarem 2 compromissos reais no mesmo dia. E a recusa está **no `llm_cache`** (`use_count=1`) — será reentregue sem chamar o LLM. Causa raiz da recusa: `core/intents.py:_GOOGLE_W_CRIAR_RE` não tem "marque/agende/coloque" → a intenção não casa e o turno cai no cache/LLM. |
| C3 | [622] 02/10 12:38 "Sim, eu tenho acesso ao seu Google Drive" vs [632] 12:40 "não tenho acesso direto ao Google Drive" | 2 minutos de distância, respostas opostas — e as duas eram falsas: o commit da integração é `20b724d` 17:25 do mesmo dia. |
| C4 | [484] 29/09 "R$ 4,73" (sem fonte) · [516]/[518]/[520] 30/09 "US$ 5.20 **por real**" · [524] 30/09 20:40 AwesomeAPI "R$ 5,184" | 3 valores incompatíveis em 2 dias e a formulação 5.20 **inverte** dólar↔real. (O 4,73 é o D3 já registrado.) |
| C5 | [672] confirma "…em 2026-10-08 **15:00**" → [674] sucesso "criado … em 2026-10-08 **18:00**" → [680] leitura "08/10 **15:00**" | A mensagem de SUCESSO contradiz a própria confirmação e a leitura real (bug de fuso do lote 07/10; [678] 16:00 já saiu certo). |
| C6 | [665] 06/10 dono: "quando pergunto isso você deve olhar minha agenda" → [666] cumpre → [692] 07/10 "O que tem pra hoje" responde pelo LLM | A instrução do dono não persistiu; e a resposta usa prefixo "🌐 Atualizado:" de fastpath com `llm_used=gemma-local`. |

### 8.2 Resposta imitando ferramenta (critério 5 do protocolo §14 — que em 30/09 foi registrado como "ZERO")

| Turno | Conteúdo | Evidência contrária |
|-------|----------|---------------------|
| [618] 02/10 | "Fase da Lua … **Fonte: Open-Meteo — leitura real de agora**", `llm_used=gemma-local` | Não existe action de fase da Lua: `grep -ri 'moon\|phase\|fase da lua' tools/ core/ integrations/` = **0**. Formato de fastpath + fonte inventada; **está no `llm_cache`**. |
| [660] 05/10 | "10 Mbps. Estado verificado.", `gemma-local` | Nenhuma action de velocidade (`grep -ri 'speedtest\|mbps\|velocidade da internet'` = **0** no código). |
| [664] 06/10 | "temperatura da CPU … **na porta 5000** do serviço web" | Nada escuta na 5000 (`ss -lntp`: 8000/8001/8081/8123/5432) e `grep '5000'` no código = **0**. |

### 8.3 Conteúdo fabricado / pergunta não respondida

- **Xintoísmo:** [570] pergunta "quem fundou o xintoísmo" → respondeu
  sobre o **cristianismo**; [572] fabrica o fundador "Chūkyō / Ippon
  Kyo, 1869" e fecha com "hoje o **cristianismo** é praticado por
  quase todos os japoneses".
- **Lua (01/10 14:13, 4 perfis):** [576] "Lua é uma enorme pedra",
  "maior que a Marta", "satélite Luna Menina", "300°C de dia";
  [578] "rocha volátil e argila"; [580] "segundo maior **planeta**"
  + caractere chinês "**卫星**" numa resposta em pt-BR; [582] "58% da
  massa terrestre … revolução de 12 dias". Nenhuma bate com a outra.
- **[616] 02/10** "vai chover em Teodoro Sampaio" → devolveu o clima
  ATUAL (sem previsão).
- **[658] 05/10** "O estado verificado." — frase incompleta.
- **[539] 30/09 21:14** "bom dia" → "Bom dia!" (7 perfis iguais).

### 8.4 Metadados que mentem (auditoria não confiável)

1. **`llm_cache.profile` 100% errado:** 71/71 linhas gravadas como
   `guardian`, inclusive prompts de outros perfis — ex.:
   `qual a velocidade da internet` foi perguntado pelo **nexus**
   (05/10 16:16, msg [659]) e está gravado `profile='guardian'`.
   Causa: `runtime/launcher.py:161` cria o cache com
   `profile=OD_PROFILE` e `memory/cache.py:set()` grava
   `profile=self._profile`, ignorando o `profile=` que o orquestrador
   passa (`core/orchestrator.py:1642`). A **chave está certa**
   (`make_key` recebe o param: 7 chaves distintas para "bom dia", uma
   por perfil) — quem erra é a coluna.
2. **Execução real de luz gravada como `fastpath:math`** — [508]/[512]
   30/09 ("sim" → ✅ executado). `core/orchestrator.py:767` inicializa
   `route_detail = "math"` e o ramo de confirmação de luz (≈823-831)
   executa **sem** reatribuir; o caminho síncrono (1188) e o do Google
   (843) atribuem `ha_device_control`/`gw_action`. Os dois caminhos do
   mesmo arquivo discordam entre si.
3. **Contador ≠ lista:** [644]/[650] "📁 **20** arquivo(s)" com **15**
   itens listados — `core/intents.py:1310` usa `len(files)` no título
   e corta em `files[:15]` sem avisar. Mesmo padrão do Gmail (`[:10]`).
4. **Mesma action, respostas diferentes em 11 min:** [640] 03/10 11:30
   "10 mensagem(ns)" — 10× "(sem assunto)" vs [646] 11:41 com
   assunto e remetente.

### 8.5 Cache herdado da pré-zerada

- A zerada de 29/09 (§14 do dia 29) apagou só o histórico
  ("`llm_cache` INTACTOS" ficou registrado como decisão). Consequência:
  em **30/09 21:14** os 7 perfis devolveram a saudação gravada em
  **27/09 12:49** (7 chaves, uma por perfil, todas rotuladas guardian).
  O que parecia "personalidade" naquele turno era replay de 3 dias
  antes.
- Observação para não virar falso-positivo: `conversation_messages`
  começa no id 465 (ids 1-464 inexistentes) — **é** a zerada, não bug.

### 8.6 Inconsistência com o registro da sessão (CI)

- **CI vermelho não registrado:** [646] 03/10 11:41 e [652] 03/10
  16:41 mostram no chat "Run failed: CI - master (**ced23cc**)".
  API do GitHub confirma: run `37147058947` = **failure**, passo
  "Suíte completa + gate de cobertura ≥ 90%". A transcrição de 03/10
  fecha em "CI VERDE `433458e`" (12:49) e nunca mais cita CI — o verde
  foi quebrado 3h depois e ninguém registrou.
- **"100%" apressado:** a sessão de 07/10 declara "SISTEMA 100% /
  nenhuma pendência" às 14:2x, e o próprio chat registra [694] (devaneio
  de agenda, cacheado) às 15:06.

**Estado:** análise publicada — 6 contradições diretas, 3 imitações de
ferramenta com dado inventado, 4 problemas de metadado, 1 cache
herdado, 1 divergência de CI. Nenhum deploy envolvido (só registro).

## 9. Correções da auditoria executadas (08/10 00:1x — pedido do dono)

Pedido: **"faça as correções necessárias"** (chat; o relatório com a
pergunta "o que corrigir" tinha ido para o `txt.txt`).

### 9.1 Código (commit nesta sessão)

- `core/intents.py`
  - `_GOOGLE_W_CRIAR_RE` passou a casar **marcar/marque/marcamos,
    agendar/agende/agendando, colocar/coloque/coloco, incluir/inclua,
    anotar/anote, registrar/registre/registra** — antes
    'Marque na agenda um compromisso' caía em NENHUMA intenção e
    'coloque na minha agenda um compromisso' caía na **leitura**
    de eventos (`google_calendar_events`).
  - `_GOOGLE_W_CAL_RE`: `reuni[õo]es?` **não casa 'reunião'** (singular)
    — 'agende uma reunião' nem chegava à Agenda. Agora
    `reuni(?:[ãa]o|[õã]es|oes)`.
  - Pergunta diária sem dizer 'agenda' (`_GOOGLE_O_QUE_TEM_RE`):
    'o que tem pra hoje' / 'tenho algo hoje' / 'o que vou fazer amanhã'
    → `google_calendar_events` (days 1/2), com guarda para
    'no sistema'/'no drive' continuarem fora. Era a frase que gerou o
    devaneio 'você não tem tarefas' ([660]/[664]).
  - `_GOOGLE_W_ARTIGO_RE`: artigo/preposição sai também no **fim da
    frase** e o conector 'com o/a' entrou ('agende a reunião com o pedro'
    virava título `'com o pedro'`; `'registre a reunião de amanhã'` →
    `'de'`). `\s+`/`$` obrigatório para não cortar `'atas'` → `'tas'`
    (pego pelo teste existente `test_extrai_parametros`).
  - Drive/Gmail: título contava tudo, lista cortava (20 → 15) →
    '… e mais N não listado(s)'.
- `core/orchestrator.py` — ramo do **stream** da confirmação de luz não
  reatribuía `route_detail` (default do `safe_math`): execução real
  gravada como `fastpath:math`. Agora `fastpath:ha_device_control`
  (igual ao caminho síncrono, que já atribuía certo).
- `memory/cache.py` — `set()` gravava `self._profile` (fixo: guardian)
  na coluna `profile` em vez do `profile=` do orquestrador.

### 9.2 Banco (`runtime/llm_cache_saneamento.py`, novo)

- **21 linhas** com `profile` errado reatribuídas **pela chave**
  (make_key reproduz o par instância × `profile=`): 0 chaves não
  reconhecidas, 0 ambíguas → agora 54/54 corretas.
- **17 respostas devaneio podadas** (prova viva de 06-07/10): CPU
  31,7 °C na porta 5000, 10 Mbps, fase da lua com 'Fonte: Open-Meteo',
  4 curiosidades da Lua inventadas, xintoísmo → cristianismo, recusas de
  Agenda ('como está minha agenda' ×2, 'Marque na agenda…'),
  'LLM gemma', 'sou o dono adm', 'tenho acesso ao seu Drive', '/' como
  raiz do Drive, 'crie uma sckill…' que não criou nada.
- Snapshots de rollback em `backups/llm-cache-perfil-20261008-0040*.bak`
  e `backups/llm-cache-poda-20261008-004020.bak` (poda com TODAS as
  colunas, `INSERT` executável); gitignorado por `backups/*.bak`.
  Dry-run é o default da CLI; a segunda rodada não acha nada (idempotente).

### 9.3 Registro

- `docs/CHANGELOG.md`: seção nova **[1.19.2] — CORREÇÕES DA AUDITORIA
  DAS CONVERSAS**, marcada **SANDBOX — SEM DEPLOY** (servidor segue em
  1.19.1; bump só no deploy, regra 13); e nota **retroativa do CI
  vermelho** em `[1.19.0]` (run 37147058947 do `ced23cc`, 03/10 19:12
  UTC, step 'Suíte completa + gate de cobertura ≥ 90%' exit 1; verde só
  em `a7c3e1d`).

### 9.4 Evidência

- Suíte **2315 passed, 16 skipped** (+16 testes sobre as 2299 da
  1.19.1) · guardas de versão 9/9 · **gate de cobertura 90,11%** (meta
  90, `pytest --cov --cov-config=.coveragerc --cov-fail-under=90`).
- **3 mutações detectadas** e restauradas bit-exato: `route_detail` sem
  reatribuir → `test_ws_tambem_injeta_user_id_e_executa` vermelho;
  verbos fora da regex → 2 testes de `TestGoogleIntents` vermelhos;
  coluna `profile` de volta ao fixo → `TestCacheDB` +
  `TestProfileGravado` vermelhos.

### 9.5 Pendências (não feitas — fora do pedido ou exigem decisão)

1. **Deploy + bump 1.19.2** — checklist do `VERSIONAMENTO.md` §5
   (`.env`, capabilities, pubspec, `_APP_VERSION_CODE`, site, README de
   versão) + restart do serviço: **exige autorização do dono**.
2. **C6 — instrução do dono não persiste** ('quando pergunto isso você
   deve olhar minha agenda'): viraria memória de instruções; é feature,
   precisa de escopo + bump MINOR.
3. **Teste intermitente:** `tests/test_mqtt.py::TestBridgeLifecycle::
   test_start_stop_thread` falhou 1x em 3 aqui e 1x em 3 no worktree
   limpo (HEAD) — flake de timing no `stop()`/thread, **não** regressão
   destas correções, mas pode deixar o CI vermelho sem motivo.

**Estado:** correções em sandbox, commitadas e publicadas; nada de
deploy/restart feito.

## 10. Deploy 1.19.2+2041 — itens "1 e 3" do dono e o esclarecimento do "2" (08/10 00:5x→01:2x)

Pedido do dono: **"1 e 3"** + explicação do 2: *"a instrução era a
continuação de uma conversa onde percebi que não acessou a agenda, então
pedi para acessar"* — ou seja, **mensagem pontual, não regra global**.
Não vira feature de memória de instruções; o defeito era o ROTEAMENTO,
que já está corrigido.

### 10.1 O que aquela conversa de 06/10 mostrou (revisada na fonte)

- [663] `o que tem pra hoje` → [664] devaneio de CPU (`fastpath` nenhum,
  `llm=gemma-local`, resposta com '31,7 °C na porta 5000').
- [665] `quando pergunto isso você deve olhar minha agenda` → [666]
  **já saiu** `fastpath:google_calendar_events` (leu de verdade). Ou
  seja: a "instrução" dele funcionou no turno seguinte; o problema era o
  turno ANTERIOR, que não reconhecia a pergunta diária.
- Correções que fecham esse caso: pergunta diária sem dizer 'agenda' e
  verbos de ACESSO (`olhe/acessa/consulte minha agenda`) → leitura.

### 10.2 Item 3 — flake do MQTT corrigido na causa (não no teste)

- Causa: `stop()` podia acontecer entre a checagem de `_closed` do loop
  e o `connect()` — o socket abria **depois** da desconexão e ficava
  vivo. Era a corrida que fazia `test_start_stop_thread` falhar **1 em
  3** (também no worktree limpo do HEAD).
- Correção em `integrations/mqtt/bridge.py`: `connect()` recusa ponte
  encerrada; `run()` desconecta no `finally`; `start()` reabre
  (`_closed = False`). 2 testes determinísticos.
- **2 mutações detectadas** e restauradas (`finally` sem desconectar →
  `test_stop_no_meio_do_connect…` vermelho; `connect()` sem a guarda →
  `test_ponte_encerrada_nao_reconecta…` vermelho). A 3ª mutação que
  testei (tirar o `break` pós-falha de connect) **não** foi detectada e
  foi **removida do código** — ramos sem cobertura não entram.
- Suíte de MQTT: **6/6 rodadas verdes** (antes: 1 vermelho em 3).

### 10.3 Item 1 — bump PATCH 1.19.2+2041 (checklist VERSIONAMENTO §5)

| Passo | Estado |
|---|---|
| `.env` `OD_VERSION=1.19.2` | ✓ |
| `core/capabilities.py` fallback `1.19.2` | ✓ |
| `app/pubspec.yaml` `1.19.2+2041` | ✓ |
| `_APP_VERSION_CODE = 2041` | ✓ |
| `site/index.html` 2x (badge + card) | ✓ |
| `docs/CHANGELOG.md` `[1.19.2]` (sai do status sandbox) | ✓ |
| `docs/README_VERSAO.md` §2.1 da 1.19.2 | ✓ |
| Suíte verde + prova viva | ✓ (abaixo) |

- APKs rebuildados por `app/build_apk.sh` e conferidos com **aapt2**:
  `versionCode='2041' versionName='1.19.2'` nos dois
  (`OmegaDrakon.apk` 53.972.629 B · `arm64` 19.245.103 B).
- **Lição de ambiente:** o build quebra sem `JAVA_HOME` — o JDK é
  `/home/alex/jdk` (Temurin 17) e não está no PATH; o comando que
  funcionou: `JAVA_HOME=/home/alex/jdk PATH=$JAVA_HOME/bin:/home/alex/flutter/bin:$PATH ./build_apk.sh`.

### 10.4 Deploy (autorizado: "1 e 3")

- `systemctl --user restart od-core` às **01:14:21**, PID **745013**;
  serviço `active`.
- `GET /health` → **200**, todos os checks `up`.
- `GET /app/version` → `{"version": "1.19.2", "version_code": 2041,
  "size": 53972629, "sha256": "646b3823…"}` — **sha256 igual** ao do
  arquivo publicado (contrato da auto-atualização íntegro).
- journal desde o restart: **0 erros/tracebacks**; MQTT conectado
  (`client_id=od-core`) com o código novo.

### 10.5 Prova viva da versão

`POST /message` **"o que tem pra hoje"** →
`route=action_intent` · `llm_used=fastpath:google_calendar_events` ·
"📅 Nenhum compromisso nos próximos 1 dia(s) na sua Agenda." (o Google
renovou o `access_token`; action executou em 770 ms). É **exatamente** a
frase que, em 06/10 05:08, devolveu a CPU inventada na porta 5000.

### 10.6 CI

- Runs verdes: `3ec53b7` (saneamento) e `e8ff0e9` (bump).
- `d1fb797` (fix MQTT) **não teve run próprio**: ele só entrou como pai
  do push do bump — a CI roda no HEAD do push (`e8ff0e9`), que contém a
  árvore completa. Fato registrado para o histórico não parecer que o
  commit ficou sem CI.

**Estado:** 1.19.2+2041 no ar, serviço reiniciado, C4/C3/C1/C5 e C2
fechados por código/estado, C6 fechada como pedido pontual (sem feature).
Pendência: nenhuma de código — só observar a CI.

---

OD // CORE

## 11. Correção do "dia inteiro" + encadeamento do 'quando' (08/10 02:4x→03:5x)

Pedido: dono testou a agenda no chat (IDs 709–734) e pediu **"corrija"** —
"mesmo dizendo as horas ele marca para o dia todo"; esclareceu: escrever
NO site funciona, o defeito é o **sistema gravar NO site**.

### 11.1 Achados (banco `conversation_messages`, IDs 709–734)

- "marque na agenda um compromisso para as 4:00 de hoje" → confirmação
  `'compromisso para as 4:00 de' em 2026-10-08` **sem "às"** → leitura
  `2026-10-08 (dia inteiro)` (IDs 723–728 e 729–734, idem "5 horas").
- Causa raiz em 3 passos: `_GOOGLE_W_QUANDO_RE` só via hora DEPOIS de
  hoje/amanhã → a hora ficava no TÍTULO e `quando="hoje"` → `parse_when`
  devolvia date-only → `create_event` enviaba `{"date": …}` = dia inteiro.
- Colaterais: 'Testar Agenda' NUNCA foi criado (ID 700 route=gemma-local
  alucinou o sucesso — 'hoje' após o hint não voltava ao fastpath);
  "me mostre os compromissos" fora de `_GOOGLE_ASK_RE` → LLM ecoava a
  alucinação; "crei" fora de `_GOOGLE_W_CRIAR_RE` → caía em leitura.

### 11.2 Correções (sandbox → validado)

- `core/intents.py`: `_GOOGLE_W_QUANDO_RE` captura hora ANTES do dia
  ("para as 4:00 de hoje"/"…5 horas de hoje") e limpa o fragmento do
  título; fallback de título quando todo o resto era o quando ("crei um
  evento na agenda …" → "evento"); `_GOOGLE_ASK_RE` + `mostre|montre|
  mostra[r]`; `_GOOGLE_W_CRIAR_RE` + `crei`.
- `integrations/google/calendar.py`: `parse_when` aceita "5 horas" sem
  "às" (dia inteiro só quando o dono NÃO deu hora).
- `tools/actions/actions.py`: `_CALENDAR_WHEN` — o hint 'não entendi
  quando' guarda o título (TTL 300 s) e `peek_pending_calendar_when`
  devolve params quando a frase É um quando.
- `core/orchestrator.py` (stream + síncrono): frase sem intenção +
  pendência de quando → executa `google_calendar_create` no fastpath
  com `user_id` (0 idas ao LLM).

### 11.3 Evidência

- Testes novos: 7 (6 em `TestHoraAntesDoDia` + encadeamento no
  orquestrador). Suíte **2325 passed, 16 skipped**, gate de cobertura
  **90,06%** (meta 90), exit 0.
- **6 mutações detectadas** e restauradas bit-exato (regex de quando;
  store da pendência; user_id do ramo encadeado; `mostre`; `crei`;
  fallback de hora sem "às").
- Contrato provado: o POST ao Google agora leva `dateTime` com a hora
  falada (04:00), nunca `{"date": …}`.

**Estado:** correções commitadas (regra 7.1); deploy pendente de
autorização (regra 13) — bump PATCH seria 1.19.3 no checklist do
VERSIONAMENTO.
