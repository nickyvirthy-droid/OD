"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/api/ws_server.py
Descrição: Servidor WebSocket para streaming token-a-token do chat.
           Permite que o app Flutter receba a resposta do LLM conforme
           é gerada, em vez de esperar o bloco inteiro.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Protocolo:
  Cliente -> Servidor:
    {"type": "auth", "api_key": "..."}                    # OD_API_KEY (app/bot)
    {"type": "auth", "api_key": "...", "user_id": "..."}   # idem, escolhe o balde
    {"type": "auth", "token": "..."}                      # sessão do chat web
    {"type": "auth", "api_key": "od_..."}                 # API key de usuário
    {"type": "message", "text": "...", "profile": "...", "session_id": "..."}

Identidade (mesma regra do POST /message do REST):
  - credencial de USUÁRIO (sessão `token` ou API key `od_...`) → o servidor usa
    o username autenticado e IGNORA o `user_id` do frame;
  - OD_API_KEY do servidor (app/bot, sem usuário associado) → vale o `user_id`
    do frame, validado por `valid_user_id`;
  - sem chaves e sem UserStore (dev local) → aberto, vale o `user_id` do frame.

  Servidor -> Cliente:
    {"type": "authenticated"}
    {"type": "processing"}
    {"type": "token", "content": "..."}
    {"type": "done", "content": "...", "route": "...", "llm_used": "..."}
    {"type": "error", "message": "..."}

O servidor usa a API moderna do websockets (>=14):
`websockets.asyncio.server.serve`. O import é TARDIO (dentro de start()), no
mesmo espírito do google-auth em core/push.py: sem a dependência instalada o
resto do sistema continua de pé e o WebSocket simplesmente não sobe.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
from typing import Any, Optional

from core.logger import get_logger
from core.orchestrator import Orchestrator

# Mesma lista/registro do REST (`/message`) — o streaming precisa resolver
# `auto` e recusar perfil desconhecido IGUAL, senão a mesma conversa cai em
# baldes diferentes de cache/histórico conforme o transporte (o app manda
# `auto` por padrão).
from core.identity import resolve_account
from integrations.api.server import DEFAULT_PROFILE, DEFAULT_PROFILES, valid_user_id

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.api.ws")

# Porta padrão do WebSocket (separada da API REST)
DEFAULT_WS_PORT = 8001

# Subida/parada da thread: start() é síncrono, então espera o bind de verdade.
START_TIMEOUT_S = 5.0
STOP_TIMEOUT_S = 5.0

# Nomes das exceções de desconexão do websockets (import tardio → comparar por
# nome evita importar o pacote só para isso). Desconexão de cliente é rotina e
# NÃO deve virar WARN no journal (mesma lição do handle_error de 2026-09-15).
CLOSED_EXC_NAMES = {"ConnectionClosed", "ConnectionClosedOK", "ConnectionClosedError"}


class _LibraryLogger(logging.LoggerAdapter):
    """Redireciona o log do websockets para o log do OD, sem traceback.

    O padrão da biblioteca é `logger.error(..., exc_info=True)`: um TCP cru que
    abre e fecha (sonda de porta, health check, port scanner) faz o stderr
    ganhar um traceback inteiro de `handshake_exc`. É exatamente o ruído que o
    handle_error do http.server causava (2026-09-15) e recebe o mesmo
    tratamento: UMA linha no log, sem stack.

    O projeto é quem sabe formatar (NickyLogger só aceita `msg` + campos), por
    isso o %-style da biblioteca é resolvido aqui antes de repassar.

    Tudo cai em DEBUG: o que é acionável (falha de handler, erro de protocolo)
    já é logado por `_handle_connection`; o resto — sonda de porta, keepalive,
    encerramento — é conversa da biblioteca. Com OD_LOG_LEVEL=DEBUG aparece.
    """

    def log(self, level: int, msg: Any, *args: Any, **kwargs: Any) -> None:  # noqa: A003
        kwargs.pop("exc_info", None)
        kwargs.pop("stack_info", None)
        try:
            texto = msg % args if args else str(msg)
        except Exception:  # pragma: no cover — formato inesperado da lib
            texto = str(msg)
        log.debug(f"websockets: {texto}", lib_level=logging.getLevelName(level))


class WebSocketAuthError(Exception):
    """Autenticação falhou."""


