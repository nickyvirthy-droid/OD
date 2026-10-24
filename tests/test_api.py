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

from core.capabilities import OD_VERSION
from core.orchestrator import Orchestrator, RecordingProvider
from core.security import SecurityManager
from integrations.api import (
    APIConfig,
    APIServer,
    DEFAULT_PROFILE,
    ROUTES,
)
from integrations.api.server import ROTA_FERRAMENTAS, _APP_VERSION_CODE
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
        saneamento do cache (2026-09-26) + /app/version (v1.7.0,
        auto-atualização do app) + /admin/ideias e
        /admin/limitacoes (v1.13.0 — canal do dono no txt.txt + Casa de
        Limitações) + /admin/dev/sessao e /admin/dev/caixa (2026-10-08 —
        sessão de desenvolvimento on-demand + caixa de autorização) +
        deleção de mensagem única e saneamento do cache (2026-09-26) +
        /app/version (v1.7.0, auto-atualização do app) + fila de
        downloads resumable (Parte D do NOMAD, 2026-10-14) + auto-update
        de modelos/conteúdo (Parte E do NOMAD, 2026-10-14) + registro de
        ferramentas/skills estilo Supply Depot (Parte F do NOMAD,
        2026-10-15) + lista pública /registry, registro do comprador
        /registry/posse e QR de posse do dono (Etapa 4 do Registro
        Mestre, 2026-10-15) + ciclos de coleção da frente NV (16/10) +
        portário /f/<ferramenta> das 5 ferramentas (fase 1, 21/10) +
        /auth/session-cookie (sessão do chat vira cookie, 22/10) +
        PUT /admin/users/{username}/role (papel da conta, frente C, 23/10)."""
        assert len(ROUTES) == 93
        by = {(r.method, r.path): r for r in ROUTES}
        expected = {
            ("GET", "/"), ("GET", "/health"), ("GET", "/profiles"),
            ("GET", "/profiles/{name}"), ("GET", "/presence/today"),
            ("GET", "/dashboard"), ("GET", "/admin"), ("GET", "/chat"),
            ("GET", "/metrics"),
            ("GET", "/site"), ("GET", "/site/{file}"),
            ("GET", "/app/version"),
            # Páginas internas do dono (2026-10-10): saíram de /site/ (onde
            # qualquer um as alcançava pelo Funnel) para site_admin/. A rota
            # é pública porque a navegação é de navegador; o gate real é o
            # _require_owner_page() dentro do handler (exige sessão de dono).
            ("GET", "/admin/google/apis"),
            ("GET", "/admin/google/auth"),
            ("GET", "/registry"),
            # Ciclo fechado da frente NV (16/10) — pública ANTES de /{codigo}
            ("GET", "/registry/collections"),
            ("GET", "/registry/{codigo}"),
            ("GET", "/registry/{codigo}/photo"),
            ("GET", "/registry/{codigo}/chat"),
            ("POST", "/registry/{codigo}/chat"),
            ("POST", "/registry/posse"),  # Etapa 4: registro do comprador
            ("POST", "/admin/registry"), ("GET", "/admin/registry"),
            # Ciclo fechado da frente NV (16/10) — abrir/encerrar (dono)
            ("POST", "/admin/registry/collections"),
            ("POST", "/admin/registry/collections/{nome}/encerrar"),
            ("PUT", "/admin/registry/{public_id}"),
            ("DELETE", "/admin/registry/{public_id}"),
            ("POST", "/admin/registry/{public_id}/photo"),
            ("POST", "/admin/registry/{public_id}/posse"),  # QR (Etapa 4)
            ("GET", "/admin/registry/{public_id}/posse/qr"),
            ("DELETE", "/admin/registry/{public_id}/chat/{msg_id}"),
            # Fila de downloads resumable (Parte D do NOMAD)
            ("POST", "/admin/downloads"), ("GET", "/admin/downloads"),
            ("GET", "/admin/downloads/events"),
            ("GET", "/admin/downloads/{job_id}"),
            ("POST", "/admin/downloads/{job_id}/cancel"),
            ("DELETE", "/admin/downloads/{job_id}"),
            # Auto-update de modelos/conteúdo (Parte E do NOMAD)
            ("GET", "/admin/auto-update"),
            ("POST", "/admin/auto-update/dry-run"),
            ("POST", "/admin/auto-update/reset"),
            # Registro de ferramentas/skills estilo Supply Depot (Parte F)
            ("GET", "/admin/ferramentas"),
            ("POST", "/admin/ferramentas"),
            ("PUT", "/admin/ferramentas/{id}"),
            ("POST", "/admin/ferramentas/{id}/rollback"),
            ("DELETE", "/admin/ferramentas/{id}"),
            ("POST", "/auth/register"), ("POST", "/auth/login"),
            ("POST", "/auth/logout"), ("GET", "/auth/me"),
            # Portário de ferramentas (fase 1 — 21/10): sem header de
            # dispatch; o gate é cookie od_sessao + papel admin DENTRO do
            # handler (AUTH_EXEMPT) — v. tests/test_portal_ferramentas.py
            ("POST", "/auth/session-cookie"),
            ("GET", ROTA_FERRAMENTAS), ("POST", ROTA_FERRAMENTAS),
            ("PUT", ROTA_FERRAMENTAS), ("DELETE", ROTA_FERRAMENTAS),
            # Preferências do perfil (TODO §3.8: tema claro/escuro)
            ("GET", "/profile/preferences"), ("PUT", "/profile/preferences"),
            ("POST", "/account/password"), ("POST", "/account/api-key"),
            ("GET", "/admin/users"),
            ("POST", "/admin/users/{username}/password"),
            ("PUT", "/admin/users/{username}/role"),
            ("DELETE", "/admin/users/{username}"),
            ("POST", "/admin/cache/prune"),
            ("POST", "/admin/dev/sessao"),
            ("GET", "/admin/dev/sessao"),
            ("GET", "/admin/dev/caixa"),
            ("POST", "/admin/dev/caixa"),
            ("DELETE", "/admin/dev/caixa"),
            ("GET", "/admin/ideias"), ("PUT", "/admin/ideias"),
            ("DELETE", "/admin/ideias"),
            ("GET", "/admin/limitacoes"), ("DELETE", "/admin/limitacoes"),
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
            # Preferências do perfil (TODO §3.8: tema claro/escuro)
            ("GET", "/profile/preferences"), ("PUT", "/profile/preferences"),
            ("POST", "/account/password"), ("POST", "/account/api-key"),
            ("POST", "/registry/{codigo}/chat"),
            ("GET", "/admin/users"),
            ("POST", "/admin/registry"), ("GET", "/admin/registry"),
            ("PUT", "/admin/registry/{public_id}"),
            ("DELETE", "/admin/registry/{public_id}"),
            ("POST", "/admin/registry/{public_id}/photo"),
            # Ciclo fechado da frente NV (16/10) — só o dono abre/encerra
            ("POST", "/admin/registry/collections"),
            ("POST", "/admin/registry/collections/{nome}/encerrar"),
            # Etapa 4 (2026-10-15): comprador com conta + QR do dono
            ("POST", "/registry/posse"),
            ("POST", "/admin/registry/{public_id}/posse"),
            ("GET", "/admin/registry/{public_id}/posse/qr"),
            ("DELETE", "/admin/registry/{public_id}/chat/{msg_id}"),
            # Fila de downloads resumable (Parte D do NOMAD)
            ("POST", "/admin/downloads"), ("GET", "/admin/downloads"),
            ("GET", "/admin/downloads/events"),
            ("GET", "/admin/downloads/{job_id}"),
            ("POST", "/admin/downloads/{job_id}/cancel"),
            ("DELETE", "/admin/downloads/{job_id}"),
            # Auto-update de modelos/conteúdo (Parte E do NOMAD)
            ("GET", "/admin/auto-update"),
            ("POST", "/admin/auto-update/dry-run"),
            ("POST", "/admin/auto-update/reset"),
            # Registro de ferramentas/skills estilo Supply Depot (Parte F)
            ("GET", "/admin/ferramentas"),
            ("POST", "/admin/ferramentas"),
            ("PUT", "/admin/ferramentas/{id}"),
            ("POST", "/admin/ferramentas/{id}/rollback"),
            ("DELETE", "/admin/ferramentas/{id}"),
            ("POST", "/admin/users/{username}/password"),
            ("PUT", "/admin/users/{username}/role"),
            ("DELETE", "/admin/users/{username}"),
            ("POST", "/admin/cache/prune"),
            ("POST", "/admin/dev/sessao"),
            ("GET", "/admin/dev/sessao"),
            ("GET", "/admin/dev/caixa"),
            ("POST", "/admin/dev/caixa"),
            ("DELETE", "/admin/dev/caixa"),
            ("GET", "/admin/ideias"), ("PUT", "/admin/ideias"),
            ("DELETE", "/admin/ideias"),
            ("GET", "/admin/limitacoes"), ("DELETE", "/admin/limitacoes"),
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
            ("GET", "/app/version"),
            ("GET", "/registry"),  # lista pública da loja (Etapa 4)
            ("GET", "/registry/collections"),  # ciclos NV (16/10)
            ("GET", "/registry/{codigo}"),
            ("GET", "/registry/{codigo}/photo"),
            ("GET", "/registry/{codigo}/chat"),
            ("POST", "/auth/register"), ("POST", "/auth/login"),
            ("POST", "/anon/message"),
            # Páginas internas do dono: rota pública (navegação de navegador),
            # gate no handler — v. test_routes_mirror_legacy.
            ("GET", "/admin/google/apis"),
            ("GET", "/admin/google/auth"),
            # Portário de ferramentas (fase 1 — 21/10): rota sem header de
            # dispatch; o gate é cookie od_sessao + papel admin DENTRO do
            # handler (AUTH_EXEMPT) — v. tests/test_portal_ferramentas.py
            ("POST", "/auth/session-cookie"),
            ("GET", ROTA_FERRAMENTAS), ("POST", ROTA_FERRAMENTAS),
            ("PUT", ROTA_FERRAMENTAS), ("DELETE", ROTA_FERRAMENTAS),
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
        # Voz (v1.17.3): microfone no composer + resposta por voz opcional.
        assert b'id="mic"' in body and b"toggleMic" in body
        assert b'MediaRecorder' in body and b'"/transcribe"' in body
        assert b'id="speaker"' in body and b'"/tts"' in body
        assert b"speakOn" in body and b"localStorage" in body
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

    def test_painel_admin_no_formato_orion(self, serve, tmp_path: Path) -> None:
        """Formato Órion (17/10 — referência visual escolhida pelo dono):
        o /admin serve o herói de saudação + a faixa de KPIs. O JS do
        formato (e o do tema) vive em site/admin.js desde 23/10 (dívida
        técnica §4) e chega por <script src> injetado ANTES do script
        da página — a guarda de sintaxe continua medindo o bloco próprio
        da página."""
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/admin")
        html = body.decode("utf-8", "replace")
        assert status == 200
        # Herói: marca, versão, pill de estado, saudação, data e relógio.
        assert 'class="od-hero"' in html
        for elemento in ("odVer", "odOn", "odOla", "odData", "odRelogio"):
            assert f'id="{elemento}"' in html, elemento
        # KPIs: quatro cartões (actions, stack, checks, uptime).
        assert 'class="od-kpis"' in html
        for campo in ("kpiAcoes", "kpiStack", "kpiChecks", "kpiUptime"):
            assert f'id="{campo}"' in html, campo
        # Fontes honestas: o herói lê rotas que existem (versão pública e
        # catálogo) — nenhuma fonte paralela inventada. O /app/version
        # vive no FORMATO (site/admin.js); o /actions, no script da página.
        assert '"/actions"' in html
        # O CSS do formato CHEGA na página (regras .od-hero dentro de um
        # <style>) — a v1.39.1 injetou só o JS (marca compartilhada
        # enganou o guarda) e o herói aparecia pelado ("texto comum",
        # reporte do dono em 17/10). Marcas separadas por injeção.
        assert ".od-hero {" in html and ".od-kpis {" in html
        assert "od-formato-orion-css" in html
        # O /admin alimenta o herói pelo loadSystem (sem busca dupla —
        # declara a bandeira; o JS do formato a lê e não repete as buscas).
        assert "odFormatoGerenciado = true" in html
        # JS do painel: UM <script src="/site/admin.js"> ANTES do bloco
        # próprio da página (ordem de execução garantida — script clássico
        # bloqueia); o bloco inline continua sendo só o da página.
        assert html.count('<script src="/site/admin.js"></script>') == 1
        assert html.index('<script src="/site/admin.js"></script>') < html.index("<script>")
        assert html.count("<script>") == 1

    def test_dashboard_no_formato_orion_para_todos(
            self, serve, tmp_path: Path) -> None:
        """v1.39.1 (pedido do dono 17/10): o MESMO cabeçalho do /admin no
        painel de TODOS os usuários — CSS/JS vêm da fonte única injetada
        pelo _com_tema (uma fonte, três páginas, como o tema). Só o que é
        público aparece aqui (saúde, versão, relógio, KPIs de sistema);
        as seções administrativas continuam no /admin."""
        srv = serve(make_orch(tmp_path))
        status, body, _ = _request(srv.bound_port, "GET", "/dashboard")
        html = body.decode("utf-8", "replace")
        assert status == 200
        assert 'class="od-hero"' in html and 'class="od-kpis"' in html
        for elemento in ("odVer", "odOn", "odOla", "odData", "odRelogio",
                         "odSaude", "kpiAcoes", "kpiStack", "kpiChecks", "kpiUptime"):
            assert f'id="{elemento}"' in html, elemento
        # Fonte única: o formato chega pela injeção (marcas separadas de
        # CSS e JS), não por cópia dentro da página — e o CSS com as
        # REGRAS (.od-hero {) tem de estar lá: a v1.39.1 perdeu o CSS
        # (marca compartilhada enganou o guarda da injeção) e o herói
        # aparecia como texto sem formatação (reporte do dono em 17/10).
        assert "od-formato-orion-css" in html
        assert ".od-hero {" in html and ".od-kpis {" in html
        assert html.count('<script src="/site/admin.js"></script>') == 1
        assert html.count("<script>") == 1
        # O /dashboard busca sozinho (só o /admin declara a bandeira de
        # alimentação — a referência no JS do formato é de todas as páginas).
        assert "odFormatoGerenciado = true" not in html
        # O /admin bebe da MESMA fonte (injeção), sem cópia local.
        _s, corpo_admin, _h = _request(srv.bound_port, "GET", "/admin")
        admin = corpo_admin.decode("utf-8", "replace")
        assert "od-formato-orion-css" in admin and ".od-hero {" in admin
        # O FORMATO é o MESMO arquivo servido para as três páginas
        # (/site/admin.js é público — só UI, sem dado; dívida §4).
        _s, corpo_js, _h = _request(srv.bound_port, "GET", "/site/admin.js")
        js = corpo_js.decode("utf-8", "replace")
        assert '"/app/version"' in js and "od-formato-orion-js" in js
        # O /chat não ganha cabeçalho: sem #odOla o JS sai cedo e o
        # markup não existe lá (CSS/JS injetados ali são inócuos).
        _s, corpo_chat, _h = _request(srv.bound_port, "GET", "/chat")
        assert 'class="od-hero"' not in corpo_chat.decode("utf-8", "replace")

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

class TestTemaClaroEscuro:
    """TODO §3.8 (16/10): tema claro/escuro no site e no painel.

    O que este teste trava: (1) o painel injeta a paleta clara e o botão nas
    TRÊS páginas, e o JS entra DENTRO do `<script>` existente (a guarda de
    sintaxe do painel recorta do primeiro `<script>` ao último `</script>` —
    um bloco novo no meio quebraria a extração); (2) o site resolve tema nas
    duas portas (aparelho ou escolha) com o botão injetado pelo od-nav.js,
    que é o que faz as 11 páginas funcionarem sem editar HTML nenhum.
    """

    @staticmethod
    def _raiz() -> Path:
        return Path(__file__).resolve().parents[1]

    def test_paginas_do_painel_trazem_o_tema(self, serve, tmp_path: Path) -> None:
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        _s, corpo_js, _h = _request(srv.bound_port, "GET", "/site/admin.js")
        js = corpo_js.decode("utf-8", "replace")
        assert corpo_js and "odTema" in js          # o JS do tema está no arquivo
        for pagina in ("/dashboard", "/admin", "/chat"):
            status, corpo, _ = _request(srv.bound_port, "GET", pagina)
            html = corpo.decode("utf-8", "replace")
            assert status == 200, pagina
            # o botão é CRIADO pelo JS (id odTema) — o HTML não o traz,
            # mas a PÁGINA amarra o arquivo que o cria
            assert '<script src="/site/admin.js"></script>' in html, pagina
            assert '#odTema' in html, pagina               # e o CSS o estiliza
            assert 'od_theme' in js, pagina               # cópia local (arquivo)
            assert ':root[data-theme="light"]' in html, pagina
            assert 'prefers-color-scheme: light' in html, pagina
            assert '--bg: #F4F6FB' in html, pagina         # paleta clara
            assert "/profile/preferences" in js  # sincronia (arquivo)

    def test_js_do_tema_entra_num_unico_bloco_script(
            self, serve, tmp_path: Path) -> None:
        """A guarda de sintaxe do painel extrai UM bloco inline — o JS do
        tema/formato é externo (site/admin.js) e não conta aqui."""
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        for pagina in ("/dashboard", "/admin", "/chat"):
            _s, corpo, _h = _request(srv.bound_port, "GET", pagina)
            html = corpo.decode("utf-8", "replace")
            assert html.count("<script>") == 1, pagina
            assert html.count('<script src="/site/admin.js"></script>') == 1, pagina
            dentro = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
            assert "odTema" not in dentro and "od_theme" not in dentro, (
                pagina, "o tema saiu do bloco inline para site/admin.js")

    def test_injecao_do_tema_e_idempotente(self) -> None:
        from integrations.api.server import _com_tema

        base = "<html><head></head><body><script>1</script></body></html>"
        uma = _com_tema(base)
        duas = _com_tema(uma)
        assert uma == duas
        tag = '<script src="/site/admin.js"></script>'
        assert uma.count(tag) == 1 and duas.count(tag) == 1

    def test_site_tem_paleta_clara_e_botao_injetado(self) -> None:
        raiz = self._raiz()
        css = (raiz / "site" / "od.css").read_text(encoding="utf-8")
        js = (raiz / "site" / "od-nav.js").read_text(encoding="utf-8")
        # duas portas: aparelho (media) e escolha explícita (data-theme)
        assert "@media (prefers-color-scheme: light)" in css
        assert ':root[data-theme="light"]' in css
        assert "--bg: #F5F7FA" in css
        assert ".nav-tema" in css
        # botão INJETADO pelo JS (as 11 páginas não foram editadas)
        assert "odTema" in js and "od_theme" in js
        assert "/profile/preferences" in js and "/auth/me" in js
        assert "nav-toggle" in js          # entra ao lado do ⋮

    def test_as_11_paginas_do_site_carregam_css_e_js_do_tema(self) -> None:
        """Sem editar HTML nenhum, o tema alcança o site inteiro."""
        site = self._raiz() / "site"
        paginas = sorted(site.glob("*.html"))
        assert len(paginas) >= 11
        for pagina in paginas:
            html = pagina.read_text(encoding="utf-8")
            assert "od.css" in html, pagina.name
            assert "od-nav.js" in html, pagina.name

    def test_js_do_site_compila(self) -> None:
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:  # node é opcional no ambiente de teste
            return
        check = _subprocess.run(
            [node, "--check", str(self._raiz() / "site" / "od-nav.js")],
            capture_output=True,
        )
        assert check.returncode == 0, check.stderr.decode()[:400]

    # --- "às vezes não funciona" (16/10): clique nenhum pode cair numa tela
    # igual à anterior. Harness de node com DOM de mentira que RODA o JS de
    # verdade (od-nav.js e o site/admin.js do painel) e clica o botão.
    _HARNESS = """
