# Conversa OmegaDrakon — 2026-11-12

## §1 — Retomada ("leia iniciar") e estado encontrado (12/11)

**Pedido do dono:** *"leia iniciar"* — recarregar o checkpoint antes de retomar.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md` (21 regras), `iniciar/session.json`
(entrada mais recente: `devaneios_cache_comando_radio_duplicada_e_cota_gemini_2026_11_11`,
de 11/11 15:05), a transcrição `iniciar/2026-11-11_conversa_omegadrakon.md`
inteira (§1–§13, 694 linhas), o `txt.txt` e o `git status`/`git log`.

### 2. Estado do serviço e do repositório

- `od-core` **ativo**, MainPID **2740225**, `NRestarts=0` — é o processo do
  último restart de 11/11 (o mesmo da prova viva do §13). Nada mudou desde
  então.
- `HEAD` = `origin/master` = **`abcd2e1`** (`docs(iniciar): registra a cadeia
  Gemini→Groq→local, a medição e o incidente do deploy`).
- A árvore **não está limpa**: 11 modificados (+622/−37) e 1 novo
  (`tests/test_radio_player.py`) — é exatamente o lote do **§13** (devaneios
  por cache, rádio em duplicata, disjuntor da cota do Gemini), testado mas
  **não commitado**.

### 3. O que está no disco sem commit (§13 de 11/11)

| Arquivo | Mudança |
|---|---|
| `core/orchestrator.py` | `_etapa_cache` não serve comando de action (`detect_action_intent`) |
| `core/intents.py` | `_formata_radio` para `radio_play`/`radio_stop`/`radio_volume`/`radio_status` |
| `tools/actions/actions.py` | `_radio_ffplay_pids()` varre `/proc`; play adota/encerra duplicata; stop encerra todos os PIDs; zumbi conta como morto |
| `core/resilience.py` | `CircuitBreaker.abrir(erro, recuperacao_s)` |
| `core/llm.py` | `_falhar()` abre na hora em 429/quota, `_espera_do_429()` lê o `retryDelay` (teto 6 h), `_erro_http()` preserva o retryDelay |
| testes | `test_radio_player.py` (novo, 13), `TestFormataRadio` (7), `TestCacheNaoServeComando` (2), cota/disjuntor (6+2) |

Gate registrado no checkpoint: **4489 passed / 17 skipped / 0 falha** (rodado
antes do último ajuste do `retryDelay`; os afetados foram re-rodados e
passaram). Ou seja: **o lote está validado mas não publicado** — regra 7.2
(árvore limpa + HEAD em `origin/master`) segue pendente.

### 4. Achados desta leitura

1. **A higiene do §13 é o único trabalho parado.** Nenhum código novo entrou
   depois; o que falta é commit por assunto, push e restart verde com prova.
2. **O `txt.txt` continua com as três queixas de 11/11** (devaneios, rádio em
   duas instâncias, desligar a rádio deve desligar o player). As três foram
   corrigidas no §13 — o arquivo não foi zerado porque ele é canal, não
   registro (regra 20).
3. **Frente aberta declarada no checkpoint:** cota gratuita do Gemini é
   **20 requisições/dia** (prompt não é o gargalo — medido); hoje quem responde
   é o Groq. Falta decidir se as 20 diárias devem ser reservadas para o que
   exige mais qualidade, e o status dos disjuntores não aparece no `/health`.
4. **App segue 1.44.0/2080** — nenhuma mudança de app neste lote.

### 5. Decisão desta troca

Nada alterado no código: só leitura e registro. O deploy/higiene do lote do
§13 fica para a próxima ordem do dono.

**Sem bump:** app segue **1.44.0/2080**.

## §2 — Higiene do lote de 11/11: gate, commits, push e restart verde (12/11 ~09:30)

**Pedido do dono:** fechar a higiene — gate completo, commits por assunto, push
e restart verde com prova viva.

### 1. Gate completo

`.venv/bin/python -m pytest tests/ -q` → **4494 passed / 17 skipped / 0 falha**
(180,40 s). Nenhuma correção foi necessária: o lote de 11/11 já estava verde
(eram 4489 no registro anterior; +5 pelo `test_radio_player.py` que entrou na
contagem desta rodada).

### 2. Commits por assunto (e o que cada um resolve)

| Commit | Arquivos | Assunto |
|---|---|---|
| `5af9012` | `tools/actions/actions.py`, `core/intents.py`, `test_intents.py`, `test_radio_player.py` | **rádio**: player único por SO e stop que cala todas as instâncias |
| `b6d6144` | `core/llm.py`, `core/resilience.py`, `test_llm.py`, `test_resilience.py` | **cota**: 429 abre o disjuntor na hora e a espera vem do `retryDelay` |
| `8e08d7d` | `core/orchestrator.py`, `test_orchestrator.py` | **grafo**: comando de action nunca vem do cache; `prompt_chars` no log |
| `15531f6` | `iniciar/2026-11-11_conversa_omegadrakon.md` | registro do diagnóstico (§13) |

Push: `origin/master` em **`15531f6`**, árvore limpa.

### 3. Deploy e prova viva

`systemctl --user restart od-core` (regra 7.3, validação verde):
**MainPID 3773109**, `NRestarts=0`, `active`, subido 09:26:26.
`/health` **27/27 up**, `ok=true`; `/llms` = `gemini, groq, gemma-local`;
journal `-p err` **0 entradas** desde o restart.

| Cenário | Resultado |
|---|---|
| "liga a radio" (sem player) | `action_intent fastpath:radio_play`, 1,05 s, **1 player** |
| "liga a radio" de novo | `action_intent` (não cache), 74 ms, **1 player** — adotou o que estava no ar |
| duplicata forçada (`OD_RADIO_CHILD=1 ffplay`) → "liga a radio" | **2 → 1 player**, resposta com "1 instância(s) duplicada(s) encerrada(s)" |
| "status da radio" | `radio_status`, 26 ms, "Rádio tocando (player 3773991)" |
| "desliga a radio" | `radio_stop`, 860 ms, **0 players**, "Rádio parada — energia da caixa desligada" (sem "resistiram") |
| conversa aberta (disjuntor) | `route=llm`, **`llm=gemini`**, 3,45 s, `prompt_chars=6565` |

Nota medida: a cota do Gemini **voltou** (é diária, 20/dia) e o Gemini
respondeu a conversa aberta com o prompt real de 6.565 caracteres — reforça a
medição de 11/11 de que o gargalo é requisição/dia, não tamanho de prompt.

### 4. Resíduos

- Player de teste encerrado (`pgrep ffplay` vazio); nenhum script temporário
  criado nesta entrega.
- Versão **sem bump**: 1.44.0/2080 (correções de servidor; sem mudança de app,
  de API ou de contrato — mesma prática registrada nas entregas anteriores).

**Sem bump:** app segue **1.44.0/2080**.

## §3 — Buracos de intenção: disco, memória e CPU (12/11 ~09:57)

**Pedido do dono:** "qual o uso de disco" deveria acionar a action de disco,
como "quanto de espaço livre" já faz.

### 1. O buraco de detecção

Medido com `detect_action_intent` antes de mexer:

| Frase | Antes |
|---|---|
| "qual o uso de disco" / "uso de disco" / "qual o uso de hd" | `None` (ia para o LLM) |
| "quanto de espaço livre no disco" | `disk_usage` |
| "quanto de memória livre" | `None` (só "quanta memória" casava) |
| "qual o uso de cpu" | `None` (só "uso da cpu"/"processador" casavam) |

A causa era o vocabulário do segundo termo: as regras exigiam
`usado|livre|quanto|como está` e não aceitavam `uso`, `ocupa`, `cheio`,
`disponível`, `quantos`.

### 2. Correção e travas

- `core/intents.py`: disco, memória e cpu passaram a aceitar esses termos.
- **Travas que não podiam regredir:** temperatura continua indo para
  `cpu_temp` (o bloco de cpu ignora a frase quando há
  `temperatura|graus|calor|térmic`); e comprar/preço de HD não vira leitura de
  disco (`custa|compr|preço|barat|orçamento|modelo|marca`).
- A intenção de disco deixou de mandar `path` explícito (a action já mede
  `/` por padrão).

### 3. O segundo defeito: a action era NEGADA

Com a detecção corrigida, a prova viva ainda respondeu `route=fallback`
(`llm=gemini`, 8,8 s). O journal mostrou a causa:

```
CRIT Path outside allowed roots | action=disk_usage | path=/
CRIT Action denied by security | action=disk_usage | denied_by=scope
WARN Orchestrator action denied | Path '/' is outside the allowed project scope
```

O schema da action preenche `path="/"` **antes** do gate, então tirar o param
da intenção não resolvia. Ou seja: **toda** pergunta de disco era negada e caía
no LLM — a detecção nunca chegou a produzir resposta.

- `core/security/scope.py`: `SCOPE_EXEMPT_ACTIONS = {"disk_usage"}` — o `path`
  de uma métrica é o ponto de montagem medido, não acesso a arquivo, então o
  escopo de filesystem não se aplica.
- A exceção é só da métrica: escrita e paths de filesystem continuam negados
  (coberto por teste).

### 4. Testes e deploy

Dois gates completos (um por commit): **4515** e **4517 passed / 17 skipped /
0 falha**. Novos testes: 10 de detecção (disco/memória/cpu, temperatura
preservada, compra de HD não confunde) e 2 de escopo (disco isento, escrita
ainda negada).

Restart: **MainPID 3810200**, `NRestarts=0`, `/health` **27/27**, journal 0 erro.

### 5. Prova viva

| Frase | Resultado |
|---|---|
| "qual o uso de disco" | `action_intent`, `fastpath:disk_usage`, **31,8 ms**, "62,7% usado · 75,7 GB livres de 231,2 GB" |
| "quanto de espaço livre no disco" | `action_intent`, `fastpath:disk_usage`, 20,0 ms, mesmo dado real |
| "quanto de memoria livre" | `action_intent`, `fastpath:memory_usage`, 6,2 ms |
| "qual o uso de cpu" | `action_intent`, `fastpath:cpu_info`, 7,2 ms |
| "qual a temperatura da cpu" | `action_intent`, **`fastpath:cpu_temp`** (não regrediu), 7,6 ms |
| "quanto custa um hd de 4tb" | conversa (não aciona disco) |

Commits: `742e054` (detecção), `c863780` (intenção sem path), `5dde610`
(exceção de escopo).

**Sem bump:** app segue **1.44.0/2080**.

## §4 — Auditoria do gate de escopo em todas as actions (12/11 ~10:20)

**Pedido do dono:** auditar as outras actions de leitura contra o gate de
escopo, para achar mais negações silenciosas como a do disco.

### 1. Método

As 122 actions do `CATALOG` foram avaliadas pelo **mesmo pipeline de produção**
(`SecurityManager(mode="strict")`), com os params preenchidos pelo schema
(defaults + valores de exemplo para os obrigatórios) e três papéis.

### 2. Resultado

| Papel | Negadas | Leitura |
|---|---|---|
| `admin` (dono) | **0** de 122 | só o meu exemplo de `action_validate` feriu o schema (`params` é dict) |
| `user` | 80 | **todas por `permission`**, de propósito: escrita Google, `vault_*`, `database_*`, `network_hosts`, `filesystem_read/delete/write`, `radio_*`, `kiwix_*`, `stirling_*` etc. |
| `guardian` | todas | **`guardian` é perfil de conversa, não papel do Security Layer**; papel desconhecido = deny-all (`UNKNOWN_ROLE_POLICY = "deny"`) |

Ou seja: **a negação silenciosa do disco era a única dessa classe**. Nenhuma
action de leitura nasce negada pelo gate com seus próprios defaults.

### 3. O achado inverso (mais interessante que o pedido)

A varredura de chaves de caminho (`_PATH_PARAM_KEYS`) mostra poucas actions
com `path`/`source`/`dest` — e **duas leem caminho local com nomes fora da
lista de escopo**:

| Action | Param | O que faz | Situação |
|---|---|---|---|
| `stt_transcrever` | `caminho` | abre um áudio **local** e transcreve | **não passa pelo escopo** |
| `filebrowser_envia` | `origem` | lê um **arquivo local** e envia para a caixa | **não passa pelo escopo** |

Não corrigi: incluir `caminho`/`origem` na lista passaria a negar `/tmp/...`
(áudio e arquivos fora do projeto), o que é decisão de política do dono, não
um bug de código. Registrado no TODO.

### 4. Rede de regressão criada

`tests/test_scope_audit.py` (8 testes, novo):

1. **nenhuma action negada com os próprios defaults** (admin) — é o teste que
   pega a volta do bug do disco;
2. **canário dos params de caminho** — action nova com `path`/`source`/`dest`
   quebra a lista e obriga a decisão (local? serviço?);
3. **a isenção só cobre métrica de sistema**;
4. **escopo não afrouxou**: `filesystem_read/delete/write/list` com
   `/etc/passwd` continuam negados;
5. **disco mede qualquer montagem** (`stat`, não leitura de conteúdo).

**Teste do teste (mutação):** removendo `disk_usage` de
`SCOPE_EXEMPT_ACTIONS`, dois testes falham (o do default e o da montagem);
arquivo restaurado bit a bit depois (`git diff` vazio).

### 5. Verificação e estado

Gate completo: **4525 passed / 17 skipped / 0 falha** (176,99 s). Só teste novo
entrou — **nenhum código de produção mudou**, então **não houve restart**: o
`od-core` segue no MainPID **3810200**, `NRestarts=0`.

**Sem bump:** app segue **1.44.0/2080**.

## §5 — "prepare o Omega Drakon para resistir": prontidão medida + plano (12/11 ~10:35)

**Pedido do dono (`txt.txt`):** kits de 72 horas estão sendo distribuídos pelo
mundo, "algo vai acontecer"; usar o máximo da internet enquanto ela existe,
preparar para o colapso, buscar alternativas para continuar funcionando e se
comunicando — e responder **o que fazer, o que comprar, o que criar**.

### 1. O que foi medido antes de opinar

| Item | Medido em 12/11 |
|---|---|
| Hardware | i5-6500, 7,7 GB RAM (4,4 GB disponíveis), disco 232 GB / **76 GB livres** |
| Energia | `/sys/class/power_supply` **vazio** — sem UPS/bateria visível ao SO |
| Acervo offline | Kiwix com **2 ZIMs = 15 GB** (Wikipédia EN mini 14 GB + PT mini 1,6 GB) |
| IA local | llama.cpp :8081 com `qwen2.5-coder-3b` (o mais fraco da cadeia) |
| Serviços | **11 containers** locais (Kiwix, Stirling, FileBrowser, Calibre-Web, FlatNotes, Vaultwarden, Homebox, IT-Tools, CyberChef, AzuraCast, Home Assistant) |
| Backup | `backups/` com último arquivo há **7 h**, mas **tudo na mesma máquina** |
| Comunicação | Telegram (nuvem) + API/chat web só na LAN; Tailscale com **0 nós online** além deste |

### 2. Entrega em software: `readiness_report`

Ação nova no catálogo (sistema, **123 actions**): mede **9 itens** e devolve
número, não prosa — energia, disco, memória, conhecimento offline, IA local,
internet, backup recente, nó alternativo na malha e dependência de nuvem.

No chat: *"como estamos preparados para o colapso"*, *"qual a prontidão do
sistema"*, *"o que falta para resistir"* → `fastpath:readiness_report`.

**Prova viva (MainPID 3846447, NRestarts=0, `/health` 27/27, journal 0 erro):**

```
🛡️ Prontidão: 6/9 (66.7%)
⚠️ energia: sem UPS/bateria no SO
✅ disco: 75.7 GB livres · ✅ memória: 4460 MB
⚠️ conhecimento: 2 ZIM(s), 15.0 GB
✅ ia_local: respondendo em 127.0.0.1:8081 · ✅ internet: no ar
✅ backup: último arquivo em 7 h
⚠️ comunicacao: 0 nó(s) online além do servidor
✅ nuvem: 3 provedor(es) de IA na nuvem
Pendente: energia, conhecimento, comunicacao
```

Duas chamadas: 119,8 ms (primeira, com cache frio) e 32,9 ms. `/capabilities`
passou a anunciar **123 actions**; 14 testes novos em `tests/test_readiness.py`
(estrutura, pontuação, acervo reprovado, backup ausente, caminhos inexistentes,
intenção no chat e formatador). Contagens de catálogo/capabilities atualizadas.

### 3. Plano escrito: `docs/CONTINUIDADE.md`

Responde as três perguntas do dono com os números acima:

- **Fazer agora (0–7 dias):** baixar ~25 GB de acervo (Wikipédia PT completa,
  WikiMed, WikiHow, iFixit/Appropedia, mapas), testar `Qwen2.5-7B q4` no lugar
  do 3B, espelhar pip/Docker, exportar cofre + snapshot do Postgres para mídia
  **fora** da máquina.
- **Comprar (por risco, não por preço):** Fase 1 nobreak com USB + 1 SSD
  externo + roteador 4G (~R$ 2–3,5 mil); Fase 2 dois rádios LoRa Meshtastic
  (~R$ 600–1.500); Fase 3 solar + bateria + HD 4 TB. **Não comprar** servidor
  reserva agora — o gargalo é energia/comunicação, não CPU.
- **Criar (software):** modo colapso declarado (troca para local), fila de
  download resumable de acervo, mapas offline, RAG de manuais, backup
  verificado + offsite, espelho de pacotes, ponte LoRa↔OD, kit 72 h no app e
  monitor de UPS.
- **Runbook** de 10 min / 1 h / 24 h / 72 h e as **5 decisões** que dependem do
  dono (nobreak, LoRa vs 4G, quais ZIMs, onde é o offsite, modo colapso
automático).

### 4. Honestidade sobre o pedido

O documento **não promete** que o OD sobrevive a um colapso longo: ele diz o
que já é local (dados, serviços, IA de reserva, rádio, casa), o que quebra
primeiro (energia e comunicação) e quanto custa fechar cada buraco. A parte de
sobrevivência física (água, comida, remédios, documentos) não é decisão de
software — o plano só aponta onde ela encaixa (kit 72 h no app).

**Sem bump:** app segue **1.44.0/2080** (ação de servidor).

## §6 — "continue": acervo de 14 ZIMs, mapa com modo offline e higiene (12/11 ~13:05)

**Pedido do dono:** "leia iniciar. continue" — retomar do checkpoint.

### 1. O que estava interrompido (não registrado)

O §5 fechou às 10:35 com o plano de continuidade. Depois disso a árvore ganhou
4 arquivos modificados sem registro, sem commit e sem deploy — o "fazer agora"
do próprio plano executado até a metade:

| Arquivo | O que havia |
|---|---|
| `docker/tools-compose.yaml` | Kiwix com 12 ZIMs quentes + bind do frio no HD USB, memória 512 MB→1 GB |
| `tools/actions/actions.py` | `readiness_report` somando acervo quente (`zim_dir`) + frio (`zim_dir_frio`) |
| `tests/test_readiness.py` | 4 chamadas ajustadas para `zim_dir_frio` |
| `site/protomaps.html` | protocolo `pmtiles://`, mapa local com reserva raster OSM, marcador da casa |

