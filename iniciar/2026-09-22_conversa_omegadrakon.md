# OmegaDrakon — conversa de 2026-09-22

> Transcrição da sessão (regra 4 do `iniciar/RULES.md`). Contexto completo em
> `iniciar/session.json` (§`reboot_prova_2026_09_22`, §`alias_transporte_2026_09_22`).

---

## 1. Retomada: "leia iniciar"

Pedido: "leia iniciar".

Lidos `iniciar/README.md`, `iniciar/RULES.md`, `iniciar/session.json` e a
transcrição de 09-21. Estado vivo conferido antes de assumir contexto (regra 3).

**Achado principal:** o reboot que a sessão anterior deixara pendente **já
aconteceu** — e o Funnel sobreviveu sozinho — **mas o provador nunca foi
instalado**.

| Verificação | Resultado |
|---|---|
| `boot_id` | `3f33b3fe…` → **`64896b18…`** (diferente = reboot confirmado) |
| Journal | od-core parou 11:00:51 → `-- Boot 64896b18…` → subiu **11:01:36** (PID 1130, `NRestarts=0`) |
| Autonomia | `Linger=yes`, `tailscaled` e `od-core` **enabled+active** |
| Funnel pós-boot | **`# Funnel on`** com `/`→8000 e `/ws`→8001 |
| Probe da URL pública | `/health` → **401** (nossa API) · `/ws` → **426** (nosso WS), 0,03 s |
| `od-boot-prover` | `not-found`, sem `last.txt` (instalação nunca ocorreu) |

O usuário escolheu **aceitar a evidência retroativa** do boot (o Funnel
sobrevive ao reboot; o critério formal do `last.txt` fica dispensado) e seguir
para **migrar o histórico app + Telegram**.

## 2. Alias de transporte legado → conta

Decisão: **"Migrar + rotear Telegram e app por código"**, estendida (com
autorização) ao balde `web` do chat em modo avançado.

O motivo de os baldes terem ficado de fora antes era real: o **app** manda
`user_id: "app"` fixo (via `OD_API_KEY`), o **bot** usa o id numérico do chat e
o **chat web em modo avançado** usa `web` — cada um renasceria na mensagem
seguinte. A solução é um mapa de operador: `OD_ACCOUNT_ALIASES`.

### Implementação

- **`core/identity.py` (novo)** — `parse_aliases("app=alex,…")` e
  `resolve_account(id, mapa)`: casamento sem diferenciar maiúsculas, entradas
  malformadas ignoradas, mapa vazio = comportamento antigo.
- **REST** (`integrations/api/server.py`) — `APIConfig.account_aliases` +
  `resolve_account` no caminho **sem usuário** do `POST /message`.
- **WebSocket** (`integrations/api/ws_server.py`) —
  `WebSocketServer(account_aliases=...)` aplicado quando o frame `auth` não traz
  identidade de usuário.
- **Telegram** (`integrations/telegram/bot.py`) —
  `TelegramBot(account_aliases=...)` + `_account_for(chat)` em `process()`,
  `history_lines()` e `clear_chat()`.
- **`runtime/launcher.py`** — monta o mapa em um único lugar e injeta no REST,
  no WS e no bot. `.env`: `OD_ACCOUNT_ALIASES=app=alex,660518870=alex,web=alex`
  (backup em `backups/env-20260922-pre-alias.bak`).

Regra mantida: **credencial de usuário manda** — sessão `Bearer` ou API key
`od_...` ainda define a identidade e o alias é ignorado.

### Verificação (regra 12)

| Prova | Resultado |
|---|---|
| `tests/test_identity.py` (novo) + alias no REST/WS/bot | **1870 passed, 16 skipped** |
| Teste do teste (4 mutações, revertidas) | resolve bruto → 6 falhas · REST sem alias → 1 · WS → 1 · bot → 1 |
| Sandbox `sandbox_agent/auth_sandbox.py` (5º cenário: REST+WS+Telegram) | **44/44 OK** (era 36) |

### Migração no banco real

```
.venv/bin/python -m runtime.migrate_history_owner \
    --de app,660518870,web --para alex --apply
```

- `660518870`/guardian **20** + `app`/guardian **44** + `web`/guardian **6** =
  **70 msgs** → `alex` (**28 → 98**).
- Total da tabela **intacto** (102 antes e depois); resíduo na origem: nenhum.
- Snapshot de rollback: `backups/history-owner-20260922-020027.bak`.
- Fora da migração, de propósito: `deploy-check(-2)` (4 msgs sintéticas).

## 3. Deploy do Alias de Transporte

Restart do `od-core` autorizado pelo usuário — registrado com a prova viva no
§`alias_transporte_2026_09_22` do `iniciar/session.json` após o deploy.

---

