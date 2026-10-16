# Conversa 2026-10-16 — OmegaDrakon

## §1 — Melhorar o RAG ENTREGUE — memória histórica no corpus + recalibração medida do floor (ordem "prossiga")

Dono mandou **"prossiga"** (~00:25) — interpretado como o próximo da
fila do TODO §7 (mesmo critério da Etapa 4: primeiro item da lista):
**Melhorar o RAG (embedding + corpus externo)**. Registrado como
`ordem_rag_2026_10_16` em `iniciar/session.json`. Entrega **sem bump**
(backend puro — nenhuma linha de app ou site mudou).

### O caminho foi pela medição — e o plano ingênuo foi FALSIFICADO antes de virar código

| Etapa | Achado (medido, não suposto) |
|---|---|
| Estudo | `memory/rag.py` (pipeline: reescrita → busca top-24 → **floor duplo** `0.8·cosseno + 0.2·ov ≥ PISO_SCORE` **E** `ov ≥ PISO_OVERLAP` → visibilidade → orçamento) + `memory/vector.py` (`VectorStore` com `EmbeddingProvider` injetável; hoje `HashEmbeddingProvider` 256-d/blake2b; provider versionado só pelo NOME — trocar sem re-embed seria silently errado) |
| Runtime do box | **A 8081 é llama-server (llama.cpp), não Ollama** — `qwen2.5-coder-3b` só `completion`; `POST /v1/embeddings` → **501 "start it with --embeddings"**. Não existe Ollama nenhum. RAM livre ~**1,7 GB** (7 GB no total) → segundo servidor de embedding = impossível |
| Spike `fastembed` | `pip install fastembed` (spike, **fora do requirements**): MiniLM multilingual int8, 384-d — re-embed de 895 chunks **39 s** (23/s), busca pura-Python **46 ms**, consulta **7 ms**, RSS ~875 MB (batch 32; batch 256 estourava +1,7 GB de arena ORT) |
| Separação semântica | relevante mín **0,394** × irrelevante máx **0,546** — **SOBREPÕE**: a consulta de clima casa com `README_VERSAO` (**colisão REAL**: o corpus *documenta* a action `weather_city`) e essa pergunta bate o pior relevante em TODAS as chaves (sem 0,546 · ov 0,498 · comb 0,537 · suporte top-3 1,522) |
| Chaves candidatas — todas testadas | fusão linear `w·sem+(1−w)·ov` (provada impossível: a irrelevante domina o pior relevante em ambos os eixos), suporte top-3, mean-center, PCA-3 → **nenhuma região de gate** em nenhum modelo; `mpnet` descartado na triagem: **3,8 GB RSS**, 419 s/895 chunks (2/s) |
| Experimento autoritativo (gate pelo `consult()` REAL, 4 configs) | **E1** hash+padrão: 8/8 + 8/8, parafrases **3/8** (recall conservador PROVADO na pipeline de produção) · **E2** hash+externo no floor velho: 8/8+8/8 mas parafrases **1/8** — corpus externo SEM recalibração **REGRESSA** (IDF diluído + transcrições disputando as 24 vagas de candidato) · **E3/E4** semântico: **IRR 7/8** — entra a consulta de clima → quebra de contrato |
| Bug de integração pegue no spike | fastembed devolve `numpy.float32` → `VectorStore persist failed | TypeError` (JSON não serializa) — se um dia o semântico entrar, é `float(v)` na hora do embed |
| Grid de recalibração (espaço hash) | ms 0,380–0,420 × mo 0,000–0,060, passo 0,001, no corpus final: **780 células** mantêm o gate 8/8+8/8 **E** as parafrases em 6/8; centro medido **(0,399 · 0,036)** — confirmado célula de maior margem |

### O que foi feito

| Peça | Detalhe |
|---|---|
| `memory/rag.py` | `fontes_padrao()` += **`iniciar/*.md`** (32 transcrições + RULES, visibilidade interna) — corpus **895 → 1.598 chunks**. `TODO.md` ficou DE FORA por decisão medida: muda a cada sessão (churn de IDF puro) e nenhuma linha vencedora do grid veio dele. `PISO_SCORE 0.36 → **0.399**`, `PISO_OVERLAP 0.22 → **0.036**` — centro das janelas medidas, comentários no código com as faixas e a data |
| `core/auto_update.py` | alvo `indice-rag` cobre `iniciar/` (`hash_conteudo` com as 3 pastas) — transcrição editada → resync sozinho, sem esperar boot |
| `tests/test_rag.py` | **+6** `TestRecallParafrases` (as 6 medidas passam; docstring registra as 2 PERDIDAS como estruturais: a primeira perdida comb **0,3922** × a consulta de clima **0,3929** = Δ0,0007 — nenhum piso separa as duas — e a segunda perdida em 0,3682); gate de calibração recalibrado **com medição** (docstring com grid, faixas e fronteiras); teste de fontes cobre `iniciar/` |

