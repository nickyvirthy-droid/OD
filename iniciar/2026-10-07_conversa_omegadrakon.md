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

## 4. Estado e pendências

- **Bump 1.19.0 fechado no git; deploy pendente de autorização** — o
  restart sobe a 1.19.0 com **78 actions** (leitura provada; escrita
  degrada honesta).
- **Pendência do dono:** re-autorização do Google com os escopos de
  escrita (3 passos de 03/10: túnel `8766` + `/site/google_auth.html` +
  "codigo chegou"), para a troca código→token com os 7 escopos.

---
OD // CORE
