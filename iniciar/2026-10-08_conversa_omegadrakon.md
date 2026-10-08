# Conversa OmegaDrakon — 2026-10-08

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar"** (~04:2x). Continuação da noite de 07/10 (transcrição
`2026-10-07_conversa_omegadrakon.md`).

## 1. Retomada — o bump 1.19.3 já tinha saído sozinho

- `git log`: **`a2cc2a1`** `chore(release): bump PATCH 1.19.3+2042 — hora
  antes do dia na agenda + criação encadeada sem LLM` (04:20:12),
  antecedido por `f2fba6b` (fix da agenda) — HEAD == origin/master, árvore
  limpa. O checkpoint anterior dizia "bump seria 1.19.3" — **o bump já
  estava commitado depois do último registro** (corrigido nesta retomada).
- od-core ativo desde **01:14:21 (PID 745013, NRestarts=0)** → serviço
  rodando **1.19.2**; o 1.19.3 estava commitado e publicado no site
  (APKs rebuildados 04:15:16) mas **sem deploy** (regra 13).
- **Incoerência no ar até o deploy:** o processo 1.19.2 anunciava
  `/app/version {1.19.2, 2041}` com o `sha256` calculado do arquivo
  **novo** (`9cf3e58c…` = APK 2042) — ou seja, code 2041 com hash 2042.

## 2. txt.txt do dono (04:11) — app com 401 em tudo

Relato: atualização da versão nova funciona **sem tailscale**, mas chat
vazio, Ações → `401`, Painel → `auth/me falhou 401`, Status → offline.
Dono testou tudo pela URL do Funnel e está ok → acha que é o APP.

Evidência apurada no servidor:

- Auth **não** está quebrada: o próprio dono se autenticou no `/admin`
  às 04:11 para gravar o txt.txt.
- Sessões **válidas** de alex no Postgres (4; a mais nova criada
  07/10 22:40, expira 14/10) — não é expiração global.
- `/app/version` é **AUTH_EXEMPT** (desde o 1.7.0) — explica exatamente
  o sintoma: atualização (isenta) funciona, toda rota autenticada dá 401
  → o celular **chega** ao servidor, mas a credencial enviada é
  rejeitada (ou não é enviada).
- **Sem rastro server-side:** od-core não loga 401 (journal e
  `logs/audit.jsonl` desde 03:50 só têm o txt.txt e snapshots de
  percepção).

Hipóteses (pendentes do dono — item 2): **A)** token antigo/expirado no
app → re-login nas Configurações (alex/senha123), o teste mais barato;
**B)** bug do app pós-update em `od_api.dart` (header Authorization);
**C)** outro host devolvendo 401.

## 3. Deploy 1.19.3+2042 (dono respondeu "1" — autorizado)

- `systemctl --user restart od-core` → **04:27:28, PID 768455,
  NRestarts=0, SubState=running**.
- **Prova viva 5/5:**
  1. `/app/version` = **1.19.3 / 2042 / sha256 `9cf3e58c…` == site/OmegaDrakon.apk**
     (incoerência fechada; arm64 `1851e34f…`);
  2. `/capabilities` **1.19.3** · **78 actions** (system 17, google 13,
     filesystem 15, iot 5, git 10…);
  3. `/health` **up**, todos os checks ok; `/supervision` up,
     **restarts 0**, degraded [];
  4. WS `:8001` → **426** (nosso WebSocket no ar);
  5. journal desde o restart: **0** ERROR/CRIT/Traceback.
- **Prova da correção da agenda (a razão do bump):**
  - `o que tem pra hoje` → `route=action_intent`,
    `fastpath:google_calendar_events` (772 ms) → `📅 Próximos 3
    compromisso(s)` — leitura real (aparecem os eventos-dia-inteiro
    ruins criados pelo dono na noite de ontem: `evento para as 5 horas
    de`, `compromisso para as 4:00 de`);
  - `criar compromisso prova deploy 1.19.3 para as 4:00 de hoje` →
    `fastpath:google_calendar_create` → **`em 2026-10-08 04:00`** com
    título limpo (`prova deploy 1.19.3`) — **ANTES** sairia
    `em 2026-10-08` (dia inteiro) com título `…para as 4:00 de`.
    A confirmação **não foi respondida** → nenhum evento criado (TTL 2 min).
- Nota: as provas usaram `user_id=deploy-check`, que a OD_API_KEY assume
  como **alex** → 2 turnos (4 msgs) gravados no histórico do dono.

