#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_resilience.py
Descrição: Circuit breaker (R2) — estados, janela de recuperação, registro
           global e integração com o OpenAICompatProvider.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio

import pytest

from core import resilience
from core.llm import LLMError, OpenAICompatProvider
from core.resilience import CircuitBreaker, obter_breaker, resetar_breakers


class RelogioFalso:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    for var in (
        resilience.ENV_LIGADO,
        resilience.ENV_FALHAS,
        resilience.ENV_RECUPERACAO,
    ):
        monkeypatch.delenv(var, raising=False)
    resetar_breakers()
    yield
    resetar_breakers()


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_comeca_fechado_e_permite(self):
        b = CircuitBreaker("teste", falhas_limite=2)
        assert b.estado() == resilience.FECHADO
        assert b.permitir() is True

    def test_abre_ao_atingir_o_limite(self):
        b = CircuitBreaker("teste", falhas_limite=3)
        b.registrar_falha("erro 1")
        b.registrar_falha("erro 2")
        assert b.estado() == resilience.FECHADO
        b.registrar_falha("erro 3")
        assert b.estado() == resilience.ABERTO
        assert b.permitir() is False
        assert b.status()["recusas"] == 1

    def test_abrir_e_imediato_sem_esperar_o_limite(self):
        """Cota estourada (429) abre na primeira falha: insistir só queima cota."""
        b = CircuitBreaker("teste", falhas_limite=5, recuperacao_s=30.0)
        b.abrir("HTTP 429 quota exceeded")
        assert b.estado() == resilience.ABERTO
        assert b.permitir() is False
        assert "429" in b.status()["ultimo_erro"]

    def test_abrir_desligado_nao_faz_nada(self):
        b = CircuitBreaker("teste", ligado=False)
        b.abrir("x")
        assert b.estado() == resilience.FECHADO

    def test_sucesso_zera_as_falhas(self):
        b = CircuitBreaker("teste", falhas_limite=3)
        b.registrar_falha()
        b.registrar_falha()
        b.registrar_sucesso()
        assert b.status()["falhas"] == 0
        b.registrar_falha()
        assert b.estado() == resilience.FECHADO

    def test_janela_de_recuperacao_meia_aberta(self):
        relogio = RelogioFalso()
        b = CircuitBreaker(
            "teste", falhas_limite=1, recuperacao_s=10.0, relogio=relogio
        )
        b.registrar_falha()
        assert b.permitir() is False

        relogio.avancar(10.0)
        assert b.estado() == resilience.MEIA_ABERTO
        assert b.permitir() is True

    def test_falha_em_meia_aberta_reabre(self):
        relogio = RelogioFalso()
        b = CircuitBreaker(
            "teste", falhas_limite=1, recuperacao_s=10.0, relogio=relogio
        )
        b.registrar_falha()
        relogio.avancar(10.0)
        assert b.permitir() is True
        b.registrar_falha()
        assert b.estado() == resilience.ABERTO
        assert b.permitir() is False

    def test_sucesso_em_meia_aberta_fecha(self):
        relogio = RelogioFalso()
        b = CircuitBreaker(
            "teste", falhas_limite=1, recuperacao_s=10.0, relogio=relogio
        )
        b.registrar_falha()
        relogio.avancar(10.0)
        b.permitir()
        b.registrar_sucesso()
        assert b.estado() == resilience.FECHADO
        assert b.status()["falhas"] == 0

    def test_desligado_permite_tudo(self, monkeypatch):
        monkeypatch.setenv(resilience.ENV_LIGADO, "0")
        b = CircuitBreaker("teste", falhas_limite=1)
        b.registrar_falha()
        assert b.estado() == resilience.FECHADO
        assert b.permitir() is True

    def test_executar_conta_falha_e_sucesso(self):
        b = CircuitBreaker("teste", falhas_limite=2)
        with pytest.raises(ValueError):
            b.executar(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert b.status()["falhas"] == 1
        assert b.executar(lambda: 42) == 42
        assert b.status()["sucessos"] == 1

    def test_executar_recusa_com_circuito_aberto(self):
        b = CircuitBreaker("teste", falhas_limite=1)
        b.registrar_falha()
        chamou = []
        with pytest.raises(RuntimeError, match="circuito aberto"):
            b.executar(lambda: chamou.append(1))
        assert chamou == []

    def test_registro_devolve_o_mesmo_breaker(self):
        a = obter_breaker("x")
        b = obter_breaker("x")
        assert a is b
        assert "x" in [s["nome"] for s in resilience.status_breakers()]

    def test_env_configura_limite_e_recuperacao(self, monkeypatch):
        monkeypatch.setenv(resilience.ENV_FALHAS, "9")
        monkeypatch.setenv(resilience.ENV_RECUPERACAO, "2.5")
        b = CircuitBreaker("teste")
        assert b.falhas_limite == 9
        assert b.recuperacao_s == 2.5


# ---------------------------------------------------------------------------
# Integração com o provider LLM
# ---------------------------------------------------------------------------

class TestProviderComDisjuntor:
    def _provider(self, post_chat):
        provider = OpenAICompatProvider(name="fake-r2", base_url="http://127.0.0.1:9")
        provider._post_chat = post_chat
        return provider

    def test_falhas_abrem_e_chamada_seguinte_nao_vai_a_rede(self, monkeypatch):
        monkeypatch.setenv(resilience.ENV_FALHAS, "2")
        chamadas = {"n": 0}

        def _falha(_body, _timeout):
            chamadas["n"] += 1
            raise LLMError("servidor fora")

        provider = self._provider(_falha)
        for _ in range(2):
            with pytest.raises(LLMError):
                asyncio.run(provider.generate("oi"))
        assert provider._breaker.estado() == resilience.ABERTO

        with pytest.raises(LLMError, match="circuito aberto"):
            asyncio.run(provider.generate("oi"))
        assert chamadas["n"] == 2  # a terceira não tocou a rede

    def test_sucesso_fecha_o_circuito(self, monkeypatch):
        monkeypatch.setenv(resilience.ENV_FALHAS, "1")
        provider = self._provider(
            lambda _body, _timeout: {"choices": [{"message": {"content": "ok"}}]}
        )
        assert asyncio.run(provider.generate("oi")) == "ok"
        assert provider._breaker.estado() == resilience.FECHADO

    def test_is_available_falso_com_circuito_aberto(self, monkeypatch):
        monkeypatch.setenv(resilience.ENV_FALHAS, "1")
        provider = self._provider(lambda _b, _t: (_ for _ in ()).throw(LLMError("fora")))
        with pytest.raises(LLMError):
            asyncio.run(provider.generate("oi"))
        assert provider.is_available() is False
