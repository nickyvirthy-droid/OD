"""
OMEGA DRAKON • TESTS
Módulo: tests/test_push.py
Descrição: Testes do push FCM (core/push.py) — registro de dispositivos
           (upsert por token, persistência, escrita atômica) e envio via FCM
           HTTP v1 (payload, autenticação, tokens mortos). Nenhum teste toca a
           rede: o transporte é injetado.

           Cobre também a fachada usada pelo launcher/notifier (PushService)
           e a factory que lê OD_* do ambiente, incluindo o modo DORMENTE
           (sem credencial nada é enviado e nada quebra).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/push.py
  - docs/FIREBASE_SETUP.md (FCM HTTP v1, projeto nicky-e4f99)
  - integrations/notifier.py (sink de alertas)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.push import (
    DEAD_TOKEN_CODES,
    FCM_ENDPOINT,
    HttpResponse,
    DeviceRegistry,
    FcmSender,
    PushError,
    PushService,
    build_push_service,
    configure_push,
    current_push,
)


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------


class FakeTransport:
    """Transporte HTTP dublê: registra as chamadas e devolve a fila."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.calls: list[dict] = []
        self.responses = list(responses) or [HttpResponse(200, {}, b'{"name":"x"}')]

    def __call__(self, url, method="GET", body=None, headers=None,
                 timeout=10.0, **kwargs) -> HttpResponse:
        self.calls.append(
            {
                "url": url,
                "method": method,
                "body": json.loads((body or b"{}").decode("utf-8")),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def _ok() -> HttpResponse:
    return HttpResponse(200, {}, b'{"name":"projects/p/messages/1"}')


def _error(code: str, status: int = 404) -> HttpResponse:
    payload = json.dumps({"error": {"status": code, "message": f"{code} erro"}})
    return HttpResponse(status, {}, payload.encode("utf-8"))


class FakeCredentials:
    """Credencial no formato do google-auth (sem assinar nada de verdade)."""

    def __init__(self) -> None:
        self.valid = False
        self.token = ""
        self.refreshes = 0

    def refresh(self, request) -> None:  # noqa: ANN001 — protocolo google-auth
        self.refreshes += 1
        self.token = "access-token-fake"
        self.valid = True


def _sender(transport: FakeTransport, project: str = "nicky-e4f99") -> FcmSender:
    """Sender com credencial dublê (não lê arquivo, não chama a rede)."""
    sender = FcmSender(project_id=project, transport=transport)
    sender._credentials = FakeCredentials()
    sender._credentials_error = None
    return sender


def _service(tmp_path: Path, transport: FakeTransport) -> PushService:
    registry = DeviceRegistry(tmp_path / "push_devices.json")
    return PushService(registry, _sender(transport), enabled=True)


# ---------------------------------------------------------------------------
# DeviceRegistry — registro dos aparelhos
# ---------------------------------------------------------------------------


class TestDeviceRegistry:
    def test_register_persiste_e_le(self, tmp_path: Path) -> None:
        registry = DeviceRegistry(tmp_path / "devices.json")
        device = registry.register("token-abc", device="Redmi Note 14")

        assert device.token == "token-abc"
        assert device.platform == "android"
        assert device.registered_at > 0

        # nova instância lê o mesmo arquivo (persistência real)
        other = DeviceRegistry(tmp_path / "devices.json")
        assert other.tokens() == ["token-abc"]
        assert other.get("token-abc").device == "Redmi Note 14"

    def test_register_e_upsert_por_token(self, tmp_path: Path) -> None:
        """Reenviar o mesmo token atualiza — não duplica o aparelho."""
        registry = DeviceRegistry(tmp_path / "devices.json")
        first = registry.register("mesmo-token", device="antigo")
        time.sleep(0.001)
        second = registry.register("mesmo-token", device="novo")

        assert registry.count() == 1
        assert second.registered_at == first.registered_at  # preserva o 1º
        assert second.updated_at >= first.updated_at
        assert second.device == "novo"

    def test_register_token_vazio(self, tmp_path: Path) -> None:
        registry = DeviceRegistry(tmp_path / "devices.json")
        with pytest.raises(ValueError):
            registry.register("   ")

    def test_unregister(self, tmp_path: Path) -> None:
        registry = DeviceRegistry(tmp_path / "devices.json")
        registry.register("t1")
        registry.register("t2")

        assert registry.unregister("t1") is True
        assert registry.unregister("t1") is False  # já não existe
        assert registry.tokens() == ["t2"]

    def test_arquivo_corrompido_nao_estoura(self, tmp_path: Path) -> None:
        """JSON inválido vira registro vazio (push nunca derruba o OD)."""
        path = tmp_path / "devices.json"
        path.write_text("{isso não é json", encoding="utf-8")

        registry = DeviceRegistry(path)
        assert registry.tokens() == []
        # e volta a funcionar normalmente
        registry.register("t1")
        assert registry.tokens() == ["t1"]

    def test_arquivo_ilegivel_nao_estoura(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.json"
        path.mkdir()  # diretório no lugar do arquivo → OSError na leitura
        assert DeviceRegistry(path).tokens() == []

    def test_mark_conta_envios(self, tmp_path: Path) -> None:
        registry = DeviceRegistry(tmp_path / "devices.json")
        registry.register("t1")
        registry.mark("t1", sent=True)
        registry.mark("t1", sent=True)
        registry.mark("t1", sent=False)

        device = registry.get("t1")
        assert (device.sent, device.failed) == (2, 1)
        registry.mark("inexistente", sent=True)  # não estoura

    def test_masked_token_nunca_inteiro(self, tmp_path: Path) -> None:
        registry = DeviceRegistry(tmp_path / "devices.json")
        device = registry.register("abcdefghijklmnop")
        assert "abcdefghijklmnop" not in device.masked_token()
        assert DeviceRegistry(tmp_path / "d2.json").register("curto").masked_token() == "***"


# ---------------------------------------------------------------------------
# FcmSender — envio
# ---------------------------------------------------------------------------


class TestFcmSender:
    def test_send_monta_payload_e_autentica(self, tmp_path: Path) -> None:
        transport = FakeTransport(_ok())
        sender = _sender(transport)

        result = sender.send("token-1", "Título", "Corpo", {"tipo": "teste"})

        assert result["name"].startswith("projects/")
        call = transport.calls[0]
        assert call["url"] == FCM_ENDPOINT.format(project="nicky-e4f99")
        assert call["method"] == "POST"
        assert call["headers"]["Authorization"] == "Bearer access-token-fake"
        assert call["headers"]["Content-Type"].startswith("application/json")
        message = call["body"]["message"]
        assert message["token"] == "token-1"
        assert message["notification"] == {"title": "Título", "body": "Corpo"}
        assert message["data"] == {"tipo": "teste"}
        assert message["android"]["priority"] == "high"

    def test_send_sem_data_nao_inclui_campo(self) -> None:
        transport = FakeTransport(_ok())
        _sender(transport).send("t", "a", "b")
        assert "data" not in transport.calls[0]["body"]["message"]

    def test_error_code_extraido_da_push_error(self) -> None:
        from core.push import _error_code

        assert _error_code(PushError("FCM recusou status=404 code=UNREGISTERED boom")) \
            == "UNREGISTERED"
        assert _error_code(PushError("falha de rede")) == ""

    def test_credencial_ausente_e_dormente(self, tmp_path: Path) -> None:
        sender = FcmSender(credentials_file=tmp_path / "nao-existe.json")
        assert sender.available is False
        assert sender.reason == "credencial_ausente"
        with pytest.raises(PushError):
            sender.send("t", "a", "b")

    def test_credentials_file_sem_google_auth(self, monkeypatch, tmp_path: Path) -> None:
        """Ambiente sem google-auth → dormente, não ImportError."""
        creds = tmp_path / "sa.json"
        creds.write_text("{}", encoding="utf-8")
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("google"):
                raise ImportError("sem google-auth")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        sender = FcmSender(credentials_file=creds)
        assert sender.available is False
        assert sender.reason == "google_auth_ausente"

    def test_fcm_recusa_levanta_push_error(self) -> None:
        transport = FakeTransport(_error("UNREGISTERED"))
        with pytest.raises(PushError) as exc:
            _sender(transport).send("morto", "a", "b")
        assert "UNREGISTERED" in str(exc.value)

    def test_send_token_vazio(self) -> None:
        with pytest.raises(PushError):
            _sender(FakeTransport(_ok())).send("  ", "a", "b")

    def test_refresh_do_access_token_uma_vez(self) -> None:
        transport = FakeTransport(_ok())
        sender = _sender(transport)
        sender.send("t", "a", "b")
        sender.send("t", "a", "b")
        assert sender._credentials.refreshes == 1  # credencial reaproveitada


# ---------------------------------------------------------------------------
# PushService — fachada (launcher + notifier + API)
# ---------------------------------------------------------------------------


class TestPushService:
    def test_notify_envia_para_todos(self, tmp_path: Path) -> None:
        transport = FakeTransport(_ok())
        service = _service(tmp_path, transport)
        service.register("t1")
        service.register("t2")

        summary = service.notify("Alerta", "texto")

        assert summary["ok"] is True
        assert summary["sent"] == 2
        assert summary["failed"] == 0
        assert [c["body"]["message"]["token"] for c in transport.calls] == ["t1", "t2"]

    def test_notify_sem_dispositivos(self, tmp_path: Path) -> None:
        summary = _service(tmp_path, FakeTransport(_ok())).notify("a", "b")
        assert summary["sent"] == 0 and summary["ok"] is True

    def test_notify_desligado_nao_envia(self, tmp_path: Path) -> None:
        transport = FakeTransport(_ok())
        service = PushService(
            DeviceRegistry(tmp_path / "d.json"), _sender(transport), enabled=False
        )
        service.register("t1")

        summary = service.notify("a", "b")
        assert summary["ok"] is False
        assert summary["sent"] == 0
        assert summary["skipped"] == 1
        assert transport.calls == []  # nada saiu na rede

    def test_token_morto_sai_do_registro(self, tmp_path: Path) -> None:
        transport = FakeTransport(_ok(), _error("UNREGISTERED"))
        service = _service(tmp_path, transport)
        service.register("vivo")
        service.register("morto")

        summary = service.notify("a", "b")

        assert summary["failed"] == 1
        assert summary["ok"] is False
        assert summary["errors"][0]["code"] in DEAD_TOKEN_CODES
        assert "morto" not in summary["errors"][0]["token"]  # mascarado no erro
        assert service.registry.tokens() == ["vivo"]

    def test_falha_transitoria_mantem_token(self, tmp_path: Path) -> None:
        transport = FakeTransport(_error("INTERNAL", status=500))
        service = _service(tmp_path, transport)
        service.register("t1")

        service.notify("a", "b")
        assert service.registry.tokens() == ["t1"]  # tentará de novo depois
        assert service.registry.get("t1").failed == 1

    def test_sink_plugavel_no_notifier(self, tmp_path: Path) -> None:
        transport = FakeTransport(_ok())
        service = _service(tmp_path, transport)
        service.register("t1")

        result = service.sink()("disco cheio")

        assert result["sent"] == 1
        message = transport.calls[0]["body"]["message"]
        assert message["notification"]["title"] == "OmegaDrakon"
        assert message["notification"]["body"] == "disco cheio"

    def test_status_sem_expor_token(self, tmp_path: Path) -> None:
        service = _service(tmp_path, FakeTransport(_ok()))
        service.register("token-secreto-123456")

        status = service.status()

        assert status["enabled"] is True
        assert status["devices"] == 1
        assert "token-secreto-123456" not in json.dumps(status)
        assert status["project_id"] == "nicky-e4f99"

    def test_register_funciona_com_push_desligado(self, tmp_path: Path) -> None:
        """Sem credencial o aparelho ainda se registra (para quando ela vier)."""
        service = PushService(
            DeviceRegistry(tmp_path / "d.json"),
            FcmSender(credentials_file=tmp_path / "nada.json"),
            enabled=True,
        )
        service.register("t1")
        assert service.enabled is False
        assert service.registry.tokens() == ["t1"]


# ---------------------------------------------------------------------------
# Factory (ambiente) + injeção global
# ---------------------------------------------------------------------------


class TestBuildPushService:
    def test_sem_credencial_fica_dormente(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv("OD_FCM_CREDENTIALS", raising=False)
        monkeypatch.delenv("OD_PUSH_ENABLED", raising=False)
        monkeypatch.chdir(tmp_path)  # nenhum caminho candidato existe

        service = build_push_service(tmp_path)

        assert service.enabled is False
        assert service.sender.reason == "credencial_ausente"

    def test_od_push_enabled_zero_desliga(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("OD_PUSH_ENABLED", "0")
        service = build_push_service(tmp_path)
        assert service.enabled is False

    def test_credencial_por_env(self, monkeypatch, tmp_path: Path) -> None:
        """Caminho vindo de OD_FCM_CREDENTIALS é usado (mesmo inválido)."""
        creds = tmp_path / "sa.json"
        creds.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("OD_FCM_CREDENTIALS", str(creds))

        service = build_push_service(tmp_path)
        assert service.sender.credentials_file == creds
        assert service.enabled is False  # JSON vazio não é credencial válida

    def test_arquivo_de_dispositivos_em_data_dir(self, tmp_path: Path) -> None:
        service = build_push_service(tmp_path)
        service.register("t1")
        assert (tmp_path / "push_devices.json").exists()

    def test_configure_e_current_push(self, tmp_path: Path) -> None:
        service = build_push_service(tmp_path)
        configure_push(service)
        try:
            assert current_push() is service
        finally:
            configure_push(None)
        assert current_push() is None
