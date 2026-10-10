"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/api/server.py
Descrição: API REST sobre o Orchestrator (Fase 5, item 5.2) — os 17
           endpoints do legado Nicky (interfaces/api.py) reimplementados em
           http.server stdlib (ThreadingHTTPServer), sem FastAPI/uvicorn:
           health, profiles, presence, dashboard/chat (HTML), metrics,
           message (pipeline), transcribe/tts (hooks plugáveis), history,
           memory (RAG) — com API key via header X-API-Key (mesma semântica
           do legado), rate limit por IP (janela deslizante) e CORS.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/api.py (17 endpoints, porta 8000)
  - docs/NICKY_LEGACY_ANALYSIS.md §9 (tabela de endpoints)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.2

Decisões registradas (ver CHANGELOG):
  - Sem dependência externa: http.server + urllib, não FastAPI/uvicorn
  - WebSocket /ws/chat responde 501 (streaming token-a-token exige servidor
    assíncrono dedicado — tema de evolução da Fase 5)
  - STT/TTS reais são Fase 6 (6.3/6.4): os endpoints aceitam handlers
    plugáveis injetados; sem handler, 501
  - HTML do dashboard/chat é placeholder mínimo (sem JS/PWA)
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from tools.registry import ActionRegistry

from core.capabilities import OD_VERSION, capabilities_manifest
from core.dev_canal import ideia_ja_implementada

# versionCode do APK publicado em site/ — sincronizado no bump (v1.7.0:
# auto-atualização do app compara este número com o dele).
# 2017 (e não 17): builds ATÉ a 1.6.1 somavam 2000 no split arm64 — o
# celular do dono está na linhagem arm64 (2016). Um code abaixo disso é
# downgrade e o instalador recusa ("pacote parece ser inválido").
# O versionName (X.Y.Z) é o OD_VERSION — vem do core.capabilities.
_APP_VERSION_CODE = 2052  # versionCode cru do APK publicado (v1.24.0+2052)
from core.identity import resolve_account
from agents.profiles import resolve_auto as resolve_auto_profile
from agents.profiles import profile_display_name as _profile_display_name
from core.orchestrator import cache_failure_reason as _cache_failure_reason
from core.logger import get_logger
from core.orchestrator import OrchestrationResult, Orchestrator
from core.supervision import get_supervision
from integrations.telegram.commands import (
    _classificar_risco,
    NIVEL_1_ADMIN,
    NIVEL_2_DESTRUTIVO,
)
from integrations.api.auth import AuthError, _hash_password
from tools.registry import ActionNotFoundError

__signature__ = "OD // CORE"

# Identificador de servidor HTTP, derivado da versão do sistema.
# Quando a versão central mudar, aqui também se atualiza sem tocar no código.
SERVER_VERSION = f"OmegaDrakon/{OD_VERSION}"

if TYPE_CHECKING:
    from memory.vector import VectorStore

log = get_logger("omega.integrations.api")

# Perfis do agente (mesma lista do legado Nicky; Profile Manager é o 6.5;
# nexus/Conector = 7º perfil da Plêiade — v1.0.0, item 1.3).
DEFAULT_PROFILES = (
    "auto", "guardian", "regulus", "luma", "vox", "athenae", "nyx", "nexus",
)
DEFAULT_PROFILE = "guardian"

API_NAME = "Omega Drakon REST API"

# Site do projeto (landing + APK) servido estaticamente em /site*.
# Caminho padrão: pasta site/ na raiz do repo (config.site_dir sobrescreve).
DEFAULT_SITE_DIR = Path(__file__).resolve().parents[2] / "site"

# Shells de página (HTML estático, sem dados) — com page_shells_public,
# continuam abertos para o navegador carregar a UI mesmo com auth_all.
# /site* entra aqui para a landing + download do APK funcionarem no
# celular (Tailscale) sem exigir X-API-Key no navegador.
PAGE_PATHS = frozenset({"/", "/chat", "/dashboard", "/admin", "/site", "/site/{file}", "/auth/register", "/auth/login"})

# Endpoints que NÃO passam pela chave mesmo com auth_all ligado: o fluxo de
# autenticação em si (register/login), a conversa ANÔNIMA (quem só quer
# conversar, sem conta — privilégio mínimo, nada é gravado) e o anúncio de
# versão (o app consulta /app/version SEM credencial no boot — e o APK em si
# já é público por /site/, coberto por test_site_public_under_auth_all).
AUTH_EXEMPT_PATHS = frozenset(
    {"/auth/register", "/auth/login", "/anon/message", "/app/version",
     "/registry/{codigo}", "/registry/{codigo}/photo",
     "/registry/{codigo}/chat"}
)


