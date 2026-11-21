"""
OMEGA DRAKON • TESTS
Módulo: tests/test_registro_restart.py
Descrição: auto-registro do restart do od-core em `iniciar/session.json`.
           A regra 4 não pode depender de quem reiniciou lembrar: o serviço
           anota PID, commit, branch, horário, host e motivo. Aqui se prova
           que a lista é append-only, não duplica o mesmo PID, respeita o
           limite, preserva o resto do arquivo e nunca corrompe nem derruba
           o boot quando o JSON está ilegível.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.registro_restart import CHAVE, registrar_restart


def _sessao(tmp_path: Path, dados: dict | None = None) -> Path:
    caminho = tmp_path / "session.json"
    caminho.write_text(
        json.dumps(dados if dados is not None else {"entrada_existente": {"x": 1}},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return caminho


def _agora() -> datetime:
    return datetime(2026, 11, 21, 4, 0, 0, tzinfo=timezone.utc)


class TestRegistroRestart:
    def test_grava_pid_commit_e_horario(self, tmp_path: Path) -> None:
        caminho = _sessao(tmp_path)
        entrada = registrar_restart(
            caminho=caminho, pid=1234, commit="abc1234", agora=_agora(),
            motivo="teste",
        )
        assert entrada is not None
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        registros = dados[CHAVE]
        assert len(registros) == 1
        assert registros[0]["pid"] == 1234
        assert registros[0]["commit"] == "abc1234"
        assert registros[0]["iniciado_em"].startswith("2026-11-21T04:00:00")
        assert registros[0]["motivo"] == "teste"
        assert "host" in registros[0] and "branch" in registros[0]

    def test_preserva_o_resto_do_arquivo(self, tmp_path: Path) -> None:
        caminho = _sessao(tmp_path, {"vigia_rede_app_2026_11_19": {"pedido": "x"}})
        registrar_restart(caminho=caminho, pid=1, commit="c", agora=_agora())
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        assert dados["vigia_rede_app_2026_11_19"] == {"pedido": "x"}

    def test_mesmo_pid_nao_duplica(self, tmp_path: Path) -> None:
        caminho = _sessao(tmp_path)
        primeiro = registrar_restart(caminho=caminho, pid=99, commit="c", agora=_agora())
        segundo = registrar_restart(caminho=caminho, pid=99, commit="c", agora=_agora())
        assert primeiro is not None and segundo is None
        assert len(json.loads(caminho.read_text(encoding="utf-8"))[CHAVE]) == 1

    def test_respeita_o_limite(self, tmp_path: Path) -> None:
        caminho = _sessao(tmp_path)
        for pid in range(1, 8):
            registrar_restart(caminho=caminho, pid=pid, commit="c", agora=_agora(), limite=3)
        registros = json.loads(caminho.read_text(encoding="utf-8"))[CHAVE]
        assert [r["pid"] for r in registros] == [5, 6, 7]

    def test_arquivo_ausente_nao_quebra(self, tmp_path: Path) -> None:
        assert registrar_restart(caminho=tmp_path / "nao_existe.json", pid=1) is None

    def test_json_invalido_nao_e_sobrescrito(self, tmp_path: Path) -> None:
        caminho = tmp_path / "session.json"
        caminho.write_text("{ nao e json", encoding="utf-8")
        assert registrar_restart(caminho=caminho, pid=1, commit="c") is None
        assert caminho.read_text(encoding="utf-8") == "{ nao e json"

    def test_motivo_do_ambiente(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("OD_RESTART_MOTIVO", "deploy do vigia")
        caminho = _sessao(tmp_path)
        entrada = registrar_restart(caminho=caminho, pid=7, commit="c", agora=_agora())
        assert entrada is not None
        assert entrada["motivo"] == "deploy do vigia"
