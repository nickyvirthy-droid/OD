# Conversa OmegaDrakon — 2026-11-14

## §1 — Retomada: "leia iniciar" (14/11 ~08:20)

**Pedido do dono:** `leia iniciar`.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md` (22 regras), `iniciar/session.json`
(entradas de 11→13/11), a transcrição `2026-11-13` inteira (§1–§6),
`txt.txt` (vazio) e `git status` / `git log` / `git diff`.

### 2. Estado encontrado

- **HEAD == origin/master == `a5ccb96`** (13/11 14:45, digest do TODO).
- **od-core ativo desde 12/11 12:57:43** — MainPID 3996872, NRestarts=0.
  Ou seja: o processo em produção é o código de **12/11**.
- 11 containers up (`od-kiwix` Up 44 h; `od-stirling-pdf`, `od-filebrowser`,
  `od-calibre-web`, `od-flatnotes`, `od-vaultwarden`, `od-homebox`,
  `od-it-tools`, `od-cyberchef`, `azuracast`, `homeassistant` Up 7 dias).
- Timers: `od-pg-dump` rodou **hoje 02:50** (OK) e `od-vigia-mensagens`
  04:33; próximas execuções 15/11.

### 3. Achado principal: um lote de 13/11 fora do registro e fora do git

A árvore **não está limpa** — 8 modificados (+716/−27) e 8 novos, feitos
**depois** do checkpoint das 14:45 de 13/11 e nunca registrados nem
commitados:

| Área | Onde | Estado |
|---|---|---|
| **R1 Task Queue** | `core/task_queue.py` (novo), rotas `/admin/tasks*` (create/list/events SSE/detail/retry/delete) em `integrations/api/server.py`, `build_task_queue` no launcher | sem teste, desligada por padrão (`OD_TASK_QUEUE_ENABLED=0`) |
| **I1 Semantic Cache** | `runtime/launcher.py`: `semantic_cache=` no `build_orchestrator` + `stats()` | ligado no caminho de boot (não no ar) |
| **OpenAI na cadeia** | `OpenAIProvider` em `core/llm.py` + `OD_OPENAI_AUTO` no launcher | pronto; chaves seguem sem crédito |
| **Actions novas** | `web_search` (DuckDuckGo lite) e `mapa_forca_consulta` (lê `data/refs_todo/Projeti/Cod`) → catálogo **123 → 125** | sem detecção em `core/intents.py` |
| **Escopo** | `core/security/scope.py`: `caminho`/`origem` em `_PATH_PARAM_KEYS` + `/tmp` quando as raízes são as padrão | fecha o bypass da auditoria de 12/11 |
| **/health** | `circuit_breakers` registrado no monitor em `runtime/launcher.py` | 27 → 28 itens |
| **pg_dump diário** | `runtime/pg_dump_diario.py` + `systemd/od-pg-dump.{service,timer}` | **ESTE JÁ ESTÁ VIVO** |
| **Docs/empacotamento** | `docs/ARCHITECTURE_v2.md`, `docs/NV_DAG_SCHEDULER_REFERENCE.md`, `pyproject.toml` (1.44.0) | novos, não commitados |

O `pg_dump` é o único item do lote que já rodou em produção: timer
instalado, 3 dumps em `data/pg_dumps/` (13/11 17:32 e 17:33, 14/11 02:50
— 33 KB, sha256 `b7d7edac…`) e journal `OD // PG DUMP OK` nas duas noites.
O resto é código não publicado: o `od-core` não reiniciou desde 12/11.

### 4. Defeitos medidos no lote (não corrigidos nesta troca)

1. **`_task_queue_or_503` definido duas vezes** em
   `integrations/api/server.py` (mesma classe, mesmo corpo) — a segunda
   definição sombreia a primeira.
2. **`core/task_queue.py` não tem teste** (`tests/test_task_queue.py` não
   existe); a única prova do lote é `tests/test_pg_dump_diario.py`.
3. `tools/actions/actions.py` e `core/llm.py` terminam **sem newline final**.
4. **Nenhum gate registrado** para este lote — não há prova de que a suíte
   passa com ele.
5. `core/intents.py` **não foi alterado**: "pesquise na internet …" ainda
   não dispara a `web_search` (a action existe, a intenção não).

### 5. Verificação desta troca

Turno de leitura — sem gate completo. Conferido: `ast.parse` nos 7
arquivos do lote (sintaxe OK), serviço ativo, timers e dumps pelo journal,
`git diff` lido por inteiro nas partes que definem comportamento.

**Sem bump:** app segue **1.44.0/2080**; sem restart do od-core.

## §2 — Fechamento do lote de 13/11 (14/11 ~08:40–10:05)

