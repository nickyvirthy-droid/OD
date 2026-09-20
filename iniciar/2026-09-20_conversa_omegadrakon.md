2026-09-20 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu: `iniciar/README.md`, `iniciar/RULES.md`, `iniciar/session.json`
  e a transcrição mais recente (2026-09-18). NÃO existia transcrição de 09-19.

Achado na leitura (evidência, não memória):

O `session.json` parava em **09-19 10:55** (APK 1.2.8). Mas:
- `git log`: três commits de 09-19 sem registro no checkpoint — `22eae1c`
  (v1.2.8 app+api), `e0b0222` (site), `587012b` (chat web);
- `git status`: working tree **sujo** com uma feature inteira de auth
  (`integrations/api/auth.py` **untracked**; `server.py`, `launcher.py`,
  `test_api.py` modificados);
- `systemctl --user show od-core`: `ExecMainStartTimestamp=2026-09-19 11:39:02`,
  PID **543923**, `:8000` e `:8001` escutando;
- journal: `Auth de usuários habilitado` e `Usuário registrado | username=alex
  | user_id=1` (11:39:05); `/auth/login` responde 400 (rota existe) e `/chat`
  contém `auth/login`.

Leitura: **produção rodava código do working tree, à frente do último commit**
— feature de auth não commitada, não transcrita e sem teste dedicado.

Checkpoint atualizado imediatamente com o bloco
`estado_2026_09_19_nao_registrado` (JSON validado) e `last_turn`.

---

## Rodada — testar e travar a feature de auth

Usuário escolheu: **"Testar e travar a feature"** (cobertura + sandbox + commit).

### Leitura de contrato

- `integrations/api/auth.py`: `UserStore` com `register`/`login`/
  `validate_session`/`logout`/`logout_all`/`cleanup_expired`,
  `login_with_api_key`/`rotate_api_key`; hash **PBKDF2-SHA256** (260k iterações,
  salt 32 B) — stdlib, sem bcrypt.
- `server.py`: rotas `/auth/register|login|logout|me`; `_check_api_key` com
  Bearer de sessão + `X-API-Key` do `.env`; gate do chat web com login/registro.
- `storage/database.py`: `Database` (SQLite stdlib), `create_table/query/
  execute/repository/scalar`.

### Bugs reais encontrados (e corrigidos)

1. **Bypass de auth:** com `UserStore` ligada e **sem `OD_API_KEY`**, o
   `_check_api_key` caía no caminho "auth desligada" e **retornava True** — um
   `Bearer` inválido passava. Correção: com `UserStore` configurada, exige
   credencial válida (sem `Store`, o dev local segue aberto).
2. **API key de usuário não autenticava** no gate (`/auth/me` documentava que
   sim): o gate só comparava com `OD_API_KEY`. O caminho de API key de usuário
   (`login_with_api_key`) entrou no `_check_api_key`, com `_auth_via`
   (`session` | `api_key`) para o campo `via` do `/auth/me`.
3. **Teste pré-existente quebrado:** `test_api.py::test_auth_flags_follow_legacy`
   não listava `/auth/logout` e `/auth/me` — a feature havia quebrado a suíte
   sem ninguém notar (estava uncommitted).

### Testes

- `tests/test_auth.py` (**novo, 45 testes**): hash/salt e senha nunca em
  claro; registro (validação 400, duplicata 409, normalização, unicidade de
  api_key); sessão (login, expiração, logout, logout_all, cleanup); API keys
  (login/rotação/leitura, `list_users` sem `password_hash`); rotas `/auth/*`
  por HTTP real; e o gate (`_check_api_key`): sessão, API key de usuário,
  `OD_API_KEY`, Bearer inválido, sem credencial, e o caminho real
  `login → Bearer → POST /message`.
- **Teste do teste (5 mutações, todas revertidas):**
  | Mutação | Falhas |
  |---|---|
  | remover o bloqueio do bypass | 1 |
  | remover o caminho de API key de usuário no gate | 2 |
  | `_verify_password` sempre aceita | 3 |
  | `validate_session` ignora expiração | 1 |
  | `register` sem checar duplicata | 3 |
- Suíte: **1800 passed, 16 skipped** (39,49s).

### Sandbox (regra 12)

- `sandbox_agent/auth_sandbox.py` (pasta ignorada pelo git): `APIServer` real
  (sockets + SQLite de arquivo), com e sem `OD_API_KEY` → **16/16 OK**.
  Cobre register/login/Bearer, `/auth/me` por sessão e por API key, `POST
  /message` pela sessão, casos negativos (401) e o cenário do bypass.

### Commit

- `4337d02` — `feat(api): autentica usuários no chat web (registro, login,
  sessão)` — 6 arquivos (+1289/-32): `auth.py` (novo), `server.py`,
  `launcher.py`, `test_api.py`, `test_auth.py` (novo) e `docs/CHANGELOG.md`.
- **Não implantado:** o `od-core` (PID 543923) roda o código de 11:39, anterior
  ao fix do bypass. Restart exige autorização do usuário. No cenário real
  `OD_API_KEY` está definida, então o bypass não estava exposto — o fix é
  defesa em profundidade.

### Pendências

- Restart do `od-core` para levar o fix do bypass (autorização).
- Port forwarding 8001 no roteador e instalação do APK 1.2.8 no Redmi Note 14.
- Decidir se `/message` deve registrar o `user_id` derivado da sessão em vez
  do que o cliente manda (hoje o cliente manda `user_id: "web"`).
