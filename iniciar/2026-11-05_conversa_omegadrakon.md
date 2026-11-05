# 2026-11-05 — conversa OmegaDrakon

> Sessão contínua de 04/11 (§1 a §9 em
> `iniciar/2026-11-04_conversa_omegadrakon.md`). Este arquivo começa em
> 05/11 15:45.

## §1 — "leia iniciar" + duas perguntas no meio (05/11 15:45–17:00)

### 1. O pedido

1. *"leia iniciar"* (15:45) — reverificação de rotina (regra 3). Checkpoint
   anterior: `recado_no_ar_cooldown_chaves_2026_11_04` (04/11 19:15).
2. No meio da leitura: *"porque o resto das musicas da lista do legiao
   urbana não foram baixadas?"*.
3. Logo depois: *"existem musicas muito longas na lista, varias em um só
   arquivo, não gosto disso, prefiro separadas. vamos analisar essas também
   para saber o que vou fazer"*.

### 2. Estado medido (só leitura, antes de qualquer mudança)

- **Git:** `HEAD 78b0916 == origin/master`, árvore limpa (0 resíduos; a
  sessão das 01:00–02:00 fechou §8/§9 e publicou).
- **Serviço:** `od-core` **active** desde 05/11 01:47:20, `MainPID 2014305`,
  `NRestarts=0` (~14 h), 899 MB.
- **Health:** `ok=true status=up` (autenticado). **Journal** desde 04/11
  19:00: **0 `[ERROR]`/`[CRITICAL]`** e 54 `[WARN]` (o ruído de sempre:
  feeds RSS, clima, transporte).
- **Versão:** 1.44.0/2080, sem bump.

### 3. Por que o resto da lista do Legião Urbana não baixou (medido)

- O pedido `id=8` (05/11 03:41, playlist
  `PLk_SH7F8Y60WEjS87AGhEPBNvyjd3lvxh`) tocou a primeira faixa
  (`Tempo Perdido`) e disparou o "resto da lista".
- `logs/radio_link_8.log`: a extração viu **97 entradas**; baixou até a
  **6ª** (`[6/97] Antes Das Seis`, 04:01:53) e às **04:03:50** morreu com
  `[NICKY][WARN] download do resto da lista falhou | error=TimeoutExpired`
  — exatamente 20 min depois do início (03:43:50), que é o
  `TIMEOUT_PRIMEIRA=1200` do **download único**.
- **Causa raiz:** `_baixar_resto()` chamava `rodar(urls)` sem timeout;
  `rodar_pipeline` caía no default `TIMEOUT_PRIMEIRA`. O lote de 96 faixas
  (3 min de `DOWNLOAD_DELAY` cada ≈ 5 h) nunca caberia em 1200 s. O
  `except` só escrevia um `[WARN]` — o dono não era avisado, e as 5 faixas
  já baixadas ficaram presas em `/tmp/od_link_2z1h3l5i` sem entrar no
  acervo.
- **Correção:** resto em **lotes de 10**, cada lote com
  `timeout_do_lote()` (300 s/faixa, piso 1200 s, teto `TIMEOUT_RESTO`);
  lote que falha não derruba os seguintes; aviso ao dono com a contagem de
  lotes e falhas. +3 testes (41 no módulo); gate **4169/16/0**.
- **Recuperação:** as 5 faixas órfãs + `Tempo Perdido` foram processadas
  pelo pipeline oficial com `TEMP_DIR` apontando para o `/tmp` (acervo
  **267 → 273**). O `/tmp` foi removido (0 resíduo).

### 4. Achado colateral: Gemini com chave inválida

- As 6 faixas recuperadas nasceram `Desconhecido - <título>`: o
  `musica.py` chamou o Gemini e recebeu **400 `API_KEY_INVALID`** (não é
  cota — testado também em `gemini-2.5-flash`, mesma resposta).
