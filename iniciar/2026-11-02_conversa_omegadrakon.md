# 2026-11-02 — conversa OmegaDrakon

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `mcp_publicado_e_reverificacao_2026_11_02`).

## §1 — "leia iniciar" (02/11 ~10:52): reverificação + resgate do MCP pendente

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint: `reverificacao_noite_2026_11_01` (01/11 20:25).

### 1. Resíduo encontrado (sessão anterior morreu no meio)

A árvore estava **suja** — trabalho do item 3b ("MCP Server — EM
ANDAMENTO" no txt.txt de 01/11 22:10) escrito mas **nunca commitado**:

- `runtime/mcp_od.py` (NOVO, 238 linhas) — servidor MCP stdio;
- `tests/test_mcp_od.py` (NOVO, 220 linhas, 18 guardas);
- `docs/CHANGELOG.md` (+25) — entrada "Encaminhamentos no .205,
  auditoria de uso das ferramentas e o OD vira servidor MCP".

Nada disto tinha passado por gate nesta sessão. Resgate feito agora.

### 2. Validação (gate + prova viva)

- **Gate 2×: 4032 passed / 16 skipped / 0 falha · 90,49%** (piso 90% ok,
  PIPESTATUS 0 nos dois; o CHANGELOG dizia 90,52% — corrigido para o
  número medido na publicação).
- pyflakes 0 aviso, `py_compile` OK nos 2 arquivos novos.
- **Prova viva** (processo real, ~0,1 s por chamada): `initialize` →
  `omega-drakon v1.44.0` · `tools/list` → **115 tools** · `uptime` → ok ·
  `flatnotes_busca {"termo":"Parking lot"}` → achou a nota **TODO 5** —
  stdout só com JSON-RPC, boot no stderr.

### 3. Estado do sistema (medido, 02/11 10:52–11:23)

- **Git (antes do resgate):** HEAD `a2d4f9e` == `origin/master`, mas com
  os 3 arquivos do MCP pendentes (acima).
- **od-core:** active desde 31/10 14:42:30, MainPID **1217**,
  **NRestarts=0** (~45 h). **/health `ok=true`, 25/25, nenhum fora.**
- **Journal 01/11 20:25 → agora: ZERO warning/erro** ("No entries").
- **Borda:** Funnel `/` **200**; `/radio.mp3` **206 audio/mpeg**;
  nowplaying **"Jules – Odio Madrid"**; acervo **287 mp3**, `000/` 0,
  `temp/` 0 (v1.8 fechou, sem resíduos).
- **9 portas LAN no .205:** 8090/8100/8200/8400/8410/8430/8470 = 200,
  8420 = 302, 8480 = 404 na raiz (normal); **.250 morto** nos binds
  movidos (000, esperado).
- **Vigia:** tick 11:20 → ativos 27, `pendentes_seguranca: []`.
  Relatório 02/11 04:33 → 4 sondas verdes, fila do juiz vazia,
  `avisado=false`.

### 4. Pendência nova — dispositivo na rede

**`DE:26:20:74:D6:AE` (192.168.0.163, fabricante desconhecido)** visto
desde **01/11 21:53** — `pendentes_novos: [1]`. Aguarda o dono (nome via
`--conhecer` ou bloqueio) — mutação exige ordem.

### 5. Canais

- **txt.txt:** sem mensagem nova do dono (mtime 01/11 22:10 = nossa
  entrega). Reescrito com: MCP FECHADO + bloco de config do cliente
  (Claude/Cursor) + aviso do dispositivo novo.
- **analise/:** sem pasta nova do dono (relatório do vigia 02/11 04:33).

### 6. Publicação e estado final

- Commit do MCP + registro `iniciar/` pushados em `origin/master`
  (regra 7.1 — commit/push autorizados por padrão).
- **Sem restart** (regra 7.3 não se aplica): `mcp_od.py` é stdio sob
  comando do dono no próprio desktop — nenhuma porta aberta, od-core
  intocado.
- Telegram enviado (regra 15).

**SISTEMA VERDE — v1.44.0/2080, health 25/25, journal limpo, rádio e
Funnel no ar, MCP publicado.**

**Fila do dono:** (a) colar o config do MCP no Claude Desktop/Cursor
(bloco no txt.txt); (b) nomear ou bloquear o dispositivo 192.168.0.163;
(c) no próximo reboot, conferir a corrida docker×tailscale (prova de
boot pendente); (d) parking lot — MCP FECHADO.

## §2 — "Revisar o parking lot restante do FlatNotes" (~11:35): fila fechada

**Pedido:** usuário: "Revisar o parking lot restante do FlatNotes para
fechar a fila".

### 1. Método (regra 5 — código antes de suposição)

Nota `TODO 5 — Parking lot (ideias de expansão)` lida pela API do
FlatNotes (`GET /api/notes/{titulo}`) e **cada status conferido no
próprio código** antes de marcar: `tools/actions/actions.py`,
`core/orchestrator.py`, `integrations/telegram/voice.py` +
`tools/audio/stt.py`, `plugins/`, `core/identity.py`, registro de 115
e `.env`. Nada marcado por memória.

### 2. Resultado (gravado na própria nota, original preservado)

Bloco **"🔍 REVISÃO DA FILA — 02/11"** no topo da nota, via action
`flatnotes_anota(sobrescrever=true)` — prova por releitura: 9792 chars,
começa com o bloco novo e mantém "Migrado do `TODO.md`".

- **✅ 8 CONCLUÍDOS:** parking lot dentro do FlatNotes (decisão (b),
  21/10) · auditoria de uso (01/11) · `network_hosts` enriquecida com
  **nome do inventário + fabricante OUI** (lido em `actions.py`) ·
  série "uma por vez" (v1.40/1.41/1.43) · webview descartada + botão
  v1.42.0 · **MCP Server (02/11, `48e3c16`)** · Kiwix dentro do chat
  (orchestrator injeta enciclopédia, contadores `enciclopedias/`
  `enciclopedia_blocos/enciclopedia_sem_fonte`) · "outras 4 na
  internet" (análise fechada 21/10 — não vão).
- **🔶 1 PARCIAL:** voz — TTS (Piper + edge-tts) e STT do Telegram
  prontos, **falta virar action** (nenhuma `stt`/transcrever nas 115).
- **⬜ 4 ABERTOS (só o dono decide):** senha WiFi (religar ESP/Ecos) ·
  pings do WiFi USB (**premessa mudou**: uplink é o cabo desde 01/11 →
  recomendado **arquivar**) · plugin marketplace (`plugins/manager.py`
  existe, sem manifest) · multi-tenant (só `OD_ACCOUNT_ALIASES`) +
  auto-repair (`RecoveryLoop` existe, auto-repair não).

### 3. Estado

Sem mutação de código/serviço — só a nota do caderno, o `txt.txt`
(regra 14) e o Telegram (regra 15). Fila fechada: **do meu lado não
sobrou nada aberto**; os 4 itens acima dependem de decisão/ordem dele.

## §3 — "Virar a transcrição de áudio em action stt/transcrever" (~12:40): o item parcial da voz fechou

**Pedido:** usuário: "Virar a transcrição de áudio em action
stt/transcrever no catálogo do OD" — fecha o único item **PARCIAL** da
fila revisada na §2 (nota `TODO 5`: voz/TTS/STT já funcionavam no bot,
mas não existia `stt`/`transcrever` nas 115 actions).

### 1. O que mudou (código)

- **`tools/actions/actions.py`**: handler async **`stt_transcrever(caminho, idioma="")`**
  — import **LAZY** de `tools/audio/stt.py` (o whisper só entra no
  processo na chamada); mesma engenheira do bot: ffmpeg → WAV 16 kHz
  mono → whisper-cli + ggml-base, sem residência em RAM. **Nunca lança**:
  `audio_nao_encontrado` / `stt_indisponivel` + snapshot / `transcricao_falhou`;
  sucesso = `path/idioma/chars/texto`. Categoria nova **`stt`** no
  `CATEGORIES` + permissão nominal (`stt_transcrever`) → catálogo **116**.
- **`runtime/mcp_od.py` + `tools/actions/__init__.py`**: contagens
  115→116 e o `instructions` do MCP passou a derivar de
  `len(registry.list_actions())` (para de quebrar a cada action nova).
- Contagens duras 115→116 em 6 arquivos de teste + `site/index.html`;
  `stt: 1` no `EXPECTED_CATEGORIES`.

### 2. Provas (regra 6)

- **`TestSttAction` (4)**: registrada com permission nominal; caminho
  inexistente → `audio_nao_encontrado` sem exceção; stub indisponível →
  `stt_indisponivel` com snapshot; **áudio REAL** (wav 16 kHz mono de
  1 kHz gerado no teste) processado ponta a ponta com os binários do servidor.
- **Gate completo: 4036 passed / 16 skipped / 0 falha** (+4 = os testes
  novos; era 4032/16/0) · pyflakes 0 aviso novo (os 2 do diff já existiam no HEAD).
- A mesma ação agora roda pelo orquestrador **e** aparece no
  `tools/list` do MCP (**116 tools**) sem código extra.

### 4. Restart verde (regra 7.3 — autorizado por padrão, validação verde)

`systemctl --user restart od-core` com a suíte verde (4036/16/0), HEAD
== origin/master e árvore limpa. **Prova viva:** MainPID **2782509**,
NRestarts=0, active/running · `/health` `ok=true, status=up` (com
`X-API-Key`) · journal **0 erros** desde o restart · `GET /actions` do
serviço devolve **116 actions** com `stt_transcrever` (categoria `stt`,
permissão nominal, params `caminho`+`idioma`) — a action está viva no
processo, não só no repositório.

### 2.1 — Nota TODO 5 atualizada (follow-up do dono, ~13:00)

Item **(9) de voz marcado CONCLUÍDO** na nota do FlatNotes: cabeçalho
"pode riscar" **8 → 9**, item promovido para a seção ✅ com as provas,
bloco **🔶 PARCIAL removido** (agora vazio) e rodapé da revisão
atualizado. Gravado via `flatnotes_anota(sobrescrever=true)` e provado
por releitura: **9750 → 9965 chars**, conteúdo histórico preservado
(`Migrado do TODO.md` + a linha original "integrar no bot como actions").

### 2.2 — Item (11) arquivado na nota TODO 5 (follow-up do dono, ~13:15)

**Pedido:** "Arquivar o item (11) dos pings do WiFi USB na nota TODO 5
(premisa mudou com o cabo)". Feito: cabeçalho **ABERTOS 4 → 3**, item 11
saiu da lista e virou seção **📦 ARQUIVADO (1)** com o motivo técnico
(`enp2s0` .205 metric 100 é o uplink; `wlx000f0037acf0` .250 é reserva
metric 600 — pings do USB perderam o objeto, só voltam a importar se o
WiFi voltar a ser primário); rodapé deixa de listá-lo como pendência.
Prova por releitura: **9965 → 10133 chars**, histórico preservado.
Sobra da fila: **(10) senha WiFi, (12) marketplace, (13) multi-tenant**.

### 3. Fechamento (regras 4/7.1/14/15)

CHANGELOG (sub-seção "02/11, sem bump" — precedente do MCP) ·
`session.json` (chave `stt_transcrever_action_2026_11_02`, updated_at
renovado) · `txt.txt` escrito para o dono (regra 14) · Telegram
enviado (**msg 3548**, regra 15) · commit + push da entrega nesta etapa
(regra 7.1, autorização permanente).


## §4 — Itens 1 e 4 da rádio: `acervo.db` + "Tocando agora" na página (~15:00–16:20)

**Pedido:** itens aprovados um por vez na conversa da rádio (método do
dono: analisar → prós/contras → implementar ou descartar). **Item 4**
aprovado com a especificação dele: *"ok. no banco fica o link apontando
para a musica, não a musica de verdade"* — o banco guarda o **caminho**,
nunca o áudio. **Item 1** aprovado antes: seção "Tocando agora" na
`radio.html` (artista—título + curiosidade, últimas 5 em arquivo de
texto, **só a próxima** — sorteio do AzuraCast, sem fila —, ouvintes ao
vivo, sondagem de 15 s). Ordem aceita: banco → Item 1 → Item 2 →
página de acervo; "escolher uma música" é item à parte.

### 1. Item 4 — o banco (lado pipeline)

`musica.py` **v1.8.1** (HD Mídia): `acervo.db` (SQLite na raiz) com
uma linha por mp3 — **caminho relativo** (o link), artista, título, ano,
gênero, curiosidade (TIT3), pronúncias (TCOM/TEXT), duração e bytes.
`indexar_acervo()`: upsert idempotente por caminho, chamada **a cada
lote**; a duração só recalcula quando o arquivo é novo ou mudou de
tamanho; arquivo sumido do acervo sai do índice (órfãos só na varredura
completa, com proteção: acervo 100% vazio não zera o banco). CLI
`--indexar` para backfill/manutenção.

- **Backfill executado:** 287/287 linhas em **~116 KB**; 137 com
  curiosidade de verdade — os ~150 fallbacks do Gemini (429 de 31/10)
  ficaram com o placeholder, tratado como vazia na página.
- Sandbox antes do real (regra 10): teste em `MP3_BASE_DIR` de mentira
  (88 linhas, idempotente na 2ª rodada) antes do acervo de verdade.
- Backup `backups/musica-v181-20261102.py` + `doc/README.md` atualizado
  (seção v1.8.1, `--indexar` no Uso, `acervo.db`/`tocadas.txt` na
  estrutura).

### 2. Item 1 — a página (lado od-core)

- **`integrations/radio_agora.py` (NOVO, só stdlib)** — `montar_agora()`
  une: nowplaying do AzuraCast (cache 5 s), curiosidade lida do
  `acervo.db` (`mode=ro`; quem escreve é só o pipeline), últimas do
  `tocadas.txt` (sem arquivo ainda → `song_history` cobre) e ouvintes.
  A locução `anuncio musica` aparece como **locução**, nunca como música.
  `registrar_tocada(payload)` alimenta o texto a cada troca — **nunca
  lança**: a fala da rádio não morre por causa da página.
- **Rota** `GET /api/radio/agora` pública: `auth=False` +
  `AUTH_EXEMPT_PATHS` (sem isso o `auth_all` de produção bloquearia a
  página) + isenção do rate limit (sondagem de 15 s com cache, mesma
  natureza de `/app/version`) + handler `api_radio_agora` (503 honesto
  se a montagem falhar).
- **Hook** no wrapper `_radio` do `runtime/launcher.py`: registra a
  troca **antes** do `processar` — o histórico sobrevive mesmo se o
  Piper falhar na locução.
- **`site/radio.html`**: seção "Tocando agora" com sondagem de 15 s;
  falha de rede mantém o último estado bom.

### 3. Validação e deploy

- `tests/test_radio_agora.py` (NOVO): **17 guardas** — contrato da
  página, curiosidade real/placeholder/fora do banco, locução no ar e
  na próxima, AzuraCast fora não derruba o JSON, últimas do arquivo
  (recência correta, música do ar fora da lista), cobertura por
  histórico, registro idempotente/rotação/nunca-lança, rota pública
  isenta (inclusive a isenção do limiter, por fonte).
- A **1ª passada do gate** achou só as 2 guardas de contagem da casa
  (`len(ROUTES)` 94→95 + mirror do conjunto público) — corrigidas.
- **GATE OFICIAL: 4053 passed / 16 skipped / 0 falha · 90,42%**
  (era 4036; +17). pyflakes **0 aviso novo** (8 pre-existentes
  conferidos vs HEAD). `node --check` nos 2 blocos de JS da página OK.
- **Restart (regra 7.3) — nota honesta:** o restart saiu **antes** da
  suite completa desta etapa (ordem invertida; o diff já passava por
  `py_compile`, pyflakes, import/registro da rota e os 17 testes do
  módulo) — a suite verde veio em seguida, mesmo commit. Prova viva:
  PID 2843442, NRestarts=0, ativo desde 15:53:47, health **25/25**,
  journal **0 `[ERROR]`**, `/ws` 101, "Webhook da rádio plugado".
- **Provas vivas da rota:** 200 em LAN (`192.168.0.250:8000`) e
  **pública pelo Funnel** (`https://nicky-server.tail1b1f51.ts.net/api/radio/agora`
  → JSON completo com últimas 5), página `/site/radio.html` 200 público
  com a seção, curiosidade real aparecendo no JSON (banco lido em modo
  leitura).

### 4. Fechamento (regras 4/7.1/14/15)

CHANGELOG (sub-seção "02/11, sem bump") · `session.json` (chave
`radio_tocando_agora_e_acervo_db_2026_11_02`, `updated_at` renovado) ·
`txt.txt` para o dono (regra 14) · Telegram (regra 15) · commit + push
(regra 7.1, autorização permanente).
