"""
OMEGA DRAKON • TESTS
Módulo: tests/test_llm_quota_health.py
Descrição: Testes do check `llm_quota` do /health (item TODO 681, 14/11) e
do QuotaTracker com limite provisório + override por env.
Autor: OpenClaude (sessão 2026-11-14)
"""

from __future__ import annotations

import pathlib

import pytest

import core.resilience as resilience
from runtime.launcher import _check_llm_quota, build_health


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    """QuotaTracker isolado em arquivo temporário, singleton resetado."""
    monkeypatch.setenv("OD_QUOTA_FILE", str(tmp_path / "quota.json"))
    resilience._QUOTA_TRACKER = None
    t = resilience.QuotaTracker(tmp_path / "quota.json")
    resilience._QUOTA_TRACKER = t
    yield t
    resilience._QUOTA_TRACKER = None


class TestCheckLlmQuota:
    def test_registrado_no_build_health(self):
        monitor = build_health()
        assert "llm_quota" in monitor.components

    def test_uso_baixo_ok(self, tracker):
        tracker.record_usage("groq", 60)   # 60/500 = 12%
        tracker.record_usage("gemini", 1)  # 1/20 = 5%
        r = _check_llm_quota(None)
        assert r["ok"] is True and r["status"] == "up"
        assert "groq: 12.0% (60/500)" in r["detail"]
        assert "gemini: 5.0% (1/20)" in r["detail"]

    def test_acima_de_80_degrada(self, tracker):
        tracker.set_limit("groq", 100)
        tracker.record_usage("groq", 90)   # 90%
        r = _check_llm_quota(None)
        assert r["ok"] is False and r["status"] == "degraded"
        assert "groq" in r["detail"] and "90.0%" in r["detail"]

    def test_esgotada_degrada(self, tracker):
        tracker.set_limit("groq", 100)
        tracker.record_usage("groq", 100)
        r = _check_llm_quota(None)
        assert r["ok"] is False and r["status"] == "degraded"
        assert "ESGOTADA" in r["detail"]

    def test_threshold_por_env(self, tracker, monkeypatch):
        monkeypatch.setenv("OD_QUOTA_ALERTA_PCT", "50")
        tracker.record_usage("gemini", 11)  # 11/20 = 55%
        r = _check_llm_quota(None)
        assert r["ok"] is False and r["status"] == "degraded"
        assert "55.0%" in r["detail"]

    def test_threshold_env_invalido_usa_80(self, tracker, monkeypatch):
        monkeypatch.setenv("OD_QUOTA_ALERTA_PCT", "abc")
        tracker.record_usage("gemini", 17)  # 85% >= 80
        r = _check_llm_quota(None)
        assert r["ok"] is False and r["status"] == "degraded"


class TestLimiteDe:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OD_QUOTA_GROQ_LIMIT", "1234")
        assert resilience._limite_de("groq") == 1234

    def test_env_invalido_cai_no_default(self, monkeypatch):
        monkeypatch.setenv("OD_QUOTA_GROQ_LIMIT", "xyz")
        assert resilience._limite_de("groq") == 500  # provisório 14/11

    def test_default_provisorio_groq_500(self, monkeypatch):
        monkeypatch.delenv("OD_QUOTA_GROQ_LIMIT", raising=False)
        assert resilience._limite_de("groq") == 500

    def test_provider_desconhecido_ilimitado(self, monkeypatch):
        monkeypatch.delenv("OD_QUOTA_FOO_LIMIT", raising=False)
        assert resilience._limite_de("foo") == resilience._DEFAULT_UNLIMITED

    def test_status_quota_inclui_pct(self, tracker):
        tracker.record_usage("groq", 25)  # 25/500 = 5%
        status = {q["provider"]: q for q in resilience.status_quota()}
        assert status["groq"]["pct_used"] == 5.0
        assert status["groq"]["used"] == 25
        assert status["groq"]["limit"] == 500
