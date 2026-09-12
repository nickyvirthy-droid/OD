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

Quarta rodada: validação do contrato do APK 1.2.0 via Tailscale

Método: exercitei os endpoints exatos que o app usa contra
http://100.77.67.53:8000 (mesmo caminho do celular), com a chave do `.env`, e
reproduzi a tela Status com o payload REAL do `/capabilities` num teste de
widget temporário (apagado depois).

PASSOU:
- GET /health autenticado → ok=true, status=up; 401 sem chave
- GET /capabilities → 200 (manifesto: 40 capacidades, 57 actions)
- GET /actions → 57 ações com name/description/category/permission/params/risk
- POST /message com o payload do app (text/user_id=app/profile=auto) → ok=true,
  campo `message` preenchido. Levou 109s (LLM local gemma).
- POST /executa system_info → status=ok com data
- POST /executa filesystem_mkdir sem confirm → HTTP 422 confirmacao_obrigatoria
- POST /executa filesystem_mkdir com confirm em path do projeto → status=ok
- POST /executa action inexistente → HTTP 404

FALHOU:
1. BUG NO APP — a aba Status quebra com o payload real:
   `_TypeError: type 'String' is not a subtype of type 'Map<String, dynamic>?'`
   em `status_screen.dart:136` (`_capabilities?['system'] as Map<...>?`).
   O servidor devolve `"system": "Omega Drakon"` (string) e a versão no
   topo do manifesto; o app espera um `system` aninhado. O teste existente
   passa porque o mock de `widget_test.dart:68` usa um `system` aninhado
   (`{"version": "v0.28.0", ...}`) que o servidor real não tem.
2. SERVIDOR DESATUALIZADO — o od-core em execução ainda reporta
   `version: 0.28.0` (uptime ~29k s, subiu antes da correção). Precisa de
   `systemctl --user restart od-core` para servir 1.2.0.
3. GET /info → 404 (não é rota; a raiz é GET / e exige chave). Não afeta o
   app (que não usa /info), mas contradiz o registro §0.27.3.

OBSERVAÇÕES:
- Chat: 109s — dentro do timeout de 240s do app, mas apertado.
- `filesystem_mkdir` com path fora de /home/alex/OmegaDrakon → denied
  (Security Layer; esperado, mas o app mostra o erro).
- Redmi Note 14 (`redmi-note-14-1`, 100.80.224.73) está ONLINE no tailnet,
  mas não tenho acesso ao aparelho: instalar e operar o APK é ação do usuário.

Quinta rodada (autorizada): corrigir a tela Status + reiniciar o od-core

1. od-core reiniciado (`systemctl --user restart od-core`):
   - GET / autenticado → version 1.2.0 (antes 0.28.0, uptime 8h14)
   - /capabilities → version 1.2.0
   - /health → ok=true, 8 checks OK (orchestrator, llm, audit, metrics,
     database, homeassistant, mqtt, perception)
   - /actions → 57
2. Correção do app:
   - `app/lib/screens/status_screen.dart`: `_buildSystemInfo` passou a ler o
     manifesto plano com `is` + fallback '?', sem cast. Mostra Versão,
     'N modos' (runtime.modes), Capacidades e Actions (counts).
     A linha "Agentes: N perfis" saiu: o manifesto não expõe contagem de
     agentes (o endpoint /profiles existe, mas a tela não o chama).
   - `app/test/widget_test.dart`: mock de /capabilities alinhado à forma real
     (o antigo usava `system` aninhado — teste mentindo verde) e novo teste de
     regressão que usa o manifesto real do servidor.
   - `app/test/fixtures/capabilities_manifest.json` (16 KB): manifesto
     capturado do servidor de produção (v1.2.0; 40 capacidades, 57 actions,
     8 modos).
3. Evidência:
   - `flutter analyze` → No issues found!
   - `flutter test` → 37 passed (36 + 1 regressão)
   - TESTE DO TESTE: reintroduzindo a linha antiga, 2 testes falharam com o
     mesmo `_TypeError: type 'String' is not a subtype of type
     'Map<String, dynamic>'` → a regressão é realmente pega.
   - suíte do servidor: 1610 passed, 16 skipped

Sexta rodada (autorizada): rebuild e republicação do APK

- `app/pubspec.yaml`: 1.2.0+3 → **1.2.0+4**. Motivo: com o mesmo
  `versionCode` (1003) o Android recusaria instalar por cima do APK anterior.
- Build: `flutter build apk --release` + `--split-per-abi`
  → app-release.apk 51.9MB · arm64 18.5MB · armeabi-v7a 16.0MB · x86_64 20.0MB
  → "versionName": "1.2.0" / versionCode 1004·2004·4004
- Publicado em `site/OmegaDrakon.apk` e `site/OmegaDrakon-arm64.apk`,
  sha256 origem==site (`6d3c73a5...b616ade` full); o build anterior (1.2.0+3,
  com o bug) foi preservado em `backups/apk-v1.2.0-1003/`.
- Confirmação extra: `GET /site/OmegaDrakon.apk` na API → HTTP 200,
  51935299 bytes (igual ao arquivo local) — o download da landing entrega o
  build novo. `strings` no APK encontra a string nova ('modos') 3x.

Sétima rodada (autorizada): commit + push do fix (e do backlog do app)

