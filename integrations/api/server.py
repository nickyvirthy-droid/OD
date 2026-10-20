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
import io
import json
import mimetypes
import os
import queue as queue_mod
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
_APP_VERSION_CODE = 2079  # versionCode cru do APK publicado (v1.43.0+2079)
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
# Páginas INTERNAS do dono (habilitar/autorizar o Google). Saíram de site/
# em 2026-10-10: eram alcançáveis por qualquer um via /site/google_auth.html
# e vazavam IP da rede local, o número do projeto Google, o client_id e o
# caminho do token. Continuam existindo — só que atrás do gate de dono.
DEFAULT_SITE_ADMIN_DIR = Path(__file__).resolve().parents[2] / "site_admin"

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
     "/registry", "/registry/collections", "/registry/{codigo}",
     "/registry/{codigo}/photo", "/registry/{codigo}/chat"}
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
    # Fila de downloads resumable (Parte D do NOMAD, 2026-10-14):
    # core.downloads.DownloadQueue — worker em thread própria. None =
    # fila desligada (as rotas /admin/downloads* respondem 503).
    downloads: Optional[Any] = None
    # Auto-update de modelos/conteúdo (Parte E do NOMAD, 2026-10-14):
    # core.auto_update.AutoUpdateService — janela/cool-off/cap/auto-disable.
    # None = serviço fora (as rotas /admin/auto-update* respondem 503).
    auto_update: Optional[Any] = None
    # Registro de ferramentas/skills estilo Supply Depot (Parte F do NOMAD,
    # 2026-10-15): tools/supply_depot.py — pré-voo (conflito/versão/tamanho),
    # rollback e customização preservada. None = depot fora (as rotas
    # /admin/ferramentas* respondem 503).
    supply_depot: Optional[Any] = None
    # Ferramentas do stack Nômade (DECISÃO FINAL, 2026-10-15):
    # core.nomad_tools.NomadToolsMonitor — sonda HTTP das 9 do compose
    # (Kiwix, Stirling PDF, CyberChef...). None = monitor fora (o bloco
    # nomad_tools some do /dashboard/stats).
    nomad_tools: Optional[Any] = None
    # Métricas do ProactiveNotifier (pedido do dono, 2026-10-16):
    # integrations.notifier.NotifierMetrics — ticks, alertas emitidos ×
    # bloqueados pelo anti-spam e erros. None = notifier fora
    # (OD_NOTIFIER_ENABLED=0) e o bloco notifier some do /dashboard/stats.
    notifier: Optional[Any] = None
    # Backups automáticos (TODO §3.6, ordem do dono 2026-10-16): lista de
    # core.backup.BackupService, UM POR PERFIL — `estado` (diário, .env +
    # data/ sem capturas) e `capturas` (semanal, com as fotos/vídeos).
    # None/[] = backups fora (OD_BACKUP=0) e o bloco backup some do
    # /dashboard/stats.
    backups: Optional[list[Any]] = None
    # Off-site pelo canal PRIVADO do Telegram (core/offsite.py, 20/10):
    # envia os tars locais para fora de casa. None = off-site fora
    # (OD_OFFSITE=0 ou sem OD_OFFSITE_CHAT) e o bloco offsite some do
    # /dashboard/stats.
    offsite: Optional[Any] = None
    # URL pública absoluta (Etapa 4): base do QR de posse — o QR precisa
    # de URL com esquema/hospedeiro (o site em si é relativo). Padrão =
    # hostname do Funnel; o launcher pode sobrescrever (OD_PUBLIC_URL).
    public_url: str = "https://nicky-server.tail1b1f51.ts.net"
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
    # /app/version, v. AUTH_EXEMPT_PATHS). /registry (lista) alimenta a
    # loja do site; /registry/posse é o REGISTRO DO COMPRADOR (conta).
    ("GET", "/registry", "registry_list", False),
    # Ciclos de coleção (frente NV, 16/10) ANTES de /{codigo} — o matcher
    # pega a primeira rota que casa, senão "collections" viraria um código.
    ("GET", "/registry/collections", "registry_collections", False),
    ("GET", "/registry/{codigo}", "registry_verify", False),
    ("POST", "/registry/posse", "registry_posse", True),
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
    # Preferências do perfil (TODO §3.8: tema claro/escuro sincronizado):
    # a MESMA preferência serve app, site e painel — o valor é validado no
    # servidor (allowlist) porque orienta a UI dos três.
    ("GET", "/profile/preferences", "profile_preferences_get", True),
    ("PUT", "/profile/preferences", "profile_preferences_put", True),
    # Conta do usuário logado (dashboard do usuário)
    ("POST", "/account/password", "account_password", True),
    ("POST", "/account/api-key", "account_api_key", True),
    # Admin — handlers exigem papel admin (403 para os demais)
    ("GET", "/admin/users", "admin_users", True),
    # Páginas INTERNAS do dono (2026-10-10): antes eram /site/google_*.html,
    # alcançáveis sem credencial pelo Funnel e vazavam IP local + client_id
    # do projeto. Agora ficam em site_admin/ e o handler valida o dono.
    # auth=False na rota porque a navegação é de navegador (link do painel);
    # o gate real é o _require_owner_page() dentro do handler.
    ("GET", "/admin/google/apis", "admin_google_apis", False),
    ("GET", "/admin/google/auth", "admin_google_auth", False),
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
    # Ciclos de coleção (frente NV): abrir ciclo e encerrar PARA SEMPRE
    # (PROTOCOLO_NV: "uma vez Encerrada, nunca é reeditada"). Não existe
    # DELETE/PUT de coleção — a imutabilidade é por ausência de rota.
    ("POST", "/admin/registry/collections", "admin_registry_collection_create", True),
    ("POST", "/admin/registry/collections/{nome}/encerrar",
     "admin_registry_collection_close", True),
    ("PUT", "/admin/registry/{public_id}", "admin_registry_update", True),
    ("DELETE", "/admin/registry/{public_id}", "admin_registry_delete", True),
    ("POST", "/admin/registry/{public_id}/photo", "admin_registry_photo", True),
    # Etapa 4 (2026-10-15): código de posse (QR) — gerar/regenerar e o
    # SVG do QR para imprimir no cartão da compra.
    ("POST", "/admin/registry/{public_id}/posse", "admin_registry_posse", True),
    ("GET", "/admin/registry/{public_id}/posse/qr", "admin_registry_qr", True),
    ("DELETE", "/admin/registry/{public_id}/chat/{msg_id}",
     "admin_registry_chat_delete", True),
    # Fila de downloads resumable (Parte D do NOMAD, 2026-10-14) —
    # retry com backoff, progresso ao vivo (SSE), dedup e cancelamento.
    # /events ANTES de /{job_id}: o matcher pega a primeira rota que casa.
    ("POST", "/admin/downloads", "admin_downloads_create", True),
    ("GET", "/admin/downloads", "admin_downloads_list", True),
    ("GET", "/admin/downloads/events", "admin_downloads_events", True),
    ("GET", "/admin/downloads/{job_id}", "admin_downloads_detail", True),
    ("POST", "/admin/downloads/{job_id}/cancel", "admin_downloads_cancel", True),
    ("DELETE", "/admin/downloads/{job_id}", "admin_downloads_delete", True),

    # Auto-update de modelos/conteúdo (Parte E do NOMAD, 2026-10-14) —
    # estado por alvo, dry-run do pipeline (o MESMO caminho do ciclo) e
    # religação manual de um alvo auto-desligado.
    ("GET", "/admin/auto-update", "admin_auto_update_get", True),
    ("POST", "/admin/auto-update/dry-run", "admin_auto_update_dry_run", True),
    ("POST", "/admin/auto-update/reset", "admin_auto_update_reset", True),
    # Registro de ferramentas/skills estilo Supply Depot (Parte F do NOMAD,
    # 2026-10-15) — catálogo persistente: instala/atualiza com pré-voo,
    # customização do dono (PUT), rollback por versão e desinstalação.
    ("GET", "/admin/ferramentas", "admin_ferramentas_list", True),
    ("POST", "/admin/ferramentas", "admin_ferramentas_create", True),
    ("PUT", "/admin/ferramentas/{id}", "admin_ferramentas_update", True),
    ("POST", "/admin/ferramentas/{id}/rollback",
     "admin_ferramentas_rollback", True),
    ("DELETE", "/admin/ferramentas/{id}", "admin_ferramentas_delete", True),
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


#: Parâmetros de rota que podem conter barra (caminho de arquivo do site).
#: Ex.: GET /site/avatares/nicky.png — subpastas de galeria criadas a partir
#: da pasta analise/ do dono (2026-10-12). Os demais parâmetros são ids de
#: um único segmento ([^/]+). A trava de path traversal continua no handler
#: (_serve_site_file: resolve() + is_relative_to()).
_ROUTE_PARAMS_COM_BARRA = frozenset({"file"})


def _compile_route(pattern: str) -> re.Pattern[str]:
    """Converte '/history/{user_id}/stats' em regex de fullmatch."""
    def _param(m: re.Match[str]) -> str:
        nome = m.group(1)
        classe = r".+" if nome in _ROUTE_PARAMS_COM_BARRA else r"[^/]+"
        return f"(?P<{nome}>{classe})"

    regex = re.sub(r"\{(\w+)\}", _param, pattern)
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
# Tema claro/escuro do painel (TODO §3.8, 2026-10-16)
# ---------------------------------------------------------------------------
# O painel tem TRÊS páginas com CSS inline próprio (/dashboard, /admin,
# /chat) e a paleta já vive duplicada nelas. Em vez de triplicar de novo a
# paleta clara e o comportamento, os dois vivem AQUI e são injetados no
# HTML antes de servir (`_com_tema`): uma fonte, três páginas.
#
# Diferente do SITE (que resolve "segue o aparelho" por
# `@media prefers-color-scheme` e funciona sem JS), o painel é 100% JS
# (toda a página é montada por fetch) — aqui o JS resolve a preferência e
# grava o tema CONCRETO em `data-theme`, então uma única regra clara basta.
_TEMA_PAINEL_CSS = """<style>
  /* Paleta clara do painel (o tema escuro é o :root da própria página).
     Mesma dualidade do site: o APARELHO pede (quem nunca escolheu, ou
     escolheu "segue o aparelho") ou a escolha explícita grava
     data-theme="light" (o JS cuida disso). */
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) { __OD_TEMA_VARS__ }
  }
  :root[data-theme="light"] { __OD_TEMA_VARS__ }
  /* Onde o âmbar era TEXTO (ilegível no claro), escurece. */
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) header a:hover,
    :root:not([data-theme="dark"]) #badge b,
    :root:not([data-theme="dark"]) section h2,
    :root:not([data-theme="dark"]) .h-brand a:hover,
    :root:not([data-theme="dark"]) .transport-badge.rest { color: #92400E; }
  }
  :root[data-theme="light"] header a:hover,
  :root[data-theme="light"] #badge b,
  :root[data-theme="light"] section h2,
  :root[data-theme="light"] .h-brand a:hover,
  :root[data-theme="light"] .transport-badge.rest { color: #92400E; }
  #odTema {
    width: 34px; height: 34px; border-radius: 8px; margin-left: 10px;
    background: transparent; border: 1px solid var(--border);
    color: var(--text); cursor: pointer; font-size: 1rem; line-height: 1;
    display: grid; place-items: center;
  }
  #odTema:hover { border-color: var(--accent); }
</style>"""

# As variáveis ficam num só lugar e entram nas DUAS portas (aparelho ou
# escolha) — o CSS acima é montado a partir daqui, sem duas listas
# paralelas que possam divergir.
_TEMA_PAINEL_VARS = """color-scheme: light;
    --bg: #F4F6FB; --bg2: #FFFFFF; --bg3: #E9EEF7;
    --text: #131722; --muted: #5B6478; --border: #D5DCEA;
    --accent: #F59E0B;            /* âmbar da marca (botões seguem com texto preto) */
    --accent-glow: rgba(245,158,11,0.25);
    --ok: #0F766E; --err: #B91C1C; --warn: #92400E;
    --user-bg: #DCE8FF; --od-bg: #EEF1F8;"""
_TEMA_PAINEL_CSS = _TEMA_PAINEL_CSS.replace("__OD_TEMA_VARS__", _TEMA_PAINEL_VARS)

_TEMA_PAINEL_JS = """(function () {
  'use strict';
  var CHAVE = 'od_theme', VALIDOS = ['system', 'light', 'dark'];
  var ICONES = { system: '🌗', light: '☀️', dark: '🌙' };
  var ROTULOS = { system: 'Tema: segue o aparelho', light: 'Tema: claro', dark: 'Tema: escuro' };
  var CICLO = { system: 'light', light: 'dark', dark: 'system' };

  function ler() {
    try {
      var v = localStorage.getItem(CHAVE);
      return VALIDOS.indexOf(v) >= 0 ? v : 'system';
    } catch (e) { return 'system'; }
  }
  function resolvido(pref) {
    if (pref === 'light' || pref === 'dark') return pref;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  /* Nenhum clique pode cair numa tela igual à anterior (o dono relatou
     "às vezes não funciona" em 16/10): "escuro → segue o aparelho" num
     aparelho escuro não muda nada. Se o próximo estado resolve para a
     MESMA cor do atual, pula para o seguinte — todo clique pinta. Os 3
     estados continuam válidos (o app tem o rádio completo). */
  function proximoTema(pref) {
    var atual = resolvido(pref);
    var proximo = CICLO[pref] || 'system';
    if (resolvido(proximo) === atual) proximo = CICLO[proximo] || 'system';
    return proximo;
  }
  function aplicar(pref) {
    var raiz = document.documentElement;
    raiz.setAttribute('data-theme', resolvido(pref));
    raiz.style.colorScheme = resolvido(pref);
    var b = document.getElementById('odTema');
    if (!b) return;
    b.textContent = ICONES[pref] || ICONES.system;
    b.setAttribute('aria-label', ROTULOS[pref] || ROTULOS.system);
    b.title = (ROTULOS[pref] || '') + ' (toque para trocar)';
  }
  function cabecalhos() {
    var h = {};
    try {
      var token = localStorage.getItem('od_session_token');
      var chave = localStorage.getItem('od_api_key');
      if (token) h['Authorization'] = 'Bearer ' + token;
      if (chave) h['X-API-Key'] = chave;
    } catch (e) {}
    return h;
  }
  // Best-effort: sem credencial (ou sem rede) só o local vale.
  function salvar(pref) {
    var h = cabecalhos();
    if (!h['Authorization'] && !h['X-API-Key']) return;
    try {
      h['Content-Type'] = 'application/json';
      fetch('/profile/preferences', {
        method: 'PUT', headers: h, body: JSON.stringify({ theme: pref })
      }).catch(function () {});
    } catch (e) {}
  }
  // O PERFIL é a verdade da conta; o localStorage é o cache (sem pisca).
  function sincronizar() {
    var h = cabecalhos();
    if (!h['Authorization'] && !h['X-API-Key']) return;
    try {
      fetch('/auth/me', { headers: h })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          var doServidor = d && d.preferences && d.preferences.theme;
          if (VALIDOS.indexOf(doServidor) < 0) return;
          if (doServidor === ler()) return;
          try { localStorage.setItem(CHAVE, doServidor); } catch (e) {}
          aplicar(doServidor);
        }).catch(function () {});
    } catch (e) {}
  }
  function montar() {
    if (document.getElementById('odTema')) return;
    var cabecalho = document.querySelector('header');
    if (!cabecalho) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.id = 'odTema';
    cabecalho.appendChild(b);
  }
  function iniciar() {
    aplicar(ler());
    montar();
    var b = document.getElementById('odTema');
    if (b) b.addEventListener('click', function () {
      var proximo = proximoTema(ler());
      try { localStorage.setItem(CHAVE, proximo); } catch (e) {}
      aplicar(proximo);
      salvar(proximo);
    });
    sincronizar();
    try {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function () {
        if (ler() === 'system') aplicar('system');
      });
    } catch (e) {}
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else { iniciar(); }
})();"""


