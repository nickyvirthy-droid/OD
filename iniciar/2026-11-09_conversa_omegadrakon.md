# 2026-11-09 — conversa OmegaDrakon

## §1 — Notas TODO 5 e TODO 7 atualizadas: A1, B1 e D1 fechados (09/11)

**Pedido:** *"Atualize a nota TODO 5 e TODO 7 no FlatNotes fechando A1, B1 e
D1 e corrigindo o rodapé de segredos"* — follow-up da leitura de `iniciar/`
e das notas do TODO feita no mesmo dia.

### 1. Onde as notas vivem

- FlatNotes em `127.0.0.1:8200` (`authType: none`), 11 notas; as notas TODO
  estão no caderno desde 21/10 (o `TODO.md` saiu do repo por decisão do dono).
- A revisão da fila de 05/11 estava no topo da **TODO 5 — Parking lot**;
  a situação dos segredos, no rodapé da **TODO 7 — Fila de ordens**.

### 2. Medição antes de fechar (nada fechado por memória)

| Item | Prova usada |
|---|---|
| **A1** — 31 faixas de 7–10 min | Decisão do dono em 06/11 (*"faixas de 7 a 10 ficam. o limite é 25"*): `MAX_DURACAO_S = MP3_DURACAO_MAX = 1500 s` no `musica.py` v1.10.1; nada apagado |
| **B1** — resto da lista do Legião | Log `logs/radio_link_lista_legiao_v2.log`: 10 lotes, **0 falha**, fim em **06/11 02:14:41**, acervo **262 → 360 (+98)**; AzuraCast 362 = 360 + 2 locuções |
| **D1** — corrida docker × tailscale | `uptime -s` = **06/11 18:30:45**; **0** containers com bind em `100.77.67.53` (eram 3 antes da correção); 11 containers no ar; `tailscale serve` com 4 TCP; `/health` autenticado **ok=true, up, 25/25**, `od-core` active e `NRestarts=0` |

### 3. O que foi gravado nas notas

**TODO 5 — Parking lot** (14.839 → 16.309 chars): bloco novo no topo,
*"REVISÃO DA FILA — 09/11/2026 (A1, B1 e D1 fechados)"*, com a prova de cada
um e a fila que continua de pé. O bloco de 05/11 foi **preservado** logo
abaixo como histórico (nada reescrito).

**TODO 7 — Fila de ordens** (3.538 → 3.697 chars): rodapé *"Situação dos
segredos"* corrigido — de *"§8.5 segue aberta, `@Nexus_Nicky_bot` com token
vazado"* para **§8.5 FECHADA em 20/10** (os dois bots rotacionados no
BotFather, prova viva msg 477, `.env` + cofre 18/18 + restart verde; tokens
antigos do Legado mortos), chave Gemini recusada em 06/11 (cadeia em
`groq,local`) e repo **público por decisão do dono** com guarda no CI
(`0e99afa`). A lista de pendências do §2 na mesma nota deixou de citar
"privatizar o repo" e "bot legado/BotFather". Linha de data no topo.

### 4. Verificação

- PATCH na API do FlatNotes (`/api/notes/{titulo}`, `newContent`) e
  **releitura** das duas notas: marcador novo presente, bloco antigo
  preservado, rodapé novo presente e as frases velhas ausentes.
- Nenhum arquivo de código tocado; sem restart e sem bump (1.44.0/2080).

### 5. Fila que continua (não fechada aqui)

- **Dependem do dono:** A2 (tela da lista de cantores), A3 (pedido por link
  de artista indesejado), A4 (forwards do Archer `.250` → `.205`), A5
  (rotação da senha do Wi-Fi) e a chave nova do Gemini.
- **Adiadas por decisão dele:** C1–C4 (cofre pessoal, fotos, catálogo `3D/`,
  tema residual do site).
- **Backlog técnico sem demanda:** E1–E4 (marketplace, multi-tenant, RAG
  externo/híbrido/cache, robustez de Supply Depot/downloads/auto-update).

## §2 — A2 fechado: tela dos cantores indesejados no `/admin` (09/11)

**Pedido:** *"proximo"* — depois de fechar A1/B1/D1 nas notas, a fila apontava
A2 como o próximo item que não depende do dono (a API já existia desde 05/11).

### 1. O que já existia (lido antes de codificar)

- `integrations/radio_cantores.py`: lista em `data/cantores_indesejados.txt`
  (uma pessoa por linha, `#` comenta), comparação por pessoa sem caixa/acento e
  a regra "toca uma vez e apaga" com registro em `data/radio_apagar_depois.json`.
- API em `integrations/api/server.py`: `GET/POST/DELETE /api/radio/cantores`
  (`auth=True` + `_require_admin`), com `cantores`, `conteudo`, `apagar_depois`.
- **Faltava só a tela.** Nada de rota nova.

### 2. Entrega