## 4. Papéis, Vínculo do Telegram e Modo Anônimo (Fases 1a, 1b, 1c)

Decisão do usuário: **cada pessoa com a própria conta, a mesma em qualquer plataforma (chat/app/Telegram)**, continuando a conversa de onde parou; dono confirmado por `OD_API_KEY` tem privilégio total; no chat web, quem quer só conversar entra como anônimo sem privilégios.

- **Fase 1a (Papéis & Gate):** `OD_OWNER_USERNAME=alex`; a `OD_API_KEY` assume a conta do dono com `role="admin"`; `POST /executa` restringe níveis 1 e 2 apenas ao dono (403 fora dele, 422 sem confirmação para nível 2); papel `user` com lista explícita de actions de leitura; papel `anonymous` bloqueia qualquer action.
- **Fase 1b (Telegram `/entrar`):** tabela `telegram_links` no PostgreSQL (`UserStore.link_telegram` / `unlink_telegram`); comandos `/entrar <user> <pass>` e `/sair` no bot. Chat vinculado roteia para o balde da conta.
- **Fase 1c (Chat Anônimo):** rota pública `POST /anon/message` em `AUTH_EXEMPT_PATHS`; botão "Entrar como anônimo" na UI web; histórico mantido estritamente no navegador (`persist=False` no backend, zero mensagens gravadas em banco).
- **Validação e Deploy:** Suíte 1887 passed, 16 skipped; sandbox `auth_sandbox.py` 57/57 OK. Deploy com restart autorizado em 02:38:52 (PID 77701, NRestarts=0); provas vivas 4/4 OK. Commits: `d64e930`, `859b624`, `dd0428c`.

---

## 5. Fase 2 — Login/Registro no App Flutter e APK 1.2.8+10

Objetivo: permitir autenticação por conta no aplicativo móvel com token de sessão, unificando o histórico do celular com o chat web e o Telegram.

### Implementação
- **`app/lib/screens/login_screen.dart` (novo):** tela de entrada para entrar ou registrar conta (`/auth/login` e `/auth/register`), exibição de erros da API, alternância entre modos e botão de "Modo avançado (API key)".
- **`app/lib/services/od_api.dart`:** suporte a token de sessão (`login`, `register`, `logout`, `setToken`), persistência em SharedPreferences (`od_session_token`, `od_username`), envio de header `Authorization: Bearer <token>` prioritário sobre `X-API-Key`.
- **`app/lib/services/od_ws.dart`:** frame `auth` transmite `token` quando logado, atrelando o canal WebSocket à identidade da conta no servidor.
- **`app/lib/main.dart`:** `OdRoot` faz bootstrap inicial — direciona para `LoginScreen` se não houver credencial salva ou `OdHome` se autenticado/modo avançado.
- **`app/pubspec.yaml`:** versão incrementada de `1.2.8+9` para `1.2.8+10`.

### Verificação e Build
- `flutter analyze` — 0 issues.
- `flutter test` — 77 passed, 2 skipped (smoke tests e testes de API com Bearer e sessão validados).
- `app/build_apk.sh` — APKs gerados e publicados em `site/`:
  - `site/OmegaDrakon.apk` (52.394.459 B, universal)
  - `site/OmegaDrakon-arm64.apk` (18.715.654 B, arm64)
  - `versionCode='10'`, `versionName='1.2.8'` conferidos via `aapt2`.

---

## 6. Retomada: "leia iniciar" (03:20)

Retomada da sessão e leitura do checkpoint.
- Sistema em execução: `od-core` ativo (PID 77701, 0 restarts), Funnel ativo (`https://nicky-server.tail1b1f51.ts.net`), banco de dados Postgres saudável.
- Fase 2 (App Flutter) finalizada e validada; pronta para instalação no dispositivo e commit `721927e`.

---

## 7. Ajuste de Senha da Conta `alex` (03:45)

Pedido: "ainda não funciona. o usuario é alex mas senha não entra, seria senha123".

### Diagnóstico
- Consulta ao PostgreSQL revelou que o hash armazenado para o usuário `alex` (criado em 19/09) não correspondia à senha `senha123` (`_verify_password` retornava `False`).
- Tentativa registrada no journal com `401: Usuário ou senha inválidos`.
- `LoginGuard` não bloqueou a conta (apenas 1 tentativa na janela, teto é 5).