_FORMATO_ORION_CSS = """<style>
  /* od-formato-orion-css — fonte única, injetada pelo _com_tema (mesma
     arquitetura do tema): /dashboard (todos os usuários), /admin
     (dono) e /chat (inócuo, sem markup) falam a mesma tela. */
  /* --- Painel no FORMATO ÓRION (referência do dono, analisada 17/10) ---
     Herói de saudação + faixa de KPIs + mini-painéis vivos (relógio e
     saúde), tudo lendo as MESMAS fontes das seções (/auth/me, /health,
     /dashboard/stats, /actions, /app/version) — nenhuma fonte paralela.
     Tinta só nas variáveis (--bg/--text/...), então funciona no claro e
     no escuro sem paleta duplicada (§ tema). */
  .od-hero {
    display: flex; gap: 18px; align-items: center; flex-wrap: wrap;
    background: linear-gradient(135deg, var(--bg3), var(--bg2));
    border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px;
  }
  .od-hero-marca {
    width: 54px; height: 54px; border-radius: 14px; flex: none;
    display: grid; place-items: center; font-size: 1.7rem;
    background: var(--bg); border: 1px solid var(--border);
  }
  .od-hero-tag {
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.14em;
    color: var(--muted); display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  }
  .od-hero-tag b { color: var(--accent); }
  .od-ola { font-size: 1.35rem; font-weight: 800; margin-top: 4px; }
  .od-hero-data { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }
  .od-hero-chips { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .od-ponto {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--ok); margin-right: 6px;
  }
  .od-ponto.err { background: var(--err); }
  .od-vivos { display: flex; gap: 10px; margin-left: auto; flex-wrap: wrap; }
  .od-vivo {
    min-width: 134px; background: var(--bg); border: 1px solid var(--border);
    border-radius: 12px; padding: 10px 14px;
  }
  .od-vivo .k {
    font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted);
  }
  .od-vivo .v {
    font-size: 1.05rem; font-weight: 700; margin-top: 2px;
    font-variant-numeric: tabular-nums;
  }
  .od-kpis {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px;
  }
  .od-kpi {
    display: flex; gap: 12px; align-items: center;
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 14px;
  }
  .od-kpi-ico {
    width: 38px; height: 38px; border-radius: 10px; flex: none;
    display: grid; place-items: center; font-size: 1.1rem; color: #fff;
  }
  .od-ico-azul { background: linear-gradient(135deg, #2563EB, #3B82F6); }
  .od-ico-laranja { background: linear-gradient(135deg, #D97706, #F59E0B); }
  .od-ico-roxo { background: linear-gradient(135deg, #7C3AED, #A78BFA); }
  .od-ico-verde { background: linear-gradient(135deg, #059669, #34D399); }
  .od-kpi .n { font-size: 1.3rem; font-weight: 800; line-height: 1.1; }
  .od-kpi .l {
    font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted);
  }
  /* pills do cabeçalho: o /dashboard não tem .pill próprio — escopo
     no .od-hero para não brigar com as páginas. */
  .od-hero .pill {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 0.72rem; background: var(--bg3); border: 1px solid var(--border);
  }
  .od-hero .pill.ok { color: var(--ok); }
  .od-hero .pill.err { color: var(--err); }
  /* --- Menu lateral (2026-10-20, formato Órion do dono) ------------------
     A referência (Sistema Órion, capturas de 16/10) traz barra fixa à
     esquerda: marca em cima, itens embaixo e botão de RECOLHER. Injetado
     pelo _FORMATO_ORION_JS (fonte única, mesma arquitetura do tema):
     /dashboard e /admin recebem; /chat mantém o próprio cabeçalho. Tinta
     só nas variáveis do tema → claro e escuro sem paleta duplicada. */
  .od-lateral { display: none; }
  @media (min-width: 1024px) {
    html.od-com-lateral {
      --od-lat-w: 236px;
      padding-left: var(--od-lat-w);
      transition: padding-left .2s;
    }
    html.od-com-lateral.od-lateral-recolhido { --od-lat-w: 68px; }
    html.od-com-lateral .od-lateral {
      display: flex; flex-direction: column; gap: 10px;
      position: fixed; top: 0; bottom: 0; left: 0; z-index: 120;
      width: var(--od-lat-w); padding: 14px 12px; overflow-y: auto;
      background: var(--bg2); border-right: 1px solid var(--border);
      transition: width .2s;
    }
    .od-lateral-marca { display: grid; place-items: center; }
    .od-lateral-marca img { width: 30px; height: 30px; }
    .od-lateral-btn {
      width: 34px; height: 34px; border-radius: 8px; flex: none; margin-left: auto;
      background: transparent; border: 1px solid var(--border);
      color: var(--text); cursor: pointer; font-size: 1rem; line-height: 1;
      display: grid; place-items: center;
      transition: border-color .18s, background .18s;
    }
    .od-lateral-btn:hover { border-color: var(--accent); background: var(--bg3); }
    .od-lateral-links a {
      display: block; padding: 10px 6px; color: var(--text);
      font-size: .78rem; letter-spacing: .09em; text-transform: uppercase;
      text-decoration: none; border-bottom: 1px solid var(--border);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .od-lateral-links a:last-child { border-bottom: 0; }
    .od-lateral-links a:hover { color: var(--accent); }
    /* Recolhida: a marca sai e os rótulos encolhem (sem ícones no kit —
       texto curto centrado, nada de inventar iconografia). */
    html.od-lateral-recolhido .od-lateral-marca { display: none; }
    html.od-lateral-recolhido .od-lateral-links a {
      text-align: center; font-size: .66rem; padding: 10px 2px;
    }
  }
</style>"""


_FORMATO_ORION_JS = """(function () {
  'use strict';
  /* od-formato-orion-js — fonte única, injetada pelo _com_tema. Saudação por
     período, relógio de São Paulo, pill de estado e KPIs — tudo lendo as
     MESMAS fontes de sempre (health / version / actions / stats). Sem
     resposta o campo fica "—" (nunca verde de mentira); falha daqui nunca
     derruba a página (try/catch). O /admin repassa os dados do loadSystem
     via pintar(); o /dashboard (todos os usuários) busca sozinho. */
  var nome = "";

  function saudacao() {
    var h = new Date().getHours();
    return h < 5 ? "Boa madrugada" : h < 12 ? "Boa manhã" : h < 18 ? "Boa tarde" : "Boa noite";
  }

  function fmtUptime(s) {
    if (s == null) return "—";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
        m = Math.floor((s % 3600) / 60);
    return (d ? d + "d " : "") + (h ? h + "h " : "") + m + "m";
  }

  function cabecalhos() {
    var h = {};
    try {
      var t = localStorage.getItem("od_session_token");
      var k = localStorage.getItem("od_api_key");
      if (t) h["Authorization"] = "Bearer " + t;
      else if (k) h["X-API-Key"] = k;
    } catch (e) {}
    return h;
  }

  function relogio() {
    var el = document.getElementById("odRelogio");
    if (!el) return;
    el.textContent = new Date().toLocaleTimeString("pt-BR", {
      timeZone: "America/Sao_Paulo", hour12: false
    });
  }

  function pintar(health, stats, acoes) {
    try {
      var ola = document.getElementById("odOla");
      if (!ola) return;  // página sem o cabeçalho (ex.: chat)
      ola.textContent = saudacao() + (nome ? ", " + nome : "");
      document.getElementById("odData").textContent =
        new Date().toLocaleDateString("pt-BR", {
          weekday: "long", day: "2-digit", month: "long", year: "numeric"
        });
      var vivo = !!(health && health.ok);
      var on = document.getElementById("odOn");
      on.className = "pill" + (vivo ? " ok" : " err");
      on.innerHTML = '<span class="od-ponto' + (vivo ? "" : " err") + '"></span>' +
        (vivo ? "ONLINE" : "DEGRADADO");
      var up = (health && health.uptime_s != null) ? health.uptime_s : null;
      if (stats && stats.uptime_s != null) up = stats.uptime_s;
      var upTxt = fmtUptime(up);
      document.getElementById("kpiUptime").textContent = upTxt;
      var chipUp = document.getElementById("odChipUptime");
      if (chipUp) chipUp.textContent = "uptime " + upTxt;
      document.getElementById("kpiAcoes").textContent =
        acoes && acoes.count != null ? acoes.count : "—";
      var nt = stats && stats.nomad_tools;
      document.getElementById("kpiStack").textContent = nt ? nt.up + "/" + nt.total : "—";
      var chipSt = document.getElementById("odChipStack");
      if (chipSt) chipSt.textContent = nt ? "stack " + nt.up + "/" + nt.total : "stack —";
      var ch = (health && health.checks) || {};
      var nomes = Object.keys(ch);
      var bons = nomes.filter(function (n) { return ch[n] && ch[n].ok; }).length;
      document.getElementById("kpiChecks").textContent =
        nomes.length ? bons + "/" + nomes.length : "—";
      var saude = document.getElementById("odSaude");
      if (nomes.length && bons === nomes.length) {
        saude.textContent = "Tudo verde";
      } else if (nomes.length) {
        saude.textContent = bons + " ok · " + (nomes.length - bons) + " alerta";
      }
      document.getElementById("odSaudeDet").textContent =
        nomes.length + " checks · " + ((health && health.status) || "?");
    } catch (e) { /* enfeite vivo: a falha dele não derruba a página */ }
  }

  function buscarJson(url, auth) {
    return fetch(url, auth ? { headers: cabecalhos() } : undefined)
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function atualizar() {
    if (!document.getElementById("odOla")) return Promise.resolve();
    return Promise.all([
      buscarJson("/health"),                // pública
      buscarJson("/dashboard/stats", true), // dono: uptime/stack (403 vira null)
      buscarJson("/actions", true)          // catálogo (contagem)
    ]).then(function (r) { pintar(r[0], r[1], r[2]); });
  }

  function versao() {
    buscarJson("/app/version").then(function (d) {
      if (!d || !d.version) return;
      var el = document.getElementById("odVer");
      if (el) el.textContent = "v" + d.version;
      var build = document.getElementById("odChipBuild");
      if (build) build.textContent = "build " + (d.version_code || "");
    });
  }

  /* --- Menu lateral (2026-10-20, formato Órion do dono) ------------------
     Barra fixa à esquerda (marca, itens, ☰ de recolher) como na
     referência. Montada AQUI, na fonte única: /dashboard e /admin têm
     #odOla e recebem; /chat sai cedo no iniciar() e mantém o próprio
     cabeçalho. Itens sempre presentes: Painel, Chat, Site — o Admin só
     entra para papel admin (o quemAmI da página repassa o papel em
     odFormato.nome). Estado recolhido no localStorage, como no site. */
  function lateralMontar() {
    if (document.getElementById("odLateral")) return;  // idempotente
    var itens = [
      { href: "/dashboard", rot: "Painel" },
      { href: "/chat", rot: "Chat" },
      { href: "/site", rot: "Site" }
    ];
    var aside = document.createElement("aside");
    aside.id = "odLateral";
    aside.className = "od-lateral";
    aside.setAttribute("aria-label", "Menu lateral");
    var marca = '<div class="od-lateral-topo">' +
      '<a class="od-lateral-marca" href="/dashboard">' +
      '<img src="/site/simbolo_minimo.png" alt="OD"></a>' +
      '<button class="od-lateral-btn" aria-label="Recolher menu lateral">' +
      '&#9776;</button></div><div class="od-lateral-links">';
    var html = marca;
    for (var i = 0; i < itens.length; i++) {
      html += '<a href="' + itens[i].href + '">' + itens[i].rot + "</a>";
    }
    aside.innerHTML = html + "</div>";
    document.body.appendChild(aside);
    document.documentElement.classList.toggle("od-com-lateral", true);
    var recolhido = false;
    try { recolhido = localStorage.getItem("od_lateral") === "recolhido"; }
    catch (e) {}
    document.documentElement.classList.toggle("od-lateral-recolhido", recolhido);
    var btn = aside.querySelector(".od-lateral-btn");
    if (btn) btn.addEventListener("click", function () {
      var agora = !document.documentElement
        .classList.contains("od-lateral-recolhido");
      document.documentElement.classList.toggle("od-lateral-recolhido", agora);
      try {
        localStorage.setItem("od_lateral", agora ? "recolhido" : "aberto");
      } catch (e) {}
    });
  }

  function lateralAdmin() {
    var l = document.getElementById("odLateral");
    if (!l || l.querySelector('a[href="/admin"]')) return;
    var links = l.querySelector(".od-lateral-links");
    if (!links) return;
    var a = document.createElement("a");
    a.setAttribute("href", "/admin");
    a.textContent = "Admin";
    links.appendChild(a);
  }

  // Interface para a página: o /admin chama pintar() no refresh do
  // loadSystem; quem logar entrega o nome (o cabeçalho chama pelo nome) —
  // e o papel, que decide o item Admin do menu lateral.
  window.odFormato = {
    nome: function (n, papel) {
      if (!n) return;
      nome = n;
      var ola = document.getElementById("odOla");
      if (ola) ola.textContent = saudacao() + ", " + nome;
      if (papel === "admin") lateralAdmin();
    },
    pintar: pintar,
    atualizar: atualizar
  };

  // Início adiado até DOMContentLoaded: assim a PÁGINA consegue declarar
  // a bandeira odFormatoGerenciado antes (o /admin declara — o
  // loadSystem dele já busca health/stats/actions e repassa via
  // pintar(); o herói não repete as mesmas requests). Relógio e versão
  // continuam de graça; a busca dupla não.
  function iniciar() {
    if (!document.getElementById("odOla")) return;  // ex.: chat
    lateralMontar();
    relogio();
    setInterval(relogio, 1000);
    versao();
    if (!window.odFormatoGerenciado) atualizar();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else { iniciar(); }
})();"""


