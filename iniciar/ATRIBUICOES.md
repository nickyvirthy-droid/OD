# ATRIBUIÇÕES — quem fez o quê no OmegaDrakon

> **Regra 23 (`iniciar/RULES.md`).** O dono constrói o OD com várias IAs, quase
> sempre em ferramentas gratuitas cujos créditos acabam antes do fim do
> serviço. Este é o **livro-caixa compartilhado**: toda entrega registra
> (a) autor, (b) arquivos criados/modificados e (c) intenção + estado.
> Ordem: mais recente no topo. Nada de adivinhação: origem desconhecida é
> registrada como desconhecida.

---

## 14/11/2026 — Conserto do "menos inteligente": recusa, Query Router e papéis do OD

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11
~16:10, a pedido do dono ("resolva o problema, faça o que for necessário").

### Criados

- Nenhum arquivo novo.

### Modificados

- `core/query_router.py` — `tokenizar_pt()`/`STOPWORDS_PT` de módulo (o
  tokenizer era método vinculado e derrubava o pickle) + `_dump_atomic`
  (tmp + `os.replace`).
- `core/orchestrator.py` — `_refusal_reason` só no início +
  `limpa_etiquetas_resposta()` em 7 pontos (em recusa, crua para o cache
  banir).
- `agents/nicky_virthy/personality.py` — linha do protocolo proíbe a
  etiqueta na resposta ao usuário.
- `tools/actions/actions.py` — action `role_list` (125 → 126);
  `core/intents.py` — detecção (com menção ao OD) e formatter;
  `core/security/permissions.py` — `role_list` para `user`/`familia`.
- Testes: `test_query_router.py` (persistência real — o antigo era cego),
  `test_resposta_transparente.py` (contrato novo + `limpa_etiquetas`),
  `test_intents.py` (`TestPapeisOD`), `test_security.py`,
  `test_actions_catalog.py` (handler) e contagens 125 → 126 em
  `test_actions_catalog/test_capabilities/test_mcp_od/test_orchestrator/
  test_orchestrator_action_registry`.
- Registro: `iniciar/session.json`, transcrição (§20), `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md` (3 checkboxes entregues).

### Intenção e estado

- **Intenção:** fechar os 3 diagnósticos da §18/§19 que faziam o OD parecer
  "menos inteligente": resposta errada sobre os próprios papéis (1 de 6),
  11 refazs/dia pelo detector de etiqueta e Query Router sem persistência.
- **Estado:** **gate completo 4700 passed / 16 skipped / 0 falha** (195 s);
  3 commits publicados (`868a3ad`, `809b7fc`, `3c134fb`); `od-core`
  reiniciado 17:03 (MainPID 2945652) com prova viva — `/health` ok=true
  (29 checks), "quais os tipos de usuários de OD" → `fastpath:role_list` em
  **28,9 ms**, mensagem LLM sem etiqueta e **0 refazs**, `Query Router model
  loaded` sem bootstrap.
- **Achado do gate:** o título da §18 colidiu no RAG com a irrelevante
  "quanto é 15% de 380 reais" (nenhum grid recalibrava) — reescrito só o
  título nosso (citação do dono intacta), piso intocado (precedente 20/10).
- **Sem bump:** 1.45.0+2081 — correção de servidor, contrato do app intacto.

---

## 14/11/2026 — Retomada: publicação do lote da §16 e higiene do TODO

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11 ~15:33,
a pedido do dono ("leia iniciar").

### Criados

- Nenhum arquivo novo.

### Modificados

- `docs/ANALISE_SISTEMA_TODO.md` — 2 checkboxes **entregues mas abertos**
  marcados com evidência: fila ligada com 1 worker + custo medido (§13) e
  métricas de retenção no `/health` (§15).
