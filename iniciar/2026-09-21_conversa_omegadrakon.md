# OmegaDrakon — conversa de 2026-09-21

> Transcrição da sessão (regra 4 do `iniciar/RULES.md`). Contexto completo em
> `iniciar/session.json` (§`estado_2026_09_21`, §`dono_historico_2026_09_21`).

---

## 1. Verificação do estado geral

Pedido: "verifique o estado geral do sistema. Agora que vamos utilizar senha
podemos manter as conversas. você está usando o banco de dados para armazenar
as informações dos usuários e as conversas?"

**Runtime:** `od-core` (systemd `--user`) ativo desde 2026-09-20 14:01:48,
PID 662233, `NRestarts=0`; `:8000` REST, `:8001` WS, `:1883` Mosquitto,
`:5432` PostgreSQL; `/supervision` → `restarts: 0`.

**Suíte:** 1814 passed, 16 skipped.

**Resposta: sim, PostgreSQL.** `OD_DB_URL` no `.env` →
`postgres://od@127.0.0.1:5432/od` (driver `pg8000`), health `ok`, 4 tabelas:

| tabela | linhas |
|---|---|
| `users` | 1 (`alex`, id=1, criado 2026-09-19 11:38) |
| `sessions` | 1 (válida até 2026-09-26 11:38, TTL 7 dias) |
| `conversation_messages` | 86 |
| `llm_cache` | 43 |

O `launcher.py` monta a `Database` **antes** do Orchestrator e injeta em
`ConversationHistory` e `LLMCache` — o caminho JSON não é exercido. Legado
inerte: `data/conversations/*.json` (último write 09-03) e `data/od.db`
(SQLite com 0 tabelas).

**Consequência:** a conversa sobrevive a restart e a novo login, porque desde
o commit `9bdc5ea` a identidade é o username autenticado. Baldes antigos
ficaram órfãos: `web`=14, `web/nyx`=6, `app`=36, `660518870`=20, `ws_user`=4,
`deploy-check*`=4.

**Lacunas encontradas (não registradas até então):**

1. `LoginGuard` (freio de força bruta) existia no working tree sem commit,
   **sem deploy** (mtime 14:07–14:16 > restart 14:01:48) e sem registro.
2. `/history/{user_id}` e `/memory/{user_id}/search` não checavam dono.

---

## 2. Checagem de dono em /history e /memory

Pedido: "Adicione checagem de dono em /history e /memory (usuário só acessa o
próprio histórico; OD_API_KEY como admin)".

### Implementação

`integrations/api/server.py` — novo `APIHandler._check_owner(user_id)`:

- **Credencial de usuário** (sessão `Bearer` ou API key `od_...`): o
  `{user_id}` do caminho tem de ser o username autenticado → senão **403
  `acesso_negado`** + log de aviso com `autenticado`, `alvo` e `path`.
- **`OD_API_KEY`** (servidor/app/bot): `_current_user is None` → **admin**,
  lê e apaga qualquer histórico.
- Sem `UserStore` (dev local): comportamento legado; sem credencial: **401**.
- Comparação **case-insensitive** (`/history/Alex` casa com `alex`).

Aplicado em `DELETE /history/{user_id}`, `GET /history/{user_id}/stats` e
`GET /memory/{user_id}/search` — neste a checagem vem **antes** do 501 do
`VectorStore` (não revela a estranhos se a memória vetorial existe).

### Verificação (regra 12 antes do sistema real)

| Prova | Resultado |
|---|---|
| `tests/test_auth.py` (+11, `TestHistoryOwnership`) | 70 passed |
| Teste do teste (5 mutações, revertidas) | sempre-libera → 5 falhas · só `Bearer` → 1 · case-sensitive → 1 · delete sem checagem → 1 · `/memory` após o 501 → 2 |
| Sandbox `sandbox_agent/auth_sandbox.py` (3º cenário, 2 usuários) | **27/27 OK** (era 18) |
| Suíte completa | **1825 passed, 16 skipped** |

Nota: `tests/test_mqtt.py::TestBridgeLifecycle::test_start_stop_thread`
falhou **uma vez** num run por timing (`assert not bridge.is_connected`);
passa isolado, 3× no arquivo e no run completo seguinte — flaky pré-existente.

---

## 3. Deploy e prova viva

Autorizado. `systemctl --user restart od-core` → **09:05:45**, PID **749398**,
`NRestarts=0`, `:8000`/`:8001` escutando, journal com **0**
`Traceback`/`ERROR`/`CRIT`; loops api/telegram/recovery/mqtt/presence/vision
de pé.

> **Atenção:** o restart levou junto o **`LoginGuard`** (mesmos arquivos) — o
> freio de força bruta passou a valer em produção neste deploy.