def _com_tema(html: str) -> str:
    """Injeta a paleta clara + o tema na página do painel.

    O JS entra DENTRO do `<script>` que a página já tem (e não como um
    segundo bloco): a guarda de sintaxe do painel (`node --check` em
    tests/test_api.py) recorta do primeiro `<script>` ao último
    `</script>` — um bloco novo no meio quebraria a extração e a guarda
    passaria a medir outra coisa.

    Idempotente pela marca `odTema`: chamada duas vezes não duplica nada.
    """
    if "odTema" in html:
        return html
    # Formato Órion (v1.39.2): CSS ANTES do JS e cada injeção com a
    # PRÓPRIA marca. Marca compartilhada entrei errado na v1.39.1: o
    # JS (comentado com a marca) entrava primeiro e o guarda do CSS
    # achava que o CSS já estava lá — o herói aparecia pelado ("texto
    # comum", reporte do dono em 17/10).
    if "od-formato-orion-css" not in html and "</head>" in html:
        html = html.replace("</head>", _FORMATO_ORION_CSS + "\n</head>", 1)
    if "</head>" in html:
        html = html.replace("</head>", _TEMA_PAINEL_CSS + "\n</head>", 1)
    marca = "<script>"
    pos = html.find(marca)
    if pos >= 0 and "</script>" in html[pos:]:
        corte = pos + len(marca)
        html = (html[:corte] + "\n" + _TEMA_PAINEL_JS + "\n"
                + _FORMATO_ORION_JS + "\n" + html[corte:])
    return html


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
  <!-- Formato Órion (v1.39.1, pedido do dono 17/10): o MESMO cabeçalho do
       /admin no painel de TODOS — CSS/JS vêm da fonte única injetada pelo
       _com_tema. Aqui só o que é público (saúde, versão, relógio, KPIs de
       sistema); as seções administrativas continuam no /admin. -->
  <div class="od-hero">
    <div class="od-hero-marca"><img src="/site/simbolo_minimo.png" alt="OD" style="width:30px;height:30px"></div>
    <div>
      <div class="od-hero-tag">Omega Drakon · <b id="odVer">…</b>
        <span class="pill" id="odOn"><span class="od-ponto"></span>CARREGANDO</span></div>
      <div class="od-ola" id="odOla">Boa tarde</div>
      <div class="od-hero-data" id="odData">—</div>
      <div class="od-hero-chips">
        <span class="pill" id="odChipUptime">uptime —</span>
        <span class="pill" id="odChipStack">stack —</span>
      </div>
    </div>
    <div class="od-vivos">
      <div class="od-vivo">
        <div class="k">Horário</div>
        <div class="v" id="odRelogio">—</div>
        <div class="k">São Paulo · GMT-3</div>
      </div>
      <div class="od-vivo">
        <div class="k">Saúde do sistema</div>
        <div class="v" id="odSaude">—</div>
        <div class="k" id="odSaudeDet">carregando…</div>
      </div>
    </div>
  </div>
  <div class="od-kpis">
    <div class="od-kpi"><div class="od-kpi-ico od-ico-azul">⚡</div>
      <div><div class="n" id="kpiAcoes">—</div><div class="l">Actions prontas</div></div></div>
    <div class="od-kpi"><div class="od-kpi-ico od-ico-laranja">🧰</div>
      <div><div class="n" id="kpiStack">—</div><div class="l">Stack Nômade</div></div></div>
    <div class="od-kpi"><div class="od-kpi-ico od-ico-roxo">🩺</div>
      <div><div class="n" id="kpiChecks">—</div><div class="l">Checks de saúde</div></div></div>
    <div class="od-kpi"><div class="od-kpi-ico od-ico-verde">⏱</div>
      <div><div class="n" id="kpiUptime">—</div><div class="l">Uptime do núcleo</div></div></div>
  </div>
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
  if (window.odFormato) window.odFormato.nome(data.user.username, role);
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
  <!-- Formato Órion (referência analisada do dono, 17/10): herói de
       saudação + faixa de KPIs. O JS do script único preenche tudo a
       partir das MESMAS fontes das seções abaixo. -->
  <div class="od-hero">
    <div class="od-hero-marca"><img src="/site/simbolo_minimo.png" alt="OD" style="width:30px;height:30px"></div>
    <div>
      <div class="od-hero-tag">Omega Drakon · <b id="odVer">…</b>
        <span class="pill" id="odOn"><span class="od-ponto"></span>CARREGANDO</span></div>
      <div class="od-ola" id="odOla">Boa tarde, dono</div>
      <div class="od-hero-data" id="odData">—</div>
      <div class="od-hero-chips">
        <span class="pill" id="odChipBuild">build —</span>
        <span class="pill" id="odChipUptime">uptime —</span>
        <span class="pill" id="odChipStack">stack —</span>
      </div>
    </div>
    <div class="od-vivos">
      <div class="od-vivo">
        <div class="k">Horário</div>
        <div class="v" id="odRelogio">—</div>
        <div class="k">São Paulo · GMT-3</div>
      </div>
      <div class="od-vivo">
        <div class="k">Saúde</div>
        <div class="v" id="odSaude">—</div>
        <div class="k" id="odSaudeDet">carregando…</div>
      </div>
    </div>
  </div>
  <div class="od-kpis">
    <div class="od-kpi"><div class="od-kpi-ico od-ico-azul">⚡</div>
      <div><div class="n" id="kpiAcoes">—</div><div class="l">Actions prontas</div></div></div>
    <div class="od-kpi"><div class="od-kpi-ico od-ico-laranja">🧰</div>
      <div><div class="n" id="kpiStack">—</div><div class="l">Stack Nômade</div></div></div>
    <div class="od-kpi"><div class="od-kpi-ico od-ico-roxo">🩺</div>
      <div><div class="n" id="kpiChecks">—</div><div class="l">Checks de saúde</div></div></div>
    <div class="od-kpi"><div class="od-kpi-ico od-ico-verde">⏱</div>
      <div><div class="n" id="kpiUptime">—</div><div class="l">Uptime do núcleo</div></div></div>
  </div>
  <section>
    <h2>Visão do sistema (System Overview)
      <span class="pill" id="sys-resumo">…</span></h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Um card por subsistema — tudo lido das MESMAS fontes de sempre
      (/health · /supervision · /dashboard/stats · /actions), sem busca
      nova. Bloco sem dado, o campo fica "—"; verde só com dado existindo.
    </p>
    <div class="grid" id="sys"></div>
    <details><summary>Loops do núcleo (/supervision)</summary><pre id="loops">—</pre></details>
    <details><summary>Métricas do orquestrador (/dashboard/stats)</summary><pre id="metrics">—</pre></details>
    <details><summary>Stack Nômade — ferramentas ativas (DECISÃO FINAL)</summary><pre id="nomadTools">—</pre></details>
    <div class="row" style="margin-top:8px">
      <button id="btn-refresh">↻ Atualizar</button>
      <span class="muted msg" id="sys-msg"></span>
    </div>
  </section>

  <section>
    <h2>Google (Drive · Agenda · Gmail)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Páginas internas de configuração. Saíram do site público em 2026-10-10
      (vazavam IP local, o número do projeto e o client_id) — agora exigem a
      sua sessão de dono. O link abre já com o token da sessão.
    </p>
    <div class="row">
      <a id="g-apis" href="/admin/google/apis">⚙️ Habilitar as 3 APIs</a>
      <a id="g-auth" href="/admin/google/auth" style="margin-left:12px">🔑 Autorizar o Google</a>
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
      <input id="reg-nome" placeholder="Nome (ex.: Anel Abissal)" style="width:180px">
      <select id="reg-frente" title="Frente do ID (FRENTE-TIPO-AAAA-NNNN)" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px;font-size:0.85rem">
        <option value="NV" selected>NV (joias)</option>
        <option value="PROD">PROD</option>
        <option value="SYS">SYS</option>
        <option value="NUC">NUC</option>
        <option value="SUP">SUP</option>
      </select>
      <select id="reg-tipo" title="Tipo do ID" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px;font-size:0.85rem">
        <option value="SJ">SJ (semi-joia)</option>
        <option value="PE" selected>PE (peça especial)</option>
        <option value="COD">COD</option>
        <option value="MAN">MAN</option>
        <option value="AUTH">AUTH</option>
        <option value="COL">COL</option>
        <option value="EMB">EMB</option>
        <option value="CART">CART</option>
      </select>
      <input id="reg-colecao" title="Frente NV: só entra peça em coleção com ciclo ABERTO (crie abaixo)"
        placeholder="Coleção (NV: obrigatória/aberta)" style="width:170px">
      <select id="reg-kind" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px;font-size:0.85rem">
        <option value="exclusiva">exclusiva</option>
        <option value="publica">pública</option>
      </select>
      <input id="reg-codigo" placeholder="Cód. gravado (auto se vazio)" style="width:170px">
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

    <h3 style="margin-top:16px">Coleções (ciclo fechado — frente NV)</h3>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Regra do Protocolo NV: <b>coleção é ciclo fechado — uma vez encerrada,
      nunca é reeditada</b> (não existe reabrir, renomear nem apagar). Peça NV
      só nasce em coleção com ciclo <b>aberto</b>. Encerrar é para sempre:
      confirme só quando a série estiver de fato fechada.
    </p>
    <div class="row">
      <input id="col-nome" placeholder="Nova coleção (ex.: DRAKONIS)" style="width:200px">
      <button id="col-add" style="border-color:var(--accent);color:var(--accent)">＋ Abrir ciclo</button>
      <span class="muted msg" id="col-msg"></span>
    </div>
    <table style="margin-top:10px">
      <thead><tr>
        <th>Coleção</th><th>Ciclo</th><th class="num">Peças</th>
        <th>Aberta em</th><th>Encerrada em</th><th>Ações</th>
      </tr></thead>
      <tbody id="col-lista"><tr><td colspan="6" class="muted">Carregando…</td></tr></tbody>
    </table>
  </section>

  <section>
    <h2>Downloads (fila resumable)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Fila de downloads do servidor (Parte D do NOMAD): modelos, datasets e
      documentos grandes. Retomada por <code>Range</code> — um restart no
      meio não zera 14 GB —, retry com backoff, dedup por URL+destino e
      cancelamento preservando o parcial. O progresso chega ao vivo por SSE.
    </p>
    <div class="row">
      <input id="dl-url" placeholder="https://…/arquivo.bin" style="flex:1;min-width:260px">
      <input id="dl-destino" placeholder="destino (opcional, sob downloads/)" style="width:210px">
      <button id="dl-add" style="border-color:var(--accent);color:var(--accent)">↓ Baixar</button>
      <button id="dl-refresh">↻ Carregar</button>
      <span class="muted msg" id="dl-msg"></span>
    </div>
    <table style="margin-top:10px">
      <thead><tr>
        <th>ID</th><th>Arquivo</th><th>Progresso</th><th>Status</th>
        <th>Tentativas</th><th class="num">Bytes</th><th>Ações</th>
      </tr></thead>
      <tbody id="dl-jobs"><tr><td colspan="7" class="muted">Carregando…</td></tr></tbody>
    </table>
    <p class="muted" style="font-size:0.75rem;margin-top:6px">
      📡 ao vivo por SSE (<code>/admin/downloads/events</code>); se a conexão
      cair, o painel volta a consultar sozinho. ✕ cancela (o parcial fica
      guardado), 🗑 apaga o registro (só de job já terminado — o arquivo em
      disco não é mexido).
    </p>
  </section>

  <section>
    <h2>Auto-update (modelos/conteúdo)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Parte E do NOMAD: o servidor atualiza o que consome sozinho, mas só
      dentro da <b>janela</b>, depois do <b>cool-off</b>, sem passar do
      <b>cap de bytes</b> e nunca num <b>major</b> (é com você). Três
      falhas duras e o alvo se <b>desliga sozinho</b> com o motivo gravado —
      religar é seu, aqui embaixo. O dry-run é o MESMO caminho do ciclo,
      só que sem executar.
    </p>
    <div class="row">
      <span class="muted" id="au-config" style="font-size:0.8rem">carregando…</span>
      <span style="flex:1"></span>
      <button id="au-dry">🧪 Dry-run</button>
      <button id="au-refresh">↻ Carregar</button>
      <span class="muted msg" id="au-msg"></span>
    </div>
    <table style="margin-top:10px">
      <thead><tr>
        <th>Alvo</th><th>Categoria</th><th>Versão</th><th>Status</th>
        <th>Falhas</th><th>Último ciclo</th><th>Ações</th>
      </tr></thead>
      <tbody id="au-alvos"><tr><td colspan="7" class="muted">Carregando…</td></tr></tbody>
    </table>
    <pre id="au-decisoes" class="muted" style="font-size:0.72rem;margin-top:8px;display:none"></pre>
    <div class="muted" id="au-metricas" style="font-size:0.75rem;margin-top:8px"></div>
    <p class="muted" style="font-size:0.75rem;margin-top:6px">
      Alvos de arquivo entram pelo manifesto <code>data/auto_update_alvos.json</code>
      (url + sha256 + versão de destino — edite e salve, o ciclo pega na
      próxima janela). O índice RAG (<code>indice-rag</code>) se atualiza
      sozinho quando <code>docs/</code> ou <code>knowledge/</code> mudam.
      🧪 dry-run mostra o que o próximo ciclo FARIA; ⟳ religa um alvo
      desligado (zera as falhas).
    </p>
  </section>

  <section>
    <h2>Ferramentas (Supply Depot)</h2>
    <p class="muted" style="font-size:0.8rem;margin-bottom:8px">
      Parte F do NOMAD: o catálogo de ferramentas do orquestrador virou
      registro de verdade. Toda entrada passa por <b>pré-voo</b> — conflito
      (nome de outra fonte? recusa), versão (downgrade não entra, major
      exige sua confirmação) e tamanho — e toda atualização guarda
      <b>backup</b> da versão anterior, com <b>rollback</b> de um clique.
      Suas personalizações (descrição/params) <b>sobrevivem</b> a qualquer
      atualização. Ferramenta gerada pelo <code>/gerar</code> agora
      <b>persiste</b>: reiniciou o core, ela continua lá.
    </p>
    <div class="row">
      <input id="fr-nome" placeholder="nome (ex.: util.calcular)" style="flex:1;min-width:180px">
      <input id="fr-versao" placeholder="1.0.0" style="width:80px">
      <input id="fr-desc" placeholder="descrição" style="flex:1;min-width:160px">
      <button id="fr-add" style="border-color:var(--accent);color:var(--accent)">＋ Instalar</button>
      <button id="fr-refresh">↻ Carregar</button>
      <span class="muted msg" id="fr-msg"></span>
    </div>
    <textarea id="fr-codigo" rows="5" spellcheck="false"
      placeholder="def calcular(**params):&#10;    return {&quot;ok&quot;: True, &quot;result&quot;: ...}"
      style="width:100%;margin-top:8px;font-family:monospace;font-size:0.8rem"></textarea>
    <table style="margin-top:10px">
      <thead><tr>
        <th>Ferramenta</th><th>Versão</th><th>Origem</th>
        <th class="num">Tam</th><th>Custom</th><th>Histórico</th><th>Ações</th>
      </tr></thead>
      <tbody id="fr-lista"><tr><td colspan="7" class="muted">Carregando…</td></tr></tbody>
    </table>
    <p class="muted" style="font-size:0.75rem;margin-top:6px">
      ✎ edita a descrição (sobrevive a atualizações); ⟲ volta para a versão
      anterior (backup em <code>data/ferramentas_backup/</code>); ✕
      desinstala (o arquivo é preservado no backup). No bot,
      <code>/gerar</code> cria ferramentas novas e avisa conflito antes de
      gastar o LLM.
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
  if (window.odFormato) window.odFormato.nome(data.user.username, role);
  return data;
}

