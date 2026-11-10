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

### 7. Fila

- Análise/TODO de 10/11: execução devagar; próximo recomendado é **F2
  (OpenTelemetry)** — menor risco e maior visibilidade.
- **A5** (senha Wi-Fi) segue adiado pelo dono; **C3/C4** adiados.
- Sem bump em nenhuma destas entregas: app segue **1.44.0/2080**.
