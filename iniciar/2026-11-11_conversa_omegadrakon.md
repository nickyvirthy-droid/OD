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

## §3 — Origem do human_loop ligada (11/11 ~10:40)

**Pedido do dono:** ligar a origem do `human_loop` — action sensível cria
`pending_human_input` e pausa o turno.

### 1. O que mudou

| Peça | Entrega |
|---|---|
| `core/orchestrator.py` | `ACOES_SENSIVEIS_PADRAO` = escritas no Google (drive create/update/delete, calendar delete, gmail send/delete); override por `OD_HUMAN_APPROVAL_ACTIONS` (lista por vírgula ou `off`). `classificar` força a rota `tool` quando a intenção detectada é sensível (não depende do acerto do classificador). `selecionar` devolve `pending_human_input` (ação, params, texto, detalhes) e o motor pausa antes do `human_loop`. `_aplicar_decisao_humana` executa a action no `sim` — via `execute_action`, com o papel do dono — ou responde “cancelada” no `não`, limpando a pausa. |
| `core/orchestrator_graph.py` | `no_select` aceita dict do seletor (pausa) e `rota_por_intencao` passou a reconhecer `tool` (estratégia do Query Router) além de `tools` — antes a estratégia `tool` caía em `generate`. |
| Testes | `test_orchestrator_graph_integration.py` **+4**: pausa sem executar, `aprovar` executa, `cancelar` não executa, lista `off` mantém o fluxo; a retomada agora também cobre a execução da action. |

### 2. Verificação

- Gate completo: **4426 passed / 17 skipped / 0 falha** (179,09 s).
- `POST /message` real (“apaga o arquivo teste_prova_human_loop no drive”):
  `route=human_loop_pending`, `paused=true`,
  `thread_id=alex:prova-human-loop-11-11:f1c2002567ce42395621`,
  `pending_human_input.acao=google_drive_delete` — nada executou.
- Retomada real com “cancelar” no checkpoint de produção:
  `route=human_loop_cancelado`, mensagem “🚫 Ação cancelada — nada foi
  executado.”, `pending=None`.
- Serviço: MainPID **2404384**, `NRestarts=0`, `/health` **27/27**,
  `journalctl -p err` **0 entradas**.

### 3. Prós e contras

- **Prós:** a ação sensível deixa de depender de o classificador acertar;
  a pausa fica no checkpoint (sobrevive a restart) e a decisão é auditável.
  O caminho do Google já tinha confirmação de 2 passos no modo direto; agora
  o modo grafo usa o `human_loop` como fonte única.
- **Contras:** o pacote inteiro de params vai para o checkpoint (sem segredos
  na lista padrão); a retomada exige o grafo ligado (`OD_ORCHESTRATOR_GRAPH=1`
  está no `.env` de produção). `ha_device_control` e `google_calendar_create`
  continuam fora do `select_tools` (fluxo próprio), então **não** passam por
  este human_loop — fica para uma próxima unificação.

---

**Sem bump:** app segue **1.44.0/2080**.

## §4 — Human-loop unificado: HA e calendar create (11/11 ~10:40)

**Pedido do dono:** unificar `ha_device_control` e `google_calendar_create` no
`human_loop`.

### 1. O que mudou

| Peça | Entrega |
|---|---|
| `tools/actions/actions.py` | Contextvar `_APROVACAO_HUMANA` e `aprovacao_humana_em_curso()`; `_light_confirm_check` e `_write_confirm_check` devolvem `confirmed` dentro do contexto. A aprovação do dono no `human_loop` passa a ser a confirmação — a action não pede “sim” uma segunda vez. |
| `core/orchestrator.py` | `ha_device_control` e `google_calendar_create` entraram em `ACOES_SENSIVEIS_PADRAO`. `selecionar` só seleciona quando o pedido está completo (`entity_id` resolvido / `quando` presente); sem isso continua indo ao `generate` para pedir o dado que falta. `_aplicar_decisao_humana` executa dentro do contexto de aprovação. |
| Testes | `test_orchestrator_graph_integration.py` **+3**: calendar create pausa/aprova, HA pausa/aprova e a aprovação pula as confirmações de 2 passos (luz e escrita Google). |

### 2. Verificação

- Gate completo: **4429 passed / 17 skipped / 0 falha** (180,36 s).
- Prova viva (`POST /message` real):
  - “liga a luz da cozinha” → `human_loop_pending`,
    `pending.acao=ha_device_control`,
    `entity_id=switch.luz_cozinha_sonoff_1000ab588f` (nada foi ligado);
  - “cria um compromisso teste_prova amanhã às 15 horas” →
    `human_loop_pending`, `pending.acao=google_calendar_create` (nada criado);
  - ambos retomados com “cancelar” → “🚫 Ação cancelada — nada foi executado”.
- Serviço: MainPID **2421067**, `NRestarts=0`, `/health` **27/27**,
  `journalctl -p err` **0 entradas**.

### 3. Prós e contras

- **Prós:** um único mecanismo de aprovação para toda ação sensível reaproveita
  o checkpoint (sobrevive a restart) e evita confirmação dupla; o pedido
  incompleto continua sendo completado pelo `generate` em vez de pausar à toa.
- **Contras:** o contexto de aprovação é do processo — quem chamar a action
  diretamente (fora do grafo) continua vendo o fluxo de 2 passos. Retomada
  depende do grafo ligado e de o cliente saber responder à pausa (Telegram já
  responde; REST ainda não tem endpoint de decisão).

---

**Sem bump:** app segue **1.44.0/2080**.
