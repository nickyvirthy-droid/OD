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