// O herói do /admin é alimentado pelo loadSystem (pintar() com os
// dados que a página JÁ busca) — o JS injetado não repete as buscas
// (bandeira lida no DOMContentLoaded antes da injeção iniciar).
window.odFormatoGerenciado = true;

function visaoCards(health, sup, stats) {
    const cards = [
      ["Estado", health.status || (health.ok ? "up" : "?"), health.ok ? "ok" : "err"],
      ["Uptime", fmtUptime(stats.uptime_s != null ? stats.uptime_s : health.uptime_s), ""],
      ["Processadas", stats.processed != null ? stats.processed : "—", ""],
      ["Latência média", stats.avg_latency_ms != null ? stats.avg_latency_ms + " ms" : "—", ""],
      ["Loops", sup.restarts + " restart", sup.ok ? "ok" : "err"],
      ["Cache LLM", stats.cache && stats.cache.entries != null ? stats.cache.entries : "—", ""],
      ["Stack Nômade", stats.nomad_tools ? stats.nomad_tools.up + "/" + stats.nomad_tools.total : "—",
        stats.nomad_tools && stats.nomad_tools.fora.length ? "err" : ""],
      ["Alertas", stats.notifier
        ? stats.notifier.alerts_emitted + " env · " + stats.notifier.alerts_blocked + " blq" : "—",
        stats.notifier && stats.notifier.errors ? "err" : ""],
      ["Backup", stats.backup && stats.backup.estado
        ? (stats.backup.estado.ultimo_sucesso_em || "—") + " · " + fmtBytes(stats.backup.estado.ultimo_bytes)
        : "—",
        stats.backup && stats.backup.estado && (stats.backup.estado.pendente_hoje || stats.backup.estado.falhas) ? "err" : ""],
      ["Backup fotos", stats.backup && stats.backup.capturas
        ? (stats.backup.capturas.ultimo_sucesso_em || "—") + " · " + fmtBytes(stats.backup.capturas.ultimo_bytes)
        : "—",
        stats.backup && stats.backup.capturas && (stats.backup.capturas.pendente_hoje || stats.backup.capturas.falhas) ? "err" : ""],
      // Snapshots de HD externo (core/hd_backup.py): um card por alvo,
      // com o rótulo do dono — "HD fora" quando o fstab nofail montou
      // sem disco (pendente honesto, não verde de mentira).
      ...Object.keys(stats.backup || {}).filter(k => k.startsWith("hd_")).map(k => {
        const b = stats.backup[k];
        return [b.rotulo || k,
          b.ultimo_sucesso_em
            ? b.ultimo_sucesso_em + " · " + fmtBytes(b.ultimo_bytes)
            : (b.montado ? "nunca" : "HD fora"),
          (b.pendente_hoje || b.falhas || !b.montado) ? "err" : ""];
      }),
      // Off-site (canal privado do Telegram, 20/10): "nunca" em vermelho
      // enquanto o primeiro envio não acontecer — pendente honesto.
      ["Off-site", stats.offsite
        ? (stats.offsite.ultimo_diario
            ? "ok · " + stats.offsite.ultimo_diario : "nunca")
        : "—", stats.offsite && !stats.offsite.ultimo_diario ? "err" : ""],
      // --- System Overview (TODO §3.6, 20/10): os quatro subsistemas que
      // o /dashboard/stats JÁ trazia e a visão não mostrava. Sempre com
      // fallback honesto: bloco ausente = "—" (nunca verde de mentira).
      // RAG: a memória viva — documentos indexados e namespaces.
      ["RAG", stats.vector_store
        ? stats.vector_store.docs + " docs · " +
          (stats.vector_store.namespaces || []).length + " ns"
        : "—", ""],
      // Auto-update (Parte E): alvos do manifesto × auto-disable ×
      // pendentes — desligado é problema de verdade (vermelho).
      ["Auto-update", stats.auto_update
        ? stats.auto_update.alvos + " alvos · " +
          stats.auto_update.desabilitados + " desl · " +
          stats.auto_update.pendentes + " pend"
        : "—",
        stats.auto_update && stats.auto_update.desabilitados ? "err" : ""],
      // Fila de downloads (Parte D): em voo × concluídos × erros.
      ["Downloads", stats.downloads
        ? stats.downloads.ativas + " ativas · " +
          stats.downloads.concluidos + " ok · " +
          stats.downloads.erros + " erro"
        : "—",
        stats.downloads && stats.downloads.erros ? "err" : ""],
      // Supply Depot (Parte F): catálogo ativo, versões guardadas e o
      // último erro de restauração (se existe, o card fica vermelho).
      ["Ferramentas", stats.ferramentas
        ? stats.ferramentas.ativas + "/" + stats.ferramentas.total +
          " · " + stats.ferramentas.com_historico + " c/ histórico"
        : "—",
        stats.ferramentas && stats.ferramentas.ultimo_erro ? "err" : ""],
    ];
  return cards;
}

