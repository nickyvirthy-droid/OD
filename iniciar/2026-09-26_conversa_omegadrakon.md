# Conversa OmegaDrakon — 2026-09-26

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia iniciar" (01:48). Ambiente canônico de testes: `.venv/bin/python`
SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada (01:48)

Checkpoint lido. Estado confirmado: od-core active (PID 481232),
NRestarts=0, HEAD `f522abe` == origin/master.

## 2. Confirmação do dono (01:5x)

"site esta funcionando normal agora, atualizou sem f5" — o ponto da
rodada 2 de 09-25 (f522abe) está FECHADO com confirmação visual.

## 3. Painéis: dashboard do usuário + backend do admin (02:0x–03:4x)

Pedido: "vamos criar um dashboard para os user e um backend para o
admin". Escopo fechado com o dono (perguntas objetivas):

- **User**: completo — stats + histórico + conta (trocar senha, API key).
- **Admin**: completo — usuários + ações (reset/remoção) + métricas.
- **Formato**: estender `/dashboard` (que era shell morto) e criar `/admin`.

### Implementação

**Backend** (`integrations/api/`):

- `auth.py` — `UserStore.change_password(id, current, new)` (PBKDF2,
  exige a senha atual), `delete_user(id)` (mata sessões + vínculo do
  Telegram; NÃO apaga histórico), `count_sessions(id)` (sessões válidas).
- `server.py` — 6 rotas novas (33 → 39):
  - `POST /account/password` — troca a própria senha; encerra TODAS as
    sessões da conta;
  - `POST /account/api-key` — rotaciona a própria API key;
  - `GET /admin/users` — contas + uso real (history.stats) + baldes
    legados; campo `owner` por conta;
  - `POST /admin/users/{username}/password` — reset (sem senha atual);
    mata sessões;
  - `DELETE /admin/users/{username}` — remove conta; dono é alvo
    proibido (403 `dono_nao_removivel`); 404 `usuario_inexistente`.
  - Gate `_require_admin()` — `_role() != "admin"` → 403 + log.
- Páginas embutidas `_DASHBOARD_PAGE_HTML` (painel do usuário: stats,
  últimas 20 msgs, limpar histórico, trocar senha, rotacionar key) e
  `_ADMIN_PAGE_HTML` (tabela de contas com ações, baldes legados,
  cards de saúde + /supervision e /dashboard/stats em <details>).
  O menu 👤 do /chat ganhou atalho "📊 Meu painel".

### Verificação (regra 12)

- **Contrato** (`tests/test_api.py`): tabela de rotas 33 → 39
  (TestAPIRoutes) e `/dashboard`/`/admin` no
  `test_dashboard_and_chat_html` (páginas novas sem dados no shell).
- **Cobertura nova** (`tests/test_auth.py`): `TestAccountEndpoints` (5)
  + `TestAdminEndpoints` (9): troca de senha exige a atual / senha curta
  400 / sessões morrem / rotação invalida a key antiga; lista de contas
  com uso, 403 para usuário comum, reset mata sessões, dono intocável,
  remoção preserva o balde, 404, OD_API_KEY opera o painel, 503 sem
  UserStore.
- **Suíte: 1913 passed, 16 skipped** (+14). 1 falha isolada do mqtt
  (flaky de timing conhecido) — passa isolado e no arquivo.
- **Teste do teste — 4 mutações, TODAS detectadas e revertidas**:
  1. papel `user` vira admin em `_role()` → 403 some → 1 falha;
  2. troca de senha aceita senha atual errada → 1 falha;
  3. dono removível (`if False and _is_owner...`) → 1 falha;
  4. reset sem fechar sessões → 1 falha.

### Lição: guarda node --check pegou bug NOVO no ar (2ª vez)

A prova viva de deploy (`node --check` no HTML SERVIDO) acusou erro de
sintaxe no JS do /admin: `onclick="resetPass(\'' + u.username + '\'')"`
tinha barra invertida LITERAL no arquivo Python — o `node --check`
pré-deploy (fechado no texto do `_pages_tmp.py`) passou porque a
fusão/edição dobrou a barra depois. Correção: onclick inline trocado por
`data-*` + addEventListener (sem escape frágil) e CONTRATO ENDURECIDO:
`test_painel_pages_js_compiles` passa a exigir JS válido em /dashboard e
/admin — as duas páginas agora têm a mesma guarda do /chat (2026-09-23).

### Deploy e prova viva (7/7)

