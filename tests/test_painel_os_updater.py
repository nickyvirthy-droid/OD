"""Painel do atualizador de SO — botão "Aplicar atualizações" (26/11).

Contexto medido: as três rotas `/admin/os-updater/*` respondiam **503 desde
10/11** porque `APIConfig` nunca teve o campo `os_updater` — o painel não
tinha como mostrar nada e muito menos agir. E o od-core roda como `alex`:
`apt full-upgrade` ali falharia (mesmo defeito da unit corrigida em 26/11).

Desenho provado aqui:
  * `POST /admin/os-updater/executar` **não** roda apt dentro da requisição:
    pede a unit oneshot root `od-os-updater-forcar.service` por
    `sudo -n systemctl start --no-block` e responde **202** na hora;
  * o comando é EXATO (é o que a regra do sudoers autoriza) — trocar a ordem
    dos argumentos ou usar caminho relativo quebraria o botão em silêncio;
  * falha de sudo devolve 503 com o motivo, nunca "ok" de mentira;
  * `GET /admin/os-updater/status` usa `status_painel()` (barato, sem apt);
  * `{"dry_run": true}` continua simulando em processo;
  * o HTML do painel tem o botão e **duas** confirmações.
"""

from __future__ import annotations

from pathlib import Path

from core import os_updater as osu_mod
from integrations.api.server import APIHandler, _ADMIN_PAGE_HTML


class _RotaFalsa:
    """Self falso das rotas do atualizador (mesmo padrão do reboot, 15/11)."""

    def __init__(self, body: dict | None = None, updater: object | None = None) -> None:
        self._body = body or {}
        self._updater = updater
        self.chamadas: list[tuple[int, dict]] = []

    def _require_admin(self) -> None:
        pass

    def _has_body(self) -> bool:
        return bool(self._body)

    def _read_json(self) -> dict:
        return self._body

    def _os_updater_or_503(self) -> object:
        if self._updater is None:  # pragma: no cover - caminho não exercitado
            raise AssertionError("updater não deveria ser instanciado aqui")
        return self._updater

    def _json(self, status: int, payload: dict) -> None:
        self.chamadas.append((status, payload))


class TestComandoDoBotao:
    def test_comando_exato_que_o_sudoers_autoriza(self, monkeypatch) -> None:
        """O botão só funciona se o comando for idêntico à regra do sudoers."""
        comandos: list[list[str]] = []

        def fake(cmd, **kwargs):  # noqa: ANN001
            comandos.append(list(cmd))
            return 0, "", ""

        monkeypatch.setattr(osu_mod, "_executar", fake)
        ok, msg = osu_mod.iniciar_ciclo_forcado()
        assert ok is True and msg == "ciclo solicitado"
        assert comandos == [[
            "sudo", "-n", "/usr/bin/systemctl", "start", "--no-block",
            "od-os-updater-forcar.service",
        ]]

    def test_falha_do_sudo_devolve_motivo(self, monkeypatch) -> None:
        monkeypatch.setattr(
            osu_mod,
            "_executar",
            lambda cmd, **k: (1, "", "sudo: a password is required"),
        )
        ok, motivo = osu_mod.iniciar_ciclo_forcado()
        assert ok is False
        assert "password" in motivo