async function loadSystem() {
  const msg = document.getElementById("sys-msg");
  try {
    const [health, sup, stats, acoes] = await Promise.all([
      fetch("/health", { headers: authHeaders() }).then(r => r.json()),
      fetch("/supervision", { headers: authHeaders() }).then(r => r.json()),
      fetch("/dashboard/stats", { headers: authHeaders() }).then(r => r.json()),
      fetch("/actions", { headers: authHeaders() }).then(r => r.ok ? r.json() : null)
    ]);
    const cards = visaoCards(health, sup, stats);
    document.getElementById("sys").innerHTML = cards.map(c =>
      '<div class="card"><div class="k">' + c[0] + '</div><div class="v ' + c[2] + '">' + c[1] + "</div></div>"
    ).join("");
    // Resumo da visão (§3.6): a pill conta os cards em atenção — o
    // número vem dos MESMOS cards, então nunca pinta "tudo ok" por fora.
    const resumo = document.getElementById("sys-resumo");
    const atencao = cards.filter(c => c[2] === "err").length;
    resumo.className = "pill " + (atencao ? "err" : "ok");
    resumo.textContent = atencao ? atencao + " em atenção" : "tudo ok";
    document.getElementById("loops").textContent = JSON.stringify(sup, null, 2);
    document.getElementById("metrics").textContent = JSON.stringify(stats, null, 2);
    document.getElementById("nomadTools").textContent = stats.nomad_tools
      ? JSON.stringify(stats.nomad_tools, null, 2)
      : "monitor desligado (OD_NOMAD_TOOLS=0)";
    if (window.odFormato) window.odFormato.pintar(health, stats, acoes);
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

function fmtBytes(n) {
  if (n == null || !n) return "—";
  if (n < 1048576) return Math.round(n / 1024) + " KB";
  return (n / 1048576).toFixed(2) + " MB";
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
  // Batimento (10/10): sessão longa mostra o tempo — deixar de parecer travado.
  if (estado.decorrido_s) {
    const m = Math.floor(estado.decorrido_s / 60), s = estado.decorrido_s % 60;
    partes.push("executando há: " + (m ? m + "min" : "") + s + "s");
  }
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
        acoes = '<span class="pill ok">com dono</span> ';
        // Etapa 4 (2026-10-15): desfazer o REGISTRO exige o código de
        // posse — a prova secreta que o bloqueio pedia desde 09/10.
        acoes += '<button class="reg-desreg" data-id="' + esc(p.public_id) + '">↩ Registro</button>';
      }
      if (p.kind === "exclusiva") {
        acoes += ' <button class="reg-posse" data-id="' + esc(p.public_id) + '">🧾 QR</button>';
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
        '<div class="muted" style="font-size:0.78rem">Carregando sala…</div></td></tr>' +
        // Etapa 4: linha que abre com o QR/código de posse (🧾).
        '<tr class="reg-posse-linha" data-id="' + esc(p.public_id) + '" style="display:none">' +
        '<td colspan="10" style="background:var(--bg2)">' +
        '<div class="muted" style="font-size:0.78rem">Clique em 🧾 QR para gerar o código.</div></td></tr>';
      return linha;
    }).join("") : '<tr><td colspan="10" class="muted">Nenhuma peça cadastrada ainda.</td></tr>';
    document.querySelectorAll(".reg-vender").forEach(b =>
      b.addEventListener("click", () => regStatus(b.dataset.id, "vendida")));
    document.querySelectorAll(".reg-registrar").forEach(b =>
      b.addEventListener("click", () => regRegistrar(b.dataset.id)));
    document.querySelectorAll(".reg-desfazer").forEach(b =>
      b.addEventListener("click", () => regDesfazer(b.dataset.id)));
    document.querySelectorAll(".reg-posse").forEach(b =>
      b.addEventListener("click", () => regPosse(b.dataset.id)));
    document.querySelectorAll(".reg-desreg").forEach(b =>
      b.addEventListener("click", () => regDesreg(b.dataset.id)));
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
    frente: (document.getElementById("reg-frente").value || "").trim() || null,
    tipo: (document.getElementById("reg-tipo").value || "").trim() || null,
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

// --- Ciclo fechado das coleções (frente NV, 16/10) ------------------------
function colSetMsg(t, cls) {
  const el = document.getElementById("col-msg");
  el.textContent = t;
  el.className = "muted msg " + (cls || "");
}

function colData(ts) {
  return ts ? new Date(ts * 1000).toLocaleString("pt-BR") : "—";
}

async function colLoad() {
  try {
    // Mesma projeção pública (GET /registry/collections) — o painel não
    // tem campos privados de coleção: o ciclo aberto/fechado é de todos.
    const resp = await fetch("/registry/collections");
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { colSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    const cols = data.colecoes || [];
    document.getElementById("col-lista").innerHTML = cols.length ? cols.map(c => {
      const aberta = c.ciclo === "aberta";
      const acao = aberta
        ? '<button class="danger col-encerrar" data-nome="' + esc(c.name) +
          '">⛔ Encerrar (para sempre)</button>'
        : '<span class="pill ok">fechado — imutável</span>';
      return "<tr><td><b>" + esc(c.name) + "</b></td>" +
        '<td><span class="pill ' + (aberta ? "" : "ok") + '">' + c.ciclo + "</span></td>" +
        '<td class="num">' + c.pecas + "</td>" +
        '<td class="muted">' + colData(c.criada_em) + "</td>" +
        '<td class="muted">' + colData(c.encerrada_em) + "</td>" +
        "<td>" + acao + "</td></tr>";
    }).join("") : '<tr><td colspan="6" class="muted">Nenhuma coleção ainda — abra o primeiro ciclo.</td></tr>';
    document.querySelectorAll(".col-encerrar").forEach(b =>
      b.addEventListener("click", () => colEncerrar(b.dataset.nome)));
  } catch (e) { colSetMsg("Falha ao carregar: " + e.message, "err"); }
}

async function colAdd() {
  const nome = (document.getElementById("col-nome").value || "").trim();
  if (!nome) { colSetMsg("Dê um nome à coleção.", "err"); return; }
  try {
    const resp = await fetch("/admin/registry/collections", {
      method: "POST", headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({ name: nome })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { colSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    document.getElementById("col-nome").value = "";
    colSetMsg("✔ Ciclo aberto: " + data.colecao.name, "ok");
    colLoad();
  } catch (e) { colSetMsg("Falha: " + e.message, "err"); }
}

async function colEncerrar(nome) {
  if (!window.confirm("ENCERRAR o ciclo de " + nome + "?\\n\\n" +
      "PARA SEMPRE — o Protocolo NV proíbe reabrir, renomear ou apagar " +
      "a coleção. Confirme só se a série estiver de fato fechada.")) return;
  try {
    const resp = await fetch(
      "/admin/registry/collections/" + encodeURIComponent(nome) + "/encerrar",
      { method: "POST", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { colSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    colSetMsg("⛔ Ciclo de " + data.colecao.name + " encerrado — para sempre.", "ok");
    colLoad();
  } catch (e) { colSetMsg("Falha: " + e.message, "err"); }
}

async function regStatus(id, status, owner, posseCode) {
  const body = { status: status };
  if (owner) body.owner_username = owner;
  // Etapa 4: prova secreta para sair de "registrada" (sem ela o store
  // levanta registro_pendente_codigo_secreto).
  if (posseCode) body.posse_code = posseCode;
  try {
    const resp = await fetch("/admin/registry/" + encodeURIComponent(id), {
      method: "PUT", headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify(body)
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      let erro = data.error || "Erro HTTP " + resp.status;
      if (erro === "registro_pendente_codigo_secreto")
        erro = "Código de posse inválido — registro protegido.";
      regSetMsg(erro, "err"); return;
    }
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

// --- Etapa 4 (2026-10-15): código de posse (QR do cartão da compra) -------
async function regPosse(id) {
  const linha = document.querySelector('.reg-posse-linha[data-id="' + CSS.escape(id) + '"]');
  if (!linha) return;
  const aberta = linha.style.display !== "none";
  document.querySelectorAll(".reg-posse-linha").forEach(l => { l.style.display = "none"; });
  if (aberta) return;
  linha.style.display = "";
  linha.firstElementChild.innerHTML = '<div class="muted" style="font-size:0.78rem">Gerando código de posse…</div>';
  try {
    const resp = await fetch("/admin/registry/" + encodeURIComponent(id) + "/posse", {
      method: "POST", headers: authHeaders()
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      linha.firstElementChild.innerHTML = '<span class="msg err">Erro ' + resp.status + ': ' + esc(data.error || "?") + '</span>';
      regSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return;
    }
    const aviso = data.regenerado
      ? '<b style="color:var(--accent)">O código ANTERIOR foi invalidado</b> — imprima só o novo.'
      : 'Imprima no cartão: quem TIVER o QR registra a peça no app no próprio nome.';
    linha.firstElementChild.innerHTML =
      '<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center">' +
      '<img src="/admin/registry/' + encodeURIComponent(id) + '/posse/qr?codigo=' + encodeURIComponent(data.codigo_posse) + '" ' +
      'alt="QR de posse" width="132" height="132" style="background:#fff;border-radius:8px;padding:6px" loading="lazy">' +
      '<div style="font-size:.8rem;min-width:260px">' +
      '<div>Código: <code style="font-size:1.05rem;letter-spacing:.08em">' + esc(data.codigo_posse) + '</code> ' +
      '<button class="reg-copiar-posse" data-url="' + esc(data.url) + '">Copiar link</button></div>' +
      '<div class="muted" style="margin-top:6px">' + aviso + '</div>' +
      '<div class="muted" style="margin-top:4px;word-break:break-all">QR abre: ' + esc(data.url) + '</div>' +
      '</div></div>';
    const copiar = linha.querySelector(".reg-copiar-posse");
    if (copiar) copiar.onclick = () => {
      navigator.clipboard.writeText(copiar.dataset.url)
        .then(() => regSetMsg("Link do QR copiado.", "ok"))
        .catch(() => regSetMsg("Não deu para copiar — selecione o texto do QR.", "err"));
    };
    regSetMsg("Código de posse " + (data.regenerado ? "REGENERADO" : "gerado") + ": " + data.codigo_posse, "ok");
  } catch (e) { regSetMsg("Falha: " + e.message, "err"); }
}

async function regDesreg(id) {
  // Desfazer REGISTRO (Etapa 4): sai de "registrada" só com a prova
  // secreta — o mesmo código que estava no cartão do comprador.
  const codigo = (window.prompt(
    "Código de posse de " + id + " (POSSE-…) para DESFAZER o registro — sem ele a posse fica protegida:") || "").trim();
  if (!codigo) return;
  if (!window.confirm("Desfazer o REGISTRO de " + id + "? A peça deixa de ter dono e vai para o estado VENDIDA.")) return;
  await regStatus(id, "vendida", undefined, codigo);
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

// --- Fila de downloads resumable — Parte D do NOMAD (2026-10-14) ----------
const DL_STATUS = {
  na_fila: "Na fila", baixando: "Baixando", aguardando: "Retry agendado",
  concluido: "Concluído", erro: "Erro", cancelado: "Cancelado"
};
let dlJobs = {};      // id → job (espelho da fila, alimentado pelo SSE)
let dlResumo = null;

function dlSetMsg(t, cls) {
  const el = document.getElementById("dl-msg");
  if (el) { el.textContent = t; el.className = "muted msg " + (cls || ""); }
}

function dlBytes(n) {
  if (n == null || isNaN(Number(n))) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; let v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(i === 0 || v >= 100 ? 0 : 1) + " " + u[i];
}

function dlRender() {
  const jobs = Object.values(dlJobs);
  const corpo = jobs.map(j => {
    const pct = j.pct != null ? Math.round(j.pct * 100) : null;
    const mostrando = j.status === "baixando" || j.status === "concluido";
    const barra = mostrando
      ? '<div style="background:var(--bg3);border-radius:6px;height:10px;min-width:120px;overflow:hidden">' +
        '<div style="height:100%;width:' + (pct != null ? pct : 100) + '%;background:var(--accent)"></div></div>'
      : '<span class="muted">—</span>';
    const pill = j.status === "concluido" ? "ok" : (j.status === "erro" ? "err" : "");
    let acoes = "";
    if (["baixando", "na_fila", "aguardando"].indexOf(j.status) >= 0)
      acoes += '<button class="dl-cancel" data-id="' + esc(j.id) + '">✕</button> ';
    const terminal = ["concluido", "erro", "cancelado"].indexOf(j.status) >= 0;
    acoes += '<button class="dl-del" data-id="' + esc(j.id) + '"' +
             (terminal ? "" : " disabled") + '>🗑</button>';
    const detalhe = j.erro
      ? '<div class="muted" style="font-size:0.72rem">' + esc(j.erro) +
        (j.proximo_retry ? " · próxima tentativa agendada" : "") + "</div>"
      : "";
    return "<tr><td><code>" + esc(j.id) + "</code></td>" +
      "<td><b>" + esc(j.nome) + "</b>" + detalhe + "</td>" +
      "<td>" + barra + (pct != null ? " " + pct + "%" : "") + "</td>" +
      '<td><span class="pill ' + pill + '">' + (DL_STATUS[j.status] || esc(j.status)) + "</span></td>" +
      '<td class="muted">' + j.tentativas + "/" + j.max_tentativas + "</td>" +
      '<td class="num muted">' + dlBytes(j.bytes_feitos) +
        (j.bytes_total > 0 ? " / " + dlBytes(j.bytes_total) : "") + "</td>" +
      "<td>" + acoes + "</td></tr>";
  }).join("");
  document.getElementById("dl-jobs").innerHTML = corpo ||
    '<tr><td colspan="7" class="muted">Nenhum download ainda.</td></tr>';
  document.querySelectorAll(".dl-cancel").forEach(b =>
    b.addEventListener("click", () => dlAcao(b.dataset.id, "cancel")));
  document.querySelectorAll(".dl-del").forEach(b =>
    b.addEventListener("click", () => dlAcao(b.dataset.id, "del")));
  if (dlResumo) {
    dlSetMsg(dlResumo.ativas + " ativa(s) · " + dlResumo.concluidos +
             " concluído(s) · " + dlResumo.erros + " erro(s) · " +
             dlBytes(dlResumo.bytes_baixados) + " gravados", "");
  }
}

function dlAplicar(pacote) {
  if (!pacote || !pacote.job) return;
  if (pacote.evento === "removido") delete dlJobs[pacote.job.id];
  else dlJobs[pacote.job.id] = pacote.job;
  dlRender();
}

async function dlLoad() {
  try {
    const resp = await fetch("/admin/downloads", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { dlSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    dlJobs = {};
    (data.jobs || []).forEach(j => { dlJobs[j.id] = j; });
    dlResumo = data.resumo || null;
    dlRender();
  } catch (e) { dlSetMsg("Falha: " + e.message, "err"); }
}

async function dlAdd() {
  const url = (document.getElementById("dl-url").value || "").trim();
  if (!url) { dlSetMsg("Cole a URL do arquivo.", "err"); return; }
  const destino = (document.getElementById("dl-destino").value || "").trim();
  try {
    const resp = await fetch("/admin/downloads", {
      method: "POST",
      headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({ url: url, destino: destino })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { dlSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    document.getElementById("dl-url").value = "";
    dlSetMsg((data.duplicado ? "⟳ Já estava na fila: " : "✔ Enfileirado: ") + data.job.id, "ok");
    dlLoad();
  } catch (e) { dlSetMsg("Falha: " + e.message, "err"); }
}

async function dlAcao(id, acao) {
  const url = "/admin/downloads/" + encodeURIComponent(id) +
              (acao === "cancel" ? "/cancel" : "");
  try {
    const resp = await fetch(url, {
      method: acao === "cancel" ? "POST" : "DELETE",
      headers: authHeaders()
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { dlSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    if (acao !== "cancel") delete dlJobs[id];
    dlSetMsg((acao === "cancel" ? "✕ Cancelado " : "🗑 Removido ") + id, "ok");
    dlRender();
  } catch (e) { dlSetMsg("Falha: " + e.message, "err"); }
}

// SSE do progresso ao vivo: snapshot inicial e depois cada transição.
// Queda (rede/servidor) desliga o stream — o carregarTudo continua
// consultando e uma nova chamada reabre.
let dlSseAtiva = false;
function dlSse() {
  if (dlSseAtiva || typeof ReadableStream === "undefined") return;
  dlSseAtiva = true;
  fetch("/admin/downloads/events", { headers: authHeaders() })
    .then(resp => {
      if (!resp.ok || !resp.body) { dlSseAtiva = false; return null; }
      const leitor = resp.body.getReader();
      const decodificador = new TextDecoder();
      let buffer = "";
      const pacotes = () => leitor.read().then(res => {
        if (res.done) { dlSseAtiva = false; return; }
        buffer += decodificador.decode(res.value, { stream: true });
        const partes = buffer.split("\\n\\n");
        buffer = partes.pop();
        partes.forEach(p => {
          const linha = p.split("\\n").find(l => l.indexOf("data: ") === 0);
          if (!linha) return;
          try {
            const pacote = JSON.parse(linha.slice(6));
            if (pacote.evento === "snapshot") {
              dlJobs = {};
              (pacote.jobs || []).forEach(j => { dlJobs[j.id] = j; });
              dlResumo = pacote.resumo || dlResumo;
              dlRender();
            } else if (pacote.evento === "removido") {
              delete dlJobs[pacote.job.id];
              dlRender();
            } else {
              dlAplicar(pacote);
            }
          } catch (e) { /* linha parcial — o próximo pacote completa */ }
        });
        return pacotes();
      }).catch(() => { dlSseAtiva = false; });
      return pacotes();
    })
    .catch(() => { dlSseAtiva = false; });
}

// --- Auto-update de modelos/conteúdo — Parte E do NOMAD (2026-10-14) --------
// Estado do serviço: config (janela/cool-off/cap), alvos do manifesto +
// índice RAG, e o estado por alvo (falhas/auto-disable). Dry-run mostra o
// que o próximo ciclo FARIA — é o mesmo caminho do tick de produção.
let auAlvos = [];
let auEstado = {};

function auSetMsg(t, cls) {
  const el = document.getElementById("au-msg");
  if (el) { el.textContent = t; el.className = "muted msg " + (cls || ""); }
}

function auQuando(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" +
         String(d.getMinutes()).padStart(2, "0");
}

function auRender() {
  const cfg = auEstado.config || {};
  // Contadores do processo (TODO §3.2): os mesmos od_auto_update_* do
  // /metrics — aqui sem precisar de um Prometheus apontado.
  const mm = auEstado.metricas || {};
  const alvo = document.getElementById("au-metricas");
  if (alvo) alvo.innerHTML = "ciclos <b>" + (mm.ticks || 0) + "</b>" +
    " (+ " + (mm.ticks_dry_run || 0) + " dry-run) · aplicados <b>" +
    (mm.aplicados || 0) + "</b> · falhas <b>" + (mm.falhas || 0) + "</b>" +
    " · auto-desligados <b>" +
    (mm.auto_desligados || 0) + "</b> · baixados <b>" + (mm.downloads || 0) +
    "</b> · desde o boot; soma-se no <code>/metrics</code> " +
    "(<code>od_auto_update_*</code>)";
  document.getElementById("au-config").innerHTML =
    "janela <b>" + esc(cfg.janela || "—") + "</b> · cool-off " +
    esc(cfg.cooloff_h != null ? cfg.cooloff_h + "h" : "—") +
    " · cap " + esc(cfg.cap_mb != null ? cfg.cap_mb + " MB" : "—") +
    " · máx " + esc(cfg.max_falhas != null ? cfg.max_falhas + " falhas" : "—") +
    " · ciclo " + esc(cfg.intervalo_min != null ? cfg.intervalo_min + " min" : "—");
  const est = {};
  (auEstado.estado || []).forEach(e => { est[e.id] = e; });
  const corpo = auAlvos.map(a => {
    const e = est[a.id] || {};
    const versao = e.versao_instalada
      ? esc(e.versao_instalada) + (a.versao_nova && a.versao_nova !== e.versao_instalada
          ? " → <b>" + esc(a.versao_nova) + "</b>" : "")
      : (a.versao_nova ? "<b>" + esc(a.versao_nova) + "</b>" : "—");
    let pill, status, acoes = "";
    if (e.desabilitado) {
      pill = "err";
      status = "Desligado: " + esc(e.motivo_desabilitado || "");
      acoes += '<button class="au-reset" data-id="' + esc(a.id) + '">⟳</button>';
    } else if (a.versao_nova && a.versao_nova !== (e.versao_instalada || "")) {
      pill = "";
      status = "Atualização pendente";
    } else if (a.versao_nova) {
      pill = "ok";
      status = "Atualizado";
    } else {
      pill = "ok";
      status = "Sem atualização";
    }
    const erro = e.ultimo_erro
      ? '<div class="muted" style="font-size:0.72rem">' + esc(e.ultimo_erro) + "</div>" : "";
    return "<tr><td><b>" + esc(a.nome || a.id) + "</b>" +
      '<div class="muted" style="font-size:0.72rem"><code>' + esc(a.id) + "</code></div></td>" +
      '<td class="muted">' + esc(a.categoria) + "</td>" +
      "<td>" + versao + "</td>" +
      '<td><span class="pill ' + pill + '">' + status + "</span>" + erro + "</td>" +
      '<td class="muted">' + (e.falhas || 0) + "</td>" +
      '<td class="muted">' + auQuando(e.ultima_tentativa) + "</td>" +
      "<td>" + acoes + "</td></tr>";
  }).join("");
  document.getElementById("au-alvos").innerHTML = corpo ||
    '<tr><td colspan="7" class="muted">Nenhum alvo declarado.</td></tr>';
  document.querySelectorAll(".au-reset").forEach(b =>
    b.addEventListener("click", () => auReset(b.dataset.id)));
}

async function auLoad() {
  try {
    const resp = await fetch("/admin/auto-update", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { auSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    auAlvos = data.alvos || [];
    auEstado = data;
    auRender();
    if (data.ultimo_tick)
      auSetMsg("último ciclo às " + auQuando(data.ultimo_tick), "");
  } catch (e) { auSetMsg("Falha: " + e.message, "err"); }
}

async function auDry() {
  auSetMsg("avaliando…", "");
  try {
    const resp = await fetch("/admin/auto-update/dry-run", {
      method: "POST", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { auSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    const linhas = (data.decisoes || []).map(d =>
      d.alvo.padEnd(14) + d.acao.padEnd(9) + d.motivo);
    const pre = document.getElementById("au-decisoes");
    const nl = String.fromCharCode(10);
    pre.textContent = "próximo ciclo (" + (data.decisoes || []).length +
      " alvo(s)):" + (linhas.length ? nl + linhas.join(nl) : " sem alvos");
    pre.style.display = "block";
    auAlvos = data.alvos || [];
    auEstado = data;
    auRender();
    auSetMsg("dry-run: nada foi executado", "ok");
  } catch (e) { auSetMsg("Falha: " + e.message, "err"); }
}

async function auReset(id) {
  try {
    const resp = await fetch("/admin/auto-update/reset", {
      method: "POST",
      headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({ alvo: id })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { auSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    auSetMsg("⟳ " + id + " religado (falhas zeradas)", "ok");
    auLoad();
  } catch (e) { auSetMsg("Falha: " + e.message, "err"); }
}

// --- Ferramentas (Supply Depot) — Parte F do NOMAD (2026-10-15) --------------
// Catálogo persistente com pré-voo: 409 = conflito/versão/tamanho (o motivo
// vem da resposta), 400 = código rejeitado. Rollback é um clique e a
// customização do dono (✎) sobrevive a qualquer atualização.
let frLista = [];

function frSetMsg(t, cls) {
  const el = document.getElementById("fr-msg");
  if (el) { el.textContent = t; el.className = "muted msg " + (cls || ""); }
}

function frRender() {
  const corpo = frLista.map(f => {
    const custom = Object.keys(f.custom || {});
    const hist = (f.anteriores || []).length;
    let pill, status;
    if (!f.ativa) { pill = ""; status = "desinstalada"; }
    else if (!f.no_registry) { pill = "err"; status = "fora do registry"; }
    else { pill = "ok"; status = "registrada"; }
    const acoes =
      (hist ? '<button class="fr-rollback" data-id="' + esc(f.id) + '" title="voltar para ' +
        esc(f.anteriores[hist - 1].versao || "v anterior") + '">⟲</button>' : "") +
      '<button class="fr-custom" data-id="' + esc(f.id) + '">✎</button>' +
      '<button class="fr-del" data-id="' + esc(f.id) + '">✕</button>';
    return "<tr><td><b>" + esc(f.id) + "</b>" +
      '<div class="muted" style="font-size:0.72rem">' +
      esc((f.descricao || "—").slice(0, 72)) + "</div></td>" +
      "<td>" + esc(f.versao) + "</td>" +
      '<td class="muted">' + esc(f.origem) + "</td>" +
      '<td class="num muted">' + f.bytes + " B</td>" +
      '<td class="muted">' + esc(custom.length ? custom.join(", ") : "—") + "</td>" +
      '<td><span class="pill ' + pill + '">' + status +
      (hist ? " · " + hist + " backup(s)" : "") + "</span></td>" +
      "<td>" + acoes + "</td></tr>";
  }).join("");
  document.getElementById("fr-lista").innerHTML = corpo ||
    '<tr><td colspan="7" class="muted">Nenhuma ferramenta no depot.</td></tr>';
  document.querySelectorAll(".fr-rollback").forEach(b =>
    b.addEventListener("click", () => frRollback(b.dataset.id)));
  document.querySelectorAll(".fr-custom").forEach(b =>
    b.addEventListener("click", () => frCustom(b.dataset.id)));
  document.querySelectorAll(".fr-del").forEach(b =>
    b.addEventListener("click", () => frDelete(b.dataset.id)));
}

async function frLoad() {
  try {
    const resp = await fetch("/admin/ferramentas", { headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { frSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    frLista = data.ferramentas || [];
    frRender();
    frSetMsg(frLista.length + " no catálogo" +
      (data.ultimo_erro ? " · ⚠ " + data.ultimo_erro : ""), "");
  } catch (e) { frSetMsg("Falha: " + e.message, "err"); }
}

async function frAdd() {
  const nome = (document.getElementById("fr-nome").value || "").trim();
  const codigo = document.getElementById("fr-codigo").value || "";
  if (!nome || !codigo) { frSetMsg("nome + código obrigatórios", "err"); return; }
  frSetMsg("pré-voo + instalação…", "");
  try {
    const resp = await fetch("/admin/ferramentas", {
      method: "POST",
      headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({
        nome: nome,
        versao: (document.getElementById("fr-versao").value || "1.0.0").trim(),
        descricao: (document.getElementById("fr-desc").value || "").trim(),
        codigo: codigo
      })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { frSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    frSetMsg("✓ " + (data.acao || "ok") + (data.motivo ? " · " + data.motivo : ""), "ok");
    document.getElementById("fr-nome").value = "";
    document.getElementById("fr-codigo").value = "";
    frLoad();
  } catch (e) { frSetMsg("Falha: " + e.message, "err"); }
}

async function frRollback(id) {
  try {
    const resp = await fetch("/admin/ferramentas/" + encodeURIComponent(id) + "/rollback",
      { method: "POST", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { frSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    frSetMsg("⟲ " + esc(data.de) + " → " + esc(data.para), "ok");
    frLoad();
  } catch (e) { frSetMsg("Falha: " + e.message, "err"); }
}

async function frCustom(id) {
  const atual = (frLista.find(f => f.id === id) || {}).descricao || "";
  const desc = prompt("Nova descrição de " + id + " — ela SOBREVIVE a atualizações:", atual);
  if (desc === null) return;
  try {
    const resp = await fetch("/admin/ferramentas/" + encodeURIComponent(id), {
      method: "PUT",
      headers: authHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({ descricao: desc })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { frSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    frSetMsg("✎ descrição atualizada (sobrevive a update)", "ok");
    frLoad();
  } catch (e) { frSetMsg("Falha: " + e.message, "err"); }
}

async function frDelete(id) {
  if (!confirm("Desinstalar " + id + "? (o arquivo é preservado no backup)")) return;
  try {
    const resp = await fetch("/admin/ferramentas/" + encodeURIComponent(id),
      { method: "DELETE", headers: authHeaders() });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { frSetMsg(data.error || "Erro HTTP " + resp.status, "err"); return; }
    frSetMsg("✕ " + data.removido + " desinstalada (arquivo no backup)", "ok");
    frLoad();
  } catch (e) { frSetMsg("Falha: " + e.message, "err"); }
}

// Páginas internas do Google: o link precisa do token da sessão na query
// porque o navegador navega sem header — o handler valida e exige dono.
function linkGoogle() {
  if (!token) return;
  ["g-apis", "g-auth"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.href = el.getAttribute("href").split("?")[0] + "?t=" + encodeURIComponent(token);
  });
}

const carregarTudo = () => { loadSystem(); loadUsers(); sessaoStatus(); caixaLoad(); ideiasLoad(); limLoad(); regLoad(); colLoad(); dlLoad(); auLoad(); frLoad(); linkGoogle(); };
document.getElementById("btn-refresh").onclick = carregarTudo;
document.getElementById("reg-add").onclick = regAdd;
document.getElementById("reg-refresh").onclick = regLoad;
document.getElementById("col-add").onclick = colAdd;
document.getElementById("col-nome").addEventListener("keydown", e => { if (e.key === "Enter") colAdd(); });
document.getElementById("reg-nome").addEventListener("keydown", e => { if (e.key === "Enter") regAdd(); });
document.getElementById("dl-add").onclick = dlAdd;
document.getElementById("dl-refresh").onclick = dlLoad;
document.getElementById("dl-url").addEventListener("keydown", e => { if (e.key === "Enter") dlAdd(); });
document.getElementById("au-dry").onclick = auDry;
document.getElementById("au-refresh").onclick = auLoad;
document.getElementById("fr-add").onclick = frAdd;
document.getElementById("fr-refresh").onclick = frLoad;
document.getElementById("fr-nome").addEventListener("keydown", e => { if (e.key === "Enter") frAdd(); });
whoAmI().then(u => { if (u) { carregarTudo(); dlSse(); } });
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
        # Sinal de desligamento: o SSE (GET /admin/downloads/events) fica
        # aberto por natureza — sem este sinal, server_close() esperaria o
        # handler até o próximo ping (15 s) em TODO stop()/restart.
        self.encerrando = threading.Event()
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
        self.encerrando.set()   # derruba os streams SSE antes do join
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
        """Janela deslizante por IP. Escreve 429 e retorna False se estourou.

        Isenções — navegar NUNCA pode cair no limiter (reporte do dono
        em 17/10: páginas abrindo como rate_limited e precisando de F5
        até a janela deslizar):
          * /admin* — gestão do dono (exige auth de admin; evita 429 ao
            salvar o txt.txt longo);
          * GET de shells de página ("/", /chat, /dashboard) e de
            /site/* — HTML/assets estáticos baratos. O orçamento do
            limiter existe para o que faz trabalho de verdade (POST
            /message, /executa, tentativas de login, dados), não para
            o navegador pedir o documento: um abrir de /dashboard custa
            ~10 requests (HTML, ícones, auth, dados, chip do herói);
          * GET /app/version — leitura de um inteiro; o app e os chips
            do site chamam em toda abertura de página.
        /auth/register e /auth/login SEGUEM contados (superfície de
        força-bruta) e /health SEGUI contado (roda os checks ao vivo —
        o cache curto do handler é o que o barateia, não a isenção).
        """
        method = self.command
        path = urlsplit(self.path).path
        if path.startswith("/admin"):
            return True
        if method == "GET" and (
            path in ("/", "/chat", "/dashboard", "/site", "/app/version")
            or path.startswith("/site/")
        ):
            return True
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
            # Fase 7.3: /health responde o agregado do HealthMonitor.
            # Cache curto (8s): health() roda os checks AO VIVO (9 probes
            # docker incluídos) e os chips do herói/site chamam /health
            # em toda abertura de página — sem cache, cada F5 do dono
            # dispara 22 probes e cada chamada gastava o orçamento do
            # limiter. Rajadas compartilham a mesma rodada de probes e
            # o agregado nunca fica com mais de 8s de idade.
            agora = time.monotonic()
            cache = getattr(self.api, "_health_cache", None)
            if cache and agora - cache[0] < 8.0:
                result = dict(cache[1])
            else:
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
                self.api._health_cache = (agora, result)
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
        self._html(200, _com_tema(_DASHBOARD_PAGE_HTML))

    def admin_html(self) -> None:
        """Painel do DONO (papel admin): contas, uso e saúde do sistema.
        O gate de dados é o _require_admin nos handlers /admin/users* — aqui
        é só o shell; sem papel admin a própria página se desliga."""
        self._html(200, _com_tema(_ADMIN_PAGE_HTML))

    def chat_html(self) -> None:
        """Chat funcional: shell aberto + chave pedida UMA vez no navegador
        (sessionStorage) e usada nas chamadas a POST /message."""
        self._html(200, _com_tema(_CHAT_PAGE_HTML))

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

    def registry_list(self) -> None:
        """GET /registry — lista PÚBLICA das peças (loja do site).

        Alimenta site/loja.html: projeção pública de todas as peças
        (preço/notas/hash nunca; username só nas registradas — mesma
        regra do verify). Sem preço à vista: a negociação acontece na
        sala da peça (decisão da etapa 1-3 — preço é campo privado).
        """
        store = self.api._registry
        if store is None:
            raise APIError(503, "registry_indisponivel")
        pecas: list[dict[str, Any]] = []
        for item in store.list_all():
            public = store.verify_public(item["public_id"])
            if public is not None:
                pecas.append(public)
        self._json(200, {"ok": True, "total": len(pecas), "pecas": pecas})

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

    def registry_collections(self) -> None:
        """GET /registry/collections — lista PÚBLICA dos ciclos (frente NV).

        Projeção sem segredo (mesma natureza de /registry): nome, ciclo
        (aberta/encerrada), contagem de peças e datas. Ciclo encerrado é
        escassez visível — "nunca reeditada" (PROTOCOLO_NV) vira prova
        pública na loja/verificação.
        """
        store = self._registry_store_or_503()
        colecoes = [
            {"name": c["name"], "ciclo": "aberta" if c["aberta"] else "encerrada",
             "pecas": c["pecas"], "criada_em": c["created_at"],
             "encerrada_em": c["closed_at"]}
            for c in store.listar_colecoes()
        ]
        self._json(200, {"ok": True, "total": len(colecoes),
                         "colecoes": colecoes})

    def registry_posse(self) -> None:
        """POST /registry/posse — comprador registra a PEÇA NO PRÓPRIO NOME.

        Etapa 4 (2026-10-15): o QR do cartão da compra carrega o código
        POSSE-…; quem tem CONTA (app, sessão/API key de usuário) cola o
        código e a peça passa a constar como dele na consulta pública
        (username, nunca nome real).

        Body: {"codigo_posse": str}. Erros: 401 sem conta, 400
        posse_invalida (mesma resposta para peça inexistente e para
        chute — sem oráculo), 409 ja_registrada. Rate limit por IP já
        cobre o endpoint (30/min) além dos 64 bits do código.
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
            peca = store.registrar_posse(
                str(data.get("codigo_posse") or ""), username
            )
        except ValueError as exc:
            msg = str(exc)
            raise APIError(
                409 if msg == "ja_registrada" else 400, msg
            )
        # O dono da loja fica sabendo que a peça dele ganhou dono
        # (falha do Telegram nunca derruba a resposta do comprador).
        notify = self.api.config.chat_notify
        if notify is not None:
            try:
                notify(
                    f"🔑 Peça {peca.get('public_id')} registrada "
                    f"por @{username} (código de posse)"
                )
            except Exception:  # pragma: no cover — Telegram fora do ar
                log.debug("chat_notify posse falhou (seguindo)",
                          public_id=peca.get("public_id"))
        self._json(201, {"ok": True, "peca": peca})

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

    def _serve_site_file(self, name: str, base: Optional[Path] = None) -> None:
        """Serve um arquivo de site/ com streaming (o APK tem ~50MB).

        `base` permite servir de outro diretório (site_admin/ para as páginas
        internas do dono) — a trava de path traversal vale igual para os dois.

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
        base = (
            Path(self.api.config.site_dir or DEFAULT_SITE_DIR).resolve()
            if base is None
            else base.resolve()
        )
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
        # Attachment SÓ no que é download de verdade (APK e afins).
        # CSS/JS precisam ser SERVIDOS como texto: sem isto, o navegador
        # baixava od.css/od-nav.js em vez de aplicá-los e o menu
        # compartilhado das páginas do site não carregava (10/10).
        if ctype != "text/html" and not ctype.startswith("text/"):
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
        # Fila de downloads (Parte D): contagens vivas — o que está em
        # voo, o que esperou retry e o que já caiu em erro nunca somem.
        downloads = self.api.config.downloads
        if downloads is not None:
            payload["downloads"] = downloads.snapshot()
        # Auto-update (Parte E): o dono vê do Status sem abrir o painel —
        # janela vigente, quantos alvos estão desligados (auto-disable)
        # e quanto tempo faz do último ciclo.
        auto_update = self.api.config.auto_update
        if auto_update is not None:
            estado = auto_update.estado_resumo()
            payload["auto_update"] = {
                "config": estado["config"],
                "alvos": len(estado["alvos"]),
                "desabilitados": len(estado["desabilitados"]),
                "pendentes": len(estado["pendentes"]),
                "ultimo_tick": estado["ultimo_tick"],
                # Contadores do processo (TODO §3.2): os MESMOS números
                # que o /metrics expõe (od_auto_update_*) — o dono vê no
                # Status sem precisar de um Prometheus apontado.
                "metricas": auto_update.metricas.snapshot(),
            }
        # Supply Depot (Parte F): o dono vê do Status quantas ferramentas
        # estão no catálogo, quantas com histórico (rollback disponível) e
        # o último erro de restauração — sem abrir o painel.
        supply_depot = self.api.config.supply_depot
        if supply_depot is not None:
            payload["ferramentas"] = supply_depot.resumo()
        # Ferramentas Nômades (DECISÃO FINAL): quantas das 8 respondem e
        # quem está fora — o dono vê no Status sem abrir o /health.
        nomad_tools = self.api.config.nomad_tools
        if nomad_tools is not None:
            payload["nomad_tools"] = nomad_tools.resumo()
        # Notifier (pedido do dono, 2026-10-16): emitidos × bloqueados ×
        # erros — sem abrir o journal o dono vê se um alerta está sendo
        # engolido pelo anti-spam (o caso de 35 dias mudos do conserto).
        notifier = self.api.config.notifier
        if notifier is not None:
            payload["notifier"] = notifier.metrics.snapshot()
        # Backups automáticos (TODO §3.6): um bloco por perfil (nome =
        # estado/capturas) com o último snapshot, se a janela está pendente
        # e os arquivos que o dono copia para o HD externo.
        backups = self.api.config.backups
        if backups:
            payload["backup"] = {
                backup.cfg.nome: backup.snapshot() for backup in backups
            }
        # Off-site (canal privado do Telegram, 20/10): o dono vê no
        # Status qual artefato já saiu de casa e quando — sem abrir o
        # canal. None = fora e o bloco some.
        offsite = self.api.config.offsite
        if offsite is not None:
            payload["offsite"] = offsite.snapshot()
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
            store = self.api._user_store
            self._json(200, {
                "ok": True,
                "user": {"id": u.id, "username": u.username, "email": u.email},
                # As preferências vão JUNTO com o "quem sou eu" (TODO §3.8):
                # site, painel e app já chamam /auth/me no boot — assim o
                # tema sincroniza sem uma segunda ida à API.
                "preferences": store.get_preferences(u.id),
                "via": self._auth_via or "session",
                "role": self._role(),
            })
            return
        raise APIError(401, "não autenticado")

    # -- Preferências do perfil (tema claro/escuro) --------------------------

    def _conta_ou_401(self) -> Any:
        """Conta do usuário logado (sessão ou API key de conta).

        Sem conta por trás da credencial (ex.: OD_API_KEY sem admin
        configurado) não há perfil onde gravar — 401 é a resposta honesta.
        """
        if self._current_user is None:
            raise APIError(401, "não autenticado")
        return self._current_user

    def profile_preferences_get(self) -> None:
        """GET /profile/preferences — preferências da conta logada.

        Sempre devolve as chaves conhecidas (padrão + escolhidas), o mesmo
        formato que o PUT aceita — o cliente não precisa do padrão.
        """
        store = self._user_store_or_503()
        user = self._conta_ou_401()
        self._json(200, {"ok": True,
                         "preferences": store.get_preferences(user.id)})

    def profile_preferences_put(self) -> None:
        """PUT /profile/preferences — grava (merge) as preferências da conta.

        Body: {"theme": "system" | "light" | "dark"}. Chave desconhecida
        ou valor fora do contrato é **400** (`preferencia_desconhecida` /
        mensagem do validador): o cliente precisa saber que não guardou.
        """
        store = self._user_store_or_503()
        user = self._conta_ou_401()
        data = self._read_json() if self._has_body() else {}
        try:
            prefs = store.set_preferences(user.id, data)
        except Exception as exc:
            from integrations.api.auth import AuthError
            if isinstance(exc, AuthError):
                raise APIError(exc.status, str(exc))
            raise
        self._json(200, {"ok": True, "preferences": prefs})

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

    def _require_owner_page(self) -> None:
        """Gate de páginas HTML INTERNAS do dono (site_admin/).

        Diferente dos endpoints de dados, isto é navegado pelo browser (link
        clicado no /admin) — browser não manda header, então o token da
        sessão também é aceito na query `?t=<token>`; o /admin monta o link
        já com o token guardado no navegador.

        Só passa quem tem sessão de DONO (o _role() devolve admin apenas
        para o username do dono). Nega também para conta de usuário comum.

        Exceção herdada de _check_api_key: sem UserStore E sem OD_API_KEY a
        auth está explicitamente desligada (dev local) — aí segue liberado,
        como o resto do painel.
        """
        store = self.api._user_store
        if store is None and not self.api.config.api_key:
            return
        token = ""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        if not token:
            query = parse_qs(urlsplit(self.path).query)
            token = (query.get("t") or [""])[0].strip()
        user = store.validate_session(token) if (store is not None and token) else None
        if user is None:
            raise APIError(401, "acesso_restrito")
        self._current_user = user
        self._auth_via = "session"
        if self._role() != "admin":
            log.warn(
                "Acesso à página interna negado (não é o dono)",
                autenticado=user.username,
                path=urlsplit(self.path).path,
            )
            raise APIError(403, "acesso_negado")

    def admin_google_apis(self) -> None:
        """GET /admin/google/apis — habilitar as 3 APIs no projeto Google.

        Página interna do dono: saiu de /site/ (acessível sem credencial)
        e passou a exigir conta de dono — v. _require_owner_page().
        """
        self._require_owner_page()
        self._serve_site_file("google_apis.html", DEFAULT_SITE_ADMIN_DIR)

    def admin_google_auth(self) -> None:
        """GET /admin/google/auth — autorizar o OAuth (Drive/Agenda/Gmail).

        Página interna do dono: saiu de /site/ (acessível sem credencial e
        pelo Funnel público) e passou a exigir conta de dono — v.
        _require_owner_page(). Vazava IP local, client_id e caminho do token.
        """
        self._require_owner_page()
        self._serve_site_file("google_auth.html", DEFAULT_SITE_ADMIN_DIR)

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
        "frente"?: str (2–4 letras, padrão PROD), "tipo"?: str (padrão PE),
        "collection"?: str, "engraved_code"?: str, "price_brl"?: float,
        "notes"?: str}. Gera o public_id canônico FRENTE-TIPO-AAAA-NNNN
        (ex.: NV-SJ-2026-0001); exclusiva sem código gravado ganha um
        curto auto-gerado (NV-ABI-7F3A).

        Frente NV (ciclo fechado, 16/10): coleção OBRIGATÓRIA e precisa
        existir ABERTA — 400 colecao_obrigatoria_nv / colecao_ausente /
        colecao_encerrada (peça não entra em ciclo já encerrado).
        """
        store = self._registry_store_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        try:
            item = store.create(
                name=data.get("name", ""),
                kind=data.get("kind", ""),
                frente=data.get("frente"),
                tipo=data.get("tipo"),
                collection=data.get("collection"),
                engraved_code=data.get("engraved_code"),
                price_brl=data.get("price_brl"),
                notes=data.get("notes"),
            )
        except ValueError as exc:
            raise APIError(400, str(exc))
        self._json(201, {"ok": True, "peca": self._registry_admin_view(item)})

    def admin_registry_list(self) -> None:
        """GET /admin/registry — lista todas as peças (dono; com preço)."""
        store = self._registry_store_or_503()
        itens = [self._registry_admin_view(i) for i in store.list_all()]
        self._json(200, {"ok": True, "total": len(itens), "pecas": itens})

    def admin_registry_collection_create(self) -> None:
        """POST /admin/registry/collections — ABRE um ciclo (dono).

        Body: {"name": str}. Erros: 400 colecao_nome_invalido (3–40,
        letras/números/espaço) e 400 colecao_ja_existe (não existe
        "reabrir" ciclo velho — um nome = um ciclo, para sempre).
        """
        store = self._registry_store_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        try:
            col = store.criar_colecao(data.get("name", ""))
        except ValueError as exc:
            raise APIError(400, str(exc))
        self._json(201, {"ok": True,
                         "colecao": {"name": col["name"], "ciclo": "aberta",
                                     "criada_em": col["created_at"],
                                     "encerrada_em": None}})

    def admin_registry_collection_close(self, nome: str) -> None:
        """POST /admin/registry/collections/{nome}/encerrar — fecha o ciclo
        PARA SEMPRE (dono; PROTOCOLO_NV: "uma vez Encerrada, nunca é
        reeditada"). Não existe rota de reabrir/renomear/apagar — só de
        encerrar, e só uma vez: 400 colecao_ja_encerrada na segunda.

        Erros: 404 colecao_inexistente, 400 colecao_ja_encerrada.
        """
        store = self._registry_store_or_503()
        try:
            col = store.encerrar_colecao(unquote(nome))
        except ValueError as exc:
            if str(exc) == "colecao_inexistente":
                raise APIError(404, str(exc))
            raise APIError(400, str(exc))
        self._json(200, {"ok": True,
                         "colecao": {"name": col["name"], "ciclo": "encerrada",
                                     "criada_em": col["created_at"],
                                     "encerrada_em": col["closed_at"]}})

    @staticmethod
    def _registry_admin_view(item: dict[str, Any]) -> dict[str, Any]:
        """Item admin sem o HASH da posse (o hash é interno; vira só
        `tem_posse` para o painel mostrar que já existe QR emitido)."""
        view = {k: v for k, v in item.items() if k != "posse_code_hash"}
        view["tem_posse"] = bool(item.get("posse_code_hash"))
        return view

    def admin_registry_update(self, public_id: str) -> None:
        """PUT /admin/registry/{public_id} — atualiza uma peça (dono).

        Body: campos de whitelist (name, collection, kind, status,
        price_brl, owner_username, notes, engraved_code). Status
        "registrada" exige dono (owner_username); voltar DE registrada
        (estoque/vendida) exige `posse_code` — a prova secreta da
        Etapa 4 (sem ela: 400 registro_pendente_codigo_secreto).
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
        self._json(200, {"ok": True, "peca": self._registry_admin_view(item)})

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

    def admin_registry_posse(self, public_id: str) -> None:
        """POST /admin/registry/{public_id}/posse — gera/regenera o código (QR).

        Etapa 4: o código sai em claro na resposta (o dono imprime no
        cartão); o banco guarda só o sha256. Regenerar invalida o
        anterior na hora (cartão perdido → código novo, o antigo não
        registra mais). Peça `publica` responde 400 publica_sem_posse.
        """
        store = self._registry_store_or_503()
        try:
            gero = store.gerar_posse(public_id)
        except ValueError as exc:
            raise APIError(
                404 if str(exc) == "peca_inexistente" else 400, str(exc)
            )
        self._json(201, {
            "ok": True,
            "codigo_posse": gero["codigo_posse"],
            "regenerado": gero["regenerado"],
            "public_id": gero["public_id"],
            "url": self._posse_url(gero["codigo_posse"]),
        })

    def admin_registry_qr(self, public_id: str) -> None:
        """GET /admin/registry/{public_id}/posse/qr?codigo=POSSE-… — SVG do QR.

        O código vem na query porque o banco guarda SÓ o hash (não dá
        para re-renderizar do nada); ele precisa bater com o hash da
        peça (?codigo= errado → 400 posse_invalida). QR aponta para a
        página de verificação com o código embutido — o comprador lê
        (câmera do celular) e cola no app. Lib `qrcode` (requirements);
        ausente → 503 qr_indisponivel sem derrubar nada (padrão da casa).
        """
        store = self._registry_store_or_503()
        item = store.get(public_id)
        if item is None:
            raise APIError(404, "peca_inexistente")
        query = parse_qs(urlsplit(self.path).query)
        codigo = str(query.get("codigo", [""])[0] or "")
        if not store.posse_valida(item, codigo):
            raise APIError(400, "posse_invalida")
        try:
            import qrcode
            from qrcode.image.svg import SvgPathImage
        except ImportError as exc:  # pragma: no cover — dep ausente
            raise APIError(503, "qr_indisponivel") from exc
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(self._posse_url(codigo))
        qr.make(fit=True)
        imagem = qr.make_image(image_factory=SvgPathImage)
        buffer = io.BytesIO()
        imagem.save(buffer)
        svg = buffer.getvalue()
        self.send_response(200)
        self._send_cors()
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(svg)))
        self.send_header("Cache-Control", "no-store")  # código é secreto
        self.end_headers()
        self.wfile.write(svg)

    def _posse_url(self, codigo_posse: str) -> str:
        """URL absoluta que o QR carrega (página pública de verificação)."""
        base = str(self.api.config.public_url or "").rstrip("/")
        return f"{base}/site/verificacao.html?posse={codigo_posse}"

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

    # ------------------------------------------------------------------#
    # Fila de downloads resumable (Parte D do NOMAD, 2026-10-14)        #
    # ------------------------------------------------------------------#
    def _downloads_or_503(self) -> Any:
        fila = self.api.config.downloads
        if fila is None:
            raise APIError(503, "downloads_indisponivel")
        return fila

    def admin_downloads_create(self) -> None:
        """POST /admin/downloads — enfileira; dedup devolve 200 (não 201).

        Body: {"url": "https://…/peso.gguf", "destino"?: "sub/peso.gguf"}
        """
        self._require_admin()
        fila = self._downloads_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "body_invalido")
        try:
            job, criado = fila.enqueue(
                str(data.get("url") or ""), str(data.get("destino") or ""),
                str(data.get("sha256") or ""),
            )
        except ValueError as exc:
            raise APIError(400, str(exc)) from exc
        self._json(201 if criado else 200,
                   {"ok": True, "job": job.para_dict(),
                    "duplicado": not criado})

    def admin_downloads_list(self) -> None:
        """GET /admin/downloads — fila inteira (FIFO) + resumo."""
        self._require_admin()
        fila = self._downloads_or_503()
        self._json(200, {"ok": True, "jobs": fila.lista(),
                         "resumo": fila.snapshot()})

    def admin_downloads_events(self) -> None:
        """GET /admin/downloads/events — SSE do progresso ao vivo.

        Abre com um evento `snapshot` (fila inteira); depois vêm
        `estado`/`progresso`/`removido` a cada transição. `: ping` quando
        15 s passam sem eventos (keepalive atrás de proxy — enquanto há
        progresso, o próprio fluxo já mantém o canal vivo). O loop sai em
        ~1 s quando o servidor encerra (stop()) e na primeira escrita
        falha quando o cliente foi embora.
        """
        self._require_admin()
        fila = self._downloads_or_503()
        eventos, cancela = fila.subscribe()
        try:
            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self._sse({"evento": "snapshot", "jobs": fila.lista(),
                       "resumo": fila.snapshot()})
            ultimo = time.time()
            while not self.api.encerrando.is_set():
                try:
                    pacote = eventos.get(timeout=1.0)
                except queue_mod.Empty:
                    pacote = None
                if pacote is not None:
                    self._sse(pacote)
                    ultimo = time.time()
                elif time.time() - ultimo >= 15.0:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    ultimo = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # cliente fechou o stream
        finally:
            cancela()

    def _sse(self, pacote: dict[str, Any]) -> None:
        """Uma linha `data: <json>` + linha em branco (formato SSE)."""
        linha = json.dumps(pacote, ensure_ascii=False)
        self.wfile.write(f"data: {linha}\n\n".encode("utf-8"))
        self.wfile.flush()

    def admin_downloads_detail(self, job_id: str) -> None:
        """GET /admin/downloads/{job_id} — polling de um job."""
        self._require_admin()
        fila = self._downloads_or_503()
        job = fila.get(job_id)
        if job is None:
            raise APIError(404, "job_inexistente")
        self._json(200, {"ok": True, "job": job.para_dict()})

    def admin_downloads_cancel(self, job_id: str) -> None:
        """POST /admin/downloads/{job_id}/cancel — cancela (idempotente)."""
        self._require_admin()
        fila = self._downloads_or_503()
        try:
            job = fila.cancelar(job_id)
        except ValueError as exc:
            raise APIError(404, str(exc)) from exc
        self._json(200, {"ok": True, "job": job.para_dict()})

    def admin_downloads_delete(self, job_id: str) -> None:
        """DELETE /admin/downloads/{job_id} — só job terminal (409 se ativo).

        Apaga o REGISTRO: o arquivo baixado e o `.part` ficam em disco.
        """
        self._require_admin()
        fila = self._downloads_or_503()
        try:
            fila.remover(job_id)
        except ValueError as exc:
            codigo = str(exc)
            raise APIError(409 if codigo == "job_ativo" else 404,
                           codigo) from exc
        self._json(200, {"ok": True, "removido": job_id})

    # ------------------------------------------------------------------#
    # Auto-update de modelos/conteúdo (Parte E do NOMAD, 2026-10-14)     #
    # ------------------------------------------------------------------#
    def _auto_update_or_503(self) -> Any:
        svc = self.api.config.auto_update
        if svc is None:
            raise APIError(503, "auto_update_indisponivel")
        return svc

    def admin_auto_update_get(self) -> None:
        """GET /admin/auto-update — config + alvos + estado + decisões.

        O resumo é o MESMO formato do health_check (painel e testes
        leem a mesma fonte); `desabilitados` é o que o dono religa pelo
        POST /admin/auto-update/reset.
        """
        self._require_admin()
        svc = self._auto_update_or_503()
        self._json(200, {"ok": True, "metricas": svc.metricas.snapshot(),
                         **svc.estado_resumo()})

    def admin_auto_update_dry_run(self) -> None:
        """POST /admin/auto-update/dry-run — avalia sem executar (CI/painel).

        O caminho é o MESMO do tick de produção (avaliar() puro), só que
        sobre cópia do estado: nada é gravado, nenhum download é
        enfileirado, nenhum índice é re-sincronizado. Devolve a lista de
        decisões (aplicar/aguardar/pular + motivo) e o resumo do estado.
        """
        self._require_admin()
        svc = self._auto_update_or_503()
        decisoes = svc.tick(dry_run=True)
        self._json(200, {"ok": True, "dry_run": True,
                         "decisoes": [d.para_dict() for d in decisoes],
                         "metricas": svc.metricas.snapshot(),
                         **svc.estado_resumo()})

    def admin_auto_update_reset(self) -> None:
        """POST /admin/auto-update/reset — religa um alvo auto-desligado.

        Body: {"alvo": "indice-rag", ...}. Auto-disable é barato (3 falhas
        duras), religar é do DONO — aqui, e pelo painel.
        """
        self._require_admin()
        svc = self._auto_update_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict) or not str(data.get("alvo") or ""):
            raise APIError(400, "alvo_obrigatorio")
        alvo = str(data["alvo"])
        if not svc.resetar_alvo(alvo):
            raise APIError(404, "alvo_inexistente")
        self._json(200, {"ok": True, "religado": alvo})

    # ------------------------------------------------------------------#
    # Supply Depot — registro de ferramentas (Parte F do NOMAD, 2026-10-15) #
    # ------------------------------------------------------------------#
    def _supply_depot_or_503(self) -> Any:
        depot = self.api.config.supply_depot
        if depot is None:
            raise APIError(503, "supply_depot_indisponivel")
        return depot

    def admin_ferramentas_list(self) -> None:
        """GET /admin/ferramentas — catálogo vivo + resumo do depot.

        Cada entrada traz `no_registry` (estado real no ActionRegistry) e
        `anteriores` (backup disponível p/ rollback).
        """
        self._require_admin()
        depot = self._supply_depot_or_503()
        self._json(200, {"ok": True, "ferramentas": depot.listar(),
                         **depot.resumo()})

    def admin_ferramentas_create(self) -> None:
        """POST /admin/ferramentas — instala/atualiza com pré-voo no caminho.

        Body: {nome, codigo, versao?, descricao?, categoria?, params?,
        permission?, funcao?, substituir?}. Código obrigatório (é a fonte
        da verdade do depot). 201 = instalou / 200 = atualizou ou já
        estava na versão / 409 = pré-voo bloqueou (conflito, downgrade,
        major sem confirmação) / 400 = código rejeitado (sintaxe,
        allowlist, função ausente) / 500 = falha no meio → rollback.
        """
        self._require_admin()
        depot = self._supply_depot_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "corpo_invalido")
        nome = str(data.get("nome") or "").strip()
        codigo = data.get("codigo")
        if not nome:
            raise APIError(400, "nome_obrigatorio")
        if not isinstance(codigo, str) or not codigo.strip():
            raise APIError(400, "codigo_obrigatorio")
        params = data.get("params")
        resultado = depot.instalar(
            nome=nome,
            codigo=codigo,
            versao=str(data.get("versao") or "1.0.0"),
            descricao=str(data.get("descricao") or ""),
            categoria=str(data.get("categoria") or "manual"),
            params=params if isinstance(params, dict) else None,
            permission=str(data.get("permission") or ""),
            origem=str(data.get("origem") or "manual"),
            confirmar=bool(data.get("substituir") or data.get("confirmar")),
            funcao=str(data.get("funcao") or ""),
        )
        if resultado.get("ok"):
            status = 201 if resultado.get("acao") == "instalar" else 200
            self._json(status, {"ok": True, **resultado})
            return
        if resultado.get("rollback"):
            raise APIError(500, str(resultado.get("motivo") or "rollback"))
        if resultado.get("acao") == "bloquear":
            # Pré-voo: conflito de nome, downgrade, major sem confirmação,
            # código grande demais ou disco — o dono decide o próximo passo.
            raise APIError(409, str(resultado.get("motivo") or "bloqueado"))
        raise APIError(400, str(resultado.get("motivo") or "codigo_rejeitado"))

    def admin_ferramentas_update(self, id: str) -> None:
        """PUT /admin/ferramentas/{id} — customização do dono.

        Body: {descricao?, params?, permission?, ativa?}. As
        sobrescritas ficam em `custom` e SOBREVIVEM a atualizações e a
        rollback (é a peça central da "preservar customização").
        `ativa: false` desinstala (arquivo vai pro backup), `ativa: true`
        reativa.
        """
        self._require_admin()
        depot = self._supply_depot_or_503()
        data = self._read_json() if self._has_body() else {}
        if not isinstance(data, dict):
            raise APIError(400, "corpo_invalido")
        resultado = depot.customizar(
            id,
            descricao=data.get("descricao"),
            params=data.get("params"),
            permission=data.get("permission"),
            ativa=data.get("ativa"),
        )
        if resultado.get("ok"):
            self._json(200, resultado)
            return
        motivo = str(resultado.get("motivo") or "")
        if motivo == "ferramenta_inexistente":
            raise APIError(404, motivo)
        if motivo in ("params_invalido", "nada_para_alterar",
                      "codigo_ausente_em_disco", "funcao_nao_encontrada"):
            raise APIError(400, motivo)
        raise APIError(500, motivo or "falha_na_customizacao")

    def admin_ferramentas_rollback(self, id: str) -> None:
        """POST /admin/ferramentas/{id}/rollback — volta para a versão
        anterior (ou a `versao` pedida no body). Histórico guardado em
        data/ferramentas_backup/. 409 = sem histórico (nunca atualizou).
        """
        self._require_admin()
        depot = self._supply_depot_or_503()
        data = self._read_json() if self._has_body() else {}
        versao = str(data.get("versao") or "") if isinstance(data, dict) else ""
        resultado = depot.rollback(id, versao=versao or None)
        if resultado.get("ok"):
            self._json(200, resultado)
            return
        motivo = str(resultado.get("motivo") or "")
        if motivo == "ferramenta_inexistente" or \
                motivo.startswith("versao_nao_encontrada"):
            raise APIError(404, motivo)
        if motivo == "sem_historico_de_versoes":
            raise APIError(409, motivo)
        if resultado.get("rollback") or motivo.startswith("backup_ausente"):
            raise APIError(500, motivo)
        raise APIError(500, motivo or "rollback_falhou")

    def admin_ferramentas_delete(self, id: str) -> None:
        """DELETE /admin/ferramentas/{id} — desinstala (não destrutivo):
        sai do registry e do catálogo, o arquivo fica preservado como
        `data/ferramentas_backup/<id>.removido.v<versao>.py`.
        """
        self._require_admin()
        depot = self._supply_depot_or_503()
        resultado = depot.remover(id)
        if resultado.get("ok"):
            self._json(200, resultado)
            return
        raise APIError(404, str(resultado.get("motivo") or "nao_removido"))

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
    #: 'freebuff' saiu em 10/10: a 0.2.22 ficou interativa apenas (ver
    #: orquestrador.CLIS) — aceitá-la aqui devolveria 400 em todo clique.
    SESSAO_CLIS = ("auto", "opencode", "kilo")

    def admin_dev_sessao(self) -> None:
        """POST /admin/dev/sessao — ativa/para UMA sessão de desenvolvimento.

        Body: {"acao": "ativar"|"parar", "cli"?: "auto"|"opencode"|"kilo"}

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