**Floor duplo continua load-bearing dos dois lados** (não virou chão
único): `ms` prende a consulta de clima (0,3929 < 0,399), `mo` prende
as irrelevantes sem termo raro (ov 0,000 < 0,036), teto do `mo` = 0,071 = ov da parafrase
"contêiner" via ROADMAP. Fronteira ±0,006 no `ms`: **o gate de
calibração é o tripwire** — corpus novo cruzar → CI grita → recalibrar
com o mesmo grid (procedimento no docstring da classe).

### Embedding semântico: MEDIDO E RECUSADO (e por que isso é a entrega certa)

A ordem do dono pedia "embedding + corpus externo"; os dados dizem que
**embarcar o semântico quebraria o contrato de precisão da casa** neste
corpus: a consulta de clima sobe para cosseno 0,546 >
relevante mínimo 0,394 e **nenhuma chave medida** (fusão linear, suporte
top-3, centralização, PCA-3) separa os conjuntos — a colisão não é
artefato do modelo, é o corpus documentando a action de clima. Com RAM
de 1,7 GB e llama-server respondendo 501, também não há runtime
confortável. **Decisão: provider do hash permanece; o ganho de recall
veio por corpus + recalibração, medido.** Registro completo no
CHANGELOG §Infra de 16/10 para a eventual retomada (com o bug do
`numpy.float32` já mapeado).

Achados honestos da madrugada: (1) 8081 é llama-server, não Ollama;
(2) box não tem RAM para servidor de embedding; (3) corpus externo SEM
recalibração piora o recall (1/8); (4) semântico quebra a precisão
(weather_city é colisão real); (5) 2 parafrases são perda estrutural
(Δ0,0007) — nenhuma constante resolve; (6) `pip check` mostra conflitos
`scipy/rembg` e `httpx2/idna` que são **pré-existentes** (dist-infos de
11 e 12/10 — provado por mtime, não mexi neles); (7) **o próprio
tripwire pegou a poluição documental na hora da entrega**: escrever a
frase literal da query na documentação (CHANGELOG e transcrição são
CORPUS — `fontes_padrao` indexa as duas pastas) fez a irrelevante
passar o floor em minutos, exatamente como o gate foi projetado para
gritar. Corrigido com eufemismo ("consulta de clima") em qualquer doc,
frase literal só em `tests/` (que não é fonte); a ficha histórica do
CHANGELOG atingida pela regex global foi restaurada ao original (era
corpus já calibrado). Lição registrada: **documentar a calibração sem
ensinar o corpus a responder a prova.**

### Verificação

- Suíte oficial gate `--cov-fail-under=90`: **2935 passed / 16 skipped ·
  cobertura 90,60%** (+6 recall; `tests/test_rag.py` 85,
  `test_auto_update.py` 60). `tests/test_rag.py` isolado: 85 em 3 s.
- Sem mudança de app → sem bump (1.30.0/2060 intactos), sem
  `flutter`/APK, sem `node --check` (nenhum JS tocado).

### Prova viva no serviço (pós-deploy, 03:39:57, PID 3300626)

| Verificação | Resultado |
|---|---|
| Restart verde (regra 7.3 — feat `626bc82` pushado ANTES) | `active/running`, **NRestarts=0**, journal **0 erros** |
| Boot do corpus | `RAG corpus sincronizado \| chunks=1598 \| novos=703 \| iguais=895` + 2º sync idempotente `iguais=1598` |
| Store no disco | `data/vector_memory/vector_store.json` = **1.598 docs**, provider hash 256-d |
| `/health` | **up** · `checks: tools up 9/9` |

### Canais e commits

- feat **`626bc82`** (código + testes) pushado antes do restart; docs
  (CHANGELOG §Infra 16/10, esta transcrição, session.json, TODO §7) no
  commit de docs do mesmo push.
