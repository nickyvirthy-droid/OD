"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/audio/stt.py
Descrição: Audio Capture / STT (Fase 6, item 6.3) — transcrição local de
           áudio via whisper.cpp (binário compilado chamado por subprocess
           assíncrono). Converte qualquer áudio de entrada (ogg/opus/mp3/wav)
           para WAV 16kHz mono via ffmpeg antes de repassar ao whisper-cli,
           que exige esse formato. Não mantém estado entre chamadas (modelo
           não fica residente em RAM — importante dado o orçamento do
           servidor), espelhando o legado Nicky vision/audio_capture.py.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky vision/audio_capture.py (whisper.cpp via subprocess + ffmpeg)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.3 (tools/audio/stt.py)

Decisões registradas (ver CHANGELOG):
  - Binário e modelo REAIS do legado reaproveitados no servidor
    (whisper-cli compilado + ggml-base.bin) — nenhum download novo
  - Execução por subprocess async: modelo não ocupa RAM residente
  - Nunca lança: qualquer falha retorna None (padrão das integrações OD)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.tools.audio.stt")

DEFAULT_BINARY = "/home/alex/nicky/whisper.cpp/build/bin/whisper-cli"
DEFAULT_MODEL = "/home/alex/nicky/whisper.cpp/models/ggml-base.bin"
DEFAULT_FFMPEG = "/usr/bin/ffmpeg"
DEFAULT_LANGUAGE = "pt"


@dataclass(slots=True)
class STTConfig:
    """Configuração da transcrição via whisper.cpp."""

    binary: Union[str, Path] = DEFAULT_BINARY
    model: Union[str, Path] = DEFAULT_MODEL
    ffmpeg: Union[str, Path] = DEFAULT_FFMPEG
    language: str = DEFAULT_LANGUAGE
    threads: int = 4
    enabled: bool = True
    convert_timeout_s: float = 30.0
    transcribe_timeout_s: float = 120.0


class WhisperSTT:
    """STT local via whisper.cpp (subprocess assíncrono, sem estado)."""

    def __init__(self, config: Optional[STTConfig] = None) -> None:
        self.config = config or STTConfig()
        if self.config.enabled:
            if not Path(self.config.binary).is_file():
                log.warn("whisper.cpp binário não encontrado", binary=str(self.config.binary))
            if not Path(self.config.model).is_file():
                log.warn("Modelo whisper não encontrado", model=str(self.config.model))

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def available(self) -> bool:
        """Binário + modelo presentes e habilitado."""
        return (
            self.config.enabled
            and Path(self.config.binary).is_file()
            and Path(self.config.model).is_file()
        )

    # -- Conversão -----------------------------------------------------------

    async def _convert_to_wav(self, input_path: Path, wav_path: Path) -> bool:
        """Converte qualquer áudio para WAV 16kHz mono via ffmpeg."""
        cmd = [
            str(self.config.ffmpeg), "-y", "-i", str(input_path),
            "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.convert_timeout_s
            )
            if proc.returncode != 0:
                log.error(
                    "ffmpeg falhou",
                    returncode=proc.returncode,
                    stderr=stderr.decode(errors="ignore")[:300],
                )
                return False
            return True
        except asyncio.TimeoutError:
            log.error("ffmpeg timeout na conversão de áudio")
            return False
        except Exception as exc:  # pragma: no cover
            log.error("ffmpeg exceção", error=str(exc))
            return False

    # -- Transcrição ---------------------------------------------------------

    async def transcribe_wav(self, wav_path: Path) -> Optional[str]:
        """Transcreve um WAV 16kHz mono pronto via whisper-cli."""
        if not self.config.enabled:
            log.warn("Transcrição desabilitada (enabled=False)")
            return None

        cmd = [
            str(self.config.binary),
            "-m", str(self.config.model),
            "-f", str(wav_path),
            "-l", self.config.language,
            "-t", str(self.config.threads),
            "-nt",              # sem timestamps
            "-otxt",            # gera arquivo .txt ao lado do wav
            "-of", str(wav_path.with_suffix("")),
        ]
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.transcribe_timeout_s
            )
            elapsed = time.monotonic() - t0

            if proc.returncode != 0:
                log.error(
                    "whisper.cpp falhou",
                    returncode=proc.returncode,
                    elapsed_s=round(elapsed, 1),
                    stderr=stderr.decode(errors="ignore")[:300],
                )
                return None

            txt_path = wav_path.with_suffix(".txt")
            if not txt_path.exists():
                log.error("whisper.cpp não gerou arquivo .txt esperado")
                return None

            text = txt_path.read_text(encoding="utf-8").strip()
            if not text:
                log.warn("Transcrição vazia (silêncio?)", elapsed=round(elapsed, 1))
                return None
            log.info(
                "Transcrição concluída",
                elapsed_s=round(elapsed, 1),
                chars=len(text),
            )
            return text
        except asyncio.TimeoutError:
            log.error(
                "whisper.cpp timeout",
                timeout_s=self.config.transcribe_timeout_s,
            )
            return None
        except Exception as exc:  # pragma: no cover
            log.error("whisper.cpp exceção", error=str(exc))
            return None

    async def transcribe(
        self, audio_path: Union[str, Path]
    ) -> Optional[str]:
        """Ponto de entrada: converte + transcreve. Retorna texto ou None."""
        if not self.config.enabled:
            log.warn("Transcrição desabilitada (enabled=False)")
            return None
        input_path = Path(audio_path)
        if not input_path.is_file():
            log.error("Áudio não encontrado", path=str(input_path))
            return None

        try:
            with tempfile.TemporaryDirectory(prefix="od_stt_") as tmp_dir:
                tmp = Path(tmp_dir)
                wav_path = tmp / "audio.wav"
                if not await self._convert_to_wav(input_path, wav_path):
                    return None
                if not wav_path.is_file() or wav_path.stat().st_size == 0:
                    log.error("Conversão não gerou WAV válido")
                    return None
                return await self.transcribe_wav(wav_path)
        except Exception as exc:  # pragma: no cover
            log.error("STT exceção", error=str(exc))
            return None

    # -- Introspecção --------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "available": self.available,
            "binary": str(self.config.binary),
            "model": str(self.config.model),
            "language": self.config.language,
            "threads": self.config.threads,
        }