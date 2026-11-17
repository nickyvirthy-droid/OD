"""Rota POST /admin/os-updater/reboot — regressão do import (15/11).

A rota fazia `from core.os_updater import _precisa_reboot, _reboot`, mas
`_reboot` NÃO existe no módulo: é método de `OSUpdater`. O POST levantava
ImportError na hora de executar (bug achado pela frente de cobertura do
os_updater e confirmado por leitura do código). Coberto aqui: os três
desfechos da rota, com o método real da classe.
"""

from __future__ import annotations

from core import os_updater as osu_mod
from core.os_updater import OSUpdater
from integrations.api.server import APIHandler


class _RotaFalsa:
    """Self falso da rota: só o trio que `admin_os_updater_reboot` usa."""

    def __init__(self, updater: object) -> None:
        self._updater = updater
        self.chamadas: list[tuple[int, dict]] = []

    def _require_admin(self) -> None:
        pass

    def _os_updater_or_503(self) -> object:
        return self._updater

    def _json(self, status: int, payload: dict) -> None:
        self.chamadas.append((status, payload))


def _updater_real() -> OSUpdater:
    """Instância sem __init__: zero efeitos de disco/estado. dry_run=True
    faz o método real `_reboot` devolver o rascunho antes de tocar em
    qualquer subprocess."""
    updater = object.__new__(OSUpdater)
    updater.dry_run = True
    return updater


class TestRotaRebootOSUpdater:
    def test_sem_reboot_pendente_devolve_409(self, monkeypatch) -> None:
        monkeypatch.setattr(osu_mod, "_precisa_reboot", lambda: False)
        rota = _RotaFalsa(_updater_real())
        APIHandler.admin_os_updater_reboot(rota)
        status, payload = rota.chamadas[0]
        assert status == 409
        assert payload["motivo"] == "reboot_nao_necessario"

    def test_reboot_pendente_agenda_com_metodo_real(self, monkeypatch) -> None:
        """Prova que o método existe na classe (era ele que faltava)."""
        monkeypatch.setattr(osu_mod, "_precisa_reboot", lambda: True)
        rota = _RotaFalsa(_updater_real())
        APIHandler.admin_os_updater_reboot(rota)
        status, payload = rota.chamadas[0]
        assert status == 200
        assert payload == {"ok": True, "reboot": "agendado"}

    def test_falha_no_reboot_devolve_500(self, monkeypatch) -> None:
        monkeypatch.setattr(osu_mod, "_precisa_reboot", lambda: True)
        updater = _updater_real()
        updater._reboot = lambda: (False, "boom")  # type: ignore[method-assign]
        rota = _RotaFalsa(updater)
        APIHandler.admin_os_updater_reboot(rota)
        status, payload = rota.chamadas[0]
        assert status == 500
        assert payload == {"ok": False, "erro": "boom"}
