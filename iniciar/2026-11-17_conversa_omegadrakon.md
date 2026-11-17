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
   bloqueio de download é o limite de tamanho/tempo do pipeline.
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
  decidida/não pendente/400/403/401), prazo e tempo restante, registro
  legado, e o toque **não** apagando mais; na curadoria, exclusão sem
  bloqueio e com `bloquear=True` explícito; no `radio_pro`, música bloqueada
  marcada e dono avisado.
- **JS:** página e painel passam no `node --check` (testes de `test_api.py`).

### 4. Estado ao fechar

- Sem bump: **1.45.0+2081**.
- O prazo é conferido pelo webhook da rádio (`limpar_tocados` a cada troca de
  faixa) — resolução de minutos, não de segundos.
