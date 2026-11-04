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
