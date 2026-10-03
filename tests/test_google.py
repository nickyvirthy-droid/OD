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
        assert len(console.scopes) == 4  # lote 2 (03/10): escopo cheio

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
        from urllib.parse import unquote

        url = oauth.build_authorization_url(_creds(), state="xyz")
        assert "accounts.google.com" in url
        assert "client_id=cid" in url
        assert "access_type=offline" in url and "prompt=consent" in url
        assert "state=xyz" in url
        livre = unquote(url)
        # Lote 2 (03/10): escopo cheio aprovado pelo dono.
        for escopo in ("/auth/drive", "/auth/calendar.events",
                       "/auth/gmail.modify", "/auth/gmail.send"):
            assert escopo in livre, escopo
        assert "drive.readonly" not in livre  # lote 1 superado

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

    def test_catalogo_tem_as_6_de_leitura_e_7_de_escrita(self) -> None:
        from tools.actions import CATALOG, CATEGORIES

        names = {spec["name"] for spec in CATALOG if spec["category"] == "google"}
        assert names == {
            # leitura (allowlist do papel user)
            "google_drive_list", "google_drive_read", "google_calendar_events",
            "google_gmail_list", "google_gmail_read", "google_gmail_labels",
            # escrita (FORA da allowlist — só admin, com confirmação)
            "google_drive_create", "google_drive_update", "google_drive_delete",
            "google_calendar_create", "google_calendar_delete",
            "google_gmail_send", "google_gmail_delete",
        }
        assert CATEGORIES["google"] == 13

    def test_escrita_nunca_entra_na_allowlist_do_user(self) -> None:
        """Papel user NÃO pode escrever no Google (gate admin, lote 2)."""
        from core.security.permissions import DEFAULT_ROLE_PERMISSIONS

        permitidas = set(DEFAULT_ROLE_PERMISSIONS["user"])
        escrita = {
            "google_drive_create", "google_drive_update", "google_drive_delete",
            "google_calendar_create", "google_calendar_delete",
            "google_gmail_send", "google_gmail_delete",
        }
        assert not (escrita & permitidas)


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


# ---------------------------------------------------------------------------
# Escrita (lote 2, 2026-10-03) — serviços com HTTP 100% mockado
# ---------------------------------------------------------------------------

class TestDriveEscrita:
    def test_find_by_name_escapa_aspas_e_exige_nao_lixeira(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b'{"files": []}'))
        DriveService(_client(transport)).find_by_name("o'neill\\x")
        url = transport.calls[0]["url"]
        assert "name+%3D+%27" in url  # name = '...'
        assert "trashed+%3D+false" in url
        assert "o%5C%27neill" in url  # aspas simples escapadas (URL-encoded)

    def test_create_file_multipart(self) -> None:
        transport = FakeTransport(
            lambda m, u, d: (200, b'{"id": "f1", "name": "atas", "mimeType": "text/plain",'
                             b' "webViewLink": "https://x/f1"}')
        )
        data = DriveService(_client(transport)).create_file("atas", "conteudo")
        call = transport.calls[0]
        assert call["method"] == "POST"
        assert "uploadType=multipart" in call["url"]
        assert b"multipart/related" in call["headers"]["Content-Type"].encode()
        assert b"conteudo" in call["data"] and b'"atas"' in call["data"]
        assert data["id"] == "f1" and data["web_view_link"] == "https://x/f1"

    def test_update_content_put_media(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b'{"id": "f1", "name": "n"}'))
        data = DriveService(_client(transport)).update_content("f1", "novo")
        call = transport.calls[0]
        assert call["method"] == "PUT" and "uploadType=media" in call["url"]
        assert call["data"] == b"novo"
        assert data["file_id"] == "f1"

    def test_delete_file(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b"{}"))
        data = DriveService(_client(transport)).delete_file("f9")
        assert transport.calls[0]["method"] == "DELETE"
        assert transport.calls[0]["url"].endswith("/files/f9")
        assert data == {"file_id": "f9", "deleted": True}


