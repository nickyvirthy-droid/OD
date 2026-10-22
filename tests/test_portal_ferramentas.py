"""Portário /f/<ferramenta> (fase 1 — ordem do dono, 21/10).

O Site vira portaria das 5 ferramentas que suportam subcaminho. Trava
aqui o contrato do portão: sem credencial não passa um byte de
ferramenta; registro aberto não vira passagem livre; o prefixo /f/<nome>
sai do caminho antes de chegar no backend; redirect do backend ganha o
prefixo de volta; WebSocket (notificações do Cofre) passa cru.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import pytest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.database import Database
from integrations.api import APIConfig, APIServer
from integrations.api.auth import UserStore
from integrations.api.server import APIHandler, ROTA_FERRAMENTAS


# ===========================================================================
# Infra de teste (espelha o test_api.py, sem seguir redirect — o portário
# DEVE devolver o 3xx ao navegador em vez de consumi-lo aqui)
# ===========================================================================

class _SemRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


_OPENER = urllib.request.build_opener(_SemRedirect)


def chamar(porta: int, metodo: str, caminho: str, *,
           corpo: Optional[dict] = None,
           headers: Optional[dict[str, str]] = None):
    """(status, bytes, headers) contra 127.0.0.1:porta, sem seguir 3xx."""
    url = f"http://127.0.0.1:{porta}{caminho}"
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    for chave, valor in (headers or {}).items():
        req.add_header(chave, valor)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


class _FerramentaStub(BaseHTTPRequestHandler):
    """Backend fake: ecoa o que o proxy repassa (caminho, método, corpo)."""

    ultimo: dict[str, Any] = {}

    def log_message(self, *args) -> None:  # noqa: ANN002
        pass

    def do_GET(self) -> None:
        self._responde()

    def do_POST(self) -> None:
        self._responde()

    def _responde(self) -> None:
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b""
        _FerramentaStub.ultimo = {
            "metodo": self.command, "path": self.path,
            "corpo": corpo, "host": self.headers.get("Host"),
            "upgrade": self.headers.get("Upgrade"),
        }
        if self.path == "/redireciona":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/cookie":
            resposta = b"cookie-tool"
            self.send_response(200)
            self.send_header("Set-Cookie", "sessao_tool=abc123; Path=/")
            self.send_header("Content-Length", str(len(resposta)))
            self.end_headers()
            self.wfile.write(resposta)
            return
        resposta = json.dumps(
            {"metodo": self.command, "path": self.path,
             "corpo": corpo.decode("utf-8", "replace")},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)


def _ws_eco(porta: list[int], registro: dict, pronto: threading.Event) -> None:
    """Servidor cru: handshake 101 fixo + eco de bytes (prova do relé)."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    porta.append(srv.getsockname()[1])
    pronto.set()
    conn, _ = srv.accept()
    try:
        pedidos = b""
        while b"\r\n\r\n" not in pedidos:
            pedidos += conn.recv(4096)
        registro["pedido"] = pedidos
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Connection: Upgrade\r\nUpgrade: websocket\r\n"
            b"Sec-WebSocket-Accept: prova\r\n\r\n"
        )
        while True:
            bloco = conn.recv(65536)
            if not bloco:
                break
            conn.sendall(bloco)
    finally:
        conn.close()
        srv.close()


