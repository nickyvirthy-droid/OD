"""
OMEGA DRAKON • TESTS
Módulo: tests/test_auth.py
Descrição: Autenticação de usuários (integrations/api/auth.py) e as rotas
           /auth/* da API REST — registro, login, sessão (Authorization:
           Bearer), API key de usuário, expiração, logout e a integração com
           o gate de auth do servidor (_check_api_key). A feature subiu em
           produção em 2026-09-19 sem cobertura dedicada; este arquivo pina o
           contrato real (hash de senha, unicidade, isolamento de sessão e o
           caminho de credencial ponta a ponta pelo HTTP).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/api/auth.py (UserStore)
  - integrations/api/server.py (rotas /auth/*, _check_api_key)
  - docs/CHANGELOG.md (09-19: chat web com login)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.orchestrator import Orchestrator, RecordingProvider
from integrations.api import APIConfig, APIServer
from integrations.api.auth import (
    AuthError,
    UserStore,
    _hash_password,
    _verify_password,
)
from memory.cache import LLMCache
from memory.history import ConversationHistory
from storage.database import Database


# ===========================================================================
# Helpers
# ===========================================================================

def make_orch(base: Path) -> Orchestrator:
    """Orchestrator com RecordingProvider (não toca LLM real)."""
    return Orchestrator(
        providers=[RecordingProvider("echo", reply="resposta-od")],
        history=ConversationHistory(base_dir=base / "hist"),
        cache=LLMCache(cache_dir=base / "cache", profile="guardian"),
    )


@pytest.fixture()
def store(tmp_path: Path) -> UserStore:
    """UserStore sobre um SQLite de arquivo (thread-safe com o APIServer)."""
    db = Database(tmp_path / "auth.db")
    yield UserStore(db)
    db.close()


@pytest.fixture()
def serve():
    """Sobe APIServers sob demanda e derruba todos no fim do teste."""
    servers: list[APIServer] = []

    def _start(orch=None, *, config=None) -> APIServer:
        cfg = config or APIConfig(port=0, rate_limit_max=0)
        srv = APIServer(orch, config=cfg)
        srv.serve_background()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        try:
            srv.stop()
        except Exception:  # pragma: no cover — teardown defensivo
            pass


def _request(
    port,
    method,
    path,
    *,
    api_key=None,
    bearer=None,
    body=None,
    headers=None,
):
    """Faz uma requisição HTTP real; devolve (status, corpo, headers)."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if api_key:
        request.add_header("X-API-Key", api_key)
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _json_response(result) -> dict:
    return json.loads(result[1].decode("utf-8"))


# ===========================================================================
# Hash de senha (PBKDF2-SHA256, stdlib)
# ===========================================================================

class TestPasswordHashing:
    """_hash_password/_verify_password — sem bcrypt, sem senha em claro."""

    def test_hash_is_salted_and_verifies(self) -> None:
        first = _hash_password("senha123")
        second = _hash_password("senha123")
        # Salt aleatório: mesmo texto → hashes diferentes
        assert first != second
        assert _verify_password("senha123", first) is True
        assert _verify_password("senha123", second) is True
        assert _verify_password("senha124", first) is False

    def test_stored_format_is_salt_colon_hash(self) -> None:
        stored = _hash_password("senha123")
        salt_hex, hash_hex = stored.split(":", 1)
        assert len(salt_hex) == 64  # 32 bytes em hex
        assert len(hash_hex) == 64  # 32 bytes de chave em hex
        assert "senha123" not in stored

    def test_verify_rejects_malformed_stored_value(self) -> None:
        for stored in ("", "sem-separador", "zz:zz", "abc:def"):
            assert _verify_password("senha123", stored) is False

    def test_password_never_persisted_in_plaintext(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "auth.db")
        user_store = UserStore(db)
        user_store.register("alex", "alex@example.com", "senha123")
        rows = db.query("SELECT password_hash FROM users")
        assert len(rows) == 1
        stored = rows[0]["password_hash"]
        assert stored != "senha123" and ":" in stored
        db.close()


