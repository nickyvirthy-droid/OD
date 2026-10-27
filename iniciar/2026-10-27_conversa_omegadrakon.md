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

## §2 — "continue. feche o 4.6b e limpe o cache" (27/10 ~14:40): piso de
       fato no acervo + PODA de 20 respostas erradas — as duas limitações
       honestas da §1 fechadas no mesmo turno

**Pedido:** dono: *"continue. feche o 4.6b e limpe o cache"* — as duas
pendências que eu mesmo apontei na §1 (régua dele já valendo: os dois
itens foram oferecidos como fila e ele mandou executar).

**Medição antes de codar (regra 5 — pipeline RAG real, 2216 chunks):**

| pergunta (sem artigo no Kiwix) | floor antigo | piso de fato |
|---|---|---|
| `quem inventou o flogisto líquido?` | **1 trecho do CHANGELOG, ov=0.66** (o raro `flogisto` não estava lá — o overlap vinha de palavra comum) | bloco vazio → 4.6b |
| `quem descobriu a odmistica?` / `o que é a xilofonética?` / `quem foi o sábio odralak?` | 0 trechos (sorte: o termo não existe no corpus) | idem |
| `o que é o omegadrakon?` / `quem é o vigia…` / `qual a versão atual…` | 4 / 3 / 2 trechos, ov 1.0 / 0.69 / 0.76 | **seguem passando** (termo identidade presente) |

**Entrega:**

1. `memory/rag.py`: `consult(..., fato=True)` — **piso de fato**: o trecho
   só entra se citar o termo **mais raro** da pergunta **original** (maior
   IDF do corpus = identidade do assunto; termo nunca visto tem o maior
   IDF e não pode estar em nenhum trecho → derruba o bloco). Descarte
   conta como `descartados_floor`. Fora de `fato=True`, **nada muda**.
2. `core/orchestrator.py`: `_bloco_rag(..., fato=True)` **só** no caminho
   de pergunta de fato; sem artigo E sem trecho que case → **nota 4.6b**.
3. Guardas **+3** (`test_rag.py` +1 — presente segue, inventado derruba;
   `test_enciclopedia.py` +2 — `fato=True` só no caminho de fato).
4. `runtime/llm_cache_saneamento.py`: `PODA_PROMPTS` ampliado com **20
   prompts EVIDENCIADOS pelo juiz** — 4 fabricadas de 22/10 (3 senhas +
   "fentanila quimioterápico"), 6× fato errado de 24/10, 3× da fila do
   vigia de 26/10, 4× inventadas na apuração viva de 27/10.

**Poda (regra 7: dry-run primeiro, `--apply` sob ordem dele):** dry-run
conferido linha a linha → `--so poda --apply` removeu **20 linhas**
(110 → 90) com snapshot de rollback
`backups/llm-cache-poda-20261027-150933.bak`. Entre as podadas: a senha
fabricada do file browser, `calibrer123`, "fentanila quimioterápico",
"Sol é um gigante asteróide" e "Antoine Marie Eschaton". Cache é lido do
Postgres a cada consulta → vale **sem restart**.

**Validação:** gate oficial **3892 passed / 16 skipped / 0 falha ·
90,60%** (eram 3889 — os **+3** são as guardas novas); pyflakes 0 aviso
novo. Commit **`d5d2daf`** pushado, árvore limpa, HEAD == origin/master.
**Restart verde 15:14:12** (MainPID 1696462, NRestarts=0, health 25/25,
1.44.0/2080, journal 0 `[ERROR]`).

**Prova viva (`cache_hits=0` nas 3 perguntas podadas — a poda funcionou):**

- *"quem inventou o flogisto líquido?"* → journal **`Nota de fonte
  (4.6b): pergunta de fato sem artigo`** + **`enciclopedia_sem_fonte=1`**
  → **"Isso não existe no sistema."** (antes: *"criada por William Cullen
  em 1746"*, inventada **e** servida pelo cache).
- *"define dia"* → **`artigo por título direto | titulo=Dia`** →
  **"intervalo igual a 24 horas"** (promessa original da etapa 4.6).
- *"quem descobriu a penicilina?"* → Wikipédia sem artigo para a frase
  crua, o acervo casou pelo termo identidade → **Alexander Fleming, 1928**
  (a errada cachada dizia *"Antoine Marie Eschaton"*).

**Nota honesta / fila:** a limpeza de verbos-guia (`quem descobriu…`) no
assunto da consulta do Kiwix **não** está coberta — por isso a Wikipédia
não achou "Penicilina" com a frase crua. Candidata a próxima frente,
junto com a decisão de piso do acervo (que hoje já tem o piso de fato).

**Estado:** SISTEMA VERDE E NO AR — v1.44.0/2080, HEAD `d5d2daf`,
árvore limpa, health 25/25, cache com 93 linhas (90 podadas + 3 recriadas
**pelas respostas novas** da prova viva). `txt.txt` + Telegram avisados.

## §3 — "Limpar os verbos-guia do assunto consultado no Kiwix" (27/10
       ~15:50): a frase CRUA agora acha o artigo — 3 provas vivas pelo
       título direto