- Restart (autorização permanente de 09-23): **PID 535581, NRestarts=0**.
- `node --check` OK no HTML servido das duas páginas.
- Shells: /dashboard, /admin, /chat → 200; /health com chave → 200.
- Dados: /admin/users sem credencial → 401; /account/password sem
  credencial → 401; Bearer do `teste` (role user) em /admin/users → 403.
- /admin/users com OD_API_KEY → lista correta (alex owner=true, 11
  sessões, 110 msgs; teste owner=false; baldes deploy-check*).
- Reset real: conta de prova `prova-dash` criada → reset pelo admin →
  login com a senha NOVA 200 → conta removida 200.
- /admin/users/jonas → 404; reset em alex → 403 dono_nao_removivel.
- Journal: 0 Traceback/ERROR/CRIT.

## 4. Confirmação do dono nos painéis (~04:00)

"Confirmei os painéis visualmente, fechamos esse ponto." — /dashboard e
/admin validados pelo dono. Ponto FECHADO; suíte 1913/16; PID 535581.

## 5. Regra da versão — SemVer aplicado (04:1x–04:5x)

Pedido: "vamos colocar a regra da versão, voce parou na 1.2.8 quando na
verdade já fez implementações e colocou um + alguma coisa na frente ao
invez de inclementar a contagem. leia na internet sobre regras de versão
e aplique no sistema".

### Diagnóstico (confere com o dono)

- Servidor: `OD_VERSION=1.2.0` no `.env` CONGELADA desde 09-12, enquanto
  entravam auth, papéis, histórico, painéis (tudo feature = MINOR).
- App: `1.2.8+8…+11` — features entrando com o versionName parado e o
  `+N` (versionCode Android, metadado de build) fazendo o papel do X.Y.Z.
- Especificação aplicada: **SemVer 2.0.0** (semver.org/lang/pt-BR).

### Implementação

- **docs/VERSIONAMENTO.md (NOVO)** — política formal: formato X.Y.Z,
  quando bumpar MINOR/PATCH/MAJOR, `+N` = metadado (nunca substitui a
  versão), fonte da verdade (`.env` → capabilities → pubspec/site/docs),
  checklist de bump, histórico do saneamento. Referenciada na regra 12
  de `iniciar/RULES.md` (a antiga 12 virou 13).
- **Saneamento → 1.3.0:** `.env` OD_VERSION=1.3.0; fallback de
  `core/capabilities.py` 1.3.0; `app/pubspec.yaml` 1.3.0+12 (versionCode
  12); `site/index.html` badge hero + card do APK v1.3.0;
  `docs/CHANGELOG.md` seção **[1.3.0]** no topo com a nota de mapeamento
  (entradas 09-19→09-26 ficam na [1.2.0] por ordem de registro; de agora
  em diante nascem na release vigente).

### Verificação

- Suíte completa: **1914 passed, 16 skipped**; test_capabilities/test_api
  (98) verdes; OD_VERSION resolvido = 1.3.0 e fallback = 1.3.0.
- flutter analyze 0 issues; flutter test 81 passed, 2 skipped.
- APK publicado: `aapt2` → **versionCode='12' versionName='1.3.0'**;
  full 52.410.843 B (sha256 1efa5b22…) + arm64 18.715.654 B (36934ff9…);
  anterior preservado em `backups/apk-v1.2.8+11-20260926/`.
- Deploy: restart do od-core (autorização permanente de 09-23) — **PID
  547622, NRestarts=0**; journal 0 Traceback/ERROR/CRIT.
- Prova viva 7/7: GET / → version 1.3.0; Server header
  OmegaDrakon/1.3.0; /capabilities → 1.3.0; site local e pela URL pública
  do Funnel (200) exibindo v1.3.0 (4 ocorrências); REST 401/WS 426 no ar.

## 6. Guardas de coerência da versão (04:5x–05:0x)

Pedido: "Guardar guardas de teste que fixem a coerência da versão entre
.env, capabilities, pubspec e site".

- **tests/test_version_policy.py (NOVO, 6 testes)** — SemVer válido;
  .env = OD_VERSION resolvida; fallback congelado = versão vigente;
  pubspec versionName = versão do sistema (+N inteiro positivo); site
  com ≥ 2 ocorrências de v{versão} e sem resíduo v1.2.8; CHANGELOG com
  '## [X.Y.Z]' da versão vigente.
- **Teste do teste: 5 mutações, TODAS detectadas e revertidas** (.env
  antiga → 3 falhas; pubspec antigo, site antigo, fallback antigo e
  CHANGELOG renomeado → 1 falha cada).