# ===========================================================================
# UserStore — registro
# ===========================================================================

class TestUserStoreRegister:
    """register(): validação, normalização e unicidade."""

    def test_register_creates_user(self, store: UserStore) -> None:
        user = store.register("  Alex ", " Alex@Example.com ", "senha123")
        assert user.id == 1
        assert user.username == "alex"  # stripped + lower
        assert user.email == "alex@example.com"
        assert user.api_key.startswith("od_")
        assert len(user.api_key) == 43  # od_ + 40 hex
        assert store.count() == 1
        assert store.get_user_by_username("ALEX").id == user.id

    def test_register_generates_unique_api_keys(self, store: UserStore) -> None:
        a = store.register("alex", "alex@example.com", "senha123")
        b = store.register("bia", "bia@example.com", "senha123")
        assert a.api_key != b.api_key

    def test_register_rejects_short_username(self, store: UserStore) -> None:
        with pytest.raises(AuthError) as exc:
            store.register("ab", "ab@example.com", "senha123")
        assert exc.value.status == 400
        assert store.count() == 0

    def test_register_rejects_short_password(self, store: UserStore) -> None:
        with pytest.raises(AuthError) as exc:
            store.register("alex", "alex@example.com", "12345")
        assert exc.value.status == 400

    def test_register_rejects_invalid_email(self, store: UserStore) -> None:
        with pytest.raises(AuthError) as exc:
            store.register("alex", "sem-arroba", "senha123")
        assert exc.value.status == 400

    def test_register_duplicate_username_conflicts(self, store: UserStore) -> None:
        store.register("alex", "alex@example.com", "senha123")
        with pytest.raises(AuthError) as exc:
            store.register("ALEX", "outro@example.com", "senha123")
        assert exc.value.status == 409

    def test_register_duplicate_email_conflicts(self, store: UserStore) -> None:
        store.register("alex", "alex@example.com", "senha123")
        with pytest.raises(AuthError) as exc:
            store.register("bia", "alex@example.com", "senha123")
        assert exc.value.status == 409


# ===========================================================================
# UserStore — login e sessões
# ===========================================================================

class TestUserStoreSessions:
    """login/validate_session/logout/expiração."""

    def test_login_returns_valid_session(self, store: UserStore) -> None:
        user = store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        assert token
        current = store.validate_session(token)
        assert current is not None
        assert current.id == user.id
        assert current.username == "alex"

    def test_login_rejects_wrong_password_and_unknown_user(
        self, store: UserStore
    ) -> None:
        store.register("alex", "alex@example.com", "senha123")
        with pytest.raises(AuthError) as wrong:
            store.login("alex", "errada123")
        with pytest.raises(AuthError) as unknown:
            store.login("ninguem", "senha123")
        assert wrong.value.status == 401
        assert unknown.value.status == 401
        # Mesma mensagem: não revela se o usuário existe
        assert str(wrong.value) == str(unknown.value)

    def test_login_is_case_insensitive_on_username(self, store: UserStore) -> None:
        store.register("alex", "alex@example.com", "senha123")
        assert store.validate_session(store.login("ALEX", "senha123")) is not None

    def test_validate_session_rejects_unknown_token(self, store: UserStore) -> None:
        assert store.validate_session("token-inexistente") is None

    def test_session_expires_and_is_cleaned(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "auth.db")
        store = UserStore(db, session_ttl_s=-1)  # já nasce expirada
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        assert store.validate_session(token) is None
        # A sessão expirada é removida na validação
        assert db.query("SELECT 1 FROM sessions WHERE token = ?", (token,)) == []
        db.close()

    def test_logout_invalidates_only_that_session(self, store: UserStore) -> None:
        store.register("alex", "alex@example.com", "senha123")
        token_a = store.login("alex", "senha123")
        token_b = store.login("alex", "senha123")
        store.logout(token_a)
        assert store.validate_session(token_a) is None
        assert store.validate_session(token_b) is not None

    def test_logout_all_removes_every_session_of_user(
        self, store: UserStore
    ) -> None:
        alex = store.register("alex", "alex@example.com", "senha123")
        bia = store.register("bia", "bia@example.com", "senha123")
        alex_token = store.login("alex", "senha123")
        bia_token = store.login("bia", "senha123")
        removed = store.logout_all(alex.id)
        assert removed == 1
        assert store.validate_session(alex_token) is None
        assert store.validate_session(bia_token) is not None
        assert bia.id == 2

    def test_cleanup_expired_counts_removals(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "auth.db")
        store = UserStore(db, session_ttl_s=-1)
        store.register("alex", "alex@example.com", "senha123")
        store.register("bia", "bia@example.com", "senha123")
        store.login("alex", "senha123")
        store.login("bia", "senha123")
        assert store.cleanup_expired() == 2
        db.close()


