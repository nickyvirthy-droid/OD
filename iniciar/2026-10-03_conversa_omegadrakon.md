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

## 4. Prova viva do Google — bloqueio (~09:58)

Pedido: **"Já autorizei — reinicie o od-core e faça a prova viva do
Google"**. Antes de reiniciar (evidência primeiro):

- `config/google_credentials.json` e `data/google_token.json`
  **inexistentes**; `find` em `/home/alex` e `/tmp` → nenhum
  `google_token*.json` — o troca-código **nunca rodou no servidor**.
- A credencial baixada existe (`config/client_secret_….json` e
  `docs/client_secret_….json`, de 01/10 18:12), mas com o nome errado.
- Sem token, reiniciar só faria as actions `google_*` degradarem com
  "não autorizado" — **prova viva impossível**; reinício adiado.

**Ações:**

1. `cp config/client_secret_….json → config/google_credentials.json`
   (0600) — passo 4 do guia; `--check` agora reconhece a credencial
   (token AUSENTE, exit 1).
2. **Achado de segurança:** `config/client_secret_*.json` estava
   *untracked* e **fora** do `.gitignore` (só `docs/client_secret_*.json`
   era coberto) → risco de commitar o segredo. Corrigido no `.gitignore`
   (commit `5ab0d87`, publicado).
3. URL de consentimento gerada (`runtime.google_auth --url`) e entregue
   ao dono.

**Estado: BLOQUEADO numa ação do dono** — abrir a URL, autorizar e colar
a URL de retorno (`http://localhost/?code=…`; a página não abre = normal;
o redirect sai como `http://localhost` porque o JSON do Console é
*Desktop app* e `models.py` usa `redirect_uris[0]`). Depois: `--code` →
`--check` → restart do od-core → prova viva → bump MINOR 1.18.0 com
checklist + APK (regra 12).

## 5. "Faça por arquivos" — fluxo sem copiar/colar (~10:0x–10:3x)

Dono: **"não consigo copiar nada. faça por arquivos"** — ele lê o chat
pelo terminal (freebuff) e não consegue mover a URL longa até o navegador.

### 5.1 Evidência antes de propor (curl no endpoint de consentimento)

- Servidor **sem navegador** (`loginctl`: só sessões tty/ssh) — a
  autorização precisa do navegador dele e o código precisa voltar por
  arquivo.
- **Desktop client aceita só loopback**: redirect não-loopback
  (`https://nicky-server…/site/oauth_cb.html`) → `redirect_uri_mismatch`;
  `postmessage` → `invalid_client (no registered origin)`;
  `urn:ietf:wg:oauth:2.0:oob` → removido pelo Google.
- `http://localhost:8766/` é aceito (302 → sign-in) — porta escolhida.

### 5.2 O que foi construído

1. `config/google_credentials.json` (novo, 0600 — cópia do JSON baixado
   em 01/10) com `redirect_uri http://localhost:8766/` (o `models.py` lê
   `redirect_uri` antes de `redirect_uris`).
2. **`tools/google_oauth_helper.py`** (roda no PC do dono): sobe
   `127.0.0.1:8766`, abre a URL de consentimento, captura `?code=`, grava
   `google_auth_url.txt` e envia ao servidor por SSH
   (`alex@192.168.0.250:OmegaDrakon/data/google_auth_url.txt`); flags
   `--no-open/--no-ssh/--dry-run`; recusa porta ocupada. **Bug pego no
   1º teste manual:** `NameError: 'corro'` (typo de `corpo`) na resposta
   HTTP — corrigido e coberto por teste.
3. **`site/google_auth.html`** (público): botão ▶ Autorizar com a URL
   idêntica à do CLI + Rota A (helper) e Rota B (túnel SSH).
4. `docs/GOOGLE.md` §4 reescrito (3 rotas) + troubleshooting ampliado.
5. `tests/test_google_oauth_helper.py` — **9 testes** (URL = redirect do
   config, 3 escopos, sem `client_secret`, captura→arquivo, página 200,
   `access_denied` → rc 1, porta ocupada → 1, SSH falha com mensagem).

### 5.3 Validação

- **Suíte completa: 2238 passed, 16 skipped** (86s) · gate de cobertura
  **90,20% ≥ 90%** (helper 86%).
- A suíte pegou uma **dependência de estado do repo**:
  `test_main_sem_flags_usa_defaults` assumia `config/google_credentials.json`
  inexistente → teste tornado hermético (arquivo fantasma em `tmp_path`).
- Página servida: `GET /site/google_auth.html` → **200** local **e** pela
  URL pública do Funnel; `redirect_uri` da página == o do CLI.
- **Sem bump**: ferramenta do dono + página estática + docs/testes — o
  od-core nem foi reiniciado.

**Estado: PRONTO, aguardando o dono escolher a rota (A: helper / B:
túnel).** Depois que o código chegar: `--code` → `--check` → restart →
prova viva → bump MINOR 1.18.0.

## 6. OAuth concluído + regra do txt.txt (~10:45–11:1x)

Pedido: **"estou no tunel"** (Rota B) e, em seguida, **"codigo chegou"**.