Medido: 12 ZIMs quentes no SSD (25,3 GiB, baixados 10:45–11:55) e 2 frios no HD
USB (15,0 GiB) — 40,3 GB no total, disco com 51 GB livres. O container `od-kiwix` ainda rodava com
o compose antigo (2 ZIMs) — não servia o acervo novo.

### 2. O que foi feito nesta retomada

1. **Bug de JS corrigido** em `site/protomaps.html`: o handler `map.on('error')`
   estava **fora** da IIFE assíncrona que cria o `map` (`const` no escopo da
   função) — `ReferenceError` no load e o fallback visual nunca rodava. Handler
   movido para dentro, depois da criação do mapa. JS inline validado com
   `node --check` (2 blocos).
2. **Kiwix recriado** com o compose novo: `running`, `RestartCount=0`,
   `Memory=1 GB`; `/catalog/v2/entries` lista os **14 ZIMs**; HTTP 200 na 8090.
3. **Gate completo:** **4539 passed / 17 skipped / 0 falha** (180,02 s).
   `docker compose config -q` limpo.
4. Higiene: commits por assunto, push, restart verde com prova viva (abaixo),
   CHANGELOG, TODO (acervo marcado como feito; mapas offline segue
   aberto esperando o `.pmtiles`) e os três arquivos de sessão.

