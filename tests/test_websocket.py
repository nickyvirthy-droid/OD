"""
Testes do servidor WebSocket de streaming (integrations/api/ws_server.py).

Histórico (2026-09-18): a primeira versão deste arquivo só conferia formato de
dict e existência de método — passava 14/14 enquanto `WebSocketServer.start()`
quebrava com `import websockets.serve` (ModuleNotFoundError). Os testes abaixo
chamam `start()` de verdade e falam com o servidor por um cliente WebSocket
real; é isso que pina o caminho que estava quebrado.
"""

import asyncio
import json
import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from core.logger import LogLevel, get_logger

# Logger compartilhado do módulo sob teste (mesma instância: get_logger cacheia).
WS_LOG_NAME = "omega.integrations.api.ws"


def _espera_registro(logger, trecho: str, timeout: float = 3.0) -> bool:
    """Espera um registro com `trecho` na mensagem (evidência positiva)."""
    limite = time.time() + timeout
    while time.time() < limite:
        if any(trecho in r.message for r in logger.records):
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def ws_log():
    """Ring buffer do logger do WS em DEBUG (o logger global é INFO)."""
    logger = get_logger(WS_LOG_NAME)
    nivel_original = logger.level
    logger.set_level(LogLevel.DEBUG)
    logger.clear_records()
    try:
        yield logger
    finally:
        logger.clear_records()
        logger.set_level(nivel_original)


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------