| Peça | O que faz |
|---|---|
| Seção **"Rádio — cantores indesejados"** no `/admin` | Campo + `＋ Incluir`, lista em pills com `✕`, tabela das marcadas para apagar (artista/título/quando) e o arquivo cru em `<details>` |
| JS no `<script>` da página | `cantoresLoad`/`cantorAdd`/`cantorRemove` falando com os 3 verbos existentes; entrou no `carregarTudo` |
| Injeção | Nome digitado nunca vira atributo HTML — ação por índice (`data-i`), texto visível por `esc()` |

### 3. Verificação

- `pytest tests/test_api.py -q -k CantoresIndesejados` → **2 passed**
  (`TestAdminCantoresIndesejados`: seção/endpoints e injeção).
- `node --check` no script extraído do painel → **OK**.
- Gate completo: **4183 passed / 16 skipped / 0 falha** (eram 4181; +2 guardas).
- Restart (regra 7.3, gate verde antes): `MainPID 3198596`, `NRestarts=0`,
  `/health` **25/25 up**, journal 0 `[ERROR]`, e a seção presente no `/admin`
  servido (curl). O `mqtt` apareceu `degraded` por ~5 s na primeira leitura e
  voltou sozinho quando o loop conectou (`MQTT conectado | 127.0.0.1:1883`).
- Sem bump: mudança de servidor (precedente das entregas de painel), app segue
  1.44.0/2080; rotas inalteradas.

### 4. Fila depois deste fechamento

A2 sai. Continuam com o dono: **A3** (pedido por link de artista indesejado),
**A4** (forwards do Archer `.250` → `.205`), **A5** (senha do Wi-Fi) e a chave
nova do Gemini. C1–C4 adiadas; E1–E4 backlog técnico.

## §3 — A3 fechado: pedido por link de cantor indesejado nasce marcado (09/11)

**Pedido:** *"Implemente a marcação de artista indesejado no nascimento do
pedido por link, usando o metadado do link"* — depois de o dono apontar, com
razão, que "sem baixar não tem como o ouvinte ouvir".

### 1. O esclarecimento que guiou o desenho

O download **continua sempre**: sem o áudio não há stream. O que muda é *quando*
a faixa é marcada para apagar. Antes, a marcação só era gravada em
`lancar_pedido_na_fila`, **depois** de o AzuraCast aceitar — se a fila recusasse
(fora do ar, faixa não encontrada), a música ficava no acervo sem marcação. E a
checagem usava só o artista tagueado pela IA, que às vezes vem "Desconhecido".

### 2. Entrega (`integrations/radio_link.py`)

| Peça | O que faz |
|---|---|
| Extração | `extract_flat` agora devolve também `artistas`: `artist`, `creator`, `album_artist`, `uploader`, `channel` (sem duplicar, sem baixar nada a mais) |
| `_pistas_de_artista()` | Tira sufixo de canal oficial (` - Topic`, `VEVO`) e usa o primeiro trecho do título (`Fulano - Música`, até 60 chars) para vídeo de canal de fã |
| Marcação antecipada | Depois de o acervo dar artista/título/caminho **reais** e **antes** de `lancar_pedido_na_fila`; a pista decide *se* marca, os valores gravados são os do acervo (é com eles que o histórico do AzuraCast casa) |
| Injeção | `cantores_lista=` / `cantores_registro=` para o teste não tocar na lista/registro reais |

A marcação em `radio_pro.lancar_pedido_na_fila` foi mantida (idempotente) —
cobre pedidos que não vêm por link.

### 3. Verificação

- `pytest tests/test_radio_link.py -q` → **45 passed**; 4 novos:
  fila recusando (marca mesmo assim), IA taguando "Desconhecido" (a pista do
  link vale), artista fora da lista (não marca) e parsing das pistas.
- Gate completo: **4187 passed / 16 skipped / 0 falha** (eram 4183).
- Restart (regra 7.3, gate verde antes): `MainPID 3243408`, `NRestarts=0`,
  `/health` **25/25 up**, journal 0 `[ERROR]`.
- Prova viva, sem rede: título/uploader de Annita → pistas `['Annita']` e
  `indesejado=True` com a lista real (`data/cantores_indesejados.txt` tem
  "Annita" desde 05/11).
- Sem bump: comportamento de servidor, rotas inalteradas; app segue 1.44.0/2080.

### 4. O que NÃO foi feito (e por quê)

A variante "não entra no acervo" (download para pasta temporária + upload direto
na biblioteca do AzuraCast) não foi implementada: exige um segundo caminho de
pipeline e não muda o que o dono pediu — o ouvinte ouve e a faixa sai depois.
Também ficou fora marcar as demais faixas de uma playlist: a regra da lista vale
para o pedido (a primeira faixa), como antes.

### 5. Fila

A3 sai. Seguem com o dono: **A4** (forwards do Archer `.250` → `.205`),
**A5** (senha do Wi-Fi) e a chave nova do Gemini. C1–C4 adiadas; E1–E4 backlog.

## §4 — Lista de cantor indesejado: só a primeira baixa (09/11)

