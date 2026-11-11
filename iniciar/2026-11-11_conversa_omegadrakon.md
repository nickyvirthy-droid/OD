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

## §5 — Endpoint REST de decisão do human_loop (11/11 ~10:50)

**Pedido do dono:** criar endpoint REST para o app responder aprovação
(sim/não) de turno pausado.

### 1. O que mudou

| Peça | Entrega |
|---|---|
| `integrations/api/server.py` | `POST /api/v1/chat/decision` (API Key obrigatória). Body: `{"thread_id": "...", "decision": "sim"|"nao"}`; aceita `decisao`, `aprovar/cancelar`, `s/n`, `true/false`. Valida que a conta autenticada só decide o próprio turno (`thread_id` começa com `<username>:`); sem conta (API key de operador) mantém o comportamento legado. Chama `retomar_turno_humano` e devolve `route`, `message`, `pending_human_input`, `pos_processado`. Erros: 400 campos, 403 turno de outro usuário, 409 grafo desligado/thread sem checkpoint, 503 orquestrador ausente. |
| Testes | `test_api.py` **+3** (validação, 409 sem grafo, cancelamento de checkpoint pausado) e contrato de rotas 123 → 124 + auth. |

### 2. Verificação

- Gate completo: **4432 passed / 17 skipped / 0 falha** (182,50 s).
- Prova viva:
  1. `POST /message` “liga a luz da cozinha” → `human_loop_pending`,
     `thread_id=alex:prova-decision-endpoint:c4f211a5644458a7ea35`;
  2. `POST /api/v1/chat/decision` com `decision=nao` → **200**,
     `route=human_loop_cancelado`, “🚫 Ação cancelada — nada foi executado.”,
     `pending_human_input=null`, `pos_processado=true`.
- Serviço: MainPID **2435532**, `NRestarts=0`, `/health` **27/27**,
  `journalctl -p err` **0 entradas**.

### 3. Prós e contras

- **Prós:** app/chat web fecham o ciclo sem depender do Telegram; a decisão é
  auditável no checkpoint e o endpoint é simétrico ao `/message`.
- **Contras:** é uma ação de decisão sensível — exige API Key e checagem de
  dono do turno. Não há expiração: thread antiga sem checkpoint devolve 409 (e
  a mensagem “Thread sem checkpoint”); aprovar depois de o estado já ter sido
  consumido também dá 409.

---

**Sem bump:** app segue **1.44.0/2080**.

## §6 — Decisão de aprovação no WebSocket do app (11/11 ~11:10)

**Pedido do dono:** adicionar a decisão de aprovação ao protocolo WebSocket
do app (o Flutter fala WS, não REST).

### 1. O que mudou

| Peça | Entrega |
|---|---|
| `integrations/api/ws_server.py` | Frame `{"type": "decision", "thread_id": "...", "decision": "sim"|"nao"}`. Responde `processing` e depois `done` com `content`, `route`, `decision`, `thread_id`, `pending_human_input`, `pos_processado`. Erros: `thread_id_obrigatorio`, `decision_invalida`, `thread_de_outro_usuario`, `decisao_falhou: ...`. Protocolo no docstring. |
| `integrations/api/server.py` | `normalizar_decisao()` compartilhado: REST e WS aceitam as mesmas palavras (`sim/s/yes/aprovar/confirmo/true/1`, `nao/não/n/cancelar/recuso/false/0`). |
| `core/orchestrator.py` | `_process_stream_grafo` espelha o grafo de `process`: ação sensível força a rota `tools` e `selecionar` devolve `pending_human_input` — antes o streaming executava direto. |
| `core/orchestrator_graph.py` | `SqliteSaver.ultimo` ordena por `created_at` (não por `passo`); a poda mantém os mais recentes. |
| Testes | `test_websocket.py` **+4**, `test_orchestrator_graph_integration.py` **+1** (stream pausa), `test_orchestrator_graph.py` **+1** (último = mais recente). |

### 2. Defeitos encontrados no caminho (e por que importam)

1. **Streaming não pausava.** `_process_stream_grafo` tinha uma cópia própria
   da classificação, sem `_exige_aprovacao_humana`, e devolvia `[]` para HA e
   calendar create. Resultado da primeira prova viva: o WS “liga a luz da
   cozinha” **executou direto** — o frame `decision` nunca teria o que decidir.
   Corrigido espelhando a lógica do grafo de `process`.
2. **Checkpoint antigo ganhava do novo.** Turno repetido na mesma thread
   (mesmo texto/sessão/perfil) recomeça no passo 0, mas `ultimo()` ordenava por
   `passo DESC` e devolvia o turno anterior. A prova viva do `nao` respondeu com
   a mensagem do turno velho (`route=llm`). Agora a ordem é `created_at DESC`.

### 3. Verificação