**Pedido do dono:** "Feche o lote pendente: gate completo, commits por assunto,
push e restart verde com prova viva". No meio do trabalho ele explicou que usa
**várias IAs** (ferramentas free, créditos acabam antes do fim) — o lote de 13/11
é justamente um serviço interrompido — e pediu que **toda IA informe quem fez
qual parte, os arquivos e as intenções**. Virou a regra 23 (abaixo).

### 1. Gate encontrado: 14 falhas

O primeiro `pytest tests/ -q` com o lote no lugar deu **14 failed / 4626 passed
/ 16 skipped**: todas por contagens fixas que o lote não atualizou (123 ações,
124 rotas) e, no `test_api`, também as duas listas de rotas/auth.

### 2. Defeitos reais corrigidos (medidos, não supostos)

| # | Defeito | Correção |
|---|---|---|
| 1 | A **mesma task rodava duas vezes** no `start()`: `enqueue` persistia e mantinha em memória, e `_load_pending` recarregava o disco por cima (métrica `completed` = 2 para 1 task) | `_load_pending` ignora ids já em memória/running |
| 2 | O JSON da task era **apagado no `finally`** justamente quando ela voltava para retry | unlink só em COMPLETED/DEAD_LETTER |
| 3 | O **dead letter ignorava o `queue_dir`** da instância (ia para `data/task_queue/dead_letter` global) | `self.dead_letter_dir = queue_dir/"dead_letter"` |
| 4 | `GET /admin/tasks` dava **500** (`_query_param` não existe no handler) | `parse_qs` + `limit` validado (400 `limit_invalido`) |
| 5 | O **SSE repetia** `task_running`/`task_completed` a cada segundo | emite só quando o status muda |
| 6 | `_task_queue_or_503` **definido duas vezes** em `server.py` | duplicata removida |
| 7 | `tests/test_api.py` sem as 6 rotas novas | rotas + auth + `len(ROUTES)` 124→130 |

### 3. Testes novos

`tests/test_task_queue.py` — **16 testes**: prioridade e persistência no
`enqueue`; recuperação após restart; worker concluindo com role do metadata;
sem registry → dead letter; retry até dead letter; **JSON vivo durante o backoff**
(regressão do defeito 2); `stop` encerrando workers; e a API (401 sem
credencial, 201 + listagem + detalhe, 400 de corpo/status, 404, 409 no retry de
pendente, 503 com a fila desligada).

**Gate completo: 4656 passed / 16 skipped / 0 falha (191,38 s).**

### 4. Commits por assunto

`runtime/launcher.py` misturava três assuntos: foi separado em dois commits por
hunk (`git apply --cached`) — um para a fila, outro para IA/disjuntores.

- `f9949b2` feat(pesquisa): actions web_search e mapa_forca_consulta (123→125)
- `8229a5d` feat(fila): Task Queue R1 com retry exponencial, dead letter e rotas
- `81ea83f` feat(ia): OpenAI na cadeia, Semantic Cache no boot e disjuntores
- `93aadd7` fix(segurança): caminho/origem no escopo e /tmp com raízes padrão
- `85b2177` feat(backup): pg_dump diário do Postgres od
- `docs(arquitetura)` — ARCHITECTURE_v2, referência DAG do NV, pyproject
- `docs(iniciar)` — regra 23, livro-caixa, transcrição, TODO, CHANGELOG

### 5. Regra 23 — atribuição obrigatória

`iniciar/RULES.md` ganhou a regra 23 e nasceu o livro-caixa
**`iniciar/ATRIBUICOES.md`**: toda entrega, de qualquer IA, declara autor,
arquivos criados/modificados e intenção + estado (o que ficou pela metade e o
próximo passo). Origem desconhecida é registrada como desconhecida — o lote de
13/11 está assim.

### 6. Deploy e prova viva

Ver §3 desta transcrição (preenchido após o restart).

## §3 — Publicação e restart verde (14/11 ~09:03)

### 1. Uma decisão tomada no fechamento (não no lote)

O lote ligava o **I1 Semantic Cache** no boot sem aprovação. Como a decisão de
ligar é do dono (risco de servir resposta parecida na ≥ 0.95), a ligação ficou
**desligada por padrão**: `OD_SEMANTIC_CACHE_ENABLED=1` no `.env` é o único
passo que falta. Commit `f2c784a`.

### 2. Publicação

- `git push origin master` → **`a5ccb96..f2c784a`**; árvore limpa,
  `HEAD == origin/master == f2c784a`.
- Nove commits por assunto (oito do lote + o ajuste do I1), com o
  `runtime/launcher.py` separado por hunk entre fila e IA.