class APIError(Exception):
    """Erro de API com status HTTP correspondente.

    `extra` são campos que entram NO CORPO da resposta junto do código
    (ex.: o commit/data da ideia "já implementado" — o painel precisa deles
    para montar o aviso, e só o código não diz nada).
    """

    def __init__(self, status: int, message: str,
                 extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra: dict[str, Any] = extra or {}


@dataclass(slots=True)
class APIConfig:
    """Configuração do servidor REST.

    Attributes:
        host:           Endereço de bind (padrão loopback — nunca 0.0.0.0
                        sem auth; ver decisão de segurança no CHANGELOG).
        port:           Porta (0 = efêmera, útil em testes).
        api_key:        Chave exigida nos endpoints protegidos (header
                        X-API-Key). Vazia = sem auth (uso local/dev).
        auth_all:       Quando True, a API key passa a ser exigida em TODOS
                        os endpoints (inclusive os públicos) — modo para
                        bind exposto na LAN (0.0.0.0).
        page_shells_public: Com auth_all=True, os SHELLS das páginas web
                        (GET /chat e /dashboard — HTML estático sem dados)
                        continuam abertos para o navegador carregar a UI; a
                        chave é exigida em TODA chamada de dados/API. False
                        fecha também os shells.
        rate_limit_max: Máximo de requests por IP na janela (0 desliga).
        rate_window_s:  Janela do rate limit em segundos.
        profiles:       Perfis válidos expostos em /profiles.
        max_body_bytes: Limite de corpo em POSTs (413 acima disso).
        stt:            Handler plugável de transcrição (bytes) -> texto.
        tts:            Handler plugável de síntese (texto) -> áudio bytes.
        metrics:        MetricsCollector opcional (Fase 7.2): quando
                        presente, o GET /metrics renderiza o coletor
                        (que inclui os contadores od_api_* e fontes
                        externas). Ausente = comportamento legado inline.
        health:         HealthMonitor opcional (Fase 7.3): quando presente,
                        o GET /health responde o agregado do monitor
                        (up/degraded/down + checks por componente).
                        Ausente = comportamento legado.
        site_dir:       Diretório do site estático servido em /site*
                        (landing + OmegaDrakon.apk). None = padrão
                        site/ na raiz do repo.
        account_aliases: Mapa id-legado → conta do dono (core/identity.py,
                        `OD_ACCOUNT_ALIASES`). O app manda `user_id: "app"`
                        fixo e o bot do Telegram usa o id numérico do chat;
                        apontar esses ids para a conta faz a conversa cair no
                        balde do dono. Vazio = desligado (comportamento
                        antigo). Só vale no caminho SEM usuário (OD_API_KEY).
        owner_username: conta do DONO (`OD_OWNER_USERNAME`, ex.: "alex").
                        A `OD_API_KEY` é a chave do dono: com esse nome
                        configurado e a conta existindo, a chave assume a
                        conta (histórico contínuo) e ganha o papel admin —
                        inclusive para ler qualquer histórico. Essa conta
                        também é admin quando entra por sessão/API key
                        própria. Vazio = sem dono (OD_API_KEY segue sem
                        conta, comportamento anterior).
    """

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str = ""
    auth_all: bool = False
    page_shells_public: bool = True
    rate_limit_max: int = 30
    rate_window_s: float = 60.0
    profiles: tuple[str, ...] = DEFAULT_PROFILES
    max_body_bytes: int = 256_000
    stt: Optional[Callable[[bytes], Optional[str]]] = None
    tts: Optional[Callable[[str], Optional[bytes]]] = None
    metrics: Optional[Any] = None
    health: Optional[Any] = None
    site_dir: Optional[str] = None
    action_registry: Optional[Any] = None
    push: Optional[Any] = None
    user_store: Optional[Any] = None  # integrations.api.auth.UserStore
    registry: Optional[Any] = None    # core.registry.RegistryStore (peças)
    # Callable síncrono(texto) → avisa o dono no Telegram (sala das peças);
    # montado pelo launcher com o loop principal (build_chat_notify).
    chat_notify: Optional[Any] = None
    # Freio contra força bruta em POST /auth/login (integrations.api.auth
    # .LoginGuard). `login_guard` permite injetar uma instância (testes);
    # ausente = o servidor constrói uma a partir dos números abaixo.
    login_guard: Optional[Any] = None
    login_max_attempts: int = 5
    login_window_s: float = 300.0
    login_lockout_s: float = 900.0
    # Alias de transporte legado → conta do dono (core/identity.py).
    account_aliases: dict[str, str] = field(default_factory=dict)
    # Conta do dono: OD_API_KEY assume essa conta e ganha papel admin.
    owner_username: str = ""

    # Nota (SLOTS): campos novos entram aqui, como `push` (core/push.py) —
    # registro de dispositivos + envio FCM usados por /push/*.


# ---------------------------------------------------------------------------
# Roteamento declarativo
# ---------------------------------------------------------------------------

# (method, path_pattern, handler_name, requires_api_key)
_ROUTE_SPECS: list[tuple[str, str, str, bool]] = [
    ("GET", "/", "info", False),
    ("GET", "/health", "health", False),
    ("GET", "/profiles", "profiles", False),
    ("GET", "/profiles/{name}", "profile_detail", False),
    ("GET", "/presence/today", "presence_today", False),
    ("GET", "/dashboard", "dashboard_html", False),
    ("GET", "/admin", "admin_html", False),
    ("GET", "/chat", "chat_html", False),
    ("GET", "/metrics", "metrics_text", False),
    ("GET", "/site", "site_index", False),
    ("GET", "/site/{file}", "site_file", False),
    ("GET", "/app/version", "app_version", False),
    # Registro Mestre: consulta pública de autenticidade de peças — o ID
    # vem GRAVADO na peça; público sem credencial (mesma natureza de
    # /app/version, v. AUTH_EXEMPT_PATHS).
    ("GET", "/registry/{codigo}", "registry_verify", False),
    # Foto do produto (pública) e sala de bate-papo da peça: leitura
    # pública, escrita exige conta.
    ("GET", "/registry/{codigo}/photo", "registry_photo", False),
    ("GET", "/registry/{codigo}/chat", "registry_chat_get", False),
    ("POST", "/registry/{codigo}/chat", "registry_chat_post", True),
    # Auth — sem auth (o handler valida internamente)
    ("POST", "/auth/register", "auth_register", False),
    ("POST", "/auth/login", "auth_login", False),
    ("POST", "/auth/logout", "auth_logout", True),
    ("GET", "/auth/me", "auth_me", True),
    # Conta do usuário logado (dashboard do usuário)
    ("POST", "/account/password", "account_password", True),
    ("POST", "/account/api-key", "account_api_key", True),
    # Admin — handlers exigem papel admin (403 para os demais)
    ("GET", "/admin/users", "admin_users", True),
    ("POST", "/admin/users/{username}/password", "admin_reset_password", True),
    ("DELETE", "/admin/users/{username}", "admin_delete_user", True),
    ("POST", "/admin/cache/prune", "admin_cache_prune", True),
    # Sessão de desenvolvimento on-demand + caixa de autorização (2026-10-08)
    ("POST", "/admin/dev/sessao", "admin_dev_sessao", True),
    ("GET", "/admin/dev/sessao", "admin_dev_sessao_status", True),
    ("GET", "/admin/dev/caixa", "admin_dev_caixa_status", True),
    ("POST", "/admin/dev/caixa", "admin_dev_caixa_write", True),
    ("DELETE", "/admin/dev/caixa", "admin_dev_caixa_clear", True),
    # Canal de ideias do dono (txt.txt) + Casa de Limitações (limitacoes.txt)
    # — v1.13.0, mesmo gate do canal de pedidos
    ("GET", "/admin/ideias", "admin_ideias_status", True),
    ("PUT", "/admin/ideias", "admin_ideias_write", True),
    ("DELETE", "/admin/ideias", "admin_ideias_clear", True),
    ("GET", "/admin/limitacoes", "admin_limitacoes_status", True),
    ("DELETE", "/admin/limitacoes", "admin_limitacoes_clear", True),
    # Registro Mestre de peças (item 2 da pauta, 2026-10-09) — escrita só
    # do dono; a consulta pública é GET /registry/{codigo}.
    ("POST", "/admin/registry", "admin_registry_create", True),
    ("GET", "/admin/registry", "admin_registry_list", True),
    ("PUT", "/admin/registry/{public_id}", "admin_registry_update", True),
    ("DELETE", "/admin/registry/{public_id}", "admin_registry_delete", True),
    ("POST", "/admin/registry/{public_id}/photo", "admin_registry_photo", True),
    ("DELETE", "/admin/registry/{public_id}/chat/{msg_id}",
     "admin_registry_chat_delete", True),
    # Dados protegidos
    ("GET", "/dashboard/stats", "dashboard_stats", True),
    ("GET", "/llms", "llms", True),
    ("GET", "/capabilities", "capabilities", True),
    ("GET", "/actions", "actions_catalog", True),
    ("POST", "/message", "message", True),
    ("POST", "/anon/message", "anon_message", False),
    ("POST", "/executa", "executa", True),
    ("POST", "/push/register", "push_register", True),
    ("POST", "/push/unregister", "push_unregister", True),
    ("POST", "/push/test", "push_test", True),
    ("GET", "/push/devices", "push_devices", True),
    ("GET", "/supervision", "supervision", True),
    ("POST", "/transcribe", "transcribe", True),
    ("POST", "/tts", "tts", True),
    ("DELETE", "/history/{user_id}", "history_delete", True),
    ("DELETE", "/history/{user_id}/messages/{message_id}", "history_delete_message", True),
    ("GET", "/history/{user_id}/stats", "history_stats", True),
    ("GET", "/history/{user_id}", "history_get", True),
    ("GET", "/memory/{user_id}/search", "memory_search", True),
    ("GET", "/ws/chat", "ws_chat", True),
]


def _compile_route(pattern: str) -> re.Pattern[str]:
    """Converte '/history/{user_id}/stats' em regex de fullmatch."""
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    return re.compile(regex + r"/?\Z")


# --- Canal de desenvolvimento (orquestrador.py) ----------------------------

#: Raiz do projeto (integrations/api/server.py → 3 níveis acima).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Estado da sessão on-demand — escrito pelo runner, lido pelo painel (atômico).
SESSAO_ESTADO_FILE = Path("data/dev_sessao.json")

#: Caixa de desenvolvimento: perguntas do sistema e respostas do dono.
SESSAO_CAIXA_FILE = Path("data/dev_caixa.json")

#: Log da sessão (stdout/stderr do processo desanexado).
SESSAO_LOG_FILE = Path("logs/dev_sessao.log")

#: Teto de uma mensagem do dono na caixa.
SESSAO_CAIXA_MAX_CHARS = 4000

#: argv que identifica UMA SESSÃO do orquestrador.
_SESSAO_ARGV_MARK = "--sessao"


# --- Sessão de desenvolvimento on-demand (2026-10-08) ----------------------
#
# O dono escreve a ideia no `txt.txt` (seção "Ideias (txt.txt)" do painel) e
# aperta ▶ Ativar na seção "Canal de desenvolvimento": o od-core sobe
# `orquestrador.py --sessao` desanexado (start_new_session — sobrevive a
# restart do od-core). A sessão pausa na CAIXA de desenvolvimento
# (data/dev_caixa.json) quando a CLI pede autorização e encerra com
# validação (suíte canônica) + commit (sem push). A fila `pedido.txt` e a
# UI dela foram removidas em 2026-10-08 a pedido do dono.


def _ler_json_caminho(caminho: Path) -> dict:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_json_caminho(caminho: Path, objeto: object) -> None:
    """Escrita atômica (tmp + rename) — o runner escreve concorrentemente."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(objeto, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho)


def _ler_caixa_caminho(caminho: Path) -> list[dict]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return dados if isinstance(dados, list) else []


def _gravar_caixa_caminho(caminho: Path, mensagens: list[dict]) -> None:
    _gravar_json_caminho(caminho, mensagens)


def _pid_sessao_vivo(pid: int) -> bool:
    """True quando `pid` é um `orquestrador.py --sessao` vivo (varredura /proc)."""
    if pid <= 0:
        return False
    try:
        bruto = Path("/proc", str(pid), "cmdline").read_bytes()
    except OSError:
        return False
    partes = [p.decode("utf-8", "replace") for p in bruto.split(b"\x00") if p]
    return any(p.endswith("orquestrador.py") for p in partes) and _SESSAO_ARGV_MARK in partes


def _tail_log(caminho: Path, linhas: int = 40) -> str:
    """Últimas `linhas` do log da sessão para o painel (best-effort)."""
    try:
        texto = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(texto.splitlines()[-linhas:])


# Formato aceito para `user_id` vindo do CLIENTE (corpo de /message, frame de
# auth do WebSocket). O id entra em nome de arquivo no backend JSON
# (`data/conversations/{user_id}`) e no cache — sem essa peneira, um `../..`
# escaparia do diretório. Os ids legados casam todos: "web", "app",
# "ws_user", "deploy-check-2", "660518870" (Telegram) e os usernames das contas.
_USER_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


# Teto de contexto aceito na conversa anônima (mensagens do cliente).
ANON_HISTORY_MAX = 20


def valid_user_id(user_id: str) -> bool:
    """True quando o `user_id` é seguro para virar chave de histórico/cache."""
    return bool(_USER_ID_RE.fullmatch(user_id)) and user_id not in (".", "..")


@dataclass(slots=True)
class _Route:
    method: str
    path: str
    pattern: re.Pattern[str]
    handler: str
    auth: bool


ROUTES: list[_Route] = [
    _Route(method, path, _compile_route(path), handler, auth)
    for method, path, handler, auth in _ROUTE_SPECS
]

# ---------------------------------------------------------------------------
# Página de chat (shell público + chave no navegador + POST /message)
# ---------------------------------------------------------------------------

_DASHBOARD_PAGE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OmegaDrakon — Meu painel</title>
<link rel="icon" href="/site/favicon.png">
<style>
  :root {
    --bg: #06080f; --bg2: #0c1120; --bg3: #111830;
    --text: #e8eaf0; --muted: #7a839a; --border: #1c2440;
    --accent: #f59e0b; --ok: #34d399; --err: #f87171;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100dvh;
    -webkit-font-smoothing: antialiased;
  }
  header {
    padding: 12px 20px; background: var(--bg2);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px;
  }
  header a { color: var(--text); text-decoration: none; font-weight: 700; }
  header a:hover { color: var(--accent); }
  header h1 { font-size: 15px; font-weight: 600; margin: 0; color: var(--muted); }
  #badge { margin-left: auto; font-size: 0.85rem; color: var(--muted); }
  #badge b { color: var(--accent); }
  main { max-width: 960px; margin: 0 auto; padding: 20px; display: grid; gap: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
  .card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px 16px;
  }
  .card .k { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .card .v { font-size: 1.6rem; font-weight: 700; margin-top: 4px; }
  section h2 { font-size: 1rem; margin-bottom: 10px; color: var(--accent); }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 0.72rem; text-transform: uppercase; }
  td.num, th.num { text-align: right; }
  .muted { color: var(--muted); }
  .msg { font-size: 0.85rem; min-height: 1.2em; margin-top: 8px; }
  .msg.ok { color: var(--ok); }
  .msg.err { color: var(--err); }
  button {
    background: var(--bg3); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 14px; font-size: 0.85rem; cursor: pointer;
  }
  button:hover { border-color: var(--accent); color: var(--accent); }
  button.danger:hover { border-color: var(--err); color: var(--err); }
  label { display: block; font-size: 0.8rem; color: var(--muted); margin: 8px 0 4px; }
  input {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 10px; font-size: 0.9rem; width: 260px; max-width: 100%;
  }
  .row { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; }
  code { color: var(--accent); font-size: 0.8rem; word-break: break-all; }
</style>
</head>
<body>
<header>
  <a href="/"><img src="/site/simbolo_minimo.png" alt="OD" style="width:22px;height:22px;vertical-align:-4px"></a><h1>Meu painel</h1>
  <div id="badge"></div>
</header>
<main>
  <section>
    <h2>Uso da conta</h2>
    <div class="grid" id="stats"></div>
    <div class="muted msg" id="stats-note"></div>
  </section>

  <section>
    <h2>Minha conversa</h2>
    <table><tbody id="hist"></tbody></table>
    <div class="row">
      <button class="danger" id="btn-limpar">🧹 Limpar meu histórico</button>
      <span class="muted msg" id="limpar-msg"></span>
    </div>
  </section>

  <section>
    <h2>Conta</h2>
    <div class="card">
      <b>Trocar senha</b>
      <div class="row">
        <div><label>Senha atual</label><input type="password" id="cur-pass"></div>
        <div><label>Nova senha (mín. 6)</label><input type="password" id="new-pass"></div>
        <button id="btn-trocar-senha">Trocar</button>
      </div>
      <div class="msg" id="senha-msg"></div>
    </div>
    <div class="card" style="margin-top:12px">
      <b>API key</b>
      <p class="muted" style="font-size:0.8rem;margin-top:4px">Chave de app/curl. Rotacionar invalida a antiga na hora.</p>
      <div class="row" style="margin-top:8px">
        <code id="api-key" class="muted">rotacionar gera uma chave nova</code>
        <button class="danger" id="btn-rotacionar">Rotacionar</button>
      </div>
      <div class="msg" id="key-msg"></div>
    </div>
  </section>
</main>
<script>
let token = localStorage.getItem("od_session_token") || "";
let key = localStorage.getItem("od_api_key") || "";

function authHeaders(extra) {
  const h = extra || {};
  if (token) h["Authorization"] = "Bearer " + token;
  else if (key) h["X-API-Key"] = key;
  return h;
}

async function whoAmI() {
  const resp = await fetch("/auth/me", { headers: authHeaders() });
  if (!resp.ok) { location.href = "/chat"; return null; }
  const data = await resp.json();
  const role = data.role || "user";
  document.getElementById("badge").innerHTML =
    "👤 <b>" + data.user.username + "</b> · " + role +
    ' · <a href="/chat">💬 Chat</a>' + (role === "admin" ? ' · <a href="/admin">🛡 Admin</a>' : "");
  return data;
}

async function loadStats() {
  const resp = await fetch("/history/me/stats", { headers: authHeaders() });
  const note = document.getElementById("stats-note");
  if (!resp.ok) { note.textContent = "Stats indisponível (HTTP " + resp.status + ")."; return; }
  const data = await resp.json();
  const s = data.stats || {};
  const cards = [
    ["Mensagens", s.messages != null ? s.messages : "—"],
    ["Conversas", s.conversations != null ? s.conversations : "—"],
  ];
  const profiles = s.profiles || (s.per_user && s.per_user[data.user_id] ? s.per_user[data.user_id].profiles : {});
  let last = null;
  for (const p of Object.values(profiles)) {
    if (p.last_ts && (!last || p.last_ts > last)) last = p.last_ts;
  }
  cards.push(["Última atividade", last ? new Date(last * 1000).toLocaleString("pt-BR") : "—"]);
  document.getElementById("stats").innerHTML = cards.map(c =>
    '<div class="card"><div class="k">' + c[0] + '</div><div class="v">' + c[1] + "</div></div>"
  ).join("");
}

async function loadHistory() {
  const resp = await fetch("/history/me?limit=20", { headers: authHeaders() });
  const tbody = document.getElementById("hist");
  if (!resp.ok) { tbody.innerHTML = '<tr><td class="muted">Histórico indisponível (HTTP ' + resp.status + ").</td></tr>"; return; }
  const data = await resp.json();
  const msgs = data.messages || [];
  if (!msgs.length) { tbody.innerHTML = '<tr><td class="muted">Nenhuma mensagem ainda.</td></tr>'; return; }
  tbody.innerHTML = msgs.slice(-20).map(m => {
    const who = m.role === "user" ? "🙋" : '<img src="/site/simbolo_minimo.png" alt="OD" style="width:14px;height:14px;vertical-align:-2px">';
    const when = m.ts ? new Date(m.ts * 1000).toLocaleString("pt-BR") : "";
    const text = String(m.content || "").slice(0, 140);
    return "<tr><td>" + who + " " + escapeHtml(text) +
      '</td><td class="muted" style="white-space:nowrap">' + when + "</td></tr>";
  }).join("");
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

document.getElementById("btn-limpar").onclick = async () => {
  if (!window.confirm("Apagar TODAS as suas conversas?") ) return;
  if (!window.confirm("Confirma de novo? Não dá para desfazer.")) return;
  const resp = await fetch("/history/me", { method: "DELETE", headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  const el = document.getElementById("limpar-msg");
  el.textContent = resp.ok ? ("Removidas: " + (data.removed || 0)) : ("Erro HTTP " + resp.status);
  el.className = "msg " + (resp.ok ? "ok" : "err");
  loadStats(); loadHistory();
};

document.getElementById("btn-trocar-senha").onclick = async () => {
  const msg = document.getElementById("senha-msg");
  const cur = document.getElementById("cur-pass").value;
  const nova = document.getElementById("new-pass").value;
  if (!cur || nova.length < 6) { msg.textContent = "Preencha a atual e a nova (mín. 6)."; msg.className = "msg err"; return; }
  const resp = await fetch("/account/password", {
    method: "POST", headers: authHeaders({"Content-Type": "application/json"}),
    body: JSON.stringify({current_password: cur, new_password: nova})
  });
  const data = await resp.json().catch(() => ({}));
  if (resp.ok && data.ok) {
    msg.textContent = "Senha trocada. Faça login novamente com a nova.";
    msg.className = "msg ok";
    localStorage.removeItem("od_session_token");
    setTimeout(() => { location.href = "/chat"; }, 1500);
  } else {
    msg.textContent = data.error || ("Erro HTTP " + resp.status);
    msg.className = "msg err";
  }
};

document.getElementById("btn-rotacionar").onclick = async () => {
  if (!window.confirm("Rotacionar a API key? A antiga para de valer AGORA.")) return;
  const resp = await fetch("/account/api-key", { method: "POST", headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  const msg = document.getElementById("key-msg");
  if (resp.ok && data.ok) {
    msg.textContent = "Nova chave: " + data.api_key;
    msg.className = "msg ok";
  } else {
    msg.textContent = data.error || ("Erro HTTP " + resp.status);
    msg.className = "msg err";
  }
};

whoAmI().then(u => { if (u) { loadStats(); loadHistory(); } });
</script>
</body>
</html>
"""


_ADMIN_PAGE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OmegaDrakon — Admin</title>
<link rel="icon" href="/site/favicon.png">
<style>
  :root {
    --bg: #06080f; --bg2: #0c1120; --bg3: #111830;
    --text: #e8eaf0; --muted: #7a839a; --border: #1c2440;
    --accent: #f59e0b; --ok: #34d399; --err: #f87171; --warn: #fbbf24;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100dvh;
    -webkit-font-smoothing: antialiased;
  }
  header {
    padding: 12px 20px; background: var(--bg2);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px;
  }
  header a { color: var(--text); text-decoration: none; font-weight: 700; }
  header a:hover { color: var(--accent); }
  header h1 { font-size: 15px; font-weight: 600; margin: 0; color: var(--warn); }
  #badge { margin-left: auto; font-size: 0.85rem; color: var(--muted); }
  #badge b { color: var(--accent); }
  main { max-width: 1080px; margin: 0 auto; padding: 20px; display: grid; gap: 18px; }
  section h2 { font-size: 1rem; margin-bottom: 10px; color: var(--accent); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
  .card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px 16px;
  }
  .card .k { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .card .v { font-size: 1.5rem; font-weight: 700; margin-top: 4px; }
  .card .v.ok { color: var(--ok); }
  .card .v.err { color: var(--err); }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 0.72rem; text-transform: uppercase; }
  td.num, th.num { text-align: right; }
  .muted { color: var(--muted); }
  .msg { font-size: 0.85rem; min-height: 1.2em; margin-top: 8px; }
  .msg.ok { color: var(--ok); }
  .msg.err { color: var(--err); }
  button {
    background: var(--bg3); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 12px; font-size: 0.8rem; cursor: pointer;
  }
  button:hover { border-color: var(--accent); color: var(--accent); }
  button.danger:hover { border-color: var(--err); color: var(--err); }
  input {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 10px; font-size: 0.85rem; width: 180px; max-width: 100%;
  }
  .row { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.72rem; background: var(--bg3); border: 1px solid var(--border); }
  .pill.ok { color: var(--ok); }
  .pill.err { color: var(--err); }
  details summary { cursor: pointer; color: var(--muted); font-size: 0.85rem; margin: 6px 0; }
  pre {
    background: var(--bg2); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px; font-size: 0.75rem; overflow-x: auto; color: var(--muted);
  }
</style>
</head>
<body>
<header>
  <a href="/"><img src="/site/simbolo_minimo.png" alt="OD" style="width:22px;height:22px;vertical-align:-4px"></a><h1>🛡 Admin</h1>
  <div id="badge"></div>
</header>
<main>
  <section>
    <h2>Sistema</h2>
    <div class="grid" id="sys"></div>
    <details><summary>Loops do núcleo (/supervision)</summary><pre id="loops">—</pre></details>
    <details><summary>Métricas do orquestrador (/dashboard/stats)</summary><pre id="metrics">—</pre></details>
    <div class="row" style="margin-top:8px">
      <button id="btn-refresh">↻ Atualizar</button>
      <span class="muted msg" id="sys-msg"></span>
    </div>
  </section>

  <section>
    <h2>Ideias (txt.txt)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Canal do DONO: ideias de melhoria e pedidos de informação que o
      sistema ainda não cobre. Escreva aqui e leia de qualquer lugar
      (site ou app) — é o mesmo arquivo que o orquestrador/leitura do
      sistema consomem.
    </p>
    <textarea id="ideias-texto" placeholder="Ex.: o sistema não sabe o valor do dólar — criar action de cotação..."
      style="width:100%;min-height:110px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:10px;font-size:0.85rem;font-family:inherit"></textarea>
    <div class="row" style="margin-top:8px">
      <button id="ideias-load">↻ Carregar</button>
      <button id="ideias-save" style="border-color:var(--accent);color:var(--accent)">💾 Salvar txt.txt</button>
      <button id="ideias-clear" class="danger">🗑 Zerar</button>
      <span class="muted msg" id="ideias-msg"></span>
    </div>
  </section>

  <section>
    <h2>Canal de desenvolvimento</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      A ideia vem do <b>txt.txt</b> (seção <b>Ideias (txt.txt)</b> — escreva
      lá) e aperte <b>▶ Ativar desenvolvimento</b>. O canal faz três coisas:
      <b>txt.txt vazio → não faz nada</b>; <b>ideia igual a uma sessão já
      concluída → avisa "já implementado" e pergunta se quer limpar o
      txt.txt</b>; <b>ideia nova → a CLI analisa viabilidade, prós, contras
      e alternativas, publica a análise na caixa abaixo e implementa a
      melhor opção</b>, validando com a suíte antes de commitar. Se precisar
      de autorização, pergunta na <b>caixa de desenvolvimento</b> — responda
      ali que a sessão retoma. A fila <code>pedido.txt</code> foi removida
      (2026-10-08): o canal agora é só sob demanda.
    </p>
    <div class="row">
      <button id="sess-ativar" style="border-color:var(--accent);color:var(--accent)">▶ Ativar desenvolvimento</button>
      <button id="sess-parar" class="danger">⏹ Parar</button>
      <select id="sess-cli" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px;font-size:0.85rem">
        <option value="auto">CLI: automática (cascata)</option>
        <option value="freebuff">Freebuff</option>
        <option value="opencode">OpenCode</option>
        <option value="kilo">Kilo</option>
      </select>
      <span class="pill" id="sess-estado">sessão: —</span>
      <span class="muted msg" id="sess-msg"></span>
    </div>
    <pre id="sess-info" style="display:none;max-height:150px;overflow:auto;margin-top:8px">—</pre>
    <div style="margin-top:10px">
      <h3 style="font-size:0.95rem;margin-bottom:6px">Caixa de desenvolvimento (autorizações)</h3>
      <div id="sess-caixa" style="max-height:220px;overflow:auto;border:1px solid var(--border);border-radius:8px;padding:8px;font-size:0.82rem;white-space:pre-wrap;word-break:break-word">— nenhuma mensagem —</div>
      <div class="row" style="margin-top:6px">
        <input id="sess-resposta" placeholder="Resposta/autorização para a sessão..."
          style="flex:1;min-width:200px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px;font-size:0.85rem">
        <button id="sess-enviar">➤ Enviar</button>
        <button id="sess-limpar-caixa" class="danger">🗑 Limpar caixa</button>
      </div>
    </div>
    <details style="margin-top:8px">
      <summary class="muted" style="cursor:pointer;font-size:0.85rem">Log da sessão</summary>
      <pre id="sess-log" style="max-height:220px;overflow:auto;margin-top:6px">—</pre>
    </details>
  </section>

  <section>
    <h2>Limitações (registro automático)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      O que o sistema NÃO soube responder — registrado sozinho:
      fallback honesto esgotado e action degradada (sem rede, fonte
      indisponível). Cada linha é uma candidata a melhoria: resolva,
      teste e limpe.
    </p>
    <div class="row">
      <button id="lim-load">↻ Carregar</button>
      <button id="lim-clear" class="danger">🗑 Limpar registro</button>
      <span class="pill" id="lim-total">total: —</span>
      <span class="muted msg" id="lim-msg"></span>
    </div>
    <pre id="lim-lista" style="display:none;max-height:220px;overflow:auto">—</pre>
  </section>

  <section>
    <h2>Contas</h2>
    <table>
      <thead><tr>
        <th>Usuário</th><th>E-mail</th><th class="num">Msgs</th>
        <th class="num">Sessões</th><th>Criada em</th><th>Ações</th>
      </tr></thead>
      <tbody id="users"></tbody>
    </table>
    <div class="msg" id="users-msg"></div>
  </section>

  <section>
    <h2>Baldes sem conta (legado)</h2>
    <table><tbody id="buckets"></tbody></table>
  </section>

  <section>
    <h2>Registro Mestre (peças)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Cadastro de todas as peças físicas do ecossistema. O público consulta
      pelo ID gravado na peça em <a href="/site/verificacao.html">/site/verificacao.html</a>
      — lá aparecem nome, coleção, status e o <b>username</b> de quem registrou;
      <b>preço e notas nunca saem daqui</b>. Status: estoque → vendida →
      registrada (registrar exige o username de quem comprou — o QR é a
      prova de posse).
    </p>
    <div class="row">
      <input id="reg-nome" placeholder="Nome (ex.: Anel Abissal)" style="width:200px">
      <input id="reg-colecao" placeholder="Coleção (ABISSAL)" style="width:140px">
      <select id="reg-kind" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px;font-size:0.85rem">
        <option value="exclusiva">exclusiva</option>
        <option value="publica">pública</option>
      </select>
      <input id="reg-codigo" placeholder="Cód. gravado (NV-ABI-7F3A)" style="width:180px">
      <input id="reg-preco" type="number" step="0.01" min="0" placeholder="Preço R$" style="width:110px">
      <button id="reg-add" style="border-color:var(--accent);color:var(--accent)">＋ Cadastrar peça</button>
      <button id="reg-refresh">↻ Carregar</button>
      <span class="muted msg" id="reg-msg"></span>
    </div>
    <div class="row" style="margin-top:6px">
      <input id="reg-notas" placeholder="Notas internas (opcional — nunca públicas)"
        style="flex:1;min-width:220px">
    </div>
    <table style="margin-top:10px">
      <thead><tr>
        <th>ID</th><th>Foto</th><th>Nome</th><th>Coleção</th><th>Tipo</th>
        <th>Cód. gravado</th><th>Status</th><th>Dono</th>
        <th class="num">Preço R$</th><th>Ações</th>
      </tr></thead>
      <tbody id="reg-pecas"><tr><td colspan="10" class="muted">Carregando…</td></tr></tbody>
    </table>
    <p class="muted" style="font-size:0.75rem;margin-top:6px">
      📷 envia a foto do produto (reduzida aqui no navegador; o público vê em
      /site/verificacao.html) · 💬 abre a sala de bate-papo da peça — leitura
      pública, escrita com conta, ✕ apaga mensagem (moderação).
    </p>
  </section>
</main>
<script>
let token = localStorage.getItem("od_session_token") || "";
let key = localStorage.getItem("od_api_key") || "";

function authHeaders(extra) {
  const h = extra || {};
  if (token) h["Authorization"] = "Bearer " + token;
  else if (key) h["X-API-Key"] = key;
  return h;
}

async function whoAmI() {
  const resp = await fetch("/auth/me", { headers: authHeaders() });
  if (!resp.ok) { location.href = "/chat"; return null; }
  const data = await resp.json();
  const role = data.role || "user";
  document.getElementById("badge").innerHTML =
    "👤 <b>" + data.user.username + "</b> · " + role + ' · <a href="/chat">💬 Chat</a>';
  if (role !== "admin") {
    document.body.innerHTML = "<main><h2>Acesso restrito ao admin.</h2><p class='muted'>Sua conta não tem papel admin. <a href='/chat'>Voltar ao chat</a></p></main>";
    return null;
  }
  return data;
}

async function loadSystem() {
  const msg = document.getElementById("sys-msg");
  try {
    const [health, sup, stats] = await Promise.all([
      fetch("/health", { headers: authHeaders() }).then(r => r.json()),
      fetch("/supervision", { headers: authHeaders() }).then(r => r.json()),
      fetch("/dashboard/stats", { headers: authHeaders() }).then(r => r.json())
    ]);
    const cards = [
      ["Estado", health.status || (health.ok ? "up" : "?"), health.ok ? "ok" : "err"],
      ["Uptime", fmtUptime(stats.uptime_s != null ? stats.uptime_s : health.uptime_s), ""],
      ["Processadas", stats.processed != null ? stats.processed : "—", ""],
      ["Latência média", stats.avg_latency_ms != null ? stats.avg_latency_ms + " ms" : "—", ""],
      ["Loops", sup.restarts + " restart", sup.ok ? "ok" : "err"],
      ["Cache LLM", stats.cache && stats.cache.entries != null ? stats.cache.entries : "—", ""],
    ];
    document.getElementById("sys").innerHTML = cards.map(c =>
      '<div class="card"><div class="k">' + c[0] + '</div><div class="v ' + c[2] + '">' + c[1] + "</div></div>"
    ).join("");
    document.getElementById("loops").textContent = JSON.stringify(sup, null, 2);
    document.getElementById("metrics").textContent = JSON.stringify(stats, null, 2);
    msg.textContent = "Atualizado " + new Date().toLocaleTimeString("pt-BR");
    msg.className = "muted msg";
  } catch (e) {
    msg.textContent = "Falha ao carregar: " + e.message;
    msg.className = "msg err";
  }
}

function fmtUptime(s) {
  if (s == null) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return (d ? d + "d " : "") + (h ? h + "h " : "") + m + "m";
}

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

async function loadUsers() {
  const resp = await fetch("/admin/users", { headers: authHeaders() });
  const msg = document.getElementById("users-msg");
  if (!resp.ok) { msg.textContent = "Erro HTTP " + resp.status; msg.className = "msg err"; return; }
  const data = await resp.json();
  document.getElementById("users").innerHTML = (data.users || []).map(u => {
    const isOwner = !!u.owner;
    const actions = isOwner
      ? '<span class="pill ok">dono</span>'
      : '<input type="password" class="admin-pass" data-user="' + esc(u.username) + '" placeholder="nova senha" style="width:120px"> ' +
        '<button class="admin-reset" data-user="' + esc(u.username) + '">Reset</button> ' +
        '<button class="danger admin-del" data-user="' + esc(u.username) + '">Remover</button>';
    return "<tr><td><b>" + esc(u.username) + "</b>" + "</td><td class='muted'>" + esc(u.email) + '</td><td class="num">' + (u.messages || 0) +
      '</td><td class="num">' + (u.sessions || 0) + "</td><td class='muted'>" +
      new Date(u.created_at * 1000).toLocaleDateString("pt-BR") + "</td><td>" + actions + "</td></tr>";
  }).join("");
  document.querySelectorAll(".admin-reset").forEach(b =>
    b.addEventListener("click", () => resetPass(b.dataset.user)));
  document.querySelectorAll(".admin-del").forEach(b =>
    b.addEventListener("click", () => delUser(b.dataset.user)));
  document.getElementById("buckets").innerHTML = (data.legacy_buckets || []).length
    ? (data.legacy_buckets || []).map(b =>
        "<tr><td>" + esc(b.user_id) + '</td><td class="num">' + (b.messages || 0) + " msgs</td></tr>"
      ).join("")
    : '<tr><td class="muted">Nenhum balde legado.</td></tr>';
}

async function resetPass(username) {
  const inp = document.getElementById("pass-" + username);
  const nova = (inp && inp.value || "").trim();
  if (nova.length < 6) { alert("Senha nova deve ter pelo menos 6 caracteres."); return; }
  if (!window.confirm("Resetar a senha de '" + username + "'? As sessões da conta caem.")) return;
  const resp = await fetch("/admin/users/" + encodeURIComponent(username) + "/password", {
    method: "POST", headers: authHeaders({"Content-Type": "application/json"}),
    body: JSON.stringify({new_password: nova})
  });
  const data = await resp.json().catch(() => ({}));
  const msg = document.getElementById("users-msg");
  msg.textContent = resp.ok ? ("Senha de " + username + " resetada. Sessões fechadas: " + data.sessions_closed) : (data.error || "Erro HTTP " + resp.status);
  msg.className = "msg " + (resp.ok ? "ok" : "err");
  if (resp.ok) loadUsers();
}

async function delUser(username) {
  if (!window.confirm("REMOVER a conta '" + username + "'? Sessões e vínculo do Telegram caem. O histórico de conversas NÃO é apagado.")) return;
  if (!window.confirm("Confirma de novo? Não dá para desfazer.")) return;
  const resp = await fetch("/admin/users/" + encodeURIComponent(username), { method: "DELETE", headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  const msg = document.getElementById("users-msg");
  msg.textContent = resp.ok ? ("Conta removida: " + username) : (data.error || "Erro HTTP " + resp.status);
  msg.className = "msg " + (resp.ok ? "ok" : "err");
  if (resp.ok) loadUsers();
}

// --- Sessão de desenvolvimento on-demand — canal (2026-10-08) ----------
function sessSetMsg(t, cls) {
  const el = document.getElementById("sess-msg");
  el.textContent = t;
  el.className = "muted msg " + (cls || "");
}
function sessErro(cod) {
  const mapa = {
    sem_ideia: "txt.txt vazio — nada a ativar. Escreva a ideia em Ideias (txt.txt).",
    ja_implementado: "Essa ideia já foi implementada — txt.txt mantido.",
    sessao_ativa: "Já existe uma sessão ativa — pare antes de ativar outra.",
    sessao_nao_ativa: "Nenhuma sessão ativa.",
    cli_invalida: "CLI inválida.",
    acao_invalida: "Ação inválida.",
  };
  return mapa[cod] || cod || "Erro";
}
function sessRender(estado) {
  const rotulo = {
    parada: "PARADA", parado: "PARADA", preparando: "PREPARANDO",
    executando: "EXECUTANDO", aguardando_autorizacao: "AGUARDANDO AUTORIZAÇÃO",
    validando: "VALIDANDO", concluido: "CONCLUÍDA", falhou: "FALHOU",
    interrompida: "INTERROMPIDA",
  };
  const status = estado.status || "parada";
  const pill = document.getElementById("sess-estado");
  pill.textContent = "sessão: " + (rotulo[status] || String(status).toUpperCase()) +
    (estado.pid ? " (pid " + estado.pid + ")" : "");
  pill.className = "pill " + (estado.ativo
    ? (status === "aguardando_autorizacao" ? "err" : "ok")
    : (status === "concluido" ? "ok" : "err"));
  const partes = [];
  if (estado.ideia_preview) partes.push("ideia: " + String(estado.ideia_preview).slice(0, 300));
  if (estado.analise) partes.push("análise:\\n" + String(estado.analise).slice(0, 1500));
  if (estado.cli_usada || estado.rodando) partes.push("CLI: " + (estado.cli_usada || estado.rodando));
  if (estado.rodada) partes.push("rodada: " + estado.rodada + " · autorizações: " + (estado.autorizacoes || 0));
  if (estado.testes) partes.push("testes: " + estado.testes);
  if (estado.diff) partes.push("diff: " + estado.diff);
  if (estado.commit) partes.push("commit: " + estado.commit);
  if (estado.motivo) partes.push("motivo: " + estado.motivo);
  const info = document.getElementById("sess-info");
  info.style.display = partes.length ? "block" : "none";
  info.textContent = partes.join("\\n");
  document.getElementById("sess-log").textContent = estado.log_tail || "—";
}
async function sessaoStatus() {
  try {
    const resp = await fetch("/admin/dev/sessao", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { sessSetMsg(sessErro(data.error) + " (HTTP " + resp.status + ")", "err"); return null; }
    sessRender(data);
    if (data.status === "aguardando_autorizacao" && data.caixa_pendente > 0) {
      sessSetMsg("⚠ A sessão pediu autorização — responda na caixa abaixo.", "err");
    }
    return data;
  } catch (e) { sessSetMsg("Falha ao consultar a sessão: " + e.message, "err"); return null; }
}
function renderCaixa(mensagens) {
  const caixa = document.getElementById("sess-caixa");
  if (!mensagens.length) { caixa.textContent = "— nenhuma mensagem —"; return; }
  caixa.textContent = mensagens.map(m =>
    "[" + m.ts + "] " + (m.de === "dono" ? "VOCÊ" : "SISTEMA") +
    (m.tipo === "pedir_autorizacao" ? (m.respondida ? " (respondida)" : " ⚠ AGUARDANDO") : "") +
    ": " + m.texto
  ).join("\\n\\n");
  caixa.scrollTop = caixa.scrollHeight;
}
async function caixaLoad() {
  try {
    const resp = await fetch("/admin/dev/caixa", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok) renderCaixa(data.mensagens || []);
  } catch (e) { /* o próximo refresh tenta de novo */ }
}
async function sessaoAtivar() {
  try {
    const cli = document.getElementById("sess-cli").value;
    // A ideia vem do txt.txt (canal do dono) — só mostra um trecho no confirm.
    let ideia = "";
    let previewOk = false;
    try {
      const ide = await fetch("/admin/ideias", { headers: authHeaders() });
      const d = await ide.json().catch(() => ({}));
      ideia = String(d.conteudo || "").trim();
      previewOk = ide.ok;
    } catch (e) { /* sem preview, o servidor ainda decide */ }
    // (1) txt.txt vazio → NÃO faz nada: nem diálogo, nem chamada.
    if (previewOk && !ideia) {
      sessSetMsg("txt.txt vazio — nada a ativar. Escreva a ideia em Ideias (txt.txt).");
      return;
    }
    if (!window.confirm("▶ Ativar desenvolvimento com a CLI '" + cli + "'? A sessão lê o txt.txt, iniciar/ e docs/, analisa viabilidade/prós/contras/alternativas e só commita com testes verdes." +
      (ideia ? "\\n\\nIdeia no txt.txt:\\n" + ideia.slice(0, 300) + (ideia.length > 300 ? "…" : "")
             : "\\n\\n⚠ sem prévia do txt.txt — o servidor valida antes de subir."))) return;
    const resp = await fetch("/admin/dev/sessao", {
      method: "POST", headers: authHeaders({"Content-Type":"application/json"}),
      body: JSON.stringify({acao: "ativar", cli: cli})
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      // (2) ideia igual a uma sessão concluída → aviso + oferta de limpeza.
      if (data.error === "ja_implementado") { sessJaImplementado(data); return; }
      sessSetMsg(sessErro(data.error), "err"); return;
    }
    sessSetMsg("▶ Sessão iniciada (pid " + data.pid + ").", "ok");
    sessaoStatus(); caixaLoad();
  } catch (e) { sessSetMsg("Falha ao ativar: " + e.message, "err"); }
}
async function sessJaImplementado(data) {
  const onde = (data.commit ? "commit " + data.commit : "sessão concluída") +
    (data.ts ? " em " + data.ts : "");
  const limpar = window.confirm(
    "✔ Essa ideia já foi implementada (" + onde + ").\\n\\nLimpar o txt.txt agora?" +
    "\\n\\n(Cancelar mantém o texto — para rodar de novo, edite a ideia.)");
  if (!limpar) { sessSetMsg("Ideia já implementada — txt.txt mantido.", "err"); return; }
  const del = await fetch("/admin/ideias", { method: "DELETE", headers: authHeaders() });
  if (del.ok) {
    const campo = document.getElementById("ideias-texto");
    if (campo) campo.value = "";
    sessSetMsg("✔ Ideia já implementada — txt.txt zerado.", "ok");
  } else {
    sessSetMsg("Ideia já implementada, mas não consegui limpar o txt.txt.", "err");
  }
}
async function sessaoParar() {
  if (!window.confirm("⏹ Parar a sessão de desenvolvimento? A CLI em execução é encerrada.")) return;
  try {
    const resp = await fetch("/admin/dev/sessao", {
      method: "POST", headers: authHeaders({"Content-Type":"application/json"}),
      body: JSON.stringify({acao: "parar"})
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { sessSetMsg(sessErro(data.error), "err"); return; }
    sessSetMsg("⏹ Sessão parada.", "ok");
    sessaoStatus();
  } catch (e) { sessSetMsg("Falha ao parar: " + e.message, "err"); }
}
async function caixaEnviar() {
  const campo = document.getElementById("sess-resposta");
  const texto = campo.value.trim();
  if (!texto) { sessSetMsg("Escreva a resposta antes de enviar.", "err"); return; }
  try {
    const resp = await fetch("/admin/dev/caixa", {
      method: "POST", headers: authHeaders({"Content-Type":"application/json"}),
      body: JSON.stringify({texto: texto})
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { sessSetMsg(sessErro(data.error), "err"); return; }
    campo.value = "";
    sessSetMsg("➤ Resposta enviada — a sessão retoma.", "ok");
    caixaLoad();
  } catch (e) { sessSetMsg("Falha ao enviar: " + e.message, "err"); }
}
async function caixaLimpar() {
  if (!window.confirm("🗑 Limpar a caixa de desenvolvimento?")) return;
  try {
    const resp = await fetch("/admin/dev/caixa", { method: "DELETE", headers: authHeaders() });
    if (resp.ok) { caixaLoad(); sessSetMsg("🗑 Caixa limpa.", "ok"); }
  } catch (e) { sessSetMsg("Falha ao limpar: " + e.message, "err"); }
}
document.getElementById("sess-ativar").onclick = sessaoAtivar;
document.getElementById("sess-parar").onclick = sessaoParar;
document.getElementById("sess-enviar").onclick = caixaEnviar;
document.getElementById("sess-limpar-caixa").onclick = caixaLimpar;
document.getElementById("sess-resposta").addEventListener("keydown", e => { if (e.key === "Enter") caixaEnviar(); });

// --- Ideias (txt.txt) — v1.13.0 -------------------------------------
function ideiasSetMsg(t, cls) {
  const el = document.getElementById("ideias-msg");
  el.textContent = t;
  el.className = "muted msg " + (cls || "");
}
async function ideiasLoad() {
  try {
    const resp = await fetch("/admin/ideias", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { ideiasSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    document.getElementById("ideias-texto").value = data.conteudo || "";
    ideiasSetMsg("Carregado (" + (data.bytes || 0) + " bytes).", "ok");
  } catch (e) { ideiasSetMsg("Falha ao carregar: " + e.message, "err"); }
}
async function ideiasSave() {
  try {
    const resp = await fetch("/admin/ideias", {
      method: "PUT", headers: authHeaders(),
      body: JSON.stringify({ conteudo: document.getElementById("ideias-texto").value }),
    });
    const data = await resp.json().catch(() => ({}));
    ideiasSetMsg(resp.ok ? "💾 Salvo (" + (data.bytes || 0) + " bytes)." : (data.error || "Erro HTTP " + resp.status), resp.ok ? "ok" : "err");
  } catch (e) { ideiasSetMsg("Falha ao salvar: " + e.message, "err"); }
}
async function ideiasClear() {
  if (!window.confirm("Zerar o txt.txt? (snapshot manual recomendado)")) return;
  try {
    const resp = await fetch("/admin/ideias", { method: "DELETE", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok) { document.getElementById("ideias-texto").value = ""; ideiasSetMsg("🗑 Zerado.", "ok"); }
    else ideiasSetMsg(data.error || "Erro HTTP " + resp.status, "err");
  } catch (e) { ideiasSetMsg("Falha ao zerar: " + e.message, "err"); }
}
document.getElementById("ideias-load").onclick = ideiasLoad;
document.getElementById("ideias-save").onclick = ideiasSave;
document.getElementById("ideias-clear").onclick = ideiasClear;

// --- Limitações (registro automático) — v1.13.0 -----------------------
function limSetMsg(t, cls) {
  const el = document.getElementById("lim-msg");
  el.textContent = t;
  el.className = "muted msg " + (cls || "");
}
async function limLoad() {
  try {
    const resp = await fetch("/admin/limitacoes", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { limSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    document.getElementById("lim-total").textContent = "total: " + (data.total || 0);
    const pre = document.getElementById("lim-lista");
    pre.style.display = "block";
    pre.textContent = (data.entradas || []).length
      ? (data.entradas || []).map(e => "[" + e.ts + "] " + e.motivo + "\\n  " + e.pergunta).join("\\n\\n")
      : "— nenhuma limitação registrada —";
    limSetMsg("Carregado.", "ok");
  } catch (e) { limSetMsg("Falha ao carregar: " + e.message, "err"); }
}
async function limClear() {
  if (!window.confirm("Limpar o registro de limitações?")) return;
  try {
    const resp = await fetch("/admin/limitacoes", { method: "DELETE", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok) { limSetMsg("🗑 Registro limpo.", "ok"); limLoad(); }
    else limSetMsg(data.error || "Erro HTTP " + resp.status, "err");
  } catch (e) { limSetMsg("Falha ao limpar: " + e.message, "err"); }
}
document.getElementById("lim-load").onclick = limLoad;
document.getElementById("lim-clear").onclick = limClear;

// --- Registro Mestre (peças) — cadastro do dono (item 2, 2026-10-09) ------
function regSetMsg(t, cls) {
  const el = document.getElementById("reg-msg");
  el.textContent = t;
  el.className = "muted msg " + (cls || "");
}

const REG_STATUS = { estoque: "Em estoque", vendida: "Vendida", registrada: "Registrada" };

async function regLoad() {
  try {
    const resp = await fetch("/admin/registry", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    const pecas = data.pecas || [];
    document.getElementById("reg-pecas").innerHTML = pecas.length ? pecas.map(p => {
      let acoes = "";
      if (p.status === "estoque") {
        acoes += '<button class="reg-vender" data-id="' + esc(p.public_id) + '">→ Vender</button> ';
        acoes += '<button class="reg-registrar" data-id="' + esc(p.public_id) + '">🔑 Registrar</button>';
      } else if (p.status === "vendida") {
        acoes = '<button class="reg-registrar" data-id="' + esc(p.public_id) + '">🔑 Registrar</button> ';
        // Desfazer venda (1.24.0): o comprador desistiu antes de concluir —
        // a peça volta para o estoque e some da consulta como "vendida".
        acoes += '<button class="reg-desfazer" data-id="' + esc(p.public_id) + '">↩ Desfazer</button>';
      } else {
        acoes = '<span class="pill ok">com dono</span>';
      }
      acoes += ' <button class="reg-chat-btn" data-id="' + esc(p.public_id) + '">💬</button>';
      acoes += ' <button class="reg-foto-btn" data-id="' + esc(p.public_id) + '">📷</button>';
      acoes += ' <button class="danger reg-del" data-id="' + esc(p.public_id) + '">✕</button>';
      const foto = p.photo
        ? '<img src="' + esc(p.photo) + '" alt="" style="width:34px;height:34px;object-fit:cover;border-radius:6px;border:1px solid var(--border)" loading="lazy">'
        : '<span class="muted">—</span>';
      const linha = "<tr><td><code>" + esc(p.public_id) + "</code></td>" +
        "<td>" + foto + "</td>" +
        "<td><b>" + esc(p.name) + "</b></td>" +
        '<td class="muted">' + esc(p.collection || "—") + "</td>" +
        "<td>" + (p.kind === "publica" ? "pública" : "exclusiva") + "</td>" +
        '<td class="muted">' + esc(p.engraved_code || "—") + "</td>" +
        '<td><span class="pill ' + (p.status === "registrada" ? "ok" : "") + '">' +
          esc(REG_STATUS[p.status] || p.status) + "</span></td>" +
        "<td>" + (p.owner_username ? "<b>@" + esc(p.owner_username) + "</b>" : '<span class="muted">—</span>') + "</td>" +
        '<td class="num">' + (p.price_brl != null ? Number(p.price_brl).toFixed(2) : "—") + "</td>" +
        "<td>" + acoes + "</td></tr>" +
        '<tr class="reg-chat-linha" data-id="' + esc(p.public_id) + '" style="display:none">' +
        '<td colspan="10" style="background:var(--bg2)">' +
        '<div class="muted" style="font-size:0.78rem">Carregando sala…</div></td></tr>';
      return linha;
    }).join("") : '<tr><td colspan="10" class="muted">Nenhuma peça cadastrada ainda.</td></tr>';
    document.querySelectorAll(".reg-vender").forEach(b =>
      b.addEventListener("click", () => regStatus(b.dataset.id, "vendida")));
    document.querySelectorAll(".reg-registrar").forEach(b =>
      b.addEventListener("click", () => regRegistrar(b.dataset.id)));
    document.querySelectorAll(".reg-desfazer").forEach(b =>
      b.addEventListener("click", () => regDesfazer(b.dataset.id)));
    document.querySelectorAll(".reg-del").forEach(b =>
      b.addEventListener("click", () => regDel(b.dataset.id)));
    document.querySelectorAll(".reg-chat-btn").forEach(b =>
      b.addEventListener("click", () => regChatToggle(b)));
    document.querySelectorAll(".reg-foto-btn").forEach(b =>
      b.addEventListener("click", () => regFotoPicker(b.dataset.id)));
    regSetMsg(pecas.length + " peça(s) no Registro Mestre.", "");
  } catch (e) { regSetMsg("Falha ao carregar: " + e.message, "err"); }
}

async function regAdd() {
  const nome = (document.getElementById("reg-nome").value || "").trim();
  if (!nome) { regSetMsg("Dê um nome à peça.", "err"); return; }
  const preco = document.getElementById("reg-preco").value;
  const body = {
    name: nome,
    kind: document.getElementById("reg-kind").value,
    collection: (document.getElementById("reg-colecao").value || "").trim() || null,
    engraved_code: (document.getElementById("reg-codigo").value || "").trim() || null,
    price_brl: preco === "" ? null : Number(preco),
    notes: (document.getElementById("reg-notas").value || "").trim() || null,
  };
  try {
    const resp = await fetch("/admin/registry", {
      method: "POST", headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify(body)
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    ["reg-nome", "reg-colecao", "reg-codigo", "reg-preco", "reg-notas"]
      .forEach(id => document.getElementById(id).value = "");
    regSetMsg("✔ Cadastrada: " + data.peca.public_id, "ok");
    regLoad();
  } catch (e) { regSetMsg("Falha: " + e.message, "err"); }
}

async function regStatus(id, status, owner) {
  const body = { status: status };
  if (owner) body.owner_username = owner;
  try {
    const resp = await fetch("/admin/registry/" + encodeURIComponent(id), {
      method: "PUT", headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify(body)
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    regSetMsg(id + " → " + (REG_STATUS[status] || status), "ok");
    regLoad();
  } catch (e) { regSetMsg("Falha: " + e.message, "err"); }
}

function regRegistrar(id) {
  const username = (window.prompt(
    "Username de quem passa a ser o dono — na consulta pública aparece SÓ o username, nunca o nome real:") || "").trim();
  if (!username) return;
  regStatus(id, "registrada", username);
}

async function regDesfazer(id) {
  // Desfazer venda (1.24.0): o comprador desistiu antes de concluir.
  // A peça volta para o estoque e o carimbo de venda é apagado.
  if (!window.confirm("DESFAZER a venda de " + id + "? A peça volta para o estoque.")) return;
  await regStatus(id, "estoque");
}

async function regDel(id) {
  if (!window.confirm("REMOVER a peça " + id + " do Registro Mestre? Some também da consulta pública.")) return;
  if (!window.confirm("Confirma de novo? Não dá para desfazer.")) return;
  try {
    const resp = await fetch("/admin/registry/" + encodeURIComponent(id), { method: "DELETE", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    regSetMsg("Peça removida: " + id, "ok");
    regLoad();
  } catch (e) { regSetMsg("Falha: " + e.message, "err"); }
}

// --- Foto do produto (1.23.0): reduz no navegador e envia ------------------
function regFotoPicker(id) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "image/*";
  inp.onchange = () => { if (inp.files && inp.files[0]) regFotoEnviar(id, inp.files[0]); };
  inp.click();
}

async function regFotoEnviar(id, file) {
  regSetMsg("Reduzindo e enviando a foto de " + id + "…", "");
  try {
    const dataUrl = await regReduzirImagem(file, 900, 0.82);
    const b64 = dataUrl.split(",")[1];
    const mime = dataUrl.slice(5, dataUrl.indexOf(";"));
    const resp = await fetch("/admin/registry/" + encodeURIComponent(id) + "/photo", {
      method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ image_b64: b64, mime: mime })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    regSetMsg("✔ Foto de " + id + " no ar — aparece na verificação pública.", "ok");
    regLoad();
  } catch (e) { regSetMsg("Falha na foto: " + e.message, "err"); }
}

function regReduzirImagem(file, maxLado, qualidade) {
  // Reduz no navegador (canvas → JPEG) antes de enviar: foto de celular
  // vira ~100-200 KB em vez de 5 MB — e o servidor fica burro de propósito.
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const escala = Math.min(1, maxLado / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(img.width * escala));
      c.height = Math.max(1, Math.round(img.height * escala));
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", qualidade));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("não consegui ler a imagem")); };
    img.src = url;
  });
}

// --- Sala de bate-papo da peça (1.23.0): leitura + moderação ----------------
async function regChatToggle(botao) {
  const id = botao.dataset.id;
  const linha = document.querySelector('.reg-chat-linha[data-id="' + CSS.escape(id) + '"]');
  if (!linha) return;
  const aberta = linha.style.display !== "none";
  document.querySelectorAll(".reg-chat-linha").forEach(l => { l.style.display = "none"; });
  if (aberta) return;
  linha.style.display = "";
  linha.firstElementChild.innerHTML = '<div class="muted" style="font-size:0.78rem">Carregando sala…</div>';
  try {
    const resp = await fetch("/registry/" + encodeURIComponent(id) + "/chat");
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { linha.firstElementChild.innerHTML = '<span class="msg err">Erro ' + resp.status + '</span>'; return; }
    const msgs = data.mensagens || [];
    if (!msgs.length) {
      linha.firstElementChild.innerHTML = '<span class="muted" style="font-size:0.78rem">Sala vazia — ninguém falou ainda.</span>';
      return;
    }
    linha.firstElementChild.innerHTML =
      '<div class="muted" style="font-size:0.75rem;margin-bottom:6px">Sala de ' + esc(id) +
      ' — leitura pública · ✕ apaga mensagem (moderação)</div>' +
      msgs.map(m =>
        '<div style="display:flex;gap:10px;align-items:baseline;padding:3px 0;font-size:0.82rem">' +
        '<b style="color:var(--accent)">@' + esc(m.username) + '</b>' +
        '<span style="flex:1">' + esc(m.text) + '</span>' +
        '<span class="muted" style="font-size:0.7rem">' +
          new Date(m.created_at * 1000).toLocaleString("pt-BR") + '</span>' +
        '<button class="danger reg-chat-del" data-id="' + esc(id) + '" data-mid="' + m.id + '">✕</button>' +
        '</div>'
      ).join("");
    linha.querySelectorAll(".reg-chat-del").forEach(b =>
      b.addEventListener("click", () => regChatApagar(b.dataset.id, b.dataset.mid)));
  } catch (e) {
    linha.firstElementChild.innerHTML = '<span class="msg err">Falha: ' + esc(e.message) + '</span>';
  }
}

async function regChatApagar(id, mid) {
  if (!window.confirm("Apagar a mensagem #" + mid + " da sala de " + id + "?")) return;
  try {
    const resp = await fetch("/admin/registry/" + encodeURIComponent(id) + "/chat/" + mid,
      { method: "DELETE", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    regSetMsg("Mensagem #" + mid + " apagada.", "ok");
    const botao = document.querySelector('.reg-chat-btn[data-id="' + CSS.escape(id) + '"]');
    if (botao) {
      const linha = document.querySelector('.reg-chat-linha[data-id="' + CSS.escape(id) + '"]');
      linha.style.display = "none";
      regChatToggle(botao);
    }
  } catch (e) { regSetMsg("Falha: " + e.message, "err"); }
}

const carregarTudo = () => { loadSystem(); loadUsers(); sessaoStatus(); caixaLoad(); ideiasLoad(); limLoad(); regLoad(); };
document.getElementById("btn-refresh").onclick = carregarTudo;
document.getElementById("reg-add").onclick = regAdd;
document.getElementById("reg-refresh").onclick = regLoad;
document.getElementById("reg-nome").addEventListener("keydown", e => { if (e.key === "Enter") regAdd(); });
whoAmI().then(u => { if (u) carregarTudo(); });
// a sessão roda fora do od-core: o painel acompanha de 5 em 5 s
setInterval(async () => {
  const estado = await sessaoStatus();
  if (estado && estado.ativo) caixaLoad();
}, 5000);
</script>
</body>
</html>
"""


_CHAT_PAGE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OmegaDrakon — Chat</title>
<link rel="icon" href="/site/favicon.png">
<style>
  :root {
    --bg: #06080f; --bg2: #0c1120; --bg3: #111830;
    --text: #e8eaf0; --muted: #7a839a; --border: #1c2440;
    --accent: #f59e0b; --accent-glow: rgba(245,158,11,0.2);
    --user-bg: #1a3a7a; --od-bg: #111830;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--text);
    display: flex; flex-direction: column; height: 100dvh;
    -webkit-font-smoothing: antialiased;
  }
  /* --- Header --- */
  header {
    padding: 12px 20px; background: var(--bg2);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }
  .h-brand { display: flex; align-items: center; gap: 8px; }
  .h-brand a { color: var(--text); text-decoration: none; font-weight: 700; font-size: 1rem; display: flex; align-items: center; gap: 6px; }
  .h-brand a:hover { color: var(--accent); }
  .h-sep { color: var(--border); font-size: 1.2rem; }
  header h1 { font-size: 15px; font-weight: 600; margin: 0; color: var(--text); }
  .h-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  #profile {
    padding: 5px 10px; border-radius: 8px; font-size: 0.8rem;
    border: 1px solid var(--border); background: var(--bg); color: var(--text);
  }
  .transport-badge {
    font-size: 0.7rem; padding: 3px 8px; border-radius: 6px;
    font-weight: 600; display: none;
  }
  .transport-badge.active { display: inline-block; }
  .transport-badge.ws { background: rgba(34,197,94,0.15); color: #22c55e; }
  .transport-badge.rest { background: rgba(245,158,11,0.15); color: var(--accent); }
  #btn-logout {
    padding: 5px 12px; border-radius: 8px; font-size: 0.78rem; font-weight: 600;
    border: 1px solid var(--border); background: var(--bg); color: var(--muted);
    cursor: pointer; display: none;
  }
  #btn-logout.active { display: inline-block; }
  #btn-logout:hover { color: #f85149; border-color: #f85149; }
  #hist-note {
    display: none; margin: 10px auto 0; width: fit-content; max-width: 90%;
    font-size: 0.78rem; color: var(--muted); background: var(--bg2);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px;
  }
  #hist-note.active { display: block; }
  /* --- Messages --- */
  #messages {
    flex: 1; overflow-y: auto; padding: 20px;
    display: flex; flex-direction: column; gap: 12px;
  }
  .bubble {
    max-width: 75%; padding: 12px 16px; border-radius: 14px;
    white-space: pre-wrap; word-wrap: break-word; line-height: 1.5;
    font-size: 0.92rem; animation: fadeIn 0.15s ease;
  }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } }
  .user { align-self: flex-end; background: var(--user-bg); border-bottom-right-radius: 4px; }
  .od { align-self: flex-start; background: var(--od-bg); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
  .meta { font-size: 0.7rem; color: var(--muted); margin-top: 6px; }
  .typing { align-self: flex-start; padding: 12px 16px; font-size: 0.85rem; color: var(--muted); }
  .typing::after { content: '...'; animation: dots 1.2s infinite; }
  @keyframes dots { 0%,20% { content: '.'; } 40% { content: '..'; } 60%,100% { content: '...'; } }
  /* Histórico carregado: agrupamento por dia + hora discreta na bolha. */
  .day-sep {
    align-self: center; margin: 8px 0 2px; padding: 3px 12px;
    font-size: 0.68rem; font-weight: 600; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--muted);
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 999px;
  }
  .bubble .hist-time {
    display: block; margin-top: 4px; font-size: 0.64rem;
    color: var(--muted); opacity: 0.85; text-align: right;
  }
  .bubble.od .hist-time { text-align: left; }
  #hist-top {
    align-self: center; margin: 0 0 10px; padding: 6px 14px;
    font-size: 0.75rem; font-weight: 600; cursor: pointer;
    border: 1px solid var(--border); background: var(--bg2);
    color: var(--accent); border-radius: 999px; display: none;
  }
  #hist-top.active { display: inline-block; }
  #hist-top:disabled { opacity: 0.5; cursor: wait; }
  /* --- Composer --- */
  #composer {
    display: flex; gap: 10px; padding: 14px 20px; background: var(--bg2);
    border-top: 1px solid var(--border); align-items: center;
  }
  #text {
    flex: 1; padding: 10px 14px; border-radius: 10px; font-size: 0.92rem;
    border: 1px solid var(--border); background: var(--bg); color: var(--text);
    outline: none; transition: border-color 0.2s;
  }
  #text:focus { border-color: var(--accent); }
  #send {
    padding: 10px 20px; border-radius: 10px; font-size: 0.9rem; font-weight: 600;
    border: none; background: var(--accent); color: #000; cursor: pointer;
    transition: all 0.2s; white-space: nowrap;
  }
  #send:hover { box-shadow: 0 0 20px var(--accent-glow); }
  #send:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
  /* --- Voz (v1.17.3): microfone no composer --- */
  #mic {
    padding: 10px 12px; border-radius: 10px; font-size: 0.95rem; line-height: 1;
    border: 1px solid var(--border); background: var(--bg); color: var(--text);
    cursor: pointer; transition: all 0.2s; white-space: nowrap;
  }
  #mic:hover { border-color: var(--accent); }
  #mic.rec {
    background: #f85149; border-color: #f85149; color: #fff;
    animation: mic-pulse 1.2s infinite;
  }
  @keyframes mic-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.55; }
  }
  #mic:disabled { opacity: 0.4; cursor: not-allowed; }
  #speaker { background: none; border: none; cursor: pointer;
    font-size: 0.95rem; color: var(--muted); padding: 4px; }
  #speaker.on { color: var(--accent); }
  /* --- Gate --- */
  #gate {
    display: flex; flex-direction: column; gap: 16px; margin: auto;
    width: min(420px, 90vw); padding: 2rem; background: var(--bg2);
    border-radius: 16px; border: 1px solid var(--border);
  }
  #gate h2 { margin: 0; font-size: 1.3rem; }
  #gate p { color: var(--muted); margin: 0; font-size: 0.88rem; line-height: 1.5; }
  #gate input {
    padding: 10px 14px; border-radius: 10px; font-size: 0.92rem;
    border: 1px solid var(--border); background: var(--bg); color: var(--text);
  }
  #gate button {
    padding: 10px; border-radius: 10px; font-size: 0.95rem; font-weight: 600;
    border: none; background: var(--accent); color: #000; cursor: pointer;
  }
  #gate button:hover { box-shadow: 0 0 20px var(--accent-glow); }
  #err, #err2, #err3 { color: #f85149; font-size: 0.82rem; min-height: 18px; }
  .hidden { display: none !important; }
  .gate-switch { font-size: 0.82rem; color: var(--muted); margin-top: 0.5rem; }
  .gate-switch a { color: var(--accent); text-decoration: none; }
  .gate-switch a:hover { text-decoration: underline; }
  /* --- Layout fixo: header e composer sempre visíveis --- */
  #gate { flex: 1; min-height: 0; overflow-y: auto; }
  #chat {
    flex: 1; min-height: 0; display: flex; flex-direction: column;
  }
  #chat.hidden { display: none; }
  /* Menu da conta: clicar no nome abre Limpar/Sair. */
  #user-menu { position: relative; display: none; }
  #user-menu.active { display: inline-block; }
  #user-badge {
    font-size: 0.78rem; font-weight: 600; color: var(--text);
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: 8px; padding: 5px 10px; cursor: pointer;
  }
  #user-badge::before { content: "👤 "; }
  #user-badge::after { content: " ▾"; font-size: 0.65rem; color: var(--muted); }
  #user-dropdown {
    position: absolute; right: 0; top: calc(100% + 6px); min-width: 200px;
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 10px; padding: 6px; display: none; z-index: 50;
    box-shadow: 0 8px 24px rgba(0,0,0,0.45);
  }
  #user-dropdown.active { display: block; }
  #user-dropdown .menu-hint {
    font-size: 0.66rem; color: var(--muted); padding: 2px 10px 6px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
  #user-dropdown button {
    display: flex; width: 100%; gap: 8px; align-items: center;
    padding: 8px 10px; border-radius: 8px; font-size: 0.82rem;
    font-weight: 600; border: none; background: transparent;
    color: var(--text); cursor: pointer; text-align: left;
  }
  #user-dropdown button:hover { background: var(--bg3); }
  #btn-painel {
    display: flex; width: 100%; gap: 8px; align-items: center;
    padding: 8px 10px; border-radius: 8px; font-size: 0.82rem;
    font-weight: 600; color: var(--text); text-decoration: none;
  }
  #btn-painel:hover { background: var(--bg3); color: var(--accent); }
  #btn-limpar:hover { color: var(--accent); }
  #btn-logout:hover { color: #f85149; }
  /* --- Welcome --- */
  .welcome { text-align: center; margin: auto; color: var(--muted); }
  .welcome .icon { font-size: 3rem; margin-bottom: 0.5rem; }
  .welcome h2 { color: var(--text); font-size: 1.2rem; margin-bottom: 0.3rem; }
  .welcome p { font-size: 0.85rem; }
</style>
</head>
<body>

<header>
  <div class="h-brand">
    <a href="/site"><img src="/site/simbolo_minimo.png" alt="OD" style="width:18px;height:18px;vertical-align:-3px"> OD</a>
    <span class="h-sep">|</span>
    <h1>Chat</h1>
  </div>
  <div class="h-right">
    <span id="transport" class="transport-badge"></span>
    <select id="profile" title="Perfil">
      <option value="auto">🤖 Auto</option>
      <option value="guardian">Nicky Virthy</option>
      <option value="regulus">⚖️ Regulus</option>
      <option value="luma">🌟 Luma</option>
      <option value="vox">📜 Vox</option>
      <option value="athenae">🏛️ Athenae</option>
      <option value="nyx">🌙 Nyx</option>
      <option value="nexus">🔗 Nexus</option>
    </select>
    <span id="user-menu">
      <button id="user-badge" title="Opções da conta"></button>
      <div id="user-dropdown">
        <div class="menu-hint">Conta</div>
        <a id="btn-painel" href="/dashboard" title="Meu painel: uso, histórico e conta">📊 Meu painel</a>
        <button id="btn-limpar" title="Apaga TODA a conversa salva desta conta">🧹 Limpar conversa</button>
        <button id="btn-logout" title="Encerra a sessão neste navegador e no servidor">🚪 Sair</button>
      </div>
    </span>
  </div>
</header>

<div id="gate">
  <div id="gate-login">
    <h2><img src="/site/simbolo_minimo.png" alt="" style="width:26px;height:26px;vertical-align:-5px"> Entrar no Chat</h2>
    <p>Faça login para conversar com o OmegaDrakon.</p>
    <input id="login-user" type="text" placeholder="Username" autocomplete="username">
    <input id="login-pass" type="password" placeholder="Senha" autocomplete="current-password">
    <div id="err"></div>
    <button id="enter">Entrar</button>
    <p class="gate-switch">Não tem conta? <a href="#" id="show-register">Registrar</a></p>
    <p class="gate-switch" style="font-size:0.75rem;color:var(--muted);">Ou use sua API key: <a href="#" id="show-apikey">Modo avançado</a></p>
    <p class="gate-switch" style="font-size:0.75rem;color:var(--muted);">Só conversar? <a href="#" id="anon">Entrar como anônimo</a> — sem histórico salvo, sem comandos</p>
  </div>
  <div id="gate-register" class="hidden">
    <h2>📝 Criar Conta</h2>
    <p>Registre-se para começar a conversar.</p>
    <input id="reg-user" type="text" placeholder="Username (mín. 3 caracteres)" autocomplete="username">
    <input id="reg-email" type="email" placeholder="Email" autocomplete="email">
    <input id="reg-pass" type="password" placeholder="Senha (mín. 6 caracteres)" autocomplete="new-password">
    <div id="err2"></div>
    <button id="register">Criar conta</button>
    <p class="gate-switch">Já tem conta? <a href="#" id="show-login">Fazer login</a></p>
  </div>
  <div id="gate-apikey" class="hidden">
    <h2>🔑 API Key</h2>
    <p>Use sua API key para acessar diretamente.</p>
    <input id="key" type="password" placeholder="Sua OD_API_KEY" autocomplete="off">
    <div id="err3"></div>
    <button id="enter-key">Entrar</button>
    <p class="gate-switch"><a href="#" id="show-login2">← Voltar ao login</a></p>
  </div>
</div>  <div id="chat" class="hidden">
  <div id="messages">
    <button id="hist-top">↑ Carregar conversas anteriores</button>
    <div class="welcome">
      <div class="icon"><img src="/site/logo.png" alt="Omega Drakon" style="width:72px;height:72px"></div>
      <h2>OmegaDrakon</h2>
      <p>Envie uma mensagem para começar a conversar.</p>
    </div>
  </div>
  <div id="hist-note"></div>
  <div id="composer">
    <button id="mic" title="Falar com o OmegaDrakon">🎤</button>
    <input id="text" placeholder="Digite sua mensagem…" autocomplete="off">
    <button id="speaker" title="Resposta por voz (liga/desliga)" aria-pressed="false">🔇</button>
    <button id="send">Enviar</button>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
const gate = $("gate"), chat = $("chat");
let token = localStorage.getItem("od_session_token") || "";
let key = localStorage.getItem("od_api_key") || "";
let busy = false;
let ws = null;
let wsReady = false;
// Identidade enviada ao servidor. Com sessão, o servidor usa o usuário
// autenticado de qualquer forma; este valor só importa no modo API key (WS).
let user_id = "web";
// Modo anônimo: quem só quer conversar. O contexto fica AQUI no navegador
// (o servidor não grava nada) e nenhum comando/action é autorizado.
let anonMode = false;
let anonHistory = [];
// Paginação do histórico: cursor = id da mensagem mais antiga já carregada.
let histOldestId = null;
let histHasMore = false;
let histLoading = false;
const WS_PORT = 8001;

// --- Gate switching ---
function showGateView(view) {
  $("gate-login").classList.toggle("hidden", view !== "login");
  $("gate-register").classList.toggle("hidden", view !== "register");
  $("gate-apikey").classList.toggle("hidden", view !== "apikey");
  ["err","err2","err3"].forEach(id => $(id).textContent = "");
}
$("show-register").onclick = (e) => { e.preventDefault(); showGateView("register"); };
$("show-login").onclick = (e) => { e.preventDefault(); showGateView("login"); };
$("show-login2").onclick = (e) => { e.preventDefault(); showGateView("login"); };
$("show-apikey").onclick = (e) => { e.preventDefault(); showGateView("apikey"); };
$("anon").onclick = (e) => {
  e.preventDefault();
  anonMode = true; anonHistory = [];
  showChat();
  const el = $("transport"); el.className = "transport-badge active";
  el.textContent = "🕶 anônimo";
};

function showGate(msg, errId) {
  if (msg) $(errId || "err").textContent = msg;
  gate.classList.remove("hidden");
  chat.classList.add("hidden");
}
function setUserBadge(name) {
  const menu = $("user-menu");
  $("user-badge").textContent = name;
  menu.classList.toggle("active", !!name);
  closeUserMenu();
}
function closeUserMenu() { $("user-dropdown").classList.remove("active"); }
$("user-badge").addEventListener("click", (e) => {
  e.stopPropagation();
  $("user-dropdown").classList.toggle("active");
});
document.addEventListener("click", (e) => {
  if (!$("user-dropdown").contains(e.target)) closeUserMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeUserMenu();
});
function showChat() {
  gate.classList.add("hidden");
  chat.classList.remove("hidden");
  $("text").focus();
  if (!anonMode) {
    setUserBadge(user_id);
    tryConnectWs();  // o anônimo não tem credencial para o WS
    loadHistory();
  } else {
    setUserBadge("");  // anônimo não expõe nome (não há)
  }
}
function histNote(msg) {
  const el = $("hist-note");
  if (msg) { el.textContent = msg; el.classList.add("active"); }
  else { el.textContent = ""; el.classList.remove("active"); }
}
function histAuthHeaders() {
  return token ? {"Authorization": "Bearer " + token} : (key ? {"X-API-Key": key} : {});
}
function setHistTop(visible, loading) {
  const btn = $("hist-top");
  if (!btn) return;  // resetMessages preserva o botão; guarda defensiva
  btn.classList.toggle("active", !!visible);
  btn.disabled = !!loading;
  btn.textContent = loading ? "Carregando…" : "↑ Carregar conversas anteriores";
}
async function loadOlder() {
  // Página ANTERIOR via cursor: mensagens mais antigas que a 1ª já na tela.
  if (!histHasMore || histLoading || histOldestId == null) return;
  histLoading = true;
  setHistTop(true, true);
  try {
    const prof = $("profile").value;
    // "me": a identidade vem da CREDENCIAL no servidor — nunca do estado do
    // navegador. Na troca de usuário ou no 1º acesso, um user_id defasado
    // aqui buscaria o balde errado (ou 403) e o histórico "não atualizaria".
    const url = "/history/me?limit=50&profile=" + prof + "&before=" + histOldestId;
    const res = await fetch(url, { headers: histAuthHeaders() });
    if (!res.ok) { setHistTop(histHasMore, false); return; }
    const data = await res.json();
    const msgs = data.messages || [];
    if (msgs.length > 0) {
      // Preserva a posição: âncora é o 1º elemento visível antes do prepend.
      const box = $("messages");
      const anchor = box.firstChild;
      const antesTop = anchor ? anchor.offsetTop : 0;
      let diaCorrente = dayLabel(new Date(msgs[msgs.length - 1].ts * 1000));
      // O separador do dia da página atual pode já existir: msgs da página
      // anterior mais antigas que ele entram ANTES, então removemos e
      // re-agrupamos só o início da janela.
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        const dia = m.ts ? dayLabel(new Date(m.ts * 1000)) : "";
        if (dia && dia !== diaCorrente) {
          addDaySeparatorBefore(anchor, new Date(m.ts * 1000));
          diaCorrente = dia;
        }
        prependHistoryBubble(m, anchor);
      }
      // Mantém o usuário na mesma mensagem (sem "pulo").
      if (anchor) box.scrollTop += anchor.offsetTop - antesTop;
    }
    histHasMore = !!data.has_more;
    if (data.oldest_id != null) histOldestId = data.oldest_id;
    setHistTop(histHasMore, false);
    if (!histHasMore) {
      const fim = document.createElement("div");
      fim.className = "day-sep";
      fim.textContent = "Início da conversa";
      $("messages").insertBefore(fim, $("messages").firstChild);
    }
  } catch(e) {
    setHistTop(histHasMore, false);
  } finally {
    histLoading = false;
  }
}
function addDaySeparatorBefore(anchor, d) {
  const sep = document.createElement("div");
  sep.className = "day-sep";
  sep.textContent = dayLabel(d);
  $("messages").insertBefore(sep, anchor);
}
function prependHistoryBubble(m, anchor) {
  // Reaproveita addHistoryBubble com insertBefore: constrói fora e move.
  const div = addHistoryBubble(m);
  $("messages").insertBefore(div, anchor);
}
async function loadHistory() {
  histNote("");
  histOldestId = null;
  histHasMore = false;
  setHistTop(false, false);
  try {
    const prof = $("profile").value;
    // "me" (igual ao loadOlder): servidor resolve quem é pela credencial.
    const res = await fetch("/history/me?limit=50&profile=" + prof, {
      headers: histAuthHeaders()
    });
    if (res.ok) {
      const data = await res.json();
      // O servidor é a fonte da verdade da identidade: se o navegador achava
      // que era outro usuário, o badge corrige na hora.
      if (data.user_id) setUserBadge(data.user_id);
      if (data.messages && data.messages.length > 0) {
        clearWelcome();
        let diaCorrente = "";
        data.messages.forEach(m => {
          // Agrupa por dia: separador quando a data muda de uma msg para outra.
          const dia = m.ts ? dayLabel(new Date(m.ts * 1000)) : "";
          if (dia && dia !== diaCorrente) {
            addDaySeparator(new Date(m.ts * 1000));
            diaCorrente = dia;
          }
          addHistoryBubble(m);
        });
        scrollToLatest();  // abre na conversa mais recente, não no topo
        // Cursor da paginação: 1ª mensagem carregada (a mais antiga na tela).
        const first = data.messages[0];
        histHasMore = !!data.has_more;
        histOldestId = data.oldest_id != null ? data.oldest_id : null;
        setHistTop(histHasMore, false);
      } else {
        histNote("Nenhuma conversa anterior nesta conta.");
      }
      return;
    }
    histNote("Histórico indisponível agora (HTTP " + res.status + ") — a conversa nova funciona normalmente.");
  } catch(e) {
    histNote("Histórico indisponível agora (falha de rede) — a conversa nova funciona normalmente.");
  }
}
// Rolar até o topo dispara a página anterior (com folga para não piscar).
$("messages").addEventListener("scroll", () => {
  if (!histHasMore || histLoading) return;
  const box = $("messages");
  if (box.scrollTop <= 60) loadOlder();
});
$("hist-top").addEventListener("click", loadOlder);
// --- Limpar conversa (menu da conta) ---
$("btn-limpar").onclick = async () => {
  closeUserMenu();
  if (anonMode) { histNote("Anônimo não tem conversa salva para limpar."); return; }
  // Dupla confirmação: apaga TODA a conversa da conta no servidor.
  if (!window.confirm("Apagar TODA a conversa salva desta conta? Essa ação não tem volta.")) return;
  if (!window.confirm("Confirma de novo? As mensagens não voltam.")) return;
  try {
    const res = await fetch("/history/me", {
      method: "DELETE",
      headers: histAuthHeaders()
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) {
      histOldestId = null; histHasMore = false;
      resetMessages('<div class="welcome"><div class="icon"><img src="/site/logo.png" alt="Omega Drakon" style="width:72px;height:72px"></div><h2>OmegaDrakon</h2><p>Conversa limpa. Envie uma mensagem para começar de novo.</p></div>');
      histNote("Conversa apagada (" + (data.removed ?? 0) + " mensagens). A IA começa sem memória desta conta.");
    } else {
      histNote("Não deu para limpar agora (HTTP " + res.status + (") — tente novamente."));
    }
  } catch(e) {
    histNote("Não deu para limpar agora (falha de rede) — tente novamente.");
  }
};
// --- Logout (menu da conta) ---
$("btn-logout").onclick = async () => {
  closeUserMenu();
  // O token morre no SERVIDOR (POST /auth/logout) e no navegador; a API key
  // do modo avançado sai só daqui (não há como revogá-la por request).
  try {
    if (token) {
      await fetch("/auth/logout", {
        method: "POST",
        headers: {"Authorization": "Bearer " + token}
      });
    }
  } catch(e) {}
  token = ""; localStorage.removeItem("od_session_token");
  key = ""; localStorage.removeItem("od_api_key");
  anonMode = false; anonHistory = [];
  setUserBadge("");
  if (ws) { try { ws.close(); } catch(e) {} ws = null; wsReady = false; }
  setTransport("");
  const el = $("transport"); el.className = "transport-badge"; el.textContent = "";
  user_id = "web";
  histOldestId = null; histHasMore = false;
  resetMessages('<div class="welcome"><div class="icon"><img src="/site/logo.png" alt="Omega Drakon" style="width:72px;height:72px"></div><h2>OmegaDrakon</h2><p>Envie uma mensagem para começar a conversar.</p></div>');
  showGate("");
};
function setTransport(type) {
  const el = $("transport");
  el.className = "transport-badge active " + type;
  el.textContent = type === "ws" ? "⚡ Streaming" : "↔ REST";
}
function clearWelcome() {
  const w = $("messages").querySelector(".welcome");
  if (w) w.remove();
}
function resetMessages(welcomeHTML) {
  // Zera a lista de mensagens PRESERVANDO o #hist-top: ele é elemento
  // PERMANENTE da lista (paginação). Substituir o innerHTML inteiro o
  // destruiria — e o próximo loadHistory quebraria em setHistTop (botão
  // null) ANTES do fetch do histórico: mensagens só apareciam depois de
  // atualizar a página (F5 recria o botão). Causa do bug de 2026-09-25.
  const box = $("messages");
  const hist = $("hist-top");
  box.innerHTML = "";
  if (hist) box.appendChild(hist);
  box.insertAdjacentHTML("beforeend", welcomeHTML);
  setHistTop(false, false);
}
// Rótulo do agrupamento por dia do histórico (dias recentes por nome).
function dayLabel(d) {
  const hoje = new Date(); hoje.setHours(0,0,0,0);
  const dia = new Date(d); dia.setHours(0,0,0,0);
  const dias = Math.round((hoje - dia) / 86400000);
  if (dias === 0) return "Hoje";
  if (dias === 1) return "Ontem";
  return dia.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}
function addDaySeparator(d) {
  const sep = document.createElement("div");
  sep.className = "day-sep";
  sep.textContent = dayLabel(d);
  $("messages").appendChild(sep);
}
function addHistoryBubble(m) {
  const d = m.ts ? new Date(m.ts * 1000) : null;
  const hora = d
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : "";
  const meta = m.role === "user"
    ? null
    : (m.llm_used ? (m.llm_used + (hora ? " · " + hora : "")) : (hora || null));
  const div = addBubble(m.role === "user" ? "user" : "od", m.content, meta, { noScroll: true });
  if (hora) {
    const t = document.createElement("span");
    t.className = "hist-time";
    t.textContent = hora;
    div.appendChild(t);
  }
  return div;
}
// Leva a conversa para a mensagem mais recente. O duplo rAF garante que a
// rolagem acontece DEPOIS da pintura do último elemento — sem isso o
// scrollHeight ainda é o antigo e a lista abre no meio.
function scrollToLatest() {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $("messages").scrollTop = $("messages").scrollHeight;
  }));
}
function addBubble(who, text, meta, opts) {
  clearWelcome();
  const div = document.createElement("div");
  div.className = "bubble " + who;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  $("messages").appendChild(div);
  // Durante a montagem do histórico o scroll é feito uma única vez no final
  // (scrollToLatest, pós-pintura) — rolar bolha a bolha para no meio.
  if (!(opts && opts.noScroll)) {
    $("messages").scrollTop = $("messages").scrollHeight;
  }
  return div;
}
let typingEl = null;
function showTyping() {
  clearWelcome();
  typingEl = document.createElement("div");
  typingEl.className = "typing";
  typingEl.textContent = "Digitando";
  $("messages").appendChild(typingEl);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function removeTyping() {
  if (typingEl) { typingEl.remove(); typingEl = null; }
}

// --- WebSocket ---
function tryConnectWs() {
  if (ws && ws.readyState <= 1) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const host = location.hostname;
  const url = proto + "://" + host + ":" + WS_PORT;
  try {
    ws = new WebSocket(url);
    ws.onopen = () => {
      // O token da sessão TEM que ir no frame auth: sem ele o servidor nega
      // (api_key_invalida → close 4001) e o streaming nunca conecta para quem
      // entrou por login/senha. A API key entra quando é o modo avançado.
      ws.send(JSON.stringify({ type: "auth", token: token || "", api_key: key || "", user_id: user_id }));
    };
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data);
        if (frame.type === "authenticated") { wsReady = true; }
        if (frame.type === "error") { wsReady = false; ws.close(); }
      } catch(e) {}
    };
    ws.onerror = () => { wsReady = false; };
    ws.onclose = () => { wsReady = false; ws = null; };
  } catch(e) { wsReady = false; }
}

function sendWs(text, profile) {
  return new Promise((resolve, reject) => {
    if (!wsReady || !ws || ws.readyState !== 1) return reject("no ws");
    removeTyping();
    showTyping();
    let buffer = "";
    let gotToken = false;
    let bubble = null;
    const timeout = setTimeout(() => { ws.onmessage = null; reject("timeout"); }, 240000);
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data);
        if (frame.type === "token" && frame.content) {
          if (!gotToken) { removeTyping(); gotToken = true; bubble = addBubble("od", ""); }
          buffer += frame.content;
          bubble.textContent = buffer;
          $("messages").scrollTop = $("messages").scrollHeight;
        }
        if (frame.type === "done") {
          clearTimeout(timeout);
          ws.onmessage = null;
          removeTyping();
          if (bubble && frame.route) {
            const m = document.createElement("div");
            m.className = "meta";
            m.textContent = "WebSocket · " + (frame.route || "") + (frame.latency_ms ? " · " + (frame.latency_ms/1000).toFixed(1) + "s" : "");
            bubble.appendChild(m);
          }
          setTransport("ws");
          resolve(buffer);
        }
        if (frame.type === "error") {
          clearTimeout(timeout);
          ws.onmessage = null;
          removeTyping();
          reject(frame.message || "erro");
        }
      } catch(e) {}
    };
    ws.send(JSON.stringify({ type: "message", text: text, profile: profile, user_id: user_id }));
  });
}

// --- REST fallback ---
function authHeaders() {
  const h = {"Content-Type": "application/json"};
  if (token) h["Authorization"] = "Bearer " + token;
  else if (key) h["X-API-Key"] = key;
  return h;
}
async function sendRest(text, profile) {
  showTyping();
  const t0 = Date.now();
  const resp = await fetch("/message", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ user_id, profile, text })
  });
  removeTyping();
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) {
    key = ""; localStorage.removeItem("od_api_key");
    showGate("Chave inválida — informe novamente.");
    throw new Error("auth");
  }
  if (!resp.ok) throw new Error(data.error || "erro " + resp.status);
  const ms = ((Date.now() - t0) / 1000).toFixed(1);
  const meta = (data.profile ? data.profile + " · " : "") + (data.route || "") + " · " + ms + "s";
  addBubble("od", data.message || "(sem resposta)", meta);
  setTransport("rest");
  return data.message;
}

// --- Anônimo (nada é gravado no servidor; o contexto vem daqui) ---
async function sendAnon(text, profile) {
  showTyping();
  const t0 = Date.now();
  const resp = await fetch("/anon/message", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ message: text, profile: profile, history: anonHistory })
  });
  removeTyping();
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "erro " + resp.status);
  anonHistory.push({ role: "user", content: text });
  anonHistory.push({ role: "assistant", content: data.message || "" });
  if (anonHistory.length > 20) anonHistory = anonHistory.slice(-20);
  const ms = ((Date.now() - t0) / 1000).toFixed(1);
  addBubble("od", data.message || "(sem resposta)", "anônimo · " + (data.route || "") + " · " + ms + "s");
  return data.message;
}

// --- Voz (v1.17.3): microfone → /transcribe → texto no campo; resposta por voz via /tts ---
let mediaRecorder = null;
let micChunks = [];
let speakOn = localStorage.getItem("od_speak") === "1";
const micBtn = $("mic"), speakerBtn = $("speaker");
function setSpeak(on) {
  speakOn = on;
  localStorage.setItem("od_speak", on ? "1" : "0");
  speakerBtn.textContent = on ? "🔊" : "🔇";
  speakerBtn.classList.toggle("on", on);
  speakerBtn.setAttribute("aria-pressed", on ? "true" : "false");
}
setSpeak(speakOn);
speakerBtn.onclick = () => setSpeak(!speakOn);

async function speak(text) {
  // Sintetiza e toca. Best-effort: falha de voz NUNCA derruba a resposta.
  if (!speakOn || !text) return;
  try {
    const resp = await fetch("/tts", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ text: text.slice(0, 600) })
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.audio_b64) return;
    const audio = new Audio("data:audio/wav;base64," + data.audio_b64);
    await audio.play().catch(() => {});
  } catch (e) { /* voz é opcional */ }
}

async function toggleMic() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  if (!window.MediaRecorder || !navigator.mediaDevices) {
    addBubble("od", "Este navegador não suporta captura de áudio.", "voz");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    micChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) micChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      micBtn.classList.remove("rec");
      micBtn.disabled = true;
      micBtn.textContent = "⏳";
      const blob = new Blob(micChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      try {
        const b64 = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result).split(",")[1]);
          r.onerror = rej;
          r.readAsDataURL(blob);
        });
        const resp = await fetch("/transcribe", {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({ audio_b64: b64 })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
          addBubble("od", data.error || "Não consegui transcrever o áudio.", "voz");
          return;
        }
        $("text").value = data.text;
        $("send").click();
      } catch (e) {
        addBubble("od", "Falha na transcrição: " + e.message, "voz");
      } finally {
        micBtn.disabled = false;
        micBtn.textContent = "🎤";
      }
    };
    mediaRecorder.start();
    micBtn.classList.add("rec");
    micBtn.textContent = "⏹";
  } catch (e) {
    addBubble("od", "Microfone indisponível: " + e.message, "voz");
  }
}
micBtn.onclick = toggleMic;

// --- Send ---
async function send() {
  const text = $("text").value.trim();
  if (!text || busy) return;
  busy = true; $("send").disabled = true; $("text").value = "";
  addBubble("user", text);
  const profile = $("profile").value;
  if (anonMode) {
    try { const msg = await sendAnon(text, profile); }
    catch(e) { addBubble("od", "Erro: " + e.message, "anônimo"); }
  } else {
    try {
      const msg = await sendWs(text, profile);
      speak(msg);
    } catch(e) {
      try { const msg = await sendRest(text, profile); speak(msg); } catch(e2) {
        if (e2.message !== "auth") addBubble("od", "Erro: " + e2.message, "API");
      }
    }
  }
  busy = false; $("send").disabled = false; $("text").focus();
}

// --- Login ---
function resetProfileFilter() {
  // O filtro é da SESSÃO, não do navegador: um perfil com 0 mensagens para
  // o próximo usuário faria o histórico parecer vazio.
  $("profile").value = "auto";
}
$("enter").onclick = async () => {
  const user = $("login-user").value.trim();
  const pass = $("login-pass").value.trim();
  if (!user || !pass) { $("err").textContent = "Preencha username e senha."; return; }
  try {
    const resp = await fetch("/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username: user, password: pass})
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.ok) { $("err").textContent = data.error || "Falha no login."; return; }
    token = data.token;
    if (data.user && data.user.username) { user_id = data.user.username; }
    localStorage.setItem("od_session_token", token);
    resetProfileFilter();
    showChat();
  } catch(e) { $("err").textContent = "Falha de rede."; }
};
// --- Registro ---
$("register").onclick = async () => {
  const user = $("reg-user").value.trim();
  const email = $("reg-email").value.trim();
  const pass = $("reg-pass").value.trim();
  if (!user || !email || !pass) { $("err2").textContent = "Preencha todos os campos."; return; }
  try {
    const resp = await fetch("/auth/register", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username: user, email: email, password: pass})
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.ok) { $("err2").textContent = data.error || "Falha no registro."; return; }
    // Auto-login após registro
    const loginResp = await fetch("/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username: user, password: pass})
    });
    const loginData = await loginResp.json().catch(() => ({}));
    if (loginData.ok && loginData.token) {
      token = loginData.token;
      if (loginData.user && loginData.user.username) { user_id = loginData.user.username; }
      localStorage.setItem("od_session_token", token);
      resetProfileFilter();
      showChat();
    } else { showGate("Conta criada. Faça login.", "err"); showGateView("login"); }
  } catch(e) { $("err2").textContent = "Falha de rede."; }
};
// --- API Key (modo avançado) ---
$("enter-key").onclick = async () => {
  key = $("key").value.trim();
  if (!key) { $("err3").textContent = "Informe a chave."; return; }
  const probe = await fetch("/llms", { headers: { "X-API-Key": key } });
  if (!probe.ok) { $("err3").textContent = "Chave inválida (" + probe.status + ")."; return; }
  localStorage.setItem("od_api_key", key);
  resetProfileFilter();
  showChat();
};
$("send").onclick = send;
$("text").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
async function tryAutoLogin() {
  // Tenta relogar com session token salvo
  if (token) {
    try {
      const resp = await fetch("/auth/me", { headers: {"Authorization": "Bearer " + token} });
      if (resp.ok) {
        const data = await resp.json().catch(() => ({}));
        if (data.user && data.user.username) { user_id = data.user.username; }
        showChat(); return;
      }
    } catch(e) {}
    token = ""; localStorage.removeItem("od_session_token");
  }
  // Tenta com API key salva
  if (key) {
    try {
      const resp = await fetch("/llms", { headers: {"X-API-Key": key} });
      if (resp.ok) { user_id = "web"; showChat(); return; }
    } catch(e) {}
    key = ""; localStorage.removeItem("od_api_key");
  }
  showGate("");
}
tryAutoLogin();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------

class APIServer(ThreadingHTTPServer):
    """Servidor REST (ThreadingHTTPServer) sobre o Orchestrator.

    Uso típico:
        server = APIServer(orch, config=APIConfig(port=8000, api_key="..."))
        thread = server.serve_background()
        ...
        server.shutdown() / server.server_close()
    """

    daemon_threads = True
    allow_reuse_address = True
    # serve_forever checa o evento de shutdown a cada poll_interval —
    # padrão 0.5s deixaria stop() lento em testes com muitos servidores.
    poll_interval = 0.05

    def __init__(
        self,
        orchestrator: Optional[Orchestrator] = None,
        *,
        config: Optional[APIConfig] = None,
        vector: Optional["VectorStore"] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config or APIConfig()
        self.vector = vector
        # Registry usado por POST /executa e GET /actions (v1.2.0 app).
        if self.config.action_registry is not None:
            self._action_registry = self.config.action_registry
        else:
            self._action_registry = self.orchestrator.action_registry \
                if self.orchestrator is not None else None
        # Push FCM (core/push.py) — None = endpoints respondem 503.
        self._push = self.config.push
        # User auth (integrations/api/auth.py) — None = auth desabilitado
        self._user_store = self.config.user_store
        self._registry = self.config.registry
        # Cooldown por peça do aviso de chat no Telegram (anti-spam do dono).
        self._chat_notified: dict[str, float] = {}
        self._chat_notified_lock = threading.Lock()
        # Freio contra força bruta no login — construído só quando há auth
        self._login_guard = self.config.login_guard
        if self._login_guard is None and self._user_store is not None:
            from integrations.api.auth import LoginGuard
            self._login_guard = LoginGuard(
                max_attempts=self.config.login_max_attempts,
                window_s=self.config.login_window_s,
                lockout_s=self.config.login_lockout_s,
            )
        self.started_at = time.time()
        self.requests_total = 0
        self.errors_total = 0
        self._lock = threading.Lock()
        self._rate_buckets: dict[str, list[float]] = {}
        # Fase 7.2: contadores espelhados no MetricsCollector (quando presente)
        self._m_requests = None
        self._m_errors = None
        if self.config.metrics is not None:
            self._m_requests = self.config.metrics.counter(
                "od_api_requests_total",
                "Requisições recebidas pela API REST.",
            )
            self._m_errors = self.config.metrics.counter(
                "od_api_errors_total",
                "Erros respondidos pela API REST.",
            )
        super().__init__((self.config.host, self.config.port), APIHandler)

    def _owner_user(self) -> Optional[Any]:
        """Conta do dono (`OD_OWNER_USERNAME`) no UserStore, ou None.

        É a conta que a `OD_API_KEY` assume: o histórico do dono fica contínuo
        entre o app, o curl e o chat, e o gate de actions trata como admin.
        Sem dono configurado ou sem UserStore, devolve None (comportamento
        anterior: a chave não tem conta).
        """
        store = self.config.user_store
        nome = (self.config.owner_username or "").strip()
        if store is None or not nome:
            return None
        try:
            return store.get_user_by_username(nome)
        except Exception as exc:  # pragma: no cover — store indisponível
            log.warn("Falha ao resolver a conta do dono", error=str(exc))
            return None

    # -- Ruído de desconexão de cliente --------------------------------------
    #
    # O `handle_error` herdado do socketserver imprime o traceback inteiro no
    # stderr do processo quando um cliente aborta a conexão no meio do request
    # — e isso é rotina: app Android perdendo rede, navegador fechando a aba,
    # health check que estoura o timeout. No journal do systemd esse traceback
    # vira ruído que esconde erro de verdade (foi o que aconteceu em
    # 2026-09-15 10:14:41, com dois `ConnectionResetError` de um peer do
    # tailnet). Aqui a desconexão vira UMA linha de debug, sem stack.
    #
    # O que NÃO é desconexão continua avisando no nível WARN — e nada de
    # diagnóstico se perde: os erros dos handlers já são tratados em
    # `APIHandler._handle` (APIError → status próprio; Exception → 500 +
    # log.error), então o que chega aqui é falha de socket.
    _CLIENT_GONE_ERRORS = (
        ConnectionError,  # cobre Reset/BrokenPipe/Aborted
        TimeoutError,
    )

    def handle_error(self, request, client_address) -> None:
        """Contém o erro de um request sem poluir o journal (ver acima)."""
        exc = sys.exc_info()[1]
        peer = (
            f"{client_address[0]}:{client_address[1]}"
            if isinstance(client_address, tuple)
            else str(client_address)
        )
        if exc is None or isinstance(exc, self._CLIENT_GONE_ERRORS):
            log.debug(
                "Cliente desconectou durante o request",
                peer=peer,
                error=type(exc).__name__ if exc is not None else "unknown",
            )
            return
        log.warn(
            "Erro inesperado ao atender request",
            peer=peer,
            error=type(exc).__name__,
            detail=str(exc)[:200],
        )

    # -- Métricas internas ---------------------------------------------------

    @property
    def started_at_text(self) -> str:
        return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(self.started_at))

    @property
    def bound_port(self) -> int:
        """Porta real (útil quando config.port == 0)."""
        return int(self.server_address[1])

    def count_request(self) -> None:
        with self._lock:
            self.requests_total += 1
        if self._m_requests is not None:
            self._m_requests.inc()

    def count_error(self) -> None:
        with self._lock:
            self.errors_total += 1
        if self._m_errors is not None:
            self._m_errors.inc()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests": self.requests_total,
                "errors": self.errors_total,
                "uptime_s": int(time.time() - self.started_at),
            }

    # -- Ciclo de vida -------------------------------------------------------

    def serve_background(self) -> threading.Thread:
        """Sobe o servidor em thread daemon (dev/testes/runtime leve)."""
        thread = threading.Thread(
            target=self.serve_forever,
            kwargs={"poll_interval": self.poll_interval},
            daemon=True,
        )
        thread.start()
        log.info(
            "API REST no ar",
            host=self.config.host,
            port=self.bound_port,
            auth=bool(self.config.api_key),
            orchestrator=self.orchestrator is not None,
        )
        return thread

    def stop(self) -> None:
        """Encerra o serve_forever e libera o socket."""
        self.shutdown()
        self.server_close()


# ---------------------------------------------------------------------------
# Handler HTTP
# ---------------------------------------------------------------------------

class APIHandler(BaseHTTPRequestHandler):
    """Dispatch dos 18 endpoints + JSON/HTML, auth e rate limit."""

    protocol_version = "HTTP/1.1"
    server_version = SERVER_VERSION
    sys_version = ""

    @property
    def api(self) -> APIServer:
        return self.server  # type: ignore[return-value]

    # -- Ciclo de requisição -------------------------------------------------

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:
        # CORS preflight
        self.send_response(204)
        self._send_cors()
        self.send_header("Allow", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle(self, method: str) -> None:
        self.api.count_request()
        self._current_user = None  # preenchido pelo _check_api_key (sessão/API key de usuário)
        self._auth_via = None  # 'session' | 'api_key' — de onde veio a credencial
        try:
            path = urlsplit(self.path).path
            route, match = self._match_route(method, path)
            if route is None:
                allowed = self._allowed_methods(path)
                if allowed:
                    self._json(
                        405, {"ok": False, "error": "method_not_allowed",
                              "allow": ", ".join(allowed)}
                    )
                else:
                    self._json(
                        404, {"ok": False, "error": "not_found", "path": path}
                    )
                return
            if not self._check_rate_limit():
                return
            # auth_all exige a chave também nos endpoints públicos
            # auth_all exige a chave também nos endpoints públicos, EXCETO
            # nos shells de página (GET /chat, /dashboard): HTML estático
            # sem dados — navegador não envia header X-API-Key. Os dados e
            # serviços (incluindo POST /message) seguem exigindo a chave.
            page_shell = bool(
                method == "GET"
                and route.path in PAGE_PATHS
                and self.api.config.page_shells_public
            )
            # Redirect de / para /site quando navegador pede HTML: assim
            # nicky.theworkpc.com mostra a landing sem /site. O redirect
            # é sem conteúdo sensível, então passa sem auth.
            if route.path == "/" and method == "GET" and page_shell:
                accept = self.headers.get("Accept", "")
                if "text/html" in accept and "application/json" not in accept:
                    self.send_response(302)
                    self._send_cors()
                    self.send_header("Location", "/site")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            # auth_all: chave exigida em TODOS os endpoints, exceto:
            # - shells de página (GET /chat, /dashboard, /site) — HTML
            #   estático sem dados, navegador não envia X-API-Key
            # - endpoints de auth (POST /auth/register, /auth/login)
            #   — o próprio fluxo de autenticação não pode exigir auth
            auth_exempt = route.path in AUTH_EXEMPT_PATHS
            if (route.auth or (self.api.config.auth_all and not page_shell and not auth_exempt)) \
                    and not self._check_api_key():
                return
            handler = getattr(self, route.handler)
            kwargs: dict[str, str] = dict(match.groupdict()) if match else {}
            handler(**kwargs)
        except APIError as exc:
            self.api.count_error()
            log.warn("API erro", status=exc.status, detail=exc.message)
            # ok/error ficam DEPOIS: um extra nunca pode mascarar o código.
            payload: dict[str, Any] = dict(exc.extra)
            payload.update({"ok": False, "error": exc.message})
            self._json(exc.status, payload)
        except (BrokenPipeError, ConnectionResetError):
            pass  # cliente foi embora no meio da resposta
        except Exception as exc:  # pragma: no cover — defeito inesperado
            self.api.count_error()
            log.error("API interna", error=type(exc).__name__)
            self._json(
                500, {"ok": False, "error": "internal_error",
                      "detail": type(exc).__name__}
            )

    def _match_route(
        self, method: str, path: str
    ) -> tuple[Optional[_Route], Optional[re.Match[str]]]:
        """Rota exata (método+path). None se não houver para o método."""
        for route in ROUTES:
            match = route.pattern.fullmatch(path)
            if match and route.method == method:
                return route, match
        return None, None

    def _allowed_methods(self, path: str) -> list[str]:
        return sorted(
            {r.method for r in ROUTES if r.pattern.fullmatch(path)}
        )

    # -- Segurança -----------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Janela deslizante por IP. Escreve 429 e retorna False se estourou."""
        limit = self.api.config.rate_limit_max
        if limit <= 0:
            return True
        window = self.api.config.rate_window_s
        client = self.client_address[0]
        now = time.monotonic()
        with self.api._lock:
            stamps = self.api._rate_buckets.setdefault(client, [])
            while stamps and stamps[0] <= now - window:
                stamps.pop(0)
            if len(stamps) >= limit:
                retry = int(window - (now - stamps[0])) + 1
                self._json(
                    429,
                    {"ok": False, "error": "rate_limited",
                     "retry_after_s": retry},
                )
                return False
            stamps.append(now)
            return True

    def _check_api_key(self) -> bool:
        """Autentica por sessão (Bearer), API key de usuário ou API key do servidor.

        Ordem de checagem:
          1. Authorization: Bearer <session_token> — valida via UserStore;
          2. X-API-Key de usuário (od_...) — valida via UserStore;
          3. X-API-Key do servidor — compara com OD_API_KEY do .env.

        Com UserStore configurada (auth de usuários ligada), uma credencial
        válida passa a ser obrigatória: sem OD_API_KEY configurada, a request é
        negada em vez de liberada — senão um token Bearer inválido cairia no
        caminho "auth desligada" e passaria. A exceção continua sendo o dev
        local explícito: sem auth_all e sem UserStore, tudo fica aberto.

        Retorna False e escreve 401 quando negado.
        """
        store = self.api._user_store
        # 1) Session token (chat web)
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token and store is not None:
                user = store.validate_session(token)
                if user is not None:
                    self._current_user = user
                    self._auth_via = "session"
                    return True
            # Token inválido ou sem UserStore — cai para checagem de API key

        provided = self.headers.get("X-API-Key", "")
        # 2) API key de usuário (registro/login web) — só quando há UserStore
        if provided and store is not None:
            user = store.login_with_api_key(provided)
            if user is not None:
                self._current_user = user
                self._auth_via = "api_key"
                return True

        # 3) API key do servidor (legado / app mobile)
        expected = self.api.config.api_key
        if not expected:
            if self.api.config.auth_all:
                log.error(
                    "auth_all=True sem api_key — todas as requests negadas; "
                    "defina OD_API_KEY no .env"
                )
                self._json(
                    401,
                    {"ok": False, "error": "unauthorized",
                     "hint": "servidor sem chave configurada (auth_all)"},
                )
                return False
            if store is not None:
                # Auth de usuários ligada sem OD_API_KEY: exige credencial
                self._json(
                    401,
                    {"ok": False, "error": "unauthorized",
                     "hint": "envie X-API-Key ou faça login"},
                )
                return False
            return True  # auth desligada (uso local/dev explícito)
        if not provided or not hmac.compare_digest(provided, expected):
            self._json(
                401,
                {"ok": False, "error": "unauthorized",
                 "hint": "envie X-API-Key ou faça login"},
            )
            return False
        # OD_API_KEY é a chave do DONO (OD_OWNER_USERNAME): com a conta
        # configurada, a chave assume a conta — o histórico do dono fica
        # contínuo entre app, curl e chat — e o papel vira admin. Sem dono
        # configurado, segue como antes (chave sem conta).
        owner = self.api._owner_user()
        if owner is not None:
            self._current_user = owner
            self._auth_via = "server"
        return True

    def _check_owner(self, user_id: str) -> str:
        """Autoriza o acesso a um recurso por username (histórico/memória).

        Credencial de USUÁRIO (sessão Bearer ou API key ``od_...``) só acessa o
        PRÓPRIO recurso: o ``{user_id}`` do caminho tem de ser o username
        autenticado. A ``OD_API_KEY`` do servidor é o passe de admin — não tem
        usuário associado (``_current_user is None``), é a chave do operador e
        do app/bot, e continua lendo e apagando qualquer histórico.

        Antes, qualquer credencial válida lia ou **apagava** o histórico de
        qualquer username: inofensivo enquanto todo mundo era o balde "web",
        inaceitável desde que cada pessoa tem conta e senha.

        Retorna:
            O username já decodificado (``unquote`` + strip).

        Raises:
            APIError: 403 quando o username do caminho não é o autenticado.
        """
        raw = unquote(user_id).strip()
        user = self._current_user
        if raw.lower() in ("me", "@me"):
            uid = user.username if user else ((self.api.config.owner_username or "alex").strip().lower())
        else:
            uid = raw
        if user is None:  # OD_API_KEY sem dono configurado ou dev sem auth
            return uid
        if self._is_owner_username(user.username):
            return uid  # o dono é admin: lê e apaga qualquer histórico
        if uid.lower() != user.username.lower():
            log.warn(
                "Acesso a recurso de outro usuário negado",
                autenticado=user.username,
                alvo=uid,
                path=urlsplit(self.path).path,
            )
            raise APIError(403, "acesso_negado")
        return uid

    def _is_owner_username(self, username: str) -> bool:
        """True quando o username é a conta do dono (OD_OWNER_USERNAME)."""
        owner = (self.api.config.owner_username or "").strip().lower()
        return bool(owner) and str(username or "").strip().lower() == owner

    def _role(self) -> str:
        """Papel de quem chama, para o gate de actions e da segurança.

        - conta do dono (`OD_OWNER_USERNAME`, inclusive assumida pela
          `OD_API_KEY`) → **admin** (pode tudo; destrutiva pede confirmação);
        - demais contas → **user** (conversa + ações sobre os próprios dados);
        - sem conta e autenticado pela chave do servidor/dev → **admin**, para
          preservar o comportamento anterior (chave de operador).
        """
        user = self._current_user
        if user is None:
            return "admin"
        if self._is_owner_username(user.username):
            return "admin"
        return "user"

    # -- Helpers de corpo/resposta -------------------------------------------

    def _has_body(self) -> bool:
        """True quando há corpo na requisição (Content-Length > 0)."""
        try:
            return int(self.headers.get("Content-Length") or 0) > 0
        except ValueError:
            return False

    def _read_json(self, max_bytes: Optional[int] = None) -> dict[str, Any]:
        """ Lê o corpo JSON. `max_bytes` sobrepõe o limite global (413 acima)."""
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        limite = max_bytes if max_bytes is not None else self.api.config.max_body_bytes
        if length > limite:
            raise APIError(413, "body_too_large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(400, f"json_invalido: {exc}") from exc
        if not isinstance(data, dict):
            raise APIError(400, "esperado objeto JSON")
        return data

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(
            payload, ensure_ascii=False, indent=2
        ).encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        # Páginas embutidas EVOLUEM junto com o servidor (o JS do /chat é
        # parte do contrato da API). Sem no-store o navegador pode rodar
        # uma versão antiga do script do cache e o site parece "não atualizar"
        # ao trocar de usuário ou depois de um deploy.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _text(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _raw(self, status: int, body: bytes, content_type: str,
             cache: str = "no-store") -> None:
        """Resposta binária bruta (foto da peça e afins)."""
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, X-API-Key"
        )
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
        )

    def log_message(self, fmt: str, *args: Any) -> None:
        # Log padrão do http.server redirecionado ao NICKY em nível debug
        # (o acesso real é auditado no dispatch), mantendo o console limpo.
        try:
            log.debug(fmt % args if args else fmt)
        except (TypeError, ValueError):  # pragma: no cover — formato inesperado
            log.debug(str(fmt))

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    # -- Info/health (sem auth, como no legado) ---------------------------

    def info(self) -> None:
        # Navegadores (Accept: text/html) vão direto para /site — assim
        # nicky.theworkpc.com mostra a landing page sem o /site. APIs e
        # curl continuam recebendo o JSON normalmente.
        accept = self.headers.get("Accept", "")
        if "text/html" in accept and "application/json" not in accept:
            self.send_response(302)
            self._send_cors()
            self.send_header("Location", "/site")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(
            200,
            {
                "name": API_NAME,
                "signature": __signature__,
                "version": OD_VERSION,
                "endpoints": len(ROUTES),
                "orchestrator": self.api.orchestrator is not None,
                "uptime_s": int(time.time() - self.api.started_at),
            },
        )

    def health(self) -> None:
        monitor = self.api.config.health
        if monitor is not None:
            # Fase 7.3: /health responde o agregado do HealthMonitor
            import asyncio

            try:
                result = asyncio.run(monitor.health())
            except RuntimeError:  # pragma: no cover — loop ativo
                result = {
                    "ok": False,
                    "status": "down",
                    "checks": {},
                    "detail": "health indisponível em contexto async",
                }
            result["uptime_s"] = int(time.time() - self.api.started_at)
            self._json(200, result)
            return
        orch = self.api.orchestrator
        llms = self._provider_names()
        ok = orch is not None
        self._json(
            200,
            {
                "ok": ok,
                "status": "up" if ok else "degraded",
                "orchestrator": ok,
                "llms": llms,
                "uptime_s": int(time.time() - self.api.started_at),
            },
        )

    def profiles(self) -> None:
        items = []
        for name in self.api.config.profiles:
            items.append(
                {
                    "name": name,
                    "display_name": _profile_display_name(name),
                    "default": name == DEFAULT_PROFILE,
                }
            )
        self._json(200, {"ok": True, "profiles": items})

    def profile_detail(self, name: str) -> None:
        decoded = unquote(name)
        valid = decoded in self.api.config.profiles
        self._json(
            200,
            {
                "ok": valid,
                "name": decoded,
                "available": valid,
                "default": decoded == DEFAULT_PROFILE,
                "options": list(self.api.config.profiles),
            },
        )

    def presence_today(self) -> None:
        self._json(
            200,
            {
                "ok": False,
                "message": "Monitor de presença não conectado — capacidade "
                           "da Fase 6.2 (Presence Monitor).",
                "detections": [],
            },
        )

    def dashboard_html(self) -> None:
        """Painel do USUÁRIO logado: uso da própria conta, histórico e conta
        (troca de senha / API key). Shell aberto; dados só via credencial —
        sem login o navegador é redirecionado para /chat."""
        self._html(200, _DASHBOARD_PAGE_HTML)

    def admin_html(self) -> None:
        """Painel do DONO (papel admin): contas, uso e saúde do sistema.
        O gate de dados é o _require_admin nos handlers /admin/users* — aqui
        é só o shell; sem papel admin a própria página se desliga."""
        self._html(200, _ADMIN_PAGE_HTML)

    def chat_html(self) -> None:
        """Chat funcional: shell aberto + chave pedida UMA vez no navegador
        (sessionStorage) e usada nas chamadas a POST /message."""
        self._html(200, _CHAT_PAGE_HTML)

    def site_index(self) -> None:
        """Landing do site (index.html) em GET /site e /site/."""
        self._serve_site_file("index.html")

    def app_version(self) -> None:
        """GET /app/version — versão do APK publicada em site/ (sem auth).

        Contrato para a AUTO-ATUALIZAÇÃO do app (v1.7.0):
          {"ok": true, "version": "1.7.0", "version_code": 17,
           "apk": "/site/OmegaDrakon.apk", "size": 52723923,
           "sha256": "..."}

        O app compara `version_code` com o seu (o do pubspec via
        package_info) e baixa /site/OmegaDrakon.apk quando o do servidor é
        maior — sem o usuário precisar entrar no site. `sha256` permite ao
        app conferir o download antes de instalar.

        Metadados do APK são lidos de forma LAZY: o hash de um binário de
        ~50 MB não deve pesar na memória nem na CPU de quem só checa se há
        atualização (o endpoint é público e o app o sonda a cada aberto).
        """
        import hashlib

        base = Path(self.api.config.site_dir or DEFAULT_SITE_DIR).resolve()
        apk = base / "OmegaDrakon.apk"
        payload: dict[str, Any] = {
            "ok": True,
            "version": OD_VERSION,
            "version_code": _APP_VERSION_CODE,
            "apk": "/site/OmegaDrakon.apk",
        }
        if apk.is_file():
            payload["size"] = apk.stat().st_size
            digest = hashlib.sha256()
            with apk.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            payload["sha256"] = digest.hexdigest()
        self._json(200, payload)

    def registry_verify(self, codigo: str) -> None:
        codigo = unquote(codigo).strip()  # espaços/%XX viram caractere normal
        """GET /registry/{codigo} — consulta PÚBLICA de autenticidade.

        O ID vem gravado na peça (ou no cartão/QR): aceita o canônico
        (OD-PROD-2026-0001) ou o código curto gravado (NV-ABI-7F3A).
        Público sem credencial (AUTH_EXEMPT_PATHS), como /app/version.

        Resposta (200): {"ok": true, "peca": {"public_id", "name",
        "collection", "kind", "status", "engraved_code", "owner_username",
        "registered", ...}} — username de quem registrou (nunca nome
        real), SEM preço/notas/dados privados (404 "nao_encontrada" se
        o código não existe).
        """
        store = self.api._registry
        if store is None:
            raise APIError(503, "registry_indisponivel")
        public = store.verify_public(codigo)
        if public is None:
            self._json(404, {"ok": False, "error": "nao_encontrada",
                             "codigo": str(codigo).strip().upper()})
            return
        self._json(200, {"ok": True, "peca": public})

    def registry_photo(self, codigo: str) -> None:
        codigo = unquote(codigo).strip()
        """GET /registry/{codigo}/photo — foto pública da peça.

        Serve o arquivo enviado pelo dono no painel (jpeg/png/webp).
        Público sem credencial (AUTH_EXEMPT_PATHS).
        """
        store = self.api._registry
        if store is None:
            raise APIError(503, "registry_indisponivel")
        path = store.photo_path(codigo)
        if path is None:
            raise APIError(404, "foto_inexistente")
        try:
            data = path.read_bytes()
        except OSError as exc:  # pragma: no cover — arquivo sumiu no meio
            raise APIError(404, "foto_inexistente") from exc
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._raw(200, data, ctype, cache="public, max-age=3600")

    def registry_chat_get(self, codigo: str) -> None:
        codigo = unquote(codigo).strip()
        """GET /registry/{codigo}/chat — mensagens da sala (leitura pública).

        Query opcional: `?since=<id>` devolve só o que é novo (polling).
        """
        store = self.api._registry
        if store is None:
            raise APIError(503, "registry_indisponivel")
        query = parse_qs(urlsplit(self.path).query)
        try:
            since = int(query.get("since", ["0"])[0] or 0)
        except ValueError:
            since = 0
        mensagens = store.chat_messages(codigo, since_id=since)
        if mensagens is None:
            self._json(404, {"ok": False, "error": "nao_encontrada",
                             "codigo": str(codigo).strip().upper()})
            return
        self._json(200, {"ok": True, "mensagens": mensagens,
                         "total": len(mensagens)})

    def registry_chat_post(self, codigo: str) -> None:
        codigo = unquote(codigo).strip()
        """POST /registry/{codigo}/chat — publica na sala (conta obrigatória).

        Qualquer pessoa COM CONTA conversa com quem tem a peça (estoque →
        dono do sistema; registrada → @dono). O username público assina a
        mensagem; nome real nunca. Avisos ao dono no Telegram com cooldown
        por peça (2 min) — falha no aviso nunca derruba o envio.
        """
        store = self.api._registry
        if store is None:
            raise APIError(503, "registry_indisponivel")
        user = self._current_user
        if user is None:
            raise APIError(401, "login_obrigatorio")
        username = str(
            user.get("username") if isinstance(user, dict)
            else getattr(user, "username", "")
        ).strip()
        data = self._read_json()
        try:
            msg = store.chat_post(codigo, username, data.get("text", ""))
        except ValueError as exc:
            raise APIError(
                404 if str(exc) == "peca_inexistente" else 400, str(exc)
            )
        self._maybe_notify_chat(msg["public_id"], username, str(msg["text"]))
        self._json(201, {"ok": True, "mensagem": msg})

    def _maybe_notify_chat(self, public_id: str, username: str,
                           text: str) -> None:
        """Avisa o dono no Telegram (1 aviso a cada 2 min por peça)."""
        cb = self.api.config.chat_notify
        if cb is None:
            return
        now = time.time()
        with self.api._chat_notified_lock:
            if now - self.api._chat_notified.get(public_id, 0.0) < 120.0:
                return
            self.api._chat_notified[public_id] = now
        preview = text if len(text) <= 200 else text[:200] + "…"
        try:
            cb(f"💬 Peça {public_id} — {username}: {preview}")
        except Exception:  # pragma: no cover — Telegram fora do ar
            log.debug("chat_notify falhou (seguindo)", public_id=public_id)

    def site_file(self, file: str) -> None:
        """Arquivo do site (ex.: OmegaDrakon.apk) em GET /site/{file}."""
        self._serve_site_file(unquote(file))

    def _serve_site_file(self, name: str) -> None:
        """Serve um arquivo de site/ com streaming (o APK tem ~50MB).

        Segurança: resolve() + is_relative_to() antes de abrir — GET
        /site/../segredo ou /site/etc/passwd nunca escapa do diretório.
        Sem auth (landing pública no tailnet).

        Cache (v1.7.0 — site demorava para carregar às vezes):
          - HTML (index): ETag + Cache-Control max-age=60 — o navegador
            revalida por If-None-Match (304 barato) e a landing abre na
            hora nas visitas repetidas; mtime novo gera ETag nova.
          - APK/outros binários: continuam no-store (download sempre
            completo, sem cache parcial corrompido).

        Robustez p/ celular: suporta Range (o download manager do Android
        retoma em bytes=-N após falha) e envia Content-Disposition
        attachment em arquivos que não são HTML (o APK baixa como arquivo,
        não abre no navegador).
        """
        base = Path(self.api.config.site_dir or DEFAULT_SITE_DIR).resolve()
        target = (base / name).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise APIError(404, "not_found")
        ctype = (
            mimetypes.guess_type(target.name)[0]
            or "application/octet-stream"
        )
        size = target.stat().st_size
        etag = f'"{int(target.stat().st_mtime)}-{size}"'
        # Revalidação condicional (só para HTML — o APK baixa por inteiro).
        if ctype == "text/html" and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self._send_cors()
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "max-age=60")
            self.end_headers()
            return
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if match and (match.group(1) or match.group(2)):
                raw_start, raw_end = match.group(1), match.group(2)
                if raw_start == "":  # sufixo: bytes=-N (últimos N bytes)
                    length = int(raw_end)
                    start = max(0, size - length)
                else:
                    start = int(raw_start)
                    end = int(raw_end) if raw_end else size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self._send_cors()
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206
        length = end - start + 1
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if ctype == "text/html":
            # HTML estático: cache curtíssimo + revalidação por ETag.
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "max-age=60")
        else:
            # Binário (APK): baixar por inteiro, sem cache parcial.
            self.send_header("Cache-Control", "no-store")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if ctype != "text/html":
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{target.name}"',
            )
        self.end_headers()
        with target.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1 << 20, remaining))  # ≤ 1 MiB
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def metrics_text(self) -> None:
        if self.api.config.metrics is not None:
            # Fase 7.2: /metrics renderiza o MetricsCollector (fontes + api)
            self._text(200, self.api.config.metrics.render())
            return
        orch = self.api.orchestrator
        lines = [
            "# TYPE od_uptime_seconds gauge",
            f"od_uptime_seconds {int(time.time() - self.api.started_at)}",
        ]
        if orch is not None:
            m = orch.metrics.snapshot()
            lines.append("# TYPE od_processed_total counter")
            lines.append(f"od_processed_total {m['processed']}")
            lines.append(f"od_llm_total {m['llm']}")
            lines.append(f"od_fallback_total {m['fallback']}")
            lines.append(f"od_cache_hits_total {m['cache_hits']}")
            lines.append(f"od_quick_total {m['quick']}")
            lines.append(f"od_datetime_total {m['datetime']}")
            lines.append(f"od_rate_limited_total {m['rate_limited']}")
            lines.append(f"od_errors_total {m['errors']}")
        api_stats = self.api.snapshot()
        lines.append("# TYPE od_api_requests_total counter")
        lines.append(f"od_api_requests_total {api_stats['requests']}")
        lines.append(f"od_api_errors_total {api_stats['errors']}")
        self._text(200, "\n".join(lines) + "\n")

    # -- Endpoints protegidos (API Key) -----------------------------------

    def dashboard_stats(self) -> None:
        payload: dict[str, Any] = {"ok": True}
        payload.update(self._orch_snapshot())
        orch = self.api.orchestrator
        if orch is not None and orch.history is not None:
            payload["history"] = orch.history.stats()
        if orch is not None and orch.cache is not None:
            payload["cache"] = orch.cache.stats()
        if self.api.vector is not None:
            payload["vector_store"] = {
                "docs": self.api.vector.count(),
                "namespaces": self.api.vector.list_namespaces(),
            }
        self._json(200, payload)

    def llms(self) -> None:
        items = []
        for position, provider in enumerate(self._providers()):
            items.append(
                {
                    "position": position,
                    "name": getattr(provider, "name", ""),
                    "kind": type(provider).__name__,
                }
            )
        self._json(200, {"ok": True, "llms": items})

    def capabilities(self) -> None:
        """Manifesto completo das capacidades do sistema (core/capabilities.py)."""
        self._json(200, capabilities_manifest())

    async def _process_message(
        self, user_id: str, profile: str, text: str,
        system_prompt: str, session_id: str,
        *, role: str = "admin", persist: bool = True,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> OrchestrationResult:
        if self.api.orchestrator is None:
            raise APIError(503, "orchestrator_indisponivel")
        return await self.api.orchestrator.process(
            user_id, profile, text,
            system_prompt=system_prompt, session_id=session_id,
            role=role, persist=persist, extra_history=extra_history,
        )

    def anon_message(self) -> None:
        """POST /anon/message — conversa ANÔNIMA (sem conta, sem rastro).

        Não exige credencial (mesmo com auth_all). O contexto da conversa vem
        do CLIENTE (`history`), porque nada é gravado no banco: sem cache e
        sem histórico, e o papel "anonymous" não aciona action nenhuma. O
        limite por IP do servidor continua valendo.
        """
        data = self._read_json()
        text = str(data.get("message") or data.get("text") or "").strip()
        if not text:
            raise APIError(400, "text_obrigatorio")
        profile = str(data.get("profile") or DEFAULT_PROFILE).strip()
        if profile not in self.api.config.profiles:
            raise APIError(400, f"perfil_desconhecido: {profile}")
        if profile == "auto":
            # Mesma detecção por domínio do /message (Plêiade).
            profile = resolve_auto_profile(text)
        historico = data.get("history") or []
        if not isinstance(historico, list):
            raise APIError(400, "history_deve_ser_lista")
        # Anti-abuso: o cliente não manda um prompt gigante de contexto.
        result = asyncio.run(self._process_message(
            "anonimo", profile, text, "", "anon",
            role="anonymous", persist=False, extra_history=historico[-ANON_HISTORY_MAX:],
        ))
        payload = result.to_dict()
        payload["ok"] = result.ok
        payload["anonimo"] = True
        self._json(200, payload)

    def message(self) -> None:
        data = self._read_json()
        # Compat v1.2.0 (app Android): aceita {"message": ...} como alias de
        # "text" e user_id implícito "app" quando ausente (o app não tem
        # login por usuário; a API key já autentica o dispositivo).
        text = str(data.get("text") or data.get("message") or "").strip()
        # Identidade: quando a credencial é de usuário (sessão Bearer ou API key
        # od_...), o servidor usa o usuário AUTENTICADO e ignora o user_id do
        # corpo — antes o chat web mandava sempre "web", o que fazia contas
        # diferentes dividirem o mesmo balde de histórico/cache e permitia
        # postar como qualquer nome. Sem credencial de usuário (OD_API_KEY
        # legado/app), segue valendo o user_id do corpo.
        if self._current_user is not None:
            user_id = self._current_user.username
        else:
            user_id = str(
                data.get("user_id") or ("app" if data.get("message") else "")
            ).strip()
            if not user_id:
                raise APIError(400, "user_id_obrigatorio")
            # Sem credencial de usuário o cliente escolhe o balde — mas só com
            # id de formato conhecido (o legado/app usa "app", o bot usa o id
            # do Telegram, o chat antigo usava "web").
            if not valid_user_id(user_id):
                raise APIError(400, "user_id_invalido")
            # Alias de transporte legado → conta do dono (OD_ACCOUNT_ALIASES):
            # o app ("app") e o bot (id do Telegram) passam a gravar no balde
            # da conta, sem mudança no cliente.
            user_id = resolve_account(user_id, self.api.config.account_aliases)
        if not text:
            raise APIError(400, "text_obrigatorio")
        profile = str(data.get("profile") or DEFAULT_PROFILE).strip()
        if profile not in self.api.config.profiles:
            raise APIError(400, f"perfil_desconhecido: {profile}")
        if profile == "auto":
            # Modo auto: o perfil é detectado pelo DOMÍNIO do texto
            # (ProfileManager — Plêiade). Antes forçava guardian, e uma
            # pergunta de religião respondia como Guardian em vez de Nyx.
            profile = resolve_auto_profile(text)
        system_prompt = str(data.get("system_prompt") or "")
        session_id = str(data.get("session_id") or f"api:{user_id}")
        result = asyncio.run(
            self._process_message(
                user_id, profile, text, system_prompt, session_id,
                role=self._role(),
            )
        )
        payload = result.to_dict()
        payload["ok"] = result.ok
        self._json(200, payload)

    # -- Catálogo e execução de actions (v1.2.0 — app Android) ---------------

    def actions_catalog(self) -> None:
        """GET /actions — catálogo completo do ActionRegistry com risco.

        Formato consumido pelo app (OdAction.fromJson): name, description,
        category, permission, params (dict do schema) e risk ('low'|'medium'
        |'high') derivado da classificação de risco do Telegram (nível 0/1/2).
        """
        registry = self.api._action_registry
        if registry is None:
            raise APIError(503, "action_registry_indisponivel")
        items = []
        for action in registry.list_actions():
            nivel = _classificar_risco(action["name"])
            items.append({
                "name": action["name"],
                "description": action["description"],
                "category": action["category"],
                "permission": action["permission"],
                "params": action["params"],
                "risk": {0: "low", 1: "medium", 2: "high"}.get(nivel, "low"),
            })
        self._json(200, {"ok": True, "count": len(items), "actions": items})

    def executa(self) -> None:
        """POST /executa — executa uma action do catálogo (paridade /executa
        do Telegram). Body: {"action": str, "params"?: dict, "confirm"?: bool}.

        Segurança (mesma semântica do Telegram):
          - nível 2 (destrutivo) exige confirm=true → 422 sem ele;
          - execução passa pelo pipeline completo do ActionRegistry
            (validação de schema + gate do Security Layer, role admin).
        """
        registry = self.api._action_registry
        if registry is None:
            raise APIError(503, "action_registry_indisponivel")
        data = self._read_json()
        action_name = str(data.get("action") or "").strip().lower()
        if not action_name:
            raise APIError(400, "action_obrigatoria")
        params = data.get("params") or {}
        if not isinstance(params, dict):
            raise APIError(400, "params_deve_ser_objeto")
        try:
            registry.get(action_name)
        except ActionNotFoundError:
            raise APIError(404, f"action_desconhecida: {action_name}")
        # Papel de quem chama: o dono é admin; a conta comum é 'user' e só
        # passa nas ações sobre os próprios dados (leitura + memória). O
        # nível 1 (admin) e o 2 (destrutivo) são do dono — o destrutivo ainda
        # exige confirm=true. Antes o `/executa` mandava role="admin" fixo,
        # então QUALQUER credencial válida rodava ação destrutiva.
        role = self._role()
        nivel = _classificar_risco(action_name)  # 0 público · 1 admin · 2 destrutivo
        if nivel >= 1 and role != "admin":
            raise APIError(403, f"acao_restrita_ao_dono: {action_name}")
        if nivel >= 2 and not data.get("confirm"):
            raise APIError(
                422, f"confirmacao_obrigatoria: {action_name} é destrutiva; "
                     "reenvie com confirm=true"
            )
        result = asyncio.run(registry.execute(
            action_name, params=params, role=role,
            session_id="api:app",
        ))
        status_http = {
            "ok": 200,
            "invalid": 400,
            "denied": 403,
            "not_found": 404,
            "error": 500,
        }.get(result.status, 500)
        payload = result.to_dict()
        payload["ok"] = result.status == "ok"
        self._json(status_http, payload)

    # -- Push FCM (notificações no app) -------------------------------------

    def _push_service(self) -> Any:
        """PushService real, ou 503 quando o push não foi montado."""
        push = self.api._push
        if push is None:
            raise APIError(503, "push_indisponivel")
        return push

    def push_register(self) -> None:
        """POST /push/register — registra o token FCM deste dispositivo.

        Body: {"token": str, "platform"?: str, "device"?: str}
        O token é a chave (upsert): o app reenvia a cada boot e a cada
        refresh, então registrar de novo só atualiza o aparelho.

        Funciona mesmo com o push DESLIGADO (sem credencial): assim, quando a
        service account chegar, o dispositivo já está registrado.
        """
        push = self._push_service()
        data = self._read_json()
        token = str(data.get("token") or "").strip()
        if not token:
            raise APIError(400, "token_obrigatorio")
        device = push.register(
            token,
            platform=str(data.get("platform") or "android"),
            device=str(data.get("device") or ""),
        )
        self._json(200, {
            "ok": True,
            "token": device.masked_token(),
            "devices": push.registry.count(),
            "push_enabled": push.enabled,
        })

    def push_unregister(self) -> None:
        """POST /push/unregister — remove o dispositivo (logout/troca de aparelho)."""
        push = self._push_service()
        data = self._read_json()
        token = str(data.get("token") or "").strip()
        if not token:
            raise APIError(400, "token_obrigatorio")
        removed = push.unregister(token)
        self._json(200, {
            "ok": True,
            "removed": removed,
            "devices": push.registry.count(),
        })

    def push_devices(self) -> None:
        """GET /push/devices — estado do push (tokens mascarados, nunca inteiros)."""
        push = self._push_service()
        self._json(200, {"ok": True, **push.status()})

    # -- Auth (registro, login, sessão) ------------------------------------

    def auth_register(self) -> None:
        """POST /auth/register — registra um novo usuário.

        Body: {"username": ..., "email": ..., "password": ...}
        Retorna o usuário (sem password_hash) e a API key.
        """
        if self.api._user_store is None:
            raise APIError(503, "auth não configurado")
        data = self._read_json()
        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip()
        password = (data.get("password") or "").strip()
        if not username or not email or not password:
            raise APIError(400, "username, email e password são obrigatórios")
        try:
            from integrations.api.auth import AuthError
            user = self.api._user_store.register(username, email, password)
        except AuthError as exc:
            raise APIError(exc.status, str(exc))
        self._json(201, {
            "ok": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "api_key": user.api_key,
            },
        })

    def auth_login(self) -> None:
        """POST /auth/login — autentica e retorna session token.

        Body: {"username": ..., "password": ...}
        Retorna {token, user} — o chat web salva o token em localStorage.
        """
        if self.api._user_store is None:
            raise APIError(503, "auth não configurado")
        data = self._read_json()
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        if not username or not password:
            raise APIError(400, "username e password são obrigatórios")
        ip = self.client_address[0]
        guard = self.api._login_guard
        # Freio ANTES de tocar no banco: tentativa bloqueada não consome hash
        retry = guard.retry_after(ip, username) if guard is not None else 0.0
        if retry > 0:
            self._json(
                429,
                {"ok": False, "error": "too_many_attempts",
                 "retry_after_s": int(retry) + 1},
            )
            return
        try:
            from integrations.api.auth import AuthError
            token = self.api._user_store.login(username, password)
        except AuthError as exc:
            if guard is not None:
                guard.register_failure(ip, username)
            raise APIError(exc.status, str(exc))
        if guard is not None:
            guard.reset(ip, username)
        user = self.api._user_store.validate_session(token)
        self._json(200, {
            "ok": True,
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            } if user else None,
        })

    def auth_logout(self) -> None:
        """POST /auth/logout — encerra a sessão atual.

        Requer Authorization: Bearer <token>.
        """
        if self.api._user_store is None:
            raise APIError(503, "auth não configurado")
        auth_header = self.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        if not token:
            raise APIError(400, "token não fornecido")
        self.api._user_store.logout(token)
        self._json(200, {"ok": True})

    def auth_me(self) -> None:
        """GET /auth/me — retorna o usuário logado (session token ou API key).

        Requer Authorization: Bearer <token> ou X-API-Key.
        """
        if self.api._user_store is None:
            raise APIError(503, "auth não configurado")
        # Se _current_user foi preenchido pelo middleware de sessão
        # _check_api_key já resolveu a credencial (sessão OU API key de usuário)
        # antes do handler — aqui só resta reportar quem é o usuário.
        if self._current_user is not None:
            u = self._current_user
            self._json(200, {
                "ok": True,
                "user": {"id": u.id, "username": u.username, "email": u.email},
                "via": self._auth_via or "session",
                "role": self._role(),
            })
            return
        raise APIError(401, "não autenticado")

    # -- Conta do usuário logado (dashboard do usuário) ---------------------

    def _user_store_or_503(self) -> Any:
        store = self.api._user_store
        if store is None:
            raise APIError(503, "auth não configurado")
        return store

    def account_password(self) -> None:
        """POST /account/password — troca a PRÓPRIA senha (exige a atual).

        Body: {"current_password": ..., "new_password": ...}. Com a troca
        feita, TODAS as sessões da conta são encerradas — força novo login em
        todos os aparelhos, inclusive o de quem trocou.
        """
        store = self._user_store_or_503()
        if self._current_user is None:
            raise APIError(401, "não autenticado")
        data = self._read_json()
        current = str(data.get("current_password") or "")
        new = str(data.get("new_password") or "").strip()
        try:
            store.change_password(self._current_user.id, current, new)
        except AuthError as exc:
            raise APIError(exc.status, str(exc))
        sessions_killed = store.logout_all(self._current_user.id)
        log.info(
            "Senha trocada — sessões encerradas",
            user=self._current_user.username,
            sessoes=int(sessions_killed),
        )
        self._json(200, {
            "ok": True,
            "sessions_closed": int(sessions_killed),
            "message": "Senha trocada. Entre novamente com a nova senha.",
        })

    def account_api_key(self) -> None:
        """POST /account/api-key — rotaciona a PRÓPRIA API key.

        A antiga deixa de valer na hora (app/curl que a usavam recebem 401
        até atualizarem a chave). """
        store = self._user_store_or_503()
        if self._current_user is None:
            raise APIError(401, "não autenticado")
        new_key = store.rotate_api_key(self._current_user.id)
        log.info(
            "API key rotacionada pelo usuário",
            user=self._current_user.username,
        )
        self._json(200, {"ok": True, "api_key": new_key})

    # -- Admin — gestão de contas (papel admin, 403 para os demais) ---------

    def _require_admin(self) -> None:
        """403 para quem NÃO é admin (dono pela OD_API_KEY/sessão própria).

        Com auth desligada (dev local sem api_key), o papel resolve admin —
        preserva o uso local sem bloquear o painel.
        """
        if self._role() != "admin":
            log.warn(
                "Acesso admin negado",
                autenticado=(
                    self._current_user.username
                    if self._current_user is not None else "-"
                ),
                path=urlsplit(self.path).path,
            )
            raise APIError(403, "acesso_negado")

    def _admin_store(self) -> Any:
        self._require_admin()
        return self._user_store_or_503()

    def admin_users(self) -> None:
        """GET /admin/users — lista contas com uso real (admin).

        Junto de cada conta: sessões ativas e o MESMO agregado de histórico
        que o /history/{user_id}/stats devolve para cada balde — inclusive
        baldes legados sem conta (app, web, ids do Telegram), porque quem
        conversa sem login também ocupa o banco.
        """
        store = self._admin_store()
        orch = self.api.orchestrator
        hist_stats = (
            orch.history.stats() if orch is not None and orch.history is not None
            else {"per_user": {}}
        )
        per_user = hist_stats.get("per_user", {})
        users = []
        for row in store.list_users():
            uid = row["username"]
            usage = per_user.get(uid, {})
            users.append({
                "id": row["id"],
                "username": uid,
                "email": row["email"],
                "created_at": row["created_at"],
                "sessions": store.count_sessions(row["id"]),
                "messages": usage.get("messages", 0),
                "conversations": usage.get("conversations", 0),
                # A UI usa para inibir reset/remoção da conta do dono.
                "owner": self._is_owner_username(uid),
            })
        # Baldes sem conta (app/web/Telegram legado) — visíveis para o admin
        # decidir limpar, e para o total de mensagens bater com o banco.
        orfaos = sorted(
            (name for name in per_user if name not in {
                u["username"] for u in users
            }),
        )
        buckets = [
            {
                "user_id": name,
                "messages": per_user.get(name, {}).get("messages", 0),
            }
            for name in orfaos
        ]
        self._json(200, {
            "ok": True,
            "users": users,
            "legacy_buckets": buckets,
            "total": len(users),
        })

    def _admin_target(self, username: str) -> tuple[Any, Any]:
        """Resolve a conta alvo do admin. 404 quando não existe.

        O dono NÃO pode ser alvo: é a conta da OD_API_KEY — removê-la/resetar
        por engano derrubaria o operador de fora do painel.
        """
        store = self._admin_store()
        target = store.get_user_by_username(unquote(username).strip())
        if target is None:
            raise APIError(404, "usuario_inexistente")
        if self._is_owner_username(target.username):
            raise APIError(403, "dono_nao_removivel")
        return store, target

    def admin_reset_password(self, username: str) -> None:
        """POST /admin/users/{username}/password — reset da senha pelo admin.

        Body: {"new_password": ...}. Sem a senha atual (admin não tem): o
        reset é para "esqueci minha senha", não para troca do dia a dia. Mata
        todas as sessões da conta — token antigo não continua valendo.
        """
        store, target = self._admin_target(username)
        data = self._read_json()
        new = str(data.get("new_password") or "").strip()
        if len(new) < 6:
            raise APIError(400, "senha_deve_ter_pelo_menos_6_caracteres")
        store._db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(new), target.id),
        )
        sessions_killed = store.logout_all(target.id)
        log.info(
            "Senha resetada pelo admin",
            alvo=target.username,
            sessoes=int(sessions_killed),
        )
        self._json(200, {
            "ok": True,
            "user": target.username,
            "sessions_closed": int(sessions_killed),
        })

    def admin_delete_user(self, username: str) -> None:
        """DELETE /admin/users/{username} — remove a conta (admin).

        Sessões e vínculo do Telegram morrem junto. O histórico de conversas
        NÃO é apagado aqui: balde é separado e o admin usa o botão de
        limpar histórico quando quiser removê-lo também.
        """
        store, target = self._admin_target(username)
        store.delete_user(target.id)
        log.info("Conta removida pelo admin", alvo=target.username)
        self._json(200, {"ok": True, "user": target.username})

    def supervision(self) -> None:
        """GET /supervision — estado dos loops do núcleo (quedas e reinícios).

        Cada loop do modo all é isolado pelo launcher (`_supervise`): uma
        falha não derruba o core. Este endpoint expõe o MESMO estado que o
        check "loops" do /health degrada e que a sonda `_check_loops` do
        notifier alerta — para o app mostrar sem depender do Telegram.

        `ok=false` e `status=degraded` significam "loop caiu dentro da
        janela" (o core segue de pé); passada a janela, volta a ok sozinho.
        """
        registro = get_supervision()
        loops = registro.evaluate()
        degradados = [item["name"] for item in loops if item["degraded"]]
        self._json(200, {
            "ok": not degradados,
            "status": "degraded" if degradados else "up",
            "window_s": registro.degraded_window_s,
            "degraded": degradados,
            "restarts": sum(int(item["restarts"]) for item in loops),
            "loops": loops,
            "ts": time.time(),
        })

    def push_test(self) -> None:
        """POST /push/test — notificação de teste para todos os aparelhos.

        Body opcional: {"title": str, "body": str}. Responde 503 quando o
        push está desligado (sem credencial) — é o teste de ponta a ponta.
        """
        push = self._push_service()
        if not push.enabled:
            raise APIError(
                503, f"push_desligado: {push.sender.reason or 'sem credencial'}"
            )
        data = self._read_json()
        result = push.test(
            str(data.get("title") or "Teste OD"),
            str(data.get("body") or "Push funcionando 🎉"),
        )
        self._json(200, {"ok": bool(result.get("ok")), **result})

    def transcribe(self) -> None:
        handler = self.api.config.stt
        if handler is None:
            raise APIError(
                501,
                "STT não configurado — transcrição real é a Fase 6.3 "
                "(tools/audio/stt.py)",
            )
        data = self._read_json()
        audio_b64 = data.get("audio_b64")
        if not audio_b64:
            raise APIError(400, "audio_b64_obrigatorio")
        try:
            audio = base64.b64decode(audio_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise APIError(400, "audio_b64_invalido") from exc
        text = handler(audio) or ""
        self._json(200, {"ok": bool(text), "text": text})

    def tts(self) -> None:
        handler = self.api.config.tts
        if handler is None:
            raise APIError(
                501,
                "TTS não configurado — síntese real é a Fase 6.4 "
                "(tools/audio/tts.py)",
            )
        data = self._read_json()
        text = str(data.get("text") or "").strip()
        if not text:
            raise APIError(400, "text_obrigatorio")
        audio = handler(text)
        if not audio:
            raise APIError(502, "sintese_falhou")
        self._json(
            200,
            {
                "ok": True,
                "audio_b64": base64.b64encode(audio).decode("ascii"),
                "bytes": len(audio),
            },
        )

    def _historico_existe(self, uid: str) -> bool:
        """True quando o `user_id` é uma CONTA ou um balde com mensagens.

        404 é só para nome que **não é de ninguém** (`/history/jonas` digitado
        errado). Conta recém-criada responde 200 com zero mensagens — e também
        quem acabou de apagar o próprio histórico (a conta existe) —, senão a
        tela de histórico vazio viraria erro.

        Sem `UserStore` (dev local) não há como dizer que um nome é de alguém:
        o comportamento antigo (sempre 200) permanece.
        """
        store = self.api._user_store
        if store is None:
            return True
        try:
            if store.get_user_by_username(uid) is not None:
                return True
        except Exception:  # pragma: no cover — store indisponível
            return True
        orch = self.api.orchestrator
        if orch is None or orch.history is None:  # pragma: no cover — 501 antes
            return True
        return bool(orch.history.stats(user_id=uid).get("per_user"))

    def history_delete(self, user_id: str) -> None:
        orch = self.api.orchestrator
        if orch is None or orch.history is None:
            raise APIError(501, "historico_indisponivel")
        uid = self._check_owner(user_id)
        if not self._historico_existe(uid):
            raise APIError(404, "historico_inexistente")
        removed = orch.history.clear(uid)
        self._json(
            200,
            {"ok": True, "user_id": uid, "removed": removed},
        )

    def _registry_store_or_503(self) -> Any:
        """RegistryStore ou 503 (banco de peças desligado)."""
        self._require_admin()
        store = self.api._registry
        if store is None:
            raise APIError(503, "registry_indisponivel")
        return store

    def admin_registry_create(self) -> None:
        """POST /admin/registry — cadastra peça no Registro Mestre (dono).

        Body: {"name": str (obrig.), "kind": "exclusiva"|"publica",
        "collection"?: str, "engraved_code"?: str, "price_brl"?: float,
        "notes"?: str}. Gera o public_id canônico (OD-PROD-AAAA-NNNN).
        """
        store = self._registry_store_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        try:
            item = store.create(
                name=data.get("name", ""),
                kind=data.get("kind", ""),
                collection=data.get("collection"),
                engraved_code=data.get("engraved_code"),
                price_brl=data.get("price_brl"),
                notes=data.get("notes"),
            )
        except ValueError as exc:
            raise APIError(400, str(exc))
        self._json(201, {"ok": True, "peca": item})

    def admin_registry_list(self) -> None:
        """GET /admin/registry — lista todas as peças (dono; com preço)."""
        store = self._registry_store_or_503()
        itens = store.list_all()
        self._json(200, {"ok": True, "total": len(itens), "pecas": itens})

    def admin_registry_update(self, public_id: str) -> None:
        """PUT /admin/registry/{public_id} — atualiza uma peça (dono).

        Body: campos de whitelist (name, collection, kind, status,
        price_brl, owner_username, notes, engraved_code). Status
        "registrada" exige dono (owner_username) — posse por QR.
        """
        store = self._registry_store_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        try:
            item = store.update(public_id, **data)
        except ValueError as exc:
            raise APIError(400, str(exc))
        if item is None:
            raise APIError(404, "peca_inexistente")
        self._json(200, {"ok": True, "peca": item})

    def admin_registry_delete(self, public_id: str) -> None:
        """DELETE /admin/registry/{public_id} — remove uma peça (dono).

        Limpeza de cadastros (ex.: peças de teste) — a remoção some também
        da consulta pública.
        """
        store = self._registry_store_or_503()
        if not store.delete(public_id):
            raise APIError(404, "peca_inexistente")
        self._json(200, {"ok": True, "removida": str(public_id).strip().upper()})

    def admin_registry_photo(self, public_id: str) -> None:
        """POST /admin/registry/{public_id}/photo — envia a foto da peça (dono).

        Body: {"image_b64": "<base64 ou data URI>", "mime": "image/jpeg"}.
        Tamanho máximo 6 MB de binário (o painel já reduz para ~700-900 px
        no navegador antes de enviar). Substitui a foto anterior.
        """
        store = self._registry_store_or_503()
        data = self._read_json(max_bytes=9 * 1024 * 1024)
        b64 = str(data.get("image_b64") or "")
        if "," in b64 and b64.strip().startswith("data:"):
            b64 = b64.split(",", 1)[1]  # data:image/jpeg;base64,XXXX
        if not b64:
            raise APIError(400, "image_b64_obrigatorio")
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception as exc:
            raise APIError(400, "base64_invalido") from exc
        try:
            store.save_photo(public_id, raw, data.get("mime", ""))
        except ValueError as exc:
            raise APIError(
                404 if str(exc) == "peca_inexistente" else 400, str(exc)
            )
        self._json(200, {"ok": True,
                         "photo": f"/registry/{str(public_id).strip().upper()}/photo"})

    def admin_registry_chat_delete(self, public_id: str, msg_id: str) -> None:
        """DELETE /admin/registry/{public_id}/chat/{msg_id} — moderação (dono)."""
        store = self._registry_store_or_503()
        try:
            mid = int(msg_id)
        except ValueError as exc:
            raise APIError(400, "msg_id_invalido") from exc
        if store.get(public_id) is None:
            raise APIError(404, "peca_inexistente")
        if not store.chat_delete(public_id, mid):
            raise APIError(404, "mensagem_inexistente")
        self._json(200, {"ok": True, "removida": mid})

    def admin_cache_prune(self) -> None:
        """POST /admin/cache/prune — saneia o cache LLM (admin/dono).

        Body: {"dry_run"?: bool, "keys"?: [str, ...]}
        - Sem `keys`: varre a tabela e remove entradas de FALHA (respostas
          com etiqueta de log [CRIT]/[WARN]/..., vazias ou truncadas) — as
          "respostas de cache sem nexo" que renasciam a cada repetição.
        - Com `keys`: remove exatamente as chaves passadas (poda cirúrgica).
        dry_run=true devolve o que SERIA removido, sem tocar nos dados.
        """
        orch = self.api.orchestrator
        cache = orch.cache if orch is not None else None
        if cache is None:
            raise APIError(503, "cache_indisponivel")
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        dry_run = bool(data.get("dry_run", False))
        keys = data.get("keys")
        database = getattr(cache, "_database", None)
        if keys is not None:
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise APIError(400, "keys_deve_ser_lista_de_strings")
            targets = [(k, "", "", "chave informada") for k in keys]
        elif database is not None:
            rows = database.query(
                "SELECT key, response FROM llm_cache", (), limit=100000
            )
            targets = []
            for r in rows or []:
                resp = str(r.get("response") or "")
                reason = _cache_failure_reason(resp)
                if reason:
                    targets.append((r["key"], resp, "", reason))
        elif isinstance(getattr(cache, "_entries", None), dict):
            # Modo JSON: varre as entradas em memória/disco.
            targets = []
            for key, entry in list(cache._entries.items()):
                resp = str(getattr(entry, "response", "") or "")
                reason = _cache_failure_reason(resp)
                if reason:
                    targets.append((key, resp, "", reason))
        else:
            raise APIError(501, "cache_json_sem_varredura")
        removed = 0
        details = []
        for key, preview, _profile, reason in targets:
            details.append({"key": key, "motivo": reason,
                            "resposta": preview[:80]})
            if not dry_run and key:
                if database is not None:
                    database.execute(
                        "DELETE FROM llm_cache WHERE key = ?", (key,)
                    )
                elif isinstance(getattr(cache, "_entries", None), dict):
                    with cache._lock:
                        cache._entries.pop(key, None)
                        cache._persist()
                removed += 1
        self._json(
            200,
            {
                "ok": True,
                "dry_run": dry_run,
                "total_varrido": len(targets) if keys is None else None,
                "removidas": removed if not dry_run else 0,
                "candidatas": len(targets),
                "detalhes": details[:200],
            },
        )

    # --- Sessão de desenvolvimento on-demand (2026-10-08) -----------------

    #: CLIs aceitas no seletor do painel (mesmas opções do `--cli` do runner).
    SESSAO_CLIS = ("auto", "freebuff", "opencode", "kilo")

    def admin_dev_sessao(self) -> None:
        """POST /admin/dev/sessao — ativa/para UMA sessão de desenvolvimento.

        Body: {"acao": "ativar"|"parar", "cli"?: "auto"|"freebuff"|"opencode"|"kilo"}

        `ativar` exige ideia no txt.txt (400 `sem_ideia`), nenhuma sessão
        viva (409 `sessao_ativa`), uma CLI válida (400 `cli_invalida`) e que
        a ideia NÃO tenha sido implementada antes (409 `ja_implementado`,
        com `commit`/`ts`/`motivo` no corpo para o painel oferecer a limpeza
        do txt.txt); spawna
        `orquestrador.py --sessao` com cwd na raiz e stdout em
        logs/dev_sessao.log. `start_new_session=True` desanexa o processo:
        a sessão sobrevive a um restart do od-core, e Parar derruba o GRUPO
        inteiro (runner + CLI), não só o pai.
        """
        self._require_admin()
        data = self._read_json()
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        acao = data.get("acao")
        if acao == "ativar":
            self._sessao_ativar(data)
        elif acao == "parar":
            self._sessao_parar()
        else:
            raise APIError(400, "acao_invalida")

    def _sessao_ativar(self, data: dict) -> None:
        estado = _ler_json_caminho(SESSAO_ESTADO_FILE)
        if estado.get("ativo") and _pid_sessao_vivo(int(estado.get("pid") or 0)):
            raise APIError(409, "sessao_ativa")
        # A ideia vem do txt.txt — o canal onde o dono anota as atualizações
        # (decisão dele de 08/10; o pedido.txt e a fila saíram do sistema).
        try:
            ideia = self.IDEIAS_FILE.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            ideia = ""
        if not ideia:
            raise APIError(400, "sem_ideia")
        # Mesma ideia de uma sessão já CONCLUÍDA → não roda de novo: o dono
        # é avisado (409 com o commit/data) e pode limpar o txt.txt.
        entrada = ideia_ja_implementada(ideia)
        if entrada is not None:
            log.warn(
                "Ativação recusada — ideia já implementada",
                commit=entrada.get("commit") or "",
                ts=entrada.get("ts") or "",
            )
            raise APIError(409, "ja_implementado", extra={
                "commit": str(entrada.get("commit") or ""),
                "ts": str(entrada.get("ts") or ""),
                "motivo": str(entrada.get("motivo") or ""),
            })
        cli = data.get("cli") or "auto"
        if not isinstance(cli, str) or cli not in self.SESSAO_CLIS:
            raise APIError(400, "cli_invalida")

        comando = [
            sys.executable, str(REPO_ROOT / "orquestrador.py"),
            "--sessao", "--cli", cli,
        ]
        try:
            SESSAO_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SESSAO_LOG_FILE, "ab") as log_handle:
                processo = subprocess.Popen(  # noqa: S603 — comando fixo da casa
                    comando,
                    cwd=str(REPO_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as erro:
            raise APIError(500, "falha_ao_iniciar_sessao") from erro

        _gravar_json_caminho(SESSAO_ESTADO_FILE, {
            "ativo": True,
            "pid": processo.pid,
            "cli": cli,
            "status": "preparando",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ideia_preview": ideia[:2000],
            "testes": "",
            "diff": "",
            "commit": "",
            "motivo": "",
        })
        log.info(
            "Sessão de desenvolvimento ativada",
            pid=processo.pid, cli=cli, chars=len(ideia),
        )
        self._json(200, {
            "ok": True,
            "pid": processo.pid,
            "cli": cli,
            "status": "preparando",
        })

    def _sessao_parar(self) -> None:
        estado = _ler_json_caminho(SESSAO_ESTADO_FILE)
        if not estado.get("ativo"):
            raise APIError(409, "sessao_nao_ativa")
        pid = int(estado.get("pid") or 0)
        if _pid_sessao_vivo(pid):
            try:
                os.killpg(pid, signal.SIGTERM)  # grupo = runner + CLI
            except OSError as erro:
                raise APIError(500, "falha_ao_parar") from erro
        estado["ativo"] = False
        estado["status"] = "parado"
        estado["motivo"] = "parada_pelo_dono"
        _gravar_json_caminho(SESSAO_ESTADO_FILE, estado)
        log.info("Sessão de desenvolvimento parada pelo painel", pid=pid)
        self._json(200, {"ok": True, "pid": pid, "status": "parado"})

    def admin_dev_sessao_status(self) -> None:
        """GET /admin/dev/sessao — estado + log + caixa pendente do painel.

        Contrato: {ok, ativo, pid, cli, status, started_at, ideia_preview,
        analise, testes, diff, commit, motivo, caixa_pendente, log_tail}.
        Sessão cujo processo morreu sem registrar (crash/restart) é
        normalizada aqui — o painel nunca mente sobre "executando".
        """
        self._require_admin()
        estado = _ler_json_caminho(SESSAO_ESTADO_FILE)
        pid = int(estado.get("pid") or 0)
        if estado.get("ativo") and not _pid_sessao_vivo(pid):
            estado["ativo"] = False
            estado["status"] = "interrompida"
            estado["motivo"] = "processo_ausente"
            _gravar_json_caminho(SESSAO_ESTADO_FILE, estado)
        caixa = _ler_caixa_caminho(SESSAO_CAIXA_FILE)
        pendentes = [
            m for m in caixa
            if m.get("de") == "sistema"
            and m.get("tipo") == "pedir_autorizacao"
            and not m.get("respondida")
        ]
        resposta: dict[str, Any] = {
            "ok": True,
            "ativo": False,
            "status": "parada",
            "pid": None,
            "cli": "auto",
            "caixa_pendente": 0,
        }
        resposta.update(estado)
        resposta["caixa_pendente"] = len(pendentes)
        resposta["log_tail"] = _tail_log(SESSAO_LOG_FILE)
        self._json(200, resposta)

    # --- Caixa de desenvolvimento (autorização do dono) -------------------

    def admin_dev_caixa_status(self) -> None:
        """GET /admin/dev/caixa — mensagens sistema ↔ dono da sessão.

        O runner publica `pedir_autorizacao` quando a CLI emite o marcador
        [AUTORIZACAO]; o dono responde aqui (POST) e a sessão retoma.
        Contrato: {ok, mensagens, total, pendentes}.
        """
        self._require_admin()
        mensagens = _ler_caixa_caminho(SESSAO_CAIXA_FILE)
        pendentes = [
            m for m in mensagens
            if m.get("de") == "sistema"
            and m.get("tipo") == "pedir_autorizacao"
            and not m.get("respondida")
        ]
        self._json(200, {
            "ok": True,
            "mensagens": mensagens,
            "total": len(mensagens),
            "pendentes": len(pendentes),
        })

    def admin_dev_caixa_write(self) -> None:
        """POST /admin/dev/caixa — resposta/autorização do dono (texto novo).

        Body: {"texto": str (1..4000)}. O runner só conta mensagens NOVAS
        depois do pedido — a história nunca é re-enviada à CLI.
        """
        self._require_admin()
        data = self._read_json()
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        texto = data.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            raise APIError(400, "texto_obrigatorio")
        if len(texto) > SESSAO_CAIXA_MAX_CHARS:
            raise APIError(400, "texto_muito_longo")
        mensagens = _ler_caixa_caminho(SESSAO_CAIXA_FILE)
        if len(mensagens) > 500:  # teto anti-desborro do histórico
            mensagens = mensagens[-400:]
        mensagem = {
            "id": str(uuid.uuid4()),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "de": "dono",
            "tipo": "resposta",
            "texto": texto.strip(),
            "respondida": False,
        }
        mensagens.append(mensagem)
        _gravar_caixa_caminho(SESSAO_CAIXA_FILE, mensagens)
        log.info(
            "Resposta do dono na caixa de desenvolvimento",
            chars=len(texto),
            sessao_ativa=bool(_ler_json_caminho(SESSAO_ESTADO_FILE).get("ativo")),
        )
        self._json(200, {"ok": True, "mensagem": mensagem, "total": len(mensagens)})

    def admin_dev_caixa_clear(self) -> None:
        """DELETE /admin/dev/caixa — limpa o histórico da caixa (idempotente)."""
        self._require_admin()
        _gravar_caixa_caminho(SESSAO_CAIXA_FILE, [])
        log.info("Caixa de desenvolvimento limpa pelo painel admin")
        self._json(200, {"ok": True, "total": 0})

    # -- Canal de ideias (txt.txt) + Casa de Limitações (v1.13.0) ------------

    IDEIAS_FILE = Path("txt.txt")
    IDEIAS_MAX_CHARS = 20000  # mesmo teto do canal de pedidos

    def admin_ideias_status(self) -> None:
        """GET /admin/ideias — conteúdo do txt.txt (canal do DONO).

        O dono escreve ideias/pedidos de informação aqui (pelo painel do
        site ou do app); v1.13.0. Contrato: {ok, existe, conteudo, bytes}.
        """
        self._require_admin()
        caminho = self.IDEIAS_FILE
        if not caminho.is_file():
            self._json(200, {"ok": True, "existe": False, "conteudo": "", "bytes": 0})
            return
        bruto = caminho.read_text(encoding="utf-8", errors="replace")
        self._json(200, {
            "ok": True,
            "existe": True,
            "conteudo": bruto,
            "bytes": len(bruto.encode("utf-8")),
        })

    def admin_ideias_write(self) -> None:
        """PUT /admin/ideias — o dono escreve no txt.txt (substitui).

        Body: {"conteudo": str (0..20000 chars)} — vazio é válido (rascunho
        limpo). Escrita ATÔMICA (tmp + rename), padrão do canal de pedidos.
        """
        self._require_admin()
        data = self._read_json()
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        conteudo = data.get("conteudo")
        if not isinstance(conteudo, str):
            raise APIError(400, "conteudo_obrigatorio")
        if len(conteudo) > self.IDEIAS_MAX_CHARS:
            raise APIError(400, "conteudo_muito_longo")
        tmp = self.IDEIAS_FILE.with_suffix(".txt.tmp")
        try:
            tmp.write_text(conteudo, encoding="utf-8")
            tmp.replace(self.IDEIAS_FILE)
        except OSError as erro:
            raise APIError(500, "falha_ao_gravar") from erro
        log.info(
            "txt.txt gravado pelo painel admin", chars=len(conteudo)
        )
        self._json(200, {
            "ok": True,
            "bytes": len(conteudo.encode("utf-8")),
        })

    def admin_ideias_clear(self) -> None:
        """DELETE /admin/ideias — zera o txt.txt (idempotente)."""
        self._require_admin()
        tmp = self.IDEIAS_FILE.with_suffix(".txt.tmp")
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        try:
            self.IDEIAS_FILE.write_text("", encoding="utf-8")
        except OSError as erro:
            raise APIError(500, "falha_ao_limpar") from erro
        log.info("txt.txt zerado pelo painel admin")
        self._json(200, {"ok": True, "bytes": 0})

    def admin_limitacoes_status(self) -> None:
        """GET /admin/limitacoes — o que o sistema NÃO soube responder.

        Registro AUTOMÁTICO (core/limitacoes.py): fallback honesto esgotado
        e action de fastpath degradada. O dono lê aqui as candidatas a
        melhoria — o sistema percebendo as próprias limitações (v1.13.0).
        Contrato: {ok, existe, entradas: [{ts, motivo, pergunta}], total, bytes}.
        """
        self._require_admin()
        from core.limitacoes import ler_limitacoes
        self._json(200, ler_limitacoes())

    def admin_limitacoes_clear(self) -> None:
        """DELETE /admin/limitacoes — limpa o registro (idempotente)."""
        self._require_admin()
        from core.limitacoes import limpar_limitacoes
        self._json(200, limpar_limitacoes())

    def history_delete_message(self, user_id: str, message_id: str) -> None:
        """DELETE /history/{user_id}/messages/{message_id} — apaga UMA mensagem.

        Dono ou admin (mesmo gate do /history). A mensagem tem de pertencer
        ao balde do user_id — 404 caso contrário (não revela existência).
        Uso: remover do histórico uma resposta sem nexo (ex.: falha cacheada
        que o cache antigo guardou).
        """
        orch = self.api.orchestrator
        if orch is None or orch.history is None:
            raise APIError(501, "historico_indisponivel")
        uid = self._check_owner(user_id)
        try:
            mid = int(message_id)
        except ValueError:
            raise APIError(400, "message_id_invalido")
        removed = orch.history.delete_message(uid, mid)
        if not removed:
            raise APIError(404, "mensagem_inexistente")
        self._json(200, {"ok": True, "user_id": uid, "message_id": mid})

    def history_stats(self, user_id: str) -> None:
        orch = self.api.orchestrator
        if orch is None or orch.history is None:
            raise APIError(501, "historico_indisponivel")
        uid = self._check_owner(user_id)
        if not self._historico_existe(uid):
            raise APIError(404, "historico_inexistente")
        stats = orch.history.stats(user_id=uid)
        self._json(
            200,
            {"ok": True, "user_id": uid, "stats": stats},
        )

    def history_get(self, user_id: str) -> None:
        orch = self.api.orchestrator
        if orch is None or orch.history is None:
            raise APIError(501, "historico_indisponivel")
        uid = self._check_owner(user_id)
        if not self._historico_existe(uid):
            raise APIError(404, "historico_inexistente")
        query = parse_qs(urlsplit(self.path).query)
        profile = query.get("profile", ["auto"])[0].strip() or "auto"
        raw_limit = query.get("limit", ["50"])[0]
        try:
            limit = max(1, min(int(raw_limit), 200))
        except ValueError:
            limit = 50
        # Paginação por cursor: ?before=<id> devolve a página ANTERIOR (mensagens
        # mais antigas que o id), com has_more/oldest_id para encadear.
        before_raw = query.get("before", [""])[0].strip()
        before_id: Optional[int] = None
        if before_raw:
            try:
                before_id = int(before_raw)
            except ValueError:
                raise APIError(400, "before_invalido")
        has_page = hasattr(orch.history, "get_messages_page")
        if has_page:
            page = orch.history.get_messages_page(
                uid, profile=profile, limit=limit, before_id=before_id
            )
            messages = [m.to_dict() for m in page["messages"]]
            self._json(
                200,
                {
                    "ok": True,
                    "user_id": uid,
                    "profile": profile,
                    "messages": messages,
                    "total": len(messages),
                    "has_more": page["has_more"],
                    "oldest_id": page["oldest_id"],
                },
            )
            return
        msgs = orch.history.get_messages(uid, profile=profile, limit=limit)
        messages = [m.to_dict() for m in msgs]
        self._json(
            200,
            {
                "ok": True,
                "user_id": uid,
                "profile": profile,
                "messages": messages,
                "total": len(messages),
            },
        )

    def memory_search(self, user_id: str) -> None:
        # Dono ANTES da disponibilidade: não revela se o store existe para o
        # histórico de outra pessoa (403 precede o 501).
        uid = self._check_owner(user_id)
        vector = self.api.vector
        if vector is None:
            raise APIError(
                501,
                "memória vetorial não conectada (VectorStore) — RAG "
                "requer store_dir injetado",
            )
        query = parse_qs(urlsplit(self.path).query).get("q", [""])[0].strip()
        if not query:
            raise APIError(400, "q_obrigatorio")
        raw_top = parse_qs(urlsplit(self.path).query).get("top_k", ["3"])[0]
        try:
            top_k = max(1, min(int(raw_top), 20))
        except ValueError:
            top_k = 3
        results = vector.search(uid, query, top_k=top_k)
        self._json(
            200,
            {
                "ok": True,
                "user_id": uid,
                "query": query,
                "results": [
                    {
                        "doc_id": r.doc_id,
                        "text": r.text,
                        "score": round(r.score, 4),
                        "metadata": r.metadata,
                    }
                    for r in results
                ],
            },
        )

    def ws_chat(self) -> None:
        raise APIError(
            501,
            "WebSocket /ws/chat não implementado na camada stdlib — "
            "streaming token-a-token exige servidor assíncrono dedicado "
            "(decisão registrada na Fase 5.2)",
        )

    # -- Helpers internos ----------------------------------------------------

    def _providers(self) -> list[Any]:
        if self.api.orchestrator is None:
            return []
        return list(self.api.orchestrator.providers)

    def _provider_names(self) -> list[str]:
        return [
            getattr(p, "name", "") or type(p).__name__
            for p in self._providers()
        ]

    def _orch_snapshot(self) -> dict[str, Any]:
        orch = self.api.orchestrator
        if orch is None:
            return {"status": "degraded", "orchestrator": False}
        snapshot = orch.metrics.snapshot()
        snapshot["status"] = "up"
        snapshot["orchestrator"] = True
        return snapshot