- Gate completo: **4438 passed / 17 skipped / 0 falha** (181,14 s).
- Prova viva por WS real (`ws://127.0.0.1:8001`, API Key + `user_id`):
  1. “desliga a luz da cozinha” → `human_loop_pending` (`ha_device_control`);
  2. `{"type": "decision", "decision": "nao"}` → `done`,
     `route=human_loop_cancelado`, “🚫 Ação cancelada — nada foi executado.”,
     `pending=null`, `pos_processado=true`;
  3. novo turno → `decision: sim` → `route=ha_device_control`,
     “✅ Luz Cozinha: desligar executado (⚪ estado agora: off)”.
- Serviço: MainPID **2460735**, `NRestarts=0`, `/health` **27/27**,
  journal **0 ERROR/Traceback**.

### 4. Prós e contras

- **Prós:** o app fecha o ciclo de aprovação no transporte que já usa, sem
  REST extra; a checagem de dono do turno vale também no WS; a pausa do
  streaming alinha os dois transportes.
- **Contras:** ainda não há expiração de aprovação pendente; o frame exige o
  `thread_id` recebido em `human_loop_pending` (cliente que perdeu o frame
  precisa reenviar a mensagem).

---

**Sem bump:** app segue **1.44.0/2080**.

## §7 — Aprovação no app, no chat web e expiração (11/11 ~11:30)

Pedido do dono, em três partes: (a) o app Flutter enviar o frame `decision` ao
receber `human_loop_pending`; (b) aprovações pendentes expirarem após um tempo
configurável; (c) botões sim/não no chat web quando o turno pausar.

### 1. O que mudou

| Peça | Entrega |
|---|---|
| `app/lib/services/od_ws.dart` | `OdHumanApproval` a partir do frame; `OdChatDelta.approval` e `finalText`; `decide()` abre socket, autentica, manda `decision` e lê o turno retomado. `OdStreamingProtocolError` não cai para o REST. |
| `app/lib/screens/chat_screen.dart` | Card "Aprovação necessária" (texto do servidor + Sim/Não) no rodapé; `_decidir()` consome o stream da decisão; card volta com aviso se falhar. |
| `core/orchestrator.py` | `criado_em` no pedido; `ttl_aprovacao_humana()`/`pending_expirado()`; rota `human_loop_expirado`. Padrão 30 min, `OD_HUMAN_APPROVAL_TTL` em minutos, `off`/`0` desliga; checkpoint antigo sem `criado_em` não expira. |
| `integrations/api/server.py` | Chat web: `human_loop_pending` monta o card `.approval` com Sim/Não; decisão pelo WS (REST como reserva); selo "Aprovado"/"Cancelado". |

### 2. Decisões e por quês

1. **A pausa fecha o socket; a decisão abre outro.** O servidor retoma do
   checkpoint e valida o dono pelo prefixo do `thread_id`, então não precisa da
   conexão original — decisão virou método próprio (`decide`).
2. **Uma tentativa só ao decidir.** Se a conexão cair depois da execução,
   reenviar poderia executar a ação duas vezes (Drive/agenda). O erro orienta a
   conferir antes de decidir de novo.
3. **Frame de pausa sem `thread_id` não cai para o REST.** Reenviar a mensagem
   geraria um segundo pedido de aprovação; virou `OdStreamingProtocolError`.
4. **Expiração no servidor, não no cliente.** Vale para os três transportes
   (app, chat web, Telegram) e para qualquer cliente futuro; o card do app some
   porque o servidor recusa, não porque o relógio do celular decidiu.
5. **Pedido sem `criado_em` não expira.** Checkpoints gravados antes desta
   regra continuam válidos — não se inventa idade para dado antigo.

### 3. Verificação

- Gate completo: **4445 passed / 17 skipped / 0 falha** (180,63 s).
- App: `flutter analyze` → **No issues found!**; `flutter test` → **213
  passed / 2 skipped** (5 novos no serviço, 2 de widget).
- Chat web: script extraído e validado com `node --check` → **JS_OK**.

### 4. Prós e contras

- **Prós:** o ciclo de aprovação fecha no celular e no navegador, sem depender
  do Telegram; a expiração elimina aprovação esquecida executando horas depois;
  o chat web deixa de reenviar a mensagem pausada pelo REST.
- **Contras:** o card do app não mostra contagem regressiva (o servidor é quem
  recusa); a decisão pelo app não tem retry automático (por desenho); o chat web
  só foi verificado por sintaxe + testes de servidor — não há navegador nesta
  máquina para prova visual.

**Sem bump:** app segue **1.44.0/2080**.

## §8 — Retomada ("leia iniciar") depois da entrega §7 (11/11 ~11:58)

