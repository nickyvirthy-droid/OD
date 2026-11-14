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

---

## §8 — Retomada: "leia iniciar" (14/11 ~11:50)

**Pedido do dono:** "leia iniciar" (segunda retomada do dia, regra 3).

**Autor:** Freebuff (Buffy). **Nenhum código alterado** — leitura e registro.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md` (23 regras), `iniciar/session.json`
(entradas de 12–14/11), `iniciar/ATRIBUICOES.md`, esta transcrição inteira
(§1–§7), `txt.txt` (vazio) e `git status`/`git log`/estado do serviço.

### 2. Estado encontrado

Árvore **limpa**; `HEAD == origin/master == 8370c7b`. `od-core` ativo,
MainPID 2464540, `NRestarts=0` — roda o código de `13ac90d` (web_search
liberada a `user`/`família`).

### 3. O que ficou aberto

1. `OD_TASK_QUEUE_ENABLED=0` — a fila R1 existe e tem teste, mas nunca rodou
   em produção.
2. I1 (Semantic Cache) **desligado** por default, aguardando decisão do dono —
   e agora com número: não acrescentaria acerto no tráfego medido (§7).
3. OpenAI fora da cadeia automática por falta de crédito (o `OD_OPENAI_AUTO`
   só testa a existência da chave).
4. Backlog do `docs/ANALISE_SISTEMA_TODO.md`: cota do Gemini, disjuntores no
   `/health`, rádio/Bluetooth, energia/comunicação (compra do dono), NV (DAG/
   scheduler) e Projeti.

**Sem bump / sem restart:** app segue 1.44.0/2080; nada de código mudou.

---

## §9 — Task Queue provada em sandbox com task real (14/11 ~12:00–12:50)

**Pedido do dono:** "Ligue a Task Queue num teste controlado com
`OD_TASK_QUEUE_ENABLED=1` e prove com uma task real, medindo retry e dead
letter."

**Autor:** Freebuff (Buffy).

### 1. Defeitos medidos antes da prova

Antes de rodar, a leitura do contrato apontou o problema: `TaskQueue` chama
`registry.execute(..., request_id=...)`, mas o `ActionRegistry` aceita
`session_id`. O teste antigo não pegava porque o `_RegistryFalso` dos testes
declara `**kwargs`.

O sandbox confirmou (2 tasks, 0 concluídas, 2 em dead letter, 4 retries):

```
ActionRegistry.execute() got an unexpected keyword argument 'request_id'
```

O segundo achado veio do próprio teste: `DELETE /admin/tasks/{id}` apagava em
`data/task_queue/dead_letter` **fixo** — respondia 200, o arquivo continuava e
o `GET` seguia devolvendo a task.

Correções: `session_id=task.task_id` em `core/task_queue.py`; `tq.dead_letter_dir`
em `integrations/api/server.py`.

### 2. Prova (sandbox: API + ActionRegistry + catálogo reais, `/tmp`, 1 worker)

| passo | medida |
|---|---|
| `POST /admin/tasks` `filesystem_write` | **201**; arquivo com o conteúdo em **1,0 s**; `completed = 1` |
| `filesystem_read` de arquivo inexistente | tentativa 1 em **1,0 s** → tentativa 2 em **2,7 s** → **dead letter** em **6,5 s** (attempts 3; backoff medido 1,7 s e 3,8 s, com jitter) |
| dead letter | JSON em `/tmp/od-tq-sandbox/fila/dead_letter/` (queue_dir da instância) |
| `DELETE /admin/tasks/{id}` | 200 → arquivo removido → `GET` **404** |
| métricas | `enqueued 2 · completed 1 · failed 1 · dead_letter 1 · retried 2` |

### 3. Gate e testes

`tests/test_task_queue.py` 16 → **18** (task real no registry real; DELETE do
dead letter no `queue_dir` da instância). **Gate completo: 4675 passed / 16
skipped / 0 falha** (193,28 s).

### 4. Limitação e decisão

Task **concluída** some da API: o JSON é apagado no `finally` e ela não está
mais em memória — `GET /admin/tasks/{id}` devolve 404 e a listagem nunca mostra
`completed`. Vira checkbox no TODO (decisão de retenção de histórico).

A fila **continua desligada em produção** (`OD_TASK_QUEUE_ENABLED=0`); ligar é
decisão do dono. O código corrigido entra no ar com restart verde.

**Sem bump:** app segue 1.44.0/2080 (correção interna de servidor).

### 5. Deploy e prova viva

Commits `f583fb2` (fix) e `eda77b9` (docs) publicados. `systemctl --user
restart od-core`: **MainPID 2618250**, `NRestarts=0`, ativo desde 12:12:25;
`/health` **ok=true, 28 itens, nenhum falhando**; journal `-p err` **0
entradas**. Boot registra `TaskQueue desabilitado (OD_TASK_QUEUE_ENABLED=0)` e
`GET /admin/tasks` responde **503 `task_queue_indisponivel`** — o esperado com a
fila desligada. Resumo enviado ao Telegram do dono (`ok=true`, msg 3996).

---

## §10 — Task Queue: concluídas visíveis com retenção e poda (14/11 ~13:00–13:45)

**Pedido do dono:** "Faça as tasks concluídas continuarem visíveis na API, com
retenção limitada e poda automática."

**Autor:** Freebuff (Buffy).

### 1. Desenho

- Concluída sai de `queue_dir/*.json` (para `_load_pending` não a tratar como
  pendente num restart) e vai para `queue_dir/completed/{id}.json`.
- `GET /admin/tasks/{id}` e `?status=completed` devolvem `completed` com
  `result`; `DELETE` apaga o registro do histórico.
- Retenção por `OD_TASK_QUEUE_KEEP_COMPLETED` (**200**); poda no `start()` e a
  cada conclusão, mantendo as N mais recentes por `finished_ts` (mtime como
  reserva).

### 2. Prova em sandbox (API + registry + catálogo reais, KEEP_COMPLETED=2)

| passo | medida |
|---|---|
| 3 tasks reais `filesystem_exists` | concluídas, `result=true` |
| `GET /admin/tasks/{recente}` | **200**, `status=completed`, `result=true` |
| `GET /admin/tasks?status=completed` | **count = 2** |
| `GET /admin/tasks?status=dead_letter` | count = 0 |
| histórico em disco | 2 arquivos (os 2 mais recentes) |
| `GET` da mais antiga (podada) | **404** |

### 3. Gate

`tests/test_task_queue.py` 18 → **20** (histórico visível + poda; concluída na
API e `DELETE` removendo o histórico). **Gate completo: 4677 passed / 16
skipped / 0 falha** (196,06 s).

**Sem bump / fila segue desligada em produção** (decisão do dono). Tela de
histórico no painel/app e filtro por data viraram checkboxes no TODO.

### 4. Deploy e prova viva

Commits `4a11491` (feat) e `f54cbcf` (docs) publicados. Restart do `od-core`:
**MainPID 2635416**, `NRestarts=0`; `/health` **ok=true, 28 itens, nenhum
falhando**; journal `-p err` **0 entradas**; `GET /admin/tasks` = **503**
(fila desligada, esperado). Telegram do dono: `ok=true`, msg 3997.

---

## §11 — Histórico de tasks no painel `/admin` e no app (14/11 ~14:00–15:10)

**Pedido do dono:** "Mostre o histórico de tasks no painel/app com status e
resultado."

**Autor:** Freebuff (Buffy).

### 1. Painel `/admin`

Novo bloco **"Tarefas (Task Queue)"**: tabela com ação, status (pendente /
rodando / concluída / falha / dead letter), tentativas `n/max`, criação,
**duração** (relógio correndo em `running`), resultado em JSON curto ou o erro
da última tentativa, e as ações ⟳ (reenfileirar falha/dead letter) e 🗑 (apagar
registro terminal). Filtro por status, resumo da fila pelo `snapshot` do SSE
(`/admin/tasks/events`) e aviso explícito quando a fila responde 503.

### 2. App Flutter

`TasksScreen` como 8ª aba (depois de Downloads): os mesmos campos, filtro em
chips, retry, apagar com confirmação, releitura a cada 5 s e mensagem legível
para fila desligada. `OdApi.listTasks/retryTask/deleteTask` + modelo `OdTask`.

### 3. Verificação

| gate | resultado |
|---|---|
| Python | **4678 passed / 16 skipped / 0 falha** (197,44 s) |
| `flutter analyze` | **No issues found** |
| `flutter test` | **223 passed / 2 skipped** (inclui `tasks_api_test` 5 e `tasks_screen_test` 5) |
| JS do painel | `node --check` OK — pegou 1 aspa errada antes de publicar |

O teste de widget achou dois defeitos antes do commit: o chip de filtro ficava
clipado no tamanho padrão de teste (800×600) e o estado vazio aparecia junto
com o erro de 503 (agora o 503 mostra "sem dados" em vez de "nenhuma tarefa").

### 4. Limitações declaradas

- **APK não recompilado:** a aba só chega ao celular no próximo build/versão
  (bump SemVer + `app/build_apk.sh`, que é deploy do app e não foi autorizado).
- **Sem prova visual:** não há navegador na máquina; a verificação foi por
  teste, `node --check` e `flutter analyze`.
- Fila continua **desligada** em produção.

### 5. Deploy e prova viva

Commits `dbf6abf` (painel), `6741ef8` (app) e `21b0ff7` (docs) publicados.
Restart do `od-core`: **MainPID 2670206**, `NRestarts=0`; `/health`
**ok=true, 28 itens, nenhum falhando**; journal `-p err` **0 entradas**.
`GET /admin` = **200** com a seção `Tarefas (Task Queue)`, o caminho
`/admin/tasks/events` e as funções `tqLoad`/`tqSse` no HTML;
`GET /admin/tasks` = **503** (fila desligada, esperado). Telegram do dono:
`ok=true`, msg 3998.

---

## §12 — Release v1.45.0+2081: APK com a aba Tarefas (14/11 ~15:20–16:10)

**Pedido do dono:** "Publique o APK com a aba Tarefas, fazendo o bump SemVer e
o checklist de release."

**Autor:** Freebuff (Buffy).

### 1. Bump (MINOR — feature nova compatível)

Seguindo `docs/VERSIONAMENTO.md` §5, **1.44.0 → 1.45.0**, versionCode
**2080 → 2081**, nas 7 fontes:

| fonte | valor |
|---|---|
| `.env` (gitignored) | `OD_VERSION=1.45.0` |
| `core/capabilities.py` | fallback congelado `1.45.0` |
| `app/pubspec.yaml` | `version: 1.45.0+2081` |
| `integrations/api/server.py` | `_APP_VERSION_CODE = 2081` |
| `site/index.html` | badge, card e `versionCode 2081` |
| `site/historico.html` | linha da 1.45.0 (76 releases; era final 10) |
| `docs/CHANGELOG.md` + `docs/README_VERSAO.md` | `## [1.45.0]` e §1.45.0 |

### 2. Build do APK

`app/build_apk.sh` canônico (completo + `--split-per-abi`), com o toolchain que
não está no PATH: `JAVA_HOME=/home/alex/jdk`,
`ANDROID_HOME=/home/alex/android-sdk`. `EXIT=0`.

| artefato | tamanho | sha256 |
|---|---|---|
| `site/OmegaDrakon.apk` | 72.143.782 B | `08992119314b3896a68b19a4ec6e67c47e08c8489ff7d1fa3bf03d7ad6008436` |
| `site/OmegaDrakon-arm64.apk` | 26.906.437 B | `bcb1d466f6cffcb0cc9fa84cfebca734109c29e64699f93a471f6590114851b8` |

`aapt dump badging`: `versionCode='2081' versionName='1.45.0'`.

### 3. Validação

- **Gate Python:** 4678 passed / 16 skipped / 0 falha (199,29 s), rodado depois
  do bump e dos documentos.
- **Defeito pego pelo gate:** a guarda do `historico.html` acusou as contagens
  desatualizadas após inserir a linha nova (75 → **76** lançamentos, era final
  9 → **10**); corrigidas kicker, meta, span da era, card do index e o
  "Ver os 76 releases". `TestAPISite` 12/12.
- **Flutter:** `analyze` 0 issues; `flutter test` **223 passed / 2 skipped**.
- **`test_version_policy`:** 9/9 (7 fontes coerentes).

### 4. Deploy e prova viva

Commit `a1f362a` publicado; `od-core` reiniciado: **MainPID 2699533**,
`NRestarts=0`, journal `-p err` **0 entradas**. Provas ao vivo:

- `/app/version` → **1.45.0 / 2081**, `size=72143782` e **sha256 igual** ao
  binário em `site/`;
- `/health` → **ok=true, 28 itens, nenhum falhando**;
- `/site/index.html` → `v1.45.0` ×3 e `versionCode 2081`;
- `/site/historico.html` → 1.45.0 e "Os 76 Lançamentos";
- `/admin/tasks` → **503** (fila desligada, esperado).

Telegram do dono: `ok=true`, msg 3999.

## §13 — Fila LIGADA em produção (1 worker) com custo medido + achado do RAG (14/11 ~16:20–18:00)

**Pedido do dono:** "Ligue a fila em produção com 1 worker e meça o custo real
de CPU/RAM".

### 1. Ligação

- `.env` (gitignored, backup em `/tmp/od_env_backup_<ts>`):
  `OD_TASK_QUEUE_ENABLED=1` e `OD_TASK_QUEUE_WORKERS=1`; defaults mantidos
  (3 retries, backoff 5 s, 200 concluídas).
- `od-core` é unidade **de usuário** (`systemctl --user`), não de sistema.
- Boot: `TaskQueue iniciado | workers=1 | pending=0`; `GET /admin/tasks` 200.

### 2. Custo medido (`/proc/<pid>`, 1 s de amostragem)

| cenário | CPU | RSS mediano | RSS máx | delta |
|---|---|---|---|---|
| fila desligada | 3,65% | 226,0 MB | 233,1 MB | — |
| ligada ociosa | 3,20% | 231,1 MB | 245,3 MB | +5,1 MB |
| rajada 50 tasks reais | **14,03%** | — | — | +0,1 MB |
| pós-rajada ociosa | 3,25% | 200,7 MB | 207,7 MB | — |

- Rajada: 50 tasks em 3,42 s (68 ms/task com POST + polling), execução
  p50 0,7 ms / máx 3,5 ms; máquina 7845 MB (4190 livres), 4 vCPUs.
- Retry em produção: `max_retries=2`/backoff 2 s → tentativa 1 em 1,4 s,
  **dead letter em 6,01 s**; `POST .../retry` 200; `DELETE` de task ativa 409.
- Limpeza: 52 registros de teste por `DELETE` → 0 restantes.

### 3. Defeito real achado na medição

Boot logava a fila iniciada mas `GET /admin/tasks` devolvia **503 para
sempre**: `build_api_server` recebia `task_queue` na assinatura e **não o
repassava ao `APIConfig`**. Corrigido em `runtime/launcher.py` + guarda
`test_build_api_server_repassa_a_fila` (commit `459decb`).

### 4. Achado do gate e correção medida (RAG)

Com a seção nova do CHANGELOG, `TestCalibracaoCorpusReal` falhou: o alvo do
"projeto nômade" (`[1.26.0]` do CHANGELOG) estava **na 24ª posição** e os dois
chunks novos o moveram para 26ª — fora do pool de 24. Medição mostrou que o
piso estava certo e o **pool** no limite: grid com `TOP_K=32` → 600 células
válidas (ms 0.394..0.403 × mo 0.001..0.060), 8/8 relevantes, 8/8
irrelevantes e 6/6 parafrases, piso (0.399/0.036) dentro da região
(margem 0.4038 vs 0.3936). `TOP_K_CANDIDATOS` 24 → 32, piso intocado.

### 5. Validação e prova viva

- Gate completo: **4679 passed / 16 skipped / 0 falha** (198,27 s);
  `tests/test_rag.py` 93/93.
- `od-core` reiniciado: MainPID **2752075**, `NRestarts=0`, journal `-p err`
  0 entradas; `/health` **ok=true, 28 itens**; `/admin/tasks` **200** com
  `count=0`.

### 6. Limitações declaradas

- Custo medido é de 1 worker ocioso + rajada de `filesystem_exists`; não cobre
  action de LLM longa (aí o custo é do modelo, não da fila).
- O pool 32 tem folga medida até a 26ª posição; novas seções diárias de
  CHANGELOG/transcrição continuam empurrando alvos — o gate é o alarme.

## §14 — Custo da fila com action de LLM longa (14/11 ~18:10–18:40)

**Pedido do dono:** "Meça o custo da fila com uma action de LLM longa para
completar o quadro".

### 1. O que existe hoje

O catálogo de actions (`tools/actions/actions.py`) tem **125 actions e nenhuma
de LLM** (são sistema/IoT/arquivos/cloud). A medição usou o caminho real de uma
action desse tipo: fila em **sandbox** (1 worker, `queue_dir` em `/tmp`) cuja
action chama o `OpenAICompatProvider._post_chat` — **a mesma chamada HTTP** que
o orchestrator faz — no llama-server local
(`qwen2.5-coder-3b-instruct-q4_k_m`, 4 threads, porta 8081).

### 2. Medição (`/proc` a cada 0,5 s nos três processos)

| action | duração | tokens (prompt→resposta) | llama-server | RSS máx |
|---|---|---|---|---|
| longa, `max_tokens=600` | **105,36 s** | 111 → 600 (2.119 chars) | 333,2 s = **312,0% de 1 core** | 1.915 MB |
| curta, `max_tokens=150` | **19,19 s** | 111 → 150 (600 chars) | 71,1 s = 337,8% de 1 core | 1.943 MB |
| processo **da fila** | mesma janela | — | 0,25 s = **0,23% de 1 core** | 27 MB |

- ~0,56 s de CPU por token gerado (~5,7 tok/s): **o custo é do modelo, não
  da fila**.
- RSS do modelo ~1,9 GB (já residente, não cresce por task).

### 3. O custo real de 1 worker: serialização

Task curta (`filesystem_exists`) enfileirada **0,4 s depois** de uma action de
LLM de **14,89 s**: **esperou 14,49 s** na fila e executou em ~0 ms. Com 1
worker, toda action longa segura as demais.

### 4. Ruído identificado (honestidade da medição)

O repouso do `od-core` subiu de 3,2% para 8,5% num intervalo — investigado no
journal: **TTS da rádio** gerando locuções a cada ~3 min (rajadas de 10–29%
por segundo). Não é a fila; o RSS seguiu estável em ~262 MB.

### 5. Conclusão

- Custo de infraestrutura da fila: desprezível (0,23% de core por 105 s de
  task; +5,1 MB de RSS em repouso).
- Custo de uma action de LLM: integralmente no llama-server (~3,1 dos 4
  threads durante a geração).
- Limitação/risco: **1 worker + action longa = fila parada**; para LLM o
  desenho pede prioridade dedicada ou 2 workers.

## §15 — Métricas da fila no /health (14/11 ~19:05–19:40)

**Pedido do dono:** "Exponha queue_depth, workers, dead_letter e a retenção da
fila no /health" (escolhido da lista de próximos do TODO).

### 1. Por que

A fila estava LIGADA em produção (14/11) e só se enxergava por `/admin/tasks`;
o agregado de saúde não dizia nada sobre ela — nem se os workers estavam de pé.

### 2. O que entrou

- `core/task_queue.py`: `snapshot()` com `enabled`, `running`, `workers`,
  `queue_depth`, `running_tasks`, `dead_letter` (arquivos em disco),
  `completed_on_disk`, `keep_completed`, `pruned` e o dicionário `metrics`.
  Novo contador `pruned` em `_metrics`, incrementado pela própria poda.
  `_contar()` best-effort: pasta ilegível → 0, sem exceção.
- `runtime/launcher.py`: `register_task_queue_health(monitor, fila)` registra
  o check `task_queue` **não-crítico** (workers parados ou dead letter →
  `degraded`; nunca derruba o core) e é chamado no `_run_api_forever`, logo
  depois do `task_queue.start()` — a fila nasce depois do `build_health()`.
- `integrations/api/server.py`: `GET /health` passa a trazer o bloco
  `task_queue` (nos dois caminhos: com monitor agregado e no fallback),
  montado **fora do cache de 8 s** — leitura de memória + contagem de
  arquivos, o dono vê a fila andar na hora.

### 3. Testes (5 novos, `tests/test_task_queue.py`)

- `snapshot()` com fila, workers, dead letter em disco vs acumulado, retenção;
- pasta ilegível não explode;
- poda alimenta `completed_on_disk` / `keep_completed` / `pruned` (e `metrics`);
- check no HealthMonitor: parado → degraded, rodando → up, dead letter → ok
  degradado (`critical=False`);
- `/health` da API traz o bloco com os números da instância.

### 4. Sem bump

Entrega **só de servidor** (contrato do app/APK intacto): versão segue
**1.45.0+2081**, com subseção datada no CHANGELOG — a mesma convenção do lote
de 14/11.

## §16 — As mesmas métricas no painel /admin (14/11 ~20:00–20:30)

**Pedido do dono:** "Mostre as métricas da fila também no painel /admin".

### 1. O que entrou

- `GET /admin/tasks` e o `snapshot` do SSE `/admin/tasks/events` passaram a
  devolver `queue` = `TaskQueue.snapshot()` — o MESMO retrato do `/health`,
  sem uma requisição extra para o painel.
- Seção "Tarefas (Task Queue)" ganhou a linha `#tq-resumo`: **na fila**,
  **executando**, **workers**, **dead letter**, **concluídas/teto**,
  **podadas** e o total acumulado (recebidas · ok · retry · falhas finais).
- Fila e execução são contadas das PRÓPRIAS tasks da tabela (o SSE atualiza
  cada linha em tempo real); dead letter, histórico e poda vêm do disco pelo
  snapshot. Workers parados → pill vermelha "workers parados".
- Fila desligada (503): "métricas indisponíveis", sem quebrar a seção; o
  aviso de fila desligada continua no `#tq-msg`.
- Substituído o `tqMetrics` órfão (o render antigo esperava `pending`/`workers`
  que a API nunca mandava — mostrava sempre 0).

### 2. Testes

- `test_lista_traz_o_snapshot_da_fila` (novo) e o teste do painel agora
  verifica `#tq-resumo` e `tqResumoFila`. `tests/test_task_queue.py`: 27 passed.

### 3. Sem bump

Só servidor/painel; contrato do app e APK intactos → 1.45.0+2081.

## §17 — Retomada ("leia iniciar") + publicação do lote da §16 (14/11 ~15:33–15:45)

**Pedido do dono:** "leia iniciar" — recarregar o checkpoint antes de retomar.

### 1. Lido

`iniciar/README.md`, `iniciar/RULES.md` (23 regras), `iniciar/session.json`
(entradas de 12–14/11), `iniciar/ATRIBUICOES.md`, transcrição
`2026-11-14` inteira (§1–§16), `txt.txt` (vazio), `git status`/`log` e o
serviço.

### 2. Estado encontrado

- **HEAD == origin/master == `b98de68`** ("feat(task-queue): métricas da
  fila no /health", 14:55) — a árvore estava **suja com o lote da §16**:
  6 arquivos modificados, **nunca commitados** (`integrations/api/server.py`,
  `tests/test_task_queue.py`, `docs/CHANGELOG.md` + os 3 de `iniciar/`).
  A sessão anterior concluiu e registrou a entrega (painel com `#tq-resumo`,
  suíte da fila 27) mas **parou antes de publicar** — exatamente o cenário
  da regra 23 (crédito acabando no meio).
- O código do lote **já estava vivo**: `od-core` reiniciado às **15:07:44**
  (MainPID 2822359, `NRestarts=0`) depois da última edição do `server.py`
  (15:03:51) — `/admin` servia `#tq-resumo`/`tqResumoFila` e
  `GET /admin/tasks` + SSE devolviam `queue`.
- **Serviço:** `/health` **ok=true, 29 checks**, bloco `task_queue` up
  (`workers=1 fila=0 executando=0 dead_letter=0 concluidas=0/200 podadas=0`);
  journal `-p err` sem entradas; fila **LIGADA** em produção
  (`OD_TASK_QUEUE_ENABLED=1`, `WORKERS=1`).
- **Nota de relógio:** os horários "~19:05"/"~20:00" das entradas anteriores
  ficam à frente do relógio real; os commits reais são das **14:11–15:07**
  (`git log`). Este registro usa hora real.

### 3. Validado antes de publicar

- **GATE COMPLETO: 4684 passed / 16 skipped / 0 falha (200,26 s), exit 0** —
  rodado com os arquivos do lote na árvore.
- Prova viva: `/admin` 200 com `#tq-resumo` + `tqResumoFila`;
  `/admin/tasks` 200 com `queue` (`queue_depth`, `workers`, `dead_letter`,
  `keep_completed`, `pruned`, `metrics`); SSE `snapshot` com `queue`.

### 4. Publicado

- `feat(painel): métricas da fila no /admin` (server.py + test + CHANGELOG)
  e `docs(iniciar): retomada e fechamento do lote da §16` (iniciar/ + TODO)
  em `origin/master`.

### 5. Higiene do TODO (mesmo passo)

Dois checkboxes **entregues mas abertos** marcados com a evidência:
(a) ligar a fila com 1 worker e medir o custo (§13 — entregue, agora
contínuo em produção); (b) métricas de retenção no `/health` (§15 —
`completed_on_disk/keep` + `pruned`). Contagem: **47 abertos / 46 feitos**.

### 6. Em aberto (nada disto mudou neste turno)

Fila ligada desde 14/11 (avaliação de custo por semana segue no TODO);
**I1 Semantic Cache desligado** esperando decisão do dono; OpenAI sem
crédito; APK 1.45.0+2081 ainda não publicado (deploy do app = ordem dele);
criar task pelo painel; SSE na aba Tarefas do app; ~47 checkboxes no TODO.

### 7. Sem bump / sem restart

Só servidor/painel/docs: **1.45.0+2081**. Sem restart — o processo em ar
(15:07) já roda exatamente o código publicado.

## §18 — Por que "melhorar o sistema deixa ele menos inteligente"? (14/11 ~15:50)

**Pergunta do dono:** "porque parece que quanto mais eu tento melhorar o
sistema, menos inteligente ele fica?"

### 1. Medição (journal do od-core, sem achismo)

- **Cota do Gemini estourou às 15:42** (HTTP 429, `retryDelay=21600s` —
  primeiro 429 da janela: 12/11 e 13/11 = 0). Circuito `llm:gemini` aberto
  por 6 h; a mensagem das 15:42 respondeu pelo **groq** em **13,6 s**
  (`route=fallback`). A cadeia troca de cérebro sozinho, sem aviso no chat.
- **Detector de recusa atirando em quase tudo:** "Recusa indevida —
  etiqueta de log no lugar da resposta ([info])": **11 em 14/11**, 5 em
  13/11, 4 em 12/11, 6 em 11/11 (em Set/Out era 1–2 esporádicos). Das
  15:28 às 15:32 **7 mensagens seguidas do dono** passaram por refaz —
  2 chamadas de LLM por pergunta, 4,1–7,7 s cada. O guardião v1.15.0
  (caça etiqueta em qualquer posição) está atirando em resposta legítima.
- **Query Router não persiste:** 15:42 load falhou (`Ran out of input` =
  pickle vazio), treinou com **só 26 exemplos** e o save falhou
  (`cannot pickle '_thread.lock'`) → a cada boot recomeça do zero.
- **Volume de hoje:** 7 fastpath (ações), 11 fallback (conversa) — 0 no
  caminho `route=llm` limpo: **nenhuma resposta veio direto do provider
  principal sem retrabalho**.
- **O que entrou em 13–14/11 foi operação, não inteligência:** fila,
  retry/dead letter, métricas, painel, aba do app, pg_dump, escopo, pool
  do RAG — nenhum deles melhora resposta; todos acrescentam lugar onde a
  resposta pode desviar em silêncio.

### 2. Leitura

Confiabilidade ≠ inteligência. A percepção piorou porque (a) o cérebro
principal foi cortado por cota e caiu para reserva, (b) quase toda
resposta custa um refaz, (c) o roteador não acumula nada e (d) agora dá
para VER a degradação (health/fila/métricas) — antes ela existia sem
instrumentação.

### 3. Próximo passo proposto (ordem)

1. Medir/furar o falso positivo do detector de etiqueta de log;
2. Reserva/transparência da cota do Gemini (mostrar qual modelo respondeu);
3. Consertar ou desligar o Query Router (save/load);
4. Rodar `evals --modo e2e --comparar` antes/depois de cada mudança —
   nota objetiva em vez de sensação. **Escolha do dono.**

## §19 — Verificação: o que o OD respondeu sobre "tipos de usuário" (14/11 ~16:00)

**Pedido do dono:** "me responda: quais os tipos de usuários de OD. agora
verifique o que OD me respondeu…" + hipótese dele: seria "uma resposta
conjunta entre Nicky (segurança) e Athenae (guarda as informações)".

### 1. A verdade (código, `core/security/permissions.py` — Permission Engine)

Cinco papéis, tudo o mais é negado por política (`unknown_role_policy=deny`):

| papel | o que é |
|---|---|
| `admin` | `*` — dono, confirmado pela `OD_API_KEY` |
| `user` | conta comum: conversa + leitura; **sem** escrita, segredo, `filesystem_read`, `database_*`, `network_hosts`, `ip_address` |
| `familia` | herda o `user` **por código** + a única escrita do lar: `ha_device_control` |
| `agent` | leitura interna (`system.*`, `filesystem.*` leitura, `memory.*`, `knowledge.*`, `config.read`) |
| `router` | só `router.*` (interno) |

O painel de contas só alterna `user`/`familia` (`PAPEIS_CONTA_VALIDOS`) e o
banco tem **2 contas, ambas `user`**. Perfis (`guardian`, `vox`, `Athenae`,
`Regulus`, `Luma`, `Nyx`) são **personas/vozes** (`agents/profiles.py`), não
papéis de permissão.

### 2. O que o OD respondeu (msg 1320, `llm_used=groq`, 15:42:08)

1. Administrador (admin) — **existe** ✔
2. Operador (operator) — **não existe** ✘
3. Desenvolvedor (developer) — **não existe** ✘
4. Auditor (auditor) — **não existe** ✘
5. Conta de serviço (service account) — **não existe** ✘
6. Convidado (guest) — **não existe** ✘
7. "Estado verificado." — **falso**: nada foi verificado.

**Acerto: 1 de 6.** Resposta genérica de RBAC de internet, não do OD.

### 3. A trilha real (journal, mesma mensagem)

`Enciclopédia: título fora do assunto recusado` (assunto=tipos de usuários
de OD, sem artigo) → `Nota de fonte (4.6b): pergunta de fato sem artigo` →
**Gemini HTTP 429** (cota, circuito aberto 6 h) → `Recusa indevida — etiqueta
de log ([info])` refaz → **`route=fallback llm=groq`, 13,6 s**, resposta
fria sem fonte e sem contexto do OD.

### 4. Sobre a hipótese do dono (Nicky + Athenae)

O desenho existe e está certo: a **Athenae/Enciclopédia foi consultada** e
respondeu "não tenho artigo"; o **Nicky** entrou só como guardião de formato
(detecção da etiqueta de log). Mas **ninguém respondeu junto** — sem fonte
interna, o LLM frio improvisou. O elo que falta: pergunta sobre o **próprio
OD** deveria cair em fastpath de autoconhecimento lendo o código (como
`system_info` faz com o disco). Checkbox novo no TODO §4.

---

## §20 — Resolvido: o lote do "menos inteligente" (14/11 ~17:10)

**Pedido do dono:** "resolva o problema, faça o que for necessário"
(continuação da §18/§19).

### 1. Query Router persiste — causa raiz reproduzida em sandbox

`pickle.dumps(TfidfVectorizer(tokenizer=extrator._tokenize))` →
`TypeError: cannot pickle '_thread.lock'`: o tokenizador era um **método
vinculado**, e o pickle de método vinculado leva a instância inteira do
extrator — que tem `threading.Lock()`. O `open("wb")` já tinha truncado o
arquivo antes do dump falhar → boot seguinte `Ran out of input`. Correção:
`tokenizar_pt()` + `STOPWORDS_PT` de **módulo** (picklada por referência) e
`_dump_atomic()` (tmp + `os.replace` — dump falho só deixa `.tmp` pela
metade). O teste de persistência antigo era **cego**: passava mesmo com o
save falhando (o bootstrap re-treinava sozinho no boot seguinte); o novo
exige arquivos > 0 e boot que carrega **sem re-treinar**.

### 2. Detector de recusa medido e contido (11 refazs → contrato novo)

Medição: 11 refazs em 14/11 (7 seguidas às 15:28–15:32), 2 chamadas de LLM
e 4–8 s por pergunta — a guard v1.15.0 caçava a etiqueta em qualquer
posição. Contrato novo (teste do contrato antigo reescrito, caso real da
v1.15.0 preservado):

- etiqueta **NO INÍCIO** (log no lugar da resposta) → refaz;
- etiqueta no meio **+ frase de recusa** → refaz (as listas de frases já
  existiam);
- etiqueta no meio, **sem recusa** → não refaz: `limpa_etiquetas_resposta()`
  remove as etiquetas deterministicamente (grafo, stream, não-stream, retry,
  REST — 7 pontos), sem 2ª chamada de LLM;
- em **RECUSA** a resposta fica **crua de propósito** — é ela que
  `_cacheable` baniria; limpada, a falha viraria "resposta normal" e entraria
  no cache (caiu no gate: `test_falha_nao_e_cacheada`);
- prompt (`personality.py`): a linha do protocolo agora proíbe escrever as
  etiquetas na resposta ao usuário — a raiz do vazamento.

### 3. Papéis do OD saem do código — fastpath `role_list`

Action nova (catálogo 125 → **126**) lendo `DEFAULT_ROLE_PERMISSIONS`,
`ROLE_HIERARQUIA`, `UNKNOWN_ROLE_POLICY` e `PAPEIS_CONTA_VALIDOS`; detecção
exige menção a **od/omega drakon/drakon** (sem ela, "tipos de usuário do
linux" segue para o LLM de propósito — provado como negativo); permissão
`role_list` para `user`/`familia` (mesma natureza do `action_list`).
Contagens 125 → 126 atualizadas em 5 arquivos de teste; 16 testes novos.

### 4. Validação e prova viva

- **Gate completo: 4700 passed / 16 skipped / 0 falha** (195 s).
- **RAG (achado do gate):** o título da §18 colidiu com a irrelevante
  "quanto é 15% de 380 reais" (comb 0.4718 vs piso 0.399; overlap 0.3195,
  4× o teto histórico 0.071 — **nenhum grid recalibrava**). Correção pela
  via do precedente 20/10: reescrito **só o título nosso** (citação verbatim
  do dono intacta) → comb **0.3827**; piso intocado.
- **Provas pós-restart (`od-core` 17:03, MainPID 2945652):**
  `/health` `ok=true`, **29 checks**, 3 breakers fechados;
  "quais os tipos de usuários de OD" → `route=action_intent`,
  `llm=fastpath:role_list`, **28,9 ms** (antes: 13,6 s no groq, 1 de 6
  acertos); mensagem LLM normal → `route=llm llm=gemini`, resposta sem
  etiqueta e **0 "Recusa indevida"** no journal; `Query Router model loaded |
  model=data/query_router/model.pkl` **sem bootstrap e sem erro de save**.