- Corrigido à mão no acervo (evidência: a lista é *"Todas as músicas do
  Legião Urbana"* e os 6 títulos são faixas da banda): `TPE1=Legião
  Urbana`, `TIT2` do título, arquivo renomeado, `acervo.db` reindexado
  (273, 0 `Desconhecido`), `.m3u` regerados, AzuraCast sincronizado.
- **Consequência para o resto da lista:** sem chave válida, as ~90 faixas
  restantes entrariam todas como `Desconhecido`. É decisão do dono trocar
  a chave (`GEMINI_API_KEY` do `.env`) antes de retomar.

### 5. Análise das faixas longas ("várias em um só arquivo")

Varredura do `acervo.db` (273 faixas, 25,2 h): **42 têm ≥ 7 min**, mas só
**11** são candidatas a "várias músicas no mesmo arquivo". Medição com
`ffmpeg silencedetect` (-30 dB, 1,2 s) e `ffprobe` (capítulos):

| Duração | Arquivo | Silêncios | Leitura |
|---|---|---|---|
| 77:29 | Fernandinho — Louvores que Tocam o Coração / Todas as Coisas, Não Mais Escravos e Mais | 8 emendas (13:39, 20:37, 25:59, 32:49, 38:06, 62:36, 67:52, 71:10) | **compilação real**; blocos de 13:39 / 6:58 / 5:21 / 6:50 / 5:17 / **24:30** / 5:15 / 3:18 / 6:18 — o bloco de 24:30 não tem pausa detectável |
| 40:18 | Blues Gospel — Ele Perdoou Antes do Pedido | 12 emendas, várias de 5–20 s | mix contínuo; os cortes por silêncio geram fragmentos (0:05, 0:18, 0:20) — **não separa sozinho** |
| 17:33 | Mantra da Prosperidade — Eu Recebo Dinheiro… | 0 | é uma faixa única (mantra), não várias músicas |
| 14:54 | Julliany Souza — Lindo Momento | 0 | faixa única longa |
| 8:55 | Eyshila e Dani Ferber — Aguenta Firme / Na Eternidade | 0 | medley **emendado** (sem pausa) |
| 8:49 | Morada — Só Tu És Santo / Uma Coisa / Deixa Queimar / Quando Ele Vem | 1 | medley emendado (4 músicas) |
| 8:43 | Casa Worship — Yeshua + Espontâneo | 2 | parte + espontâneo |
| 8:32 | Fernanda Madaloni — Maranata / Oh Quão Lindo / Pra Sempre (Medley) | 1 | medley emendado |
| 7:57 | Fhop Music — Tu És + Águas Purificadoras | 1 | medley emendado |
| 7:26 | Juliano Son — Lindo És + Só Quero Ver Você | 1 | medley emendado |
| 7:23 | Morada — É Tudo sobre Você / Ser Mudado | 1 | medley emendado |

- **Nenhum** desses arquivos tem capítulos (`ffprobe` = 0 em todos).
- Conclusão honesta: **cortar por silêncio só funciona na compilação do
  Fernandinho** (e ainda sobra um bloco de 24:30). Os medleys gospel são
  emendados de propósito — o corte automático cairia no meio da música.
- Caminhos possíveis (decisão do dono): (a) tirar do acervo as 2 peças
  grandes (77 e 40 min) para `removidas/`, como foi feito com a compilação
  da Kailane; (b) cortar por **marcas dadas por ele** (timestamp por
  música) — o corte é mecânico e as tags são preenchidas no mesmo passo;
  (c) cortar só o que o silêncio resolve e revisar faixa a faixa;
  (d) deixar como está e só não tocar essas faixas na rádio.

### 6. O que NÃO foi feito (de propósito)

- **Não retomei** o resto da lista (91–93 faixas, ~5 h): depende da decisão
  dele sobre as faixas longas e da chave do Gemini.
- **Não implementei** a lista de cantores indesejados do `txt.txt`
  (recado de 05/11 04:34, exemplo *Annita*): é feature nova, com decisões
  em aberto (onde ele preenche a lista, o que acontece com faixas já no
  acervo e o "baixa, toca para ele e depois deleta").
- **Sem restart:** `radio_link.py` é importado por um processo novo a cada
  pedido e `server.py` não mudou.

### 7. Fila

1. **Decisão sobre as faixas longas** (tabela acima: reter, cortar por
   marcas, cortar por silêncio ou remover as 2 grandes).
2. **Chave do Gemini** inválida — pedir a nova para o pipeline voltar a
   nomear as faixas.
3. **Retomar o resto da lista** depois de (1) e (2).
4. **Cantores indesejados** (txt 05/11 04:34): definir onde a lista mora e
   o comportamento (toca uma vez para quem pediu e sai).
5. Restos antigos: 19 faixas em `para_analisar/` aguardando artistas.

## §2 — "leia iniciar" de novo + a chave do Gemini + limpeza das pastas (05/11 19:20–19:50)

### 1. O pedido

1. *"leia iniciar"* (19:20) — terceira reverificação do dia (regra 3, só leitura).
2. No meio: *"você consegue criar outra chave do gemini? a minha só funciona no
   modelo gemini-3-flash-preview, não adianta tentar outro, já fizemos isso
   antes, pode colocar como regra pra não perder tempo"*.
3. Depois, três autorizações de limpeza: *"pasta reprovadas pode ser apagada"*,
   *"pasta removidas tambem pode ser apagada"* e *"para_analisar também pode
   apagar, melhor baixar novamente depois"*.

### 2. Estado medido da reverificação

- **Git:** árvore limpa, `HEAD 5e94c5b == origin/master` (o trabalho das
  15:45–17:00 foi publicado; 0 resíduos).
- **Serviço:** `od-core` active desde 05/11 01:47:20, `MainPID 2014305`,
  `NRestarts=0` (~17 h), 721 MB.
- **Health:** `ok=true status=up`, **25/25** checks, nenhum fora.
- **Journal** 04/11 19:00 → 05/11 19:20: **0 `[ERROR]`/`[CRITICAL]`**, 62
  `[WARN]` (33 RSS G1 quebrado, 15 transporte indisponível, 2 snapshot HD).
- **Versão:** 1.44.0/2080, sha `aeb8566b` — sem bump.
- **Borda:** Funnel `/` 200; `/radio.mp3` **206** pelo Funnel e pelo icecast
  (`127.0.0.1:8600`); `/api/radio/agora` 200 tocando *Leandro Soares —
  Todavia Me Alegrarei* (curiosidade real do banco), próxima *Midian Lima —
  Jó*. Portas LAN no `.205`: 8090/8100/8200/8400/8410/8430/8470 = 200,
  8420 = 302, 8480 = 404 na raiz (normal), `/books` na 8430 = 200.
- **Acervo:** 273 mp3, `acervo.db` 273 linhas, 0 `Desconhecido`, 8 do Legião;
  AzuraCast com 275 mp3 = 273 + 2 locuções.
- **Vigia:** tick 19:14:25, 28 dispositivos, 4316 ciclos, `pendentes_novos []`
  e `pendentes_seguranca []`.
- **Pedidos:** 8 no banco, 0 pendentes. Achado pequeno: `id=9` (15:15,
  *Tempo Perdido*) já `tocada` — pedido feito depois do recorte das 17:00 e
  que não precisou baixar (faixa já no acervo).
- **Falso alarme evitado:** `.od_pipeline.lock` com 0 byte e mtime 03:43 (hora
  em que o download da lista morreu) **não** é trava órfã — é `flock`, morre
  com o processo (`integrations/radio_link.py:31`/`:65`).
- **Nota honesta:** 8443 não escuta; o `/books` vivo é a 8430. Não é defeito.

### 3. A chave do Gemini: não era a chave, nem o modelo

Medido com a **mesma** chave do `.env`:

| Forma | Modelo | Resultado |
|---|---|---|
| `?key=` na URL | `gemini-3-flash-preview` | **400 API_KEY_INVALID** |
| header `x-goog-api-key` | `gemini-3-flash-preview` | **200** (resposta válida) |
| header `x-goog-api-key` | `GET /v1beta/models` | **200** (lista modelos) |

O `musica.py` já usava `gemini-3-flash-preview` desde antes — o que quebrou foi
a **autenticação na query string**. Por isso as 6 faixas recuperadas nasceram
`Desconhecido`: não era cota, não era chave morta, não era modelo.

- **Correção:** `musica.py` **v1.9.0 → v1.9.1** (backup
  `backups/musica-v190-antes-header-20261105.py`): `chamar_gemini()` sem
  `?key=` e com `headers={"x-goog-api-key": ...}`; `_sem_chave()` mantida como
  blindagem de log; topo/doc e `doc/README.md` com a seção da v1.9.1.
- **Prova viva:** `venv` do acervo chamando `musica.chamar_gemini()` de
  verdade → `['/x/faixa.mp3 | Legião Urbana | Tempo Perdido']` (antes `[]`).
  `py_compile` OK; o venv do acervo não tem `pyflakes`.
- **Sem restart:** `radio_link.py` não fixa `env=`, herda `GEMINI_API_KEY` do
  `od-core`, e o `musica.py` roda em processo novo a cada pedido.
- **Chave nova:** não é necessária e eu não consigo criar uma (isso exige
  login na conta Google do dono).
- **Regra:** `iniciar/RULES.md` **regra 19** — toda chamada começa pelo
  `gemini-3-flash-preview`; outros modelos podem ser testados **depois** dele,
  sem substituí-lo como padrão (ajuste do dono na mesma troca: *"pode sim
  testar outros modelos, mas deve sempre começar pelo que indiquei, esse foi o
  que funcionou pra mim"*); autenticar por header; e "`API_KEY_INVALID` não
  significa chave morta".

### 4. Pastas apagadas (ordem do dono)

Inventário salvo em `/home/alex/dados/musicas/logs/remocao_autorizada_20261105.txt`
(30 linhas, nome e tamanho de cada arquivo):

| Pasta | Conteúdo | Tamanho |
|---|---|---|
| `reprovadas/` | 2 curtas (*Pr. Lucas — Pintor Do Mundo* 4 s, *Jawed Karim — Me at the Zoo* 19 s) | 548 K |
| `removidas/` | compilação *Kailane Frauches — Os Melhores Clipes* | 34 M |
| `para_analisar/` | 19 faixas `Desconhecido` + `LEIA-ME.txt` | 255 M |

- Nenhuma das três é referenciada no `acervo.db` (0/0/0) e o código não usa
  `removidas/` nem `para_analisar/`; `reprovadas/` é recriada sozinha quando
  precisar (`mkdir(parents=True)` em `musica.py:673`/`:1588`).
- Acervo segue **273 mp3**; rádio e `.m3u` intactos.

### 5. O que não foi feito (de propósito)

- **Não retomei** o resto da lista do Legião (91–93 faixas, ~5 h): agora está
  tecnicamente liberado, mas depende da ordem do dono e faz sentido resolver
  antes a decisão das faixas longas.
- **Sem restart e sem bump:** nada do servidor mudou (1.44.0/2080).
- **Não inventei** lista de cantores indesejados nem toquei nas faixas longas
  do acervo.

### 6. Fila

1. **Decisão das faixas longas** (a/b/c/d — tabela da §1.5) — única decisão
   grande em aberto.
2. ~~Chave do Gemini~~ **RESOLVIDO**: era a forma de autenticar.
3. **Retomar o resto da lista do Legião** quando ele mandar.
4. **Cantores indesejados** (Annita): onde a lista mora e o "baixa, toca e
   depois deleta".
5. ~~`para_analisar/`~~ **apagado por ordem dele** — vai rebaixar depois.

## §3 — "pesquise todas as IAs e use a melhor" (05/11 ~20:00)

### 1. O pedido

*"existem várias IAs instaladas no computador e mais as onli com chave no cofre
e env, pesquise todas e use a melhor, não precisa ficar preso no gemini"*, e
antes disso: *"pode sim testar outros modelos, mas deve sempre começar pelo que
indiquei, esse foi o que funcionou pra mim"*.

### 2. Inventário (medido, não suposto)

**Locais**

- `od-llm.service` → `llama-server` em `127.0.0.1:8081` com
  `qwen2.5-coder-3b-instruct-q4_k_m` (escolha declarada em 01/10).
- Modelos no disco (`/home/alex/llama.cpp/models`): `gemma-4-E4B` (4,9 GB —
  provado em 01/10 que não cabe com latência útil em 8 GB), `qwen2.5-coder-7b`
  (4,7 GB), `qwen2.5-3b-instruct` (2,1 GB), `Qwen2.5-0.5B`.
- `whisper.cpp` para voz (fora do escopo de metadados).

**Online com chave no `.env`** (o cofre só espelha o `.env` via
`vault_env_mirror.py`; não há IA a mais lá): `GEMINI_API_KEY`, `GROQ_API_KEY`,
`OPENAI_API_KEY`, `OPENAI_API_KEY2`. `HBOX_API_KEY` é do Homebox (inventário de
bens), não é IA.

### 3. Benchmark na tarefa real

Mesmo `PROMPT_SISTEMA` do pipeline, 3 faixas reais (Marcio Couth —
*Caminho no Deserto*; *Pais e Filhos*; medley da Morada). Critérios: latência,
aderência aos 8 campos e acerto de artista/gênero.

| Provedor / modelo | Tempo | 8 campos | Acertos | Situação |
|---|---|---|---|---|
| `gemini-3-flash-preview` | 5,6 s | 3/3 | **3/3** | **1º lugar** |
| `groq openai/gpt-oss-120b` | 3,4 s | 3/3 | **3/3** | **reserva** |
| `groq qwen/qwen3.8-27b` | 1,3 s | 0/3 | 0/3 | fora (não respeita o formato) |
| local `qwen2.5-coder-3b` | 31 s | 3/3 | 2/3 | última opção (offline) |
| OpenAI `gpt-5.4` / `gpt-5.4-mini` (2 chaves) | — | — | — | **sem créditos** (`429 credit_balance_exhausted`) |

Achados de campo: (a) a Groq devolve **403 imediato** para o User-Agent padrão
do Python (Cloudflare) — com UA de navegador responde em ~1 s; (b) `gpt-oss` é
modelo de raciocínio: com `max_tokens` curto o `content` volta vazio;
(c) o local às vezes responde `"Título - Gênero"`, sem pipe.

### 4. O que foi implementado

`musica.py` **v1.9.1 → v1.10.0** (backup
`backups/musica-v190-antes-header-20261105.py`):

- `chamar_ia()` percorre a cadeia `IA_ORDEM` (padrão `gemini,groq,local`,
  configurável por `OD_IA_ORDEM`, ex. `local,groq,gemini`); falha de um
  provedor (cota, 403, resposta vazia) **passa para o próximo sem backoff
  longo** e loga `IA <nome> respondeu no lugar da principal`;
- `_chamar_gemini_ia` (header `x-goog-api-key`), `_chamar_groq_ia` (Bearer +
  `User-Agent` de navegador, `max_tokens` 2000), `_chamar_local_ia` (8081,
  timeout 600);
- `chamar_gemini()` mantido como nome antigo — os 4 pontos de chamada não
  mudaram;
- `py_compile` OK e `pyflakes` **0 aviso** (roda no venv do OD).

**Provas:** cada provedor isolado respondeu (gemini 2,0 s / groq 0,6 s) e a
queda foi provada de propósito — `GEMINI_API_KEY` inválida →
`IA gemini falhou HTTP 400` → `IA groq respondeu no lugar da principal` →
linha correta em **1,0 s**.

### 5. Limites honestos

- O local (3B, 8 GB sem GPU) serve como último recurso, não como motor de
  qualidade; trocar o modelo do `od-llm.service` é outra decisão (mexe na
  persona do OD).
- O benchmark usou 3 faixas: é evidência, não estatística. A cadeia pode ser
  reordenada por `OD_IA_ORDEM` sem mexer no código.
- OpenAI volta à cadeia no dia em que houver créditos: basta criar
  `_chamar_openai_ia` e registrá-lo em `_PROVEDORES` (hoje **não** existe, então
  pôr `openai` em `OD_IA_ORDEM` só gera um aviso de provedor desconhecido).

## §4 — CLIs de código e o dossiê permanente das IAs (05/11 ~20:30)

### 1. O que o dono acrescentou

*"também temos o Kilo, Freebuff, OpenCode e Aider, acho que um do Google..."* e
*"sempre guarde essas informações para não ser preciso refazer essas
pesquisas"*.

### 2. Verificação dos CLIs (ele estava certo: existem — fora do PATH)

| CLI | Caminho | Estado medido |
|---|---|---|
| `freebuff` | `/usr/local/bin/freebuff` | 0.2.36; `--help` só expõe `login`/`doctor` — agente de TUI, não API |
| `opencode` | `~/.npm-global/bin/opencode` | `opencode run --standalone --model ...` responde, mas `--model google/gemini-3-flash-preview` → **`API key not valid`** (a chave do provedor dele é outra/estragada) e `opencode/nemotron-3-ultra-free` (citado no `orquestrador.py`) **não existe mais** |
| `kilo` / `kilocode` | `~/.npm-global/bin/kilo` | 7.8.1; `kilo models` lista, mas `kilo run` → **`You need to sign in to use this model`**; IDs do orquestrador (`kilo/nvidia/nemotron-3-super-120b-a12b:free`) mudaram |
| `aider` | `OmegaDrakon/.venv/bin/aider` | instalado; depende de credencial utilizável (OpenAI sem créditos) |

Nenhum serve como motor de lote hoje — são agentes de código, com login
interativo e peso de inicialização. O `gemini` CLI (o "do Google") **não está
instalado** nesta máquina.

### 3. Dossiê permanente (pedido explícito)

Criado **`docs/IAS_DISPONIVEIS.md`** — fonte única com:

- inventário (modelos locais e por que o `gemma-4` não cabe em 8 GB; chaves
  online e estado real de cada uma; CLIs com caminho e versão);
- tabela do benchmark de 05/11 e critérios;
- como a cadeia está no `musica.py` v1.10.0 (`OD_IA_ORDEM`, nomes de variáveis);
- **pegadinhas que já custaram tempo**: Gemini `?key=` x header, Cloudflare/UA
  da Groq, `gpt-oss` com `content` vazio, IDs de modelo que mudam, `HBOX` não é
  IA, cofre só espelha o `.env`;
- seção **"Histórico de medições"** para atualizar só quando algo mudar.

A **regra 19** do `iniciar/RULES.md` agora aponta para esse documento e diz
explicitamente para lê-lo antes de refazer a pesquisa.
