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
    {"type": "auth", "api_key": "..."}
    {"type": "message", "text": "...", "profile": "...", "session_id": "..."}

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
import json
import logging
import threading
from typing import Any, Optional

from core.logger import get_logger
from core.orchestrator import Orchestrator

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
    ) -> None:
        self.orchestrator = orchestrator
        self.host = host
        self.port = port
        self.api_keys = api_keys or set()
        self._server = None
        self._serve: Any = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connections: dict[str, Any] = {}
        self._bound_port = 0
        self._ready = threading.Event()
        self._start_error: Optional[BaseException] = None
        
    async def _handle_connection(self, ws: Any) -> None:
        """Lida com uma conexão WebSocket."""
        conn_id = f"{ws.remote_address[0]}:{ws.remote_address[1]}" if ws.remote_address else "unknown"
        log.info("WebSocket connection opened", conn_id=conn_id)
        
        authenticated = False
        user_id = "ws_user"
        
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
                    api_key = data.get("api_key", "")
                    if self.api_keys and api_key not in self.api_keys:
                        await ws.send(json.dumps({"type": "error", "message": "api_key_invalida"}))
                        await ws.close(code=4001, reason="Unauthorized")
                        return
                    authenticated = True
                    user_id = data.get("user_id", "ws_user")
                    await ws.send(json.dumps({"type": "authenticated"}))
                    log.info("WebSocket authenticated", conn_id=conn_id, user_id=user_id)
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
                    
                    profile = data.get("profile", "guardian")
                    session_id = data.get("session_id", f"ws:{user_id}")
                    
                    # Enviar confirmação de recebimento
                    await ws.send(json.dumps({"type": "processing"}))
                    
                    # Processar com streaming
                    try:
                        async for chunk in self.orchestrator.process_stream(
                            user_id=user_id,
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