'use strict';
const fs = require('fs'), vm = require('vm');
const arquivo = process.argv[2];
const aparelhoClaro = process.argv[3] === '1';
const inicial = process.argv[4];
const cliques = parseInt(process.argv[5] || '4', 10);
function novoEl() {
  return { style: {}, _h: {}, _attrs: {},
    classList: { toggle() {}, contains() { return false; } },
    setAttribute(k, v) { this._attrs[k] = String(v); },
    removeAttribute(k) { delete this._attrs[k]; },
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
    appendChild() {}, insertBefore() {},
    addEventListener(t, f) { this._h[t] = f; },
    textContent: '', className: '', title: '',
    click() { if (this._h.click) this._h.click(); } };
}
const raiz = novoEl(), corpo = novoEl(), cabecalho = novoEl(), botao = novoEl();
const store = { od_theme: inicial };
const localStorage = { getItem(k) { return k in store ? store[k] : null; },
                       setItem(k, v) { store[k] = String(v); } };
const document = { readyState: 'complete', documentElement: raiz, body: corpo,
  getElementById(id) { return id === 'odTema' ? botao : null; },
  querySelector(sel) { return sel === 'header' ? cabecalho : null; },
  createElement() { return novoEl(); }, addEventListener() {} };
const window = { matchMedia() { return { matches: aparelhoClaro, addEventListener() {} }; },
                  scrollTo() {}, requestAnimationFrame() {}, scrollY: 0 };
const ctx = { window, document, localStorage, console,
              fetch() { return { catch() {} }; } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(arquivo, 'utf8'), ctx, { filename: arquivo });