- `txt.txt` reescrito (600, gitignored — fluxo, números, notas honestas).
- Telegram resumo ao dono (chat 660518870, HTML).
- Spike: `fastembed`/`onnxruntime`/`tokenizers`/`huggingface-hub`/
  `hf-xet` **desinstalados**, `~/.cache/fastembed` e logs xet de hoje
  removidos — **resíduo zero**.
- Próxima fila (§7): **Observabilidade/Alertas** ou **App auto-update +
  FCM** — ordem do dono.

## §2 — Retomada "leia iniciar" (~04:20) — sistema verde + 2 capturas órfãs do dono em `analise/`

| Verificação | Resultado |
|---|---|
| od-core | `active` **PID 3320551** desde 16/10 **04:02:35** (2º restart verde da madrugada — fecho da sessão anterior engoliu a documentação do dia; 1º foi 03:39:55/PID 3300626), **NRestarts=0**, journal **0 erros** desde 03:39 |
| `/app/version` | **1.30.0 / 2060** · sha `57ed3845…` |
| `/health` (OD_API_KEY) | **up** · 20 checks · `nomad_tools` **9/9** · `rag_*` zerados (contadores frescos pós-boot) |
| Store RAG | `data/vector_memory/vector_store.json` = **1609 chunks** (1598 + docs do dia) · provider hash 256-d |
| Git | **HEAD `3eb6dbb` == `origin/master`**, árvore **LIMPA** (0 resíduos) |
| `txt.txt` | sem mensagem nova do dono (arquivo inteiro = nossa entrega da ordem "prossiga", 04:08) |
| `analise/` | **depósito novo (01:39)** — 2 capturas do **Sistema Órion** (PMESP) SEM instrução |

**Capturas órfãs (não processadas — a sessão do RAG estava rodando e não as viu):**
`analise/Captura de tela 2026-10-16 013444.jpg` e `…013545.jpg` = painel
`orion.intranet.policiamilitar.sp.gov.br/v2/dashboard` (Laravel), dashboard do
42°BPMI, escalas 18/10 e 19/10, 01:34–01:35. **Contêm dado pessoal/servidor do
dono** → ficam onde estão, nada publicado, até ele dizer o que quer (referência
de design? replicar um painel parecido no `/admin`?).

**Alerta conhecido:** `router:down` (warn) 00:03, 01:03, 03:00 — mesma
intermittência de ping do gateway já registrada em 15/10; monitorar, sem ação.

**Fila §7 (ordem do dono):** (A) Observabilidade/Alertas Telegram ·
(B) App auto-update + FCM.

## §3 — Item (A) da fila: Observabilidade / Alertas Telegram (TODO §3.6) — ENTREGUE sem bump

Dono mandou **"a"** (~04:30) = escolha do item **(A)** da fila §7
(`Observabilidade / Alertas Telegram`, esforço baixo). Interpretação
documentada na resposta e em `session.json`
(`ordem_a_observabilidade_alertas_2026_10_16`).

### Apuração no código ANTES de codar — o gap era real e medido

| O que o §3.6 pedia | O que existia (medido) |
|---|---|
| `/health` degraded → msg | **NÃO existia ponte**: notifier cobria 6 sondas (orchestrator/llm/disco/loops/restart/router + tools); o HealthMonitor tem **20 checks** — audit, metrics, database, mqtt, perception, supply_depot, auto_update degradavam **sem alerta nenhum** |
| NRestarts > 0 → msg | **NÃO existia**: só `_check_restart` (PID mudou), que pega até o restart autorizado — o restart **automático** do systemd (queda anormal) era invisível |
| disco > 85% → msg | **JÁ existia** (`_check_disk`, `DEFAULT_DISK_THRESHOLD_PERCENT=85` do legado) — faltava só provar ao vivo |

### O que foi feito