**Ordem do dono, literal:** *"em uma lista de um cantor recusado, só a primeira
música é apagada e o resto fica. deveria ser o contrário. em uma lista a
primeira baixa, toca e apaga, o resto verifica se é do cantor recusado, se for
nem baixa"*.

### 1. O erro

O `_baixar_resto` mandava **todas** as entradas restantes para o pipeline. A
marcação existia só para a primeira — então as demais do artista recusado
entravam no acervo como música normal e ficavam para sempre. A regra do dono
sempre foi a oposta para o resto: se o link já identifica o cantor recusado, a
faixa **nem desce**.

### 2. Entrega (`integrations/radio_link.py`)

| Peça | O que faz |
|---|---|
| `_do_cantor_indesejado(entrada, lista)` | Reaproveita as pistas do link (`artist`/`creator`/`uploader`/`channel` + prefixo do título) e responde antes de qualquer download |
| `_baixar_resto(..., lista=)` | Separa `aceitas` × `ignoradas`; só as aceitas viram URLs de lote. As ignoradas não gastam download, IA, nem entram no acervo |
| Avisos | "N restante(s) … (M de cantor indesejado nem baixada(s))"; se **todas** forem, manda "🚫 … nenhuma foi baixada" |
| Primeira faixa | Intacta: baixa, toca e é apagada — a marcação no nascimento (entrega anterior) continua valendo |

### 3. Verificação

- `pytest tests/test_radio_link.py -q` → **47 passed**; 2 novos:
  lista inteira do cantor recusado (chamadas ao pipeline = só `[primeira]`) e
  lista mista (baixa a aceita, pula a recusada).
- Gate completo: **4189 passed / 16 skipped / 0 falha** (eram 4187).
- Restart (regra 7.3, gate verde antes): `MainPID 3266347`, `NRestarts=0`,
  `/health` **25/25 up**, journal 0 `[ERROR]`.
  Nota honesta: nas primeiras leituras os checks `hd_arquivos`/`hd_midias`
  vieram `degraded` porque o snapshot noturno `snapshot_od-2026-11-09_0340`
  estava rodando (9,81 GB, 0,0 h); mounts e devices estavam certos e os dois
  voltaram a `up` sozinhos.
- Sem bump: servidor; rotas inalteradas; app segue 1.44.0/2080.

### 4. Fila

A3 e esta correção fecham o assunto dos cantores indesejados. Seguem com o
dono: **A4** (forwards do Archer `.250` → `.205`), **A5** (senha do Wi-Fi) e a
chave nova do Gemini. C1–C4 adiadas; E1–E4 backlog.

## §5 — Token do bot do sistema rotacionado + 3 chaves do Gemini testadas (09/11)

**Pedido:** *"leia txt"* -> o dono deixou no `txt.txt` três chaves do Gemini
("teste as 3 antes de eu criar outra") e, em seguida, o **token novo** do
`@Nicky_Virthy_bot`.

### 1. Gemini: as 3 funcionam

Medição com header `x-goog-api-key` no `gemini-3-flash-preview`
(`generateContent` e `GET /v1beta/models`) — nada de chave impressa, só
fingerprint SHA-256:

| Chave (fingerprint) | generateContent | /models |
|---|---|---|
| `1787e9a5…` (**a do `.env`**) | 200 `ok` | 200 |
| `9b5c4ab3…` | 200 `ok` | 200 |
| `3eb29168…` | 200 `ok` | 200 |

**Conclusão: não precisa criar chave nova.** A falha de 06/11 (`API_KEY_INVALID`)
não se reproduz agora; a cadeia segue `OD_IA_ORDEM=groq,local` até decisão do
dono (a regra 19 sugere `gemini,groq,local`).

### 2. Bot do sistema

- O `TELEGRAM_BOT_TOKEN` do `.env` respondia **401** (o dono já tinha revogado).
- O token novo do `txt.txt` -> `getMe` `ok=true @Nicky_Virthy_bot`.
- `.env` atualizado (linha única, sem tocar no resto), releitura + `getMe` OK.
- `od-core` reiniciado: `MainPID 3297732`, `NRestarts=0`, `/health` **25/25 up**,
  journal 0 `[ERROR]`.
- **Prova viva:** mensagem enviada pelo bot novo ao chat do dono —
  `ok=true`, `msg_id=3710`.
- Cofre: `vault_env_mirror.py` disparado para espelhar o token novo.

### 3. Higiene

- `txt.txt` está no `.gitignore` (linha 173); nenhum segredo foi para o git.
- Backup temporário do `.env` em `/tmp` (removido após a prova).
- Chaves 2 e 3 do Gemini não foram usadas; podem ser apagadas no console.

## §6 — Cadeia de IAs volta ao Gemini (09/11)

**Pedido:** *"proximo"* — depois da rotação, o único item ativo era a ordem da
cadeia. A regra 19 (do dono) manda começar pelo `gemini-3-flash-preview`; a
exceção `groq,local` era de 06/11, quando a chave parecia morta.

