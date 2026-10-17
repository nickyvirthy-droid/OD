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

import base64
import hashlib
import io
import json
import subprocess
import urllib.error
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
    _vw_register_payload,
    _vw_hkdf_expand,
    _vw_decstring,
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
        """Lista de serviços bate com o compose (8 containers ativos)."""
        assert len(_NOMAD_SERVICES) == 8
        expected = {
            "kiwix", "cyberchef", "it-tools", "flatnotes",
            "stirling-pdf", "filebrowser", "calibre-web",
            "vaultwarden"
        }
        assert set(_NOMAD_SERVICES) == expected

    def test_ports_mapping(self) -> None:
        """Mapeamento de portas completo e sem duplicatas."""
        assert len(_NOMAD_PORTS) == 8
        assert set(_NOMAD_PORTS.keys()) == set(_NOMAD_SERVICES)
        assert len(set(_NOMAD_PORTS.values())) == 8  # portas únicas
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
        assert len(result["results"]) == 8
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
    """Testes de nomad_vaultwarden_setup (rota /identity + payload RegisterData
    oficial + fechamento real de signups — regressões do bug de 2026-10-15)."""

    # ---------- crypto do payload (sem rede) ----------

    def test_register_payload_formato_oficial(self) -> None:
        """Payload RegisterData: KDF, EncStrings e chaves nos formatos oficiais."""
        payload = _vw_register_payload("  Dono@Gmail.COM ", "senha-forte-9876", name="Alex")
        assert payload["email"] == "dono@gmail.com"  # normalizado
        assert payload["name"] == "Alex"
        assert payload["kdf"] == 0
        assert payload["kdfIterations"] == 600000
        # user key embrulhada: EncString tipo 2 (2.iv|data|mac)
        assert payload["key"].startswith("2.")
        assert payload["key"].count("|") == 2
        # masterPasswordHash: PBKDF2 de 1 iteração -> 32 bytes em base64
        assert len(base64.b64decode(payload["masterPasswordHash"], validate=True)) == 32
        # chave pública: SPKI DER (SEQUENCE); privada: EncString tipo 2
        pub = base64.b64decode(payload["keys"]["publicKey"], validate=True)
        assert pub[0] == 0x30
        assert payload["keys"]["encryptedPrivateKey"].startswith("2.")
        assert payload["keys"]["encryptedPrivateKey"].count("|") == 2

    def test_register_payload_roundtrip_interno(self) -> None:
        """Decifra o payload com as chaves derivadas: user key, PKCS8 e auth hash coerentes."""
        from cryptography.hazmat.primitives import serialization

        senha = "senha-forte-9876"
        payload = _vw_register_payload("dono@gmail.com", senha)
        material = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), b"dono@gmail.com", 600000, dklen=32
        )
        user_key = _vw_decstring(
            payload["key"],
            _vw_hkdf_expand(material, b"enc", 32),
            _vw_hkdf_expand(material, b"mac", 32),
        )
        assert len(user_key) == 64
        pkcs8 = _vw_decstring(payload["keys"]["encryptedPrivateKey"], user_key[:32], user_key[32:])
        priv = serialization.load_der_private_key(pkcs8, password=None)
        spki = priv.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        assert spki == base64.b64decode(payload["keys"]["publicKey"])
        auth = base64.b64encode(
            hashlib.pbkdf2_hmac("sha256", material, senha.encode("utf-8"), 1, dklen=32)
        ).decode("ascii")
        assert auth == payload["masterPasswordHash"]

    # ---------- criação de conta ----------

    @patch("tools.actions.actions.nomad_tools_status")
    @patch("urllib.request.urlopen")
    def test_register_rota_oficial_e_payload(self, mock_urlopen, mock_status) -> None:
        """POST vai para /identity/accounts/register com RegisterData completo (sem token falso)."""
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"object": "register"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = nomad_vaultwarden_setup(
            admin_email="admin@test.com",
            admin_password="senha123",
            disable_signups=False,
        )
        assert result["ok"] is True
        assert "Conta admin@test.com criada" in result["message"]
        assert "token" not in result  # registro não retorna token — sem sucesso falso
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://127.0.0.1:8480/identity/accounts/register"
        assert req.get_method() == "POST"
        body = json.loads(req.data.decode("utf-8"))
        for campo in ("email", "kdf", "kdfIterations", "key", "keys", "masterPasswordHash"):
            assert campo in body
        assert body["email"] == "admin@test.com"
        assert body["keys"]["publicKey"] and body["keys"]["encryptedPrivateKey"]

    @patch("tools.actions.actions.nomad_tools_status")
    @patch("urllib.request.urlopen")
    def test_register_recusado_signups_fechados(self, mock_urlopen, mock_status) -> None:
        """HTTP 400 do servidor vira erro honesto (nunca sucesso)."""
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        fp = io.BytesIO(b'{"message": "Registration not allowed or user already exists"}')
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://127.0.0.1:8480/identity/accounts/register",
            400, "Bad Request", {}, fp,
        )
        result = nomad_vaultwarden_setup(
            admin_email="novo@x.com", admin_password="senha123", disable_signups=False
        )
        assert result["ok"] is False
        assert result["error"] == "registro_recusado"
        assert result["http_status"] == 400
        assert "Registration not allowed" in result["message"]

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
        mock_urlopen.side_effect = OSError("connection refused")
        result = nomad_vaultwarden_setup(
            admin_email="a@b.com", admin_password="pass", disable_signups=False
        )
        assert result["ok"] is False
        assert result["error"] == "criar_conta_falhou"

    @patch("tools.actions.actions.nomad_tools_status")
    @patch("urllib.request.urlopen")
    def test_vaultwarden_setup_no_credentials(self, mock_urlopen, mock_status) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        result = nomad_vaultwarden_setup(disable_signups=False)
        assert result["ok"] is True
        assert result["message"] == "Vaultwarden pronto. Acesse via tailscale serve https://127.0.0.1:8480"
        assert "token" not in result
        mock_urlopen.assert_not_called()

    # ---------- fechamento real de signups ----------

    @patch("tools.actions.actions._run", return_value=(0, "WEBSOCKET_ENABLED=true\nSIGNUPS_ALLOWED=false\n", ""))
    @patch("tools.actions.actions._compose", return_value={"ok": True, "output": "Vaultwarden recriado"})
    @patch("tools.actions.actions.nomad_tools_status")
    def test_disable_signups_edita_compose_e_recria(
        self, mock_status, mock_compose, mock_run, tmp_path
    ) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        compose = tmp_path / "tools-compose.yaml"
        compose.write_text(
            "  vaultwarden:\n    environment:\n      - SIGNUPS_ALLOWED=true\n      - DOMAIN=x\n",
            encoding="utf-8",
        )
        with patch("tools.actions.actions.NOMAD_COMPOSE_FILE", str(compose)):
            result = nomad_vaultwarden_setup(disable_signups=True)

        assert result["ok"] is True
        assert result["signups"] == {
            "compose_atualizado": True,
            "signups_allowed": False,
            "container_env": True,
        }
        texto = compose.read_text(encoding="utf-8")
        assert "SIGNUPS_ALLOWED=false" in texto
        assert "SIGNUPS_ALLOWED=true" not in texto
        mock_compose.assert_called_once_with(["up", "-d", "vaultwarden"], timeout=90.0)
        assert "od-vaultwarden" in mock_run.call_args[0][0]
        assert "Signups fechados" in result["message"]

    @patch("tools.actions.actions._run", return_value=(0, "SIGNUPS_ALLOWED=false\n", ""))
    @patch("tools.actions.actions._compose", return_value={"ok": True, "output": "ok"})
    @patch("tools.actions.actions.nomad_tools_status")
    def test_disable_signups_ja_fechado_idempotente(
        self, mock_status, mock_compose, mock_run, tmp_path
    ) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        compose = tmp_path / "tools-compose.yaml"
        compose.write_text("      - SIGNUPS_ALLOWED=false\n", encoding="utf-8")
        with patch("tools.actions.actions.NOMAD_COMPOSE_FILE", str(compose)):
            result = nomad_vaultwarden_setup(disable_signups=True)

        assert result["ok"] is True
        assert result["signups"]["compose_atualizado"] is False
        # up -d continua sendo chamado (no-op do compose quando nada mudou)
        mock_compose.assert_called_once()

    @patch("tools.actions.actions._run", return_value=(0, "WEBSOCKET_ENABLED=true\n", ""))
    @patch("tools.actions.actions._compose", return_value={"ok": True, "output": "ok"})
    @patch("tools.actions.actions.nomad_tools_status")
    def test_disable_signups_env_nao_aplicada_falha(
        self, mock_status, mock_compose, mock_run, tmp_path
    ) -> None:
        """Se a env não chegou ao container, a ação FALHA (sem sucesso falso)."""
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        compose = tmp_path / "tools-compose.yaml"
        compose.write_text("      - SIGNUPS_ALLOWED=true\n", encoding="utf-8")
        with patch("tools.actions.actions.NOMAD_COMPOSE_FILE", str(compose)):
            result = nomad_vaultwarden_setup(disable_signups=True)

        assert result["ok"] is False
        assert result["error"] == "signups_nao_fecharam"
        assert result["etapa"] == "fechar_signups"

    @patch("tools.actions.actions._compose", return_value={"ok": False, "tool": "docker_compose", "error": "docker indisponível"})
    @patch("tools.actions.actions.nomad_tools_status")
    def test_disable_signups_recriar_container_falhou(
        self, mock_status, mock_compose, tmp_path
    ) -> None:
        mock_status.return_value = {"ok": True, "output": "od-vaultwarden running"}
        compose = tmp_path / "tools-compose.yaml"
        compose.write_text("      - SIGNUPS_ALLOWED=true\n", encoding="utf-8")
        with patch("tools.actions.actions.NOMAD_COMPOSE_FILE", str(compose)):
            result = nomad_vaultwarden_setup(disable_signups=True)

        assert result["ok"] is False
        assert result["error"] == "recriar_container_falhou"


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
    async def test_nomad_vaultwarden_setup_via_registry(self, tmp_path) -> None:
        from core.security import SecurityManager
        registry = build_registry(security=SecurityManager(mode="strict"))
        compose = tmp_path / "tools-compose.yaml"
        compose.write_text("      - SIGNUPS_ALLOWED=true\n", encoding="utf-8")
        with patch("tools.actions.actions.nomad_tools_status", return_value={"ok": True, "output": "od-vaultwarden running"}), \
             patch("urllib.request.urlopen") as mock_urlopen, \
             patch("tools.actions.actions.NOMAD_COMPOSE_FILE", str(compose)), \
             patch("tools.actions.actions._compose", return_value={"ok": True, "output": "ok"}), \
             patch("tools.actions.actions._run", return_value=(0, "SIGNUPS_ALLOWED=false\n", "")):
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"object": "register"}'
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
        assert result.data["signups"]["container_env"] is True
        assert "SIGNUPS_ALLOWED=false" in compose.read_text(encoding="utf-8")

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