| Peça | Detalhe |
|---|---|
| `integrations/notifier.py` | `_check_health` (async, **última** sonda do tick — as tools já enchem o cache de 10s compartilhado): roda o HealthMonitor real por tick; **dedupe `SAUDE_JA_COBERTA` ("tool_", "orchestrator", "llm", "loops")** = mensagem dupla é proibida, o detalhe lista só o que ninguém cobre mas o total é honesto; `degraded` → warn **após 120s**, `down` crítico → **crit na hora**; baixa explícita das duas chaves (sem zumbi em `active_problems`). `nrestarts_do_systemd(unit)` + `_check_nrestarts`: `systemctl --user show … --value` com timeout 5s em **`asyncio.to_thread`**; **`None` → ok** (desconhecido nunca grita nem dá baixa); **warn ≥ 1, crit ≥ `CRASH_LOOP_RESTARTS` (3)** |
| `runtime/launcher.py` | `build_notifier(..., health=health)`; kill-switches `OD_NOTIFIER_HEALTH=0` / `OD_NOTIFIER_NRESTARTS=0`; sonda NRestarts **só liga com `INVOCATION_ID`** (serviço systemd) ou `OD_SERVICE_UNIT` explícito (CI nunca dispara `systemctl`); `OD_DISK_THRESHOLD_PERCENT` (padrão **85**); log de boot `health_ponte=True \| nrestarts=True \| disco_pct=85.0` |
| **fix achado pela prova de fogo** | `format_alert` fazia `time.localtime()` em cima do `ts` **monotônico** → mensagem saía **"(31/12 21:16)"** (valia para todos os alertas antigos). `Alert` ganhou `wall = time.time()` carimbado em `_emit`; `ts` monotônico segue no anti-spam. Prova: re-run do drill saiu `(16/10 04:47:47)` |

### Verificação

- Suíte oficial gate `--cov-fail-under=90`: **2964 passed / 16 skipped ·
  cobertura 90,60%** (**+29 testes**: `test_notifier.py` 70, +22 —
  ponte (delay/recuperação/dedupe/down/sonda quebrada/ordem do tick),
  NRestarts (0/1/3/recuperação/parse/ausência do binário), exibição
  `wall`; `test_launcher_health_external.py` 21, +7 — wiring e
  kill-switches).
- pyflakes limpo nos 4 arquivos tocados (os 3 avisos do launcher são
  pré-existentes — conferidos com `git show HEAD:… | pyflakes`).
- Sem mudança de app → **sem bump** (1.30.0/2060 intacto), sem
  `flutter`/APK, sem `node --check` (nenhum JS tocado).

### Prova de fogo (sandbox, sink REAL — regra 10/13)

Script fora do serviço com os **dois probes novos** e o
`build_telegram_sink()` de produção: **6 mensagens entregues** ao chat
do dono marcadas `[PROVA DE FOGO 3.6 — sandbox]` — as 3 do primeiro
run **reproduziram o bug de data**; o re-run pós-fix saiu com
`(16/10 04:47)`. Prova do caminho inteiro: probe → `format_alert` →
sink async → API do Telegram, sem tocar `data/notifier_state.json`.

### Prova viva no serviço (pós-deploy, 04:51:49, PID 3367820)

| Verificação | Resultado |
|---|---|
| Restart verde (regra 7.3 — código `a67a6f6` pushado ANTES) | `active`, **NRestarts=0**, journal **0 erros** |
| Wiring no boot | `ProactiveNotifier habilitado \| health_ponte=True \| nrestarts=True \| disco_pct=85.0` |
| 1º tick ao vivo (60s) | **0 alertas proativos** — ponte ligada e nada degradado, NRestarts 0 (sem falso positivo) |
| `/health` | **up · 20 checks · nenhum fora** |
| Leitor real | `nrestarts_do_systemd("od-core.service")` → **0** no ambiente do serviço |
| Versão | `/app/version` **1.30.0 / 2060** (sem bump) |

### Canais e commits

- feat **`a67a6f6`** (código + testes) pushado ANTES do restart; docs
  (CHANGELOG §Infra 3.6, TODO §3.6/§7, esta transcrição, session.json)
  no commit de docs do mesmo push.
- `txt.txt` reescrito (regra 14) · Telegram resumo (regra 15).
- **Fila §7 seguinte: App auto-update + FCM** (ordem do dono).
- Pendência do dono registrada em `analise/`: 2 capturas do Sistema
  Órion (01:39) **sem instrução** — aguardando o que ele quer fazer.

## §4 — Reverificação "leia iniciar" (~06:20) — sistema VERDE + apuração: notifier com 2 classes de alerta mudas desde 11/09

Pedido de rotina do dono (**"leia iniciar"**, ~06:20). Status verde
confirmado com prova; na checagem de rotina apareceu uma anomalia em
`data/notifier_state.json` que foi apurada até a causa raiz. **Nada foi
alterado** — correção proposta aguardando ordem (regras 7/10).

### Status (medido)

