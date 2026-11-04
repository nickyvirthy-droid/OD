# 2026-11-04 — conversa OmegaDrakon

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `reverificacao_0404_txt_pendente`).

## §1 — "leia iniciar" (04/11 ~08:40): reverificação + pedido do dono parado no txt.txt

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint anterior: `radio_item2_locucao_e_filtro_vinheta_2026_11_02`
(02/11 17:12).

### 1. Estado do sistema (medido, 08:38–08:45)

- **Git:** árvore **limpa**, HEAD `202e220` == `origin/master`.
  **Nenhum resíduo** de sessão morta (o padrão 21–29/10 não repetiu).
- **od-core:** active desde **02/11 17:10:59** (o 3º restart da §5 anterior),
  MainPID **2928162**, **NRestarts=0** (~1 dia e 15 h), 1.0 G de RAM.
- **Journal desde 02/11 17:12: ZERO `[ERROR]` e ZERO `[WARNING]`**
  (52 h sem uma única linha de erro). Rádio gerando locução normalmente
  (08:33, `anuncio_musica.mp3`, 479 KB) e presença facial viva.
- **/health:** `ok=true`, todos os checks verdes (orchestrator, llm
  gemma-local, audit, metrics, database 13 tabelas).
- **Borda:** Funnel `/` **200**; `/radio.mp3` **200 audio/mpeg**;
  `/api/radio/agora` público servindo JSON (tocando *Blues Gospel — Ele
  Perdoou Antes Do Pedido*, próxima *Fernandinho — Caminho No Deserto*).
- **Versão:** 1.44.0 / 2080 (sha `aeb8566b`), inalterada.
- **Vigia (tick 08:38):** 28 ativos, `pendentes_seguranca: []`.
  **2 pendentes de dispositivo** aguardando nome do dono:
  - `DE:26:20:74:D6:AE` — 192.168.0.163, desconhecido, desde 01/11 21:53;
  - `F4:F5:E8:53:BA:B0` — 192.168.0.104, Google Inc., desde 02/11 15:26
    (**novo** em relação ao último checkpoint).
- **Relatórios de 04/11 04:32:** auditoria do chat com 1 turno, veredito
  `ok` (clima em Teodoro Sampaio, fastpath); vigia de mensagens verde.

### 2. O achado: pedido do dono parado desde 02/11 17:52

O `txt.txt` (canal do dono, regra 14) foi **reescrito às 17:52 de 02/11** —
36 min depois do último checkpoint — e **nunca foi tratado**. Conteúdo:

**(a) Bug relatado:** *"musica com lixo no nome, não limpo direito"*, com o
exemplo `CAMINHO NO DESERTO — Márcio Couth - ft. Viviane Martins -
(Way Maker - Sinach) #worship #live #music`.

**(b) Feature nova:** usuário logado escolhe uma música da lista do
servidor; se não quiser nenhuma, manda link do YouTube — se não for
repetida, o sistema baixa, transforma e classifica, e ela entra no acervo;
link de playlist baixa todas mas **só toca a primeira**; depois de escolher,
o usuário pode deixar um recado que a locutora lê antes da música (vazio =
só "pedido do usuário tal"); música por link **avisa o dono** para poder
retirar se for inconveniente, e **cadastra o usuário** para ser comunicado
da infração.

Isto é exatamente o "escolher uma música é item à parte" que já estava na
fila do checkpoint de 02/11 — agora com o detalhamento do dono.

#### Diagnóstico do bug (medido, sem mexer em nada)

- O arquivo citado existe **literalmente** como está no acervo:
  `acervo/.../Caminho No Deserto - Márcio Couth - Ft. Viviane Martins
  -(Way Maker - Sinach)#worship #live #music.mp3`, e no banco
  (`acervo.db`, tabela `musicas`, 287 linhas) está gravado com
  `artista = "CAMINHO NO DESERTO"` e o resto inteiro como título.
- **95 de 287** entradas (33%) têm lixo de YouTube: hashtags,
  `[Clipe Oficial]`, `｜`, `(Ao Vivo)`, emoji 🕊️/✨, e artista
  **`Desconhecido`** com o nome real **dentro do título** (ex.: *Soraya
  Moraes ｜ Caminho No Deserto*). Nos nomes de arquivo: **32** com sobra.
