# 2026-10-29 — conversa OmegaDrakon

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `reverificacao_residuo_tts_2026_10_29`).

## §1 — "leia iniciar" (29/10 ~09:05): sistema verde, mas RESÍDUO derruba o gate

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint: `acervo_na_estacao_2026_10_28` (28/10 17:40, §4 — frente (a)
fechada e Funnel de volta).

### 1. Sistema — verde (evidência lida, não presumida)
- **Git:** árvore com **UM residuo** (`M tools/audio/tts.py`), HEAD
  `595c42e` (registro da §4, 28/10 18:12) **== origin/master**
  (`ls-remote` devolveu o mesmo sha).
- **od-core:** `active` desde **27/10 21:06:45**, MainPID **2081285**,
  **NRestarts=0**. `/health` autenticado (`OD_API_KEY`): **`ok=true`,
  25 checks, NENHUM fora**. `/app/version` → **1.44.0 / 2080** (sha
  `aeb8566b`).
- **Journal 24 h:** **0 entradas em `-p warning`** (nada de ERROR/WARN
  novo).
- **Funnel:** `# Funnel on` com os 3 handlers da 443 (`/` → 8000,
  `/ws` → 8001, `/radio.mp3` → 8600) e a 8443 tailnet intacta — segue de
  pé desde a queda de ontem (§4).
- **Rádio:** `GET /api/nowplaying/1` → estação Nicky, frontend icecast /
  backend liquidsoap, no ar.
- **Vigia da rede (tick 29/10 09:07):** 25 ativos, `rich: true`,
  **2 pendentes os MESMOS de 27/10** (aguardando ordem, regra 7):
  `26:14:7A:43:2E:11` @ 192.168.0.163 e `7A:25:D5:8C:03:EE` @
  192.168.0.233.