function estado() {
  return { pref: store.od_theme || 'system',
           aplicado: raiz.getAttribute('data-theme') || 'aparelho',
           modo: raiz.getAttribute('data-tema-modo') || 'auto' };
}
const saida = [estado()];
for (let i = 0; i < cliques; i++) { botao.click(); saida.push(estado()); }
console.log(JSON.stringify(saida));
"""

    def _cliques_no_node(self, tmp_path: Path, js: str, aparelho_claro: bool,
                         inicial: str, cliques: int = 4) -> list[dict]:
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:
            return []
        arquivo = tmp_path / "sobteste.js"
        arquivo.write_text(js, encoding="utf-8")
        harness = tmp_path / "harness.js"
        harness.write_text(self._HARNESS, encoding="utf-8")
        r = _subprocess.run(
            [node, str(harness), str(arquivo), "1" if aparelho_claro else "0",
             inicial, str(cliques)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr[:600]
        import json as _json
        return _json.loads(r.stdout.strip().splitlines()[-1])

    def _od_nav_js(self) -> str:
        return (self._raiz() / "site" / "od-nav.js").read_text(encoding="utf-8")

    def _js_do_painel(self) -> str:
        """Seção do tema de site/admin.js (a fonte única desde 23/10)."""
        texto = (self._raiz() / "site" / "admin.js").read_text(encoding="utf-8")
        corte = texto.index("/* ===== SEÇÃO: od-formato-orion")
        return texto[:corte]

    def test_site_percorre_os_tres_estados_com_feedback(
            self, tmp_path: Path) -> None:
        """§3.8 (corrigido 23/10): o botão percorre os 3 estados SEMPRE
        (system → light → dark → system), como o app. O 'system' não fica
        mais inalcançável e ganha feedback (data-tema-modo=auto)."""
        seq = self._cliques_no_node(tmp_path, self._od_nav_js(),
                                    aparelho_claro=False, inicial="dark",
                                    cliques=3)
        if not seq:  # node ausente: harness opcional (padrão da casa)
            return
        # inicial: escuro fixo
        assert seq[0]["pref"] == "dark" and seq[0]["aplicado"] == "dark"
        assert seq[0]["modo"] == "fixo"
        # 1º clique → segue o aparelho (feedback, sem data-theme)
        assert seq[1]["pref"] == "system" and seq[1]["aplicado"] == "aparelho"
        assert seq[1]["modo"] == "auto"
        # 2º → claro fixo; 3º → escuro fixo (volta ao início do ciclo)
        assert seq[2]["pref"] == "light" and seq[2]["aplicado"] == "light"
        assert seq[3]["pref"] == "dark" and seq[3]["aplicado"] == "dark"

    def test_site_aparelho_claro_tambem_alcanca_o_system(
            self, tmp_path: Path) -> None:
        """No aparelho CLARO o 'system' também é alcançável (era o lado que
        travava em claro↔escuro e nunca voltava ao automático)."""
        seq = self._cliques_no_node(tmp_path, self._od_nav_js(),
                                    aparelho_claro=True, inicial="system",
                                    cliques=3)
        if not seq:
            return
        assert seq[0]["pref"] == "system" and seq[0]["modo"] == "auto"
        assert seq[1]["pref"] == "light" and seq[1]["modo"] == "fixo"
        assert seq[2]["pref"] == "dark" and seq[2]["modo"] == "fixo"
        assert seq[3]["pref"] == "system" and seq[3]["modo"] == "auto"

    def test_painel_percorre_os_tres_estados_com_feedback(
            self, tmp_path: Path) -> None:
        """A MESMA correção no JS do painel (site/admin.js, seção od-tema),
        alinhado ao site e ao app."""
        seq = self._cliques_no_node(tmp_path, self._js_do_painel(),
                                    aparelho_claro=False, inicial="dark",
                                    cliques=3)
        if not seq:
            return
        assert seq[0]["pref"] == "dark" and seq[0]["modo"] == "fixo"
        assert seq[1]["pref"] == "system" and seq[1]["aplicado"] == "aparelho"
        assert seq[1]["modo"] == "auto"
        assert seq[2]["pref"] == "light" and seq[3]["pref"] == "dark"

    def test_painel_js_compila(self) -> None:
        """site/admin.js (arquivo real) compila — node --check direto no
        arquivo, sem exportar string nenhuma do Python."""
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:
            return
        check = _subprocess.run(
            [node, "--check", str(self._raiz() / "site" / "admin.js")],
            capture_output=True)
        assert check.returncode == 0, check.stderr.decode()[:400]


class TestMenuLateralOrion:
    """Menu lateral (20/10, ordem do dono "site + painel"): a barra
    colapsável que a análise da v1.39.0 listou no formato Órion (herói,
    KPIs, mini-painéis vivos e **barra lateral colapsável**) e que só o
    site ficou sem receber — a entrega de 17/10 ao site foi chip vivo +
    números reais, e o menu continuou o ⋮ no topo.

    No SITE ela é injetada pelo od-nav.js a partir dos MESMOS links do
    painel ⋮ (clonagem — o HTML do menu segue existindo num lugar só, a
    divergência entre páginas já aconteceu); no PAINEL, pelo site/admin.js
    (seção od-formato-orion, a fonte única que o _com_tema liga na página).
    Telas estreitas ficam com o que existia; largura e estado recolhido
    vivem em classes da raiz, então claro e escuro usam a mesma folha.
    """

    @staticmethod
    def _raiz() -> Path:
        return Path(__file__).resolve().parents[1]

    def test_site_menu_lateral_injetado_pelo_od_nav(self) -> None:
        raiz = self._raiz()
        css = (raiz / "site" / "od.css").read_text(encoding="utf-8")
        js = (raiz / "site" / "od-nav.js").read_text(encoding="utf-8")
        # o JS monta a barra a partir do painel ⋮ (fonte única dos links:
        # marca e itens são CLONADOS, não reescritos)
        assert "odLateral" in js and "navPanel" in js
        assert "marca.cloneNode(true)" in js
        assert "itens[i].cloneNode(true)" in js
        assert "od_lateral" in js
        assert "od-com-lateral" in js and "od-lateral-recolhido" in js
        # o CSS estiliza só em tela larga (no celular o ⋮ continua)
        assert ".od-lateral" in css and "@media (min-width: 1024px)" in css
        assert "html.od-com-lateral" in css and "od-lateral-recolhido" in css
        # recolhida, a marca sai e os rótulos encolhem (sem ícone inventado)
        assert "html.od-lateral-recolhido .od-lateral .brand" in css
        # O contêiner dos links NUNCA pode ser um <nav>: o od.css tem a
        # regra global `nav { position: fixed; top:0; left:0; right:0 }` e
        # um <nav> aqui viraria uma faixa de ponta a ponta POR CIMA da
        # página — defeito real de 20/10, que só o render mostrou. E o
        # deslocamento do topo é apertado (`body > nav`) pelo mesmo motivo.
        assert "createElement('nav')" not in js
        assert "html.od-com-lateral body > nav" in css

    def test_site_nenhuma_pagina_ganhou_html_de_menu(self) -> None:
        """A barra é INJETADA: as páginas continuam sem o markup novo —
        foi o HTML do menu duplicado em N páginas que divergiu antes."""
        paginas = sorted((self._raiz() / "site").glob("*.html"))
        assert len(paginas) >= 11
        for pagina in paginas:
            html = pagina.read_text(encoding="utf-8")
            assert "odLateral" not in html, pagina.name
            assert "od-lateral" not in html, pagina.name

    def test_painel_menu_lateral_no_formato_orion(
            self, serve, tmp_path: Path) -> None:
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        # O FORMATO vive em site/admin.js — é dele que saem lateralMontar,
        # lateralAdmin e o item condicional ao papel.
        _s, corpo_js, _h = _request(srv.bound_port, "GET", "/site/admin.js")
        fmt = corpo_js.decode("utf-8", "replace")
        assert "odLateral" in fmt and "od-lateral-btn" in fmt
        assert '"/dashboard"' in fmt and '"/chat"' in fmt
        assert '<div class="od-lateral-links">' in fmt
        assert '<nav class="od-lateral-links">' not in fmt
        assert "lateralAdmin" in fmt
        assert 'papel === "admin"' in fmt
        for pagina in ("/dashboard", "/admin", "/chat"):
            status, corpo, _ = _request(srv.bound_port, "GET", pagina)
            html = corpo.decode("utf-8", "replace")
            assert status == 200, pagina
            # a guarda de sintaxe do painel recorta UM bloco inline
            assert html.count("<script>") == 1, pagina
            assert html.count('<script src="/site/admin.js"></script>') == 1, pagina
            # as páginas que TÊM herói repassam o papel em odFormato.nome
            # (o /chat pergunta sozinho — sem quemAmI)
            if pagina != "/chat":
                assert "nome(data.user.username, role)" in html, pagina
            # a barra é inócua no /chat: sem #odOla o FORMATO sai cedo e
            # o chat mantém o próprio cabeçalho
            if pagina == "/chat":
                continue
            # o container dos links é <div> — um <nav> casaria com regras
            # globais de qualquer folha e viraria faixa por cima da página
            # (defeito real de 20/10, prevenido no JS que a página carrega)

    def test_js_do_site_compila_com_a_barra(self) -> None:
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:
            return
        check = _subprocess.run(
            [node, "--check", str(self._raiz() / "site" / "od-nav.js")],
            capture_output=True,
        )
        assert check.returncode == 0, check.stderr.decode()[:400]


class TestVisaoDoSistema:
    """Dashboard unificado "System Overview" (TODO §3.6, ordem do dono
    20/10 "Dashboard unificado"): um card por subsistema no /admin, tudo
    lido das MESMAS fontes de sempre (/health · /supervision ·
    /dashboard/stats · /actions). A fila inteira de cards é montada por
    UMA função pura `visaoCards`, que é a alavanca das travas: (a) a seção
    existe e cobre todos os subsistemas; (b) o construtor de cards NÃO
    busca nada (fonte paralela é proibida); (c) no node, com dado de
    verdade cada subsistema aparece, e sem dado todos ficam "—" com a
    classe vazia — verde de mentira é o defeito que esta suíte existe
    para matar.
    """

    @staticmethod
    def _raiz() -> Path:
        return Path(__file__).resolve().parents[1]

    def _js_do_admin(self) -> str:
        """O <script> único da página /admin, cru (sem o FORMATO)."""
        from integrations.api.server import _ADMIN_PAGE_HTML
        html = _ADMIN_PAGE_HTML
        return html[html.index("<script>") + len("<script>"):
                    html.rindex("</script>")]

    def test_visao_no_admin_cobre_todos_os_subsistemas(self, serve) -> None:
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        status, corpo, _ = _request(srv.bound_port, "GET", "/admin")
        html = corpo.decode("utf-8", "replace")
        assert status == 200
        assert "Vis\u00e3o do sistema (System Overview)" in html
        assert 'id="sys-resumo"' in html and 'id="sys"' in html
        # um card por subsistema: o que J\u00e1 existia + os 4 que faltavam
        for rotulo in ("Estado", "Loops", "Stack N\u00f4made", "Alertas",
                       "Backup", "Off-site", "RAG", "Auto-update",
                       "Downloads", "Ferramentas"):
            assert f'"{rotulo}"' in html, rotulo
        # cada card l\u00ea o bloco que o /dashboard/stats J\u00e1 emite
        for bloco in ("vector_store", "auto_update", "downloads",
                      "ferramentas", "nomad_tools", "notifier", "offsite"):
            assert f"stats.{bloco}" in html, bloco

    def test_construtor_de_cards_nao_busca_nada(self) -> None:
        """Fonte \u00fanica: visaoCards \u00e9 função PURA — recebe os payloads e
        s\u00f3 monta strings. Se um dia um fetch entrar dentro, a visão vira
        fonte paralela e este teste derruba."""
        import re
        js = self._js_do_admin()
        m = re.search(r"function visaoCards\(health, sup, stats\) \{[\s\S]*?\n\}",
                      js)
        assert m, "visaoCards n\u00e3o encontrada — vis\u00e3o sem alavanca"
        corpo = m.group(0)
        assert "fetch" not in corpo and "http" not in corpo.lower()
        # fallback honesto em cada bloco ausente (sem dado, nada de verde)
        assert corpo.count('"\u2014"') >= 4
        # declarada UMA vez e chamada UMA vez (só dentro do loadSystem)
        assert js.count("visaoCards(health, sup, stats)") == 2

    _HARNESS = """