**Pedido:** dono escolheu o follow-up da §2 — *"Limpar os verbos-guia do
assunto consultado no Kiwix para a Wikipedia achar o artigo com a frase
crua"*.

**O que estava errado (medido na prova viva da §2):** `_assunto_da_pergunta`
só tirava o prefixo `define/o que é/quem foi…`. Sobravam na busca:

- `quem descobriu a penicilina?` → termos **`quem descobriu penicilina`**
  (3 termos, `quem` nem era stopword da casa) → kiwix sem artigo;
- `o que é o sol, em uma frase?` → **`sol responda frase`** → título
  direto `Sol_Frase` 404 → busca escolhia o artigo tangencial (o
  "império" da §1);
- `quem foi marie curie, em 3 frases?` → `marie curie frases`.

**Entrega (`memory/enciclopedia.py`):** o assunto passa a ter **3
limpezas** — (1) prefixo (já existia), (2) **enquadramento à esquerda**
(wh + stopwords + verbos-guia até o primeiro conteúdo) **com safeguard**
(só come o verbo se RESTAR conteúdo: *"o que é a descoberta?"* mantém
`descoberta`), (3) **instrução final** cortada (`", em 3 frases"`,
`", em uma frase"`, `"responda com uma frase"`). Guardas **+4**; o caso
tangencial da §1 agora cobre as duas travas no mesmo teste.

**Validação:** gate **3895 passed / 16 skipped / 0 falha** em todas as
rodadas, **≥ 90% sempre** (faixa de 90,4% a 90,6% com corpus reeditado
entre as rodadas; eram 3892) · pyflakes 0 aviso novo · commit **`311f4de`**
pushado, árvore limpa · **restart verde 16:03:08** (MainPID 1750867,
NRestarts=0, health 25/25, 1.44.0/2080, journal 0 `[ERROR]`).

**Prova viva (as 3 no TÍTULO DIRETO do acervo PT, `candidatos=0`):**

| pergunta (crua) | journal | resposta |
|---|---|---|
| `quem inventou a penicilina?` | `titulo=Penicilina \| chars=1329` | "Alex Fleming" |
| `quem foi marie curie, em 3 frases?` | `titulo=Marie Curie \| chars=1330` | física/química, 2 Nobels |
| `o que é o sol, em uma frase?` | `titulo=Sol \| chars=1322` | "estrela central do Sistema Solar… 99,86% da massa" |

Antes: frase crua sem artigo, instrução poluindo a busca e o artigo do
império espanhol no lugar do Sol.

**Estado:** SISTEMA VERDE E NO AR — v1.44.0/2080, HEAD `311f4de`,
árvore limpa, health 25/25. Fila do dono inalterada: `analise/Nicky
Locutor/`, rota WiFi, auditoria de uso de ferramentas, MCP.

## §4 — "leia iniciar" (27/10 ~16:50): reverificação de rotina — tudo
       verde, sem resíduo, fila do dono inalterada

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint lido: `session.json` (chave `frase_crua_limpa_para_o_kiwix_2026_10_27`,
updated 16:10, §3 — frente FECHADA) + transcrição de 27/10 §1–§3 + `RULES.md`.

**Achados verdes (medidos, regra 5):** git **ÁRVORE LIMPA**, HEAD `bf9fa51`
(commit de registro da §3) == `origin/master`. `od-core` active desde
**16:03:08**, MainPID 1750867, 41 min sem restart. `/health` autenticado
**ok=True, 25 checks NENHUM fora**; `/app/version` **1.44.0/2080** intacta.
Journal desde o restart: **0 `[ERROR]`** e **1 `[WARN]`** = o próprio alerta
proativo `key=restart` do boot (esperado). **Nenhum resíduo** — nada
modificado sem commit desde a §3 (diferente do padrão das interrupções de
21–26/10).

**Canais do dono:** `txt.txt` = nossa entrega da §3 escrita 16:06 —
**NENHUMA mensagem nova dele**. `analise/` = apenas `Nicky Locutor/`
(PENDENTE desde 23/10, aguardando ordem — regra 17) + 5 relatórios do
vigia (nossos).

**Vigia:** disparou 27/10 04:33/04:34 — 4 sondas **VERDES**, fila de
8 itens, **todos anteriores** às frentes fechadas hoje (5× "quantas
pessoas" + 3× fato errado de 26/10 20:43 — "define dia", "o que é o
sol?", "quem descobriu a penicilina?" — consertados e provados ao vivo
nas §1/§2/§3). Nenhum problema novo. Próximo disparo: 28/10 04:30.

**Estado:** SISTEMA VERDE E ESTÁVEL — v1.44.0/2080, HEAD `bf9fa51`,
árvore limpa, health 25/25. Nenhuma mutação nesta troca. Fila do dono:
(a) `analise/Nicky Locutor/` (pauta única de conteúdo), (b) parking lot
§5 restante: rota WiFi, auditoria de uso de ferramentas, MCP.
