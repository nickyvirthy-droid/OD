"""
OMEGA DRAKON • TESTS
Módulo: tests/test_api.py
Descrição: Testes da API REST (integrations/api/) — Fase 5, item 5.2:
           tabela de rotas (17 endpoints), servidor real em loopback
           (ThreadingHTTPServer), API key via X-API-Key, rate limit por IP,
           CORS e comportamento de cada endpoint (health, profiles,
           presence, dashboard/chat HTML, metrics, message sobre o
           Orchestrator, transcribe/tts com handlers plugáveis, history,
           memory search/RAG, ws/chat 501).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/api.py (17 endpoints, porta 8000)
  - docs/NICKY_LEGACY_ANALYSIS.md §9
  - ROADMAP_ABSORCAO.md Fase 5, item 5.2
"""

from __future__ import annotations

import json

from storage.database import Database
from pathlib import Path

import pytest

from core.orchestrator import Orchestrator, RecordingProvider
from core.security import SecurityManager
from integrations.api import (
    APIConfig,
    APIServer,
    DEFAULT_PROFILE,
    ROUTES,
)
from memory.cache import LLMCache
from memory.history import ConversationHistory
from memory.vector import VectorStore
from tools.actions import build_registry


import urllib.request as _urllib_req


class _NoRedirectHandler(_urllib_req.HTTPRedirectHandler):
    """Redirect handler que NÃO segue 3xx — captura o 302 no teste."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(port, method, path, api_key=None, body=None, raw_body=None,
             headers=None):
    """Faz uma requisição HTTP real; devolve (status, corpo, headers)."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}{path}"
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode("utf-8") if body is not None else None
    )
    request = urllib.request.Request(url, data=data, method=method)
    if api_key:
        request.add_header("X-API-Key", api_key)
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


def make_orch(
    base: Path, *, history: bool = True, cache: bool = True,
    database: bool = False,
) -> Orchestrator:
    """Orchestrator com RecordingProvider e memórias opcionais em tmp.
    Com database=True, histórico e cache usam SQLite temporária (com ids)."""
    db = Database(base / "od-test.db") if database else None
    kwargs = {"database": db} if db is not None else {}
    return Orchestrator(
        providers=[RecordingProvider("echo", reply="resposta-od")],
        history=(
            ConversationHistory(base_dir=base / "hist", **kwargs)
            if history else None
        ),
        cache=(
            LLMCache(cache_dir=base / "cache", profile="guardian", **kwargs)
            if cache else None
        ),
    )


@pytest.fixture()
def serve():
    """Sobe APIServers sob demanda e derruba todos no fim do teste."""
    servers: list[APIServer] = []

    def _start(
        orch=None, *, config=None, vector=None
    ) -> APIServer:
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


# ===========================================================================
# Tabela de rotas (17 endpoints do legado)
# ===========================================================================

class TestAPIRoutes:
    """Registro declarativo: 17 rotas com método, handler e auth."""

    def test_routes_mirror_legacy(self) -> None:
        """17 endpoints do legado + /capabilities (v0.27.3) + /site* +
        /actions + /executa (v1.2.0 — app Android) + /push/* (push FCM) +
        /supervision (2026-09-15) + /account/* e /admin/* (painéis
        dashboard/admin, 2026-09-26) + deleção de mensagem única e
        saneamento do cache (2026-09-26)."""
        assert len(ROUTES) == 41
        by = {(r.method, r.path): r for r in ROUTES}
        expected = {
            ("GET", "/"), ("GET", "/health"), ("GET", "/profiles"),
            ("GET", "/profiles/{name}"), ("GET", "/presence/today"),
            ("GET", "/dashboard"), ("GET", "/admin"), ("GET", "/chat"),
            ("GET", "/metrics"),
            ("GET", "/site"), ("GET", "/site/{file}"),
            ("POST", "/auth/register"), ("POST", "/auth/login"),
            ("POST", "/auth/logout"), ("GET", "/auth/me"),
            ("POST", "/account/password"), ("POST", "/account/api-key"),
            ("GET", "/admin/users"),
            ("POST", "/admin/users/{username}/password"),
            ("DELETE", "/admin/users/{username}"),
            ("POST", "/admin/cache/prune"),
            ("GET", "/dashboard/stats"), ("GET", "/llms"),
            ("GET", "/capabilities"), ("GET", "/actions"),
            ("POST", "/message"), ("POST", "/anon/message"),
            ("POST", "/executa"),
            ("POST", "/transcribe"), ("POST", "/tts"),
            ("POST", "/push/register"), ("POST", "/push/unregister"),
            ("POST", "/push/test"), ("GET", "/push/devices"),
            ("GET", "/supervision"),
            ("DELETE", "/history/{user_id}"),
            ("DELETE", "/history/{user_id}/messages/{message_id}"),
            ("GET", "/history/{user_id}/stats"),
            ("GET", "/history/{user_id}"),
            ("GET", "/memory/{user_id}/search"), ("GET", "/ws/chat"),
        }
        assert set(by) == expected

    def test_auth_flags_follow_legacy(self) -> None:
        """Somente os endpoints operacionais pedem API Key (como no legado)."""
        auth = {(r.method, r.path) for r in ROUTES if r.auth}
        assert auth == {
            ("POST", "/account/password"), ("POST", "/account/api-key"),
            ("GET", "/admin/users"),
            ("POST", "/admin/users/{username}/password"),
            ("DELETE", "/admin/users/{username}"),
            ("POST", "/admin/cache/prune"),
            ("GET", "/dashboard/stats"), ("GET", "/llms"),
            ("GET", "/capabilities"), ("GET", "/actions"),
            ("POST", "/message"), ("POST", "/executa"),
            ("POST", "/push/register"), ("POST", "/push/unregister"),
            ("POST", "/push/test"), ("GET", "/push/devices"),
            ("GET", "/supervision"),
            ("POST", "/transcribe"), ("POST", "/tts"),
            ("POST", "/auth/logout"), ("GET", "/auth/me"),
            ("DELETE", "/history/{user_id}"),
            ("DELETE", "/history/{user_id}/messages/{message_id}"),
            ("GET", "/history/{user_id}/stats"),
            ("GET", "/history/{user_id}"),
            ("GET", "/memory/{user_id}/search"), ("GET", "/ws/chat"),
        }
        public = {(r.method, r.path) for r in ROUTES if not r.auth}
        assert public == {
            ("GET", "/"), ("GET", "/health"), ("GET", "/profiles"),
            ("GET", "/profiles/{name}"), ("GET", "/presence/today"),
            ("GET", "/dashboard"), ("GET", "/admin"), ("GET", "/chat"),
            ("GET", "/metrics"),
            ("GET", "/site"), ("GET", "/site/{file}"),
            ("POST", "/auth/register"), ("POST", "/auth/login"),
            ("POST", "/anon/message"),
        }


# ===========================================================================
# Endpoints públicos (sem API Key)
# ===========================================================================

