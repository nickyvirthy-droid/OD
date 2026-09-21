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

## 6. Sequência dos 5 pendentes (autorizada: "faça todos na sequencia")

Antes: o usuário liberou **commit e push por padrão** (regra 7.1 do RULES.md) e
pediu sistema limpo e atualizado; informou que o **APK já está instalado**, mas
só acessa pela internet via Tailscale.

| # | Item | Commit | Prova |
|---|---|---|---|
| 1 | Identidade do WS vem da credencial | `d8374e2` | +17 testes, 4 mutações, sandbox `ws_sandbox.py` **18/18** (llama real), suíte 1842/16 |
| 2 | Histórico órfão migrado | `a630b47` | `web`+`web/nyx`+`ws_user` = 24 msgs → `alex` (2 → **26**), total 86 intacto, confirmado pela API no ar |
| 3 | Sandbox do `LoginGuard` (regra 12) | `d42e2be` | `auth_sandbox.py` **36/36** (era 27) |
| 4 | Acesso externo: diagnóstico | `03580ba` | `docs/ACESSO_EXTERNO.md` + medições externas |
| 5 | 404 em `/history` e backup do legado | `6af4d2f` | +4 testes, 4 mutações, suíte **1854/16** |

### 4 — o que o app tem (e o que não tem)

O APK **não está com defeito**: `app/lib/main.dart` já traz primária Tailscale +
externa `http://nicky.theworkpc.com`, a tela de Configurações separa "rede
local" de "internet" e o manifesto libera HTTP (`usesCleartextTraffic`). O que
falta é o caminho de entrada, e as medições fecharam o caso:

| Teste | Origem | Resultado |
|---|---|---|
| `curl http://nicky.theworkpc.com/health` | dentro da LAN | **401 em 0,31s** (hairpin NAT — não prova acesso externo) |
| DNS do domínio | público | `189.124.4.56` = IP público atual (DDNS em dia) |
| domínio + IP puro, HTTP | **de fora** (hackertarget) | **timeout** (controle `example.com` → 200) |
| `tracepath` | no servidor | `192.168.0.1` → `189.124.0.25` → internet: **não é CGNAT** |

Conclusão: nada entra pela **porta 80**; provavelmente bloqueio da operadora ou
a regra do roteador inativa/apontando para outro IP interno (a máquina hoje é
`192.168.0.250`). Caminho recomendado: **Tailscale Funnel** — o CLI respondeu
que ele não está habilitado no tailnet e deu o link de um clique; depois,
`tailscale funnel --bg 8000` publica `https://nicky-server.tail1b1f51.ts.net`.

### Pendências abertas

- **Caminho externo:** decisão do usuário (Funnel × porta 8443 no roteador) e,
  depois, ajustar o campo externo do app.
- **Restart do `od-core`:** o processo em execução é o do deploy da manhã
  (09:05:45) — o WS por credencial e o 404 ainda **não estão no ar**.
  Deploy/restart continua exigindo autorização explícita (regra 7.1).
- **Legado inerte:** backup pronto (`backups/legacy-json-sqlite-20260921.tar.gz`,
  gzip verificado, sha256 `545c29e3…`); a remoção de `data/conversations/` e
  `data/od.db` aguarda confirmação (regra 9).
- **Histórico ainda separado:** `app` (36) e `660518870` (20, Telegram) ficaram
  fora da migração de propósito — migrar depois que o app autenticar por sessão.- **Regra 12 do `LoginGuard`:** ele subiu no restart de 09-21 sem passar pelo
  sandbox antes do deploy (foi escrito em 09-20 e ficou sem registro). A
  cobertura são os 11 testes + a prova viva no ar; se quiser fechar a lacuna,
  vale um cenário no `auth_sandbox.py`.
- **Probe do LoginGuard:** travou `__probe_deploy__` por 900s e deixou 5
  falhas na chave de IP 127.0.0.1 (limite 15, janela 300s) — expira sozinho.
- **Antigas:** port forwarding 8001 no roteador e APK no Redmi Note 14 (o APK
  já está instalado; o que falta é o acesso externo — ver §6).

---

## 7. Funnel publicado e provado de fora

Pedido: "Habilitei o Funnel no tailnet (cliquei no link) — publique o Funnel e
confira de fora".

### Publicação

- `tailscale funnel --bg --https=443 8000` → REST (`/` → `127.0.0.1:8000`)
- `tailscale serve --bg --https=443 --set-path=/ws 8001` → streaming
  (`/ws` → `127.0.0.1:8001`)
- **Detalhe de operação:** o primeiro `serve --set-path` **derrubou** o
  `funnel` da 443 (`serve` e `funnel` dividem a mesma porta); republicar os
  dois resolveu — estado final `# Funnel on` com `/` e `/ws`.
- TLS emitido via ACME **dns-01** (journal: `got cert` às **10:06:23**).
- **DNS público demorou ~4 min** para aparecer: o autoritativo (dnsimple)
  respondeu NODATA e depois publicou os ingress `209.177.145.97` /
  `209.177.145.192` (TTL 300). Registrado para não repetir falso diagnóstico.

### Prova de fora

| Teste | Resultado |
|---|---|
| check-host `/health` (5 nós) | **4/5 → HTTP 401 `unauthorized` da nossa API** (Israel, Irã, Itália, Eslovênia; 1,1–1,4 s; ingress `209.177.145.97`). Com `OD_API_AUTH_ALL=1`, o 401 **é** a prova de chegada ao od-core. O 5º nó (Ucrânia) deu erro interno do próprio nó. |
| `GET https://nicky-server.tail1b1f51.ts.net/ws` | **HTTP 426** com `server: Python/3.12 websockets/16.1.1` — o próprio WS do od-core responde pelo mesmo host |
| `curl` do servidor pela URL pública | `/health` → 401 em 0,03–0,4 s |
| DNS público | Google/Cloudflare resolvem os dois ingress (TTL 300) |

`od-core` **não foi reiniciado** (segue PID 762754, NRestarts=0) — o Funnel é
externo ao serviço.

**Resultado:** a URL externa do app passa a ser
**`https://nicky-server.tail1b1f51.ts.net`** — o streaming nela é
`wss://host/ws`, que o app já deriva desde o commit `57c4710`. Falta atualizar
o default externo no app e gerar o APK novo.