- `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§17),
  `iniciar/ATRIBUICOES.md` — registro desta retomada.
- **Publicou o lote órfão da §16** (autor: Freebuff/Buffy, feito e registrado
  mas nunca commitado): `integrations/api/server.py`,
  `tests/test_task_queue.py`, `docs/CHANGELOG.md`.

### Intenção e estado

- **Intenção:** a sessão anterior terminou antes de publicar a entrega da §16
  (métricas da fila no painel `/admin`) — risco de perda (regra 23). Fechar o
  ciclo: **validar → commitar → publicar** (regras 7.1/7.2).
- **Estado:** **gate completo 4684 passed / 16 skipped / 0 falha** com o lote
  na árvore; 2 commits em `origin/master`; prova viva (`/admin` com
  `#tq-resumo`, `/admin/tasks` e SSE com `queue`).
- **Sem bump / sem restart:** 1.45.0+2081; o `od-core` (15:07:44) já roda
  exatamente o código publicado.

---

## 14/11/2026 — Métricas da fila no painel /admin

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Modificados

- `integrations/api/server.py` — `queue` (snapshot) no `GET /admin/tasks` e
  no `snapshot` do SSE; linha `#tq-resumo` + `tqResumoFila()` na seção
  "Tarefas (Task Queue)".
- `tests/test_task_queue.py` — `test_lista_traz_o_snapshot_da_fila` + painel.
- `docs/CHANGELOG.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§16).

### Intenção e estado

- **Intenção:** os números do `/health` (14/11) também no painel, onde o dono
  já opera a fila.
- **Estado:** resumo no topo da seção (fila, executando, workers, dead letter,
  concluídas/teto, podadas, totais). Fila/execução contadas das tasks da
  tabela (SSE); disco vem do snapshot. Painel testado (27 testes na suíte).
- **Sem bump:** 1.45.0+2081.

---

## 14/11/2026 — Métricas da fila no /health

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Modificados

- `core/task_queue.py` — `snapshot()`, contador `pruned`, `_contar()`.
- `runtime/launcher.py` — `register_task_queue_health()` + chamada no
  `_run_api_forever`.
- `integrations/api/server.py` — bloco `task_queue` no `GET /health`.
- `tests/test_task_queue.py` — 5 testes novos.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§15).

### Intenção e estado

- **Intenção:** a fila ligada em produção desde hoje só se enxergava por
  `/admin/tasks`; expor profundidade, workers, dead letter e retenção no
  agregado de saúde.
- **Estado:** bloco `task_queue` no `/health` (fora do cache de 8 s) +
  check não-crítico no HealthMonitor (workers parados/dead letter → degraded).
  `dead_letter` é o que está em disco; o acumulado segue em `metrics`.
- **Sem bump** (só servidor, contrato do app intacto): 1.45.0+2081.

---

## 14/11/2026 — Custo da fila com action de LLM longa

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo versionado (harness de medição em `/tmp`, descartado).

### Modificados

- `docs/CHANGELOG.md` (subseção de custo com LLM na entrada da fila),
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§14).

### Intenção e estado

- **Intenção:** completar o quadro de custo com o cenário mais pesado — uma
  action que chama o LLM local pela fila.
- **Método:** o catálogo (125 actions) não tem action de LLM; medido com fila
  em sandbox (1 worker) cuja action faz a mesma chamada HTTP do orchestrator
  (`OpenAICompatProvider._post_chat`) no llama-server local
  (qwen2.5-coder-3b-q4, 4 threads).
- **Resultado:** task de 600 tokens → **105,36 s**, **312% de 1 core no
  llama-server** (333,2 s de CPU), RSS ~1,9 GB; o processo **da fila** gastou
  **0,23% de 1 core** na mesma janela. Custo é do modelo, não da fila.
- **Custo de 1 worker:** task curta atrás de uma LLM de 14,89 s esperou
  **14,49 s**; action longa serializa a fila (avaliar 2 workers/prioridade).
- **Ruído declarado:** repouso do `od-core` de 3,2% → 8,5% no intervalo era o
  TTS da rádio (rajadas de 10–29%/s), não a fila; RSS estável ~262 MB.

---

## 14/11/2026 — Task Queue LIGADA em produção (1 worker), custo medido e pool do RAG

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo novo versionado (medição em `/tmp`, descartada).

### Modificados

- `runtime/launcher.py` — `build_api_server` repassa `task_queue` ao
  `APIConfig` (fix do 503 permanente, commit `459decb`).
- `tests/test_task_queue.py` — `test_build_api_server_repassa_a_fila`.
- `memory/rag.py` — `TOP_K_CANDIDATOS` 24 → **32** (medição do gate; piso
  0.399/0.036 intocado).
- `tests/test_rag.py` — fixture `rag_real` com `top_k=32` + nota da
  recalibração de 14/11.
- `.env` (gitignored) — `OD_TASK_QUEUE_ENABLED=1`, `OD_TASK_QUEUE_WORKERS=1`.
- `docs/CHANGELOG.md` (§Task Queue, com a medição e o achado do RAG),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox da fila fechado),
  `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§13).

