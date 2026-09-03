"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/telegram/bot.py
Descrição: TelegramBot — orquestra transporte + comandos + Orchestrator:
           recebe Updates do Transport, resolve comandos (13 de texto) ou
           voz (STT, 14º recurso), e encaminha mensagens livres ao pipeline
           do Orchestrator (perfis por chat, admin gate, métricas, polling).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py (Telegram Bot API, 14 comandos)
  - core/orchestrator.py (pipeline process(user_id, profile, text))
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger
from core.orchestrator import OrchestrationResult, Orchestrator
from integrations.telegram.commands import (
    CommandContext,
    TelegramCommand,
    build_default_commands,
)
from integrations.telegram.models import Message, Update
from integrations.telegram.transport import TelegramTransport, TransportError

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.telegram.bot")

DEFAULT_PROFILE = "guardian"
AUTO_PROFILE = "auto"
ChatId = Union[int, str]

# Decodificador de voz (STT) plugável: recebe os bytes do áudio e devolve
# texto transcrito (ou None se não conseguiu transcrever).
STTDecoder = Callable[[bytes], Optional[str]]


@dataclass(slots=True)
class BotMetrics:
    """Métricas acumuladas do bot."""

    messages: int = 0
    commands: int = 0
    replies: int = 0
    voices: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "commands": self.commands,
            "replies": self.replies,
            "voices": self.voices,
            "errors": self.errors,
        }


def _resolve_auto(profile: str) -> str:
    """'auto' significa deixar o OD escolher — hoje o perfil padrão."""
    return DEFAULT_PROFILE if profile == AUTO_PROFILE else profile


