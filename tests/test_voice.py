"""
OMEGA DRAKON • TESTS
Módulo: tests/test_voice.py
Descrição: Testes dos adaptadores de voz do Telegram (integrations/telegram/
           voice.py, v0.21.0) — TelegramVoiceSTT (whisper.cpp via
           tools/audio/stt.py) e TelegramVoiceTTS (Piper via tools/audio/
           tts.py): chamada com dados vazios, delegação ao engine real e
           propagação do perfil de voz.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/telegram/voice.py (TelegramVoiceSTT, TelegramVoiceTTS)
  - runtime/launcher.py (montagem com WhisperSTT/Piper reais)
"""

from __future__ import annotations

import pytest

from integrations.telegram.voice import TelegramVoiceSTT, TelegramVoiceTTS


class _FakeWhisper:
    """Engine STT fake: registra o path recebido e devolve transcrição."""

    def __init__(self) -> None:
        self.calls: list = []

    async def transcribe(self, audio_path):
        self.calls.append(audio_path)
        return "olá, aqui é a nicky"


class _FakePiper:
    """Engine TTS fake: registra (texto, perfil) e devolve áudio."""

    def __init__(self) -> None:
        self.calls: list = []

    async def synthesize(self, text, profile=None):
        self.calls.append((text, profile))
        return b"RIFF\x00\x00audio"


class TestTelegramVoiceSTT:
    """Bytes de áudio do Telegram → texto (whisper.cpp)."""

    @pytest.mark.asyncio
    async def test_dados_vazios_nao_chama_whisper(self) -> None:
        whisper = _FakeWhisper()
        stt = TelegramVoiceSTT(whisper)
        assert await stt(b"") is None
        assert whisper.calls == []

    @pytest.mark.asyncio
    async def test_audio_gravado_e_transcrito(self) -> None:
        whisper = _FakeWhisper()
        stt = TelegramVoiceSTT(whisper)
        result = await stt(b"\x1aE\xdf\xa3ogg data fake")
        assert result == "olá, aqui é a nicky"
        assert len(whisper.calls) == 1
        path = whisper.calls[0]
        assert path.name == "voz.oga"  # .oga temporário escrito antes da STT


class TestTelegramVoiceTTS:
    """Texto → bytes de voz (Piper, voz por perfil)."""

    @pytest.mark.asyncio
    async def test_texto_vazio_nao_chama_piper(self) -> None:
        piper = _FakePiper()
        tts = TelegramVoiceTTS(piper)
        assert await tts("") is None
        assert await tts("   \n ") is None
        assert piper.calls == []

    @pytest.mark.asyncio
    async def test_sintese_delega_ao_piper(self) -> None:
        piper = _FakePiper()
        tts = TelegramVoiceTTS(piper)
        assert await tts("resposta em voz") == b"RIFF\x00\x00audio"
        assert piper.calls == [("resposta em voz", None)]

    @pytest.mark.asyncio
    async def test_perfil_de_voz_propagado(self) -> None:
        piper = _FakePiper()
        tts = TelegramVoiceTTS(piper, profile="nexus")
        await tts("conectando a plêiade")
        assert piper.calls == [("conectando a plêiade", "nexus")]