| Verificação | Resultado |
|---|---|
| Serviço | `od-core.service` (unidade **USER** do systemd) `active` desde **04:51:49**, MainPID **3367820**, **NRestarts=0** |
| Journal | **0 erros no dia**; WARN de aplicação só os 4 `router:down` já conhecidos (00:03, 01:03, 03:00, 04:41); último evento sync RAG 05:23 `chunks=1622` |
| `/health` (com `OD_API_KEY`) | **ok=true · 20 checks · nenhum fora** |
| `/app/version` | **1.30.0 / 2060** (sha `57ed3845…`) |
| git | **HEAD `07d63fb` == origin/master**, árvore LIMPA |
| `txt.txt` | sem mensagem nova do dono (escrita nossa 04:58 = entrega do item A) |
| `analise/` | inalterado: 2 capturas do Órion (01:39) **sem instrução** + `fotos-adicionais/` |

Fila §7: próximo = **(B) App auto-update + FCM** (ordem do dono).

### Achado — `data/notifier_state.json`: duas camadas de sujeira

O arquivo hoje:

```json
{"pid": 3373227, "started_at": 1230770.312,
 "last_alerts": {"restart": 3754164.292, "llm:offline": 3682439.017,
                 "router:down": 1229671.103}}
```

**Camada 1 — veneno de boot antigo (a séria).** `restart` e
`llm:offline` são **monotônicos do boot 29/07→11/09** (o de 43 dias de
uptime). A prova veio do journald persistente: o **último** `key=restart`
da história é **11/09 00:55:40** e o **último** `key=llm:offline` é
**10/09 05:00:15** — convertendo os valores envenenados pela data de
boot saem **00:55:43** e **05:00:18** (Δ3 s idêntico nos dois = o kernel
contou 3 s antes do primeiro evento do journald). Ou seja: os valores
foram gravados **nesses próprios alertas** e o `_save_state` os
preservou **verbatim** (`integrations/notifier.py` 688–696 e 946–964)
através dos reboots de **11/09, 21/09 e 01/10**.

**Efeito — 2 classes de alerta mudas há 35 dias.** O anti-spam em
`_consume_result` (798–799): `if last is not None and (now - last) <
cooldown:` — com `last` do boot anterior, `now - last` é **negativo**,
sempre `< 3600` (`DEFAULT_COOLDOWN_S`) → **bloqueio permanente**.
Corroboração viva: os **3 restarts de hoje (03:39:55, 04:02:35,
04:51:49) não geraram nenhum alerta `restart`** no journal;
`router:down` continua passando porque foi **re-emitido** com relógio
real às 04:41 (linha 814 atualiza o valor no emit). Tradução: **se o
LLM cair agora, não há aviso proativo** (`llm:offline` é `severity=crit`).
Sem reboot do host, o desbloqueio "sozinho" só aconteceria por volta de
**13–14/11** (quando o monotônico atual alcançar esses valores).

**Camada 2 — poluição da suíte de testes (a menor).** O arquivo foi
**reescrito por `pid 3373227` às 04:59:25.894**; `started_at`
1230770.312 converte para **04:59:25.31** (boot 01/10 23:06:35) — bate
bit a bit com o mtime. Essa janela é da **suíte gate rodada antes do
commit de docs `07d63fb`** (`.coverage` 05:00:18, commit 05:00:35).
Causa: `tests/test_nomad_tools.py::TestLauncherWiring::
test_build_notifier_*` chama `launcher.build_notifier()` **sem isolar
`DATA_DIR`** — o `tests/conftest.py` só redireciona `LIMITACOES_FILE`; a
fixture de isolamento existe **só** em `test_launcher_health_external`.
Assim `state_file=DATA_DIR/"notifier_state.json"` (`launcher.py:1347`)
grava pid/started_at do pytest no estado **de produção** no `__init__`
(linha 696). É transitório (o próximo emit do od-core regrava o pid
dele) e **não disparou alerta nenhum** — mas é risco latente: um teste
que fizesse `tick()` com sinks reais mandaria mensagem de verdade ao
dono.

**Não afetado:** as pontes do item (A) (NRestarts/health/disco) leem
fonte fresca a cada tick — intactas. As métricas do notifier
(`alerts_emitted`/`alerts_blocked`) continuam fora do
`/dashboard/stats` (daí o mute não aparecer em lugar nenhum).

### Correção proposta — AGUARDANDO ORDEM (nada aplicado)

1. **Saneamento no load**: descartar entradas de `last_alerts` com
   valor **> relógio atual** (monotônico de boot anterior nunca pode ser
   válido) + teste de regressão — mata o veneno no próximo restart.
