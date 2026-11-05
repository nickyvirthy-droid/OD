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