### Intenção e estado

- **Intenção:** ligar a fila com 1 worker e medir o custo real de CPU/RAM,
  sem bump (servidor não mudou o APK nem o contrato do app).
- **Custo medido** (`/proc`, 1 s): ocioso ligado 3,20% CPU / 231,1 MB (mediana)
  contra 3,65% / 226,0 MB desligado (+5,1 MB); rajada de 50 tasks reais
  14,03% CPU, +0,1 MB, 68 ms/task (execução p50 0,7 ms); retry real com dead
  letter em 6,01 s. Máquina: 4190 MB livres, 4 vCPUs.
- **Achados:** (1) `GET /admin/tasks` respondia 503 com a fila ligada —
  `task_queue` não chegava ao `APIConfig`; (2) o gate do RAG caiu porque o
  chunk-alvo estava na 24ª posição do pool (medição → 32).
- **Estado entregue:** gate **4679 passed / 16 skipped / 0 falha**,
  `test_rag.py` 93/93, `od-core` (unidade de usuário) reiniciado com MainPID
  2752075, `/health` 28/28, `/admin/tasks` 200 com 0 tarefas, journal 0 erros.
- **Limitação:** o custo medido não cobre action de LLM longa (o custo ali é
  do modelo, não da fila).

---

## 14/11/2026 — Release v1.45.0+2081 (APK com a aba Tarefas)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo de código novo (bump + build + registro).

### Modificados

- `.env` → `OD_VERSION=1.45.0` (gitignored)
- `core/capabilities.py` — fallback congelado
- `app/pubspec.yaml` — `1.45.0+2081`
- `integrations/api/server.py` — `_APP_VERSION_CODE = 2081`
- `site/index.html` (badge, card, versionCode), `site/historico.html`
  (1.45.0 + contagens 76 releases/10 na era final)
- `docs/CHANGELOG.md` → seção `## [1.45.0]`; `docs/README_VERSAO.md` → §1.45.0
- `site/OmegaDrakon.apk` e `site/OmegaDrakon-arm64.apk` (gitignored) —
  recompilados por `app/build_apk.sh`

### Intenção e estado

- **Intenção:** publicar a aba Tarefas no aparelho do dono, com o bump SemVer
  e o checklist de release completo.
- **Pronto/validado:** APK com versionName **1.45.0** / versionCode **2081**
  (`aapt`), completo 72.143.782 B e arm64 26.906.437 B; `/app/version`
  anuncia o mesmo build **com o sha256 do binário publicado**; gates Python
  **4678/16/0** e Flutter **analyze 0 issues / 223 passed**; `od-core`
  reiniciado (MainPID 2699533, `/health` 28/28, 0 erros).
- **Pendência:** ligar a fila em produção (`OD_TASK_QUEUE_ENABLED=1`) segue
  sendo decisão do dono.

---

## 14/11/2026 — Task Queue no painel `/admin` e no app (histórico com status e resultado)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- `app/lib/screens/tasks_screen.dart` (aba "Tarefas")
- `app/test/tasks_api_test.dart` (5 testes)
- `app/test/tasks_screen_test.dart` (5 testes)

