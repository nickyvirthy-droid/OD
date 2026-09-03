"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/telegram/models.py
Descrição: Modelos tipados de mensagens do Telegram (User, Message, Update)
           — desacoplados do transporte HTTP (tests usam o mesmo formato).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py (Telegram Bot API)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__signature__ = "OD // CORE"


@dataclass(slots=True)
class User:
    """Um usuário do Telegram."""

    id: int
    first_name: str = ""
    username: str = ""
    is_bot: bool = False

    @property
    def display(self) -> str:
        return self.first_name or self.username or f"id{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "username": self.username,
            "is_bot": self.is_bot,
        }


@dataclass(slots=True)
class Voice:
    """Anexo de voz (para STT)."""

    file_id: str
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"file_id": self.file_id, "duration_s": self.duration_s}


@dataclass(slots=True)
class Message:
    """Uma mensagem recebida em um chat."""

    message_id: int
    chat_id: int
    user: User
    text: str = ""
    voice: Optional[Voice] = None
    date: float = 0.0

    @property
    def has_voice(self) -> bool:
        return self.voice is not None

    @property
    def is_command(self) -> bool:
        return self.text.startswith("/")

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "user": self.user.to_dict(),
            "text": self.text,
            "voice": self.voice.to_dict() if self.voice else None,
            "date": self.date,
        }


@dataclass(slots=True)
class Update:
    """Um update (nova mensagem) vindo do Telegram."""

    update_id: int
    message: Optional[Message] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "message": self.message.to_dict() if self.message else None,
        }
