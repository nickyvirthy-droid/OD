"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: integrations/google/
Descrição: Integração com o Google Workspace (Drive, Agenda/Gmail) via OAuth
           2.0 e REST, em stdlib puro. PRIMEIRO LOTE = SOMENTE LEITURA
           (decisão do dono, 2026-10-02); a escrita entra num 2º lote com
           gate de papel + confirmação.

Módulos:
  - transport.py → UrllibTransport + GoogleError (HTTP stdlib)
  - models.py    → GoogleCredentials, GoogleToken, escopos
  - oauth.py     → URL de autorização, troca de código e refresh
  - client.py    → GoogleClient (Bearer + renovação) e persistência do token
  - drive.py     → DriveService (leitura)
  - calendar.py  → CalendarService (leitura)
  - gmail.py     → GmailService (leitura)

Headless: o consentimento é feito no navegador do dono e a URL de retorno é
colada de volta (runtime/google_auth.py). Sem token salvo, o cliente degrada
com GoogleError legível — as actions respondem ok=False e o chat nunca
inventa dados.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from typing import Optional

from integrations.google import oauth
from integrations.google.calendar import CalendarService
from integrations.google.client import (
    CALENDAR_BASE,
    DRIVE_BASE,
    GMAIL_BASE,
    GoogleClient,
    load_token,
    save_token,
)
from integrations.google.drive import DriveService
from integrations.google.gmail import GmailService
from integrations.google.models import (
    DEFAULT_REDIRECT_URI,
    SCOPES_READ,
    GoogleCredentials,
    GoogleToken,
)
from integrations.google.transport import GoogleError, UrllibTransport

__signature__ = "OD // CORE"

__all__ = [
    "CalendarService",
    "DriveService",
    "GmailService",
    "GoogleClient",
    "GoogleCredentials",
    "GoogleError",
    "GoogleToken",
    "SCOPES_READ",
    "DEFAULT_REDIRECT_URI",
    "DRIVE_BASE",
    "CALENDAR_BASE",
    "GMAIL_BASE",
    "UrllibTransport",
    "oauth",
    "load_token",
    "save_token",
    "build_google_client",
]


def build_google_client(
    credentials_path: str,
    token_path: Optional[str] = None,
    *,
    transport: Optional[object] = None,
) -> GoogleClient:
    """Carrega as credenciais e o token e devolve um GoogleClient pronto.

    Sem token salvo, o cliente existe mas `authorized` é False — as actions
    degradam com a instrução de rodar o fluxo de autorização.
    """
    credentials = GoogleCredentials.from_file(credentials_path)
    token = load_token(token_path) if token_path else GoogleToken()
    return GoogleClient(
        credentials,
        token,
        token_path=token_path,
        transport=transport,
    )
