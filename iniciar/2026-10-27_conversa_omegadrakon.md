# Transcrição da sessão — 2026-10-27

## §1 — "leia iniciar. continue de onde parou" (27/10 ~13:45): resíduo da
       frente dos FATOS DO MODELO LOCAL achado e FECHADO — ordem nova das
       fontes (etapa 4.6/4.6b) + 3 travas do enciclopédia, provadas ao vivo

**Pedido:** usuário: "leia iniciar. continue de onde parou" — reverificação
de rotina + retomada (regras 3/4). Checkpoint lido: `session.json` (chave
`reverificacao_rotina_2026_10_26_1946`, updated 26/10 20:12, com a frente
"FATOS DO MODELO LOCAL (6x 24/10)" marcada como **AGUARDANDO régua do
dono**) + transcrição `2026-10-26` §1–§7 + `RULES.md`.

**Achado principal — RESÍDUO NO DISCO (sessão morta 26/10 21:16):** `git
status` sujo com **1 arquivo** — `memory/enciclopedia.py` (+18/−5, só a
docstring), última edição **21:16**, ~17 h parados. A docstring já trazia
a **régua do dono de 26/10** escrita ("pergunta de FATO consulta ESTA
fonte ANTES do acervo da casa") e as 3 travas medidas, mas **nenhuma linha
de código** existia: a sessão morreu entre a spec e a implementação —
mesmo padrão das interrupções de 21–26/10. Contexto medido antes de
decidir (regra 5):

- HEAD `8b84eab` == `origin/master`, árvore limpa fora do resíduo, sistema
  verde (v1.44.0/2080, health 25/25);
- `txt.txt` **zerado desde 26/10 18:25** (nenhuma mensagem nova do dono);
  `analise/` = só `Nicky Locutor/` (pendente, aguardando ordem — regra 17)
  + relatórios do próprio vigia;
- vigia das mensagens disparou **27/10 04:33/04:34**: 4 sondas **verdes**
  (as 2 frentes fechadas ontem seguem fechadas) e **fila com 8 itens** —
  3× *"quantas pessoas"* + 2× inconsistente + **3× novos `resposta_errada`
  de 26/10 20:43** ("define dia", "o que é o sol?", "quem descobriu a
  penicilina?") = exatamente a classe dos FATOS DO MODELO LOCAL que a
  docstring do resíduo descrevia.

**Entrega (a frente da docstring, implementada):**

1. `memory/enciclopedia.py`:
   - `eh_pergunta_de_fato()` — verbo-guia (`define`, `o que é`, `quem
     foi`…) ou interrogativo factual (`o que/quem/onde/quando/qual/quais`);
     **`quantas…` fica de fora de propósito** (contagem é dado do sistema,
     fastpath de rede, não enciclopédia);
   - `_eh_pt()` — o catálogo devolve **`por`** (ISO 639-2) e a ordem antiga
     comparava com `"pt"`: empatava com `"eng"` e o EN vencia pela ordem do
     catálogo (é o que devolvia desambiguação e o artigo errado);
   - `_eh_desambiguacao()` — recusa página de sentidos no título direto e
     no hit da busca;
   - trava final nos DOIS caminhos: título tem que **casar com o assunto**
     (≥1 termo em comum e **no máximo 1 token extra**, ou 2 em comum);
   - `NOTA_SEM_FONTE` (etapa 4.6b) + campo `recusados` no resultado.
2. `core/orchestrator.py`: `_bloco_de_referencia()` centraliza 4.5/4.6/4.6b
   nos **dois transportes** (REST + WS) — pergunta de fato: fonte
   verificada **primeiro**, acervo só se não houver artigo, sem artigo em
   nenhuma → **nota honesta**; fora de fato: ordem antiga. Uma fonte por
   prompt. Métrica nova `enciclopedia_sem_fonte`.
3. `runtime/launcher.py`: docstring/log da `build_enciclopedia()`
   atualizados para a ordem nova.
4. Guardas **+26** (`tests/test_enciclopedia.py` 21 → 47).

**A prova viva achou um defeito da própria entrega (27/10, pós-restart):**
*"o que é o sol, em uma frase?"* injetou **"O império no qual o sol nunca
se põe"** — 1 termo em comum, 4 tokens fora do assunto — porque o piso era
de 1 overlap. Trava 3 endurecida no mesmo dia (**+2 guardas**: o caso ao
vivo e o qualifier de 1 token que continua valendo).

**Validação (regra 6):** gate oficial **3× verde**: `3887 / 16 skipped /
0 falha · 90,59%` (antes do CHANGELOG), `3887` de novo após a edição do
CHANGELOG, `3889` após o endurecimento + CHANGELOG (eram **3863** — os
**+26** são as guardas novas). pyflakes **0 aviso novo** (os 4 de
`orchestrator.py`/`launcher.py` conferidos contra o HEAD via `git stash`).

**Deploy (regras 7.1/7.3):** `7e0b8a4` (frente) + `b98971c` (endurecimento
pela prova viva) pushados, HEAD == `origin/master`, árvore limpa. Restart
verde **27/10 14:11:23**, `MainPID 1633473`, `NRestarts=0`, `/health`
**25/25 nenhum fora**, `/app/version` **1.44.0/2080** intacta, journal
desde o boot **0 `[ERROR]`**.

**Prova viva (chat real, POST `/message`):**

- *"qual é o sol?"* → journal **`Enciclopédia: artigo por título direto |
  titulo=Sol | livro=wikipedia_pt_all_mini_2026-05`** + **`Enciclopédia no
  prompt | titulo=Sol | chars=1322`** → **"O Sol é a estrela central do
  Sistema Solar… ~150 milhões de quilômetros"** (antes: *"gigante
  asteróide"* / *"estrela gigante… iluminação da Terra durante a noite"*,
  saído do modelo sem fonte). RAG **não** consultado.
- *"quem foi alexander fleming?"* → **`titulo=Alexander Fleming |
  chars=624`** → datas e descoberta da penicilina corretas.
- Métricas do ciclo: `enciclopedias=6 · blocos=2 · erros=0 · sem_fonte=0 ·
  rag_consultas=5` — as perguntas de fato consultaram **primeiro** a fonte
  verificada; o acervo entrou só nas que ficaram sem artigo.
- **Dois achados honestos para a fila:** (a) a **etapa 4.6b não disparou
  ao vivo em 6 tentativas** — sem artigo no Kiwix, o acervo devolve trecho
  fraco mesmo para termo inventado (`min_overlap 0.036`), o prompt não
  fica vazio e o modelo local continua livre para inventar (*"quem
  inventou o flogisto líquido?"* → invenção); exigir relevância do trecho
  do acervo em pergunta de fato é **decisão de design** (fila do dono);
  (b) as **respostas erradas de 26/10 continuam no cache do LLM**
  (`route=cache` serviu "penicilina" inventada) — poda com `--apply` no
  `runtime/llm_cache_saneamento.py` é ação destrutiva, **aguardando ordem**
  (regra 7).

**Canais do dono:** `txt.txt` escrito com o resumo da entrega (regra 14) +
mesmo resumo no Telegram (regra 15). `analise/Nicky Locutor/` segue
pendente, aguardando ordem (regra 17).

**Estado:** SISTEMA VERDE E NO AR — v1.44.0/2080, HEAD `b98971c`, árvore
limpa, health 25/25. Frente dos **FATOS DO MODELO LOCAL (ordem das
fontes)** FECHADA e provada ao vivo. Fila do dono: (a) relevância do
trecho do acervo em pergunta de fato (design), (b) poda do cache com
respostas erradas de 24–26/10 (destrutiva, sob ordem), (c) parking lot §5
restante: rota WiFi, auditoria de uso de ferramentas, MCP, (d)
`analise/Nicky Locutor/`.