2. **Isolar `DATA_DIR`** nos testes `build_notifier` do
   `test_nomad_tools` (mesmo padrão da fixture já existente em
   `test_launcher_health_external`).
3. *(opcional)* expor `alerts_emitted`/`alerts_blocked` no
   `/dashboard/stats`.

Registro em `session.json` (`reverificacao_2026_10_16_0640`). Próxima
etapa: ordem do dono — **correção do notifier** ou **seguir a fila §7
(B) App auto-update + FCM**.

## §5 — "conserte o notifier" — conserto entregue, provado e no ar

Dono mandou **"conserte o notifier"** (~11:10) — a correção proposta
no §4, na íntegra. Backend puro, **sem bump** (1.30.0/2060 intacto).

### O que mudou

| Peça | Entrega |
|---|---|
| `integrations/notifier.py` | A carga do `last_alerts` **descarta timestamp futuro** (`quando <= agora + 0.01`): monotônico de boot anterior nunca é válido — é o veneno que deixou `restart` e `llm:offline` mudos por 35 dias. Folga de 10 ms cobre o `round(v, 3)` do save com relógio congelado nos testes. O `_save_state()` do `__init__` regrava o arquivo limpo → **a limpeza de `data/` acontece sozinha no restart**, sem mutação manual de estado. |
| `tests/test_nomad_tools.py` | Fixture `_data_dir_isolada` nos 2 `test_build_notifier_*` (mesmo padrão do `test_launcher_health_external`: `DATA_DIR` → `tmp_path` + cache de env zerado) + asserção de `state_file` no tmp → **a suíte inteira parou de gravar `data/notifier_state.json`**. |
| `tests/test_notifier.py` **+2** | Regressão do incidente: (1) carga descarta `restart: 3_754_164.292` e regrava o arquivo **limpo**, preservando o `router:down` legítimo; (2) comportamento: com o veneno no arquivo, o alerta `restart` **emite** (antes: bloqueado pelo delta negativo). |
| `.gitignore` | `logs/*.log.*` — a rotação de 11:09 do serviço criou `interface_monitor.log.1` fora de `logs/*.log` e poluiu o status (resíduo da regra 7.2). |

### Validação (antes de qualquer mutação)

- Gate oficial `--cov-fail-under=90`: **2966 passed / 16 skipped ·
  cobertura 90,62%** (+2 testes; o único warning é o pré-existente de
  `tests/test_orchestrator.py`, conferido isolado).
- pyflakes limpo nos 3 arquivos.
- **Prova da não-polução:** mtime de `data/notifier_state.json`
  idêntico antes/depois do gate (04:59:25.894) — a suíte não toca mais
  o estado de produção.

### Deploy verde (regra 7.3) — 11:17:09, PID 3703628

| Verificação | Resultado |
|---|---|
| Código pushado ANTES | `5fcdd3b` (fix+testes) e `d0d0cba` (.gitignore) em `origin/master`, árvore limpa |
| Unidade | `active`, **NRestarts=0**, journal **0 erros** |
| Boot do notifier | `ProactiveNotifier habilitado \| health_ponte=True \| nrestarts=True \| disco_pct=85.0` |
| **Prova do desbloqueio** | **11:17:10 `Alerta proativo \| key=restart` — o PRIMEIRO em 35 dias** (2 s após o boot) + push FCM `enviados=1` no celular do dono |
| `data/notifier_state.json` pós-boot | **LIMPO**: `llm:offline: 3682439.017` e `restart: 3754164.292` **fora**; `router:down: 1229671.103` **preservado** (legítimo); `restart` regravado com o relógio novo (1253434.859) |
| `/health` | **ok · 20/20 · nenhum fora** |
| `/app/version` | **1.30.0 / 2060** (sem bump) |

### Canais e pendências

- `txt.txt` reescrito (regra 14) mantendo as 2 perguntas pendentes ao
  dono; Telegram resumo (regra 15); CHANGELOG §Infra + esta transcrição
  no commit de docs.
- **Fica de fora (não ordenado):** expor `alerts_emitted`/
  `alerts_blocked` no `/dashboard/stats` — melhoria opcional registrada
  no session.json.
- Próximo da fila §7 segue **(B) App auto-update + FCM** (ordem do
  dono); `analise/` com as 2 capturas do Órion ainda sem instrução.
