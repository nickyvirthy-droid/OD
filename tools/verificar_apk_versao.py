#!/usr/bin/env python3
"""Confere o versionName/versionCode real dos APKs contra o `app/pubspec.yaml`.

Motivo (medido em 28/11/2026): o `backups/apk-v1.45.1-2082/OmegaDrakon-arm64.apk`
saiu com **versionCode 4082** em vez de 2082 — 1000 × ABI (arm64 = 2) somado pelo
Flutter porque o build foi feito **fora do `app/build_apk.sh`**, sem
`-Pforce-version-code-ignoring-abi=true`. O app compara `versionCode` para se
auto-atualizar: um 4082 instalado nunca aceitaria builds 2xxx.

Este verificador lê a versão declarada e o badging real de cada APK e falha se
divergirem. O `app/build_apk.sh` chama ele antes de publicar em `site/`.

Uso:
    python3 tools/verificar_apk_versao.py                      # site/*.apk
    python3 tools/verificar_apk_versao.py --apk a.apk b.apk
    python3 tools/verificar_apk_versao.py --aapt /caminho/aapt

Saída: exit 0 tudo confere · 1 divergência · 2 não deu para medir (aapt/pubspec).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PUBSPEC_PADRAO = RAIZ / "app" / "pubspec.yaml"
SITE_PADRAO = RAIZ / "site"

RE_PUBSPEC = re.compile(r"^version:\s*([0-9][0-9A-Za-z.\-]*)\+(\d+)\s*$", re.M)
RE_BADGING = re.compile(
    r"package:\s+name='([^']*)'\s+versionCode='(\d+)'\s+versionName='([^']*)'"
)


class ErroMedicao(RuntimeError):
    """Não deu para medir (aapt ausente, pubspec inválido, APK ilegível)."""


def ler_pubspec(caminho: Path) -> tuple[str, int]:
    texto = caminho.read_text(encoding="utf-8")
    achado = RE_PUBSPEC.search(texto)
    if not achado:
        raise ErroMedicao(f"{caminho}: linha 'version: X.Y.Z+N' não encontrada")
    return achado.group(1), int(achado.group(2))


def descobrir_aapt(explicito: str | None = None) -> str:
    candidatos: list[str] = []
    if explicito:
        candidatos.append(explicito)
    if os.environ.get("OD_AAPT"):
        candidatos.append(os.environ["OD_AAPT"])
    encontrado = shutil.which("aapt")
    if encontrado:
        candidatos.append(encontrado)
    for raiz_sdk in (
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        str(Path.home() / "android-sdk"),
        str(Path.home() / "Android" / "Sdk"),
    ):
        if not raiz_sdk:
            continue
        pasta = Path(raiz_sdk) / "build-tools"
        if not pasta.is_dir():
            continue
        versoes = sorted(
            (p for p in pasta.iterdir() if (p / "aapt").is_file()),
            key=lambda p: p.name,
        )
        candidatos.extend(str(p / "aapt") for p in reversed(versoes))

    for caminho in candidatos:
        if caminho and Path(caminho).is_file() and os.access(caminho, os.X_OK):
            return caminho
    raise ErroMedicao(
        "aapt não encontrado — instale build-tools ou aponte com --aapt/OD_AAPT"
    )


def ler_apk(aapt: str, apk: Path) -> dict:
    if not apk.is_file():
        raise ErroMedicao(f"{apk}: arquivo não existe")
    try:
        saida = subprocess.run(
            [aapt, "dump", "badging", str(apk)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as erro:
        raise ErroMedicao(f"{apk}: falha ao executar aapt ({erro})") from erro
    achado = RE_BADGING.search(saida.stdout)
    if not achado:
        raise ErroMedicao(
            f"{apk}: aapt não devolveu 'package:' (arquivo corrompido ou não é APK)"
        )
    return {
        "pacote": achado.group(1),
        "versionCode": int(achado.group(2)),
        "versionName": achado.group(3),
    }


def conferir(
    apks: list[Path], esperado_name: str, esperado_code: int, aapt: str
) -> tuple[list[dict], list[str]]:
    """Devolve (medições, divergências em texto)."""
    medicoes: list[dict] = []
    problemas: list[str] = []
    for apk in apks:
        dados = ler_apk(aapt, apk)
        dados["arquivo"] = apk
        medicoes.append(dados)
        if dados["versionName"] != esperado_name:
            problemas.append(
                f"{apk.name}: versionName {dados['versionName']} "
                f"(esperado {esperado_name})"
            )
        if dados["versionCode"] != esperado_code:
            diferenca = dados["versionCode"] - esperado_code
            dica = ""
            if diferenca in (1000, 2000, 3000, 4000):
                dica = (
                    " — parece o offset 1000×ABI do Flutter: o build saiu do "
                    "app/build_apk.sh, que passa "
                    "-Pforce-version-code-ignoring-abi=true?"
                )
            problemas.append(
                f"{apk.name}: versionCode {dados['versionCode']} "
                f"(esperado {esperado_code}, diferença {diferenca:+d}){dica}"
            )
    return medicoes, problemas


def _principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", nargs="*", default=None)
    parser.add_argument("--pubspec", default=str(PUBSPEC_PADRAO))
    parser.add_argument("--aapt", default=None)
    args = parser.parse_args(argv)

    try:
        esperado_name, esperado_code = ler_pubspec(Path(args.pubspec))
        aapt = descobrir_aapt(args.aapt)
        if args.apk:
            apks = [Path(p) for p in args.apk]
        else:
            apks = sorted(SITE_PADRAO.glob("*.apk"))
            if not apks:
                raise ErroMedicao(f"{SITE_PADRAO}: nenhum .apk para conferir")
        medicoes, problemas = conferir(apks, esperado_name, esperado_code, aapt)
    except ErroMedicao as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 2

    for dados in medicoes:
        print(
            f"{dados['arquivo'].name}: {dados['versionName']}+"
            f"{dados['versionCode']} (pacote {dados['pacote']})"
        )
    if problemas:
        print(
            f"\nFALHOU: {len(problemas)} divergência(s) contra "
            f"{esperado_name}+{esperado_code} em {args.pubspec}:",
            file=sys.stderr,
        )
        for problema in problemas:
            print(f"  - {problema}", file=sys.stderr)
        return 1

    print(
        f"\nOK: {len(medicoes)} APK(s) com {esperado_name}+{esperado_code}, "
        f"igual ao pubspec."
    )
    return 0


if __name__ == "__main__":
    sys.exit(_principal())
