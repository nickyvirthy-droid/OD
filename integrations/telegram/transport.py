"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/telegram/transport.py
Descrição: Camada de transporte do Telegram Bot — protocolo comum com
           duas implementações: InMemoryTransport (testes/dev, sem rede) e
           HTTPTransport (Bot API via urllib stdlib, token obrigatório).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py (Telegram Bot API)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1

Architecture:
    O bot não conhece HTTP: depende de um Transport que entrega Updates e
    envia mensagens. Em produção usa-se HTTPTransport (getUpdates/sendMessage
    contra api.telegram.org via urllib — sem dependência externa); em testes
    e desenvolvimento local, InMemoryTransport evita rede e tokens.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Protocol

from core.logger import get_logger
from integrations.telegram.models import Update

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.telegram.transport")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TransportError(Exception):
    """Erro de transporte do Telegram."""


class TransportConfigError(TransportError, ValueError):
    """Configuração ausente/inválida (ex: token)."""


class TelegramTransport(Protocol):
    """Contrato de transporte do bot."""

    async def get_updates(self, offset: Optional[int] = None) -> list[Update]: ...

    async def send_message(self, chat_id: int, text: str) -> bool: ...

    async def fetch_file(self, file_id: str) -> Optional[bytes]: ...


# ---------------------------------------------------------------------------
# InMemoryTransport (testes e dev sem rede)
# ---------------------------------------------------------------------------

class InMemoryTransport:
    """Transporte em memória: filas de updates e mensagens enviadas."""

    def __init__(self) -> None:
        self.incoming: list[Update] = []
        self.sent: list[dict[str, Any]] = []
        self._next_update_id = 1
        self.files: dict[str, bytes] = {}
        self.closed = False
        # Confirmação, como o offset mantido pelo servidor real do Telegram:
        # getUpdates(offset=N) confirma updates com update_id < N e devolve
        # os com update_id >= N. O bot avança enviando offset = último + 1.
        self._confirmed = 0

    # -- Helpers de teste ----------------------------------------------------

    def add_message(self, chat_id: int, text: str, user_id: int = 1) -> Update:
        """Enfileira uma mensagem de texto como update."""
        from integrations.telegram.models import Message, User

        update = Update(
            update_id=self._next_update_id,
            message=Message(
                message_id=self._next_update_id * 10,
                chat_id=chat_id,
                user=User(id=user_id, first_name=f"user{user_id}"),
                text=text,
                date=time.time(),
            ),
        )
        self._next_update_id += 1
        self.incoming.append(update)
        return update

    def add_voice(
        self, chat_id: int, file_id: str, user_id: int = 1
    ) -> Update:
        """Enfileira um update de voz."""
        from integrations.telegram.models import Message, User, Voice

        update = Update(
            update_id=self._next_update_id,
            message=Message(
                message_id=self._next_update_id * 10,
                chat_id=chat_id,
                user=User(id=user_id, first_name=f"user{user_id}"),
                voice=Voice(file_id=file_id, duration_s=2.0),
                date=time.time(),
            ),
        )
        self._next_update_id += 1
        self.incoming.append(update)
        return update

    def seed_file(self, file_id: str, content: bytes) -> None:
        """Simula download de arquivo (para testes de STT)."""
        self.files[file_id] = content

    # -- Protocolo -----------------------------------------------------------

    async def get_updates(self, offset: Optional[int] = None) -> list[Update]:
        if offset is not None:
            self._confirmed = max(self._confirmed, int(offset) - 1)
        pending = [u for u in self.incoming if u.update_id > self._confirmed]
        return sorted(pending, key=lambda u: u.update_id)

    async def send_message(self, chat_id: int, text: str) -> bool:
        self.sent.append({"chat_id": chat_id, "text": text, "ts": time.time()})
        return True

    async def fetch_file(self, file_id: str) -> Optional[bytes]:
        return self.files.get(file_id)

    @property
    def sent_texts(self) -> list[str]:
        return [entry["text"] for entry in self.sent]

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# HTTPTransport (Bot API via urllib — token obrigatório)
# ---------------------------------------------------------------------------

class HTTPTransport:
    """Transporte real contra a Telegram Bot API (stdlib urllib).

    Exige um bot token (ex: env TELEGRAM_BOT_TOKEN). Sem token, o bot pode
    existir mas não conecta à rede (TransportConfigError no construtor).
    """

    def __init__(
        self,
        token: str,
        *,
        timeout: float = 10.0,
        api_base: str = TELEGRAM_API,
    ) -> None:
        token = (token or "").strip()
        if not token:
            raise TransportConfigError(
                "token do Telegram ausente — configure TELEGRAM_BOT_TOKEN"
            )
        self.token = token
        self.timeout = timeout
        self.api_base = api_base
        self._offset: Optional[int] = None

    def _call(self, method: str, **params: Any) -> dict[str, Any]:
        url = self.api_base.format(token=self.token, method=method)
        payload = json.dumps(params).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TransportError(
                f"Telegram API {exc.code}: {body[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TransportError(f"Telegram API indisponível: {exc}") from exc
        if not data.get("ok"):
            raise TransportError(f"Telegram API erro: {data}")
        return data

    @staticmethod
    def _parse_update(raw: dict[str, Any]) -> Update:
        from integrations.telegram.models import Message, User, Voice

        msg_raw = raw.get("message") or {}
        user_raw = msg_raw.get("from") or {}
        user = User(
            id=user_raw.get("id", 0),
            first_name=user_raw.get("first_name", ""),
            username=user_raw.get("username", ""),
            is_bot=bool(user_raw.get("is_bot", False)),
        )
        message: Optional[Message] = None
        if msg_raw:
            voice_raw = msg_raw.get("voice")
            voice = None
            if voice_raw:
                voice = Voice(
                    file_id=voice_raw.get("file_id", ""),
                    duration_s=float(voice_raw.get("duration", 0.0)),
                )
            message = Message(
                message_id=int(msg_raw.get("message_id", 0)),
                chat_id=int((msg_raw.get("chat") or {}).get("id", 0)),
                user=user,
                text=msg_raw.get("text") or "",
                voice=voice,
                date=float(msg_raw.get("date", 0.0)),
            )
        return Update(update_id=int(raw.get("update_id", 0)), message=message, raw=raw)

    async def get_updates(self, offset: Optional[int] = None) -> list[Update]:
        params: dict[str, Any] = {"timeout": 1}
        if offset is not None:
            params["offset"] = offset
        data = self._call("getUpdates", **params)
        updates = [self._parse_update(raw) for raw in data.get("result", [])]
        if updates:
            self._offset = updates[-1].update_id + 1
        return updates

    async def send_message(self, chat_id: int, text: str) -> bool:
        self._call("sendMessage", chat_id=chat_id, text=text)
        return True

    async def fetch_file(self, file_id: str) -> Optional[bytes]:
        """Baixa arquivo via getFile + file download (leitura, sem escrita)."""
        data = self._call("getFile", file_id=file_id)
        file_path = (data.get("result") or {}).get("file_path")
        if not file_path:
            return None
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.URLError as exc:
            raise TransportError(f"download falhou: {exc}") from exc
