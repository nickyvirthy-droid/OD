"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/telegram/voice.py
Descrição: Voz real no Telegram (v0.21.0) — adaptadores que ligam o pipeline
           de voz do bot (14º recurso) aos módulos reais da Fase 6:
           TelegramVoiceSTT (whisper.cpp via tools/audio/stt.py) transcreve
           áudio recebido (ogg/opus → WAV 16kHz via ffmpeg) e
           TelegramVoiceTTS (Piper via tools/audio/tts.py) sintetiza a
           resposta em voz por perfil (dii/faber).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - tools/audio/stt.py (6.3) e tools/audio/tts.py (6.4) — binários reais
  - integrations/telegram/bot.py (STTDecoder plugável, transporte)

Decisões registradas (ver CHANGELOG):
  - Ambos os adaptadores são async (o pipeline do bot é async); o decoder
    do bot aceita callables sync OU async
  - STT: bytes do Telegram gravados em arquivo temporário (.oga) e
    convertidos/transcritos pelo WhisperSTT (ffmpeg + whisper-cli)
  - TTS: resposta sintetizada em WAV (Piper) e enviada como voz; se a
    síntese falhar, o bot cai para resposta de texto (nunca silencia)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.telegram.voice")


class TelegramVoiceSTT:
    """Decodificador real: bytes de áudio → texto (whisper.cpp)."""

    def __init__(self, whisper: Any) -> None:
        self.whisper = whisper

    async def __call__(self, data: bytes) -> Optional[str]:
        if not data:
            return None
        try:
            with tempfile.TemporaryDirectory(prefix="od_tg_stt_") as tmp_dir:
                audio_path = Path(tmp_dir) / "voz.oga"
                audio_path.write_bytes(data)
                return await self.whisper.transcribe(audio_path)
        except Exception as exc:  # pragma: no cover — transcribe nunca lança
            log.error("STT Telegram exceção", error=str(exc))
            return None


class TelegramVoiceTTS:
    """Sintetizador real: texto → bytes de voz (Piper, voz por perfil)."""

    def __init__(self, piper: Any, profile: Optional[str] = None) -> None:
        self.piper = piper
        self.profile = profile

    async def __call__(self, text: str) -> Optional[bytes]:
        if not text or not text.strip():
            return None
        return await self.piper.synthesize(text, profile=self.profile)