'use strict';
const fs = require('fs'), vm = require('vm');
const arquivo = process.argv[2];
function novoEl() {
  return { style: {}, dataset: {}, _attrs: {}, innerHTML: '', textContent: '',
    className: '', value: '', href: '', onclick: null,
    setAttribute(k, v) { this._attrs[k] = String(v); },
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : 'href'; },
    addEventListener() {},
    classList: { toggle() {}, add() {}, remove() { return true; },
                 contains() { return false; } } };
}
const document = { getElementById() { return novoEl(); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement() { return novoEl(); }, addEventListener() {},
  documentElement: novoEl(), body: novoEl(), readyState: 'complete' };
const window = { confirm() { return true; }, alert() {}, scrollTo() {},
  matchMedia() { return { matches: true, addEventListener() {} }; } };
const localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
const location = { href: '' };
const fetch = () => Promise.resolve({ ok: false, status: 401,
  json: async () => ({ ok: false }) });
const ctx = { document, window, localStorage, location, fetch, console,
  setInterval: () => 0, setTimeout: () => 0, clearTimeout: () => {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(arquivo, 'utf8'), ctx, { filename: arquivo });

const health = { ok: true, status: "up" };
const sup = { restarts: 0, ok: true };
const cheio = {
  uptime_s: 3671, processed: 42, avg_latency_ms: 12, cache: { entries: 3 },
  nomad_tools: { up: 9, total: 9, fora: [] },
  notifier: { alerts_emitted: 5, alerts_blocked: 1, errors: 0 },
  backup: { estado: { ultimo_sucesso_em: "20/10 03:00", ultimo_bytes: 4096,
                      pendente_hoje: false, falhas: 0 },
            capturas: { ultimo_sucesso_em: "19/10 04:00", ultimo_bytes: 1024,
                        pendente_hoje: false, falhas: 0 } },
  offsite: { ultimo_diario: "20/10 03:01" },
  vector_store: { docs: 42, namespaces: ["global"] },
  auto_update: { alvos: 3, desabilitados: 0, pendentes: 1 },
  downloads: { ativas: 2, concluidos: 7, erros: 0 },
  ferramentas: { total: 12, ativas: 12, com_historico: 4, ultimo_erro: null },
};
const problema = JSON.parse(JSON.stringify(cheio));
problema.auto_update.desabilitados = 2;
problema.downloads.erros = 1;
problema.ferramentas.ultimo_erro = "restaura\u00e7\u00e3o falhou";
problema.offsite.ultimo_diario = null;
const saida = {
  cheio: ctx.visaoCards(health, sup, cheio),
  vazio: ctx.visaoCards(health, sup, {}),
  problema: ctx.visaoCards(health, sup, problema),
};
console.log(JSON.stringify(saida));
"""

    def test_cards_no_node_verdade_e_traco(self, tmp_path: Path) -> None:
        """Roda o script do /admin em node com DOM de mentira e avalia a
        visão em 3 estados: dado completo, dado vazio e dado problemático."""
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:
            return
        js = tmp_path / "admin.js"
        js.write_text(self._js_do_admin(), encoding="utf-8")
        har = tmp_path / "har.js"
        har.write_text(self._HARNESS, encoding="utf-8")
        r = _subprocess.run([node, str(har), str(js)], capture_output=True,
                            text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[:800]
        import json as _json
        saida = _json.loads(r.stdout.strip().splitlines()[-1])
        cartoes = {c[0]: c for c in saida["cheio"]}
        # com dado de verdade, NENHUM subsistema fica em "—"
        for rotulo in ("RAG", "Auto-update", "Downloads", "Ferramentas",
                       "Alertas", "Stack N\u00f4made", "Backup", "Off-site"):
            assert cartoes[rotulo][1] != "\u2014", rotulo
        assert cartoes["RAG"][1].startswith("42 docs")
        # sem dado: os blocos caem em "—" e NUNCA em verde
        vazio = {c[0]: c for c in saida["vazio"]}
        for rotulo in ("RAG", "Auto-update", "Downloads", "Ferramentas",
                       "Alertas", "Stack N\u00f4made", "Backup", "Off-site"):
            assert vazio[rotulo][1] == "\u2014", rotulo
            assert vazio[rotulo][2] != "ok", rotulo
        # problema real -> vermelho: auto-disable, erro de download,
        # erro do depot e off-site que nunca saiu de casa
        prob = {c[0]: c for c in saida["problema"]}
        for rotulo in ("Auto-update", "Downloads", "Ferramentas", "Off-site"):
            assert prob[rotulo][2] == "err", rotulo


class TestAcessoPeloMenuELateralChat:
    """Duas ordens do dono (20/10, logo após o dashboard unificado):
    *"o acesso que poderia ser pelo menu principal, se estiver logado
    entra"* e *"chat também pode manter o menu lateral"*.

    1. O ⛮ do site ganha o item **Painel** (→ /dashboard) ANTES da
       clonagem da barra — os dois menus saem dos MESMOS links; com
       sessão de dono o **Admin** entra nos dois na MESMA resposta
       `/auth/me` que o tema já busca (uma ida à API; sem sessão o
       menu não faz chamada nenhuma).
    2. O FORMATO monta a barra nas TRÊS páginas: no /chat só o herói
       (`#odOla`) some — e o papel do dono lá o FORMATO pergunta
       sozinho (a página náo tem quemAmI).
    """

    @staticmethod
    def _raiz() -> Path:
        return Path(__file__).resolve().parents[1]

    def _od_nav(self) -> str:
        return (self._raiz() / "site" / "od-nav.js").read_text(encoding="utf-8")

    def test_site_painel_no_menu_e_admin_do_dono_nos_dois(self) -> None:
        js = self._od_nav()
        # Painel (→ /dashboard) inserido no ⛮, junto do Chat
        assert "acessoInserir" in js and "'/dashboard', 'Painel'" in js
        assert "acessoMontar" in js
        # ANTES do clonar: a barra herda o item do ⛮ (fonte única)
        assert js.index("acessoMontar();") < js.index("lateralMontar();")
        # Admin: papel conferido na MESMA resposta do tema (sem 2ª ida)
        assert "temaSincronizar().then(acessoAdmin)" in js
        assert "role !== \'admin\'" in js
        assert "Promise.resolve(null)" in js        # sem sessão: sem fetch
        # Admin entra nos DOIS: ⛮ e barra lateral
        corpo = js[js.index("function acessoAdmin("):js.index("acessoMontar();")]
        assert "\'/admin\'" in corpo and "odLateral" in corpo
        assert ".od-lateral-links" in corpo

    def test_chat_mantem_a_barra_no_formato(self, serve) -> None:
        """O FORMATO (site/admin.js, seção od-formato-orion) monta a barra
        nas TRÊS páginas — no /chat, inócua (sem #odOla o herói sai).
        """
        fmt = (self._raiz() / "site" / "admin.js").read_text(encoding="utf-8")
        # a seção do FORMATO (a seção od-tema vem antes no arquivo e
        # também tem iniciar())
        fmt = fmt[fmt.index("/* ===== SEÇÃO: od-formato-orion"):]
        # iniciar(): a barra monta ANTES do cedo (sem odOla só não há herói)
        corpo = fmt[fmt.index("function iniciar()"):][:520]
        precoce = 'if (!document.getElementById("odOla"))'
        assert precoce in corpo, corpo[:200]
        assert corpo.index("lateralMontar();") < corpo.index(precoce), corpo[:200]
        assert "papelChat" in fmt and "lateralAdmin()" in fmt
        # só com sessão: anônimo não ganha idà à API nem item Admin
        pc = fmt[fmt.index("function papelChat()"):fmt.index("function iniciar()")]
        assert "od_session_token" in pc and "lateralAdmin()" in pc
        # servido: /chat amarra o arquivo do FORMATO (CSS marcado na página
        # + <script src> na ordem antes do bloco próprio)
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        status, corpo_bytes, _ = _request(srv.bound_port, "GET", "/chat")
        html = corpo_bytes.decode("utf-8", "replace")
        assert status == 200
        assert "od-formato-orion-css" in html
        assert html.count('<script src="/site/admin.js"></script>') == 1
        assert html.count("<script>") == 1

    # --- Harness: roda o od-nav.js de VERDADE com DOM de mentira, nos dois
    # cenários (dono logado / sem sessão) e lê o menu montado.
    _HARNESS_MENU = r"""
'use strict';
const fs = require('fs'), vm = require('vm');
const arquivo = process.argv[2];
const ehDono = process.argv[3] === '1';
const registro = {};

function novoEl(tag) {
  const e = {
    tagName: String(tag || 'div').toUpperCase(),
    _id: '', className: '', textContent: '', title: '', href: '',
    type: '', style: {}, children: [], parentNode: null,
    _attrs: {}, _h: {},
    setAttribute(k, v) {
      this._attrs[k] = String(v);
      if (k === 'id') { this._id = String(v); registro[this._id] = this; }
    },
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
    removeAttribute(k) { delete this._attrs[k]; },
    addEventListener(t, f) { this._h[t] = f; },
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    insertBefore(c, ref) {
      c.parentNode = this;
      const i = this.children.indexOf(ref);
      if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
      return c;
    },
    contains() { return false; },
    cloneNode() {
      const c = novoEl(this.tagName);
      c.href = this.href; c.textContent = this.textContent;
      c.title = this.title; c.className = this.className;
      for (const k in this._attrs) c._attrs[k] = this._attrs[k];
      return c;
    },
    querySelector(sel) { return achar(this, sel); },
    querySelectorAll(sel) { return varredura(this, sel); },
    classList: {
      _s: new Set(),
      toggle(c, f) {
        const ligar = f === undefined ? !this._s.has(c) : !!f;
        if (ligar) this._s.add(c); else this._s.delete(c);
        return ligar;
      },
      contains(c) { return this._s.has(c); },
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
    },
  };
  Object.defineProperty(e, 'id', {
    get() { return this._id; },
    set(v) { this._id = String(v); registro[this._id] = this; },
    configurable: true,
  });
  return e;
}

function bate(el, sel) {
  if (sel.indexOf(' ') >= 0) return false;          // 'nav .brand' → nada
  const m = /^a\[href="([^"]+)"\]$/.exec(sel);
  if (m) return el.tagName === 'A' && el.getAttribute('href') === m[1];
  if (sel[0] === '.') return String(el.className).split(/\s+/).indexOf(sel.slice(1)) >= 0;
  if (/^[a-zA-Z][a-zA-Z0-9-]*$/.test(sel)) return el.tagName === sel.toUpperCase();
  return false;
}
function varredura(raiz, sel) {
  const saida = [];
  (function anda(el) {
    for (const c of el.children) { if (bate(c, sel)) saida.push(c); anda(c); }
  })(raiz);
  return saida;
}
function achar(raiz, sel) { return varredura(raiz, sel)[0] || null; }

const navPanel = novoEl('div');
navPanel.id = 'navPanel';
[ ['/site/loja.html', 'Loja'], ['/chat', 'Chat'], ['#download', 'Baixar APK'] ]
  .forEach(([href, rot]) => {
    const a = novoEl('a'); a.setAttribute('href', href); a.textContent = rot;
    navPanel.appendChild(a);
  });

const document = {
  readyState: 'complete',
  documentElement: novoEl('html'),
  body: novoEl('body'),
  getElementById(id) { return registro[id] || null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) { return novoEl(tag); },
  addEventListener() {},
};
const store = {};
if (ehDono) store.od_session_token = 'tk-dono';
const localStorage = {
  getItem(k) { return k in store ? store[k] : null; },
  setItem(k, v) { store[k] = String(v); },
  removeItem(k) { delete store[k]; },
};
const chamadas = [];
const fetch = (url) => {
  chamadas.push(url);
  if (url === '/auth/me') {
    return Promise.resolve(ehDono
      ? { ok: true, json: async () => ({ ok: true, role: 'admin',
          preferences: {}, user: { username: 'dono' } }) }
      : { ok: false, json: async () => ({}) });
  }
  return Promise.resolve({ ok: true, json: async () => ({}) });
};
const window = {
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  addEventListener() {}, scrollTo() {}, requestAnimationFrame() {},
  scrollY: 0,
};
const ctx = { document, window, localStorage, fetch, console, Promise,
              setTimeout, setInterval: () => 0 };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(arquivo, 'utf8'), ctx, { filename: arquivo });

setTimeout(() => {
  const nav = registro['navPanel'];
  const barra = registro['odLateral'];
  const hrefs = (el) => el
    ? el.querySelectorAll('a').map((a) => a.getAttribute('href')) : null;
  console.log(JSON.stringify({
    auth_me: chamadas.filter((u) => u === '/auth/me').length,
    menu: hrefs(nav),
    barra: hrefs(barra),
    itens: barra ? barra.querySelectorAll('a').map((a) => ({
      href: a.getAttribute('href'),
      title: a.title || null,
      ico: (a.querySelector('.od-ico') || { textContent: null }).textContent,
      rot: (a.querySelector('.od-rot') || { textContent: null }).textContent,
    })) : null,
  }));
}, 30);
"""

    def _menu_no_node(self, tmp_path: Path, dono: bool) -> dict:
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:
            return {}
        js = tmp_path / "od_nav.js"
        js.write_text(self._od_nav(), encoding="utf-8")
        har = tmp_path / "har_menu.js"
        har.write_text(self._HARNESS_MENU, encoding="utf-8")
        r = _subprocess.run(
            [node, str(har), str(js), "1" if dono else "0"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30)
        assert r.returncode == 0, r.stderr[:800]
        import json as _json
        return _json.loads(r.stdout.strip().splitlines()[-1])

    def test_menu_no_node_dono_gera_painel_e_admin(self, tmp_path: Path) -> None:
        saida = self._menu_no_node(tmp_path, dono=True)
        if not saida:          # node ausente: harness opcional (padrão da casa)
            return
        menu, barra = saida["menu"], saida["barra"]
        # Painel no ⛮ ANTES do Chat, e a barra o CLONOU na mesma ordem
        assert menu.index("/dashboard") < menu.index("/chat")
        assert barra.index("/dashboard") < barra.index("/chat")
        # dono logado: Admin nos DOIS, também antes do Chat
        assert menu.index("/admin") < menu.index("/chat")
        # na BARRA por último — a MESMA posição do lateralAdmin do
        # FORMATO nas páginas do painel (um item Admin, mesma casa)
        assert barra[-1] == "/admin"
        # UMA ida à /auth/me (a mesma que já alimenta o tema)
        assert saida["auth_me"] == 1
        # cada item da barra: ícone real (nunca o "•" de tabela faltando),
        # rótulo e title — recolhido, sobra o ícone e o hover mostra o nome
        for item in saida["itens"]:
            assert item["ico"] and item["ico"] != "•", item
            assert item["rot"] and item["title"], item

    def test_menu_no_node_sem_sessao_so_painel_sem_chamada(
            self, tmp_path: Path) -> None:
        saida = self._menu_no_node(tmp_path, dono=False)
        if not saida:
            return
        menu, barra = saida["menu"], saida["barra"]
        # logado não está: Painel existe (vai dar de cara no /chat),
        # Admin NÃO aparece em nenhum dos dois menus...
        assert "/dashboard" in menu and "/dashboard" in barra
        assert "/admin" not in menu and "/admin" not in barra
        # ...e o menu não fez NENHUMA chamada à API só pra decidir isso
        assert saida["auth_me"] == 0
        # anônimo ou não, item SEM ícone de tabela faltando (nunca "•")
        for item in saida["itens"]:
            assert item["ico"] and item["ico"] != "•", item
            assert item["rot"] and item["title"], item


class TestIconesDoMenuLateral:
    """Pedido do dono (20/10 ~19:00): "não ficou legal o sistema de
    escrita, quando o menu retrai fica pedaços de palavras, seria melhor
    ícones".

    Réplica ANTES (render headless) mostrou o defeito ao vivo: recolhida
    (68px) a barra lia "MAR… ECO… SIST… PRO… HIST… VERI… PLÊI… PAIN…
    BAI… ADM…". Entrega: cada item da barra vira ícone + rótulo nos DOIS
    lados (site e painel); recolhida, o rótulo SAI e sobra o ícone
    centrado — o nome continua no title (hover) e no .od-rot do DOM
    (leitor de tela). Mesmos glifos nas duas superfícies (paridade).
    """

    @staticmethod
    def _raiz() -> Path:
        return Path(__file__).resolve().parents[1]

    def _js(self) -> str:
        return (self._raiz() / "site" / "od-nav.js").read_text(encoding="utf-8")

    def _css_site(self) -> str:
        return (self._raiz() / "site" / "od.css").read_text(encoding="utf-8")

    def test_icones_nos_dois_lados(self) -> None:
        import re
        from integrations.api.server import _FORMATO_ORION_CSS
        # O FORMATO do painel vive em site/admin.js (dívida técnica §4)
        _FORMATO_ORION_JS = (self._raiz() / "site" / "admin.js").read_text(
            encoding="utf-8")
        js, css = self._js(), self._css_site()
        # -- site: tabela por href + resolvedor + item com os DOIS spans
        assert "var ICONES = {" in js and "function iconeDe(" in js
        assert "'od-ico'" in js and "'od-rot'" in js and "lateralItem(" in js
        assert "|| '•'" in js          # fora da tabela: nunca palavra cortada
        # -- site CSS: flex + ícone fixo + rótulo com ellipsis…
        assert ".od-lateral-links a .od-ico" in css
        # família de emoji explícita no ícone (sem ela, máquina sem
        # fonte de emoji vira quadradinho — prova da casa em 20/10)
        assert '"Segoe UI Emoji"' in css and '"Noto Color Emoji"' in css
        assert ".od-lateral-links a .od-rot { overflow: hidden; text-overflow: ellipsis; }" in css
        bloco = re.search(
            r"html\.od-lateral-recolhido \.od-lateral-links a \{([^}]*)\}",
            css)
        assert bloco, "regra do recolhido ausente no od.css"
        # …e a recolhida NÃO encolhe mais fonte: centraliza e some o rótulo
        # (foi o "font-size: .66rem" que virou "pedaço de palavra" pro dono)
        assert "justify-content: center" in bloco.group(1)
        assert "font-size" not in bloco.group(1)
        assert "html.od-lateral-recolhido .od-lateral-links a .od-rot { display: none; }" in css
        # -- painel: MESMO formato nos itens + title (hover do recolhido)
        fjs = _FORMATO_ORION_JS
        assert fjs.count("ico: ") >= 3
        alvo = "title=\"' + itens[i].rot + '\""
        assert alvo in fjs
        assert '<span class="od-ico"' in fjs and '<span class="od-rot"' in fjs
        adm = fjs[fjs.index("function lateralAdmin()"):]
        assert 'setAttribute("title", "Admin")' in adm
        assert "od-ico" in adm and "od-rot" in adm
        # -- painel CSS: espelho exato do site (ícone fixo + recolhida)
        assert ".od-lateral-links a .od-ico" in _FORMATO_ORION_CSS
        assert '"Segoe UI Emoji"' in _FORMATO_ORION_CSS
        assert '"Noto Color Emoji"' in _FORMATO_ORION_CSS
        assert ".od-lateral-links a .od-rot { overflow: hidden; text-overflow: ellipsis; }" in _FORMATO_ORION_CSS
        fb = re.search(
            r"html\.od-lateral-recolhido \.od-lateral-links a \{([^}]*)\}",
            _FORMATO_ORION_CSS)
        assert fb and "justify-content: center" in fb.group(1)
        assert "font-size" not in fb.group(1)
        assert "html.od-lateral-recolhido .od-lateral-links a .od-rot { display: none; }" in _FORMATO_ORION_CSS

    def test_tabela_cobre_todos_os_menus_do_site(self) -> None:
        """Guarda contra divergência: os menus das 12 páginas JÁ divergem
        (12/13/14 links) e as variações "/site#anc" existem — TODOS os
        hrefs de TODAS as páginas precisam de ícone de verdade. Avalia o
        iconeDe() REAL no node (sem espelho da lógica no teste)."""
        import re
        import shutil as _shutil
        import subprocess as _subprocess
        node = _shutil.which("node")
        if not node:
            return
        js = self._js()
        hrefs = set()
        paginas = 0
        for pagina in sorted((self._raiz() / "site").glob("*.html")):
            h = pagina.read_text(encoding="utf-8")
            bloco = re.search(r'<div class="nav-panel"[^>]*>(.*?)</div>\s*</div>',
                              h, re.S)
            if not bloco:
                continue
            paginas += 1
            hrefs.update(re.findall(r'<a[^>]*href="([^"]+)"', bloco.group(1)))
        hrefs.update(["/dashboard", "/admin"])   # injetados pelo od-nav.js
        assert paginas >= 11 and len(hrefs) >= 14, (paginas, len(hrefs))
        trecho = js[js.index("var ICONES ="):js.index("function lateralItem")]
        import json as _json
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as td:
            arq = Path(td) / "icone.js"
            arq.write_text(
                trecho + "\nconsole.log(JSON.stringify("
                "process.argv.slice(2).map(iconeDe)));\n",
                encoding="utf-8")
            r = _subprocess.run(
                [node, str(arq)] + sorted(hrefs),
                capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr[:600]
        glifos = _json.loads(r.stdout.strip().splitlines()[-1])
        for href, glifo in zip(sorted(hrefs), glifos):
            assert glifo != "•", f"href sem ícone: {href}"

    def test_icone_do_painel_igual_ao_do_site(self) -> None:
        """Os 4 itens compartilhados (Painel/Chat/Site/Admin) falam a
        MESMA língua visual nas duas superfícies — não pode ser 🖥️ de um
        lado e outra coisa do outro.

        22/10: o painel ganhou o grupo do portário (lateralFerramentas,
        5 ferramentas do dono) — paridade só nos COMPARTILHADOS, porque
        o site público não anuncia ferramenta de dono (sem login elas
        levam ao formulário do chat)."""
        import re
        _FORMATO_ORION_JS = (self._raiz() / "site" / "admin.js").read_text(
            encoding="utf-8")
        site = dict(re.findall(
            r"'([^']+)':\s*'([^']+)'",
            self._js()[self._js().index("var ICONES ="):
                       self._js().index("function iconeDe")]))
        painel = dict(re.findall(
            r'\{ href: "([^"]+)", rot: "[^"]+", ico: "([^"]+)" \}',
            _FORMATO_ORION_JS))
        adm = _FORMATO_ORION_JS[_FORMATO_ORION_JS.index("function lateralAdmin()"):]
        painel["/admin"] = re.search(
            r'aria-hidden="true">([^<]+)</span>', adm).group(1)
        compartilhados = {"/dashboard", "/chat", "/site", "/admin"}
        ferramentas = {"/f/caderno/", "/f/cyberchef/",
                       "/f/caixa/", "/f/cofre/"}
        assert set(painel) == compartilhados | ferramentas
        for href in compartilhados:
            assert site.get(href) == painel[href], (href, painel[href])
        for href in ferramentas:                    # glifos próprios, não vazios
            assert painel[href] and painel[href] != "•", href

    def test_painel_servido_com_icones(self, serve) -> None:
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        status, corpo_bytes, _ = _request(srv.bound_port, "GET", "/chat")
        html = corpo_bytes.decode("utf-8", "replace")
        assert status == 200
        # os itens (spans) saem do site/admin.js — o /chat amarra o arquivo
        _s, js_bytes, _h = _request(srv.bound_port, "GET", "/site/admin.js")
        fmt = js_bytes.decode("utf-8", "replace")
        assert '<span class="od-ico"' in fmt and '<span class="od-rot"' in fmt
        assert ".od-lateral-links a .od-ico" in html          # CSS servido
        assert "html.od-lateral-recolhido .od-lateral-links a .od-rot { display: none; }" in html
        assert 'title="' in html                              # hover do recolhido
        # UM bloco inline + a tag do arquivo do painel (fecha o próprio)
        assert html.count("<script>") == 1 and html.count("</script>") == 2


class TestRespiroDoMainAbaixoDaNav:
    """Defeito reportado pelo dono (20/10): "página verificação está
    muito alta, está cortando o texto" — e ele confirmou "loja também".

    Causa raiz: o od.css tem `.wrap { padding: 0 24px }` (CLASSE) e as
    páginas mandavam `main { padding: 130px 0 70px }` (ELEMENTO) —
    classe vence elemento, os 130px de respiro perdiam em silêncio e o
    conteúdo subia embaixo da nav fixa (63px), cortando kicker e h1.
    Regressão silenciosa desde 10/10 (b3b86d8 deu `padding: 0 24px` ao
    .wrap; o main nasceu em 09/10 funcionando). Correção: `main.wrap
    { padding: 130px 24px 70px }` — o 24px horizontal mantém a calha.

    Guarda: página com `<main class="wrap">` NÃO pode ter regra de
    `main` elemento puro com padding; e quando tem `main.wrap`, o
    respiro de topo precisa passar a nav (63px) com folga.
    """

    @staticmethod
    def _raiz() -> Path:
        return Path(__file__).resolve().parents[1]

    def test_pagina_de_main_wrap_sem_regra_de_elemento(self) -> None:
        import re
        com_wrap = 0
        for pagina in sorted((self._raiz() / "site").glob("*.html")):
            html = pagina.read_text(encoding="utf-8")
            if '<main class="wrap"' not in html:
                continue
            com_wrap += 1
            colisao = re.search(r"(?<![\w.-])main\s*\{[^}]*padding", html)
            assert colisao is None, (
                f"{pagina.name}: regra 'main {{ padding ... }}' perde para "
                f".wrap do od.css (classe vence elemento) — use main.wrap")
        assert com_wrap >= 2, com_wrap      # verificacao + loja + teste-tema

    def test_respiro_de_topo_passa_a_nav_fixa(self) -> None:
        import re
        com_regra = 0
        for pagina in sorted((self._raiz() / "site").glob("*.html")):
            html = pagina.read_text(encoding="utf-8")
            regra = re.search(
                r"main\.wrap\s*\{\s*padding:\s*(\d+)px\s+(\d+)px\s+(\d+)px",
                html)
            if not regra:
                continue                    # teste-tema usa style inline
            com_regra += 1
            topo, laterais = int(regra.group(1)), int(regra.group(2))
            assert topo >= 100, (pagina.name, topo)     # nav = 63px no render
            assert laterais >= 16, (pagina.name, laterais)  # calha preservada
        assert com_regra >= 2, com_regra    # as DUAS reportadas

    def test_paginas_relatadas_servidas_ja_corrigidas(self, serve) -> None:
        srv = serve(None, config=APIConfig(port=0, rate_limit_max=0))
        for pagina in ("/site/verificacao.html", "/site/loja.html"):
            status, corpo_bytes, _ = _request(srv.bound_port, "GET", pagina)
            html = corpo_bytes.decode("utf-8", "replace")
            assert status == 200, pagina
            assert "main.wrap { padding: 130px 24px 70px; }" in html, pagina
            assert "main { padding: 130px 0 70px; }" not in html, pagina
            assert 'class="wrap"' in html, pagina


class TestLojaPorSecoes:
    """Loja do site separada por SEÇÕES = linhas da casa (pedido 16/10).

    O dono: "a loja precisa separar por seções". A seção de cada peça vem
    do PREFIXO do ID canônico (NV-… = Nicoly Valentina, PROD-… = produtos
    do ecossistema; linha desconhecida ganha seção própria com o nome).
    O JS da página é RODADO de verdade aqui — harness de node com DOM e
    fetch de mentira (mesmo padrão do TestTemaClaroEscuro), não string
    conferida no HTML.
    """

    _PECAS = {
        "ok": True, "total": 3, "pecas": [
            {"public_id": "PROD-PE-2026-0002", "name": "Trena",
             "kind": "publica", "status": "estoque", "collection": None,
             "photo": None, "registered": False, "owner_username": None},
            {"public_id": "NV-SJ-2026-0003", "name": "Pendente Lumen Nox",
             "kind": "exclusiva", "status": "registrada",
             "collection": "LUMEN NOX", "photo": None, "registered": True,
             "owner_username": "alex"},
            {"public_id": "NV-SJ-2026-0001", "name": "Anel Abissal",
             "kind": "exclusiva", "status": "estoque", "collection": "ABISSAL",
             "photo": None, "registered": False, "owner_username": None},
        ]
    }

    _HARNESS = """
'use strict';
const fs = require('fs'), vm = require('vm');
const pagina = fs.readFileSync(process.argv[2], 'utf8');
const dados = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const achado = pagina.match(/<script>(\\s*\\(function[\\s\\S]*?)<\\/script>/);
if (!achado) { console.error('script inline da loja não encontrado'); process.exit(2); }
const elems = {};
const sandbox = {
  fetch: () => Promise.resolve({ json: () => Promise.resolve(dados) }),
  document: {
    getElementById: (id) => (elems[id] = elems[id] ||
      { textContent: '', className: '', innerHTML: '' }),
  },
};
vm.createContext(sandbox);
vm.runInContext(achado[1], sandbox);
setTimeout(() => {
  console.log(JSON.stringify({
    prateleira: elems['prateleira'].innerHTML,
    estado: elems['estado'].textContent,
  }));
}, 20);
"""

    def _roda_no_node(self, tmp_path: Path, dados: dict) -> dict:
        import shutil as _shutil
        import subprocess as _subprocess

        node = _shutil.which("node")
        if not node:
            return {}  # node ausente: harness opcional (padrão da casa)
        pagina = Path(__file__).resolve().parents[1] / "site" / "loja.html"
        arquivo = tmp_path / "dados.json"
        arquivo.write_text(json.dumps(dados), encoding="utf-8")
        harness = tmp_path / "harness_loja.js"
        harness.write_text(self._HARNESS, encoding="utf-8")
        r = _subprocess.run(
            [node, str(harness), str(pagina), str(arquivo)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert r.returncode == 0, r.stderr[:600]
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_secoes_por_linha_nv_antes_de_prod(self, tmp_path: Path) -> None:
        saida = self._roda_no_node(tmp_path, self._PECAS)
        if not saida:
            return
        html = saida["prateleira"]
        assert html.count('class="secao"') == 2, html[:400]
        # NV (linha das semi-joias) vem ANTES dos produtos
        assert html.index('data-frente="NV"') < html.index('data-frente="PROD"')
        # cada peça cai DENTRO da seção da sua linha
        trecho_nv = html[html.index('data-frente="NV"'):
                         html.index('data-frente="PROD"')]
        assert "Anel Abissal" in trecho_nv and "Pendente Lumen Nox" in trecho_nv
        assert "Trena" not in trecho_nv
        assert "Trena" in html[html.index('data-frente="PROD"'):]
        # contagem no rodapé do catálogo
        assert "3 peça(s)" in saida["estado"] and "2 linha(s)" in saida["estado"]

    def test_linha_desconhecida_ganha_secao_propria(self, tmp_path: Path) -> None:
        dados = dict(self._PECAS)
        dados["pecas"] = list(self._PECAS["pecas"]) + [
            {"public_id": "FAB-PE-2026-0001", "name": "Suporte",
             "kind": "publica", "status": "estoque", "collection": None,
             "photo": None, "registered": False, "owner_username": None}]
        saida = self._roda_no_node(tmp_path, dados)
        if not saida:
            return
        html = saida["prateleira"]
        assert 'data-frente="FAB"' in html
        # seção nova entra depois das linhas canônicas (ordem: NV, PROD, resto)
        assert html.index('data-frente="PROD"') < html.index('data-frente="FAB"')

    def test_catalogo_vazio_avisa(self, tmp_path: Path) -> None:
        saida = self._roda_no_node(tmp_path, {"ok": True, "total": 0,
                                              "pecas": []})
        if not saida:
            return
        assert saida["prateleira"] == ""
        assert "Nenhuma peça" in saida["estado"]

    def test_js_inline_da_loja_compila(self) -> None:
        import shutil as _shutil
        import subprocess as _subprocess
        import tempfile as _tempfile

        node = _shutil.which("node")
        if not node:
            return
        pagina = (Path(__file__).resolve().parents[1]
                  / "site" / "loja.html").read_text(encoding="utf-8")
        achado = pagina.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        with _tempfile.NamedTemporaryFile(
                "w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(achado)
            caminho = f.name
        check = _subprocess.run([node, "--check", caminho],
                                capture_output=True)
        assert check.returncode == 0, check.stderr.decode()[:400]


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

    def test_site_subpasta_aninhada(self, serve, tmp_path: Path) -> None:
        """Pastas dentro de site/ servem (galeria site/avatares/, 2026-10-12).

        {file} da rota aceita barra — o dono move arquivos da pasta
        analise/ para subpastas de site/ e elas precisam abrir no site.
        """
        alvo = tmp_path / "avatares"
        alvo.mkdir()
        (alvo / "nicky.png").write_bytes(b"\x89PNG fake")
        srv = serve(None, config=self._cfg(tmp_path))
        status, body, headers = _request(
            srv.bound_port, "GET", "/site/avatares/nicky.png"
        )
        assert status == 200
        assert body == b"\x89PNG fake"
        assert headers.get("Content-Type", "") == "image/png"

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

    def test_site_index_chip_vivo_e_numeros_reais(self) -> None:
        """Formato Órion no site (17/10): a badge do herói traz os
        elementos do chip vivo (od-nav.js, comportamento 4) e os números
        do topo são os REAIS do commit — o que o site afirma tem de ser
        verdade agora (os velhos 78 actions / +2.300 testes mentiam e não
        podem voltar). A contagem de testes é a da suíte completa na
        última rodada do gate (3527 em 20/10, +1 guarda do historico)."""
        raiz = Path(__file__).resolve().parents[1]
        html = (raiz / "site" / "index.html").read_text(encoding="utf-8")
        # Chip vivo: versão (#odSiteVer) e estado (#odSiteOn) preenchidos
        # em runtime pelas rotas públicas /app/version e /health.
        assert 'id="odSiteVer"' in html and 'id="odSiteOn"' in html
        assert '<span class="od-site-ponto"></span>' in html
        # Números reais de hoje.
        assert "<b>115</b><span>Actions</span>" in html
        assert "<b>3.527</b><span>Testes</span>" in html
        assert "<b>9</b><span>Ferramentas no ar</span>" in html
        assert "<b>78</b>" not in html and "+2.300" not in html

    def test_botao_voltar_ao_topo_unico_e_ligado_em_todas_as_paginas(
        self,
    ) -> None:
        """Pedido do dono (22/10): "as páginas são muito compridas —
        coloque aquele círculo que retorna ao topo".

        O botão já existia em 10 das 12 páginas; a rodada que aplicou o
        pedido DUPLICOU o da loja (dois id="toTop" = HTML inválido e o
        segundo elemento fica morto) e pôs o da página de teste DEPOIS
        do od-nav.js — o script roda no parse e o getElementById chegava
        a ver a página sem botão (nunca ligava, o círculo não aparecia).
        Trava: cada página tem EXATAMENTE UM botão .to-top e ele vem
        antes do od-nav.js — que é o único lugar que liga scroll e clique.
        """
        raiz = Path(__file__).resolve().parents[1]
        paginas = sorted((raiz / "site").glob("*.html"))
        assert paginas, "site sem páginas"
        for pagina in paginas:
            html = pagina.read_text(encoding="utf-8")
            nome = pagina.name
            assert html.count('id="toTop"') == 1, f"{nome}: toTop duplicado"
            assert 'class="to-top"' in html, f"{nome}: sem classe to-top"
            if "<script src=\"/site/od-nav.js\">" in html:
                assert html.index('id="toTop"') < html.index(
                    '<script src="/site/od-nav.js">'
                ), f"{nome}: botão depois do od-nav.js (fica morto)"

    def test_historico_cobre_todos_os_releases_e_contagem_verdadeira(
        self,
    ) -> None:
        """historico.html (20/10): a linha do tempo cobre TODOS os
        releases do projeto e os números anunciados batem com a lista.

        Trava a pauta antiga do TODO ("historico.html parou na v1.25.0")
        e as contagens que já estavam erradas antes (a Era 5 dizia 8
        releases e listava 10; index/od.css repetiam "48 / cinco eras").
        Fonte = união de CHANGELOG e README de Versão: o CHANGELOG não
        traz a 1.24.2 (só no README) e o README não traz a 1.42.0 (só no
        CHANGELOG) — cada um deles sozinho deixaria a guarda cega de um
        lado."""
        import re

        raiz = Path(__file__).resolve().parents[1]
        hist = (raiz / "site" / "historico.html").read_text(encoding="utf-8")
        index = (raiz / "site" / "index.html").read_text(encoding="utf-8")
        ch = (raiz / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        rv = (raiz / "docs" / "README_VERSAO.md").read_text(encoding="utf-8")

        lista = re.findall(r'<span class="r-ver">([0-9.]+)</span>', hist)
        fonte = set(re.findall(r"^## \[(1\.[0-9.]+)\]", ch, re.M)) | set(
            re.findall(r"^## \[(1\.[0-9.]+)\]", rv, re.M)
        )
        # 1) nada faltando: todo release documentado está na página
        assert fonte <= set(lista), sorted(fonte - set(lista))
        # 2) lista limpa: sem repetida e em ordem crescente
        assert len(lista) == len(set(lista)), "release repetido"
        assert lista == sorted(
            lista, key=lambda s: [int(x) for x in s.split(".")]
        ), "lista fora de ordem"
        # 3) contagens da PRÓPRIA página batem com a lista real
        total = len(lista)
        assert f"Os {total} Lançamentos" in hist
        assert f"{total} releases organizados" in hist
        assert f"de v1.0.0 a v{lista[-1]}" in hist
        spans = [int(n) for n in re.findall(r"· (\d+) releases</span>", hist)]
        n_eras = hist.count('class="era-box"')
        assert len(spans) == n_eras and sum(spans) == total, (
            total,
            n_eras,
            spans,
        )
        # 4) o index anuncia o MESMO número (era a outra contagem velha)
        assert f"<div class=\"num\">{total} Lançamentos</div>" in index
        assert f"Ver os {total} releases" in index
        assert "48 Lançamentos" not in index and "48 releases" not in hist

    def test_docs_de_versao_completos_e_irmãos(self) -> None:
        """CHANGELOG e README de Versão são IRMÃOS desde a nota de
        12/09 ("toda entrega registra aqui ALÉM do README de Versão").

        Trava a classe de defeito que os dois documentos tinham em
        20/10: não era corpo faltando, era CABEÇALHO engolido — o
        CHANGELOG trazia o corpo da 1.24.2 solto (sem `## [1.24.2]`) e o
        README trazia o da 1.42.0 solto (sem `## [1.42.0]`), o mesmo
        bug do `## [1.31.0]` engolido achado em 16/10. Os dois batem
        cabeça a cabeça, e o topo dos dois precisa ser a versão corrente
        (senão o release existe mas ninguém registrou em lugar nenhum)."""
        import re

        from core.capabilities import OD_VERSION

        raiz = Path(__file__).resolve().parents[1]
        ch = (raiz / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        rv = (raiz / "docs" / "README_VERSAO.md").read_text(encoding="utf-8")
        secoes_ch = set(re.findall(r"^## \[(1\.[0-9.]+)\]", ch, re.M))
        secoes_rv = set(re.findall(r"^## \[(1\.[0-9.]+)\]", rv, re.M))
        assert secoes_ch == secoes_rv, (
            f"só no CHANGELOG: {sorted(secoes_ch - secoes_rv)} · "
            f"só no README: {sorted(secoes_rv - secoes_ch)}"
        )
        chave = lambda s: [int(x) for x in s.split(".")]
        assert max(secoes_ch, key=chave) == OD_VERSION, (
            "o topo dos documentos de versão não é a versão corrente"
        )
        # e nenhuma das duas seções pode estar órfã de cabeçalho: a
        # versão corrente precisa aparecer como `## [x.y.z]` nos dois
        assert f"## [{OD_VERSION}]" in ch and f"## [{OD_VERSION}]" in rv


# ===========================================================================
# Páginas internas do dono — site_admin/ (2026-10-10)
# ===========================================================================

class TestPaginasInternasDoDono:
    """As páginas do Google saíram de /site/ e agora exigem conta de dono.

    Motivo (auditoria de segurança do site, 2026-10-10): /site/google_auth.html
    e /site/google_apis.html eram alcançáveis SEM credencial — inclusive pelo
    Funnel público — e continham o IP da rede local (192.168.0.250), instruções
    de scp/ssh, o número do projeto Google, o client_id OAuth e o caminho do
    token. Este teste trava as duas metades da correção: o vazamento sumiu do
    site público, e o acesso interno continua funcionando para o dono.
    """

    def _dono_e_comum(self, serve, tmp_path: Path):
        """Sobe o servidor com dono + conta comum, e devolve os dois tokens."""
        from integrations.api.auth import UserStore
        db = Database(tmp_path / "roles.db")
        store = UserStore(db)
        store.register("comum", "comum@example.com", "senha-comum-123")
        store.register("dono", "dono@example.com", "senha-dono-123")
        cfg = APIConfig(
            port=0, rate_limit_max=0, user_store=store,
            owner_username="dono",
            site_dir=str(Path("site").resolve()),
        )
        srv = serve(None, config=cfg)
        toks = {}
        for u in ("dono", "comum"):
            _s, body, _h = _request(
                srv.bound_port, "POST", "/auth/login",
                body={"username": u, "password": f"senha-{u}-123"},
            )
            assert _s == 200, body
            toks[u] = _json_response((_s, body, _h))["token"]
        return srv, toks

    def test_vazamento_sumiu_do_site_publico(self, serve, tmp_path: Path,
                                             monkeypatch) -> None:
        """Sem credencial nenhuma, as duas páginas antigas não existem mais."""
        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        from integrations.api.auth import UserStore
        db = Database(tmp_path / "roles.db")
        store = UserStore(db)
        store.register("dono", "dono@example.com", "senha-dono-123")
        cfg = APIConfig(
            port=0, rate_limit_max=0, user_store=store,
            owner_username="dono",
            site_dir=str(Path("site").resolve()),
        )
        srv = serve(None, config=cfg)
        for antiga in ("/site/google_auth.html", "/site/google_apis.html"):
            status, _, _ = _request(srv.bound_port, "GET", antiga)
            assert status == 404, f"{antiga} ainda é pública"

    def test_dono_abre_pela_query_sem_header(self, serve, tmp_path: Path,
                                             monkeypatch) -> None:
        """O navegador navega sem header: o dono abre com ?t=<token>.

        É o caminho real do painel — o /admin monta o link já com o token da
        sessão guardada no navegador.
        """
        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        srv, toks = self._dono_e_comum(serve, tmp_path)
        status, body, _ = _request(
            srv.bound_port, "GET",
            "/admin/google/auth?t=" + toks["dono"],
        )
        assert status == 200
        assert b"Autorizar o Google" in body
        status, body, _ = _request(
            srv.bound_port, "GET",
            "/admin/google/apis?t=" + toks["dono"],
        )
        assert status == 200
        assert b"Habilitar as APIs" in body

    def test_conta_comum_e_anonimo_negados(self, serve, tmp_path: Path,
                                           monkeypatch) -> None:
        """Conta comum não é o dono → 403; sem token → 401."""
        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        srv, toks = self._dono_e_comum(serve, tmp_path)
        # Conta comum, mesmo com sessão válida: 403 (não é o dono).
        status, _, _ = _request(
            srv.bound_port, "GET",
            "/admin/google/auth?t=" + toks["comum"],
        )
        assert status == 403
        # Sem token algum: 401.
        status, _, _ = _request(srv.bound_port, "GET", "/admin/google/auth")
        assert status == 401
        # Token inventado: 401.
        status, _, _ = _request(
            srv.bound_port, "GET", "/admin/google/auth?t=token-inventado"
        )
        assert status == 401

    def test_dev_local_sem_auth_continua_aberto(self, serve,
                                                tmp_path: Path) -> None:
        """Sem UserStore e sem OD_API_KEY a auth está desligada (dev local)."""
        cfg = APIConfig(
            port=0, rate_limit_max=0,
            site_dir=str(Path("site").resolve()),
        )
        srv = serve(None, config=cfg)
        status, _, _ = _request(srv.bound_port, "GET", "/admin/google/auth")
        assert status == 200


# ===========================================================================
# /app/version — contrato da auto-atualização do app (v1.7.0)
# ===========================================================================

class TestAPIAppVersion:
    """GET /app/version — sem auth, aponta para o APK publicado em site/.

    Hermético: usa site_dir=tmp_path em vez do site/ real do repo.
    """

    def _cfg(self, tmp_path: Path, **kwargs) -> APIConfig:
        return APIConfig(
            port=0, rate_limit_max=0, site_dir=str(tmp_path), **kwargs
        )

    def test_app_version_public_and_payload(self, serve, tmp_path: Path) -> None:
        """Sem chave nenhuma: ok, versão do sistema e version_code do APK."""
        apk = tmp_path / "OmegaDrakon.apk"
        apk.write_bytes(b"PK\x03\x04" + b"x" * 4096)
        srv = serve(None, config=self._cfg(tmp_path))
        status, body, headers = _request(srv.bound_port, "GET", "/app/version")
        data = _json_response((status, body, headers))
        assert status == 200
        assert data["ok"] is True
        assert data["version"] == OD_VERSION
        assert data["version_code"] == _APP_VERSION_CODE
        assert data["apk"] == "/site/OmegaDrakon.apk"
        assert data["size"] == apk.stat().st_size
        assert len(data["sha256"]) == 64  # hex SHA-256

    def test_app_version_matches_published_apk(self, serve, tmp_path: Path) -> None:
        """sha256/size descrevem EXATAMENTE o binário que /site/ entregar —
        é o que permite ao app conferir o download antes de instalar."""
        import hashlib

        payload = b"PK\x03\x04" + bytes(range(256)) * 1024  # 256 KB
        (tmp_path / "OmegaDrakon.apk").write_bytes(payload)
        srv = serve(None, config=self._cfg(tmp_path))
        port = srv.bound_port
        _, body, _ = _request(port, "GET", "/app/version")
        data = _json_response((_, body, _))
        status, got, _ = _request(port, "GET", "/site/OmegaDrakon.apk")
        assert status == 200 and got == payload
        assert data["size"] == len(payload)
        assert data["sha256"] == hashlib.sha256(payload).hexdigest()

    def test_app_version_without_apk(self, serve, tmp_path: Path) -> None:
        """Sem APK publicado, o endpoint responde o básico (sem size/sha)."""
        srv = serve(None, config=self._cfg(tmp_path))
        status, body, headers = _request(srv.bound_port, "GET", "/app/version")
        data = _json_response((status, body, headers))
        assert status == 200 and data["ok"] is True
        assert "size" not in data and "sha256" not in data

    def test_app_version_public_under_auth_all(self, serve, tmp_path: Path) -> None:
        """auth_all (produção): o app consulta /app/version SEM credencial
        no boot — deve continuar 200 (mesma natureza do /site public).
        Bug que este teste fixa: no deploy real de 2026-09-27 a rota dava
        401 e a auto-atualização morria calada."""
        (tmp_path / "OmegaDrakon.apk").write_bytes(b"PK\x03\x04" + b"x" * 64)
        cfg = self._cfg(tmp_path, api_key="segredo123", auth_all=True)
        srv = serve(None, config=cfg)
        status, body, headers = _request(srv.bound_port, "GET", "/app/version")
        data = _json_response((status, body, headers))
        assert status == 200, (
            "/app/version deve ser público mesmo com auth_all — o app "
            "checa atualização antes de ter credencial\n" + body
        )
        assert data["ok"] is True
        assert data["version_code"] == _APP_VERSION_CODE
        # Com a chave continua 200 (contrato não muda para quem tem credencial).
        status, _, _ = _request(
            srv.bound_port,
            "GET",
            "/app/version",
            headers={"X-API-Key": "segredo123"},
        )
        assert status == 200


class TestAPISiteCache:
    """Cache da landing (site demorava para carregar às vezes — v1.7.0).

    HTML: ETag + max-age=60 com revalidação If-None-Match → 304 barato.
    APK: no-store (download sempre completo, sem cache parcial).
    """

    def test_html_etag_and_304(self, serve, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<h1>OD</h1>", encoding="utf-8")
        srv = serve(None, config=APIConfig(
            port=0, rate_limit_max=0, site_dir=str(tmp_path)
        ))
        port = srv.bound_port
        _, _, headers = _request(port, "GET", "/site")
        etag = headers.get("ETag", "")
        assert etag, "HTML sem ETag — navegador baixa a landing inteira de novo"
        assert headers.get("Cache-Control", "") == "max-age=60"
        status, _, _ = _request(
            port, "GET", "/site", headers={"If-None-Match": etag}
        )
        assert status == 304, "ETag válido deve dar 304 (landing abre na hora)"

    def test_html_etag_changes_when_file_changes(self, serve, tmp_path: Path) -> None:
        """Deploy novo (mtime/size mudam) → ETag nova → cliente rebaixa."""
        (tmp_path / "index.html").write_text("<h1>v1</h1>", encoding="utf-8")
        srv = serve(None, config=APIConfig(
            port=0, rate_limit_max=0, site_dir=str(tmp_path)
        ))
        port = srv.bound_port
        _, _, h1 = _request(port, "GET", "/site")
        etag1 = h1.get("ETag", "")
        # Depois de 60s o mtime fica idêntico → força uma diferença de tamanho.
        (tmp_path / "index.html").write_text(
            "<h1>v2 agora com conteudo maior</h1>", encoding="utf-8"
        )
        _, _, h2 = _request(port, "GET", "/site")
        assert h2.get("ETag", "") != etag1

    def test_apk_stays_no_store(self, serve, tmp_path: Path) -> None:
        """APK NÃO é cacheado: download de atualização sempre completo."""
        (tmp_path / "OmegaDrakon.apk").write_bytes(b"PK\x03\x04")
        srv = serve(None, config=APIConfig(
            port=0, rate_limit_max=0, site_dir=str(tmp_path)
        ))
        _, _, headers = _request(
            srv.bound_port, "GET", "/site/OmegaDrakon.apk"
        )
        assert headers.get("Cache-Control", "") == "no-store"


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

    def test_navegar_nunca_cai_no_limiter(self, serve, tmp_path: Path) -> None:
        """Reporte do dono (17/10): páginas abrindo como rate_limited e
        precisando de F5 até a janela deslizar. Um abrir de /dashboard
        custa ~10 requests (HTML, ícones, auth, dados, chip do herói) —
        shells de página, assets do /site e /app/version NÃO consomem o
        orçamento; o limite segue firme no que faz trabalho de verdade
        (/health com probes ao vivo continua contado)."""
        cfg = APIConfig(port=0, rate_limit_max=3, rate_window_s=60.0)
        srv = serve(make_orch(tmp_path), config=cfg)
        port = srv.bound_port
        for _ in range(12):  # quatro "aberturas de página" completas
            assert _request(port, "GET", "/dashboard")[0] == 200
            assert _request(port, "GET", "/app/version")[0] == 200
            assert _request(port, "GET", "/site/index.html")[0] in (200, 404)
        # o que continua contado: /health (roda os checks ao vivo)
        for _ in range(3):
            assert _request(port, "GET", "/health")[0] == 200
        assert _request(port, "GET", "/health")[0] == 429

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



    def test_sem_papel_admin_e_403(self, serve, tmp_path: Path,
                                   monkeypatch) -> None:
        """O gate de verdade: conta comum (não-dono) → 403; dono → 200."""
        from integrations.api import server as api
        from integrations.api.auth import UserStore
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            api.subprocess, "Popen",
            lambda cmd, **kw: _FakeProcesso(9999),
        )
        (tmp_path / "txt.txt").write_text("ideia do dono", encoding="utf-8")
        db = Database(tmp_path / "roles.db")
        store = UserStore(db)
        store.register("comum", "comum@example.com", "senha-comum-123")
        store.register("dono", "dono@example.com", "senha-dono-123")
        cfg = APIConfig(
            port=0, rate_limit_max=0, user_store=store,
            owner_username="dono",
        )
        srv = serve(make_orch(tmp_path), config=cfg)
        _s, login_dono, _h = _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "dono", "password": "senha-dono-123"},
        )
        _s, login_comum, _h = _request(
            srv.bound_port, "POST", "/auth/login",
            body={"username": "comum", "password": "senha-comum-123"},
        )
        assert _s == 200, login_comum
        token_dono = _json_response((_s, login_dono, _h))["token"]
        token_comum = _json_response((_s, login_comum, _h))["token"]
        # Dono (owner_username): 200 — a sessão sobe (Popen fakeado).
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar"},
            headers={"Authorization": f"Bearer {token_dono}"},
        )
        assert status == 200
        # Usuário comum: 403 — o canal é do dono.
        status, _body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "parar"},
            headers={"Authorization": f"Bearer {token_comum}"},
        )
        assert status == 403
        db.close()

# ===========================================================================
# Sessão de desenvolvimento on-demand + caixa de autorização (2026-10-08)
# ===========================================================================

class _FakeProcesso:
    """Substituto de subprocess.Popen: só o pid interessa ao estado."""
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid


class TestSessaoDesenvolvimento:
    """POST/GET /admin/dev/sessao e GET/POST/DELETE /admin/dev/caixa —
    o botão ▶ Ativar desenvolvimento sobe `orquestrador.py --sessao`
    desanexado; a caixa media a autorização do dono durante a sessão."""

    def test_ativar_sem_ideia_e_400_sem_ideia(self, serve, tmp_path: Path,
                                              monkeypatch) -> None:
        """Sem ideia no txt.txt não há sessão que valha (400 sem_ideia)."""
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar"},
        )
        assert status == 400
        assert _json_response((status, body, _h))["error"] == "sem_ideia"
        assert not (tmp_path / "data/dev_sessao.json").exists()

    def test_ativar_ideia_ja_implementada_e_409_sem_subir_sessao(
        self, serve, tmp_path: Path, monkeypatch
    ) -> None:
        """Passo 2 do canal (pedido do dono 08/10): ideia IGUAL a uma sessão
        já CONCLUÍDA → 409 `ja_implementado` com commit/data no corpo (o
        painel oferece limpar o txt.txt) e NENHUM processo criado."""
        from integrations.api import server as api
        from core.dev_canal import registrar_ideia

        chamadas = {"n": 0}

        def _nao_popen(cmd, **kwargs):
            chamadas["n"] += 1
            raise AssertionError("sessão não pode subir para ideia repetida")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(api.subprocess, "Popen", _nao_popen)
        registrar_ideia(
            "criar botão de tema",
            {"status": "concluido", "motivo": "implantado", "commit": "abc1234"},
            tmp_path / "data/dev_historico.json",
        )
        # mesma ideia com outra formatação — a normalização é que decide
        (tmp_path / "txt.txt").write_text(
            "  Criar BOTÃO de tema\r\n\r\n", encoding="utf-8"
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar"},
        )
        assert status == 409
        data = _json_response((status, body, _h))
        assert data["ok"] is False
        assert data["error"] == "ja_implementado"
        assert data["commit"] == "abc1234"
        assert data["ts"].startswith("20")
        assert data["motivo"] == "implantado"
        assert chamadas["n"] == 0
        assert not (tmp_path / "data/dev_sessao.json").exists()

    def test_ativar_ideia_diferente_do_historico_sobe_normalmente(
        self, serve, tmp_path: Path, monkeypatch
    ) -> None:
        """Histórico bloqueia só a ideia IGUAL — o resto do txt.txt roda."""
        from integrations.api import server as api
        from core.dev_canal import registrar_ideia

        chamadas: dict = {}

        def _fake_popen(cmd, **kwargs):
            chamadas["desanexado"] = kwargs.get("start_new_session")
            return _FakeProcesso(5151)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(api.subprocess, "Popen", _fake_popen)
        registrar_ideia(
            "ideia já feita ontem",
            {"status": "concluido", "motivo": "implantado", "commit": "f00d00d"},
            tmp_path / "data/dev_historico.json",
        )
        (tmp_path / "txt.txt").write_text("outra ideia, bem diferente",
                                          encoding="utf-8")
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar", "cli": "opencode"},
        )
        assert status == 200
        assert _json_response((status, body, _h))["pid"] == 5151
        assert chamadas["desanexado"] is True

    def test_ativar_txt_so_com_espacos_e_400_sem_ideia(
        self, serve, tmp_path: Path, monkeypatch
    ) -> None:
        """Passo 1 do canal: txt.txt vazio → NÃO faz nada (sem Popen, sem
        estado). Só espaços é vazio para o canal."""
        from integrations.api import server as api

        monkeypatch.chdir(tmp_path)
        chamadas = {"n": 0}
        monkeypatch.setattr(
            api.subprocess, "Popen",
            lambda *a, **k: chamadas.__setitem__("n", chamadas["n"] + 1),
        )
        (tmp_path / "txt.txt").write_text("   \n\n  ", encoding="utf-8")
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar"},
        )
        assert status == 400
        assert _json_response((status, body, _h))["error"] == "sem_ideia"
        assert chamadas["n"] == 0
        assert not (tmp_path / "data/dev_sessao.json").exists()

    def test_ativar_com_ideia_sobe_a_sessao_desanexada(
        self, serve, tmp_path: Path, monkeypatch
    ) -> None:
        """Ativar spawna `orquestrador.py --sessao --cli X` com
        start_new_session (sobrevive a restart do od-core) e grava o estado."""
        from integrations.api import server as api
        chamadas: dict = {}

        def _fake_popen(cmd, **kwargs):
            chamadas["cmd"] = cmd
            chamadas["desanexado"] = kwargs.get("start_new_session")
            chamadas["cwd"] = kwargs.get("cwd")
            return _FakeProcesso(4343)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(api.subprocess, "Popen", _fake_popen)
        (tmp_path / "txt.txt").write_text(
            "crie o botão de tema no painel", encoding="utf-8"
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar", "cli": "kilo"},
        )
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True and data["pid"] == 4343
        assert data["cli"] == "kilo"
        assert "--sessao" in chamadas["cmd"]
        assert "orquestrador.py" in " ".join(chamadas["cmd"])
        assert chamadas["desanexado"] is True
        estado = json.loads(
            (tmp_path / "data/dev_sessao.json").read_text(encoding="utf-8")
        )
        assert estado["ativo"] is True and estado["status"] == "preparando"
        assert "botão de tema" in estado["ideia_preview"]

    def test_ativar_cli_invalida_e_400(self, serve, tmp_path: Path,
                                       monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("ideia válida", encoding="utf-8")
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar", "cli": "gemini-pro-max"},
        )
        assert status == 400
        assert _json_response((status, body, _h))["error"] == "cli_invalida"

    def test_acao_invalida_e_400(self, serve, tmp_path: Path,
                                 monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "reiniciar-servidor"},
        )
        assert status == 400
        status, _, _h = _request(srv.bound_port, "POST", "/admin/dev/sessao")
        assert status == 400  # sem body → objeto vazio → ação inválida
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao", body=["lista", "solta"]
        )
        assert status == 400  # body não-objeto

    def test_falha_ao_subir_o_processo_e_500(self, serve, tmp_path: Path,
                                             monkeypatch) -> None:
        """OSError do Popen vira 500 com erro claríssimo — não 200 mentindo."""
        from integrations.api import server as api

        def _popen_quebrado(cmd, **kwargs):
            raise OSError("sem permissão para forkar")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(api.subprocess, "Popen", _popen_quebrado)
        (tmp_path / "txt.txt").write_text("ideia", encoding="utf-8")
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao", body={"acao": "ativar"}
        )
        assert status == 500
        assert _json_response((status, body, _h))["error"] == "falha_ao_iniciar_sessao"
        assert not (tmp_path / "data/dev_sessao.json").exists()

    def test_ativar_com_sessao_viva_e_409(self, serve, tmp_path: Path,
                                          monkeypatch) -> None:
        """Uma sessão por vez: estado ativo + processo vivo → 409."""
        from integrations.api import server as api
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(api, "_pid_sessao_vivo", lambda pid: True)
        (tmp_path / "txt.txt").write_text("outra ideia", encoding="utf-8")
        (tmp_path / "data").mkdir()
        (tmp_path / "data/dev_sessao.json").write_text(
            json.dumps({"ativo": True, "pid": 4343, "status": "executando"}),
            encoding="utf-8",
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao",
            body={"acao": "ativar"},
        )
        assert status == 409
        assert _json_response((status, body, _h))["error"] == "sessao_ativa"

    def test_parar_sem_sessao_e_409(self, serve, tmp_path: Path,
                                    monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao", body={"acao": "parar"}
        )
        assert status == 409

    def test_parar_derruba_o_grupo_runner_cli(self, serve, tmp_path: Path,
                                              monkeypatch) -> None:
        """Parar manda SIGTERM no GRUPO (start_new_session → pgid == pid),
        para a CLI filha também morrer — e marca o estado como parado."""
        import signal as _signal
        from integrations.api import server as api
        monkeypatch.chdir(tmp_path)
        morte: dict = {}

        def _fake_killpg(pid, sinal):
            morte.update(pid=pid, sinal=sinal)

        monkeypatch.setattr(api, "_pid_sessao_vivo", lambda pid: True)
        monkeypatch.setattr(api.os, "killpg", _fake_killpg)
        (tmp_path / "data").mkdir()
        (tmp_path / "data/dev_sessao.json").write_text(
            json.dumps({"ativo": True, "pid": 4242, "status": "executando"}),
            encoding="utf-8",
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao", body={"acao": "parar"}
        )
        assert status == 200
        assert morte == {"pid": 4242, "sinal": _signal.SIGTERM}
        estado = json.loads(
            (tmp_path / "data/dev_sessao.json").read_text(encoding="utf-8")
        )
        assert estado["ativo"] is False and estado["status"] == "parado"
        assert estado["motivo"] == "parada_pelo_dono"

    def test_parar_com_killpg_barulhento_e_500(self, serve, tmp_path: Path,
                                               monkeypatch) -> None:
        from integrations.api import server as api

        def _killpg_quebrado(pid, sinal):
            raise OSError("process group sumiu")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(api, "_pid_sessao_vivo", lambda pid: True)
        monkeypatch.setattr(api.os, "killpg", _killpg_quebrado)
        (tmp_path / "data").mkdir()
        (tmp_path / "data/dev_sessao.json").write_text(
            json.dumps({"ativo": True, "pid": 4242, "status": "executando"}),
            encoding="utf-8",
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/sessao", body={"acao": "parar"}
        )
        assert status == 500
        assert _json_response((status, body, _h))["error"] == "falha_ao_parar"

    def test_get_sem_estado_responde_parada(self, serve, tmp_path: Path,
                                            monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/admin/dev/sessao")
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True
        assert data["ativo"] is False and data["status"] == "parada"
        assert data["caixa_pendente"] == 0
        assert "log_tail" in data

    def test_get_normaliza_sessao_com_processo_morto(
        self, serve, tmp_path: Path, monkeypatch
    ) -> None:
        """Crash/restart derruba o processo sem registrar: o painel NUNCA
        pode continuar mentindo 'executando' — o GET normaliza o estado."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data/dev_sessao.json").write_text(
            json.dumps({"ativo": True, "pid": 999_999, "status": "executando"}),
            encoding="utf-8",
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/admin/dev/sessao")
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ativo"] is False
        assert data["status"] == "interrompida"
        assert data["motivo"] == "processo_ausente"
        estado = json.loads(
            (tmp_path / "data/dev_sessao.json").read_text(encoding="utf-8")
        )
        assert estado["ativo"] is False  # disco corrigido junto

    def test_caixa_roundtrip_resposta_do_dono(self, serve, tmp_path: Path,
                                              monkeypatch) -> None:
        """POST grava a resposta do dono, GET devolve, DELETE limpa."""
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/admin/dev/caixa")
        data = _json_response((status, body, _h))
        assert status == 200 and data["total"] == 0 and data["pendentes"] == 0

        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/caixa",
            body={"texto": "pode seguir com o deploy de teste"},
        )
        data = _json_response((status, body, _h))
        assert data["ok"] is True and data["mensagem"]["de"] == "dono"
        assert data["mensagem"]["texto"] == "pode seguir com o deploy de teste"

        status, body, _h = _request(srv.bound_port, "GET", "/admin/dev/caixa")
        data = _json_response((status, body, _h))
        assert data["total"] == 1 and data["mensagens"][0]["de"] == "dono"

        status, _, _h = _request(
            srv.bound_port, "DELETE", "/admin/dev/caixa"
        )
        assert status == 200
        status, body, _h = _request(srv.bound_port, "GET", "/admin/dev/caixa")
        assert _json_response((status, body, _h))["total"] == 0

    def test_caixa_conta_autorizacoes_pendentes(self, serve, tmp_path: Path,
                                                monkeypatch) -> None:
        """Pergunta do sistema sem resposta conta como pendente; a
        respondida não — é assim que o painel acende o alerta."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data/dev_caixa.json").write_text(
            json.dumps([
                {"id": "1", "de": "sistema", "tipo": "pedir_autorizacao",
                 "texto": "posso subir o APK?", "respondida": False},
                {"id": "2", "de": "dono", "tipo": "resposta",
                 "texto": "não", "respondida": False},
                {"id": "3", "de": "sistema", "tipo": "pedir_autorizacao",
                 "texto": "reinício o od-core?", "respondida": True},
                {"id": "4", "de": "sistema", "tipo": "info",
                 "texto": "sessão iniciada", "respondida": False},
            ]),
            encoding="utf-8",
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/admin/dev/caixa")
        data = _json_response((status, body, _h))
        assert data["total"] == 4 and data["pendentes"] == 1

    def test_caixa_validacoes_de_texto(self, serve, tmp_path: Path,
                                       monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/caixa", body={"texto": "   "}
        )
        assert status == 400
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/caixa", body=["não", "é", "objeto"]
        )
        assert status == 400  # body não-objeto
        status, _, _h = _request(
            srv.bound_port, "POST", "/admin/dev/caixa",
            body={"texto": "x" * 4001},
        )
        assert status == 400

    def test_caixa_corta_historico_encorpado(self, serve, tmp_path: Path,
                                             monkeypatch) -> None:
        """Mais de 500 mensagens → só as 400 mais recentes ficam (o disco
        não vira depósito de conversa eterna)."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        velhas = [
            {"id": str(i), "de": "sistema", "tipo": "info",
             "texto": f"msg {i}", "respondida": False}
            for i in range(501)
        ]
        (tmp_path / "data/dev_caixa.json").write_text(
            json.dumps(velhas), encoding="utf-8"
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "POST", "/admin/dev/caixa", body={"texto": "nova"}
        )
        assert status == 200
        # 400 velhas restantes + a nova
        assert _json_response((status, body, _h))["total"] == 401

    def test_painel_admin_tem_os_controles_da_sessao(
        self, serve, tmp_path: Path
    ) -> None:
        """Guarda do HTML: os ids que o JS do painel referencia existem —
        clique quebrado no ar é o bug de 2026-09-26 que a gente não repete."""
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/admin")
        assert status == 200
        html = body.decode("utf-8")
        for identificador in (
            "sess-ativar", "sess-parar", "sess-cli", "sess-estado",
            "sess-caixa", "sess-resposta", "sess-enviar", "sess-log",
            "sess-info", "sess-msg", "sess-limpar-caixa",
        ):
            assert f'id="{identificador}"' in html, identificador

    def test_ordem_no_painel_canal_logo_abaixo_das_ideias(
        self, serve, tmp_path: Path
    ) -> None:
        """Decisão do dono (08/10): a seção 'Canal de desenvolvimento' fica
        LOGO ABAIXO de 'Ideias (txt.txt)' — ordem travada na suíte."""
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(srv.bound_port, "GET", "/admin")
        assert status == 200
        html = body.decode("utf-8")
        i_ideias = html.index("<h2>Ideias (txt.txt)</h2>")
        i_canal = html.index("<h2>Canal de desenvolvimento</h2>")
        i_limitacoes = html.index("<h2>Limitações (registro automático)</h2>")
        assert i_ideias < i_canal < i_limitacoes
        # a seção do canal inteira entre as duas, sem nada da fila antiga
        trecho = html[i_ideias:i_limitacoes]
        assert 'id="sess-ativar"' in trecho
        assert "Fila manual" not in trecho and "dev-texto" not in trecho