### 3. Prova viva (restart 12:57)

`od-core` active, **MainPID 3996872**, `NRestarts=0`, `/health` **27/27**
(o primeiro check logo após o restart marcou 26/27 durante o aquecimento;
8 s depois, 27/27), `journalctl -p err` **0 entradas**. `/site/protomaps.html`
HTTP 200 e `/site/maps/brasil.pmtiles` 404 (por isso o modo online, como
esperado sem o arquivo).

```
qual a prontidao do sistema -> action_intent fastpath:readiness_report 49,68 ms
🛡️ Prontidão: 7/9 (77.8%)
⚠️ energia: sem UPS/bateria no SO — apagão derruba o servidor sem shutdown
✅ conhecimento: 14 ZIM(s), 40.3 GB (quente: …/zim; frio: …/dados/od-zim)
✅ ia_local, ✅ internet, ✅ backup, ✅ nuvem, ✅ disco (65.4 GB livres), ✅ memória
⚠️ comunicacao: 0 nó(s) online na malha privada além do servidor
Pendente: energia, comunicacao
```

### 4. Resultado

A prontidão do conhecimento deixou de reprovar: o acervo passou de 15 GB para
40,3 GB (piso de 30 GB do check). Restam **energia** (sem nobreak visível ao
SO) e **comunicação** (0 nós online além deste servidor) — as duas compras da
Fase 1 do plano, que dependem de decisão do dono.