- **Causa raiz (lida no código, `musica.py` v1.8.1):**
  `extrair_artista_titulo()` divide o nome no **primeiro `" - "`** — quando
  o YouTube entrega `Título - Artista - ft. ... (Cover) #tags`, o "artista"
  vira pedaço do título e o lixo todo sobra no título. `sanitizar_nome_arquivo()`
  só troca caractere proibido de filesystem (`| : ? *`), **não remove
  hashtag/qualificador**. O `titulo_nucleo()` (que sabe tirar
  `(Ao Vivo)`/`[Clipe Oficial]`) é usado **só na comparação de dedup**,
  nunca na hora de gravar o nome/tags.
- Correção exige mais que regex: renomear 95 entradas do acervo, regravar
  tags (TPE1/TIT2), regerar `.m3u` e **sincronizar o AzuraCast** — 95
  faixas saem/entram na rádio no ar. Precisa de aval e de janela.

### 3. Ações desta troca

**Somente leitura** em git/serviço/banco (nenhuma mutação de código,
serviço ou rede). Um deslize honesto: ao consultar o banco errei o caminho
e o `sqlite3` criou um `acervo/acervo.db` **vazio (0 byte)** dentro da
pasta de músicas — **removido na mesma troca** (o banco real é
`dados/musicas/acervo.db`, 118 KB).

Registro em `iniciar/` + commit/push (regra 7.1), `txt.txt` atualizado com
a fila e Telegram (regra 15). **Sem restart** (nada de código mudou).

### 4. Fila (ordem a combinar com o dono)

1. **Bug dos nomes** (95 entradas) — o dono reclamou; corrigir na origem
   (`musica.py`) e depois um passa-limpo no acervo com relatório do
   antes/depois, `.m3u` e sync.
2. **Pedido de música pelo usuário** (feature da letra (b)) — precisa de
   decisões: quem é "usuário logado" (app/chat/conta), fila ou toca na
   hora, limite por usuário, e o que "cadastrar o usuário para comunicar
   infração" significa em dados (tabela + canal).
3. Pendências antigas: Item 3 (letra) guardado por direito autoral;
   página de acervo pro ouvinte; 2 dispositivos para nomear/bloquear.

## §2 — "Corrigir a limpeza de nomes no musica.py e passar um limpo nas 95 faixas" (~10:45): nomes limpos + ordem artista-música

**Pedido:** usuário: "Corrigir a limpeza de nomes no musica.py e passar um
limpo nas 95 faixas do acervo, com relatório antes/depois e sync da rádio".
Durante a execução ele acrescentou 6 regras (todas aplicadas):

1. "nome da musica > artista - musica (cantor/cantores e musica, nessa ordem)";
2. "musicas com menos de um minuto não é musica, pode excluir";
3. "nada de caixa alta, capitalize o texto, tudo em maiúsculo pra mim é gritar";
4. "voce esta removendo o segundo cantor? cantor ft cantor são dois cantores…
   isso deve ficar" + "Part é participação, o mesmo que feat e Ft";
5. "o & fica feio, prefiro que deixe e normal" — "R&B não troca, é nome do
   artista, assim como ABBA não capitaliza";
6. "aplique voce as correções, deixe o gemini fazer sozinho na proxima,
   apenas teste se ele consegue fazer".

### 1. O que mudou no `musica.py` (v1.8.1 → **v1.9.0**)

Backup: `backups/musica-v181-antes-limpeza-20261104.py` (e o banco em
`backups/acervo-antes-limpeza-20261104.db`). Sandbox: `.od_sandbox/limpeza-nomes/`.

- **Limpeza em 3 camadas**: `limpar_enfeite()` (hashtag, emoji,
  `[Clipe Oficial]`, `(Ao Vivo)`, `(DVD…)`, `(Legado ao Vivo)`, `- Ministração
  ao Vivo`, `@handle`, sufixo `- ao Vivo`), `segmentos_nome()` (só `｜` e `–`)
  e `separar_nome_musical()` — decide artista × título **com evidência**
  (catálogo do acervo, caixa alta de 3+ palavras, qualificador no lado errado).
  Sem evidência → status `revisar` (vai ao relatório, **não** aplica).