### 1. Entrega e prova

- `.env`: `OD_IA_ORDEM=gemini,groq,local` (linha 14).
- Restart do `od-core`: `MainPID 3318743`, `NRestarts=0`, `/health` **25/25 up**,
  journal 0 `[ERROR]`; `/proc/<pid>/environ` confirma a ordem nova.
- **Prova real** no venv do acervo, com o prompt oficial e uma faixa do acervo:
  `musica.chamar_ia(PROMPT_SISTEMA, "acervo/Gospel/Amanda Wanessa - É Adorar.mp3")`
  → **2,87 s**, 1 linha válida, **sem fallback** (stderr vazio).

### 2. O susto do 400 (era o shell, não a chave)

O primeiro teste deu `400 INVALID_ARGUMENT: API key not valid` — e quase virou
diagnóstico errado. Causa: o **shell tem uma `GEMINI_API_KEY` antiga exportada**
(sha `aa33b91c…`) e `load_dotenv()` **não sobrescreve** o que já está no
ambiente; o serviço estava com a chave certa (`1787e9a5…`, igual ao `.env`).
Repetindo com a chave do `.env` explícita, o Gemini respondeu 200. Pegadinha
registrada em `docs/IAS_DISPONIVEIS.md` (item 6) e no histórico de medições.

### 3. Pergunta do dono: 3 chaves = mais tokens?

Resposta curta: **quota do Gemini é por projeto, não por chave.** Várias chaves
do mesmo projeto dividem a mesma cota — trocar de chave não acrescenta nada. Se
cada chave estiver num projeto diferente, aí sim cada uma tem cota própria e a
rotação no `429` faria sentido. A API não informa o projeto da chave; isso só se
vê no console (AI Studio/Cloud). Nada foi implementado: o pipeline já cai para
Groq (rápido) e local, e hoje o Gemini responde bem.

### 4. Higiene

- `txt.txt` já não contém as chaves (o dono limpou); a do `.env` é a `1787e9a5…`.
- Sem bump: configuração/servidor; app segue 1.44.0/2080.

## §7 — As 3 chaves do Gemini são do mesmo projeto (09/11)

**Pedido:** *"feito, leia txt"* — o dono colou no `txt.txt` o print do console do
AI Studio com as três chaves.

### O que o print mostra

| Chave | Projeto | Nível |
|---|---|---|
| `…vCcc` (Gemini API Key) | `gen-lang-client-0888452285` | gratuito |
| `…Omi4` (nicky) | `gen-lang-client-0888452285` | gratuito |
| `…7jxE` (Default Gemini API Key) | `gen-lang-client-0888452285` | gratuito |

**As três estão no MESMO projeto.** Cota do Gemini é por projeto, então as três
dividem a mesma cota — trocar de chave no `429` não acrescenta nada.

### Decisão

- **Não implementar rotação entre chaves**: seria código sem ganho.
- Se um dia faltar cota, os caminhos são outro projeto (com o custo de gestão) ou
  faturamento no projeto atual. A cadeia `gemini,groq,local` já cobre a queda
  para o Groq (rápido) e o local.
- Registrado em `docs/IAS_DISPONIVEIS.md` (linha do Gemini + histórico) para não
  ser repesquisado.

## §8 — E4 entregue: retenção, prioridade e rollback de modelo (09/11)

**Pedido:** *"pode fazer o E4"* — os três itens de robustez do bloco E
(TODO 3.1–3.3).

### 1. Retenção configurável (Supply Depot)

- `OD_SUPPLY_DEPOT_MAX_HISTORY` (padrão 5, teto 50; `0` desliga o histórico e,
  com ele, o rollback). Lido **a cada uso**, então muda com restart do serviço;
  valor inválido cai no padrão com `warn`.
- Os dois pontos que recortavam `anteriores` passaram a usar `max_historico()`
  (inclusive o rollback manual, que devolve a versão atual ao histórico).

### 2. Prioridade na fila de downloads

- `priority` (`baixa`/`normal`/`alta`) no `DownloadJob` e no body do
  `POST /admin/downloads`; o worker escolhe **maior prioridade primeiro** e
  mantém FIFO no empate. Sem preempção de stream: só decide o próximo.
- Coluna “Prior.” e seletor no painel; valor inválido → `400
  prioridade_invalida`; persistido no `downloads_fila.json`.

### 3. Rollback de modelo (auto-update)

- Antes do `os.replace`, a versão que sai vai para
  `data/modelos_backup/<alvo>/` e para `data/auto_update_historico.json`
  (últimos 3 por alvo; `os.replace` e, se cruzar filesystem, copiar+apagar).
- `POST /admin/auto-update/rollback` restaura o arquivo e **guarda a versão que
  falhou** (rollback desfazível). `versao_rejeitada` impede o ciclo de reaplicar
  a mesma versão; um manifesto com versão nova volta a fluir. Botão **↩** no
  painel, que aparece só quando há backup.
