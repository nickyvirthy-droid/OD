# Conversa OmegaDrakon — 2026-10-07

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar"**. Ambiente canônico: `.venv/bin/python` SEM
`OD_TEST_POSTGRES_DSN`.

## 1. Retomada — bump 1.19.0 encontrado pela metade

- Herdado da sessão de 03/10: código da escrita Google + site já
  commitados (`df20177`, `ced23cc`), porém:
  - **4 arquivos do bump sem commit** (pubspec, capabilities, server.py,
    CHANGELOG);
  - **od-core no ar ainda em 1.18.0** (PID 206597, desde 03/10 12:48 —
    `/app/version` {1.18.0, 2038, sha `d9dd74a3…`});
  - **`docs/README_VERSAO.md` sem a seção §1.19.0** (lacuna do checklist).
- APKs em `site/` já eram 1.19.0+2039 (aapt2 conferido) e `.env`
  `OD_VERSION=1.19.0`.

## 2. Achado: registro desonesto do escopo do token

- O CHANGELOG afirmava *"token com os 7 escopos"* — **falso**:
  - o **log do capturador** (`data/google_oauth_helper.log`, 03/10 13:38)
    prova que o callback veio com os **7 escopos**
    (gmail.send/gmail.modify/drive/calendar.events + os 3 readonly);
  - mas a **troca código→token não foi concluída**:
    `data/google_token.json` (mtime 06/10 05:08) carrega só os
    **3 readonly**; refresh OK (access expirou 06/10 e renova);
  - journal de 13:44 registra **syntax error em `drive.py`** na mesma
    rodada (SelfRepair `no_fix`) — a sessão de 03/10 morreu no meio da
    integração da escrita.
- **Correção do registro** (honestidade antes de tudo): CHANGELOG e
  README_VERSAO agora dizem a verdade — código veio com 7 escopos, token
  NÃO trocado, escrita degrada `ok=False` até a re-autorização.

## 3. Trabalho executado

1. `docs/README_VERSAO.md` — seção **§1.19.0** criada no formato da casa.
2. `docs/CHANGELOG.md` + README_VERSAO — parágrafo do escopo reescrito.
3. Guardas: `tests/test_version_policy.py` **9/9**.
4. Suíte completa: **2297 passed, 16 skipped** (77,9 s) — igual à
   evidência registrada.
5. Commit **`a7c3e1d`** + push (`origin/master`) — árvore limpa.

## 4. Deploy (autorizado via ask_user — "Reiniciar agora")

- `systemctl --user restart od-core` 13:21:22 → **PID 669019**, NRestarts=0.
- **Prova viva:** `/app/version` {1.19.0, 2039, sha256 `d9dd74a3…` ==
  `site/OmegaDrakon.apk`} · `/health` up (9 checks) · `/supervision`
  restarts 0 · journal **0** Traceback/ERROR/CRIT.
- **78 actions registradas** (journal "Action registered", únicas):
  **13 google** — 6 leitura + **7 escrita** (calendar_create/delete,
  drive_create/update/delete, gmail_send/delete).
- Escrita segue dormente na prática: token com 3 readonly → as 7
  actions de escrita degradam `ok=False` honestamente.

## 5. Estado e pendências

- **v1.19.0+2039 NO AR** (PID 669019) — bump, registro e deploy fechados.
- **Pendência do dono:** re-autorização do Google com os escopos de
  escrita (3 passos de 03/10: túnel `8766` + `/site/google_auth.html` +
  "codigo chegou"), para a troca código→token com os 7 escopos.

---
OD // CORE

## 6. Escrita no Google NO AR — re-autorização + 2 bugs da prova viva + v1.19.1

- **Autorização:** dono 'quero fazer agora' → capturador (8766, setsid -f)
  → túnel + clique → 'codigo chegou' → callback com os **7 escopos** →
  token trocado (refresh sim; backup do readonly em backups/, não
  commitado). Achar: capturador salva o callback na RAIZ
  (`google_auth_url.txt`), não em `data/` — lido do log do helper.
- **Bugs pegos pela 1ª prova viva (antes de tocar a agenda real):**
  1. 'com o título X' não virava título → marcador explícito vence
     (`_GOOGLE_W_TITULO_RE`, título depois do marcador, 'quando' antes);
  2. confirmação com UTC cru ('18:00' p/ 'às 15h') → `_quando_legivel()`
     converte ao fuso local na confirmação E no sucesso; dia inteiro
     intacto (regressão do 1º patch pega na mesma rodada).
- **v1.19.1 (PATCH):** 6 fontes de versão + APKs (aapt2 2040/1.19.1) +
  CHANGELOG/README §1.19.1. Suíte **2299 passed, 16 skipped** (+2
  regressões); guardas 9/9.
- **Prova viva FINAL (agenda real):** criar 2 compromissos (15h/16h, fuso
  certo, confirmação 2 passos) → leitura mostrou os 2 → apagar os 2 →
  'Nenhum compromisso nos próximos 7 dia(s)'. Journal 0 erros.
