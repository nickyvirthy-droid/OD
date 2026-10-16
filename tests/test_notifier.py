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
import time
from collections import namedtuple
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator, RecordingProvider
from core.supervision import CRASH_LOOP_RESTARTS
from integrations.notifier import (
    HEALTH_DEGRADADO_APOS_S,
    RESTART_ALERT_GUARD_S,
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
    health=None,
    nrestarts=None,
    nomad_tools=None,
    unidade="od-core.service",
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
        health_monitor=health,
        nrestarts_fn=nrestarts,
        nomad_tools=nomad_tools,
        unidade=unidade,
    )


def orch(*providers) -> Orchestrator:
    return Orchestrator(providers=list(providers))


@pytest.fixture(autouse=True)
def _isola_od_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste do módulo lê logs/ de produção (2026-10-10).

    A sonda ``_check_router`` lê ``<OD_LOG_DIR>/router_monitor.log``, que o
    monitor da máquina escreve de verdade a cada minuto. Sem este isolamento,
    um blip de rede real no meio da suíte injetava ``router:down`` em testes
    que nada têm a ver com o roteador (ex.: ``test_restart_alert_emitted_once``
    falhava com ``['restart', 'router:down']``). Os testes de roteador
    continuam à vontade: eles apontam ``OD_LOG_DIR`` para o próprio tmp_path.
    """
    monkeypatch.setenv("OD_LOG_DIR", str(tmp_path))


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
        # Alerta de restart é EVENTO: guarda de rajada, não 1 alerta/hora
        assert cfg.restart_alert_guard_s == RESTART_ALERT_GUARD_S == 300.0


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

    def test_last_alerts_de_boot_anterior_descartado(
        self, tmp_path: Path
    ) -> None:
        """Regressão do incidente 11/09 → 16/10/2026.

        Timestamp monotônico gravado num boot antigo fica MAIOR que o
        relógio do boot novo e o anti-spam (`now - last` negativo <
        cooldown) bloqueava `restart` e `llm:offline` para sempre — 35
        dias sem alerta. Entrada futura deve ser descartada na carga e
        o arquivo regravado limpo pelo próprio __init__.
        """
        state = tmp_path / "notifier.json"
        state.write_text(
            json.dumps({
                "pid": 424242,
                "started_at": 1.0,
                "last_alerts": {"restart": 3_754_164.292,
                                "router:down": 900.0},
            }),
            encoding="utf-8",
        )
        notifier = ProactiveNotifier(
            config=NotifierConfig(state_file=state),
            clock=_Clock(1000.0),
        )
        # futuro (outro boot) => fora; passado (este boot) => mantido
        assert "restart" not in notifier._last_alerts
        assert notifier._last_alerts["router:down"] == 900.0
        salvo = json.loads(state.read_text(encoding="utf-8"))
        assert "restart" not in salvo["last_alerts"]
        assert salvo["last_alerts"]["router:down"] == 900.0


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
                restart_alert_guard_s=3600.0,
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
    async def test_restart_alert_emits_with_poisoned_state(
        self, tmp_path: Path
    ) -> None:
        """Com `restart` envenenado por boot anterior no arquivo, o alerta
        AGORA emite — antes o anti-spam via `now - last` negativo
        bloqueava (prova do incidente de 11/09; a carga limpa está no
        teste da regressão em TestNotifierChecks).
        """
        state = tmp_path / "notifier.json"
        state.write_text(
            json.dumps({"pid": 99999, "started_at": 1.0,
                        "last_alerts": {"restart": 3_754_164.292}}),
            encoding="utf-8",
        )
        notifier = ProactiveNotifier(
            orch(OnlineProvider()),
            config=NotifierConfig(
                state_file=state, default_cooldown_s=0.0,
                restart_alert_guard_s=3600.0,
            ),
            clock=_Clock(),
        )
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["restart"]
        # o _save_state do emit regravou COM o relógio atual (1000.0)
        salvo = json.loads(state.read_text(encoding="utf-8"))
        assert salvo["last_alerts"]["restart"] == 1000.0

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
        # checks: orchestrator + llm + disk + restart + router = 5
        assert snapshot["checks_run"] == 5
        assert snapshot["problems"] == 0

    @pytest.mark.asyncio
    async def test_checks_run_counted_for_offline(self) -> None:
        notifier = make_notifier(orch(OfflineProvider()))
        await notifier.tick()
        snapshot = notifier.metrics.snapshot()
        assert snapshot["checks_run"] == 5
        assert snapshot["problems"] == 1  # apenas llm (abaixo do threshold)


# ===========================================================================
# Alerta de restart: um disparo por boot (2026-10-16)
# ===========================================================================

class TestAlertaDeRestartPorBoot:
    """Restart é EVENTO: dispara UMA vez por boot, no primeiro tick.

    Regressão do comportamento medido em 16/10/2026 (transcrição §8): com
    o anti-spam de 1 h o alerta de um boot novo era ATRASADO pelo alerta
    do boot anterior (deploys 11:17 / 11:38 / 12:23 → os alertas saíram
    11:17:10, 12:17:33 e 13:17:39, com 39 e 54 min de atraso) e o padrão
    parecia um push de hora em hora. Agora o cooldown do `restart` é a
    guarda de rajada da própria sonda (300 s), não o de 1 h.
    """

    @staticmethod
    def _estado_de_boot_anterior(
        tmp_path: Path, alerta_anterior: float | None = None
    ) -> Path:
        """Estado de um boot ANTERIOR (pid diferente = restart detectado)."""
        state = tmp_path / "notifier.json"
        salvo: dict = {"pid": 99999, "started_at": 1.0, "last_alerts": {}}
        if alerta_anterior is not None:
            salvo["last_alerts"]["restart"] = alerta_anterior
        state.write_text(json.dumps(salvo), encoding="utf-8")
        return state

    @staticmethod
    def _notifier(state: Path, clock: _Clock, **cfg) -> ProactiveNotifier:
        # threshold de disco alto: o teste não depende do disco da máquina
        return ProactiveNotifier(
            orch(OnlineProvider()),
            config=NotifierConfig(
                state_file=state, disk_threshold_percent=99.0, **cfg
            ),
            clock=clock,
        )

    @pytest.mark.asyncio
    async def test_um_disparo_por_boot_nunca_repete_no_mesmo_boot(
        self, tmp_path: Path
    ) -> None:
        """Um boot = um aviso: passada até a hora cheia do anti-spam
        antigo, o MESMO processo não repete (nada de push de hora em hora).
        """
        clock = _Clock()
        notifier = self._notifier(self._estado_de_boot_anterior(tmp_path),
                                  clock)
        assert [a.key for a in await notifier.tick()] == ["restart"]
        clock.advance(3600.0)
        assert await notifier.tick() == []
        clock.advance(3600.0)
        assert await notifier.tick() == []
        assert notifier.metrics.snapshot()["alerts_emitted"] == 1

    @pytest.mark.asyncio
    async def test_boot_novo_nao_espera_o_cooldown_de_1_hora(
        self, tmp_path: Path
    ) -> None:
        """Regressão do atraso de 16/10: o boot novo alerta no PRIMEIRO
        tick mesmo com o alerta do boot anterior há 40 min — e mesmo com
        `cooldowns["restart"]` (anti-spam de condição) configurado, que
        NÃO governa mais este alerta.
        """
        state = self._estado_de_boot_anterior(tmp_path,
                                             alerta_anterior=1000.0)
        clock = _Clock(1000.0 + 2400.0)  # 40 min depois do boot anterior
        notifier = self._notifier(
            state, clock, default_cooldown_s=0.0,
            cooldowns={"restart": 3600.0},
        )
        assert [a.key for a in await notifier.tick()] == ["restart"]

    @pytest.mark.asyncio
    async def test_rajada_de_boots_espera_a_guarda_e_emite_uma_vez(
        self, tmp_path: Path
    ) -> None:
        """Guarda de rajada: boot em cima de boot (10 s, 70 s) não vira
        push por boot — o alerta é segurado e sai UMA vez quando a guarda
        vence (o crash loop em si é sinal do `systemd:nrestarts`).
        """
        state = self._estado_de_boot_anterior(tmp_path,
                                              alerta_anterior=1000.0)
        clock = _Clock(1000.0 + 10.0)  # 10 s depois do alerta anterior
        notifier = self._notifier(state, clock)
        assert await notifier.tick() == []
        clock.advance(60.0)  # 70 s: ainda dentro dos 300 s de guarda
        assert await notifier.tick() == []
        assert notifier.metrics.snapshot()["alerts_blocked"] == 2
        clock.advance(240.0)  # 310 s: guarda vencida
        assert [a.key for a in await notifier.tick()] == ["restart"]
        clock.advance(3600.0)
        assert await notifier.tick() == []  # e não repete no mesmo boot
        assert notifier.metrics.snapshot()["alerts_emitted"] == 1


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
        # Sondas padrão: orchestrator, llm, disk, loops (supervisão), restart e router
        assert data["checks"] == [
            "_check_orchestrator",
            "_check_llm",
            "_check_disk",
            "_check_loops",
            "_check_restart",
            "_check_router",
        ]
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


# ===========================================================================
# _check_router
# ===========================================================================


class TestCheckRouter:
    """Sonda de saúde do roteador (ler logs/router_monitor.log)."""

    def test_log_ausente_retorna_ok(self, tmp_path: Path) -> None:
        """Sem log, o roteador é considerado ok (monitor não configurado)."""
        from integrations.notifier import _check_router

        notifier = make_notifier(orch(OnlineProvider()))
        # Força o caminho do log para um diretório vazio
        import os
        os.environ["OD_LOG_DIR"] = str(tmp_path)
        try:
            result = _check_router(notifier)
            assert result.ok is True
            assert result.source == "router"
            assert "ausente" in result.detail
        finally:
            os.environ.pop("OD_LOG_DIR", None)

    def test_router_up(self, tmp_path: Path) -> None:
        """Última linha com status=up → ok=True."""
        from integrations.notifier import _check_router

        log = tmp_path / "router_monitor.log"
        log.write_text(
            '{"ts":"2026-09-18T08:00:00Z","local":"2026-09-18 05:00:00 -0300",'
            '"gateway":"192.168.0.1","status":"up","latency_ms":1.2}\n'
        )
        notifier = make_notifier(orch(OnlineProvider()))
        import os
        os.environ["OD_LOG_DIR"] = str(tmp_path)
        try:
            result = _check_router(notifier)
            assert result.ok is True
            assert "Roteador OK" in result.detail
            assert "1.2" in result.detail
        finally:
            os.environ.pop("OD_LOG_DIR", None)

    def test_router_down(self, tmp_path: Path) -> None:
        """Última linha com status=down → ok=False, WARN, key router:down."""
        from integrations.notifier import _check_router

        log = tmp_path / "router_monitor.log"
        log.write_text(
            '{"ts":"2026-09-18T08:00:00Z","local":"2026-09-18 05:00:00 -0300",'
            '"gateway":"192.168.0.1","status":"down","latency_ms":2001, '
            '"detail":"ping_failed"}\n'
        )
        notifier = make_notifier(orch(OnlineProvider()))
        import os
        os.environ["OD_LOG_DIR"] = str(tmp_path)
        try:
            result = _check_router(notifier)
            assert result.ok is False
            assert result.severity == SEVERITY_WARN
            assert result.key == "router:down"
            assert "Roteador fora" in result.detail
            assert "ping_failed" in result.detail
        finally:
            os.environ.pop("OD_LOG_DIR", None)

    def test_router_down_multiplas_linhas(self, tmp_path: Path) -> None:
        """Lê só a última linha — up antes, down agora = down."""
        from integrations.notifier import _check_router

        log = tmp_path / "router_monitor.log"
        log.write_text(
            '{"ts":"2026-09-18T07:59:00Z","local":"2026-09-18 04:59:00 -0300",'
            '"gateway":"192.168.0.1","status":"up","latency_ms":1.0}\n'
            '{"ts":"2026-09-18T08:00:00Z","local":"2026-09-18 05:00:00 -0300",'
            '"gateway":"192.168.0.1","status":"down","latency_ms":2001, '
            '"detail":"ping_failed"}\n'
        )
        notifier = make_notifier(orch(OnlineProvider()))
        import os
        os.environ["OD_LOG_DIR"] = str(tmp_path)
        try:
            result = _check_router(notifier)
            assert result.ok is False
            assert result.key == "router:down"
        finally:
            os.environ.pop("OD_LOG_DIR", None)

    def test_router_log_vazio(self, tmp_path: Path) -> None:
        """Log existe mas vazio → ok=True (sem dados)."""
        from integrations.notifier import _check_router

        log = tmp_path / "router_monitor.log"
        log.write_text("")
        notifier = make_notifier(orch(OnlineProvider()))
        import os
        os.environ["OD_LOG_DIR"] = str(tmp_path)
        try:
            result = _check_router(notifier)
            assert result.ok is True
            assert "vazio" in result.detail
        finally:
            os.environ.pop("OD_LOG_DIR", None)

    def test_router_log_malformado(self, tmp_path: Path) -> None:
        """Log com JSON inválido → ok=True (não derruba o notifier)."""
        from integrations.notifier import _check_router

        log = tmp_path / "router_monitor.log"
        log.write_text("nao eh json\n")
        notifier = make_notifier(orch(OnlineProvider()))
        import os
        os.environ["OD_LOG_DIR"] = str(tmp_path)
        try:
            result = _check_router(notifier)
            assert result.ok is True
            assert "erro ao ler" in result.detail
        finally:
            os.environ.pop("OD_LOG_DIR", None)

# ===========================================================================
# Observabilidade / Alertas Telegram — item 3.6 do TODO (2026-10-16)
# ===========================================================================

def _agregado(status: str, falhas: dict) -> dict:
    """Agregado no formato exato do HealthMonitor.health().

    `falhas` mapeia nome do check → (ok, critical) — só o que interessa
    ao caso de teste entra no dicionário.
    """
    checks = {
        nome: {
            "ok": ok,
            "status": "up" if ok else ("down" if crit else "degraded"),
            "detail": "",
            "latency_ms": 0.1,
            "critical": crit,
        }
        for nome, (ok, crit) in falhas.items()
    }
    return {"ok": status == "up", "status": status, "checks": checks,
            "ts": 0.0}


class _Saude:
    """HealthMonitor fake: devolve a sequência de agregados (último repete)."""

    def __init__(self, *agregados: dict) -> None:
        self._agregados = list(agregados)
        self.chamadas = 0

    async def health(self) -> dict:
        idx = min(self.chamadas, len(self._agregados) - 1)
        self.chamadas += 1
        return self._agregados[idx]


class TestPonteDeSaude:
    """`/health` degraded → alerta no Telegram (ponte HealthMonitor→notifier).

    O gap medido em 16/10: o notifier conhecia orchestrator/llm/disco/
    loops/restart/router/tools, mas NÃO os outros 11 checks do /health —
    audit, metrics, database, mqtt, perception e auto_update degradavam
    sem ninguém receber nada.
    """

    @pytest.mark.asyncio
    async def test_sem_monitor_a_sonda_fica_fora(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        assert "_check_health" not in notifier.snapshot()["checks"]

    @pytest.mark.asyncio
    async def test_degraded_alerta_depois_do_delay(self) -> None:
        clock = _Clock()
        saude = _Saude(_agregado("degraded", {"database": (False, False)}))
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 health=saude)
        # 1º tick: problema registrado mas ainda abaixo dos 120s
        primeiro = await notifier.tick()
        assert "health:degraded" not in [a.key for a in primeiro]
        # Passa do delay → warn com o nome do check quebrado
        clock.advance(HEALTH_DEGRADADO_APOS_S + 1)
        segundo = await notifier.tick()
        alerta = next(a for a in segundo if a.key == "health:degraded")
        assert alerta.severity == SEVERITY_WARN
        assert "/health degraded" in alerta.detail
        assert "database" in alerta.detail

    @pytest.mark.asyncio
    async def test_quando_volta_ao_up_limpa_o_problema(self) -> None:
        clock = _Clock()
        saude = _Saude(
            _agregado("degraded", {"audit": (False, False)}),
            _agregado("degraded", {"audit": (False, False)}),
            _agregado("up", {}),
        )
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 health=saude)
        await notifier.tick()                      # registra (abaixo do delay)
        clock.advance(HEALTH_DEGRADADO_APOS_S + 1)
        assert [a.key for a in await notifier.tick()] == ["health:degraded"]
        clock.advance(60)
        assert await notifier.tick() == []         # agregado voltou ao up
        assert "health:degraded" not in notifier.snapshot()["active_problems"]
        assert saude.chamadas == 3

    @pytest.mark.asyncio
    async def test_falha_so_de_tools_nao_duplica_mensagem(self) -> None:
        # tool_kiwix fora já grita pela sonda dedicada `tool:*`
        # (emit_after 120s) — o agregado não repete a mesma queda.
        clock = _Clock()
        saude = _Saude(_agregado("degraded", {"tool_kiwix": (False, False)}))
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 health=saude)
        await notifier.tick()
        clock.advance(HEALTH_DEGRADADO_APOS_S + 1)
        alerts = await notifier.tick()
        assert [a.key for a in alerts if a.key.startswith("health")] == []

    @pytest.mark.asyncio
    async def test_dedupe_lista_só_o_que_ninguém_cobre(self) -> None:
        clock = _Clock()
        saude = _Saude(_agregado("degraded", {
            "tool_kiwix": (False, False),
            "database": (False, False),
        }))
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 health=saude)
        await notifier.tick()
        clock.advance(HEALTH_DEGRADADO_APOS_S + 1)
        alerts = await notifier.tick()
        alerta = next(a for a in alerts if a.key == "health:degraded")
        assert "database" in alerta.detail
        assert "kiwix" not in alerta.detail          # já coberta por tool:*
        assert "2 check(s) fora" in alerta.detail    # total honesto

    @pytest.mark.asyncio
    async def test_down_critico_grita_na_hora(self) -> None:
        clock = _Clock()
        saude = _Saude(_agregado("down", {"api_core": (False, True)}))
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 health=saude)
        alerts = await notifier.tick()          # sem avanço: down não espera
        alerta = next(a for a in alerts if a.key == "health:down")
        assert alerta.severity == SEVERITY_CRIT
        assert alerta.detail.startswith("/health down")

    @pytest.mark.asyncio
    async def test_down_só_por_check_coberta_nao_duplica(self) -> None:
        # status down veio do llm (crítica) — _check_llm já grita sozinha
        clock = _Clock()
        saude = _Saude(_agregado("down", {"llm": (False, True)}))
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 health=saude)
        alerts = await notifier.tick()
        assert [a.key for a in alerts if a.key.startswith("health")] == []

    @pytest.mark.asyncio
    async def test_monitor_quebrado_nao_derruba_o_tick(self) -> None:
        class _Quebrado:
            async def health(self) -> dict:
                raise RuntimeError("boom")

        notifier = make_notifier(orch(OnlineProvider()), health=_Quebrado())
        alerts = await notifier.tick()          # não pode levantar exceção
        assert alerts == []
        metrics = notifier.metrics.snapshot()
        assert metrics["errors"] == 1
        assert metrics["checks_run"] == 5       # as outras 5 sondas seguiram

    @pytest.mark.asyncio
    async def test_ponte_roda_depois_das_tools(self) -> None:
        """Ordem do tick: tools antes do agregado (o cache de 10s é deles)."""
        class _Tools:
            @staticmethod
            def estado() -> list:
                return []

        notifier = make_notifier(
            orch(OnlineProvider()),
            health=_Saude(_agregado("up", {})),
            nomad_tools=_Tools(),
        )
        nomes = notifier.snapshot()["checks"]
        assert nomes.index("_check_tools") < nomes.index("_check_health")
        assert nomes[-1] == "_check_health"


class TestSondaNRestarts:
    """NRestarts do systemd → alerta de queda anormal (item 3.6 do TODO).

    `NRestarts` sobe só quando o systemd ressuscita o serviço depois de
    uma queda anormal — um restart manual zera. Foi o sinal que faltava:
    o od-core podia cair e voltar sozinho que o dono não recebia nada.
    """

    @pytest.mark.asyncio
    async def test_sem_fn_a_sonda_fica_fora(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()))
        assert "_check_nrestarts" not in notifier.snapshot()["checks"]

    @pytest.mark.asyncio
    async def test_zero_nao_alerta(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()), nrestarts=lambda: 0)
        assert await notifier.tick() == []

    @pytest.mark.asyncio
    async def test_reinicio_automatico_alerta_warn(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()), nrestarts=lambda: 1)
        alerts = await notifier.tick()
        assert [a.key for a in alerts] == ["systemd:nrestarts"]
        assert alerts[0].severity == SEVERITY_WARN
        assert "reiniciado 1x pelo systemd" in alerts[0].detail
        assert "NRestarts=1" in alerts[0].detail
        assert "od-core.service" in alerts[0].detail

    @pytest.mark.asyncio
    async def test_laco_de_falha_vira_critico(self) -> None:
        notifier = make_notifier(
            orch(OnlineProvider()),
            nrestarts=lambda: CRASH_LOOP_RESTARTS,
            unidade="od-outro.service",
        )
        alerts = await notifier.tick()
        assert alerts[0].severity == SEVERITY_CRIT
        assert "od-outro.service" in alerts[0].detail
        # logo abaixo do limiar da casa (3) continua warn
        quase = make_notifier(orch(OnlineProvider()),
                              nrestarts=lambda: CRASH_LOOP_RESTARTS - 1)
        assert (await quase.tick())[0].severity == SEVERITY_WARN

    @pytest.mark.asyncio
    async def test_indisponivel_nunca_alerta(self) -> None:
        notifier = make_notifier(orch(OnlineProvider()),
                                 nrestarts=lambda: None)
        assert await notifier.tick() == []

    @pytest.mark.asyncio
    async def test_fn_quebrada_nao_derruba_o_tick(self) -> None:
        def _explode():
            raise OSError("sem systemd")

        notifier = make_notifier(orch(OnlineProvider()), nrestarts=_explode)
        assert await notifier.tick() == []
        assert notifier.metrics.snapshot()["errors"] == 0

    @pytest.mark.asyncio
    async def test_quando_zera_limpa_o_problema(self) -> None:
        valor = {"n": 1}
        notifier = make_notifier(orch(OnlineProvider()),
                                 nrestarts=lambda: valor["n"])
        assert [a.key for a in await notifier.tick()] == ["systemd:nrestarts"]
        valor["n"] = 0
        assert await notifier.tick() == []
        assert "systemd:nrestarts" not in (
            notifier.snapshot()["active_problems"]
        )


class TestLeituraSystemd:
    """`nrestarts_do_systemd`: parse, ausência do binário, timeout."""

    def test_parseia_valor_e_monta_o_comando(self, monkeypatch) -> None:
        from types import SimpleNamespace

        import integrations.notifier as mod

        vistos: dict = {}

        class _Proc:
            stdout = "7\n"

        def _run(cmd, **kwargs):
            vistos["cmd"] = cmd
            vistos["timeout"] = kwargs.get("timeout")
            return _Proc()

        monkeypatch.setattr(mod, "subprocess", SimpleNamespace(run=_run))
        assert mod.nrestarts_do_systemd("od-core.service") == 7
        assert vistos["cmd"][:3] == ["systemctl", "--user", "show"]
        assert vistos["cmd"][3] == "od-core.service"
        assert "NRestarts" in vistos["cmd"]
        assert vistos["timeout"] == mod.NRESTARTS_TIMEOUT_S

    def test_sem_binario_ou_timeout_devolve_none(self, monkeypatch) -> None:
        from types import SimpleNamespace

        import subprocess as _sub

        import integrations.notifier as mod

        def _ausente(*_args, **_kwargs):
            raise FileNotFoundError("systemctl")

        monkeypatch.setattr(
            mod, "subprocess",
            SimpleNamespace(run=_ausente, SubprocessError=_sub.SubprocessError),
        )
        assert mod.nrestarts_do_systemd("od-core.service") is None

        def _demorou(*_args, **_kwargs):
            raise _sub.TimeoutExpired(cmd="systemctl", timeout=5)

        monkeypatch.setattr(
            mod, "subprocess",
            SimpleNamespace(run=_demorou, SubprocessError=_sub.SubprocessError),
        )
        assert mod.nrestarts_do_systemd("od-core.service") is None

    def test_valor_nao_numerico_devolve_none(self, monkeypatch) -> None:
        from types import SimpleNamespace

        import integrations.notifier as mod

        class _Proc:
            stdout = "NRestarts=?\n"

        monkeypatch.setattr(
            mod, "subprocess", SimpleNamespace(run=lambda *a, **k: _Proc())
        )
        assert mod.nrestarts_do_systemd("od-core.service") is None


class TestExibicaoDoAlerta:
    """Hora na mensagem: `wall` (parede) na frente, `ts` monotônico atrás.

    Bug achado pela prova de fogo da 3.6 (16/10): `format_alert` fazia
    `time.localtime(alert.ts)` em cima do relógio monotônico — a mensagem
    no Telegram do dono saía com data tipo "(31/12 21:16)".
    """

    def test_format_alert_usa_wall_quando_existe(self) -> None:
        monotonic_bruto = 1000.0          # não é hora de parede
        alert = Alert(key="health:degraded", severity=SEVERITY_WARN,
                      title="health", detail="x", ts=monotonic_bruto,
                      wall=1_760_000_000.0)
        text = ProactiveNotifier.format_alert(alert)
        esperado = time.strftime("%d/%m %H:%M:%S",
                                 time.localtime(1_760_000_000.0))
        errado = time.strftime("%d/%m %H:%M:%S",
                               time.localtime(monotonic_bruto))
        assert esperado in text
        assert errado not in text

    def test_alert_sem_wall_nenhuma_cai_no_menos(self) -> None:
        alert = Alert(key="x", severity=SEVERITY_WARN, title="x", ts=0.0)
        assert "-" in ProactiveNotifier.format_alert(alert)

    @pytest.mark.asyncio
    async def test_emit_carimba_wall_mesmo_com_relogio_falso(self) -> None:
        clock = _Clock()                     # 1000.0 (monotônico fake)
        notifier = make_notifier(orch(OnlineProvider()), clock=clock,
                                 nrestarts=lambda: 1)
        alerts = await notifier.tick()
        alerta = next(a for a in alerts if a.key == "systemd:nrestarts")
        assert alerta.ts == 1000.0           # monotônico preservado
        assert alerta.wall > 1_600_000_000   # epoch de verdade
        assert alerta.to_dict()["wall"] == alerta.wall


# ---------------------------------------------------------------------------
# API — bloco notifier no /dashboard/stats (pedido do dono, 2026-10-16)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _serve_stats():
    """Sobe APIServer sob demanda (mesmo padrão do test_api.py)."""
    from integrations.api import APIServer

    servidores = []

    def _start(orch_, *, config=None):
        from integrations.api import APIConfig

        cfg = config or APIConfig(port=0, rate_limit_max=0)
        srv = APIServer(orch_, config=cfg)
        srv.serve_background()
        servidores.append(srv)
        return srv

    yield _start
    for srv in servidores:
        try:
            srv.stop()
        except Exception:  # pragma: no cover — teardown defensivo
            pass


class TestStatsDoNotifier:
    """Métricas do notifier expostas no /dashboard/stats.

    O dono vê no Status (e no card "Alertas" do /admin) quantos alertas
    saíram, quantos o anti-spam bloqueou e quantos erros o tick teve —
    sem abrir o journal. None (notifier desligado) = bloco ausente.
    """

    def test_sem_notifier_o_bloco_nao_aparece(self, _serve_stats,
                                              tmp_path) -> None:
        from tests.test_api import _json_response, _request, make_orch

        srv = _serve_stats(make_orch(tmp_path))
        resposta = _request(srv.bound_port, "GET", "/dashboard/stats")
        dados = _json_response(resposta)
        assert resposta[0] == 200
        assert "notifier" not in dados
        assert b'"notifier"' not in resposta[1]

    def test_com_notifier_traz_os_contadores(self, _serve_stats,
                                             tmp_path) -> None:
        from tests.test_api import _json_response, _request, make_orch
        from integrations.api import APIConfig

        notif = ProactiveNotifier()
        notif.metrics.ticks = 3
        notif.metrics.alerts_emitted = 2
        notif.metrics.alerts_blocked = 5
        notif.metrics.errors = 1
        cfg = APIConfig(port=0, rate_limit_max=0, notifier=notif)
        srv = _serve_stats(make_orch(tmp_path), config=cfg)
        resposta = _request(srv.bound_port, "GET", "/dashboard/stats")
        status, body, _headers = resposta
        dados = _json_response(resposta)
        assert status == 200
        assert b'"notifier"' in body
        assert dados["notifier"] == {
            "ticks": 3,
            "checks_run": 0,
            "problems": 0,
            "alerts_emitted": 2,
            "alerts_blocked": 5,
            "errors": 1,
        }
        # card "Alertas" do painel — a linha referencia stats.notifier
        status, corpo_admin, _ = _request(srv.bound_port, "GET", "/admin")
        assert status == 200
        assert b"stats.notifier" in corpo_admin
        notif.stop()
