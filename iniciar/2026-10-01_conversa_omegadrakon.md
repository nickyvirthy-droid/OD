# Conversa OmegaDrakon — 2026-10-01

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar. chat esta dando erro interno"** (~09:5x).
Ambiente canônico de testes: `.venv/bin/python` SEM
`OD_TEST_POSTGRES_DSN`.

---

## 1. Diagnóstico do erro interno (~09:5x–10:0x)

- Retomada pela ordem da casa: `iniciar/README.md` → `session.json`
  (estado herdado: **v1.15.0 NO AR**, PID 1178955, de 30/09 21:36) →
  transcrição de 30/09.
- `systemctl --user status od-core`: active, mas o journal mostrava o
  padrão do erro:

  ```
  [NICKY][WARN] DB query falhou | error=network error | sql=SELECT ... FROM sessions s JOIN users u ...
  [NICKY][ERROR] API interna | error=DatabaseError
  ```

  Nas 4 queries de banco do caminho do chat (sessions JOIN users,
  users por username, telegram_links, llm_cache) desde **08:26** —
  `network error` é a mensagem do **pg8000 para socket morto**.
- Causa raiz: o **Postgres reiniciou às 06:31** (PID novo, processos
  background todos de 06:31) e o od-core, de pé desde 30/09 21:36,
  manteve no pool as conexões que o banco encerrou. O
  `PostgresConnectionPool.acquire` nunca validava a conexão antes de
  entregar → **conexão podre servida para sempre** → toda query de
  usuário/sessão/cache falhava → o chat devolvia **erro interno**.
- `/health` sem credencial dava 401 (auth_all no ar) — o diagnóstico
  veio do journal, não do endpoint.

## 2. Correção — pool postgres auto-curável (§pool_postgres_auto_cura_2026_10_01)

`storage/database.py` — só o `PostgresConnectionPool` (SQLite intacto):

- `acquire` valida cada conexão ociosa com **`SELECT 1`**
  (`_conn_viva`); qualquer falha = podre.
- Conexão morta: **fechada, removida da contagem** (`_discard`) e
  **substituída** — o sistema se recupera sozinho de restart do
  Postgres, sem restart do od-core.
- Retry limitado (`size + 1` tentativas); se todas vieram podres,
  cria uma nova no slot liberado. Contrato de **fila bloqueante
  quando esgotado** (sem estouro de conexões) preservado — e agora
  fixado por teste.
- Log novo: `DB conexão morta descartada pelo pool (postgres)`.

## 3. Testes e teste do teste

- `tests/test_database.py`: **+5 `TestPoolPostgresConexaoMorta`**
  (fake `_FakePgConn`): morta descartada e substituída · pool se
  recupera quando TODAS morrem · viva passa sem criar · pool fechado
  recusa · esgotado BLOQUEIA.
- Suíte completa: **2130 passed, 16 skipped** (68s, .venv canônico).
- **Teste do teste — 3/3 mutações bit-exata:**
  - M1 validação desligada (`if True`) → 2 falhas;
  - M2 socket morto tratado como vivo (`except Exception` →
    `RuntimeError`) → 2 falhas;
  - M3 fila bloqueante virou criação fora do lock → **1ª rodada
    SOBREVIVEU** (teste fraco: pool não estava esgotado) → endurecido
    com o contrato do cabeçalho do módulo ("quando o pool esgota,
    acquire bloqueia até uma liberação — sem estouro") → mutação
    re-detectada (1 falha). **Lição da casa de novo** (precedentes
    28–30/09): teste fraco passa mutação — endurecer antes de
    declarar coberto. Nota de método: a 1ª tentativa de restauração
    do M1 deixou a mutação no arquivo quando o M2 rodou (backup
    defasado) — `git diff` de conferência antes de cada rodada.

## 4. Bump MINOR 1.16.0

Política do CHANGELOG: "correção de robustez interna (sem rota/
endpoint/action nova) com testes novos = MINOR conservador".

- `.env` OD_VERSION=1.16.0 · capabilities fallback · pubspec
  **1.16.0+2032** · `_APP_VERSION_CODE=2032` · site 2x ·
  `CHANGELOG [1.16.0]` · `README_VERSAO §1.16.0`. Zero sobra de
  1.15.0 nos pontos do checklist.
- APKs rebuildados (`JAVA_HOME=~/jdk`, `PATH += ~/flutter/bin` — o
  flutter não está no PATH do serviço) e publicados em `site/`:
  aapt2 `versionCode='2032' versionName='1.16.0'` nos dois; sha256
  full `c80b9c1b…`, arm64 `30607f36…` (lição 4384e5b: nunca anunciar
  build não publicado).

## 5. Commit, deploy e prova viva (~10:1x–10:3x)

- **Commit `925baba`** fix(storage) — 9 arquivos +288/−7 (inclui
  `limitacoes.txt`, padrão da casa: dados do runtime vão junto) →
  push `d559b72..925baba master -> master` (regra 7.1).
- **Deploy IMPLANTADO** — restart 10:15, **PID 1238524**, NRestarts=0.
- **Prova viva:**
  1. `/health` ok, **9/9 checks up** (database incluso);
  2. `/app/version` → `{1.16.0, 2032, sha256 == binário de site/}`;
  3. `/capabilities` → 1.16.0 · **65 actions**;
  4. WS do chat na **8001**: handshake ok com credencial (o 426 das
     provas antigas é do ws_server dedicado; a rota `/ws/chat` da API
     REST responde 501 por decisão da Fase 5.2 — não é regressão);
  5. `/executa datetime` → pipeline completo ok;
  6. journal desde o restart: **0 Traceback · 0 ERROR**.
- **Prova da cura (o passo decisivo):** `pg_terminate_backend`
  derrubou as conexões do od-core pelo lado do Postgres (simulação
  EXATA do evento de 06:31) → journal registrou
  `DB conexão morta descartada pelo pool (postgres)` → a action
  seguinte respondeu `ok: True` **SEM restart** — auto-cura provada
  no ar.

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.16.0.** O erro interno do
chat estava na camada de persistência, não no LLM/orquestrador; a
classe inteira de falha (restart do banco com o servidor de pé) está
fechada. Pendência do dono: instalar o APK 1.16.0+2032 no celular
(2032 > 2031). Pendência do sistema: nenhuma desta entrega.
