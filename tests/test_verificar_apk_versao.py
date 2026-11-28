"""Testes do verificador de versão dos APKs (tools/verificar_apk_versao.py)."""

from __future__ import annotations

import os
import stat

import pytest

from tools import verificar_apk_versao as vv

BADGING_2082 = (
    "package: name='com.omegadrakon.nicky' versionCode='2082' "
    "versionName='1.45.1' platformBuildVersionName='17'"
)
BADGING_4082 = BADGING_2082.replace("2082", "4082")


def _aapt_falso(tmp_path, conteudo: str):
    """aapt de mentira que imprime um badging fixo."""
    arquivo = tmp_path / "badging.txt"
    arquivo.write_text(conteudo, encoding="utf-8")
    script = tmp_path / "aapt"
    script.write_text(f'#!/bin/sh\ncat "{arquivo}"\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _pubspec(tmp_path, versao="1.45.1+2082"):
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text(f'name: app\nversion: {versao}\n', encoding="utf-8")
    return pubspec


def _apks(tmp_path, *nomes):
    caminhos = []
    for nome in nomes:
        caminho = tmp_path / nome
        caminho.write_bytes(b"PK-fake")
        caminhos.append(caminho)
    return caminhos


def _ambiente_sem_aapt(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.delenv("OD_AAPT", raising=False)


def test_dois_apks_com_a_versao_do_pubspec(tmp_path, capsys):
    aapt = _aapt_falso(tmp_path, BADGING_2082)
    apks = _apks(tmp_path, "OmegaDrakon.apk", "OmegaDrakon-arm64.apk")

    codigo = vv._principal(
        ["--pubspec", str(_pubspec(tmp_path)), "--aapt", str(aapt), "--apk", *map(str, apks)]
    )

    saida = capsys.readouterr()
    assert codigo == 0
    assert "OK: 2 APK(s) com 1.45.1+2082" in saida.out


def test_versioncode_com_offset_de_abi_falha_com_dica(tmp_path, capsys):
    aapt = _aapt_falso(tmp_path, BADGING_4082)
    apks = _apks(tmp_path, "OmegaDrakon-arm64.apk")

    codigo = vv._principal(
        ["--pubspec", str(_pubspec(tmp_path)), "--aapt", str(aapt), "--apk", *map(str, apks)]
    )

    erros = capsys.readouterr().err
    assert codigo == 1
    assert "versionCode 4082" in erros
    assert "+2000" in erros
    assert "force-version-code-ignoring-abi" in erros


def test_versionname_divergente_falha(tmp_path, capsys):
    aapt = _aapt_falso(tmp_path, BADGING_2082.replace("1.45.1", "1.46.0"))
    apks = _apks(tmp_path, "OmegaDrakon.apk")

    codigo = vv._principal(
        ["--pubspec", str(_pubspec(tmp_path)), "--aapt", str(aapt), "--apk", *map(str, apks)]
    )

    erros = capsys.readouterr().err
    assert codigo == 1
    assert "versionName 1.46.0" in erros


def test_aapt_ausente_devolve_2(tmp_path, capsys, monkeypatch):
    _ambiente_sem_aapt(monkeypatch, tmp_path)
    apks = _apks(tmp_path, "OmegaDrakon.apk")

    codigo = vv._principal(
        ["--pubspec", str(_pubspec(tmp_path)), "--apk", *map(str, apks)]
    )

    assert codigo == 2
    assert "aapt não encontrado" in capsys.readouterr().err


def test_pubspec_sem_version_devolve_2(tmp_path, capsys):
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text("name: app\n", encoding="utf-8")
    aapt = _aapt_falso(tmp_path, BADGING_2082)

    codigo = vv._principal(
        ["--pubspec", str(pubspec), "--aapt", str(aapt), "--apk", str(tmp_path / "x.apk")]
    )

    assert codigo == 2
    assert "version: X.Y.Z+N" in capsys.readouterr().err


def test_apk_sem_badging_devolve_2(tmp_path, capsys):
    aapt = _aapt_falso(tmp_path, "lixo\n")
    apks = _apks(tmp_path, "OmegaDrakon.apk")

    codigo = vv._principal(
        ["--pubspec", str(_pubspec(tmp_path)), "--aapt", str(aapt), "--apk", *map(str, apks)]
    )

    assert codigo == 2
    assert "não é APK" in capsys.readouterr().err


def test_apk_inexistente_devolve_2(tmp_path, capsys):
    aapt = _aapt_falso(tmp_path, BADGING_2082)

    codigo = vv._principal(
        ["--pubspec", str(_pubspec(tmp_path)), "--aapt", str(aapt), "--apk", str(tmp_path / "nao.apk")]
    )

    assert codigo == 2
    assert "não existe" in capsys.readouterr().err


def test_descobrir_aapt_usa_explicito(tmp_path):
    aapt = _aapt_falso(tmp_path, BADGING_2082)
    assert vv.descobrir_aapt(str(aapt)) == str(aapt)


def test_ler_pubspec_com_sufixo_extra(tmp_path):
    pubspec = _pubspec(tmp_path, "1.47.0+2085")

    assert vv.ler_pubspec(pubspec) == ("1.47.0", 2085)
