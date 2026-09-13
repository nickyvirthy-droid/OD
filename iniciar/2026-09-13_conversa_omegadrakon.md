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

Próximo passo: aguardando o usuário escolher o ponto de retomada.
