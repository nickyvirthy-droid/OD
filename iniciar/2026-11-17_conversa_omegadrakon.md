# Transcrição — conversa com o dono (17/11/2026)

> Arquivo do dia: `iniciar/2026-11-17_conversa_omegadrakon.md`.
> Continua a série de `2026-11-15_conversa_omegadrakon.md` e `2026-11-14_conversa_omegadrakon.md`.

## §1 — Retomada: "leia inicar e txt" (17/11 ~02:30)

**Pedido (verbatim):** `leia inicar e txt`

### 1. Leitura do `txt.txt` (conteúdo encontrado)

1. `onde foi parar a lista de musicas do raul seixas.`
2. `quero poder excluir musicas que nao gosto.`
3. `tambem quero poder deixar algumas musicas de cantores bloqueados.`
4. `Site para analise: https://gsnoffline.com/`
5. `https://youtu.be/DRPBIftVb1Q?is=5odBXlk4BEA7f4DB`
6. `https://youtu.be/mso8YnboVEo?is=l7Werfu3k2flo0Vb`

---

### 2. Diagnóstico e Resposta aos 6 Pontos

#### Ponto 1 — Lista de músicas do Raul Seixas
- **Achado real no acervo:** O banco `acervo.db` possui atualmente **apenas 1 música** de Raul Seixas:
  - Arquivo: `/home/alex/dados/musicas/acervo/Rock/Raul Seixas - Metamorfose Ambulante.mp3`
  - Gênero: Rock | Duração: 231 s | Inclusa em `Rock.m3u` e `Mix_Radio.m3u`.
  - Histórico de download: baixada em 09/11/2026 04:40 (`logs/musica_2026-11-09.log`) a partir de uma playlist de 1 única música (`Metamorfose Ambulante`).
  - No ar no AzuraCast: tocou em 17/11 às 10:32 e 21:55 (`tocadas.txt`).
- **Verificação de backups:** O banco anterior (`acervo-antes-limpeza-20261104.db`) e o snapshot tarball (`acervo-20261031-antes-reset.tar.gz`) foram checados e **não continham** outras faixas de Raul Seixas.
- **Conclusão:** Nenhuma música ou lista de Raul Seixas foi apagada por erro ou sumiu do sistema; o acervo só recebeu até hoje essa faixa isolada. Se houver uma lista/discografia para baixar, basta passar a playlist ou os links do YouTube.

#### Ponto 2 — Excluir músicas que não gosta
- **Situação:** O sistema possui hoje apenas o descarte automático por *cantor indesejado* (`integrations/radio_cantores.py`) que apaga a faixa após tocar. Não há exclusão direta de faixa única pela API/App/Painel.
- **Proposta de implementação:**
  1. Criar lista negra de músicas: `data/musicas_bloqueadas.txt` (armazenando `artista | titulo`).
  2. Criar rota protegida na API: `POST /admin/radio/musica/excluir` ou `DELETE /api/radio/musica`.
  3. Ação executada:
     - Deleta o arquivo `.mp3` de `/home/alex/dados/musicas/acervo/`.
     - Remove do `acervo.db`, refaz os `.m3u` e dispara o sync do AzuraCast (`azuracast:media:sync`).
     - Registra o título/artista em `musicas_bloqueadas.txt` para rejeitar downloads futuros caso alguém peça via YouTube.

#### Ponto 3 — Deixar algumas músicas de cantores bloqueados (Whitelist de exceções)
- **Situação:** Em `integrations/radio_cantores.py`, a função `indesejado(artista)` verifica apenas o artista. Se o cantor estiver em `cantores_indesejados.txt`, qualquer faixa dele entra na fila de descarte pós-tocagem.
- **Proposta de implementação:**
  1. Criar `data/cantores_excecoes.txt` (formato `artista | titulo`).
  2. Atualizar `indesejado(artista, titulo)`: antes de checar se o cantor está na lista indesejada, verifica se a combinação `(artista, titulo)` está nas exceções permitidas. Se estiver, retorna `False` e a música é mantida de forma definitiva no acervo.

#### Ponto 4 — Análise do site `https://gsnoffline.com/` (Regra 22)
- **Inventário:** GSN Offline (GSN Terminal). Empresa que comercializa drives físicos (50GB, 128GB, 512GB) com inteligências artificiais pré-instaladas para execução 100% offline (sem internet, sem assinatura, privacidade total).
- **Recursos:** Chat local, RAG em documentos locais, chat IA-para-IA, comparação paralela de respostas entre modelos, monitor de consumo de hardware (CPU/GPU/VRAM).
- **Relação com o OmegaDrakon:**
  - O OD já adota a mesma filosofia com o `llama-server` local (Qwen2.5-Coder-3B em 127.0.0.1:8081), busca híbrida vetorial/BM25, cofre e acervo offline.
  - **Ideias a incorporar no OD:** tela de comparação lado a lado de modelos (Gemini vs Groq vs Local) e exibição do uso de hardware no `/health` ou `/admin`.

#### Pontos 5 e 6 — Análise dos Vídeos do YouTube
- **Vídeo 1 (`DRPBIftVb1Q`):** *"BAIXE ESTES 5 APPS antes que sejam banidos"* (Jonata Ribas).
  - Guia de sobrevivência digital e resiliência offline para situações de colapso/apagão.
  - 5 ferramentas cruciais:
    1. **PocketPal AI**: Execução de LLMs locais no celular sem necessidade de rede.
    2. **Organic Maps**: Navegação geográfica offline baseada em OpenStreetMap (aderente ao nosso Protomaps).
    3. **Bitchat / Meshtastic**: Comunicação sem infraestrutura (Bluetooth mesh e rádio LoRa).
    4. **Cake Wallet**: Soberania financeira com autocustódia cripto (Monero/Bitcoin).
    5. **Session**: Mensageria privada criptografada sem vínculo com operadora ou número de telefone.
- **Vídeo 2 (`mso8YnboVEo`):** *"Comunicação Off-Grid: Sem Internet, Sem Operadora! Descubra o Meshtastic e a Rede Mesh LoRa"* (Eduardo Germano).
  - Explicação prática e hardware do protocolo Meshtastic em 915 MHz com módulos Heltec, LilyGO T-Echo e WisBlock.
  - Comunicação de texto, telemetria e GPS ponto a ponto em malha criptografada sem depender de internet.
  - Forte sinergia com o OmegaDrakon para futura estação base de telemetria e mensageria local.

