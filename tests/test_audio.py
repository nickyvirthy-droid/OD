"""
OMEGA DRAKON • TESTS
Módulo: tests/test_audio.py
Descrição: Testes do pacote tools/audio (Fase 6): STT (6.3, whisper.cpp via
           subprocess) e TTS (6.4, Piper com vozes por perfil). Subprocess
           mockado — nenhum binário real necessário; WAV sintético via stdlib.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pytest

from tools.audio import PiperTTS, STTConfig, TTSConfig, WhisperSTT


# ─── Fake process (subprocess mockado) ─────────────────────────────────────


class FakeProc:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self, input: bytes = b"") -> tuple[bytes, bytes]:
        return b"", self._stderr


def make_wav(path: Path, seconds: float = 0.5) -> Path:
    """WAV sintético 16kHz mono (um tom) via stdlib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        import math

        for i in range(int(rate * seconds)):
            frames += int(8000 * math.sin(2 * math.pi * 440 * i / rate)).to_bytes(
                2, "little", signed=True
            )
        w.writeframes(bytes(frames))
    return path


def stt_config(tmp_path: Path) -> STTConfig:
    return STTConfig(
        binary=str(tmp_path / "whisper-cli"),
        model=str(tmp_path / "ggml-base.bin"),
        ffmpeg="/usr/bin/ffmpeg",
        threads=2,
    )


# ─── STT ───────────────────────────────────────────────────────────────────


class TestSTT:
    def test_available_false_sem_binario(self, tmp_path: Path) -> None:
        cfg = stt_config(tmp_path)  # paths inexistentes
        stt = WhisperSTT(cfg)
        assert not stt.available
        assert stt.enabled

    def test_disabled_retorna_none(self, tmp_path: Path) -> None:
        cfg = stt_config(tmp_path)
        cfg.enabled = False
        stt = WhisperSTT(cfg)
        assert not stt.enabled

        async def run() -> None:
            wav = make_wav(tmp_path / "in.wav")
            assert await stt.transcribe(wav) is None
            assert await stt.transcribe_wav(wav) is None

        asyncio.run(run())

    def test_transcribe_arquivo_inexistente(self, tmp_path: Path) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def run() -> None:
            assert await stt.transcribe(tmp_path / "nao_existe.ogg") is None

        asyncio.run(run())

    def test_transcribe_wav_sucesso(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        wav = make_wav(tmp_path / "fala.wav")
        (tmp_path / "fala.txt").write_text("olá mundo, teste de voz\n", encoding="utf-8")

        async def run() -> None:
            text = await stt.transcribe_wav(wav)
            assert text == "olá mundo, teste de voz"

        asyncio.run(run())

    def test_transcribe_wav_falha_returncode(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=1, stderr=b"modelo nao encontrado")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        wav = make_wav(tmp_path / "fala.wav")

        async def run() -> None:
            assert await stt.transcribe_wav(wav) is None

        asyncio.run(run())

    def test_transcribe_wav_timeout(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        class SlowProc(FakeProc):
            async def communicate(self):
                raise asyncio.TimeoutError()

        async def fake_exec(*args, **kwargs):
            return SlowProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        wav = make_wav(tmp_path / "fala.wav")

        async def run() -> None:
            assert await stt.transcribe_wav(wav) is None

        asyncio.run(run())

    def test_transcribe_wav_sem_txt_gerado(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        wav = make_wav(tmp_path / "fala.wav")  # sem .txt

        async def run() -> None:
            assert await stt.transcribe_wav(wav) is None

        asyncio.run(run())

    def test_transcribe_pipeline_completo(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))
        calls: list[str] = []

        async def fake_convert(input_path: Path, wav_path: Path) -> bool:
            calls.append("convert")
            make_wav(wav_path)
            return True

        async def fake_transcribe(wav_path: Path):
            calls.append("transcribe")
            return "texto transcrito"

        monkeypatch.setattr(stt, "_convert_to_wav", fake_convert)
        monkeypatch.setattr(stt, "transcribe_wav", fake_transcribe)
        inp = make_wav(tmp_path / "entrada.ogg")

        async def run() -> None:
            text = await stt.transcribe(inp)
            assert text == "texto transcrito"
            assert calls == ["convert", "transcribe"]

        asyncio.run(run())

    def test_transcribe_pipeline_conversao_falha(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_convert(input_path: Path, wav_path: Path) -> bool:
            return False

        monkeypatch.setattr(stt, "_convert_to_wav", fake_convert)
        inp = make_wav(tmp_path / "entrada.ogg")

        async def run() -> None:
            assert await stt.transcribe(inp) is None

        asyncio.run(run())

    def test_snapshot(self, tmp_path: Path) -> None:
        stt = WhisperSTT(stt_config(tmp_path))
        snap = stt.snapshot()
        assert snap["enabled"] is True
        assert "binary" in snap and "model" in snap


# ─── TTS ───────────────────────────────────────────────────────────────────


class TestTTS:
    def test_available_false_sem_binario(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
        )
        tts = PiperTTS(cfg)
        assert not tts.available
        assert tts.enabled

    def test_disabled(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            enabled=False,
        )
        tts = PiperTTS(cfg)

        async def run() -> None:
            assert await tts.synthesize("olá") is None
            assert not await tts.synthesize_to_file("olá", tmp_path / "x.wav")

        asyncio.run(run())

    def test_texto_vazio(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
        )
        tts = PiperTTS(cfg)

        async def run() -> None:
            assert not await tts.synthesize_to_file("   ", tmp_path / "x.wav")
            assert await tts.synthesize("") is None

        asyncio.run(run())

    def test_synthesize_to_file_sucesso(self, tmp_path: Path, monkeypatch) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
        )
        tts = PiperTTS(cfg)

        async def fake_exec(*args, **kwargs):
            # piper grava o wav; simulamos aqui (output_path é args[-1])
            make_wav(Path(args[-1]))
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        out = tmp_path / "speech.wav"

        async def run() -> None:
            assert await tts.synthesize_to_file("olá mundo", out)
            assert out.is_file() and out.stat().st_size > 0

        asyncio.run(run())

    def test_synthesize_to_file_falha(self, tmp_path: Path, monkeypatch) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
        )
        tts = PiperTTS(cfg)

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=1, stderr=b"modelo invalido")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            assert not await tts.synthesize_to_file("olá", tmp_path / "speech.wav")

        asyncio.run(run())

    def test_synthesize_retorna_bytes(self, tmp_path: Path, monkeypatch) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
        )
        tts = PiperTTS(cfg)

        async def fake_exec(*args, **kwargs):
            make_wav(Path(args[-1]))
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            data = await tts.synthesize("voz de teste")
            assert data is not None and data[:4] == b"RIFF"

        asyncio.run(run())

    def test_resolve_voice_por_perfil(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            regulus_model=str(tmp_path / "faber.onnx"),
            regulus_config=str(tmp_path / "faber.onnx.json"),
        )
        tts = PiperTTS(cfg)
        assert tts._resolve_voice(None)[0] == str(tmp_path / "dii.onnx")
        assert tts._resolve_voice("regulus")[0] == str(tmp_path / "faber.onnx")
        assert tts._resolve_voice("desconhecido")[0] == str(tmp_path / "dii.onnx")

    def test_snapshot(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
        )
        tts = PiperTTS(cfg)
        snap = tts.snapshot()
        assert snap["enabled"] is True
        assert "voices" in snap