### 3. Gate antes do restart (executado de novo após o ajuste do I1)

`pytest tests/ -q` → **4656 passed / 16 skipped / 0 falha (189,29 s)**, exit 0.

### 4. Restart e prova viva (`systemctl --user restart od-core`)

- **MainPID 2424782**, **NRestarts=0**, `active`, subido **09:03:49**.
- `journal -p err` desde o restart: **No entries**.
- Boot no journal: `Semantic Cache desligado (OD_SEMANTIC_CACHE_ENABLED=0)`,
  `Orchestrator real montado | llm=['gemini','groq','gemma-local'] … 
  semantic_cache=desligado`, `TaskQueue desabilitado (OD_TASK_QUEUE_ENABLED=0)`,
  `API REST no ar`.
- **`/health`: `ok=true` com 28 itens** — o check `circuit_breakers` está no ar
  (era o item invisível desde 11/11).
- **`GET /admin/tasks` → 503 `task_queue_indisponivel`** — rota viva e a fila
  desligada por padrão, como documentado.
- **`/llms`**: gemini, groq, gemma-local (ordem correta).
- **Chat real**: "qual o uso de disco" → `route=action_intent`,
  `llm_used=fastpath:disk_usage`, **35,9 ms**, resposta
  `💾 Disco /: 66.2% usado · 67.7 GB livres de 231.2 GB` (dado medido, sem LLM).

**Sem bump:** app segue **1.44.0/2080** (servidor/infra).

## §4 — Pesquisa web ligada à intenção e provada no chat (14/11 ~09:20–09:35)

**Pedido do dono:** "Ligue a action web_search à intenção 'pesquise na
internet…' e teste no chat real."

- **`core/intents.py`**: `_extrai_busca_web` reconhece verbo de busca no
  início (`pesquise`, `busque`, `procure`, `faça uma busca`), tira veículo
  (`na internet`, `no google`, `na web`, `online`) e conector (`sobre`, `por`,
  `de`); substantivo ("a pesquisa mostrou…") e comando sem termo **não** casam.
  `_formata_web_search` responde com até 5 resultados (título, URL, trecho,
  fonte) e **degrada honestamente** sem rede — nunca cai no LLM.
- **Câmbio preservado**: "pesquise na web: preço do bitcoin" continua em
  `exchange_rate`.
- **Testes**: `TestPesquisaWeb` (+16) em `tests/test_intents.py`.
  **Gate: 4672 passed / 16 skipped / 0 falha (189,78 s).**
- **Publicado**: `6d1e49b` (`2218c01..6d1e49b`).
- **Restart**: MainPID **2448964**, NRestarts=0, journal `-p err` **0**.
- **Prova viva**: "pesquise na internet sobre a Reforma Tributária 2026" →
  `action_intent / fastpath:web_search`, **1,05 s**, 5 resultados com fonte;
  "quem foi Alan Turing" → **0,74 s**, 5 resultados (Wikipédia, TecnoBlog,
  Brasil Escola…).

**Sem bump:** app segue 1.44.0/2080.

## §5 — Pergunta do dono: Semantic Cache ligado ou desligado? (14/11)

**Pergunta:** "o que faz semantic cache? qual a melhor alternativa para ele,
ficar ligado ou desligado?"

**O que é (código lido):** `memory/semantic_cache.py` guarda
`prompt → resposta` com o embedding do prompt (MiniLM local, 384 dims) e, na
leitura, devolve a resposta da entrada mais parecida **se o cosseno ≥ 0,95**
(TTL 24 h, 5000 entradas, por perfil). É um cache de *significado*, não de
texto exato — o `LLMCache` já cobre o exato.

**Medido neste turno** (`all-MiniLM-L6-v2`, modelo já em cache local):

| par | similaridade |
|---|---|
| "quem foi Alan Turing" × "quem foi Alan Turing?" | **0,979** |
| "qual o uso de disco" × "qual o uso do disco" | 0,921 |
| "pesquise … sobre python" × "… sobre python 3.13" | 0,913 |
| "liga a luz da cozinha" × "liga a luz da sala" | 0,887 |
| "bom dia" × "bom dia, tudo bem?" | 0,816 |
| "quem foi Alan Turing" × "quem foi Ada Lovelace" | 0,550 |

Custo medido do embedding: **~17 ms por mensagem** (medido com o gate rodando
em paralelo, portanto pessimista).

