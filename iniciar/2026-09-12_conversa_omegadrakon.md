2026-09-12 — sessão de auditoria de alinhamento de versão do OmegaDrakon.

Contexto de entrada:
- Usuário pediu "leia iniciar".
- Agente leu iniciar/README.md, iniciar/RULES.md, iniciar/session.json,
  iniciar/2026-09-11_conversa_omegadrakon.md e docs/REGRAS_DE_TRABALHO.md
  antes de avançar (regra 3 — nenhuma sessão começa do zero).
- session.json atualizado com o last_turn (regra 4 — salvamento obrigatório).

Trabalho escolhido pelo usuário:
- Opção (1) do session.json: validar o alinhamento de versão
  (pubspec/app vs site vs OD_VERSION).

Auditoria — fontes e valores reais (evidência por grep/stat):
- site/index.html            → v1.2.0 (linhas 350, 472, 487)
- app/pubspec.yaml           → 1.0.0+1
- APK release (build)        → versionName 1.0.0 (versionCode 1001/2001/4001)
- core/capabilities.py       → fallback 0.28.0; lia só os.environ
- .env                       → SEM OD_VERSION (só TELEGRAM/OD_*/API keys)
- docs/ROADMAP_V1.md         → declara v1.2.0 em execução
- docs/README_VERSAO.md      → última seção [0.28.4]; nenhuma seção v1.x
- docs/CHANGELOG.md          → não existia

Divergências encontradas:
1. OD_VERSION não definido → servidor reportava 0.28.0 enquanto o sistema era
   v1.2.0 (API, capabilities, bot).
2. Site anunciava v1.2.0, mas o APK entregue é 1.0.0 (pubspec nunca subiu).
3. README_VERSAO.md parou na 0.28.4 — fases v1 sem relatório §2.1 (viola
   REGRAS_DE_TRABALHO §2.1.1).
4. CHANGELOG.md ausente — item 4 da Definition of Done sem arquivo-alvo.

Correções aprovadas pelo usuário (as três opções) e aplicadas:
- core/capabilities.py: fallback 0.28.0 → 1.2.0 e resolução
  os.environ → OD_VERSION do `.env` → fallback. Motivo: o launcher tem o
  próprio carregador de .env, mas nem todo entrypoint passa por ele (ex:
  uvicorn direto), então a versão do `.env` não chegava ao manifesto.
- app/pubspec.yaml: 1.0.0+1 → 1.2.0+3 (rebuild do APK ainda necessário).
- docs/README_VERSAO.md: seções v1.0.0 / v1.1.0 / v1.2.0 reconstruídas
  retroativamente + seção [1.2.0] AUDITORIA DE VERSÃO (2026-09-12).
- docs/CHANGELOG.md: criado (v1.2.0, v1.1.0, v1.0.0 + fechamento da série 0.x).

Segunda rodada (autorizada pelo usuário na mesma sessão):
- OD_VERSION=1.2.0 gravado no `.env`:
  `grep -q '^OD_VERSION=' .env || printf 'OD_VERSION=1.2.0\n' >> .env`
  → `grep -c '^OD_VERSION=' .env` = 1; resolução passa a vir do `.env`.
- APK rebuildado na nicky-server (Flutter 3.47.2 em /home/alex/flutter, JDK em
  /home/alex/jdk — nenhum dos dois no PATH, foi preciso exportar):
  `flutter pub get` + `flutter build apk --release` +
  `flutter build apk --release --split-per-abi`
  → app-release.apk 51.9MB · arm64 18.5MB · armeabi-v7a 16.0MB · x86_64 20.0MB
  → versionName 1.2.0, versionCode 1003/2003/4003 (antes 1.0.0 / 1001-2001-4001)
- Publicação em site/ com backup antes: APKs antigos preservados em
  `backups/apk-v1.0.0/`; sha256 origem==site conferido
  (3b800c87...d978ff full · f3535e75...2f2fc6 arm64).

Terceira rodada (autorizada pelo usuário): commit + push (§2.1.2)
- Decisão sobre os binários: ficam FORA do repo — `.gitignore` ganhou
  `site/*.apk`, `backups/apk-*/` e `.od_repair_backups/` (164 .bak do
  self-repair). O APK oficial é republicado em `site/` pelo
  `app/build_apk.sh`, não precisa ser versionado.
- Staged: .gitignore, app/pubspec.yaml, core/capabilities.py,
  docs/CHANGELOG.md, docs/README_VERSAO.md, iniciar/RULES.md,
  iniciar/session.json, iniciar/2026-09-11_*.md, iniciar/2026-09-12_*.md.
- Commit **ffeab4f** — "fix(version): alinha OD_VERSION, pubspec e docs na
  v1.2.0" (9 arquivos, +600/-146).
- Push: `origin/master 3768bcb..ffeab4f` (incluiu o commit local 87ee078
  "fix: remove arquivo deletado", que já estava à frente do remoto).
- Ficou de fora (backlog pré-existente, não relacionado): app/lib/,
  app/android/, app/README.md, core/llm.py, core/orchestrator.py,
  integrations/api/server.py, tests/test_api.py, docs/CAPACIDADES.md,
  docs/ROADMAP_V1.md, site/index.html, requirements.txt,
  runtime/launcher.py, runtime/install_postgres.sh.

Ainda não foi feito:
- Validar o APK no celular via Tailscale e ativar o FCM (pendências da v1.2.0).
- Tratar o backlog pré-existente listado acima.

Evidência da validação:
- .venv/bin/python -m pytest tests/ -q → 1610 passed, 16 skipped (15.01s antes
  do .env; 15.72s depois)
- import de integrations.api.server → SERVER_VERSION = "OmegaDrakon/1.2.0"
- OD_VERSION sem env var → 1.2.0; com OD_VERSION=9.9.9 → 9.9.9
- .venv/bin/python -m pytest tests/test_capabilities.py tests/test_api.py -q
  → 80 passed in 4.58s
- app: flutter analyze → No issues found! · flutter test → 36 passed

Próximos passos possíveis:
- Validar o APK no celular via Tailscale.
- Ativar Firebase FCM (docs/FIREBASE_SETUP.md).
- Retomar a Fase 4 (Execução) ou a v1.3.0 (WebSocket /ws/chat, plugins, voz).
