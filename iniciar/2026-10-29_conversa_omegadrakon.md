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