---

### 3. Estado ao fechar

- Checklist de regras verificado: PT-BR estrito, salvamento a cada troca (`session.json`, transcrição e `ATRIBUICOES.md`).
- Aguardando direcionamento do dono para iniciar as implementações nos itens da rádio.

## §2 — Causa Raiz: Por que a lista de Raul Seixas não baixou as outras faixas? (17/11 ~02:55)

**Pergunta do dono:** *"quero saber onde foi parar a lista do raul seixas, quando pedi a musica era uma lista, baixou e executou a primeira, metamorfose..., onde estão as outras, porque não baixou?"*

### 1. Auditoria do Pedido 11 (09/11/2026 04:40:31)

1. **Registro no banco (`data/radio_pedidos.db`):**
   - `id`: 11
   - `usuario`: alex
   - `link`: `https://www.youtube.com/watch?v=CmB4sfoZkwo`
   - `artista`: Raul Seixas | `titulo`: Metamorfose Ambulante
2. **Log de execução (`logs/radio_link_11.log`):**
   - O worker `radio_link.py` recebeu essa URL e o yt-dlp detectou:
     `Playlist detectada: 1 músicas | Já processadas: 0 | Faltam: 1`
   - Baixou apenas `Metamorfose Ambulante`, normalizou, classificou e tocou.
   - Como `len(entradas)` era 1, a rotina `_baixar_resto()` nunca foi acionada.

### 2. A Causa Raiz do Defeito

- **Local:** `integrations/radio_pro.py`, linhas 519–525 (função `link_do_youtube`):
  ```python
  if caminho == "/watch":
      video = str((query.get("v") or [""])[0]).strip()
      if _ID_VIDEO.match(video):
          return f"https://www.youtube.com/watch?v={video}"
      if lista:
          return f"https://www.youtube.com/playlist?list={lista}"
      return ""
  ```
- **O Bug:** Quando o usuário copia o link de uma playlist do YouTube que já está reproduzindo no navegador ou app, o YouTube gera a URL com ambos os parâmetros:
  `https://www.youtube.com/watch?v=CmB4sfoZkwo&list=PL...`
  Como o código testava `video` primeiro (`if _ID_VIDEO.match(video)`), ele **jogava fora o parâmetro `&list=...`**, normalizando a URL para um vídeo individual.
  O mesmo acontecia com `youtu.be/ID?list=...`.
- **Por que com Legião Urbana (Pedido 8) funcionou:** O link colado foi no formato puro `/playlist?list=PLk_SH7F8Y60WEjS87AGhEPBNvyjd3lvxh` (sem `/watch` e sem `v=`), preservando a extração das 99 faixas.
- **Destino da lista original:** Como a URL foi decepada antes de salvar no banco `radio_pedidos.db`, o identificador da playlist não ficou persistido no sistema.

### 3. Ação Corretiva
- Ajustar `link_do_youtube` em `integrations/radio_pro.py` para priorizar `lista` (ou preservar o parâmetro `list=`) quando presente, permitindo que URLs de reprodução de playlist baixem todas as faixas conforme a regra do dono.

## §3 — Retomada: "leia iniciar" (17/11, sessão atual)

**Pedido (verbatim):** `leia iniciar`

### 1. Lido
`iniciar/README.md`, `iniciar/RULES.md` (23 regras), `iniciar/session.json`,
`iniciar/ATRIBUICOES.md`, transcrição de hoje (§1–§2) e a de 15/11 (§1–§4),
além do `txt.txt` atual (pedidos 1–6 + resposta já entregue).

### 2. Estado encontrado

- `git`: `HEAD == origin/master == fccb6bc` (fix da playlist do YouTube já
  publicado). **Árvore suja** com um lote posterior, não registrado:
  - modificados: `integrations/radio_cantores.py` (+256 — listas
    `data/cantores_excecoes.txt` e `data/musicas_bloqueadas.txt`,
    `_ler_pares`/`_casa_par`/`_adicionar_par`/`_remover_par`,
    `listar_musicas_bloqueadas`, `musica_bloqueada`), `integrations/api/server.py`
    (reboot do OS updater via `updater._reboot()`), `tools/supply_depot.py`
    (staging do código), `app/lib/screens/tasks_screen.dart` (payload `{}`
    válido), `app/test/tasks_api_test.dart` e `tasks_screen_test.dart`
    (+5 testes), `tests/test_task_queue.py` (+263), `docs/ANALISE_SISTEMA_TODO.md`
    (sugestão de app por papel) e `iniciar/2026-11-14_*.md`.
  - novos: `iniciar/2026-11-15_conversa_omegadrakon.md` e 10 arquivos de
    cobertura (`test_radio_cobertura`, `test_actions_cobertura`,
    `test_embed_hybrid_cobertura`, `test_marketplace_cobertura`,
    `test_os_updater`, `test_rota_reboot_os_updater`,
    `test_server_rotas_novas_cobertura`, `test_supply_depot_cobertura`,
    `test_tools_diversos_cobertura`, `test_tools_telemetry`).
- **Verificação medida agora:** os 12 arquivos de teste acima → **682 passed
  em 8,82 s**. O lote está verde, mas **sem registro e sem commit** — a
  origem não é identificável pelo livro-caixa (regra 23: registrar como
  "origem não identificada" em vez de presumir).
- `od-core`: active, MainPID **2183349**, NRestarts=0 (PID novo em relação ao
  3322791 registrado em 15/11 — houve restart não anotado).
- **O que o lote ainda NÃO tem:** as rotas de API/App/painel para excluir
  música e para gerenciar exceções (só a camada `radio_cantores.py` existe),
  ou seja o pedido 2 e o pedido 3 do `txt.txt` estão **pela metade**:
  biblioteca pronta, interface não.

### 3. Estado ao fechar

- Nenhum código alterado nesta troca (só leitura + registro).
- Registro: esta §3, `session.json` e `ATRIBUICOES.md`.
- **Aguardando ordem do dono** para (a) validar com gate completo + commitar
  o lote verde achado na árvore e (b) fechar as rotas de exclusão/exceções
  da rádio.

## §4 — Ordem cumprida: gate completo e commit do lote órfão (17/11)

