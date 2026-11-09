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
