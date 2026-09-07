"""
OMEGA DRAKON * TESTS
Modulo: tests/test_setup_script.py
Descricao: Testes de integridade do script de setup do servidor
           (runtime/setup/setup-server.sh) — valida que o script
           cobre todos os itens 1.7-1.10 da v1.0.0.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path

import pytest


SETUP_DIR = Path(__file__).resolve().parent.parent / "runtime" / "setup"


@pytest.fixture()
def script() -> str:
    return (SETUP_DIR / "setup-server.sh").read_text(encoding="utf-8")


class TestSetupScript:
    def test_file_exists(self) -> None:
        assert (SETUP_DIR / "setup-server.sh").exists()

    def test_has_shebang(self, script: str) -> None:
        assert script.startswith("#!/usr/bin/env bash")

    def test_set_euo_pipefail(self, script: str) -> None:
        assert "set -euo pipefail" in script

    def test_creates_swap(self, script: str) -> None:
        assert "fallocate -l 4G /swapfile" in script
        assert "mkswap /swapfile" in script
        assert "swapon /swapfile" in script

    def test_swap_in_fstab(self, script: str) -> None:
        assert "/swapfile none swap sw 0 0" in script

    def test_swappiness(self, script: str) -> None:
        assert "vm.swappiness" in script

    def test_ufw_setup(self, script: str) -> None:
        assert "ufw allow 22/tcp" in script
        assert "ufw allow 8000/tcp" in script
        assert "ufw allow 8123/tcp" in script
        assert "ufw --force enable" in script

    def test_env_variables(self, script: str) -> None:
        assert "OD_PRESENCE_ENABLED" in script
        assert "OD_PRESENCE_POLL_S" in script
        assert "OD_HA_CREDENTIALS" in script
        assert "OD_RECOVERY_INTERVAL_S" in script
        assert "OD_SELF_REPAIR_ENABLED" in script
        assert "OD_NOTIFIER_ENABLED" in script

    def test_mount_sdb1(self, script: str) -> None:
        assert "/dev/sdb1" in script
        assert "mkfs.ext4" in script
        assert "mount /dev/sdb1" in script

    def test_fstab_sdb1(self, script: str) -> None:
        assert "/dev/sdb1 /home/alex/dados ext4" in script

    def test_idempotent(self, script: str) -> None:
        # Script deve verificar se cada item já existe antes de criar
        assert "já existe" in script or "já está" in script or "já montado" in script

    def test_summary_output(self, script: str) -> None:
        assert "Setup concluído" in script