**Pedido (verbatim):** `Rode o gate completo e commite o lote órfão que está
na árvore (rádio, coverage, supply_depot, app)`

### 1. Validação (executada antes de qualquer commit)

- **Gate Python completo** (`.venv/bin/python -m pytest tests/ -q`):
  **5319 passed / 16 skipped / 0 falha**, 210,60 s, **exit 0**.
- **App:** `/home/alex/flutter/bin/flutter analyze` → `No issues found!`;
  `flutter test` → **228 passed / 2 skipped** (antes do lote: 223; os +5
  são os testes do diálogo de payload).
- `flutter` não está no `PATH` desta shell — usado o caminho absoluto
  `/home/alex/flutter/bin/flutter`.

### 2. O que o lote entregava (agora publicado)

1. `integrations/radio_cantores.py` — **pedidos 2 e 3 do `txt.txt` na camada
   de biblioteca:** `data/musicas_bloqueadas.txt` e
   `data/cantores_excecoes.txt` (`Artista | Título`, sem caixa/acento),
   `eh_excecao`/`adicionar_excecao`/`remover_excecao`/`linhas_excecoes`,
   `musica_bloqueada`/`adicionar_musica_bloqueada`/
   `remover_musica_bloqueada`/`linhas_bloqueadas`,
   `excluir_musica_do_acervo` (arquivo + `acervo.db` + bloqueio + sync do
   AzuraCast) e `indesejado(artista, titulo=)` consultando a **exceção antes**
   do bloqueio — é isso que permite manter uma música de cantor bloqueado.
2. `integrations/api/server.py` — reboot do OS updater pela instância
   (`updater._reboot()`), não mais pela função de módulo.
3. `tools/supply_depot.py` — código gerado vai para o **staging** (era o
   defeito do roundtrip: `codigo_ausente_no_staging` permanente).
4. `app/lib/screens/tasks_screen.dart` — payload `{}` válido (o defeito que
   eu havia corrigido em 15/11 e ficou sem commit).
5. **Cobertura:** 10 arquivos novos (`test_radio_cobertura`,
   `test_actions_cobertura`, `test_embed_hybrid_cobertura`,
   `test_marketplace_cobertura`, `test_os_updater`,
   `test_rota_reboot_os_updater`, `test_server_rotas_novas_cobertura`,
   `test_supply_depot_cobertura`, `test_tools_diversos_cobertura`,
   `test_tools_telemetry`) e 8 testes de borda da Task Queue
   (`TestCoberturaDeBorda`, `_RegistryPresa`).

### 3. O que continua faltando

As **rotas de API**, o painel `/admin` e a página `/radio-pro` para excluir
música e gerenciar exceções **não existem** — o dono ainda não consegue
operar nada disso pela interface. A biblioteca está pronta e testada, o
botão não. Anotado no TODO §4.

### 4. Estado ao fechar

- Sem bump: **1.45.0+2081** (servidor + biblioteca; o APK publicado não muda).
- Registro: `docs/CHANGELOG.md` (seção datada), TODO §4, esta §4,
  `session.json` e `ATRIBUICOES.md`.

## §5 — Pedidos 2 e 3 na interface: API, painel e /radio-pro (17/11)

**Pedido (verbatim):** `Implemente as rotas de API, o painel e a página
/radio-pro para excluir música e gerenciar exceções de cantores`

### 1. O que foi construído

A biblioteca já existia (publicada na §4); faltava o que o dono usa.

1. **API (6 rotas novas, 130 → 136):**
   - `GET /api/radio/musicas?q=` — acervo com `bloqueada` e
     `artista_bloqueado` por faixa, mais `bloqueadas`, `excecoes` e
     `cantores` numa chamada só;
   - `POST /api/radio/musicas/excluir` — `{caminho, bloquear}`: apaga do
     disco, do `acervo.db`, bloqueia e ressincroniza o AzuraCast (aceita
     também `"Artista - Título"`);
   - `POST|DELETE /api/radio/musicas/bloqueadas`;
   - `POST|DELETE /api/radio/musicas/excecoes`.
2. **Gate do dono no handler** (`_exige_admin_do_acervo`) — a mesma régua
   aceita cookie `od_sessao` (navegador), Bearer (app) e `X-API-Key`
   (painel); conta comum 403, anônimo 401. Sem isso a página `/radio-pro`
   não conseguiria operar (navegador não manda header) e a rota ficaria
   aberta se confiasse só no `_role()` — que devolve admin quando não há
   usuário (auth desligada em dev).
3. **Painel `/admin`:** seção "Rádio — acervo e cantores" com busca no
   acervo, botão 🚫 Excluir (confirmação + aviso do sync), listas de
   bloqueadas e de exceções com inclusão/remoção; a lista de cantores
   indesejados continua abaixo, com os endpoints de 05/11 intactos.
4. **`/radio-pro`:** card "Curadoria do acervo" que só aparece para o dono
   — o servidor responde 403 e a página esconde. Excluir/bloquear/liberar
   direto do celular.
5. **Testes:** `tests/test_radio_curadoria.py` novo (**28 testes**) +
   contagem de rotas no `test_api.py`.

### 2. Validação

- **Gate completo:** **5347 passed / 16 skipped / 0 falha** (205,23 s,
  exit 0; eram 5319).
- **Sandbox contra o acervo REAL, só leitura:** `GET /api/radio/musicas`
  → 200 faixas; `?q=raul` → "Raul Seixas — Metamorfose Ambulante"
  desbloqueada; bloquear/desbloquear e exceção criar/remover gravaram em
  arquivos de `/tmp`; excluir faixa inexistente → 404
  `musica_nao_encontrada`. **Nenhuma música real foi apagada.**
- **Pegos no caminho:** (a) `admin` não está em `PAPEIS_CONTA_VALIDOS` —
  quem é admin é a conta do `OD_OWNER_USERNAME`, e o teste precisou disso;
  (b) o JS do painel quebrou no `node --check` por aspas escapadas dentro
  do HTML em string Python — corrigido antes de publicar.

### 3. O que continua faltando

O `radio_link.py` **não recusa** baixar uma faixa que está em
`data/musicas_bloqueadas.txt` — o bloqueio vale para o painel/página, não
para o pedido por link. Checkbox novo no TODO §4.

### 4. Estado ao fechar