class TestCalendarEscrita:
    def test_parse_when_hoje_e_amanha_com_e_sem_hora(self) -> None:
        from integrations.google.calendar import parse_when
        import datetime as dt

        agora = dt.datetime(2026, 10, 3, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        com_hora = parse_when("amanhã às 15h", now=agora)
        # 15h no fuso -03 → 18:00Z (o serviço grava em UTC)
        assert com_hora is not None and com_hora["start"] == "2026-10-04T18:00:00Z"
        dia = parse_when("hoje", now=agora)
        assert dia is not None and dia["start"] == "2026-10-03"
        assert "T" not in dia["start"]  # dia inteiro
        assert parse_when("nunca nunca", now=agora) is None
        assert parse_when("amanhã às 27h", now=agora) is None

    def test_find_events_by_title_exato_casefold(self) -> None:
        payload = {"items": [
            {"id": "e1", "summary": "Reunião", "start": {"date": "2026-10-05"}},
            {"id": "e2", "summary": "Reunião extra", "start": {"date": "2026-10-06"}},
        ]}
        transport = FakeTransport(lambda m, u, d: (200, json.dumps(payload).encode()))
        achados = CalendarService(_client(transport)).find_events_by_title("reunião")
        assert [e["id"] for e in achados] == ["e1"]  # exato, não prefixo

    def test_create_event_com_hora_e_dia_inteiro(self) -> None:
        transport = FakeTransport(
            lambda m, u, d: (200, b'{"id": "ev1", "summary": "Dentista", '
                             b'"start": {"dateTime": "2026-10-04T15:00:00Z"}}')
        )
        svc = CalendarService(_client(transport))
        data = svc.create_event(summary="Dentista", when={
            "start": "2026-10-04T15:00:00Z", "end": "2026-10-04T16:00:00Z",
        })
        call = transport.calls[0]
        assert call["method"] == "POST"
        assert b'"dateTime"' in call["data"]
        assert data["id"] == "ev1"

        transport2 = FakeTransport(lambda m, u, d: (200, b'{"id": "ev2"}'))
        CalendarService(_client(transport2)).create_event(
            summary="Feriado", when={"start": "2026-10-05", "end": "2026-10-06"}
        )
        assert b'"date"' in transport2.calls[0]["data"]

    def test_delete_event(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b"{}"))
        CalendarService(_client(transport)).delete_event("ev1")
        assert transport.calls[0]["method"] == "DELETE"
        assert transport.calls[0]["url"].endswith("/events/ev1")


class TestGmailEscrita:
    def test_send_message_monta_mime_e_base64url(self) -> None:
        import base64 as b64
        import urllib.parse

        sent: list[dict[str, Any]] = []

        def handler(method, url, data):
            sent.append(json.loads(data.decode("utf-8")))
            return 200, b'{"id": "m1", "threadId": "t1"}'

        transport = FakeTransport(handler)
        data = GmailService(_client(transport)).send_message(
            to="ana@ex.com", subject="Oi", body="tudo bem"
        )
        assert "/messages/send" in transport.calls[0]["url"]
        raw = sent[0]["raw"]
        raw += "=" * (-len(raw) % 4)  # padding removido pelo serviço
        mime = b64.urlsafe_b64decode(raw).decode("utf-8")
        assert "To: ana@ex.com" in mime
        assert "Subject: Oi" in mime
        assert "tudo bem" in mime
        assert data["id"] == "m1" and data["to"] == "ana@ex.com"

    def test_trash_message(self) -> None:
        transport = FakeTransport(
            lambda m, u, d: (200, b'{"id": "m1", "labelIds": ["TRASH"]}')
        )
        data = GmailService(_client(transport)).trash_message("m1")
        assert transport.calls[0]["method"] == "POST"
        assert transport.calls[0]["url"].endswith("/messages/m1/trash")
        assert data["trashed"] is True


