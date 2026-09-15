"""
OMEGA DRAKON • TESTS
Módulo: tests/test_supervision.py
Descrição: Testes do registro de supervisão dos loops do núcleo
           (core/supervision.py) e dos seus dois consumidores: o check
           "loops" do Health Monitor (/health) e a sonda _check_loops do
           ProactiveNotifier (alerta no Telegram/push).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/supervision.py
  - runtime/launcher.py (check "loops" em build_health)
  - integrations/notifier.py (_check_loops + anti-spam)
"""

from __future__ import annotations

import pytest

from core.supervision import (
    CRASH_LOOP_RESTARTS,
    SupervisionRegistry,
    get_supervision,
)
from integrations.notifier import (
    SEVERITY_CRIT,
    SEVERITY_WARN,
    NotifierConfig,
    ProactiveNotifier,
    _check_loops,
)


class FakeClock:
    """Relógio controlável para testar a janela de degradação."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _registro_limpo():
    """O registro global é do processo (od-core) — zera entre os testes."""
    get_supervision().reset()
    yield
    get_supervision().reset()


def _notifier(**kwargs) -> ProactiveNotifier:
    """Notifier mínimo, com o relógio real e sem estado em disco."""
    kwargs.setdefault("config", NotifierConfig(state_file=None, disk_paths=()))
    return ProactiveNotifier(None, **kwargs)


# ===========================================================================
# Registro
# ===========================================================================

class TestSupervisionRegistry:
    def test_record_drop_e_restart(self) -> None:
        reg = SupervisionRegistry()
        queda = reg.record_drop(
            "telegram", kind="TimeoutError",
            detail="The read operation timed out",
        )
        assert queda.failures == 1
        assert queda.last_kind == "TimeoutError"
        assert queda.last_error == "The read operation timed out"
        assert reg.record_restart("telegram") == 1
        assert reg.record_restart("telegram") == 2
        assert reg.snapshot()["telegram"]["restarts"] == 2
        assert reg.names() == ["telegram"]

    def test_detalhe_longo_e_truncado(self) -> None:
        reg = SupervisionRegistry()
        queda = reg.record_drop("mqtt", kind="OSError", detail="x" * 5000)
        assert len(queda.last_error) == 300

    def test_queda_recente_degrada_e_depois_estabiliza(self) -> None:
        clock = FakeClock()
        reg = SupervisionRegistry(degraded_window_s=300.0, clock=clock)
        reg.record_drop("mqtt", kind="TimeoutError", detail="read timed out")
        reg.record_restart("mqtt")
        estado = reg.evaluate()[0]
        assert estado["degraded"] is True
        assert estado["age_s"] == 0.0
        assert estado["restarts"] == 1
        clock.advance(301.0)
        estado = reg.evaluate()[0]
        assert estado["degraded"] is False
        assert estado["age_s"] == 301.0

    def test_health_contrato_do_monitor(self) -> None:
        reg = SupervisionRegistry()
        # sem loops conhecidos: ok (nada a reportar)
        assert reg.health() == {
            "ok": True,
            "status": "up",
            "detail": "nenhum loop supervisionado registrado",
        }
        reg.record_drop("telegram", kind="TimeoutError", detail="timed out")
        degradado = reg.health()
        assert degradado["ok"] is False
        assert degradado["status"] == "degraded"
        assert "telegram" in degradado["detail"]
        assert "TimeoutError" in degradado["detail"]

    def test_health_volta_a_ok_fora_da_janela(self) -> None:
        clock = FakeClock()
        reg = SupervisionRegistry(degraded_window_s=300.0, clock=clock)
        reg.record_drop("vision", kind="TimeoutError", detail="x")
        assert reg.health()["ok"] is False
        clock.advance(299.0)
        assert reg.health()["ok"] is False
        clock.advance(2.0)  # total 301s > janela
        saude = reg.health()
        assert saude["ok"] is True
        assert "sem quedas" in saude["detail"]

    def test_crash_loop_marcado(self) -> None:
        reg = SupervisionRegistry()
        reg.record_drop("vision", kind="TimeoutError", detail="x")
        for _ in range(CRASH_LOOP_RESTARTS):
            reg.record_restart("vision")
        assert reg.evaluate()[0]["crash_loop"] is True

    def test_reset_por_loop_e_global(self) -> None:
        reg = SupervisionRegistry()
        reg.record_drop("api", kind="Returned", detail="retornou")
        reg.record_drop("mqtt", kind="TimeoutError", detail="x")
        reg.reset("api")
        assert reg.names() == ["mqtt"]
        reg.reset()
        assert reg.names() == []
        assert reg.evaluate() == []


# ===========================================================================
# Consumidor 1: sonda do ProactiveNotifier
# ===========================================================================

class TestNotifierLoopsCheck:
    def test_sem_loops_conhecidos_nao_reporta(self) -> None:
        assert _check_loops(_notifier(checks=[])) == []

    def test_queda_vira_problema_warn(self) -> None:
        reg = get_supervision()
        reg.record_drop(
            "telegram", kind="TimeoutError",
            detail="The read operation timed out",
        )
        reg.record_restart("telegram")
        [resultado] = _check_loops(_notifier(checks=[]))
        assert resultado.ok is False
        assert resultado.key == "loop:telegram"
        assert resultado.severity == SEVERITY_WARN
        assert "TimeoutError" in resultado.detail
        assert "reiniciado 1x pela supervisão" in resultado.detail

    def test_crash_loop_escala_para_crit(self) -> None:
        reg = get_supervision()
        reg.record_drop("vision", kind="TimeoutError", detail="x")
        for _ in range(CRASH_LOOP_RESTARTS):
            reg.record_restart("vision")
        [resultado] = _check_loops(_notifier(checks=[]))
        assert resultado.severity == SEVERITY_CRIT

    @pytest.mark.asyncio
    async def test_tick_emite_alerta_e_respeita_anti_spam(self) -> None:
        get_supervision().record_drop(
            "telegram", kind="TimeoutError",
            detail="The read operation timed out",
        )
        notifier = _notifier(checks=[_check_loops])
        alertas = await notifier.tick()
        assert len(alertas) == 1
        alerta = alertas[0]
        assert alerta.key == "loop:telegram"
        assert alerta.severity == SEVERITY_WARN
        assert "telegram" in alerta.title
        assert "TimeoutError" in alerta.detail
        # Segundo tick: o cooldown (1h) bloqueia a repetição
        assert await notifier.tick() == []
        assert notifier.metrics.alerts_blocked >= 1

    @pytest.mark.asyncio
    async def test_problema_limpa_quando_o_loop_estabiliza(self) -> None:
        reg = get_supervision()
        notifier = _notifier(checks=[_check_loops])
        reg.record_drop("mqtt", kind="TimeoutError", detail="x")
        assert len(await notifier.tick()) == 1
        assert "loop:mqtt" in notifier._problem_since
        janela = reg.degraded_window_s
        reg.degraded_window_s = -1.0  # força a queda para fora da janela
        try:
            assert await notifier.tick() == []
            assert "loop:mqtt" not in notifier._problem_since
        finally:
            reg.degraded_window_s = janela
