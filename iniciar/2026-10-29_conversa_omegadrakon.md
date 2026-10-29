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

## §5 — Inventário de portas do `192.168.0.250` (29/10 ~11:30)

**Pedido:** dono: *"Inventarie quais portas já estão escutando hoje em
192.168.0.250 e o que cada uma serve"* — resposta do follow-up da regra 18.
**Só leitura** (nenhuma porta aberta/fechada, nenhuma mutação).

**Método:** `ss -tln/-uln` (255 sockets TCP LISTEN; 200 = faixa
8600–8699 do AzuraCast em IPv4+IPv6) → `docker ps` (binds por container) →
`systemctl show od-*` (od-core 8000/8001, od-llm 8081, od-azura-proxy 8466,
od-control-bridge 8765) → `tailscale serve/funnel status` (o que é tailnet)
→ script `/proc/net/{tcp,udp}*` + inode → `/proc/*/fd` rodado **dentro** dos
containers (método que nomeou o que `ss -p` esconde sem root) → sondas
`curl` no bind certo.

**Resultado — LAN (`0.0.0.0`/`192.168.0.250`/`*`):** 22 (sshd) · 8000/8001
(od-core API + `/ws`) · 8090 Kiwix · 8091/8445 painel AzuraCast (HTTP/HTTPS,
nginx → `/login`) · 8100 CyberChef · 8123 Home Assistant · 8200 FlatNotes ·
8400 Stirling PDF · 8410 File Browser · 8420 Calibre Web · 8430 IT Tools ·
8470 Homebox · 8480 Vaultwarden · 8600–8699 streams AzuraCast (8600 =
`/radio.mp3`) · 18555 go2rtc · 20220 SFTP AzuraCast · 37603/41377
(listeners efêmeros de descoberta do HA).

**Só local (`127.0.0.1`):** 53 resolved · 5432 PostgreSQL · 8081
llama-server (od-llm) · 8466 od-azura-proxy · 8765 od-control-bridge ·
18554 go2rtc · 49374 `opencode serve --service`.

**Só tailnet:** 443 (Funnel — a ÚNICA saída para a internet) · 1883 (o
mosquitto escuta só em `127.0.0.1` e a tailnet encaminha) · 8443
(ferramentas) · 8446 (painel Azura de fora) · 40804/55870 (página
*"Hello, this is my Tailscale device"* do próprio `tailscaled`, efêmera).

**UDP:** 1900 SSDP · 5353 mDNS · 38787/53141 efêmeros · 41641 WireGuard ·
53 local. Dono de 1900/38787/53141 é processo de **root** e **não foi
nomeado** (sem sudo — honesto, não chutei).

**Achados entregues ao dono (sem agir):** (1) `18555` (go2rtc, câmeras) em
**todas as interfaces sem senha**; (2) `20220`/`8091`/`8445` em `0.0.0.0`
(com login). Dois apertos possíveis, aguardando ordem.

**Canais:** inventário inteiro escrito no `txt.txt` (regra 14 — o arquivo
havia sido zerado por ele às 10:47).

## §6 — Player da rádio no menu lateral + botão Rádio do admin (29/10 ~13:14)

**Pedido (duas partes, no canal `txt.txt`):** dono: *"Toda vez que mudo de
página a rádio para. O player deveria ficar no menu lateral, assim iria
permanecer tocando enquanto navego do site"*; e *"o botão rádio dentro do
menu admin não está abrindo (`https://nicky-server.tail1b1f51.ts.net:8446/`)
… ERR_CONNECTION_TIMED_OUT"*. Duas decisões perguntadas antes de codar
(`ask_user`): **retomar automático** (não SPA, não janela à parte) e
**botão adaptativo à origem** (não só-LAN, não manter como estava).

### 1. Causa medida dos dois sintomas
- **Som morria:** o site é **multipágina** — navegar recarrega o documento
  e mata o `<audio>` que vivia dentro de `site/radio.html`. Mudar o lugar do
  elemento sozinho não faria nada tocar; o que atravessa a troca é o
  **estado**, que passou a morar no `localStorage` (`od_radio`).
- **Timeout do 8446:** o `tailscale serve` escuta **só** em
  `100.77.67.53:8446` (medido: `302` pela tailnet, **`000`** pela LAN) e
  **nenhum outro nó da tailnet estava conectado** (`tailscale status`: todos
  *offline, last seen 1d/14d/35d*) → no aparelho o nome resolvia pelo cache
  e o TCP morria. **Nada no servidor estava quebrado**: backend
  `127.0.0.1:8466` respondendo e o painel da LAN já aberto
  (`http://192.168.0.250:8091 → 302 → /login 200`).