class TestAPIPublicEndpoints:
    """/, /health, /profiles, /presence/today, HTML e /metrics."""

    def test_info(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/")
        data = _json_response((status, body, _))
        assert status == 200
        assert data["name"] == "Omega Drakon REST API"
        assert data["endpoints"] == len(ROUTES)
        assert data["orchestrator"] is True

    def test_health_up_with_orchestrator(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/health")
        data = _json_response((status, body, _))
        assert status == 200 and data["ok"] is True
        assert data["status"] == "up"
        assert data["llms"] == ["echo"]

    def test_health_degraded_without_orchestrator(self, serve) -> None:
        srv = serve(None)
        status, body, _ = _request(srv.bound_port, "GET", "/health")
        data = _json_response((status, body, _))
        assert data["ok"] is False and data["status"] == "degraded"
        assert data["llms"] == []

    def test_profiles_list(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/profiles")
        data = _json_response((status, body, _))
        names = {p["name"] for p in data["profiles"]}
        assert status == 200 and len(names) == 8
        assert "auto" in names and "guardian" in names and "nyx" in names
        assert "nexus" in names
        guardian = next(p for p in data["profiles"] if p["name"] == "guardian")
        assert guardian["default"] is True

    def test_profile_detail_valid_and_unknown(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        port = srv.bound_port
        status, body, _ = _request(port, "GET", "/profiles/regulus")
        data = _json_response((status, body, _))
        assert data["available"] is True and data["default"] is False
        status, body, _ = _request(port, "GET", "/profiles/nao_existe")
        data = _json_response((status, body, _))
        assert status == 200 and data["available"] is False

    def test_presence_today_placeholder(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/presence/today")
        data = _json_response((status, body, _))
        assert data["ok"] is False and "6.2" in data["message"]

    def test_dashboard_and_chat_html(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        port = srv.bound_port
        status, body, headers = _request(port, "GET", "/dashboard")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")
        # 2026-09-26: o /dashboard é o PAINEL DO USUÁRIO (uso, histórico e
        # conta) — não é mais o shell morto com link para /dashboard/stats.
        assert b"Meu painel" in body
        assert b"/history/me/stats" in body
        assert b"/account/password" in body and b"/account/api-key" in body
        assert b"btn-limpar" in body and b"/history/me" in body
        assert headers.get("Cache-Control", "") == "no-store"
        # /admin: shell do painel do dono (dados só nos handlers /admin/users*)
        status, admin_body, admin_headers = _request(port, "GET", "/admin")
        assert status == 200
        assert admin_headers.get("Cache-Control", "") == "no-store"
        assert b"/admin/users" in admin_body
        assert b"/supervision" in admin_body and b"/dashboard/stats" in admin_body
        assert b"resetPass" in admin_body and b"delUser" in admin_body
        status, body, headers = _request(port, "GET", "/chat")
        assert status == 200
        # 2026-09-25: página EVOLUI com o servidor — sem no-store o navegador
        # roda JS velho do cache (histórico "não atualiza" na troca de conta).
        assert headers.get("Cache-Control", "") == "no-store"
        assert b"localStorage" in body  # token salvo no navegador
        # Sessão tem SAÍDA: menu da conta (clique no nome) com Limpar e Sair.
        assert b"btn-logout" in body
        assert b"/auth/logout" in body
        assert b"btn-limpar" in body
        assert "Opções da conta".encode() in body or b"user-dropdown" in body
        # O frame auth do WebSocket leva o token da sessão (sem ele o servidor
        # nega com 4001 e o streaming nunca conecta para quem logou).
        assert b'type: "auth", token: token' in body
        # Histórico carrega ao abrir e avisa quando não carrega.
        assert b"loadHistory" in body and b"hist-note" in body
        # Layout fixo (2026-09-23): header e composer nunca saem da tela —
        # o #chat ocupa o resto com min-height 0 e o scroll fica na lista.
        assert b"min-height: 0" in body
        # Nome do usuário logado visível no cabeçalho.
        assert b"user-badge" in body and b"setUserBadge" in body
        # Histórico agrupado: separador por dia (Hoje/Ontem/data) e hora
        # discreta dentro da bolha (.hist-time).
        assert b"day-sep" in body and b"dayLabel" in body
        assert b"hist-time" in body and b"addHistoryBubble" in body
        # 2026-09-25: histórico e badge pela identidade do SERVIDOR (/history/me
        # + user_id da resposta) e filtro de perfil por sessão (reset no login).
        assert b'/history/me?limit=50' in body
        assert b"resetProfileFilter" in body
        # Abre rolado até a mensagem mais recente (scroll único pós-pintura).
        assert b"scrollToLatest" in body and b"noScroll" in body
        # Paginação infinita: pill no topo + cursor + gatilho por scroll.
        assert b"hist-top" in body and b"loadOlder" in body
        assert b"histOldestId" in body and b"has_more" in body
        # Link para o painel do usuário (2026-09-26).
        assert b'href="/dashboard"' in body
        # Guarda de regressão (2026-09-23): o <script> da página tem que ser JS
        # VÁLIDO — um erro de sintaxe (ex.: quebra de linha dentro de string)
        # mata TODOS os handlers e o site não entra nem no anônimo.
        import re as _re
        import shutil as _shutil
        import subprocess as _subprocess
        import tempfile as _tempfile
        script = _re.search(r"<script>(.*)</script>", body.decode(), _re.S).group(1)
        node = _shutil.which("node")
        if node:  # node é opcional no ambiente de teste
            with _tempfile.NamedTemporaryFile(suffix=".js", mode="wb") as _tmp:
                _tmp.write(script.encode())
                _tmp.flush()
                check = _subprocess.run(
                    [node, "--check", _tmp.name], capture_output=True,
                )
            assert check.returncode == 0, check.stderr.decode()[:400]

    def test_painel_pages_js_compiles(self, serve, tmp_path: Path) -> None:
        """Guarda de regressão (2026-09-26) para os painéis novos: o <script>
        de /dashboard e /admin tem de ser JS VÁLIDO — o bug de escape nos
        onclick do /admin só foi pego no AR porque as páginas não tinham a
        guarda que o /chat ganhou em 2026-09-23."""
        import re as _re
        import shutil as _shutil
        import subprocess as _subprocess
        import tempfile as _tempfile
        srv = serve(make_orch(tmp_path))
        node = _shutil.which("node")
        if not node:
            return
        for path in ("/dashboard", "/admin"):
            _status, body, _h = _request(srv.bound_port, "GET", path)
            script = _re.search(
                r"<script>(.*)</script>", body.decode(), _re.S
            ).group(1)
            with _tempfile.NamedTemporaryFile(suffix=".js", mode="wb") as _tmp:
                _tmp.write(script.encode())
                _tmp.flush()
                check = _subprocess.run(
                    [node, "--check", _tmp.name], capture_output=True,
                )
            assert check.returncode == 0, (
                f"{path}: " + check.stderr.decode()[:400]
            )

    def test_metrics_text(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        port = srv.bound_port
        status, body, headers = _request(port, "GET", "/metrics")
        text = body.decode()
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/plain")
        assert "od_uptime_seconds" in text
        assert "od_processed_total 0" in text
        assert "od_api_requests_total 1" in text
        # Processar mensagem incrementa o contador de LLM
        _request(
            port, "POST", "/message",
            body={"user_id": "alex", "text": "pergunta única"},
        )
        _, body2, _ = _request(port, "GET", "/metrics")
        assert "od_processed_total 1" in body2.decode()


# ===========================================================================
# Site estático (landing + APK) em /site*
# ===========================================================================

class TestAPISite:
    """GET /site serve a landing e /site/{file} serve arquivos (APK).

    Hermético: usa site_dir=tmp_path em vez do site/ real do repo.
    """

    def _cfg(self, tmp_path: Path, **kwargs) -> APIConfig:
        return APIConfig(
            port=0, rate_limit_max=0, site_dir=str(tmp_path), **kwargs
        )

    def test_site_serves_index_html(self, serve, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(
            "<h1>OmegaDrakon</h1>baixar", encoding="utf-8"
        )
        srv = serve(None, config=self._cfg(tmp_path))
        port = srv.bound_port
        status, body, headers = _request(port, "GET", "/site")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")
        assert b"OmegaDrakon" in body and b"baixar" in body
        # /site/ (barra final) resolve no mesmo index
        status, body, _ = _request(port, "GET", "/site/")
        assert status == 200 and b"OmegaDrakon" in body

    def test_site_serves_apk_streaming(self, serve, tmp_path: Path) -> None:
        # > 1 MiB para exercitar o streaming em chunks do handler
        payload = b"x" * (2_500_000)
        (tmp_path / "app.apk").write_bytes(payload)
        srv = serve(None, config=self._cfg(tmp_path))
        status, body, headers = _request(srv.bound_port, "GET", "/site/app.apk")
        assert status == 200
        assert body == payload
        assert int(headers.get("Content-Length", "0")) == len(payload)
        assert headers.get("Accept-Ranges") == "bytes"
        assert headers.get("Content-Type", "") in (
            "application/octet-stream",
            "application/vnd.android.package-archive",
        )
        assert headers.get("Content-Disposition", "").startswith("attachment")

    def test_site_range_requests(self, serve, tmp_path: Path) -> None:
        """Range parcial, sufixo e fora do arquivo (retomada no Android)."""
        payload = bytes(range(256)) * 2000  # 512 KB
        (tmp_path / "app.apk").write_bytes(payload)
        srv = serve(None, config=self._cfg(tmp_path))
        port = srv.bound_port
        status, body, headers = _request(
            port, "GET", "/site/app.apk", headers={"Range": "bytes=1000-1999"}
        )
        assert status == 206
        assert body == payload[1000:2000]
        assert headers.get("Content-Range") == f"bytes 1000-1999/{len(payload)}"
        status, body, _ = _request(
            port, "GET", "/site/app.apk", headers={"Range": "bytes=-10"}
        )
        assert status == 206 and body == payload[-10:]
        status, _, _ = _request(
            port, "GET", "/site/app.apk",
            headers={"Range": f"bytes={len(payload)}-"},
        )
        assert status == 416

    def test_site_html_inline_sem_attachment(self, serve, tmp_path: Path) -> None:
        """A landing continua abrindo no navegador (sem Content-Disposition)."""
        (tmp_path / "index.html").write_text("<h1>OD</h1>", encoding="utf-8")
        srv = serve(None, config=self._cfg(tmp_path))
        status, _, headers = _request(srv.bound_port, "GET", "/site")
        assert status == 200
        assert "Content-Disposition" not in headers

    def test_site_missing_file_404(self, serve, tmp_path: Path) -> None:
        srv = serve(None, config=self._cfg(tmp_path))
        status, _, _ = _request(srv.bound_port, "GET", "/site/nao_existe.apk")
        assert status == 404

    def test_site_path_traversal_blocked(self, serve, tmp_path: Path) -> None:
        secret = tmp_path.parent / "segredo.txt"
        secret.write_text("vazou", encoding="utf-8")
        srv = serve(None, config=self._cfg(tmp_path))
        # %2e%2e evita normalização do client — o handler decodifica o nome
        status, body, _ = _request(
            srv.bound_port, "GET", "/site/%2e%2e/segredo.txt"
        )
        assert status == 404

    def test_site_public_under_auth_all(self, serve, tmp_path: Path) -> None:
        """Landing e APK abrem no navegador mesmo com auth_all."""
        (tmp_path / "index.html").write_text("<h1>OmegaDrakon</h1>",
                                             encoding="utf-8")
        cfg = self._cfg(tmp_path, api_key="segredo123", auth_all=True)
        srv = serve(None, config=cfg)
        port = srv.bound_port
        status, body, _ = _request(port, "GET", "/site")
        assert status == 200 and b"OmegaDrakon" in body
        # Sem page_shells_public, /site fecha e exige a chave
        cfg2 = self._cfg(
            tmp_path, api_key="segredo123", auth_all=True,
            page_shells_public=False,
        )
        srv2 = serve(None, config=cfg2)
        status, _, _ = _request(srv2.bound_port, "GET", "/site")
        assert status == 401


# ===========================================================================
# Auth — API Key via X-API-Key
# ===========================================================================

class TestAPIAuth:
    """Proteção dos endpoints operacionais (mesma semântica do legado)."""

    def test_protected_without_key_rejected(self, serve, tmp_path: Path) -> None:
        cfg = APIConfig(port=0, api_key="segredo123", rate_limit_max=0)
        srv = serve(make_orch(tmp_path), config=cfg)
        status, body, _ = _request(
            srv.bound_port, "POST", "/message",
            body={"user_id": "alex", "text": "oi"},
        )
        data = _json_response((status, body, _))
        assert status == 401 and data["error"] == "unauthorized"

    def test_wrong_key_rejected_correct_accepted(self, serve, tmp_path: Path) -> None:
        cfg = APIConfig(port=0, api_key="segredo123", rate_limit_max=0)
        srv = serve(make_orch(tmp_path), config=cfg)
        port = srv.bound_port
        status, _, _ = _request(port, "GET", "/llms", api_key="errada")
        assert status == 401
        status, body, _ = _request(port, "GET", "/llms", api_key="segredo123")
        assert status == 200
        data = _json_response((status, body, _))
        assert data["llms"] == [{"position": 0, "name": "echo",
                                 "kind": "RecordingProvider"}]

    def test_public_endpoints_need_no_key(self, serve, tmp_path: Path) -> None:
        cfg = APIConfig(port=0, api_key="segredo123", rate_limit_max=0)
        srv = serve(make_orch(tmp_path), config=cfg)
        status, _, _ = _request(srv.bound_port, "GET", "/health")
        assert status == 200

    def test_no_key_configured_means_open(self, serve, tmp_path: Path) -> None:
        # Auth desligada: config sem api_key (dev local explícito)
        srv = serve(make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=0))
        status, _, _ = _request(
            srv.bound_port, "POST", "/message",
            body={"user_id": "alex", "text": "oi"},
        )
        assert status == 200


# ===========================================================================
# Rate limit por IP
# ===========================================================================

class TestAPIRateLimit:
    """Janela deslizante por IP; config 0 desliga."""

    def test_429_after_limit(self, serve, tmp_path: Path) -> None:
        cfg = APIConfig(port=0, rate_limit_max=3, rate_window_s=60.0)
        srv = serve(make_orch(tmp_path), config=cfg)
        port = srv.bound_port
        for _ in range(3):
            assert _request(port, "GET", "/health")[0] == 200
        status, body, _ = _request(port, "GET", "/health")
        data = _json_response((status, body, _))
        assert status == 429
        assert data["error"] == "rate_limited"
        assert data["retry_after_s"] >= 1

    def test_rate_limit_disabled(self, serve, tmp_path: Path) -> None:
        cfg = APIConfig(port=0, rate_limit_max=0)
        srv = serve(make_orch(tmp_path), config=cfg)
        port = srv.bound_port
        for _ in range(50):
            assert _request(port, "GET", "/health")[0] == 200

    def test_limits_are_per_server(self, serve, tmp_path: Path) -> None:
        # Buckets por instância: servidor sem limite não herda 429 do outro
        strict = serve(
            make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=2)
        )
        open_srv = serve(
            make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=0)
        )
        for _ in range(3):
            _request(strict.bound_port, "GET", "/health")
        assert _request(open_srv.bound_port, "GET", "/health")[0] == 200


# ===========================================================================
# POST /message — pipeline sobre o Orchestrator
# ===========================================================================

class TestAPIMessage:
    """Validação e roteamento do pipeline completo."""

    def _send(self, srv: APIServer, body: dict) -> dict:
        status, resp, _ = _request(
            srv.bound_port, "POST", "/message", body=body
        )
        data = _json_response((status, resp, _))
        return {**data, "_status": status}

    def test_missing_fields_rejected(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        port = srv.bound_port
        assert _json_response(_request(port, "POST", "/message",
                                       body={"text": "oi"}))["error"] == \
            "user_id_obrigatorio"
        assert _json_response(_request(port, "POST", "/message",
                                       body={"user_id": "alex"}))["error"] == \
            "text_obrigatorio"

    def test_unknown_profile_rejected(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        data = self._send(srv, {"user_id": "alex", "text": "oi",
                                "profile": "fantasma"})
        assert data["_status"] == 400
        assert "perfil_desconhecido" in data["error"]

    def test_message_runs_pipeline(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        data = self._send(srv, {"user_id": "alex", "text": "pergunta única 1"})
        assert data["_status"] == 200
        assert data["ok"] is True
        assert data["route"] == "llm"
        assert data["message"] == "resposta-od"
        assert data["profile"] == DEFAULT_PROFILE  # padrão guardian
        assert "latency_ms" in data

    def test_message_alias_message_and_implicit_user_id(
        self, serve, tmp_path: Path
    ) -> None:
        """Compat v1.2.0 (app Android): {"message": ...} vira text e
        user_id ausente vira 'app'."""
        srv = serve(make_orch(tmp_path))
        data = self._send(srv, {"message": "pergunta única alias"})
        assert data["_status"] == 200
        assert data["message"] == "resposta-od"
        assert data["user_id"] == "app"

    def test_message_explicit_fields_win_over_alias(
        self, serve, tmp_path: Path
    ) -> None:
        """text/user_id explícitos têm precedência sobre o alias."""
        srv = serve(make_orch(tmp_path))
        data = self._send(
            srv,
            {"text": "pergunta única explícita", "message": "ignorado",
             "user_id": "alex"},
        )
        assert data["_status"] == 200
        assert data["message"] == "resposta-od"
        assert data["user_id"] == "alex"

    def test_second_identical_message_hits_cache(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        first = self._send(srv, {"user_id": "alex", "text": "pergunta única 2"})
        second = self._send(srv, {"user_id": "alex", "text": "pergunta única 2"})
        assert first["route"] == "llm"
        assert second["route"] == "cache" and second["cached"] is True

    def test_profile_and_system_prompt_passed(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        data = self._send(srv, {"user_id": "alex", "text": "pergunta única 3",
                                "profile": "luma"})
        assert data["_status"] == 200
        assert data["profile"] == "luma"
        history = srv.orchestrator.history
        assert history is not None
        assert history.get_history("alex", "luma")  # persistida sob luma

    def test_auto_profile_resolves_by_domain(self, serve, tmp_path: Path) -> None:
        """Modo auto: o perfil é detectado pelo DOMÍNIO do texto (Plêiade).
        Religião → nyx; texto sem domínio mapeado → guardian."""
        srv = serve(make_orch(tmp_path))
        data = self._send(srv, {"user_id": "alex", "text": "pergunta única 4",
                                "profile": "auto"})
        assert data["profile"] == DEFAULT_PROFILE  # sem domínio → guardian
        reli = self._send(srv, {"user_id": "alex",
                                "text": "explique a mitologia grega para mim 742",
                                "profile": "auto"})
        assert reli["_status"] == 200
        assert reli["profile"] == "nyx"

    def test_user_isolation_in_history(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        self._send(srv, {"user_id": "alex", "text": "pergunta única 5"})
        self._send(srv, {"user_id": "bia", "text": "pergunta única 6"})
        history = srv.orchestrator.history
        assert history is not None
        assert history.get_history("alex", "guardian")
        assert history.get_history("bia", "guardian")


# ===========================================================================
# History e Memory (RAG)
# ===========================================================================

class TestAPIHistoryAndMemory:
    """DELETE /history/{uid}, stats e busca semântica (VectorStore)."""

    def _orchestrator(self, tmp_path: Path) -> Orchestrator:
        return make_orch(tmp_path)

    def test_history_stats_and_delete(self, serve, tmp_path: Path) -> None:
        srv = serve(self._orchestrator(tmp_path))
        port = srv.bound_port
        _request(port, "POST", "/message",
                 body={"user_id": "alex", "text": "pergunta única 7"})
        status, body, _ = _request(port, "GET", "/history/alex")
        data_get = _json_response((status, body, _))
        assert data_get["ok"] is True
        assert len(data_get["messages"]) >= 1
        assert any(m["content"] == "pergunta única 7" for m in data_get["messages"])
        status, body, _ = _request(port, "DELETE", "/history/alex")
        data = _json_response((status, body, _))
        assert data["ok"] is True and data["removed"] >= 1
        status, body, _ = _request(port, "GET", "/history/alex/stats")
        assert _json_response((status, body, _))["stats"]["messages"] == 0

    def test_history_unavailable_returns_501(self, serve, tmp_path: Path) -> None:
        orch = make_orch(tmp_path, history=False)
        srv = serve(orch)
        status, _, _ = _request(srv.bound_port, "DELETE", "/history/alex")
        assert status == 501

    def test_memory_search_returns_results(self, serve, tmp_path: Path) -> None:
        orch = self._orchestrator(tmp_path)
        vector = VectorStore(store_dir=tmp_path / "vec")
        vector.add("alex", "a capital do brasil é brasília")
        vector.add("alex", "omega drakon respira tecnologia")
        vector.add("bia", "documento de outro usuário")
        srv = serve(orch, vector=vector)
        status, body, _ = _request(
            srv.bound_port,
            "GET", "/memory/alex/search?q=capital&top_k=2",
        )
        data = _json_response((status, body, _))
        assert data["ok"] is True
        assert len(data["results"]) >= 1
        texts = [r["text"] for r in data["results"]]
        assert any("brasília" in t for t in texts)
        # Isolamento por namespace: nada do usuário 'bia'
        assert all("outro usuário" not in t for t in texts)
        # Score presente e tipado
        assert all(isinstance(r["score"], float) for r in data["results"])

    def test_memory_search_missing_q(self, serve, tmp_path: Path) -> None:
        vector = VectorStore(store_dir=tmp_path / "vec")
        srv = serve(make_orch(tmp_path), vector=vector)
        status, body, _ = _request(srv.bound_port, "GET", "/memory/alex/search")
        assert _json_response((status, body, _))["error"] == "q_obrigatorio"

    def test_memory_search_without_store_501(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, _, _ = _request(
            srv.bound_port, "GET", "/memory/alex/search?q=oi"
        )
        assert status == 501

    def test_top_k_clamped(self, serve, tmp_path: Path) -> None:
        vector = VectorStore(store_dir=tmp_path / "vec", top_k=1)
        for i in range(5):
            vector.add("alex", f"documento número {i}")
        srv = serve(make_orch(tmp_path), vector=vector)
        from urllib.parse import quote

        status, body, _ = _request(
            srv.bound_port,
            "GET", f"/memory/alex/search?q={quote('número')}&top_k=999",
        )
        data = _json_response((status, body, _))
        assert len(data["results"]) <= 20
        assert len(data["results"]) >= 1


# ===========================================================================
# transcribe / tts (handlers plugáveis — STT/TTS reais são Fase 6)
# ===========================================================================

class TestAPIAudio:
    """501 sem handler; funcionais com handlers injetados."""

    def _cfg(self, *, stt=None, tts=None) -> APIConfig:
        return APIConfig(port=0, rate_limit_max=0, stt=stt, tts=tts)

    def test_transcribe_501_without_handler(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(
            srv.bound_port, "POST", "/transcribe",
            body={"audio_b64": "eA=="},
        )
        data = _json_response((status, body, _))
        assert status == 501 and "6.3" in data["error"]

    def test_transcribe_with_handler(self, serve, tmp_path: Path) -> None:
        seen: list[bytes] = []

        def fake_stt(audio: bytes) -> str:
            seen.append(audio)
            return "transcrição do áudio"

        srv = serve(make_orch(tmp_path), config=self._cfg(stt=fake_stt))
        status, body, _ = _request(
            srv.bound_port, "POST", "/transcribe",
            body={"audio_b64": "T2xhISBtdW5kbyE="},
        )
        data = _json_response((status, body, _))
        assert data["ok"] is True
        assert data["text"] == "transcrição do áudio"
        assert seen == [b"Ola! mundo!"]

    def test_transcribe_invalid_base64(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(stt=lambda b: "x"))
        status, body, _ = _request(
            srv.bound_port, "POST", "/transcribe",
            body={"audio_b64": "!!!não-base64!!!"},
        )
        assert _json_response((status, body, _))["error"] == "audio_b64_invalido"

    def test_tts_501_without_handler(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, _, _ = _request(
            srv.bound_port, "POST", "/tts", body={"text": "oi"}
        )
        assert status == 501

    def test_tts_with_handler_roundtrip(self, serve, tmp_path: Path) -> None:
        import base64

        def fake_tts(text: str) -> bytes:
            return f"audio-para-{text}".encode()

        srv = serve(make_orch(tmp_path), config=self._cfg(tts=fake_tts))
        status, body, _ = _request(
            srv.bound_port, "POST", "/tts", body={"text": "bom dia"}
        )
        data = _json_response((status, body, _))
        assert data["ok"] is True
        assert data["bytes"] == len("audio-para-bom dia")
        assert base64.b64decode(data["audio_b64"]) == b"audio-para-bom dia"

    def test_tts_missing_text(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path), config=self._cfg(tts=lambda t: b"x"))
        status, body, _ = _request(srv.bound_port, "POST", "/tts", body={})
        assert _json_response((status, body, _))["error"] == "text_obrigatorio"


# ===========================================================================
# Comportamento HTTP (erros, CORS, método, corpo)
# ===========================================================================

class TestAPIHTTPBehaviour:
    """404/405/CORS/413/JSON inválido e ws/chat 501."""

    def test_ws_chat_501(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/ws/chat")
        data = _json_response((status, body, _))
        assert status == 501 and "WebSocket" in data["error"]

    def test_unknown_path_404(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/nao-existe")
        data = _json_response((status, body, _))
        assert status == 404 and data["error"] == "not_found"

    def test_wrong_method_405_with_allow(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, headers = _request(srv.bound_port, "DELETE", "/message")
        data = _json_response((status, body, headers))
        assert status == 405
        assert data["error"] == "method_not_allowed"
        assert "POST" in data["allow"]

    def test_options_preflight_cors(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, _, headers = _request(srv.bound_port, "OPTIONS", "/message")
        assert status == 204
        assert headers.get("Access-Control-Allow-Origin") == "*"
        assert "X-API-Key" in headers.get(
            "Access-Control-Allow-Headers", ""
        )

    def test_cors_header_on_json(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        _, _, headers = _request(srv.bound_port, "GET", "/health")
        assert headers.get("Access-Control-Allow-Origin") == "*"

    def test_invalid_json_400(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", raw_body=b"{json quebrado"
        )
        data = _json_response((status, body, _))
        assert status == 400 and "json_invalido" in data["error"]

    def test_body_too_large_413(self, serve, tmp_path: Path) -> None:
        cfg = APIConfig(port=0, rate_limit_max=0, max_body_bytes=64)
        srv = serve(make_orch(tmp_path), config=cfg)
        big = json.dumps({"user_id": "a", "text": "x" * 500}).encode()
        status, body, _ = _request(
            srv.bound_port, "POST", "/message", raw_body=big
        )
        assert _json_response((status, body, _))["error"] == "body_too_large"

    def test_dashboard_stats_shape(self, serve, tmp_path: Path) -> None:
        orch = make_orch(tmp_path)
        vector = VectorStore(store_dir=tmp_path / "vec")
        srv = serve(orch, vector=vector)
        status, body, _ = _request(srv.bound_port, "GET", "/dashboard/stats")
        data = _json_response((status, body, _))
        assert data["status"] == "up"
        assert "processed" in data and "avg_latency_ms" in data
        assert "cache" in data and "history" in data
        assert data["vector_store"] == {"docs": 0, "namespaces": []}


# ===========================================================================
# Orchestrator.providers (exposição usada por /llms)
# ===========================================================================

class TestOrchestratorProviders:
    """Propriedade pública adicionada ao Orchestrator para a API."""

    def test_providers_public_tuple(self) -> None:
        orch = Orchestrator(
            providers=[RecordingProvider("primeiro", reply="a")]
        )
        assert [p.name for p in orch.providers] == ["primeiro"]
        orch.add_provider(RecordingProvider("segundo", reply="b"))
        assert [p.name for p in orch.providers] == ["primeiro", "segundo"]

    def test_providers_readonly_snapshot(self) -> None:
        orch = Orchestrator(providers=[RecordingProvider("x", reply="a")])
        snapshot = orch.providers
        snapshot  # tuple — mutações não afetam o registrado
        assert orch.providers[0].name == "x"


# ===========================================================================
# auth_all — API key exigida em TODOS os endpoints (bind na LAN)
# ===========================================================================

class TestAuthAll:
    """Modo de segurança para bind exposto (0.0.0.0): chave em tudo."""

    def test_public_endpoints_require_key(self, serve, tmp_path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="segredo-lan", auth_all=True,
                rate_limit_max=0,
            ),
        )
        # Sem chave: dados/públicos negam (exceto / que é página pública
        # e redireciona 302 para /site quando o Accept é text/html)
        for path in ("/health", "/profiles", "/metrics"):
            status, _body, _h = _request(srv.bound_port, "GET", path)
            assert status == 401, path
        # / sem Accept:text/html sem chave → 200 (redirect 302 seguido
        # pelo opener, que chega em /site — página pública sem auth)
        status, _body, _h = _request(srv.bound_port, "GET", "/")
        assert status == 200
        # / com Accept:text/html sem chave → redirect 302 para /site
        # (verificado pelo redirect_no_follow abaixo)
        import urllib.request as _urllib_req
        import urllib.error as _urllib_err
        url = f"http://127.0.0.1:{srv.bound_port}/"
        req = _urllib_req.Request(url, method="GET")
        req.add_header("Accept", "text/html")
        # opener sem redirect handler: captura o 302 sem seguir
        opener = _urllib_req.build_opener(_NoRedirectHandler)
        try:
            with opener.open(req, timeout=10) as resp:
                loc = resp.headers.get("Location", "")
                assert resp.status == 302
        except _urllib_err.HTTPError as exc:
            loc = exc.headers.get("Location", "")
            assert exc.code == 302
        assert loc.endswith("/site")
        # Com chave: respondem
        for path in ("/health", "/metrics", "/profiles"):
            status, _body, _h = _request(
                srv.bound_port, "GET", path, api_key="segredo-lan"
            )
            assert status == 200, path

    def test_page_shells_open_without_key_but_dataless(self, serve,
                                                       tmp_path) -> None:
        """Shells HTML (UI) carregam sem chave; dados continuam protegidos."""
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="segredo-lan", auth_all=True,
                rate_limit_max=0,
            ),
        )
        # Shell do chat carrega no navegador (sem header possível)
        status, body, _h = _request(srv.bound_port, "GET", "/chat")
        assert status == 200
        assert b"X-API-Key" in body and b"localStorage" in body
        # Shell do dashboard (2026-09-26: painel do usuário) carrega sem
        # chave e SEM dados — números só chegam via fetch autenticado.
        status, body, _h = _request(srv.bound_port, "GET", "/dashboard")
        assert status == 200
        assert b"Meu painel" in body
        assert b"<tbody" in body  # tabelas existem, VAZIAS no shell
        assert b"carregar" not in body and b"od_processed" not in body
        # Mas os DADOS seguem exigindo a chave
        status, _body, _h = _request(
            srv.bound_port, "GET", "/dashboard/stats"
        )
        assert status == 401

    def test_page_shells_closed_when_flag_false(self, serve, tmp_path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="segredo-lan", auth_all=True,
                page_shells_public=False, rate_limit_max=0,
            ),
        )
        status, _body, _h = _request(srv.bound_port, "GET", "/chat")
        assert status == 401

    def test_protected_endpoints_also_require_key(self, serve, tmp_path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="segredo-lan", auth_all=True,
                rate_limit_max=0,
            ),
        )
        status, _body, _h = _request(srv.bound_port, "GET", "/llms")
        assert status == 401
        status, _body, _h = _request(
            srv.bound_port, "GET", "/llms", api_key="segredo-lan"
        )
        assert status == 200

    def test_wrong_key_denied_everywhere(self, serve, tmp_path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="certa", auth_all=True, rate_limit_max=0
            ),
        )
        status, _body, _h = _request(
            srv.bound_port, "GET", "/health", api_key="errada"
        )
        assert status == 401

    def test_auth_all_without_key_denies_all(self, serve, tmp_path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, auth_all=True, rate_limit_max=0),
        )
        status, body, _h = _request(srv.bound_port, "GET", "/health")
        assert status == 401
        assert "sem chave" in body.decode("utf-8")

    def test_auth_all_off_keeps_public_open(self, serve, tmp_path) -> None:
        # Padrão: sem auth_all, públicos continuam abertos (dev/local)
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="segredo", auth_all=False,
                rate_limit_max=0,
            ),
        )
        status, _body, _h = _request(srv.bound_port, "GET", "/health")
        assert status == 200
        status, _body, _h = _request(srv.bound_port, "GET", "/llms")
        assert status == 401


# ===========================================================================
# POST /executa + GET /actions (v1.2.0 — app Android)
# ===========================================================================

class TestAPIAnonimo:
    """POST /anon/message — conversar sem conta, sem credencial e sem rastro."""

    @staticmethod
    def _serve(serve, tmp_path: Path):
        # auth_all ligado: mesmo assim o endpoint anônimo responde sem chave.
        return serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, rate_limit_max=0, auth_all=True, api_key="s3cr3ta",
            ),
        )

    def test_conversa_sem_credencial(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(
            srv.bound_port, "POST", "/anon/message",
            body={"message": "oi anônimo", "profile": "guardian"},
        )
        data = _json_response((status, body, _h))
        assert status == 200 and data["ok"] is True
        assert data["anonimo"] is True
        assert data["user_id"] == "anonimo"

    def test_nada_e_gravado_no_historico(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, _body, _h = _request(
            srv.bound_port, "POST", "/anon/message",
            body={
                "message": "primeira mensagem anônima",
                "profile": "guardian",
                "history": [
                    {"role": "user", "content": "antes"},
                    {"role": "assistant", "content": "ok"},
                ],
            },
        )
        assert status == 200
        history = srv.orchestrator.history
        assert history is not None
        assert history.get_history("anonimo", "guardian") == []

    def test_texto_vazio_400(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(
            srv.bound_port, "POST", "/anon/message", body={"message": "   "},
        )
        data = _json_response((status, body, _h))
        assert status == 400 and data["error"] == "text_obrigatorio"


class TestAPIActions:
    """Catálogo e execução de actions do ActionRegistry via API."""

    @staticmethod
    def _serve(serve, tmp_path: Path, *, with_registry: bool = True):
        registry = (
            build_registry(security=SecurityManager(mode="strict"))
            if with_registry else None
        )
        return serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, rate_limit_max=0, action_registry=registry,
            ),
        )

    def test_actions_catalog_lists_registry(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(srv.bound_port, "GET", "/actions")
        data = _json_response((status, body, _h))
        assert status == 200
        assert data["ok"] is True
        assert data["count"] >= 50  # catálogo completo (56)
        names = [a["name"] for a in data["actions"]]
        assert "system_info" in names
        for item in data["actions"]:
            assert item["risk"] in ("low", "medium", "high")
            assert "description" in item

    def test_actions_catalog_without_registry_503(
        self, serve, tmp_path: Path
    ) -> None:
        srv = self._serve(serve, tmp_path, with_registry=False)
        status, body, _h = _request(srv.bound_port, "GET", "/actions")
        data = _json_response((status, body, _h))
        assert status == 503
        assert data["error"] == "action_registry_indisponivel"

    def test_executa_runs_action(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(
            srv.bound_port, "POST", "/executa",
            body={"action": "system_info"},
        )
        data = _json_response((status, body, _h))
        assert status == 200
        assert data["ok"] is True
        assert data["status"] == "ok"
        assert isinstance(data["data"], dict)

    def test_executa_unknown_action_404(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(
            srv.bound_port, "POST", "/executa",
            body={"action": "nao_existe"},
        )
        data = _json_response((status, body, _h))
        assert status == 404
        assert "action_desconhecida" in data["error"]

    def test_executa_destructive_requires_confirm(
        self, serve, tmp_path: Path
    ) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(
            srv.bound_port, "POST", "/executa",
            body={"action": "filesystem_write",
                  "params": {"path": "/tmp/od-x", "content": "1"}},
        )
        data = _json_response((status, body, _h))
        assert status == 422
        assert "confirmacao_obrigatoria" in data["error"]

    def test_executa_invalid_params_400(self, serve, tmp_path: Path) -> None:
        srv = self._serve(serve, tmp_path)
        status, body, _h = _request(
            srv.bound_port, "POST", "/executa",
            body={"action": "filesystem_info"},  # path obrigatório ausente
        )
        data = _json_response((status, body, _h))
        assert status == 400
        assert data["ok"] is False
        assert data["status"] == "invalid"

    def test_executa_requires_auth(self, serve, tmp_path: Path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="s3cr3ta", auth_all=True, rate_limit_max=0,
            ),
        )
        status, body, _h = _request(
            srv.bound_port, "POST", "/executa", body={"action": "system_info"}
        )
        assert status == 401
        assert "unauthorized" in body.decode("utf-8")


# ===========================================================================
# Push FCM (/push/*) — notificações no app Android
# ===========================================================================

class TestAPIPush:
    """Registro de dispositivos e envio de push pela API."""

    @staticmethod
    def _service(tmp_path: Path):
        """PushService com sender dublê (nada sai na rede)."""
        from core.push import DeviceRegistry, FcmSender, HttpResponse, PushService
        from tests.test_push import FakeTransport

        transport = FakeTransport(
            HttpResponse(200, {}, b'{"name":"projects/p/messages/1"}')
        )
        sender = FcmSender(project_id="nicky-e4f99", transport=transport)
        sender._credentials = type(
            "Cred", (), {"valid": True, "token": "tok", "refresh": lambda s, r: None}
        )()
        sender._credentials_error = None
        return PushService(
            DeviceRegistry(tmp_path / "devices.json"), sender, enabled=True
        )

    def test_register_persiste_token(self, serve, tmp_path: Path) -> None:
        push = self._service(tmp_path)
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, rate_limit_max=0, push=push),
        )

        status, body, _h = _request(
            srv.bound_port, "POST", "/push/register",
            body={"token": "token-do-redmi", "device": "Redmi Note 14"},
        )
        data = _json_response((status, body, _h))

        assert status == 200
        assert data["ok"] is True
        assert data["devices"] == 1
        assert "token-do-redmi" not in json.dumps(data)  # mascarado na resposta
        assert push.registry.tokens() == ["token-do-redmi"]

    def test_register_sem_token_400(self, serve, tmp_path: Path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, rate_limit_max=0, push=self._service(tmp_path)),
        )
        status, body, _h = _request(
            srv.bound_port, "POST", "/push/register", body={}
        )
        assert status == 400
        assert _json_response((status, body, _h))["error"] == "token_obrigatorio"

    def test_unregister_remove(self, serve, tmp_path: Path) -> None:
        push = self._service(tmp_path)
        push.register("t1")
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, rate_limit_max=0, push=push),
        )

        status, body, _h = _request(
            srv.bound_port, "POST", "/push/unregister", body={"token": "t1"}
        )
        data = _json_response((status, body, _h))
        assert status == 200 and data["removed"] is True
        assert push.registry.tokens() == []

    def test_devices_lista_sem_token_inteiro(self, serve, tmp_path: Path) -> None:
        push = self._service(tmp_path)
        push.register("token-bem-secreto-1234", device="Redmi")
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, rate_limit_max=0, push=push),
        )

        status, body, _h = _request(srv.bound_port, "GET", "/push/devices")
        data = _json_response((status, body, _h))

        assert status == 200
        assert data["devices"] == 1
        assert data["project_id"] == "nicky-e4f99"
        assert "token-bem-secreto-1234" not in body.decode("utf-8")

    def test_test_endpoint_envia(self, serve, tmp_path: Path) -> None:
        push = self._service(tmp_path)
        push.register("t1")
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, rate_limit_max=0, push=push),
        )

        status, body, _h = _request(
            srv.bound_port, "POST", "/push/test",
            body={"title": "Oi", "body": "teste"},
        )
        data = _json_response((status, body, _h))

        assert status == 200
        assert data["ok"] is True and data["sent"] == 1

    def test_test_endpoint_503_sem_credencial(self, serve, tmp_path: Path) -> None:
        from core.push import DeviceRegistry, FcmSender, PushService

        push = PushService(
            DeviceRegistry(tmp_path / "d.json"),
            FcmSender(credentials_file=tmp_path / "nao-existe.json"),
            enabled=True,
        )
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(port=0, rate_limit_max=0, push=push),
        )

        status, body, _h = _request(srv.bound_port, "POST", "/push/test", body={})
        data = _json_response((status, body, _h))
        assert status == 503
        assert "push_desligado" in data["error"]

    def test_push_indisponivel_503(self, serve, tmp_path: Path) -> None:
        """Sem PushService montado, os endpoints avisam em vez de estourar."""
        srv = serve(make_orch(tmp_path), config=APIConfig(port=0, rate_limit_max=0))

        for method, path in (
            ("POST", "/push/register"),
            ("POST", "/push/unregister"),
            ("POST", "/push/test"),
            ("GET", "/push/devices"),
        ):
            status, body, _h = _request(
                srv.bound_port, method, path, body={"token": "t"}
            )
            assert status == 503, path
            assert _json_response((status, body, _h))["error"] == "push_indisponivel"

    def test_push_requires_auth(self, serve, tmp_path: Path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="s3cr3ta", auth_all=True, rate_limit_max=0,
                push=self._service(tmp_path),
            ),
        )
        status, _body, _h = _request(
            srv.bound_port, "POST", "/push/register", body={"token": "t"}
        )
        assert status == 401