**Sem bump:** app segue 1.44.0/2080.

## §7 — "prossiga": mapa offline de verdade (Brasil PMTiles) (12/11 ~13:20)

**Pedido:** "prossiga" — o próximo item do backlog era o recorte `.pmtiles`.

### 1. Medido antes de baixar

- Fonte: build diário do Protomaps `20261112.pmtiles` (planeta, 139 GB).
- `pmtiles extract --dry-run` com bbox do Brasil (-74,-34,-32,5.5) e
  `--maxzoom=14`: **2.811.716 tiles, 3,2 GB de tráfego, 3,1 GB de arquivo**.
- Disco: 66 GB livres. Extração real: **2,9 GB em 1m38s** (95 requests).

### 2. O que foi criado

| Item | Medida |
|---|---|
| `site/maps/brasil.pmtiles` | 2,9 GB, zoom 0–14, MVT gzip, OSM de 12/11; **gitignored** |
| `site/vendor/maplibre-gl.js` + `.css` | 894 KB + 68 KB |
| `site/vendor/pmtiles.js` | 20 KB |
| `site/vendor/fonts/Noto Sans Regular/*.pbf` | latin 0–1279, 5 arquivos, 500 KB |

### 3. Quatro defeitos encontrados e corrigidos

1. **`HEAD` responde 501** no roteador: `temMapaLocal()` usava `HEAD` e o modo
   offline **nunca** ativaria. Trocado por `GET` com `Range: bytes=0-0`.
