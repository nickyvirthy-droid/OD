# Conversa OmegaDrakon — 06/11/2026

## §1 — "leia iniciar" (06/11 ~13:00)

Pedido: *"leia iniciar"* — retomada do zero, regra 3 (ler o checkpoint e os
arquivos recentes antes de assumir contexto). Checkpoint anterior:
`revisao_pendencias_2026_11_05` (05/11 22:30).

### 1. Estado do sistema

| Item | Medido hoje |
|---|---|
| Git | árvore limpa, `HEAD 34ea596` == `origin/master` |
| od-core | active desde 05/11 21:23:56, `MainPID 3145390`, `NRestarts=0` |
| `/health` | `ok=true`, 25/25 checks, nenhum fora |
| journal (desde o restart) | **0** `[ERROR]`/`[CRITICAL]` e **0** `[WARNING]` |
| app | 1.44.0 / 2080, sha `aeb8566b` (sem bump) |
| Acervo | 360 mp3 · `acervo.db` 360 linhas · max duração 690 s (`>1500 s` = 0) |
| AzuraCast | 362 = 360 faixas + 2 locuções (bate) · `.m3u` de 02:14 |
| Rádio | no ar: *Jota Quest — Dias Melhores* |

### 2. O lote do Legião terminou sozinho

`logs/radio_link_lista_legiao_v2.log`:

```
2026-11-06 02:14:41 | lote 10: acervo agora 360 (+9)
2026-11-06 02:14:41 | === fim: 10 lote(s), 0 com falha, acervo 360 ===
```

- 99 entradas → **98 baixadas** (262 → 360). Uma ficou de fora sem falha
  registrada (dedupe de título repetido), nenhum lote com erro.
- `.m3u` regerados e AzuraCast sincronizado no fim (02:14).
- O aviso de conclusão no Telegram é enviado pelo próprio runner.

### 3. Defeito: as 98 novas entraram "Desconhecido"

- `SELECT` no `acervo.db`: **98 linhas com `artista='Desconhecido'`** e
  `genero='Outros'` — todas as novas. Títulos limpos e curiosidade real.