# ===========================================================================
# GET /supervision — observabilidade dos loops (2026-09-15)
# ===========================================================================

class TestAPISupervision:
    """/supervision expõe o estado dos loops supervisionados (X-API-Key)."""

    @pytest.fixture(autouse=True)
    def _registro_limpo(self):
        from core.supervision import get_supervision

        get_supervision().reset()
        yield
        get_supervision().reset()

    def test_sem_quedas(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/supervision")
        data = _json_response((status, body, _h))
        assert status == 200
        assert data["ok"] is True
        assert data["status"] == "up"
        assert data["degraded"] == []
        assert data["restarts"] == 0
        assert data["loops"] == []
        assert data["window_s"] > 0
        assert isinstance(data["ts"], float)

    def test_loop_caido_degrada(self, serve, tmp_path: Path) -> None:
        from core.supervision import get_supervision

        registro = get_supervision()
        registro.record_drop(
            "telegram", kind="TimeoutError",
            detail="The read operation timed out",
        )
        registro.record_restart("telegram")
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/supervision")
        data = _json_response((status, body, _h))
        assert status == 200  # o core está de pé: degradado, não erro HTTP
        assert data["ok"] is False
        assert data["status"] == "degraded"
        assert data["degraded"] == ["telegram"]
        assert data["restarts"] == 1
        [loop] = data["loops"]
        assert loop["name"] == "telegram"
        assert loop["degraded"] is True
        assert loop["last_kind"] == "TimeoutError"
        assert loop["last_error"] == "The read operation timed out"
        assert loop["age_s"] is not None

    def test_requer_api_key(self, serve, tmp_path: Path) -> None:
        srv = serve(
            make_orch(tmp_path),
            config=APIConfig(
                port=0, api_key="s3cr3ta", auth_all=True, rate_limit_max=0
            ),
        )
        status, _body, _h = _request(srv.bound_port, "GET", "/supervision")
        assert status == 401
        status, body, _h = _request(
            srv.bound_port, "GET", "/supervision", api_key="s3cr3ta"
        )
        assert status == 200
        assert _json_response((status, body, _h))["ok"] is True


class TestHandleErrorDoServidor:
    """Desconexão de cliente não pode virar traceback no journal.

    Regressão do ruído observado em produção (2026-09-15 10:14:41): o
    `handle_error` herdado do socketserver imprime o traceback inteiro no
    stderr quando um cliente aborta a conexão no meio do request. O app
    Android perdendo rede faz isso, e no journal do systemd o traceback
    esconde erro de verdade.
    """

    def _log(self):
        from core.logger import get_logger

        return get_logger("omega.integrations.api")

    def test_override_substitui_o_do_socketserver(self, serve) -> None:
        import socketserver

        assert "handle_error" in APIServer.__dict__
        assert APIServer.handle_error is not socketserver.BaseServer.handle_error

    def test_desconexao_vira_debug_sem_traceback(self, serve, capfd) -> None:
        """Exercita o caminho real: socket abortado com RST durante o request.

        `capfd` (e não `capsys`) porque o logger escreve no stream que capturou
        na criação — só a captura por file descriptor enxerga os dois sinks.
        """
        import socket
        import struct
        import time

        srv = serve()
        log = self._log()
        nivel_antigo = log.level
        log.set_level("DEBUG")
        log.clear_records()
        try:
            sock = socket.create_connection(
                ("127.0.0.1", srv.bound_port), timeout=5
            )
            sock.sendall(b"GET /health HTTP/1.1\r\n")  # request incompleta
            # SO_LINGER zerado manda RST no close: aborta em vez de fechar.
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
            sock.close()

            # Espera o thread de request tratar a desconexão. Sem isso a
            # ausência de traceback passaria por acidente (nada processado).
            prazo = time.time() + 5
            registros: list = []
            while time.time() < prazo:
                registros = [
                    r for r in log.records
                    if r.message == "Cliente desconectou durante o request"
                ]
                if registros:
                    break
                time.sleep(0.05)
        finally:
            log.set_level(nivel_antigo)

        assert registros, "o handle_error não tratou a desconexão"
        [registro] = registros
        assert registro.level_name == "DEBUG"
        assert registro.context["peer"].startswith("127.0.0.1:")
        assert registro.context["error"] == "ConnectionResetError"
        assert "Traceback" not in capfd.readouterr().err

    def test_erro_que_nao_e_desconexao_continua_avisando(
        self, serve, capfd
    ) -> None:
        """O silenciamento é só para desconexão — defeito de verdade continua
        aparecendo (é o risco de tratar todo erro como ruído)."""
        srv = serve()
        log = self._log()
        log.clear_records()
        try:
            raise RuntimeError("falha interna")
        except RuntimeError:
            srv.handle_error(None, ("127.0.0.1", 43210))

        registros = [
            r for r in log.records
            if r.message == "Erro inesperado ao atender request"
        ]
        assert len(registros) == 1
        assert registros[0].level_name == "WARN"
        assert registros[0].context["error"] == "RuntimeError"


# ===========================================================================
# Cache são (2026-09-26) — falha nunca vira resposta permanente
# ===========================================================================

class TestCacheSanidade:
    """Respostas de falha NÃO entram no cache (problem 1 do dono)."""

    def test_falha_nao_e_cacheada(self, serve, tmp_path: Path) -> None:
        """Provider que devolve etiqueta de log [CRIT]: a 2ª chamada NÃO
        pode vir do cache — a falha não vira resposta permanente."""
        from core.orchestrator import _cacheable
        orch = make_orch(tmp_path)
        orch.providers[0].reply = "[NICKY][CRIT] Erro: Não foi possível carregar"
        srv = serve(orch)
        first = _json_response(_request(
            srv.bound_port, "POST", "/message",
            body={"user_id": "alex", "text": "pergunta falha única 1"},
        ))
        assert first["route"] == "llm"
        second = _json_response(_request(
            srv.bound_port, "POST", "/message",
            body={"user_id": "alex", "text": "pergunta falha única 1"},
        ))
        assert second["route"] != "cache", (
            "falha cacheada renasce a cada repetição (sem nexo para sempre)"
        )

    def test_resposta_normal_continua_cacheavel(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path))
        primeiro = _json_response(_request(
            srv.bound_port, "POST", "/message",
            body={"user_id": "alex", "text": "pergunta cacheável 926"},
        ))
        segundo = _json_response(_request(
            srv.bound_port, "POST", "/message",
            body={"user_id": "alex", "text": "pergunta cacheável 926"},
        ))
        assert primeiro["route"] == "llm"
        assert segundo["route"] == "cache" and segundo["cached"] is True

    def test_cacheable_rejeita_etiquetas_e_truncamento(self) -> None:
        from core.orchestrator import _cacheable
        for falha in (
            "[NICKY][CRIT] Erro: x", "[CRIT] y", "[WARN] z",
            "[NICKY][ONLINE] status", "[ONLINE][INFO] ok",
            "[NICKY][INFO] avisando", "[INFO] x",
            "Here's a thinking process to answer",
            "", "resposta cortada,",
        ):
            assert not _cacheable(falha), falha
        for boa in ("Resposta completa.", "Bom dia! Tudo bem?",
                    "Sou a Nicky Virthy."):
            assert _cacheable(boa), boa