DECISÃO sobre o backlog de `app/lib` e `app/test`: entraram no commit.
Motivos: (1) o APK publicado foi buildado exatamente desse código, então
manter fora do repo recria a divergência repo↔artefato que a auditoria de
versão acabou de corrigir; (2) `status_screen.dart` não dá para separar do
fix sem descartar as mudanças pré-existentes do arquivo, que só existiam no
working tree; (3) a fixture/teste de regressão não fazem sentido sem a fonte.

- Commit **e2f4960** — "feat(app): publica o código do app v1.2.0 e corrige a
  aba Status" (41 arquivos, +2375/-98): app/lib, app/test (+fixture do
  manifesto real), app/android, push_service.dart, build_apk.sh, run_tests.sh,
  pubspec 1.2.0+4, docs/CHANGELOG, docs/README_VERSAO, iniciar/.
- Push: `origin/master f42e5c5..e2f4960`.
- Segredos conferidos: `app/android/app/google-services.json` segue ignorado
  (nada de credencial entrou no commit).

Ficou de fora (backlog de servidor, não relacionado ao app): core/llm.py,
core/orchestrator.py, integrations/api/server.py, tests/test_api.py,
docs/CAPACIDADES.md, docs/ROADMAP_V1.md, site/index.html, requirements.txt,
runtime/launcher.py, runtime/install_postgres.sh.

Oitava rodada: registro do teste no celular — CONCLUÍDO COM SUCESSO

Relato do usuário: **tudo funcionou** (Chat, Ações e Status sem erro).

COMPROVADO PELO SERVIDOR (journal do od-core, pid 20419, pós-restart):
- CHAT — 11:25:58: "Message processed | route=cache | user=app |
  profile=guardian | llm=- | latency_ms=32.325" → o app sempre manda
  user_id='app' e o request é posterior ao restart (11:14:52): mensagem do app
  respondida pelo cache em 32 ms.
- AÇÕES — 11:27:58: "Security decision | action=cpu_info | allowed=True |
  session_id=api:app" + "Action executed | action=cpu_info | role=admin |
  duration_ms=5.608" → uma action FOI executada pelo app, com o Security
  Layer aprovando.
- Nenhum "[NICKY][WARN] API erro" depois do restart → nenhum 4xx do app.

CORREÇÃO DE UM ERRO MEU: eu havia registrado "nenhuma action executada via
app", inferindo isso de zero entradas `api:app` em logs/audit.jsonl. Estava
ERRADO — a trilha de auditoria só guarda perception.snapshot (2267 linhas) e
system.startup (643); execuções de action não vão para lá, vão para o journal.
O controle foi o meu próprio teste pré-restart, que aparece no journal como
"Action executed | action=system_info" e "Action executed |
filesystem_mkdir". Lição: ausência de evidência numa fonte não é evidência
quando a fonte não cobre o evento.

NÃO COMPROVADO (só o relato do usuário atesta):
- se o APK 1.2.0+4 foi baixado/instalado (a API não loga acesso a /site)
- a tela Status: /health e /capabilities são GET e não são registrados

ACHADOS INCIDENTAIS NO JOURNAL (não relacionados ao app):
- SelfRepair no_fix a cada ~5 min: file=agent.py | failure=invalid syntax —
  o auto-reparo tenta consertar agent.py e não acha estratégia.
- face.presence: handler _run_vision_forever.on_change falhou 3x com
  AttributeError → evento para dead letter (bug real em visão/presença).

Comandos de consulta: `journalctl --user -u od-core --since "2026-09-12
11:14:00" | grep -v 'Action registered'` e `grep -a api:app
logs/audit.jsonl`.

Nona rodada: fechar a pendência na documentação e publicar a sessão

A pendência "validar o APK no celular" foi riscada/atualizada em:
- `docs/CHANGELOG.md` — nova seção "Validado no aparelho (2026-09-12)" com a
  evidência do journal (11:25:58 chat, 11:27:58 cpu_info) e a nota de que a
  tela Status e o download do APK não deixam rastro no servidor.
- `docs/README_VERSAO.md` — §[1.2.0] da entrega original e §[1.2.0]
  AUDITORIA: item riscado nos dois; o backlog do app passa a constar como
  publicado no `e2f4960` (antes listado como pendente).
- `docs/ROADMAP_V1.md` — cabeçalho e §3 atualizados: APK `1.2.0+4`, 37 testes,
  validação no Redmi Note 14; resta só o push FCM. (O arquivo carrega também
  as mudanças pré-existentes de progresso v1.x — foram commitadas junto, por
  serem coerentes com a mesma entrega.)

Ainda não foi feito:
- Ativar o FCM.
- Tratar o backlog de servidor e os dois achados do journal
  (SelfRepair no_fix em agent.py e o handler face.presence).

Evidência da validação:
- .venv/bin/python -m pytest tests/ -q → 1610 passed, 16 skipped (15.01s antes
  do .env; 15.72s depois)
- import de integrations.api.server → SERVER_VERSION = "OmegaDrakon/1.2.0"
- OD_VERSION sem env var → 1.2.0; com OD_VERSION=9.9.9 → 9.9.9
- .venv/bin/python -m pytest tests/test_capabilities.py tests/test_api.py -q
  → 80 passed in 4.58s
- app: flutter analyze → No issues found! · flutter test → 36 passed

Próximos passos possíveis:
- Instalar/validar o APK 1.2.0+4 (1004) no Redmi Note 14 via Tailscale.
- Tratar o backlog de servidor que ficou fora do commit e2f4960.
- Ativar Firebase FCM (docs/FIREBASE_SETUP.md).
- Retomar a Fase 4 (Execução) ou a v1.3.0 (WebSocket /ws/chat, plugins, voz).