- **Não é o pipeline quebrado.** Os títulos dessa playlist vêm do YouTube
  **sem o artista** (só o nome da música: "Tempo Perdido", "Eduardo e
  Mônica"). Medido hoje: pedindo ao Groq e ao local qwen o artista de
  "Tempo Perdido", **os dois respondem `Desconhecido`** (e o modelo local
  chegou a inventar que é versão do The Prodigy). A IA não serve como
  identificador de artista a partir do título.
- Consequência viva: a rádio toca **"Desconhecido - Tempo Perdido"**.
  98 arquivos com prefixo `Desconhecido - ` (60 em `acervo/Outros/`, o resto
  nos gêneros antigos).

### 4. A chave do Gemini morreu (medido, não suposto)

| Teste | Resultado |
|---|---|
| `generateContent` **com** `x-goog-api-key` (3×) | `400 API_KEY_INVALID` |
| `GET /v1beta/models` com a mesma chave (3×) | `400 API_KEY_INVALID` |
| chave obviamente inválida (`AIzaSyAAAA…`) | mesmo erro, mesmo texto |
| `GET /openai/v1/models` da Groq (mesma `.env`) | **200** |

Ontem (05/11) a mesma chave respondia 200 com header. Hoje **não autentica
em nenhuma das duas formas** — é chave revogada/expirada, não forma de
autenticação. O Groq continua bom e assume a cadeia (`OD_IA_ORDEM`), o local
é a última reserva. Sem ação minha: precisa de chave nova do dono.

### 5. Achado extra (não é desta leva)

Duas faixas infantis de Cocomelon no acervo desde **04/11 10:56** —
`Cocomelon - Wheels On The Bus` e `Fire Truck Song - … Cocomelon …`.
Uma delas apareceu como **próxima** na rádio agora. Candidatas a sair.

### 6. O que ficou na mesa do dono

1. **31 faixas de 7–10 min** (músicas únicas, não medley): apagar ou não.
2. **Tela da lista de cantores** no painel (`/admin`) — hoje é arquivo + API.
3. **Pedido por link** de artista indesejado: baixa antes de marcar.
4. **Forwards** `.250 → .205`; **rotação da senha WiFi**.
5. **Novas**: (a) chave Gemini nova **ou** rodar com
   `OD_IA_ORDEM=groq,local`; (b) carimbar `Legião Urbana` nas 98 (conferindo
   as de Renato Russo solo); (c) tirar as 2 da Cocomelon.

Nada disso foi executado: a sessão foi **só leitura**. Sem restart, sem bump,
sem tocar no acervo.

---

## §2 — Conserto autorizado (06/11 ~14:00)

Ordens do dono: *"Carimbar 'Legião Urbana' nas 98 faixas novas, renomear
arquivos, regravar tags, indexar e sincronizar a rádio"*, *"Tirar as duas
faixas de Cocomelon do acervo e ressincronizar a rádio"* e *"Ajustar a ordem
das IAs para groq,local enquanto não houver chave nova do Gemini"*.

### 1. Acervo: 360 → 351

| Ação | Quantos |
|---|---|
| Renomeadas + `TPE1 = Legião Urbana` | **91** |
| Duplicatas exatas removidas (já existiam certas) | **7** |
| Cocomelon removidas | **2** |
| Erros | **0** |

- As 7 duplicatas foram conferidas por duração **e** tamanho (A Dança, Antes
das Seis, Eu Sei, O Senhor da Guerra, Perfeição, Tempo Perdido, Teorema) —
mesma gravação, ficou a que já tinha o artista certo.
- `Pais e Filhos` (308 s) **não** é duplicata da de 302 s: virou
`Legião Urbana - Pais e Filhos (2).mp3`.
- `acervo.db`: **351 linhas**, **0 `Desconhecido`**, **99 Legião**;
`classificar`/`.m3u` refeitos (13:53) e AzuraCast **353** = 351 + 2 locuções.
- Estação sem nenhum caminho `Desconhecido` e sem Cocomelon (API conferida
página a página; a chave do paginador é `rows`, não `items`).

### 2. Cadeia de IA: Groq → local

- `OD_IA_ORDEM=groq,local` gravado no `.env` (a linha entra logo abaixo de
  `GROQ_API_KEY`). Teste real: a ordem lida é `['groq','local']` e a resposta
  veio em ~1 s, sem o 400 do Gemini.
- `.env` só é lido no start do `od-core` (`load_dotenv` no `orquestrador`), e
  o pipeline herda o env do processo pai → **restart necessário**.
- Gate antes do restart: `.venv/bin/python -m pytest tests/ -q` →
  **4177 passed / 16 skipped / 0 falha** (192 s).
- `systemctl --user restart od-core` às **14:05**: `MainPID 4105067`,
  `NRestarts=0`, `OD_IA_ORDEM=groq,local` visível no `/proc/<pid>/environ`,
  `/health` **25/25**, journal **0 `[ERROR]` e 0 `[WARNING]`** depois.

### 3. Sobrou de olho

- 5 títulos do lote têm cara de solo/cover do Renato Russo e não de Legião:
  `The Last Time I Saw Richard`, `Rhapsody In Blue`, `Head On`,
  `Come Share My Life`, `Riding Song`. Ficaram com o artista que o dono pediu;
  revisar quando ele quiser.
- O log do lote mostrou que o pipeline **corta o parêntese do título**
  ("The Last Time I Saw Richard (Ao Vivo Em São Paulo / 1999)" → sem o
  "Ao Vivo") — pode ser interessante preservar a versão no nome futuro.
- Seguem na mesa: 31 faixas de 7–10 min, tela da lista de cantores, pedido por
  link, forwards `.250 → .205`, senha WiFi e a chave nova do Gemini.

Registro: CHANGELOG (entrada de 06/11, sem bump), `session.json`, este arquivo,
`txt.txt` e Telegram.

---

## §3 — Versão no nome, faixas de 7–10 min e a separação que não houve (06/11 ~15:00)

### 1. As "5 do Renato Russo" eram Legião Urbana

Fui conferir antes de mexer e **não separei nada** — a hipótese do §2 estava
errada:

| Faixa | Onde está |
|---|---|
| `The Last Time I Saw Richard` | **Acústico MTV (1999)**, cover de Joni Mitchell |
| `Head On` | **Acústico MTV (1999)**, cover de The Jesus and Mary Chain |
| `On The Way Home / Rise` | **Acústico MTV (1999)**, Neil Young / Public Image Ltd |
| `Come Share My Life` | **V (1991)**, folclore americano |
| `Riding Song` | **Uma Outra Estação (1997)**, Russo/Villa-Lobos/Bonfá |
| `Rhapsody In Blue` | *exit music* de **Música p/ Acampamentos (1992)**, Gershwin |

O artista `Legião Urbana` que o dono pediu estava certo desde o começo.

### 2. Decisão do dono: as 31 faixas de 7–10 min ficam

*"faixas de 7 a 10 ficam. o limite é 25"* — nada a apagar; o teto de 25 min
já está no pipeline (`MAX_DURACAO_S = 1500`). Fecha o **A1** do quadro de 05/11.

### 3. Pipeline preserva o sufixo de versão — `musica.py` v1.11.0

- O corte vinha de `limpar_enfeite` (o regex `_NOME_ENFEITE` tratava "ao vivo"
  como enfeite) e de `_nome_extremos` (cortava o ano final).
- Agora o sufixo é extraído antes da limpeza e volta no fim: `(Ao Vivo)`,
  `(Ao Vivo Em São Paulo / 1999)`, `(Live)`, `(Acústico MTV)`, `(Remix)`,
  `(Remasterizado 2019)`. Barra interna vira ` - ` (nome de arquivo e medley).
- `_nome_extremos` só corta ano quando o parêntese continua fechado; `MTV`
  entrou nos acrônimos (antes virava `Mtv`).
- Enfeite continua saindo: `Faroeste Caboclo (Clipe Oficial)` → `Faroeste Caboclo`.
- **10 faixas** do lote que já estavam no acervo com a versão cortada foram
  corrigidas (título + arquivo + índice + `.m3u` + AzuraCast), ex.:
  `Índios (Ao Vivo em São Paulo - 1999)`, `Meninos e Meninas (Ao Vivo)`,
  `Hoje a Noite Não Tem Luar (Live)`, `Rhapsody In Blue (Live From Brazil - 1992)`.
- Acervo segue **351**, estação **353** (351 + 2 locuções).

Documentação da versão nova em `dados/musicas/doc/README.md` (v1.11).

---

## §4 — Subtítulo perdido e testes do nome (06/11 ~15:40)

### 1. Mais 42 faixas com o título mutilado

Ordem do dono: restaurar os títulos que perderam subtítulo (ex.:
"Hoy Me Voy Para México"). Varri os **578 títulos** de `Iniciando:` nos logs,
cruzei com os **351** do `acervo.db` e só agi onde o artista do log batia com o
do banco (evita casar faixa errada):

| O que voltou | Quantas |
|---|---|
| `(Ao Vivo)`, `(Ao Vivo em Brasília)`, `(Acústico)`, `(Live Session)`, `(Versão Acústica)` | 41 |
| subtítulo de título — `Hoje a Noite Não Tem Luar (Hoy Me Voy Para México) (Live)` | 1 |

Ficaram **de fora, de propósito**: `(Clipe Oficial)`, `(Official Video)`,
`(Lyric)`, `(DVD …)`, `(CD …)`, `(Vevo Presents)`, `(Cover)`, `(Audio)`,
`(Marquinhos Gomes)` e `(O Encontro)` — crédito, álbum ou formato, não título.
O relatório completo fica no script `/tmp/restaura_subtitulos.py` (dry-run).

Acervo segue **351**, estação **353** (351 + 2 locuções); conferido na API:
46 caminhos com "Ao Vivo", 3 com "(Live" e 1 com "Hoy Me Voy".

### 2. Testes do nome — `dados/musicas/tests/test_musica.py`

21 casos em pytest cobrindo `limpar_enfeite()` e `separar_nome_musical()`:

- enfeite sai (`Clipe Oficial`, `Cover`, hashtag, emoji);
- versão fica e é normalizada (`⧸` → `-`, `Em` → `em`, `MTV` não vira `Mtv`);
- subtítulo entre parênteses não é confundido com enfeite;
- o ano final não quebra o parêntese da versão;
- `limpar_enfeite` é idempotente e fecha parêntese quebrado;
- `separar_nome_musical` devolve `auto` / `igual` / `revisar` nos casos certos e
  o nome final sempre "artista - título", sem espaço duplo.

Gate: `venv/bin/python -m pytest tests/ -q` → **21 passed**. `pytest` instalado
no venv do projeto (não entrou no `requirements.txt`, que é de produção).

### 3. Achado para a próxima rodada

`acervo/Outros/Fácil - Jota Quest.mp3` está com artista e título trocados —
`Fácil` é a música e `Jota Quest` o artista. Não mexi naquela rodada: é outro
defeito, fora da ordem.

---

## §5 — Artista e título trocados (06/11 ~15:45)

Ordem do dono: corrigir o arquivo.

- Origem: o log de 10/02 registra `Iniciando: Fácil - Jota Quest` — o YouTube
  entregou nessa ordem e o pipeline antigo (antes da v1.9) leu como
  "artista - título", gravando `TPE1=Fácil` e `TIT2=Jota Quest`.
- Correção: `TPE1=Jota Quest`, `TIT2=Fácil` (319 s, mesma gravação), arquivo
  renomeado para `acervo/Outros/Jota Quest - Fácil.mp3`.
- Refiz `indexar_acervo` + `exportar_playlists_m3u` + `publicar_azuracast`:
  acervo **351** linhas, estação **353** (351 + 2 locuções), caminho novo
  presente na biblioteca, nenhum arquivo antigo sobrando.
- Jota Quest passa a ter 7 faixas no acervo: `Dentro de um Abraço`,
  `Do Seu Lado`, `Só Hoje`, `Dias Melhores`, `Pra Quando Você se Lembrar de
  Mim`, `O Sol` (com Milton Nascimento) e `Fácil`.
- O `.m3u` corta em 50 faixas por arquivo, então `Fácil` não entrou em
  `Outros.m3u`/`Mix_Radio.m3u` — a rádio toca pelo sync da biblioteca, que
  pegou o arquivo. Se o dono quiser, dá para trocar o critério de corte.
