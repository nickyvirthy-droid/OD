"""Validação pós-reboot: o que voltou depois do reboot (26/11).

Motivo: o veredito do retorno não pode depender da sessão do agente sobreviver
ao reboot — uma unit oneshot roda o validador no boot e manda no Telegram.
"""

from __future__ import annotations

import json

from tools import validar_pos_reboot as v


def _fake_cmd(mapa: dict[str, str], chave=lambda cmd: " ".join(cmd)):
    def fake(cmd, timeout=20):
        return 0, mapa.get(chave(cmd), "active")
    return fake


def test_recem_iniciado_marca_pos_reboot(monkeypatch) -> None:
    monkeypatch.setattr(v, "uptime_s", lambda: 90.0)
    monkeypatch.setattr(v, "esperar_health", lambda timeout_s=180: {
        "status": "up", "checks": {
            "database": {"ok": True}, "orchestrator": {"ok": True},
            "backup": {"ok": True}, "offsite": {"ok": True},
            "units_instaladas": {"ok": True},
        }, "_espera_s": 8.0,
    })
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: False)

    r = v.coletar()

    assert r["recem_iniciado"] is True
    assert r["ok"] is True and r["problemas"] == []
    texto = v.texto_relatorio(r)
    assert texto.startswith("🟢 Pós-reboot OK (uptime 1.5 min)")
    assert "34" not in texto and "5 checks" in texto


def test_servico_de_usuario_inativo_vira_problema(monkeypatch) -> None:
    monkeypatch.setattr(v, "uptime_s", lambda: 60.0)
    monkeypatch.setattr(v, "esperar_health", lambda timeout_s=180: {
        "status": "up", "checks": {}, "_espera_s": 1.0,
    })
    monkeypatch.setattr(v, "_is_active_usuario",
                        lambda nome: "inactive" if "azura" in nome else "active")
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: False)

    r = v.coletar()

    assert r["ok"] is False
    assert any("od-azura-proxy" in p and "inactive" in p for p in r["problemas"])
    assert "🟠" in v.texto_relatorio(r)


def test_health_fora_do_ar_e_problema(monkeypatch) -> None:
    monkeypatch.setattr(v, "uptime_s", lambda: 30.0)
    monkeypatch.setattr(v, "esperar_health",
                        lambda timeout_s=180: {"_erro": "URLError: refused",
                                               "_espera_s": 180.0})
    monkeypatch.setattr(v, "_is_active_usuario", lambda nome: "active")
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: False)

    r = v.coletar()

    assert r["ok"] is False
    assert any("/health não respondeu" in p for p in r["problemas"])


def test_checagem_manual_nao_se_diz_pos_reboot(monkeypatch) -> None:
    """Uptime alto = não foi reboot: o texto tem de dizer isso."""
    monkeypatch.setattr(v, "uptime_s", lambda: 27843 * 60.0)
    monkeypatch.setattr(v, "esperar_health", lambda timeout_s=180: {
        "status": "up", "checks": {}, "_espera_s": 0.1,
    })
    monkeypatch.setattr(v, "_is_active_usuario", lambda nome: "active")
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: True)  # reboot pendente

    r = v.coletar()

    assert r["recem_iniciado"] is False
    texto = v.texto_relatorio(r)
    assert "checagem manual" in texto
    assert "reboot pendente: sim" in texto


def test_estado_gravado_em_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(v, "ESTADO", tmp_path / "pos_reboot.json")
    monkeypatch.setattr(v, "coletar", lambda: {"ok": True, "problemas": [],
                                               "uptime_s": 60.0})

    assert v.main(["--sem-envio"]) == 0
    assert json.loads((tmp_path / "pos_reboot.json").read_text()) == {
        "ok": True, "problemas": [], "uptime_s": 60.0,
    }
