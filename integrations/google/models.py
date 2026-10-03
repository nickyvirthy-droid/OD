"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/models.py
Descrição: Modelos da integração Google (Drive/Agenda/Gmail) — credenciais do
           aplicativo (client_id/secret), escopos e o token OAuth (access +
           refresh + expiração). Sem dependência externa: a leitura do
           arquivo aceita tanto o formato baixado do Google Cloud Console
           ("installed"/"web") quanto um JSON achatado do OmegaDrakon.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Google Cloud Console (OAuth client ID — Desktop app)
  - Google OAuth 2.0 (access_type=offline → refresh_token)
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

__signature__ = "OD // CORE"

# Endpoints (fixos do Google).
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Redirecionamento de loopback (Desktop app). O dono autoriza no navegador e
# cola a URL de retorno de volta no `runtime/google_auth.py` (headless: o
# servidor não tem navegador, então o código é capturado por colagem).
DEFAULT_REDIRECT_URI = "http://localhost:8766/"

# LOTE 1 (decisão do dono, 2026-10-02) = SOMENTE LEITURA. LOTE 2 = ESCRITA
# aprovada pelo dono (2026-10-03, "escopo cheio: atende o txt.txt inteiro"):
# criar/editar/apagar no Drive, criar/apagar eventos, enviar/apagar e-mail.
# As actions de escrita continuam atrás do gate de papel (admin) +
# confirmação de 2 passos, como o controle do lar (v1.8.1).
# Escopos: drive ⊃ drive.readonly · calendar.events ⊃ leitura de eventos +
# CRUD · gmail.modify (ler/mover para lixeira) + gmail.send (enviar).
SCOPES_FULL: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
)


@dataclass(slots=True)
class GoogleCredentials:
    """Credenciais do aplicativo OAuth (não confundir com o token do dono)."""

    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: tuple[str, ...] = SCOPES_FULL

    # -- Carregamento -------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | pathlib.Path) -> "GoogleCredentials":
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GoogleCredentials":
        """Aceita o formato do Cloud Console ou um JSON achatado.

        O Cloud Console baixa {"installed": {...}} (Desktop) ou {"web": {...}}.
        """
        data: dict[str, Any] = raw
        for key in ("installed", "web"):
            if isinstance(raw.get(key), dict):
                data = raw[key]
                break
        client_id = str(data.get("client_id", "")).strip()
        client_secret = str(data.get("client_secret", "")).strip()
        if not client_id or not client_secret:
            raise ValueError(
                "credenciais Google sem client_id/client_secret — veja "
                "config/google_credentials.example.json"
            )
        redirect_uri = str(data.get("redirect_uri", "")).strip()
        if not redirect_uri:
            uris = data.get("redirect_uris") or []
            redirect_uri = str(uris[0]) if uris else DEFAULT_REDIRECT_URI
        scopes = data.get("scopes")
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=tuple(str(s) for s in scopes) if scopes else SCOPES_FULL,
        )

    def to_dict(self, *, include_secret: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scopes": list(self.scopes),
        }
        if include_secret:
            out["client_secret"] = self.client_secret
        return out

    # -- Estado -------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(slots=True)
class GoogleToken:
    """Token OAuth do dono (access + refresh). Nunca é logado em claro."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # epoch seconds
    scope: str = ""
    token_type: str = "Bearer"

    def is_expired(self, skew: float = 60.0) -> bool:
        """True se já expirou (ou expira em <= skew segundos)."""
        return (time.time() + skew) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GoogleToken":
        try:
            expires_at = float(raw.get("expires_at", 0.0))
        except (TypeError, ValueError):
            expires_at = 0.0
        return cls(
            access_token=str(raw.get("access_token", "")),
            refresh_token=str(raw.get("refresh_token", "")),
            expires_at=expires_at,
            scope=str(raw.get("scope", "")),
            token_type=str(raw.get("token_type", "Bearer")),
        )

    @classmethod
    def from_token_response(
        cls, data: dict[str, Any], *, previous_refresh: str = ""
    ) -> "GoogleToken":
        """Converte a resposta do endpoint /token (preserva o refresh antigo)."""
        token = cls(
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token") or previous_refresh),
            scope=str(data.get("scope", "")),
            token_type=str(data.get("token_type", "Bearer")),
        )
        expires_in = data.get("expires_in")
        if expires_in is not None:
            try:
                token.expires_at = time.time() + float(expires_in)
            except (TypeError, ValueError):
                token.expires_at = 0.0
        return token

    @property
    def authorized(self) -> bool:
        return bool(self.refresh_token or self.access_token)