# ===========================================================================
# Deleção de mensagem única + saneamento do cache (admin)
# ===========================================================================

class TestHistoryMessageDelete:
    """DELETE /history/{uid}/messages/{mid} — remoção cirúrgica.
    Usa SQLite (database=True): o id é a PK de conversation_messages,
    igual à produção (PostgreSQL)."""

    def test_apaga_uma_mensagem_e_preserva_o_resto(
        self, serve, tmp_path: Path
    ) -> None:
        orch = make_orch(tmp_path, database=True)
        srv = serve(orch)
        port = srv.bound_port
        orch.providers[0].reply = "resposta-do-turno-um"
        _request(port, "POST", "/message",
                 body={"user_id": "alex", "text": "turno um 926"})
        orch.providers[0].reply = "resposta-do-turno-dois"
        _request(port, "POST", "/message",
                 body={"user_id": "alex", "text": "turno dois 926"})
        hist = _json_response(_request(port, "GET", "/history/alex"))
        msgs = hist["messages"]
        assert len(msgs) == 4  # 2 turnos × (user+assistant)
        # Apaga a resposta do 1º turno (a 2ª mensagem, índice 1)
        alvo = msgs[1]
        assert "id" in alvo  # o id vem na resposta para o ✕ do chat
        status, body, _h = _request(
            port, "DELETE", f"/history/alex/messages/{alvo['id']}"
        )
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True
        hist2 = _json_response(_request(port, "GET", "/history/alex"))
        conteudos = [m["content"] for m in hist2["messages"]]
        assert "resposta-do-turno-um" not in conteudos
        assert len(conteudos) == 3
        # O resto intacto
        for resto in (msgs[0], msgs[2], msgs[3]):
            assert resto["content"] in conteudos

    def test_mensagem_de_outro_balde_e_404(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path, database=True))
        port = srv.bound_port
        _request(port, "POST", "/message",
                 body={"user_id": "alex", "text": "minha msg 926"})
        hist = _json_response(_request(port, "GET", "/history/alex"))
        mid = hist["messages"][0]["id"]
        # bia não pode apagar mensagem de alex (404, não revela existência)
        status, body, _h = _request(
            port, "DELETE", f"/history/bia/messages/{mid}"
        )
        assert status == 404
        # id inexistente
        status2, _, _h2 = _request(
            port, "DELETE", "/history/alex/messages/999999"
        )
        assert status2 == 404

    def test_message_id_invalido_e_400(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path, database=True))
        status, body, _h = _request(
            srv.bound_port, "DELETE", "/history/alex/messages/abc"
        )
        assert status == 400
        assert _json_response((status, body, _h))["error"] == "message_id_invalido"

    def test_dono_apaga_no_proprio_balde(self, serve, tmp_path: Path) -> None:
        """Gate de dono: /history/{uid}/messages/{mid} segue o _check_owner."""
        srv = serve(make_orch(tmp_path, database=True))
        port = srv.bound_port
        _request(port, "POST", "/message",
                 body={"user_id": "alex", "text": "msg do alex 926"})
        hist = _json_response(_request(port, "GET", "/history/alex"))
        mid = hist["messages"][0]["id"]
        status, _, _h = _request(
            port, "DELETE", f"/history/alex/messages/{mid}",
            api_key="outra-chave",
        )
        # Sem auth_all, sem api_key configurada: qualquer um passa no gate
        # da rota, mas o balde de bia não tem essa mensagem (404).
        assert status in (200, 404)


