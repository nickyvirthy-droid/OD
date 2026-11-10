# Telemetria (F2) — traces, métricas e correlação de log

> Estado: implementado em 2026-11-10 (F2 do roadmap de `docs/ANALISE_SISTEMA_TODO.md`).
> Código: `core/telemetry.py`. Testes: `tests/test_telemetry.py`.

## Princípio

A telemetria é **opcional e de import tardio**, como as outras dependências do
projeto: sem `opentelemetry-sdk` o `od-core` sobe normal, todas as funções
públicas viram no-op e o `/health` mostra o check `telemetria` degradado (não
crítico). Nada no caminho crítico quebra.

Sem `OD_OTEL_ENDPOINT`, spans e métricas continuam disponíveis em processo
(inclusive para o log correlacionar), mas nada é enviado pela rede.

## Variáveis de ambiente

| Variável | Padrão | Efeito |
|---|---|---|
| `OD_TELEMETRY_ENABLED` | `1` | `0` desliga tudo (no-op puro). |
| `OD_OTEL_ENDPOINT` | vazio | Base do OTLP/HTTP (ex.: `http://127.0.0.1:4318`). Vazio = sem exportador. |
| `OD_OTEL_SERVICE` | `omega-drakon` | `service.name` do Resource. |
| `OD_OTEL_SAMPLE_RATIO` | `0.1` | Amostragem head-based (0..1); `1` = tudo. |
| `OD_TELEMETRY_CONSOLE` | `0` | `1` = exportador de console (dev, sem coletor). |
| `OD_OTEL_HEADERS` | vazio | Headers extras do OTLP, formato `chave=valor,chave2=valor`. |
| `OD_ENVIRONMENT` | `production` | `deployment.environment` do Resource. |

As URLs são normalizadas: `http://host:4318` vira `/v1/traces` e
`/v1/metrics`; uma URL já completa é respeitada.

## O que é medido

| Sinal | Nome | Onde |
|---|---|---|
| Span | `http.request` (atributos `od.metodo`, `od.rota`, `http.status_code`) | `integrations/api/server.py` (`APIHandler._handle`) |
| Histograma | `od.http_request.seconds` (atributo `od.metodo`) | idem |
| Contador | `od.http_requests` | idem |
| Span | `rag.consult` (papel, fato, candidatos, trechos, descartados, reescrita) | `memory/rag.py` (`RAGPipeline.consult`) |
| Histograma | `od.rag_retrieval.seconds` (atributo `od.papel`) | idem |

Qualquer módulo novo pode usar sem dependência direta:

```python
from core import telemetry

with telemetry.span("downloads.job", job="abc"):
    with telemetry.cronometrar("download_job", prioridade="alta"):
        ...
telemetry.contar("downloads_concluidos", 1)
telemetry.atribuir("bytes", 1234)      # anexa ao span ativo
```

## Correlação log ↔ trace

`core/logger.py` consulta `telemetry.trace_id()`/`span_id()` a cada registro.
Com um span ativo, a linha (texto ou JSON) ganha `trace_id` e `span_id`; um
`trace_id` passado explicitamente no contexto da chamada é preservado. Fora de
span, nenhum campo é inventado.

## Operação

- `telemetry.configurar()` roda no início de `runtime/launcher.py::main()` e é
  **idempotente**.
- `telemetry.status()` alimenta o check `telemetria` do `/health`
  (`runtime/launcher.py::build_health`) e pode ser exposto em rotas novas.
- `telemetry.desligar()` força o flush (`provider.shutdown()`) — chamado nos
  testes; o processo em si encerra com os providers vivos.
- Os providers ficam no estado do módulo, **não** nos globais do OpenTelemetry:
  `set_tracer_provider` aceita só a primeira chamada do processo, o que
  impediria reconfiguração em testes e hot-reload.

## Monitor de latência (F3)

A sonda `tools/monitor/io_probe.py` mede p50/p95 de endpoints do `od-core` de
fora do processo e grava `data/io_monitor.json` (atômico, com `ts`/`iso`).
O timer de usuário **`od-io-probe.timer`** roda o serviço a cada 5 minutos
(3 min após o boot) e faz duas passadas, que alimentam o mesmo arquivo:

| Alvo | Amostras | Por quê |
|---|---|---|
| `GET /site/` | 20 em série + 20 concorrentes (8 threads) | estático e isento do limiter — mede o custo do socket/servidor sem consumir orçamento |
| `GET /health` | 5 em série, 1,1 s de intervalo | mede a rota real da API; 5 req/5 min cabe no limiter de 30/min |

O check não-crítico **`latencia`** do `/health` (`runtime/launcher.py::check_latencia`)
lê esse arquivo e devolve `p50`, `p95`, número de alvos e idade em `detail`:

- arquivo ausente → `up` ("sonda ainda não rodou"): instalação nova não degrada
  antes do primeiro disparo;
- idade > `OD_IO_MONITOR_MAX_IDADE_S` (padrão **900**) → `degraded` (o timer
  parou);
- pior p95 > `OD_IO_MONITOR_P95_MS` (padrão **250**) → `degraded`, nomeando o alvo.

Operação: `systemctl --user list-timers od-io-probe.timer`,
`journalctl --user -u od-io-probe` e `cat data/io_monitor.json`. As units vivem
em `systemd/` (instaladas em `~/.config/systemd/user/`).

## O que ainda não existe (roadmap)

- OTel Collector/Grafana (Tempo + Loki + Prometheus) no host — a config do
  coletor e os dashboards são a Semana 1-2 do roadmap.
- Auto-instrumentação de `requests`/`asyncio` (instrumentors) — depende da
  migração assíncrona (F3).
- Métricas de cache hit rate e de sessões ativas (chegam com I1/F1).
