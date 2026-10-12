"""
OMEGA DRAKON • TESTS
Módulo: tests/test_nomad_tools_actions.py
Descrição: Testes funcionais das actions nomad_tools_* (ferramentas Nômade
            absorvidas do Project NOMAD) — validação de parâmetros, degradação
            graciosa quando docker/tailscale indisponíveis, e integração com
            Action Registry.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - tools/actions/actions.py (nomad_tools_up/down/status/logs/restart/tailscale_serve/zim_download/vaultwarden_setup)
  - docker/tools-compose.yaml (a2bba40)
  - docs/ANALISE_PROJECT_NOMAD.md (DECISÃO FINAL 12/10)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.actions import (
    ACTIONS_COUNT,
    CATALOG,
    CATEGORIES,
    build_registry,
    register_all,
)
from tools.registry import ActionRegistry
from tools.actions.actions import (
    nomad_tools_up,
    nomad_tools_down,
    nomad_tools_status,
    nomad_tools_logs,
    nomad_tools_restart,
    nomad_tools_tailscale_serve,
    nomad_wikipedia_zim_download,
    nomad_vaultwarden_setup,
    _NOMAD_SERVICES,
    _NOMAD_PORTS,
    NOMAD_COMPOSE_FILE,
    NOMAD_TOOLS_DIR,
    _compose,
)


EXPECTED_NOMAD_ACTIONS = 8


class TestNomadToolsCatalog:
    """Validação do catálogo de actions Nômade."""

    def test_nomad_category_count(self) -> None:
        """Categoria 'nomad' tem 8 actions registradas."""
        assert CATEGORIES.get("nomad", 0) == EXPECTED_NOMAD_ACTIONS
        nomad_names = [s["name"] for s in CATALOG if s["category"] == "nomad"]
        assert len(nomad_names) == EXPECTED_NOMAD_ACTIONS
        expected = {
            "nomad_tools_up",
            "nomad_tools_down",
            "nomad_tools_status",
            "nomad_tools_logs",
            "nomad_tools_restart",
            "nomad_tools_tailscale_serve",
            "nomad_wikipedia_zim_download",
            "nomad_vaultwarden_setup",
        }
        assert set(nomad_names) == expected

    def test_nomad_actions_in_registry(self) -> None:
        """Todas as 8 actions nomad registradas no ActionRegistry."""
        registry = build_registry()
        for name in [
            "nomad_tools_up",
            "nomad_tools_down",
            "nomad_tools_status",
            "nomad_tools_logs",
            "nomad_tools_restart",
            "nomad_tools_tailscale_serve",
            "nomad_wikipedia_zim_download",
            "nomad_vaultwarden_setup",
        ]:
            action = registry.get(name)
            assert action is not None, f"{name} não registrada"
            assert action.category == "nomad"
            assert action.permission == name


class TestNomadToolsConstants:
    """Validação das constantes de serviços e portas."""

    def test_services_list(self) -> None:
        """Lista de serviços bate com o compose (9 containers)."""
        assert len(_NOMAD_SERVICES) == 9
        expected = {
            "kiwix", "cyberchef", "it-tools", "flatnotes",
            "stirling-pdf", "filebrowser", "calibre-web",
            "homebox", "vaultwarden"
        }
        assert set(_NOMAD_SERVICES) == expected

    def test_ports_mapping(self) -> None:
        """Mapeamento de portas completo e sem duplicatas."""
        assert len(_NOMAD_PORTS) == 9
        assert set(_NOMAD_PORTS.keys()) == set(_NOMAD_SERVICES)
        assert len(set(_NOMAD_PORTS.values())) == 9  # portas únicas
        # Verificar portas conhecidas
        assert _NOMAD_PORTS["kiwix"] == 8090
        assert _NOMAD_PORTS["vaultwarden"] == 8480
        assert _NOMAD_PORTS["flatnotes"] == 8200

    def test_paths(self) -> None:
        """Caminhos do compose e diretório de ferramentas."""
        assert NOMAD_COMPOSE_FILE == "/home/alex/OmegaDrakon/docker/tools-compose.yaml"
        assert NOMAD_TOOLS_DIR == "/home/alex/omegadrakon-tools"


class TestNomadComposeHelper:
    """Testes do helper _compose (mock de docker compose)."""

    @patch("tools.actions.actions._run")
    def test_compose_success(self, mock_run) -> None:
        mock_run.return_value = (0, "up -d done", "")
        result = _compose(["up", "-d"])
        assert result["ok"] is True
        assert result["output"] == "up -d done"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[:4] == ["docker", "compose", "-f", NOMAD_COMPOSE_FILE]

    @patch("tools.actions.actions._run")
    def test_compose_failure(self, mock_run) -> None:
        mock_run.return_value = (1, "", "error: no such service")
        result = _compose(["ps"])
        assert result["ok"] is False
        assert "no such service" in result["error"]
        assert result["tool"] == "docker_compose"


class TestNomadToolsUpDown:
    """Testes de nomad_tools_up e nomad_tools_down."""

    @patch("tools.actions.actions._compose")
    def test_nomad_tools_up(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": True, "output": "started"}
        result = nomad_tools_up()
        assert result["ok"] is True
        mock_compose.assert_called_once_with(["up", "-d"], timeout=120.0)

    @patch("tools.actions.actions._compose")
    def test_nomad_tools_down(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": True, "output": "stopped"}
        result = nomad_tools_down()
        assert result["ok"] is True
        mock_compose.assert_called_once_with(["down"], timeout=60.0)


class TestNomadToolsStatus:
    """Testes de nomad_tools_status."""

    @patch("tools.actions.actions._compose")
    def test_nomad_tools_status_success(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": True, "output": '{"Name":"od-kiwix","State":"running"}'}
        result = nomad_tools_status()
        assert result["ok"] is True
        mock_compose.assert_called_once_with(["ps", "--format", "json"])

    @patch("tools.actions.actions._compose")
    def test_nomad_tools_status_failure(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": False, "error": "compose not found"}
        result = nomad_tools_status()
        assert result["ok"] is False
        assert "compose not found" in result["error"]


class TestNomadToolsLogs:
    """Testes de nomad_tools_logs."""

    @patch("tools.actions.actions._compose")
    def test_logs_all_services(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": True, "output": "logs..."}
        result = nomad_tools_logs()
        assert result["ok"] is True
        mock_compose.assert_called_once_with(["logs", "--tail", "100"], timeout=30.0)

    @patch("tools.actions.actions._compose")
    def test_logs_specific_service(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": True, "output": "kiwix logs"}
        result = nomad_tools_logs(service="kiwix", lines=50)
        assert result["ok"] is True
        mock_compose.assert_called_once_with(["logs", "--tail", "50", "kiwix"], timeout=30.0)

    def test_logs_invalid_service(self) -> None:
        result = nomad_tools_logs(service="inexistente")
        assert result["ok"] is False
        assert result["error"] == "servico_invalido"
        assert "inexistente" in result["message"]

    def test_logs_invalid_lines(self) -> None:
        with pytest.raises(ValueError, match="lines deve ser > 0"):
            nomad_tools_logs(lines=0)


class TestNomadToolsRestart:
    """Testes de nomad_tools_restart."""

    @patch("tools.actions.actions._compose")
    def test_restart_valid_service(self, mock_compose) -> None:
        mock_compose.return_value = {"ok": True, "output": "restarted"}
        result = nomad_tools_restart("vaultwarden")
        assert result["ok"] is True
        mock_compose.assert_called_once_with(["restart", "vaultwarden"], timeout=60.0)

    def test_restart_invalid_service(self) -> None:
        result = nomad_tools_restart("nao_existe")
        assert result["ok"] is False
        assert result["error"] == "servico_invalido"


class TestNomadToolsTailscaleServe:
    """Testes de nomad_tools_tailscale_serve."""

    @patch("tools.actions.actions._run")
    def test_tailscale_serve_status(self, mock_run) -> None:
        mock_run.return_value = (0, "http://127.0.0.1:8090\nhttp://127.0.0.1:8480", "")
        result = nomad_tools_tailscale_serve(action="status")
        assert result["ok"] is True
        assert "8090" in result["output"]
        mock_run.assert_called_once_with(["tailscale", "serve", "status"])

    @patch("tools.actions.actions._run")
    def test_tailscale_serve_status_failure(self, mock_run) -> None:
        mock_run.return_value = (1, "", "tailscale not installed")
        result = nomad_tools_tailscale_serve(action="status")
        assert result["ok"] is False
        assert result["error"] == "tailscale not installed"

    @patch("tools.actions.actions._run")
    def test_tailscale_serve_up_all(self, mock_run) -> None:
        mock_run.return_value = (0, "started", "")
        result = nomad_tools_tailscale_serve(action="up")
        assert result["ok"] is True
        assert len(result["results"]) == 9
        for r in result["results"]:
            assert r["ok"] is True
            assert r["port"] in _NOMAD_PORTS.values()

    @patch("tools.actions.actions._run")
    def test_tailscale_serve_up_one(self, mock_run) -> None:
        mock_run.return_value = (0, "started", "")
        result = nomad_tools_tailscale_serve(service="kiwix", action="up")
        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["service"] == "kiwix"
        assert result["results"][0]["port"] == 8090

    @patch("tools.actions.actions._run")
    def test_tailscale_serve_down(self, mock_run) -> None:
        mock_run.return_value = (0, "stopped", "")
        result = nomad_tools_tailscale_serve(service="flatnotes", action="down")
        assert result["ok"] is True
        assert result["results"][0]["service"] == "flatnotes"
        mock_run.assert_called_with(
            ["tailscale", "serve", "--bg", "off", "http://127.0.0.1:8200"]
        )

    def test_tailscale_serve_invalid_action(self) -> None:
        result = nomad_tools_tailscale_serve(action="invalid")
        assert result["ok"] is False
        assert result["error"] == "acao_invalida"

    def test_tailscale_serve_invalid_service(self) -> None:
        result = nomad_tools_tailscale_serve(service="invalido", action="up")
        assert result["ok"] is False
        assert result["error"] == "servico_invalido"


class TestNomadWikipediaZimDownload:
    """Testes de nomad_wikipedia_zim_download."""

    @patch("tools.actions.actions._run")
    @patch("tools.actions.actions.os.path.getsize")
    @patch("tools.actions.actions.os.path.exists")
    @patch("tools.actions.actions.os.makedirs")
    def test_zim_download_success(self, mock_makedirs, mock_exists, mock_getsize, mock_run) -> None:
        mock_run.return_value = (0, "downloaded", "")
        mock_exists.return_value = True
        # 12.5 GB in bytes (using 1024^3 as the code does)
        size_bytes = int(12.5 * (1024 ** 3))
        mock_getsize.return_value = size_bytes
        result = nomad_wikipedia_zim_download()
        assert result["ok"] is True
        assert result["dest"].endswith("wikipedia.zim")
        assert result["size_gb"] == round(size_bytes / (1024**3), 2)
        mock_makedirs.assert_called_once()

    @patch("tools.actions.actions._run")
    @patch("tools.actions.actions.os.makedirs")
    def test_zim_download_custom_url_dest(self, mock_makedirs, mock_run) -> None:
        mock_run.return_value = (0, "ok", "")
        mock_makedirs.return_value = None
        with patch("tools.actions.actions.os.path.getsize", return_value=5_000_000_000), \
             patch("tools.actions.actions.os.path.exists", return_value=True):
            result = nomad_wikipedia_zim_download(
                url="https://custom.mirror/wikipedia_pt.zim",
                dest="/custom/path/wiki.zim"
            )
        assert result["ok"] is True
        assert result["dest"] == "/custom/path/wiki.zim"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "custom.mirror" in args[-1]

    @patch("tools.actions.actions._run")
    def test_zim_download_failure(self, mock_run) -> None:
        mock_run.return_value = (1, "", "404 Not Found")
        with patch("tools.actions.actions.os.makedirs"):
            result = nomad_wikipedia_zim_download()
        assert result["ok"] is False
        assert result["error"] == "download_falhou"
        assert "404" in result["message"]


class TestNomadVaultwardenSetup:
    """Testes de nomad_vaultwarden_setup."""

    @patch("tools.actions.actions.nomad_tools_status")
    @patch("urllib.request.urlopen")
    @patch("json.loads")
    def test_vaultwarden_setup_with_credentials(self, mock_json_loads, mock_urlopen, mock_status) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"token": "abc123"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        mock_json_loads.return_value = {"token": "abc123"}

        result = nomad_vaultwarden_setup(
            admin_email="admin@test.com",
            admin_password="senha123",
            disable_signups=True
        )
        assert result["ok"] is True
        assert "Conta admin criada" in result["message"]
        assert result["token"] == "abc123"

    @patch("tools.actions.actions.nomad_tools_status")
    def test_vaultwarden_setup_container_not_running(self, mock_status) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden exited"}
        result = nomad_vaultwarden_setup()
        assert result["ok"] is False
        assert result["error"] == "container_nao_rodando"

    @patch("tools.actions.actions.nomad_tools_status")
    @patch("urllib.request.urlopen")
    def test_vaultwarden_setup_api_failure(self, mock_urlopen, mock_status) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        mock_urlopen.side_effect = Exception("connection refused")
        result = nomad_vaultwarden_setup(admin_email="a@b.com", admin_password="pass")
        assert result["ok"] is False
        assert result["error"] == "criar_conta_falhou"

    @patch("tools.actions.actions.nomad_tools_status")
    @patch("urllib.request.urlopen")
    @patch("json.loads")
    def test_vaultwarden_setup_no_credentials(self, mock_json_loads, mock_urlopen, mock_status) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        result = nomad_vaultwarden_setup(disable_signups=False)
        assert result["ok"] is True
        assert result["message"] == "Vaultwarden pronto. Acesse via tailscale serve https://127.0.0.1:8480"
        assert result["token"] is None
        mock_urlopen.assert_not_called()
        mock_json_loads.assert_not_called()


class TestNomadToolsIntegration:
    """Testes de integração via ActionRegistry."""

    def _registry(self) -> ActionRegistry:
        return build_registry()

    @pytest.mark.asyncio
    async def test_nomad_tools_up_via_registry(self) -> None:
        registry = self._registry()
        with patch("tools.actions.actions._compose", return_value={"ok": True, "output": "ok"}):
            result = await registry.execute("nomad_tools_up", role="admin")
        assert result.status == "ok"
        assert result.data["ok"] is True

    @pytest.mark.asyncio
    async def test_nomad_tools_status_via_registry(self) -> None:
        registry = self._registry()
        with patch("tools.actions.actions._compose", return_value={"ok": True, "output": "{}"}):
            result = await registry.execute("nomad_tools_status", role="admin")
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_nomad_tools_logs_via_registry(self) -> None:
        registry = self._registry()
        with patch("tools.actions.actions._compose", return_value={"ok": True, "output": "logs"}):
            result = await registry.execute(
                "nomad_tools_logs", params={"service": "kiwix", "lines": 10}, role="admin"
            )
        assert result.status == "ok"
        assert result.data["ok"] is True

    @pytest.mark.asyncio
    async def test_nomad_tools_restart_via_registry(self) -> None:
        registry = self._registry()
        with patch("tools.actions.actions._compose", return_value={"ok": True, "output": "restarted"}):
            result = await registry.execute(
                "nomad_tools_restart", params={"service": "cyberchef"}, role="admin"
            )
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_nomad_tools_tailscale_serve_via_registry(self) -> None:
        registry = self._registry()
        with patch("tools.actions.actions._run", return_value=(0, "ok", "")):
            result = await registry.execute(
                "nomad_tools_tailscale_serve", params={"service": "flatnotes", "action": "up"}, role="admin"
            )
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_nomad_wikipedia_zim_download_via_registry(self) -> None:
        registry = self._registry()
        with patch("tools.actions.actions._run", return_value=(0, "ok", "")), \
             patch("tools.actions.actions.os.makedirs"), \
             patch("tools.actions.actions.os.path.exists", return_value=True), \
             patch("tools.actions.actions.os.path.getsize", return_value=1_000_000_000):
            result = await registry.execute("nomad_wikipedia_zim_download", role="admin")
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_nomad_vaultwarden_setup_via_registry(self) -> None:
        from core.security import SecurityManager
        registry = build_registry(security=SecurityManager(mode="strict"))
        with patch("tools.actions.actions.nomad_tools_status", return_value={"ok": True, "output": "od-vaultwarden running"}), \
             patch("urllib.request.urlopen") as mock_urlopen, \
             patch("json.loads", return_value={"token": "xyz"}):
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"token": "xyz"}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = await registry.execute(
                "nomad_vaultwarden_setup",
                params={"admin_email": "a@b.com", "admin_password": "pass", "disable_signups": True},
                role="admin"
            )
        assert result.status == "ok"
        assert result.data["ok"] is True

    @pytest.mark.asyncio
    async def test_nomad_tools_denied_for_non_admin(self) -> None:
        """Actions Nômade só executam para admin (permission = nome da action)."""
        from core.security import SecurityManager
        registry = build_registry(security=SecurityManager(mode="strict"))
        with patch("tools.actions.actions._compose", return_value={"ok": True, "output": "ok"}):
            result = await registry.execute("nomad_tools_up", role="user")
        assert result.status == "denied"
        assert result.denied_by == "permission"


class TestNomadToolsDegradation:
    """Testes de degradação graciosa quando docker/tailscale indisponíveis."""

    @patch("tools.actions.actions._run")
    def test_compose_docker_not_installed(self, mock_run) -> None:
        mock_run.return_value = (127, "", "command not found: docker")
        result = nomad_tools_status()
        assert result["ok"] is False
        assert result["tool"] == "docker_compose"

    @patch("tools.actions.actions._run")
    def test_tailscale_not_installed(self, mock_run) -> None:
        mock_run.return_value = (127, "", "command not found: tailscale")
        result = nomad_tools_tailscale_serve(action="status")
        assert result["ok"] is False
        assert result["tool"] == "tailscale"


__all__ = [
    "TestNomadToolsCatalog",
    "TestNomadToolsConstants",
    "TestNomadComposeHelper",
    "TestNomadToolsUpDown",
    "TestNomadToolsStatus",
    "TestNomadToolsLogs",
    "TestNomadToolsRestart",
    "TestNomadToolsTailscaleServe",
    "TestNomadWikipediaZimDownload",
    "TestNomadVaultwardenSetup",
    "TestNomadToolsIntegration",
    "TestNomadToolsDegradation",
]