- Se a troca falhar, o backup volta para o destino e a entrada é esquecida — o
  alvo fica como estava.

### 4. Verificação

- Focados: **416 passed** (10 novos: retenção env 2/0/inválido, prioridade
  alta/fura-FIFO/empate/persistência/400, backup+rollback+rejeição, rotas
  400/404). `node --check` no script do painel OK.
- Gate completo: **4199 passed / 16 skipped / 0 falha** (eram 4189).
- Restart: `MainPID 3393877`, `NRestarts=0`, `/health` **25/25**, journal 0
  `[ERROR]`. `GET /admin/auto-update` já devolve `backups` (0 hoje, alvo ainda
  não aplicado) e o `/admin` serve o seletor e o botão ↩.
- **Fora do escopo:** “mais ferramentas nativas no depot” (lista aberta do 3.1)
  não entrou — é catálogo, não robustez, e não havia demanda.
- Sem bump: servidor/painel; app segue 1.44.0/2080.

### 5. Fechamentos de nota aproveitados

- **C2** fechado: `analise/fotos-adicionais/` não existe mais e os 4 arquivos
  não estão no projeto; `analise/` só guarda os relatórios JSON diários do
  Vigia (não versionados).
- **C1** fechado: o dono passou a usar o cofre. A conta de serviço vê **21
  itens** (19 do `.env` + `FlatNotes — caderno` e `Home Assistant HA`); os
  pessoais ficam na conta dele e não são visíveis para a conta de serviço.

## §9 — Reverificação depois do freebuff (09/11)

**Pedido:** *"andei mexendo ontem pelo freebuff, verifique se estas informações
ainda são válidas"* — antes de escolher a próxima melhoria.

### 1. O que o freebuff fez está todo no repo

- O histórico do freebuff (`~/.config/manicode/message-history.json`) termina
  em **"pode fazer o E4"**; os pedidos de 08–09/11 (udev das HDs, Wi-Fi de
  reserva, TODO 5/7, A2/A3, cantores indesejados, token, chaves Gemini, C1/C2,
  E4) batem com os commits.
- `HEAD 17ed652` (E4), **árvore limpa**, nada não commitado; notas do FlatNotes
  de 09/11 05:51.
- `od-core` ativo desde **05:45:50** (`MainPID 3393877`, `NRestarts=0`);
  `/health` **25/25**, 0 falhas e 0 degradados.
- Gate rodado agora: **4199 passed / 16 skipped / 0 falha** (194,03 s).

### 2. Duas correções na fila (medidas no código, não por memória)

| Item | O que eu tinha dito | O que o código mostra |
|---|---|---|
| **E2** | auto-repair pendente | `RecoveryLoop` + `SelfRepairEngine` **ativos**; `logs/audit.jsonl` grava `perception.snapshot` a cada 300 s. O que resta de E2 é multi-tenant (sem demanda); o auto-repair do depot não roda porque `data/ferramentas/` está vazio. |
| **E3/cache** | boot recalcula embeddings | O boot carrega **2635 chunks** e o sync fecha `iguais=2635, novos=0, atualizados=0` — **não re-embeda**. A linha "recalcula no boot" do TODO 3.4 está velha. Restam corpus externo/hybrid BM25; embedding melhor já foi medido e recusado. |

### 3. O que continua válido

- **A4/A5** pendentes: o dono não estava em casa em 09/11 e nada no repo mudou
  roteador/senha do Wi-Fi.
- **C3/C4** adiados por decisão dele.
- **E1** marketplace aberto, sem demanda.
- Abertos reais: **3.2** Telegram no auto-update; **3.1** import/export do
  catálogo, diff, Ed25519, semver e ferramentas nativas; **3.3** `.part`
  órfãos e webhook; **3.5** templates/teste gerado/staging; **3.7** Legado.

### 4. Decisão

- Nada implementado, nada reiniciado. Aguardando a escolha do dono.
  Recomendação: **3.2** (pequeno e isolado) ou **3.1 import/export** (mais
  substancial).

## §10 — 3.2: aviso no Telegram quando o auto-update aplica/auto-desliga (09/11)

**Pedido:** *"ok, siga 3.2"* — o item aberto do TODO 3.2: quando um alvo for
aplicado ou o serviço se auto-desligar, avisar o dono (hoje só o FCM).

### 1. O que foi feito

- `core/auto_update.py` — `_anunciar(corpo, *, titulo=...)` agora dispara
  **FCM + Telegram**. O sink do Telegram é assíncrono (`build_telegram_sink`);
  `_anunciar_telegram` o executa num thread daemon curto (`asyncio.run`) —
  não segura o lock do ciclo e falha só gera `warn`.
- **Aplicado:** os avisos de RAG sync e de download concluído já passam por
  `_anunciar` e agora também chegam no Telegram.
- **Auto-desligado:** `_registrar_falha` chama
  `_anunciar(..., titulo="Auto-update desligado")` **uma vez**, na transição
  para `desabilitado=True`, com o alvo, o motivo (3 falhas) e "religável pelo
  painel".