### Ação e Verificação
1. **Snapshot de segurança:** `backups/users-pre-password-reset-20260922-034629.bak`.
2. **Atualização:** novo hash PBKDF2-SHA256 gravado no PostgreSQL para o usuário `alex`.
3. **Provas vivas:**
   - `POST http://127.0.0.1:8000/auth/login` → **HTTP 200** com token de sessão gerado.
   - `GET /auth/me` com o token → **HTTP 200**, `role="admin"`, `username="alex"`.
   - `POST https://nicky-server.tail1b1f51.ts.net/auth/login` (via Funnel público) → **HTTP 200** com sessão ativa.
   - `UserStore.verify_credentials('alex', 'senha123')` → **True** (habilita login no Telegram via `/entrar alex senha123`).
   - Mensagens da tabela `conversation_messages`: 100 mensagens da conta `alex` intactas.

---

## 8. Diagnóstico: Histórico Visual no App e Web (03:55)

Pedido: "feito, mas nada mudou, não deveria aparecer as conversas".

### Diagnóstico
- As 104 mensagens da conta `alex` estão salvas no banco PostgreSQL e são carregadas no contexto da IA (memória ativa do assistente ao responder).
- No entanto, a interface visual do app Flutter (`ChatScreen`) e do chat web iniciavam com lista de mensagens vazia (`_messages = []`) e nunca faziam requisição para buscar o histórico salvo.
- Na API REST (`integrations/api/server.py`), só existiam rotas para estatísticas (`/history/{user_id}/stats`) e exclusão (`DELETE`), sem rota `GET /history/{user_id}` para fornecer as mensagens anteriores para a tela.
- Proposta: criar a rota `GET /history/{user_id}` na API e fazer o app carregar e exibir as mensagens anteriores automaticamente ao abrir o chat.

---

## 9. Implementação do Histórico Visual (retomada)

A sessão anterior foi interrompida com o backend parcialmente pronto no working
tree. Esta retomada completou o trabalho (achado pela regra 5 — código antes de
suposições: `git diff` mostrou backend + chat web já implementados e testados;
no app Flutter não havia nada).

### Backend (já pronto no working tree, conferido)
- **`GET /history/{user_id}`** — rota `history_get` com `?limit=N` (1–200,
  default 50) e `?profile=` (default `auto`). `_check_owner` ANTES do 404/501
  (não revela existência de histórico alheio); aceita `me`/`@me` resolvendo para
  a própria conta.
- **`memory/history.py: get_messages()`** — consulta direta no banco
  (`ORDER BY id DESC`, devolvido em ordem cronológica) com fallback em memória.
- **Chat web** — `loadHistory()` carrega 50 msgs ao entrar (não roda no anônimo).

### App Flutter (implementado nesta retomada)
- **`OdApi.getHistory({userId='me', limit=50})`** — best-effort (lista vazia em
  erro; sem credencial não chama); modelo `OdHistoryMessage` com `ts` em
  segundos → `DateTime`.
- **`ChatScreen._loadHistory()`** no `initState`: as últimas 50 mensagens da
  conta aparecem ao abrir a conversa; falha silenciosa não trava o chat.
- **`app/pubspec.yaml`**: `1.2.8+10` → `1.2.8+11`.

### Verificação (regra 12)
| Prova | Resultado |
|---|---|
| Suíte python | **1887 passed, 16 skipped** (+5 do GET) |
| flutter analyze | **0 issues** |
| flutter test | **81 passed, 2 skipped** (+4 do histórico) |
| APK | `site/OmegaDrakon.apk` 52.410.843 B · arm64 18.715.654 B · aapt2 `versionCode='11'` |

### Estado
- COMMITADO e PUSHED (regra 7.1).
- **PENDENTE:** restart autorizado do `od-core` (endpoint no ar + prova viva
  `GET /history/alex` com credencial) e instalação do APK 1.2.8+11 no celular.

---

## 10. Deploy do Histórico Visual (2026-09-23 13:23)

Restart do `od-core` **autorizado pelo usuário** nesta retomada.

- **Serviço:** active desde 13:23:22 — PID 235324, `NRestarts=0`; :8000 e :8001
  escutando; journal sem nenhum err/Traceback desde o restart; `/health` ok/up;
  `/supervision` up, restarts: 0; Funnel on (`# Funnel on` na URL pública) e
  `/health` de fora → 401 em 0,06s.
- **Prova viva do endpoint (no ar):**
  - `GET /history/alex?limit=5` com `OD_API_KEY` → HTTP 200 em 0,05s, 5
    mensagens em ordem cronológica (roles user/assistant reais da conta).
  - `GET /history/me` → `user_id: alex` (resolução do `me` funcionando).
  - Sem credencial → HTTP 401 (`OD_API_AUTH_ALL=1`).
  - `GET :8001` → HTTP 426 (WS no ar).
- **Commit:** `b3d767d` (12 arquivos, +394/-10; `HEAD == origin/master`).

### Estado final
CONCLUÍDO — resta o usuário instalar o **APK 1.2.8+11** no celular
(versionCode 11 > 10 instala por cima) e conferir as conversas anteriores ao
abrir o chat.



