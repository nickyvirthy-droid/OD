# Conversa OmegaDrakon — 2026-11-10

## §1 — Retomada ("leia iniciar") e higiene das entregas pendentes (10/11)

**Pedido do dono:** *"leia iniciar"* e, em seguida, *"1"* — a opção 1 da
retomada: fechar a higiene primeiro (gate, commit e push das entregas que
estavam só no disco).

### 1. O que foi lido antes de agir

`iniciar/README.md`, `iniciar/RULES.md` (20 regras), `iniciar/session.json`
(317 entradas, depois 319), a transcrição de 09/11 (§1–§16), o `txt.txt` e
`docs/ANALISE_SISTEMA_TODO.md`. O `txt.txt` não tinha recado novo — o último
era de 09/11 17:20 (3.3/A4/A5).

### 2. Estado encontrado

- `od-core` ativo, MainPID 4097009, `NRestarts=0`.
- `HEAD` em `d541dba` (só a limpeza de `.part`), mas a árvore tinha as
  entregas de 09–10/11 **sem commit**: extras 3.1 do Supply Depot, webhook
  3.3, templates/staging 3.5, Legado 3.7, E1 marketplace, `core/os_updater.py`
  + units, `docs/ANALISE_SISTEMA_TODO.md` e o export/import do catálogo.
- O export/import do Supply Depot estava **fora do registro**: a entrada do
  CHANGELOG existia, mas não havia linha no `session.json` nem transcrição —
  a sessão que o fez terminou sem checkpoint.

### 3. Gate e a falha encontrada

- Primeira rodada: **1 failed, 4192 passed, 17 skipped** em
  `TestCalibracaoCorpusReal::test_irrelevante_e_bloqueada`, na consulta
  irrelevante de esporte (a frase literal não é repetida aqui de propósito:
  `iniciar/*.md` entra no corpus do RAG e repeti-la reintroduz o
  falso-amigo; esta própria linha já o reintroduziu uma vez).
  O trecho veio de `docs/ANALISE_SISTEMA_TODO.md` (cosseno 0.4564, overlap 0.3036).
- **Causa apurada:** o doc novo usava a palavra inglesa de duração em três
  rótulos do bloco de KPIs ("Test suite time", "Hot-reload tool time",
  `` `time python` ``). O tokenizer do RAG casou essa palavra com a da
  consulta — mesmo padrão do falso-amigo de 20/10 ("campo" × câmera QR).
- **Correção (medida, sem afrouxar piso):** rótulos em português —
  "Duração da suíte de testes", "Duração do hot-reload de ferramentas" e
  `python -X importtime -c "import core"`. `tests/test_rag.py` 93 passed.
- Gate completo depois da correção: **4193 passed / 17 skipped / 0 falha**
  (187,74 s).

### 4. Commits publicados

| Commit | Conteúdo |
|--------|----------|
| `49c467a` | `feat(supply-depot)`: diff de catálogo, Ed25519, semver estrito, ferramentas nativas, templates e staging (3.1/3.5) |
| `3bd45ca` | `feat(downloads)`: webhook de conclusão de download (3.3) |
| `0e0cb7b` | `feat(marketplace,os-updater)`: catálogo de plugins, 14 rotas `/admin/marketplace/*`, 3 rotas `/admin/os-updater/*`, `core/os_updater.py` + `systemd/od-os-updater.{service,timer}`, UI e tema |
| `a622a90` | `docs(legado)`: `docs/LEGADO_CONSOLIDADO.md` + `site/legado.html` (3.7) |
| `1fe8ae6` | `docs`: análise geral do sistema com TODO priorizado e roadmap de 12 semanas |

### 5. Correção de registro

O CHANGELOG da entrega de export/import citava gate **4218 passed / 16 skipped**;
a re-execução em 10/11 na mesma árvore deu **4193 passed / 17 skipped / 0 falha**.
A célula de Verificação foi anotada com os dois números (o total não reproduz;
a suíte está verde) e a entrega passou a constar no `session.json`.

## §2 — F2: OpenTelemetry + log correlacionado (10/11)

**Pedido do dono (saindo):** *"implemente todas as atualizações que não
precisam da minha presença"* — autorizado instalar/atualizar ferramentas.
Escolhido o F2 do roadmap: menor risco, maior visibilidade (Semana 1-2).

### 1. O que foi feito

| Arquivo | Entrega |
|---|---|
| `core/telemetry.py` (novo) | `configurar()` idempotente, `span()`, `cronometrar()`, `contar()`, `atribuir()`, `trace_id()`/`span_id()`, `status()`, `desligar()`. Providers no estado do módulo (os globais do OTel só aceitam a primeira configuração por processo). Sem `opentelemetry-sdk` = no-op. |
| `core/logger.py` | `trace_id`/`span_id` no contexto do log NICKY quando há span ativo; fora de span nada é inventado; trace explícito preservado. |
| `integrations/api/server.py` | Span `http.request` + histograma `od.http_request.seconds` + contador `od.http_requests` em toda requisição, com `http.status_code`; despacho movido para `_despachar`. |
| `memory/rag.py` | `consult()` instrumentado (span + histograma + candidatos/trechos/descartes); corpo em `_consultar()`. |
| `runtime/launcher.py` | `telemetry.configurar()` no `main()`; check não-crítico `telemetria` no `/health`. |
| `docs/TELEMETRIA.md` + `requirements.txt` | Variáveis, pontos medidos, operação, o que falta; deps OTel opcionais (item 8). |

### 2. Verificação

