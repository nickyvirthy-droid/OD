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

