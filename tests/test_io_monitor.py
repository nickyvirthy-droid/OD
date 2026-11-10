#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_io_monitor.py
Descrição: Monitor periódico de latência (F3): gravação/merga do JSON pela
           sonda (tools/monitor/io_probe.py) e o check `latencia` do /health
           (runtime/launcher.py) — ausente, fresco, velho, p95 alto e ilegível.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F3 (fatias 1 e 2) e docs/TELEMETRIA.md
  - tools/monitor/io_probe.py · runtime/launcher.py (check_latencia)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from runtime.launcher import check_latencia
from tools.monitor import io_probe


def _gravar(caminho: Path, rotulo: str, p50: float, p95: float, ts: float | None = None) -> None:
    io_probe.gravar_resultado(
        caminho,
        rotulo,
        f"http://127.0.0.1:8000/{rotulo.strip('/')}",
        {"n": 10, "p50_ms": p50, "p95_ms": p95, "max_ms": p95, "codigos": {200: 10}},
        {},
    )
    if ts is not None:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        dados["ts"] = ts
        caminho.write_text(json.dumps(dados), encoding="utf-8")


@pytest.fixture()
def arquivo(tmp_path, monkeypatch):
    caminho = tmp_path / "io_monitor.json"
    monkeypatch.setenv("OD_IO_MONITOR_PATH", str(caminho))
    monkeypatch.delenv("OD_IO_MONITOR_MAX_IDADE_S", raising=False)
    monkeypatch.delenv("OD_IO_MONITOR_P95_MS", raising=False)
    return caminho


class TestGravacao:
    def test_grava_json_com_alvo_e_timestamp(self, arquivo: Path) -> None:
        _gravar(arquivo, "site", 1.0, 2.0)
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        assert dados["versao"] == 1
        assert dados["ts"] > 0 and dados["iso"]
        assert dados["alvos"]["site"]["serie"]["p95_ms"] == 2.0

    def test_segunda_execucao_preserva_o_outro_alvo(self, arquivo: Path) -> None:
        _gravar(arquivo, "site", 1.0, 2.0)
        _gravar(arquivo, "health", 10.0, 20.0)
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        assert set(dados["alvos"]) == {"site", "health"}

    def test_arquivo_corrompido_e_sobrescrito(self, arquivo: Path) -> None:
        arquivo.write_text("{lixo", encoding="utf-8")
        _gravar(arquivo, "site", 1.0, 2.0)
        assert json.loads(arquivo.read_text(encoding="utf-8"))["alvos"]["site"]

    def test_nao_deixa_arquivo_temporario(self, arquivo: Path) -> None:
        _gravar(arquivo, "site", 1.0, 2.0)
        assert not list(arquivo.parent.glob("*.tmp"))


class TestCheckLatencia:
    def test_sem_sonda_ainda_e_ok(self, arquivo: Path) -> None:
        r = check_latencia(None)
        assert r["ok"] is True and "não rodou" in r["detail"]

    def test_fresco_e_ok_com_p50_e_p95(self, arquivo: Path) -> None:
        _gravar(arquivo, "site", 1.25, 3.5)
        r = check_latencia(None)
        assert r["ok"] is True
        assert "p50=1.25ms" in r["detail"] and "p95=3.50ms" in r["detail"]

    def test_p95_usa_o_pior_alvo(self, arquivo: Path) -> None:
        _gravar(arquivo, "site", 1.0, 2.0)
        _gravar(arquivo, "health", 20.0, 30.0)
        r = check_latencia(None)
        assert "p95=30.00ms" in r["detail"] and "alvos=2" in r["detail"]

    def test_sonda_velha_degrada(self, arquivo: Path) -> None:
        _gravar(arquivo, "site", 1.0, 2.0, ts=time.time() - 5000)
        r = check_latencia(None)
        assert r["ok"] is False and r["status"] == "degraded"
        assert "parada" in r["detail"]

    def test_p95_acima_do_limite_degrada(self, arquivo: Path, monkeypatch) -> None:
        monkeypatch.setenv("OD_IO_MONITOR_P95_MS", "10")
        _gravar(arquivo, "site", 5.0, 40.0)
        r = check_latencia(None)
        assert r["ok"] is False and "p95 acima" in r["detail"]

    def test_limite_configuravel_por_env(self, arquivo: Path, monkeypatch) -> None:
        monkeypatch.setenv("OD_IO_MONITOR_P95_MS", "500")
        _gravar(arquivo, "site", 5.0, 400.0)
        assert check_latencia(None)["ok"] is True

    def test_ilegivel_degrada(self, arquivo: Path) -> None:
        arquivo.write_text("{nao-e-json", encoding="utf-8")
        r = check_latencia(None)
        assert r["ok"] is False and "ilegível" in r["detail"]

    def test_json_sem_alvos_degrada(self, arquivo: Path) -> None:
        arquivo.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
        r = check_latencia(None)
        assert r["ok"] is False and "sem alvos" in r["detail"]

    def test_registrado_no_build_health(self) -> None:
        from runtime.launcher import build_health

        monitor = build_health()
        assert "latencia" in monitor._checks
