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


def _checks(**falhando: bool) -> dict[str, dict]:
    nomes = {"database", "orchestrator", "backup", "offsite", "units_instaladas",
             "mqtt", "tool_homebox"}
    mapa = {n: {"ok": True} for n in nomes}
    for nome, ok in falhando.items():
        mapa[nome] = {"ok": ok}
    return mapa


def test_containers_subindo_nao_viram_falha(monkeypatch) -> None:
    """Boot de 26/11: /health 'degraded' só por container começando = OK."""
    monkeypatch.setattr(v, "uptime_s", lambda: 22.0)
    primeiro = {"status": "degraded", "_espera_s": 6.1,
                "checks": _checks(mqtt=False, tool_homebox=False)}
    depois = {"status": "up", "checks": _checks()}
    monkeypatch.setattr(v, "esperar_health", lambda timeout_s=180: primeiro)
    monkeypatch.setattr(v, "_ler_health", lambda timeout=10: depois)
    monkeypatch.setattr(v.time, "sleep", lambda s: None)
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: False)

    r = v.coletar()

    assert r["ok"] is True
    assert r["problemas"] == []
    assert r["containers_pendentes"] == []
    assert r["checks_falhando"] == []
    assert r["health_status"] == "up"
    texto = v.texto_relatorio(r)
    assert texto.startswith("🟢 Pós-reboot OK")
    assert "checks falhando" not in texto


def test_container_que_nao_sobe_na_janela_vira_pendencia(monkeypatch) -> None:
    monkeypatch.setattr(v, "JANELA_TRANSITORIOS_S", 0)
    monkeypatch.setattr(v, "uptime_s", lambda: 40.0)
    estado = {"status": "degraded", "_espera_s": 5.0,
              "checks": _checks(tool_homebox=False)}
    monkeypatch.setattr(v, "esperar_health", lambda timeout_s=180: estado)
    monkeypatch.setattr(v, "_ler_health", lambda timeout=10: estado)
    monkeypatch.setattr(v.time, "sleep", lambda s: None)
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: False)

    r = v.coletar()

    assert r["ok"] is False
    assert r["containers_pendentes"] == ["tool_homebox"]
    assert any("containers/broker ainda falhando: tool_homebox" in p
               for p in r["problemas"])
    texto = v.texto_relatorio(r)
    assert "🟠" in texto
    assert "containers ainda fora do ar: tool_homebox" in texto


def test_check_real_falhando_nao_ganha_carencia(monkeypatch) -> None:
    """Banco/orchestrator/backup falhou: não espera container, alarma já."""
    def nao_devia_reler(timeout=10):
        raise AssertionError("não devia reler o /health: há falha real")

    dormiu = {"n": 0}
    monkeypatch.setattr(v.time, "sleep", lambda s: dormiu.__setitem__("n", dormiu["n"] + 1))
    monkeypatch.setattr(v, "uptime_s", lambda: 40.0)
    monkeypatch.setattr(v, "esperar_health", lambda timeout_s=180: {
        "status": "degraded", "_espera_s": 5.0,
        "checks": _checks(database=False, tool_homebox=False),
    })
    monkeypatch.setattr(v, "_ler_health", nao_devia_reler)
    monkeypatch.setattr(v, "_cmd", _fake_cmd({}))
    monkeypatch.setattr(v, "reboot_pendente", lambda: False)

    r = v.coletar()

    assert dormiu["n"] == 0
    assert r["ok"] is False
    assert any("check database não está ok" in p for p in r["problemas"])
    assert r["containers_pendentes"] == ["tool_homebox"]


def test_relatorio_conta_a_espera_dos_containers() -> None:
    texto = v.texto_relatorio({
        "ok": True, "problemas": [], "uptime_s": 120.0, "recem_iniciado": True,
        "health_status": "up", "checks": 34, "espera_core_s": 6.1,
        "espera_transitorios_s": 12.0, "containers_pendentes": [],
        "checks_falhando": [], "servicos": {}, "timers": {},
        "kernel": "6.8.0-151-generic", "reboot_pendente": False,
    })

    assert "containers: subiram em ~12.0s (espera do boot)" in texto