- **`dividir_feat()`**: `ft./Feat./Part./participação` **não somem** — viram
  ` e ` e entram no artista (`Carol Resende e Weslei Santos - Exaltado`);
  featuring no título sobe para o artista.
- **Caixa pt-BR**: `capitalizar_titulo()`/`capitalizar_artista()` respeitam
  de/da/do/e/com, cada trecho de medley (`/`) começa com maiúscula e siglas
  (`ABBA`, `R&B`, `CCB`, `LS Jack`, `XXI`) ficam. **Nada de caixa alta.**
- **`&` → `e`** quando isolado (`Jorge & Mateus` → `Jorge e Mateus`); `R&B` fica.
- **`--limpar-nomes [--aplicar] [--gemini]`**: migração com relatório
  antes/depois (`logs/limpeza_nomes_<ts>.md`) e mapa de renomeações
  (`logs/limpeza_nomes_<ts>.json` — reversível), regravando TPE1/TIT2 e
  limpando TCOM/TEXT quando o nome mudou.
- **< 1 minuto**: `MP3_DURACAO_MIN=60` no portão de qualidade e na migração →
  `reprovadas/curtas/`.
- **Segurança**: `_sem_chave()` — o erro do Gemini imprimia a API key na URL
  no log; agora sai `key=***`.
- **18 testes** em `.od_sandbox/limpeza-nomes/test_musica_limpeza.py`
  (caixa pt-BR, siglas, feat, inversões, `&`/`R&B`, @handle, duração, vazamento
  de chave) — todos verdes.

### 2. Aplicação no acervo (8 rodadas + 1 lote curado)

- **287 → 285 faixas** (2 curtas para `reprovadas/curtas/`: *Pr. Lucas - Pintor
  Do Mundo*, 4 s, download quebrado; *Jawed Karim - Me at the Zoo*, 19 s).
- **Resultado medido no fim**: **0 nomes com lixo de YouTube**, **0 em caixa
  alta**, **0 com `&`** (era 95 com lixo, 12 em caixa alta, 8 com `&`).
  Sobrou só *Kailane Frauches - Os Melhores Clipes* (é uma **compilação**, não
  uma faixa — fica para decisão do dono).
- **31 correções curadas** por mim (`logs/correcoes_manuais_*.json`), incluindo
  as inversões que a regra não provava (Terra Seca, Vento Impetuoso, Oceanos,
  Meu Barquinho, Me Leva pra Casa, Altomonte, Babi Garcia, Mário Couth…).
- **Rádio**: `acervo.db` reindexado, `.m3u` regerados (7 gêneros + Mix) e
  `azuracast:media:sync` a cada rodada. AzuraCast = **285 faixas + 2 locuções**
  (bate com o acervo). Stream 200, `/api/radio/agora` com nomes limpos,
  /health ok.

### 3. Bug real achado no caminho

Nomes que **só** precisavam perder a caixa alta ficavam com status `igual` e
**nunca eram aplicados** (12 faixas continuaram gritando depois da 1ª rodada).
Corrigido em `_capitalizar()` e coberto por teste.

### 4. Gemini (teste, como pedido)

Testado ponta a ponta: em rodadas anteriores resolveu **24/24** e **40/113**
ambiguidades com validação estrita (nome tem de existir no texto original).
No teste final a API respondeu **429 — cota esgotada** pelas rodadas de hoje.
Ou seja: **funciona**, mas está sem cota agora. Na próxima leva ele roda
sozinho com `--gemini`; o que ele acerta entra, o que não passar na validação
continua em `revisar` e eu resolvo.

**Fila do dono:** decidir o que fazer com *Kailane Frauches - Os Melhores
Clipes* (compilação) e com as 20 faixas de artista `Desconhecido` (nomes
finlandeses/poloneses sem artista no título). Itens da §1 continuam abertos.

## §3 — "leia iniciar" (04/11 ~12:45): reverificação de rotina (só leitura)

**Pedido:** usuário: "leia iniciar". Checkpoint anterior: §2 (11:30).

