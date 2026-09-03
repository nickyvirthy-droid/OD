"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/audio/tts.py
Descrição: TTS (Fase 6, item 6.4) — síntese de voz local via Piper
           (binário compilado chamado por subprocess assíncrono). Voz por
           perfil: "regulus" usa voz masculina (faber); qualquer outro perfil
           usa a voz feminina padrão (dii) — espelhando o legado Nicky
           interfaces/text_to_speech.py.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/text_to_speech.py (Piper via subprocess, vozes por perfil)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.4 (tools/audio/tts.py)

Decisões registradas (ver CHANGELOG):
  - Binário Piper e vozes pt-BR REAIS do legado reaproveitados no servidor
    (piper + dii_pt-BR.onnx feminina, pt_BR-faber-medium.onnx masculina)
  - Nunca lança: qualquer falha retorna None/False (padrão das integrações OD)
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

log = get_logger("omega.tools.audio.tts")

DEFAULT_BINARY = "/home/alex/nicky/piper/piper/piper"
DEFAULT_MODEL = "/home/alex/nicky/piper/voices/dii_pt-BR.onnx"
DEFAULT_CONFIG = "/home/alex/nicky/piper/voices/dii_pt-BR.onnx.json"
REGULUS_MODEL = "/home/alex/nicky/piper/voices/pt_BR-faber-medium.onnx"
REGULUS_CONFIG = "/home/alex/nicky/piper/voices/pt_BR-faber-medium.onnx.json"


@dataclass(slots=True)
class TTSConfig:
    """Configuração da síntese via Piper."""

    binary: Union[str, Path] = DEFAULT_BINARY
    model: Union[str, Path] = DEFAULT_MODEL
    config: Union[str, Path] = DEFAULT_CONFIG
    regulus_model: Union[str, Path] = REGULUS_MODEL
    regulus_config: Union[str, Path] = REGULUS_CONFIG
    enabled: bool = True
    timeout_s: float = 60.0


class PiperTTS:
    """TTS local via Piper (subprocess assíncrono, sem estado)."""

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        self.config = config or TTSConfig()
        self._voice_map = {
            "default": (str(self.config.model), str(self.config.config)),
            "regulus": (str(self.config.regulus_model), str(self.config.regulus_config)),
        }
        if self.config.enabled:
            if not Path(self.config.binary).is_file():
                log.warn("Piper binário não encontrado", binary=str(self.config.binary))
            for name, (model_path, config_path) in self._voice_map.items():
                if not Path(model_path).is_file():
                    log.warn("Modelo Piper não encontrado", voice=name)
                if not Path(config_path).is_file():
                    log.warn("Config Piper não encontrada", voice=name)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def available(self) -> bool:
        """Binário + pelo menos a voz padrão presentes e habilitado."""
        if not self.config.enabled or not Path(self.config.binary).is_file():
            return False
        model, _ = self._voice_map["default"]
        return Path(model).is_file()

    def _resolve_voice(self, profile: Optional[str]) -> tuple[str, str]:
        """(model_path, config_path) para o perfil, com fallback para default."""
        key = (profile or "default").lower()
        return self._voice_map.get(key, self._voice_map["default"])

    async def synthesize_to_file(
        self,
        text: str,
        output_path: Union[str, Path],
        profile: Optional[str] = None,
    ) -> bool:
        """Sintetiza texto em WAV gravando em output_path. True em sucesso."""
        if not self.config.enabled:
            log.warn("TTS desabilitado (enabled=False)")
            return False
        if not text or not text.strip():
            log.warn("Texto vazio recebido para síntese")
            return False

        model_path, config_path = self._resolve_voice(profile)
        cmd = [
            str(self.config.binary),
            "--model", model_path,
            "--config", config_path,
            "--output_file", str(output_path),
        ]
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(input=text.encode("utf-8")),
                timeout=self.config.timeout_s,
            )
            elapsed = time.monotonic() - t0

            if proc.returncode != 0:
                log.error(
                    "Piper falhou",
                    returncode=proc.returncode,
                    elapsed_s=round(elapsed, 1),
                    stderr=stderr.decode(errors="ignore")[:300],
                )
                return False
            out = Path(output_path)
            if not out.is_file() or out.stat().st_size == 0:
                log.error("Piper não gerou arquivo de áudio válido")
                return False
            log.info(
                "Síntese TTS concluída",
                elapsed_s=round(elapsed, 2),
                bytes=out.stat().st_size,
            )
            return True
        except asyncio.TimeoutError:
            log.error("Piper timeout", timeout_s=self.config.timeout_s)
            return False
        except Exception as exc:  # pragma: no cover
            log.error("Piper exceção", error=str(exc))
            return False

    async def synthesize(
        self, text: str, profile: Optional[str] = None
    ) -> Optional[bytes]:
        """Ponto de entrada principal: retorna bytes do WAV (ou None)."""
        if not self.config.enabled:
            log.warn("TTS desabilitado (enabled=False)")
            return None
        if not text or not text.strip():
            return None
        try:
            with tempfile.TemporaryDirectory(prefix="od_tts_") as tmp_dir:
                out_path = Path(tmp_dir) / "speech.wav"
                ok = await self.synthesize_to_file(text, out_path, profile)
                if not ok:
                    return None
                return out_path.read_bytes()
        except Exception as exc:  # pragma: no cover
            log.error("TTS exceção", error=str(exc))
            return None

    # -- Introspecção --------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "available": self.available,
            "binary": str(self.config.binary),
            "voices": {k: v[0] for k, v in self._voice_map.items()},
        }