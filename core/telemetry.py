#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/telemetry.py
Descrição: OpenTelemetry + métricas com correlação de trace no log NICKY.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F2 (OTel completo: traces + metrics + logs
    correlacionados)
  - Protocolo NICKY de logs (core/logger.py)

Architecture:
    Fundação de observabilidade do núcleo. O princípio é o mesmo das outras
    dependências opcionais do projeto: a telemetria é OPCIONAL e de import
    tardio — sem `opentelemetry-sdk` instalado, o serviço sobe normal e todas
    as funções públicas viram no-op silencioso.

    O que existe aqui:
      - `configurar()`   — monta TracerProvider/MeterProvider uma única vez
                           (Resource com service.name/version, amostragem,
                           exportador OTLP/HTTP ou console para dev);
      - `span()`         — contexto de span com atributos; no-op sem OTel;
      - `cronometrar()`  — histograma `<nome>_seconds` com atributos;
      - `contar()`       — contador monotônico;
      - `trace_id()` / `span_id()` — hex do span ativo, para o log NICKY
                           correlacionar linha de log com trace;
      - `status()`       — estado para o painel (/health, /admin).

    O `core/logger.py` consulta `trace_id()`/`span_id()` a cada registro: com
    um span ativo, toda linha JSON carrega `trace_id` e `span_id`, e o mesmo
    trace aparece no Tempo/Grafana junto dos spans.

Usage:
    from core import telemetry

    telemetry.configurar()                    # idempotente; lê o ambiente
    with telemetry.span("rag.consult", papel="admin"):
        ...
    with telemetry.cronometrar("rag_retrieval", pergunta_len=42):
        ...
    telemetry.contar("http.requests", 1, metodo="GET")
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import Any, Iterator

__signature__ = "OD // CORE"

# ---------------------------------------------------------------------------
# Configuração (ambiente)
# ---------------------------------------------------------------------------

ENV_LIGADO = "OD_TELEMETRY_ENABLED"
ENV_ENDPOINT = "OD_OTEL_ENDPOINT"
ENV_SERVICO = "OD_OTEL_SERVICE"
ENV_AMOSTRA = "OD_OTEL_SAMPLE_RATIO"
ENV_CONSOLE = "OD_TELEMETRY_CONSOLE"
ENV_CABECALHOS = "OD_OTEL_HEADERS"

SERVICO_PADRAO = "omega-drakon"
RATIO_PADRAO = 0.1

_LOG = logging.getLogger("omega.core.telemetry")

_estado_lock = threading.RLock()
_configurado = False
_ligado = False
_endpoint = ""
_servico = SERVICO_PADRAO
_versao = ""
_tracer: Any = None
_meter: Any = None
_provider_trace: Any = None
_provider_metrica: Any = None
_amostra = RATIO_PADRAO
_erro = ""
_contadores: dict[tuple[str, tuple[tuple[str, Any], ...]], Any] = {}
_histogramas: dict[tuple[str, tuple[tuple[str, Any], ...]], Any] = {}


# ---------------------------------------------------------------------------
# Disponibilidade e versão
# ---------------------------------------------------------------------------

def otel_disponivel() -> bool:
    """True quando o SDK do OpenTelemetry está importável."""
    try:  # pragma: no cover - depende do ambiente
        import opentelemetry.sdk.trace  # noqa: F401
        import opentelemetry.sdk.metrics  # noqa: F401
    except Exception:
        return False
    return True


def _versao_do_sistema() -> str:
    """Versão do sistema (OD_VERSION) sem criar ciclo de import."""
    try:
        from core.capabilities import OD_VERSION

        return str(OD_VERSION)
    except Exception:
        return "0.0.0"


def _bool_env(nome: str, padrao: bool) -> bool:
    valor = os.environ.get(nome)
    if valor is None or valor == "":
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