### Estado medido (12:45–12:55)

- **Git:** árvore limpa, `HEAD fde8e21 == origin/master` — o trabalho da §2
  está publicado, nenhum resíduo.
- **Serviço:** `od-core` active desde 02/11 17:10:59, MainPID 2928162,
  **NRestarts=0** (~1 dia e 20 h). `/health` autenticado `ok=true` com
  **nenhum check fora**; versão 1.44.0/2080 e sha `aeb8566b` inalterados.
- **Journal:** de 04/11 00:00 até 12:50 — **0 [ERROR] e 0 [WARNING]**.
- **Borda:** Funnel `/` 200; `/radio.mp3` público 200 `audio/mpeg` e icecast
  `127.0.0.1:8600` 200 `audio/mpeg`; `/api/radio/agora` público 200 com
  `Mantra da Prosperidade - Eu Recebo Dinheiro com Gratidão e Alegria`
  tocando, próxima `Duda Santos - Eu Confio em Ti`, últimas 5 com nomes
  limpos; `/site/index.html` 200.
- **Acervo:** AzuraCast 287 mp3 = **285 faixas + 2 locuções** — bate com o
  resultado da §2.
- **Vigia (tick 12:48:52):** 6 ativos no ciclo, 0 novos, `rich` true,
  `pendentes_seguranca []`; 28 dispositivos no inventário. Seguem os **mesmos
  2 pendentes** de dispositivo (DE:26:20:74:D6:AE / 192.168.0.163 desde
  01/11 21:53 e F4:F5:E8:53:BA:B0 / 192.168.0.104 desde 02/11 15:26).
- **Auditoria do chat (04/11 04:32):** 1 turno, veredito `ok`, 0 problemáticos.

### Falso alarme evitado (registro honesto)

Sondei `http://127.0.0.1:8000/radio.mp3` e veio **404** — quase reportei o
stream caído. O áudio **não mora no od-core**: a 8000 é a API, e o
`/radio.mp3` é caminho do Funnel → icecast `8600`. Pela rota certa: 200 nos
dois. (Mesma pegadinha vale para o painel: `8000/listen/...` também 404.)

### Canais do dono

`txt.txt` com mtime 11:33 = **nossa** entrega de 11:30; nenhuma mensagem nova
dele, e o recado de 02/11 continua preservado no arquivo. `analise/` sem pasta
nova (só Nicky Radio/, Prompt_Nicky_Musicas.txt e os relatórios de 04/11).

### Fila

1. **Decisão do dono:** *Kailane Frauches - Os Melhores Clipes* é compilação,
   não faixa — tiro?
2. **Decisão do dono:** as faixas `Desconhecido` (19 arquivos com esse início
   de nome) ficam assim ou ele passa os nomes dos artistas?
3. Abertos da §1: pedido de música pelo usuário (4 decisões), os 2
   dispositivos da rede e o Item 3 (letra, guardado por direito autoral).

**Ações:** só leitura em git/serviço/banco/containers; nenhuma mutação, sem
restart (nada de código mudou). Registro + commit/push (7.1) + Telegram (15).

## §4 — Acervo a limpo + área do ouvinte logado (04/11 13:00–14:40)

**Pedido (4 mensagens):** "1. tira. 2. coloca em uma pasta separada para eu
analisar. 3. vamos analisar as decisões, verifique o dispositivo por endereço
MAC, ip pode ser reatribuido, ignore direitos autorais, a rádio não é pública,
não vai ter muitos usuários" · "crie uma segunda pagina rádio que só aparece
para usuário logado, nela vai conter a letra da musica e a opção de pedido de
musica" · "ou paineis que só aparecem para quem estiver logado. o que for
melhor e mais seguro de implementar" · "conclua".

### 1. Acervo: 285 → 265 faixas

- *Kailane Frauches - Os Melhores Clipes* (era `acervo/Gospel/`) →
  `removidas/compilacao/`.
- **19 faixas `Desconhecido*`** → `para_analisar/` (pastas Gospel/ e Outros/
  mantidas) com `LEIA-ME.txt` (duração e gênero de cada uma). Nada apagado.