**Conclusão:** com 0,95 o cache é **seguro e quase inútil** — só acerta
diferença de pontuação/erro de digitação (0,979), e o gargalo real do chat hoje
é a **cota diária** do Gemini, não o tempo de resposta. Abaixar para 0,85–0,90
para ele render exigiria aceitar trocas erradas — "liga a luz da cozinha" e
"liga a luz da sala" ficam em 0,887, ou seja, **acenderia o cômodo errado**.
Recomendação: **manter desligado** (é o default atual,
`OD_SEMANTIC_CACHE_ENABLED=0`); o ganho real viria de cache exato (já existe) e
de aproveitar as 20 req/dia com critério. A decisão continua do dono.

## §6 — Pesquisa web liberada para user/família, provada com conta comum (14/11 ~10:00)

**Pedido do dono:** "Exponha a pesquisa web aos papéis família/user e teste com
uma conta comum."

**Autor:** Freebuff (Buffy). **Arquivos:** `core/security/permissions.py` e
`tests/test_security.py` (modificados); `docs/CHANGELOG.md`,
`docs/ANALISE_SISTEMA_TODO.md` e esta transcrição (registro).

- **Mudança:** `web_search` na lista do papel `user` (o `familia` herda por
  código). Justificativa: é leitura pública da fonte, sem chave/escrita/segredo
  — mesma natureza de `weather_city`/`exchange_rate`. Sem isso, quem não é o
  dono caía em **negação silenciosa** e o LLM voltava a inventar.
- **Fronteira preservada:** `mapa_forca_consulta` (nomes/matrículas de
  policiais) continua só do dono — acrescentado ao teste de menor privilégio.
- **Testes:** `test_user_e_familia_podem_pesquisar_na_web` + o item de dado
  sensível. **Gate: 4673 passed / 16 skipped / 0 falha (188,36 s).**
- **Publicado:** `13ac90d`. **Restart:** MainPID **2464540**, NRestarts=0,
  journal `-p err` **0**.

**Prova viva com conta comum** (não-dono), criada por `/auth/register`:

| papel | frase | resultado |
|---|---|---|
| `user` | "pesquise na internet quem foi Ada Lovelace" | `fastpath:web_search`, **1,00 s**, 4 resultados (Wikipédia, Brasil Escola…) |
| `família` | "pesquise na internet sobre o ENEM 2026" | `fastpath:web_search`, **0,68 s**, resultados reais (G1) |

**Limpeza:** conta `teste_pesquisa_14` apagada por `DELETE /admin/users`
(confirmado ausente na listagem) e as **4 mensagens** que ela gravou em
`conversation_messages` removidas por SQL — nenhum resíduo no banco.

**Sem bump:** app segue 1.44.0/2080.

## §7 — Hit rate do LLMCache exato no uso real (14/11 ~10:20)

**Pedido do dono:** "Meça o hit rate do LLMCache exato no uso real antes de
investir em cache semântico."

**Autor:** Freebuff (Buffy). **Nenhum código alterado** — só medição e
registro (`docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/`).

**Método:** logs `Message processed` do journal (janela de ~29 dias,
16/10→14/11) classificados por `route`; tabela `llm_cache` para o acumulado; as
mensagens reais de `conversation_messages` para o potencial de paráfrase
(MiniLM + janela de 24 h, mesmo usuário).

### 1. Cache exato

| métrica | valor |
|---|---|
| mensagens processadas | 210 |
| comandos de action (bypass proposital) | 95 |
| `datetime` fastpath | 2 |
| conversa (llm 73 + fallback 28 + cache 12) | 113 |
| **hit rate** | **12/113 = 10,6%** |
| últimos 7 dias | 9/66 = 13,6% |
| p50 com cache | **10,4 ms** |
| p50 sem cache | **33.532 ms** |
| tabela `llm_cache` | 136 entradas · 177 usos · 41 reúsos · média 1,30 |

### 2. Potencial do semântico (dados reais)

81 mensagens de usuário em 30 dias: **57 (70%) são comandos**, que o pipeline
não cacheia de propósito; **24 elegíveis**. Repetição exata em 24 h: **4/24
(16,7%)**. Paráfrases que passariam do corte: **0 em 0,95**, **0 em 0,90**,
**0 em 0,85**. Normalizar caixa/acento/pontuação não acrescentou hit (4/24 →
4/24).

### 3. Conclusão

O cache exato paga: ~11% de acerto e ~33 s por hit. O semântico **não teria
acertado nenhuma mensagem adicional** no tráfego medido, com qualquer corte
razoável — investir nele agora é esforço sem retorno medido. Fica desligado
(default) e a decisão tem número.

**Limitações:** amostra pequena (113 mensagens de conversa, 24 elegíveis);
janela limitada pela rotação do journal; histórico retido pode podar mensagens
antigas. Os arquivos temporários com texto de conversa foram apagados.

**Sem bump:** app segue 1.44.0/2080; sem restart (nenhum código mudou).