def _ratio_env(nome: str, padrao: float) -> float:
    valor = os.environ.get(nome)
    if not valor:
        return padrao
    try:
        ratio = float(valor)
    except ValueError:
        return padrao
    return min(1.0, max(0.0, ratio))


def _headers_env() -> dict[str, str]:
    """Cabeçalhos extras do exportador OTLP (formato `chave=valor,chave2=`)."""
    bruto = os.environ.get(ENV_CABECALHOS, "")
    headers: dict[str, str] = {}
    for par in bruto.split(","):
        if "=" not in par:
            continue
        chave, valor = par.split("=", 1)
        chave = chave.strip()
        if chave:
            headers[chave] = valor.strip()
    return headers


# ---------------------------------------------------------------------------
# Configuração do provider
# ---------------------------------------------------------------------------

def configurar(
    *,
    servico: str | None = None,
    endpoint: str | None = None,
    versao: str | None = None,
    ratio: float | None = None,
    console: bool | None = None,
    forcar: bool = False,
    exportador_span: Any = None,
    leitor_metrica: Any = None,
) -> bool:
    """Configura traces e métricas (uma vez por processo).

    Lê, nesta ordem: argumentos → variáveis de ambiente → padrões.
    `OD_TELEMETRY_ENABLED=0` desliga tudo; sem endpoint e sem console nada
    é exportado (spans continuam disponíveis para o log correlacionar, mas
    não geram rede). Devolve True quando o SDK foi configurado.

    `exportador_span`/`leitor_metrica` são ganchos de teste (exportador em
    memória); em produção o destino vem do endpoint/console.

    Idempotente: chamadas seguintes devolvem o estado atual, a menos que
    `forcar=True` (usado nos testes).
    """
    global _configurado, _ligado, _endpoint, _servico, _versao
    global _tracer, _meter, _amostra, _erro, _provider_trace, _provider_metrica

    with _estado_lock:
        if _configurado and not forcar:
            return _ligado

        _configurado = True
        _erro = ""

        ligado_env = _bool_env(ENV_LIGADO, True)
        _endpoint = (endpoint or os.environ.get(ENV_ENDPOINT, "")).strip()
        _servico = servico or os.environ.get(ENV_SERVICO, SERVICO_PADRAO)
        _versao = versao or _versao_do_sistema()
        _amostra = ratio if ratio is not None else _ratio_env(ENV_AMOSTRA, RATIO_PADRAO)
        usar_console = (
            console
            if console is not None
            else _bool_env(ENV_CONSOLE, False)
        )

        if not ligado_env:
            _ligado = False
            _tracer = None
            _meter = None
            return False

        if not otel_disponivel():
            _ligado = False
            _erro = "opentelemetry-sdk ausente"
            _LOG.info("Telemetria dormente: opentelemetry-sdk não instalado")
            return False

        try:
            (
                _tracer,
                _meter,
                _provider_trace,
                _provider_metrica,
            ) = _montar_providers(
                servico=_servico,
                versao=_versao,
                endpoint=_endpoint,
                ratio=_amostra,
                console=usar_console,
                exportador_span=exportador_span,
                leitor_metrica=leitor_metrica,
            )
        except Exception as exc:  # dependência presente mas quebrada
            _ligado = False
            _tracer = None
            _meter = None
            _provider_trace = None
            _provider_metrica = None
            _erro = f"{type(exc).__name__}: {exc}"
            _LOG.warning("Telemetria indisponível: %s", _erro)
            return False

        _ligado = True
        destino = _endpoint or ("console" if usar_console else "sem exportador")
        _LOG.info(
            "Telemetria ativa | servico=%s versao=%s destino=%s amostra=%s",
            _servico, _versao, destino, _amostra,
        )
        return True