### 2. O que foi feito
- **`site/od-nav.js` (seção 7, +163):** `radioMontar()` chamado **depois** de
  `lateralMontar()` — um SÓ `<audio>` (filho do `body`, `display:none`;
  recolher a barra não encerra a transmissão) e **dois controles do mesmo
  estado**: dentro da barra (13 páginas) e pílula flutuante que só aparece
  com som (abaixo de 1024px a barra é `display:none` — sem a pílula o áudio
  religado seria mudo: dava para começar e não havia como parar). Quem saiu
  ouvindo religa **no instante da montagem**; a pausa do ouvinte apaga o
  cache. Rótulo segue o estado REAL: autoplay segurado → *"Retomar"*, stream
  fora → *"Sem sinal"*. Contrato público `window.odRadio`
  (`alternar`/`estado`/`aoMudar`).
- **`site/od.css` (+54):** player na barra e na barra **recolhida** (só o
  botão), pílula em `@media (max-width: 1023px)`, `<audio>` escondido.
- **`site/radio.html`:** sai o `<audio>` próprio (dois players brigariam
  pelo cache); a página **delega** para `odRadio.aoMudar` e mantém botão +
  aviso honestos.
- **`site/admin.js` (+15):** `hrefNaOrigem()` — `http://` (rede local) manda
  para `http://<host>:8091` (porta já aberta pela regra 18, `200` no
  `/login`); `https://` (tailnet/Funnel) mantém a `8446`, **nunca pública**.

### 3. Verificação (evidência)
- **Gate 2×: 4010 passed / 16 skipped / 0 falha · 90,54% e 90,53%**
  (pós-CHANGELOG), `PIPESTATUS=0` nos dois · `node --check` nos 2 arquivos ·
  **pyflakes: 0 aviso novo** (o `_cacheable` sem uso de `test_api.py:3573`
  já existia no HEAD — fora do meu diff, não mexi).
- **Estado real no node** (o MESMO DOM de mentira da barra, com `<audio>`
  jogável), duas corridas:
  `{"barra":true,"pilula":true,"audio":1,"antes":{"ico":"▶","rot":"Rádio",
  "ativo":false,"cache":null},"depois":{"ico":"⏸","rot":"No ar",
  "ativo":true,"cache":"tocando"}}` ·
  `{"antes":{"ico":"⏸",…,"cache":"tocando"},"depois":{"ico":"▶",…,
  "cache":"parado"}}` — a 2ª é a página NOVA religando sozinha.
- **od-core vivo entregando os arquivos novos** (sem restart: `/site/*` é
  lido do disco): `od-nav.js` 24129 B, `od.css` 30012 B, `admin.js` 18212 B,
  `radio.html` 6176 B com **0** `<audio>` e 4 `window.odRadio`.
- **Rede:** stream da LAN `200 audio/mpeg` (icecast ecoando o Origin → o
  `crossorigin` segue seguro) · `8446` continua **000** pela LAN · painel
  `302 → /login 200`.
- **Sem navegador no host** (Chrome não instalado): o que ficou provado é o
  estado (node) e a entrega dos arquivos (HTTP) — o olho do dono fecha o
  resto. Guardas novas: `tests/test_api.py` **+5** (4005 → 4010).

### 4. Duas correções honestas sobre a §5
- **Achado (1) da §5 estava errado no essencial:** `18555` **não é** uma API
  de vídeo sem senha. Lido o config dentro do container (gerado pela HA):
  `api.listen: ""` + `unix_listen` em socket **0600** (a API do go2rtc **não
  existe em TCP**), `rtsp.listen: 127.0.0.1:18554` e
  `webrtc.listen: ":18555/tcp"` — 18555 é o **ICE/WebRTC sobre TCP**, dono
  confirmado por inode (`/bin/go2rtc`, filho de `python3 -m homeassistant`).
  Sondas de HTTP e STUN de dentro e de fora da LAN dão *reset*, ou seja,
  não serve conteúdo. **Sem restringir a 127.0.0.1:** a sinalização é o
  socket unix (inalcançável da rede) e o arquivo é *"managed by Home
  Assistant — do not edit"*; baixar o bind quebraria o fallback TCP do vídeo
  das câmeras e seria revertido no próximo start da HA. Risco residual
  ~nulo, custo real → **mantido como está, com motivo registrado**.
- **As 3 portas UDP de root que ficaram sem nome foram nomeadas sem sudo:**
  rodando o mapeamento de inode **dentro** do container (root, mesmo netns)
  — `1900` SSDP, `5353` mDNS e os efêmeros `38787`/`53141` são **todos do
  Home Assistant** (`python3 -m homeassistant`); `41641` é o `tailscaled`
  (`--port=41641`, visível no `ps`) e `53` é o `resolved` (só loopback).
  **Inventário da §5 fechado por completo.**

