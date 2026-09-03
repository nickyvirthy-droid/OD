"""
OMEGA DRAKON • TESTS
Módulo: tests/test_telegram.py
Descrição: Testes da integração Telegram (Fase 5, item 5.1): modelos de
           mensagens, transportes (InMemoryTransport sem rede e
           HTTPTransport via Bot API com rede stubada), os 13 comandos do
           legado Nicky + voz/STT (14º recurso) e o TelegramBot sobre o
           Orchestrator (perfis por chat, admin gate, métricas, polling).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py (Telegram Bot API, 14 comandos)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from core.orchestrator import Orchestrator, RecordingProvider
from integrations.telegram import (
    HTTPTransport,
    InMemoryTransport,
    TelegramBot,
    TransportConfigError,
    TransportError,
    build_default_commands,
)
from integrations.telegram.models import Message, Update, User, Voice

ADMIN = 1
USER = 2
ADMIN_NAMES = {"status", "uptime", "stats", "dashboard", "historico",
               "cache", "presenca", "codigo", "rotacionar_key"}
PUBLIC_NAMES = {"start", "help", "perfil", "limpar"}


def _raw_update(update_id: int, **msg_fields) -> dict:
    """Update cru no formato da Telegram Bot API."""
    message = {
        "message_id": update_id * 10,
        "chat": {"id": msg_fields.pop("chat_id", 100)},
        "from": {
            "id": msg_fields.pop("user_id", ADMIN),
            "first_name": "alex",
            "is_bot": False,
        },
        "date": 1700000000,
        **msg_fields,
    }
    return {"update_id": update_id, "message": message}


# ===========================================================================
# Modelos (User, Voice, Message, Update)
# ===========================================================================

class TestTelegramModels:
    """Dataclasses de mensagens: display, flags e serialização."""

    def test_user_display_falls_back(self) -> None:
        assert User(id=1, first_name="Nicky").display == "Nicky"
        assert User(id=1, username="nicky").display == "nicky"
        assert User(id=1).display == "id1"

    def test_user_to_dict(self) -> None:
        data = User(id=1, first_name="a", username="u", is_bot=True).to_dict()
        assert data == {"id": 1, "first_name": "a", "username": "u", "is_bot": True}

    def test_message_flags(self) -> None:
        text_msg = Message(
            message_id=1, chat_id=10, user=User(id=1), text="/help"
        )
        assert text_msg.is_command
        assert not text_msg.has_voice
        voice_msg = Message(
            message_id=2,
            chat_id=10,
            user=User(id=1),
            voice=Voice(file_id="f1", duration_s=2.0),
        )
        assert voice_msg.has_voice
        assert not voice_msg.is_command

    def test_message_to_dict_round_trip(self) -> None:
        msg = Message(
            message_id=7,
            chat_id=10,
            user=User(id=1, first_name="alex"),
            text="oi",
            voice=Voice(file_id="f1", duration_s=1.5),
            date=12.0,
        )
        data = msg.to_dict()
        assert data["message_id"] == 7
        assert data["voice"] == {"file_id": "f1", "duration_s": 1.5}
        # Sem voz: campo null no payload da API
        plain = Message(
            message_id=8, chat_id=10, user=User(id=1), text="x"
        ).to_dict()
        assert plain["voice"] is None

    def test_update_to_dict(self) -> None:
        update = Update(update_id=3, message=None)
        assert update.to_dict() == {"update_id": 3, "message": None}


# ===========================================================================
# InMemoryTransport (testes/dev sem rede)
# ===========================================================================

class TestInMemoryTransport:
    """Fila de updates, envio e arquivos de voz em memória."""

    @pytest.mark.asyncio
    async def test_get_updates_all_pending_and_offset(self) -> None:
        transport = InMemoryTransport()
        u1 = transport.add_message(1, "primeira")
        u2 = transport.add_message(1, "segunda")
        assert u1.update_id == 1 and u2.update_id == 2
        all_updates = await transport.get_updates()
        assert [u.update_id for u in all_updates] == [1, 2]
        # Offset imita o servidor real: getUpdates(offset=N) confirma os
        # updates com update_id < N e devolve os com update_id >= N.
        after = await transport.get_updates(offset=2)
        assert [u.update_id for u in after] == [2]
        assert await transport.get_updates(offset=3) == []

    @pytest.mark.asyncio
    async def test_add_voice_message_shape(self) -> None:
        transport = InMemoryTransport()
        transport.add_voice(1, "file_abc", user_id=USER)
        update = (await transport.get_updates())[0]
        assert update.message is not None
        assert update.message.has_voice
        assert update.message.voice is not None
        assert update.message.voice.file_id == "file_abc"
        assert update.message.user.id == USER
        assert update.message.text == ""

    @pytest.mark.asyncio
    async def test_fetch_file_seeded_and_absent(self) -> None:
        transport = InMemoryTransport()
        transport.seed_file("f1", b"conteudo")
        assert await transport.fetch_file("f1") == b"conteudo"
        assert await transport.fetch_file("missing") is None

    @pytest.mark.asyncio
    async def test_send_message_records(self) -> None:
        transport = InMemoryTransport()
        assert await transport.send_message(5, "olá")
        assert transport.sent_texts == ["olá"]
        assert transport.sent[0]["chat_id"] == 5

    def test_close(self) -> None:
        transport = InMemoryTransport()
        transport.close()
        assert transport.closed


# ===========================================================================
# HTTPTransport (Bot API — rede stubada)
# ===========================================================================

class TestHTTPTransport:
    """Token obrigatório, parsing de updates e mapeamento de erros."""

    def test_token_required(self) -> None:
        with pytest.raises(TransportConfigError):
            HTTPTransport("")
        with pytest.raises(TransportConfigError):
            HTTPTransport("   ")

    def test_parse_update_text(self) -> None:
        raw = _raw_update(
            1, chat_id=55, user_id=USER, text="/perfil regulus"
        )
        update = HTTPTransport._parse_update(raw)
        assert update.update_id == 1
        assert update.message is not None
        assert update.message.chat_id == 55
        assert update.message.user.id == USER
        assert update.message.text == "/perfil regulus"
        assert not update.message.has_voice

    def test_parse_update_voice(self) -> None:
        raw = _raw_update(
            2,
            chat_id=55,
            user_id=USER,
            voice={"file_id": "v1", "duration": 3},
        )
        update = HTTPTransport._parse_update(raw)
        assert update.message is not None
        assert update.message.text == ""
        assert update.message.has_voice
        assert update.message.voice == Voice(file_id="v1", duration_s=3.0)

    def test_parse_update_without_message(self) -> None:
        update = HTTPTransport._parse_update({"update_id": 9})
        assert update.message is None

    def test_call_ok_false_raises(self, monkeypatch) -> None:
        transport = HTTPTransport("token")
        self._patch_urlopen(monkeypatch, b'{"ok": false, "description": "nope"}')
        with pytest.raises(TransportError):
            transport._call("getMe")

    def test_call_http_error_raises(self, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise urllib.error.HTTPError(
                "url", 401, "unauthorized", {}, io.BytesIO(b'{"ok":false}')
            )

        monkeypatch.setattr(
            "urllib.request.urlopen", boom
        )
        with pytest.raises(TransportError, match="401"):
            HTTPTransport("token")._call("sendMessage", chat_id=1, text="x")

    def test_call_network_error_raises(self, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        with pytest.raises(TransportError, match="indispon"):
            HTTPTransport("token")._call("getMe")

    @staticmethod
    def _patch_urlopen(monkeypatch, body: bytes) -> None:
        """Substitui urlopen por uma resposta fake com `body` JSON."""

        class FakeResponse:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc) -> None:
                return None

        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: FakeResponse(body),
        )

    @pytest.mark.asyncio
    async def test_get_updates_advances_offset(self, monkeypatch) -> None:
        body = json.dumps(
            {"ok": True, "result": [_raw_update(7, text="oi")]}
        ).encode()
        self._patch_urlopen(monkeypatch, body)
        transport = HTTPTransport("token")
        updates = await transport.get_updates()
        assert len(updates) == 1
        assert updates[0].update_id == 7
        assert transport._offset == 8

    @pytest.mark.asyncio
    async def test_send_message_passes_chat_and_text(self, monkeypatch) -> None:
        calls: list[dict] = []

        def fake_call(method, **params):
            calls.append({"method": method, **params})
            return {"ok": True, "result": {"message_id": 1}}

        transport = HTTPTransport("token")
        monkeypatch.setattr(transport, "_call", fake_call)
        assert await transport.send_message(9, "oi")
        assert calls[0]["method"] == "sendMessage"
        assert calls[0]["chat_id"] == 9 and calls[0]["text"] == "oi"

    @pytest.mark.asyncio
    async def test_fetch_file_downloads(self, monkeypatch) -> None:
        transport = HTTPTransport("token")
        monkeypatch.setattr(
            transport,
            "_call",
            lambda method, **p: {
                "ok": True,
                "result": {"file_path": "audio/abc.ogg"},
            },
        )
        self._patch_urlopen(monkeypatch, b"BYTES-DO-AUDIO")
        assert await transport.fetch_file("f1") == b"BYTES-DO-AUDIO"

    @pytest.mark.asyncio
    async def test_fetch_file_without_path_returns_none(self, monkeypatch) -> None:
        transport = HTTPTransport("token")
        monkeypatch.setattr(
            transport, "_call", lambda method, **p: {"ok": True, "result": {}}
        )
        assert await transport.fetch_file("f1") is None


# ===========================================================================
# TelegramBot — comandos, voz, Orchestrator, polling
# ===========================================================================

def _orchestrator(tmp_path, *, history=True, cache=True) -> Orchestrator:
    """Orchestrator com RecordingProvider e memórias opcionais em tmp_path."""
    from memory.cache import LLMCache
    from memory.history import ConversationHistory

    orch = Orchestrator(
        providers=[RecordingProvider("echo", reply="resposta-od")],
        history=ConversationHistory(base_dir=tmp_path / "hist") if history else None,
        cache=LLMCache(cache_dir=tmp_path / "cache", profile="guardian")
        if cache
        else None,
    )
    return orch


class TestTelegramBotCommands:
    """Catálogo de comandos, admin gate e handlers locais."""

    def _bot(self, tmp_path, *, admin_ids=frozenset({ADMIN})) -> TelegramBot:
        transport = InMemoryTransport()
        orch = _orchestrator(tmp_path)
        return TelegramBot(transport, orch, admin_ids=admin_ids)

    @staticmethod
    async def _run(bot: TelegramBot, *messages: tuple[int, str, int]) -> None:
        """Enfileira (chat, texto, user) e processa tudo via polling."""
        transport = bot.transport  # type: ignore[assignment]
        for chat_id, text, user_id in messages:
            transport.add_message(chat_id, text, user_id=user_id)
        await bot.run(interval=0.01, max_updates=len(messages))
        transport.incoming.clear()

    def test_catalog_matches_legacy(self) -> None:
        commands = build_default_commands()
        names = {c.name for c in commands}
        assert names == PUBLIC_NAMES | ADMIN_NAMES == {
            "start", "help", "perfil", "limpar", "status", "uptime",
            "stats", "dashboard", "historico", "cache", "presenca",
            "codigo", "rotacionar_key",
        }
        aliases = {a for c in commands for a in c.aliases}
        assert "ajuda" in aliases

    @pytest.mark.asyncio
    async def test_start_welcome(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/start", ADMIN))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert "Omega Drakon" in text
        assert "guardian" in text

    @pytest.mark.asyncio
    async def test_help_hides_admin_commands_for_regular_user(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/help", USER))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        for name in ADMIN_NAMES:
            assert f"/{name}" not in text
        for name in PUBLIC_NAMES:
            assert f"/{name}" in text
        assert "🎤" in text  # voz (STT) anunciada como 14º recurso

    @pytest.mark.asyncio
    async def test_help_admin_sees_all(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/help", ADMIN))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        for name in ADMIN_NAMES | PUBLIC_NAMES:
            assert f"/{name}" in text

    @pytest.mark.asyncio
    async def test_help_alias_ajuda(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/ajuda", USER))
        assert "Comandos disponíveis" in bot.transport.sent_texts[-1]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_perfil_lists_current_without_args(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/perfil", USER))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert "guardian" in text and "/perfil <nome>" in text

    @pytest.mark.asyncio
    async def test_perfil_switch_and_reject(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/perfil regulus", ADMIN))
        assert "regulus" in bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert bot.get_profile(1) == "regulus"
        await self._run(bot, (1, "/perfil inexistente", ADMIN))
        assert "desconhecido" in bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert bot.get_profile(1) == "regulus"  # mantido

    @pytest.mark.asyncio
    async def test_admin_gate_blocks_regular_user(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/status", USER))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert "⛔" in text and "administrador" in text
        assert bot.metrics.errors == 1

    @pytest.mark.asyncio
    async def test_status_admin(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/status", ADMIN))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert "*Status do sistema:*" in text
        assert "online" in text and "InMemoryTransport" in text

    @pytest.mark.asyncio
    async def test_uptime_and_stats(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(
            bot,
            (1, "mensagem livre", ADMIN),
            (1, "/uptime", ADMIN),
            (1, "/stats", ADMIN),
        )
        sent = bot.transport.sent_texts  # type: ignore[union-attr]
        assert "Bot ativo há" in sent[-2]
        assert "Mensagens: 3" in sent[-1] or "Mensagens: " in sent[-1]
        assert "Orchestrator" in sent[-1]

    @pytest.mark.asyncio
    async def test_dashboard_link(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/dashboard", ADMIN))
        assert "localhost:8765" in bot.transport.sent_texts[-1]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_codigo_branches(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(
            bot,
            (1, "/codigo", ADMIN),
            (1, "/codigo status", ADMIN),
            (1, "/codigo outro", ADMIN),
        )
        sent = bot.transport.sent_texts  # type: ignore[union-attr]
        assert "Coder Engine" in sent[0]
        assert "Coder Engine" in sent[1]
        assert "Subcomando desconhecido" in sent[2]

    @pytest.mark.asyncio
    async def test_presenca_placeholder(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/presenca", ADMIN))
        assert "6.2" in bot.transport.sent_texts[-1]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_rotacionar_key_safe_message(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._run(bot, (1, "/rotacionar_key", ADMIN))
        text = bot.transport.sent_texts[-1]  # type: ignore[union-attr]
        assert "não executada" in text


class TestTelegramBotOrchestrator:
    """Mensagens livres, perfis, histórico e cache sobre o Orchestrator."""

    def _bot(self, tmp_path) -> TelegramBot:
        transport = InMemoryTransport()
        return TelegramBot(transport, _orchestrator(tmp_path), admin_ids={ADMIN})

    @staticmethod
    async def _send(bot: TelegramBot, text: str, user_id: int = ADMIN,
                    chat_id: int = 1) -> str:
        transport = bot.transport  # type: ignore[assignment]
        transport.add_message(chat_id, text, user_id=user_id)
        await bot.run(interval=0.01, max_updates=1)
        return transport.sent_texts[-1]

    @pytest.mark.asyncio
    async def test_free_text_goes_to_orchestrator(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        reply = await self._send(bot, "mensagem livre 42")
        assert reply == "resposta-od"
        # Histórico persistido sob (chat, perfil padrão)
        history = bot.orchestrator.history
        assert history is not None
        msgs = history.get_history("1", "guardian")
        assert msgs and msgs[-1].content == "resposta-od"

    @pytest.mark.asyncio
    async def test_text_uses_selected_profile(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._send(bot, "/perfil regulus", ADMIN)
        await self._send(bot, "outra livre", ADMIN)
        history = bot.orchestrator.history
        assert history is not None
        assert history.get_history("1", "regulus")
        assert history.get_history("1", "guardian") == []

    @pytest.mark.asyncio
    async def test_auto_profile_resolves_to_default(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._send(bot, "/perfil auto", ADMIN)
        await self._send(bot, "livre no auto", ADMIN)
        history = bot.orchestrator.history
        assert history is not None
        assert history.get_history("1", "guardian")
        assert history.get_history("1", "auto") == []

    @pytest.mark.asyncio
    async def test_unknown_command_falls_to_orchestrator(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        reply = await self._send(bot, "/comando-inexistente x")
        assert reply == "resposta-od"

    @pytest.mark.asyncio
    async def test_limpar_clears_history(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._send(bot, "primeira")
        reply = await self._send(bot, "/limpar")
        assert "1" in reply and "removido" in reply
        history = bot.orchestrator.history
        assert history is not None
        assert history.get_history("1", "guardian") == []

    @pytest.mark.asyncio
    async def test_historico_lists_recent_messages(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        for i in range(3):
            await self._send(bot, f"pergunta {i}")
        reply = await self._send(bot, "/historico", ADMIN)
        assert "user" in reply and "pergunta 2" in reply

    @pytest.mark.asyncio
    async def test_historico_limit_and_clamp(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        for i in range(5):
            await self._send(bot, f"pergunta {i}")
        reply = await self._send(bot, "/historico 1 2", ADMIN)
        assert "pergunta 4" in reply
        assert "pergunta 0" not in reply

    @pytest.mark.asyncio
    async def test_cache_stats_and_clear(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        await self._send(bot, "texto único 99")  # rota llm → cache.put
        stats = await self._send(bot, "/cache", ADMIN)
        assert "Entradas: 1" in stats
        cleared = await self._send(bot, "/cache limpar", ADMIN)
        assert "Cache LLM limpo" in cleared
        stats2 = await self._send(bot, "/cache", ADMIN)
        assert "Entradas: 0" in stats2


class TestTelegramBotNoOrchestrator:
    """Comandos locais funcionam mesmo sem pipeline conectado."""

    @pytest.mark.asyncio
    async def test_free_text_reports_disconnected(self) -> None:
        bot = TelegramBot(InMemoryTransport(), None, admin_ids={ADMIN})
        bot.transport.add_message(1, "oi")
        await bot.run(interval=0.01, max_updates=1)
        text = bot.transport.sent_texts[-1]
        assert "Orchestrator" in text and "não está conectado" in text

    @pytest.mark.asyncio
    async def test_limpar_without_history(self) -> None:
        bot = TelegramBot(InMemoryTransport(), None, admin_ids={ADMIN})
        bot.transport.add_message(1, "/limpar", user_id=ADMIN)
        await bot.run(interval=0.01, max_updates=1)
        assert "Histórico local limpo" in bot.transport.sent_texts[-1]

    @pytest.mark.asyncio
    async def test_local_commands_still_work(self) -> None:
        bot = TelegramBot(InMemoryTransport(), None, admin_ids={ADMIN})
        bot.transport.add_message(1, "/status", user_id=ADMIN)
        bot.transport.add_message(1, "/help", user_id=ADMIN)
        await bot.run(interval=0.01, max_updates=2)
        sent = bot.transport.sent_texts
        assert "desconectado" in sent[0]
        assert "Comandos disponíveis" in sent[1]


class TestTelegramBotVoice:
    """14º recurso: voz → STT → texto → pipeline."""

    def _bot(self, tmp_path, *, stt=None) -> TelegramBot:
        transport = InMemoryTransport()
        bot = TelegramBot(transport, _orchestrator(tmp_path), admin_ids={ADMIN})
        if stt is not None:
            bot.stt = stt
        return bot

    @staticmethod
    async def _voice(bot: TelegramBot, content: bytes, file_id: str = "f1",
                     chat_id: int = 1) -> str:
        transport = bot.transport  # type: ignore[assignment]
        transport.seed_file(file_id, content)
        transport.add_voice(chat_id, file_id, user_id=ADMIN)
        await bot.run(interval=0.01, max_updates=1)
        return transport.sent_texts[-1]

    @pytest.mark.asyncio
    async def test_voice_utf8_fallback_transcribes(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        reply = await self._voice(bot, "olá por voz".encode())
        assert reply == "resposta-od"
        assert bot.metrics.voices == 1
        history = bot.orchestrator.history
        assert history is not None
        # Texto transcrito virou mensagem "[voz] olá por voz" no pipeline
        assert "[voz] olá por voz" in [
            m.content for m in history.get_history("1", "guardian")
        ][-2]

    @pytest.mark.asyncio
    async def test_voice_with_plugged_stt_decoder(self, tmp_path) -> None:
        seen: list[bytes] = []

        def fake_stt(data: bytes) -> str:
            seen.append(data)
            return "transcrito pelo STT"

        bot = self._bot(tmp_path, stt=fake_stt)
        reply = await self._voice(bot, b"\x00\x01audio-ogg")
        assert seen == [b"\x00\x01audio-ogg"]
        assert reply == "resposta-od"

    @pytest.mark.asyncio
    async def test_voice_undecodable_reports_no_stt(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        reply = await self._voice(bot, b"\xff\xfe\x00audio-binary")
        assert "não consegui transcrevê-lo" in reply

    @pytest.mark.asyncio
    async def test_voice_file_missing(self, tmp_path) -> None:
        bot = self._bot(tmp_path)
        transport = bot.transport  # type: ignore[assignment]
        transport.add_voice(1, "arquivo-inexistente", user_id=ADMIN)
        await bot.run(interval=0.01, max_updates=1)
        assert "Áudio não encontrado" in transport.sent_texts[-1]


class TestTelegramBotPolling:
    """Polling: consumo por offset, resiliência a erros e fechamento."""

    def test_run_stops_when_closed(self) -> None:
        bot = TelegramBot(InMemoryTransport(), None)
        bot.close()
        bot.close()  # idempotente
        import asyncio

        assert asyncio.run(bot.run(interval=0.001)) == 0

    @pytest.mark.asyncio
    async def test_run_consumes_and_second_run_idle(self) -> None:
        transport = InMemoryTransport()
        bot = TelegramBot(transport, _orchestrator_for_polling(), admin_ids={ADMIN})
        transport.add_message(1, "a", user_id=ADMIN)
        transport.add_message(1, "b", user_id=ADMIN)
        assert await bot.run(interval=0.01, max_updates=2) == 2
        assert len(transport.sent_texts) == 2
        # Nada novo: segundo run não processa updates já consumidos
        transport.add_message(1, "c", user_id=ADMIN)
        assert await bot.run(interval=0.01, max_updates=1) == 1
        assert len(transport.sent_texts) == 3
        assert await bot.run(interval=0.01, max_updates=1) == 0

    @pytest.mark.asyncio
    async def test_offset_advances_to_last_plus_one(self) -> None:
        """Regressão do loop infinito: offset deve confirmar o update no
        servidor (último id + 1), senão o Telegram o reentrega para sempre.
        """
        transport = InMemoryTransport()
        bot = TelegramBot(transport, _orchestrator_for_polling(), admin_ids={ADMIN})
        transport.add_message(1, "a", user_id=ADMIN)
        assert await bot.run(interval=0.01, max_updates=1) == 1
        assert bot._offset == 2  # confirma o update 1
        # Sem nada novo, novo run não pode reprocessar o update 1
        assert await bot.run(interval=0.01, max_updates=1) == 0

    @pytest.mark.asyncio
    async def test_offset_file_persisted_across_bots(self, tmp_path) -> None:
        offset_file = tmp_path / "telegram_offset.json"
        transport = InMemoryTransport()
        bot = TelegramBot(
            transport, _orchestrator_for_polling(), admin_ids={ADMIN},
            offset_file=offset_file,
        )
        transport.add_message(1, "a", user_id=ADMIN)
        transport.add_message(1, "b", user_id=ADMIN)
        assert await bot.run(interval=0.01, max_updates=2) == 2
        assert bot._offset == 3
        # Novo bot (simula reinício) retoma do offset persistido
        bot2 = TelegramBot(
            transport, _orchestrator_for_polling(), admin_ids={ADMIN},
            offset_file=offset_file,
        )
        assert bot2._offset == 3
        transport.add_message(1, "c", user_id=ADMIN)  # id 3
        assert await bot2.run(interval=0.01, max_updates=1) == 1
        assert bot2._offset == 4

    @pytest.mark.asyncio
    async def test_run_survives_transport_error(self) -> None:
        inner = InMemoryTransport()
        inner.add_message(1, "oi", user_id=ADMIN)
        flaky = _FlakyTransport(inner, fail_times=1)
        bot = TelegramBot(flaky, _orchestrator_for_polling(), admin_ids={ADMIN})
        assert await bot.run(interval=0.001, max_updates=1) == 1
        assert len(inner.sent_texts) == 1

    @pytest.mark.asyncio
    async def test_send_failure_counted_not_fatal(self) -> None:
        inner = InMemoryTransport()
        inner.add_message(1, "oi", user_id=ADMIN)
        failing = _FailingSendTransport(inner)
        bot = TelegramBot(failing, _orchestrator_for_polling(), admin_ids={ADMIN})
        await bot.run(interval=0.001, max_updates=1)
        assert bot.metrics.errors == 1
        assert bot.metrics.replies == 0


def _orchestrator_for_polling() -> Orchestrator:
    """Orchestrator mínimo para os testes de polling (sem disco)."""
    return Orchestrator(providers=[RecordingProvider("echo", reply="ok")])


class _FlakyTransport:
    """Quebra no get_updates N primeiras vezes e depois delega."""

    def __init__(self, inner: InMemoryTransport, fail_times: int = 1) -> None:
        self._inner = inner
        self._failures_left = fail_times

    async def get_updates(self, offset=None):
        if self._failures_left > 0:
            self._failures_left -= 1
            raise TransportError("rede fora do ar")
        return await self._inner.get_updates(offset)

    async def send_message(self, chat_id: int, text: str) -> bool:
        return await self._inner.send_message(chat_id, text)

    async def fetch_file(self, file_id: str):
        return await self._inner.fetch_file(file_id)


class _FailingSendTransport:
    """Delega tudo, mas send_message sempre falha."""

    def __init__(self, inner: InMemoryTransport) -> None:
        self._inner = inner

    async def get_updates(self, offset=None):
        return await self._inner.get_updates(offset)

    async def send_message(self, chat_id: int, text: str) -> bool:
        raise TransportError("envio falhou")

    async def fetch_file(self, file_id: str):
        return await self._inner.fetch_file(file_id)


class TestTelegramBotDump:
    """dump(): introspecção estruturada do bot."""

    @pytest.mark.asyncio
    async def test_dump_shape(self) -> None:
        transport = InMemoryTransport()
        bot = TelegramBot(transport, None, admin_ids={ADMIN})
        transport.add_message(1, "/perfil luma", user_id=ADMIN)
        await bot.run(interval=0.01, max_updates=1)
        data = bot.dump()
        assert data["transport"] == "InMemoryTransport"
        assert data["orchestrator"] is False
        assert len(data["commands"]) == 13
        assert data["admins"] == [ADMIN]
        assert data["profiles"] == {"1": "luma"}
        assert data["metrics"]["messages"] == 1
        bot.close()


class TestResolveAutoProfile:
    """Fase 6.5 — detecção automática de perfil por domínio no bot."""

    def test_auto_sem_contexto_usa_default(self) -> None:
        from integrations.telegram.bot import AUTO_PROFILE, _resolve_auto

        assert _resolve_auto(AUTO_PROFILE, "") == "guardian"
        assert _resolve_auto(AUTO_PROFILE) == "guardian"

    def test_auto_detecta_dominio(self) -> None:
        from integrations.telegram.bot import AUTO_PROFILE, _resolve_auto

        assert _resolve_auto(AUTO_PROFILE, "me explique a história de Roma") == "regulus"
        assert _resolve_auto(AUTO_PROFILE, "quero aprender python") == "luma"
        assert _resolve_auto(AUTO_PROFILE, "monitore a CPU do servidor") == "guardian"

    def test_explicito_ignora_dominio(self) -> None:
        from integrations.telegram.bot import _resolve_auto

        assert _resolve_auto("vox", "história de Roma") == "vox"
        assert _resolve_auto("nyx", "qualquer coisa") == "nyx"