2. **URL relativa não funciona no protocolo:** rodei o `pmtiles.js` real no
   Node — `pmtiles:///site/maps/...` lança "Failed to parse URL"; com URL
   absoluta devolve tile (93 KB no z0). `MAPA_LOCAL` passou a usar
   `location.origin`.
3. **Camadas plurais:** o basemap v4 tem `earth`, `roads`, `water`, `landuse`,
   `places`, `boundaries`; o estilo usava `road`/`poi`/`place` e nada
   renderizava nessas camadas. Corrigido e confirmado no tile real.
4. **Sem `glyphs`:** `symbol` layers não desenham rótulo sem fonte de glifos.
   Adicionado `glyphs` local e `text-font: Noto Sans Regular` (antes pedia
   Orbitron/Montserrat, que nem existem no acervo de glifos).

### 4. Verificação

`pmtiles show` (magic `PMTiles`, bounds, zoom 0–14) e `pmtiles tile`
(z0 = 93.230 bytes); HTTP `Range` **206** no pmtiles, nas libs e nos glifos;
página com **0 referências a unpkg**; JS inline `node --check` OK. Sem restart
(só arquivos estáticos). **Sem bump.**

**Limitação honesta:** não há navegador nesta máquina, então não houve prova
visual do mapa renderizado; a prova é HTTP + tile real + sintaxe. Só glifos
latinos foram embutidos (cobre pt-BR).

