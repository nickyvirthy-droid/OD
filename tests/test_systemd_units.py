"""Verificador de units: o que está em `systemd/` mas o systemd não conhece.

Dois casos reais em 26/11 (`od-os-updater`, `od-io-probe`) ficaram `not-found`
por dias com a unit versionada — o sintoma só aparecia indiretamente (arquivo
velho → `latencia` degraded). Aqui a comparação é direta e barata.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core import systemd_units as su


def _dir(tmp_path: Path, nomes: list[str]) -> Path:
    d = tmp_path / "systemd"
    d.mkdir()
    for n in nomes:
        (d / n).write_text("[Unit]\nDescription=x\n", encoding="utf-8")
    return d


def _fake_systemctl(monkeypatch, *, system: set[str], user: set[str] | None = None,
                    falhar: bool = False) -> None:
    def fake(cmd, **kwargs):
        if falhar:
            raise OSError("systemctl não existe")
        nomes = system if "--user" not in cmd else (user or set())
        saida = "".join(f"{n} enabled enabled\n" for n in sorted(nomes))
        return subprocess.CompletedProcess(cmd, 0, saida, "")

    monkeypatch.setattr(su.subprocess, "run", fake)
    su.limpar_cache()


def test_lista_units_do_repo_e_ignora_outros_arquivos(tmp_path: Path) -> None:
    d = _dir(tmp_path, ["a.service", "b.timer"])
    (d / "notas.txt").write_text("x", encoding="utf-8")
    assert su.units_do_repo(d) == ["a.service", "b.timer"]


def test_unit_versionada_mas_nao_instalada_aparece(
    monkeypatch, tmp_path: Path
) -> None:
    d = _dir(tmp_path, ["a.service", "b.timer", "c.service"])
    _fake_systemctl(monkeypatch, system={"a.service"}, user={"b.timer"})

    r = su.verificar(d, usar_cache=False)

    assert r["ok"] is False
    assert r["faltando"] == ["c.service"]
    assert r["total"] == 3


def test_tudo_instalado_entre_system_e_user(monkeypatch, tmp_path: Path) -> None:
    d = _dir(tmp_path, ["a.service", "b.timer"])
    _fake_systemctl(monkeypatch, system={"a.service"}, user={"b.timer"})

    r = su.verificar(d, usar_cache=False)

    assert r == {"ok": True, "faltando": [], "total": 2, "erro": ""}


def test_systemctl_ausente_nao_acusa_o_dono(monkeypatch, tmp_path: Path) -> None:
    """Sem `systemctl` não dá para afirmar que falta algo."""
    d = _dir(tmp_path, ["a.service"])
    _fake_systemctl(monkeypatch, system=set(), falhar=True)

    r = su.verificar(d, usar_cache=False)

    assert r["ok"] is False and r["faltando"] == []
    assert "indisponível" in r["erro"]


def test_cache_de_cinco_minutos_evita_systemctl_a_cada_health(
    monkeypatch, tmp_path: Path
) -> None:
    d = _dir(tmp_path, ["a.service"])
    chamadas: list[list[str]] = []

    def fake(cmd, **kwargs):
        chamadas.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "a.service enabled enabled\n", "")

    monkeypatch.setattr(su.subprocess, "run", fake)
    su.limpar_cache()

    su.verificar(d, agora=1000.0)
    su.verificar(d, agora=1100.0)   # dentro dos 5 min → cache
    assert len(chamadas) == 2       # system + user, uma vez só

    su.verificar(d, agora=1000.0 + 301)  # expirou
    assert len(chamadas) == 4


def test_check_do_health_registra_status_degraded(monkeypatch, tmp_path: Path) -> None:
    from runtime import launcher

    class _Mon:
        def __init__(self) -> None:
            self.checks: dict = {}

        def register(self, nome, fn, critical=True):  # noqa: ANN001
            self.checks[nome] = (fn, critical)

    monkeypatch.setattr(
        su, "verificar",
        lambda *a, **k: {"ok": False, "faltando": ["x.service"], "total": 2,
                         "erro": ""},
    )
    mon = _Mon()
    launcher.register_units_health(mon)

    fn, critical = mon.checks["units_instaladas"]
    r = fn(mon)
    assert critical is False
    assert r["ok"] is False and r["status"] == "degraded"
    assert "x.service" in r["detail"] and "1 de 2" in r["detail"]
