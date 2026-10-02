"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/oauth.py
Descrição: OAuth 2.0 do Google em stdlib — monta a URL de consentimento,
           troca o `code` por tokens e renova o access_token usando o
           refresh_token. Sem navegador embutido e sem libs: o servidor é
           headless, então o fluxo é "autorizar no navegador → colar a URL
           de retorno de volta" (ver runtime/google_auth.py).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - https://developers.google.com/identity/protocols/oauth2/native-app
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from integrations.google.models import (
    AUTH_ENDPOINT,
    TOKEN_ENDPOINT,
    GoogleCredentials,
    GoogleToken,
)
from integrations.google.transport import DEFAULT_TRANSPORT, GoogleError, checked

__signature__ = "OD // CORE"


def build_authorization_url(
    credentials: GoogleCredentials,
    *,
    state: str = "",
    access_type: str = "offline",
    prompt: str = "consent",
) -> str:
    """URL para o dono abrir no navegador e autorizar os escopos.

    `access_type=offline` + `prompt=consent` garantem o **refresh_token**
    (sem ele a integração expira em ~1h e exige nova autorização).
    """
    params = {
        "client_id": credentials.client_id,
        "redirect_uri": credentials.redirect_uri,
        "response_type": "code",
        "scope": " ".join(credentials.scopes),
        "access_type": access_type,
        "prompt": prompt,
        "include_granted_scopes": "true",
    }
    if state:
        params["state"] = state
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def extract_code(redirect_url_or_code: str) -> str:
    """Aceita a URL de retorno colada OU o código puro.

    O dono cola a URL inteira (http://localhost:8766/?code=...&scope=...);
    aqui extraímos o `code` e detectamos `error=access_denied`.
    """
    text = (redirect_url_or_code or "").strip()
    if not text:
        raise GoogleError("código de autorização vazio")
    if "code=" not in text and "error=" not in text:
        return text  # já é o código puro
    from urllib.parse import parse_qs, urlparse

    query = urlparse(text).query or text
    parsed = parse_qs(query)
    if parsed.get("error"):
        raise GoogleError(
            f"autorização recusada pelo Google: {parsed['error'][0]}"
        )
    codes = parsed.get("code") or []
    if not codes:
        raise GoogleError("URL de retorno sem 'code'")
    return codes[0]


def _token_request(
    form: dict[str, str], *, transport: Optional[Any] = None
) -> dict[str, Any]:
    http = transport or DEFAULT_TRANSPORT
    body = urlencode(form).encode("utf-8")
    status, raw = http(
        "POST",
        TOKEN_ENDPOINT,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    return checked(status, raw, context="OAuth do Google")


def exchange_code(
    credentials: GoogleCredentials,
    code: str,
    *,
    previous_refresh: str = "",
    transport: Optional[Any] = None,
) -> GoogleToken:
    """Troca o `code` de autorização por access_token + refresh_token."""
    if not credentials.configured:
        raise GoogleError("credenciais Google incompletas (client_id/secret)")
    data = _token_request(
        {
            "code": extract_code(code),
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "redirect_uri": credentials.redirect_uri,
            "grant_type": "authorization_code",
        },
        transport=transport,
    )
    token = GoogleToken.from_token_response(data, previous_refresh=previous_refresh)
    if not token.access_token:
        raise GoogleError("Google não devolveu access_token")
    return token


def refresh_access_token(
    credentials: GoogleCredentials,
    token: GoogleToken,
    *,
    transport: Optional[Any] = None,
) -> GoogleToken:
    """Renova o access_token a partir do refresh_token."""
    if not token.refresh_token:
        raise GoogleError(
            "token sem refresh_token — rode o fluxo de autorização de novo "
            "(prompt=consent)"
        )
    data = _token_request(
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
        },
        transport=transport,
    )
    renewed = GoogleToken.from_token_response(data, previous_refresh=token.refresh_token)
    if not renewed.access_token:
        raise GoogleError("renovação não devolveu access_token")
    return renewed
