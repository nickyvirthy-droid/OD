"""Verificador de units: o que está em `systemd/` mas não foi instalado.

Dois casos reais em 26/11 (`od-os-updater`, `od-io-probe`) ficaram `not-found`
por dias mesmo com a unit versionada no repositório — o sintoma apareceu longe
da causa (timer sumido → arquivo velho → `latencia` degraded). Este módulo
compara os arquivos de `systemd/` com o que o systemd conhece e devolve o que
falta, para o `/health` avisar antes do sintoma.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Optional

REPO_DIR = Path(__file__).resolve().parent.parent
SYSTEMD_DIR = REPO_DIR / "systemd"
_CACHE: dict[str, Any] = {"em": 0.0, "resultado": None}
_CACHE_S = 300.0


def units_do_repo(systemd_dir: Path = SYSTEMD_DIR) -> list[str]:
    """Nomes das units versionadas (`*.service` e `*.timer`)."""
    if not systemd_dir.exists():  # pragma: no cover - instalação empacotada
        return []
    return sorted(
        p.name
        for p in systemd_dir.iterdir()
        if p.is_file() and p.suffix in (".service", ".timer")
    )


def units_conhecidas(timeout: int = 15) -> Optional[set[str]]:
    """O que o systemd conhece (system + user). `None` se `systemctl` falhar.

    `None` é diferente de conjunto vazio: sem `systemctl` não dá para afirmar
    que falta algo — e o check não deve acusar o dono por um erro de leitura.
    """
    nomes: set[str] = set()
    comandos = (
        ["systemctl", "list-unit-files", "--type=service,timer",
         "--no-legend", "--no-pager", "--plain"],
        ["systemctl", "--user", "list-unit-files", "--type=service,timer",
         "--no-legend", "--no-pager", "--plain"],
    )
    algum_ok = False
    for cmd in comandos:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode != 0:
            continue
        algum_ok = True
        for linha in r.stdout.splitlines():
            partes = linha.split()
            if partes:
                nomes.add(partes[0])
    return nomes if algum_ok else None


def verificar(
    systemd_dir: Path = SYSTEMD_DIR,
    *,
    agora: Optional[float] = None,
    usar_cache: bool = True,
) -> dict[str, Any]:
    """Compara repositório × systemd e devolve `{ok, faltando, total}`."""
    agora = time.time() if agora is None else agora
    if usar_cache and _CACHE["resultado"] is not None:
        if agora - float(_CACHE["em"]) < _CACHE_S:
            return dict(_CACHE["resultado"])

    repo = units_do_repo(systemd_dir)
    conhecidas = units_conhecidas()
    if conhecidas is None:
        resultado: dict[str, Any] = {
            "ok": False,
            "faltando": [],
            "total": len(repo),
            "erro": "systemctl indisponível",
        }
    else:
        faltando = [u for u in repo if u not in conhecidas]
        resultado = {
            "ok": not faltando,
            "faltando": faltando,
            "total": len(repo),
            "erro": "",
        }
    _CACHE["em"] = agora
    _CACHE["resultado"] = resultado
    return dict(resultado)


def limpar_cache() -> None:
    """Só para testes: zera o cache de 5 min."""
    _CACHE["em"] = 0.0
    _CACHE["resultado"] = None
