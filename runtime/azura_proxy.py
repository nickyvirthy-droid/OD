"""Proxy HTTP do painel AzuraCast atrás do portão do Od.

Por que existe (medido em 28/10, não deduzido):

    Host: nicky-server.tail1b1f51.ts.net:8446      -> 200 no AzuraCast
    X-Forwarded-Host: nicky-server.tail1b1f51.ts.net:8446 -> 500
    X-Forwarded-Host: nicky-server.tail1b1f51.ts.net      -> 200

O ``tailscale serve`` entrega ao backend os DOIS cabeçalhos com a porta e o
guzzle do AzuraCast recusa host com porta ("Invalid host", Uri.php L478) —
foi isso que derrubou a publicação direta da porta tailnet. Este proxy tira
a porta antes de encaminhar: ``X-Forwarded-Host`` fica só com o domínio e
``Host`` vira o do backend (``127.0.0.1:8091``, o valor que o container já
aceita — medido 200). Todo o resto passa cru: método, caminho, corpo,
cabeçalhos do navegador (cookies do AzuraCast incluídos) e a resposta com
streaming byte a byte (não bufferiza — o preview de áudio não trava).

Cadeia de acesso (o painel NUNCA é público):

    navegador -> https://<tailnet>:8446   (porta tailnet only:
                credenciais Tailscale-User-* entram aqui)
      -> 127.0.0.1:8466  (este proxy, OD_AZURA_PROXY_PORTA)
        -> 127.0.0.1:8091 (nginx do container azuracast)
          -> login do próprio AzuraCast por cima de tudo.

Uso:

    .venv/bin/python -m runtime.azura_proxy

Env: ``OD_AZURA_PROXY_PORTA`` (padrão 8466), ``OD_AZURA_BACKEND``
(padrão ``127.0.0.1:8091``).
"""

from __future__ import annotations

import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.logger import get_logger

log = get_logger("omega.runtime.azura_proxy")

PORTA = int(os.environ.get("OD_AZURA_PROXY_PORTA", "8466"))
BACKEND = os.environ.get("OD_AZURA_BACKEND", "127.0.0.1:8091")

#: Hop-by-hop (RFC 7230) não podem ser repassados de um hop ao outro —
#: exceto Transfer-Encoding, que repassamos cru junto com os bytes.
_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade",
})

#: Corpo máximo lido de uma vez no pedido (formulários/painel: KB, não MB).
_TAM_CORPO_MAX = 32 * 1024 * 1024


def sem_porta(host: str) -> str:
    """``dom:8446`` -> ``dom``. IPv6 entre colchetes mantém o colchete.

    ``count(':') == 1`` de propósito: IPv6 cru sem colchete tem vários
    ``:`` e nunca deve ser cortado.
    """
    h = (host or "").strip()
    if not h:
        return h
    if h.startswith("["):
        fim = h.find("]")
        return h[:fim + 1] if fim > 0 else h
    if h.count(":") == 1:
        return h.split(":", 1)[0]
    return h


def _limpa_location(valor: str, alvos: set[str]) -> str:
    """``http://127.0.0.1:8091/login`` -> ``/login`` (só se o alvo é o
    backend — redirect absoluto pra fora passa inteiro)."""
    if not valor.startswith(("http://", "https://")):
        return valor
    resto = valor.split("://", 1)[1]
    netloc, _, caminho = resto.partition("/")
    if netloc in alvos:
        return "/" + caminho
    return valor


