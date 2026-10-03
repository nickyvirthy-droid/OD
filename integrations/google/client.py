"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/client.py
Descrição: GoogleClient — cliente HTTP autenticado (Bearer) das APIs do
           Google, com renovação automática do access_token pelo
           refresh_token e persistência do token em disco. Sem token salvo,
           degrada com GoogleError legível (nunca estoura no pipeline).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Optional
from urllib.parse import urlencode

from core.logger import get_logger
from integrations.google import oauth
from integrations.google.models import GoogleCredentials, GoogleToken
from integrations.google.transport import DEFAULT_TRANSPORT, GoogleError, checked

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.google")

# Bases das APIs (Google Discovery).
DRIVE_BASE = "https://www.googleapis.com/drive/v3"
CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"

DEFAULT_TOKEN_PATH = "data/google_token.json"


def load_token(path: str | pathlib.Path) -> GoogleToken:
    """Carrega o token salvo; ausente/corrompido → token vazio (não autorizado)."""
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return GoogleToken()
    if not isinstance(raw, dict):
        return GoogleToken()
    return GoogleToken.from_dict(raw)


def save_token(path: str | pathlib.Path, token: GoogleToken) -> None:
    """Grava o token (0600) criando o diretório se preciso."""
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(token.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:  # pragma: no cover — FS sem permissão de chmod
        pass


class GoogleClient:
    """Cliente autenticado. O token pode ser injetado (testes) ou carregado."""

    def __init__(
        self,
        credentials: GoogleCredentials,
        token: Optional[GoogleToken] = None,
        *,
        token_path: Optional[str | pathlib.Path] = None,
        transport: Optional[Any] = None,
        timeout: float = 30.0,
    ) -> None:
        self.credentials = credentials
        self.token = token or GoogleToken()
        self.token_path = pathlib.Path(token_path) if token_path else None
        self._transport = transport or DEFAULT_TRANSPORT
        self.timeout = timeout

    # -- Token --------------------------------------------------------------

    @property
    def authorized(self) -> bool:
        return self.token.authorized

    def ensure_access_token(self) -> str:
        """Access token válido, renovando se expirado. Sem token → GoogleError."""
        if not self.token.authorized:
            raise GoogleError(
                "Google não autorizado — rode `python -m runtime.google_auth` "
                "para autorizar a conta"
            )
        if self.token.is_expired():
            log.info("Renovando access_token do Google")
            self.token = oauth.refresh_access_token(
                self.credentials, self.token, transport=self._transport
            )
            if self.token_path is not None:
                save_token(self.token_path, self.token)
        return self.token.access_token

    # -- HTTP ---------------------------------------------------------------

    def _headers(self, *, json_body: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.ensure_access_token()}",
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Requisição JSON autenticada; levanta GoogleError em erro."""
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                # doseq: valores em lista viram parâmetros REPETIDOS
                # (metadataHeaders=From&metadataHeaders=Subject), como o Google
                # espera — sem isso a lista vira repr de Python na URL e o
                # Gmail responde sem cabeçalhos (bug da prova viva 03/10).
                url = f"{url}?{urlencode(clean, doseq=True)}"
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
        status, raw = self._transport(
            method,
            url,
            headers=self._headers(json_body=json_body is not None),
            data=data,
            timeout=timeout or self.timeout,
        )
        return checked(status, raw, context=f"{method} {url.split('?')[0]}")

    def request_raw(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        accept: str = "*/*",
        timeout: Optional[float] = None,
    ) -> bytes:
        """Requisição que devolve o corpo cru (download/export de arquivos)."""
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url = f"{url}?{urlencode(clean, doseq=True)}"
        headers = {
            "Authorization": f"Bearer {self.ensure_access_token()}",
            "Accept": accept,
        }
        status, raw = self._transport(
            method, url, headers=headers, data=None, timeout=timeout or self.timeout
        )
        if 200 <= status < 300:
            return raw
        checked(status, raw, context=f"{method} {url.split('?')[0]}")
        return b""  # inalcançável (checked levanta), mantém o type checker feliz

    def get(self, url: str, **kw: Any) -> Any:
        return self.request("GET", url, **kw)

    def request_body(
        self,
        method: str,
        url: str,
        *,
        body: bytes,
        content_type: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Requisição com corpo CRU — upload multipart/mídia do Drive e
        envio de e-mail (lote 2 de escrita, 2026-10-03)."""
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url = f"{url}?{urlencode(clean, doseq=True)}"
        headers = {
            "Authorization": f"Bearer {self.ensure_access_token()}",
            "Accept": "application/json",
            "Content-Type": content_type,
        }
        status, raw = self._transport(
            method, url, headers=headers, data=body, timeout=timeout or self.timeout
        )
        return checked(status, raw, context=f"{method} {url.split('?')[0]}")