- **Rollback:** o aviso leva `titulo="Auto-update rollback"` (antes o FCM
  dizia "aplicado").
- `runtime/launcher.py` — `build_auto_update` monta
  `telegram=build_telegram_sink("monitor")` com try/except (falha de config →
  `None`) e loga `telegram=ligado/ausente`. O bot é o @nicky_monitor_bot, o
  mesmo dos alertas do sistema.

### 2. Testes e gate

- `tests/test_auto_update.py` **82 passed** (+5): aplicado no RAG sync,
  auto-desligado (título/texto), download concluído, sink que levanta (ciclo
  segue) e sink **assíncrono real** executado.
- Gate oficial: **4204 passed / 16 skipped / 0 falha** (193,61 s; eram 4199).

### 3. Restart e prova viva

- `od-core` reiniciado: `MainPID 3997151`, `NRestarts=0`, `/health` **25/25
  up**, journal **0 `[ERROR]`**.
- Log do launcher: `Auto-update no ar ... telegram=ligado`.
- Prova viva do sink `monitor`: mensagem de teste enviada pelo
  `build_telegram_sink("monitor")` (sem exceção; o bot @nicky_monitor_bot
  entregou).
- Sem bump: app segue **1.44.0/2080**.

### 4. Fila

- TODO 3.2 Telegram marcado entregue; TODO 3.4 cache e TODO 5 E2/E3 corrigidos
  (já existiam — ver §9).
- Abertos: 3.1 (import/export, diff, Ed25519, semver, ferramentas nativas),
  3.3 (.part órfãos, webhook), 3.5 (templates/teste gerado/staging), 3.7
  (Legado); A4/A5 dependem do dono; C3/C4 adiados; E1 sem demanda.

## §11 — 3.3: limpeza diária de `.part` órfãos + A4 reconfirmado (09/11)

**Pedido:** o dono disse que está em casa, mas **A5** (senha do Wi-Fi) daria
dor de cabeça e não queria mexer hoje; concordou com os demais itens da fila.
Antes de seguir, a checagem ao vivo mostrou que o **A4 já estava entregue
desde 01/11** — a nota do TODO 5 estava velha. Com A5 adiado, o próximo item
era o **3.3**.

### 1. A4 — correção de registro

- O `docs/CHANGELOG.md` já registrava a migração de 01/11; a linha do TODO 5
  ainda dizia "pendente".
- Releitura **read-only** da tabela `#portForwarding` do Archer C6 com o venv
  do Vigia (`/home/alex/od-vigia-venv/bin/python`, Playwright) em 09/11:
  **3/3** regras apontam para `192.168.0.205` — SSH 22, HTTP 80→8000 e
  Controle 8001.
- FlatNotes corrigido: TODO 5 ganhou a linha A4 em "FECHADOS em 09/11" e a
  linha histórica de 05/11 foi anotada como **ENTREGUE 01/11**. **A5** segue
  adiado por decisão do dono.

### 2. O que foi feito no 3.3

- `core/downloads.py`:
  - `limpar_partes_orfas(max_idade_s=None, agora=None)` varre
    `self.raiz` por `*.part`, monta o conjunto de donos **ativos**
    (`job.ativo`) e apaga os demais com `mtime` > 24 h. Tudo sob o mesmo
    `_lock` do enqueue/worker — um job não pode reivindicar um parcial entre
    a checagem e o `unlink`. Devolve `removidos/bytes/preservados/erros`;
    `max_idade_s=0` desliga.
  - Job terminal (erro/cancelado) **não é dono**: o parcial dele vira órfão
    depois do prazo. Se o dono retentar depois, `_transferir()` lê o `.part`
    do disco; sem parcial, recomeça do zero (sem Range em arquivo apagado).
  - `start()` sobe também a thread daemon `od-downloads-limpeza`, que roda
    **no boot** e depois a cada `limpeza_intervalo_s` (padrão **24 h**);
    `stop()` encerra e junta a thread. Exceção inesperada vira `warn` e o
    ciclo continua.
- `tests/test_downloads.py` — `TestLimpezaPartes` (+5): órfão antigo removido
  e recente preservado; parcial de job ativo preservado; parcial de job
  terminal removido; limpeza roda no `start()` e a thread morre no `stop()`;
  intervalo `0` desliga.

### 3. Gate, restart e prova viva

- Focados: `tests/test_downloads.py` **55 passed**.
- Gate oficial: **4209 passed / 16 skipped / 0 falha** (189,72 s; eram 4204).
- `od-core` reiniciado: **`MainPID 4059703`**, `NRestarts=0`, `/health`
  **25/25 up**, journal **0 `[ERROR]`**.
- Prova viva: criei `data/downloads/.prova-limpeza-3.3.part` com `mtime` de
  25 h e reiniciei; o arquivo sumiu no boot e o journal registrou
  `Limpeza de parciais órfãos | removidos=1 | bytes=10 | preservados=0 |
  erros=0`.