**Prova viva (13/13 OK)** — criada a conta `prova-dono` (user id=2) para
verificar com duas contas, usando as credenciais reais:

- `alex` → `GET /history/prova-dono/stats` = **403 `acesso_negado`**
- `alex` → `DELETE /history/prova-dono` = **403**, e o histórico do alvo
  continuou **intacto** (2 mensagens conferidas depois com o admin)
- `alex` → `GET /memory/prova-dono/search` = **403** (antes do 501)
- `prova-dono` lê o **próprio** = 200 · `alex` lê o próprio = 200
- `OD_API_KEY` (admin) lê o histórico **dos dois** = 200
- sem credencial = 401 · API key errada = 401
- `LoginGuard` vivo: 6ª tentativa de login do mesmo usuário → **429
  `too_many_attempts`**

Journal (09:06:04), três vezes:
```
[NICKY][WARN] Acesso a recurso de outro usuário negado | autenticado=alex | alvo=prova-dono | path=/history/prova-dono/stats
[NICKY][WARN] API erro | status=403 | detail=acesso_negado
```

MVP: a identidade vem da credencial e o histórico agora tem dono — quem entra
com a própria conta não lê nem apaga a conversa de outra pessoa.

## 4. Limpeza da conta de prova

Pedido: "Remova a conta de prova 'prova-dono' e seu histórico do banco de
produção".

Feito com **snapshot de rollback antes**
(`backups/prova-dono-removido-20260921-090719.bak`, gitignored — contém a
linha de `users`, as sessões e as mensagens). A remoção rodou em transação
(`with db.transaction():`, que usa a conexão por thread — `_Transaction` não
expõe `execute`).

| | antes | depois |
|---|---|---|
| `users` | 2 | **1** (`alex`) |
| `sessions` | 1 | 1 (a de `alex`) |
| `conversation_messages` | 88 | **86** |

Removidos: 1 user, 0 sessões (a conta nunca logou — só usou API key), 2
mensagens. Zero resíduo. A chave da conta removida agora responde **401**;
o admin segue lendo `/history/alex/stats` = 200 com 2 mensagens.

Observação de operação: a primeira tentativa abortou com
`AttributeError: '_Transaction' object has no attribute 'execute'` — o
rollback do contexto desfez tudo, nenhum dado saiu do banco.

## 5. Commit

Pedido: "Commite a checagem de dono e o LoginGuard, com mensagens no padrão do
repositório". Feito em **dois commits**, um por mudança:

| commit | mudança | arquivos |
|---|---|---|
| `6c888bf` | `feat(api): freio contra força bruta no login (LoginGuard)` | auth.py, server.py, launcher.py, test_auth.py, CHANGELOG (+355) |
| `7ca6eec` | `fix(api): histórico e memória só para o dono da conta (OD_API_KEY é admin)` | server.py, test_auth.py, CHANGELOG (+256/−5) |

Os dois trabalhos estavam nos mesmos arquivos, então a divisão foi feita por
hunk: os patches foram reatribuídos ao arquivo certo **testando cada hunk com
`git apply --check`** (auto-verificável) e o estado do `LoginGuard` foi
verificado antes de commitar (`tests/test_auth.py` 59 passed, suíte
**1814/16**), depois o estado final (**1825/16**).

**Prova de que os commits contêm exatamente o que está no ar:** sha256 dos 4
arquivos de código antes da divisão × depois dos dois commits → **idênticos**;
a árvore de trabalho bate com o que o PID 749398 carregou em 09:05:45. O
`docs/CHANGELOG.md` é o único que difere do estado pré-divisão — de propósito:
ganhou a seção do `LoginGuard`, que não existia (o trabalho tinha subido sem
registro).

O CHANGELOG ficou com as duas seções (`dono do histórico` e `freio contra
força bruta`), ambas de 2026-09-21. Push para o `origin` **não** foi feito
(2 commits à frente).

### Pendências abertas

- **Push:** 2 commits locais à frente do `origin/master`.
- **Regra 12 do `LoginGuard`:** ele subiu no restart de 09-21 sem passar pelo
  sandbox antes do deploy (foi escrito em 09-20 e ficou sem registro). A
  cobertura são os 11 testes + a prova viva no ar; se quiser fechar a lacuna,
  vale um cenário no `auth_sandbox.py`.
- **Probe do LoginGuard:** travou `__probe_deploy__` por 900s e deixou 5
  falhas na chave de IP 127.0.0.1 (limite 15, janela 300s) — expira sozinho.
- **Antigas:** port forwarding 8001 no roteador e APK 1.2.8 no Redmi Note 14.