class WebSocketServer:
    """Servidor WebSocket para streaming do chat.
    
    Attributes:
        orchestrator: Pipeline central para processar mensagens.
        port: Porta do servidor WebSocket.
        api_keys: Conjunto de chaves de API válidas.
    """
    
    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        port: int = DEFAULT_WS_PORT,
        api_keys: Optional[set[str]] = None,
        host: str = "0.0.0.0",
        profiles: tuple[str, ...] = DEFAULT_PROFILES,
        user_store: Optional[Any] = None,
        account_aliases: Optional[dict[str, str]] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.host = host
        self.port = port
        self.api_keys = api_keys or set()
        self.profiles = profiles
        # Alias de transporte legado → conta do dono (core/identity.py): o app
        # manda `user_id: "app"` fixo no frame de auth; apontar para a conta
        # faz o stream gravar no mesmo balde do REST e do chat web.
        self.account_aliases = dict(account_aliases or {})
        # UserStore (integrations/api/auth.py): quando presente, sessão e API
        # key de usuário passam a autenticar aqui também — é o que dá identidade
        # ao stream (antes o cliente dizia quem era).
        self.user_store = user_store
        self._server = None
        self._serve: Any = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connections: dict[str, Any] = {}
        self._bound_port = 0
        self._ready = threading.Event()
        self._start_error: Optional[BaseException] = None
        
    def _authenticate(self, data: dict[str, Any]) -> tuple[bool, str, str]:
        """Resolve o frame `auth` em (ok, identidade, via).

        Ordem espelha o gate do REST (`APIHandler._check_api_key`):
          1. `token` de sessão (chat web) → `UserStore.validate_session`;
          2. `api_key` de USUÁRIO (`od_...`) → `UserStore.login_with_api_key`;
          3. `api_key` do SERVIDOR (OD_API_KEY) → sem usuário associado, quem
             escolhe o balde é o cliente (é assim que o app fala hoje).

        `identidade` vazia significa "sem usuário": o `user_id` do frame vale.
        Com UserStore configurada e sem OD_API_KEY a credencial é obrigatória
        (mesma correção do bypass feita no REST em 2026-09-20) — sem isso, um
        `auth` vazio passaria no caminho "auth desligada".
        """
        store = self.user_store
        token = str(data.get("token") or "").strip()
        if token and store is not None:
            user = store.validate_session(token)
            if user is not None:
                return True, user.username, "session"
        api_key = str(data.get("api_key") or "").strip()
        if api_key and store is not None:
            user = store.login_with_api_key(api_key)
            if user is not None:
                return True, user.username, "api_key"
        if api_key:
            for valida in self.api_keys:
                if hmac.compare_digest(api_key, valida):
                    return True, "", "server"
        if not self.api_keys and store is None:
            return True, "", "dev"  # dev local explícito, sem auth configurada
        return False, "", "api_key_invalida"

    async def _handle_connection(self, ws: Any) -> None:
        """Lida com uma conexão WebSocket."""
        conn_id = f"{ws.remote_address[0]}:{ws.remote_address[1]}" if ws.remote_address else "unknown"
        log.info("WebSocket connection opened", conn_id=conn_id)
        
        authenticated = False
        user_id = "ws_user"
        identidade = ""  # username vindo da credencial ("" = sem usuário)
        
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    await ws.send(json.dumps({"type": "error", "message": "json_invalido"}))
                    continue
                
                msg_type = data.get("type")
                
                # Autenticação
                if msg_type == "auth":
                    ok, identidade, via = self._authenticate(data)
                    if not ok:
                        await ws.send(json.dumps({"type": "error", "message": via}))
                        await ws.close(code=4001, reason="Unauthorized")
                        return
                    pedido = str(data.get("user_id") or "").strip()
                    if pedido and not valid_user_id(pedido):
                        await ws.send(json.dumps({
                            "type": "error", "message": "user_id_invalido",
                        }))
                        await ws.close(code=4002, reason="Invalid user_id")
                        return
                    authenticated = True
                    # Com usuário autenticado a credencial manda; sem usuário
                    # (OD_API_KEY do app/bot) vale o user_id do frame — passando
                    # pelo alias de transporte legado → conta do dono.
                    if identidade:
                        user_id = identidade
                    else:
                        user_id = resolve_account(
                            pedido or "ws_user", self.account_aliases
                        )
                    await ws.send(json.dumps({"type": "authenticated"}))
                    log.info(
                        "WebSocket authenticated",
                        conn_id=conn_id, user_id=user_id, via=via,
                    )
                    continue
                
                # Se não autenticado e tem chaves configuradas, rejeitar
                if not authenticated and self.api_keys:
                    await ws.send(json.dumps({"type": "error", "message": "nao_autenticado"}))
                    continue
                
                # Processar mensagem
                if msg_type == "message":
                    text = data.get("text", "").strip()
                    if not text:
                        await ws.send(json.dumps({"type": "error", "message": "text_obrigatorio"}))
                        continue
                    
                    # Mesma resolução do REST: perfil desconhecido é erro,
                    # `auto` vira o perfil padrão (guardian).
                    profile = str(
                        data.get("profile") or DEFAULT_PROFILE
                    ).strip()
                    if profile not in self.profiles:
                        await ws.send(json.dumps({
                            "type": "error",
                            "message": f"perfil_desconhecido: {profile}",
                        }))
                        continue
                    if profile == "auto":
                        profile = DEFAULT_PROFILE
                    # Identidade fixada na credencial: um `user_id` enviado
                    # depois do auth não troca de balde (mesma regra do REST).
                    efetivo = identidade or user_id
                    session_id = data.get("session_id", f"ws:{efetivo}")
                    
                    # Enviar confirmação de recebimento
                    await ws.send(json.dumps({"type": "processing"}))
                    
                    # Processar com streaming
                    try:
                        async for chunk in self.orchestrator.process_stream(
                            user_id=efetivo,
                            profile=profile,
                            text=text,
                            session_id=session_id,
                        ):
                            await ws.send(json.dumps(chunk))
                    except Exception as exc:
                        if type(exc).__name__ in CLOSED_EXC_NAMES:
                            # Cliente caiu no meio do stream (app sem rede, aba
                            # fechada): rotina, uma linha de debug e nada de
                            # tentar responder em cima de conexão morta.
                            log.debug(
                                "Cliente desconectou durante o stream",
                                conn_id=conn_id,
                                error=str(exc),
                            )
                            raise
                        log.error("WebSocket processing error", error=str(exc))
                        await ws.send(json.dumps({
                            "type": "error",
                            "message": f"erro_processamento: {type(exc).__name__}"
                        }))
                else:
                    await ws.send(json.dumps({"type": "error", "message": f"tipo_desconhecido: {msg_type}"}))
                    
        except Exception as exc:
            # Desconexão de cliente é rotina (app em rede ruim, aba fechada).
            if type(exc).__name__ not in CLOSED_EXC_NAMES:
                log.warn("WebSocket connection error", conn_id=conn_id, error=str(exc))
        finally:
            log.info("WebSocket connection closed", conn_id=conn_id)

    # -- Ciclo de vida -------------------------------------------------------

    async def _serve_forever(self, serve: Any) -> None:
        """Abre o servidor e fica até o stop()."""
        async with serve(
            self._handle_connection,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=10,
            logger=_LibraryLogger(logging.getLogger("websockets.server")),
        ) as server:
            self._server = server
            # Porta real (importante quando port == 0, o caso dos testes).
            self._bound_port = int(server.sockets[0].getsockname()[1])
            self._ready.set()
            log.info(
                "WebSocket server no ar",
                host=self.host,
                port=self._bound_port,
                auth=bool(self.api_keys),
            )
            await server.wait_closed()

    def _thread_main(self) -> None:
        """Corpo da thread: o event loop é criado E usado aqui dentro."""
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve_forever(self._serve))
        except BaseException as exc:  # noqa: BLE001 — nada escapa da thread
            if self._ready.is_set():
                # Já estava no ar: falha em runtime, contida e logada.
                if type(exc).__name__ not in CLOSED_EXC_NAMES:
                    log.warn(
                        "WebSocket server encerrou com erro",
                        error=f"{type(exc).__name__}: {exc}",
                    )
            else:
                # Falhou ao subir (porta ocupada, dependência ausente):
                # start() precisa ver o erro para decidir. Sem traceback cru.
                self._start_error = exc
                self._ready.set()
        finally:
            self._ready.set()
            try:
                self._loop.close()
            except Exception:  # pragma: no cover — melhor esforço
                pass

    def start(self) -> None:
        """Inicia o servidor WebSocket em uma thread separada.

        É síncrono de propósito: só retorna quando o socket está de fato
        escutando. Se não subir, levanta RuntimeError com o motivo — quem
        chama (launcher) loga e segue, em vez de ficar com uma thread morta.
        """
        if self.is_running:
            return
        # Import tardio: sem websockets instalado, o core continua de pé.
        try:
            from websockets.asyncio.server import serve
        except ImportError as exc:  # pragma: no cover — dependência ausente
            raise RuntimeError(
                "websockets não instalado (pip install -r requirements.txt)"
            ) from exc

        self._serve = serve
        self._start_error = None
        self._ready.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._thread_main, name="od-ws-server", daemon=True
        )
        self._thread.start()

        if not self._ready.wait(timeout=START_TIMEOUT_S):
            raise RuntimeError(
                f"timeout ao subir o WebSocket server (porta {self.port})"
            )
        if self._start_error is not None:
            raise RuntimeError(
                "falha ao subir o WebSocket server: "
                f"{type(self._start_error).__name__}: {self._start_error}"
            ) from self._start_error

    def stop(self) -> None:
        """Para o servidor WebSocket e a thread (idempotente)."""
        server, loop = self._server, self._loop
        if server is not None and loop is not None and loop.is_running():
            try:
                # Server.close() é SÍNCRONO no websockets.asyncio (quem espera
                # é o wait_closed() do _serve_forever). Precisa rodar na thread
                # do loop, por isso call_soon_threadsafe.
                loop.call_soon_threadsafe(server.close)
            except RuntimeError:  # pragma: no cover — loop já encerrando
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=STOP_TIMEOUT_S)
            if thread.is_alive():  # pragma: no cover — melhor esforço
                log.warn("WebSocket server não encerrou no prazo", port=self._bound_port)
                return
        self._thread = None
        self._server = None
        self._loop = None
        log.info("WebSocket server parado", port=self._bound_port)

    @property
    def bound_port(self) -> int:
        """Porta real de escuta (útil quando port == 0)."""
        return self._bound_port or self.port

    @property
    def is_running(self) -> bool:
        """Verifica se o servidor está rodando de fato.

        Thread viva não basta: uma thread que falhou no bind também fica viva
        por alguns instantes enquanto encerra o loop.
        """
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._start_error is None
        )

