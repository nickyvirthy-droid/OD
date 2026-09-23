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
    LoginGuard,
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

    def _start(orch=None, *, config=None, vector=None) -> APIServer:
        cfg = config or APIConfig(port=0, rate_limit_max=0)
        srv = APIServer(orch, config=cfg, vector=vector)
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

    def test_message_alias_de_transporte_cai_na_conta(
        self, serve, tmp_path, store
    ) -> None:
        """`OD_ACCOUNT_ALIASES` mapeia o `user_id` legado (app) para a conta.

        O app manda `user_id: "app"` fixo; com o alias, a conversa do celular
        cai no mesmo balde da conta do dono — sem tocar no cliente.
        """
        srv = serve(
            make_orch(tmp_path),
            config=self._cfg(
                store, api_key="segredo123", account_aliases={"app": "alex"}
            ),
        )
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key="segredo123",
            body={"user_id": "app", "profile": "auto", "text": "do celular"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "alex"
        history = srv.orchestrator.history
        assert history is not None
        assert history.get_history("alex", data["profile"])
        assert not history.get_history("app", data["profile"])

    def test_message_alias_nao_vale_para_credencial_de_usuario(
        self, serve, tmp_path, store
    ) -> None:
        """A credencial de usuário segue mandando: o alias é só do legado."""
        srv = serve(
            make_orch(tmp_path),
            config=self._cfg(
                store, api_key="segredo123", account_aliases={"app": "alex"}
            ),
        )
        user = store.register("bia", "bia@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key=user.api_key,
            body={"user_id": "app", "profile": "auto", "text": "quem sou eu"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "bia"

    # -- Papéis: dono (OD_API_KEY → conta) x usuário comum -------------------

    @staticmethod
    def _with_registry(serve, tmp_path, store, **kwargs):
        """Serve com ActionRegistry real para exercitar o gate de ações."""
        from core.security.manager import SecurityManager
        from tools.actions import build_registry

        registry = build_registry(security=SecurityManager(mode="strict"))
        return serve(
            make_orch(tmp_path),
            config=TestAuthGate._cfg(
                store, action_registry=registry, **kwargs
            ),
        )

    def test_od_api_key_assume_a_conta_do_dono(
        self, serve, tmp_path, store
    ) -> None:
        """Com OD_OWNER_USERNAME, a chave do servidor vira a conta do dono."""
        srv = serve(
            make_orch(tmp_path),
            config=self._cfg(
                store, api_key="segredo123", owner_username="alex"
            ),
        )
        store.register("alex", "alex@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "GET", "/auth/me", api_key="segredo123"
        )
        data = _json_response((status, body, _))
        assert status == 200
        assert data["user"]["username"] == "alex"
        assert data["via"] == "server" and data["role"] == "admin"

        # E o histórico do dono fica contínuo: a chave grava sob a conta,
        # mesmo mandando ``user_id: "app"`` no corpo (o app do dono).
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key="segredo123",
            body={"user_id": "app", "profile": "auto", "text": "do app"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "alex"

    def test_conta_comum_tem_papel_user(self, serve, tmp_path, store) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=self._cfg(
                store, api_key="segredo123", owner_username="alex"
            ),
        )
        bia = store.register("bia", "bia@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "GET", "/auth/me", api_key=bia.api_key
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["role"] == "user"

    def test_dono_le_qualquer_historico(self, serve, tmp_path, store) -> None:
        """O dono (OD_API_KEY) é admin: lê o histórico de qualquer conta."""
        srv = serve(
            make_orch(tmp_path),
            config=self._cfg(
                store, api_key="segredo123", owner_username="alex"
            ),
        )
        store.register("alex", "alex@example.com", "senha123")
        bia = store.register("bia", "bia@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key=bia.api_key,
            body={"profile": "guardian", "text": "conversa da bia"},
        )
        assert status == 200
        # bia não lê o alex; o dono lê a bia
        status, _, _ = _request(
            srv.bound_port, "GET", "/history/alex/stats", api_key=bia.api_key
        )
        assert status == 403
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/bia/stats", api_key="segredo123"
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["stats"]["messages"] >= 1

    def test_executa_acao_de_admin_e_do_dono(self, serve, tmp_path, store) -> None:
        """A conta comum não roda ação de nível 1 nem destrutiva; o dono roda."""
        srv = self._with_registry(
            serve, tmp_path, store,
            api_key="segredo123", owner_username="alex",
        )
        store.register("alex", "alex@example.com", "senha123")
        bia = store.register("bia", "bia@example.com", "senha123")

        # nível 1 (admin) com conta comum → 403 antes de executar
        status, body, _ = _request(
            srv.bound_port, "POST", "/executa", api_key=bia.api_key,
            body={"action": "system_ping", "params": {"host": "127.0.0.1"}},
        )
        data = _json_response((status, body, _))
        assert status == 403 and "acao_restrita_ao_dono" in data["error"]

        # destrutiva com conta comum → 403 (nem chega à confirmação)
        status, body, _ = _request(
            srv.bound_port, "POST", "/executa", api_key=bia.api_key,
            body={"action": "filesystem_write",
                  "params": {"path": "/tmp/od-x", "content": "1"},
                  "confirm": True},
        )
        data = _json_response((status, body, _))
        assert status == 403 and "acao_restrita_ao_dono" in data["error"]

        # leitura (nível 0) com conta comum → roda
        status, body, _ = _request(
            srv.bound_port, "POST", "/executa", api_key=bia.api_key,
            body={"action": "system_info"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["status"] == "ok"

        # o dono passa pelo gate de admin
        status, body, _ = _request(
            srv.bound_port, "POST", "/executa", api_key="segredo123",
            body={"action": "system_info"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["status"] == "ok"

    def test_executa_destrutiva_do_dono_ainda_pede_confirmacao(
        self, serve, tmp_path, store
    ) -> None:
        srv = self._with_registry(
            serve, tmp_path, store,
            api_key="segredo123", owner_username="alex",
        )
        store.register("alex", "alex@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/executa", api_key="segredo123",
            body={"action": "filesystem_write",
                  "params": {"path": "/tmp/od-x", "content": "1"}},
        )
        data = _json_response((status, body, _))
        assert status == 422 and "confirmacao_obrigatoria" in data["error"]

    @pytest.mark.parametrize(
        "ruim", ["../../etc/passwd", "com espaço", "..", "x" * 65]
    )
    def test_message_legacy_rejects_bad_user_id(
        self, serve, tmp_path, store, ruim
    ) -> None:
        """No modo OD_API_KEY o cliente escolhe o balde — mas só com id de
        formato conhecido (o id vira nome de arquivo no backend JSON)."""
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key="segredo123",
            body={"user_id": ruim, "profile": "auto", "text": "oi"},
        )
        data = _json_response((status, body, _))
        assert status == 400 and data["error"] == "user_id_invalido"

    def test_message_ignores_user_id_from_body_when_authenticated(
        self, serve, tmp_path, store
    ) -> None:
        """Com credencial de usuário o id do corpo é irrelevante — nem chega a
        ser validado, porque a identidade vem da credencial."""
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store, api_key="segredo123")
        )
        user = store.register("alex", "alex@example.com", "senha123")
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", api_key=user.api_key,
            body={"user_id": "../../etc/passwd", "profile": "auto", "text": "oi"},
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "alex"

    def test_login_lockout_blocks_even_correct_password(
        self, serve, tmp_path, store
    ) -> None:
        cfg = self._cfg(store, login_max_attempts=3, login_lockout_s=60.0)
        srv = serve(make_orch(tmp_path), config=cfg)
        store.register("alex", "alex@example.com", "senha123")
        for _ in range(3):
            status, _, _ = _request(
                srv.bound_port, "POST", "/auth/login",
                body={"username": "alex", "password": "errada"},
            )
            assert status == 401
        status, body, _ = _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "alex", "password": "senha123"},
        )
        data = _json_response((status, body, _))
        assert status == 429
        assert data["error"] == "too_many_attempts"
        assert data["retry_after_s"] >= 1

    def test_login_success_resets_account_counter(
        self, serve, tmp_path, store
    ) -> None:
        cfg = self._cfg(store, login_max_attempts=3, login_lockout_s=60.0)
        srv = serve(make_orch(tmp_path), config=cfg)
        store.register("alex", "alex@example.com", "senha123")
        for _ in range(2):
            assert _request(
                srv.bound_port, "POST", "/auth/login",
                body={"username": "alex", "password": "errada"},
            )[0] == 401
        assert _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "alex", "password": "senha123"},
        )[0] == 200
        # Contador zerado: mais 2 falhas ainda não travam
        for _ in range(2):
            assert _request(
                srv.bound_port, "POST", "/auth/login",
                body={"username": "alex", "password": "errada"},
            )[0] == 401
        assert _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "alex", "password": "senha123"},
        )[0] == 200

    def test_login_ip_lock_across_usernames(self, serve, tmp_path, store) -> None:
        """Password spraying: trocar o username não escapa do freio do IP."""
        guard = LoginGuard(max_attempts=10, ip_max_attempts=3, lockout_s=60.0)
        cfg = self._cfg(store, login_guard=guard)
        srv = serve(make_orch(tmp_path), config=cfg)
        store.register("alex", "alex@example.com", "senha123")
        store.register("bia", "bia@example.com", "senha123")
        for name in ("alex", "bia", "alex"):
            assert _request(
                srv.bound_port, "POST", "/auth/login",
                body={"username": name, "password": "errada"},
            )[0] == 401
        # 4a tentativa, agora no usuário bia (sem falhas da conta dela): IP travado
        assert _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "bia", "password": "senha123"},
        )[0] == 429

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