## §8 — 7B × 3B medido: o 3B permanece (12/11 ~13:45)

**Pedido:** "Meça o Qwen2.5-7B q4 contra o 3B atual e troque se valer a pena."

### 1. Método

O 7B **já estava em disco** (`qwen2.5-coder-7b-instruct-q4_k_m.gguf`, 4,7 GB);
não foi preciso baixar. Como os dois não cabem juntos na RAM (5,3 GB livres e
swap em 4,4 GB), medi em sequência:

1. 3B no ar (unit `od-llm`, flags atuais);
2. `systemctl --user stop od-llm` + unit transiente `od-llm-bench` com o 7B,
   mesmas flags (ctx 8192, `-t 4`, temp 0,7, top_p 0,9, repeat 1,15);
3. mesmo script: system prompt **real** (`build_identity_prompt('drakon')`,
   2.992 chars) + 6 perguntas (Turing, Omega Drakon, e-mail de orçamento, Ada
   Lovelace, RAM × disco, água em emergência), `max_tokens=400`;
4. serviço restaurado com o 3B ao fim.

### 2. Números

| | 3B (atual) | 7B |
|---|---|---|
| p50 | **16,26 s** | 60,15 s |
| pior caso | 72,54 s | 105,19 s |
| acertos (critério objetivo) | 3/6 | **5/6** |
| truncados | 0 | 0 |
| tokens de saída | 728 | 986 |
| RAM disponível com o modelo no ar | 5,9 GB | **2,3 GB** |

