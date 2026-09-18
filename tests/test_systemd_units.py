"""
OMEGA DRAKON * TESTS
Modulo: tests/test_systemd_units.py
Descricao: Testes de integridade das units systemd do OmegaDrakon —
           valida estrutura, sandboxing e configuração das units do núcleo
           (od-core, od-llm, od-control-bridge) e o timer do monitor do
           roteador (router-monitor.service/timer).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path

import pytest


SYSTEMD_DIR = Path(__file__).resolve().parent.parent / "runtime" / "systemd"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def core_unit() -> str:
    return (SYSTEMD_DIR / "od-core.service").read_text(encoding="utf-8")


@pytest.fixture()
def llm_unit() -> str:
    return (SYSTEMD_DIR / "od-llm.service").read_text(encoding="utf-8")


@pytest.fixture()
def bridge_unit() -> str:
    return (SYSTEMD_DIR / "od-control-bridge.service").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# od-core.service
# ---------------------------------------------------------------------------


class TestOdCoreService:
    def test_file_exists(self) -> None:
        assert (SYSTEMD_DIR / "od-core.service").exists()

    def test_has_description(self, core_unit: str) -> None:
        assert "Description=" in core_unit

    def test_runs_launcher_all(self, core_unit: str) -> None:
        assert "runtime.launcher all" in core_unit

    def test_depends_on_llm(self, core_unit: str) -> None:
        assert "od-llm.service" in core_unit

    def test_restart_on_failure(self, core_unit: str) -> None:
        assert "Restart=on-failure" in core_unit

    def test_environment_file(self, core_unit: str) -> None:
        assert "EnvironmentFile=" in core_unit

    def test_sandboxing_no_new_privileges(self, core_unit: str) -> None:
        assert "NoNewPrivileges=true" in core_unit

    def test_sandboxing_protect_system(self, core_unit: str) -> None:
        assert "ProtectSystem=" in core_unit

    def test_sandboxing_protect_kernel(self, core_unit: str) -> None:
        assert "ProtectKernelTunables=true" in core_unit

    def test_memory_limit(self, core_unit: str) -> None:
        assert "MemoryMax=" in core_unit

    def test_not_running_as_root(self, core_unit: str) -> None:
        # Deve ter User= especificado (nunca rodar como root)
        assert "User=" in core_unit

    def test_wanted_by_default(self, core_unit: str) -> None:
        assert "WantedBy=default.target" in core_unit

    def test_journald_logging(self, core_unit: str) -> None:
        assert "StandardOutput=journal" in core_unit

    def test_read_write_data_dir(self, core_unit: str) -> None:
        assert "ReadWritePaths=" in core_unit


# ---------------------------------------------------------------------------
# od-llm.service
# ---------------------------------------------------------------------------


class TestOdLlmService:
    def test_file_exists(self) -> None:
        assert (SYSTEMD_DIR / "od-llm.service").exists()

    def test_runs_llama_server(self, llm_unit: str) -> None:
        assert "llama-server" in llm_unit

    def test_restart_on_failure(self, llm_unit: str) -> None:
        assert "Restart=on-failure" in llm_unit

    def test_wanted_by_default(self, llm_unit: str) -> None:
        assert "WantedBy=default.target" in llm_unit


# ---------------------------------------------------------------------------
# od-control-bridge.service
# ---------------------------------------------------------------------------


class TestControlBridgeService:
    def test_file_exists(self) -> None:
        assert (SYSTEMD_DIR / "od-control-bridge.service").exists()

    def test_runs_bridge(self, bridge_unit: str) -> None:
        assert "bridge.py" in bridge_unit

    def test_depends_on_core(self, bridge_unit: str) -> None:
        assert "od-core.service" in bridge_unit

    def test_restart_on_failure(self, bridge_unit: str) -> None:
        assert "Restart=on-failure" in bridge_unit

    def test_wanted_by_default(self, bridge_unit: str) -> None:
        assert "WantedBy=default.target" in bridge_unit

    def test_environment_file(self, bridge_unit: str) -> None:
        assert "EnvironmentFile=" in bridge_unit


# ---------------------------------------------------------------------------
# router-monitor.service / router-monitor.timer
# ---------------------------------------------------------------------------


class TestRouterMonitorUnits:
    """Monitor do roteador: service oneshot disparado por timer de 1 minuto."""

    def test_files_exist(self) -> None:
        assert (SYSTEMD_DIR / "router-monitor.service").exists()
        assert (SYSTEMD_DIR / "router-monitor.timer").exists()

    def test_service_runs_script_once(self) -> None:
        unit = (SYSTEMD_DIR / "router-monitor.service").read_text(encoding="utf-8")
        assert "router_monitor.sh --once" in unit
        assert "/bin/bash" in unit

    def test_service_uses_repo_working_directory(self) -> None:
        unit = (SYSTEMD_DIR / "router-monitor.service").read_text(encoding="utf-8")
        assert "WorkingDirectory=/home/alex/OmegaDrakon" in unit

    def test_service_does_not_restart(self) -> None:
        # oneshot por minuto: Restart= aqui só multiplicaria a execução.
        unit = (SYSTEMD_DIR / "router-monitor.service").read_text(encoding="utf-8")
        assert "Restart=" not in unit

    def test_service_journal_identifier(self) -> None:
        unit = (SYSTEMD_DIR / "router-monitor.service").read_text(encoding="utf-8")
        assert "SyslogIdentifier=router-monitor" in unit

    def test_timer_fires_every_minute(self) -> None:
        timer = (SYSTEMD_DIR / "router-monitor.timer").read_text(encoding="utf-8")
        assert "OnBootSec=1min" in timer
        assert "OnUnitActiveSec=1min" in timer

    def test_timer_install_target(self) -> None:
        timer = (SYSTEMD_DIR / "router-monitor.timer").read_text(encoding="utf-8")
        assert "WantedBy=timers.target" in timer


# ---------------------------------------------------------------------------
# install-user.sh
# ---------------------------------------------------------------------------


class TestInstallScript:
    def test_file_exists(self) -> None:
        assert (SYSTEMD_DIR / "install-user.sh").exists()

    def test_installs_all_three_units(self) -> None:
        script = (SYSTEMD_DIR / "install-user.sh").read_text(encoding="utf-8")
        assert "od-llm.service" in script
        assert "od-core.service" in script
        assert "od-control-bridge.service" in script

    def test_daemon_reload(self) -> None:
        script = (SYSTEMD_DIR / "install-user.sh").read_text(encoding="utf-8")
        assert "daemon-reload" in script

    def test_enable_services(self) -> None:
        script = (SYSTEMD_DIR / "install-user.sh").read_text(encoding="utf-8")
        assert "systemctl --user enable" in script

    def test_mentions_linger(self) -> None:
        script = (SYSTEMD_DIR / "install-user.sh").read_text(encoding="utf-8")
        assert "loginctl enable-linger" in script

    def test_installs_router_monitor_units(self) -> None:
        script = (SYSTEMD_DIR / "install-user.sh").read_text(encoding="utf-8")
        assert "router-monitor.service" in script
        assert "router-monitor.timer" in script

    def test_enables_router_monitor_timer(self) -> None:
        # Quem manda é o timer (o service é oneshot por minuto).
        script = (SYSTEMD_DIR / "install-user.sh").read_text(encoding="utf-8")
        assert "enable --now router-monitor.timer" in script
