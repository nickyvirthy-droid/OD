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
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from tools.registry import ActionRegistry

from core.capabilities import OD_VERSION, capabilities_manifest
from core.logger import get_logger
from core.orchestrator import OrchestrationResult, Orchestrator
from core.supervision import get_supervision
from integrations.telegram.commands import (
    _classificar_risco,
    NIVEL_1_ADMIN,
    NIVEL_2_DESTRUTIVO,
)
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
PAGE_PATHS = frozenset({"/", "/chat", "/dashboard", "/site", "/site/{file}", "/auth/register", "/auth/login"})


class APIError(Exception):
    """Erro de API com status HTTP correspondente."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


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
    # Freio contra força bruta em POST /auth/login (integrations.api.auth
    # .LoginGuard). `login_guard` permite injetar uma instância (testes);
    # ausente = o servidor constrói uma a partir dos números abaixo.
    login_guard: Optional[Any] = None
    login_max_attempts: int = 5
    login_window_s: float = 300.0
    login_lockout_s: float = 900.0

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
    ("GET", "/chat", "chat_html", False),
    ("GET", "/metrics", "metrics_text", False),
    ("GET", "/site", "site_index", False),
    ("GET", "/site/{file}", "site_file", False),
    # Auth — sem auth (o handler valida internamente)
    ("POST", "/auth/register", "auth_register", False),
    ("POST", "/auth/login", "auth_login", False),
    ("POST", "/auth/logout", "auth_logout", True),
    ("GET", "/auth/me", "auth_me", True),
    # Dados protegidos
    ("GET", "/dashboard/stats", "dashboard_stats", True),
    ("GET", "/llms", "llms", True),
    ("GET", "/capabilities", "capabilities", True),
    ("GET", "/actions", "actions_catalog", True),
    ("POST", "/message", "message", True),
    ("POST", "/executa", "executa", True),
    ("POST", "/push/register", "push_register", True),
    ("POST", "/push/unregister", "push_unregister", True),
    ("POST", "/push/test", "push_test", True),
    ("GET", "/push/devices", "push_devices", True),
    ("GET", "/supervision", "supervision", True),
    ("POST", "/transcribe", "transcribe", True),
    ("POST", "/tts", "tts", True),
    ("DELETE", "/history/{user_id}", "history_delete", True),
    ("GET", "/history/{user_id}/stats", "history_stats", True),
    ("GET", "/memory/{user_id}/search", "memory_search", True),
    ("GET", "/ws/chat", "ws_chat", True),
]


def _compile_route(pattern: str) -> re.Pattern[str]:
    """Converte '/history/{user_id}/stats' em regex de fullmatch."""
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    return re.compile(regex + r"/?\Z")


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

_CHAT_PAGE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OmegaDrakon — Chat</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🐉</text></svg>">
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
    <a href="/site">🐉 OD</a>
    <span class="h-sep">|</span>
    <h1>Chat</h1>
  </div>
  <div class="h-right">
    <span id="transport" class="transport-badge"></span>
    <select id="profile" title="Perfil">
      <option value="auto">🤖 Auto</option>
      <option value="guardian">🐉 Nicky Virthy</option>
      <option value="regulus">⚖️ Regulus</option>
      <option value="luma">🌟 Luma</option>
      <option value="vox">📜 Vox</option>
      <option value="athenae">🏛️ Athenae</option>
      <option value="nyx">🌙 Nyx</option>
      <option value="nexus">🔗 Nexus</option>
    </select>
  </div>
</header>

<div id="gate">
  <div id="gate-login">
    <h2>🐉 Entrar no Chat</h2>
    <p>Faça login para conversar com o OmegaDrakon.</p>
    <input id="login-user" type="text" placeholder="Username" autocomplete="username">
    <input id="login-pass" type="password" placeholder="Senha" autocomplete="current-password">
    <div id="err"></div>
    <button id="enter">Entrar</button>
    <p class="gate-switch">Não tem conta? <a href="#" id="show-register">Registrar</a></p>
    <p class="gate-switch" style="font-size:0.75rem;color:var(--muted);">Ou use sua API key: <a href="#" id="show-apikey">Modo avançado</a></p>
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
</div>

<div id="chat" class="hidden">
  <div id="messages">
    <div class="welcome">
      <div class="icon">🐉</div>
      <h2>OmegaDrakon</h2>
      <p>Envie uma mensagem para começar a conversa.</p>
    </div>
  </div>
  <div id="composer">
    <input id="text" placeholder="Digite sua mensagem…" autocomplete="off">
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

function showGate(msg, errId) {
  if (msg) $(errId || "err").textContent = msg;
  gate.classList.remove("hidden");
  chat.classList.add("hidden");
}
function showChat() {
  gate.classList.add("hidden");
  chat.classList.remove("hidden");
  $("text").focus();
  tryConnectWs();
}
function setTransport(type) {
  const el = $("transport");
  el.className = "transport-badge active " + type;
  el.textContent = type === "ws" ? "⚡ Streaming" : "↔ REST";
}
function clearWelcome() {
  const w = $("messages").querySelector(".welcome");
  if (w) w.remove();
}
function addBubble(who, text, meta) {
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
  $("messages").scrollTop = $("messages").scrollHeight;
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
      const wsKey = key || "";
      ws.send(JSON.stringify({ type: "auth", api_key: wsKey, user_id: user_id }));
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

// --- Send ---
async function send() {
  const text = $("text").value.trim();
  if (!text || busy) return;
  busy = true; $("send").disabled = true; $("text").value = "";
  addBubble("user", text);
  const profile = $("profile").value;
  try {
    await sendWs(text, profile);
  } catch(e) {
    try { await sendRest(text, profile); } catch(e2) {
      if (e2.message !== "auth") addBubble("od", "Erro: " + e2.message, "API");
    }
  }
  busy = false; $("send").disabled = false; $("text").focus();
}

// --- Login ---
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
      if (resp.ok) { showChat(); return; }
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

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:
        # CORS preflight
        self.send_response(204)
        self._send_cors()
        self.send_header("Allow", "GET, POST, DELETE, OPTIONS")
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
            auth_exempt = route.path in {"/auth/register", "/auth/login"}
            if (route.auth or (self.api.config.auth_all and not page_shell and not auth_exempt)) \
                    and not self._check_api_key():
                return
            handler = getattr(self, route.handler)
            kwargs: dict[str, str] = dict(match.groupdict()) if match else {}
            handler(**kwargs)
        except APIError as exc:
            self.api.count_error()
            log.warn("API erro", status=exc.status, detail=exc.message)
            self._json(
                exc.status, {"ok": False, "error": exc.message}
            )
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
        return True

    # -- Helpers de corpo/resposta -------------------------------------------

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > self.api.config.max_body_bytes:
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
        # Shell estático SEM dados: métricas só via /dashboard/stats (chave)
        self._html(
            200,
            "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<title>Omega Drakon — Dashboard</title></head><body>"
            "<h1>🐉 Omega Drakon — Dashboard</h1>"
            "<p>Shell da interface (sem dados). Métricas estruturadas em "
            "<code>GET /dashboard/stats</code> — exige header "
            "<code>X-API-Key</code>.</p>"
            "</body></html>",
        )

    def chat_html(self) -> None:
        """Chat funcional: shell aberto + chave pedida UMA vez no navegador
        (sessionStorage) e usada nas chamadas a POST /message."""
        self._html(200, _CHAT_PAGE_HTML)

    def site_index(self) -> None:
        """Landing do site (index.html) em GET /site e /site/."""
        self._serve_site_file("index.html")

    def site_file(self, file: str) -> None:
        """Arquivo do site (ex.: OmegaDrakon.apk) em GET /site/{file}."""
        self._serve_site_file(unquote(file))

    def _serve_site_file(self, name: str) -> None:
        """Serve um arquivo de site/ com streaming (o APK tem ~50MB).

        Segurança: resolve() + is_relative_to() antes de abrir — GET
        /site/../segredo ou /site/etc/passwd nunca escapa do diretório.
        Sem auth (landing pública no tailnet); Cache-Control no-store
        garante que o APK novo sempre baixa por inteiro.

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
    ) -> OrchestrationResult:
        if self.api.orchestrator is None:
            raise APIError(503, "orchestrator_indisponivel")
        return await self.api.orchestrator.process(
            user_id, profile, text,
            system_prompt=system_prompt, session_id=session_id,
        )

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
        if not text:
            raise APIError(400, "text_obrigatorio")
        profile = str(data.get("profile") or DEFAULT_PROFILE).strip()
        if profile not in self.api.config.profiles:
            raise APIError(400, f"perfil_desconhecido: {profile}")
        if profile == "auto":
            profile = DEFAULT_PROFILE  # auto = OD escolhe (hoje o padrão)
        system_prompt = str(data.get("system_prompt") or "")
        session_id = str(data.get("session_id") or f"api:{user_id}")
        result = asyncio.run(
            self._process_message(
                user_id, profile, text, system_prompt, session_id
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
        if _classificar_risco(action_name) == 2 and not data.get("confirm"):
            raise APIError(
                422, f"confirmacao_obrigatoria: {action_name} é destrutiva; "
                     "reenvie com confirm=true"
            )
        result = asyncio.run(registry.execute(
            action_name, params=params, role="admin",
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
            })
            return
        raise APIError(401, "não autenticado")

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

    def history_delete(self, user_id: str) -> None:
        orch = self.api.orchestrator
        if orch is None or orch.history is None:
            raise APIError(501, "historico_indisponivel")
        uid = unquote(user_id)
        removed = orch.history.clear(uid)
        self._json(
            200,
            {"ok": True, "user_id": uid, "removed": removed},
        )

    def history_stats(self, user_id: str) -> None:
        orch = self.api.orchestrator
        if orch is None or orch.history is None:
            raise APIError(501, "historico_indisponivel")
        uid = unquote(user_id)
        stats = orch.history.stats(user_id=uid)
        self._json(
            200,
            {"ok": True, "user_id": uid, "stats": stats},
        )

    def memory_search(self, user_id: str) -> None:
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
        uid = unquote(user_id)
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
