#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_telemetry.py
Descrição: Testes do núcleo de telemetria (F2) — spans, métricas, correlação
           de trace no log NICKY e operação sem OpenTelemetry instalado.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import logging

import pytest

from core import telemetry
from core.logger import get_logger

pytest.importorskip("opentelemetry.sdk")


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    for var in (
        telemetry.ENV_LIGADO,
        telemetry.ENV_ENDPOINT,
        telemetry.ENV_SERVICO,
        telemetry.ENV_AMOSTRA,
        telemetry.ENV_CONSOLE,
        telemetry.ENV_CABECALHOS,
    ):
        monkeypatch.delenv(var, raising=False)
    telemetry.resetar()
    yield
    telemetry.desligar()


def _in_memory():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    return InMemorySpanExporter()


# ---------------------------------------------------------------------------
# Liga/desliga
# ---------------------------------------------------------------------------

class TestConfiguracao:
    def test_desligado_por_env_vira_noop(self, monkeypatch):
        monkeypatch.setenv(telemetry.ENV_LIGADO, "0")
        assert telemetry.configurar(forcar=True) is False
        assert telemetry.status()["ligado"] is False
        with telemetry.span("od.qualquer") as sp:
            assert sp is None
            assert telemetry.trace_id() == ""
            assert telemetry.span_id() == ""

    def test_configurar_e_idempotente(self):
        assert telemetry.configurar() is True
        primeiro = telemetry.status()
        assert telemetry.configurar() is True
        assert telemetry.status()["servico"] == primeiro["servico"]

    def test_status_tem_campos_de_observabilidade(self):
        telemetry.configurar(servico="od-teste", versao="9.9.9")
        s = telemetry.status()
        assert s["ligado"] is True
        assert s["sdk_disponivel"] is True
        assert s["servico"] == "od-teste"
        assert s["versao"] == "9.9.9"
        assert s["erro"] == ""

    def test_urls_otlp_aceitam_base_ou_url_completa(self):
        assert telemetry._url_traces("http://x:4318") == "http://x:4318/v1/traces"
        assert (
            telemetry._url_traces("http://x:4318/v1/traces")
            == "http://x:4318/v1/traces"
        )
        assert telemetry._url_metricas("http://x:4318") == "http://x:4318/v1/metrics"

    def test_headers_do_endpoint(self, monkeypatch):
        monkeypatch.setenv(telemetry.ENV_CABECALHOS, "authorization=Bearer x, team=od")
        assert telemetry._headers_env() == {
            "authorization": "Bearer x",
            "team": "od",
        }


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

class TestSpans:
    def test_span_exporta_atributos(self):
        exportador = _in_memory()
        telemetry.configurar(
            servico="od-teste", versao="1.0.0", exportador_span=exportador, ratio=1.0
        )
        with telemetry.span("od.test.span", papel="admin", vazio=None) as sp:
            assert sp is not None
            assert telemetry.trace_id() != ""
            assert len(telemetry.trace_id()) == 32
            assert len(telemetry.span_id()) == 16

        spans = exportador.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "od.test.span"
        assert spans[0].attributes["od.papel"] == "admin"
        assert "od.vazio" not in spans[0].attributes

    def test_atribuir_no_span_ativo(self):
        exportador = _in_memory()
        telemetry.configurar(exportador_span=exportador, ratio=1.0)
        with telemetry.span("od.test.status"):
            telemetry.atribuir("http.status_code", 200)
        spans = exportador.get_finished_spans()
        assert spans[0].attributes["http.status_code"] == 200

    def test_fora_de_span_trace_id_e_vazio(self):
        telemetry.configurar()
        assert telemetry.trace_id() == ""
        assert telemetry.span_id() == ""


# ---------------------------------------------------------------------------
# Correlação log ↔ trace
# ---------------------------------------------------------------------------

class TestCorrelacaoLog:
    def test_log_dentro_de_span_carrega_trace_e_span(self):
        telemetry.configurar(exportador_span=_in_memory(), ratio=1.0)
        log = get_logger("omega.test.telemetria")
        with telemetry.span("od.test.log"):
            esperado_trace = telemetry.trace_id()
            esperado_span = telemetry.span_id()
            log.info("evento", extra=1)
        registro = log.records[-1]
        assert registro.context["trace_id"] == esperado_trace
        assert registro.context["span_id"] == esperado_span
        assert registro.context["extra"] == 1

    def test_log_fora_de_span_nao_inventa_trace(self):
        telemetry.configurar()
        log = get_logger("omega.test.telemetria")
        log.info("sem span")
        assert "trace_id" not in log.records[-1].context

    def test_trace_explicito_nao_e_sobrescrito(self):
        telemetry.configurar(exportador_span=_in_memory(), ratio=1.0)
        log = get_logger("omega.test.telemetria")
        with telemetry.span("od.test.log"):
            log.info("manual", trace_id="abc123")
        assert log.records[-1].context["trace_id"] == "abc123"


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

class TestMetricas:
    def test_histograma_e_contador_chegam_ao_exportador(self):
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        leitor = InMemoryMetricReader()
        telemetry.configurar(leitor_metrica=leitor, ratio=1.0)
        with telemetry.cronometrar("od.test.dur", etapa="x"):
            pass
        telemetry.contar("od.test.eventos", 2, tipo="y")
        assert telemetry.ultima_duracao("od.test.dur") is not None

        dados = leitor.get_metrics_data()
        nomes = set()
        for recurso in dados.resource_metrics:
            for escopo in recurso.scope_metrics:
                for metrica in escopo.metrics:
                    nomes.add(metrica.name)
        assert "od.test.dur.seconds" in nomes
        assert "od.test.eventos" in nomes

    def test_cronometrar_mede_mesmo_sem_otel(self, monkeypatch):
        monkeypatch.setenv(telemetry.ENV_LIGADO, "0")
        telemetry.configurar(forcar=True)
        with telemetry.cronometrar("od.test.local"):
            pass
        assert telemetry.ultima_duracao("od.test.local") >= 0


# ---------------------------------------------------------------------------
# Degradação sem SDK (simulada)
# ---------------------------------------------------------------------------

class TestSemSdk:
    def test_sem_sdk_configurar_devolve_false(self, monkeypatch):
        monkeypatch.setattr(telemetry, "otel_disponivel", lambda: False)
        assert telemetry.configurar(forcar=True) is False
        assert telemetry.status()["erro"] == "opentelemetry-sdk ausente"
        with telemetry.span("od.x") as sp:
            assert sp is None

    def test_sdk_quebrado_nao_derruba_o_processo(self, monkeypatch):
        def _boom(**_kwargs):
            raise RuntimeError("provider quebrado")

        monkeypatch.setattr(telemetry, "_montar_providers", _boom)
        assert telemetry.configurar(forcar=True) is False
        assert "provider quebrado" in telemetry.status()["erro"]
        assert logging.getLogger("omega.core.telemetry") is not None