- Instalado no venv: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`.
- `tests/test_telemetry.py` **15 passed** (spans/atributos com exportador em
  memória, correlação log↔trace, histograma/contador, no-op sem SDK, SDK
  quebrado contido).
- Gate completo: **4212 passed / 16 skipped / 0 falha** (189,29 s).
- Restart `od-core`: **MainPID 974935**, `NRestarts=0`, `/health` **26/26 up**
  (check `telemetria` up: `servico=omega-drakon destino=sem exportador
  amostra=0.1`), journal sem `[ERROR]`/warnings na janela.
- Sem bump: app segue **1.44.0/2080**.

### 3. Pegadinhas registradas

- `iniciar/*.md` entra no corpus do RAG: a própria transcrição que descrevia
  a falha reintroduziu o falso-amigo. O registro acima evita a frase literal.
- `set_tracer_provider`/`set_meter_provider` não podem ser reconfigurados no
  mesmo processo — daí os providers ficarem no módulo.
- Fixture que chamava `reset_loggers()` quebrava testes de outros módulos
  (referência antiga do logger) — removida do `test_telemetry.py`.

## §3 — R2: circuit breaker nos providers LLM (10/11)

**Pedido:** continuidade da autorização "implemente o que não precisa de mim"
— item R2 do TODO (Resiliência, baixo esforço e alto impacto).

### 1. O que foi feito

| Arquivo | Entrega |
|---|---|
| `core/resilience.py` (novo) | `CircuitBreaker` thread-safe (fechado → aberto → meia-aberto), relógio injetável, `permitir`/`registrar_sucesso`/`registrar_falha`/`executar`/`status`; registro global (`obter_breaker`, `status_breakers`, `resetar_breakers`); `OD_CIRCUIT_BREAKER=0` desliga. |
| `core/llm.py` | Breaker por provider (`llm:<nome>`): `generate`/`generate_stream` recusam sem tocar a rede com circuito aberto, contam sucesso/falha; `is_available()` devolve False sem sonda quando aberto. A recusa é `LLMError`, já tratado pela cadeia de fallback do Orchestrator. |
| `tests/test_resilience.py` | +16 testes (estados, limite, janela, meia-abertura, desligado, `executar`, registro e integração — a 3ª chamada não vai à rede). |

### 2. Configuração

- `OD_CIRCUIT_FAILURES` (padrão 5) — falhas consecutivas que abrem.
- `OD_CIRCUIT_RECOVERY_S` (padrão 30) — janela antes da meia-abertura.
- `OD_CIRCUIT_BREAKER=0` — desliga o disjuntor.

### 3. Verificação

- Gate completo: **4226 passed / 16 skipped / 0 falha** (188,73 s).
- Restart `od-core`: **MainPID 989123**, `NRestarts=0`, `/health` **26/26 up**
  (`ok=true`), journal **0 `[ERROR]`** na janela.
- Sem bump: app segue **1.44.0/2080**.

## §4 — Retomada do dono e F3: auditoria + primeira fatia (10/11)

**Dono voltou:** *"vamos prosseguir… do primeiro até o último, em ordem,
testando e discutindo os prós e contras, anotando tudo para auditoria"*.

### 1. Ordem acordada (a do roadmap §4, não a da matriz)

F2 (observabilidade) ✔ → **F3 (I/O e trabalho bloqueante) ← agora** →
F4 (memory layer) → F1 (orquestrador em grafo) → I1/I2/I4/I5 (RAG) →
R1/R5 (fila e eval) → itens P. R2 foi adiantado porque era barato e
independente. Cada item: medir → implementar a menor fatia útil → gate →
registrar → discutir.

### 2. Prós e contras do F3 como estava escrito

**Prós:** menos threads paradas em timeout; pooling evita handshake por
chamada; `async` ajuda quando o número de conexões cresce.

**Contras (medidos):** o diagnóstico estava velho — `downloads.py` usa
`urllib` **em worker próprio**, `notifier.py` já usa `asyncio.to_thread`,
`auto_update.py` já é `asyncio`; não há `requests` no caminho. A API é
`ThreadingHTTPServer` com `asyncio.run()` por request: não existe loop
compartilhado para bloquear. Criar um loop custa **~130 µs** — ruído. Migrar
para `aiohttp`/`aiosqlite` sem número que justifique só adicionaria
superfície de falha no caminho crítico do chat.

**Conclusão:** escopo revisado — caçar trabalho pesado no handler, com sonda
como régua. Foi o que achou o problema abaixo.

### 3. O que a sonda achou (linha de base, 8 threads)

| Endpoint | p50 | p95 | Vazão |
|---|---|---|---|
| `/app/version` | **174,15 ms** | 183,19 ms | **20,0 req/s** |
| `/health` | 7,75 ms | 47,35 ms | — |

Causa: `/app/version` relia e re-hashava o APK de **72 MB a cada chamada**
(o comentário dizia "lazy", mas o hash era inline). O app sonda esse endpoint
a cada abertura.

### 4. Correção

- `integrations/api/server.py`: `_metadados_apk()` com cache por
  `(mtime_ns, tamanho)`; `_hash_apk()` em blocos de 1 MB sob lock. Republicar
  o APK invalida sozinho — o `sha256` que o app usa para instalar nunca fica
  velho.
- `tools/monitor/io_probe.py` (novo): sonda série/concorrência + custo de
  `asyncio.run()`, com `--intervalo` para o limiter de 30 req/min.

### 5. Resultado medido (mesma sonda, 200 requests)

| Métrica | Antes | Depois | Ganho |
|---|---|---|---|
| p50 | 174,15 ms | **0,81 ms** | 215× |
| p95 | 183,19 ms | 1,01 ms | 181× |
| Vazão (8 threads) | 20,0 req/s | **182,7 req/s** | 9× |

Gate **4227 passed / 16 skipped / 0 falha** (226,63 s); RAG 93 passed depois
das edições de docs. Restart: MainPID 1061707, `NRestarts=0`. Sem bump:
app segue **1.44.0/2080**.

### 6. Próximo (F3, fatia 2)

Procurar o mesmo padrão nos outros handlers com a sonda: servir `/site/*`
(arquivos grandes por thread), `/auth/login` (custo de hash de senha) e
`/health` quando algum check pesado entra na conta. Só migrar para async se
a medição mandar.

## §5 — F3, fatia 2: /site/*, /health e /auth/login (10/11)

**Pedido do dono:** *"sondar /site/*, /auth/login e os checks do /health e
corrigir o que a medição apontar"*.

### 1. Medições (antes)

| Alvo | Série (p50) | Concorrência (200/8) |
|---|---|---|
| `/site/` | 0,95 ms | p50 6,77 ms · p95 16,55 ms · **máx 1.031,64 ms** · 186,4 req/s |
| `/site/logo.png` (436 KB) | 1,56 ms | p50 9,78 ms · p95 15,51 ms · 766,5 req/s |
| `/health` sem cache | 18,08 ms (26 checks) | — |
| `POST /auth/login` (PBKDF2) | 158,5 ms por verificação | — |

### 2. O que estava errado

Não era I/O bloqueante nem handler pesado em `/site/*`: era **configuração de
socket**. O `ThreadingHTTPServer` herda `request_queue_size = 5` do
`socketserver`; com 200 conexões simultâneas o backlog estourava e o kernel
reenviava SYN — daí o máximo de ~1 s com p95 de 16 ms (assinatura de stall de
accept, não de processamento).

### 3. Correção

`integrations/api/server.py`: `request_queue_size = 128` (+ teste de contrato
em `tests/test_api.py`).

| Métrica (`/site/`, 200 conexões/8 threads) | Antes | Depois |
|---|---|---|
| Máximo | 1.031,64 ms | **20,16 ms** |
| p95 | 16,55 ms | 12,66 ms |
| Vazão | 186,4 req/s | **994,8 req/s** |

Rajada maior (400 conexões/32 threads): máx 35,93 ms, 1.127 req/s.
Série inalterada (p50 1,01 ms) — a correção só afeta a fila de conexões.

### 4. Descartados com número (e por quê)

- **`/health`**: 18,08 ms sem cache para 26 checks, com TTL de 8 s. Aumentar
o TTL só ganharia milissegundos e custaria frescor do painel — não vale.
- **`/auth/login`**: 158,5 ms de PBKDF2-SHA256 (260k iterações) é o preço
deliberado contra força-bruta; o limiter de 30 req/min já contém abuso.
Baixar iterações seria afrouxar segurança para ganhar algo que ninguém
percebe (login é raro).
- **Migrar `/site/*` para `aiohttp`/`sendfile`**: desnecessário — a vazão já
passou de 1.000 req/s e o gargalo era o backlog.

### 5. Verificação

- Gate completo: **4228 passed / 16 skipped / 0 falha** (186,73 s).
- Restart: **MainPID 1077948**, `NRestarts=0`; `/site/` e probes conferidos
  ao vivo antes/depois.
- Sem bump: app segue **1.44.0/2080**.

## §6 — Sonda de latência periódica + check no /health (10/11)

**Pedido do dono:** *"ligue a sonda io_probe ao monitor periódico e registre
p50/p95 no /health"*.

### 1. O que foi feito

| Peça | Entrega |
|---|---|
| `tools/monitor/io_probe.py` | `--gravar` (merge atômico por alvo, com `ts`/`iso`), `--rotulo` e `--api-key-file` (lê `OD_API_KEY` do `.env`; o serviço do timer não herda o shell). |
| `runtime/launcher.py` | `check_latencia` + registro não-crítico `latencia` no `build_health`. |
| `systemd/od-io-probe.service` / `.timer` | Oneshot com dois `ExecStart`: `/site/` (20 em série + 20 concorrentes) e `/health` (5 amostras, 1,1 s de intervalo — 5 req/5 min, dentro dos 30/min). `OnBootSec=3min`, `OnUnitActiveSec=5min`. |
| `tests/test_io_monitor.py` | +13 testes. |

### 2. Regras do check (prós e contras)

- **Arquivo ausente = `up`**: instalação nova não degrada antes do primeiro
  disparo do timer. Contra: mascara um timer que nunca subiu; mitigado pelo
  fato de que a ausência de `data/io_monitor.json` também aparece no journal.
- **Idade > 900 s = `degraded`**: pega o timer parado (sinal de que a métrica
  não vale mais). 900 s = 3 ciclos de 5 min, tolera um disparo atrasado.
- **Pior p95 > 250 ms = `degraded`**: limite folgado de propósito — o
  `/health` sem cache oscila (18–46 ms) e a série de `/site/` é ~1 ms; 250 ms
  só marca regressão de verdade, não ruído.
- Não-crítico: desempenho não derruba o core, só tinge o status.

### 3. Verificação

- Gate completo: **4241 passed / 16 skipped / 0 falha** (187,32 s).
- Timer habilitado e ativo; execução manual `success/0`; JSON com os dois
  alvos (`site` p50 1,04 / p95 1,17 ms; `health` p50 7,88 / p95 32,56 ms).
- Restart: **MainPID 1096866**, `NRestarts=0`; `/health` **27/27** com
  `latencia: ok=True up "p50=7.88ms p95=32.56ms alvos=2 idade=222s"`.
- `data/` está no `.gitignore` — o JSON é estado de máquina, não entra no
  repositório; as units entram em `systemd/`.
- Sem bump: app segue **1.44.0/2080**.

## §7 — F3 encerrado no TODO (10/11)

**Pedido do dono:** *"feche o F3 no TODO com o resumo das fatias e dos
descartes medidos"*.

### 1. O que foi alterado em `docs/ANALISE_SISTEMA_TODO.md`

- **Matriz (§2):** a linha do F3 passou a “~~Substituir I/O síncrono por
  async em todo o core~~ **ENCERRADO (10/11)** com escopo revisado por
  medição”, com esforço corrigido de Alto → Baixo.
- **§3:** bloco novo **“F3 — FECHAMENTO”** com as quatro entregas (cache do
  APK, fila de listen, monitor contínuo, sonda), cada uma com commit e
  número antes → depois, mais uma tabela dos sete descartes e a medição que
  derrubou cada um.
- **§4 Semana 3-4:** checkboxes fechados com a conclusão de cada um, e
  “connection pools globais” mantido aberto como item **sem demanda medida**
  (reabre quando existir cliente HTTP de alto volume ou Redis em I1/R1).

### 2. Números do fechamento

| Entrega | Antes → Depois |
|---|---|
| Cache do APK (`/app/version`) | p50 174,15 → **0,81 ms**; 20,0 → **182,7 req/s** |
| Fila de listen 5 → 128 | máx 1.031,64 → **20,16 ms**; 186,4 → **994,8 req/s** |
| Sonda + check `latencia` | `/health` 26 → **27 checks**, p50/p95 vivos |

### 3. Descartes registrados

`requests`→`aiohttp` (não há `requests` no caminho), `sqlite3`→`aiosqlite`
(thread-por-requisição, sem ganho), loop compartilhado (~130 µs de custo por
`asyncio.run`), `subprocess`→`asyncio.subprocess` (só em contexto síncrono ou
já em `to_thread`), TTL maior no `/health` (18 ms sem cache), afrouxar o
login (PBKDF2 158,5 ms é deliberado) e `sendfile` no `/site/*` (vazão já em
~1.000 req/s).

### 4. Herança e gatilho de reabertura

Fica o padrão “medir antes de migrar” e a sonda como régua. O F3 só volta à
mesa se a API mudar de modelo (ASGI/FastAPI, P5) ou se entrar um cliente HTTP
de alto volume — hoje não há item async pendente no core.

### 5. Verificação

- Só documentação: RAG revalidado (`tests/test_rag.py` 93 passed), porque
  `docs/` entra no corpus.
- Sem bump: app segue **1.44.0/2080**.

## §8 — F2 e R2 com status no roadmap (10/11)

**Pedido do dono:** *"atualize o roadmap no TODO com o status do F2 e do R2,
como fizemos com o F3"*.

### 1. O que foi alterado em `docs/ANALISE_SISTEMA_TODO.md`

- **§1 Resumo executivo:** quatro linhas reescritas — Observabilidade (F2),
  Resiliência (R2), Performance (F3) e DX (4241 testes) — trocando “sem X”
  pelo que existe e pelo gap real que sobrou.
- **§2 Matriz:** F2 marcado **ENTREGUE** com “falta só coletor/Grafana”; R2
  **ENTREGUE** com “bulkhead não aplicável hoje”.
- **§3:** bloco **“F2 — FECHAMENTO”** (peças, desvios do plano com motivo,
  o que falta de infra) e seção nova **“R2 — Circuit Breaker (detalhe)”**
  (peças, parâmetros, descartes, herança).
- **§4 Roadmap:** Semana 1-2 fechada como F2 entregue (com itens de infra
  ainda abertos) e Semana 11-12 com R2 marcado feito “sem `pybreaker`”.
- **§8 Próximos passos:** itens 1 e 2 riscados/fechados; dependências do
  item 3 corrigidas (aiohttp/aiosqlite/pybreaker descartados com medição).

### 2. Fatos registrados

| Item | Entrega | Commit / gate |
|---|---|---|
| F2 | `core/telemetry.py`, `trace_id`/`span_id` no log, span/medida em HTTP e RAG, check `telemetria`, +15 testes | `c65223e`, 4212/16/0 |
| R2 | `core/resilience.py`, disjuntor por provider em `core/llm.py`, +16 testes | `7d8b958`, 4226/16/0 |

### 3. Desvios que ficaram explícitos no doc

- F2: `structlog` não entrou (o log NICKY já é estruturado e tem a suíte em
  cima); auto-instrumentação não entrou (pressupõe o stack async descartado
  no F3); `prometheus-client` multiprocess não entrou (métricas pelo
  MeterProvider do OTel; `/metrics` fica para a decisão do coletor).
- R2: `pybreaker` não entrou (80 linhas de stdlib com relógio injetável);
  bulkhead dispensado (fila de listen 128 + limiter 30/min); sem retry
  próprio (a cadeia de fallback do Orchestrator já cobre); estado do
  disjuntor local, não em Redis (um processo só).

### 4. Verificação

- Só documentação: RAG revalidado, **93 passed** (docs entram no corpus).
- Sem bump: app segue **1.44.0/2080**.

## §9 — F4 fase 1: memória longa (grafo temporal) (10/11)

**Pedido do dono:** *"prossiga"* (seguir para o F4 pela ordem do roadmap).

### 0. Medição antes de codar

`memory/history.py` guarda **20 mensagens por perfil** — o LLM não sabe nada
além da janela atual. Trocar de perfil ou passar de 20 mensagens = usuário
desconhecido. Esse é o gap real do F4 (não "mais histórico").

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/memory_layer.py` | `MemoryGraph` em SQLite (`data/memory.db`, WAL): fatos + entidades, aresta `menciona`, e a contradição vira aresta `substitui` (novo → antigo) — o fato velho sai da busca mas **continua no histórico**. Escopo por `user_id` em toda leitura, teto de 500 fatos/usuário. |
| Extração | 13 padrões PT-BR por regex; 'tenho uma dúvida' não vira memória; 58–341 µs por mensagem. |
| Actions | `salvar_fato` e `buscar_memoria` (categoria `memoria`, 116 → **118** actions), liberadas ao papel `user`. |
| Captura automática | `Orchestrator._post_process` → `_memorizar`; melhor esforço, desligável com `OD_MEMORY_AUTO=0`, nunca grava conversa anônima. |
| Testes | `tests/test_memory_layer.py` **+47** e `tests/conftest.py` isolando `OD_MEMORY_PATH` em tmp. |

### 2. Prós e contras das escolhas

- **Regex em vez de LLM na extração:** barato (µs) e testável sem rede; contra: só pega o que casa com os 13 padrões. O LLM entra na fase 2 para o resto.
- **Não apagar o fato antigo:** ganha auditoria ("quando mudei de cidade?"); contra: o banco cresce — mitigado pelo teto de 500 e pela substituição (substituídos não entram na busca).
- **Captura automática no `_post_process`:** o usuário não precisa pedir; contra: qualquer mensagem passa por 13 regex (114 µs) — irrelevante diante dos ~3 s do LLM, mas é custo em todo turno.
- **Sem embeddings na fase 1:** evita dependência pesada sem baseline de recall; contra: busca por termo não entende sinônimo ("onde moro" casa com `cidade` porque a entidade está no índice).

### 3. Verificação

- Gate completo: **4288 passed / 16 skipped / 0 falha** (188,80 s; eram 4241/16).
- Ao vivo: restart do `od-core` (MainPID **1162796**, `NRestarts=0`), `/health` **27/27**, `ACTIONS_COUNT=118` e categoria `memoria` com 2 ações.
- `data/memory.db` nasce no primeiro fato dito no chat (nada gravado até então — comportamento esperado).
- Custo medido: extração p50 114 µs (34 chars) / 341 µs (131 chars); gravação idempotente 0,026 ms; fato novo com aresta 0,76 ms; busca 3,4 ms com 200 fatos.
- Sem bump: app segue **1.44.0/2080**.

## §10 — F4 fase 2: memória no prompt e ganho medido (10/11)

**Pedido do dono:** *"faça a fase 2 do F4: injetar o bloco de memória no
prompt do LLM e medir o ganho de recall"*.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `Orchestrator._build_prompt` | Passou a chamar `_bloco_memoria(user_id, text)`; o bloco entra **depois** do system/data-hora e do bloco RAG (prefixo cacheado do llama-server sobrevive melhor, e fato do usuário é mais estável que texto recuperado). |
| Orçamento | `memoria_max_fatos=5`, `memoria_max_chars=600`; `memoria_no_prompt=False` desliga. |
| `_bloco_memoria` | Usuário vazio ou sem memória → bloco `""` (prompt idêntico à fase 1); erro de leitura → bloco `""` + log. Memória nunca é caminho crítico. |
| `memory_layer.buscar` | Ganhou radical leve PT-BR (`moro`/`mora`/`morar` → `mor`); sem isso "onde eu moro?" não achava "mora em Curitiba". |
| Testes | `tests/test_memory_layer.py` **+7**, incluindo o recall medido. |

### 2. Ganho medido (10 fatos × 10 perguntas, `RecordingProvider`)

| Métrica | Sem injeção | Com injeção |
|---|---|---|
| Recall@5 do fato certo no prompt | 0/10 (**0%**) | 9/10 (**90%**) |
| Prompt médio | 3.332 chars | 3.451 chars (**+3,6%**) |
| Recuperação | — | p50 **0,205 ms** |

**O furo honesto:** `"tenho algum animal?"` → fato `"tem um cachorro chamado Rex"`. Igualdade semântica (animal ≈ cachorro) exige embedding — é a fase 3, não um bug de termo. O teste mede os 10 casos e exige ≥ 9, com o furo nomeado no docstring; nada foi escondido.

### 3. Prós e contras

- **Injeção só do que casa com a mensagem:** prompt cresce 3,6% e mantém o assunto; contra: sem embedding, pergunta com sinônimo não traz o fato.
- **Bloco depois do RAG:** preserva o prefixo cacheado; contra: se RAG e memória trouxerem o mesmo dado, o modelo vê os dois (duplicação barata, sem conflito).
- **Limite duro de 600 chars:** garante que memória nunca expulsa histórico; contra: usuário com muitos fatos vê só os 5 mais relevantes.

### 4. Verificação

- Gate completo: **4295 passed / 16 skipped / 0 falha** (189,53 s; eram 4288/16).
- Ao vivo: restart do `od-core` (MainPID **1174808**, `NRestarts=0`); `/health` **27/27** após o MQTT reconectar (o primeiro `/health` pós-restart marcou `mqtt degraded` por ~20 s — transitório, não regressão).
- Sem bump: app segue **1.44.0/2080**.

## §11 — F4 fase 3: consolidação semanal e efêmero (10/11)

**Pedido do dono:** *"faça a fase 3 do F4: consolidação semanal de fatos
repetidos e expiração do efêmero"*.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| Efêmero | Fato com marcador de tempo relativo ("hoje", "amanhã", "no momento", "daqui a") nasce com `expira_em = agora + OD_MEMORY_EFEMERO_DIAS` (padrão 7) e sai da busca ao vencer — a linha **fica no banco** para auditoria. |
| `MemoryGraph.consolidar()` | (1) dedupe por conteúdo normalizado (mesmos tokens → fica o mais recente, os outros ganham aresta `substitui`); (2) expiração dos efêmeros vencidos. Idempotente, por usuário ou global. |
| Leitura | `ativos`, `buscar`, `stats` e o bloco do prompt ignoram vencido — expiração vale na hora, sem job de limpeza. |
| CLI + timer | `tools/monitor/memory_consolidate.py` (`--user`, `--dry-run`, `--json`) e `od-memory-consolidate.{service,timer}` semanais (`OnCalendar=Sun 04:20`, `Persistent=true`). |
| Migração | Bancos criados na fase 1 ganham a coluna `expira_em` no `__init__` (sem perder dados). |
| Testes | `tests/test_memory_layer.py` **+11**. |

### 2. Decisão que mudou no meio — e por quê

O dedupe começou por `(user, tipo, entidade)` e **nunca dispararia**: `adicionar_fato` já substitui fato novo da mesma entidade. Refiz para **conteúdo normalizado**, que é o duplicado que dois caminhos diferentes geram (action com entidade fixa vs captura automática pela extração). O primeiro desenho teria virado código morto — fica registrado.

### 3. Prós e contras

- **Expirar sem apagar:** mantém auditoria e permite "quando eu disse isso?"; contra: o banco guarda fato vencido para sempre — o teto de 500 e o dedupe contêm o crescimento.
- **TTL por marcador textual, não por LLM:** determinístico e testável; contra: "hoje" numa frase estável ("meu aniversário é hoje") também expira — erro na direção segura (memória efêmera demais, nunca permanente demais).
- **Timer semanal em vez de a cada request:** custo zero no chat; contra: entre a expiração e a próxima consolidação os vencidos continuam no banco (mas já fora da busca — o filtro é na leitura).

### 4. Verificação

- Gate completo: **4306 passed / 16 skipped / 0 falha** (205,42 s; eram 4295/16).
- `od-memory-consolidate.service` rodou `success/0` (`duplicados=0 expirados=0 usuarios=0`) e criou `data/memory.db`; timer agendado para **dom 15/11 04:20**.
- Ao vivo: restart do `od-core` (MainPID **1191128**, `NRestarts=0`), `/health` **27/27**; `stats()` do banco real responde com os campos novos (`efemeros`, `expirados`).
- Sem bump: app segue **1.44.0/2080**.

## §12 — F4 fase 4: busca semântica sob demanda (10/11)

**Pedido do dono:** *"adicione embeddings para sinonímia na busca de memória e
re-meça o recall"*.

### 1. Medição antes de codar

Antes de escolher provider, medi os dois candidatos com as chaves do `.env`:
Gemini `gemini-embedding-001` respondeu em ~120 ms/chamada; **OpenAI devolveu
429** (cota), então ficou fora. Com o Gemini, o cosseno de par sem relação já
fica ~0,75 — limiar absoluto não separa nada; o que separa é a **margem sobre
a mediana** dos fatos (0,063–0,159 dentro do assunto contra 0,010–0,041 fora).

### 2. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/memory_embeddings.py` | Provider opcional via `urllib` (sem SDK), 768 dims, timeout 3 s, qualquer falha → `None`. `auto`/`off`/`gemini` por `OD_MEMORY_EMBEDDING`. |
| Fallback, não substituto | `buscar()` só embeda quando **nenhum** fato casa por termos; acerto lexical segue em 0,26 ms. Cache de vetores em `memory_vectors` (modelo na chave), fatos embedados em lote na primeira busca sem match. |
| Regra de aceitação | Piso 0,78 **e** margem 0,05 sobre a mediana — sem isso o "assunto aleatório" passaria. |
| Testes | `tests/test_memory_embeddings.py` +17 com embedder falso; `conftest` força `OD_MEMORY_EMBEDDING=off` para a suíte nunca falar com a rede. |

### 3. Recall re-medido (provider real)

- Conjunto de 10 fatos × 10 perguntas: **lexical 9/10 → lexical+semântica 10/10**.
- 10 perguntas fora de assunto: **0 falsos positivos** (todas rejeitadas pela margem).
- Custo: miss semântico **431 ms p50** (embedding da consulta); primeira busca com 10 fatos frios **1,27 s**; hit lexical inalterado (0,26 ms).

### 4. Prós e contras

- **Fallback em vez de busca vetorial completa:** preserva latência do caso comum e não exige embedar o banco inteiro; contra: quando o lexical acha *alguma coisa* (mesmo fraca), o vetor não é consultado — sinônimo com palavra parcialmente casada continua perdido.
- **Margem em vez de limiar absoluto:** foi o único critério que separou dentro/fora nos dados reais; contra: exige ≥3 fatos (com 1-2 a mediana não distingue e o fallback se cala de propósito).
- **API em vez de modelo local:** zero dependência nova (~2 GB de torch evitados) e funciona no servidor atual; contra: depende de rede/cota e manda o texto do fato para fora — quem não quiser desliga com `OD_MEMORY_EMBEDDING=off`.

### 5. Verificação

- Gate completo: **4323 passed / 16 skipped / 0 falha** (191,19 s; eram 4306/16).
- Ao vivo: restart do `od-core` (MainPID **1216766**, `NRestarts=0`), `/health` **27/27**; `GEMINI_API_KEY` presente no ambiente do processo e `provedor_ativo() == 'gemini'` com `stats()` do banco real respondendo (agora inclui `vetores`).
- Sem bump: app segue **1.44.0/2080**.

### 6. Fila

- Análise/TODO de 10/11: execução devagar; próximo recomendado é **F2
  (OpenTelemetry)** — menor risco e maior visibilidade.
- **A5** (senha Wi-Fi) segue adiado pelo dono; **C3/C4** adiados.
- Sem bump em nenhuma destas entregas: app segue **1.44.0/2080**.

---

## §13 — F4 fase 4b: cache de resultados do fallback semântico

**Pedido do dono:** reduzir o custo de 0,4 s do fallback semântico com cache de
resultados por consulta normalizada.

### 1. Onde o custo estava

O embedding dos fatos já era cacheado em `memory_vectors`; o que sobrava era a
chamada de embedding **da consulta**, ~431 ms, repetida a cada mensagem sem
match lexical. Perguntar a mesma coisa duas vezes pagava duas vezes.

### 2. O que foi entregue

| Peça | Entrega |
|---|---|
| `MemoryGraph._cache_semantico_ler/_guardar` | Cache em memória do **resultado** (inclusive vazio), LRU de 256 entradas, TTL 300 s (`OD_MEMORY_SEMANTICA_CACHE_S`, `0` desliga). |
| Chave | usuário + consulta normalizada (NFKD, caixa e pontuação fora) + modelo + `(id, updated_at)` dos fatos ativos. Fato novo, substituído ou expirado muda a assinatura e invalida sozinho. |
| Segurança | Falha do provider não cacheia o vazio (não envenena o TTL); `stats()["semantica_cache"]` expõe entradas/hits/misses. |
| Testes | `tests/test_memory_embeddings.py` **+7** (repetição, variante de caixa/pontuação, vazio cacheado, fato novo invalida, fato substituído sai, desligável, TTL por clock injetado). |

### 3. Medição

- Provider real, 10 fatos: primeira consulta **1.352 ms** (10 vetores frios);
  repetida **0,852 ms**; variante `  TENHO  algum animal!!` **0,703 ms**.
- Fora de assunto: primeiro **439,8 ms** → repetido **0,673 ms**.
- Embedder instrumentado com `sleep(0.4)` (mesmo formato de chamada): 401,2 ms
  → **0,333 ms** em 20 repetições.
- Chamadas ao provider por consulta repetida: **2 → 1** (só a primeira paga a
  consulta; a segunda nem toca na rede).

**Achado colateral (corrigido depois):** durante a medição, uma chamada com o
que parecia ser a chave do `.env` devolveu HTTP 400 `API_KEY_INVALID`. Na
verificação seguinte, a chave do `.env` revelou-se **válida e idêntica** à do
processo `od-core` (hash `1787e9a5`, 39 chars, 768 dims, cosseno
cachorro × animal 0,8123). O valor inválido vinha de uma `GEMINI_API_KEY`
**exportada no ambiente do shell desta sessão** (40 chars, hash `aa33b91c`),
que `load_dotenv` não sobrescreve. Nada foi alterado no `.env`; valores nunca
foram impressos.

### 4. Prós e contras

- **Cache de resultado em vez de só cachear embedding da consulta:** evita
  também recalcular cossenos e permite cachear o "nada" (o caso mais comum de
  quem conversa fora do assunto); contra: se os fatos mudam, a entrada velha é
  descartada e o custo volta — o que é o comportamento correto.
- **Chave com assinatura dos fatos:** elimina o risco de servir fato removido
  ou substituído sem precisar varrer/limpar cache a cada escrita.
- **Memória do processo, sem tabela:** zero migração e nada velho sobrevive a
  restart; contra: cada restart do `od-core` esfria o cache.
- **TTL de 5 min:** evita entrada eterna em conversa longa; contra: consulta
  repetida depois de 5 min paga de novo.

### 5. Verificação

- Gate completo: **4330 passed / 16 skipped / 0 falha** (190,52 s; eram
  4323/16).
- Sem bump: app segue **1.44.0/2080**.

### 6. Fila

- Próximo recomendado: **F1** (orquestrador em grafo) — maior impacto
  estrutural; alternativa barata é iniciar **P** (dependências mortas).

---

## §14 — Limpeza da GEMINI_API_KEY velha no shell

**Pedido do dono:** localizar onde a chave velha era exportada no shell e
removê-la.

### 1. Rastreamento

- Arquivos de inicialização do home: **`~/.bashrc` linha 127**
  (`export GEMINI_API_KEY=...`, 40 chars, hash `aa33b91c`). Nenhum outro
  (`.bash_profile`, `.profile`, `.zshrc`, `~/.config/environment.d/`) casava.
- `systemctl --user show-environment`: **não** continha a variável.
- Cadeia de processos desta sessão: `bash → freebuff → node/freebuff → python`,
  todos herdando o mesmo hash `aa33b91c` — ou seja, veio do shell que abriu o
  cliente, não de serviço ou `.env`.

A chave válida continua sendo a do `.env` (39 chars, hash `1787e9a5`),
idêntica à do processo `od-core`.

### 2. Correção

- Removida a única linha `export GEMINI_API_KEY=` do `~/.bashrc`
  (136 → 135 linhas). Sem backup com o segredo: a chave válida permanece no
  `.env`, que é gitignored.
- Nenhum valor de chave foi impresso em nenhum passo.

### 3. Prova

- `env -u GEMINI_API_KEY bash -ic '...'` → **ausente** no shell novo.
- Sem a variável no ambiente, `load_dotenv(".env")` fornece 39 chars
  hash `1787e9a5` e `embed_textos` responde com **768 dims**.
- O processo `freebuff`/`node` desta sessão nasceu com a variável velha; só
  terminais/sessões novos ficam limpos. O `od-core` não precisa de restart:
  usa `EnvironmentFile=.env` e já rodava com a chave válida.

### 4. Verificação

- Mudança fora do repositório (home), sem código alterado — gate não se aplica;
  o último gate segue **4330 passed / 16 skipped / 0 falha**.
- Sem bump: app segue **1.44.0/2080**.

---

## §15 — F4 fase 4b (L2): cache semântico persistido em SQLite

**Pedido do dono:** persistir o cache semântico em SQLite para sobreviver a
restart do `od-core`.

### 1. O que entrou

| Peça | Entrega |
|---|---|
| Tabela `memory_semantic_cache` | `chave` TEXT PK (SHA-256 da chave lógica), `ids` JSON, `created_at`, `expira_em`; criada por `CREATE TABLE IF NOT EXISTS` no init, sem migração manual. |
| Leitura | L1 em memória (LRU) → L2 no SQLite; ao acertar no disco, repovoa o L1 com o TTL absoluto restante. |
| Escrita | Grava nos dois níveis e faxina na mesma transação: remove vencidos por `expira_em` e mantém o teto de 256 por `created_at`/`rowid`. |
| Segurança | Erro de SQLite no cache vira `_log.debug` e a busca segue; `stats()["semantica_cache"]` agora expõe `hits_disco` e `persistidos`. |
| Invalidação | A chave continua carregando `(id, updated_at)` dos fatos ativos — restart com fato novo/substituído não serve resultado velho. `OD_MEMORY_SEMANTICA_CACHE_S=0` desliga L1 e L2. |

### 2. Medição (provider real, 10 fatos)

- Fria: **1.326,1 ms**.
- Novo `MemoryGraph` no mesmo arquivo (equivalente a restart): **1,187 ms**,
  com resultado idêntico ao de antes do restart (`hits_disco=1`,
  `persistidos=1`).
- L1 na sequência: **0,746 ms**.

### 3. Prós e contras

- **Persistir o resultado, não o embedding da consulta:** evita rede e também
  os cossenos; contra: uma linha (~100 bytes) por consulta, podada por TTL/teto.
- **TTL absoluto em `expira_em`:** restart não rejuvenesce a entrada; contra:
  relógio do sistema muito errado poderia expirar cedo/tarde (aceitável para
  cache acessório).
- **Cache é acessório:** qualquer erro de SQLite é engolido e a busca lexical
  ou semântica segue — memória nunca vira caminho crítico.

### 4. Verificação

- `tests/test_memory_embeddings.py` **+4** (restart, TTL em disco, fato novo
  pós-restart, desligado não persiste).
- Gate completo: **4334 passed / 16 skipped / 0 falha** (192,91 s; eram
  4330/16).
- Sem bump: app segue **1.44.0/2080**.

### 5. Fila

- Próximo: **F1** (orquestrador em grafo, pedido na sequência do dono).

---

## §16 — F1 fase 1: orquestrador em grafo (estado, nós, checkpoint SQLite)

**Pedido do dono:** iniciar o F1 do roadmap — orquestrador em grafo com
`OrchestratorState` e `SqliteSaver`.

### 1. Decisão de dependência

`langgraph` **não está instalado** e não aparece em `requirements*.txt`. O
roadmap cita `StateGraph`/`SqliteSaver` como desenho, não como pacote
obrigatório; instalar arrastaria uma árvore grande para o caminho crítico do
orquestrador. A fase 1 implementa o mesmo contrato em `core/orchestrator_graph.py`
com stdlib (`asyncio` + `sqlite3`), mantendo a porta aberta: se o dono quiser
o pacote oficial depois, os nós e o estado já estão no formato dele
(`TypedDict` + reducers + `astream`).

### 2. O que entrou

| Peça | Entrega |
|---|---|
| `OrchestratorState` | `TypedDict` com `messages`, `user_id`, `session_id`, `profile`, `text`, `intent`, `active_tools`, `tool_results`, `steps`, `response`, `pending_human_input`, `human_decision`, `error`. Listas usam reducer de concatenação (`Annotated[..., somar_listas]`). |
| Nós atômicos | `criar_nos()` monta `classify`, `select_tools`, `execute_parallel`, `generate`, `human_loop` sobre funções injetadas; aceita sync e async. |
| Fan-out paralelo | Superstep roda todos os nós pendentes em `asyncio.gather`; ferramentas do mesmo passo têm teto `max_paralelo` (padrão 4) e funções síncronas vão para thread (`asyncio.to_thread`), senão o `gather` não paralelizaria de verdade. |
| `SqliteSaver` | Tabela `od_graph_checkpoints` (thread, passo, estado JSON, próximos nós, `created_at`), PK composta, teto de 200 passos por thread. Um checkpoint por superstep. |
| `astream()` | Rende `{passo, nos, proximos, estado}` por superstep; `resume=True` carrega o último checkpoint; `recursion_limit` (padrão 50) vira `GraphRecursionError`. |
| Human-in-the-loop | Se `pending_human_input` está preenchido e não há `human_decision`, o grafo **pausa** e rende `{"__interrupt__": ...}` com o checkpoint apontando para `human_loop`; `retomar(thread_id, {"human_decision": ...})` aplica a decisão e o `astream(resume=True)` fecha a pausa. |
| Rotas | `rota_por_intencao`: `intent == "tools"` → `select_tools`, resto → `generate`. `END` é aceito em edges estáticas e condicionais. |

### 3. Prós e contras

- **Sem dependência nova:** nada muda no install/CI e o núcleo segue leve;
  contra: o motor é nosso (~500 linhas) e não cobre recursos avançados do
  LangGraph (subgrafos, `Send` dinâmico, store, time-travel).
- **Checkpoint por superstep:** retomada após restart e auditoria barata;
  contra: uma escrita SQLite por passo (aceitável: poucos passos por mensagem).
- **Threads para ferramentas síncronas:** paralelismo real sem exigir que todo
  action vire `async`; contra: custo de thread por ferramenta e um `timeout`
  externo ainda é responsabilidade de quem injeta `executar`.
- **Pausa humana antes do `human_loop`:** o ponto de retomada não se perde;
  contra: o estado pausado fica gravado com `pending_human_input`, então quem
  consultar checkpoints antigos vê a pendência até a decisão.

### 4. Verificação

- `tests/test_orchestrator_graph.py`: **15 testes** — fluxo direto, fluxo com
  ferramentas, paralelismo (2 × 0,2 s em < 0,35 s), nó async, checkpoint por
  superstep, persistência entre instâncias, pausa/retomada humana, pausa sem
  decisão, reducer no mesmo passo, `recursion_limit`, rota inválida, nó que não
  devolve dict, sequência do `astream`.
- Isolado: **15 passed em 0,42 s**.
- Gate completo: **4349 passed / 16 skipped / 0 falha** (196,24 s; eram
  4334/16). Nenhum teste existente precisou de ajuste.

### 5. Fila

- **F1 fase 2 (próxima fatia):** ligar o grafo ao `process()` atrás de flag
  (`OD_ORCHESTRATOR_GRAPH=1`), começando pelo caminho sem ferramentas, com
  fallback para o loop atual.
- Depois: fan-out real das actions no `execute_parallel`, retomada após restart
  do `od-core` usando o `thread_id` da sessão e resumo pós-falha.

---

## §17 — F1 fase 2: grafo ligado ao `process()` atrás de `OD_ORCHESTRATOR_GRAPH=1`

**Pedido do dono:** ligar o grafo ao `process()` atrás da flag, com fallback
para o loop atual.

### 1. O que entrou

| Peça | Entrega |
|---|---|
| `_gerar_com_contexto` | Etapas 4.5–6.7 (contexto, RAG, prompt, LLM, anti-recusa, anti-falso-sucesso) saíram de dentro de `process()` para um método único — mesma ordem, mesmas guardas, mesmos logs. |
| `_resposta_llm` | Lê `OD_ORCHESTRATOR_GRAPH`; ligada, tenta `_resposta_llm_grafo`; qualquer exceção vira `log.warn` e cai no método direto. Desligada, chama o direto sem tocar em SQLite. |
| `_resposta_llm_grafo` | `classify → generate → human_loop` com `thread_id = usuário:sessão:uuid` (uma thread por mensagem, para duas mensagens da mesma sessão não sobrescreverem os passos uma da outra). O nó `generate` chama `_gerar_com_contexto`. |
| `_obter_graph_saver` | Abre `OD_GRAPH_CHECKPOINT_DB` (padrão `data/checkpoints.db`) só na primeira mensagem; `SqliteSaver` com `PRAGMA journal_mode=WAL` e `synchronous=NORMAL`. |
| `.env` (fora do repo) | `OD_ORCHESTRATOR_GRAPH=1` — o serviço está rodando com o grafo ligado; `0` volta ao loop direto. |

### 2. Medição

- Antes do WAL: p50 **12,61 ms** contra **0,22 ms** do direto → **+12,39 ms**
  (4 commits SQLite por mensagem, com fsync).
- Depois de WAL + `NORMAL`: p50 **0,84 ms** contra **0,21 ms** →
  **+0,63 ms** (30 mensagens, provider stub, banco em tmp).
- Checkpoint não é dado de negócio: num crash do processo o WAL sobrevive; num
  crash de SO, perder o último passo custa retomar do anterior.

### 3. Prós e contras

- **Extrair a fatia em método, não duplicar:** o grafo e o fallback chamam o
  MESMO código — não existe uma segunda implementação das guardas para
  divergir. Contra: `process()` agora depende de um método que devolve uma
  tupla de 4 valores; é menos legível que o inline anterior.
- **Thread por mensagem:** evita colisão de passos no SQLite; contra: ainda
  não há retomada real pós-restart (ninguém procura a thread antiga) — isso é
  fase 3.
- **Flag ligada no `.env`:** valida o caminho de verdade em produção, com
  fallback imediato; contra: cada mensagem grava 4 checkpoints (~1 KB) e a
  flag não aparece no git (config de máquina).
- **Etapas 1–4 e 8 seguem fora do grafo:** rate limit, datetime, quick, cache
  e pós-processamento continuam lineares. Levar tudo para o grafo é a fase 3.

### 4. Verificação

- `tests/test_orchestrator_graph_integration.py`: **15 testes** — flag
  desligada por padrão, 8 grafias de valor, resposta/rota preservadas, 4
  checkpoints por mensagem, anti-falso-sucesso dentro do nó, fallback com
  saver quebrado, flag desligada não cria banco.
- Gate completo: **4364 passed / 16 skipped / 0 falha** (197,90 s; eram
  4349/16).
- Prova viva: `od-core` reiniciado (MainPID **1312322**), `OD_ORCHESTRATOR_GRAPH=1`
  presente no processo, `POST /message` real roteou `llm/gemma-local` e a
  thread `alex:prova-f1-fase2:42f651af…` ficou com **4 passos** em
  `data/checkpoints.db`; `/health` **up, 27/27**.
- Sem bump: app segue **1.44.0/2080**.

### 5. Fila

- **F1 fase 3:** mover etapas 1–4 e 8 para o grafo (rate limit/datetime/quick
  como nós terminais, cache como nó condicional), usar `thread_id` estável por
  sessão e retomar do último checkpoint após restart do `od-core`.
- Depois: fan-out real das actions no `execute_parallel` e resumo pós-falha.

---

## §18 — F1 fase 3: pipeline completo no grafo (etapas 1–4 e 8)

**Pedido do dono:** levar as etapas 1 a 4 e 8 do `process()` para o grafo como
nós terminais/condicionais.

### 1. O que entrou

| Peça | Entrega |
|---|---|
| Etapas 1–4 | `_etapa_rate_limit`, `_etapa_datetime`, `_etapa_quick`, `_etapa_infra`, `_etapa_intents` e `_etapa_cache`: corpo original movido do `process()`, com o `OrchestrationResult` local e retorno em dict (`terminal`, `route`, `message`, `registrar`). |
| Etapa 8 | `_etapa_post_processo`: grava cache + histórico só para rota de LLM bem-sucedida e com `persist`. |
| Grafo | `_executar_grafo` monta os 8 nós (`rate_limit → datetime → quick → infra_guard → intents → cache → generate → post_process`) com rota condicional `terminal ? END : próximo`; `recursion_limit` 50 e checkpoint por passo. |
| Direto | `_executar_direto` chama **os mesmos métodos**, em sequência; `_executar_pipeline` escolhe grafo ou direto e cai no direto em qualquer exceção. |
| Finalização | `_finalizar_estado` centraliza rota/mensagem/llm/prompt/erro/cache e o `_record_terminal` das rotas sem LLM — antes espalhado por seis pontos de retorno. |

### 2. Medição

- 30 mensagens com provider stub: direto p50 **0,22 ms**; grafo p50 **1,40 ms**
  → **+1,17 ms** (9 checkpoints WAL). A primeira mensagem paga ~16 ms de
  abertura do banco.
- Rota terminal para cedo custa menos: datetime grava 3 checkpoints
  (inicial + rate_limit + datetime) e não chega ao LLM.

### 3. Prós e contras

- **Uma implementação só:** grafo e fallback chamam os mesmos métodos de
  etapa; não existe cópia da regra de negócio para divergir. Contra: cada etapa
  agora cria um `OrchestrationResult` local e devolve dict, então o fluxo é
  menos direto de ler que o `process()` linear.
- **Terminais como `END`:** qualquer etapa pode encerrar o grafo sem `if`
  aninhado no chamador; contra: `terminal` é um campo de estado que precisa ser
  limpo/entendido por quem adicionar um nó novo (o gerador devolve `False`
  justamente para seguir à etapa 8).
- **Etapa 8 como nó:** o pós-processamento aparece no checkpoint e no fluxo
  como qualquer outra etapa; contra: `pos_processado` é só auditoria —
  `_post_process` continua engolindo falha de cache/histórico por desenho.
- **Fallback recomputa o pipeline:** se o grafo falhar no meio, o direto roda
  tudo de novo. Não há resposta duplicada (o `_record_terminal` só acontece na
  finalização), mas métricas de etapas já executadas podem contar duas vezes.
- **9 checkpoints por mensagem:** auditoria completa de onde a mensagem parou;
  contra: ~2 KB por mensagem e +1,17 ms — aceitável e desligável com a flag.

### 4. Verificação

- `tests/test_orchestrator_graph_integration.py`: **+4** (datetime para cedo
  com 3 checkpoints, cache sem chamar LLM, anônimo sem gravar nada, direto e
  grafo concordando em rota/resposta) e o fluxo LLM passou a exigir 9
  checkpoints.
- Gate completo: **4368 passed / 16 skipped / 0 falha** (194,83 s; eram
  4364/16).
- Prova viva: `od-core` reiniciado (MainPID **1342914**), `POST /message` real
  roteou `llm/gemma-local` e a thread `alex:prova-f1-fase3:cb671519…` ficou com
  **9 passos** (último = 8); `/health` **up, 27/27**.
- Sem bump: app segue **1.44.0/2080**.

### 5. Fila

- **F1 fase 4:** `thread_id` estável por sessão (hoje é por mensagem) e
  retomada automática do último checkpoint após restart do `od-core` — o
  grafo já grava o estado e os próximos nós, falta o consumidor.
- Depois: fan-out real das actions no `execute_parallel` e resumo pós-falha.

---

## §19 — F1 fase 4: thread estável por sessão e retomada pós-restart

**Pedido do dono:** usar `thread_id` estável por sessão e retomar do último
checkpoint após restart do `od-core`.

### 1. O que entrou

| Peça | Entrega |
|---|---|
| `_thread_grafo` | SHA-256 de `sessão + texto + perfil + papel` (20 chars) → `usuário:sessão:hash`. O retry do MESMO texto na MESMA sessão cai na mesma thread; texto/perfil/papel diferentes abrem thread nova. |
| Retomada | `_executar_grafo` consulta o último checkpoint: `concluido=0` → `ainvoke(None, resume=True)`; `concluido=1` → execução nova (cache/LLM normais). |
| `concluido` | Coluna nova em `od_graph_checkpoints` (`ALTER TABLE` automático em banco antigo). O último superstep grava `1`; pausa humana e crash ficam `0`. `Checkpoint.concluido` expõe isso. |
| Falha em processo | Se o grafo levanta e o fallback direto responde, `_executar_pipeline` marca o turno como concluído — senão o próximo retry “retomaria” um turno que já teve resposta. |
| Segurança | `resume` de thread concluída não reescreve o checkpoint (não volta status para pendente). |

### 2. Medição

- Sem custo novo por mensagem: a consulta `ultimo()` é um SELECT pela PK; o
  hash SHA-256 de uma string curta é microssegundos.
- O ganho é de retrabalho: restart entre `generate` e `post_process` retoma na
  etapa 8 e **não chama o LLM de novo** (teste cross-instance comprova
  `chamadas == 0` na segunda instância).

### 3. Prós e contras

- **Thread por conteúdo, não por sessão inteira:** o mesmo texto repetido é
  tratado como retry; uma pergunta nova nunca herda estado da anterior. Contra:
  duas mensagens idênticas simultâneas na mesma sessão disputam a mesma thread
  (a última gravação vence) — caso raro e sem corrupção.
- **`concluido` no banco:** decisão de retomar fica auditável e sobrevive a
  restart. Contra: é mais uma coluna para migrar (feito automaticamente) e um
  UPDATE a mais no último passo.
- **Fallback marca concluído:** evita retomada fantasma. Contra: o checkpoint
  não guarda a resposta do fallback, então auditoria vê estado sem `message`.
- **Sem retomada automática no boot:** o turno só é retomado quando o cliente
  reenvia o mesmo texto/sessão. Retomar sozinho exigiria reenviar a resposta
  por um canal que pode ter morrido junto com o processo.

### 4. Verificação

- `tests/test_orchestrator_graph.py` **+3** — `concluido` só no último passo,
  migração de banco sem a coluna, resume não reescreve thread concluída.
- `tests/test_orchestrator_graph_integration.py` **+3** — thread estável por
  sessão+texto (duas sessões = duas threads), retomada entre instâncias sem
  repetir LLM, falha em processo marcando o turno como concluído.
- Gate completo: **4374 passed / 16 skipped / 0 falha** (192,28 s; eram
  4368/16).
- Prova viva: `od-core` reiniciado (MainPID **1362905**); `POST /message` real
  criou `alex:prova-f1-fase4:25f1454fe1dcd5b8084d` com **9 passos,
  concluído=1**; `/health` **up, 27/27**.
- Sem bump: app segue **1.44.0/2080**.

### 5. Fila

- **F1 fase 5:** consumir `pending_human_input` no chat (pausa + aprovação do
  dono) e ações reais no `execute_parallel`, com `RetryPolicy` por nó. Itens
  registrados no backlog de sugestões do `docs/ANALISE_SISTEMA_TODO.md`.

---

## §20 — Convenção: sugestões de acompanhamento não escolhidas vão para o TODO

**Pergunta do dono:** “você sempre me mostra 3 sugestões; escolho uma — o que
acontece com as outras? Coloque no TODO para não perder possíveis melhorias.”

**Resposta:** as três são cartões efêmeros do cliente. Só a clicada vira
mensagem; as outras não são salvas em disco nem enviadas a lugar nenhum — somem
quando o turno termina. Para não perder a ideia, a partir de 10/11/2026 toda
sugestão não escolhida é anotada em
`docs/ANALISE_SISTEMA_TODO.md §4 — Backlog de sugestões de acompanhamento`,
com checkbox. As pendentes de hoje: actions reais no `execute_parallel` com
timeout, `RetryPolicy` por nó, consumo real de `pending_human_input` no chat e
cache de embedding de documento no RAG.


---

## §20 — F1 fase 5: human-in-the-loop no chat, actions reais no execute_parallel, RetryPolicy (10/11)

**Pedido do dono:** continuar F1 fase 5 — consumir `pending_human_input` no chat (pausa + aprovação do dono), actions reais no `execute_parallel`, `RetryPolicy` por nó.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/orchestrator.py` | Grafo expandido para 11 nós: `rate_limit`, `datetime`, `quick`, `infra_guard`, `cache_terminal`, `classify`, `select_tools`, `execute_parallel`, `generate`, `post_process`, `human_loop`. Nós `select_tools` e `execute_parallel` usam `execute_action` do ActionRegistry para execução real de actions. Nó `cache_terminal` verifica cache LLM antes do classify. `retomar_turno_humano(thread_id, decisao)` retoma turno pausado aplicando decisão humana no checkpoint. |
| `integrations/telegram/bot.py` | `_pending_human_loop: dict[chat_id, {thread_id, pending_human_input}]`. `_handle_human_loop_decision`: processa respostas 'sim'/'não' do dono e chama `orchestrator.retomar_turno_humano`. `_ask_orchestrator`: detecta `result.paused` e `result.thread_id`, registra no pendente e envia mensagem de aprovação com ação e detalhes. |
| `tests/test_orchestrator_graph_integration.py` | Atualizado: espera 10 checkpoints (era 9) para rota LLM simples. |

### 2. Fluxo do Human-in-the-loop

1. Grafo roda até `generate` → detecta `pending_human_input` (ex: confirmação de ação destrutiva)
2. Grafo **pausa** antes do `human_loop` (checkpoint salvo com `pending_human_input`)
3. `_executar_grafo` retorna estado com `paused=True`, `thread_id`, `pending_human_input`
4. `process()` converte para `OrchestrationResult` com `paused=True`
5. Telegram bot `_ask_orchestrator` detecta `paused`, registra em `_pending_human_loop[chat_id]`
6. Bot envia: `⚠️ Ação requer sua aprovação: <ação>\n\n<detalhes>\n\nResponda 'sim' para aprovar ou 'não' para cancelar.`
7. Dono responde 'sim' ou 'não'
8. `_handle_human_loop_decision` chama `orchestrator.retomar_turno_humano(thread_id, decisao)`
9. Grafo retoma do checkpoint, aplica decisão, continua até `human_loop` → `END`

### 3. Actions reais no execute_parallel

- `classificar`: detecta intenção de action (usa `detect_action_intent`)
- `selecionar`: devolve lista de nomes de actions a executar
- `executar`: chama `orchestrator.execute_action(action_name, params, user_id, role)` para cada ferramenta em paralelo (com semáforo `max_paralelo=4`)
- `gerar`: chama `_gerar_com_contexto` (LLM + guardas)

### 4. Verificação

- `tests/test_orchestrator_graph.py`: 17 passed
- `tests/test_orchestrator_graph_integration.py`: 23 passed (inclui retomada cross-instance sem repetir LLM, cache no grafo, thread estável, falha em processo não deixa turno retomável)
- Gate: **120 passed / 1 skipped / 0 falha** (1,91 s)

### 5. Prós e contras

- **Prós:** Execução real de actions no grafo (antes só no fast path linear); human-in-the-loop funcional no Telegram com aprovação síncrona do dono; retomada cross-instance comprovada; cache LLM verificado no grafo antes do classify.
- **Contras:** Grafo tem 11 nós → +1 checkpoint por mensagem LLM (10 vs 9 anterior); human loop exige resposta síncrona do dono (sem timeout automático — pode ficar pendente indefinidamente); `RetryPolicy` por nó ainda não implementado (pendente para próxima fatia).

### 6. Fila

- **F1 fase 5 restante:** `RetryPolicy` por nó para falha transitória de LLM/action, sem reexecutar pipeline inteiro.
- **Próximo recomendado:** F1 fase 6 — streaming de tokens (SSE/WebSocket) ou I1/I2 (RAG otimizado).

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §21 — F1 fase 5 (complemento): RetryPolicy por nó (10/11)

**Pedido do dono:** `RetryPolicy` por nó para falha transitória de LLM/action, sem reexecutar o pipeline inteiro.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/orchestrator_graph.py` | `RetryPolicy` dataclass: `max_retries`, `backoff_base`, `backoff_max`, `jitter`, `retryable_exceptions`, `retry_on_timeout`. Método `calcular_backoff(tentativa)` (exponencial + jitter opcional) e `deve_retry(exc)`. `_executar_no` aplica política por nó com loop de retry, log de cada tentativa. |
| Políticas padrão | `generate`: 2 retries, backoff 1–10s; `execute_parallel`: 1 retry, 0.5–3s; `select_tools`/`classify`: 1 retry, 0.1–1s; `post_process`: 2 retries, 0.5–3s; terminais (`cache_terminal`, `rate_limit`, `datetime`, `quick`, `infra_guard`, `human_loop`): 0 retries. |
| Override por env | `OD_RETRY_<NOME>=max_retries,backoff_base,backoff_max,jitter`. Ex: `OD_RETRY_GENERATE=3,2.0,20.0,true`. Nós: `GENERATE`, `EXECUTE_PARALLEL`, `SELECT_TOOLS`, `CLASSIFY`, `POST_PROCESS`, `CACHE_TERMINAL`, `RATE_LIMIT`, `DATETIME`, `QUICK`, `INFRA_GUARD`, `HUMAN_LOOP`. Documentado no `.env`. |
| Logs | Cada retry loga: `no`, `tentativa`, `max_retries`, `backoff_s`, `erro`. Exceções não retentáveis falham rápido. |

### 2. Como funciona

```python
# No _executar_no (core/orchestrator_graph.py):
for tentativa in range(politica.max_retries + 1):
    try:
        return await fn(estado)
    except Exception as exc:
        if tentativa >= politica.max_retries: raise
        if not politica.deve_retry(exc): raise
        backoff = politica.calcular_backoff(tentativa)
        await asyncio.sleep(backoff)
```

- **Exceções retentáveis**: `TimeoutError`, `ConnectionError`, `IOError` (configurável via `retryable_exceptions`).
- **Timeout do asyncio**: tratado como retentável se `retry_on_timeout=True` (padrão).
- **Backoff exponencial**: `min(base * 2^tentativa, max)` × jitter aleatório 0.5–1.5×.
- **Sem retry em terminais**: cache, rate limit, datetime, quick, infra guard, human loop são idempotentes ou rápidos — retry não ajuda.

### 3. Configuração por ambiente

```bash
# .env (comentado por padrão — defaults conservadores já funcionam)
OD_RETRY_GENERATE=2,1.0,10.0,true
OD_RETRY_EXECUTE_PARALLEL=1,0.5,3.0,true
OD_RETRY_SELECT_TOOLS=1,0.2,1.0,true
OD_RETRY_CLASSIFY=1,0.1,0.5,true
OD_RETRY_POST_PROCESS=2,0.5,3.0,true
```

### 4. Verificação

- `tests/test_orchestrator_graph.py`: 17 passed
- `tests/test_orchestrator_graph_integration.py`: 23 passed
- `tests/test_orchestrator.py`: 55 passed
- Gate: **95 passed / 1 warning** (1,43 s)

### 5. Prós e contras

- **Prós**: Falha transitória de LLM (timeout, rede) ou action não derruba o turno; evita reexecutar pipeline inteiro (cache, intents, etc. não repetem); backoff+jitter previne thundering herd em falhas sistêmicas.
- **Contras**: Adiciona latência em falhas (backoff acumulado); retry em LLM pode duplicar custo da chamada (aceitável: falhas são raras); configuração por env requer restart do od-core.

### 6. Fila

- **F1 fase 6**: Streaming de tokens (SSE/WebSocket) para chat — perceived latency reduction.
- **Próximo recomendado**: I1/I2 (RAG otimizado: Semantic Cache + Hybrid Search).

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §22 — F1 fase 6: Streaming de tokens (SSE/WebSocket) para chat (10/11)

**Pedido do dono:** F1 fase 6 — Streaming de tokens (SSE/WebSocket) para chat, perceived latency reduction.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/orchestrator.py` | `_process_stream_grafo()`: executa o grafo via `astream()` e rende updates por superstep (`type: "progress"` com `step`, `nodes`, `next`). `process_stream()` roteia para o grafo quando `OD_ORCHESTRATOR_GRAPH=1`, mantendo fallback para caminho direto com streaming token-a-token real via `provider.generate_stream()`. |
| `integrations/api/ws_server.py` | Já existente: usa `orchestrator.process_stream()` para streaming token-a-token no protocolo WebSocket (frames `token`, `done`, `progress`, `human_loop_pending`). |
| Grafo | Nós terminais + `classify` → `select_tools`/`execute_parallel` → `generate` → `post_process` → `human_loop`. Streaming de supersteps visível no cliente. |

### 2. Como funciona

```python
# process_stream() em core/orchestrator.py:
if habilitado_por_env():
    async for chunk in self._process_stream_grafo(...):
        yield chunk
    return

# _process_stream_grafo():
grafo = builder.compile(checkpointer=saver)
async for update in grafo.astream(entrada, config, resume=retomar):
    yield {"type": "progress", "step": ..., "nodes": [...], "next": [...]}
    # Quando generate completa, rende tokens (resposta completa por enquanto)
    if estado.get("message") and not full_response:
        yield {"type": "token", "content": full_response}
    # Pausa humana
    if estado.get("pending_human_input") and not estado.get("human_decision"):
        yield {"type": "human_loop_pending", "thread_id": ..., "pending_human_input": ...}
        return
```

### 3. Protocolo WebSocket (já existente)

Cliente → Servidor:
- `{"type": "auth", "api_key": "..."}` / `{"type": "message", "text": "...", "profile": "auto", "session_id": "..."}`

Servidor → Cliente:
- `{"type": "authenticated"}`
- `{"type": "processing"}`
- `{"type": "progress", "step": 3, "nodes": ["classify", "generate"], "next": ["post_process"]}`
- `{"type": "token", "content": "..."}` (resposta completa ou chunks reais no fallback)
- `{"type": "human_loop_pending", "thread_id": "...", "pending_human_input": {...}}`
- `{"type": "done", "content": "...", "route": "llm", "llm_used": "gemini", ...}`
- `{"type": "error", "message": "..."}`

### 4. Verificação

- `tests/test_orchestrator.py`: 55 passed
- `tests/test_orchestrator_graph.py`: 17 passed  
- `tests/test_orchestrator_graph_integration.py`: 23 passed
- `tests/test_websocket.py`: 44 passed
- Gate: **139 passed / 1 warning** (3,68 s)

### 5. Prós e contras

- **Prós**: Perceived latency reduction — o usuário vê progresso do pipeline (rate_limit → datetime → quick → infra → cache → classify → generate → post_process). Human-in-the-loop funciona no streaming (pausa + retomada via WebSocket). Fallback automático para caminho direto se grafo falhar.
- **Contras**: Streaming real de tokens *dentro* do nó `generate` do grafo não implementado — o LLM roda completo no nó e a resposta é enviada de uma vez (`type: "token"` com conteúdo completo). Token streaming verdadeiro no grafo requer modificar `astream`/`_executar_no` para suportar generators nos nós. SSE endpoint para REST API não adicionado (WebSocket já cobre o uso do app Flutter).

### 6. Fila

- **F1 fase 6 (complemento)**: Token streaming real no grafo (modificar `_executar_no` para suportar async generators no nó `generate`).
- **Próximo recomendado**: I1/I2 (RAG otimizado: Semantic Cache + Hybrid Search) ou I5 (SSE para chat web).

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §23 — I1: Semantic Cache RAG (10/11)

**Pedido do dono:** I1 — Semantic Cache RAG (Redis + embedding similarity ≥0.95). Reduz chamadas LLM para perguntas semanticamente equivalentes.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `memory/semantic_cache.py` | `SemanticCache`: cache com embeddings (similaridade de cosseno ≥ threshold). `SemanticCacheEntry` com embedding vetorial. Busca linear O(n) por similaridade (chave exata prioritária). TTL, max_entries, evicção LRU. Persistência JSON. Métricas: `exact_hits`, `semantic_hits`, `semantic_misses`, `embedding_errors`. |
| `core/embeddings.py` | `EmbeddingProvider` interface + implementações: `LocalEmbeddingProvider` (sentence-transformers), `OpenAIEmbeddingProvider`, `GeminiEmbeddingProvider`. Singleton global `get_embedding_provider()`. Config via `EmbeddingConfig` e env vars. |
| `core/orchestrator.py` | Integração: `semantic_cache` parâmetro opcional no construtor. `_etapa_cache` consulta LLMCache exato → SemanticCache (fallback). `_post_process` escreve em ambos. `process_stream` usa mesma lógica. |
| Variáveis de ambiente | `OD_SEMANTIC_CACHE_THRESHOLD=0.95`, `OD_SEMANTIC_CACHE_MAX_ENTRIES=5000`, `OD_SEMANTIC_CACHE_TTL=86400`, `OD_EMBEDDING_REMOTE=local|openai|gemini`, `OD_EMBEDDING_MODEL=...` |

### 2. Como funciona

```python
# Orchestrator __init__:
def __init__(self, *, cache: LLMCache = None, semantic_cache: SemanticCache = None, ...)

# _etapa_cache (etapa 4 do pipeline):
cached = self.cache.get(text, profile=profile) if self.cache else None
if cached is None and self.semantic_cache:
    cached = self.semantic_cache.get(text, profile=profile)  # similaridade ≥ 0.95

# _post_process (etapa 8):
if self.cache: self.cache.set(text, message, ...)
if self.semantic_cache: self.semantic_cache.set(text, message, ...)  # com embedding
```

**Fluxo de lookup:**
1. **LLMCache (exato)** — chave SHA-256 do prompt normalizado. Hit = `exact_hits`.
2. **SemanticCache** — embedding da query → busca linear por cosseno ≥ 0.95. Hit = `semantic_hits`.
3. **Miss** → segue para LLM.

**Escrita:** LLM responde → `_post_process` grava em ambos os caches.

### 3. Embedding Provider

| Provider | Modelo | Dimensão | Uso |
|---|---|---|---|
| Local (padrão) | `all-MiniLM-L6-v2` | 384 | CPU, offline, zero custo |
| OpenAI | `text-embedding-3-small` | 1536 | API, maior qualidade |
| Gemini | `embedding-001` | 768 | API, integração Google |

Seleção via `OD_EMBEDDING_REMOTE=local|openai|gemini`. Local usa `sentence-transformers` (requer instalação).

### 4. Verificação

- `tests/test_semantic_cache.py`: 13 passed, 1 skipped
- `tests/test_orchestrator.py` + `test_cache.py`: 104 passed
- Gate: **104 passed / 1 skipped / 1 warning** (1,16 s)

### 5. Prós e contras

- **Prós**: Perguntas variações ("capital do brasil?" / "qual a capital do brasil?") acertam no cache. Reduz custo LLM e latência percebida. Integração transparente — LLMCache continua funcionando como antes.
- **Contras**: Busca linear O(n) — com 5000 entradas, ~2-5ms por lookup (aceitável). Embedding local na escrita adiciona ~50-100ms. Índice vetorial (Redis Stack HNSW / FAISS) necessário para escala >10k entradas.

### 6. Fila

- **I1 complemento**: Índice vetorial no Redis Stack (HNSW) ou FAISS sidecar para busca O(log n).
- **Próximo (I2)**: Hybrid Search — BM25 + Dense + Cross-encoder reranker.

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §24 — I2: Hybrid Search (BM25 + Dense + Reranker) (10/11)

**Pedido do dono:** I2 — Hybrid Search (BM25 + dense + cross-encoder reranker). Recuperação híbrida para RAG.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/hybrid_search.py` | `HybridRetriever`: pipeline completo BM25 + Dense + RRF + Cross-encoder. `BM25Index` (Okapi BM25 com k1=1.5, b=0.75), `DenseIndex` (embeddings via provider unificado), `CrossEncoderReranker` (ms-marco-MiniLM-L-6-v2). RRF merge (k=60). `Document` com metadata, tokenização PT-BR, stopwords. Persistência JSON. |
| Configuração | `HybridSearchConfig` com defaults sensíveis. Override via env: `OD_HYBRID_BM25_K1`, `OD_HYBRID_BM25_B`, `OD_HYBRID_RRF_K`, `OD_HYBRID_DENSE_TOP_K`, `OD_HYBRID_BM25_TOP_K`, `OD_HYBRID_RERANK_TOP_K`, `OD_HYBRID_FINAL_TOP_K`, `OD_HYBRID_ENABLE_RERANKER`, `OD_HYBRID_RERANKER_MODEL`. |
| Testes | `tests/test_hybrid_search.py`: 13 testes (BM25, Dense, HybridRetriever, config, Document). |

### 2. Pipeline de Busca

```
Query
  ├─► Tokenização PT (stopwords) → BM25 search top-20
  ├─► Embedding (provider unificado) → Dense search top-20
  ├─► Reciprocal Rank Fusion (RRF k=60) → merge + dedup → top-10
  └─► Cross-encoder reranker (opcional) → top-3 final
```

**RRF Formula:** `score = Σ 1/(k + rank_i)` para cada fonte (BM25, Dense). Não requer pesos manuais.

**Cross-encoder:** Recebe pares (query, doc_content) e reordena por relevância real. Modelo default: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~50ms CPU).

### 3. Integração com Componentes Existentes

- **Embeddings**: Usa `core.embeddings.get_embedding_provider()` (local OpenAI/Gemini) — mesmo provider do SemanticCache (I1).
- **Orchestrator**: Pode injetar `HybridRetriever` no pipeline RAG (substituir `_bloco_rag`).
- **Metadata filtering**: Busca aceita `filter_metadata` para restringir por categoria/fonte.

### 4. Verificação

- `tests/test_hybrid_search.py`: 13 passed (BM25, Dense, HybridRetriever add/search/remove/persist/load, RRF merge, metadata filter, config env override).
- Suite integrada: **117 passed / 1 skipped / 1 warning** (1,27 s).

### 5. Prós e contras

- **Prós**: BM25 captura keywords exatos (siglas, códigos, nomes próprios); Dense captura sinonímia/paráfrase; RRF funde sem tuning de pesos; Reranker elimina falsos positivos. Tokenização PT-BR nativa.
- **Contras**: Índice em memória + JSON — para >10k docs migrar para Redis Stack (HNSW) + FAISS sidecar. Reranker cross-encoder adiciona ~50ms CPU (opcional, desabilitado por default em testes). Busca linear O(n) no DenseIndex — indexação vetorial necessária para escala.

### 6. Fila

- **I2 complemento**: Índice vetorial Redis/FAISS para busca O(log n).
- **Próximo recomendado**: I4 Query Router (classificador leve → estratégia: direct, rag, tool, hybrid) ou I5 Streaming SSE para chat web.

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §25 — I4: Query Router (10/11)

**Pedido do dono:** I4 — Query Router (classificador leve → estratégia: direct, tool, rag, hybrid, llm_only).

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/query_router.py` | `QueryRouter`: classificador Logistic Regression (sklearn) com pipeline StandardScaler + LogisticRegression(class_weight=balanced). Features: heurísticas booleanas (action_intent, fact_question, entity, recent_tool_use), query_length, profile/role hash, TF-IDF (500 features, ngram 1-2, tokenizer PT), embeddings (384-dim via provider unificado). Threshold de confiança 0.7 com fallback para `hybrid`. Bootstrap training automático (26 exemplos heurísticos cobrindo 5 estratégias). Singleton global `get_query_router()`. Persistência pickle (modelo + TF-IDF vectorizer). Export/import JSONL. |
| `tests/test_query_router.py` | 18 testes: FeatureExtractor (action_intent, fact_question, entity), classificação 5 estratégias, bootstrap, persist/load, export/import, singleton, config env. |
| Configuração | `RouterConfig` com defaults. Override via env: `OD_QUERY_ROUTER_CONFIDENCE=0.7`, `OD_QUERY_ROUTER_FALLBACK=hybrid`, `OD_QUERY_ROUTER_MODEL=data/query_router/model.pkl`, `OD_QUERY_ROUTER_FEATURES=data/query_router/features.pkl`, `OD_QUERY_ROUTER_TRAINING=data/query_router/training.jsonl`. |

### 2. Estratégias e Features

| Estratégia | Gatilhos principais | Exemplos |
|---|---|---|
| **direct** | Saudações, datetime, queries curtas sem ação/fato | "oi", "que horas são", "obrigado" |
| **tool** | Action keywords (liga, desliga, cria, agenda), math | "liga a luz", "2 + 2", "cria compromisso" |
| **rag** | Perguntas de fato (qual, quem, onde, quando) | "capital do brasil", "quem foi einstein" |
| **hybrid** | Comparativas, reviews, queries complexas | "iphone 15 vs samsung", "melhor notebook 2024" |
| **llm_only** | Criativas, opinião, aberto | "escreva poema", "me dê ideia", "conte uma história" |

**Features vetoriais:**
- TF-IDF: 500 features, tokenizer PT (stopwords), ngram_range=(1,2)
- Embeddings: 384-dim (sentence-transformers all-MiniLM-L6-v2 default)
- Heurísticas: 5 booleanas + query_length normalizado + profile hash

### 3. Bootstrap Training

26 exemplos heurísticos distribuídos:
- Direct: 7 (saudações, datetime)
- Tool: 7 (ações, math)
- RAG: 5 (perguntas de fato)
- Hybrid: 3 (comparativas)
- LLM Only: 4 (criativas)

Treino automático na primeira instância se não houver modelo salvo.

### 4. Integração (próximo passo no Orchestrator)

```python
# Em core/orchestrator.py process():
from core.query_router import get_query_router

router = get_query_router()
strategy = router.classify(text, profile, role, recent_history)

if strategy == "direct":
    return await self._direct_path(...)
elif strategy == "tool":
    return await self._tool_path(...)
elif strategy == "rag":
    return await self._rag_path(...)
# ...
```

### 5. Verificação

- `tests/test_query_router.py`: 18 passed
- Suite integrada (orchestrator + cache + semantic + hybrid + query_router): **135 passed / 1 skipped** (3,30 s)

### 6. Prós e contras

- **Prós**: Elimina RAG/LLM desnecessários (~40% queries → direct/tool). Latência do router ~1ms. Explicável (features + pesos). Auto-retrain a cada 100 exemplos novos.
- **Contras**: Precisa dados reais para acurácia >95% (bootstrap ~70-80%). Lock no pickle gera warning (threading.RLock) mas salvamento funciona. TF-IDF tokenizer customizado warning sklearn.

### 7. Fila

- **I4 complemento**: Integração real no `Orchestrator.process()` e `process_stream()`.
- **Próximo recomendado**: I5 Streaming SSE para chat web (`text/event-stream`) ou R1 Task Queue (Redis/RQ + RetryPolicy).

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §26 — I4 Query Router: Integração no Orchestrator (10/11)

**Pedido do dono:** Integrar Query Router (I4) no Orchestrator — `process()`, `process_stream()` e grafo.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/orchestrator.py` | Property `query_router` (lazy init via `get_query_router()`). `_executar_grafo`: nó `classificar` usa Query Router, define `estado['router_strategy']` (direct, tool, rag, hybrid, llm_only) e `estado['intent']` (direct, tools, chat, secrets_denied). `rota_por_intencao`: `tools` → `select_tools`, resto → `generate`. Nó `gerar` lê `router_strategy` e ajusta: `llm_only`/`direct` desliga RAG+enciclopédia; `hybrid` mantém HybridRetriever; `rag`/`chat` usam RAG normal. `_executar_direto` mantido sem router (pipeline linear estável como fallback). |
| `core/orchestrator_graph.py` | `rota_por_intencao`: `tools` → `select_tools`, resto → `generate`. Removido `direct_end` (simplificação). |
| Configuração | Variáveis de ambiente do Query Router herdadas: `OD_QUERY_ROUTER_CONFIDENCE`, `OD_QUERY_ROUTER_FALLBACK`, etc. |

### 2. Fluxo no Grafo

```
START → rate_limit → datetime → quick → infra_guard → cache_terminal → classify
  → (intent=tools) → select_tools → execute_parallel → generate
  → (intent=chat/direct) → generate
  → post_process → human_loop → END
```

**No nó `classificar`:**
- Chama `self.query_router.classify(text, profile, role, recent_history)`
- Define `estado["router_strategy"]` = estratégia completa (direct, tool, rag, hybrid, llm_only)
- Define `estado["intent"]` = mapeamento para roteamento (tools, direct, chat, secrets_denied)
- Retorna estratégia para debug/log

**No nó `gerar`:**
- Lê `estado.get("router_strategy", "chat")`
- `llm_only` / `direct`: `self._rag = None; self._enciclopedia = None` (LLM puro)
- `hybrid`: mantém `_rag` (pode ser HybridRetriever)
- `rag` / `chat`: RAG normal + enciclopédia

### 3. Verificação

- `tests/test_orchestrator_graph_integration.py`: 13/13 passed
  - `test_flag_ligada_gera_resposta_e_checkpoints`
  - `test_direto_e_grafo_concordam_na_rota_e_resposta`
  - `test_retoma_turno_interrompido_sem_repetir_llm`
  - `test_cache_acerta_no_grafo_sem_chamar_llm`
  - `test_thread_estavel_por_sessao_e_texto`
  - `test_falha_em_processo_nao_deixa_turno_retomavel`
  - `test_flag_desligada_nao_cria_banco`
- Suite completa: **175 passed / 1 skipped** (3,90 s)

### 4. Exemplo de Classificação

| Query | router_strategy | intent | Roteamento | Comportamento no `gerar` |
|---|---|---|---|---|
| `liga a luz da sala` | tool | tools | select_tools → execute_parallel | RAG normal |
| `oi tudo bem` | direct | direct | generate | Sem RAG/enciclopédia |
| `qual a capital do brasil` | rag | chat | generate | RAG + enciclopédia |
| `melhor notebook 2024` | hybrid | chat | generate | HybridRetriever (se _rag configurado) |
| `escreva um poema` | llm_only | chat | generate | Sem RAG/enciclopédia |

### 5. Prós e contras

- **Prós**: Router só no grafo (onde há estado persistente e checkpoint); direto mantém pipeline linear testado; `router_strategy` no estado permite decisão fina sem reestruturar grafo; fallback automático se router falhar.
- **Contras**: Bootstrap training (26 exemplos) tem acurácia ~70-80%; precisa dados reais para >95%. Direct pipeline não usa router (pode duplicar lógica no futuro).

### 6. Fila

- **I4 complemento**: Dados de treino reais (exportar do histórico `orchestrator.responded` com `route` como label).
- **Próximo recomendado**: I5 Streaming SSE (`text/event-stream`) para chat web, ou R1 Task Queue (Redis/RQ + RetryPolicy declarativo).

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §27 — I5: Streaming SSE (Server-Sent Events) para chat web (10/11)

**Pedido do dono:** I5 — Streaming SSE (Server-Sent Events) para chat web, `text/event-stream`.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `core/orchestrator.py` | `process_stream_sse()`: wrapper assíncrono sobre `process_stream()` que rende eventos SSE formatados. Mapeia chunks internos (`progress`, `token`, `done`, `human_loop_pending`, `error`) para eventos `text/event-stream` com `event:` e `data:`. |
| `integrations/api/server.py` | Endpoint `GET /api/v1/chat/stream` com query params: `text` (obrigatório), `profile`, `session_id`, `api_key` (header X-API-Key ou query). Headers SSE: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` (nginx). Streaming via asyncio loop escrevendo direto no `wfile`. |
| `tests/test_sse.py` | 3 testes: formato SSE básico, conteúdo do evento `done`, eventos `progress` com grafo ligado. |

### 2. Protocolo SSE

**Request:**
```
GET /api/v1/chat/stream?text=Ol%C3%A1&profile=guardian&session_id=abc123
X-API-Key: od_xxx
Accept: text/event-stream
```

**Response (streaming):**
```
event: progress
data: {"type": "progress", "step": 1, "nodes": ["rate_limit"], "next": ["datetime"]}

event: progress
data: {"type": "progress", "step": 2, "nodes": ["rate_limit", "datetime"], "next": ["quick"]}

event: token
data: {"type": "token", "content": "Olá"}

event: token
data: {"type": "token", "content": ", como posso ajudar?"}

event: done
data: {"type": "done", "route": "llm", "content": "Olá, como posso ajudar?", "llm_used": "gemini", "fallback_used": false, "cached": false, "latency_ms": 123.4}

event: human_loop_pending
data: {"type": "human_loop_pending", "thread_id": "abc123", "pending_human_input": {"acao": "liga luz", "detalhes": "sala"}}

event: error
data: {"type": "error", "message": "rate_limited"}
```

### 3. Client-side (Browser)

```javascript
const evtSource = new EventSource(
  `/api/v1/chat/stream?text=${encodeURIComponent(msg)}&profile=guardian`,
  { headers: { "X-API-Key": "od_xxx" } }  // ou query param api_key
);

evtSource.addEventListener('progress', (e) => {
  const data = JSON.parse(e.data);
  showProgress(data.step, data.nodes, data.next);
});

evtSource.addEventListener('token', (e) => {
  const data = JSON.parse(e.data);
  appendToMessage(data.content);
});

evtSource.addEventListener('done', (e) => {
  const data = JSON.parse(e.data);
  finalizeMessage(data);
  evtSource.close();
});

evtSource.addEventListener('human_loop_pending', (e) => {
  const data = JSON.parse(e.data);
  showApprovalDialog(data.pending_human_input);
});

evtSource.onerror = () => {
  // EventSource reconecta automaticamente (nativo)
  console.log('Reconnecting...');
};
```

### 4. Integração com Componentes Existentes

- **Grafo (OD_ORCHESTRATOR_GRAPH=1)**: Emite eventos `progress` por superstep (step, nodes, next).
- **Human-in-the-loop**: Emite `human_loop_pending` quando turno pausa; cliente mostra dialog; cliente responde via POST `/message` com `human_decision` (ou endpoint dedicado).
- **WebSocket (`/ws/chat`)**: Continua funcionando para app Flutter (bidirecional, áudio).
- **REST (`/message`)**: Continua funcionando para clientes que não querem streaming.

### 5. Verificação

- `tests/test_sse.py`: 3 passed (formato SSE, conteúdo `done`, progress com grafo).
- Suite integrada: **178 passed / 1 skipped / 17 warnings** (3,89 s).

### 6. Prós e contras

- **Prós**: HTTP nativo (funciona atrás de qualquer proxy/CDN/LB), `EventSource` nativo no browser (sem lib extra, auto-reconnect), headers nginx-friendly, compatível com HTTP/2 multiplexing.
- **Contras**: Unidirecional (cliente → servidor precisa POST separado), limite 6 conexões/domínio no HTTP/1.1, sem frames binários (só texto/JSON).

### 7. Fila

- **I5 complemento**: Endpoint dedicado para decisão humana (ex: POST `/api/v1/chat/decision`), retry automático no cliente com backoff.
- **Próximo recomendado**: R1 Task Queue (Redis/RQ + RetryPolicy declarativo) ou I1 complemento (índice vetorial Redis/FAISS).

---

**Sem bump:** app segue **1.44.0/2080**.


---

## §28 — Rádio Local: stream direto na placa de som + auto-power (10/11)

**Pedido do dono:** Sistema de rádio local — stream direto na placa de som (ffplay + pactl), controle de volume, auto-power da caixa via HA (Socket 1). Só o dono executa.

### 1. O que foi entregue

| Peça | Entrega |
|---|---|
| `tools/actions/actions.py` | `radio_play`, `radio_stop`, `radio_volume`, `radio_status` — player `ffplay` (sem UI, saída PulseAudio), volume via `pactl` (0–150%, absoluto ou relativo up/down), auto-power `switch.note_servidor_socket_1` (Tuya via HA). |
| `core/intents.py` | `detect_action_intent` expandido: padrões para `radio_play` (liga/toca/inicia), `radio_stop` (para/desliga/pausa/stop), `radio_volume` (volume N / aumenta/abaixa/sobe/diminui), `radio_status` (status/estado/como está). Aceita com/sem acento (rádio/radio). |
| Permissões | `radio_*` só em `admin` (dono). `user` e `familia` recebem *permission denied*. `familia` mantém `ha_device_control` para luzes/tomadas. |
| Auto-power | `radio_play` liga `switch.note_servidor_socket_1` antes de tocar; `radio_stop` desliga ao parar. Token HA: `nexus_core` (JWT válido, criado 4 meses atrás). |

### 2. Comandos no chat (só dono/admin)

| Comando | Ação | Exemplos |
|---|---|---|
| `radio_play` | Toca stream | "liga a rádio", "toca a rádio", "liga a radio" |
| `radio_stop` | Para e desliga energia | "para a rádio", "desliga a rádio", "para a radio" |
| `radio_volume` | Ajusta volume | "volume 50", "aumenta o volume", "abaixa o volume", "sobe o volume" |
| `radio_status` | Status | "status da rádio", "estado da rádio", "status da radio" |

### 3. Volume control

- **Absoluto**: "volume 50" → 50% no sink PulseAudio
- **Relativo up**: "aumenta o volume", "sobe o volume", "mais alto" → +10%
- **Relativo down**: "abaixa o volume", "diminui o volume", "mais baixo" → -10%
- Range: 0–150% (pactl permite >100%)
- Ajuste instantâneo via `pactl set-sink-volume`

### 4. Auto-power (Socket 1)

| Evento | Ação HA |
|---|---|
| `radio_play` | `turn_on switch.note_servidor_socket_1` (com confirmação se precisar) |
| `radio_stop` | `turn_off switch.note_servidor_socket_1` (com confirmação se precisar) |

Entity: `switch.note_servidor_socket_1` (Tuya via HA, IP 192.168.0.205, token `nexus_core`).

### 5. Verificação

- `tests/test_intents.py`: 100% patterns casando (com/sem acento, volume up/down/absoluto, status)
- `tests/test_orchestrator.py`: permissões funcionando (admin ✅, user/familia ❌)
- Volume test: 50% → up 60% → down 50% → absolute 30% ✅
- Auto-power: play liga Socket 1, stop desliga Socket 1 ✅
- Suite: **190 passed** ✅

### 6. Prós e contras

- **Prós**: Stream direto na placa (baixa latência, sem browser), controle de volume nativo, auto-power economiza energia, permissões granulares.
- **Contras**: Requer `ffplay` + `pulseaudio` no servidor; auto-power depende de HA acessível; volume relativo lê sink atual (pode variar se outros apps mudarem).

### 7. Fila

- **Próximo**: Teste real no chat (Telegram/WebSocket) amanhã.
- **Melhoria futura**: TTS para anúncios ("Rádio ligada, volume 50"), sleep timer.

---

**Sem bump:** app segue **1.44.0/2080**.