class TestAdminCachePrune:
    """POST /admin/cache/prune — saneia entradas de falha do cache LLM."""

    def _seed_cache(self, tmp_path: Path) -> Orchestrator:
        orch = make_orch(tmp_path)
        orch.cache.set("pergunta falha A", "[NICKY][CRIT] Erro:Não carregou")
        orch.cache.set("pergunta boa B", "Resposta boa do guardião.")
        orch.cache.set("pergunta falha C", "resposta truncada,")
        return orch

    def test_dry_run_lista_sem_remover(self, serve, tmp_path: Path) -> None:
        srv = serve(self._seed_cache(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/cache/prune",
            body={"dry_run": True},
        )
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True and data["dry_run"] is True
        assert data["candidatas"] == 2
        assert data["removidas"] == 0
        motivos = " ".join(d["motivo"] for d in data["detalhes"])
        assert "etiqueta" in motivos or "truncada" in motivos

    def test_prune_remove_so_as_falhas(self, serve, tmp_path: Path) -> None:
        orch = self._seed_cache(tmp_path)
        srv = serve(orch)
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/cache/prune", body={}
        )
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["candidatas"] == 2
        assert data["removidas"] == 2
        # A boa sobrevive; as falhas sumiram
        assert orch.cache.get("pergunta boa B") == "Resposta boa do guardião."
        assert orch.cache.get("pergunta falha A") is None
        assert orch.cache.get("pergunta falha C") is None

    def test_prune_com_keys_especificas(self, serve, tmp_path: Path) -> None:
        orch = self._seed_cache(tmp_path)
        srv = serve(orch)
        key_alvo = orch.cache.make_key("pergunta boa B")
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/cache/prune",
            body={"keys": [key_alvo]},
        )
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["removidas"] == 1
        assert orch.cache.get("pergunta boa B") is None
        # As outras ficam
        assert orch.cache.get("pergunta falha A") is not None

    def test_prune_sem_cache_e_503(self, serve, tmp_path: Path) -> None:
        srv = serve(make_orch(tmp_path, cache=False))
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/cache/prune", body={}
        )
        assert status == 503

    def test_prune_keys_invalidas_e_400(self, serve, tmp_path: Path) -> None:
        srv = serve(self._seed_cache(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/cache/prune",
            body={"keys": "não-sou-lista"},
        )
        assert status == 400
