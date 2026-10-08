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