- **Suíte: 1920 passed, 16 skipped** (+6).
- docs/VERSIONAMENTO.md ganhou §6 (Guardas de coerência).

## 7. Estado da sessão

- **Código:** commitado (ver git log) e NO AR (PID 547622, v1.3.0).
- **Suíte:** 1920 passed, 16 skipped.
- **Pendente:** instalar o APK 1.3.0+12 no celular (confirmação do dono).

## 8. Retomada (~11:05) — lote não registrado + v1.4.0

Pedido: "leia iniciar". O working tree tinha 10 arquivos modificados
(mtimes 05:22–05:52, DEPOIS da transcrição de 04:54) sem commit, sem
registro em iniciar/ e SEM deploy — provavelmente de uma sessão anterior
que fechou sem salvar. Resíduo `postgres:/` (SQLite vazio de 1 página,
DSN acidental como path) encontrado na raiz e removido com autorização.

### Conteúdo do lote (analisado por diff)

- **Cânone da Plêiade corrigido** (`IDENTITY.md`, `SOUL.md`,
  `personality.py`): Nyx = Guardiã do Limiar (religião, mitologia,
  esoterismo); Regulus = Conselheiro (história, direito, ética) — antes
  trocados. Cânone: `~/Legado/Nexus/docs/Personagens.md`.
- **Perfil `auto` pelo domínio em TODOS os transportes**: nova
  `agents/profiles.resolve_auto()` compartilhada — REST (`/message`,
  `/anon/message`), WS e bot usavam caminhos próprios e REST/WS forçavam
  `guardian` (pergunta de religião respondia como Guardian, a Nyx nunca
  era convocada).
- **Cache LLM saneado** (`core/orchestrator.py`):
  `_cacheable`/`cache_failure_reason` — resposta com etiqueta de log
  (`[NICKY][CRIT]`/`[WARN]`/`[INFO]`/`[ONLINE]`), vazia ou truncada no
  meio da frase NÃO entra no cache (bug "resposta de cache sem nexo").
- **Rotas novas** (`integrations/api/server.py`, 33 → 41):
  `POST /admin/cache/prune` (dry_run/varredura/keys, admin) e
  `DELETE /history/{u}/messages/{id}` (`memory/history.py` ganha
  `delete_message` pela PK; `Message.id` exposto nas listagens).
- **+13 testes** em `tests/test_api.py`.

### Validação e bump (decisão do dono: implantar e publicar)

- Suíte completa: **1932 passed, 16 skipped** (antes e depois do bump).
- Sandbox: `auth_sandbox.py` **57 OK, 0 FALHA**.
- **Bump pela política (feature = MINOR → 1.4.0)**: `.env` OD_VERSION,
  fallback de `core/capabilities.py`, `app/pubspec.yaml` 1.4.0+13,
  `site/index.html` (2 ocorrências), `docs/CHANGELOG.md` (seção [1.4.0]
  no topo), `docs/README_VERSAO.md` (seção 1.4.0).
- APK 1.4.0+13: buildado e publicado em `site/` (aapt2
  versionCode='13' versionName='1.4.0'; full 52.410.843 B sha256
  bb3919b5…; arm64 18.715.658 B sha256 4914be4e…); flutter analyze
  0 issues; flutter test 81 passed, 2 skipped.

### Deploy e prova viva (5/5)

- `systemctl --user restart od-core` (autorização permanente de 09-23):
  **PID 586587, NRestarts=0** desde 11:10:36; journal 0
  Traceback/ERROR/CRIT.
- `/capabilities` → 200 **1.4.0**; Server header `OmegaDrakon/1.4.0`.
- `/admin/cache/prune` dry_run → 200, **47 entradas varridas e 47
  candidatas** (o cache inteiro é `[NICKY][ONLINE] …` — o bug em
  ação); poda real NÃO executada (fica a decisão do dono).
- `/history/alex` → 200 com `id` nas mensagens (base do DELETE
  individual).
- `/health` → 200 ok=true, 9/9 checks up; WS :8001 → 426; Funnel
  `/capabilities` pela URL pública → 200 versão 1.4.0.

### Publicação

- Commit **7d29592** `feat(api,agents): perfil auto pelo domínio, cache
  sem falhas e poda admin (v1.4.0)` — 17 arquivos, +569/−39; HEAD ==
  origin/master; árvore limpa (regras 7.1/7.2).

### Pendências abertas

1. **Prune real do cache** (47 falhas cacheadas): `POST
   /admin/cache/prune` sem `dry_run` — aguardando o dono.
2. **Instalar o APK 1.4.0+13 no celular** (13 > 12 instala por cima).
