"""
OMEGA DRAKON • TESTS
Tecnologia que respira.
Módulo: tests/test_voice_api.py
Descrição: Voz na API REST (v1.18.0) — o launcher pluga WhisperSTT/PiperTTS
           nos handlers de /transcribe e /tts (build_voice_handlers), que
           antes eram SEMPRE None no REST (501 no ar; voz só no Telegram).
           Cobre: contratos dos adaptadores sync (loop próprio por chamada),
           gate por env OD_VOICE_STT/OD_VOICE_TTS, auto-detect do
           LD_LIBRARY_PATH para as libs do piper e a flag --espeak_data
           ANTES de --output_file (último argumento — contrato de parse).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - runtime/launcher.py (build_voice_handlers, v1.18.0)
  - tools/audio/tts.py (espeak_data no TTSConfig)
  - integrations/api/server.py (/transcribe, /tts)
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.launcher import build_voice_handlers  # noqa: E402
from tools.audio.tts import DEFAULT_ESPEAK_DATA, PiperTTS  # noqa: E402


def _limpa_envs(monkeypatch) -> None:
    """launcher.env() usa snapshot (_ENV_CACHE): monkeypatch.setenv não basta.

    Padrão do test_websocket.py (ws_env): monkeypatch.setattr no cache.
    """
    from runtime import launcher

    monkeypatch.setattr(
        launcher,
        "_ENV_CACHE",
        {
            "OD_VOICE_STT": "0",
            "OD_VOICE_TTS": "0",
        },
    )
    monkeypatch.setattr(
        launcher,
        "_ENV_CACHE",
        dict(launcher._ENV_CACHE or {}),
    )


class TestBuildVoiceHandlers:
    """Adaptadores sync dos motores reais para o APIServer."""

    def test_motores_reais_presentes_neste_host(self) -> None:
        """O host canônico tem os binários — handlers SAEM (não 501)."""
        stt, tts = build_voice_handlers()
        assert callable(stt), "STT esperado com whisper-cli presente"
        assert callable(tts), "TTS esperado com piper presente"

    def test_tts_handler_devolve_wav_real(self) -> None:
        """TTS sync: texto → bytes WAV (prova com o binário real do host)."""
        _, tts = build_voice_handlers()
        wav = tts("prova do contrato de voz")
        assert wav and wav[:4] == b"RIFF"

    def test_gate_od_voice_stt_zero(self, monkeypatch) -> None:
        """OD_VOICE_STT=0 desliga o STT na API (mesma env do Telegram)."""
        _limpa_envs(monkeypatch)
        stt, tts = build_voice_handlers()
        assert stt is None
        assert tts is None  # TTS também veio 0 no cache isolado

    def test_gate_od_voice_tts_zero_somente(self, monkeypatch) -> None:
        """Só OD_VOICE_TTS=0: STT segue, TTS some."""
        from runtime import launcher

        monkeypatch.setattr(
            launcher,
            "_ENV_CACHE",
            {"OD_VOICE_TTS": "0"},  # STT ausente = default "1"
        )
        stt, tts = build_voice_handlers()
        assert callable(stt)
        assert tts is None

    def test_ld_library_path_detecta_lib_no_repo(self, monkeypatch, tmp_path) -> None:
        """Lib falsificada no REPO_ROOT/voice/tts → env aponta para lá."""
        _limpa_envs(monkeypatch)
        os.environ.pop("LD_LIBRARY_PATH", None)
        fake_repo = tmp_path / "repo"
        lib_dir = fake_repo / "voice" / "tts"
        lib_dir.mkdir(parents=True)
        (lib_dir / "libpiper_phonemize.so.1").write_bytes(b"\x7fELFfake")
        import runtime.launcher as launcher

        original_isfile = Path.is_file

        def fake_isfile(self: Path) -> bool:
            if self.name == "libpiper_phonemize.so.1":
                return str(self) == str(lib_dir / "libpiper_phonemize.so.1")
            return original_isfile(self)

        with mock.patch.object(launcher, "REPO_ROOT", fake_repo), \
             mock.patch.object(Path, "is_file", fake_isfile):
            launcher.build_voice_handlers()
        assert os.environ.get("LD_LIBRARY_PATH") == str(lib_dir)
        os.environ.pop("LD_LIBRARY_PATH", None)


class TestPiperEspeakData:
    """Flag --espeak_data no TTSConfig (fonemização sem phontab do sistema)."""

    def test_default_aponta_deploy_od(self) -> None:
        assert DEFAULT_ESPEAK_DATA == "/opt/omegadrakon/voice/espeak-ng-data"

    def test_flag_vai_antes_do_output_file(self, tmp_path, monkeypatch) -> None:
        """--espeak_data precede --output_file: output continua ÚLTIMO arg."""
        capturado: dict = {}

        async def fake_exec(*args, **kwargs):
            capturado["cmd"] = list(args)

            class Proc:
                returncode = 0
                async def communicate(self, input=None):
                    return (b"", b"")

            return Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        cfg = PiperTTS.__mro__  # sanity: classe real
        tts = PiperTTS(
            type(
                "Cfg",
                (object,),
                {},
            )(),  # substituído logo abaixo por TTSConfig real
        ) if False else PiperTTS()
        # Config real com paths falsos e espeak_data presente no disco:
        from tools.audio.tts import TTSConfig

        cfg_real = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            espeak_data=DEFAULT_ESPEAK_DATA,
        )
        tts = PiperTTS(cfg_real)

        async def run() -> None:
            await tts.synthesize_to_file("olá", tmp_path / "out.wav")

        import asyncio

        asyncio.run(run())
        cmd = capturado["cmd"]
        cmd = [str(c) for c in cmd]
        assert "--espeak_data" in cmd
        assert cmd.index("--espeak_data") < cmd.index("--output_file")
        assert cmd[-1] == str(tmp_path / "out.wav")

    def test_flag_omitida_sem_diretorio(self, tmp_path, monkeypatch) -> None:
        """espeak_data inexistente → flag NÃO vai na linha (piper usa default)."""
        capturado: dict = {}

        async def fake_exec(*args, **kwargs):
            capturado["cmd"] = list(args)

            class Proc:
                returncode = 0
                async def communicate(self, input=None):
                    return (b"", b"")

            return Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        from tools.audio.tts import TTSConfig

        cfg = TTSConfig(
            binary=str(tmp_path / "piper"),
            model=str(tmp_path / "dii.onnx"),
            config=str(tmp_path / "dii.onnx.json"),
            espeak_data=str(tmp_path / "nao_existe"),
        )
        tts = PiperTTS(cfg)

        async def run() -> None:
            await tts.synthesize_to_file("olá", tmp_path / "out.wav")

        import asyncio

        asyncio.run(run())
        assert "--espeak_data" not in [str(c) for c in capturado["cmd"]]


class TestVoiceAPIRestContrato:
    """/transcribe e /tts com handlers REAIS injetados (mesma assinatura)."""

    def test_transcribe_aceita_webm_do_navegador(self, tmp_path: Path) -> None:
        """Contrato do endpoint com handler REAL sync injetado no config."""
        import threading

        from integrations.api import APIConfig, APIServer
        from tests.test_api import _json_response, _request, make_orch

        def stt(audio: bytes) -> str:
            assert audio[:4] == b"\x1aE\xdf\xa3"  # magic EBML do webm
            return "fala reconhecida"

        orch = make_orch(tmp_path)
        server = APIServer(
            orch,
            config=APIConfig(port=0, rate_limit_max=0, stt=stt),
        )
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            webm = b"\x1aE\xdf\xa3" + b"audio fake" * 10
            status, body, _ = _request(
                server.bound_port,
                "POST",
                "/transcribe",
                body={"audio_b64": base64.b64encode(webm).decode()},
            )
            data = _json_response((status, body, _))
            assert status == 200 and data["ok"] is True
            assert data["text"] == "fala reconhecida"
        finally:
            server.shutdown()
            server.server_close()
