"""
OMEGA DRAKON • TESTS
Módulo: tests/test_notifier.py
Descrição: Testes do ProactiveNotifier (integrations/notifier.py) — Fase 5,
           item 5.3: tipos (CheckResult/Alert/config), sondas embutidas
           (orchestrator, LLM offline com threshold, disco com monkeypatch,
           restart por estado persistido), pipeline de tick com anti-spam
           (cooldown por chave), sinks sync/async, Event Bus, persistência
           entre instâncias e loop de execução (run/start/stop).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/notifier.py (ProactiveNotifier)
  - docs/NICKY_LEGACY_ANALYSIS.md §4.3
  - ROADMAP_ABSORCAO.md Fase 5, item 5.3
"""

from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator, RecordingProvider
from integrations.notifier import (
    SEVERITY_CRIT,
    SEVERITY_EMOJI,
    SEVERITY_OK,
    SEVERITY_WARN,
    Alert,
    CheckResult,
    NotifierConfig,
    ProactiveNotifier,
)

_DU = namedtuple("DiskUsage", "total used free")


class OfflineProvider:
    name = "offline"

    def is_available(self) -> bool:
        return False


class OnlineProvider:
    name = "online"

    def is_available(self) -> bool:
        return True


class _Clock:
    """Relógio determinístico (monotonic fake)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_notifier(
    orch=None,
    *,
    config=None,
    sinks=None,
    checks=None,
    clock=None,
    event_bus=None,
) -> ProactiveNotifier:
    """Notifier com cooldown padrão 0 e threshold LLM 0 (determinístico)."""
    cfg = config or NotifierConfig(
        default_cooldown_s=0.0,
        llm_offline_threshold_s=0.0,
        disk_threshold_percent=85.0,
    )
    return ProactiveNotifier(
        orch,
        config=cfg,
        sinks=sinks,
        checks=checks,
        clock=clock,
        event_bus=event_bus,
    )


def orch(*providers) -> Orchestrator:
    return Orchestrator(providers=list(providers))


# ===========================================================================
# Tipos e configuração
# ===========================================================================

class TestNotifierTypes:
    """CheckResult, Alert, formatação e defaults de config."""

    def test_check_result_key_defaults_to_source(self) -> None:
        result = CheckResult(ok=False, source="llm")
        assert result.key == "llm"
        assert result.is_problem()
        result2 = CheckResult(ok=False, source="disk:/", key="disk:high:/")
        assert result2.key == "disk:high:/"
        assert CheckResult(ok=True).is_problem() is False

    def test_alert_to_dict(self) -> None:
        alert = Alert(
            key="restart", severity=SEVERITY_WARN, title="restart",
            detail="reiniciou", source="restart", ts=5.0,
        )
        data = alert.to_dict()
        assert data["key"] == "restart"
        assert data["severity"] == "warn" and data["ts"] == 5.0

    def test_severity_emojis(self) -> None:
        assert SEVERITY_EMOJI == {SEVERITY_OK: "🟢", SEVERITY_WARN: "🟡",
                                  SEVERITY_CRIT: "🔴"}

    def test_format_alert(self) -> None:
        alert = Alert(
            key="llm:offline", severity=SEVERITY_CRIT, title="llm",
            detail="Nenhum provider.", source="llm", ts=0.0,
        )
        text = ProactiveNotifier.format_alert(alert)
        assert "🔴" in text and "[CRIT]" in text
        assert "Nenhum provider." in text
        warn = Alert(key="x", severity=SEVERITY_WARN, title="x", ts=0.0)
        assert "🟡" in ProactiveNotifier.format_alert(warn)

    def test_config_defaults_match_legacy(self) -> None:
        cfg = NotifierConfig()
        assert cfg.llm_offline_threshold_s == 300.0  # >5min
        assert cfg.disk_threshold_percent == 85.0
        assert cfg.default_cooldown_s == 3600.0  # 1 alerta/hora
        assert cfg.interval_s == 60.0


# ===========================================================================
# Sondas embutidas
# ===========================================================================

class TestNotifierChecks:
    """orchestrator, LLM, disco (monkeypatch) e restart."""

    @pytest.mark.asyncio
    async def test_orchestrator_check_ok_and_problem(self) -> None:
        ok_notifier = make_notifier(orch(OnlineProvider()))
        health = await ok_notifier.health()
        assert health["checks"]["orchestrator"]["ok"] is True
        empty = make_notifier(None)
        health = await empty.health()
        assert health["checks"]["orchestrator"]["ok"] is False

    @pytest.mark.asyncio
    async def test_llm_offline_reports_immediately_in_health(self) -> None:
        notifier = make_notifier(orch(OfflineProvider()))
        health = await notifier.health()
        llm = health["checks"]["llm:offline"]
        assert llm["ok"] is False and llm["severity"] == SEVERITY_CRIT
        assert health["ok"] is False

    @pytest.mark.asyncio
    async def test_llm_online_and_default_available(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        health = await notifier.health()
        assert health["checks"]["llm"]["ok"] is True
        # Provider sem is_available (ex: RecordingProvider) = disponível
        notifier2 = make_notifier(orch(RecordingProvider("x", reply="r")))
        health2 = await notifier2.health()
        assert health2["checks"]["llm"]["ok"] is True
        assert "x" in health2["checks"]["llm"]["detail"]

    @pytest.mark.asyncio
    async def test_llm_without_orchestrator_not_judged(self) -> None:
        notifier = make_notifier(None)
        health = await notifier.health()
        assert health["checks"]["llm"]["ok"] is True
        assert "não avaliável" in health["checks"]["llm"]["detail"]

    @pytest.mark.asyncio
    async def test_disk_above_threshold_warns(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "integrations.notifier.shutil.disk_usage",
            lambda path: _DU(total=100, used=90, free=10),
        )
        notifier = make_notifier(
            orch(), config=NotifierConfig(default_cooldown_s=0.0)
        )
        health = await notifier.health()
        disk = health["checks"]["disk:high:/"]
        assert disk["ok"] is False and disk["severity"] == SEVERITY_WARN
        assert "90.0%" in disk["detail"]

    @pytest.mark.asyncio
    async def test_disk_way_above_threshold_crits(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "integrations.notifier.shutil.disk_usage",
            lambda path: _DU(total=100, used=97, free=3),
        )
        notifier = make_notifier(orch())
        health = await notifier.health()
        assert health["checks"]["disk:high:/"]["severity"] == SEVERITY_CRIT

    @pytest.mark.asyncio
    async def test_disk_ok_below_threshold(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "integrations.notifier.shutil.disk_usage",
            lambda path: _DU(total=100, used=40, free=60),
        )
        notifier = make_notifier(orch())
        health = await notifier.health()
        assert health["checks"]["disk:/"]["ok"] is True

    @pytest.mark.asyncio
    async def test_disk_unreadable_path(self, monkeypatch) -> None:
        def boom(path):
            raise OSError("sem permissão")

        monkeypatch.setattr(
            "integrations.notifier.shutil.disk_usage", boom
        )
        notifier = make_notifier(
            orch(),
            config=NotifierConfig(
                default_cooldown_s=0.0, disk_paths=("/x",)
            ),
        )
        health = await notifier.health()
        assert health["checks"]["disk:unreadable"]["ok"] is False

    def test_restart_detected_from_old_pid(self, tmp_path: Path) -> None:
        state = tmp_path / "notifier.json"
        state.write_text(
            json.dumps({"pid": 424242, "started_at": 1.0, "last_alerts": {}})
        )
        notifier = ProactiveNotifier(
            config=NotifierConfig(state_file=state)
        )
        assert notifier._restart_detected is True

    def test_restart_not_detected_same_pid(self, tmp_path: Path) -> None:
        import os

        state = tmp_path / "notifier.json"
        state.write_text(
            json.dumps({"pid": os.getpid(), "started_at": 1.0,
                        "last_alerts": {}})
        )
        notifier = ProactiveNotifier(
            config=NotifierConfig(state_file=state)
        )
        assert notifier._restart_detected is False

    def test_restart_baseline_first_run(self, tmp_path: Path) -> None:
        state = tmp_path / "notifier.json"
        notifier = ProactiveNotifier(
            config=NotifierConfig(state_file=state)
        )
        assert notifier._restart_detected is False
        assert state.exists()  # baseline gravado

    def test_corrupt_state_ignored(self, tmp_path: Path) -> None:
        state = tmp_path / "notifier.json"
        state.write_text("{json quebrado", encoding="utf-8")
        notifier = ProactiveNotifier(
            config=NotifierConfig(state_file=state)
        )
        assert notifier._restart_detected is False


# ===========================================================================
# Pipeline de tick
# ===========================================================================

class TestNotifierTick:
    """Emissão, threshold de LLM, limpeza e métricas."""

    @pytest.mark.asyncio
    async def test_restart_alert_emitted_once(self, tmp_path: Path) -> None:
        state = tmp_path / "notifier.json"
        state.write_text(
            json.dumps({"pid": 99999, "started_at": 1.0, "last_alerts": {}})
        )
        clock = _Clock()
        notifier = ProactiveNotifier(
            orch(OnlineProvider()),
            config=NotifierConfig(
                state_file=state, default_cooldown_s=0.0,
                cooldowns={"restart": 3600.0},
            ),
            clock=clock,
        )
        first = await notifier.tick()
        assert [a.key for a in first] == ["restart"]
        assert first[0].severity == SEVERITY_WARN
        # Segundo tick: restart já reportado e sem novos problemas
        clock.advance(10)
        second = await notifier.tick()
        assert second == []
        assert notifier.metrics.snapshot()["alerts_emitted"] == 1

    @pytest.mark.asyncio
    async def test_llm_alert_only_after_threshold(self) -> None:
        clock = _Clock()
        cfg = NotifierConfig(
            default_cooldown_s=0.0,
            llm_offline_threshold_s=300.0,
        )
        notifier = make_notifier(orch(OfflineProvider()), config=cfg,
                                 clock=clock)
        # Abaixo do threshold (300s): health acusa, tick não emite
        clock.advance(120)
        assert await notifier.tick() == []
        assert (await notifier.health())["checks"]["llm:offline"]["ok"] is False
        # Passa do threshold (elapsed >= 300s desde a 1ª observação): alerta
        clock.advance(300)
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["llm:offline"]
        assert alerts[0].severity == SEVERITY_CRIT
        assert notifier.metrics.snapshot()["alerts_emitted"] == 1

    @pytest.mark.asyncio
    async def test_problem_cleared_when_llm_returns(self) -> None:
        clock = _Clock()
        notifier = make_notifier(orch(OfflineProvider()), clock=clock)
        clock.advance(300)
        await notifier.tick()
        assert notifier.metrics.snapshot()["alerts_emitted"] == 1
        orch_instance = notifier.orchestrator
        assert orch_instance is not None
        orch_instance._providers = [OnlineProvider()]
        clock.advance(60)
        assert await notifier.tick() == []
        assert (await notifier.health())["ok"] is True

    @pytest.mark.asyncio
    async def test_metrics_counters(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        await notifier.tick()
        snapshot = notifier.metrics.snapshot()
        assert snapshot["ticks"] == 1
        # checks: orchestrator + llm + disk + restart = 4
        assert snapshot["checks_run"] == 4
        assert snapshot["problems"] == 0

    @pytest.mark.asyncio
    async def test_checks_run_counted_for_offline(self) -> None:
        notifier = make_notifier(orch(OfflineProvider()))
        await notifier.tick()
        snapshot = notifier.metrics.snapshot()
        assert snapshot["checks_run"] == 4
        assert snapshot["problems"] == 1  # apenas llm (abaixo do threshold)


# ===========================================================================
# Anti-spam (cooldown)
# ===========================================================================

class TestNotifierAntiSpam:
    """Cooldown por chave: bloqueio, re-emissão e override por chave."""

    @pytest.mark.asyncio
    async def test_cooldown_blocks_reenvio(self) -> None:
        clock = _Clock()
        cfg = NotifierConfig(
            default_cooldown_s=3600.0,
            llm_offline_threshold_s=0.0,
        )
        notifier = make_notifier(orch(OfflineProvider()), config=cfg,
                                 clock=clock)
        assert [a.key for a in await notifier.tick()] == ["llm:offline"]
        # Mesmo problema logo depois -> bloqueado pelo anti-spam
        clock.advance(60)
        assert await notifier.tick() == []
        metrics = notifier.metrics.snapshot()
        assert metrics["alerts_blocked"] == 1
        assert metrics["alerts_emitted"] == 1

    @pytest.mark.asyncio
    async def test_reenvio_apos_cooldown(self) -> None:
        clock = _Clock()
        cfg = NotifierConfig(
            default_cooldown_s=3600.0,
            llm_offline_threshold_s=0.0,
        )
        notifier = make_notifier(orch(OfflineProvider()), config=cfg,
                                 clock=clock)
        await notifier.tick()
        clock.advance(3600)
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["llm:offline"]
        assert notifier.metrics.snapshot()["alerts_emitted"] == 2

    @pytest.mark.asyncio
    async def test_cooldown_per_key_override(self) -> None:
        clock = _Clock()
        cfg = NotifierConfig(
            default_cooldown_s=3600.0,
            cooldowns={"llm:offline": 10.0},
            llm_offline_threshold_s=0.0,
        )
        notifier = make_notifier(orch(OfflineProvider()), config=cfg,
                                 clock=clock)
        await notifier.tick()
        clock.advance(30)
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["llm:offline"]

    @pytest.mark.asyncio
    async def test_cooldown_zero_reenvia_sempre(self) -> None:
        clock = _Clock()
        notifier = make_notifier(orch(OfflineProvider()), clock=clock)
        await notifier.tick()
        await notifier.tick()
        assert notifier.metrics.snapshot()["alerts_emitted"] == 2
        assert notifier.metrics.snapshot()["alerts_blocked"] == 0


# ===========================================================================
# Sinks, Event Bus e estado persistido
# ===========================================================================

class TestNotifierDelivery:
    """Sinks sync/async, Event Bus e cooldown persistido entre instâncias."""

    @pytest.mark.asyncio
    async def test_sync_sink_receives_formatted_alert(self) -> None:
        sent: list[str] = []
        notifier = make_notifier(orch(OfflineProvider()), sinks=[sent.append])
        await notifier.tick()
        assert len(sent) == 1
        assert "🔴" in sent[0] and "llm" in sent[0]

    @pytest.mark.asyncio
    async def test_async_sink_is_awaited(self) -> None:
        sent: list[str] = []

        async def async_sink(text: str) -> None:
            sent.append(text)

        notifier = make_notifier(orch(OfflineProvider()), sinks=[async_sink])
        await notifier.tick()
        assert len(sent) == 1
        assert "🔴" in sent[0] and "[CRIT]" in sent[0]
        assert "Nenhum provider" in sent[0]

    @pytest.mark.asyncio
    async def test_broken_sink_does_not_abort_tick(self) -> None:
        def broken(text: str) -> None:
            raise RuntimeError("sink caiu")

        notifier = make_notifier(orch(OfflineProvider()), sinks=[broken])
        await notifier.tick()  # não deve propagar
        assert notifier.metrics.snapshot()["errors"] == 1

    @pytest.mark.asyncio
    async def test_event_bus_receives_alert(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        async def handler(event) -> None:
            received.append(event.data)

        bus.subscribe_handler("notifier.alert", handler)
        notifier = make_notifier(
            orch(OfflineProvider()), event_bus=bus
        )
        await notifier.tick()
        assert len(received) == 1
        assert received[0]["key"] == "llm:offline"
        assert received[0]["severity"] == SEVERITY_CRIT

    def test_cooldown_persisted_between_instances(self, tmp_path: Path) -> None:
        state = tmp_path / "notifier.json"
        clock = _Clock()

        async def run_first() -> None:
            cfg = NotifierConfig(
                state_file=state, default_cooldown_s=3600.0,
                llm_offline_threshold_s=0.0,
            )
            notifier = ProactiveNotifier(
                orch(OfflineProvider()), config=cfg, clock=clock
            )
            await notifier.tick()  # emite e grava last_alerts no state

        import asyncio

        asyncio.run(run_first())
        data = json.loads(state.read_text(encoding="utf-8"))
        assert "llm:offline" in data["last_alerts"]
        assert data["pid"] == __import__("os").getpid()

        # Nova instância com o mesmo state respeita o cooldown
        async def run_second() -> None:
            clock.advance(60)
            cfg = NotifierConfig(
                state_file=state, default_cooldown_s=3600.0,
                llm_offline_threshold_s=0.0,
            )
            notifier2 = ProactiveNotifier(
                orch(OfflineProvider()), config=cfg, clock=clock
            )
            alerts = await notifier2.tick()
            return alerts

        assert asyncio.run(run_second()) == []


# ===========================================================================
# Checks customizados e health
# ===========================================================================

class TestNotifierCustomChecks:
    """Sondas injetáveis: sync, lista e async."""

    @pytest.mark.asyncio
    async def test_custom_sync_check_problem(self) -> None:
        def always_problem(notifier) -> CheckResult:
            return CheckResult(
                ok=False, severity=SEVERITY_WARN, source="custom",
                detail="coisa estranha",
            )

        notifier = make_notifier(orch(), checks=[always_problem])
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["custom"]
        assert alerts[0].detail == "coisa estranha"

    @pytest.mark.asyncio
    async def test_custom_check_returning_list(self) -> None:
        def two_problems(notifier) -> list[CheckResult]:
            return [
                CheckResult(ok=False, source="a"),
                CheckResult(ok=False, source="b"),
            ]

        notifier = make_notifier(orch(), checks=[two_problems])
        alerts = await notifier.tick()
        assert {a.key for a in alerts} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_custom_async_check(self) -> None:
        async def slow_problem(notifier) -> CheckResult:
            return CheckResult(ok=False, source="async-check",
                               severity=SEVERITY_CRIT)

        notifier = make_notifier(orch(), checks=[slow_problem])
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["async-check"]
        assert alerts[0].severity == SEVERITY_CRIT

    @pytest.mark.asyncio
    async def test_health_captures_crashed_check(self) -> None:
        def boom(notifier) -> CheckResult:
            raise ValueError("sonda quebrou")

        notifier = make_notifier(orch(), checks=[boom])
        health = await notifier.health()
        assert health["ok"] is False
        assert health["checks"]  # entrada de erro presente

    @pytest.mark.asyncio
    async def test_tick_skips_crashed_check(self) -> None:
        def boom(notifier) -> CheckResult:
            raise ValueError("sonda quebrou")

        notifier = make_notifier(orch(), checks=[boom])
        assert await notifier.tick() == []
        assert notifier.metrics.snapshot()["errors"] == 1


# ===========================================================================
# Loop de execução e introspecção
# ===========================================================================

class TestNotifierLoop:
    """run(max_ticks), thread start/stop e dump()."""

    @pytest.mark.asyncio
    async def test_run_executes_max_ticks(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        ticks = await notifier.run(interval=0.001, max_ticks=3)
        assert ticks == 3
        assert notifier.metrics.snapshot()["ticks"] == 3

    @pytest.mark.asyncio
    async def test_run_closed_returns_zero(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        notifier.close()
        assert await notifier.run(interval=0.001) == 0

    def test_start_stop_thread(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        thread = notifier.start()
        assert thread.is_alive()
        notifier.stop()
        assert notifier._closed is True
        notifier.close()  # alias idempotente
        assert notifier._closed is True

    def test_dump_shape(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()), sinks=[lambda t: None])
        data = notifier.dump()
        assert data["pid"] >= 0
        assert len(data["checks"]) == 4
        assert data["sinks"] == 1
        assert data["metrics"]["ticks"] == 0
        assert data["alerts"] == []

    def test_history_trace(self) -> None:
        notifier = make_notifier(orch(OfflineProvider()))
        import asyncio

        asyncio.run(notifier.tick())
        history = notifier.history()
        assert len(history) == 1
        assert history[0]["key"] == "llm:offline"

    def test_history_limited(self) -> None:
        import asyncio

        notifier = make_notifier(orch(OfflineProvider()))
        for _ in range(120):
            asyncio.run(notifier.tick())
        assert len(notifier.history()) == 100  # ALERT_TRACE_LIMIT