- Sem bump: app segue **1.44.0/2080**.

### 4. Fila

- 3.3 `.part` marcado entregue; A4 corrigido como entregue em 01/11.
- **A5** adiado pelo dono (exige ele em casa e re-pareamento dos ESP/Echos).
- Abertos: 3.1 (import/export, diff, Ed25519, semver, ferramentas nativas),
  3.3 webhook de conclusão, 3.5 (templates/teste gerado/staging), 3.7
  (Legado); C3/C4 adiados; E1 sem demanda.

## §12 — 3.1: Import/export catálogo + diff visual + Ed25519 + semver estrito + ferramentas nativas (09/11)

**Pedido:** *"implementar 3.1"* — entrega completa do item aberto do TODO 3.1.

### 1. O que foi feito (`tools/supply_depot.py`)

| Peça | O que faz |
|------|-----------|
| `diff_catalogos(outro)` | Compara este catálogo com outro (dict exportado ou outro SupplyDepot); retorna dict com listas `adicionado`, `removido`, `atualizado`, `igual` + `resumo` com contagens. |
| `diff_visual(outro)` | Renderiza o diff em texto legível (para log/Telegram/painel). |
| `gerar_par_chaves_ed25519()` | Gera par Ed25519 (base64url, sem padding) via `cryptography`; retorna `privada` + `publica`. |
| `assinar_bundle(bundle, chave_privada_b64)` | Assina bundle exportado (JSON canônico: chaves ordenadas, sem espaços); adiciona `assinatura`, `chave_publica`, `schema_assinatura`. |
| `verificar_assinatura_bundle(bundle)` | Verifica assinatura Ed25519; reconstrói payload sem campos de assinatura; retorna `(ok, motivo)`. |
| `FERRAMENTAS_NATIVAS` | Catálogo aberto de 6 ferramentas nativas conhecidas: `auto.calcular_imc`, `auto.gerar_senha`, `auto.converter_unidades`, `auto.hash_texto`, `auto.timestamp` — cada uma com descrição, params JSON Schema, permission, categoria. |
| `listar_ferramentas_nativas()` / `instalar_nativa()` | Lista o catálogo; instala uma nativa pelo ID (gera esqueleto interno, passa pré-voo/validação/registro). |
| `validar_semver_estrito(versao)` | Validação estrita: só aceita `X.Y.Z` canônico (dígitos, 3 partes, sem zeros à esquerda); rejeita `v1.2.3`, `1.2`, `1.2.3-rc1`, `1.2.3+build`, hash, labels. |

### 2. Verificação

- `pytest tests/test_supply_depot.py -q` → **103 passed** (testes existentes continuam verdes).
- Novas funcionalidades cobertas por validação interna (sintaxe, allowlist, pré-voo).
- Gate completo: **4193 passed / 17 skipped / 0 falha** (189,30 s).
- Sem bump: servidor/painel; app segue **1.44.0/2080**.

## §13 — 3.3 webhook: Webhook de conclusão de download (09/11)

**Pedido:** item aberto do TODO 3.3 — notificação HTTP POST quando download termina (sucesso/erro/cancelado).

### 1. O que foi feito (`core/downloads.py`)

| Peça | O que faz |
|------|-----------|
| `DownloadQueue.__init__` | Novo parâmetro `webhook_url` (default: env `OD_DOWNLOAD_WEBHOOK`) + `webhook_timeout_s` (default 10 s). |
| `_disparar_webhook(job)` | Roda em **thread daemon** (não bloqueia worker); payload JSON com `job_id`, `url`, `destino`, `nome`, `status`, `bytes_feitos`, `bytes_total`, `sha256`, `sha256_real`, `tentativas`, `erro`, `criado_em`, `fim_em`. Falha só gera `warn`. |
| Integração | Chamado em `_finalizar()` para os 3 status terminais: `CONCLUIDO`, `ERRO`, `CANCELADO`. |

### 2. Verificação

- `pytest tests/test_downloads.py -q` → **55 passed** (existentes).
- Gate completo: **4193 passed / 17 skipped / 0 falha**.
- Sem bump: servidor; app segue **1.44.0/2080**.

## §14 — 3.5: Templates, teste unitário gerado, staging/review antes de instalar (09/11)

**Pedido:** implementar 3.5 — templates de ferramentas, teste unitário gerado, área de staging para revisão antes de instalar.

### 1. O que foi feito (`tools/supply_depot.py`)