## 4. Estado e pendências

- **v1.19.3+2042 NO AR** — deploy, provas e registro fechados;
  commit+push do registro conforme regra 7.1.
- **Pendência 1 (dono):** os 401 do app — começar pelo **re-login** nas
  Configurações; se persistir, investigar `od_api.dart`.
- **Pendência 2:** o app do dono ainda está em 1.19.2+2041 (o update
  para 2042 agora já é oferecido pelo `/app/version`).
- **Pendência 3:** C6 da auditoria (instrução "quando pergunto isso
  olhe minha agenda" não persiste) — feature nova, escopo a decidir.

## 5. Item 2 fechado — 401 do app resolvido (04:35)

- Dono: **"atualizei e reloguei. funcionou tanto no wifi quanto no 4g"**.
- **Rastro no journal:** `Login realizado | username=alex | user_id=1`
  (04:35:34) · sessão nova **`a48e2056…` criada 04:36:40, expira
  15/10 04:36** · banco: 5 sessões válidas de alex, 280 msgs intactas.
- **Causa raiz confirmada = hipótese A:** o app segurava um token de
  sessão inválido/expirado (o `/app/version`, isento de auth, funcionava
  por isso a atualização passava); re-login restaurou a credencial.
  WiFi e 4G provados → host/URL não eram o problema (também descarta a
  hipótese C).
- **Ponto FECHADO** — nenhum bug novo no app; nada a corrigir em
  `od_api.dart`.

## 6. Agenda — "quase funcionou, ainda não grava no horário"

- Dono: **"quanto a agenda quase funcionou. ainda não grava no horário"**
  + sobre o C6: **"isso é a continuação de uma conversa. pode excluir"**
  (C6 descartado — não vira feature de memória de instruções).
- **Reprodução com a conversa REAL dele** (histórico IDs 747-752):
  `criar compromisso para as 6 horas` → o `_GOOGLE_W_QUANDO_RE` exigia
  `hoje|amanhã` → não casou → a hora foi para o **TÍTULO** (`'para as
  6 horas'`) → create devolveu `quando_obrigatorio` → ele respondeu
  `hoje` → `parse_when('hoje')` = date-only → confirmação **sem hora**
  → `sim` → **evento DIA INTEIRO** (leitura de 04:41: `para as 6 horas
  → 2026-10-08 (dia inteiro)`).
- **Correções (3 arquivos):**
  1. `_GOOGLE_W_QUANDO_RE`: ramo novo — hora **sem** dia (`para as 6
     horas`, `às 12 horas`, `14:30`) com exigência de preposição `às`
     (ou HH:MM); número solto (`daqui 2 horas`, `10.000`) **não** é
     quando;
  2. `_google_quando_e_titulo`: se todo o resto era o quando, o
     **substantivo** vira título padrão (`'compromisso'`) — nunca vazio;
  3. `parse_when`: hora sem dia → **hoje**, e **amanhã** se a hora já
     passou; dia explícito nunca rola; sem hora continua dia inteiro;
     a própria dica `'às 15h'` agora completa a pendência.
- **Validação:** +5 testes (`TestHoraAntesDoDia::test_*sem_dia*`) ·
  suíte completa **2330 passed, 16 skipped** · cobertura **90,07%**
  (gate 90) · **5/5 mutações detectadas** e restauradas bit-exato.
- **Pendência:** commit + deploy com bump **1.19.4** (regras 12/13 —
  aguardando autorização do dono). Depois: limpar os 3 eventos-dia-
  inteiro de teste que ficaram na Agenda dele (apagar é mutação — pedir).

## 7. Lote autorizado pelo dono — `crei`, bump 1.19.4, deploy e limpeza

- Dono (ask_user, **"est autorizado"**): (1) remover `crei` da regex de
  criação; (2) deploy + bump **1.19.4**; (3) **apagar os 3 eventos dia
  inteiro de teste** da Agenda dele.
- **1. `crei` fora:** `_GOOGLE_W_CRIAR_RE` perdeu o `crei` — era erro de
  digitação do dono, o verbo é `crie` (já coberto). Frase com a palavra
  errada agora cai na **LEITURA** (`google_calendar_events`), nunca cria.
  Teste renomeado/estendido: `test_mostre_vira_leitura_e_crie_vira_escrita`.
- **2. bump PATCH 1.19.4+2043** (checklist §5): `.env` · capabilities ·
  pubspec · `_APP_VERSION_CODE=2043` · site 2x · CHANGELOG [1.19.4] ·
  README_VERSAO §1.19.4. APKs rebuildados — aapt2 `versionCode='2043'
  versionName='1.19.4'` nos dois (full 53.972.629 B `8603d453…`,
  arm64 19.245.103 B `5e6dd78d…`; 1.19.3+2042 preservado em
  `backups/apk-v1.19.3+2042-20261008/`).
- **3. Defeito novo pego pela PRÓPRIA prova viva:** minha frase de
  teste tinha `1.19.4` e o ramo 'só a hora' casou `HH.MM` → agendou
  **01:19**. Correção: só preposição (`às`/`para as …`) ou `HH:MM` com
  **dois-pontos** — versão (`1.19.4`) e data `dd.mm` (`08.10`) nunca
  viram horário (intents + `parse_when`), +1 teste de regressão e
  +2 mutações (**9/9** no total).
- **Validação final:** suíte **2331 passed, 16 skipped** · cobertura
  **90,07%** (gate 90) · guardas de versão **9/9**.
- **Commits:** `df0217c` (bump 1.19.4 + `crei`) e `4039108` (ponto não
  é hora) — ambos push em origin/master.
- **Deploy:** restart `od-core` (autorizado) — 1º 05:10:42, 2º após o
  fix do ponto; NRestarts=0, journal 0 erros.
- **Prova viva (chat):** (A) `criar compromisso nota 1.19.4 para as 6
  horas` → confirmação `'nota 1.19.4' em 2026-10-08 06:00` (hora no
  dia, versão preservada no título); (B) `crei um evento …` →
  **leitura** da agenda; (C) `crie um evento … para as 7 horas` →
  escrita `2026-10-08 07:00`. Confirmações NÃO respondidas (TTL 2 min):
  nenhum evento criado pelas provas.
- **4. Limpeza autorizada:** os 3 eventos dia inteiro de teste
  (`evento para as 5 horas de` · `compromisso para as 4:00 de` ·
  `para as 6 horas`, todos 08/10) apagados por título exato via
  CalendarService (ids `59f56r90…`, `6591321g…`, `nsid5esq8…`):
  antes 3 → **depois 0**, resíduo 0; leitura pelo chat confirma
  `Nenhum compromisso nos próximos 7 dia(s)`.

## 8. Dono: "mais alguns erros de escrita ou de entendimento" (05:4x)

- Ele testou o 1.19.4 na marra (IDs 759–786, 05:23–05:28) e os registros
  acusaram **3 erros de entendimento + 1 de consistência**:
  1. `crie um evento para as 7:00` / `marque um evento para as 7:30` →
     intenção **NENHUMA** (faltava o substantivo **'evento'**) → LLM (25 s);
  2. **falso sucesso**: a gemma ecoou uma confirmação VELHA da minha
     prova de 05:20 (`'teste deploy' 07:00`) sem gravar pendência e, no
     `'sim'` dele, respondeu *"Compromisso criado com sucesso"* — **agenda
     vazia** (o evento real foi só o que saiu pelo caminho certo);
  3. `'sete horas'` por extenso não casava (só dígitos);
  4. `'s'` (typo dele) executava com pendência e, sem, caía no LLM que
     dizia `'Estado verificado.'`.
- **Autorização (ask_user):** corrigir os 3 grupos + deploy, e apagar o
  evento de teste `'compromisso' 06:00`.
- **Correções:**
  1. `eventos?` nos substantivos de escrita (`_GOOGLE_W_CAL_RE`) e
     leitura (`_GOOGLE_CAL_RE`);
  2. `_NUM_POR_EXTENSO` (`um`…`vinte e três`) nos ramos do
     `_GOOGLE_W_QUANDO_RE` + `_extenso_em_digito` no `parse_when`
     (`'daqui duas horas'` continua fora);
  3. **`'sim'/'s'` sem pendência** → `fastpath:confirmacao_sem_pendencia`
     honesto nos DOIS transportes;
  4. **etapa 6.7 anti-falso-sucesso**: `fake_action_reason` troca
     resposta do LLM que imita ação (`'Confirmar:'`, `'… com sucesso'`,
     `'marquei o compromisso'`) por `FAKE_ACTION_MESSAGE` antes do
     histórico e do cache.
- **Saneamento:** 5 respostas falsas podadas do cache (snapshot
  `backups/llm-cache-fakes-20261008-055830.json`) · evento de teste
  apagado (antes 1 → depois 0).
- **Validação:** suíte **2339 passed, 16 skipped** · cobertura **90,15%**
  · guardas 9/9 · **10 mutações detectadas** (sintaxe válida) e
  restauração bit-exato; 4 testes do contrato antigo (`'sim' → LLM`)
  atualizados para o novo contrato honesto.
- **Bump + deploy:** **1.19.5+2044** (§4: bump no deploy; PATCH — só
  fixes) — checklist §5 completo, APKs aapt2 `versionCode='2044'
  versionName='1.19.5'` (2043 preservado em `backups/apk-v1.19.4+2043-20261008/`),
  commit `5110a25`, restart com NRestarts=0 e journal 0 erros.
- **Prova viva (chat, tudo fastpath/zero LLM):**
  `sim` (sem pendência) → honesto · `crie um evento para as sete horas`
  → confirmação `'evento' em 07:00` · `marque um evento para as 7:30` →
  `07:30` · agenda final: **Nenhum compromisso nos próximos 7 dias**
  (nenhuma confirmação respondida — TTL 2 min).

## 9. Nova regra 15 — resumo de conclusão também no Telegram (06:1x)

- Dono: **"Nova regra. ao concluir mandar esse resumo no telegram também."**
- Regra **15** criada em `iniciar/RULES.md`: toda conclusão de etapa (lote,
  deploy, entrega) envia o MESMO resumo ao chat do dono no Telegram
  (`sendMessage` com o bot do `.env`, chat `OD_TELEGRAM_ADMINS` = 660518870),
  além do chat e do registro em `iniciar/` — o envio passa a fazer parte do
  Definition of Done.
- Aplicada de imediato: resumo do lote 1.19.5 enviado no Telegram
  (`message_id 2012`, `ok: true`).

## 10. Tarde — canal de desenvolvimento on-demand (1.20.0 → 1.20.2)

Registro detalhado em `iniciar/session.json`
(`desenho_canal_dev_2026_10_08` → `ui_canal_abaixo_ideias_app_paridade_2026_10_08`):

- **1.20.0+2045** (MINOR): `orquestrador.py --sessao --cli auto|…` lê a ideia
  no **txt.txt**, monta prompt com `iniciar/` + `docs/` + `txt.txt`, roda a
  CLI em cascata (Freebuff → OpenCode → Kilo), valida com a suíte e
  **commita sem push**; caixa de autorização (`data/dev_caixa.json`,
  marcador `[AUTORIZACAO]`, timeout 30 min) na seção **Canal de
  desenvolvimento** do `/admin` (▶ Ativar / ⏹ Parar); 5 rotas novas
  (`/admin/dev/sessao|caixa`), ROUTES 50→55; `od-orchestrator` saiu do
  always-on (`disable --now`, decisão do dono).
- **1.20.1+2046**: fonte da ideia passou a ser só o **txt.txt**; a fila
  `pedido.txt` e suas rotas foram excluídas de ponta a ponta (ROUTES
  55→52; `deploy/od-orchestrator.service` removido do repo).
- **1.20.2+2047**: no `/admin` o **Canal de desenvolvimento ficou logo
  abaixo de Ideias (txt.txt)** e o **app ganhou paridade** (sessão, CLI,
  caixa e cards na mesma ordem; `od_api.dart` sem a fila morta).
- Validações de cada bump: suíte canônica ~2367 passed/16 skipped,
  cobertura 90,1x% (gate 90), guardas de versão 9/9, `node --check` no
  JS do painel, mutações detectadas e restauradas bit-exato; APKs
  `versionCode='2047' versionName='1.20.2'` publicados e conferidos pelo
  `/app/version` (sha256 `9cc29412…`).

## 11. Retomada — "leia iniciar" (18:4x)

- od-core **active desde 17:22:36 (PID 861929, NRestarts=0)**,
  journal 0 erros, `/health` ok, `/supervision` restarts 0,
  `/app/version` 1.20.2/2047 == site, `/capabilities` 1.20.2,
  WS :8001 → 426; `od-llm` active, `od-orchestrator` inactive/disabled.
- git: **`935e33c` == origin/master**, árvore só com o snapshot untracked
  `backups/llm-cache-fakes-20261008-055830.json` (precedente).
- txt.txt inalterado desde 08:35 (pedido já tratado); caixa do
  desenvolvimento sem pendência (0).
- Pendência do dono: instalar o **1.20.2+2047** no app (o `/app/version`
  já oferece). Nada pendente no código.