- **Túnel do lado errado:** o dono rodou `ssh -L 8766:127.0.0.1:8766`
  **dentro** da sessão SSH do servidor (processo `ssh` em nicky-server,
  cwd OmegaDrakon, stdin pts/4) — loop servidor→servidor; encerrado.
- **1º capturador morreu** (não sobreviveu ao shell da ferramenta) → o
  túnel do dono levou `canal … refused`; recriado com `setsid -f`
  (pid 184140, 30 min, log `data/google_oauth_helper.log`) — desta vez
  sobreviveu (verificado em duas chamadas separadas).
- **Código 11:03** → `runtime.google_auth --code` → token em
  `data/google_token.json` (0600, **refresh sim**, 3 escopos readonly) ·
  `--check` rc=0.
- **Restart 11:04:28** (PID 184438, NRestarts=0): log `Actions google_*
  ligadas ao Google Workspace | autorizado=True`; `/capabilities`
  **65 → 71 actions** (google: 6, batem com o código).
- **Prova viva parcial:** `route=action_intent` → `alex`, porém
  **Gmail/Calendar/Drive API desativadas** no projeto `582855984584` →
  resposta honesta `⚠️ Google indisponível agora` (sem alucinação).
  `/health` up · `/supervision` restarts 0 · journal **0 erros**.
- **Pedido do dono: "o copiar e colar não funciona aqui — trocamos
  informações pelo txt.txt"** → vira **regra 14** do `iniciar/RULES.md`
  (entregar URLs/textos longos pelo `txt.txt`; preferir páginas com
  botões em `site/`).
- **Entregas:** `site/google_apis.html` (NOVO, público — 3 botões ENABLE
  → Console; 200 local e pelo Funnel) · `txt.txt` com seção "PARA VOCÊ"
  (3 links + página + instrução "APIs ligadas"; desejos de escrita do
  dono preservados).

**Estado: BLOQUEADO numa ação do dono** — habilitar as 3 APIs no
Console → "APIs ligadas" → prova viva completa → bump MINOR 1.18.0.

## 7. APIs ligadas, prova viva 3/3 e CI verde (~11:2x–12:2x)

Pedido: **"APIs Ligadas"** (e, antes, a escolha via ask_user: reiniciar +
investigar o CI agora).

### 7.1 Prova viva do Google — COMPLETA

- **3/3 no ar:** e-mails (10, com assunto/remetente reais), agenda
  ("Nenhum compromisso nos próximos 7 dia(s)" — consulta real), Drive
  (20 arquivos reais). `/capabilities` 71 actions · journal 0 erros.
- **Bug achado pela prova:** todos os e-mails "(sem assunto)" →
  `urlencode(clean)` **sem `doseq`** em `GoogleClient.request`: a lista
  `metadataHeaders` virava repr de Python na URL e o Gmail respondia sem
  cabeçalhos. Corrigido nos dois métodos + teste (mutação detectada);
  reinício autorizado (PID 187621) → chat com assunto e remetente.
  **Lição:** durante a mutação usei `git checkout` e apaguei a própria
  correção (não commitada) — reaplicada; repetir o erro já registrado
  (backup em /tmp ANTES das mutações).
- Restaram **2 desejos de ESCRITA** do dono no txt.txt (2º lote, gate de
  papel + confirmação — ainda não implementado).

### 7.2 CI vermelho desde 15/09 — investigado e FECHADO

- E-mails do Gmail expuseram `Run failed: CI - master` nos últimos 5
  commits. API pública: **177 runs vermelhos seguidos** (último verde
  `5668b27`, 15/09 13:46; o "CI verde" do 02/10 era local, nunca do
  GitHub). Logs exigem login (sem token; push é SSH).
- **Sem log, gerei diagnóstico:** `ci.yml` ganhou anotações `::error::`
  (públicas na página do job) com cada teste falhado.
- **5 falhas = testes dependentes do HOST** (runner não tem o hardware):
  sysfs térmico (route caía no llm), whisper-cli, piper, `/opt/omegadrakon`
  + gate de cobertura 89,96%. Reproduzido em venv nova + checkout limpo
  (o websockets 17.1 já tinha sido pegue antes: mensagem do handshake
  mudou → `_espera_registro` com trechos alternativos).
- **Correções (433458e):** `cpu_temp` lê `THERMAL_DIR`/`HWMON_DIR`
  (constantes) com sysfs de fixture + teste de degradação sem sensor;
  gates de voz com STT/Piper dublê; flag `--espeak_data` com diretório
  fixture; 2 canários reais com `skipif` honesto (cobertura única deles
  **medida** antes: 90,19% sem eles — nada se perde).
- **Resultado: CI VERDE `433458e`** — suíte local 2240 passed, 17
  skipped, cobertura 90,15% em simulação CI-exata (env -i + venv nova).

**Estado: Google PROVADO no ar · CI VERDE · falta só o bump MINOR 1.18.0**
(checklist + APK + restart).

---

Interface Viva: Nicky Virthy · Arquiteto: Alex Projeti
Assinatura: `OD // CORE`