class _ColetorBiblioteca(logging.Handler):
    """Captura o que o websockets escrever DIRETO no logging (sem o adapter)."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


class StubOrchestrator:
    """Orchestrator mínimo: só o `process_stream` que o servidor consome."""

    def __init__(self, chunks=None, error=None):
        self.calls: list[dict] = []
        self._chunks = chunks if chunks is not None else [
            {"type": "token", "content": "Olá"},
            {"type": "token", "content": ", mundo"},
            {
                "type": "done",
                "content": "Olá, mundo",
                "route": "llm",
                "llm_used": "stub",
                "latency_ms": 1.5,
            },
        ]
        self._error = error

    async def process_stream(self, user_id, profile, text, *, session_id=""):
        self.calls.append(
            {"user_id": user_id, "profile": profile, "text": text, "session_id": session_id}
        )
        if self._error is not None:
            raise self._error
        for chunk in self._chunks:
            yield chunk


class StreamingProvider:
    """Provider com streaming real (async generator), no contrato do Orchestrator."""

    name = "stream-fake"

    def __init__(self, chunks=("Stream", "ing", " ok")):
        self.chunks = chunks
        self.stream_calls = 0
        self.generate_calls = 0

    async def generate_stream(self, prompt, **options):
        self.stream_calls += 1
        assert "timeout" in options
        for chunk in self.chunks:
            yield chunk

    async def generate(self, prompt, **options):  # pragma: no cover — não usado
        self.generate_calls += 1
        return "".join(self.chunks)


# Teto de tempo para CADA fluxo de cliente. Sem isso, um servidor que deixa de
# responder corretamente faz o teste PENDURAR em vez de falhar (aconteceu na
# mutação que removia a checagem de api_key: o cliente ficava esperando um
# frame de erro que nunca vinha).
FLOW_TIMEOUT_S = 10.0


def _run(coro):
    async def _com_teto():
        return await asyncio.wait_for(coro, timeout=FLOW_TIMEOUT_S)

    return asyncio.run(_com_teto())


# ---------------------------------------------------------------------------
# Construção e ciclo de vida (o que estava quebrado)
# ---------------------------------------------------------------------------


class TestWebSocketServerCicloDeVida:
    """start()/stop() — o caminho que os testes de formato não cobriam."""

    def test_init(self):
        from integrations.api.ws_server import DEFAULT_WS_PORT, WebSocketServer

        server = WebSocketServer(MagicMock())
        assert server.port == DEFAULT_WS_PORT
        assert server.api_keys == set()
        assert not server.is_running

    def test_start_abre_socket_real_e_stop_encerra(self):
        """start() sobe mesmo (import real do websockets) e libera no stop()."""
        from integrations.api.ws_server import WebSocketServer

        server = WebSocketServer(MagicMock(), port=0, host="127.0.0.1")
        try:
            server.start()
            assert server.is_running
            assert server.bound_port > 0  # porta real, não a sentinela 0

            async def _conecta():
                from websockets.asyncio.client import connect

                async with connect(f"ws://127.0.0.1:{server.bound_port}") as ws:
                    await ws.send(json.dumps({"type": "auth", "api_key": "x"}))
                    return json.loads(await ws.recv())

            assert _run(_conecta()) == {"type": "authenticated"}
        finally:
            server.stop()

        assert not server.is_running

        # A porta foi mesmo liberada: outro servidor sobe no mesmo lugar.
        outro = WebSocketServer(MagicMock(), port=server.bound_port, host="127.0.0.1")
        try:
            outro.start()
            assert outro.bound_port == server.bound_port
        finally:
            outro.stop()

    def test_stop_e_idempotente_e_sem_start(self):
        from integrations.api.ws_server import WebSocketServer

        server = WebSocketServer(MagicMock(), port=0, host="127.0.0.1")
        server.stop()  # nunca subiu
        server.start()
        server.stop()
        server.stop()
        assert not server.is_running

    def test_start_duas_vezes_nao_duplica(self):
        from integrations.api.ws_server import WebSocketServer

        server = WebSocketServer(MagicMock(), port=0, host="127.0.0.1")
        try:
            server.start()
            porta = server.bound_port
            server.start()  # idempotente
            assert server.bound_port == porta
        finally:
            server.stop()

    def test_porta_ocupada_falha_com_erro_claro_e_nao_derruba_o_primeiro(self):
        """Falha de bind vira RuntimeError (o launcher contém e segue)."""
        from integrations.api.ws_server import WebSocketServer

        primeiro = WebSocketServer(MagicMock(), port=0, host="127.0.0.1")
        primeiro.start()
        try:
            segundo = WebSocketServer(
                MagicMock(), port=primeiro.bound_port, host="127.0.0.1"
            )
            with pytest.raises(RuntimeError) as excinfo:
                segundo.start()
            assert "WebSocket server" in str(excinfo.value)
            assert not segundo.is_running

            # O primeiro continua atendendo.
            async def _conecta():
                from websockets.asyncio.client import connect

                async with connect(f"ws://127.0.0.1:{primeiro.bound_port}") as ws:
                    await ws.send(json.dumps({"type": "auth"}))
                    return json.loads(await ws.recv())

            assert _run(_conecta()) == {"type": "authenticated"}
        finally:
            primeiro.stop()


# ---------------------------------------------------------------------------
# Protocolo, com cliente real
# ---------------------------------------------------------------------------


class TestWebSocketProtocolo:
    """auth/message e os frames de resposta, ponta a ponta."""

    @pytest.fixture
    def servidor(self):
        from integrations.api.ws_server import WebSocketServer

        orchestra = StubOrchestrator()
        server = WebSocketServer(
            orchestra, port=0, api_keys={"chave-certa"}, host="127.0.0.1"
        )
        server.start()
        try:
            yield server, orchestra
        finally:
            server.stop()

    def _url(self, server):
        return f"ws://127.0.0.1:{server.bound_port}"

    def test_auth_valida_depois_streaming_completo(self, servidor):
        server, orchestra = servidor
        from websockets.asyncio.client import connect

        async def _fluxo():
            async with connect(self._url(server)) as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": "chave-certa"}))
                recebidos = [json.loads(await ws.recv())]
                await ws.send(
                    json.dumps(
                        {
                            "type": "message",
                            "text": "oi",
                            "profile": "guardian",
                            "session_id": "s1",
                        }
                    )
                )
                while True:
                    msg = json.loads(await ws.recv())
                    recebidos.append(msg)
                    if msg["type"] in ("done", "error"):
                        break
                return recebidos

        recebidos = _run(_fluxo())
        assert recebidos[0] == {"type": "authenticated"}
        assert recebidos[1] == {"type": "processing"}
        assert [m["content"] for m in recebidos[2:4]] == ["Olá", ", mundo"]
        assert recebidos[-1]["type"] == "done"
        assert recebidos[-1]["content"] == "Olá, mundo"
        assert recebidos[-1]["route"] == "llm"
        assert orchestra.calls == [
            {"user_id": "ws_user", "profile": "guardian", "text": "oi", "session_id": "s1"}
        ]

    def test_chave_invalida_recebe_erro_e_close_4001(self, servidor):
        server, orchestra = servidor
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed

        async def _fluxo():
            async with connect(self._url(server)) as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": "errada"}))
                erro = json.loads(await ws.recv())
                with pytest.raises(ConnectionClosed) as info:
                    await ws.recv()
                return erro, info.value

        erro, fechamento = _run(_fluxo())
        assert erro == {"type": "error", "message": "api_key_invalida"}
        assert fechamento.rcvd is not None and fechamento.rcvd.code == 4001
        assert orchestra.calls == []

    def test_sem_auth_nao_processa(self, servidor):
        server, orchestra = servidor
        from websockets.asyncio.client import connect

        async def _fluxo():
            async with connect(self._url(server)) as ws:
                await ws.send(json.dumps({"type": "message", "text": "oi"}))
                return json.loads(await ws.recv())

        assert _run(_fluxo()) == {"type": "error", "message": "nao_autenticado"}
        assert orchestra.calls == []

    def test_sem_chaves_configuradas_aceita_sem_auth(self):
        from integrations.api.ws_server import WebSocketServer
        from websockets.asyncio.client import connect

        orchestra = StubOrchestrator()
        server = WebSocketServer(orchestra, port=0, host="127.0.0.1")
        server.start()
        try:
            async def _fluxo():
                async with connect(self._url(server)) as ws:
                    await ws.send(json.dumps({"type": "message", "text": "oi"}))
                    msgs = []
                    while True:
                        msg = json.loads(await ws.recv())
                        msgs.append(msg)
                        if msg["type"] in ("done", "error"):
                            return msgs

            msgs = _run(_fluxo())
            assert msgs[0] == {"type": "processing"}
            assert msgs[-1]["type"] == "done"
        finally:
            server.stop()

    def test_perfil_auto_vira_o_padrao_igual_ao_rest(self, servidor):
        """Paridade com POST /message: `auto` resolve para guardian.

        O app manda `profile: auto` por padrão; se o streaming passasse
        `auto` adiante, a MESMA conversa cairia em baldes diferentes de
        cache/histórico conforme o transporte.
        """
        from integrations.api.server import DEFAULT_PROFILE

        server, orchestra = servidor
        from websockets.asyncio.client import connect

        async def _fluxo():
            async with connect(f"ws://127.0.0.1:{server.bound_port}") as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": "chave-certa"}))
                await ws.recv()
                await ws.send(json.dumps({"type": "message", "text": "oi", "profile": "auto"}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg["type"] in ("done", "error"):
                        return msg

        _run(_fluxo())
        assert orchestra.calls[0]["profile"] == DEFAULT_PROFILE

    def test_perfil_desconhecido_e_recusado_sem_processar(self, servidor):
        server, orchestra = servidor
        from websockets.asyncio.client import connect

        async def _fluxo():
            async with connect(f"ws://127.0.0.1:{server.bound_port}") as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": "chave-certa"}))
                await ws.recv()
                await ws.send(
                    json.dumps({"type": "message", "text": "oi", "profile": "frodo"})
                )
                return json.loads(await ws.recv())

        erro = _run(_fluxo())
        assert erro == {"type": "error", "message": "perfil_desconhecido: frodo"}
        assert orchestra.calls == []

    def test_texto_vazio_e_tipo_desconhecido(self, servidor):
        server, orchestra = servidor
        from websockets.asyncio.client import connect

        async def _fluxo():
            async with connect(self._url(server)) as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": "chave-certa"}))
                await ws.recv()
                await ws.send(json.dumps({"type": "message", "text": "   "}))
                vazio = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "telepatia"}))
                desconhecido = json.loads(await ws.recv())
                return vazio, desconhecido

        vazio, desconhecido = _run(_fluxo())
        assert vazio == {"type": "error", "message": "text_obrigatorio"}
        assert desconhecido == {"type": "error", "message": "tipo_desconhecido: telepatia"}
        assert orchestra.calls == []

    def test_queda_no_meio_do_stream_nao_vira_erro_e_servidor_sobrevive(self, ws_log):
        """Cliente aborta no meio do stream: rotina, não ERROR (achado do sandbox).

        Sem isso, o `ws.send` de um token levantava ConnectionClosedError e o
        servidor logava `WebSocket processing error` — o mesmo ruído que a
        correção do handle_error de 2026-09-15 tirou do journal.

        A asserção POSITIVA (o registro de debug tem que aparecer) é o que dá
        valor ao teste: só checar a ausência do ERROR passaria por acidente se
        o aborto nunca chegasse ao servidor — foi o que o capfd mascarou.
        """
        from integrations.api.ws_server import WebSocketServer
        from websockets.asyncio.client import connect

        class StreamLongo:
            """Solta tokens devagar, para dar tempo do cliente abortar."""

            def __init__(self):
                self.chunks = 200

            async def process_stream(self, user_id, profile, text, *, session_id=""):
                for _ in range(self.chunks):
                    yield {"type": "token", "content": "x"}
                    await asyncio.sleep(0.01)

        server = WebSocketServer(StreamLongo(), port=0, host="127.0.0.1")
        server.start()
        try:
            async def _aborta_no_meio():
                ws = await connect(f"ws://127.0.0.1:{server.bound_port}")
                await ws.send(json.dumps({"type": "message", "text": "conte tudo"}))
                await ws.recv()  # processing
                await ws.recv()  # primeiro token
                ws.transport.abort()  # some sem close frame

            _run(_aborta_no_meio())
            assert _espera_registro(ws_log, "Cliente desconectou durante o stream")

            assert server.is_running
            mensagens = [r.message for r in ws_log.records]
            assert "WebSocket processing error" not in mensagens
            assert not [r for r in ws_log.records if r.level >= LogLevel.WARN]

            async def _ainda_atende():
                async with connect(f"ws://127.0.0.1:{server.bound_port}") as ws:
                    await ws.send(json.dumps({"type": "auth"}))
                    return json.loads(await ws.recv())

            assert _run(_ainda_atende()) == {"type": "authenticated"}
        finally:
            server.stop()

    def test_sonda_tcp_cru_nao_despeja_traceback(self, ws_log):
        """Abrir e fechar um TCP sem handshake não pode sujar o journal.

        O websockets loga `opening handshake failed` com exc_info — uma sonda
        de porta (monitor, health check, port scanner) viraria traceback no
        stderr. Também foi o sandbox que expôs isso.

        Dois pinos: (a) a conexão da biblioteca usa o NOSSO logger (senão nada
        segura o traceback) e (b) o handshake que falha chega como UMA linha
        de debug, sem WARN/ERROR. O coletor no logger da biblioteca pega
        qualquer escape direto dela, que o capfd não pegava.
        """
        import logging as _logging
        import socket as _socket

        from integrations.api.ws_server import WebSocketServer, _LibraryLogger

        coletor = _ColetorBiblioteca()
        logger_bib = _logging.getLogger("websockets.server")
        nivel_bib = logger_bib.level
        logger_bib.addHandler(coletor)
        logger_bib.setLevel(_logging.DEBUG)

        server = WebSocketServer(MagicMock(), port=0, host="127.0.0.1")
        server.start()
        try:
            assert isinstance(server._server.logger, _LibraryLogger)
            for _ in range(3):
                with _socket.socket() as sock:
                    sock.settimeout(2.0)
                    sock.connect(("127.0.0.1", server.bound_port))
                # Fecha sem enviar nada: o servidor vê EOF no handshake.
            assert _espera_registro(ws_log, "opening handshake failed")

            # Nada saiu direto pelo logging da biblioteca (nem traceback).
            assert coletor.records == []
            assert not [r for r in ws_log.records if r.level >= LogLevel.WARN]
            assert server.is_running
        finally:
            server.stop()
            logger_bib.removeHandler(coletor)
            logger_bib.setLevel(nivel_bib)

    def test_json_invalido_nao_derruba_a_conexao(self, servidor):
        server, _ = servidor
        from websockets.asyncio.client import connect

        async def _fluxo():
            async with connect(self._url(server)) as ws:
                await ws.send("{isso não é json")
                erro = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "auth", "api_key": "chave-certa"}))
                return erro, json.loads(await ws.recv())

        erro, depois = _run(_fluxo())
        assert erro == {"type": "error", "message": "json_invalido"}
        assert depois == {"type": "authenticated"}

    def test_falha_no_orchestrator_vira_error_e_conexao_sobrevive(self, servidor):
        server, _ = servidor
        from websockets.asyncio.client import connect

        server.orchestrator = StubOrchestrator(error=RuntimeError("boom"))

        async def _fluxo():
            async with connect(self._url(server)) as ws:
                await ws.send(json.dumps({"type": "auth", "api_key": "chave-certa"}))
                await ws.recv()
                await ws.send(json.dumps({"type": "message", "text": "oi"}))
                assert json.loads(await ws.recv()) == {"type": "processing"}
                erro = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "message", "text": "oi de novo"}))
                return erro, json.loads(await ws.recv())

        erro, segundo = _run(_fluxo())
        assert erro == {
            "type": "error",
            "message": "erro_processamento: RuntimeError",
        }
        # A conexão sobreviveu: o próximo envio é atendido normalmente.
        assert segundo == {"type": "processing"}


# ---------------------------------------------------------------------------
# Streaming do provider LLM (core/llm.py)
# ---------------------------------------------------------------------------


class TestLLMProviderStreaming:
    """SSE do provider OpenAI-compat: parse dos chunks e dos erros."""

    def test_generate_stream_yields_chunks(self):
        from core.llm import OpenAICompatProvider

        mock_response = MagicMock()
        mock_response.read.side_effect = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":" "}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n',
            b"data: [DONE]\n\n",
            b"",  # EOF
        ]
        mock_response.close = MagicMock()

        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("asyncio.to_thread", side_effect=mock_to_thread):
                provider = OpenAICompatProvider()

                async def _coleta():
                    return [c async for c in provider.generate_stream("test prompt")]

                assert _run(_coleta()) == ["Hello", " ", "world"]

    def test_generate_stream_ignora_linhas_invalidas(self):
        from core.llm import OpenAICompatProvider

        mock_response = MagicMock()
        mock_response.read.side_effect = [
            b"data: {nao e json}\n",
            b'data: {"choices":[{"delta":{}}]}\n',
            b": keep-alive\n",
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
            b"data: [DONE]\n",
            b"",
        ]
        mock_response.close = MagicMock()

        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("asyncio.to_thread", side_effect=mock_to_thread):
                provider = OpenAICompatProvider()

                async def _coleta():
                    return [c async for c in provider.generate_stream("p")]

                assert _run(_coleta()) == ["ok"]

    def test_generate_stream_devolve_reasoning_quando_nao_ha_content(self):
        """Mesma tolerância do caminho não-streaming (modelos de raciocínio)."""
        from core.llm import OpenAICompatProvider

        mock_response = MagicMock()
        mock_response.read.side_effect = [
            b'data: {"choices":[{"delta":{"reasoning_content":"pensando "}}]}\n',
            b'data: {"choices":[{"delta":{"reasoning_content":"sozinho"}}]}\n',
            b"data: [DONE]\n",
            b"",
        ]
        mock_response.close = MagicMock()

        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("asyncio.to_thread", side_effect=mock_to_thread):
                provider = OpenAICompatProvider()

                async def _coleta():
                    return [c async for c in provider.generate_stream("p")]

                assert _run(_coleta()) == ["pensando sozinho"]

    def test_generate_stream_vazio_sem_reasoning_nao_produz_nada(self):
        from core.llm import OpenAICompatProvider

        mock_response = MagicMock()
        mock_response.read.side_effect = [b"data: [DONE]\n", b""]
        mock_response.close = MagicMock()

        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("asyncio.to_thread", side_effect=mock_to_thread):
                provider = OpenAICompatProvider()

                async def _coleta():
                    return [c async for c in provider.generate_stream("p")]

                assert _run(_coleta()) == []

    def test_generate_stream_erro_de_rede_vira_llm_error(self):
        import urllib.error

        from core.llm import LLMError, OpenAICompatProvider

        def _raises(*args, **kwargs):
            raise urllib.error.URLError("sem rota")

        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("urllib.request.urlopen", side_effect=_raises):
            with patch("asyncio.to_thread", side_effect=mock_to_thread):
                provider = OpenAICompatProvider()

                async def _coleta():
                    return [c async for c in provider.generate_stream("p")]

                with pytest.raises(LLMError):
                    _run(_coleta())


# ---------------------------------------------------------------------------
# Streaming no Orchestrator
# ---------------------------------------------------------------------------


class TestOrchestratorStreaming:
    """process_stream: mesmas etapas terminais + caminho LLM com streaming."""

    def test_process_stream_rate_limit(self):
        from core.orchestrator import Orchestrator, OrchestratorConfig

        config = OrchestratorConfig(rate_limit_max=1, rate_window_seconds=60)
        orch = Orchestrator(config=config)

        async def _coleta():
            primeiro = [c async for c in orch.process_stream("u", "guardian", "a")]
            segundo = [c async for c in orch.process_stream("u", "guardian", "b")]
            return primeiro, segundo

        _, segundo = _run(_coleta())
        assert any(
            c.get("type") == "error" and c.get("message") == "rate_limited" for c in segundo
        )

    def test_process_stream_datetime(self):
        from core.orchestrator import Orchestrator, OrchestratorConfig

        orch = Orchestrator(config=OrchestratorConfig(inject_datetime=True))

        async def _coleta():
            return [c async for c in orch.process_stream("u", "guardian", "que horas são?")]

        chunks = _run(_coleta())
        assert any(c.get("type") == "token" for c in chunks)
        assert chunks[-1].get("route") == "datetime"

    def test_process_stream_llm_token_a_token(self):
        from core.orchestrator import Orchestrator, OrchestratorConfig

        provider = StreamingProvider()
        orch = Orchestrator(
            providers=[provider],
            config=OrchestratorConfig(
                inject_datetime=False, enable_action_intents=False
            ),
        )

        async def _coleta():
            return [c async for c in orch.process_stream("u", "guardian", "conte algo")]

        chunks = _run(_coleta())
        assert [c["content"] for c in chunks if c["type"] == "token"] == [
            "Stream",
            "ing",
            " ok",
        ]
        assert chunks[-1]["type"] == "done"
        assert chunks[-1]["content"] == "Streaming ok"
        assert chunks[-1]["route"] == "llm"
        assert chunks[-1]["llm_used"] == "stream-fake"
        assert provider.stream_calls == 1
        assert provider.generate_calls == 0
        assert orch.metrics.llm == 1
        assert orch.metrics.processed == 1

    def test_process_stream_cai_para_generate_se_o_stream_falhar(self):
        from core.orchestrator import Orchestrator, OrchestratorConfig

        class ProviderQuebrado:
            name = "quebrado"

            async def generate_stream(self, prompt, **options):
                raise RuntimeError("stream indisponível")
                yield  # pragma: no cover — generator

            async def generate(self, prompt, **options):
                return "resposta inteira"

        orch = Orchestrator(
            providers=[ProviderQuebrado()],
            config=OrchestratorConfig(
                inject_datetime=False, enable_action_intents=False
            ),
        )

        async def _coleta():
            return [c async for c in orch.process_stream("u", "guardian", "oi")]

        chunks = _run(_coleta())
        assert [c["content"] for c in chunks if c["type"] == "token"] == [
            "resposta inteira"
        ]
        assert chunks[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Fiação no launcher
# ---------------------------------------------------------------------------


class TestLauncherWebSocket:
    """build_ws_server: env, porta e ausência de chaves."""

    @pytest.fixture
    def ws_env(self, monkeypatch):
        """Isola a config do launcher sem tocar no .env nem no cache global.

        `launcher.env()` guarda um snapshot do ambiente na PRIMEIRA chamada
        (_ENV_CACHE), então monkeypatch.setenv não basta — e sujar o cache
        afetaria os outros testes do processo. monkeypatch.setattr devolve o
        valor original ao fim do teste.
        """
        from runtime import launcher

        def _set(**values):
            monkeypatch.setattr(launcher, "_ENV_CACHE", dict(values))

        return _set

    def test_desabilitado_por_env(self, ws_env):
        from runtime import launcher

        ws_env(OD_WS_ENABLED="0")
        assert launcher.build_ws_server(MagicMock()) is None

    def test_configurado_com_porta_e_chave(self, ws_env):
        from runtime import launcher

        ws_env(OD_WS_ENABLED="1", OD_WS_PORT="8123", OD_API_KEY="chave")
        server = launcher.build_ws_server(MagicMock())
        assert server is not None
        assert server.port == 8123
        assert server.api_keys == {"chave"}
        assert not server.is_running  # só start() abre o socket

    def test_falha_do_ws_nao_derruba_o_loop_da_api(self, monkeypatch):
        """Contenção: REST e núcleo seguem de pé se o streaming não subir.

        É a lição de 2026-09-15 (isolamento dos loops) aplicada a um extra
        novo: um recurso opcional não pode levar o processo inteiro junto.
        """
        from runtime import launcher

        fake_api = MagicMock()
        fake_api.bound_port = 18123
        monkeypatch.setattr(launcher, "build_api_server", lambda *a, **k: fake_api)

        def _quebra(*args, **kwargs):
            raise RuntimeError("websockets não instalado")

        monkeypatch.setattr(launcher, "build_ws_server", _quebra)

        async def _roda():
            task = asyncio.create_task(launcher._run_api_forever(MagicMock()))
            await asyncio.sleep(0.05)
            sobreviveu = not task.done()
            task.cancel()
            await task  # o próprio launcher trata o CancelledError e sai limpo
            return sobreviveu

        assert _run(_roda()) is True
        fake_api.serve_background.assert_called_once()

    def test_ws_sobe_junto_com_a_api(self, monkeypatch):
        """O caminho feliz: com o WS saudável, a API sobe e o WS é parado no fim."""
        from runtime import launcher

        fake_api = MagicMock()
        fake_api.bound_port = 18124
        fake_ws = MagicMock()
        monkeypatch.setattr(launcher, "build_api_server", lambda *a, **k: fake_api)
        monkeypatch.setattr(launcher, "build_ws_server", lambda *a, **k: fake_ws)

        async def _roda():
            task = asyncio.create_task(launcher._run_api_forever(MagicMock()))
            await asyncio.sleep(0.05)
            task.cancel()
            await task  # o próprio launcher trata o CancelledError e sai limpo

        _run(_roda())
        fake_ws.start.assert_called_once()
        fake_api.stop.assert_called_once()
        fake_ws.stop.assert_called_once()

    def test_porta_default_quando_env_ausente(self, ws_env):
        from integrations.api.ws_server import DEFAULT_WS_PORT
        from runtime import launcher

        ws_env()
        server = launcher.build_ws_server(MagicMock())
        assert server is not None
        assert server.port == DEFAULT_WS_PORT
        assert server.api_keys == set()  # sem OD_API_KEY, sem exigência de auth