@pytest.fixture
def ferramenta_stub():
    """Backend fake numa porta efêmera — o mapa do portário aponta p/ ele."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FerramentaStub)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def serve():
    """Sobe APIServers de teste e derruba no fim (formato do test_api)."""
    servidores: list[APIServer] = []

    def _start(config: APIConfig) -> APIServer:
        srv = APIServer(None, config=config)
        srv.serve_background()
        servidores.append(srv)
        return srv

    yield _start
    for srv in servidores:
        try:
            srv.stop()
        except Exception:  # pragma: sem cobertura — teardown defensivo
            pass


def _cfg(store=None, api_key: str = "") -> APIConfig:
    return APIConfig(
        port=0, rate_limit_max=0, user_store=store, api_key=api_key,
        owner_username="dono",
    )


def _loja(tmp_path) -> UserStore:
    store = UserStore(Database(tmp_path / "portal.db"))
    store.register("comum", "comum@example.com", "senha-comum-123")
    store.register("dono", "dono@example.com", "senha-dono-123")
    return store


def _token(srv, usuario: str) -> str:
    status, corpo, _ = chamar(
        srv.bound_port, "POST", "/auth/login",
        corpo={"username": usuario, "password": f"senha-{usuario}-123"},
    )
    assert status == 200, corpo
    return json.loads(corpo)["token"]


def _cabeca(token: str) -> dict[str, str]:
    return {"Cookie": f"od_sessao={token}"}


# ===========================================================================
# O portão
# ===========================================================================

class TestPortaoDoPortario:
    """Quem não é o dono não vê ferramenta nenhuma."""

    def test_sem_credencial_vai_para_o_login(self, serve, tmp_path) -> None:
        """Navegador sem sessão vai para o formulário DE VERDADE (/chat).

        Achado em produção (22/10): o alvo antigo /auth/login é rota de
        API (só POST) e o navegador parava num 405 sem como digitar. O
        ?next devolve o dono à ferramenta pedida após o login.
        """
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, cab = chamar(srv.bound_port, "GET", "/f/caderno/")
        assert status == 302
        assert cab["Location"] == "/chat?next=/f/caderno/"
        assert corpo == b""

    def test_chat_tem_formulario_e_guarda_do_next(self, serve, tmp_path) -> None:
        """A página de login tem o formulário e o retorno só aceita /f/.

        Trava o contrato que o dono usou em produção: sem isto ele parava
        na tela sem campo para digitar, e depois de logado não voltava
        para a ferramenta.
        """
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(srv.bound_port, "GET", "/chat")
        assert status == 200
        pagina = corpo.decode("utf-8", "replace")
        assert 'id="login-pass"' in pagina              # o campo de senha
        assert 'startsWith("/f/")' in pagina            # volta só p/ portário

    def test_admin_tem_menu_das_ferramentas(self, serve, tmp_path) -> None:
        """Ordem do dono (22/10): link das 5 no menu do administrador."""
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(srv.bound_port, "GET", "/admin")
        assert status == 200
        pagina = corpo.decode("utf-8", "replace")
        for nome in ("caderno", "cyberchef", "itools", "caixa", "cofre"):
            assert f'href="/f/{nome}/"' in pagina, f"menu sem {nome}"

    def test_conta_comum_logada_leva_403(self, serve, tmp_path) -> None:
        """Registro é aberto, mas conta comum não vira passagem livre."""
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(
            srv.bound_port, "GET", "/f/caderno/",
            headers=_cabeca(_token(srv, "comum")),
        )
        assert status == 403
        assert json.loads(corpo)["error"] == "acesso_negado"

    def test_chave_do_servidor_tambem_passa(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """Chave de operador (sistema) administra sem cookie — mesma régua."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path), api_key="chave-teste"))
        status, _, _ = chamar(srv.bound_port, "GET", "/f/caderno/",
                              headers={"X-API-Key": "chave-teste"})
        assert status == 200

    def test_dono_com_cookie_passa_e_prefixo_sai_do_caminho(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """Cookie do dono abre a ferramenta; o backend recebe sem o /f/<nome>."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(
            srv.bound_port, "GET", "/f/caderno/coisa?x=1",
            headers=_cabeca(_token(srv, "dono")),
        )
        assert status == 200
        eco = json.loads(corpo)
        assert eco["path"] == "/coisa?x=1"      # strip do prefixo + query
        assert eco["metodo"] == "GET"
        assert _FerramentaStub.ultimo["host"] == f"127.0.0.1:{ferramenta_stub}"

    def test_login_entrega_cookie_e_logout_derruba(
            self, serve, tmp_path) -> None:
        """/auth/login emite od_sessao (portário); logout derruba o cookie."""
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, cab = chamar(
            srv.bound_port, "POST", "/auth/login",
            corpo={"username": "dono", "password": "senha-dono-123"},
        )
        assert status == 200
        cookie = cab.get("Set-Cookie", "")
        assert cookie.startswith("od_sessao=")
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
        token = json.loads(corpo)["token"]
        status, _, cab2 = chamar(
            srv.bound_port, "POST", "/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status == 200
        assert "Max-Age=0" in cab2.get("Set-Cookie", "")


# ===========================================================================
# O proxy
# ===========================================================================

class TestProxyDasFerramentas:
    """Prefixo sai na ida, volta na resposta — e nada se perde no caminho."""

    def test_sem_barra_final_redireciona_para_barra(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """/f/caderno (sem barra) redireciona: sem isso os relativos quebram."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path)))
        status, _, cab = chamar(srv.bound_port, "GET", "/f/caderno",
                                headers=_cabeca(_token(srv, "dono")))
        assert status == 302
        assert cab["Location"] == "/f/caderno/"

    def test_post_corpo_e_query_repassados(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """Caixa e Cofre fazem POST/PUT: corpo e query chegam intactos."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(
            srv.bound_port, "POST", "/f/caderno/echo?pag=2",
            corpo={"arquivo": "nota.txt"},
            headers=_cabeca(_token(srv, "dono")),
        )
        assert status == 200
        eco = json.loads(corpo)
        assert eco["metodo"] == "POST"
        assert eco["path"] == "/echo?pag=2"
        assert json.loads(eco["corpo"]) == {"arquivo": "nota.txt"}

    def test_redirect_do_backend_ganha_prefixo(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """Backend manda /login (acha que vive na raiz) → /f/caderno/login."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path)))
        status, _, cab = chamar(
            srv.bound_port, "GET", "/f/caderno/redireciona",
            headers=_cabeca(_token(srv, "dono")),
        )
        assert status == 302
        assert cab["Location"] == "/f/caderno/login"

    def test_cookie_do_backend_passa_ao_navegador(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """Login da ferramenta emite SEU cookie — não pode se perder no meio."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, cab = chamar(
            srv.bound_port, "GET", "/f/caderno/cookie",
            headers=_cabeca(_token(srv, "dono")),
        )
        assert status == 200 and corpo == b"cookie-tool"
        assert "sessao_tool=abc123" in cab.get("Set-Cookie", "")

    def test_cofre_manten_o_prefixo_no_backend(
            self, serve, tmp_path, ferramenta_stub, monkeypatch) -> None:
        """Cofre vive DENTRO do prefixo (DOMAIN com path): sem strip."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "cofre",
                            ferramenta_stub)
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(
            srv.bound_port, "GET", "/f/cofre/vault/",
            headers=_cabeca(_token(srv, "dono")),
        )
        assert status == 200
        assert json.loads(corpo)["path"] == "/f/cofre/vault/"

    def test_ferramenta_fora_do_ar_vira_502(self, serve, tmp_path,
                                            monkeypatch) -> None:
        """Backend morto não derruba o Site: 502 com o nome da ferramenta."""
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno", 1)
        srv = serve(_cfg(_loja(tmp_path)))
        status, corpo, _ = chamar(
            srv.bound_port, "GET", "/f/caderno/",
            headers=_cabeca(_token(srv, "dono")),
        )
        assert status == 502
        assert json.loads(corpo) == {"ok": False,
                                     "error": "ferramenta_indisponivel",
                                     "ferramenta": "caderno"}

    def test_websocket_do_cofre_passa_cru(self, serve, tmp_path,
                                          monkeypatch) -> None:
        """101 vira relé cru: notificações do Cofre chegam ao navegador."""
        registro: dict[str, bytes] = {}
        portas: list[int] = []
        pronto = threading.Event()
        threading.Thread(target=_ws_eco, args=(portas, registro, pronto),
                         daemon=True).start()
        assert pronto.wait(5), "stub de websocket não subiu"
        monkeypatch.setitem(APIHandler.FERRAMENTAS_PORTA, "caderno", portas[0])
        srv = serve(_cfg(_loja(tmp_path)))
        token = _token(srv, "dono")
        bruto = socket.create_connection(("127.0.0.1", srv.bound_port), 5)
        bruto.settimeout(5)
        try:
            bruto.sendall(
                b"GET /f/caderno/ws HTTP/1.1\r\nHost: x\r\n"
                b"Cookie: od_sessao=" + token.encode("ascii") + b"\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Key: prova\r\n"
                b"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            cabecalhos = b""
            while b"\r\n\r\n" not in cabecalhos:
                cabecalhos += bruto.recv(4096)
            assert b"101" in cabecalhos
            assert b"Upgrade: websocket" in cabecalhos
            bruto.sendall(b"ping-cru")
            assert bruto.recv(4096) == b"ping-cru"
        finally:
            bruto.close()
        # O upgrade do navegador chegou ao backend (o proxy não comeu).
        assert b"Upgrade: websocket" in registro["pedido"]


# ===========================================================================
# O mapa
# ===========================================================================

class TestMapaDoPortario:
    """Só as 5 da fase 1 — as outras 4 ficam casa+celular por enquanto."""

    def test_somente_as_cinco_da_fase_1(self) -> None:
        assert set(APIHandler.FERRAMENTAS_PORTA) == {
            "caderno", "cyberchef", "itools", "caixa", "cofre"}
        assert APIHandler.FERRAMENTAS_MANTEN_PREFIXO == {"cofre"}
        padrao = re.compile(ROTA_FERRAMENTAS)
        for nome in ("caderno", "cyberchef", "itools", "caixa", "cofre"):
            assert padrao.fullmatch(f"/f/{nome}/")
            assert padrao.fullmatch(f"/f/{nome}")
        for outra in ("livros", "kiwix", "stirling", "homebox"):
            assert padrao.fullmatch(f"/f/{outra}/") is None

    def test_ferramenta_de_casa_responde_404(self, serve, tmp_path) -> None:
        """/f/livros não existe no portário — casa é casa."""
        srv = serve(_cfg(_loja(tmp_path)))
        status, _, _ = chamar(srv.bound_port, "GET", "/f/livros/")
        assert status == 404