### Modificados

- `integrations/api/server.py` — bloco "Tarefas (Task Queue)" no
  `_ADMIN_PAGE_HTML` + JS `tqLoad/tqSse/tqAcao/tqRender` (filtro, retry, apagar,
  aviso de 503) e ligação no `carregarTudo`.
- `app/lib/services/od_api.dart` — `listTasks`, `retryTask`, `deleteTask` e o
  modelo `OdTask`.
- `app/lib/main.dart` — import, `TasksScreen` na posição 6 e a 8ª aba (Config
  foi para 7 no modo avançado).
- `tests/test_task_queue.py` — teste do painel com a seção nova.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§11).

### Intenção e estado

- **Intenção:** tornar o histórico da fila visível fora das rotas `/admin`,
  com status e resultado, e permitir retry/apagar sem curl.
- **Pronto/validado:** painel e app implementados; **Python 4678 passed / 16
  skipped**; **`flutter analyze` sem issues**; **`flutter test` 223 passed / 2
  skipped**; JS do painel passou `node --check` (pegou uma aspa errada antes da
  publicação).
- **Pela metade (deliberado):** o **APK não foi recompilado** (deploy do app
  exige bump + ordem); sem prova visual (não há navegador na máquina). Fila
  segue desligada em produção.

---

## 14/11/2026 — Task Queue: histórico de concluídas com poda automática

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo novo (subdiretório `completed/` é criado em runtime).
- Harness `/tmp/od_tq_historico.py` (fora do repo, descartado após a prova).

### Modificados

- `core/task_queue.py` — `completed_dir`, `keep_completed`
  (`OD_TASK_QUEUE_KEEP_COMPLETED`, 200), `_persist_completed`,
  `_prune_completed` (no `start()` e ao concluir), `get_task`/`list_tasks`
  passam a ler o histórico.
- `integrations/api/server.py` — `DELETE /admin/tasks/{id}` agora apaga também
  o registro de concluída (`tq.completed_dir`).
- `tests/test_task_queue.py` — 18 → 20 testes.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§10).

### Intenção e estado

- **Intenção:** fechar o buraco medido no turno anterior — a task concluída
  virava 404 e a listagem nunca mostrava `completed`.
- **Pronto/validado:** sandbox com API + registry + catálogo reais e
  `KEEP_COMPLETED=2`: 3 tasks reais → `GET` da recente 200 `completed` com
  `result=true`, `?status=completed` count=2, mais antiga podada (404). Gate
  **4677 passed / 16 skipped / 0 falha**.
- **Pela metade (deliberado):** a fila continua **desligada em produção**;
  mostrar o histórico no painel/app fica no TODO.

---

## 14/11/2026 — Task Queue provada em sandbox (task real, retry e dead letter)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- `/tmp/od_tq_prova.py` (harness da prova — **fora do repo**, descartável)

### Modificados

- `core/task_queue.py` — `registry.execute(..., request_id=)` → `session_id=`.
  O registry real não aceita `request_id`; **toda** task morria com `TypeError`.
- `integrations/api/server.py` — `DELETE /admin/tasks/{id}` passou a apagar em
  `tq.dead_letter_dir` (antes usava o caminho global e deixava o arquivo).
- `tests/test_task_queue.py` — 16 → 18 testes (task real no registry real;
  DELETE do dead letter no `queue_dir` da instância).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox novo do achado,
  item da fila atualizado), `iniciar/session.json` e
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§9). Nenhuma regra alterada.

### Intenção e estado

- **Intenção:** ligar a fila num teste controlado, provar task real, medir
  retry e dead letter — e não confiar no gate, que usava um registry falso.
- **Pronto/validado:** gate **4675 passed / 16 skipped / 0 falha**; sandbox
  com API + registry + catálogo reais (completed 1,0 s; retry 1,0 s → 2,7 s →
  dead letter 6,5 s; DELETE remove o arquivo e o `GET` volta 404).