def _montar_providers(
    *,
    servico: str,
    versao: str,
    endpoint: str,
    ratio: float,
    console: bool,
    exportador_span: Any = None,
    leitor_metrica: Any = None,
) -> tuple[Any, Any, Any, Any]:
    """Monta TracerProvider e MeterProvider (imports tardios).

    Os providers ficam no estado do módulo em vez de irem para os globais do
    OpenTelemetry: `set_tracer_provider` só aceita a primeira chamada do
    processo, o que tornaria a configuração irrepetível (testes, reload).
    """
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    resource = Resource.create(
        {
            "service.name": servico,
            "service.version": versao,
            "deployment.environment": os.environ.get(
                "OD_ENVIRONMENT", "production"
            ),
        }
    )

    # --- traces -----------------------------------------------------------
    provider = TracerProvider(resource=resource, sampler=_sampler(ratio))
    if exportador_span is not None:
        provider.add_span_processor(SimpleSpanProcessor(exportador_span))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=_url_traces(endpoint), headers=_headers_env()
                )
            )
        )
    if console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    tracer = provider.get_tracer("omega.drakon")

    # --- métricas ---------------------------------------------------------
    if leitor_metrica is not None:
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[leitor_metrica]
        )
    elif endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )

        leitor = PeriodicExportingMetricReader(
            OTLPMetricExporter(
                endpoint=_url_metricas(endpoint), headers=_headers_env()
            )
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[leitor])
    elif console:
        leitor = PeriodicExportingMetricReader(ConsoleMetricExporter())
        meter_provider = MeterProvider(resource=resource, metric_readers=[leitor])
    else:
        meter_provider = MeterProvider(resource=resource)
    meter = meter_provider.get_meter("omega.drakon")
    return tracer, meter, provider, meter_provider


def _sampler(ratio: float) -> Any:
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )

    if ratio >= 1.0:
        return ALWAYS_ON
    if ratio <= 0.0:
        return TraceIdRatioBased(0.0)
    return ParentBased(TraceIdRatioBased(ratio))


def _url_traces(endpoint: str) -> str:
    """OTLP/HTTP espera /v1/traces; aceita base ou URL completa."""
    base = endpoint.rstrip("/")
    if base.endswith("/v1/traces"):
        return base
    return base + "/v1/traces"


