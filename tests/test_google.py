"""
OMEGA DRAKON • TESTS
Módulo: tests/test_google.py
Descrição: testes da integração Google Workspace (leitura) —
           OAuth 2.0 (URL/troca/refresh), GoogleClient (Bearer, renovação,
           persistência), serviços Drive/Agenda/Gmail e o wiring no catálogo
           de actions + intents do chat. HTTP 100% mockado (FakeTransport):
           nenhuma credencial real, nenhuma chamada de rede.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import base64
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

import pytest

from core.intents import detect_action_intent, format_intent_result
from integrations.google import (
    CalendarService,
    DriveService,
    GmailService,
    GoogleClient,
    GoogleCredentials,
    GoogleError,
    GoogleToken,
    oauth,
)
from integrations.google import build_google_client
from integrations.google.client import load_token, save_token
from integrations.google.transport import UrllibTransport, checked, decode_json


class FakeTransport:
    """Transporte HTTP fake: registra chamadas e responde por handler."""

    def __init__(self, handler=None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.handler = handler

    def __call__(self, method, url, *, headers=None, data=None, timeout=30.0):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers or {}), "data": data}
        )
        if self.handler is not None:
            return self.handler(method, url, data)
        return 200, b"{}"


def _creds() -> GoogleCredentials:
    return GoogleCredentials(client_id="cid", client_secret="secret")


def _token(*, valid: bool = True, refresh: str = "refresh-1") -> GoogleToken:
    return GoogleToken(
        access_token="access-old",
        refresh_token=refresh,
        expires_at=time.time() + (3600 if valid else -10),
    )


def _client(transport: FakeTransport, *, token: Optional[GoogleToken] = None,
            token_path: Optional[Path] = None) -> GoogleClient:
    return GoogleClient(
        _creds(), token or _token(), transport=transport, token_path=token_path
    )


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class TestModels:
    def test_credentials_flat_e_installed(self) -> None:
        flat = GoogleCredentials.from_dict({"client_id": "a", "client_secret": "b"})
        assert flat.configured and flat.redirect_uri.endswith("8766/")
        console = GoogleCredentials.from_dict(
            {"installed": {
                "client_id": "x", "client_secret": "y",
                "redirect_uris": ["http://localhost:9/cb"],
            }}
        )
        assert console.redirect_uri == "http://localhost:9/cb"
        assert len(console.scopes) == 3

    def test_credentials_incompletas_falham(self) -> None:
        with pytest.raises(ValueError):
            GoogleCredentials.from_dict({"client_id": "a"})

    def test_token_expira_e_preserva_refresh(self) -> None:
        token = GoogleToken.from_token_response(
            {"access_token": "novo", "expires_in": 3600}, previous_refresh="r0"
        )
        assert token.refresh_token == "r0" and not token.is_expired()
        assert _token(valid=False).is_expired()


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

class TestOAuth:
    def test_build_authorization_url(self) -> None:
        url = oauth.build_authorization_url(_creds(), state="xyz")
        assert "accounts.google.com" in url
        assert "client_id=cid" in url
        assert "access_type=offline" in url and "prompt=consent" in url
        assert "state=xyz" in url
        assert "drive.readonly" in url and "gmail.readonly" in url

    def test_extract_code_de_url_e_de_codigo(self) -> None:
        assert oauth.extract_code("http://localhost:8766/?code=abc&scope=z") == "abc"
        assert oauth.extract_code("abc") == "abc"
        with pytest.raises(GoogleError):
            oauth.extract_code("http://localhost:8766/?error=access_denied")
        with pytest.raises(GoogleError):
            oauth.extract_code("")

    def test_exchange_e_refresh(self) -> None:
        posts: list[bytes] = []

        def handler(method, url, data):
            posts.append(data or b"")
            if b"grant_type=authorization_code" in (data or b""):
                return 200, json.dumps(
                    {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
                ).encode()
            return 200, json.dumps({"access_token": "novo", "expires_in": 3600}).encode()

        transport = FakeTransport(handler)
        token = oauth.exchange_code(_creds(), "code-1", transport=transport)
        assert token.access_token == "at" and token.refresh_token == "rt"
        renewed = oauth.refresh_access_token(_creds(), token, transport=transport)
        assert renewed.access_token == "novo" and renewed.refresh_token == "rt"
        assert b"grant_type=refresh_token" in posts[-1]

    def test_refresh_sem_refresh_token_falha(self) -> None:
        with pytest.raises(GoogleError):
            oauth.refresh_access_token(_creds(), GoogleToken(access_token="x"))

    def test_erro_do_google_vira_googleerror(self) -> None:
        transport = FakeTransport(
            lambda m, u, d: (400, b'{"error":"invalid_grant","error_description":"expired"}')
        )
        with pytest.raises(GoogleError, match="invalid_grant"):
            oauth.refresh_access_token(_creds(), _token(), transport=transport)


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class TestClient:
    def test_sem_token_nao_autorizado(self) -> None:
        client = _client(FakeTransport(), token=GoogleToken())
        with pytest.raises(GoogleError, match="não autorizado"):
            client.ensure_access_token()

    def test_renova_token_expirado_e_persiste(self, tmp_path: Path) -> None:
        def handler(method, url, data):
            return 200, json.dumps({"access_token": "novinho", "expires_in": 3600}).encode()

        transport = FakeTransport(handler)
        token_path = tmp_path / "tok.json"
        client = _client(transport, token=_token(valid=False), token_path=token_path)
        assert client.ensure_access_token() == "novinho"
        assert load_token(token_path).access_token == "novinho"

    def test_get_usa_bearer_e_parseia_json(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b'{"ok": true}'))
        client = _client(transport)
        assert client.get("https://g.example/x", params={"a": 1, "vazio": ""}) == {"ok": True}
        call = transport.calls[0]
        assert call["headers"]["Authorization"] == "Bearer access-old"
        assert "a=1" in call["url"] and "vazio" not in call["url"]

    def test_params_lista_viram_parametros_repetidos(self) -> None:
        """Lista vira chaves repetidas na URL (doseq) — não o repr de Python.

        Bug achado na prova viva de 03/10: sem doseq, o metadataHeaders
        do Gmail chegava como %5B%27From%27... e a API devolvia as 10
        mensagens sem assunto e sem remetente.
        """
        transport = FakeTransport(lambda m, u, d: (200, b"{}"))
        _client(transport).get(
            "https://g.example/m",
            params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
        )
        url = transport.calls[0]["url"]
        assert "metadataHeaders=From&metadataHeaders=Subject" in url
        assert "%5B" not in url

    def test_erro_http_vira_googleerror(self) -> None:
        transport = FakeTransport(
            lambda m, u, d: (403, b'{"error": {"message": "insufficient scopes"}}')
        )
        with pytest.raises(GoogleError, match="insufficient scopes"):
            _client(transport).get("https://g.example/x")

    def test_request_raw_devolve_bytes(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b"conteudo-cru"))
        assert _client(transport).request_raw("GET", "https://g.example/f") == b"conteudo-cru"

    def test_save_e_load_token(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "tok.json"
        save_token(path, _token())
        assert load_token(path).refresh_token == "refresh-1"
        assert load_token(tmp_path / "inexistente.json").authorized is False


# ---------------------------------------------------------------------------
# Serviços
# ---------------------------------------------------------------------------

class TestDrive:
    def test_list_files(self) -> None:
        payload = {"files": [
            {"id": "1", "name": "Doc", "mimeType": "application/pdf",
             "modifiedTime": "2026-10-01T10:00:00Z", "owners": [{"displayName": "alex"}]},
        ]}
        transport = FakeTransport(lambda m, u, d: (200, json.dumps(payload).encode()))
        data = DriveService(_client(transport)).list_files(query="name contains 'Doc'")
        assert data["count"] == 1 and data["files"][0]["name"] == "Doc"
        assert data["files"][0]["owner"] == "alex"

    def test_read_text_exporta_nativo_google(self) -> None:
        def handler(method, url, data):
            if "/export" in url:
                return 200, b"conteudo exportado"
            return 200, json.dumps(
                {"id": "1", "name": "Anotacoes",
                 "mimeType": "application/vnd.google-apps.document"}
            ).encode()

        transport = FakeTransport(handler)
        data = DriveService(_client(transport)).read_text("1")
        assert data["text"] == "conteudo exportado" and data["truncated"] is False

    def test_read_text_baixa_binario_como_texto(self) -> None:
        def handler(method, url, data):
            if "alt=media" in url:
                return 200, b"linha1\nlinha2\n"
            return 200, json.dumps(
                {"id": "2", "name": "notas.txt", "mimeType": "text/plain"}
            ).encode()

        transport = FakeTransport(handler)
        data = DriveService(_client(transport)).read_text("2")
        assert "linha1" in data["text"] and data["mime_type"] == "text/plain"


class TestCalendar:
    def test_list_events_builds_window(self) -> None:
        captured: dict[str, str] = {}

        def handler(method, url, data):
            captured["url"] = url
            return 200, json.dumps({"items": [
                {"id": "e1", "summary": "Reunião",
                 "start": {"dateTime": "2026-10-02T13:00:00-03:00"},
                 "end": {"dateTime": "2026-10-02T14:00:00-03:00"},
                 "location": "Online"},
            ]}).encode()

        transport = FakeTransport(handler)
        data = CalendarService(_client(transport)).list_events(days=2, limit=5)
        assert data["count"] == 1 and data["events"][0]["summary"] == "Reunião"
        assert "timeMin=" in captured["url"] and "timeMax=" in captured["url"]
        assert "singleEvents=true" in captured["url"]


class TestGmail:
    @staticmethod
    def _message(mid: str) -> dict[str, Any]:
        body = base64.urlsafe_b64encode(b"corpo do e-mail").decode().rstrip("=")
        return {
            "id": mid,
            "threadId": "t1",
            "snippet": "resumo curto",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "remetente@ex.com"},
                    {"name": "Subject", "value": "Assunto real"},
                    {"name": "Date", "value": "Thu, 02 Oct 2026 10:00:00 -0300"},
                ],
                "body": {"data": body},
            },
        }

    def test_list_messages(self) -> None:
        def handler(method, url, data):
            if "/messages/m1" in url:
                return 200, json.dumps(self._message("m1")).encode()
            return 200, json.dumps({"messages": [{"id": "m1"}]}).encode()

        transport = FakeTransport(handler)
        data = GmailService(_client(transport)).list_messages()
        assert data["count"] == 1 and data["messages"][0]["subject"] == "Assunto real"

    def test_get_message_decodifica_corpo(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, json.dumps(self._message("m1")).encode()))
        data = GmailService(_client(transport)).get_message("m1")
        assert data["body"] == "corpo do e-mail"
        assert data["from"] == "remetente@ex.com"

    def test_list_labels(self) -> None:
        transport = FakeTransport(
            lambda m, u, d: (200, json.dumps({"labels": [{"id": "INBOX", "name": "Caixa de entrada", "type": "system"}]}).encode())
        )
        data = GmailService(_client(transport)).list_labels()
        assert data["count"] == 1 and data["labels"][0]["name"] == "Caixa de entrada"

    def test_body_html_simples_e_base64_invalido(self) -> None:
        html = base64.urlsafe_b64encode(b"<b>oi</b>").decode().rstrip("=")
        msg_html = {"id": "m", "payload": {
            "mimeType": "text/html", "headers": [], "body": {"data": html}}}
        data = GmailService(_client(FakeTransport(
            lambda m, u, d: (200, json.dumps(msg_html).encode())))).get_message("m")
        assert data["body"] == "<b>oi</b>"

        msg_bad = {"id": "m", "payload": {
            "mimeType": "text/plain", "headers": [], "body": {"data": "@@@"}}}
        data = GmailService(_client(FakeTransport(
            lambda m, u, d: (200, json.dumps(msg_bad).encode())))).get_message("m")
        assert data["body"] == ""

    def test_body_longo_e_truncado(self) -> None:
        grande = base64.urlsafe_b64encode(b"x" * 25000).decode().rstrip("=")
        msg = {"id": "m", "payload": {
            "mimeType": "text/plain", "headers": [], "body": {"data": grande}}}
        data = GmailService(_client(FakeTransport(
            lambda m, u, d: (200, json.dumps(msg).encode())))).get_message("m")
        assert data["body"].endswith("…")


# ---------------------------------------------------------------------------
# Actions no catálogo (degradam sem credencial; funcionam com cliente fake)
# ---------------------------------------------------------------------------

class TestGoogleActions:
    def _fake_client(self) -> GoogleClient:
        return _client(FakeTransport(lambda m, u, d: (200, b'{"files": [], "messages": [], "events": [], "labels": []}')))

    def test_sem_cliente_degrada(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(None)
        result = actions.google_drive_list()
        assert result["ok"] is False and "Google" in result["error"]

    def test_com_cliente_lista(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(self._fake_client())
        try:
            assert actions.google_drive_list()["ok"] is True
            assert actions.google_calendar_events()["ok"] is True
            assert actions.google_gmail_labels()["ok"] is True
        finally:
            actions.configure_google_client(None)

    def test_erro_do_cliente_vira_ok_false(self) -> None:
        from tools.actions import actions

        bad = _client(FakeTransport(lambda m, u, d: (500, b'{"error": {"message": "boom"}}')))
        actions.configure_google_client(bad)
        try:
            result = actions.google_gmail_list()
            assert result["ok"] is False and "boom" in result["error"]
        finally:
            actions.configure_google_client(None)

    def test_catalogo_tem_as_6_actions_de_leitura(self) -> None:
        from tools.actions import CATALOG, CATEGORIES

        names = {spec["name"] for spec in CATALOG if spec["category"] == "google"}
        assert names == {
            "google_drive_list", "google_drive_read", "google_calendar_events",
            "google_gmail_list", "google_gmail_read", "google_gmail_labels",
        }
        assert CATEGORIES["google"] == 6


# ---------------------------------------------------------------------------
# Intents do chat
# ---------------------------------------------------------------------------

class TestGoogleIntents:
    def test_detecta_email_agenda_drive(self) -> None:
        assert detect_action_intent("meus e-mails")[0] == "google_gmail_list"
        assert detect_action_intent("minha agenda de hoje")[1]["days"] == 1
        assert detect_action_intent("meus arquivos no google drive")[0] == "google_drive_list"

    def test_senha_do_gmail_nao_vira_listagem(self) -> None:
        assert detect_action_intent("qual a senha do gmail") is None

    def test_pasta_local_nao_vira_drive(self) -> None:
        # 'meus arquivos' sem 'drive' não deve capturar pergunta de arquivos locais
        assert detect_action_intent("liste meus arquivos") is None

    def test_format_sem_autorizacao_e_honesto(self) -> None:
        msg = format_intent_result(
            "google_gmail_list",
            {"ok": False, "error": "Google não autorizado — rode runtime/google_auth"},
        )
        assert msg is not None and "não está" in msg
        assert "google_auth" in msg

    def test_format_lista_mensagens(self) -> None:
        msg = format_intent_result("google_gmail_list", {"ok": True, "messages": [
            {"subject": "Assunto", "from": "a@b.com"},
        ]})
        assert msg is not None and "Assunto" in msg and "a@b.com" in msg

    def test_format_eventos_e_arquivos(self) -> None:
        cal = format_intent_result("google_calendar_events", {
            "ok": True, "days": 7,
            "events": [{"summary": "Reunião", "start": "2026-10-02T13:00:00-03:00"}],
        })
        assert cal is not None and "Reunião" in cal
        drive = format_intent_result("google_drive_list", {
            "ok": True, "files": [{"name": "Doc", "mime_type": "application/pdf"}],
        })
        assert drive is not None and "Doc" in drive


# ---------------------------------------------------------------------------
# CLI de autorização
# ---------------------------------------------------------------------------

class TestModelsExtras:
    def test_to_dict_e_bordas_de_token(self) -> None:
        creds = _creds()
        assert creds.to_dict()["client_id"] == "cid"
        assert "client_secret" not in creds.to_dict()
        assert creds.to_dict(include_secret=True)["client_secret"] == "secret"
        assert GoogleToken.from_dict(
            {"access_token": "a", "expires_at": "zzz"}
        ).expires_at == 0.0
        assert GoogleToken.from_token_response(
            {"access_token": "a", "expires_in": "zzz"}
        ).expires_at == 0.0


class TestGoogleAuthCli:
    def _creds_file(self, path: Path) -> Path:
        path.write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}), encoding="utf-8")
        return path

    def test_main_url_e_check(self, tmp_path: Path, capsys) -> None:
        from runtime import google_auth

        creds = self._creds_file(tmp_path / "cred.json")
        token = tmp_path / "tok.json"

        assert google_auth.main(["--credentials", str(creds), "--token", str(token), "--url"]) == 0
        assert "accounts.google.com" in capsys.readouterr().out

        # sem token salvo → check retorna 1 e informa AUSENTE
        assert google_auth.main(["--credentials", str(creds), "--token", str(token), "--check"]) == 1
        assert "AUSENTE" in capsys.readouterr().out

    def test_main_code_nao_interativo(self, tmp_path: Path, capsys, monkeypatch) -> None:
        from runtime import google_auth

        creds = self._creds_file(tmp_path / "cred.json")
        token = tmp_path / "tok.json"

        def fake_exchange(credentials, code, *, previous_refresh="", transport=None):
            assert code == "codigo-abc"
            return GoogleToken(access_token="at", refresh_token="rt", scope="s")

        monkeypatch.setattr(oauth, "exchange_code", fake_exchange)
        rc = google_auth.main([
            "--credentials", str(creds), "--token", str(token), "--code", "codigo-abc",
        ])
        assert rc == 0
        assert load_token(token).refresh_token == "rt"

    def test_check_sem_credenciais_e_com_token(self, tmp_path: Path, capsys) -> None:
        from runtime import google_auth

        # sem credenciais → 1
        rc = google_auth.main([
            "--credentials", str(tmp_path / "nao.json"),
            "--token", str(tmp_path / "t.json"), "--check",
        ])
        assert rc == 1 and "ausentes" in capsys.readouterr().out

        # com token válido → 0 (e informa refresh/expira)
        creds = self._creds_file(tmp_path / "c2.json")
        token = tmp_path / "t2.json"
        save_token(token, _token())
        rc = google_auth.main([
            "--credentials", str(creds), "--token", str(token), "--check",
        ])
        assert rc == 0 and "válido" in capsys.readouterr().out

    def test_authorize_sem_credenciais(self, tmp_path: Path, capsys) -> None:
        from runtime import google_auth

        rc = google_auth.main([
            "--credentials", str(tmp_path / "nao.json"),
            "--token", str(tmp_path / "t.json"),
        ])
        assert rc == 1

    def test_authorize_interativo_e_erro(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from runtime import google_auth

        class _Tty:
            def isatty(self) -> bool:
                return True

        creds = self._creds_file(tmp_path / "cred.json")
        monkeypatch.setattr("sys.stdin", _Tty())
        monkeypatch.setattr("builtins.input", lambda *a: "http://localhost:8766/?code=xyz")

        def fake_exchange(credentials, code, *, previous_refresh="", transport=None):
            # o handler recebe o que foi colado; o extract_code real roda
            # dentro do exchange (aqui o exchange inteiro é mockado).
            assert "code=xyz" in code
            return GoogleToken(access_token="a", refresh_token="r")

        monkeypatch.setattr(oauth, "exchange_code", fake_exchange)
        assert google_auth.main([
            "--credentials", str(creds), "--token", str(tmp_path / "tok.json"),
        ]) == 0

        def boom(*a, **k):
            raise GoogleError("recusado")

        monkeypatch.setattr(oauth, "exchange_code", boom)
        assert google_auth.main([
            "--credentials", str(creds), "--token", str(tmp_path / "tok2.json"),
        ]) == 1

    def test_authorize_nao_interativo_sem_code(self, tmp_path: Path, monkeypatch) -> None:
        from runtime import google_auth

        creds = self._creds_file(tmp_path / "cred.json")
        monkeypatch.setattr("sys.stdin", io.StringIO(""))  # isatty() -> False
        rc = google_auth.main([
            "--credentials", str(creds), "--token", str(tmp_path / "t.json"),
        ])
        assert rc == 1

    def test_authorize_input_vazio(self, tmp_path: Path, monkeypatch) -> None:
        from runtime import google_auth

        class _Tty:
            def isatty(self) -> bool:
                return True

        creds = self._creds_file(tmp_path / "cred.json")
        monkeypatch.setattr("sys.stdin", _Tty())
        monkeypatch.setattr("builtins.input", lambda *a: "")
        rc = google_auth.main([
            "--credentials", str(creds), "--token", str(tmp_path / "t.json"),
        ])
        assert rc == 1

    def test_main_sem_flags_usa_defaults(self, tmp_path: Path, monkeypatch) -> None:
        # sem --credentials/--token cai no _resolve (env → default); apontando
        # para um arquivo inexistente, autorizar devolve 1 sem crashar.
        # (hermético: o config/google_credentials.json REAL do repositório
        # passou a existir e quebrava este teste — ver 2026-10-03.)
        from runtime import google_auth

        fantasma = tmp_path / "cred_inexistente.json"
        monkeypatch.setattr(
            "runtime.launcher.env",
            lambda k, d="": str(fantasma) if k == "OD_GOOGLE_CREDENTIALS" else d,
        )
        assert google_auth.main(["--url"]) == 1

    def test_check_renova_token_expirado(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from runtime import google_auth

        creds = self._creds_file(tmp_path / "cred.json")
        token = tmp_path / "tok.json"
        save_token(token, _token(valid=False))
        monkeypatch.setattr(
            oauth, "refresh_access_token",
            lambda credentials, tok, transport=None: _token(),
        )
        rc = google_auth.main([
            "--credentials", str(creds), "--token", str(token), "--check",
        ])
        assert rc == 0 and "renovação" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Transporte stdlib (urllib) e utilitários
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestTransport:
    def test_urllib_sucesso(self, monkeypatch) -> None:
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(200, b"ok")
        )
        assert UrllibTransport()("GET", "https://x") == (200, b"ok")

    def test_urllib_httperror_vira_status(self, monkeypatch) -> None:
        def raise_http(req, timeout=None):
            raise urllib.error.HTTPError(
                "u", 404, "nf", {}, io.BytesIO(b'{"error":"x"}')
            )

        monkeypatch.setattr(urllib.request, "urlopen", raise_http)
        assert UrllibTransport()("GET", "https://x") == (404, b'{"error":"x"}')

    def test_urllib_urlerror_vira_googleerror(self, monkeypatch) -> None:
        def raise_url(req, timeout=None):
            raise urllib.error.URLError("dns")

        monkeypatch.setattr(urllib.request, "urlopen", raise_url)
        with pytest.raises(GoogleError):
            UrllibTransport()("GET", "https://x")

    def test_decode_e_checked(self) -> None:
        assert decode_json(b"") == {}
        assert decode_json(b"{invalido") == {}
        assert checked(200, b'{"a":1}', context="x") == {"a": 1}
        with pytest.raises(GoogleError, match="HTTP 500"):
            checked(500, b"not-json", context="x")
        with pytest.raises(GoogleError, match="HTTP 502"):
            checked(502, b"", context="x")


class TestClientExtras:
    def test_load_token_invalido_e_nao_dict(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{nao json", encoding="utf-8")
        assert load_token(bad).authorized is False
        lista = tmp_path / "lista.json"
        lista.write_text("[1, 2]", encoding="utf-8")
        assert load_token(lista).authorized is False

    def test_request_com_json_body_e_raw_erro(self) -> None:
        sent: list[bytes] = []

        def handler(method, url, data):
            sent.append(data or b"")
            return 200, b"{}"

        _client(FakeTransport(handler)).request(
            "POST", "https://g.example/x", json_body={"a": 1}
        )
        assert sent[0] == b'{"a": 1}'
        bad = _client(FakeTransport(lambda m, u, d: (404, b'{"error": {"message": "nf"}}')))
        with pytest.raises(GoogleError, match="nf"):
            bad.request_raw("GET", "https://g.example/y")

    def test_build_google_client(self, tmp_path: Path) -> None:
        creds = tmp_path / "c.json"
        creds.write_text(
            json.dumps({"client_id": "a", "client_secret": "b"}), encoding="utf-8"
        )
        token = tmp_path / "t.json"
        save_token(token, _token())
        client = build_google_client(str(creds), str(token))
        assert client.authorized and client.token.refresh_token == "refresh-1"


class TestOAuthExtras:
    def test_credenciais_incompletas_e_sem_access_token(self) -> None:
        with pytest.raises(GoogleError):
            oauth.exchange_code(GoogleCredentials(client_id="", client_secret=""), "c")
        sem_token = FakeTransport(lambda m, u, d: (200, b'{"scope": "s"}'))
        with pytest.raises(GoogleError):
            oauth.exchange_code(_creds(), "c", transport=sem_token)
        with pytest.raises(GoogleError):
            oauth.refresh_access_token(_creds(), _token(), transport=sem_token)


class TestCalendarExtras:
    def test_list_calendars(self) -> None:
        payload = {"items": [
            {"id": "c1", "summary": "Trabalho", "primary": True, "timeZone": "Z"},
        ]}
        transport = FakeTransport(lambda m, u, d: (200, json.dumps(payload).encode()))
        data = CalendarService(_client(transport)).list_calendars()
        assert data["count"] == 1 and data["calendars"][0]["primary"] is True


class TestGmailExtras:
    def test_corpo_multipart_aninhado(self) -> None:
        body = base64.urlsafe_b64encode(b"texto aninhado").decode().rstrip("=")
        msg = {
            "id": "m2",
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [{"name": "Subject", "value": "S"}],
                "parts": [
                    {"mimeType": "text/html", "body": {"data": ""}},
                    {"mimeType": "text/plain", "body": {"data": body}},
                ],
            },
        }
        transport = FakeTransport(lambda m, u, d: (200, json.dumps(msg).encode()))
        data = GmailService(_client(transport)).get_message("m2")
        assert data["body"] == "texto aninhado"

    def test_list_messages_uma_ruim_nao_derruba(self) -> None:
        def handler(method, url, data):
            if "/messages/m_bom" in url:
                return 200, json.dumps({
                    "id": "m_bom", "payload": {"headers": [
                        {"name": "Subject", "value": "Bom"}], "body": {}},
                }).encode()
            if "/messages/m_ruim" in url:
                return 500, b'{"error": {"message": "falhou"}}'
            return 200, json.dumps({"messages": [{"id": "m_ruim"}, {"id": "m_bom"}]}).encode()

        data = GmailService(_client(FakeTransport(handler))).list_messages()
        assert data["count"] == 2
        assert data["messages"][0]["subject"] == ""  # placeholder da que falhou
        assert data["messages"][1]["subject"] == "Bom"