class _Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    servidor_backend: tuple[str, int] = ("127.0.0.1", 8091)

    # --- identidade do handler ------------------------------------------
    def log_message(self, formato: str, *args) -> None:  # noqa: N802
        texto = formato % args if args else formato
        log.debug(f"azura_proxy {texto}")

    # --- leitura ----------------------------------------------------------
    def _corpo(self) -> bytes | None:
        """``None`` = erro já respondido ao cliente (não encaminhar)."""
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            self.send_error(411, "Length Required (corpo chunked não suportado)")
            return None
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0:
            return b""
        if tamanho > _TAM_CORPO_MAX:
            self.send_error(413, "Corpo grande demais")
            return None
        return self.rfile.read(tamanho)

    def _le_cabecalho_resposta(self, sock: socket.socket) -> tuple[bytes, list[tuple[str, str]], bytes]:
        """Lê status + cabeçalhos da resposta; devolve também os bytes já
        lidos que pertencem ao corpo (podem vir no mesmo pacote)."""
        bruto = bytearray()
        while b"\r\n\r\n" not in bruto:
            pedaco = sock.recv(65536)
            if not pedaco:
                raise ConnectionError("backend fechou antes do cabeçalho")
            bruto.extend(pedaco)
            if len(bruto) > 128 * 1024:
                raise ConnectionError("cabeçalho de resposta grande demais")
        ini, resto = bytes(bruto).split(b"\r\n\r\n", 1)
        linhas = ini.split(b"\r\n")
        status = int(linhas[0].split(b" ", 2)[1])
        cabecas = [(l.split(b":", 1)[0].decode("latin-1").strip(),
                    l.split(b":", 1)[1].decode("latin-1").strip())
                   for l in linhas[1:] if b":" in l]
        return status, cabecas, resto

    def _encaminha(self) -> None:
        corpo = self._corpo()
        if corpo is None:
            return

        alvo_host, alvo_porta = self.servidor_backend
        try:
            back = socket.create_connection((alvo_host, alvo_porta), timeout=10)
        except OSError as exc:
            log.warn("azura_proxy backend fora do ar", erro=str(exc))
            self.send_error(502, "azura_indisponivel")
            return
        back.settimeout(None)

        try:
            self._requisita(back, corpo)
            self._resposta(back)
        except OSError as exc:
            log.warn("azura_proxy caiu no meio do repasse", erro=str(exc))
            try:
                self.send_error(502, "azura_proxy_interrompido")
            except OSError:
                pass
        finally:
            try:
                back.close()
            except OSError:
                pass

    def _requisita(self, back: socket.socket, corpo: bytes) -> None:
        """Reescreve o pedido: Host do backend + X-Forwarded-Host sem porta."""
        origem_host = self.headers.get("Host", "")
        origem_xfh = self.headers.get("X-Forwarded-Host", "") or origem_host
        alvo_host, alvo_porta = self.servidor_backend

        pecas = [f"{self.command} {self.path} HTTP/1.1"]
        for chave, valor in self.headers.items():
            baixo = chave.lower()
            if baixo in _HOP or baixo == "host":
                continue
            if baixo == "x-forwarded-host":
                # AQUI está o conserto do 500: sem a porta.
                valor = sem_porta(origem_xfh)
            pecas.append(f"{chave}: {valor}")
        pecas.append(f"Host: {alvo_host}:{alvo_porta}")
        if "X-Forwarded-Host" not in self.headers:
            # sem o tailscale na frente o conserto continua valendo:
            # o backend nunca vê host com porta.
            pecas.append(f"X-Forwarded-Host: {sem_porta(origem_host)}")
        if "X-Forwarded-For" not in self.headers:
            pecas.append(f"X-Forwarded-For: {self.client_address[0]}")
        if corpo:
            pecas.append(f"Content-Length: {len(corpo)}")
        pecas.append("Connection: close")
        cab = ("\r\n".join(pecas) + "\r\n\r\n").encode("latin-1")
        back.sendall(cab + corpo)

    def _resposta(self, back: socket.socket) -> None:
        status, cabecas, resto = self._le_cabecalho_resposta(back)

        alvo = {f"{self.servidor_backend[0]}:{self.servidor_backend[1]}",
                self.servidor_backend[0]}
        alvos = set(alvo)
        # também aceita o host de origem (dominio[:porta]) como alvo
        origem = self.headers.get("Host", "")
        if origem:
            alvos.add(origem)
            alvos.add(sem_porta(origem))

        saida = [f"HTTP/1.1 {status} {self.responses.get(status, ('',))[0] or 'OK'}"]
        tem_moldura = False
        for chave, valor in cabecas:
            baixo = chave.lower()
            if baixo in _HOP and baixo != "transfer-encoding":
                continue
            if baixo == "location":
                valor = _limpa_location(valor, alvos)
            if baixo in ("content-length", "transfer-encoding"):
                tem_moldura = True
            saida.append(f"{chave}: {valor}")
        if not tem_moldura:
            # resposta sem moldura (close-delimited): fechamos na ponta.
            saida.append("Connection: close")
        self.wfile.write(("\r\n".join(saida) + "\r\n\r\n").encode("latin-1"))

        if self.command == "HEAD":
            self.close_connection = True
            return

        tamanho = next((int(v) for k, v in cabecas
                        if k.lower() == "content-length"), None)
        restante = None if tamanho is None else tamanho - len(resto)
        if resto:
            # o corpo já pode ter vindo junto com o cabeçalho no 1º recv
            self.wfile.write(resto)
        while True:
            if restante is not None and restante <= 0:
                break
            pedaco = back.recv(65536 if restante is None else min(65536, restante))
            if not pedaco:
                break
            if restante is not None:
                restante -= len(pedaco)
            self.wfile.write(pedaco)
        self.close_connection = True

    # --- verbos -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._encaminha()

    def do_HEAD(self) -> None:  # noqa: N802
        self._encaminha()

    def do_POST(self) -> None:  # noqa: N802
        self._encaminha()

    def do_PUT(self) -> None:  # noqa: N802
        self._encaminha()

    def do_PATCH(self) -> None:  # noqa: N802
        self._encaminha()

    def do_DELETE(self) -> None:  # noqa: N802
        self._encaminha()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._encaminha()


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def construir(porta: int | None = None,
              backend: tuple[str, int] | None = None) -> _Servidor:
    """Servidor do proxy (para o unit e para os testes)."""
    classe = type("_ProxyInstancia", (_Proxy,),
                  {"servidor_backend": backend or _backend()})
    # ``porta=0`` é efêmera de verdade (testes) — ``0 or PORTA`` pegaria a
    # porta do serviço e quebraria com "Address already in use" no ar.
    srv = _Servidor(("127.0.0.1", PORTA if porta is None else porta), classe)
    return srv


def _backend() -> tuple[str, int]:
    alvo = BACKEND
    if alvo.startswith("[") and "]:" in alvo:            # [v6]:porta
        host, _, porta = alvo[1:].partition("]:")
        return host, int(porta)
    host, _, porta = alvo.rpartition(":")
    return host or alvo, int(porta or 8091)


def main() -> None:
    srv = construir()
    host, porta = srv.server_address[:2]
    log.info(f"AzuraProxy escutando em {host}:{porta} -> {BACKEND} "
             "(porta tailnet na frente)")
    print(f"azura_proxy: {host}:{porta} -> {BACKEND}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("encerrando")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
