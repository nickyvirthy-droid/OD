"""Guardas do proxy do painel AzuraCast (runtime/azura_proxy.py).

O contrato travado aqui é o que derrubou a publicação direta da porta
tailnet (28/10, medido ao vivo):

    Host: <dominio>:8446            -> AzuraCast responde 200
    X-Forwarded-Host: <dom>:8446    -> guzzle: "Invalid host" (500)
    X-Forwarded-Host: <dom>         -> 200

Então: o proxy TIRA a porta do X-Forwarded-Host e manda Host do backend,
repassa corpo/cabeçalhos/resposta sem bufferizar (streaming byte a byte),
conserta redirect absoluto do backend e responde 502 honesto quando o
AzuraCast está fora do ar.
"""

from __future__ import annotations

import http.client
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runtime.azura_proxy import construir, sem_porta

VISTAS: list[dict] = []
_LOCK = threading.Lock()


class _Backend(BaseHTTPRequestHandler):
    """Backend stub com as formas de resposta que o AzuraCast usa."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # silencia o servidor de teste
        return

    def _reg(self, corpo: bytes = b"") -> None:
        with _LOCK:
            VISTAS.append({
                "linha": self.requestline,
                "host": self.headers.get("Host"),
                "xfh": self.headers.get("X-Forwarded-Host"),
                "xff": self.headers.get("X-Forwarded-For"),
                "proto": self.headers.get("X-Forwarded-Proto"),
                "cookie": self.headers.get("Cookie"),
                "conexao": self.headers.get("Connection"),
                "corpo": corpo,
            })

    def _resp(self, status: int, corpo: bytes, extra: list[tuple[str, str]] | None = None) -> None:
        self.send_response(status)
        for chave, valor in extra or []:
            self.send_header(chave, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def do_GET(self) -> None:  # noqa: N802
        self._reg()
        caminho = self.path.split("?", 1)[0]
        if caminho == "/redireciona":
            porta = self.server.server_address[1]
            self._resp(302, b"", [("Location", f"http://127.0.0.1:{porta}/login")])
        elif caminho == "/redireciona_fora":
            self._resp(302, b"", [("Location", "https://azuracast.com/fora")])
        elif caminho == "/stream":
            # resposta SEM Content-Length (close-delimited): o proxy tem de
            # repassar os bytes na hora, sem bufferizar.
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Connection", "close")
            self.end_headers()
            for i in range(3):
                self.wfile.write(f"pedaco{i};".encode("ascii"))
                self.wfile.flush()
                time.sleep(0.05)
            self.close_connection = True
        else:
            self._resp(200, b"pagina-do-azura")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b""
        self._reg(corpo)
        self._resp(200, b"recebi:" + corpo)


def _backend_vivo() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _proxy(backend_porta: int):
    srv = construir(porta=0, backend=("127.0.0.1", backend_porta))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(porta: int, caminho: str, cabecas: dict[str, str] | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    conn.request("GET", caminho, headers=cabecas or {})
    resp = conn.getresponse()
    corpo = resp.read()
    return resp, corpo


def _proxy_com_tailscale() -> tuple[int, ThreadingHTTPServer, ThreadingHTTPServer]:
    """Backend + proxy prontos, com os cabeçalhos que o tailscale manda."""
    backend = _backend_vivo()
    proxy = _proxy(backend.server_address[1])
    return proxy.server_address[1], proxy, backend


class TestSemPorta:
    def test_corta_porta_ipv4_e_preserva_v6(self) -> None:
        assert sem_porta("dominio.ts.net:8446") == "dominio.ts.net"
        assert sem_porta("100.77.67.53:8446") == "100.77.67.53"
        assert sem_porta("dominio.ts.net") == "dominio.ts.net"
        assert sem_porta("[fd7a::1]:8446") == "[fd7a::1]"
        assert sem_porta("[fd7a::1]") == "[fd7a::1]"
        assert sem_porta("a:b:c") == "a:b:c"      # IPv6 cru não é cortado
        assert sem_porta("") == ""


class TestCabeecalhoConsertado:
    """O cabeçalho com porta é exatamente o que matava o AzuraCast."""

    def test_xfh_sem_porta_e_host_do_backend(self) -> None:
        VISTAS.clear()
        porta, proxy, backend = _proxy_com_tailscale()
        try:
            _, corpo = _get(porta, "/", {
                "Host": "nicky-server.tail1b1f51.ts.net:8446",
                "X-Forwarded-Host": "nicky-server.tail1b1f51.ts.net:8446",
                "X-Forwarded-Proto": "https",
                "Cookie": "azuracast_session=abc123",
                "X-Forwarded-For": "100.77.67.53",
            })
            assert corpo == b"pagina-do-azura"
            visto = VISTAS[-1]
            assert visto["xfh"] == "nicky-server.tail1b1f51.ts.net"  # sem porta
            assert visto["host"] == f"127.0.0.1:{backend.server_address[1]}"
            assert visto["cookie"] == "azuracast_session=abc123"    # passa cru
            assert visto["proto"] == "https"
            assert visto["xff"] == "100.77.67.53"
            assert visto["conexao"] == "close"
        finally:
            proxy.shutdown()
            backend.shutdown()

    def test_xfh_ausente_ganha_o_host_original_sem_porta(self) -> None:
        VISTAS.clear()
        porta, proxy, backend = _proxy_com_tailscale()
        try:
            _get(porta, "/", {"Host": "nicky-server.tail1b1f51.ts.net:8446"})
            visto = VISTAS[-1]
            assert visto["xfh"] == "nicky-server.tail1b1f51.ts.net"
        finally:
            proxy.shutdown()
            backend.shutdown()


class TestRedirect:
    def test_redirect_do_backend_perde_o_backend(self) -> None:
        """backend manda http://127.0.0.1:<porta>/login -> /login.

        Sem isso o navegador sai pra 127.0.0.1 e o painel morre no
        aparelho do dono."""
        porta, proxy, backend = _proxy_com_tailscale()
        try:
            resp, _ = _get(porta, "/redireciona")
            assert resp.status == 302
            assert resp.getheader("Location") == "/login"
        finally:
            proxy.shutdown()
            backend.shutdown()

    def test_redirect_para_fora_passa_inteiro(self) -> None:
        porta, proxy, backend = _proxy_com_tailscale()
        try:
            resp, _ = _get(porta, "/redireciona_fora")
            assert resp.getheader("Location") == "https://azuracast.com/fora"
        finally:
            proxy.shutdown()
            backend.shutdown()


class TestCorpoEStream:
    def test_post_corpo_chega_integro(self) -> None:
        VISTAS.clear()
        porta, proxy, backend = _proxy_com_tailscale()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
            payload = b'{"nome":"vinheta"}' * 100
            conn.request("POST", "/api/station/1", body=payload,
                         headers={"Content-Length": str(len(payload))})
            resp = conn.getresponse()
            assert resp.status == 200
            assert resp.read() == b"recebi:" + payload
            assert VISTAS[-1]["corpo"] == payload
        finally:
            proxy.shutdown()
            backend.shutdown()

    def test_resposta_sem_moldura_chega_peca_a_peca(self) -> None:
        """O preview de áudio não pode ficar no buffer do proxy."""
        porta, proxy, backend = _proxy_com_tailscale()
        try:
            resp, corpo = _get(porta, "/stream")
            assert resp.status == 200
            assert corpo == b"pedaco0;pedaco1;pedaco2;"
            assert resp.getheader("Content-Length") is None
        finally:
            proxy.shutdown()
            backend.shutdown()


class TestForaDoAr:
    def test_backend_morto_vira_502(self) -> None:
        proxy = _proxy(1)   # porta 1 nunca escuta
        try:
            resp, corpo = _get(proxy.server_address[1], "/")
            assert resp.status == 502
            assert b"azura_indisponivel" in corpo
        finally:
            proxy.shutdown()
