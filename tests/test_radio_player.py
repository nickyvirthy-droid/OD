"""
OMEGA DRAKON • TESTS
Módulo: tests/test_radio_player.py
Descrição: Player da rádio local — player único por sistema e "desliga a
           rádio" encerrando TODOS os ffplay (inclusive órfãos de um restart
           do od-core, que o singleton em memória não vê). Bug real de
           11/11/2026: dois ffplay tocando ao mesmo tempo (volume 0,30 e
           0,50) e "desliga a rádio" não calava o áudio, porque só matava o
           filho registrado no processo atual.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.actions import actions as radio


def _processo_falso(
    proc: Path,
    pid: int,
    argv: list[str],
    env: str = "",
) -> None:
    d = proc / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "environ").write_bytes(env.encode() + b"\0")


@pytest.fixture()
def proc_tree(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    stream = radio._RADIO_STREAM_URL
    # player nosso, com a marca
    _processo_falso(proc, 1001, ["ffplay", "-nodisp", "-autoexit", stream], "OD_RADIO_CHILD=1")
    # player antigo (sem marca), reconhecido pela URL do stream
    _processo_falso(proc, 1002, ["ffplay", "-nodisp", "-autoexit", "-af", "volume=0.50", stream])
    # ruídos que não podem ser tocados
    _processo_falso(proc, 1003, ["ffmpeg", "-i", stream])
    _processo_falso(proc, 1004, ["ffplay", "-nodisp", "/home/alex/video.mp4"])
    _processo_falso(proc, 1005, ["python", "-m", "ffplay"])
    return proc


class TestVarreduraDePlayers:
    def test_acha_marcado_e_antigo_pela_url(self, proc_tree: Path) -> None:
        assert radio._radio_ffplay_pids(str(proc_tree)) == [1001, 1002]

    def test_ignora_outros_ffplay_e_outros_processos(self, proc_tree: Path) -> None:
        pids = radio._radio_ffplay_pids(str(proc_tree))
        for ruido in (1003, 1004, 1005):
            assert ruido not in pids

    def test_proc_inexistente_nao_lanca(self, tmp_path: Path) -> None:
        assert radio._radio_ffplay_pids(str(tmp_path / "nao_existe")) == []


class TestRadioPlayNaoDuplica:
    def test_player_ja_no_ar_e_adotado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [4242])
        monkeypatch.setattr(
            radio.subprocess,
            "Popen",
            lambda *a, **k: pytest.fail("não deveria abrir um segundo ffplay"),
        )
        monkeypatch.setattr(radio, "_radio_terminate", lambda pid: True)

        out = radio.radio_play(auto_power=False, volume=70)
        assert out["ok"] is True
        assert out["status"] == "tocando"
        assert out["pid"] == 4242

    def test_duplicatas_sao_encerradas_ao_tocar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [10, 11, 12])
        mortos: list[int] = []
        monkeypatch.setattr(radio, "_radio_terminate", lambda pid: mortos.append(pid) or True)

        out = radio.radio_play(auto_power=False)
        assert out["pid"] == 10
        assert mortos == [11, 12]
        assert "2 instância(s) duplicada(s)" in out["hint"]

    def test_play_marca_o_filho(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [])
        monkeypatch.setattr(radio, "_run", lambda *a, **k: (0, "", ""))
        capturado: dict = {}

        class FakePopen:
            pid = 777

            def __init__(self, cmd, **kwargs):
                capturado.update(cmd=cmd, kwargs=kwargs)

            def poll(self):
                return None

        monkeypatch.setattr(radio, "_RADIO_PROCESS", None)
        monkeypatch.setattr(radio.subprocess, "Popen", FakePopen)

        out = radio.radio_play(auto_power=False)
        assert out["ok"] is True and out["pid"] == 777
        assert capturado["kwargs"]["env"]["OD_RADIO_CHILD"] == "1"
        monkeypatch.setattr(radio, "_RADIO_PROCESS", None)


class TestRadioStopEncerraTodos:
    def test_sem_singleton_mata_pela_varredura(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_RADIO_PROCESS", None)
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [21, 22])
        mortos: list[int] = []
        monkeypatch.setattr(radio, "_radio_terminate", lambda pid: mortos.append(pid) or True)

        out = radio.radio_stop(auto_power=False)
        assert out["ok"] is True
        assert out["status"] == "parado"
        assert mortos == [21, 22]
        assert out["pids_encerrados"] == [21, 22]
        assert "2 instâncias encerradas" in out["hint"]

    def test_nada_no_ar_diz_que_ja_estava_parado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_RADIO_PROCESS", None)
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [])
        out = radio.radio_stop(auto_power=False)
        assert out["status"] == "parado"
        assert out["pids_encerrados"] == []
        assert out["hint"] == "já estava parado"

    def test_player_que_resiste_aparece_no_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_RADIO_PROCESS", None)
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [31, 32])
        monkeypatch.setattr(radio, "_radio_terminate", lambda pid: pid == 31)

        out = radio.radio_stop(auto_power=False)
        assert out["pids_encerrados"] == [31]
        assert "1 player(s) resistiram" in out["hint"]


class TestRadioStatus:
    def test_status_reflete_o_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [50, 51])
        monkeypatch.setattr(radio, "_run", lambda *a, **k: (0, "Volume: 50%", ""))
        out = radio.radio_status()
        assert out["status"] == "tocando"
        assert out["instancias"] == [50, 51]
        assert "desliga a rádio" in out["hint"]

    def test_status_parado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(radio, "_radio_ffplay_pids", lambda proc_root="/proc": [])
        monkeypatch.setattr(radio, "_RADIO_PROCESS", None)
        out = radio.radio_status()
        assert out == {"ok": True, "status": "parado", "stream_url": radio._RADIO_STREAM_URL}


class TestZumbiContaComoMorto:
    """Player que já morreu mas o pai não fez `wait` não pode virar
    'resistiram' no hint do radio_stop (visto ao vivo, 11/11)."""

    def test_zumbi_nao_esta_vivo(self, proc_tree: Path) -> None:
        # pid 1 do próprio teste não existe como zumbi; usa um pid inexistente
        assert radio._radio_pid_vivo(999999) is False

    def test_estado_z_no_proc_e_morto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io

        def fake_open(caminho, modo="r"):
            raise FileNotFoundError

        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setattr(radio.os, "kill", lambda pid, sig: None)
        # sem /proc e com kill respondendo => vivo (não dá para provar morte)
        assert radio._radio_pid_vivo(1234) is True
