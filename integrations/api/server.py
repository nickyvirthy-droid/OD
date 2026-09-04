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
import re
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from core.logger import get_logger
from core.orchestrator import OrchestrationResult, Orchestrator

__signature__ = "OD // CORE"

if TYPE_CHECKING:
    from memory.vector import VectorStore

log = get_logger("omega.integrations.api")

# Perfis do agente (mesma lista do legado Nicky; Profile Manager é o 6.5).
DEFAULT_PROFILES = (
    "auto", "guardian", "regulus", "luma", "vox", "athenae", "nyx",
)
DEFAULT_PROFILE = "guardian"

API_NAME = "Omega Drakon REST API"

# Shells de página (HTML estático, sem dados) — com page_shells_public,
# continuam abertos para o navegador carregar a UI mesmo com auth_all.
PAGE_PATHS = frozenset({"/chat", "/dashboard"})


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
    ("GET", "/dashboard/stats", "dashboard_stats", True),
    ("GET", "/llms", "llms", True),
    ("POST", "/message", "message", True),
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
<title>Omega Drakon — Chat</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, sans-serif; background: #0d1117;
         color: #e6edf3; display: flex; flex-direction: column; height: 100vh; }
  header { padding: 12px 18px; background: #161b22; border-bottom: 1px solid #30363d;
           display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  header h1 { font-size: 16px; margin: 0; }
  header span { color: #8b949e; font-size: 13px; }
  #messages { flex: 1; overflow-y: auto; padding: 18px; display: flex;
              flex-direction: column; gap: 10px; }
  .bubble { max-width: 78%; padding: 10px 14px; border-radius: 12px;
            white-space: pre-wrap; word-wrap: break-word; line-height: 1.45; }
  .user { align-self: flex-end; background: #1f6feb; }
  .od { align-self: flex-start; background: #21262d; border: 1px solid #30363d; }
  .meta { font-size: 11px; color: #8b949e; margin-top: 4px; }
  #composer { display: flex; gap: 8px; padding: 12px 18px; background: #161b22;
              border-top: 1px solid #30363d; }
  input, select, button { font: inherit; padding: 9px 12px; border-radius: 8px;
              border: 1px solid #30363d; background: #0d1117; color: #e6edf3; }
  #text { flex: 1; }
  button { background: #238636; border-color: #238636; cursor: pointer;
           font-weight: 600; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  #gate { display: flex; flex-direction: column; gap: 14px; margin: auto;
          width: min(420px, 92vw); }
  #gate h2 { margin: 0; }
  #gate p { color: #8b949e; margin: 0; font-size: 14px; }
  .hidden { display: none !important; }
  .hint { color: #8b949e; font-size: 12px; }
  #err { color: #f85149; font-size: 13px; min-height: 18px; }
</style>
</head>
<body>
<header>
  <h1>🐉 Omega Drakon — Chat</h1>
  <span id="who"></span>
  <select id="profile" title="Perfil da resposta">
    <option value="auto">auto</option>
    <option value="guardian" selected>guardian</option>
    <option value="regulus">regulus</option>
    <option value="luma">luma</option>
    <option value="vox">vox</option>
    <option value="athenae">athenae</option>
    <option value="nyx">nyx</option>
  </select>
</header>

<div id="gate">
  <h2>🔑 Chave da API</h2>
  <p>Este chat conversa com o Omega Drakon pelo <code>POST /message</code>,
     que exige a chave <code>X-API-Key</code>. Informe a chave uma vez — ela
     fica só nesta aba (sessionStorage) e nunca vai para a URL.</p>
  <input id="key" type="password" placeholder="Sua OD_API_KEY" autocomplete="off">
  <div id="err"></div>
  <button id="enter">Entrar no chat</button>
</div>

<div id="chat" class="hidden">
  <div id="messages">
    <div class="bubble od">👋 Olá! Sou a interface do Omega Drakon.
      Pergunte qualquer coisa — cada mensagem passa pelo pipeline do Orchestrator.</div>
  </div>
  <div id="composer">
    <input id="text" placeholder="Digite sua mensagem…" autocomplete="off">
    <button id="send">Enviar</button>
  </div>
</div>

<script>
  const $ = (id) => document.getElementById(id);
  const gate = $("gate"), chat = $("chat");
  let key = sessionStorage.getItem("od_api_key") || "";
  let busy = false;
  const user_id = "web";

  function applyKey() {
    sessionStorage.setItem("od_api_key", key);
    $("who").textContent = "usuário: " + user_id + " · perfil da resposta abaixo";
  }
  function showGate(msg) {
    $("err").textContent = msg || "";
    gate.classList.remove("hidden");
    chat.classList.add("hidden");
  }
  function showChat() {
    gate.classList.add("hidden");
    chat.classList.remove("hidden");
    $("text").focus();
  }
  function addBubble(who, text, meta) {
    const div = document.createElement("div");
    div.className = "bubble " + who;
    div.textContent = text;
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = meta || "";
    div.appendChild(m);
    $("messages").appendChild(div);
    $("messages").scrollTop = $("messages").scrollHeight;
  }

  $("enter").onclick = async () => {
    key = $("key").value.trim();
    if (!key) { $("err").textContent = "Informe a chave."; return; }
    // valida a chave com uma chamada leve antes de liberar
    const probe = await fetch("/llms", { headers: { "X-API-Key": key } });
    if (!probe.ok) { $("err").textContent = "Chave inválida (" + probe.status + ")."; return; }
    applyKey();
    showChat();
  };

  async function send() {
    const text = $("text").value.trim();
    if (!text || busy) return;
    busy = true;
    $("send").disabled = true;
    $("text").value = "";
    addBubble("user", text);
    const t0 = Date.now();
    try {
      const resp = await fetch("/message", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": key
        },
        body: JSON.stringify({
          user_id: user_id,
          profile: $("profile").value,
          text: text
        })
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 401) {
        key = "";
        sessionStorage.removeItem("od_api_key");
        showGate("Chave expirada ou inválida — informe novamente.");
        return;
      }
      if (!resp.ok) {
        addBubble("od", "Erro " + resp.status + ": " + (data.error || "falha"), "API");
        return;
      }
      const ms = ((Date.now() - t0) / 1000).toFixed(1);
      const meta = (data.profile ? data.profile + " · " : "") +
                   (data.route || "") + " · " + ms + "s";
      addBubble("od", data.message || "(sem resposta)", meta);
    } catch (e) {
      addBubble("od", "Falha de rede: " + e.message, "API");
    } finally {
      busy = false;
      $("send").disabled = false;
      $("text").focus();
    }
  }

  $("send").onclick = send;
  $("text").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  if (key) { applyKey(); showChat(); }
  else { showGate(""); $("key").focus(); }
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
    """Dispatch dos 17 endpoints + JSON/HTML, auth e rate limit."""

    protocol_version = "HTTP/1.1"
    server_version = "OmegaDrakon/0.19"
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
            if (route.auth or (self.api.config.auth_all and not page_shell)) \
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
        """Header X-API-Key. Escreve 401 e retorna False quando negado."""
        expected = self.api.config.api_key
        if not expected:
            # auth_all sem chave configurada = nega tudo (força o operador
            # a definir OD_API_KEY antes de expor na LAN)
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
            return True  # auth desligada (uso local/dev explícito)
        provided = self.headers.get("X-API-Key", "")
        if not provided or not hmac.compare_digest(provided, expected):
            self._json(
                401,
                {"ok": False, "error": "unauthorized",
                 "hint": "envie X-API-Key"},
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
        self._json(
            200,
            {
                "name": API_NAME,
                "signature": __signature__,
                "version": "0.19.0",
                "endpoints": len(ROUTES),
                "orchestrator": self.api.orchestrator is not None,
                "uptime_s": int(time.time() - self.api.started_at),
            },
        )

    def health(self) -> None:
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
        user_id = str(data.get("user_id") or "").strip()
        text = str(data.get("text") or "").strip()
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