- Sem bump: **1.45.0+2081** (servidor + site; o APK publicado não muda).
- Registro: `docs/CHANGELOG.md`, TODO §4, esta §5, `session.json`,
  `ATRIBUICOES.md`; commits publicados e `od-core` reiniciado com prova
  viva (MainPID e `/health` na entrada do `session.json`).

## §6 — Bloqueio por música também no pedido por link (17/11)

**Pedido (verbatim):** `Faça o radio_link.py recusar o download de música que
está na lista de bloqueadas`

### 1. O que mudou em `integrations/radio_link.py`

1. **`_artista_e_titulo_do_link()`** — separa "Artista - Título" do título
   que o yt-dlp entrega, sem baixar nada.
2. **`_bloqueada_no_link()`** — cruza esse par (e as pistas de artista do
   link: canal/uploader, com "- Topic"/VEVO limpos, de `_pistas_de_artista`)
   com `data/musicas_bloqueadas.txt`. Comparação sem caixa/acento e aceitando
   sufixo ("(Clipe Oficial)", "(Ao Vivo)"). Devolve o nome que bateu para o
   log e o aviso. Falha da lista **não** bloqueia o pedido.
3. **`processar_pedido()`** — em **lista** (mais de uma entrada), o filtro
   novo roda antes de qualquer download: faixa bloqueada nem é baixada. Se
   sobrar alguma entrada, o pedido segue com ela e o dono é avisado de
   quantas ficaram de fora; se **todas** estavam bloqueadas, o pedido vira
   `rejeitada` com motivo `musica_bloqueada`.
4. **`_baixar_resto()`** — o resto da lista também filtra as bloqueadas
   (junto com as de cantor indesejado); as mensagens passaram a dizer
   "bloqueada(s) ou de cantor indesejado".
