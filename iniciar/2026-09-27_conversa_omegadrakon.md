# Conversa OmegaDrakon — 2026-09-27

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia iniciar" (~12:00). Ambiente canônico de testes: `.venv/bin/python`
SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada e resgate do lote órfão v1.7.0 (~12:00)

Pedido: "leia iniciar".

### Diagnóstico

- od-core active PID 619998 (deploy de 2026-09-26 14:05, **v1.6.1**),
  NRestarts=0; HEAD `e4ad8df` == origin/master.
- Working tree com **19 arquivos** modificados/novos (mtimes 26/09
  14:19–15:17, DEPOIS do último commit da v1.6.1) — a sessão anterior
  morreu no meio do lote **v1.7.0**: código completo, bump feito,
  CHANGELOG/README_VERSAO escritos e APK 1.7.0+17 já publicado em
  site/ (aapt2 versionCode='17') — mas **sem commit, sem deploy e sem
  registro em iniciar/**. Prova do não-deploy: `/app/version` dava 404
  no ar.

### Conteúdo do lote (v1.7.0 — feature = MINOR pela regra 12)

- **GET /app/version** — contrato público da auto-atualização:
  `{version, version_code, apk, size, sha256}`; hash calculado em
  streaming (sem carregar ~50 MB na memória).
- **App: OdUpdater** (`app/lib/services/od_updater.dart`, NOVO) — checa
  versionCode (package_info_plus) contra o servidor, baixa o APK com
  progresso, confere SHA-256 ANTES de instalar e dispara a instalação
  via FileProvider (canal nativo `com.omegadrakon.nicky/updater`,
  MainActivity.kt + file_paths.xml + manifest). Integrado no boot do
  main.dart e em settings_screen.
- **Site mais rápido** — `OmegaDrakon-debug.apk` de 155 MB saiu de
  site/ (backups/apk-debug-20260926/); landing com ETag +
  `Cache-Control: max-age=60` e 304 por If-None-Match; APK continua
  no-store (download sempre completo).
- **Trava de infra para não-dono** (permissions/intents/orchestrator).
- Bump 1.7.0 (MINOR): .env, capabilities, pubspec 1.7.0+17, site (2×),
  CHANGELOG [1.7.0], README_VERSAO §1.7.0.

### Validação em sandbox (regra 13, passo 1)

- Suíte completa: **1966 passed, 16 skipped** (+34 sobre 1932).
- App: `flutter analyze` 0 issues; `flutter test` **87 passed,
  2 skipped**.

### Commit e publicação (regra 7.1)

`c2b4508` feat(app,api): auto-atualização do APK pelo próprio app +
site mais rápido (v1.7.0) — 19 arquivos +1025/−21; HEAD==origin/master.

## 2. Bug pego no deploy: /app/version dava 401 sob auth_all (12:0x)

### Causa raiz (regra 13, passo 3 — parar e corrigir)

- Em produção `OD_API_AUTH_ALL=1`: o gate cobre tudo que não é
  page_shell/AUTH_EXEMPT_PATHS → `/app/version` respondia **401**.
- O app chama a rota **SEM credencial** (best-effort no boot) e trata
  qualquer não-200 como "não há atualização" → a auto-atualização
  NUNCA funcionaria no ar, morrendo calada.
- Os testes herméticos novos não pegaram porque a fixture `serve` sobe
  **sem auth_all** — a lacuna era exatamente essa combinação.

### Correção

- `integrations/api/server.py`: `/app/version` entra em
  `AUTH_EXEMPT_PATHS` (mesma natureza do `/site`, já público sob
  auth_all por `test_site_public_under_auth_all`).
- `tests/test_api.py`: NOVO
  `TestAPIAppVersion::test_app_version_public_under_auth_all` — fixa
  200 sem chave E com chave sob `auth_all=True` (o bug reinjetado
  quebra este teste).
- Suíte pós-correção: **1967 passed, 16 skipped**.

### Deploy e prova viva (7/7)

Restart (autorização permanente de 09-23): **PID 721757, NRestarts=0**.

1. `GET /app/version` sem chave → 200 `{ok, version 1.7.0,
   version_code 17, apk, size 52937987, sha256 804db579…}`.
2. SHA-256 anunciado == `sha256sum site/OmegaDrakon.apk` (binário real).
3. aapt2: versionCode='17' versionName='1.7.0'.
4. `/health` com chave → 200 ok/up (9 checks).
5. WS :8001 → 426 (nosso WS no ar).
6. `/site` com If-None-Match → **304** (ETag no ar; 1º teste com HEAD
   não devolve ETag — repetido com GET).
7. Journal pós-deploy: 0 Traceback/ERROR/CRIT.

### Commits

- `c2b4508` feat(app,api): auto-atualização do APK pelo próprio app +
  site mais rápido (v1.7.0) — 19 arquivos +1025/−21.
- `43746fd` fix(api): /app/version público sob auth_all —
  auto-atualização morria com 401 — 2 arquivos +32/−3.

HEAD `43746fd` == origin/master; árvore limpa (regra 7.2).

---

## 3. "Pacote parece ser inválido" — downgrade de versionCode (12:3x)

Relato do dono: baixou o APK pelo site e o celular (1.6.1) recusou a
instalação. Provas antes de mexer:

- **NÃO** é assinatura: apksigner com cert idêntico ao do backup 1.2.8+11
  (SHA-256 252cf0fe…) — mesma debug key de TODA a linhagem.
- **NÃO** é corrupção: apksigner verify OK e o download veio do /site
  intocado (no-store, attachment).
- **CAUSA RAIZ**: o lote v1.7.0 passou a forçar o versionCode CRU do
  pubspec (`force-version-code-ignoring-abi`), e o APK nasceu com code
  **17**. O backup 1.2.8+11 PROVA o offset antigo (arm64 = 2011, +2000):
  o celular do dono está na linhagem arm64 (1.6.1 = **2016**) → 17 é
  DOWNGRADE → o instalador recusa com "pacote parece ser inválido".
- Confirmado pelo dono: download do site + linhagem arm64.

### Correção (commit 8475b6a)

1. **pubspec 1.7.0+2017** e `_APP_VERSION_CODE = 2017` no server — piso
   acima de qualquer linhagem antiga (2011–2016 e 11–16); bumps futuros
   seguem monotônicos (2018, 2019…).
2. **OdUpdateInfo.isNewer**: comparação DIRETA, sem normalização de
   offset — a fórmula que o lote trouxe (desconto de 1000) transformaria
   o 2017 cru em 1017 e ofereceria a MESMA atualização para sempre; e
   uma primeira tentativa de correção (desconto de 2000) foi pegada
   pelos PRÓPRIOS testes antes do deploy (2017 viraria 17).
3. **+9 testes** (app/test/od_updater_test.dart): linhagens 2011/2014/
   2016/16/11 recebem o 2017; 2017 instalado é estável; servidor 17
   nunca derrapa 2017; bump 2018 é oferecido; downgrade nunca.

### Validação, build e prova

- flutter analyze 0 issues; flutter test **96 passed, 2 skipped** (+9).
- Suíte servidor **1967 passed, 16 skipped**.
- APKs rebuildados e publicados em site/: aapt2 versionCode='2017'
  versionName='1.7.0' nos DOIS (full e arm64); apksigner verify OK;
  assinatura idêntica à linhagem; anterior preservado em
  backups/apk-v1.7.0+17-20260927/.
- Restart: **PID 727041, NRestarts=0**; /app/version → `{version_code:
  2017, sha256 88cf9876…}` e o hash anunciado == binário de site/;
  journal 0 erros.

### Commits

- `8475b6a` fix(app,api): versionCode 2017 — downgrade era recusado
  como 'pacote inválido' — 4 arquivos +97/−18.

HEAD `8475b6a` == origin/master; árvore limpa.

## Estado final

- **CONCLUÍDO E NO AR** — v1.7.0 implantada, provada e publicada.
- **Pendência do dono:** abrir o app 1.6.1+16 no celular — deve aparecer
  o banner de atualização → baixar (progresso) → SHA-256 conferido →
  Android pede confirmação da instalação do 1.7.0+17. A partir daí o
  app se atualiza sozinho nas próximas versões.
- **ATUALIZAÇÃO (12:3x):** a instalação do 1.7.0+17 foi RECUSADA pelo
  celular (downgrade de versionCode) — ver §3. APK corrigido: 1.7.0+2017
  no ar. O dono deve baixar de novo (pelo app 1.6.1+16, quando ele
  ganhar a checagem, ou pelo site) e instalar. NOTA: o app 1.6.1+16
  NÃO tem OdUpdater — a checagem automática só existe a partir do
  1.7.0; a primeira instalação do 2017 é manual pelo site.