- Mapa reversível: `logs/movidas_20261104_131451.json` (20 itens).
- `indexar_acervo()` → **265 linhas** no acervo.db, `.m3u` regerados (Gospel,
  Internacional, MPB, Outros, Pop, Rock, Sertanejo e Mix) e
  `azuracast:media:sync` → **265 arquivos + 2 locuções = 267** linhas em
  `station_media`, **0 sobras** das faixas movidas. Rádio seguiu no ar.

### 2. Dispositivos por MAC (IP pode ser reatribuído — pedido do dono)

- **F4:F5:E8:53:BA:B0** — OUI **Google, Inc.**, nome já conhecido na lista de
  clientes do roteador: **"Chromecast"**, IP .104, última vez 02/11 17:17.
  É um cast/Google da casa; pode ser nomeado (some a pendência) e, se ele
  quiser, ganhar reserva DHCP.
- **DE:26:20:74:D6:AE** — **MAC aleatório** (bit de administração local ligado:
  `0xDE`), sem nome, IP .163, visto em 01/11 21:53 e 04/11 05:37 → celular ou
  tablet com MAC privado (Android/iOS). **Consequência:** trocar IP é o menor
  problema — esse MAC também muda. Nomear/reservar por MAC não segura o
  aparelho; o caminho é descobrir qual é (quando estiver ligado) e decidir se
  libera. Ambos estavam dormindo/offline na checagem (ping e portas 8008/8009
  fechadas).

### 3. Decisões do pedido de música (análise para o dono escolher)

| Decisão | O que já existe (medido) | Recomendação |
|---|---|---|
| Quem é "usuário logado" | Contas de verdade: `/auth/register`, `/auth/login`, tabela `users` com papel (hoje **2 contas**: alex, teste) | Usar a conta que já existe (site/chat/app) — nada de login novo |
| Fila × toca na hora | AzuraCast **já tem** o recurso: `enable_requests=0`, `request_delay=5`, `request_threshold=15` na estação `nicky` | Ligar o pedido nativo com atraso (15–30 min): segura repetição e não atropela a locução |
| Limite por usuário | — | **1 pendente por conta + 3 por dia** (já implementado no MVP) |
| "Cadastrar o usuário" | Sem direito autoral na jogada, o cadastro perde a função de infração | Vira curadoria: quem pediu, quando, o que aconteceu + aviso no Telegram |

**Pendente de escolha:** fila (atraso) × tocar na hora — é o que falta para o
pedido sair da fila e entrar no ar.

### 4. Entregue: área do ouvinte LOGADO (o "melhor e mais seguro")

Segurança primeiro: **o gate é no servidor**, não CSS — anônimo nem recebe o
HTML (`302 → /chat?next=/radio-pro`); a página pública `/site/radio.html` fica
exatamente como era.

- **`integrations/radio_pro.py` (NOVO, stdlib)**: `letra_da_musica()` (serviço
  público lyrics.ovh + cache em arquivo: 7 dias achada, 6 h negativa, teto 400,
  nunca levanta), `catalogo_musicas()`/`musica_do_acervo()` (acervo.db em
  `mode=ro`) e `criar_pedido()`/`meus_pedidos()` (SQLite próprio
  `data/radio_pedidos.db`, WAL, tabela criada na hora — sem migração do core).
- **Rotas**: `GET /radio-pro`, `GET /api/radio/pro/dados` (401 sem sessão),
  `POST /api/radio/pro/pedido` (201; 400 fora do acervo/recado > 200; 409 já
  tem pendente; 429 limite diário). Gate `_sessao_do_ouvinte()`: cookie
  `od_sessao`, Bearer ou X-API-Key **de conta**, qualquer papel.
- **`site/radio-pro.html`**: tocando agora, letra, busca no acervo, recado e
  meus pedidos; 15 s de sondagem; od.css + od-nav.js + to-top (padrão da casa).
  Link discreto na página pública.
- **Gate oficial**: **4085 passed / 16 skipped / 0 falha** (era 4061; +24 em
  `tests/test_radio_pro.py`), `len(ROUTES)` 95 → 98, pyflakes 0 aviso novo,
  `node --check` OK.
