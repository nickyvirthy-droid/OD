"""Guarda do off-site do dump do Postgres (tools/checar_offsite_pg.py).

Fixtures sintéticas (nenhum dump/estado real): árvore do snapshot com o mesmo
layout do rsync (-R → caminho absoluto) e tar de verdade montado no tmp_path.
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from tools import checar_offsite_pg as off

NOME_DUMP = "od-2026-11-25_0250.sql.gz"
CONTEUDO = b"SQL SINTETICO DO DUMP\n"


def _dump(tmp_path: Path) -> Path:
    dumps = tmp_path / "data" / "pg_dumps"
    dumps.mkdir(parents=True)
    arquivo = dumps / NOME_DUMP
    arquivo.write_bytes(CONTEUDO)
    return arquivo


def _snapshot(raiz: Path, nome: str = "snapshot_od-2026-11-25_0346") -> Path:
    pasta = raiz / nome
    copia = pasta / off.REPO_NO_SNAPSHOT / "data" / "pg_dumps"
    copia.mkdir(parents=True)
    (copia / NOME_DUMP).write_bytes(CONTEUDO)
    return pasta


def _tar(tmp_path: Path, nome: str = "od-2026-11-25_0301.tar.gz",
         conteudo_tar: bytes = CONTEUDO) -> Path:
    destino = tmp_path / "backups" / "auto"
    destino.mkdir(parents=True)
    caminho = destino / nome
    with tarfile.open(caminho, "w:gz") as tf:
        dados = io.BytesIO(conteudo_tar)
        info = tarfile.TarInfo(f"data/pg_dumps/{NOME_DUMP}")
        info.size = len(conteudo_tar)
        tf.addfile(info, dados)
    return caminho


def _estado(tmp_path: Path, tar: Path, sha: str | None = None) -> Path:
    estado = tmp_path / "data" / "offsite_state.json"
    estado.parent.mkdir(parents=True, exist_ok=True)
    estado.write_text(json.dumps({
        "diario": {
            "arquivo": tar.name,
            "sha256": sha or off.sha256_de(tar),
            "bytes": tar.stat().st_size,
        }
    }), encoding="utf-8")
    return estado


def test_ok_quando_canal_e_hd_tem_o_mesmo_sha(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    _snapshot(tmp_path / "od_snapshots")
    resumo = off.verificar(
        dump,
        snapshots=(str(tmp_path / "od_snapshots"),),
        estado_path=_estado(tmp_path, tar),
        tar_dir=tar.parent,
    )
    assert resumo["ok"] is True
    assert resumo["divergente"] is False
    assert resumo["canal"]["status"] == "ok"
    assert resumo["hds"][0]["status"] == "ok"


def test_hd_desplugada_nao_e_divergencia(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    resumo = off.verificar(
        dump,
        snapshots=(str(tmp_path / "nao-existe"),),
        estado_path=_estado(tmp_path, tar),
        tar_dir=tar.parent,
    )
    assert resumo["divergente"] is False
    assert resumo["ok"] is True  # o canal já prova a cópia
    assert resumo["hds"][0]["status"] == "ausente"


def test_snapshot_anterior_ao_dump_fica_aguardando(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    _snapshot(tmp_path / "od", nome="snapshot_od-2026-11-24_0344")
    resumo = off.verificar(
        dump,
        snapshots=(str(tmp_path / "od"),),
        estado_path=_estado(tmp_path, tar),
        tar_dir=tar.parent,
    )
    assert resumo["hds"][0]["status"] == "aguardando"
    assert resumo["divergente"] is False


def test_copia_do_hd_com_conteudo_diferente_derruba(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    pasta = _snapshot(tmp_path / "od")
    (pasta / off.REPO_NO_SNAPSHOT / "data" / "pg_dumps" / NOME_DUMP).write_bytes(
        b"outro conteudo"
    )
    resumo = off.verificar(
        dump,
        snapshots=(str(tmp_path / "od"),),
        estado_path=_estado(tmp_path, tar),
        tar_dir=tar.parent,
    )
    assert resumo["hds"][0]["status"] == "divergente"
    assert resumo["divergente"] is True
    assert resumo["ok"] is False


def test_dump_ausente_no_snapshot_novo_derruba(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    pasta = _snapshot(tmp_path / "od")
    (pasta / off.REPO_NO_SNAPSHOT / "data" / "pg_dumps" / NOME_DUMP).unlink()
    resumo = off.verificar(
        dump,
        snapshots=(str(tmp_path / "od"),),
        estado_path=_estado(tmp_path, tar),
        tar_dir=tar.parent,
    )
    assert resumo["hds"][0]["status"] == "divergente"
    assert "não está no snapshot" in resumo["hds"][0]["motivo"]


def test_tar_diferente_do_enviado_derruba(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    estado = _estado(tmp_path, tar, sha="0" * 64)
    resumo = off.verificar(
        dump, snapshots=(), estado_path=estado, tar_dir=tar.parent
    )
    assert resumo["canal"]["status"] == "divergente"
    assert "não é o que foi enviado" in resumo["canal"]["motivo"]
    assert resumo["ok"] is False


def test_dump_dentro_do_tar_com_outro_conteudo_derruba(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path, conteudo_tar=b"dump de outro dia")
    resumo = off.verificar(
        dump,
        snapshots=(),
        estado_path=_estado(tmp_path, tar),
        tar_dir=tar.parent,
    )
    assert resumo["canal"]["status"] == "divergente"
    assert "sha256 diferente" in resumo["canal"]["motivo"]


def test_tar_registrado_que_sumiu_do_disco_derruba(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    estado = _estado(tmp_path, tar)
    tar.unlink()
    resumo = off.verificar(
        dump, snapshots=(), estado_path=estado, tar_dir=tar.parent
    )
    assert resumo["canal"]["status"] == "divergente"
    assert "não existe" in resumo["canal"]["motivo"]


def test_sem_registro_de_envio_nao_prova_nem_derruba(tmp_path: Path) -> None:
    dump = _dump(tmp_path)
    resumo = off.verificar(
        dump,
        snapshots=(),
        estado_path=tmp_path / "sem_estado.json",
        tar_dir=tmp_path,
    )
    assert resumo["canal"]["status"] == "ausente"
    assert resumo["divergente"] is False
    assert resumo["ok"] is False  # nada provado: não é "OK"


def test_cli_dump_inexistente_sai_1(tmp_path: Path, capsys) -> None:
    codigo = off.main(["--dump", str(tmp_path / "nada.sql.gz")])
    assert codigo == 1
    assert "dump não encontrado" in capsys.readouterr().err


def test_cli_json_com_arvore_completa(tmp_path: Path, capsys) -> None:
    dump = _dump(tmp_path)
    tar = _tar(tmp_path)
    _snapshot(tmp_path / "od")
    codigo = off.main([
        "--dump", str(dump),
        "--snapshots", str(tmp_path / "od"),
        "--estado", str(_estado(tmp_path, tar)),
        "--tar-dir", str(tar.parent),
        "--json",
    ])
    assert codigo == 0
    resumo = json.loads(capsys.readouterr().out)
    assert resumo["ok"] is True
    assert resumo["dump"] == NOME_DUMP
    assert resumo["sha256"] == off.sha256_de(dump)


def test_selo_do_nome_ordena_por_data(tmp_path: Path) -> None:
    a = off.selo_do_nome("od-2026-11-09_2359.sql.gz", off.PADRAO_DUMP)
    b = off.selo_do_nome("od-2026-11-10_0001.sql.gz", off.PADRAO_DUMP)
    assert a < b
    assert off.selo_do_nome("snapshot_od-2026-11-25_0346",
                            off.PADRAO_SNAPSHOT) == "2026-11-25_0346"


@pytest.mark.parametrize("nome", ["od-estranho.sql.gz", "od-2026-11-25_0250.txt"])
def test_dump_fora_do_padrao_nunca_e_o_mais_novo(tmp_path: Path, nome: str) -> None:
    dumps = tmp_path / "data" / "pg_dumps"
    dumps.mkdir(parents=True)
    (dumps / nome).write_bytes(b"x")
    assert off.dump_mais_novo(dumps) is None