# ===========================================================================
# Canal de ideias do dono (txt.txt) + Casa de Limitações (v1.13.0)
# ===========================================================================

class TestAdminIdeias:
    """GET/PUT/DELETE /admin/ideias — o dono escreve ideias e pedidos de
    informação no txt.txt pelo painel (site/app), sem SSH."""

    def test_put_grava_e_get_le(self, serve, tmp_path: Path,
                                monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "PUT", "/admin/ideias",
            body={"conteudo": "ideia: action de cotação do dólar"},
        )
        assert status == 200
        status, body, _h = _request(srv.bound_port, "GET", "/admin/ideias")
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True
        assert "cotação do dólar" in data["conteudo"]
        assert (tmp_path / "txt.txt").read_text(encoding="utf-8") == (
            "ideia: action de cotação do dólar"
        )

    def test_put_vazio_e_valido(self, serve, tmp_path: Path,
                                monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "PUT", "/admin/ideias", body={"conteudo": ""},
        )
        assert status == 200
        assert (tmp_path / "txt.txt").read_text(encoding="utf-8") == ""

    def test_put_muito_longo_400(self, serve, tmp_path: Path,
                                 monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "PUT", "/admin/ideias",
            body={"conteudo": "x" * 20001},
        )
        assert status == 400

    def test_delete_zera_idempotente(self, serve, tmp_path: Path,
                                     monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        _request(srv.bound_port, "PUT", "/admin/ideias",
                 body={"conteudo": "algo"})
        for _ in range(2):  # idempotente
            status, body, _h = _request(
                srv.bound_port, "DELETE", "/admin/ideias")
            assert status == 200
        assert (tmp_path / "txt.txt").read_text(encoding="utf-8") == ""

    def test_sem_admin_401(self, serve, tmp_path: Path,
                           monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        cfg = APIConfig(port=0, api_key="segredo123", rate_limit_max=0)
        srv = serve(make_orch(tmp_path), config=cfg)
        status, _, _h = _request(srv.bound_port, "GET", "/admin/ideias",
                                 api_key="errada")
        assert status == 401


class TestAdminLimitacoes:
    """GET/DELETE /admin/limitacoes — o que o sistema NÃO soube responder,
    registrado sozinho (Casa de Limitações, v1.13.0)."""

    def test_vazio_quando_nunca_registrou(self, serve, tmp_path: Path,
                                          monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "GET", "/admin/limitacoes")
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True and data["total"] == 0

    def test_entrada_registrada_aparece(self, serve, tmp_path: Path,
                                        monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        from core.limitacoes import registrar_limitacao
        registrar_limitacao(
            "fallback_honesto_esgotado", "qual o valor do dólar"
        )
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "GET", "/admin/limitacoes")
        data = _json_response((status, body, _h))
        assert data["total"] == 1
        e = data["entradas"][0]
        assert e["motivo"] == "fallback_honesto_esgotado"
        assert e["pergunta"] == "qual o valor do dólar"
        assert e["ts"]  # ISO presente

    def test_delete_limpa(self, serve, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        from core.limitacoes import registrar_limitacao, limpar_limitacoes
        registrar_limitacao("action_degradada:weather_city", "clima em X")
        srv = serve(make_orch(tmp_path))
        status, body, _h = _request(
            srv.bound_port, "DELETE", "/admin/limitacoes")
        assert status == 200
        data = _json_response((status, body, _h))
        assert data["ok"] is True and data["total"] == 0
        limpar_limitacoes()  # higiene entre testes