- **Restart verde** (regra 7.3, gate antes): MainPID **1325274**, NRestarts=0,
  `/health` ok sem check fora, journal **0 erro / 0 aviso**.
- **Provas vivas**: anônimo 302 → login; API anônima 401; com chave de conta
  página **200** (10 214 B) e dados **200** (tocando *Juliano Son — Lindo És +
  Só Quero Ver Você*, catálogo 40); `POST` pedido **201** (linha de teste
  criada e **removida** em seguida — a fila real ficou limpa).

### 5. Limites honestos

- **Letra** depende de serviço público: cobre bem pop/MPB (*Legião Urbana —
  Tempo Perdido* → 941 caracteres) e falha em parte do gospel/lançamentos
  (*Juliano Son*, *Jota Quest — Do Seu Lado* → "não encontrada"). A página
  avisa e o resto continua funcionando.
- **O pedido ainda não toca**: entra como `pendente` e avisa o dono no
  Telegram; ligar no ar depende da escolha fila × na hora.
- **Sem bump de versão** (mudança só de servidor/site; precedente do MCP em
  01/11 e do STT em 02/11): segue **1.44.0/2080**, APK intacto.

**Fila:** (1) fila × na hora; (2) revisar `para_analisar/` e dizer os artistas
(ou autorizar descarte); (3) nomear o Chromecast (.104) e decidir o aparelho de
MAC aleatório (.163) — reserva por MAC não resolve; (4) Item 3 (letra) está
liberado e já tem base pronta.

## §5 — "leia iniciar" (04/11 15:05): residuo do manicode morto

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3,
somente leitura). Checkpoint anterior: §4 (14:40).

### 1. Estado medido (15:05–15:10)

- **Git:** HEAD `d92ee43` == `origin/master` (commit da §4, 14:34) — **porém**
  `integrations/radio_pro.py` **modificado e não commitado** (ver §2).
- **od-core:** active desde **04/11 14:22:09** (restart verde da §4),
  MainPID **1325274**, **NRestarts=0**; `/health` `ok=true` `status=up`
  sem check fora; versão 1.44.0/2080 `aeb8566b` inalterada.
- **Journal desde 14:40:** **0 [ERROR]/[CRITICAL]** e **6 [WARN]** rotineiros
  (RSS do G1 quebrado ×1, `API erro status=404` ×3, `Transporte indisponível` ×2).
  **Correção de medição honesta:** a tag real é `[WARN]`, não `[WARNING]` —
  as contagens anteriores ("0 [WARNING]") não a capturavam. Desde 02/11 17:12:
  **197 [WARN]** (83 RSS de feed, 45 alerta de dispositivo novo, 45 clima
  wttr.in fora, 14 transporte, 3 API 404, 4 snapshot HD, 2 health degraded,
  1 restart) e **ZERO [ERROR]**.
- **Borda:** Funnel `/` 200; `/radio.mp3` 200 `audio/mpeg`;
  `/api/radio/agora` 200 (*Esther e Estefany — Jesus Te Ama Sim* tocando,
  próxima *Isadora Pompeo — Se Eu Pudesse*); `/radio-pro` anônimo **302 →
  login** (gate intacto).

### 2. O achado: outro agente (manicode) morreu com o trabalho na mão

O dono roda **dois agentes**. O `manicode`
(`~/.config/manicode/projects/OmegaDrakon/chats/2026-11-04T15-46-33.943Z`)
conduziu a sessão de **12:46 às 14:39** com as mesmas ordens da §4 e depois
**3 ordens novas**:

1. *"Nomeie o Chromecast e trate o aparelho de MAC aleatório no Vigia"* (14:38)
   — **cumprida**: `F4:F5:E8:53:BA:B0` → "Chromecast",
   `DE:26:20:74:D6:AE` → conhecido, `pendentes_novos: []`.
2. *"Ligue o pedido de música para tocar de verdade na rádio, com fila e
   aviso da locutora"* (14:39) — **não executada**.
3. *"Melhore a letra da área do ouvinte com uma segunda fonte para cobrir
   gospel e lançamentos"* (14:39) — **não executada**.