- **Vigia das mensagens (29/10 04:33, relatório lido):** 4 sondas
  **VERDES**, `avisado: true`, gate/commit/restart não precisaram rodar.
  Fila do juiz = 2 itens (ambos 28/10, "sem estratégia de reparo
  determinístico"): `quais os dispositivos conectados na rede`
  (inconsistente, 06:26) e `quem está no IP 192.168.0.233`
  (resposta_errada, 07:46) — este último é **o próprio pendente do
  Vigia**, o inventário não conhece o MAC.
- **Canais do dono:** `txt.txt` (mtime 28/10 18:11) = só as nossas
  entregas de 27–28/10, **nenhuma mensagem nova dele**. `analise/`:
  as pastas viraram **`Nicky Musicas/`** (28/10 08:16) e
  **`Nicky Radio/`** (28/10 10:16) — o antigo `Nicky Locutor/` **não
  existe mais** (item (c) da fila: o dono reorganizou a caixa de
  entrada ele mesmo) + relatórios do vigia.

### 2. RESÍDUO — sessão morta 28/10 20:22 em `tools/audio/tts.py`
- **Nada registrado** na §4 (regra 4 violada pela sessão que morreu):
  o `session.json` e a transcrição param às 18:12, o arquivo foi
  editado às **20:22** e não há commit dele.
- **O que ficou (+326/−4, `pyflakes` limpo, `py_compile` OK):**
  `EdgeTTSTTS` (edge-tts / vozes Microsoft Neural, incl. a cadeia de
  locução de rádio via ffmpeg), a classe unificada `TTS` com
  primário+fallback (`engine`: `piper` | `edge-tts` | `both`), campo
  `engine` no `TTSConfig` e 4 vozes `pt-BR` novas. Docstring aponta a
  origem: `analise/Nicky Locutor/nicky-locutor v0.0.0/` (o legado
  edge-tts), "migrado 28/10".
- **O que NÃO existe:** `edge_tts` **não está instalado** no `.venv`
  (`ModuleNotFoundError`) e não está em `requirements*.txt`; **nenhum
  caller** usa as classes novas (o `runtime/launcher.py` segue com
  `PiperTTS()` direto); **nenhum teste** novo; **nenhuma entrada no
  CHANGELOG`.
- **Smoke test feito aqui:** imports OK, `engine` default continua
  `piper`, `piper available=True`, locução Piper intacta, vozotes
  unificados listam 17 chaves. **Achado:** `EdgeTTSTTS.available`
  devolve `True` mesmo sem o pacote `edge_tts` instalado (só olha
  `config.enabled`) — introspecção enganosa; na síntese o `ImportError`
  é capturado e o fallback salva, mas `available`/`vozes` mentem.
- **GATE OFICIAL RODADO AQUI (evidência):**
  `.venv/bin/python -m pytest --cov --cov-config=.coveragerc
  --cov-fail-under=90 -q` → **3966 passed / 16 skipped / 0 falha ·
  89,94%** → **`FAIL Required test coverage of 90% not reached`**.
  Causa: `tools/audio/tts.py` caiu para **55%** (349 linhas, 157
  descobertas) com 326 linhas novas sem guarda. Os testes em si não
  quebraram (a classe `PiperTTS` segue coberta e verde).

### 3. Estado e decisão pendente
- **Sistema NO AR e saudável** (1.44.0/2080, health 25/25, Funnel e
  rádio no ar, journal limpo), **mas a árvore está com o gate
  VERMELHO (89,94%) por causa do resíduo** — não dá para commitar nem
  declarar verde enquanto ele estiver lá meio-feito.
- Duas saídas honestas, **aguardando ordem do dono (regra 7)**:
  **(A) terminar a frente edge-tts** — instalar `edge-tts` no `.venv` +
  `requirements.txt`, corrigir `available` (checar o import), escrever
  as guardas em `tests/test_audio.py`, CHANGELOG, gate ≥90,
  commit+push; **(B) reverter o resíduo** (`git checkout --
  tools/audio/tts.py`) — árvore limpa e gate volta a ~90,57%, sem
  perder nada versionado (o diff morre, mas nunca foi commitado).
- Nenhuma mutação feita nesta troca além deste registro (regra 7).

## §2 — "terminar a frente edge-tts" + "conhecer os dois" (29/10 ~09:30)

**Pedido (ask_user):** dono escolheu **(A) terminar a frente edge-tts** e
**conhecer os 2 dispositivos do Vigia** (nomes ainda não dados — pendência
aberta no fim desta seção).

### 1. Entrega
- **Dependência:** `edge-tts 7.3.1` instalado no `.venv` + item **7** no
  `requirements.txt` (comentário no estilo da casa: import tardio, fora do
  caminho crítico; puxa `aiohttp`/`yarl`, já presentes).
- **`tools/audio/tts.py` (2 defeitos do resíduo consertados na causa):**
  1. `_resolve_voice` fazia `profile.lower()` e comparava com as chaves
     **sensíveis a maiúsculas** de `EDGE_TTS_VOICES` → **nenhuma voz
     Microsoft era alguma vez escolhida** (sempre o default) e, mesmo
     casando, devolveria o nome minúsculo que a API da Microsoft recusa.
     Agora: comparação case-insensitiva devolvendo o **nome canônico**.
  2. `EdgeTTSTTS.available` devolvia `True` com o pacote **fora** do
     ambiente (só olhava `enabled`) → introspecção mentia (`vozes`,
     `snapshot`, locução prometiam o que a síntese não entregaria).
     Novo `edge_tts_instalado()` com `importlib.util.find_spec`, sem cache.
  3. Docstring apontava `analise/Nicky Locutor/…`, pasta que **não existe
     mais** (o dono renomeou para `Nicky Radio/`/`Nicky Musicas/` em 28/10)
     → texto corrigido; EOF com newline.
- **`tools/audio/__init__.py`:** exporta `EdgeTTSTTS` e `TTS` (+ docstring
  do pacote).
- **`tests/test_audio.py` 35 → 74 testes (+39):** fixtures `edge_falso`
  (módulo falso em `sys.modules`) e `edge_ausente` (`sys.modules=None` →
  `ImportError` de verdade); síntese/saída vazia/timeout/ausência do
  pacote; cadeia da locução linha a linha; **3 cascatas × 3 métodos**
  (primário entrega → só ele; primário falha → fallback entrega; sem
  fallback → ninguém é chamado); introspecção com/sem pacote; resolução
  de voz com caixa mista.
- **`docs/CHANGELOG.md`:** subseção 1.44.0 "Voz Microsoft Neural (edge-tts)
  como engine opcional do sintetizador (29/10, sem bump)" com a origem
  honesta (resíduo), os 2 defeitos e a prova viva.

### 2. Validação (gate 2x, antes e depois do CHANGELOG)
- **1ª rodada: 4005 passed / 16 skipped / 0 falha · 90,53%** (era 89,94%
  no resíduo; 3966 + 39 guardas novas).
- **2ª rodada (pós-CHANGELOG): 4005 passed / 16 skipped / 0 falha ·
  90,52%** — `PIPESTATUS[0]=0` nos dois.
- `pyflakes` 0 aviso (`tts.py`, `__init__.py`, `test_audio.py`),
  `py_compile` OK.
- **Commit `c234a2f` pushado** (5 arquivos, 873+/12−), HEAD == origin/master.

### 3. Prova viva (29/10 ~09:46, rede real)
- `EdgeTTSTTS.synthesize` → **26 640 bytes em 1,8 s**, voz
  `pt-BR-FranciscaNeural`, `file` = **MPEG ADTS layer III 48 kHz**;
- locução real (edge + ffmpeg da casa) → **187 289 bytes, ID3v2.4,
  128 kb/s · 44,1 kHz estéreo · 11,7 s**;
- `PiperTTS.synthesize_to_file` intacto → **WAV 73 888 bytes**;
- `TTS().snapshot()` → engine `piper`, **17 vozes**.

### 4. Deploy verde (regra 7.3) + canais (regras 14/15)
- `systemctl --user restart od-core` **29/10 10:02:23**: MainPID
  **171882**, **NRestarts=0**, `/health` **ok=true, 25 checks, 0 fora**,
  `/app/version` **1.44.0/2080**, journal desde o restart **0 [ERROR]**.
- `POST /tts` autenticado → **200**, JSON `ok:true` com **WAV** (`RIFF`)
  de 119 053 B base64 = a rota de voz do servidor vivo com o código novo.
- `txt.txt` reescrito no topo (regra 14) + **Telegram enviado**
  (`ok:true`, message_id 3477, chat 660518870 — regra 15).

### 5. Pendência fechada (29/10 ~10:15) — os 2 aparelhos do Vigia conhecidos
- O dono respondeu o ask_user: **os dois = "Smartphone"**.
- Executado: `OD_LOG_DIR=logs python3 tools/monitor/network_watchdog.py
  --conhecer 26:14:7A:43:2E:11 Smartphone` e o mesmo para
  `7A:25:D5:8C:03:EE` (só inventário local, sem mutação no roteador) +
  `--once` para reescrever a **linha de estado** (a sonda `_check_network`
  do notificador lê a última linha — sem o ciclo novo o alerta horário
  continuaria).
- **Prova:** `--report` → `Pendências: 0 dispositivo(s) novo(s), 0 evento(s)
  de segurança`, os dois MACs agora `[conhecido] nome=Smartphone`, última
  linha do log `10:15:53` com `pendentes_novos: []` e `ativos: 25`.
  Alerta `net:dispositivo-novo` deixa de ser emitido a partir do próximo
  tick (o `network-watchdog.timer` de 5 min).
- Nomes **iguais por escolha dele** (os dois "Smartphone", IP distingue);
  renomear a qualquer momento com `--conhecer MAC NOME`.

### 6. Fila restante
- Fila do juiz: 2 itens de 28/10 (`quais os dispositivos conectados na
  rede` — inconsistente; `quem está no IP 192.168.0.233` — resposta_errada,
  agora o IP já tem nome no inventário) — ambos "sem estratégia de reparo
  determinístico" por design.
- Parking lot §5: rota WiFi, auditoria de uso de ferramentas, MCP.
- Subir músicas pelo painel AzuraCast 8091 (entrega de 27–28/10).

## §4 — Nova regra: `192.168.0.250` livre para portas (29/10 ~10:30)

**Pedido:** dono: *"nova regra: o IP interno 192.168.0.250 é livre. todas as
portas podem ser abertas nele, como funciona apenas na rede interna e
equipamentos estranhos são bloqueados o acesso a navegação pode ser livre".*

- **Registrada como regra 18** em `iniciar/RULES.md` (alteração explícita,
  como o rodapé do arquivo exige): abrir porta escutando na LAN deste
  servidor passa a ser **operação de rotina** — a exigência de ordem
  explícita da regra 7 **não se aplica** a elas.
- **Motivo dele ficou escrito junto:** o serviço roda só na rede interna e
  os equipamentos estranhos já são bloqueados de navegar.
- **Fronteira registrada (a justificativa dele é "só na rede interna"):** o
  que terminar alcançável **fora da LAN** — Funnel 443 do Tailscale,
  `tailscale serve`/portas tailnet, DDNS, túnel, internet — **não** é
  coberto pela regra 18 e segue exigindo ordem explícita (regra 7).
  Porta nova = registrar aqui a porta + o serviço.
- **Nenhuma porta aberta nesta troca:** só o registro da regra — nenhum
  serviço novo escutando, nenhum bind alterado, nenhuma mutação de rede.