class TelegramBot:
    """Bot do Telegram sobre o Orchestrator (transportes plugáveis).

    Attributes:
        transport:    Entrega Updates e envia mensagens (rede ou memória).
        orchestrator: Pipeline central (opcional — sem ele, só comandos
                      locais respondem).
        admin_ids:    IDs do Telegram com acesso a comandos admin_only.
        commands:     Catálogo de comandos (padrão: 13 do legado Nicky).
    """

    def __init__(
        self,
        transport: TelegramTransport,
        orchestrator: Optional[Orchestrator] = None,
        *,
        admin_ids: Optional[set[int]] = None,
        commands: Optional[list[TelegramCommand]] = None,
        stt: Optional[STTDecoder] = None,
        default_profile: str = DEFAULT_PROFILE,
        offset_file: Optional[Union[str, os.PathLike]] = None,
    ) -> None:
        self.transport = transport
        self.orchestrator = orchestrator
        self.admin_ids: set[int] = set(admin_ids or ())
        self.commands: list[TelegramCommand] = list(
            commands if commands is not None else build_default_commands()
        )
        self.stt = stt
        self.default_profile = default_profile
        self.offset_file = (
            str(offset_file) if offset_file is not None else None
        )
        self.started_at = time.time()
        self.metrics = BotMetrics()
        self._profiles: dict[int, str] = {}
        self._by_name: dict[str, TelegramCommand] = {}
        self._by_alias: dict[str, TelegramCommand] = {}
        for command in self.commands:
            self._by_name[command.name] = command
            for alias in command.aliases:
                self._by_alias[alias] = command
        self._closed = False
        # Offset do próximo update a buscar (semântica do servidor: confirma
        # updates com update_id < offset). Persistido em arquivo para que
        # reinícios nunca reprocessem updates já confirmados.
        self._offset: Optional[int] = self._load_offset()
        log.info(
            "TelegramBot inicializado",
            commands=len(self.commands),
            admins=len(self.admin_ids),
            orchestrator=orchestrator is not None,
            transport=type(transport).__name__,
        )

    # ------------------------------------------------------------------
    # Perfis e admin
    # ------------------------------------------------------------------

    @property
    def started_at_text(self) -> str:
        return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(self.started_at))

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def get_profile(self, chat_id: int) -> str:
        return self._profiles.get(int(chat_id), self.default_profile)

    def set_profile(self, chat_id: int, profile: str) -> str:
        self._profiles[int(chat_id)] = profile
        return profile

    def profile_display(self, chat_id: int) -> str:
        return self.get_profile(chat_id)

    # ------------------------------------------------------------------
    # Handlers usados pelos comandos (camada commands.py)
    # ------------------------------------------------------------------

    def system_status(self) -> dict[str, Any]:
        """Estado resumido do sistema (comando /status)."""
        active_profiles = sorted({self.get_profile(c) for c in self._profiles})
        return {
            "bot": "online",
            "transporte": type(self.transport).__name__,
            "orchestrator": "conectado" if self.orchestrator else "desconectado",
            "comandos": len(self.commands),
            "chats": len(self._profiles),
            "perfis": ", ".join(active_profiles) if active_profiles else self.default_profile,
            "uptime_s": int(time.time() - self.started_at),
        }

    def orchestrator_metrics(self) -> Optional[dict[str, Any]]:
        if self.orchestrator is None:
            return None
        return self.orchestrator.metrics.snapshot()

    def history_lines(self, target_id: str, limit: int) -> Optional[list[str]]:
        """Últimas mensagens do histórico do Orchestrator (comando /historico)."""
        if self.orchestrator is None or self.orchestrator.history is None:
            return None
        profile = self.default_profile
        chat_id = self._chat_from_target(target_id)
        messages = self.orchestrator.history.get_history(str(chat_id), profile)
        lines = []
        for msg in messages[-limit:]:
            lines.append(f"• {msg.role}: {str(msg.content)[:200]}")
        return lines

    def clear_chat(self, chat_id: int) -> Optional[str]:
        """Limpa o histórico do chat no Orchestrator (comando /limpar)."""
        if self.orchestrator is None or self.orchestrator.history is None:
            return None
        profile = self.get_profile(chat_id)
        removed = self.orchestrator.history.clear(str(chat_id), profile=profile)
        return f"Histórico de {chat_id} ({profile}) removido — {removed} mensagens."

    def cache_stats(self) -> Optional[str]:
        """Estatísticas do cache LLM (comando /cache)."""
        if self.orchestrator is None or self.orchestrator.cache is None:
            return None
        stats = self.orchestrator.cache.stats()
        return (
            f"Entradas: {stats.get('entries', 0)} | "
            f"hits: {stats.get('hits', 0)} | "
            f"misses: {stats.get('misses', 0)} | "
            f"evictions: {stats.get('evictions', 0)}"
        )

    def clear_cache(self) -> str:
        """Limpa o cache LLM (comando /cache limpar)."""
        if self.orchestrator is None or self.orchestrator.cache is None:
            return "Nenhum cache LLM conectado para limpar."
        removed = self.orchestrator.cache.clear()
        return f"Cache LLM limpo — {removed} entradas removidas."

    def coder_status(self) -> str:
        """Métricas do Coder Engine via métricas do Orchestrator (se expostas)."""
        return (
            "Coder Engine: veja as métricas do Orchestrator /stats. "
            "A interface de agente sobre o Coder chega com a Fase 5/6."
        )

    # ------------------------------------------------------------------
    # Processamento de Updates
    # ------------------------------------------------------------------

    def find_command(self, text: str) -> Optional[tuple[TelegramCommand, CommandContext]]:
        """Resolve o comando (nome ou alias) para um texto iniciado em '/'.

        Returns:
            (comando, contexto) ou None se não for um comando conhecido.
        """
        if not text.startswith("/"):
            return None
        parts = text[1:].split()
        if not parts:
            return None
        raw_name = parts[0].split("@")[0].lower()
        command = self._by_name.get(raw_name) or self._by_alias.get(raw_name)
        if command is None:
            return None
        return command, parts[1:]

    async def handle_update(self, update: Update) -> Optional[str]:
        """Processa um update e devolve o texto enviado como resposta."""
        message = update.message
        if message is None:
            return None
        self.metrics.messages += 1
        if message.has_voice:
            return await self._handle_voice(message)
        return await self._handle_text(message)

    async def _handle_text(self, message: Message) -> Optional[str]:
        resolved = self.find_command(message.text)
        if resolved is not None:
            command, args = resolved
            reply = self._run_command(command, message, args)
        else:
            reply = await self._ask_orchestrator(message)
        return await self._send_reply(message.chat_id, reply)

    async def _handle_voice(self, message: Message) -> Optional[str]:
        """14º recurso: voz → STT → texto → pipeline normal."""
        self.metrics.voices += 1
        file_id = message.voice.file_id if message.voice else ""
        if not file_id:
            return await self._send_reply(
                message.chat_id, "Não consegui localizar o áudio enviado."
            )
        try:
            data = await self.transport.fetch_file(file_id)
        except TransportError as exc:
            self.metrics.errors += 1
            log.error("Falha ao baixar áudio", error=str(exc))
            return await self._send_reply(
                message.chat_id, "Falha ao baixar o áudio. Tente novamente."
            )
        if data is None:
            return await self._send_reply(
                message.chat_id, "Áudio não encontrado (expirou?)."
            )
        text = self._decode_voice(data)
        if not text:
            return await self._send_reply(
                message.chat_id,
                "🎤 Recebi seu áudio, mas não consegui transcrevê-lo "
                "(STT não configurado ou áudio vazio).",
            )
        # Transcrição vira uma mensagem de texto normal do usuário.
        transcribed = Message(
            message_id=message.message_id,
            chat_id=message.chat_id,
            user=message.user,
            text=f"[voz] {text}",
            date=message.date,
        )
        reply = await self._ask_orchestrator(transcribed)
        return await self._send_reply(message.chat_id, reply)

    def _decode_voice(self, data: bytes) -> str:
        """Aplica o STT plugável ou fallback de texto puro (utf-8)."""
        if self.stt is not None:
            try:
                return (self.stt(data) or "").strip()
            except Exception as exc:  # pragma: no cover — decoder externo
                self.metrics.errors += 1
                log.error("STT falhou", error=str(exc))
                return ""
        try:
            return data.decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""

    def _run_command(
        self, command: TelegramCommand, message: Message, args: list[str]
    ) -> str:
        """Executa um comando com admin gate; devolve o texto de resposta."""
        self.metrics.commands += 1
        user = message.user
        ctx = CommandContext(
            command=command.name,
            raw=message.text,
            chat_id=message.chat_id,
            user_id=user.id,
            is_admin=self.is_admin(user.id),
            args=args,
        )
        if command.admin_only and not ctx.is_admin:
            self.metrics.errors += 1
            log.warn(
                "Comando admin negado", command=command.name, user_id=user.id
            )
            return "⛔ Comando restrito ao administrador."
        try:
            return command.handler(self, ctx)
        except Exception as exc:  # pragma: no cover — handler quebrou
            self.metrics.errors += 1
            log.error("Comando falhou", command=command.name, error=str(exc))
            return f"Erro ao executar /{command.name}: {type(exc).__name__}"

    async def _ask_orchestrator(self, message: Message) -> str:
        """Encaminha texto livre ao pipeline do Orchestrator."""
        if self.orchestrator is None:
            return (
                "Não consigo conversar agora — o Orchestrator não está "
                "conectado. Use /help para os comandos disponíveis."
            )
        profile = _resolve_auto(self.get_profile(message.chat_id))
        try:
            result: OrchestrationResult = await self.orchestrator.process(
                str(message.chat_id),
                profile,
                message.text,
                session_id=f"tg:{message.chat_id}",
            )
            if not result.ok:
                self.metrics.errors += 1
            return result.message
        except Exception as exc:
            self.metrics.errors += 1
            log.error("Orchestrator falhou", error=str(exc))
            return "Desculpe, tive um erro interno ao processar sua mensagem."

    async def _send_reply(self, chat_id: int, text: str) -> Optional[str]:
        """Envia a resposta; devolve o texto enviado (ou None se falhou)."""
        try:
            ok = await self.transport.send_message(chat_id, text)
        except TransportError:
            self.metrics.errors += 1
            log.error("Falha ao enviar mensagem", chat_id=chat_id)
            return None
        if ok:
            self.metrics.replies += 1
        return text

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def run(
        self,
        interval: float = 1.0,
        max_updates: Optional[int] = None,
    ) -> int:
        """Loop de polling: consome updates do transporte até o fechamento.

        O offset confirmado é persistido no próprio bot (e reforçado pelo
        transporte, que mantém o watermark do servidor), então chamadas
        sucessivas a run() nunca reprocessam updates já entregues.

        Args:
            interval:     Pausa entre polls (segundos).
            max_updates:  Se definido, para após processar N updates (testes);
                          com fila vazia e limite definido, retorna imediato.

        Returns:
            Número de updates processados nesta chamada.
        """
        processed = 0
        while not self._closed:
            try:
                updates = await self.transport.get_updates(self._offset)
            except TransportError:
                log.warn("Transporte indisponível — aguardando...")
                await asyncio.sleep(interval)
                continue
            if not updates:
                if max_updates is not None:
                    return processed
                await asyncio.sleep(interval)
                continue
            for update in updates:
                if self._closed:
                    return processed
                await self.handle_update(update)
                processed += 1
                # Telegram só confirma updates com update_id < offset: é
                # preciso enviar o PRÓXIMO id (último + 1), senão o servidor
                # reentrega o mesmo update para sempre (loop de respostas).
                self._offset = update.update_id + 1
                self._save_offset()
                if max_updates is not None and processed >= max_updates:
                    return processed
        return processed

    # -- Offset persistido ---------------------------------------------------

    def _load_offset(self) -> Optional[int]:
        """Lê o offset confirmado do arquivo (None se inexistente)."""
        if not self.offset_file:
            return None
        try:
            value = Path(self.offset_file).read_text(encoding="utf-8").strip()
            return int(value) if value else None
        except (OSError, ValueError):
            return None

    def _save_offset(self) -> None:
        """Persiste o próximo offset em arquivo (atômico)."""
        if not self.offset_file or self._offset is None:
            return
        try:
            path = Path(self.offset_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(str(self._offset), encoding="utf-8")
            tmp.replace(path)
        except OSError:  # pragma: no cover — sem permissão
            log.warn("Offset do bot não pôde ser salvo", path=self.offset_file)

    def close(self) -> None:
        self._closed = True
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()

    # ------------------------------------------------------------------
    # Introspecção
    # ------------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "transport": type(self.transport).__name__,
            "orchestrator": self.orchestrator is not None,
            "commands": [c.to_dict() for c in self.commands],
            "admins": sorted(self.admin_ids),
            "profiles": {str(k): v for k, v in self._profiles.items()},
            "metrics": self.metrics.snapshot(),
            "started_at": self.started_at,
        }

    @staticmethod
    def _chat_from_target(target: str) -> Union[int, str]:
        """/historico aceita chat numérico ou @handle — sem handle, vira id."""
        cleaned = target.lstrip("@")
        if cleaned.isdigit():
            return int(cleaned)
        return cleaned
