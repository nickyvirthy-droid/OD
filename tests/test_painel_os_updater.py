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


class TestSecoesDoCicloNoPainel:
    """As últimas seções do ciclo (apt, fwupdmgr, reboot) na tela.

    A rota de status já devolvia `secoes` (últimas 5 do estado) — o painel
    mostrava só o resumo numérico. O render é uma função PURA
    (`soSecoesHtml`), testada aqui no node como o `visaoCards`: assim a
    ordem (mais recente primeiro) e o escape não dependem de olhar a tela.
    """

    @staticmethod
    def _js() -> str:
        html = _ADMIN_PAGE_HTML
        return html[html.index("<script>") + len("<script>"):html.rindex("</script>")]

    _HARNESS = r"""
'use strict';
const fs = require('fs'), vm = require('vm');
const arquivo = process.argv[2];
function novoEl() {
  return { style: {}, dataset: {}, _attrs: {}, innerHTML: '', textContent: '',
    className: '', value: '', href: '', disabled: false,
    setAttribute(k, v) { this._attrs[k] = String(v); },
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : 'href'; },
    addEventListener() {}, appendChild() {},
    classList: { toggle() {}, add() {}, remove() { return true; },
                 contains() { return false; } } };
}
const document = { getElementById() { return novoEl(); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement() { return novoEl(); }, addEventListener() {},
  documentElement: novoEl(), body: novoEl(), readyState: 'complete' };
const window = { confirm() { return true; }, alert() {}, scrollTo() {},
  matchMedia() { return { matches: true, addEventListener() {} }; } };
const localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
const location = { href: '' };
const fetch = () => Promise.resolve({ ok: false, status: 401,
  json: async () => ({ ok: false }) });
const ctx = { document, window, localStorage, location, fetch, console,
  setInterval: () => 0, setTimeout: () => 0, clearTimeout: () => {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(arquivo, 'utf8'), ctx, { filename: arquivo });

console.log(JSON.stringify({
  vazio: ctx.soSecoesHtml([]),
  nulo: ctx.soSecoesHtml(null),
  cheio: ctx.soSecoesHtml([
    { timestamp: 1794273354.8, acao: 'apt_update', ok: true, detalhes: 'lido' },
    { timestamp: 1794273356.1, acao: 'apt_upgrade', ok: false,
      detalhes: '<b>falhou</b> & caiu' },
  ]),
}));
"""

    def test_secoes_ordenadas_escapadas_e_vazio_honesto(self, tmp_path: Path) -> None:
        import json as _json
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:  # pragma: no cover - máquina sem node
            return
        js = tmp_path / "admin.js"
        js.write_text(self._js(), encoding="utf-8")
        har = tmp_path / "har.js"
        har.write_text(self._HARNESS, encoding="utf-8")
        r = subprocess.run([node, str(har), str(js)], capture_output=True,
                           text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[:800]
        saida = _json.loads(r.stdout.strip().splitlines()[-1])

        assert "nenhuma seção registrada" in saida["vazio"]
        assert "nenhuma seção registrada" in saida["nulo"]

        cheio = saida["cheio"]
        # mais recente primeiro
        assert cheio.index("apt_upgrade") < cheio.index("apt_update")
        assert "falhou" in cheio and "ok" in cheio
        # detalhe escapado (nada de HTML cru do estado no painel)
        assert "&lt;b&gt;" in cheio and "<b>falhou</b>" not in cheio
        assert "&amp; caiu" in cheio

    def test_secao_tem_o_container_e_a_rota_alimenta(self) -> None:
        assert 'id="so-secoes"' in _ADMIN_PAGE_HTML
        assert "soSecoesHtml(d.secoes)" in _ADMIN_PAGE_HTML

    def test_status_entrega_as_ultimas_cinco_secoes(self, monkeypatch, tmp_path: Path) -> None:
        """A rota não inventa seções: entrega as 5 últimas do estado."""
        from core import os_updater as osu_mod

        monkeypatch.setattr(osu_mod, "_precisa_reboot", lambda: False)
        monkeypatch.setattr(
            osu_mod, "_contar_pacotes_e_firmware", lambda agora, intervalo: (1, 0)
        )
        monkeypatch.setattr(osu_mod, "_kernel_atual", lambda: "k")
        monkeypatch.setattr(osu_mod, "unidade_em_andamento", lambda: False)
        secoes = [
            {"timestamp": float(i), "acao": f"passo{i}", "ok": True, "detalhes": ""}
            for i in range(7)
        ]
        estado = tmp_path / "estado.json"
        estado.write_text(
            '{"secoes": ' + __import__("json").dumps(secoes) + "}", encoding="utf-8"
        )
        assert osu_mod.status_painel(estado)["secoes"] == secoes[-5:]
