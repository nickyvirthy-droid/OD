"""
OMEGA DRAKON • TESTS
Módulo: tests/test_colapso.py
Descrição: modo colapso declarado (P1 nº 6) — quando a nuvem cai, o OD passa
           a responder só com a IA local, DIZ isso na resposta e no /health,
           e volta sozinho quando a internet retorna (colapso automático) ou
           só por ordem (colapso manual). Nada aqui chama LLM de verdade: os
           providers são dublês e a sonda de internet é injetada.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti

Baseado em:
  - core/colapso.py (estado persistido, falhas, monitor)
  - core/orchestrator.py (_provider_bloqueado, prefixo na resposta)
  - tools/actions/actions.py (action colapso)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core import colapso as mod
from core.colapso import MonitorColapso, eh_local, registrar_falha, registrar_sucesso
from core.orchestrator import Orchestrator
from tools.actions import CATALOG
from tools.actions.actions import colapso


@pytest.fixture(autouse=True)
def _limpo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Estado isolado por teste (nunca toca o colapso real em data/)."""
    mod.resetar()
    monkeypatch.setattr(mod, "ARQUIVO", tmp_path / "colapso.json")
    monkeypatch.setenv("OD_COLAPSO_FALHAS", "3")
    yield
    mod.resetar()


class _Provider:
    def __init__(self, nome: str, resposta: str = "ok", falha: bool = False) -> None:
        self.name = nome
        self.base_url = "https://exemplo.invalid/v1"
        self._resposta = resposta
        self._falha = falha
        self.chamadas = 0

    async def generate(self, prompt: str, **kw: Any) -> str:
        self.chamadas += 1
        if self._falha:
            raise RuntimeError("nuvem fora")
        return self._resposta


class _ProviderLocal(_Provider):
    def __init__(self, resposta: str = "resposta local") -> None:
        super().__init__("gemma-local", resposta)
        self.base_url = "http://127.0.0.1:8080/v1"


class TestEstado:
    def test_comeca_normal(self) -> None:
        assert mod.ativo() is False
        assert mod.estado()["motivo"] == ""

    def test_declarar_e_revogar(self) -> None:
        mod.declarar("teste", origem="manual")
        assert mod.ativo() is True
        assert "⚡" in mod.resumo_para_resposta()
        mod.revogar("teste")
        assert mod.ativo() is False
        assert mod.resumo_para_resposta() == ""

    def test_persiste_em_disco(self, tmp_path: Path) -> None:
        mod.declarar("queda", origem="automatico")
        dados = json.loads((tmp_path / "colapso.json").read_text(encoding="utf-8"))
        assert dados["ativo"] is True and dados["origem"] == "automatico"

    def test_eh_local_por_nome_e_url(self) -> None:
        assert eh_local(_ProviderLocal()) is True
        assert eh_local(_Provider("groq")) is False
        class _Url:
            name = "x"
            base_url = "http://localhost:1234/v1"
        assert eh_local(_Url()) is True


class TestFalhas:
    def test_tres_falhas_declaram(self) -> None:
        assert registrar_falha("groq")["ativo"] is False
        assert registrar_falha("gemini")["ativo"] is False
        est = registrar_falha("openai")
        assert est["ativo"] is True
        assert est["origem"] == "automatico"
        assert "3 falhas" in est["motivo"]

    def test_falha_de_local_nao_conta(self) -> None:
        for _ in range(5):
            registrar_falha("gemma-local")
        assert mod.ativo() is False

    def test_sucesso_de_nuvem_revoga_automatico(self) -> None:
        for _ in range(3):
            registrar_falha("groq")
        assert mod.ativo() is True
        registrar_sucesso("groq")
        assert mod.ativo() is False

    def test_sucesso_nao_revoga_manual(self) -> None:
        mod.declarar("ordem do dono", origem="manual")
        registrar_sucesso("groq")
        assert mod.ativo() is True


class TestMonitor:
    def test_revoga_apos_duas_sondas_ok(self) -> None:
        mod.declarar("internet caiu", origem="automatico")
        m = MonitorColapso(probe=lambda: True)
        m.tick()
        assert mod.ativo() is True
        m.tick()
        assert mod.ativo() is False

    def test_nao_revoga_manual(self) -> None:
        mod.declarar("ordem", origem="manual")
        m = MonitorColapso(probe=lambda: True)
        m.tick(); m.tick(); m.tick()
        assert mod.ativo() is True

    def test_avisa_quando_volta(self) -> None:
        avisos: list[str] = []
        mod.declarar("internet caiu", origem="automatico")
        m = MonitorColapso(probe=lambda: True, sink=lambda t: avisos.append(t))
        m.tick(); m.tick()
        assert any("Nuvem de volta" in a for a in avisos)


class TestOrquestrador:
    @pytest.mark.asyncio
    async def test_colapso_pula_nuvem_e_usa_local(self) -> None:
        nuvem = _Provider("groq", falha=True)
        local = _ProviderLocal()
        orch = Orchestrator(providers=[nuvem, local])
        mod.declarar("teste", origem="manual")
        resultado = await orch.process("teste", "admin", "oi")
        assert nuvem.chamadas == 0
        assert local.chamadas == 1
        assert resultado.message.startswith("⚡ modo colapso")

    @pytest.mark.asyncio
    async def test_sem_colapso_tenta_nuvem_primeiro(self) -> None:
        nuvem = _Provider("groq", resposta="da nuvem")
        local = _ProviderLocal()
        orch = Orchestrator(providers=[nuvem, local])
        resultado = await orch.process("teste", "admin", "oi")
        assert nuvem.chamadas == 1
        assert local.chamadas == 0
        assert resultado.message == "da nuvem"


class TestAction:
    def test_status(self) -> None:
        r = colapso()
        assert r["ok"] is True and r["ativo"] is False
        assert "internet_ok" in r

    def test_ligar_e_desligar(self) -> None:
        assert colapso("ligar")["ativo"] is True
        assert "só IA local" in colapso("ligar")["mensagem"]
        assert colapso("desligar")["ativo"] is False

    def test_acao_invalida(self) -> None:
        r = colapso("explodir")
        assert r["ok"] is False and r["error"] == "colapso_acao_invalida"

    def test_no_catalogo(self) -> None:
        specs = {s["name"]: s for s in CATALOG}
        assert "colapso" in specs
        assert specs["colapso"]["params"]["properties"]["acao"]["default"] == "status"