**Morreu às 14:58:57** com `AI_APICallError: Gone` (a API do modelo caiu no
meio do turno; "Main prompt finished" com `outputType: error`). As duas
últimas ordens ficaram sem resposta — **sessão perdida**, o padrão que a
regra 4 existe para evitar.

**Resíduo deixado:** `integrations/radio_pro.py` **+216/−13, não commitado,
não rodando** (o serviço foi às 14:22, antes da edição):

- cadeia de letras **lrclib.net → lyrics.ovh** com campo `fonte` no cache
  (a resposta para a ordem 3, escrita mas não testada em campo);
- helpers da fila real (`_azuracast`, `pedir_no_ar`, `marcar_status`,
  `anuncio_de_pedido`) que **ninguém chama** — `server.py` intacto.

`tests/test_radio_pro.py`: **24 passed** (não cobrem o novo). `pyflakes`
indisponível neste ambiente. Nada mais modificado no repositório.

### 3. O pedido real do dono está parado no ar

`data/radio_pedidos.db`: **id=2, "alex" — *Ana Castela - Neon*, `pendente`,
criado 04/11 15:02:35** — pedido feito **pelo próprio dono** na página
`/radio-pro` **depois** da morte do manicode (o id=1 era o teste da §4).
Não toca porque a ligação pedido→AzuraCast não existe e, mesmo existindo,
`AZURACAST_API_KEY` **não está no `.env`** (`pedir_no_ar` devolveria
`sem_chave`).

### 4. Fila e ação

Ordem dada e não executada = decisão já tomada (**fila**, com aviso da
locutora). Falta: chave da API do AzuraCast, `enable_requests` na estação,
escrita no `.env` e ligação na rota — **mutações externas**, por isso antes
de agir: pergunta ao dono se **eu assumo o WIP morto** ou ele retoma o manicode.

**Ações desta troca:** somente leitura (git, serviço, banco, containers,
chat do manicode); nenhuma mutação, **sem restart**. Registro +
commit/push (7.1) + Telegram (15).

## §6 — "Assumo e concluo" (04/11 15:10–16:30): fila do AzuraCast no ar

**Pedido:** dono respondeu **"Assumo e concluo (Recomendado)"** — eu assumo
o WIP morto do manicode (ordens 2 e 3 dele) e fecho: pedido de música na
**fila real** do AzuraCast com **aviso da locutora** + **2ª fonte de letra**
(lrclib), com testes, gate, commit e restart verde. Checkpoint anterior:
§5 (15:10).

### 1. O que foi feito (commit `f8a1a7c`)

- **Chave da API criada pela API oficial do painel** (login `POST /login` +
  header `X-API-CSRF` tirado do HTML do dashboard — sessão, não key
  improvisada): `AZURACAST_API_KEY` gravada no `.env` (backup antes em
  `backups/env-backup-antes-fila-pedido-*.env`); `enable_requests` já estava
  **true** na estação `nicky`.
- **`integrations/radio_pro.py`:** `lancar_pedido_na_fila()` (submete e
  atualiza `pendente → na_fila`; falha vira `motivo`, nada some) — com bug
  `banco=` **pego em teste** e corrigido; `criar_pedido` passou a contar
  `na_fila` no limite de 1 pendente por conta; `anuncio_de_pedido` devolve o
  recado do ouvinte e marca `tocada` na 1ª leitura (a fala não repete).
- **`integrations/api/server.py`:** `api_radio_pro_pedido` chama a fila e
  informa no Telegram e na resposta (`→ na fila da rádio ✓` ou
  `→ pendente (motivo)`); `chat_notify` plugado (mesmo caminho do launcher).
- **`integrations/radio_webhook.py`:** `montar_locucao`/`processar` com
  `pedido_fn` — o aviso **abre a fala** e o alvo é `playing_next` (a locução
  nasce durante a música atual e vira vinheta antes da próxima); se o ciclo
  perder, `now_playing` anuncia na sequência.
- **Cadeia de letras:** lrclib.net **primeiro** (catálogo aberto, cobre
  gospel/lancamentos), lyrics.ovh na reserva; **404 do lrclib = "não
  achei"**, não gera WARN. Campo `fonte` no cache.
