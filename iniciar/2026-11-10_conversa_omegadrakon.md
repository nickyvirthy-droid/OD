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
