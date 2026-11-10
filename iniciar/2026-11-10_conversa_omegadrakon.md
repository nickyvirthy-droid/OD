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

### 5. Fila

- Análise/TODO de 10/11: execução devagar; próximo recomendado é **F2
  (OpenTelemetry)** — menor risco e maior visibilidade.
- **A5** (senha Wi-Fi) segue adiado pelo dono; **C3/C4** adiados.
- Sem bump em nenhuma destas entregas: app segue **1.44.0/2080**.