# ===========================================================================
# UserStore — API keys e consulta
# ===========================================================================

class TestUserStoreApiKeys:
    """login_with_api_key, rotate_api_key e leituras."""

    def test_login_with_api_key(self, store: UserStore) -> None:
        user = store.register("alex", "alex@example.com", "senha123")
        found = store.login_with_api_key(user.api_key)
        assert found is not None and found.id == user.id
        assert store.login_with_api_key("od_invalida") is None

    def test_rotate_api_key(self, store: UserStore) -> None:
        user = store.register("alex", "alex@example.com", "senha123")
        old = user.api_key
        new = store.rotate_api_key(user.id)
        assert new != old and new.startswith("od_")
        assert store.login_with_api_key(old) is None
        assert store.login_with_api_key(new).id == user.id

    def test_get_user_by_id_and_username(self, store: UserStore) -> None:
        user = store.register("alex", "alex@example.com", "senha123")
        assert store.get_user_by_id(user.id).username == "alex"
        assert store.get_user_by_id(999) is None
        assert store.get_user_by_username("ALEX").id == user.id
        assert store.get_user_by_username("ninguem") is None

    def test_list_users_excludes_password_hash(self, store: UserStore) -> None:
        store.register("alex", "alex@example.com", "senha123")
        store.register("bia", "bia@example.com", "senha123")
        users = store.list_users()
        assert [u["username"] for u in users] == ["alex", "bia"]
        assert all("password_hash" not in u for u in users)


# ===========================================================================
# Rotas /auth/* (HTTP)
# ===========================================================================

