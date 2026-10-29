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
import sys
import types
import wave
from pathlib import Path

import pytest

import tools.audio.tts as tts_mod
from tools.audio import (
    EdgeTTSTTS,
    PiperTTS,
    STTConfig,
    TTS,
    TTSConfig,
    WhisperSTT,
)


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

    def test_convert_to_wav_sucesso(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            assert await stt._convert_to_wav(
                tmp_path / "in.ogg", tmp_path / "out.wav"
            ) is True

        asyncio.run(run())

    def test_convert_to_wav_falha_returncode(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=1, stderr=b"codec invalido")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            assert await stt._convert_to_wav(
                tmp_path / "in.ogg", tmp_path / "out.wav"
            ) is False

        asyncio.run(run())

    def test_convert_to_wav_timeout(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        class SlowProc(FakeProc):
            async def communicate(self, input: bytes = b""):
                raise asyncio.TimeoutError()

        async def fake_exec(*args, **kwargs):
            return SlowProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            assert await stt._convert_to_wav(
                tmp_path / "in.ogg", tmp_path / "out.wav"
            ) is False

        asyncio.run(run())

    def test_transcribe_wav_texto_vazio(self, tmp_path: Path, monkeypatch) -> None:
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        wav = make_wav(tmp_path / "fala.wav")
        (tmp_path / "fala.txt").write_text("\n", encoding="utf-8")

        async def run() -> None:
            assert await stt.transcribe_wav(wav) is None

        asyncio.run(run())

    def test_transcribe_sem_wav_valido(self, tmp_path: Path, monkeypatch) -> None:
        """Conversão retorna True mas não gera WAV → transcribe devolve None."""
        stt = WhisperSTT(stt_config(tmp_path))

        async def fake_convert(input_path, wav_path) -> bool:
            return True  # não cria o arquivo de propósito

        monkeypatch.setattr(stt, "_convert_to_wav", fake_convert)
        inp = make_wav(tmp_path / "entrada.ogg")

        async def run() -> None:
            assert await stt.transcribe(inp) is None

        asyncio.run(run())


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
        assert "locucao" in snap


# ─── TTS — auto-descoberta de vozes (integração Nicky Locutor) ──────────────


def _criar_voz(dir_path: Path, nome: str) -> None:
    """Cria o par *.onnx + *.onnx.json de uma voz falsa."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{nome}.onnx").write_bytes(b"onnx fake")
    (dir_path / f"{nome}.onnx.json").write_text("{}", encoding="utf-8")


class TestVozesDescobertas:
    def test_vozes_do_diretorio_viram_vozes_nomeadas(self, tmp_path: Path) -> None:
        voices = tmp_path / "tts"
        _criar_voz(voices, "hal")
        _criar_voz(voices, "pt_BR-jeff-medium")
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            voices_dir=str(voices),
        )
        tts = PiperTTS(cfg)
        assert "hal" in tts.vozes
        assert "pt_BR-jeff-medium" in tts.vozes
        # default/regulus seguem existindo
        assert "default" in tts.vozes and "regulus" in tts.vozes
        # resolução por nome devolve o modelo descoberto
        assert tts._resolve_voice("hal")[0] == str(voices / "hal.onnx")

    def test_voz_sem_config_json_e_ignorada(self, tmp_path: Path) -> None:
        voices = tmp_path / "tts"
        voices.mkdir(parents=True, exist_ok=True)
        (voices / "sem-json.onnx").write_bytes(b"onnx")
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            voices_dir=str(voices),
        )
        tts = PiperTTS(cfg)
        assert "sem-json" not in tts.vozes

    def test_descoberta_nao_sobrescreve_default_e_regulus(self, tmp_path: Path) -> None:
        voices = tmp_path / "tts"
        _criar_voz(voices, "default")
        _criar_voz(voices, "regulus")
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            regulus_model=str(tmp_path / "faber.onnx"),
            regulus_config=str(tmp_path / "faber.onnx.json"),
            voices_dir=str(voices),
        )
        tts = PiperTTS(cfg)
        assert tts._resolve_voice(None)[0] == str(tmp_path / "dii.onnx")
        assert tts._resolve_voice("regulus")[0] == str(tmp_path / "faber.onnx")

    def test_voices_dir_inexistente_nao_quebra(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            voices_dir=str(tmp_path / "nao-existe"),
        )
        tts = PiperTTS(cfg)
        assert set(tts.vozes) == {"default", "regulus"}

    def test_voices_dir_none_so_tem_explicitas(self, tmp_path: Path) -> None:
        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            voices_dir=None,
        )
        tts = PiperTTS(cfg)
        assert set(tts.vozes) == {"default", "regulus"}


# ─── TTS — cadeia de locução de rádio (integração Nicky Locutor) ────────────


class TestLocucaoRadio:
    def _cfg(self, tmp_path: Path, **kwargs) -> TTSConfig:
        base = dict(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            ffmpeg_bin=str(tmp_path / "ffmpeg"),
        )
        base.update(kwargs)
        return TTSConfig(**base)

    def test_locucao_disponivel_exige_ffmpeg(self, tmp_path: Path) -> None:
        (tmp_path / "piper").write_bytes(b"bin")
        (tmp_path / "dii.onnx").write_bytes(b"onnx")
        (tmp_path / "dii.onnx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ffmpeg").write_bytes(b"bin")
        assert PiperTTS(self._cfg(tmp_path)).locucao_disponivel
        # sem ffmpeg no disco = locução indisponível (mesmo com piper ok)
        (tmp_path / "ffmpeg").unlink()
        assert not PiperTTS(self._cfg(tmp_path)).locucao_disponivel

    def test_comando_locucao_cadeia_completa(self, tmp_path: Path) -> None:
        tts = PiperTTS(self._cfg(tmp_path))
        cmd = tts._comando_locucao(tmp_path / "in.wav", tmp_path / "out.mp3")
        linha = " ".join(cmd)
        assert "equalizer=f=80" in linha  # presença/grave de voz
        assert "equalizer=f=8000" in linha  # brilho
        assert "compand=" in linha  # volume de locução
        assert "adelay=2500|2500" in linha  # 2,5 s antes da fala
        assert "anoisesrc=d=15" in linha  # fundo de ruído branco
        assert "amix=inputs=2:duration=first" in linha
        assert "128k" in linha  # mp3 128k como a rádio
        assert cmd[-1] == str(tmp_path / "out.mp3")  # saída por último

    def test_locucao_desabilitada_sem_binarios(self, tmp_path: Path) -> None:
        cfg = self._cfg(tmp_path)  # paths inexistentes
        tts = PiperTTS(cfg)

        async def run() -> None:
            assert not await tts.synthesize_locucao_to_file(
                "boa noite, rádio", tmp_path / "out.mp3"
            )

        asyncio.run(run())

    def test_locucao_texto_vazio(self, tmp_path: Path) -> None:
        (tmp_path / "piper").write_bytes(b"bin")
        (tmp_path / "dii.onnx").write_bytes(b"onnx")
        (tmp_path / "dii.onnx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ffmpeg").write_bytes(b"bin")
        tts = PiperTTS(self._cfg(tmp_path))

        async def run() -> None:
            assert not await tts.synthesize_locucao_to_file("  ", tmp_path / "o.mp3")

        asyncio.run(run())

    def test_locucao_sucesso_piper_e_ffmpeg(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "piper").write_bytes(b"bin")
        (tmp_path / "dii.onnx").write_bytes(b"onnx")
        (tmp_path / "dii.onnx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ffmpeg").write_bytes(b"bin")
        tts = PiperTTS(self._cfg(tmp_path))

        async def fake_exec(*args, **kwargs):
            destino = Path(args[-1])
            if destino.suffix == ".mp3":
                destino.write_bytes(b"ID3mp3 fake")
            else:
                make_wav(destino)
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        out = tmp_path / "locucao.mp3"

        async def run() -> None:
            assert await tts.synthesize_locucao_to_file("boa noite", out)
            assert out.is_file() and out.stat().st_size > 0

        asyncio.run(run())

    def test_locucao_ffmpeg_falha(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "piper").write_bytes(b"bin")
        (tmp_path / "dii.onnx").write_bytes(b"onnx")
        (tmp_path / "dii.onnx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ffmpeg").write_bytes(b"bin")
        tts = PiperTTS(self._cfg(tmp_path))

        async def fake_exec(*args, **kwargs):
            destino = Path(args[-1])
            if destino.suffix == ".mp3":
                return FakeProc(returncode=1, stderr=b"filtro invalido")
            make_wav(destino)
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            assert not await tts.synthesize_locucao_to_file(
                "boa noite", tmp_path / "locucao.mp3"
            )

        asyncio.run(run())

    def test_locucao_piper_falha_nao_chama_ffmpeg(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "piper").write_bytes(b"bin")
        (tmp_path / "dii.onnx").write_bytes(b"onnx")
        (tmp_path / "dii.onnx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ffmpeg").write_bytes(b"bin")
        tts = PiperTTS(self._cfg(tmp_path))
        chamadas: list = []

        async def fake_exec(*args, **kwargs):
            chamadas.append(args[0])
            return FakeProc(returncode=1, stderr=b"piper quebrou")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        async def run() -> None:
            assert not await tts.synthesize_locucao_to_file(
                "boa noite", tmp_path / "locucao.mp3"
            )
            # só o piper foi chamado (nada de ffmpeg)
            assert chamadas == [str(tmp_path / "piper")]

        asyncio.run(run())


# ─── edge-tts (engine opcional, 28/10) + TTS unificado ───────────────────


def cfg_tts(tmp_path: Path, **kwargs) -> TTSConfig:
    """Config com piper/ffmpeg apontando para arquivos FALSOS em tmp_path."""
    (tmp_path / "piper").write_bytes(b"bin")
    (tmp_path / "dii.onnx").write_bytes(b"onnx")
    (tmp_path / "dii.onnx.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ffmpeg").write_bytes(b"bin")
    base: dict = dict(
        binary=str(tmp_path / "piper"),
        model=str(tmp_path / "dii.onnx"),
        config=str(tmp_path / "dii.onnx.json"),
        ffmpeg_bin=str(tmp_path / "ffmpeg"),
        voices_dir=None,  # não varre voice/tts/ real
    )
    base.update(kwargs)
    return TTSConfig(**base)


def _comunicate_sem_arquivo(text: str, voice: str, *args, **kwargs):
    class SemArquivo:
        async def save(self, path: str) -> None:
            return None  # não grava nada

    return SemArquivo()


@pytest.fixture
def edge_falso(monkeypatch):
    """Pacote edge-tts simulado em sys.modules: sem rede, sem binário real.

    Registra cada Communicate criado e devolve (módulo, chamadas).
    """
    chamadas: list[dict] = []

    class Comunicate:
        def __init__(self, text: str, voice: str, *args, **kwargs) -> None:
            self.text = text
            self.voice = voice
            chamadas.append({"text": text, "voice": voice})

        async def save(self, path: str) -> None:
            if self.text.strip() == "LENTO":
                await asyncio.sleep(5)  # estoura o timeout_s do teste
            if self.text.strip() == "NAO_GRAVA":
                return
            Path(path).write_bytes(b"ID3\x04edge-fake")

    mod = types.ModuleType("edge_tts")
    mod.Communicate = Comunicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    monkeypatch.setattr(tts_mod, "edge_tts_instalado", lambda: True)
    return types.SimpleNamespace(mod=mod, chamadas=chamadas)


@pytest.fixture
def edge_ausente(monkeypatch):
    """Simula o pacote fora do ambiente: import quebra e a introspecção sabe."""
    monkeypatch.setitem(sys.modules, "edge_tts", None)  # import -> ImportError
    monkeypatch.setattr(tts_mod, "edge_tts_instalado", lambda: False)


def _conta(
    monkeypatch, classe, nome: str, retorno, chamadas: list[str] | None = None
) -> list[str]:
    """Substitui um método assíncrono por um fake que registra quem foi chamado.

    `chamadas` opcional = mesma lista para várias engines (ordem da cascata).
    """
    seq = chamadas if chamadas is not None else []

    async def fake(self, *args, **kwargs):
        seq.append("edge" if isinstance(self, EdgeTTSTTS) else "piper")
        return retorno

    monkeypatch.setattr(classe, nome, fake)
    return seq


class TestEdgeTTSTTS:
    def test_available_exige_pacote_instalado(self, tmp_path: Path, edge_ausente) -> None:
        tts = EdgeTTSTTS(cfg_tts(tmp_path))
        assert tts.enabled and not tts.available
        assert not tts.locucao_disponivel  # sem pacote não há locução
        snap = tts.snapshot()
        assert snap["engine"] == "edge-tts"
        assert snap["available"] is False and snap["locucao"] is False

    def test_available_true_com_pacote(self, tmp_path: Path, edge_falso) -> None:
        assert EdgeTTSTTS(cfg_tts(tmp_path)).available

    def test_available_false_quando_desabilitado(self, tmp_path: Path, edge_falso) -> None:
        assert not EdgeTTSTTS(cfg_tts(tmp_path, enabled=False)).available

    def test_resolve_voice_perfis(self, tmp_path: Path, edge_falso) -> None:
        tts = EdgeTTSTTS(cfg_tts(tmp_path))
        assert tts._resolve_voice(None) == tts_mod.EDGE_TTS_DEFAULT
        assert tts._resolve_voice("regulus") == tts_mod.EDGE_TTS_REGULUS
        assert tts._resolve_voice("pt-BR-ThalitaNeural") == "pt-BR-ThalitaNeural"
        # case-insensitive devolve o nome CANÔNICO (a API da Microsoft exige)
        assert tts._resolve_voice("pt-br-thalitaneural") == "pt-BR-ThalitaNeural"
        assert tts._resolve_voice("REGULUS") == tts_mod.EDGE_TTS_REGULUS
        assert tts._resolve_voice("  ") == tts_mod.EDGE_TTS_DEFAULT
        assert tts._resolve_voice("voz_que_nao_existe") == tts_mod.EDGE_TTS_DEFAULT

    def test_vozes_catalogo(self, tmp_path: Path, edge_falso) -> None:
        vozes = EdgeTTSTTS(cfg_tts(tmp_path)).vozes
        assert set(vozes) >= {
            "default",
            "regulus",
            "pt-BR-FranciscaNeural",
            "pt-BR-AntonioNeural",
            "pt-BR-ThalitaNeural",
            "pt-BR-DanielNeural",
        }
        assert vozes["pt-BR-FranciscaNeural"].startswith("Francisca")

    def test_to_file_desabilitado_e_texto_vazio(self, tmp_path: Path, edge_falso) -> None:
        desligado = EdgeTTSTTS(cfg_tts(tmp_path, enabled=False))
        assert not asyncio.run(desligado.synthesize_to_file("oi", tmp_path / "a.mp3"))
        ligado = EdgeTTSTTS(cfg_tts(tmp_path))
        assert not asyncio.run(ligado.synthesize_to_file("   ", tmp_path / "b.mp3"))

    def test_to_file_sucesso_usa_voz_pedida(self, tmp_path: Path, edge_falso) -> None:
        out = tmp_path / "fala.mp3"
        assert asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path)).synthesize_to_file(
                "boa noite, rádio", out, "regulus"
            )
        )
        assert out.is_file() and out.stat().st_size > 0
        assert edge_falso.chamadas[-1] == {
            "text": "boa noite, rádio",
            "voice": tts_mod.EDGE_TTS_REGULUS,
        }

    def test_to_file_sem_arquivo_gerado(self, tmp_path: Path, edge_falso) -> None:
        edge_falso.mod.Communicate = _comunicate_sem_arquivo
        assert not asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path)).synthesize_to_file("oi", tmp_path / "x.mp3")
        )

    def test_to_file_timeout(self, tmp_path: Path, edge_falso) -> None:
        cfg = cfg_tts(tmp_path, timeout_s=0.01)
        assert not asyncio.run(
            EdgeTTSTTS(cfg).synthesize_to_file("LENTO", tmp_path / "t.mp3")
        )

    def test_to_file_sem_pacote(self, tmp_path: Path, edge_ausente) -> None:
        assert not asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path)).synthesize_to_file("oi", tmp_path / "n.mp3")
        )

    def test_synthesize_devolve_bytes_e_none(self, tmp_path: Path, edge_falso) -> None:
        tts = EdgeTTSTTS(cfg_tts(tmp_path))
        dados = asyncio.run(tts.synthesize("linha no ar"))
        assert dados and dados.startswith(b"ID3")
        desligado = EdgeTTSTTS(cfg_tts(tmp_path, enabled=False))
        assert asyncio.run(desligado.synthesize("oi")) is None
        assert asyncio.run(tts.synthesize("")) is None
        assert asyncio.run(tts.synthesize("NAO_GRAVA")) is None

    def test_comando_locucao_cadeia_completa(self, tmp_path: Path, edge_falso) -> None:
        tts = EdgeTTSTTS(cfg_tts(tmp_path))
        cmd = tts._comando_locucao(tmp_path / "in.mp3", tmp_path / "out.mp3")
        linha = " ".join(cmd)
        assert str(tmp_path / "ffmpeg") == cmd[0]
        assert "equalizer=f=80" in linha and "equalizer=f=8000" in linha
        assert "compand=" in linha and "adelay=2500|2500" in linha
        assert "anoisesrc=d=15" in linha and "amix=inputs=2:duration=first" in linha
        assert "128k" in linha and cmd[-1] == str(tmp_path / "out.mp3")

    def test_locucao_disponivel_exige_ffmpeg(self, tmp_path: Path, edge_falso) -> None:
        tts = EdgeTTSTTS(cfg_tts(tmp_path))
        assert tts.locucao_disponivel
        (tmp_path / "ffmpeg").unlink()
        assert not tts.locucao_disponivel
        assert not EdgeTTSTTS(cfg_tts(tmp_path, ffmpeg_bin=None)).locucao_disponivel

    def test_locucao_indisponivel_e_texto_vazio(self, tmp_path: Path, edge_falso) -> None:
        sem_ffmpeg = EdgeTTSTTS(cfg_tts(tmp_path, ffmpeg_bin=str(tmp_path / "nao")))
        out = tmp_path / "l.mp3"
        assert not asyncio.run(sem_ffmpeg.synthesize_locucao_to_file("oi", out))
        com_tudo = EdgeTTSTTS(cfg_tts(tmp_path))
        assert not asyncio.run(com_tudo.synthesize_locucao_to_file("  ", out))
        assert not out.exists()

    def test_locucao_sucesso(self, tmp_path: Path, edge_falso, monkeypatch) -> None:
        async def fake_exec(*args, **kwargs):
            Path(args[-1]).write_bytes(b"ID3locucao")
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        out = tmp_path / "locucao.mp3"
        assert asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path)).synthesize_locucao_to_file("boa noite", out)
        )
        assert out.stat().st_size > 0

    def test_locucao_ffmpeg_falha(self, tmp_path: Path, edge_falso, monkeypatch) -> None:
        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=1, stderr=b"filtro invalido")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        assert not asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path)).synthesize_locucao_to_file(
                "boa noite", tmp_path / "f.mp3"
            )
        )

    def test_locucao_saida_vazia(self, tmp_path: Path, edge_falso, monkeypatch) -> None:
        async def fake_exec(*args, **kwargs):
            return FakeProc(returncode=0)  # sucesso mas nada gravado

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        assert not asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path)).synthesize_locucao_to_file(
                "boa noite", tmp_path / "v.mp3"
            )
        )

    def test_locucao_falha_na_sintese_nao_chama_ffmpeg(
        self, tmp_path: Path, edge_falso, monkeypatch
    ) -> None:
        chamadas: list = []

        async def fake_exec(*args, **kwargs):
            chamadas.append(args[0])
            return FakeProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        assert not asyncio.run(
            EdgeTTSTTS(cfg_tts(tmp_path, enabled=False)).synthesize_locucao_to_file(
                "boa noite", tmp_path / "n.mp3"
            )
        )
        assert chamadas == []

    def test_snapshot(self, tmp_path: Path, edge_falso) -> None:
        snap = EdgeTTSTTS(cfg_tts(tmp_path)).snapshot()
        assert snap["engine"] == "edge-tts" and snap["available"] is True
        assert snap["locucao"] is True and "pt-BR-FranciscaNeural" in snap["voices"]


class TestTTSUnificado:
    def test_engines_primario_e_fallback(self, tmp_path: Path) -> None:
        piper = TTS(cfg_tts(tmp_path))  # default
        assert isinstance(piper.piper, PiperTTS) and isinstance(piper.edge, EdgeTTSTTS)
        assert piper._primary_engine() is piper.piper
        assert piper._fallback_engine() is None  # "piper" puro: sem cair de volta

        so_edge = TTS(cfg_tts(tmp_path, engine="edge-tts"))
        assert so_edge._primary_engine() is so_edge.edge
        assert so_edge._fallback_engine() is so_edge.piper

        os_dois = TTS(cfg_tts(tmp_path, engine="both"))
        assert os_dois._primary_engine() is os_dois.piper
        assert os_dois._fallback_engine() is os_dois.edge

    def test_available_cascata(self, tmp_path: Path, edge_falso) -> None:
        # primário (piper) disponível
        assert TTS(cfg_tts(tmp_path)).available
        # primário indisponível, fallback (edge) disponível
        sem_piper = TTS(cfg_tts(tmp_path, engine="edge-tts", binary=str(tmp_path / "nao")))
        assert sem_piper._primary_engine().available  # edge
        # primário indisponível e fallback também
        cfg = cfg_tts(tmp_path, engine="edge-tts", binary=str(tmp_path / "nao"))
        assert not TTS(cfg).piper.available
        cfg.enabled = False
        assert not TTS(cfg).available  # nada habilitado

    def test_available_sem_nenhuma_engine(self, tmp_path: Path, edge_ausente) -> None:
        cfg = cfg_tts(tmp_path, engine="edge-tts", binary=str(tmp_path / "nao"))
        tts = TTS(cfg)
        assert not tts.edge.available and not tts.piper.available
        assert not tts.available
        assert tts.vozes == {}

    def test_available_cai_para_piper_quando_edge_ausente(
        self, tmp_path: Path, edge_ausente
    ) -> None:
        tts = TTS(cfg_tts(tmp_path, engine="edge-tts"))
        assert not tts.edge.available and tts.piper.available
        assert tts.available  # o fallback segura a casa

    def test_vozes_unificadas_com_prefixo(self, tmp_path: Path, edge_falso) -> None:
        vozes = TTS(cfg_tts(tmp_path)).vozes
        assert "piper:default" in vozes and "edge:default" in vozes
        assert "edge:pt-BR-FranciscaNeural" in vozes
        # sem o pacote, as vozes edge não aparecem na lista unificada

    def test_vozes_unificadas_sem_piper(self, tmp_path: Path, edge_falso) -> None:
        cfg = cfg_tts(tmp_path, binary=str(tmp_path / "nao"))
        vozes = TTS(cfg).vozes
        assert list(k for k in vozes if k.startswith("piper:")) == []
        assert "edge:default" in vozes

    def test_vozes_unificadas_sem_edge(self, tmp_path: Path, edge_ausente) -> None:
        vozes = TTS(cfg_tts(tmp_path)).vozes
        assert "piper:default" in vozes
        assert list(k for k in vozes if k.startswith("edge:")) == []

    def test_locucao_cascata_piper_salva_edge(self, tmp_path: Path, edge_ausente) -> None:
        # piper (padrão) com ffmpeg no disco: locução de pé
        assert TTS(cfg_tts(tmp_path)).locucao_disponivel
        # engine edge primária SEM o pacote -> o piper (fallback) entrega
        cfg = cfg_tts(tmp_path, engine="edge-tts")
        assert not TTS(cfg).edge.locucao_disponivel
        assert TTS(cfg).locucao_disponivel

    def test_locucao_indisponivel_nas_duas_engines(self, tmp_path: Path, edge_falso) -> None:
        # sem ffmpeg, nenhuma engine entrega locução
        cfg = cfg_tts(tmp_path, ffmpeg_bin=str(tmp_path / "nao"))
        assert not TTS(cfg).locucao_disponivel
        # desligado: mesma coisa
        cfg_off = cfg_tts(tmp_path, enabled=False)
        assert not TTS(cfg_off).locucao_disponivel

    def test_synthesize_primario_sem_fallback(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        chamadas = _conta(monkeypatch, PiperTTS, "synthesize", b"piper-mp3")
        assert asyncio.run(TTS(cfg_tts(tmp_path)).synthesize("oi")) == b"piper-mp3"
        assert chamadas == ["piper"]  # engine "piper" não cai para o edge

    def test_synthesize_cai_para_piper_quando_edge_falha(
        self, tmp_path: Path, edge_falso, monkeypatch
    ) -> None:
        seq: list[str] = []
        _conta(monkeypatch, EdgeTTSTTS, "synthesize", None, seq)
        _conta(monkeypatch, PiperTTS, "synthesize", b"piper-mp3", seq)
        tts = TTS(cfg_tts(tmp_path, engine="edge-tts"))
        assert asyncio.run(tts.synthesize("oi")) == b"piper-mp3"
        assert seq == ["edge", "piper"]  # tentou a primária e caiu

    def test_synthesize_sem_fallback_configurado(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        chamadas = _conta(monkeypatch, PiperTTS, "synthesize", None)
        assert asyncio.run(TTS(cfg_tts(tmp_path)).synthesize("oi")) is None
        assert chamadas == ["piper"]

    def test_synthesize_nenhuma_disponivel(
        self, tmp_path: Path, edge_ausente, monkeypatch
    ) -> None:
        chamadas = _conta(monkeypatch, PiperTTS, "synthesize", b"x")
        cfg = cfg_tts(tmp_path, engine="edge-tts", binary=str(tmp_path / "nao"))
        assert asyncio.run(TTS(cfg).synthesize("oi")) is None
        assert chamadas == []  # sem engine disponível, ninguém é chamado

    def test_to_file_cascata(self, tmp_path: Path, edge_falso, monkeypatch) -> None:
        out = tmp_path / "out.mp3"
        # primário já entrega -> fallback não é acionado
        seq: list[str] = []
        _conta(monkeypatch, PiperTTS, "synthesize_to_file", True, seq)
        _conta(monkeypatch, EdgeTTSTTS, "synthesize_to_file", True, seq)
        assert asyncio.run(TTS(cfg_tts(tmp_path)).synthesize_to_file("oi", out))
        assert seq == ["piper"]

        # primário falha -> fallback entrega
        seq.clear()
        _conta(monkeypatch, PiperTTS, "synthesize_to_file", True, seq)
        _conta(monkeypatch, EdgeTTSTTS, "synthesize_to_file", False, seq)
        tts = TTS(cfg_tts(tmp_path, engine="edge-tts"))
        assert asyncio.run(tts.synthesize_to_file("oi", out))
        assert seq == ["edge", "piper"]

        # primário falha e o fallback não está disponível -> ninguém além da primária
        seq.clear()
        cfg = cfg_tts(tmp_path, engine="edge-tts", binary=str(tmp_path / "nao"))
        _conta(monkeypatch, PiperTTS, "synthesize_to_file", True, seq)
        _conta(monkeypatch, EdgeTTSTTS, "synthesize_to_file", False, seq)
        assert not asyncio.run(TTS(cfg).synthesize_to_file("oi", out))
        assert seq == ["edge"]

    def test_to_file_sem_fallback_configurado(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        chamadas = _conta(monkeypatch, PiperTTS, "synthesize_to_file", False)
        assert not asyncio.run(TTS(cfg_tts(tmp_path)).synthesize_to_file("oi", tmp_path / "o.mp3"))
        assert chamadas == ["piper"]

    def test_locucao_cascata_de_sintese(self, tmp_path: Path, monkeypatch) -> None:
        # primário entrega
        seq: list[str] = []
        _conta(monkeypatch, PiperTTS, "synthesize_locucao_to_file", True, seq)
        _conta(monkeypatch, EdgeTTSTTS, "synthesize_locucao_to_file", True, seq)
        assert asyncio.run(
            TTS(cfg_tts(tmp_path)).synthesize_locucao_to_file("oi", tmp_path / "a.mp3")
        )
        assert seq == ["piper"]

        # primário falha -> fallback com locução disponível entrega
        seq.clear()
        _conta(monkeypatch, PiperTTS, "synthesize_locucao_to_file", False, seq)
        _conta(monkeypatch, EdgeTTSTTS, "synthesize_locucao_to_file", True, seq)
        tts = TTS(cfg_tts(tmp_path, engine="edge-tts"))
        assert asyncio.run(tts.synthesize_locucao_to_file("oi", tmp_path / "b.mp3"))
        assert seq == ["edge"]  # primária já entregou

        # primário falha e o fallback não tem locução disponível (sem ffmpeg)
        seq.clear()
        cfg = cfg_tts(tmp_path, engine="edge-tts", ffmpeg_bin=str(tmp_path / "nao"))
        _conta(monkeypatch, EdgeTTSTTS, "synthesize_locucao_to_file", False, seq)
        _conta(monkeypatch, PiperTTS, "synthesize_locucao_to_file", True, seq)
        assert not asyncio.run(TTS(cfg).synthesize_locucao_to_file("oi", tmp_path / "c.mp3"))
        assert seq == ["edge"]  # o piper não foi chamado: locução dele indisponível

    def test_snapshot_unificado(self, tmp_path: Path, edge_falso) -> None:
        snap = TTS(cfg_tts(tmp_path)).snapshot()
        assert snap["engine"] == "piper" and snap["available"] is True
        assert snap["piper"]["available"] is True
        assert snap["edge"]["available"] is True
        assert snap["locucao"] is True
        assert "piper:default" in snap["voices"]

    def test_snapshot_sem_edge_instalado(self, tmp_path: Path, edge_ausente) -> None:
        snap = TTS(cfg_tts(tmp_path)).snapshot()
        assert snap["edge"] == {"available": False}
        assert snap["available"] is True  # o piper continua de pé

    def test_config_engine_padrao_e_vozes(self) -> None:
        assert TTSConfig().engine == "piper"
        assert TTSConfig().edge_tts_default == tts_mod.EDGE_TTS_DEFAULT
        assert TTSConfig().edge_tts_regulus == tts_mod.EDGE_TTS_REGULUS

    def test_edge_tts_instalado_reflete_o_ambiente(self, monkeypatch) -> None:
        import importlib.util as il

        monkeypatch.setattr(il, "find_spec", lambda nome: object())
        assert tts_mod.edge_tts_instalado() is True
        monkeypatch.setattr(il, "find_spec", lambda nome: None)
        assert tts_mod.edge_tts_instalado() is False

        def _explode(nome):
            raise ImportError("sem caminho de import")

        monkeypatch.setattr(il, "find_spec", _explode)
        assert tts_mod.edge_tts_instalado() is False