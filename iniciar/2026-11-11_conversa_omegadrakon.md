# Conversa OmegaDrakon — 2026-11-11

## §1 — Retomada ("leia iniciar") e estado encontrado (11/11 08:55)

**Pedido do dono:** *"leia iniciar"* — recarregar o checkpoint antes de retomar.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md` (20 regras), `iniciar/session.json`
(347 entradas; a mais recente é `radio_local_final_2026_11_10`, de 10/11
23:28), a transcrição de 10/11 inteira (§1–§28), o `txt.txt` (vazio), o
`git status`/`git log` e o diff de `docs/ANALISE_SISTEMA_TODO.md`.

### 2. Estado do serviço e do repositório

- `od-core` **ativo**, MainPID **1362905**, `NRestarts=0` — é o mesmo processo
  do restart do F1 fase 4 (10/11 17:43). Ou seja: **nada do que veio depois
  está no ar**.
- `HEAD` em **`bc43552`** (`feat(orquestrador): retoma turno interrompido após
  restart — F1 fase 4`).
- A árvore de trabalho **não está limpa**: 12 arquivos modificados
  (+2467/−131) e 10 novos, todos posteriores ao último commit.

### 3. O que está no disco sem commit

| Frente | Arquivos | Transcrição |
|---|---|---|
| F1 fase 5 — RetryPolicy por nó | `core/orchestrator_graph.py` | §21 |
| F1 fase 6 — streaming de progresso/tokens | `core/orchestrator.py`, ws_server | §22 |
| I1 — Semantic Cache do RAG | `memory/semantic_cache.py` (novo) | §23 |
| I2 — Hybrid Search (BM25 + denso + reranker) | `core/hybrid_search.py`, `core/embeddings.py` (novos) | §24 |
| I4 — Query Router (+ integração no orquestrador) | `core/query_router.py` (novo), `core/orchestrator.py` | §25–§26 |
| I5 — SSE para chat web | `integrations/api/server.py`, `tests/test_sse.py` | §27 |
| Rádio local (ffplay/pactl + auto-power HA) | `tools/actions/actions.py`, `core/intents.py`, `integrations/telegram/bot.py` | §28 |
| Coletor OTel (infra do F2) | `docker/otel-collector-config.yaml`, `docker/tools-compose.yaml` | **sem registro próprio** |

O TODO foi atualizado junto: `execute_parallel` com actions reais e
`pending_human_input` consumido no chat passaram a `[x]`; o `RetryPolicy`
segue `[ ]` apesar de implementado; entrou um item novo de pareamento
Bluetooth (falha de autenticação com PIN 0000).

### 4. Leitura

É o mesmo padrão de 10/11 de manhã: a sessão longa terminou sem a higiene da
regra 7.2 — o trabalho existe e tem suíte focada verde, mas não foi commitado,
não foi publicado e não foi implantado. O gate completo da árvore atual
também **não** foi rodado depois dessas fatias.

### 5. Decisão desta troca

Nada alterado no código: só leitura e registro no checkpoint. Aguardando o
dono dizer por onde retomar.

---

**Sem bump:** app segue **1.44.0/2080**.

## §2 — Higiene do lote de 10/11: gate, commits, push e deploy (11/11 ~10:05)

**Pedido do dono:** opção **1** da retomada — fechar a higiene primeiro (gate,
commits por assunto, push e restart verde com prova).

### 1. O que o gate encontrou antes de qualquer commit

A árvore tinha o lote inteiro de 10/11 (fases 5–6 do F1, I1/I2/I4/I5, rádio
local, stack OTel) sem commit. A primeira rodada deu **69 falhas**, e a revisão
mostrou que não era só contagem:

| Defeito | Correção |
|---|---|
| **Duplicata de `retomar_turno_humano`** em `core/orchestrator.py`: a segunda definição (nós vazios) sombreava a primeira | Removida; a retomada agora inclui o nó `human_loop` e roda `post_process` no resume (antes pulava a etapa 8). Teste novo em `test_orchestrator_graph_integration.py`. |
| **`scikit-learn` ausente** do `requirements.txt` e do `.venv` — o Query Router rodava só em fallback e 12 testes quebravam | Instalado e declarado como dependência opcional de import tardio. |
| **Contagens 118 → 122** ações (rádio) desatualizadas em 4 arquivos de teste e em `EXPECTED_CATEGORIES` (`iot` 5 → 9) | Atualizadas. |
| **Rotas da API**: `GET /api/v1/chat/stream` faltava nas listas de espelho e de auth | Adicionada (API Key obrigatória). |
| **`test_mcp_od` e `test_vigia_mensagens`** chamavam `principal()`/`main()`, que carregam o `.env` real no `os.environ` — `OD_ORCHESTRATOR_GRAPH=1` vazava e mudava a rota de todos os módulos seguintes | `OD_MCP_ENV` para arquivo inexistente e `_ler_env` neutralizado por fixture; eram a causa de 45–69 falhas em cascata. |
| **Falso-amigo no RAG**: a palavra "piada" num exemplo da transcrição de 10/11 passava no teste de consulta irrelevante | Exemplo reescrito ("conte uma história"), sem afrouxar o piso do RAG. |
| **Stack OTel inválida**: pipeline citava exporter `logging` comentado; Tempo exportado na porta de consulta (3200); Loki no endpoint errado; faltavam `tempo.yaml`, `loki.yaml`, `prometheus.yml` e `grafana-datasources.yaml` | Configs corrigidas/criadas e `docker compose config` validado (stack **não** iniciada). |

### 2. Evolução do gate (cada rodada na árvore corrigida)

69 falhas → 51 → 45 → 2 → **0**.

**Gate final: 4422 passed / 17 skipped / 0 falha (175,41 s).**

### 3. Commits publicados

| Commit | Conteúdo |
|---|---|
| `9a40a98` | `feat(orquestrador)`: RetryPolicy por nó, SSE `/api/v1/chat/stream` e retomada humana completa |
| `59fea94` | `feat(rag)`: cache semântico, busca híbrida e Query Router (I1/I2/I4) + `scikit-learn` |
| `853b06d` | `feat(acoes)`: rádio local com auto-power, catálogo 122 e isolamento do `.env` nos testes |
| `d4f621e` | `feat(observabilidade)`: stack OTel/Tempo/Loki/Prometheus/Grafana (não implantada) |

### 4. Deploy e prova viva

- `systemctl --user restart od-core` (autorizado pela 7.3, gate verde).
- MainPID **2379496**, `NRestarts=0`, serviço `active`.
- `/health` com API Key: **ok=true, 27/27 checks**, 0 falhas.
- `journalctl -p err` desde o restart: **0 entradas**.
- `/capabilities`: **actions=122** (rádio no processo).
- Prova do SSE ao vivo (`GET /api/v1/chat/stream`, texto "que horas são?"):
  eventos `progress` (rate_limit → datetime) + `token` + `done`
  (`route=datetime`, resposta "Agora são 10:04.").

### 5. O que continua pendente (honesto)

- A **origem** do `pending_human_input` não existe: nenhum nó cria a pausa a
  partir de uma action sensível. O caminho de retomada está correto e testado,
  mas hoje só é acionável por checkpoint semeado.
- A stack de observabilidade foi commitada e validada por `docker compose
  config`, **não** subiu (sem coletor/Grafana rodando ainda).
- Rádio local ainda não foi testada no chat real (ficou para hoje).
- Pareamento Bluetooth segue com `AuthenticationFailed` (PIN 0000).

---

**Sem bump:** app segue **1.44.0/2080**.