# ===========================================================================
# LoginGuard — freio contra força bruta (unitário, clock falso)
# ===========================================================================

class _Clock:
    """Relógio monotônico controlável para o LoginGuard."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestLoginGuard:
    """Limites por conta e por IP, janela, lockout e reset."""

    def _guard(self, clock: _Clock, **kwargs) -> LoginGuard:
        params = {"max_attempts": 3, "window_s": 60.0, "lockout_s": 120.0}
        params.update(kwargs)
        return LoginGuard(clock=clock, **params)

    def test_releases_until_threshold(self) -> None:
        clock = _Clock()
        guard = self._guard(clock)
        assert guard.retry_after("10.0.0.1", "alex") == 0.0
        assert guard.register_failure("10.0.0.1", "alex") == 0.0
        assert guard.register_failure("10.0.0.1", "alex") == 0.0
        assert guard.retry_after("10.0.0.1", "alex") == 0.0

    def test_locks_at_threshold_and_counts_down(self) -> None:
        clock = _Clock()
        guard = self._guard(clock)
        for _ in range(2):
            guard.register_failure("10.0.0.1", "alex")
        remaining = guard.register_failure("10.0.0.1", "alex")
        assert remaining == 120.0
        clock.advance(30)
        assert guard.retry_after("10.0.0.1", "alex") == 90.0

    def test_lockout_expires(self) -> None:
        # ip_max_attempts=3 trava as DUAS chaves — sem isso, o max() com a
        # chave de IP liberada mascara um _remaining que devolvesse negativo.
        clock = _Clock()
        guard = self._guard(clock, ip_max_attempts=3)
        for _ in range(3):
            guard.register_failure("10.0.0.1", "alex")
        assert guard.retry_after("10.0.0.1", "alex") > 0
        clock.advance(121)
        assert guard.retry_after("10.0.0.1", "alex") == 0.0

    def test_failures_outside_window_do_not_accumulate(self) -> None:
        clock = _Clock()
        guard = self._guard(clock)
        for _ in range(3):
            guard.register_failure("10.0.0.1", "alex")
            clock.advance(61)  # cada falha sai da janela de 60s
        assert guard.retry_after("10.0.0.1", "alex") == 0.0

    def test_reset_clears_account_but_not_ip(self) -> None:
        clock = _Clock()
        guard = self._guard(clock, ip_max_attempts=3)
        for _ in range(3):
            guard.register_failure("10.0.0.1", "alex")
        assert guard.retry_after("10.0.0.1", "alex") > 0
        guard.reset("10.0.0.1", "alex")
        # Conta liberada, mas o IP continua travado (o reset não zera o IP)
        assert guard.retry_after("10.0.0.1", "alex") > 0
        assert guard.retry_after("10.0.0.1", "bia") > 0

    def test_ip_lock_catches_username_spraying(self) -> None:
        clock = _Clock()
        guard = self._guard(clock, max_attempts=10, ip_max_attempts=3, lockout_s=120.0)
        assert guard.register_failure("10.0.0.1", "alex") == 0.0
        assert guard.register_failure("10.0.0.1", "bia") == 0.0
        # 3ª falha do IP (username novo, conta sem histórico) já trava
        assert guard.register_failure("10.0.0.1", "carol") > 0
        assert guard.retry_after("10.0.0.1", "dave") > 0
        # Outro IP não foi afetado
        assert guard.retry_after("10.0.0.2", "dave") == 0.0

    def test_gc_bounds_tracked_keys(self) -> None:
        clock = _Clock()
        guard = self._guard(clock)
        for i in range(50):
            guard.register_failure("10.0.0.1", f"u{i}")
        clock.advance(61)
        guard.register_failure("10.0.0.2", "alex")  # dispara o _gc
        assert guard.snapshot()["tracked_keys"] <= 2


# ===========================================================================
# Dono do recurso — /history e /memory por username
# ===========================================================================

class TestHistoryOwnership:
    """Cada usuário só lê/apaga o PRÓPRIO histórico; OD_API_KEY é admin.

    Antes, qualquer credencial válida acessava o histórico de qualquer
    username — inofensivo enquanto todos eram o balde "web"; desde que cada
    pessoa tem conta e senha, era leitura (e exclusão) de conversa alheia.
    """

    @staticmethod
    def _cfg(store, **kwargs) -> APIConfig:
        return APIConfig(port=0, rate_limit_max=0, user_store=store, **kwargs)

    @staticmethod
    def _seed(srv, user: str, texto: str) -> None:
        """Escreve uma interação no histórico do usuário (backend do servidor)."""
        history = srv.orchestrator.history
        assert history is not None
        history.add_message(user, "guardian", "user", texto)

    def test_user_reads_own_history_stats(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        self._seed(srv, "alex", "minha conversa")
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/alex/stats", bearer=token
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["ok"] is True
        assert data["stats"]["messages"] == 1

        # GET /history/alex lista as mensagens
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/alex", bearer=token
        )
        data_msgs = _json_response((status, body, _))
        assert status == 200 and data_msgs["ok"] is True
        assert len(data_msgs["messages"]) == 1
        assert data_msgs["messages"][0]["content"] == "minha conversa"

        # GET /history/me resolve para a própria conta
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/me", bearer=token
        )
        data_me = _json_response((status, body, _))
        assert status == 200 and data_me["user_id"] == "alex"
        assert len(data_me["messages"]) == 1

    def test_username_case_does_not_open_another_bucket(
        self, serve, tmp_path, store
    ) -> None:
        """`/history/Alex` casa com a conta 'alex' (o registro é lowercase)."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        self._seed(srv, "alex", "minha conversa")
        status, _, _ = _request(
            srv.bound_port, "GET", "/history/Alex/stats", bearer=token
        )
        assert status == 200
        # 'Alex' (maiúsculo) também não é um balde separado: nada para 'alex2'
        status, _, _ = _request(
            srv.bound_port, "GET", "/history/alex2/stats", bearer=token
        )
        assert status == 403

    def test_user_denied_read_of_other_history(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store, api_key="segredo123"))
        store.register("alex", "alex@example.com", "senha123")
        store.register("bia", "bia@example.com", "senha123")
        token = store.login("alex", "senha123")
        self._seed(srv, "bia", "conversa privada da bia")
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/bia/stats", bearer=token
        )
        assert status == 403
        assert _json_response((status, body, _))["error"] == "acesso_negado"

    def test_user_denied_delete_of_other_history(
        self, serve, tmp_path, store
    ) -> None:
        """O furo mais grave: apagar a conversa de outra conta."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        store.register("bia", "bia@example.com", "senha123")
        token = store.login("alex", "senha123")
        self._seed(srv, "bia", "conversa privada da bia")
        status, _, _ = _request(
            srv.bound_port, "DELETE", "/history/bia", bearer=token
        )
        assert status == 403
        # Nada foi apagado: a conversa da bia continua inteira
        history = srv.orchestrator.history
        assert history is not None
        assert len(history.get_history("bia", "guardian")) == 1

    def test_user_api_key_follows_the_same_rule(
        self, serve, tmp_path, store
    ) -> None:
        """Vale para os dois tipos de credencial de usuário, não só o Bearer."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        alex = store.register("alex", "alex@example.com", "senha123")
        store.register("bia", "bia@example.com", "senha123")
        self._seed(srv, "bia", "conversa privada da bia")
        status, _, _ = _request(
            srv.bound_port, "GET", "/history/bia/stats", api_key=alex.api_key
        )
        assert status == 403
        status, _, _ = _request(
            srv.bound_port, "GET", "/history/alex/stats", api_key=alex.api_key
        )
        assert status == 200

    def test_user_deletes_own_history(self, serve, tmp_path, store) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        self._seed(srv, "alex", "minha conversa")
        status, body, _ = _request(
            srv.bound_port, "DELETE", "/history/alex", bearer=token
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["removed"] == 1
        history = srv.orchestrator.history
        assert history is not None
        assert history.get_history("alex", "guardian") == []

    def test_server_api_key_is_admin(self, serve, tmp_path, store) -> None:
        """OD_API_KEY não tem usuário associado: segue acessando qualquer um."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store, api_key="segredo123"))
        store.register("bia", "bia@example.com", "senha123")
        self._seed(srv, "bia", "conversa privada da bia")
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/bia/stats", api_key="segredo123"
        )
        assert status == 200 and _json_response((status, body, _))["stats"]["messages"] == 1
        status, body, _ = _request(
            srv.bound_port, "DELETE", "/history/bia", api_key="segredo123"
        )
        assert status == 200 and _json_response((status, body, _))["removed"] == 1

    def test_dev_without_user_store_stays_open(self, serve, tmp_path) -> None:
        """Sem UserStore (dev local) não há dono — o comportamento legado fica."""
        srv = serve(make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=0))
        self._seed(srv, "alex", "minha conversa")
        status, _, _ = _request(srv.bound_port, "DELETE", "/history/alex")
        assert status == 200

    def test_memory_search_denied_before_store_check(
        self, serve, tmp_path, store
    ) -> None:
        """403 precede o 501: sem VectorStore, não conta que o store não existe."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(
            srv.bound_port, "GET", "/memory/bia/search?q=oi", bearer=token
        )
        assert status == 403
        assert _json_response((status, body, _))["error"] == "acesso_negado"
        # O próprio usuário cai no 501 real (memória vetorial não conectada)
        status, _, _ = _request(
            srv.bound_port, "GET", "/memory/alex/search?q=oi", bearer=token
        )
        assert status == 501

    def test_memory_search_own_namespace_only(
        self, serve, tmp_path, store
    ) -> None:
        from urllib.parse import quote

        from memory.vector import VectorStore

        vector = VectorStore(store_dir=tmp_path / "vec")
        vector.add("alex", "documento do alex sobre brasília")
        vector.add("bia", "documento da bia sobre outro assunto")
        srv = serve(
            make_orch(tmp_path), config=self._cfg(store), vector=vector
        )
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(
            srv.bound_port, "GET",
            f"/memory/alex/search?q={quote('brasília')}", bearer=token,
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["user_id"] == "alex"
        assert all("da bia" not in r["text"] for r in data["results"])

    def test_conta_nova_responde_200_com_zero(self, serve, tmp_path, store) -> None:
        """Recém-registrado não pode levar 404 no próprio histórico vazio."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/alex/stats", bearer=token
        )
        data = _json_response((status, body, _))
        assert status == 200 and data["stats"]["messages"] == 0

    def test_nome_que_nao_e_de_ninguem_da_404(self, serve, tmp_path, store) -> None:
        """Conta inexistente e sem mensagens → 404 (pega erro de digitação)."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store, api_key="segredo123"))
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/jonas/stats", api_key="segredo123"
        )
        assert status == 404
        assert _json_response((status, body, _))["error"] == "historico_inexistente"
        status, _, _ = _request(
            srv.bound_port, "DELETE", "/history/jonas", api_key="segredo123"
        )
        assert status == 404

    def test_apos_apagar_o_proprio_historico_volta_200_com_zero(
        self, serve, tmp_path, store
    ) -> None:
        """A conta existe: apagar tudo dá 200/zero, não 404."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store))
        store.register("alex", "alex@example.com", "senha123")
        token = store.login("alex", "senha123")
        self._seed(srv, "alex", "minha conversa")
        assert _request(
            srv.bound_port, "DELETE", "/history/alex", bearer=token
        )[0] == 200
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/alex/stats", bearer=token
        )
        assert status == 200 and _json_response((status, body, _))["stats"]["messages"] == 0

    def test_balde_legado_com_mensagens_responde_200(self, serve, tmp_path, store) -> None:
        """Balde sem conta (ex.: `app` do celular) que tem mensagens: 200."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store, api_key="segredo123"))
        self._seed(srv, "app", "do celular")
        status, body, _ = _request(
            srv.bound_port, "GET", "/history/app/stats", api_key="segredo123"
        )
        assert status == 200 and _json_response((status, body, _))["stats"]["messages"] == 1

    def test_no_credential_still_401(self, serve, tmp_path, store) -> None:
        """A checagem de dono não afrouxa o gate: sem credencial → 401."""
        srv = serve(make_orch(tmp_path), config=self._cfg(store, api_key="segredo123"))
        assert _request(srv.bound_port, "GET", "/history/alex/stats")[0] == 401
        assert _request(srv.bound_port, "DELETE", "/history/alex")[0] == 401
        assert _request(
            srv.bound_port, "GET", "/memory/alex/search?q=oi"
        )[0] == 401
