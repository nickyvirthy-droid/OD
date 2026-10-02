"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/transport.py
Descrição: Transporte HTTP do Google via urllib (stdlib) — o od-core não usa
           requests no caminho crítico. Define GoogleError e o helper que
           valida o status e decodifica JSON, com mensagem de erro legível
           vinda do próprio Google (error.message / error_description).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Google OAuth 2.0 / APIs REST (docs.google.com)
  - padrão do projeto: stdlib primeiro, degradação graciosa
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

__signature__ = "OD // CORE"


class GoogleError(Exception):
    """Falha ao falar com o OAuth ou com as APIs do Google."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


class UrllibTransport:
    """Transporte padrão (urllib). Assinatura compatível com um fake em teste."""

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        data: Optional[bytes] = None,
        timeout: float = 30.0,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url, data=data, method=method, headers=dict(headers or {})
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return int(resp.status), resp.read()
        except urllib.error.HTTPError as exc:
            # 4xx/5xx do Google vêm com corpo JSON útil — devolve para o caller
            return int(exc.code), exc.read()
        except urllib.error.URLError as exc:  # rede/DNS/TLS
            raise GoogleError(
                f"falha de rede ao falar com o Google: {exc.reason}"
            ) from exc


DEFAULT_TRANSPORT = UrllibTransport()


def decode_json(body: bytes) -> Any:
    """Decodifica o corpo em JSON ({} quando vazio/ inválido)."""
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _error_message(payload: Any, status: int) -> str:
    """Mensagem legível do erro do Google (ou HTTP <status>)."""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            desc = payload.get("error_description")
            return f"{err}" + (f" ({desc})" if desc else "")
    return f"HTTP {status}"


def checked(status: int, body: bytes, *, context: str) -> Any:
    """Devolve o JSON quando 2xx; senão levanta GoogleError com o motivo."""
    payload = decode_json(body)
    if 200 <= status < 300:
        return payload
    raise GoogleError(
        f"{context}: {_error_message(payload, status)}",
        status=status,
        payload=payload,
    )
