"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: integrations/telegram/
Descrição: Integração Telegram (Fase 5, item 5.1) — bot sobre o Orchestrator
           com 13 comandos de texto + voz/STT, transportes plugáveis
           (InMemoryTransport para testes/dev, HTTPTransport via Bot API).

Módulos:
  - models.py     → User, Voice, Message, Update (tipos desacoplados)
  - transport.py  → TelegramTransport, InMemoryTransport, HTTPTransport
  - commands.py   → 13 comandos do legado Nicky (+voz como 14º recurso)
  - bot.py        → TelegramBot (orquestração + Orchestrator + polling)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1
"""

from integrations.telegram.bot import TelegramBot, BotMetrics
from integrations.telegram.commands import (
    PROFILES,
    TelegramCommand,
    CommandContext,
    build_default_commands,
)
from integrations.telegram.models import Message, Update, User, Voice
from integrations.telegram.transport import (
    HTTPTransport,
    InMemoryTransport,
    TelegramTransport,
    TransportConfigError,
    TransportError,
)

__signature__ = "OD // CORE"
__all__ = [
    "TelegramBot",
    "BotMetrics",
    "TelegramCommand",
    "CommandContext",
    "build_default_commands",
    "PROFILES",
    "User",
    "Voice",
    "Message",
    "Update",
    "TelegramTransport",
    "InMemoryTransport",
    "HTTPTransport",
    "TransportConfigError",
    "TransportError",
]