Pedido do dono: `leia iniciar`. Só leitura e registro — nada de código foi
alterado nesta troca.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md`, `iniciar/session.json` (entrada mais
recente: `aprovacao_app_chat_web_ttl_2026_11_11`, 11:35) e esta transcrição
(§1–§7). `txt.txt` está vazio (nada deixado pelo dono).

### 2. Estado encontrado

| Item | Estado |
|---|---|
| Árvore de trabalho | limpa (nenhum modificado, nenhum novo) |
| HEAD | `3738ba1` — igual a `origin/master` |
| od-core | `active`, MainPID **2460735**, NRestarts=0 |
| Restart do processo | 11:10:29 (§6) |
| Último commit de código | `eab2d57`, 11:45:13 |

### 3. Achado que importa

O processo no ar é **anterior** ao commit `eab2d57`. Ou seja: a expiração do
`human_loop_pending` (`OD_HUMAN_APPROVAL_TTL`, rota `human_loop_expirado`) e o
card Sim/Não do chat web estão **commitados e testados, mas não estão
rodando**. O `/health`, o WS `decision` e o endpoint REST de decisão (§5–§6) já
estão no ar, porque entraram antes do restart.

### 4. Situação da validação

- Gate completo da fatia: **4445 passed / 17 skipped / 0 falha** (180,63 s).
- App: `flutter analyze` limpo; `flutter test` 213 passed / 2 skipped.
- Chat web: só `node --check` (não há navegador nesta máquina).

### 5. Leitura

A fatia está fechada em código e publicada; falta apenas o deploy verde para
ficar viva. Deploy é mutação de estado externo e depende de autorização do dono
(regra 7), mesmo com a validação verde.

**Fila registrada:** restart verde do od-core (põe o TTL/card no ar) → teste
real do rádio no chat → Bluetooth (`AuthenticationFailed` com PIN 0000) → cache
de embedding de documento no RAG → R1 Task Queue → R5 Eval →
`docs/ARCHITECTURE_v2.md` → implantar a stack OTel (commitada, não implantada).

**Sem bump:** app segue **1.44.0/2080**.

## §9 — Deploy da aprovação (TTL + card do chat web) e prova viva (11/11 ~13:46)

Pedido do dono: reiniciar o `od-core` e fazer a prova viva da expiração do
`human_loop` e do card do chat web.

### 1. Pré-condições

`HEAD` = `origin/master` (`ce56eb0`), árvore limpa, gate da fatia verde
(4445/17/0) e `tests/test_rag.py` **reexecutado antes do restart**: 93 passed —
a transcrição nova (§8) entra no corpus do RAG e já causou falso-positivo antes.

### 2. Como a expiração foi provada de verdade

Esperar 30 min não era viável e forjar `criado_em` no checkpoint seria dado
fabricado. Então a janela de teste foi a própria máquina:

1. `systemctl --user set-environment OD_HUMAN_APPROVAL_TTL=1` + restart
   (13:37:46, MainPID **2609290**), TTL de 1 min confirmado no
   `/proc/<pid>/environ`.
2. Prova do fluxo completo (abaixo).
3. `unset-environment` + restart (13:42:25, MainPID **2614065**) — volta ao
   padrão de 1800 s.

### 3. Prova viva (janela de 1 min)

| Passo | Resultado |
|---|---|
| REST `POST /message` "liga a luz da cozinha" | `200`, `route=human_loop_pending`, `paused=true`, thread `alex:prova-ttl-rest:660f1e1715c77752844f`, `pending.acao=ha_device_control` **com `criado_em` numérico** |
| WS `:8001` autenticado → mesma mensagem | frames `processing`, 7x `progress`, **`human_loop_pending`** com `thread_id` e `criado_em` — é esse frame que faz o card aparecer no app e no chat web |
| WS `decision: nao` | `done`, `route=human_loop_cancelado`, `decision=cancelar`, `pending=null`, `pos_processado=true` |
| REST `POST /api/v1/chat/decision` "nao" no turno pausado | `route=human_loop_cancelado`, "🚫 Ação cancelada — nada foi executado." |
| Turno novo pausado + **70 s** + `decision: sim` | `route=human_loop_expirado`, "⏰ Aprovação expirada — nada foi executado. O pedido valia 1 min…", `pending=null` |

Nada foi executado em nenhum dos casos (os cancelamentos e a expiração
devolveram `pending_human_input=null` e rota própria, sem passar pela action).

### 4. Card do chat web

`GET /chat` servido com **57.248 bytes** contendo `mostrarAprovacao` (2x), o
tratamento de `frame.type === "human_loop_pending"`, o título "Aprovação
necessária", o CSS `.approval button.primary` e a rota
`/api/v1/chat/decision` como reserva quando o WS cai.

Não há navegador nesta máquina: a prova é o frame real do WS + a página
servida, **não** houve clique visual nos botões.

### 5. Estado final

| Item | Valor |
|---|---|
| od-core | `active`, MainPID **2614065**, NRestarts=0, subido 13:42:25 |
| `/health` | `ok=true`, **27/27** checks up |
| journal `-p err` desde o restart | **0** entradas |
| TTL efetivo | `OD_HUMAN_APPROVAL_TTL` ausente do processo → `ttl_aprovacao_humana()` = **1800 s** |
| Resíduos | script temporário `_prova_ttl_tmp.py` removido |

### 6. Achado cosmético

A descrição do pending de HA saiu como "ligar dispositivo do lar: **da
cozinha**" — o alvo perdeu o substantivo ("luz"). Vem de `params.get("alvo")`;
não afeta a decisão nem a execução. Anotado para ajuste futuro.

**Sem bump:** app segue **1.44.0/2080** (nenhuma mudança de app nesta entrega).
