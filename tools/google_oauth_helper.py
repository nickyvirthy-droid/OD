#!/usr/bin/env python3
"""OMEGA DRAKON • HELPERS
Tecnologia que respira.
Módulo: tools/google_oauth_helper.py
Descrição: captura do código OAuth do Google SEM copiar/colar.

Este arquivo roda no COMPUTADOR DO DONO (não no servidor). Ele:
  1) sobe um servidor pequeno em http://localhost:8766 (só local);
  2) abre a URL de consentimento no navegador padrão;
  3) quando o Google redirecionar com ?code=..., guarda a URL num arquivo
     e — se houver SSH até o servidor — envia o arquivo automaticamente
     para ~/OmegaDrakon/data/google_auth_url.txt;
  4) sem SSH, o arquivo fica em ./google_auth_url.txt (é só mandar esse
     arquivo para o servidor, ex.: scp google_auth_url.txt alex@192.168.0.250:OmegaDrakon/data/).

Uso:
    python3 google_oauth_helper.py               # caminho normal
    python3 google_oauth_helper.py --no-open     # não abre o navegador
    python3 google_oauth_helper.py --no-ssh      # só grava o arquivo local
    python3 google_oauth_helper.py --dry-run     # teste do servidor local

O token NUNCA é tratado aqui — quem troca o código por token é o servidor
(`.venv/bin/python -m runtime.google_auth --code "<url>"`).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import argparse
import http.server
import pathlib
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

__signature__ = "OD // CORE"

DEFAULT_PORT = 8766
DEFAULT_TIMEOUT = 600  # 10 min: o código do Google expira por volta disso
DEFAULT_TARGET = "alex@192.168.0.250:OmegaDrakon/data/google_auth_url.txt"
LOCAL_FILE = pathlib.Path("google_auth_url.txt")

# Mesma URL que o servidor gera com: .venv/bin/python -m runtime.google_auth --url
# (redirect_uri=http://localhost:8766/ confere com config/google_credentials.json)
CONSENT_URL = (
    "https://accounts.google.com/o/oauth2/v2/auth"
    "?client_id=582855984584-2mm9i3i9p3np8jtdtink43rlao4lgtak.apps.googleusercontent.com"
    "&redirect_uri=http%3A%2F%2Flocalhost%3A8766%2F"
    "&response_type=code"
    "&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.readonly"
    "+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.readonly"
    "+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly"
    "&access_type=offline"
    "&prompt=consent"
    "&include_granted_scopes=true"
)

PAGINA_OK = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>OmegaDrakon — autorização recebida</title>
<body style="font-family: sans-serif; margin: 3rem; line-height: 1.6">
<h2>✅ Código recebido pelo OmegaDrakon</h2>
<p>Pode fechar esta aba e voltar ao terminal.</p>
<p style="color:#666">{detalhe}</p>
</body></html>"""


def _porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def _enviar_para_o_servidor(url: str, alvo: str) -> str:
    """Envia a URL de retorno ao servidor por SSH (cat > arquivo)."""
    host, _, caminho = alvo.partition(":")
    if not caminho:
        caminho = "OmegaDrakon/data/google_auth_url.txt"
    comando = ["ssh", "-o", "ConnectTimeout=10", host, f"cat > {caminho}"]
    try:
        proc = subprocess.run(
            comando, input=url + "\n", text=True, timeout=45, capture_output=True
        )
    except (OSError, subprocess.SubprocessError) as exc:  # sem ssh/timeout
        return f"SSH indisponível ({exc})"
    if proc.returncode != 0:
        return f"SSH falhou ({proc.returncode}): {(proc.stderr or '').strip()[:120]}"
    return f"URL enviada ao servidor em ~{caminho}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--porta", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--alvo", default=DEFAULT_TARGET, help="user@host:caminho no servidor")
    parser.add_argument("--no-open", action="store_true", help="não abre o navegador")
    parser.add_argument("--no-ssh", action="store_true", help="não envia por SSH")
    parser.add_argument("--dry-run", action="store_true", help="só sobe o servidor local (teste)")
    args = parser.parse_args(argv)

    if not _porta_livre(args.porta):
        print(f"✗ a porta {args.porta} já está em uso — feche quem estiver nela e tente de novo")
        return 1

    capturado: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — assinatura do http.server
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            url_completa = f"http://localhost:{args.porta}/?{query}"
            if "error" in params:
                capturado["erro"] = str(params["error"][0])
            elif "code" in params:
                capturado["url"] = url_completa
            else:
                capturado.setdefault("url", url_completa)
            detalhe = "O terminal vai concluir o processo." if capturado.get("url") else ""
            corpo = PAGINA_OK.format(detalhe=detalhe).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *__) -> None:  # silencia o log padrão
            return

    servidor = http.server.HTTPServer(("127.0.0.1", args.porta), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"✓ escutando em http://localhost:{args.porta}/ (só nesta máquina)")

    if not args.dry_run and not args.no_open:
        aberto = webbrowser.open(CONSENT_URL)
        print("✓ navegador aberto com a autorização do Google"
              if aberto else "⚠ não consegui abrir o navegador — abra a URL manualmente:")
        if not aberto:
            print(f"  {CONSENT_URL}")

    limite = time.time() + (5 if args.dry_run else args.timeout)
    try:
        while time.time() < limite and not capturado:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\ninterrompido")
    finally:
        servidor.shutdown()

    if not capturado:
        print("✗ nada recebido dentro do tempo — rode de novo e autorize")
        return 1
    if "erro" in capturado:
        print(f"✗ o Google devolveu erro: {capturado['erro']}")
        return 1

    url = capturado["url"]
    LOCAL_FILE.write_text(url + "\n", encoding="utf-8")
    print(f"✓ código recebido e salvo em {LOCAL_FILE.resolve()}")
    if not args.no_ssh:
        print(f"  {_enviar_para_o_servidor(url, args.alvo)}")
    print()
    print("Próximo passo: avise o Buffy no chat que o código chegou —")
    print("ele troca o código pelo token no servidor e conclui o restante.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
