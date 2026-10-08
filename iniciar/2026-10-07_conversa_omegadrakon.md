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
