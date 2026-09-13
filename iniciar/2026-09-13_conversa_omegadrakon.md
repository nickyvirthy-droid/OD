2026-09-13 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu, nesta ordem: iniciar/README.md, iniciar/RULES.md,
  iniciar/session.json, iniciar/2026-09-12_conversa_omegadrakon.md.

Estado conferido no git (evidência, não memória):
- `git log --oneline` → HEAD é 8c58520 ("docs: registra o hash 68cf2e5 no
  checkpoint da sessão"); antes dele 68cf2e5, a5ac3a5, e2f4960, ffeab4f.
- `git status --short` → a entrega de push FCM segue NÃO commitada:
  novos: core/push.py, tests/test_push.py, docs/FIREBASE_SETUP.md
  modificados: .gitignore, app/lib/main.dart, app/lib/services/od_api.dart,
  app/lib/services/push_service.dart, app/pubspec.yaml,
  app/test/od_api_test.dart, core/capabilities.py, core/llm.py,
  core/orchestrator.py, docs/CAPACIDADES.md, docs/CHANGELOG.md,
  docs/README_VERSAO.md, docs/ROADMAP_V1.md, integrations/api/server.py,
  requirements.txt, runtime/install_postgres.sh, runtime/launcher.py,
  site/index.html, tests/test_api.py, iniciar/.

Retomada registrada:
- iniciar/session.json atualizado (updated_at 2026-09-13T14:20:31-03:00,
  last_turn = esta retomada, bloco anterior preservado em previous_turn,
  next.estado_em_2026-09-13 com o estado real do git).

Pontos abertos (do checkpoint anterior, ainda válidos):
1. Publicar a entrega de push FCM (commit + push) — aguarda autorização.
2. Gerar a service account do Firebase e rodar POST /push/test com o aparelho
   registrado (só o usuário pode gerar a credencial).
3. Instalar o APK 1.2.0+5 (1005) no Redmi Note 14.
4. Backlog de servidor que ficou fora do e2f4960.
5. Achados do journal: SelfRepair no_fix em agent.py e o handler
   face.presence com AttributeError.

Rodada 1 (autorizada): publicar a entrega de push FCM

Escolha do usuário: "Publicar o push FCM". Escopo aprovado por pergunta
explícita: **commit único com tudo que está em produção** (opção A).

Revisão do diff antes de commitar (21 modificados + 4 novos):
- Da entrega: core/push.py, tests/test_push.py, docs/FIREBASE_SETUP.md,
  .gitignore (regras de credencial Firebase), core/capabilities.py
  (push-fcm + integrations.push), requirements.txt (google-auth), app/lib/*,
  app/test/od_api_test.dart, app/pubspec.yaml (1.2.0+5).
- Colados nos mesmos arquivos (não separam por hunk): server.py e
  tests/test_api.py trazem também /actions, /executa e /site; launcher.py
  traz também max_tokens 512.
- Em produção junto: core/llm.py (512 tokens), core/orchestrator.py
  (data/hora DEPOIS do system prompt — cache de KV), install_postgres.sh,
  docs/CAPACIDADES.md, site/index.html (landing do APK arm64).
- Fora: 000/, assets/, sandbox_agent/, agent.py, agent.b64, executar.sh,
  gemini_prompt.sh, llama_prompt.sh, od_aider.sh, od_prompt.sh, txt.txt,
  GPT_preview.png (arquivos soltos de trabalho local, não são o sistema).

Verificação:
- `.venv/bin/python -m pytest tests/ -q` → 1647 passed, 16 skipped (15.13s)
- app: `flutter analyze` → No issues found! · `flutter test` → 42 passed
- segredos: varredura do staged por AIza/PRIVATE KEY/api_key sem ocorrências;
  `git check-ignore -v` confirma data/push_devices.json (.gitignore:101) e
  app/android/app/google-services.json (.gitignore:131) fora do repo.

Publicação:
- Commit **3b5599c** — "feat(push): implanta o push FCM de ponta a ponta
  (servidor + app)" (25 arquivos, +2456/-60).
- Push: `origin/master 8c58520..3b5599c`.
- O APK 1.2.0+5 já estava publicado em site/ — este commit não reconstruiu
  nem republicou binário.

Próximo passo: service account do Firebase + teste de ponta a ponta
(POST /push/test com o aparelho registrado) e a instalação do APK 1.2.0+5 no
Redmi Note 14; depois os dois achados do journal.