- **Pela metade (deliberado):** a fila **continua desligada em produção**
  (`OD_TASK_QUEUE_ENABLED=0`) — ligar é decisão do dono. Task concluída some
  da API (retenção de histórico a decidir) — checkbox no TODO.

---

## 14/11/2026 — Fechamento do lote de 13/11 (Task Queue, Semantic Cache, OpenAI, web_search, escopo, pg_dump)

**Autor:** Freebuff (Buffy) — sessão de 14/11.
**Origem do lote:** **NÃO IDENTIFICADA** — o código de 13/11 estava na árvore,
fora do git e sem registro. Foi encontrado na retomada de 14/11 e fechado por
Buffy (não presuma que o autor destas linhas seja o mesmo do lote).

### Criados

- `core/task_queue.py` (lote 13/11)
- `tests/test_task_queue.py` (Buffy — 16 testes; cobre também os defeitos
  abaixo)
- `runtime/pg_dump_diario.py`, `systemd/od-pg-dump.service`,
  `systemd/od-pg-dump.timer`, `tests/test_pg_dump_diario.py` (lote 13/11)
- `docs/ARCHITECTURE_v2.md`, `docs/NV_DAG_SCHEDULER_REFERENCE.md`,
  `pyproject.toml` (lote 13/11)
- `iniciar/ATRIBUICOES.md` (Buffy)

### Modificados

- `integrations/api/server.py` (lote 13/11) — Buffy removeu a **duplicata** de
  `_task_queue_or_503`, trocou `_query_param` (inexistente → 500) por
  `parse_qs` e fez o SSE emitir status **uma vez** por mudança.
- `runtime/launcher.py` (lote 13/11) — separado em dois commits por assunto
  (fila / IA) por Buffy.
- `core/llm.py` (lote 13/11) — `OpenAIProvider`; Buffy acrescentou o newline
  final que faltava.
- `core/security/scope.py` + `tests/test_scope_audit.py` (lote 13/11).
- `tools/actions/actions.py` + `tests/test_actions_catalog.py`,
  `tests/test_intents.py`, `tests/test_capabilities.py`, `tests/test_mcp_od.py`,
  `tests/test_orchestrator.py`, `tests/test_orchestrator_action_registry.py`,
  `tests/test_api.py` — contagens 123→125 e rotas 124→130 (Buffy).
- `iniciar/RULES.md` (regra 23), `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `docs/CHANGELOG.md` (Buffy).

### Intenção e estado

- **Intenção do lote:** fechar R1 (fila com retry/dead letter), ligar I1
  (Semantic Cache), trazer OpenAI para a cadeia, criar actions de pesquisa e de
  Mapa de Força, liberar `/tmp` no escopo e automatizar o dump do Postgres.
- **Estado ao ser encontrado:** `pg_dump` já vivo (timer instalado, 3 dumps);
  o resto **sem commit, sem teste e quebrado** — 14 falhas no gate (contagens
  fixas), fila executando a mesma task 2×, JSON de retry apagado, dead letter
  fora do diretório da instância, `GET /admin/tasks` em 500.
- **Estado entregue por Buffy (14/11):** tudo corrigido, `tests/test_task_queue.py`
  novo, **gate 4656 passed / 16 skipped / 0 falha**, commits por assunto,
  publicado em `origin/master` e `od-core` reiniciado com prova viva.
- **O que continua pendente (deliberadamente):** ligar a `web_search` à intenção
  "pesquise na internet…" (`core/intents.py` intocado); `OD_OPENAI_AUTO` só
  testa a existência da chave, não o crédito; `web_search` não está na lista do
  papel `user`; fila desligada por padrão (`OD_TASK_QUEUE_ENABLED=0`).

---

## Antes de 14/11/2026

O projeto não tinha este livro-caixa. O histórico anterior está em
`iniciar/session.json` e nas transcrições `iniciar/YYYY-MM-DD_conversa_omegadrakon.md`
(que registram pedido, feito, testes e decisões, mas **não** nomeiam o autor de
cada lote).
