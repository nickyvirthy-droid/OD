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
  - analise/Nicky Locutor/ (integração 27/10: vozes extras + cadeia de
    locução de rádio — ver CHANGELOG)

Decisões registradas (ver CHANGELOG):
  - Binário Piper e vozes pt-BR REAIS do legado reaproveitados no servidor
    (piper + dii_pt-BR.onnx feminina, pt_BR-faber-medium.onnx masculina)
  - Nunca lança: qualquer falha retorna None/False (padrão das integrações OD)
  - Auto-descoberta de vozes (27/10): todo par *.onnx + *.onnx.json em
    voice/tts/ vira voz nomeada (ex.: "hal", "pt_BR-jeff-medium") — o
    Nicky Locutor trazia 9 vozes; default/regulus nunca são sobrescritas
  - Cadeia de locução de rádio (27/10): synthesize_locucao_to_file() aplica
    o mesmo tratamento do Nicky Locutor (EQ de presença + compand + 2,5 s
    antes da fala + ruído branco de fundo → MP3 128k) — o OD fala com a
    mesma "pele" da rádio
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

DEFAULT_BINARY = "/home/alex/OmegaDrakon/voice/tts/piper"
DEFAULT_MODEL = "/home/alex/OmegaDrakon/voice/tts/dii_pt-BR.onnx"
DEFAULT_CONFIG = "/home/alex/OmegaDrakon/voice/tts/dii_pt-BR.onnx.json"
REGULUS_MODEL = "/home/alex/OmegaDrakon/voice/tts/pt_BR-faber-medium.onnx"
REGULUS_CONFIG = "/home/alex/OmegaDrakon/voice/tts/pt_BR-faber-medium.onnx.json"
#: Diretório das vozes Piper (auto-descoberta — Etapa A da integração do
#: Nicky Locutor, 27/10): qualquer par *.onnx + *.onnx.json daqui vira voz
#: nomeada acessível via profile (ex.: "hal", "pt_BR-jeff-medium").
VOICES_DIR = "/home/alex/OmegaDrakon/voice/tts"
#: Catálogo de descrições das vozes (nome.onnx - descrição, por linha) —
#: vem do legado Nicky Locutor (000.txt do nicky-locutor).
VOZES_CATALOGO = "/home/alex/OmegaDrakon/voice/tts/CATALOGO_VOZES.txt"
#: Cadeia de locução de rádio (ffmpeg): equalizador de presença + companding
#: de voz falada + 2,5 s de silêncio antes da fala + fundo de ruído branco
#: quase inaudível (15 s, cortado no fim da fala) → MP3 128k estéreo 44,1 kHz.
#: Linha a linha do nicky-locutor (main.py) — o ecossistema inteiro fala com
#: a mesma "pele" de rádio.
FFMPEG_BIN = "/usr/bin/ffmpeg"
LOCUCAO_DELAY_MS = 2500
LOCUCAO_RUIDO_S = 15
LOCUCAO_FILTER = (
    "equalizer=f=80:width_type=h:width=100:g=3,"
    "equalizer=f=8000:width_type=h:width=1000:g=2,"
    "compand=attacks=0.3:decays=0.8:points=-90/-60|-20/-12|0/-7|20/-7:gain=2,"
    "adelay={delay}|{delay},apad=pad_dur=3[a1]"
)
#: Dados do espeak-ng (fonemização) — o piper exige `--espeak_data` quando o
#: diretório não está no padrão do sistema (/usr/share/espeak-ng-data). Deploy
#: OD: /opt/omegadrakon/voice/espeak-ng-data. Vazio = flag omitida (piper
#: usa o default do sistema).
DEFAULT_ESPEAK_DATA = "/opt/omegadrakon/voice/espeak-ng-data"