**Git:** `1dcbc10` (6 arquivos, +522/−39) — árvore limpa, push na sequência.
**Sem restart:** só arquivos estáticos (`/site/*` lido do disco), od-core
continua desde 27/10 21:06.

## §7 — O mesmo player levado para /dashboard, /admin e /chat (29/10 ~15:40)

**Pedido:** dono (follow-up direto da §6): *"Leve o mesmo player para
/dashboard, /admin e /chat, que hoje param ao sair do site"*.

### 1. Por que NÃO foi o `od-nav.js` carregado nas três páginas
Medido antes de escolher: o `od-nav.js` traz o **tema** junto — ele cria o
botão `#odTema` no DOMContentLoaded, e o `site/admin.js` do painel cria o
SEU no mesmo momento. Dois handlers no mesmo botão = dois ciclos brigando
pelo mesmo estado (o defeito §3.8 da casa). A solução da casa para isso é
por **superfície**: tema/formato vivem um arquivo por página. Então o
painel ganhou um **irmão** do player, não um gêmeo esquecido — MESMA chave
`od_radio`, então **o estado atravessa a troca site ↔ painel** (o que viaja
é o cache, não o elemento).

### 2. O que foi feito
- **`site/admin.js` (+148):** espelho da seção 7 do `od-nav.js` dentro da
  seção od-formato-orion. `radioMontar()` roda em `iniciar()` **logo após
  `lateralMontar()` e ANTES do cedo do herói** — decida assim porque o
  `/chat` sai cedo (`sem #odOla → papelChat(); return`) e ainda assim tem
  que receber o player. Um SÓ `<audio>` (filho do `body`, escondido) +
  barra e pílula do mesmo estado; rótulo segue o estado real (`Retomar` /
  `Sem sinal`); contrato `window.odRadio` igual ao do site.
- **`integrations/api/server.py` (+47):** regras do player no
  **`_FORMATO_ORION_CSS`** — as 3 páginas do painel **não carregam
  `od.css`**, o CSS delas é o espelho em Python injetado pelo `_com_tema`.
  Mesmas classes, tinta nas variáveis do painel (`--accent`).
- **`tests/test_api.py` (+210, 4010 → 4012):** (a) presença + ORDEM em
  `iniciar()` (recortando o `iniciar()` do FORMATO com `rindex`, porque o
  do tema também cita `odOla`) e CSS espelho nas **páginas servidas**, sem
  mudar a estrutura de `<script>` (1 inline + 1 do admin.js); (b) **estado
  real no node** com `site/admin.js` INTEIRO rodando num DOM de mentira
  novo (`_HARNESS_PAINEL`, com `innerHTML`, `location` e `<audio>`
  jogável).

### 3. Verificação (evidência)
- **Gate 2×: 4012 passed / 16 skipped / 0 falha · 90,53% e 90,51%**,
  `PIPESTATUS=0` nos dois · `node --check` no `admin.js` · **pyflakes 0
  aviso novo** (os 4 do `server.py` e o `_cacheable` do `test_api.py`
  já existiam no HEAD — conferido com `git show HEAD:arquivo | pyflakes`).
- **Harness do painel (admin.js real), duas corridas:**
  sem semente `{"barra":true,"radio":true,"pilula":true,"audio":1,
  "antes":{"ico":"▶","rot":"Rádio","cache":null},"depois":{"ico":"⏸",
  "rot":"No ar","cache":"tocando"}}` · com semente a página NOVA nasce
  `⏸ No ar` sozinha (`cache":"tocando"`) → clique → `▶` + `parado`.
- **Deploy verde (regra 7.3):** `restart` **16:01:10** → MainPID
  **527739**, **NRestarts=0**, `/health` **ok=true, 25/25 nenhum fora**,
  `/app/version` **1.44.0/2080**, journal desde o restart **0 warning/0
  erro**. Restart NECESSÁRIO desta vez (diferente da §6): o CSS do painel
  é **código Python** carregado em memória — antes dele as 3 páginas
  serviam 0 ocorrências de `od-radio`, agora **12 cada**; estrutura de
  scripts intacta (1 inline + 1 admin.js).
- **Borda intacta pós-restart:** Funnel `/` **200**, `/radio.mp3` **206
  audio/mpeg**, painel LAN **302**, `tailscale serve` com os 3 handlers da
  443 + 1883 + 8443/8446.

**Git:** `01b1d6d` (4 arquivos, +432) pushado, árvore limpa
(HEAD == `origin/master`).
