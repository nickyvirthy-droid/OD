"""
OMEGA DRAKON • TESTS
Módulo: tests/test_energia.py
Descrição: vigia de queda de energia por INFERÊNCIA (core/energia.py) —
           o no-break do dono não tem USB, então a queda é deduzida pelo
           sumiço simultâneo dos aparelhos da LAN (ARP). Aqui se prova a
           máquina de estados (normal → suspeita → confirmada → desligando),
           o cancelamento, a volta da energia, o desligamento executado UMA
           vez só, a leitura de /proc/net/arp e /proc/net/route, as duas
           actions e o check do /health. Nenhum teste desliga a máquina de
           verdade: o comando é injetado.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/energia.py (Detector, VigiaEnergia, leitores e pkcheck)
  - tools/actions/actions.py (energia_status/energia_cancelar)
  - runtime/launcher.py (_check_energia)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core import energia as mod
from core.energia import (
    CONFIRMADA,
    DESLIGANDO,
    NORMAL,
    SUSPEITA,
    ConfigEnergia,
    Detector,
    Sinais,
    VigiaEnergia,
    ler_arp,
    ler_gateway,
)
from runtime.launcher import _check_energia
from tools.actions import CATALOG
from tools.actions.actions import energia_cancelar, energia_status


def _cfg(**kw: Any) -> ConfigEnergia:
    base = dict(
        intervalo_s=1.0, min_ancoras=2, quorum=0.5, ciclos_suspeita=2,
        segundos_confirmar=30.0, carencia_s=60.0, desligar=True,
        comando="true",
    )
    base.update(kw)
    return ConfigEnergia(**base)


class _Relogio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, s: float) -> None:
        self.t += s


def _vigia(relogio: _Relogio | None = None, **kw: Any) -> tuple[VigiaEnergia, list[str], list[Any], _Relogio]:
    relogio = relogio or _Relogio()
    avisos: list[str] = []
    desligamentos: list[Any] = []
    presentes: set[str] = set()

    def ler() -> set[str]:
        return set(presentes)

    v = VigiaEnergia(
        cfg=kw.pop("cfg", _cfg()),
        agora=relogio,
        ler_presentes=ler,
        ler_gateway_fn=lambda: "192.168.0.1",
        sink=lambda texto: avisos.append(texto),
        desligar_fn=lambda: desligamentos.append(relogio.t),
        autorizado_fn=lambda: {"autorizado": True, "motivo": ""},
        arquivo_estado=kw.pop("arquivo_estado", Path("data/_teste_energia.json")),
        arquivo_cancelar=Path("data/_teste_energia.flag"),
        **kw,
    )
    v._presentes_fn = ler  # type: ignore[attr-defined]
    v._presentes = presentes  # type: ignore[attr-defined]
    return v, avisos, desligamentos, relogio


def _ligar_dispositivos(v: VigiaEnergia, *ips: str) -> None:
    v._presentes.clear()  # type: ignore[attr-defined]
    v._presentes.update(ips)  # type: ignore[attr-defined]


class TestDetector:
    def test_suspeita_depois_de_ciclos(self) -> None:
        rel = _Relogio()
        d = Detector(_cfg(), agora=rel)
        sinais = Sinais(ancoras={"a", "b"}, visiveis=set())
        assert d.avaliar(sinais) == NORMAL       # 1º ciclo ainda não basta
        assert d.avaliar(sinais) == SUSPEITA     # 2º ciclo confirma o sumiço

    def test_presenca_parcial_nao_dispara(self) -> None:
        rel = _Relogio()
        d = Detector(_cfg(quorum=0.6), agora=rel)
        # 1 de 3 sumiu (33%) com quorum 60%: presença parcial não dispara
        sinais = Sinais(ancoras={"a", "b", "c"}, visiveis={"a", "b"})
        for _ in range(5):
            assert d.avaliar(sinais) == NORMAL

    def test_poucas_ancoras_nao_julga(self) -> None:
        d = Detector(_cfg(min_ancoras=3), agora=_Relogio())
        sinais = Sinais(ancoras={"a"}, visiveis=set())
        for _ in range(5):
            assert d.avaliar(sinais) == NORMAL

    def test_confirmada_e_desligando_com_tempo(self) -> None:
        rel = _Relogio()
        d = Detector(_cfg(), agora=rel)
        sinais = Sinais(ancoras={"a", "b"}, visiveis=set())
        d.avaliar(sinais); d.avaliar(sinais)
        assert d.estado == SUSPEITA
        rel.avancar(30)
        assert d.avaliar(sinais) == CONFIRMADA
        rel.avancar(59)
        assert d.avaliar(sinais) == CONFIRMADA
        rel.avancar(1)
        assert d.avaliar(sinais) == DESLIGANDO
        assert d.avaliar(sinais) == DESLIGANDO  # terminal

    def test_volta_da_energia_zera(self) -> None:
        rel = _Relogio()
        d = Detector(_cfg(), agora=rel)
        d.avaliar(Sinais(ancoras={"a", "b"}, visiveis=set()))
        d.avaliar(Sinais(ancoras={"a", "b"}, visiveis=set()))
        assert d.estado == SUSPEITA
        assert d.avaliar(Sinais(ancoras={"a", "b"}, visiveis={"a", "b"})) == NORMAL

    def test_cancelar_volta_para_normal(self) -> None:
        rel = _Relogio()
        d = Detector(_cfg(), agora=rel)
        sinais = Sinais(ancoras={"a", "b"}, visiveis=set())
        d.avaliar(sinais); d.avaliar(sinais)
        assert d.cancelar("teste") is True
        assert d.estado == NORMAL and d.cancelado is True
        assert d.cancelar("de novo") is False


class TestVigia:
    def test_desliga_uma_vez_so_e_avisa(self, tmp_path: Path) -> None:
        v, avisos, desligamentos, rel = _vigia(
            arquivo_estado=tmp_path / "estado.json")
        v.arquivo_cancelar = tmp_path / "cancela.flag"
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()  # aprende as âncoras
        _ligar_dispositivos(v)  # tudo sumiu
        v.tick(); v.tick()      # suspeita
        assert v.detector.estado == SUSPEITA
        assert any("sumiram da rede" in a for a in avisos)
        rel.avancar(30)
        v.tick()
        assert v.detector.estado == CONFIRMADA
        assert any("CONFIRMADA" in a for a in avisos)
        rel.avancar(60)
        v.tick()
        assert v.detector.estado == DESLIGANDO
        v.tick(); v.tick()
        assert len(desligamentos) == 1  # nunca desliga duas vezes
        estado = json.loads((tmp_path / "estado.json").read_text(encoding="utf-8"))
        assert estado["estado"] == DESLIGANDO

    def test_sem_permissao_avisa_e_nao_desliga(self, tmp_path: Path) -> None:
        v, avisos, desligamentos, rel = _vigia(
            arquivo_estado=tmp_path / "estado.json")
        v.arquivo_cancelar = tmp_path / "cancela.flag"
        v._autorizado_fn = lambda: {"autorizado": False, "motivo": "auth_admin_keep"}
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()
        _ligar_dispositivos(v)
        v.tick(); v.tick(); rel.avancar(30); v.tick(); rel.avancar(60); v.tick()
        assert desligamentos == []
        assert any("falta permissão" in a for a in avisos)

    def test_desarmado_nao_desliga_e_avisa(self, tmp_path: Path) -> None:
        v, avisos, desligamentos, rel = _vigia(
            cfg=_cfg(desligar=False), arquivo_estado=tmp_path / "estado.json")
        v.arquivo_cancelar = tmp_path / "cancela.flag"
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()
        _ligar_dispositivos(v)
        v.tick(); v.tick(); rel.avancar(30); v.tick(); rel.avancar(60); v.tick()
        assert desligamentos == []
        assert any("DESARMADO" in a for a in avisos)

    def test_cancelar_pelo_arquivo(self, tmp_path: Path) -> None:
        v, _avisos, _d, _rel = _vigia(arquivo_estado=tmp_path / "estado.json")
        v.arquivo_cancelar = tmp_path / "cancela.flag"
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()
        _ligar_dispositivos(v)
        v.tick(); v.tick()
        assert v.detector.estado == SUSPEITA
        v.arquivo_cancelar.write_text("dono pediu", encoding="utf-8")
        v.tick()
        assert v.detector.estado == NORMAL
        assert not v.arquivo_cancelar.exists()  # consumido

    def test_cancelar_metodo_avisa(self, tmp_path: Path) -> None:
        v, avisos, _d, _rel = _vigia(arquivo_estado=tmp_path / "estado.json")
        v.arquivo_cancelar = tmp_path / "cancela.flag"
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()
        _ligar_dispositivos(v)
        v.tick(); v.tick()
        assert v.cancelar("teste") is True
        assert v.detector.estado == NORMAL
        assert any("cancelado" in a for a in avisos)

    def test_queda_e_volta(self, tmp_path: Path) -> None:
        v, avisos, _d, _rel = _vigia(arquivo_estado=tmp_path / "estado.json")
        v.arquivo_cancelar = tmp_path / "cancela.flag"
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()
        _ligar_dispositivos(v)
        v.tick(); v.tick()
        assert v.detector.estado == SUSPEITA
        _ligar_dispositivos(v, "192.168.0.10", "192.168.0.11", "192.168.0.1")
        v.tick()
        assert v.detector.estado == NORMAL
        assert any("Energia de volta" in a for a in avisos)


class TestLeitores:
    def test_ler_arp_ignora_incompleto(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "arp"
        arquivo.write_text(
            "IP address       HW type     Flags       HW address            Mask     Device\n"
            "192.168.0.10     0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0\n"
            "192.168.0.11     0x1         0x0         00:00:00:00:00:00     *        eth0\n",
            encoding="utf-8",
        )
        assert ler_arp(str(arquivo)) == {"192.168.0.10"}

    def test_ler_arp_arquivo_ausente(self) -> None:
        assert ler_arp("/nao/existe/arp") == set()

    def test_ler_gateway(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "route"
        arquivo.write_text(
            "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
            "eth0\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n",
            encoding="utf-8",
        )
        assert ler_gateway(str(arquivo)) == "192.168.0.1"


class TestActionsEHealth:
    def test_status_le_o_estado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "estado_atual", lambda: {
            "estado": NORMAL, "ancoras": 4, "presentes": 4, "faltando": [],
            "autorizado": {"autorizado": True, "motivo": ""}, "desligar": True,
        })
        r = energia_status()
        assert r["ok"] is True and r["estado"] == NORMAL

    def test_cancelar_usa_o_modulo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "cancelar", lambda motivo: True)
        monkeypatch.setattr(mod, "estado_atual", lambda: {"estado": NORMAL})
        r = energia_cancelar("teste")
        assert r["ok"] is True and r["cancelado"] is True
        assert "cancelado" in r["message"].lower()

    def test_cancelar_sem_pendencia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "cancelar", lambda motivo: False)
        monkeypatch.setattr(mod, "estado_atual", lambda: {"estado": NORMAL})
        r = energia_cancelar()
        assert r["ok"] is False and "não havia" in r["message"].lower()

    def test_health_degrada_fora_do_normal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "estado_atual", lambda: {
            "estado": CONFIRMADA, "ancoras": 5, "faltando": ["a", "b", "c"],
            "autorizado": {"autorizado": True, "motivo": ""},
        })
        r = _check_energia(None)
        assert r["ok"] is False and r["status"] == "degraded"
        assert "confirmada" in r["detail"]

    def test_health_avisa_sem_permissao(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "estado_atual", lambda: {
            "estado": NORMAL, "ancoras": 3, "faltando": [],
            "autorizado": {"autorizado": False, "motivo": "auth_admin"},
        })
        r = _check_energia(None)
        assert r["ok"] is True
        assert "polkit" in r["detail"]

    def test_actions_no_catalogo(self) -> None:
        nomes = {s["name"] for s in CATALOG}
        assert {"energia_status", "energia_cancelar"} <= nomes