- **Estado: SISTEMA 100%** — escrita no Google viva de ponta a ponta.

---

OD // CORE

## 7. Retomada 23:12 — "leia iniciar" · verificação em VERDE

- **Git:** HEAD `b367701` == `origin/master`, árvore limpa.
- **Serviço:** od-core ativo desde 14:19:52, PID 677660, **NRestarts=0**.
- **Prova viva:** `/app/version` {1.19.1, 2040, sha256 `4c6a9723…` ==
  `site/OmegaDrakon.apk`} · `/health` up (orchestrator/llm ok) ·
  `/supervision` restarts 0, `degraded: []`.
- **Journal** desde o restart: 191 linhas, **0** Traceback/ERROR/CRIT
  (2× `[NICKY][WARN] Transporte indisponível` — WARN, auto-recuperado).
- **Canal do dono:** `txt.txt` e `pedido.txt` vazios (sem recado).
- **Estado:** nada pendente de deploy nem do dono — aguardando pedido.

## 8. Análise das conversas DO SISTEMA — inconsistências encontradas (23:xx)

Pedido: "leia as conversas do chat e encontre inconsistências" (as
conversas do sistema, não as transcrições de `iniciar/`).

**Amostra:** `conversation_messages` = **230 mensagens / 115 turnos**,
29/09 14:00 → 07/10 15:06, users `alex`+`teste`, 7 perfis
(guardian, regulus, luma, vox, athenae, nyx, nexus) + `llm_cache`
(71 entradas). Análise anterior registrada em
`session.json:analise_coerencia_2026_09_30` cobria 15 turnos (até
30/09 07:53) — os achados D1/D2/D3 dela **seguem valendo**; o que vem
abaixo é o que ela NÃO alcançou (30/09 21:14 em diante) + metadados.

### 8.1 Contradições diretas no mesmo assunto

| # | Turnos | Contradição |
|---|--------|-------------|
| C1 | [494] 30/09 "OpenAI GPT-4" · [498] 30/09 "gemma" · [592]/[594] 01/10 "Qwen / qwen2.5-coder-3b" | 4 identidades para a mesma pergunta, todas gravadas com `llm_used=gemma-local`. D2 do 30/09 é só 2 das 4. |
| C2 | [490] "agenda não está disponível" → [492] **inventa 3 tarefas** → [500] "não tenho capacidade de gerenciar agendas" → [666] 06/10 consulta real da Agenda → **[694] 07/10 "🚫 Não é possível criar novas agendamentos"** | A recusa vem **45 min depois** de [672]/[674] criarem 2 compromissos reais no mesmo dia. E a recusa está **no `llm_cache`** (`use_count=1`) — será reentregue sem chamar o LLM. Causa raiz da recusa: `core/intents.py:_GOOGLE_W_CRIAR_RE` não tem "marque/agende/coloque" → a intenção não casa e o turno cai no cache/LLM. |
| C3 | [622] 02/10 12:38 "Sim, eu tenho acesso ao seu Google Drive" vs [632] 12:40 "não tenho acesso direto ao Google Drive" | 2 minutos de distância, respostas opostas — e as duas eram falsas: o commit da integração é `20b724d` 17:25 do mesmo dia. |
| C4 | [484] 29/09 "R$ 4,73" (sem fonte) · [516]/[518]/[520] 30/09 "US$ 5.20 **por real**" · [524] 30/09 20:40 AwesomeAPI "R$ 5,184" | 3 valores incompatíveis em 2 dias e a formulação 5.20 **inverte** dólar↔real. (O 4,73 é o D3 já registrado.) |
| C5 | [672] confirma "…em 2026-10-08 **15:00**" → [674] sucesso "criado … em 2026-10-08 **18:00**" → [680] leitura "08/10 **15:00**" | A mensagem de SUCESSO contradiz a própria confirmação e a leitura real (bug de fuso do lote 07/10; [678] 16:00 já saiu certo). |
| C6 | [665] 06/10 dono: "quando pergunto isso você deve olhar minha agenda" → [666] cumpre → [692] 07/10 "O que tem pra hoje" responde pelo LLM | A instrução do dono não persistiu; e a resposta usa prefixo "🌐 Atualizado:" de fastpath com `llm_used=gemma-local`. |

### 8.2 Resposta imitando ferramenta (critério 5 do protocolo §14 — que em 30/09 foi registrado como "ZERO")