5. **Pedido avulso de faixa bloqueada NÃO é recusado** (correção do dono no
   mesmo dia, verbatim: *"como é uma rádio e aceita pedidos o único bloqueio
   de download é os que ultrapassam o limite de tamanho tempo, o resto vai
   para análise, se for bloqueada é igual cantor bloqueado"*): baixa, entra
   na fila, toca para quem pediu e abre a janela de decisão (§7). O único
   bloqueio de download é o limite de tamanho/duração do pipeline.
6. **Conferência pós-download** — quando o título esconde o nome
   ("Clipe oficial"), o acervo é consultado depois: se a faixa que acabou de
   entrar está bloqueada, ela é **marcada para a decisão** (não é apagada na
   hora, não recusa o pedido).
7. **`site/radio-pro.html`** — o motivo `musica_bloqueada` aparece traduzido
   ("música bloqueada pelo dono").

### 2. Validação

- **Gate completo:** **5355 passed / 16 skipped / 0 falha** (202,45 s,
  exit 0; eram 5348). +7 testes em `TestMusicaBloqueadaNoLink`
  (`tests/test_radio_link.py`): bloqueada nem baixa, título com sufixo,
  outra música do mesmo artista passa, playlist pula a bloqueada, resto
  bloqueado não baixa, link que esconde o nome é pego pós-download, lista
  ausente não barra nada.
- **Sandbox:** vídeo bloqueado → `downloads=[]`, pedido `rejeitada /
  musica_bloqueada`; playlist mista → baixou só a liberada; avisos corretos.

### 3. Estado ao fechar

- Sem bump: **1.45.0+2081** (servidor/worker; APK intacto).
- Registro: CHANGELOG, TODO (item fechado), esta §6, `session.json`,
  `ATRIBUICOES.md`.
- **Limite conhecido:** o filtro pré-download da lista é heurístico (depende
  do que o link entrega); a rede de segurança é a conferência no acervo
  depois do download, que abre a janela de decisão.

## §7 — Janela de decisão de 24 h: cantor bloqueado ou uma música só (17/11)

**Pedido (verbatim):** `se a musica for de um cantor bloqueado, vai me avisar

e tenho 24 horas para decidir, se não permitir ela é automaticamente apagada`
— completado por: `o mesmo para certas musicas, as vezes o cantor é permitido,
mas uma musica especifica não` e `musicas apagadas podem voltar a ser
baixadas, posso apagar simplesmeste por achar uma versão melhor`.

### 1. Regra final (a que ficou no código)

1. **Cantor bloqueado** com pedido de ouvinte: baixa, toca **uma vez**, e o
   dono é avisado na hora — ele tem **24 h** para permitir. Permitiu: a faixa
   fica no acervo e o par virou exceção (não é marcada de novo). Não
   permitiu (ou não respondeu): apagada automaticamente ao vencer o prazo.
2. **Música bloqueada** (cantor permitido, aquela música não): exatamente o
   mesmo fluxo, com o motivo `musica` no aviso e no painel.
3. **Apagar NÃO bloqueia:** a exclusão manual pelo painel/página só tira do
   disco/banco/playlists; se alguém pedir de novo, baixa outra vez. Bloquear
   é ação explícita (formulário "＋ Bloquear").

### 2. O que mudou

- **`integrations/radio_cantores.py`** — `HORAS_DECISAO` (24, env
  `OD_CANTORES_HORAS_DECISAO`); `registrar_para_apagar()` ganhou `motivo`
  (cantor|musica), `usuario` e `decidir_ate`; `pendentes()` devolve prazo e
  `segundos_restantes`; `decidir(permitir=...)` mantém + cria exceção ou
  apaga na hora com sync; `limpar_tocados()` **não apaga mais por ter
  tocado** — só o vencimento das 24 h (registro antigo sem prazo usa
  `HORAS_LIMITE`); `excluir_musica_do_acervo()` passou a `bloquear=False`
  por padrão.
- **`integrations/radio_link.py`** — ao marcar a faixa, avisa o dono
  (`aviso_de_decisao`, prazo e quem pediu); pedido avulso não é mais recusado.
- **`integrations/radio_pro.py`** — pedido pelo catálogo também marca música
  bloqueada (antes só olhava o cantor) e avisa o dono.
- **`integrations/api/server.py`** — `POST /api/radio/musicas/decisao`
  (`{artista, titulo, permitir}`; 400 sem `permitir`, 404 se não está
  pendente, 409 se já decidida); `GET /api/radio/musicas` agora devolve
  `decisoes` + `horas_decisao`; exclusão com `bloquear=false` por padrão.
  Rotas: **136 → 137**.
- **Painel `/admin`** — bloco "Decisões pendentes (24 h)" com prazo
  restante e botões ✓ Permitir / ✕ Apagar já; o texto de excluir avisa que
  apagar não bloqueia.
- **`site/radio-pro.html`** — mesmo bloco no card de curadoria; exclusão
  manda `bloquear:false` e o confirm explica.

### 3. Validação

- **Gate completo:** **5370 passed / 16 skipped / 0 falha** (203,89 s, exit
  0; eram 5356 depois da §6). +14 testes: decisão (permitir/negar/já
  decidida/não pendente/400/403/401), prazo e segundos restantes, registro
  legado, e o toque **não** apagando mais; na curadoria, exclusão sem
  bloqueio e com `bloquear=True` explícito; no `radio_pro`, música bloqueada
  marcada e dono avisado.
- **JS:** página e painel passam no `node --check` (testes de `test_api.py`).

### 4. Estado ao fechar

- Entrou no release **1.45.1+2082** (o app ganhou o card — ver §8).
- O prazo é conferido pelo webhook da rádio (`limpar_tocados` a cada troca de
  faixa) — resolução de minutos, não de segundos.

## §8 — Decisões da rádio no app Android (1.45.1+2082, 17/11)

**Pedido (verbatim):** `Mostrar as decisões pendentes também no app Android`

### 1. O que mudou

1. **`app/lib/services/od_api.dart`** — `OdDecisaoRadio` (artista, título,
   `motivo` cantor|musica, @quem pediu, `segundos_restantes` e prazo
   formatado) e dois métodos: `listRadioDecisoes()` (GET
   `/api/radio/musicas` → chave `decisoes`) e `decidirRadio(artista, titulo,
   permitir:)` (POST `/api/radio/musicas/decisao`). 403 → "Só o dono vê as
   decisões da rádio"; 409 `ja_decidida` e 404 `nao_encontrado` com texto
   próprio.
2. **`app/lib/screens/dashboard_screen.dart`** — card **"Decisões pendentes
   (24 h)"** no Painel, junto das seções do dono (só admin): nome da faixa,
   motivo, quem pediu, "apaga em 23h 0min" e os botões **Permitir** e
   **Apagar já** (com confirmação e o aviso de que a faixa pode voltar num
   pedido futuro). Depois de decidir, o painel recarrega; se a rota falhar,
   a tela do painel continua de pé.
3. **`app/test/dashboard_radio_test.dart`** — 9 testes (REST + card + ação).

### 2. Validação

- `flutter analyze` → **No issues found!**
- `flutter test` → **237 passed / 2 skipped** (eram 228; +9).
- `pytest tests/ -q` → **5370 passed / 16 skipped / 0 falha**.
- **APK:** versionName **1.45.1**, versionCode **2082** — completo
  72.176.786 B (sha256 `c1ba63b2…b8b9c`) e arm64 26.906.673 B
  (sha256 `f323e430…778f`) em `site/`; anteriores em
  `backups/apk-v1.45.0-2081/`.
- Checklist de bump (`VERSIONAMENTO.md` §5) completo, inclusive
  `site/index.html` e `_APP_VERSION_CODE = 2082`.

### 3. O que não foi feito

- Sem aba própria de rádio no app: o card vive no Painel e só aparece para
  o dono (a API responde 403 para conta comum — provado no teste).
- Sem push FCM dedicado a "decisão pendente": o aviso chega pelo Telegram e
  o app mostra a pendência ao abrir/atualizar o Painel.

## §9 — Push FCM ao entrar na decisão de 24 h (17/11, sem bump)

**Pedido (verbatim):** `Enviar push FCM quando uma faixa entrar na janela de
decisão de 24 h`

### 1. O que mudou

1. **`integrations/radio_cantores.py`** — `registrar_para_apagar()` agora
   chama `PushService.notify` **só na primeira marcação**: título
   "Decisão de 24 h — cantor/música bloqueada", corpo com "Artista — Título:
   permita no Painel do app ou ela é apagada sozinha" e `data`
   `{origem: radio-decisao, artista, titulo}`. Repetir a mesma faixa não
   reenvia (idempotência já existente + push no ramo do item novo).
2. **Fallback de serviço** — o worker do link (`python -m
   integrations.radio_link`) roda em subprocesso sem launcher; sem
   `current_push()`, o módulo monta `build_push_service(<raiz>/data)`, chama
   `configure_push` e segue com o serviço pronto para as próximas faixas.
3. **Sem mudança no app** — o FCM manda o bloco `notification`, então o
   Android mostra na bandeja com o app fechado, no canal já existente.

### 2. Validação

- **Gate completo:** **5375 passed / 16 skipped / 0 falha** (218,56 s, exit
  0; eram 5370). +5 testes em `tests/test_radio_cantores.py`: envio único com
  título/corpo/data corretos, idempotência sem segundo push, FCM que explode
  não impede o registro, construção do serviço quando não há global.
- **Serviço no ar:** `GET /push/devices` → `enabled: true`, projeto
  `nicky-e4f99`, 1 aparelho.
- Push de teste disparado pelo `/push/test` após o restart (prova de ponta a
  ponta no aparelho).

### 3. O que não foi feito

- O push leva para o Painel (não abre a faixa direto): o app não interpreta o
  `data` ainda — só exibe a notificação e o card no Painel.
- Sem lembrete intermediário (ex.: 2 h antes do prazo); só o aviso de entrada.

## §10 — Lembrete de push 2 h antes do prazo (17/11, sem bump)

**Pedido (verbatim):** `Enviar um lembrete de push 2 horas antes do prazo
vencer`

### 1. O que mudou

- **`integrations/radio_cantores.py`** — `HORAS_LEMBRETE` (2, env
  `OD_CANTORES_HORAS_LEMBRETE`) e o lembrete dentro de `limpar_tocados()` (o
  relógio da janela, chamado pelo webhook a cada troca de faixa): quando falta
  até 2 h, sai o push **"Faltam 2 h para decidir — rádio"** com
  `{Artista} — {Título}: se você não permitir, ela é apagada em menos de 2 h.`
  e `data.origem=radio-lembrete`.
- **Uma vez por faixa** — marca `lembrete_em`, gravado **só quando o push sai**
  (falha do FCM tenta de novo no próximo ciclo e não interfere no vencimento).
- `limpar_tocados()` devolve `lembretes` junto de `apagadas`/`restantes`/`sync`.

### 2. Validação

- **Gate completo:** **5379 passed / 16 skipped / 0 falha** (217,91 s, exit 0;
  eram 5375). +4 testes: lembrete dentro da janela e sem repetir, silêncio
  fora da janela (> 2 h), FCM que explodiu não grava `lembrete_em`, faixa já
  permitida não recebe lembrete.
- Webhook e `od-core` seguem verdes (`/health` 30 checks).

### 3. O que não foi feito

- Sem agendador próprio: o lembrete depende da troca de faixa (webhook). Rádio
  parada por horas pode fazer o aviso não sair — o apagamento, esse, continua
  acontecendo na próxima passagem.

## §11 — Timer próprio da janela de decisão no core (17/11, sem bump)

**Pedido (verbatim):** `Mover a checagem de lembretes e vencimentos para um
timer periódico do core`

### 1. O que mudou

- **`runtime/launcher.py`** — `_run_radio_decisoes_forever(intervalo_s)` e o
  loop supervisionado **`radio-decisoes`** no modo `all`: a cada
  `OD_RADIO_DECISOES_INTERVALO_S` (padrão 60 s) confere `pendentes()` e roda
  `limpar_tocados()` — lembretes de 2 h e vencimentos deixam de depender da
  troca de faixa. `OD_RADIO_DECISOES_TIMER=0` desliga.
- **Sem travar o event loop:** `pendentes()`/`limpar_tocados()` (que fazem
  HTTP do FCM) rodam em `asyncio.to_thread`; erro de uma passada vira log e o
  loop continua. Sob a supervisão existente ele aparece no check `loops` do
  `/health`.
- **`tests/test_launcher_supervisor.py`** — +3 testes com dublê de rádio e
  `dormir`/`ciclos` injetados: cadência e última passada sem dormir, sem
  pendência não limpa, erro não mata o loop.

### 2. Validação

- **Gate completo:** **5382 passed / 16 skipped / 0 falha** (215,73 s, exit 0;
  eram 5379).
- **Achado no caminho (corrigido na causa):** `TestCalibracaoCorpusReal`
  passou a falhar porque os docs desta sessão usavam uma palavra que já aparece
  numa das consultas irrelevantes da calibração (falso-amigo, mesmo caso de
  2026-10-23). Reescrito para "chave `X`"; a calibração voltou a passar com os
  mesmos pisos (nada de afrouxar o teste).
- **Prova de implantação:** log `Timer da janela de decisão da rádio
  habilitado` e check `loops` verde no `/health` após o restart.

### 3. O que não foi feito

- O webhook continua chamando `limpar_tocados()` na troca de faixa (resposta
  imediata); as duas rotas são idempotentes.
- Sem métrica dedicada no `/health` para quantos lembretes saíram — só log.

## §12 — Resumo diário das faixas apagadas pela janela (17/11, sem bump)

**Pedido (verbatim):** `Criar um resumo diário das faixas apagadas
automaticamente pela janela de 24 h`

### 1. O que mudou

- **`integrations/radio_cantores.py`** — a saída de cada faixa agora tem
  procedência: vencimento grava `motivo_fim="prazo"` e `apagada_em`; negar do
  dono grava `motivo_fim="negada"`.
- **`resumo_diario()`** — lista só as apagadas pela janela nas últimas 24 h e
  devolve `{total, faixas, texto}`, com texto pronto:
  "🗑️ Resumo da janela de 24 h: N faixas apagadas sem decisão sua." + uma
  linha por faixa.
- **`enviar_resumo_se_devido()`** — uma vez por dia, a partir de
  `OD_RADIO_RESUMO_HORA` (padrão 9 h, hora local); o dia fica em
  `data/radio_decisoes_resumo.json`. Dia sem apagada é marcado em silêncio;
  falha de envio não marca (a próxima passada tenta de novo).
- **Timer do core** — o loop `radio-decisoes` chama o resumo em
  `asyncio.to_thread`, ao lado da checagem de lembretes/vencimentos.

### 2. Validação

- **Gate completo:** **5388 passed / 16 skipped / 0 falha** (216,17 s, exit 0;
  eram 5382). +6 testes: conta só prazo, ignora negada/antiga/pendente, texto,
  horário e uma vez por dia, dia vazio em silêncio, falha que tenta de novo.
- **Falso-amigo no RAG:** a primeira redação deste §12 citava a consulta
  irrelevante da calibração e derrubou `TestCalibracaoCorpusReal`; reescrita
  sem a citação, pisos intactos (mesmo padrão do achado de 2026-10-23).

### 3. O que não foi feito

- O resumo vai só para o Telegram (não por push) — é digest, não alerta.
- Não há envio sob demanda pela API/painel: `resumo_diario()` existe na
  biblioteca, mas ainda não tem rota.

## §13 — Retomada "leia iniciar" (17/11, leitura)

**Pedido (verbatim):** `leia iniciar`

### 1. Estado encontrado

- Árvore **limpa**, `HEAD == origin/master == e51b5f2` ("docs: registrar o
  resumo diário da janela de 24 h").
- `od-core` **active**, MainPID **2433306**, NRestarts=0.
- Checkpoint anterior: `resumo_diario_janela_2026_11_17` (06:35). A **janela de
  decisão de 24 h** está fechada de ponta a ponta: push FCM na entrada,
  lembrete de 2 h antes do prazo, timer próprio de 60 s no core (vencimentos +
  lembretes, em `to_thread`) e resumo diário às 9 h no Telegram.
- Gate mais recente: **5388 passed / 16 skipped / 0 falha** (216,17 s).
- Versão **1.45.1+2082** (APK com o card "Decisões pendentes (24 h)").

### 2. Novidade no `txt.txt`

Dois pedidos do dono que ainda não estavam registrados em lugar nenhum:

1. `radio-pro não esta mostrando a curiosidade da musica.`
2. `letra de musica internacional poderia tem uma lista paralela com a tradução.`

**Medido, não suposto:** `grep -i curiosidade site/radio-pro.html` = **0
ocorrências** — a página não exibe o campo. O backend já serve o dado:
`integrations/radio_agora.py::curiosidade_da_musica()` lê o `acervo.db`
(mode=ro) e filtra o placeholder "curiosidade pendente", e
`GET /api/radio/agora` devolve `tocando.curiosidade`. Ou seja, falta a página
mostrar, não falta o dado.

Os dois viraram checkbox no §4 de `docs/ANALISE_SISTEMA_TODO.md` (regra 20:
nada durável mora só no `txt.txt`).

### 3. O que não foi feito

- Nenhum código alterado, sem gate e sem restart — turno de leitura, mesmo
  padrão dos turnos 2 e 3 de 17/11.
- Sem bump: **1.45.1+2082**.

## §14 — Curiosidade da música de volta no `/radio-pro` (17/11, sem bump)

**Pedido (verbatim):** `Fazer o /radio-pro mostrar a curiosidade da música
atual`

### 1. Diagnóstico

- `grep -i curiosidade site/radio-pro.html` = **0 ocorrências**.
- `GET /api/radio/agora` já devolve `tocando.curiosidade`; quem monta é
  `integrations/radio_agora.py::montar_agora()` chamando
  `curiosidade_da_musica()` (lê o `acervo.db` em `mode=ro` e devolve `""` para
  o placeholder "curiosidade pendente").
- `GET /api/radio/pro/dados` repassa esse mesmo bloco em `agora`, então a rota
  não precisou mudar: faltava só a página pintar.

### 2. O que mudou

- `site/radio-pro.html` — card "Tocando agora" ganhou
  `<div id="agoraCurio">` e `desenhaAgora()` faz
  `texto("agoraCurio", t && t.curiosidade ? t.curiosidade : "")` (sem
  placeholder quando a faixa não tem curiosidade).
- `tests/test_radio_pro.py` — `test_pagina_mostra_a_curiosidade_da_musica`
  guarda o contrato (elemento existe e a página lê `t.curiosidade`).

### 3. Validação

- `tests/test_radio_pro.py` **58 passed**; rádio completo
  (`test_radio_curadoria` + `test_radio_link` + `test_radio_cobertura`)
  **216 passed**, 0 falha.
- Sem restart: `_serve_site_file` lê o HTML do disco a cada requisição (ETag
  por mtime, `max-age=60`) — o arquivo já está no ar.
- Sem bump: **1.45.1+2082**.

## §15 — Letra internacional com tradução em lista paralela (17/11, sem bump)

**Pedido (verbatim):** `Mostrar a letra internacional com a tradução em lista
paralela no /radio-pro`

### 1. Desenho

- **`integrations/radio_traducao.py` (novo)** — sem serviço pago e sem
  dependência nova: traduz pela **cadeia de LLM do OD** (regra 19;
  `OD_TRADUCAO_PROVIDERS` herda `OD_CHAT_PROVIDERS`), Gemini → Groq →
  llama-server local, com `asyncio.run` no handler (que já roda fora do event
  loop).
- **Cache em `data/radio_traducao.json`**, chave `artista|título` + hash curto
  da letra: versão diferente da letra não reaproveita tradução velha. Acerto
  30 dias, falha 10 min (a página sonda de 15 s em 15 s).
- **Português não ganha "tradução"**: o modelo responde `JA_PT`, vira
  `motivo="ja_em_portugues"` e a página esconde a coluna.
- **Rota separada** `GET /api/radio/pro/traducao` (mesma sessão do `/dados`):
  o `/dados` alimenta a página inteira e não pode ficar preso atrás do modelo.
- **Página:** card "Letra" em duas colunas com
  `repeat(auto-fit, minmax(260px, 1fr))` (empilha no celular), "Traduzindo…"
  enquanto espera e descarte da resposta se a faixa trocou no meio.

### 2. Validação

- `tests/test_radio_traducao.py` (novo) — **25 testes**: contrato, cache,
  invalidação por hash, `JA_PT` em 5 grafias, fallback entre providers, cache
  negativo com TTL, cache corrompido, prompt e ordem da cadeia.
- `tests/test_radio_traducao.py` + `test_radio_pro.py` + `test_api.py`:
  **285 passed**.
- `node --check` no JS inline do `/radio-pro`: OK.
- **Prova viva:** cadeia `['groq', 'gemini', 'gemma-local']`; "Hello darkness,
  my old friend / I've come to talk with you again" →
  "Olá, escuridão, minha velha amiga / Vim conversar contigo outra vez".
- **Gate completo:** **5374 passed / 19 skipped / 0 falha** (218,8 s, exit 0)
  com docs e código no lugar. Coleção: **5391 testes** contra **5365** do HEAD
  (`e51b5f2`) medidos em worktree limpo — exatamente os 26 novos. Os 19 skips
  são dependências opcionais ausentes (cv2, opentelemetry, sentence_transformers
  e `OD_TEST_POSTGRES_DSN`), não código novo.
- Rotas: **137 → 138** (`tests/test_api.py`).
- Sem bump: **1.45.1+2082**.

## §16 — Implantação da lista paralela (restart verde, 17/11)

- **Restart** (`systemctl --user restart od-core`, regra 7.3 — gate verde,
  `HEAD == origin/master`, árvore limpa): MainPID **3210320**, NRestarts=**0**.
- **Rota nova no ar:** `GET /api/radio/pro/traducao` sem sessão responde
  **401 `login_necessario`** (antes do restart seria 404) — o dispatch
  reconhece a rota; a tradução em si exige a sessão do ouvinte.
- **`/health`:** 30 checks, **29 up**; único degradado é `llm_quota`
  (**gemini 20/20 = ESGOTADA**, cota diária) — estado **pré-existente**, não
  vem desta mudança (a prova viva da tradução saiu pelo Groq).
- **Journal:** `journalctl --user -u od-core --since '2 minutes ago' -p err` →
  **No entries**.
- Página: `site/radio-pro.html` é servida do disco a cada requisição, então a
  mudança visual já valia antes do restart; o restart foi necessário só para
  a rota nova.

## §17 — Curadoria do acervo no app Android (1.46.0+2083, 17/11)

**Pedido (verbatim):** `Fechar a pendência da curadoria do acervo no app
Android`

### 1. O que mudou

- **`app/lib/services/od_api.dart`** — `OdMusicaAcervo`, `OdParMusica` e
  `OdCuradoria` (acervo + bloqueadas + exceções + decisões + `horas_decisao`)
  e 6 métodos: `buscarCuradoria`, `excluirMusicaDoAcervo(caminho, bloquear:)`,
  `bloquearMusica`, `desbloquearMusica`, `adicionarExcecao`, `removerExcecao`
  — com as mensagens de dono (403), faixa que sumiu e item que já saiu da
  lista.
- **`app/lib/screens/curadoria_screen.dart` (nova)** — busca, selo por faixa
  (`bloqueada` / `cantor bloqueado`), menu de ações com confirmação (e o
  aviso de que **excluir não bloqueia**), listas de bloqueadas e exceções com
  desfazer.
- **Painel** — card "Curadoria do acervo" (só admin) com botão **Abrir**
  (`Navigator.push`). Não virou nona aba: o rodapé já está cheio e curadoria
  é coisa de dono.
- **Bump MINOR 1.46.0+2083** nas 8 fontes do checklist (`docs/VERSIONAMENTO.md`
  §5): `.env`, `core/capabilities.py`, `app/pubspec.yaml`,
  `_APP_VERSION_CODE`, `site/index.html`, `site/historico.html` (78
  lançamentos / Era 9 com 12 releases), `docs/CHANGELOG.md` e
  `docs/README_VERSAO.md`.

### 2. Validação

- **App:** `app/test/curadoria_api_test.dart` (10) e
  `app/test/curadoria_screen_test.dart` (10) novos; `flutter analyze`
  **0 issues**; `flutter test` **257 passed / 2 skipped**.
- **APK:** `aapt2` → `versionName 1.46.0`, `versionCode 2083`; completo
  **72.406.606 B** sha256 `dec326b5…f9d0e`, arm64 **26.972.653 B** sha256
  `9c22542c…27c1`. Os antigos foram para `backups/apk-v1.45.1-2082/`.
- **Gate Python:** **5374 passed / 19 skipped / 0 falha** (224,5 s, exit 0).

### 3. Achado no caminho (corrigido na causa)

O primeiro gate desta entrega falhou em `test_llm` e `test_orchestrator` —
nada a ver com o app: a suíte lia o **`data/llm_quota.json` real**. Com o
Gemini esgotado no dia (20/20), o Orchestrator pulava o provider e o fallback
esperado não acontecia. `tests/conftest.py` agora aponta `OD_QUOTA_FILE` para
um temporário da rodada (mesma régua da guarda do `limitacoes.txt` de 01/10).
O arquivo real ficou intacto (mtime conferido).

### 4. O que não foi feito

- Sem prova visual no aparelho (a máquina não tem navegador nem emulador); a
  prova é o binário 1.46.0+2083 em `site/` + os 20 testes de app.
- A curadoria continua só para o papel admin (decisão do servidor).

### 5. Implantação (regra 7.3, gate verde)

- `systemctl --user restart od-core` → **active**, MainPID **3259841**,
  NRestarts=**0**; `journalctl -p err` da janela: **No entries**.
- **`GET /app/version`** → `version 1.46.0`, `version_code 2083`,
  `size 72406606`, sha256 **dec326b5…f9d0e** = o binário de `site/` (o updater
  do celular vê a versão nova).
- **`GET /health`** → 30 checks, único degradado é `llm_quota`
  (**gemini 20/20**, cota real do dia) — pré-existente, não vem desta entrega.
- **Site:** `/site/index.html` anuncia **v1.46.0** e `/site/historico.html`
  anuncia **Os 78 Lançamentos**.

## §18 — Revisão das checkboxes abertas do TODO (17/11, sem bump)

**Pedido (verbatim):** `Revisar as checkboxes abertas do TODO e priorizar as
próximas entregas`

### 1. Inventário medido (conferido no código, não na memória)

- Antes: **38 abertas / 73 fechadas**. Depois da higiene: **32 abertas / 78
  fechadas**.
- Fechadas com evidência (dívida de registro, não entrega nova):
  1. "Fechar o lote de 13/11" — gate 4656 e commits de 14/11.
  2. "Remover a duplicata de `_task_queue_or_503` + teste da fila" —
     `grep -c` = **1** e `tests/test_task_queue.py` (35 KB, 28 testes).
  3. "Decisão do `semantic_cache=` no boot" — commit `f2c784a`,
     `OD_SEMANTIC_CACHE_ENABLED` padrão **0** (boot loga "desligado").
  4. "`docs/ARCHITECTURE_v2.md`" — 300 linhas, commit `93aadd7`.
  5. "Fila de download resumable" — `core/downloads.py` já retoma com
     `Range: bytes=N-`, confere sha256 e publica por SSE; é o que alimenta a
     aba Downloads do app.
- Removida **duplicata** de "Task Queue (Redis/RQ)" (dois lugares do roadmap) e
  reescopado o que ficou: a fila própria já está em produção desde 14/11; o que
  resta é fila **distribuída**, sem demanda neste servidor.
- Corrigido **texto órfão** embaixo do item de `web_search` (sobra de edição).
- Reescopado "enxugar o prompt do Gemini": a cota gratuita é por
  **requisição** (20/dia), não por byte — o ganho real do item é latência e
  contexto útil.

### 2. Priorização registrada no TODO

Seção nova `### 📍 Revisão de 17/11/2026` em `docs/ANALISE_SISTEMA_TODO.md` §2:

- **P0 (esta semana):** guarda do `llm_cache` para conversa comum; corpus de
  frases reais do dono; teste ZIM ↔ compose; `.gguf` 3B + llama.cpp no espelho.
- **P1 (duas semanas):** ligar I2 (Hybrid Search) com medição; modo colapso
  declarado; backup fora da máquina **com teste de restauração**; comparador
  de modelos + monitor de hardware.
- **P2 (decisão/compra do dono):** nobreak com USB + monitor de UPS; segundo
  nó/LoRa; app por papel; OpenAI com crédito / I1 definitivamente desligado;
  limpeza do Projeti.
- **P3 (infra/demanda):** OTel Collector + Grafana; R5 eval no CI; cache de
  embedding do RAG; rótulos não-latinos; reteste do 7B; restauração do
  espelho; referências NV/Orion.

### 3. Validação

- `python3 -m pytest tests/test_rag.py -q` → **93 passed** (a calibração do RAG
  lê `docs/`; o texto novo não criou falso-amigo).
- Nenhum código alterado, sem bump (**1.46.0+2083**), sem restart.