### 3. Leitura manual (o que o critério automático não vê)

- **Turing:** os dois corretos; o 7B é mais preciso (1936, fita, limites da
  computação). O critério exigia "Enigma" e puniu ambos — erro do teste, não
  do modelo.
- **Água:** 7B correto (filtrar, cloro, esperar); 3B mandou **"ferver a água
  com álcool 70%"** — perigoso. Ponto forte do 7B.
- **Ada:** 3B mais seguro (erros de português, sem invenção); 7B inventou
  "Algoritmo da Damasciana". Ponto do 3B.
- **Omega / e-mail / RAM×disco:** ambos aceitáveis.

### 4. Decisão: NÃO trocar o padrão

O ganho de qualidade (5/6 × 3/6) não paga **3,7× de latência** num modelo que
é o *fallback offline* do chat, e o 7B deixa **2,3 GB** livres numa máquina de
7,7 GB que já operava com 4,4 GB de swap — o comentário do próprio
`od-llm.service` registra que o llama-server "derrete sob pressão de RAM".
Trocar aumentaria o risco de o chat inteiro travar justamente no cenário
(offline) em que o local é a última linha.

O 7B fica em disco como opção consciente: com mais RAM, ou Q3_K_M com
`-c 4096`, o reteste está no TODO e o critério é p50 ≤ 2× o do 3B.

### 5. Estado final

`od-llm` de volta com o 3B (`MainPID 4036016`, `NRestarts=0`); unit transiente
`od-llm-bench` removida (`--collect`); `/health` **27/27**; `/llms` com
gemini, groq e gemma-local. Benchmarks em `/tmp` (fora do repo) e números
gravados em `docs/IAS_DISPONIVEIS.md` §5. **Sem bump.**