class TestAuthEndpoints:
    """/auth/register, /auth/login, /auth/logout e /auth/me."""

    @staticmethod
    def _cfg(store, **kwargs) -> APIConfig:
        return APIConfig(port=0, rate_limit_max=0, user_store=store, **kwargs)

    def _register_via_http(self, port, username="alex") -> dict:
        status, body, _ = _request(
            port, "POST", "/auth/register",
            body={"username": username, "email": f"{username}@example.com",
                  "password": "senha123"},
        )
        assert status == 201
        return _json_response((status, body, _))

    def test_register_endpoint(self, serve, tmp_path: Path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        data = self._register_via_http(srv.bound_port)
        assert data["ok"] is True
        assert data["user"]["username"] == "alex"
        assert data["user"]["api_key"].startswith("od_")
        assert "password_hash" not in json.dumps(data)
        assert store.count() == 1

    def test_register_missing_fields_400(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/register",
            body={"username": "alex"},
        )
        assert status == 400
        assert "obrigatórios" in _json_response((status, body, _))["error"]

    def test_register_duplicate_conflict(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        self._register_via_http(srv.bound_port)
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/register",
            body={"username": "alex", "email": "outro@example.com",
                  "password": "senha123"},
        )
        assert status == 409

    def test_register_503_without_user_store(self, serve, tmp_path) -> None:
        srv = serve(make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=0))
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/register",
            body={"username": "alex", "email": "a@b.c", "password": "senha123"},
        )
        assert status == 503
        assert _json_response((status, body, _))["error"] == "auth não configurado"

    def test_login_endpoint_returns_token(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        self._register_via_http(srv.bound_port)
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "alex", "password": "senha123"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["ok"] is True
        assert data["token"]
        assert data["user"]["username"] == "alex"
        assert store.validate_session(data["token"]) is not None

    def test_login_wrong_credentials_401(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        self._register_via_http(srv.bound_port)
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "alex", "password": "errada123"},
        )
        assert status == 401
        assert _json_response((status, body, _))["error"] == "Usuário ou senha inválidos"

    def test_login_missing_fields_400(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        status, _, _ = _request(
            srv.bound_port, "POST", "/auth/login", body={"username": "alex"}
        )
        assert status == 400

    def test_me_via_session_returns_user(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        user = store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(srv.bound_port, "GET", "/auth/me", bearer=token)
        data = _json_response((status, body, _))
        assert status == 200 and data["via"] == "session"
        assert data["user"] == {
            "id": user.id, "username": "alex", "email": "alex@example.com"
        }

    def test_me_via_user_api_key(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        user = store.register("alex", "alex@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "GET", "/auth/me", api_key=user.api_key
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["via"] == "api_key"
        assert data["user"]["username"] == "alex"

    def test_me_without_credentials_401(self, serve, tmp_path, store) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        status, body, _ = _request(srv.bound_port, "GET", "/auth/me")
        assert status == 401
        assert _json_response((status, body, _))["error"] == "unauthorized"

    def test_logout_invalidates_session(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/logout", bearer=token
        )
        assert status == 200 and _json_response((status, body, _))["ok"] is True
        assert store.validate_session(token) is None
        status, _, _ = _request(srv.bound_port, "GET", "/auth/me", bearer=token)
        assert status == 401

    def test_logout_without_bearer_400(self, serve, tmp_path, store) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/logout", api_key="segredo123"
        )
        assert status == 400
        assert _json_response((status, body, _))["error"] == "token não fornecido"


# ===========================================================================
# Gate de auth do servidor (_check_api_key)
# ===========================================================================

class TestAuthGate:
    """Credenciais aceitas/negadas nos endpoints protegidos."""

    @staticmethod
    def _cfg(store, **kwargs) -> APIConfig:
        return APIConfig(port=0, rate_limit_max=0, user_store=store, **kwargs)

    def test_protected_endpoint_accepts_session(
        self, serve, tmp_path, store
    ) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(srv.bound_port, "GET", "/llms", bearer=token)
        assert status == 200
        assert _json_response((status, body, _))["llms"][0]["name"] == "echo"

    def test_protected_endpoint_accepts_user_api_key(
        self, serve, tmp_path, store
    ) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        user = store.register("alex", "alex@example.com", "senha123")
        status, _, _ = _request(
            srv.bound_port, "GET", "/llms", api_key=user.api_key
        )
        assert status == 200

    def test_protected_endpoint_accepts_server_api_key(
        self, serve, tmp_path, store
    ) -> None:
        cfg = self._cfg(store, api_key="segredo123")
        srv = serve(make_orch(tmp_path), config=cfg)
        status, _, _ = _request(srv.bound_port, "GET", "/llms", api_key="segredo123")
        assert status == 200

    def test_bogus_bearer_falls_through_to_401(
        self, serve, tmp_path, store
    ) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        status, _, _ = _request(
            srv.bound_port, "GET", "/llms", bearer="token-falso"
        )
        assert status == 401

    def test_wrong_api_key_rejected(self, serve, tmp_path, store) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        status, _, _ = _request(srv.bound_port, "GET", "/llms", api_key="od_errada")
        assert status == 401

    def test_no_credential_rejected_when_user_store_configured(
        self, serve, tmp_path, store
    ) -> None:
        """Sem OD_API_KEY, a auth de usuários ainda exige credencial.

        Regressão: antes, um Bearer inválido caía no caminho "auth desligada"
        (sem chave configurada) e passava — bypass quando o operador liga a
        autenticação de usuários mas esquece o OD_API_KEY.
        """
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        status, _, _ = _request(srv.bound_port, "GET", "/llms")
        assert status == 401
        status, _, _ = _request(
            srv.bound_port, "GET", "/llms", bearer="token-falso"
        )
        assert status == 401

    def test_dev_without_user_store_stays_open(self, serve, tmp_path) -> None:
        """Sem UserStore e sem chave, o dev local continua aberto."""
        srv = serve(make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=0))
        assert _request(srv.bound_port, "GET", "/llms")[0] == 200

    def test_session_wins_over_wrong_api_key(self, serve, tmp_path, store) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, _, _ = _request(
            srv.bound_port, "GET", "/llms", bearer=token, api_key="chave-errada"
        )
        assert status == 200

    def test_session_authenticates_message_endpoint(
        self, serve, tmp_path, store
    ) -> None:
        """O caminho real do chat web: login → Bearer → POST /message."""
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", bearer=token,
            body={"user_id": "web", "profile": "auto", "text": "ola"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["ok"] is True
        assert data["route"] == "llm" and data["message"] == "resposta-od"

    def test_chat_page_derives_user_id_from_login(
        self, serve, tmp_path, store
    ) -> None:
        """O chat web passa a mandar o username logado (não mais \"web\")."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        status, body, _ = _request(srv.bound_port, "GET", "/chat")
        assert status == 200
        assert b"user_id = data.user.username" in body
        assert b'let user_id = "web"' in body

    def test_message_identity_comes_from_session(
        self, serve, tmp_path, store
    ) -> None:
        """A sessão manda: o user_id do corpo é ignorado."""
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", bearer=token,
            body={"user_id": "outro", "profile": "auto", "text": "quem sou eu"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "alex"
        history = srv.orchestrator.history
        assert history is not None
        assert history.get_history("alex", data["profile"])
        assert not history.get_history("outro", data["profile"])

    def test_message_identity_comes_from_user_api_key(
        self, serve, tmp_path, store
    ) -> None:
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        user = store.register("alex", "alex@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key=user.api_key,
            body={"user_id": "outro", "profile": "auto", "text": "quem sou eu 2"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "alex"

    def test_message_legacy_server_key_keeps_client_user_id(
        self, serve, tmp_path, store
    ) -> None:
        """OD_API_KEY (app/bot) não tem usuário — mantém o user_id do corpo."""
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key="segredo123",
            body={"user_id": "app", "profile": "auto", "text": "legado"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "app"

    def test_auth_endpoints_exempt_under_auth_all(
        self, serve, tmp_path, store
    ) -> None:
        """Com auth_all, register/login continuam acessíveis (o fluxo de
        autenticação não pode exigir autenticação)."""
        cfg = self._cfg(store, api_key="segredo-lan", auth_all=True)
        srv = serve(make_orch(tmp_path), config=cfg)
        port = srv.bound_port
        status, _, _ = _request(
            port, "POST", "/auth/register",
            body={"username": "alex", "email": "alex@example.com",
                  "password": "senha123"},
        )
        assert status == 201
        status, body, _ = _request(
            port, "POST", "/auth/login",
            body={"username": "alex", "password": "senha123"},
        )
        assert status == 200
        token = _json_response((status, body, _))["token"]
        # logout/me são protegidos: sem credencial → 401; com token → 200
        assert _request(port, "POST", "/auth/logout", body={})[0] == 401
        assert _request(port, "GET", "/auth/me", bearer=token)[0] == 200