class TestRequestBody:
    def test_request_body_corpo_cru_e_content_type(self) -> None:
        transport = FakeTransport(lambda m, u, d: (200, b'{"ok": 1}'))
        data = _client(transport).request_body(
            "PUT", "https://g.example/u", body=b"ola", content_type="text/plain",
            params={"uploadType": "media", "vazio": ""},
        )
        call = transport.calls[0]
        assert data == {"ok": 1}
        assert call["method"] == "PUT" and call["data"] == b"ola"
        assert call["headers"]["Content-Type"] == "text/plain"
        assert call["url"].endswith("?uploadType=media")  # vazio removido

    def test_request_body_erro_http_vira_googleerror(self) -> None:
        transport = FakeTransport(lambda m, u, d: (403, b'{"error": {"message": "sem escopo"}}'))
        with pytest.raises(GoogleError, match="sem escopo"):
            _client(transport).request_body(
                "POST", "https://g.example/u", body=b"x", content_type="text/plain"
            )


# ---------------------------------------------------------------------------
# Confirmação de 2 passos da ESCRITA (espelho do ha_device_control)
# ---------------------------------------------------------------------------

def _write_client(handler=None) -> GoogleClient:
    return _client(FakeTransport(handler))


class TestEscritaConfirmacao:
    """1ª menção pede 'sim'; o MESMO user executa dentro do TTL; consumo
    só após sucesso; alvo ausente/ambíguo/não-existente recusam ANTES."""

    def _drive_unico(self) -> GoogleClient:
        # find_by_name devolve UM arquivo → resolve o alvo falado.
        def handler(method, url, data):
            if method == "GET" and "files?" in url:
                return 200, json.dumps({"files": [{
                    "id": "f1", "name": "notas", "mimeType": "text/plain",
                    "modifiedTime": "2026-10-01T00:00:00Z",
                }]}).encode()
            if method == "PUT":
                return 200, b'{"id": "f1", "name": "notas"}'
            if method == "DELETE":
                return 200, b"{}"
            return 200, b'{"files": []}'

        return _write_client(handler)

    def setup_method(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(None)
        actions._WRITE_CONFIRMATIONS.clear()

    def teardown_method(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(None)
        actions._WRITE_CONFIRMATIONS.clear()

    def test_sem_cliente_degrada_para_todos(self) -> None:
        from tools.actions import actions

        for nome, kwargs in (
            ("google_drive_create", {"name": "x"}),
            ("google_drive_update", {"name": "x", "content": "y"}),
            ("google_drive_delete", {"name": "x"}),
            ("google_calendar_create", {"titulo": "x"}),
            ("google_calendar_delete", {"titulo": "x"}),
            ("google_gmail_send", {"para": "a@b.com", "corpo": "oi"}),
            ("google_gmail_delete", {"termo": "x"}),
        ):
            result = getattr(actions, nome)(user_id="alex", **kwargs)
            assert result["ok"] is False, nome
            assert "Google" in result["error"], nome

    def test_cria_arquivo_dois_passos(self) -> None:
        from tools.actions import actions

        calls: list[bytes] = []

        def handler(method, url, data):
            calls.append(data or b"")
            return 200, b'{"id": "f1", "name": "atas", "webViewLink": "https://x/f1"}'

        actions.configure_google_client(_write_client(handler))
        r1 = actions.google_drive_create(
            name="atas", content="reunião", user_id="alex", alvo="atas"
        )
        assert r1["ok"] is True and r1["needs_confirmation"] is True
        assert "sim" in r1["hint"].lower() and "atas" in r1["hint"]
        assert calls == []  # 1º passo NÃO escreve
        # 'sim' do MESMO user → mesmo chave → executa
        r2 = actions.google_drive_create(
            name="atas", content="reunião", user_id="alex", alvo="atas"
        )
        assert r2["ok"] is True and r2["executed"] is True
        assert r2["file_id"] == "f1" and len(calls) == 1
        # consumo: um terceiro chamado recomeça o ciclo
        r3 = actions.google_drive_create(
            name="atas", content="reunião", user_id="alex", alvo="atas"
        )
        assert r3.get("needs_confirmation") is True

    def test_user_diferente_nao_confirmacao_alheia(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(_write_client())
        r1 = actions.google_drive_create(name="a", user_id="alex")
        assert r1.get("needs_confirmation") is True
        r2 = actions.google_drive_create(name="a", user_id="outro")
        assert r2.get("needs_confirmation") is True  # chave por USER
        actions.drop_pending_google_write("outro")
        actions.drop_pending_google_write("alex")

    def test_ttl_do_pending(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(_write_client())
        actions.google_drive_create(name="a", user_id="alex")
        assert actions.peek_pending_google_write("alex") is not None
        # envelhece 121s (TTL do contrato é 120s — mutação pega pelo teste)
        key = next(iter(actions._WRITE_CONFIRMATIONS))
        stamp, alvo, params = actions._WRITE_CONFIRMATIONS[key]
        actions._WRITE_CONFIRMATIONS[key] = (stamp - 121.0, alvo, params)
        assert actions.peek_pending_google_write("alex") is None

    def test_peek_e_drop_devolvem_a_acao_e_alvo(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(_write_client())
        actions.google_drive_create(name="atas", user_id="alex", alvo="atas")
        pend = actions.peek_pending_google_write("alex")
        assert pend is not None
        acao, params, alvo = pend
        assert acao == "google_drive_create" and alvo == "atas"
        assert params["name"] == "atas"
        actions.drop_pending_google_write("alex")
        assert actions.peek_pending_google_write("alex") is None

    def test_alvo_nao_encontrado_e_ambiguo_nao_pedem_confirmacao(self) -> None:
        from tools.actions import actions

        nenhum = _write_client(lambda m, u, d: (200, b'{"files": []}'))
        actions.configure_google_client(nenhum)
        r = actions.google_drive_delete(name="fantasma", user_id="alex")
        assert r["ok"] is False and r["error"] == "nao_encontrado"
        assert actions.peek_pending_google_write("alex") is None

        dois = _write_client(lambda m, u, d: (200, json.dumps({"files": [
            {"id": "1", "name": "notas", "mimeType": "text/plain"},
            {"id": "2", "name": "notas", "mimeType": "text/plain"},
        ]}).encode()))
        actions.configure_google_client(dois)
        r2 = actions.google_drive_delete(name="notas", user_id="alex")
        assert r2["ok"] is False and r2["error"] == "alvo_ambiguo"
        assert actions.peek_pending_google_write("alex") is None

    def test_alvo_obrigatorio_sem_nome(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(_write_client())
        r = actions.google_drive_delete(user_id="alex")
        assert r["ok"] is False and r["error"] == "alvo_obrigatorio"
        assert "hint" in r

    def test_arquivo_nativo_do_google_recusa_edicao(self) -> None:
        from tools.actions import actions

        nativo = _write_client(lambda m, u, d: (200, json.dumps({"files": [{
            "id": "1", "name": "doc", "mimeType": "application/vnd.google-apps.document",
        }]}).encode()))
        actions.configure_google_client(nativo)
        r = actions.google_drive_update(name="doc", content="novo", user_id="alex")
        assert r["ok"] is False and r["error"] == "nativo_google"

    def test_update_exige_conteudo(self) -> None:
        from tools.actions import actions

        actions.configure_google_client(self._drive_unico())
        r = actions.google_drive_update(name="notas", content="   ", user_id="alex")
        assert r["ok"] is False and r["error"] == "conteudo_obrigatorio"

    def test_update_e_delete_resolvem_nome_depois_do_sim(self) -> None:
        from tools.actions import actions

        calls: list[tuple[str, bytes]] = []

        def handler(method, url, data):
            calls.append((method, data or b""))
            if method == "GET" and "files?" in url:
                return 200, json.dumps({"files": [{
                    "id": "f1", "name": "notas", "mimeType": "text/plain",
                }]}).encode()
            if method == "PUT":
                return 200, b'{"id": "f1", "name": "notas"}'
            return 200, b"{}"

        actions.configure_google_client(_write_client(handler))
        r1 = actions.google_drive_update(
            name="notas", content="novo", user_id="alex", alvo="notas"
        )
        assert r1.get("needs_confirmation") is True
        r2 = actions.google_drive_update(
            name="notas", content="novo", user_id="alex", alvo="notas"
        )
        assert r2["executed"] is True and r2["file_id"] == "f1"
        # resolve o alvo de NOVO no 2º passo (mesma precisão) e só entao grava
        assert [m for m, _ in calls] == ["GET", "GET", "PUT"]

        # apagar: GET resolve → DELETE executa após o 'sim'
        calls.clear()
        d1 = actions.google_drive_delete(name="notas", user_id="alex")
        assert d1.get("needs_confirmation") is True
        d2 = actions.google_drive_delete(name="notas", user_id="alex")
        assert d2["executed"] is True
        assert [m for m, _ in calls] == ["GET", "GET", "DELETE"]

    def test_erro_do_google_no_meio_nao_consome_a_confirmacao(self) -> None:
        from tools.actions import actions

        estado = {"falha": False}

        def handler(method, url, data):
            if method == "GET" and "files?" in url:
                return 200, json.dumps({"files": [{
                    "id": "f1", "name": "notas", "mimeType": "text/plain",
                }]}).encode()
            if estado["falha"]:
                return 500, b'{"error": {"message": "explodeu"}}'
            return 200, b"{}"

        actions.configure_google_client(_write_client(handler))
        d1 = actions.google_drive_delete(name="notas", user_id="alex")
        assert d1.get("needs_confirmation") is True
        estado["falha"] = True
        d2 = actions.google_drive_delete(name="notas", user_id="alex")
        assert d2["ok"] is False and "explodeu" in d2["error"]
        # consumo é PÓS-sucesso: a intenção continua pendente
        assert actions.peek_pending_google_write("alex") is not None

    def test_agenda_dois_passos_e_quando_obrigatorio(self) -> None:
        from tools.actions import actions

        created: list[bytes] = []

        def handler(method, url, data):
            created.append(data or b"")
            return 200, b'{"id": "ev1", "summary": "Dentista"}'

        actions.configure_google_client(_write_client(handler))
        r1 = actions.google_calendar_create(
            titulo="Dentista", quando="amanhã às 15h", user_id="alex", alvo="Dentista"
        )
        assert r1.get("needs_confirmation") is True and created == []
        r2 = actions.google_calendar_create(
            titulo="Dentista", quando="amanhã às 15h", user_id="alex", alvo="Dentista"
        )
        assert r2["executed"] is True and r2["event_id"] == "ev1"
        assert len(created) == 1 and b'"Dentista"' in created[0]

        # sem 'hoje'/'amanhã' a action recusa (nunca inventa data)
        r3 = actions.google_calendar_create(titulo="X", quando="qualquer dia", user_id="alex")
        assert r3["ok"] is False and r3["error"] == "quando_obrigatorio"
        r4 = actions.google_calendar_create(user_id="alex")
        assert r4["ok"] is False and r4["error"] == "alvo_obrigatorio"

    def test_agenda_delete_dois_passos(self) -> None:
        from tools.actions import actions

        methods: list[str] = []

        def handler(method, url, data):
            methods.append(method)
            if method == "GET":
                return 200, json.dumps({"items": [{
                    "id": "ev1", "summary": "Reunião", "start": {"date": "2026-10-05"},
                }]}).encode()
            return 200, b"{}"

        actions.configure_google_client(_write_client(handler))
        r1 = actions.google_calendar_delete(titulo="Reunião", user_id="alex")
        assert r1.get("needs_confirmation") is True and methods == ["GET"]
        r2 = actions.google_calendar_delete(titulo="Reunião", user_id="alex")
        assert r2["executed"] is True and r2["event_id"] == "ev1"
        assert methods == ["GET", "GET", "DELETE"]  # resolve de novo e apaga
        # título sem evento futuro → nao_encontrado
        r3 = actions.google_calendar_delete(titulo="Nada", user_id="alex")
        assert r3["error"] == "nao_encontrado"

    def test_gmail_enviar_dois_passos_e_validacoes(self) -> None:
        from tools.actions import actions

        sent: list[bytes] = []

        def handler(method, url, data):
            sent.append(data or b"")
            return 200, b'{"id": "m1"}'

        actions.configure_google_client(_write_client(handler))
        r0 = actions.google_gmail_send(para="banana", corpo="oi", user_id="alex")
        assert r0["error"] == "destinatario_invalido"
        r0b = actions.google_gmail_send(para="a@b.com", corpo=" ", user_id="alex")
        assert r0b["error"] == "conteudo_obrigatorio"

        r1 = actions.google_gmail_send(
            para="ana@ex.com", assunto="Oi", corpo="tudo bem",
            user_id="alex", alvo="ana@ex.com",
        )
        assert r1.get("needs_confirmation") is True and sent == []
        r2 = actions.google_gmail_send(
            para="ana@ex.com", assunto="Oi", corpo="tudo bem",
            user_id="alex", alvo="ana@ex.com",
        )
        assert r2["executed"] is True and r2["message_id"] == "m1"
        assert len(sent) == 1

    def test_gmail_delete_dois_passos(self) -> None:
        from tools.actions import actions

        methods: list[str] = []

        def handler(method, url, data):
            methods.append(method)
            if method == "GET" and "/messages/" in url:
                return 200, b'{"id": "m1", "payload": {"headers": []}}'
            if method == "GET":
                return 200, b'{"messages": [{"id": "m1"}]}'
            return 200, b'{"id": "m1", "labelIds": ["TRASH"]}'

        actions.configure_google_client(_write_client(handler))
        r1 = actions.google_gmail_delete(termo="ana", user_id="alex")
        assert r1.get("needs_confirmation") is True
        r2 = actions.google_gmail_delete(termo="ana", user_id="alex")
        assert r2["executed"] is True and r2["message_id"] == "m1"
        assert methods[-1] == "POST"

        # nenhum bate → honesto, nada pendente
        actions.drop_pending_google_write("alex")
        actions.configure_google_client(_write_client(
            lambda m, u, d: (200, b'{"messages": []}')
        ))
        r3 = actions.google_gmail_delete(termo="fantasma", user_id="alex")
        assert r3["error"] == "nao_encontrado"


class TestEscritaFormatter:
    """format_intent_result: permissão/alvo/pendência/execução — nunca LLM."""

    def test_permissao_negada_e_honesta(self) -> None:
        msg = format_intent_result("google_drive_delete", {
            "ok": False, "error": "permissao_negada",
        })
        assert msg is not None
        assert "dono" in msg and "🔒" in msg

    def test_needs_confirmation_usa_o_hint(self) -> None:
        msg = format_intent_result("google_drive_delete", {
            "ok": True, "needs_confirmation": True,
            "hint": "Confirmar: apagar 'notas'? Responda 'sim'.",
        })
        assert msg is not None and "Confirmar" in msg and "sim" in msg

    def test_erros_de_alvo_viram_dica(self) -> None:
        for acao, dados in (
            ("google_drive_delete", {"ok": False, "error": "nao_encontrado",
                                     "hint": "nenhum arquivo chamado 'x'"}),
            ("google_drive_delete", {"ok": False, "error": "alvo_ambiguo",
                                     "hint": "2 arquivos"}),
            ("google_gmail_send", {"ok": False, "error": "destinatario_invalido",
                                   "hint": "preciso do endereço"}),
            ("google_calendar_create", {"ok": False, "error": "quando_obrigatorio",
                                        "hint": "não entendi quando"}),
        ):
            msg = format_intent_result(acao, dados)
            assert msg is not None and "🤔" in msg, acao

    def test_execucao_tem_texto_por_acao(self) -> None:
        casos = {
            "google_drive_create": ({"ok": True, "executed": True, "alvo": "atas",
                                     "link": "https://x/f1"}, "criado"),
            "google_drive_update": ({"ok": True, "executed": True, "alvo": "n"},
                                     "substituído"),
            "google_drive_delete": ({"ok": True, "executed": True, "alvo": "n"},
                                     "apagado"),
            "google_calendar_create": ({"ok": True, "executed": True, "alvo": "d",
                                        "start": "2026-10-04T15:00"}, "criado"),
            "google_calendar_delete": ({"ok": True, "executed": True, "alvo": "d"},
                                        "apagado"),
            "google_gmail_send": ({"ok": True, "executed": True, "alvo": "a@b.com",
                                   "para": "a@b.com", "assunto": "Oi"}, "enviado"),
            "google_gmail_delete": ({"ok": True, "executed": True, "alvo": "x"},
                                     "lixeira"),
        }
        for acao, (dados, termo) in casos.items():
            msg = format_intent_result(acao, dados)
            assert msg is not None and termo in msg, acao

    def test_sem_credencial_continua_honesto(self) -> None:
        msg = format_intent_result("google_gmail_send", {
            "ok": False, "error": "Google não configurado/autorizado",
        })
        assert msg is not None and "não está" in msg


# ---------------------------------------------------------------------------
# Intents do chat (escrita)
# ---------------------------------------------------------------------------

class TestGoogleWriteIntents:
    """Escrita detectada SEM LLM e ANTES da leitura; alvo falado extraído."""

    @pytest.mark.parametrize(
        ("frase", "acao"),
        [
            ("crie o arquivo atas no drive", "google_drive_create"),
            ("crie o arquivo notas com conteúdo: reunião de sexta",
             "google_drive_create"),
            ("edite o arquivo notas com o texto: novo conteúdo",
             "google_drive_update"),
            ("apague o arquivo notas do drive", "google_drive_delete"),
            ("crie o compromisso dentista amanhã às 15h",
             "google_calendar_create"),
            ("apague o compromisso reunião", "google_calendar_delete"),
            ("envie um e-mail para ana@ex.com assunto: oi corpo: tudo bem",
             "google_gmail_send"),
            ("apague o e-mail da ana", "google_gmail_delete"),
        ],
    )
    def test_detecta_escrita(self, frase: str, acao: str) -> None:
        intent = detect_action_intent(frase)
        assert intent is not None and intent[0] == acao, frase

    def test_extrai_parametros(self) -> None:
        assert detect_action_intent("crie o arquivo atas no drive")[1] == {
            "name": "atas", "content": "", "alvo": "atas",
        }
        cria = detect_action_intent("crie o arquivo notas com conteúdo: reunião")[1]
        assert cria["name"] == "notas" and cria["content"] == "reunião"
        agenda = detect_action_intent(
            "crie o compromisso dentista amanhã às 15h"
        )[1]
        assert agenda["titulo"] == "dentista" and agenda["quando"] == "amanhã às 15h"
        mail = detect_action_intent(
            "envie e-mail para ana@ex.com assunto: oi corpo: tudo bem"
        )[1]
        assert mail == {
            "para": "ana@ex.com", "assunto": "oi", "corpo": "tudo bem",
            "alvo": "ana@ex.com",
        }
        assert detect_action_intent("apague o e-mail da ana")[1] == {
            "termo": "ana", "alvo": "ana",
        }

    def test_escrita_vem_antes_da_leitura(self) -> None:
        """'apague o e-mail de X' NUNCA casa como listagem de leitura."""
        assert detect_action_intent("apague o e-mail da ana")[0] == "google_gmail_delete"
        assert detect_action_intent("apague meus e-mails")[0] == "google_gmail_delete"
        # leitura continua indo para as actions de leitura
        assert detect_action_intent("meus e-mails")[0] == "google_gmail_list"
        assert detect_action_intent("minha agenda de hoje")[0] == "google_calendar_events"

    def test_leitura_de_arquivos_locais_nao_vira_escrita_google(self) -> None:
        assert detect_action_intent("liste meus arquivos") is None
        assert detect_action_intent("qual a senha do gmail") is None

    def test_gmail_sem_verbo_de_envio_nao_vira_send(self) -> None:
        intent = detect_action_intent("sobre e-mail para ana")
        assert intent is None or intent[0] != "google_gmail_send"

    def test_escrita_nunca_entra_no_fastpath(self) -> None:
        from core.intents import FASTPATH_ACTIONS, GOOGLE_WRITE_ACTIONS

        assert not (set(GOOGLE_WRITE_ACTIONS) & set(FASTPATH_ACTIONS))
        assert GOOGLE_WRITE_ACTIONS == {
            "google_drive_create", "google_drive_update", "google_drive_delete",
            "google_calendar_create", "google_calendar_delete",
            "google_gmail_send", "google_gmail_delete",
        }

    def test_detect_confirmation_aceita_sim_curto(self) -> None:
        from core.intents import detect_confirmation

        for frase in ("sim", "sim!", "pode", "ok", "isso", "pode sim"):
            assert detect_confirmation(frase) is True, frase
        # frase longa ou comando novo NÃO é confirmação
        assert detect_confirmation("sim, apague o arquivo de ontem que eu quero ver") is False
