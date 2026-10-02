"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/google_auth.py
Descrição: CLI de autorização OAuth do Google (Drive/Agenda/Gmail — leitura).

O servidor é headless: não há navegador. O fluxo é:
  1. o script imprime a URL de consentimento;
  2. o dono abre no navegador (celular/PC) e autoriza;
  3. o Google redireciona para http://localhost:8766/?code=... (a página
     pode falhar — normal, o servidor não está escutando ali);
  4. o dono copia a URL INTEIRA da barra de endereço e cola de volta;
  5. o script troca o código por tokens e salva em data/google_token.json.

Uso:
    .venv/bin/python -m runtime.google_auth            # autoriza
    .venv/bin/python -m runtime.google_auth --check    # status do token
    .venv/bin/python -m runtime.google_auth --url      # só imprime a URL
    .venv/bin/python -m runtime.google_auth --code "<url ou code>"

O token NUNCA é impresso em claro.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
from typing import Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.runtime.google_auth")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CREDENTIALS = "config/google_credentials.json"
DEFAULT_TOKEN = "data/google_token.json"


def _resolve(env_fn, key: str, default: str) -> pathlib.Path:
    raw = env_fn(key, default) or default
    path = pathlib.Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _status(credentials_path: pathlib.Path, token_path: pathlib.Path) -> int:
    """Mostra o estado do token (sem imprimir segredos)."""
    from integrations.google import GoogleClient, GoogleCredentials, load_token

    if not credentials_path.exists():
        print(f"✗ credenciais ausentes: {credentials_path}")
        print("  Copie config/google_credentials.example.json e preencha, ou")
        print("  baixe o JSON do Cloud Console (Desktop app).")
        return 1
    credentials = GoogleCredentials.from_file(str(credentials_path))
    token = load_token(str(token_path))
    print("Google — estado da autorização")
    print(f"  credenciais : {credentials_path.name} (client_id …{credentials.client_id[-12:]})")
    print(f"  token       : {token_path} ({'presente' if token.authorized else 'AUSENTE'})")
    if not token.authorized:
        print("  status      : não autorizado — rode sem --check para autorizar")
        return 1
    print(f"  refresh     : {'sim' if token.refresh_token else 'NÃO (reautorize)'}")
    if token.expires_at:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(token.expires_at))
        print(f"  expira em   : {when} ({'expirado' if token.is_expired() else 'válido'})")
    print(f"  escopos     : {token.scope or '(não registrados)'}")
    if token.is_expired():
        try:
            client = GoogleClient(credentials, token, token_path=str(token_path))
            client.ensure_access_token()
            print("  renovação   : OK (access_token renova sozinho)")
        except Exception as exc:  # noqa: BLE001 — relatório, não crash
            print(f"  renovação   : FALHOU — {exc}")
            return 1
    return 0


def _authorize(
    credentials_path: pathlib.Path,
    token_path: pathlib.Path,
    *,
    code_arg: Optional[str],
    print_url_only: bool,
) -> int:
    from integrations.google import GoogleCredentials, GoogleError, load_token, oauth, save_token

    if not credentials_path.exists():
        print(f"✗ credenciais ausentes: {credentials_path}", file=sys.stderr)
        print("  Veja config/google_credentials.example.json e docs/GOOGLE.md.", file=sys.stderr)
        return 1
    credentials = GoogleCredentials.from_file(str(credentials_path))
    url = oauth.build_authorization_url(credentials)
    if print_url_only:
        print(url)
        return 0

    print("1) Abra esta URL no navegador e autorize a conta:")
    print()
    print(url)
    print()
    print("2) O Google vai redirecionar para http://localhost:8766/?code=...")
    print("   (a página pode não abrir — normal). Copie a URL INTEIRA da barra")
    print("   de endereço e cole abaixo (ou passe com --code).")

    pasted = code_arg
    if pasted is None:
        if not sys.stdin.isatty():
            print("✗ sem terminal interativo — use --code \"<url de retorno>\"", file=sys.stderr)
            return 1
        try:
            pasted = input("URL de retorno (ou code): ").strip()
        except EOFError:
            pasted = ""
    if not pasted:
        print("✗ nada colado — autorização cancelada", file=sys.stderr)
        return 1

    previous = load_token(str(token_path))
    try:
        token = oauth.exchange_code(
            credentials, pasted, previous_refresh=previous.refresh_token
        )
    except GoogleError as exc:
        print(f"✗ falha na troca do código: {exc}", file=sys.stderr)
        return 1
    save_token(token_path, token)
    print()
    print(f"✅ Autorizado. Token salvo em {token_path}")
    print(f"   escopos: {token.scope or '(não informados)'}")
    print("   Agora reinicie o od-core para as actions google_* serem ligadas.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Autoriza o acesso do OmegaDrakon ao Google (Drive/Agenda/Gmail)."
    )
    parser.add_argument("--credentials", default="", help=f"JSON do Cloud Console (default: {DEFAULT_CREDENTIALS})")
    parser.add_argument("--token", default="", help=f"onde salvar o token (default: {DEFAULT_TOKEN})")
    parser.add_argument("--check", action="store_true", help="só mostra o estado da autorização")
    parser.add_argument("--url", action="store_true", help="só imprime a URL de consentimento")
    parser.add_argument("--code", default=None, help="URL de retorno (ou code) para modo não interativo")
    args = parser.parse_args(argv)

    try:
        from runtime.launcher import env
    except Exception:  # pragma: no cover — uso isolado sem o launcher
        def env(key: str, default: str = "") -> str:  # type: ignore[misc]
            import os

            return os.environ.get(key, default)

    credentials_path = (
        pathlib.Path(args.credentials) if args.credentials
        else _resolve(env, "OD_GOOGLE_CREDENTIALS", DEFAULT_CREDENTIALS)
    )
    token_path = (
        pathlib.Path(args.token) if args.token
        else _resolve(env, "OD_GOOGLE_TOKEN", DEFAULT_TOKEN)
    )

    if args.check:
        return _status(credentials_path, token_path)
    return _authorize(
        credentials_path, token_path, code_arg=args.code, print_url_only=args.url
    )


if __name__ == "__main__":
    raise SystemExit(main())
