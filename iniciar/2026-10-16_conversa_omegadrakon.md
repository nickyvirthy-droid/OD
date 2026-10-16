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

## §6 — "exponha as métricas do notifier" — bloco no Status + card no painel

Dono pediu **"exponha as métricas do notifier"** (~11:30) — o item
(iii) que tinha ficado de fora do conserto por não ser ordenado na
hora. Backend/painel puro, **sem bump** (1.30.0/2060 intacto).

### O que mudou

| Peça | Entrega |
|---|---|
| `integrations/api/server.py` | `APIConfig.notifier` (None = bloco ausente, mesmo padrão `nomad_tools`) + bloco `payload["notifier"] = notifier.metrics.snapshot()` no `/dashboard/stats`: `ticks`, `checks_run`, `problems`, `alerts_emitted`, `alerts_blocked`, `errors`. |
| Card **"Alertas"** no `/admin` | Linha nova no `cards`: `X env · Y blq` (classe `err` quando `errors > 0`); o dump completo já existia no details "Métricas do orquestrador". |
| `runtime/launcher.py` | `notifier=` em `build_api_server` e `_run_api_forever`; o modo all passa a instância (fechamento tardio — construída antes do `gather`). |
| `tests/test_notifier.py` **+2** | `TestStatsDoNotifier`: bloco **ausente** sem notifier (JSON bruto também sem a chave) · bloco **exato** com notifier + `stats.notifier` no HTML do `/admin`. |

### Validação (antes de qualquer mutação)

- Gate oficial: **2968 passed / 16 skipped · cobertura 90,62%** (+2
  testes; 1 warning = pré-existente de `test_orchestrator.py`).
- pyflakes: **nenhum warning novo** — os 6 apontados em server/launcher
  foram conferidos contra o HEAD e são idênticos (pré-existentes).
- Guarda `node --check` do painel verde (`test_painel_pages_js_compiles`)
  — card compilado.
- Estado de produção intocado pelo gate (mtime 11:17:11 idêntico).

### Deploy verde (regra 7.3) — 11:38:58, PID 3724539

| Verificação | Resultado |
|---|---|
| Código pushado ANTES | `c63a4d0` em `origin/master`, árvore limpa |
| Unidade | `active`, **NRestarts=0**, journal **0 erros** |
| Boot | lento de **90 s** (cache do whisper frio após a suíte) — a 1ª coleta de provas (~11:39:40) rodou na janela de subida e viu curl vazio; **repetida após a subida completa (11:40:28)** |
| `ProactiveNotifier habilitado` | `health_ponte=True · nrestarts=True` |
| **`/dashboard/stats`** | bloco **ao vivo com números reais**: `notifier = {ticks: 2, checks_run: 32, problems: 4, alerts_emitted: 1, alerts_blocked: 2, errors: 0}` |
| `/admin` | card `"Alertas"` no HTML (3 × `stats.notifier`) |
| `/health` · versão | **20/20** · **1.30.0/2060** (sem bump) |
| `notifier_state.json` | `pid 3724539`; `restart 1253434.859` **preservado** (bloqueado pelo cooldown → não re-carimbado) |

### Leitura honesta dos números

- `alerts_blocked: 2` = o `restart` segurado pelo cooldown do alerta
  das 11:17 nos 2 primeiros ticks — **o anti-spam agora visível**.
- **Previsão pelo código** (L810-811 vs L829-830, não observada ainda):
  o bloqueio não marca `_restart_reported` → até **~12:18** o restart
  segue bloqueado a cada tick; quando o cooldown vencer, emite **uma
  única vez** o alerta atrasado "Sistema foi reiniciado" (evento
  verdadeiro do boot 11:38) e trava.
- `router:down` 11:41:28 = **5º blip do dia** (padrão 00:03 / 01:03 /
  03:00 / 04:41): ping falhou de verdade, push entregue; roteador **no
  ar** na conferência (3/3, 11,5 ms) — transitivo, sem relação com o
  deploy.
- `problems: 4` = (restart + router) × 2 ticks — fecha exato.

### Canais e pendências

- `txt.txt` reescrito (regra 14) mantendo as perguntas pendentes;
  Telegram resumo (regra 15); CHANGELOG §Infra + esta transcrição no
  commit de docs.
- Próximo da fila §7 segue **(B) App auto-update + FCM**; `analise/`
  com as 2 capturas do Órion ainda sem instrução.

---

## §7 — "faça o B agora. me explique o que é essa implementação" — item (B) ENTREGUE (v1.31.0+2061)

### O que é o item (B) (a explicação pedida, apurada no código antes de mexer)

