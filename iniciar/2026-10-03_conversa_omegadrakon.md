# Conversa OmegaDrakon — 2026-10-03

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar"** (~09:41) e, em seguida, **"Rodar a verificação geral do
sistema para fechar a retomada"** (~09:44). Ambiente canônico de testes:
`.venv/bin/python` SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada (~09:41)

- Leitura da ordem da casa: `iniciar/README.md` → `RULES.md` →
  `session.json` (1244 linhas) → transcrição de 02/10 (§1–§8).
- Estado herdado: **v1.17.4 NO AR** (od-core desde 01/10 23:48:57,
  PID 10933, NRestarts=0).
- Verificação rápida: árvore limpa · HEAD `4d2c937` == origin/master ·
  od-core/od-llm/orchestrator active · `/app/version {1.17.4, 2037,
  53972629 B, sha256 6a10064b…}` == `site/OmegaDrakon.apk` ·
  `/health 401` sem chave (portão por design) · `/supervision` restarts 0 ·
  journal de hoje 0 erros.
- Pendências do dono intactas: (1) APK 1.17.4+2037 no celular;
  (2) credencial OAuth do Google; (3) gemma quando o hardware crescer.
  — Os 2 achados de infra de 30/09 já estavam **fechados** em 02/10
  (CI limpo + cobertura 90,17%, `12c34c1`) e a arquitetura Google está
  publicada (`20b724d`).
- Registro da retomada salvo no `session.json` e publicado (`63502ad`).

## 2. Verificação geral do sistema (~09:44–09:47)

**Serviços**

- od-core active PID **10933**, NRestarts=**0**, desde 01/10 23:48:57.
- od-llm active · od-orchestrator active · od-control-bridge (system)
  active PID 1182 · omega-drakon (bot) active PID 1241, NRestarts=0 desde
  01/10 23:06:41 · tailscaled active.
- Portas no ar: 8000 (REST) · 8001 (WS) · 1883 (Mosquitto) ·
  5432 (Postgres) · 8765 (control-bridge).

**API**

- `/health` → **9/9 checks up** (orchestrator, llm, audit, database…).
- `/supervision` → status up · restarts 0 · degraded [].
- `/capabilities` → 1.17.4 · **65 actions no ar** (as 71 do Google entram
  só no deploy com credencial — código commitado em 02/10, processo do
  od-core é de 01/10).
- `/app/version` → {1.17.4, code 2037, size 53972629,
  sha256 `6a10064b…`} == `site/OmegaDrakon.apk`.
- WS 8001 → HTTP 426.

**Funnel (prova de fora)**

- `# Funnel on`: `/` → 127.0.0.1:8000 e `/ws` → 127.0.0.1:8001.
- `/health` → 401 em 0,052 s · `/ws` → 426 em 0,033 s ·
  `/app/version` → 200 em 0,165 s.

**Banco (PostgreSQL)**

- users 2 · sessions 34 (**17 válidas**) · conversation_messages **168**
  (alex 166, última 02/10 12:40; teste 2, de 29/09) · telegram_links 0 ·
  llm_cache 65 com **0 etiquetadas** (100% saudável, sem poda).

**Journal**

- od-core: **0** Traceback/ERROR/CRIT desde o restart de 01/10 23:48:57.
- od-llm / od-orchestrator / od-control-bridge: 0 hoje.
- omega-drakon: 42 linhas de Traceback **hoje** — todas
  `httpx.ConnectError: Temporary failure in name resolution` (DNS
  transitório para `api.telegram.org`; rajada 03:00:13–03:01:02 +
  isolados 04:00, 05:11, 07:50 e 09:18), dentro do `network_retry_loop`
  do python-telegram-bot. Bot **não reiniciou** (NRestarts=0) e segue
  ativo (CHECK a cada minuto às 09:44); DNS resolve agora
  (`api.telegram.org` → `2001:67c:4e8:f004::9`). **Auto-recuperado,
  sem ação** — se recorrer, investigar resolv/rede do host.

**Git**

- Working tree **limpo**; HEAD `63502ad` == origin/master (0 à frente).

**Estado: VERDE** — nada reiniciado nesta verificação.

## 3. Passo a passo do OAuth do Google (~09:51)

Pedido: **"Preparar o passo a passo do OAuth do Google para eu criar a
credencial"**. Guia entregue no chat, conferido contra o código
(`docs/GOOGLE.md`, `runtime/google_auth.py`, `integrations/google/models.py`,
`runtime/launcher.py`):

1. Ativar **Drive API + Calendar API + Gmail API** no Cloud Console.
2. Consent screen **External** + e-mail como *test user* — **aviso**: em
   modo *Testing* o refresh token expira em **7 dias** (recomendado:
   *Publish app*).
3. **Credenciais → OAuth client ID → Desktop app** → baixar o JSON.
4. Copiar o JSON **como veio** para `config/google_credentials.json`
   (gitignored) — `models.py` lê `redirect_uris[0]`, então o redirect bate
   sem `redirect_uri_mismatch`; alternativa: `example.json` com
   `http://localhost:8766/`.
5. Autorização headless: `runtime/google_auth --url` → navegador →
   `--code "<URL de retorno>"` (escopos readonly; token em
   `data/google_token.json` 0600).
6. `--check` → token presente + refresh sim.
7. **Depois (aqui):** restart do od-core (o launcher só injeta o cliente se
   o arquivo existir no start) + prova viva (`meus e-mails` / `minha
   agenda` / `meus arquivos no google drive`) + **bump MINOR 1.18.0** com
   checklist completo e APK rebuildado.

**Estado base verificado:** `--check` → "credenciais ausentes" (exit 1) ·
`data/google_token.json` inexistente · `config/*_credentials.json` no
`.gitignore`.

**Aguarda:** ação do dono no Console (passos 1–5) e o resultado do
`--code`.

---

Interface Viva: Nicky Virthy · Arquiteto: Alex Projeti
Assinatura: `OD // CORE`
