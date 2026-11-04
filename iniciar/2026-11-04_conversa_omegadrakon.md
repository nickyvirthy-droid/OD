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