def _url_metricas(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1/metrics"):
        return base
    return base + "/v1/metrics"


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

def _tracer_ativo() -> Any:
    return _tracer


def span_atual() -> Any:
    """Span ativo (ou None). Serve para anexar atributos depois do fato."""
    try:
        from opentelemetry import trace

        return trace.get_current_span()
    except Exception:
        return None


def atribuir(chave: str, valor: Any) -> None:
    """Anexa um atributo ao span ativo, se houver."""
    sp = span_atual()
    if sp is None or not sp.is_recording():
        return
    try:
        sp.set_attribute(chave, valor)
    except Exception:
        pass


@contextlib.contextmanager
def span(nome: str, **atributos: Any) -> Iterator[Any]:
    """Contexto de span. Devolve o span (ou None sem OTel)."""
    tracer = _tracer_ativo()
    if tracer is None:
        yield None
        return
    try:
        cm = tracer.start_as_current_span(nome)
    except Exception:
        yield None
        return
    with cm as sp:
        for chave, valor in atributos.items():
            if valor is None:
                continue
            try:
                sp.set_attribute(f"od.{chave}", valor)
            except Exception:
                pass
        yield sp


@contextlib.contextmanager
def cronometrar(nome: str, **atributos: Any) -> Iterator[None]:
    """Mede a duração e registra no histograma `<nome>_seconds`.

    A medição local é sempre feita (mesmo sem OTel) e devolvida em
    `ultima_duracao(nome)` — útil para /health e para testes.
    """
    inicio = time.perf_counter()
    try:
        yield
    finally:
        duracao = time.perf_counter() - inicio
        _registrar_histograma(nome, duracao, atributos)
        _guardar_ultima(nome, duracao)


_ultimas: dict[str, float] = {}


def _guardar_ultima(nome: str, duracao: float) -> None:
    with _estado_lock:
        _ultimas[nome] = duracao


def ultima_duracao(nome: str) -> float | None:
    with _estado_lock:
        return _ultimas.get(nome)


def _instrumento_histograma(nome: str, atributos: dict[str, Any]) -> Any:
    meter = _meter
    if meter is None:
        return None
    chave = (nome, tuple(sorted(atributos)))
    base = nome if nome.startswith("od.") else f"od.{nome}"
    with _estado_lock:
        hist = _histogramas.get(chave)
        if hist is None:
            hist = meter.create_histogram(
                f"{base}.seconds", unit="s", description=f"duração de {nome}"
            )
            _histogramas[chave] = hist
        return hist


def _registrar_histograma(nome: str, duracao: float, atributos: dict[str, Any]) -> None:
    hist = _instrumento_histograma(nome, atributos)
    if hist is None:
        return
    try:
        hist.record(duracao, {f"od.{k}": v for k, v in atributos.items() if v is not None})
    except Exception:
        pass


def contar(nome: str, valor: int | float = 1, **atributos: Any) -> None:
    """Incrementa o contador `od.<nome>` (no-op sem OTel)."""
    meter = _meter
    if meter is None:
        return
    chave = (nome, tuple(sorted(atributos)))
    base = nome if nome.startswith("od.") else f"od.{nome}"
    with _estado_lock:
        contador = _contadores.get(chave)
        if contador is None:
            contador = meter.create_counter(base, description=f"contador {nome}")
            _contadores[chave] = contador
    try:
        contador.add(valor, {f"od.{k}": v for k, v in atributos.items() if v is not None})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Correlação com o log NICKY
# ---------------------------------------------------------------------------

def trace_id() -> str:
    """trace_id do span ativo em hex ("" quando não há span)."""
    sp = span_atual()
    if sp is None:
        return ""
    try:
        ctx = sp.get_span_context()
        if not ctx.is_valid:
            return ""
        return format(ctx.trace_id, "032x")
    except Exception:
        return ""


def span_id() -> str:
    sp = span_atual()
    if sp is None:
        return ""
    try:
        ctx = sp.get_span_context()
        if not ctx.is_valid:
            return ""
        return format(ctx.span_id, "016x")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Ciclo de vida e status
# ---------------------------------------------------------------------------

def desligar() -> None:
    """Força o flush dos exportadores e desliga (idempotente)."""
    global _ligado, _configurado, _tracer, _meter
    global _provider_trace, _provider_metrica
    with _estado_lock:
        for provider in (_provider_trace, _provider_metrica):
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    pass
        _ligado = False
        _configurado = False
        _tracer = None
        _meter = None
        _provider_trace = None
        _provider_metrica = None
        _contadores.clear()
        _histogramas.clear()
        _ultimas.clear()


def status() -> dict[str, Any]:
    """Estado da telemetria para /health e /admin."""
    with _estado_lock:
        return {
            "ligado": _ligado,
            "configurado": _configurado,
            "sdk_disponivel": otel_disponivel(),
            "servico": _servico,
            "versao": _versao,
            "endpoint": _endpoint,
            "amostra": _amostra,
            "instrumentos": len(_contadores) + len(_histogramas),
            "erro": _erro,
        }


def resetar() -> None:
    """Volta ao estado inicial (para testes)."""
    global _configurado, _ligado, _endpoint, _servico, _versao
    global _tracer, _meter, _amostra, _erro, _provider_trace, _provider_metrica
    with _estado_lock:
        _configurado = False
        _ligado = False
        _endpoint = ""
        _servico = SERVICO_PADRAO
        _versao = ""
        _tracer = None
        _meter = None
        _provider_trace = None
        _provider_metrica = None
        _amostra = RATIO_PADRAO
        _erro = ""
        _contadores.clear()
        _histogramas.clear()
        _ultimas.clear()