A fila §7 do TODO diz **"App auto-update + FCM — UX do dono no
celular"**; no TODO §3.8 são dois checkboxes: **auto-update no app**
("download em background + install") e **Push FCM** ("conectar
notificações do servidor — auto-update aplicado, saúde, etc.").

Apuração antes de mexer mostrou que **~80% já existia**:

- **FCM de ponta a ponta desde 13/09** (`3b5599c`): `core/push.py`
  (registro de tokens + FCM HTTP v1) + app `push_service.dart`
  (permissão, exibição foreground/background, token registrado em
  `/push/register` no boot autenticado) — e o notifier já entregava
  alertas (health/router/nrestarts) no celular desde 15–16/10.
- **Updater v1.7.0 desde 27/09**: checagem automática no boot
  (`_checkUpdateBestEffort`) → banner → toque → download streaming com
  SHA-256 → instalação FileProvider (`ACTION_INSTALL_PACKAGE` —
  funciona no Android 14+ com a tela de confirmação do sistema); o
  celular do dono já viveu as trocas 2017→2060 por esse caminho.

**Duas lacunas reais** restavam — e só elas foram mexidas:

1. o **servidor** aplicava auto-update (Parte E) e o dono só via no
   journal: o celular nunca era avisado;
2. o **download do APK** só começava com toque no banner (dono tinha
   que estar na tela de atualização).

### O que foi feito

| Peça | Entrega |
|---|---|
| `core/auto_update.py` | `_anunciar()` — FCM **"Auto-update aplicado"** nos 2 sucessos do ciclo: re-sync do índice RAG (`… — N chunks (alvo)`) e download concluído/movido (`<alvo> aplicado (v) → destino`). Best-effort: `PushService.notify` nunca levanta + `try/except` — o ciclo **não morre por um aviso**; `push=None` = silencioso. |
| `runtime/launcher.py` | `build_auto_update(..., push=)` + call site `push=push` (`build_push()` construído ANTES no boot, L1631). |
| App `main.dart` | `_preDownload`: a checagem do boot **dispara o download sozinho** (banner "Baixando v… N%") → "baixada — pronta para instalar" → botão **Instalar** (sem rede). Rede fora = silencioso → banner cai no "Atualizar" (retry pelo toque) e o próximo boot tenta de novo. |
| App `od_updater.dart` | `download()` **reusa cache cujo SHA-256 confere** (2ª chamada = 0 requisições; divergente = apaga e rebaixa) + `httpClient` injetável — o binding do Flutter responde 400 em cliente HTTP real (o teste novo bateu nisso na 1ª tentativa; refiz com `MockClient`, padrão `od_api_test`). |
| versionCode | 2060 → **2061** (9/9: `.env`, capabilities, pubspec, `_APP_VERSION_CODE`, site ×4, CHANGELOG, README_VERSAO). |

### Validação

- Servidor: gate **2971 passed / 16 skipped · 90,64%** (+3 em
  `tests/test_auto_update.py` — anúncio no re-sync RAG, anúncio via
  evento público `tratar_evento`, push que levanta não derruba o ciclo;
  63 no arquivo).
- App: `flutter analyze` **0 issues** · `flutter test` **179 passed /
  2 skipped** (+2 do cache de download).
- pyflakes **idêntico ao HEAD** (7 avisos pré-existentes, **0 novos**) ·
  `node --check` verde (pelo teste do gate) · política **9/9** =
  1.31.0/2061.
- APKs rebuildados (`JAVA_HOME=~/jdk`): `versionCode 2061` + `versionName
  1.31.0` nos dois (aapt2), publicados 12:20. **Backup do 1.30.0/2060
  reconstruído** em `backups/apk-v1.30.0-2060/` (worktree no commit
  `e279151`): o build de hoje sobrescrevera os APKs do site sem backup —
  padrão da casa é backuper o anterior, refito com o artefato certo.

### Prova viva no serviço (deploy 12:23:30)

| Passo | Resultado |
|---|---|
| Boot | PID **3766943** · **NRestarts=0** · **0 erros** (único `[ERROR]` do dia = DNS do Telegram às 03:00, pré-existente). Boot lento (~4 min, event loop saturado pós-gate): porta 8000 LISTEN desde cedo, `/app/version` respondeu ao destravar — observado, não maquiado. |
| `/app/version` | **1.31.0 / 2061** com `sha256 3d3f6ccf…` **idêntico** ao `site/OmegaDrakon.apk` publicado |
| `/health` | **up · 20/20 checks** |
| Auto-update | `Auto-update tick \| alvos=1 \| aplicar=0 \| resumo=indice-rag=aguardar` — serviço de pé com a injeção `push=push` |
| **Prova de fogo do caminho novo** | `_anunciar()` REAL (com espião que repassa) → journal `Push enviado \| enviados=1 \| falhas=0 \| titulo=Auto-update aplicado` + resumo `{'ok': True, 'sent': 1, 'failed': 0, …}` — aviso **[PROVA DE FOGO B]** entregue no celular do dono |
| Métricas (regressão) | `/dashboard/stats` bloco `notifier` = `{ticks:3, checks_run:48, problems:4, alerts_emitted:0, alerts_blocked:3, errors:0}` · `/admin` `stats.notifier` ×3 |
| Alerta `restart` previsto na §6 | **Disparou UMA única vez às 12:17:33** + push (evento verdadeiro do boot 11:38 — previsão da §6 confirmada); o processo novo o segura de novo pelo cooldown (`alerts_blocked:3` = sem duplicata) |

### Canais e pendências

- CHANGELOG `## [1.31.0]` + README_VERSAO `### 3` + TODO §3.8 marcado
  `[x]` + fila §7 zerada; commits `0f9b871` (feat+bump, pushado) e
  `b9ff705` (comentário); docs e registro neste commit.
- `txt.txt` reescrito (regra 14, mantendo pendências) + Telegram
  (regra 15).
- Pendências do dono inalteradas: Órion (2 capturas sem instrução),
  Vaultwarden, repo público, pauta 3 e 5. Fila §7 **zerada** — próximos
  candidatos no §3: backup `.env`+`data/`, tema escuro/claro, métricas
  Prometheus.

## §8 — Retomada "leia iniciar" (~13:38) — sistema verde + 1 achado medido (alerta `restart` re-emite de hora em hora)

Retomada de rotina depois do deploy do item (B) (12:23:30). Nada foi
alterado no sistema — leitura e verificação.

| Verificação | Resultado |
|---|---|
| od-core | `active` desde 16/10 **12:23:30** · **MainPID 3766943** · **NRestarts=0** · journal **0 erros** no boot atual (único `[ERROR]` do dia = sink Telegram 03:00 / DNS, pré-existente em PID 3091063) |
| `/health` (OD_API_KEY) | **status=up** · **20 checks** · **nenhum fora** |
| `/app/version` | **1.31.0 / 2061** · sha `3d3f6ccf…` == `site/OmegaDrakon.apk` publicado |
| Git | **HEAD `02443de` == `origin/master`** (0 à frente) · sem resíduo rastreado; único untracked = `backups/backup_od_2026-10-16/` (backup, regra 9) |
| `txt.txt` | sem mensagem nova do dono (última escrita = nossa entrega do item B, 12:37) |
| `analise/` | inalterado — 2 capturas do Órion (01:39) + as 4 de `fotos-adicionais/` |
| `notifier_state.json` | **limpo** e regravado com o relógio do boot novo (mtime 13:17:40; `last_alerts = {router:down: 1258498.501, restart: 1260663.464}`) — o veneno de boot antigo não voltou e a suíte não toca mais o arquivo |
| `push_devices.json` | **1 token, vivo** (`d8Xhaf…crcY`, sent=53 / failed=3); a app re-registrou o MESMO token em 12:47 e 13:32 (FCM renovou — o zumbi podado em 15/10 não voltou) |
| `/dashboard/stats` | `notifier {ticks:72, checks_run:1152, problems:53, alerts_emitted:2, alerts_blocked:50, errors:0}` · `nomad_tools {9,9,[]}` |

### Achado medido (não é defeito — é comportamento, e a previsão da §6 estava errada)

O alerta `key=restart` **não trava após a primeira emissão**: ele **re-emite a
cada ciclo de cooldown** (`DEFAULT_COOLDOWN_S = 3600 s`) enquanto a condição
persistir. Prova nos números do processo atual:

| Horário | Evento |
|---|---|
| 11:17:10 | `Alerta proativo \| key=restart` (pós-fix do notifier) + push |
| 12:17:33 | idem (+ push) — previsão da §6 dizia que seria a última |
| 13:17:39 | idem (+ push, `enviados=1 falhas=0`) |

`alerts_emitted:2` + `alerts_blocked:50` no processo atual batem com isso:
restart é emitido, `_restart_reported` fica marcado só na emissão e o problema
segue **ativo** (restart não tem condição de recuperação que dê baixa, ao
contrário de `router:down`, que limpa quando o ping volta). **Efeito no dono:**
um push "Sistema foi reiniciado" **por hora**, indefinidamente.

**Refinamento proposto (aguardando ordem — nada aplicado):** alerta de restart
como **um-disparo-por-boot** (guardar o `started_at` já anunciado e não
re-emitir enquanto for o mesmo boot; 3 ticks = 1 alerta, boot novo = alerta
novo) com teste de regressão. Alternativa mínima: cooldown próprio maior
(6 h/24 h) só para `restart`.

### Estado

SISTEMA ESTÁVEL E NO AR — v1.31.0+2061, fila §7 zerada, notifier saneado, push
com token único vivo; **nada em andamento**. Pendências do dono: o refinamento
acima, as 2 capturas do Órion sem instrução, Vaultwarden, repo público/pauta/e
fotos. Registro em `session.json` (`reverificacao_2026_10_16_1338`).

## §9 — Reverificação "leia iniciar" (~13:47) — sistema verde confirmado de novo; 1 WARN transitório novo (transporte do bot)

Nova reverificação de rotina do dono **~10 min depois** da §8. Estado
**idêntico e verde**; único fato novo no journal é transitório.

| Verificação | Resultado |
|---|---|
| od-core | `active` desde 16/10 **12:23:30** (1h16min) · **MainPID 3766943** · **NRestarts=0** · journal **0 erros** desde o boot |
| `/health` (OD_API_KEY) | **status=up** · **20 checks** · **nenhum fora** |
| `/app/version` | **1.31.0 / 2061** · sha `3d3f6ccf…` (APK 55 508 516 B) == publicado |
| `/dashboard/stats` | `notifier {ticks:74, checks_run:1184, problems:53, alerts_emitted:2, alerts_blocked:50, errors:0}` · `nomad_tools {9,9,[]}` |
| Git | **HEAD `74c9325` == `origin/master`** (0 à frente) · único untracked = `backups/backup_od_2026-10-16/` (regra 9) |
| `txt.txt` | sem mensagem nova do dono (mtime 12:37 = nossa entrega do item B) |
| `analise/` | inalterado — 2 capturas do Órion (01:39) + `fotos-adicionais/` |

### Fatos novos desde a §8 (ambos transitórios, sem ação)

- **13:17:39/40** — 3ª re-emissão do alerta `restart` do dia + push
  entregue (`enviados=1 falhas=0`): comportamento horário já medido na
  §8; próxima prevista **~14:17**. Refinamento um-disparo-por-boot segue
  **aguardando ordem** (nada aplicado).
- **13:08:36 e 13:10:12** — 2× `Transporte indisponível — aguardando...`
  (WARN do polling do bot, `integrations/telegram/bot.py` L500:
  `TransportError` no `get_updates` → retry automático no loop) — mesma
  instabilidade transitória de rede dos `router:down` do dia (6º blip às
  12:41:34). Recuperou sozinho, sem perda de updates nem erro.

### Estado

SISTEMA ESTÁVEL E NO AR — v1.31.0+2061 (PID 3766943, NRestarts=0,
/health 20/20), fila §7 zerada; **nada em andamento**, aguardando ordem do
dono. Registro em `session.json` (`reverificacao_2026_10_16_1347`).

## §10 — "Aplique o refinamento do alerta restart: um-disparo-por-boot, com teste de regressão" — ENTREGUE

Ordem do dono (~13:45, logo depois da §8) sobre o refinamento proposto na
retomada das 13:38. **Backend puro → sem bump** (1.31.0/2061 intacto).

### Apuração antes de mexer (a previsão da §8 estava errada)

O journal de hoje, lido **por PID**, mostra que o alerta `restart` **já era
um por boot** (o `_restart_reported` sempre foi por processo) — o que
parecia "re-emissão de hora em hora" era o **atraso** de cada boot novo:

| Boot (PID) | Alerta `key=restart` | Atraso |
|---|---|---|
| 11:17:09 (3703628) | 11:17:10 | 1 s (imediato) |
| 11:38:58 (3724539) | **12:17:33** | **39 min** |
| 12:23:30 (3766943) | **13:17:39** | **54 min** |

Causa: o anti-spam de **1 h** do legado ficava armado pelo alerta do boot
anterior (`last_alerts["restart"]`, persistido) e segurava o aviso do boot
novo. Registro honesto: a §6/§8 previu que o alerta "travaria" após a
primeira emissão e a §9 chegou a projetar a próxima às ~14:17 — as duas
leituras estavam **erradas** e ficam corrigidas aqui pela medição.

### Entrega

- **`integrations/notifier.py`** — `RESTART_ALERT_GUARD_S = 300.0` +
  `NotifierConfig.restart_alert_guard_s` + `CheckResult.cooldown_s`
  (anti-spam próprio da sonda, que **vence** `config.cooldowns`).
  `_check_restart` passa a guarda de rajada: dedupe **por boot** (o
  processo) e boot novo alerta no **primeiro tick**; boot em cima de boot
  espera a guarda vencer e ainda assim emite **uma vez**. O crash loop
  continua com sonda própria (`systemd:nrestarts`, warn ≥1 / crit ≥3,
  anti-spam 1/h) — o sinal não depende mais deste alerta.
- **`tests/test_notifier.py` +3** — `TestAlertaDeRestartPorBoot`: (1) um
  disparo por boot que **não repete** em 2 h de ticks; (2) **regressão do
  atraso**: alerta do boot anterior há 40 min + `cooldowns["restart"] =
  3600` ⇒ o boot novo **emite no primeiro tick**; (3) **guarda de rajada**:
  boots a 10 s/70 s ficam bloqueados e o alerta sai uma vez aos 310 s, sem
  repetir depois. `test_config_defaults_match_legacy` ganhou a guarda de
  300 s; os 2 testes antigos que fixavam `cooldowns["restart"]` passaram a
  fixar `restart_alert_guard_s` (mesma intenção: cooldown determinístico).

### Validação

- Gate oficial: **2974 passed / 16 skipped · cobertura 90,62%**
  (+3 testes; 1 warning pré-existente de `tests/test_orchestrator.py`).
- pyflakes **limpo** nos 2 arquivos, idêntico ao HEAD.
- **Teste do teste (mutação):** remover o `cooldown_s` da sonda (volta o
  anti-spam de 1 h) derruba **2 dos 3** testes novos; revertido bit a bit,
  77 verdes em `tests/test_notifier.py`.

### Prova viva no serviço (deploy 13:50:39, PID 3846977)

| Passo | Resultado |
|---|---|
| Boot | 13:50:39 · **PID 3846977** · **NRestarts=0** · journal **0 erros**; notifier no ar às 13:54:48 (boot lento ~4 min, padrão da casa) |
| **O fix em ação** | **13:54:48** — `Alerta proativo \| key=restart` no **MESMO segundo** em que o notifier subiu (antes: o boot de 12:23:30 só alertou 13:17:39, 54 min depois) + push `enviados=1 falhas=0` |
| **Um disparo por boot** | 5 ticks depois (13:59:23): **1** alerta restart no processo, `/dashboard/stats` `notifier {ticks:5, checks_run:80, problems:2, alerts_emitted:1, alerts_blocked:0, errors:0}` — a repetição ~14:17 projetada na §9 **não acontece** |
| Regressão de estado | `/health` **up 20/20** · `/app/version` **1.31.0/2061** sha `3d3f6ccf…` (sem bump) · RAG no boot idempotente (`chunks=1666, novos=17, atualizados=654`) |

### Canais

- Commits `a69744c` (fix + testes) e `b9c6418` (CHANGELOG §Infra +
  TODO §3.6), pushados **antes** do restart; CHANGELOG **sem bump**.
- `txt.txt` reescrito (regra 14) + Telegram (regra 15).
- Pendências do dono inalteradas: 2 capturas do Órion sem instrução,
  Vaultwarden, repo público, pauta 3 e 5, fotos, catálogo 3D. Próximos
  candidatos do TODO §3: backup `.env`+`data/`, tema escuro/claro,
  métricas Prometheus do auto-update.

## §11 — "Implemente o backup automático do .env + data/ (TODO §3.6)" — ENTREGUE (sem bump)

Backend puro → **sem bump** (1.31.0/2061 intacto). Antes de escrever uma
linha, **três decisões do dono** (levantamento na conversa: `data/` = 314 MB,
sendo 304 MB só de capturas de 43 dias e 11 MB o índice do RAG; `rclone`/MinIO
ausentes; ~~disco a 85%~~ — **FATO ERRADO, corrigido em §12:** o `85.0` era o
**limite** configurado do notifier (`OD_DISK_THRESHOLD_PERCENT`), não o uso;
o disco real estava em **62%**):

| Pergunta | Resposta do dono |
|---|---|
| Destino | **Local** em `backups/auto/` — *"me avise que está pronto que transfiro para um HD externo ao servidor"* |
| Escopo | **`.env` + `data/` sem capturas e sem vetor** (só o irreconstruível) |
| Retenção | **03:00 · 3 diários + 8 semanais** |

### Entrega

- **`core/backup.py` (novo, 100% coberto)** — `avaliar()` **puro**
  (`desligado` → `antes_da_hora` → `ja_feito_hoje` → `disco_insuficiente`
  → `rodar`, com **catch-up** quando o servidor estava desligado no
  horário) + `BackupService` executor: tar.gz **determinístico** (gzip
  `mtime=0`/`filename=""`, uid/gid 0, membros ordenados), gravação atômica,
  **`0600`/`0700`** (leva o `.env`), estado JSON atômico, limpeza de `.tmp`
  órfão, retenção por **semana ISO** (3 diários + 1 por semana das 8 mais
  recentes; nome estranho nunca é apagado) e falha que **avisa no celular**
  (best-effort, cooldown de 6 h).
- **Visibilidade** — check `backup` **não crítico** no `/health`, bloco
  `backup` no `/dashboard/stats` e card **"Backup"** no `/admin` (JS
  `fmtBytes` novo).
- **Fiação** — `build_backup()`/`_run_backup_forever()` no launcher (loop
  supervisionado, tar em `to_thread`), knobs `OD_BACKUP*` (liga/desliga,
  hora, diários, semanais, intervalo, diretório, estado, exclusões) e
  `backups/auto/` no `.gitignore` (repo público + `.env` dentro).

### Validação

- `core/backup.py` **100%** (343 stmts) · gate oficial **3034 passed / 16
  skipped · 90,80%** (+60 testes) · pyflakes **idêntico ao HEAD** (6 avisos
  pré-existentes conferidos com `git stash`).
- **Teste do teste (mutação)**: guarda de disco, retenção semanal,
  exclusões do dono e aviso de falha — **4/4 capturadas**; reversão
  bit-exata ⇒ 60 verdes.

### Prova viva no serviço (deploy 14:16, PID 3871779)

| Passo | Resultado |
|---|---|
| Boot | `Backup automático no ar \| hora=03:00 \| raiz=backups/auto \| diarios=3 \| semanais=8 \| excluidos=data/captures,data/vector_memory` + `Loop de backup habilitado` (20 s) |
| **1º tick** | **Catch-up** rodou o snapshot de hoje: `Backup concluído \| arquivo=od-2026-10-16_1416.tar.gz \| membros=16 \| bytes=189686 \| sha256=392f7bd68863 \| duracao_s=0.15` |
| Artefato | `-rw------- backups/auto/od-2026-10-16_1416.tar.gz` (185 KB) · `drwx------ backups/auto` · **sha256 do arquivo == `ultimo_sha256` do estado** |
| Conteúdo | `tar -tzf` = **16 membros** (`.env` + 15 de `data/`), **nenhum** de `captures/`/`vector_memory/`, nenhum `.part`/`.pyc` — e o `.env` extraído é **byte-idêntico ao real** (`cmp` ok) |
| API | `/health` **up, 21 checks** (`backup`: *"Backup de hoje ok (od-2026-10-16_1416.tar.gz, 0.18 MB, há 0.0 h)"*, `critical: false`) · bloco `backup` completo no `/dashboard/stats` · card no `/admin` (`stats.backup` ×3) · `/app/version` 1.31.0/2061 · NRestarts=0, 0 erros |

### Canais

- Commits `2fd75ab` (código + testes + `.gitignore`) e `dd25e5d`
  (CHANGELOG §Infra + TODO §3.6), pushados antes do restart.
- `txt.txt` reescrito (regra 14) com o caminho do arquivo e **as
  instruções de cópia para o HD externo** + Telegram (regra 15).
- Pendências do dono: 2 capturas do Órion sem instrução, Vaultwarden, repo
  público, pauta 3 e 5, fotos, catálogo 3D. Próximos candidatos do TODO §3:
  tema escuro/claro, métricas Prometheus do auto-update — e, se ele quiser,
  ligar off-site (conta S3/MinIO/rclone à escolha dele).

## §12 — "Inclua data/captures no backup (semanal, para o HD externo)" — ENTREGUE (sem bump)

Backend puro → **sem bump** (1.31.0/2061 intacto). Fecha o escopo que ficou
de fora em §11 (às 14:16 o backup diário nasceu **sem** as capturas, por
decisão dele). Medido **antes** de escrever qualquer linha: `data/captures` =
**316 MB** (43 dias de fotos/vídeos) e o **gzip NÃO reduz** (316.016.667
bytes de 316.051.501 — mídia já comprimida), **10,7 s** para empacotar; logo
snapshot **próprio e semanal**, separado do diário do estado (316 MB todo dia
seria desperdício para um acervo append-only) e 4 semanas ≈ **1,3 GB**.

> **Correção de um fato errado meu (transparência):** em §11 eu registrei
> *"disco a 85%"* — é **falso**. O `85.0` do log era o **limite
> configurado** do notifier (`OD_DISK_THRESHOLD_PERCENT`, sonda
> `_check_disk`), não o uso. Medição direta hoje: `df` = **137G usados / 85G
> livres = 62%**. Corrigido em §11, no TODO §3.6 e no CHANGELOG §Infra.

### Entrega

- **`core/backup.py`** — tabela **`PERFIS`** (um código, dois trabalhos) +
  `cadencia_dias` generalizando `proxima_janela` (dia do último sucesso + N
  dias no HH:MM; **1 = diário, 7 = semanal**, catch-up preservado) +
  `prefixo`/`check_nome` por perfil. A retenção usa o prefixo: **nome de um
  perfil nunca é apagado pelo outro**.
  - `estado` — **INTOCADO**: 03:00, `backups/auto/`, prefixo `od`, `.env` +
    `data/` sem `captures`/`vector_memory`, 3 diários + 8 semanais, knobs
    `OD_BACKUP_*`.
  - `capturas` — **novo**: **04:00**, `backups/auto-capturas/`, prefixo
    `od-capturas`, só o `vector_memory` fora (reconstruível), **0 diários +
    4 semanas**, estado próprio (`data/backup_capturas_estado.json`), knobs
    `OD_BACKUP_CAPTURAS_*`.
- **Fiação** — `build_backup()` → **`build_backups()`**: uma lista de
  perfis, cada um com o **próprio loop supervisionado** e o próprio check
  no `/health` (`OD_BACKUP=0` / `OD_BACKUP_CAPTURAS=0` desligam um sem o
  outro). O tar (10,7 s) roda em `to_thread`; o aviso de falha diz **qual
  perfil** falhou.
- **Visibilidade** — 2 checks **não críticos** (`backup`, `backup_capturas`),
  bloco por perfil no `/dashboard/stats` e cards **"Backup"** e **"Backup
  fotos"** no `/admin`.
- **Segurança (achado no caminho)** — `.gitignore`: `backups/auto/` →
  **`backups/auto*/`**. O diretório novo **não estava ignorado**: o
  `git status` o listava como *untracked* e um `git add -A` subiria **316 MB
  das fotos do dono + o `.env`** (segredo) para o repo **público**. Fechado
  antes do commit; conferido com `git check-ignore` nos dois diretórios e no
  tar dentro deles.

### Validação

- `core/backup.py` **100%** (376 stmts) · gate oficial **3046 passed / 16
  skipped · 90,83%** (exit 0; **+12** sobre §11) · `tests/test_backup.py`
  **72** verdes · pyflakes **idêntico ao HEAD** (6 avisos pré-existentes).
- **Teste do teste (mutação)**: capturas fora das exclusões, cadência
  ignorada, prefixo ignorado e check único — **4/4 capturadas**.

### Prova viva no serviço (deploy 14:34, PID 3888045)

| Passo | Resultado |
|---|---|
| Boot | **Dois perfis**: `perfil=estado \| hora=03:00 \| raiz=backups/auto \| diarios=3 \| semanais=8 \| excluidos=data/captures,data/vector_memory` e `perfil=capturas \| hora=04:00 \| raiz=backups/auto-capturas \| cadencia_dias=7 \| diarios=0 \| semanais=4 \| excluidos=data/vector_memory` |
| **1º tick** | **Catch-up** rodou o snapshot **semanal**: `Backup concluído \| perfil=capturas \| arquivo=od-capturas-2026-10-16_1434.tar.gz \| membros=923 \| bytes=316276693 \| duracao_s=10.7` |
| Artefato | `-rw------- backups/auto-capturas/od-capturas-2026-10-16_1434.tar.gz` (**301,6 MiB**) · pasta `drwx------` · **sha256 do arquivo == `ultimo_sha256` do estado** |
| Conteúdo | `tar -tzf` = **923 membros**: **906** de `data/captures/` + `.env` + estado/estatísticas, **0** de `vector_memory/`, nenhum `.part`/`.pyc` — **uma foto extraída é byte-idêntica** ao original (`cmp` ok) e o `.env` também |
| Disco | **85 GB livres (62%)** — o semanal não muda nada de escala |
| API | `/health` **up, 22 checks** (`backup`: *"Backup do estado ok de hoje (…, 0.18 MB, há 0.3 h)"*; `backup_capturas`: *"Backup das capturas ok da semana (od-capturas-2026-10-16_1434.tar.gz, 301.62 MB, há 0.0 h)"*; ambos `critical: false`) · `/dashboard/stats` com cadência **1** (estado) e **7** (capturas) · `/admin` cards **"Backup"** e **"Backup fotos"** · `/app/version` 1.31.0/2061 · NRestarts=0, 0 `[ERROR]` |

### Canais

- Commit `ac726de` (código + testes) e o commit de docs (CHANGELOG §Infra +
  TODO §3.6 + esta §12 + `.gitignore`), pushados.
- `txt.txt` reescrito (regra 14) com **o caminho dos dois arquivos** e o
  comando de cópia para o HD externo + Telegram (regra 15).
- Pendências do dono: 2 capturas do Órion sem instrução, Vaultwarden, repo
  público, pauta 3 e 5, fotos, catálogo 3D. Próximos candidatos do TODO §3:
  tema escuro/claro — e, se quiser, off-site (conta S3/MinIO/rclone à
  escolha dele), que é o que transforma este backup em proteção contra
  morte de disco.

## §13 — "vamos continuar" → escolha da fila: **Métricas Prometheus do auto-update** (TODO §3.2) — ENTREGUE (sem bump)

A fila §7 estava zerada e nada em andamento; perguntei por onde seguir com
os candidatos reais (tema escuro/claro, backup off-site, métricas
Prometheus, ProtoMaps) e o dono escolheu as **métricas Prometheus do
auto-update**. Backend puro → **sem bump** (1.31.0/2061 intacto).

O TODO §3.2 pedia `auto_update_tick_total`, `auto_update_aplicado_total` e
`auto_update_falha_total`. Os nomes saem com **prefixo `od_`** porque
**toda** métrica do `MetricsCollector` o leva (`od_processed_total`,
`od_audit_total`, `od_api_requests_total`) — `od_auto_update_tick_total` é
o **mesmo número** pedido, e o teste fixa essa equivalência.

### Entrega

- **`core/auto_update.py`** — `MetricasAutoUpdate` (dataclass `slots`, o
  padrão do `NotifierMetrics`) contada **onde o fato acontece**:
  `ticks`/`ticks_dry_run`, decisões (`decisao_aplicar`/`aguardar`/`pular`),
  `aplicados` (o que **concluiu**: re-sync do RAG ou download
  verificado/movido), `falhas` (só **DURA**), `auto_desligados` (na
  **transição**, não a cada falha), `rag_syncs`, `downloads` (novos),
  `dedups` (enqueue que a fila já tinha — **não é falha**) e `erros`
  (exceção contida no consumidor de eventos).
- **`prometheus_lines()`** — text exposition format: contadores **desde o
  boot** (zerar no restart é o esperado; `rate()`/`increase()` compensam) +
  gauges do estado **persistido** (`alvo`, `alvo_desabilitado`,
  `download_pendente`) + `ultimo_tick_segundos`, que **não é inventado como
  zero** antes do primeiro ciclo. Estado ilegível ⇒ devolve só os
  contadores (o render do coletor nunca morre por uma fonte).
- **`runtime/launcher.py`** — `ligar_metricas_auto_update(metrics, svc)`:
  fonte viva ligada **tarde de propósito** (o coletor nasce em
  `build_metrics`, o `/health` depende dele; o auto-update só existe
  depois) e **best-effort** (sem coletor/serviço devolve False).
- **API** — os MESMOS números (fonte única: `svc.metricas.snapshot()`) no
  bloco `auto_update` do `/dashboard/stats`, no GET/dry-run do
  `/admin/auto-update` e numa linha do card do painel.
- **Decisão registrada:** **sem `skip_total`** — nenhum caminho usa
  `_registrar_falha(dura=False)` hoje, e métrica que nunca sai de zero só
  confunde quem lê o painel. O docstring diz isso.

### Validação

- Gate oficial **3057 passed / 16 skipped · 90,87%** (exit 0; **+11**) ·
  `tests/test_auto_update.py` **74** verdes · `core/auto_update.py` **95%**
  (os 25 faltantes são pré-existentes; **todo** o código novo coberto) ·
  pyflakes sem aviso novo (só o **deslocamento de linha** do `plugins` do
  launcher).
- **Teste do teste (mutação)**: 6/6 capturadas — ciclos removidos,
  `aplicados` do RAG removido, dedup somado como download, auto-desligado
  não contado, **idade inventada como 0** e troca `aguardar`/`pular`.
- O `node --check` do JS do painel roda nos testes do `/admin` (node
  presente): a linha nova do card é JS válido.

### Prova viva no serviço (deploy 15:20:20, PID 3935938)

| Passo | Resultado |
|---|---|
| Boot | `Métricas do auto-update no /metrics (TODO §3.2)` · primeiro tick real `alvos=1 \| aplicar=0 \| resumo=indice-rag=aguardar` |
| **`/metrics`** | Família nova no scrape: `od_auto_update_tick_total 1` · `od_auto_update_decisao_total{decisao="aguardar"} 1` · `od_auto_update_alvo 1` · `od_auto_update_alvo_desabilitado 0` · `od_auto_update_download_pendente 0` · `od_auto_update_ultimo_tick_segundos 32.915` (= **o mesmo tick** do journal, 32,9 s antes) |
| **Sem regressão** | 42 linhas no total, com `od_audit_total 13006`, `od_uptime_seconds 41`, `od_api_requests_total 26`, `od_processed_total 0` — a fonte nova é aditiva |
| `/dashboard/stats` | `auto_update.metricas` = `{ticks: 1, decisao_aguardar: 1, …}` — **idêntico** ao scrape |
| `/admin` | Card com a linha de contadores (`id="au-metricas"`, `od_auto_update_` ×2) |
| Saúde | `/health` **up, 22 checks**, nenhum fora · `/app/version` 1.31.0/2061 · NRestarts=0 · **0 erros** no journal |

### Canais

- Commit `825a033` (código + testes; pushado **antes** do restart) e o
  commit de docs (CHANGELOG §Observabilidade + TODO §3.2 + esta §13 +
  `session.json`), pushados.
- `txt.txt` reescrito (regra 14) + Telegram (regra 15).
- Pendências do dono: 2 capturas do Órion sem instrução, copiar os
  snapshots do backup para o HD, off-site do backup, Vaultwarden, repo
  público, pauta 3 e 5, fotos, catálogo 3D. Próximos candidatos do TODO §3:
  tema escuro/claro (única pendência do §3.8) e ProtoMaps.

## §14 — "leia iniciar" (~16:38) — entrega do TEMA (v1.32.0+2062) estava no ar mas SEM registro; fechada

O dono mandou "leia iniciar" e a reverificação achou algo novo: **o sistema
estava rodando uma entrega que ninguém registrou**. O `session.json` parava
nas métricas Prometheus (§13, 15:30), mas o `git log` mostrava `7423e8e
feat(tema): tema claro/escuro sincronizado no app, site e painel (TODO
§3.8)` (16:31, já com push) e o serviço tinha reiniciado 16:32:16. Sessão
anterior (a do tema) foi **interrompida no meio do fecho** — provavelmente
limite de uso — depois do deploy e antes do registro.

### O que já estava pronto e provado (da sessão interrompida)

- **Código commitado e pushado** (`7423e8e`, 15 arquivos, +1306/−35):
  `user_prefs` + `GET/PUT /profile/preferences` + `preferences` no
  `/auth/me` (servidor), `theme_service.dart`/card Tema no app, paleta +
  botão injetados no site (`od.css`/`od-nav.js`) e no painel (`_com_tema()`),
  bump 9/9 **1.32.0/2062** e testes (+17 servidor, +13 app).
- **Deploy feito**: APKs publicados 16:27, backup do par anterior em
  `backups/apk-v1.31.0-2061/`, restart verde 16:32:16 (PID 4007853,
  NRestarts=0, 0 erros; RAG idempotente chunks=1708).
- **O que FALTAVA (feito nesta troca)**: commit dos docs (estavam
  modificados e não commitados), `session.json`, esta transcrição,
  `txt.txt` e o Telegram. Achado durante o conserto: o `README_VERSAO.md`
  estava com o **título `## [1.31.0]` engolido** (o corpo do 1.31.0 ficou
  órfão de cabeçalho) — re-insiro junto com a seção de prova viva do
  1.32.0, que o CHANGELOG pedia ("Abaixo (pós-deploy)") mas não existia.

### Provas vivas coletadas agora (16:38–16:45)

| Passo | Resultado |
|---|---|
| `/app/version` | **1.32.0 / 2062**, `sha256 b5b4ed31…` == `site/OmegaDrakon.apk` (55.656.288 B) |
| `aapt2` dos dois APKs | `versionCode 2062` cruro + `versionName 1.32.0` |
| Guarda da política | `tests/test_version_policy.py` **9 passed** (re-executada) |
| `/health` | **up · 22 checks**, nenhum fora |
| Tema no painel | `/dashboard` servido com a injeção — marca `odTema` ×6 no HTML |
| Tema no site | `od-nav.js` com `.nav-tema` + `od_theme` (2 marcas) |
| Journal | 0 `[ERROR]` desde o boot; alerta `key=restart` 16:36:04 (um-disparo-por-boot, mais uma vez confirmado) |
| Git | `7423e8e` == `origin/master` antes desta troca; docs fechados em `132b458` e pushados |

### Estado ao fechar

v1.32.0/2062 no ar (PID 4007853), fila §7 zerada, **nenhum candidato
técnico aberto no §3** — as pendências vivas são todas do dono (cópia dos
2 snapshots para o HD externo, off-site do backup, capturas do Órion sem
instrução, Vaultwarden, repo público, pauta 3 e 5, fotos, catálogo 3D).

## §15 — "revise os temas, não estou vendo diferença" — diagnóstico ao vivo + página de prova clicável

Dono não viu diferença do tema. Revisão completa SEM mexer no que estava
certo (regra: código antes de suposições):

### O que foi provado como FUNCIONANDO (no serviço em execução)

- **Assets do site**: `GET /site/od.css` e `/site/od-nav.js` respondem
  200 e o corpo é **byte-idêntico ao disco** (md5 conferido) com o tema
  novo (3 ocorrências de `data-theme` no CSS, `nav-tema` no JS).
  `Cache-Control: max-age=60` + ETag — cache do navegador não segura
  versão velha por mais de 1 min.
- **Painel**: `/dashboard` servido com a injeção (`odTema` ×6), paleta
  clara nas DUAS portas, **0 `!important`** que anule, nenhuma reescrita
  de header que apague o botão depois de montado.
- **Lógica do site** (od-nav.js linhas 79-205): ciclo system→light→dark
  correto; `system` remove `data-theme` e a porta `@media
  (prefers-color-scheme: light)` pinta; `dark` se protege pelo `:not`.
- **Lógica do painel** (`_com_tema` + `_TEMA_PAINEL_JS`): idempotente,
  aplica `data-theme` concreto, sincroniza com `/auth/me`.
- **App**: wiring conferido no código (`theme_service.dart`,
  `main.dart` com `ValueListenableBuilder`, card Tema nos Ajustes).

### O achado REAL (por que ele não vê diferença)

- **O celular dele está em 1.31.0**: desde o deploy (16:32) houve
  **0 requisições a /app/version** — o app dele nunca soube do 1.32.0,
  logo **não existe tema no app** (é lá que ele provavelmente está
  olhando; o tema no app só existe após instalar o 2062).
- O botão do site/painel existe, mas é discreto (caixa 42px ao lado do
  ⋮) — pode ter passado despercebido.
- 429 que apareceu numa checagem minha = rate limit (30 req/min/IP)
  estourado pelas PRÓPRIAS batidas de diagnóstico, não defeito: 0
  `od_rate_limited_total` no processo atual.

### Entrega nova (commit a7a6520)

- **`site/teste-tema.html`** (página de prova clicável): 3 botões
  GRANDES (☀️ Claro / 🌙 Escuro / 🌗 Seguir o aparelho) que usam as
  MESMAS linhas do botão real (localStorage `od_theme` + `data-theme` +
  `colorScheme`) e 3 amostras de cor ao vivo mostrando o rgb COMPUTADO
  do fundo/texto/cartão enquanto a página pinta + status do tema e se a
  sessão está sincronizada com o perfil. `node --check` verde;
  `tests/test_api.py` 146 passed (a guarda das páginas do site é
  glob-based, a página nova entra sozinha).
- `txt.txt` reescrito com o diagnóstico e o passo a passo (site: botão
  ao lado do ⋮; prova: digitar `/site/teste-tema.html`; app: instalar o
  1.32.0 via banner → Ajustes → Tema). Telegram enviado.

### Estado

v1.32.0/2062 no ar, tema provado no servidor; **aguardando o dono testar**
(site botão ⋮ / página de prova) e **instalar o update no app** — e
dizer onde ele estava olhando para fechar o diagnóstico.

## §16 — "pelo app está ok, já no site as vezes funciona" — CICLO DO BOTÃO CONERTADO (clique morto)

Dono confirmou: app ok (1.32.0 instalado, tema funcionando); no site,
**às vezes** funciona. Apuração no código achou a causa exata — não é
intermitência de rede, é um **clique morto por construção**:

### Causa raiz (medida, não deduzida)

O ciclo do botão é `system → light → dark → system`. Dois dos seis
transições resolvem para a MESMA cor da tela atual:

- aparelho ESCURO, tema 'escuro' → próximo passo "segue o aparelho" →
  resolve **escuro** = tela igual (clique "não faz nada");
- aparelho CLARO, tema 'system' (tela clara) → próximo passo "claro" →
  resolve **claro** = tela igual.

Ou seja: dependendo de onde o ciclo estava e da cor do aparelho, um
clique não mudava nada visualmente — "às vezes funciona" explicado
inteiro. (O ícone do botão muda 🌗/☀️/🌙, mas é discreto demais para
ser lido como feedback.)

### Correção (commit 5053c54)

- `site/od-nav.js` → `temaProximo(pref)`; `integrations/api/server.py`
  (_TEMA_PAINEL_JS) → `proximoTema(pref)`: se o próximo estado resolve
  para a **mesma cor** do atual, **pula para o seguinte** — todo clique
  pinta. Os 3 estados continuam válidos (o app tem o rádio completo e
  "segue o aparelho" segue sendo o padrão de quem nunca escolheu); no
  site o atalho só nunca para em tela igual.
- **Teste comportamental de verdade** (não substring): harness de node
  com DOM de mentira que RODA o `od-nav.js` e o `_TEMA_PAINEL_JS`
  embutido e **clica o botão** — 4 testes novos em `TestTemaClaroEscuro`:
  aparelho escuro saindo de 'dark' → 1º clique já vira 'light' e todos
  os cliques seguintes mudam a tela; aparelho claro saindo de 'system' →
  1º clique já vira 'dark'; idem no painel; `node --check` do JS do
  painel. (Harness exigiu `removeAttribute` no stub — achado ao rodar.)

### Teste do teste (mutação)

- Reverter `temaProximo` → `TEMA_CICLO[...]` no site: **2 testes
  falharam**; reverter `proximoTema` no painel: **1 teste falhou**;
  reversões bit-exatas (md5 conferido) → 10/10 verdes de novo.

### Validação e deploy

- Gate oficial: **3078 passed / 16 skipped**, exit 0 (+4 testes).
- pyflakes: 0 aviso novo (os 3 do server são os imports pré-existentes;
  o do test_api.py na L2118 também é pré-existente).
- Commit `5053c54` pushado ANTES do restart; restart verde ~17:47
  (regra 7.3): PID 4079685, NRestarts=0, **0 erros**, boot lento ~4 min
  (padrão pós-gate), `/health` **up 22/22**.
- PROVA VIVA: `/site/od-nav.js` servido com `temaProximo` (×2) — o site
  já estava no ar ANTES do restart (arquivo lido do disco a cada
  requisição); `/dashboard` servido com `proximoTema` (×2); versão
  intacta **1.32.0/2062** (backend puro, sem bump).

### Estado

Corrigido e no ar. Site: todo clique no botão (ao lado do ⋮) muda a
tela; painel idem. App intocado (ok nas palavras do dono). Aguardando o
dono testar o site de novo.

---

## §17 — "leia iniciar" (~19:43) + "por que está demorando?" — reverificação de rotina

Reverificação pós-conserto do tema (§16). Tudo verde e medido:

- od-core active desde 17:51:09 (1h52), MainPID 4079685, NRestarts=0,
  journal 0 [ERROR] desde o boot.
- /health status=up, 22 checks, nenhum fora.
- /app/version 1.32.0/2062 sha b5b4ed31… == APK publicado (55.656.288 B).
- git HEAD 7b4ccb7 == origin/master (0 à frente); único untracked =
  backups/backup_od_2026-10-16/ (dado de backup — regra 9, intocável).
- txt.txt sem mensagem nova do dono (última escrita nossa 17:57).
- analise/ inalterado (2 capturas do Sistema Órion 01:39 + fotos-adicionais/).
- /dashboard/stats: notifier {ticks:110, checks_run:1760, problems:3,
  alerts_emitted:2, errors:0} · nomad_tools {9,9,[]}.

Fato novo transitório: 18:31:54 router:down (warn) — 1 blip de ping ao
192.168.0.1, padrão intermitente já registrado desde 15/10; sem ação.
Auto-update ticks normais (aguardar).

Dono perguntou "por que está demorando?" durante a coleta — explicado:
eram as conferências reais do servidor; registro concluído na sequência.

### Estado

Sistema estável e no ar (v1.32.0+2062). Conserto do tema no ar desde
17:51. Aguardando o dono testar o site (botão ao lado do ⋮) e dizer.