class TestRotaExecutar:
    def test_inicia_e_responde_202_sem_rodar_apt(self, monkeypatch) -> None:
        monkeypatch.setattr(
            osu_mod, "iniciar_ciclo_forcado", lambda: (True, "ciclo solicitado")
        )
        rota = _RotaFalsa()
        APIHandler.admin_os_updater_executar(rota)
        status, payload = rota.chamadas[0]
        assert status == 202
        assert payload == {
            "ok": True,
            "iniciado": True,
            "unidade": "od-os-updater-forcar.service",
        }

    def test_falha_ao_iniciar_devolve_503_com_detalhe(self, monkeypatch) -> None:
        monkeypatch.setattr(
            osu_mod,
            "iniciar_ciclo_forcado",
            lambda: (False, "sudo: a password is required"),
        )
        rota = _RotaFalsa()
        APIHandler.admin_os_updater_executar(rota)
        status, payload = rota.chamadas[0]
        assert status == 503
        assert payload["erro"] == "nao_foi_possivel_iniciar"
        assert "password" in payload["detalhe"]

    def test_dry_run_simula_em_processo(self, monkeypatch) -> None:
        class _UpdaterFalso:
            dry_run = True

            def executar_ciclo(self, forcar: bool = False) -> dict:
                assert forcar is True
                return {"ok": True, "apt_update": True, "reboot_executado": False}

        rota = _RotaFalsa(body={"dry_run": True}, updater=_UpdaterFalso())
        APIHandler.admin_os_updater_executar(rota)
        status, payload = rota.chamadas[0]
        assert status == 200
        assert payload["dry_run"] is True and payload["apt_update"] is True


class TestRotaStatus:
    def test_status_usa_resumo_barato(self, monkeypatch) -> None:
        monkeypatch.setattr(
            osu_mod,
            "status_painel",
            lambda *a, **k: {
                "upgradable": 67,
                "firmware_upgrades": 51,
                "precisa_reboot": True,
                "falhas_consecutivas": 0,
                "em_andamento": False,
            },
        )
        rota = _RotaFalsa()
        APIHandler.admin_os_updater_status(rota)
        status, payload = rota.chamadas[0]
        assert status == 200 and payload["ok"] is True
        assert payload["upgradable"] == 67 and payload["em_andamento"] is False

    def test_status_painel_traz_estado_e_unidade(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(osu_mod, "_precisa_reboot", lambda: True)
        monkeypatch.setattr(
            osu_mod, "_contar_pacotes_e_firmware", lambda agora, intervalo: (67, 51)
        )
        monkeypatch.setattr(osu_mod, "_kernel_atual", lambda: "6.8.0-147-generic")
        monkeypatch.setattr(osu_mod, "unidade_em_andamento", lambda: True)
        estado = tmp_path / "estado.json"
        estado.write_text(
            '{"falhas_consecutivas": 1, "ultima_tentativa": 99.0,'
            ' "secoes": [{"acao": "apt_update", "ok": true}]}',
            encoding="utf-8",
        )
        s = osu_mod.status_painel(estado)
        assert s["upgradable"] == 67 and s["firmware_upgrades"] == 51
        assert s["falhas_consecutivas"] == 1
        assert s["ultima_tentativa"] == 99.0
        assert s["secoes"] == [{"acao": "apt_update", "ok": True}]
        assert s["em_andamento"] is True
        assert s["unidade"] == osu_mod.UNIDADE_FORCAR


class TestPainelHTML:
    def test_botao_e_duas_confirmacoes_no_html(self) -> None:
        assert 'id="so-aplicar"' in _ADMIN_PAGE_HTML
        assert "⚠ Aplicar atualizações" in _ADMIN_PAGE_HTML
        assert "/admin/os-updater/executar" in _ADMIN_PAGE_HTML
        # Duas confirmações: o código do handler tem exatamente dois confirm().
        inicio = _ADMIN_PAGE_HTML.index("async function soAplicar()")
        corpo = _ADMIN_PAGE_HTML[inicio:inicio + 1800]
        assert corpo.count("window.confirm(") == 2
        assert "REBOOT EM +5 MINUTOS" in corpo
        # O status do painel é carregado junto do resto (carregarTudo).
        assert "soLoad()" in _ADMIN_PAGE_HTML

    def test_unit_da_forcar_existe_e_forca_o_ciclo(self) -> None:
        raiz = Path(__file__).resolve().parents[1]
        unit = (raiz / "systemd" / "od-os-updater-forcar.service").read_text(
            encoding="utf-8"
        )
        assert "--forcar" in unit
        assert "DEBIAN_FRONTEND=noninteractive" in unit
        assert "EnvironmentFile=" in unit
