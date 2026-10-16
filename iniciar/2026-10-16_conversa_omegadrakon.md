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