| Turno | Conteúdo | Evidência contrária |
|-------|----------|---------------------|
| [618] 02/10 | "Fase da Lua … **Fonte: Open-Meteo — leitura real de agora**", `llm_used=gemma-local` | Não existe action de fase da Lua: `grep -ri 'moon\|phase\|fase da lua' tools/ core/ integrations/` = **0**. Formato de fastpath + fonte inventada; **está no `llm_cache`**. |
| [660] 05/10 | "10 Mbps. Estado verificado.", `gemma-local` | Nenhuma action de velocidade (`grep -ri 'speedtest\|mbps\|velocidade da internet'` = **0** no código). |
| [664] 06/10 | "temperatura da CPU … **na porta 5000** do serviço web" | Nada escuta na 5000 (`ss -lntp`: 8000/8001/8081/8123/5432) e `grep '5000'` no código = **0**. |

### 8.3 Conteúdo fabricado / pergunta não respondida

- **Xintoísmo:** [570] pergunta "quem fundou o xintoísmo" → respondeu
  sobre o **cristianismo**; [572] fabrica o fundador "Chūkyō / Ippon
  Kyo, 1869" e fecha com "hoje o **cristianismo** é praticado por
  quase todos os japoneses".
- **Lua (01/10 14:13, 4 perfis):** [576] "Lua é uma enorme pedra",
  "maior que a Marta", "satélite Luna Menina", "300°C de dia";
  [578] "rocha volátil e argila"; [580] "segundo maior **planeta**"
  + caractere chinês "**卫星**" numa resposta em pt-BR; [582] "58% da
  massa terrestre … revolução de 12 dias". Nenhuma bate com a outra.
- **[616] 02/10** "vai chover em Teodoro Sampaio" → devolveu o clima
  ATUAL (sem previsão).
- **[658] 05/10** "O estado verificado." — frase incompleta.
- **[539] 30/09 21:14** "bom dia" → "Bom dia!" (7 perfis iguais).

### 8.4 Metadados que mentem (auditoria não confiável)

1. **`llm_cache.profile` 100% errado:** 71/71 linhas gravadas como
   `guardian`, inclusive prompts de outros perfis — ex.:
   `qual a velocidade da internet` foi perguntado pelo **nexus**
   (05/10 16:16, msg [659]) e está gravado `profile='guardian'`.
   Causa: `runtime/launcher.py:161` cria o cache com
   `profile=OD_PROFILE` e `memory/cache.py:set()` grava
   `profile=self._profile`, ignorando o `profile=` que o orquestrador
   passa (`core/orchestrator.py:1642`). A **chave está certa**
   (`make_key` recebe o param: 7 chaves distintas para "bom dia", uma
   por perfil) — quem erra é a coluna.
2. **Execução real de luz gravada como `fastpath:math`** — [508]/[512]
   30/09 ("sim" → ✅ executado). `core/orchestrator.py:767` inicializa
   `route_detail = "math"` e o ramo de confirmação de luz (≈823-831)
   executa **sem** reatribuir; o caminho síncrono (1188) e o do Google
   (843) atribuem `ha_device_control`/`gw_action`. Os dois caminhos do
   mesmo arquivo discordam entre si.
3. **Contador ≠ lista:** [644]/[650] "📁 **20** arquivo(s)" com **15**
   itens listados — `core/intents.py:1310` usa `len(files)` no título
   e corta em `files[:15]` sem avisar. Mesmo padrão do Gmail (`[:10]`).
4. **Mesma action, respostas diferentes em 11 min:** [640] 03/10 11:30
   "10 mensagem(ns)" — 10× "(sem assunto)" vs [646] 11:41 com
   assunto e remetente.

### 8.5 Cache herdado da pré-zerada

- A zerada de 29/09 (§14 do dia 29) apagou só o histórico
  ("`llm_cache` INTACTOS" ficou registrado como decisão). Consequência:
  em **30/09 21:14** os 7 perfis devolveram a saudação gravada em
  **27/09 12:49** (7 chaves, uma por perfil, todas rotuladas guardian).
  O que parecia "personalidade" naquele turno era replay de 3 dias
  antes.
- Observação para não virar falso-positivo: `conversation_messages`
  começa no id 465 (ids 1-464 inexistentes) — **é** a zerada, não bug.

### 8.6 Inconsistência com o registro da sessão (CI)

- **CI vermelho não registrado:** [646] 03/10 11:41 e [652] 03/10
  16:41 mostram no chat "Run failed: CI - master (**ced23cc**)".
  API do GitHub confirma: run `37147058947` = **failure**, passo
  "Suíte completa + gate de cobertura ≥ 90%". A transcrição de 03/10
  fecha em "CI VERDE `433458e`" (12:49) e nunca mais cita CI — o verde
  foi quebrado 3h depois e ninguém registrou.
- **"100%" apressado:** a sessão de 07/10 declara "SISTEMA 100% /
  nenhuma pendência" às 14:2x, e o próprio chat registra [694] (devaneio
  de agenda, cacheado) às 15:06.

**Estado:** análise publicada — 6 contradições diretas, 3 imitações de
ferramenta com dado inventado, 4 problemas de metadado, 1 cache
herdado, 1 divergência de CI. Nenhum deploy envolvido (só registro).