@dataclass(slots=True)
class TTSConfig:
    """Configuração da síntese via Piper."""

    binary: Union[str, Path] = DEFAULT_BINARY
    model: Union[str, Path] = DEFAULT_MODEL
    config: Union[str, Path] = DEFAULT_CONFIG
    regulus_model: Union[str, Path] = REGULUS_MODEL
    regulus_config: Union[str, Path] = REGULUS_CONFIG
    espeak_data: Union[str, Path, None] = DEFAULT_ESPEAK_DATA
    #: Diretório da auto-descoberta de vozes (None = só default/regulus).
    voices_dir: Union[str, Path, None] = VOICES_DIR
    #: ffmpeg da cadeia de locução de rádio (None = locução indisponível).
    ffmpeg_bin: Union[str, Path, None] = FFMPEG_BIN
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
        self._descobrir_vozes()
        if self.config.enabled:
            if not Path(self.config.binary).is_file():
                log.warn("Piper binário não encontrado", binary=str(self.config.binary))
            for name, (model_path, config_path) in self._voice_map.items():
                if not Path(model_path).is_file():
                    log.warn("Modelo Piper não encontrado", voice=name)
                if not Path(config_path).is_file():
                    log.warn("Config Piper não encontrada", voice=name)

    def _descobrir_vozes(self) -> None:
        """Auto-descobre vozes em voices_dir (par *.onnx + *.onnx.json).

        Vozes explícitas (default/regulus) NUNCA são sobrescritas — a
        descoberta só acrescenta. Nome da voz = nome do arquivo sem ".onnx"
        (ex.: "hal", "pt_BR-jeff-medium"), que é como o legado Nicky
        Locutor as chamava no locutor.txt.
        """
        directory = self.config.voices_dir
        if not directory:
            return
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return
        for onnx in sorted(dir_path.glob("*.onnx")):
            cfg = onnx.with_name(onnx.name + ".json")
            if not cfg.is_file():
                continue
            nome = onnx.stem
            if nome in self._voice_map:
                continue
            self._voice_map[nome] = (str(onnx), str(cfg))

    @property
    def vozes(self) -> dict[str, str]:
        """Nomes das vozes disponíveis (nome -> path do modelo)."""
        return {k: v[0] for k, v in self._voice_map.items()}

    def catalogo_vozes(self) -> dict[str, str]:
        """Descrições das vozes lidas do catálogo do legado (se existir)."""
        caminho = Path(VOZES_CATALOGO)
        descricoes: dict[str, str] = {}
        if not caminho.is_file():
            return descricoes
        try:
            for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
                if " - " not in linha:
                    continue
                nome, desc = linha.split(" - ", 1)
                descricoes[nome.strip()] = desc.strip()
        except OSError as exc:
            log.warn("Catálogo de vozes ilegível", error=str(exc))
        return descricoes

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

    def _piper_env(self) -> dict[str, str]:
        """Environment para o subprocesso do Piper com LD_LIBRARY_PATH correto."""
        import os
        env = os.environ.copy()
        # Garante LD_LIBRARY_PATH apontando para as libs do Piper (deploy /opt ou repo)
        for candidato in (
            "/opt/omegadrakon/voice/piper",
            str(Path(__file__).resolve().parent.parent.parent / "voice" / "tts"),
        ):
            if Path(candidato, "libpiper_phonemize.so.1").is_file():
                env["LD_LIBRARY_PATH"] = candidato
                break
        return env

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
            # Fonemização: o piper morre com 'Error processing phontab' quando
            # os dados do espeak-ng não estão no default do sistema — flag
            # explícita ANTES do --output_file, que segue sendo o último arg
            # (contrato usado por testes e por quem parseia a linha).
        ]
        if self.config.espeak_data and Path(self.config.espeak_data).is_dir():
            cmd += ["--espeak_data", str(self.config.espeak_data)]
        cmd += [
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
                env=self._piper_env(),
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

    # -- Locução de rádio (cadeia do Nicky Locutor) --------------------------

    @property
    def locucao_disponivel(self) -> bool:
        """Piper + ffmpeg presentes (a cadeia de rádio exige os dois)."""
        return (
            self.available
            and bool(self.config.ffmpeg_bin)
            and Path(str(self.config.ffmpeg_bin)).is_file()
        )

    def _comando_locucao(self, wav_in: Path, mp3_out: Path) -> list[str]:
        """Linha do ffmpeg da locução: EQ de presença, compand de voz falada,
        2,5 s antes da fala e fundo de ruído branco quase inaudível."""
        delay = str(LOCUCAO_DELAY_MS)
        filtro = LOCUCAO_FILTER.format(delay=delay)
        return [
            str(self.config.ffmpeg_bin),
            "-y", "-loglevel", "error",
            "-i", str(wav_in),
            "-f", "lavfi",
            "-i", f"anoisesrc=d={LOCUCAO_RUIDO_S}:c=white:amplitude=0.0001",
            "-filter_complex", f"[0:a]{filtro}; [a1][1:a]amix=inputs=2:duration=first",
            "-ar", "44100", "-ac", "2", "-b:a", "128k",
            str(mp3_out),
        ]

    async def synthesize_locucao_to_file(
        self,
        text: str,
        output_path: Union[str, Path],
        profile: Optional[str] = None,
    ) -> bool:
        """Texto → MP3 com a pele de locução de rádio (Piper + ffmpeg).

        Sintetiza o WAV com a voz do perfil e aplica a cadeia de rádio do
        legado Nicky Locutor. True em sucesso (mp3 gravado e não vazio).
        """
        if not self.locucao_disponivel:
            log.warn("Locução indisponível (piper/ffmpeg ausente)")
            return False
        if not text or not text.strip():
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="od_locucao_") as tmp_dir:
                wav = Path(tmp_dir) / "fala.wav"
                ok = await self.synthesize_to_file(text, wav, profile)
                if not ok:
                    return False
                proc = await asyncio.create_subprocess_exec(
                    *self._comando_locucao(wav, Path(output_path)),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.timeout_s
                )
                if proc.returncode != 0:
                    log.error(
                        "ffmpeg da locução falhou",
                        returncode=proc.returncode,
                        stderr=stderr.decode(errors="ignore")[:300],
                    )
                    return False
                out = Path(output_path)
                if not out.is_file() or out.stat().st_size == 0:
                    log.error("Locução não gerou MP3 válido")
                    return False
                log.info(
                    "Locução de rádio concluída",
                    bytes=out.stat().st_size,
                    voice=profile or "default",
                )
                return True
        except asyncio.TimeoutError:
            log.error("Locução timeout", timeout_s=self.config.timeout_s)
            return False
        except Exception as exc:  # pragma: no cover
            log.error("Locução exceção", error=str(exc))
            return False

    # -- Introspecção --------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "available": self.available,
            "binary": str(self.config.binary),
            "locucao": self.locucao_disponivel,
            "voices": {k: v[0] for k, v in self._voice_map.items()},
        }