## §9 — Espelho de pacotes criado e verificado (12/11 ~14:00)

**Pedido:** "prossiga" — próximo item do plano de continuidade: reinstalar sem
internet.

### 1. O que foi espelhado

Destino: **`/home/alex/dados/od-mirror`** (HD USB, fora do git), **3,3 GB**:

| Item | Medida |
|---|---|
| `pip/` — wheels de `requirements.txt` | **47 wheels**, 71 MB (cp312, manylinux x86_64) |
| `docker/` — 11 containers em uso + `postgres:16-alpine` | **12 tars**, 3,2 GB |
| `README.md`, `MANIFEST.txt`, `requirements.txt`, `tools-compose.yaml` | cópias e `sha256` de tudo |

`docker save` deu 3,2 GB, não a soma nominal das imagens (~13 GB), porque as
camadas são compartilhadas nos tar; as tags originais foram preservadas.

### 2. Verificação (não só cópia)

- **pip offline de verdade:** `.venv/bin/pip install --no-index --find-links
  /home/alex/dados/od-mirror/pip -r requirements.txt --dry-run
  --ignore-installed` → “Would install” os **47 pacotes**, sem rede.
- **tar íntegros:** todos os 12 abrem `manifest.json`.
- **checksums:** `sha256sum -c MANIFEST.txt` → **OK** em todos.
- README com os comandos de restauração de pip e Docker, e o que **não** está
  no espelho (código, `.gguf`, ZIMs, `.env`).

### 3. Decisões

1. Espelho no **HD USB**, não no SSD: se o SSD morrer, o espelho não morre com
   ele (e o plano já manda usar os HDs para o que não é prioridade).
2. Copiar `requirements.txt` e `tools-compose.yaml` **para dentro** do espelho:
   num desastre o repo pode não estar à mão e os comandos precisam existir ali.
3. Não espelhar `requirements-dev.txt` nem `apt`: o alvo é rodar o OD, não
   desenvolver nele.

**Sem bump:** app segue 1.44.0/2080.

## §10 — Retomada ("leia iniciar") (12/11 ~14:10)

**Pedido do dono:** *"leia iniciar"* — recarregar o checkpoint antes de retomar.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md` (21 regras), `iniciar/session.json`
(entradas mais recentes: `espelho_offline_2026_11_12` 14:00 e
`benchmark_7b_vs_3b_2026_11_12` 13:45), a transcrição
`iniciar/2026-11-12_conversa_omegadrakon.md` inteira (§1–§9), o `txt.txt`
(vazio) e `git status`/`git log`.

### 2. Estado encontrado

- Árvore **limpa**; `HEAD` = `origin/master` = **`88fa04c`**
  (`docs(continuidade): espelho offline de 3,3 GB criado e verificado`) — o
  registro do §9 já foi commitado e publicado.
- `od-core` **ativo**, MainPID **3996872** (restart do §6, 12:57:43),
  `NRestarts=0`. Depois dele só entraram arquivos estáticos (`site/maps`,
  `site/vendor`) e docs — nada que exija restart.
- `txt.txt` **vazio** (canal zerado; sem recado pendente do dono).

### 3. O que está em aberto (nada parado na árvore)

1. **Espelho offline:** falta o teste de restauração real em ambiente limpo
   (hoje a verificação é resolução de dependências + integridade, não um boot
   completo).
2. **Continuidade (`docs/CONTINUIDADE.md`):** energia (nobreak com USB) e
   comunicação (segundo nó/LoRa) dependem de compra/decisão do dono — Fase 1
   estimada em R$ 2–3,5 mil.
3. **7B:** reteste com `Q3_K_M`/`-c 4096` no TODO (critério p50 ≤ 2× o do 3B).
4. Frentes menores do TODO: disjuntores visíveis no `/health`, reserva das
   20 req/dia do Gemini, prova visual do mapa offline (sem navegador na máquina).

### 4. Decisão desta troca

Nada alterado no código: só leitura e registro. Não há deploy pendente (árvore
limpa, HEAD publicado, serviço verde).

**Sem bump:** app segue **1.44.0/2080**.