- **`site/radio-pro.html`:** labels pt-BR de status e mensagem de fila.
- **`docs/CHANGELOG.md`:** seção nova **sem bump** (política verde; segue
  1.44.0/2080, APK intacto).

**Gate oficial:** `.venv/bin/python -m pytest tests/ -q` → **4115 passed /
16 skipped / 0 falha** (era 4085; +24 em `test_radio_pro.py`, +6
`TestAvisoDePedido` em `test_radio_webhook.py`). pyflakes **0 aviso novo**;
`node --check` OK.

### 2. Restart verde (regra 7.3, gate antes) — 16:09:35

`systemctl --user restart od-core` → **MainPID 1438243, NRestarts=0**;
`/health` com `X-API-Key` → **ok=true, status=up, 25 checks, NENHUM fora**
(3 sondagens seguidas iguais); journal desde o boot **0 [ERROR]** (1 `[WARN]`
rotineiro do próprio restart: `key=restart`); `AZURACAST_API_KEY` confirmada
em `/proc/1438243/environ`. API na **porta 8000** (o 8080 que testei à toa
não existe — a API é 8000, o site é servido por ela).

### 3. Provas vivas

- **Fila real:** pedido do dono **id=2** (*Ana Castela — Neon*, estava
  `pendente`) → `lancar_pedido_na_fila` → **`fila=azuracast`**, banco
  **`na_fila`**. Repetir o POST no AzuraCast devolve
  **500 "This song was already requested and will play soon"** = a música
  **já está na fila dele e tocará em breve**. `GET /api/station/nicky/queue`
  responde 200 com a fila de verdade.
- **Locutora:** simulação com **cópia** do banco real (para não consumir o
  pedido que vai tocar): payload com a faixa pedida em `playing_next` →
  locução **"Pedido de alex: Vamos dançar"** (o recado real do pedido); a
  cópia virou `tocada`, o **banco real segue `na_fila`**. Ao tocar de
  verdade, o webhook do AzuraCast dispara o mesmo aviso e marca `tocada`.
- **2ª fonte de letra (lrclib):** *Juliano Son — Lindo És* → lrclib 669 B;
  *Ana Castela — Neon* → lrclib 1330 B; *Jota Quest — Do Seu Lado* → lrclib
  **1772 B** (estava preso num **cache negativo stale** gravado às 14:29 pelo
  código antigo, só-lyrics.ovh — entrada removida, hoje o lrclib acha).
- **HTTP:** anônimo `/radio-pro` → **302** `/chat?next=/radio-pro`;
  anônimo `/api/radio/pro/dados` → **401**; com chave de **conta**
  (`od_…`, a `OD_API_KEY` do servidor não passa no gate de ouvinte —
  comportamento do `_sessao_do_ouvinte`, não regressão) → página **200**
  (10 593 B) e dados **200** (*Maria Marçal — Deixa* tocando, catálogo 40,
  pedidos `[]`, letra `fonte=lrclib`); `POST` com caminho inválido → **400
  `musica_desconhecida`** (sem efeito na fila).
- **Borda pública:** Funnel `/` **200**, `/api/radio/agora` **200** com JSON
  completo, `/radio.mp3` **206 audio/mpeg**.

### 4. Limites honestos e pendências

- **O pedido id=2 está na fila do AzuraCast** e tocará quando a estação
  chegar nele — nesse ciclo a locutora fala o recado e marca `tocada`.
- **Chaves órfãs no AzuraCast** (para o dono decidir): `odradio1` (hack de
  DB do manicode, segredo em `/tmp/od_azura_key`) e `9b4e93652a048442` —
  ambas **sem referência no repo**; a que vale é a do `.env`.
- **Restos da §4:** 19 faixas em `para_analisar/` aguardando artistas;
  Chromecast já nomeado pelo manicode (ordem 1 dele cumprida).
- **Sem bump de versão:** mudança só de servidor/site → **1.44.0/2080**.

**Ações desta troca:** chave API criada (mutação externa autorizada pela
escolha do dono), código + testes, gate verde, restart verde, provas vivas,
registro + commit/push (7.1) + txt.txt + Telegram (15).
