"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: tools/audio/
Descrição: Sensorial de áudio (Fase 6) — STT (6.3) via whisper.cpp e TTS
           (6.4) via Piper, ambos por subprocess assíncrono sem estado,
           espelhando o legado Nicky (vision/audio_capture.py e
           interfaces/text_to_speech.py).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - stt.py → WhisperSTT (transcrição whisper.cpp + ffmpeg)
  - tts.py → PiperTTS (síntese com vozes por perfil), EdgeTTSTTS (vozes
    Microsoft Neural via edge-tts, engine opcional de 28/10) e TTS
    (unificação com primário + fallback)
"""

from tools.audio.stt import STTConfig, WhisperSTT
from tools.audio.tts import EdgeTTSTTS, PiperTTS, TTS, TTSConfig

__signature__ = "OD // CORE"
__all__ = [
    "WhisperSTT",
    "STTConfig",
    "PiperTTS",
    "EdgeTTSTTS",
    "TTS",
    "TTSConfig",
]