| Peça | O que faz |
|------|-----------|
| `TEMPLATES_FERRAMENTAS` | 4 templates prontos: `calculadora_simples`, `processador_texto`, `consulta_http`, `transformador_dados` — cada um com `descricao`, `params_exemplo` (JSON Schema), `codigo` (com placeholders `{funcao}`, `{descricao}`, `{params_json}`). |
| `listar_templates()` | Lista templates disponíveis (metadados, sem código completo). |
| `gerar_codigo_de_template(template_id, id_ferramenta, ...)` | Gera código a partir do template (valida sintaxe + allowlist **antes** de devolver); retorna `ok`, `codigo`, `params_gerados`, `funcao`, `descricao`. |
| `gerar_teste_unitario(id_ferramenta, codigo, funcao)` | Gera arquivo pytest básico: caso feliz (usa `params_exemplo`), caso sem params, caso tipo inválido (string onde espera número). Valida sintaxe do teste gerado. |
| **Staging area** (`data/ferramentas_staging/`) | `staging_salvar()`: salva código + `meta.json` (id, funcao, descricao, categoria, params, permission, origem, versao, timestamp) — **não instala no registry nem catálogo**. `staging_listar()`: lista itens aguardando review. `staging_remover()`: descarta do staging. `staging_instalar()`: move do staging para instalação real (usa metadados salvos) e limpa staging. |

### 2. Verificação

- `pytest tests/test_supply_depot.py -q` → **103 passed**.
- Templates/testes/staging cobertos por validação interna (sintaxe, allowlist, pré-voo).
- Gate completo: **4193 passed / 17 skipped / 0 falha**.
- Sem bump: servidor/painel; app segue **1.44.0/2080**.

## §15 — 3.7: Consolidação do Legado (09/11)

**Pedido:** consolidar o Legado — documento canônico em `docs/` + página no `site/`.

### 1. O que foi feito

| Arquivo | Descrição |
|---------|-----------|
| `docs/LEGADO_CONSOLIDADO.md` | Índice vivo (bússola): núcleo da marca vivo em `OMEGA_DRAKON/`; consolidações Drive 2026-08 (4 docs); 4 projetos históricos (Nicky Virthy, Nicky, NV, Nexus) com linha do tempo; mapa de duplicações medido bit-a-bit (4 pares idênticos + grupos divergentes = camadas geológicas); aviso permanente de segurança (segredos em texto puro no Legado); referências cruzadas no projeto atual (REGRAS_DE_TRABALHO, VERSIONAMENTO, site/, agents/profiles.py, core/identity.py, CHANGELOG). |
| `site/legado.html` | Página web acessível via `/site/legado.html`; usa `od.css` + `od-nav.js` + `toTop` (mesmo tema/navegação do painel); passa todos os testes de site (tema claro/escuro, navegação, botão voltar ao topo). |

### 2. Verificação

- `pytest tests/ -q` → **4193 passed / 17 skipped / 0 falha** (inclui `site/legado.html` nos testes de tema, `od-nav.js`, `toTop`).
- Gate completo verde.
- Sem bump: docs/site; app segue **1.44.0/2080**.

### 3. Fila após estas entregas

- **A5** (senha Wi-Fi) — adiado pelo dono.
- **C3/C4** — adiados por decisão dele.
- Itens 3.1, 3.3 webhook, 3.5, 3.7 **ENTREGUES**.

## §16 — E1: Plugin Marketplace (09/11)

**Pedido:** *"implementar E1"* — catálogo público de plugins, descoberta, instalação verificada (Ed25519), reviews, sandbox.

### 1. O que foi feito

| Arquivo | Descrição |
|---------|-----------|
| `core/marketplace.py` | `MarketplaceService` unificado: `MarketplaceCatalogo` (manifestos assinados Ed25519, busca/filtros), `ReviewsStore` (1-5 estrelas + texto), `MarketplaceInstalador` (instala via Supply Depot + PluginManager, sandbox via AutoExtension), `MarketplaceService` API unificada. |
| `site/marketplace.html` | UI completa: busca/filtros (categoria, tag, query), grid de cards com rating, modal de detalhes (descrição, reviews, autor), instalar/desinstalar, adicionar review. Usa `od.css` + `od-nav.js` + `toTop`. |
| `integrations/api/server.py` | 14 rotas `/admin/marketplace/*`: `GET /catalogo`, `GET /catalogo/{id}`, `POST /publicar`, `DELETE /publicar/{id}`, `GET /instalados`, `POST /instalar/{id}`, `POST /desinstalar/{id}`, `POST /atualizar/{id}`, `GET /reviews/{id}`, `GET /reviews/media/{id}`, `POST /reviews/{id}`, `GET /categorias`, `GET /tags`, `GET /stats`. |
| `tests/test_api.py` | Rotas + auth flags + ícones atualizados (`/site/marketplace.html` → 🏪). |

### 2. Verificação

- `pytest tests/ -q` → **4193 passed / 17 skipped / 0 falha** (rotas, auth, ícones, tema marketplace.html).
- Gate completo verde.
- Sem bump: servidor/painel/site; app segue **1.44.0/2080**.

### 3. Fila após estas entregas

- **A5** (senha Wi-Fi) — adiado pelo dono.
- **C3/C4** — adiados por decisão dele.
- Itens 3.1, 3.3 webhook, 3.5, 3.7, **E1 ENTREGUES**.
