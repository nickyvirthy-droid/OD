"""
OMEGA DRAKON • TESTS
Módulo: tests/test_launcher_openai_credito.py
Descrição: Pendência do TODO — "incluir OpenAI na cadeia automaticamente
           quando as chaves tiverem saldo". Antes o `OD_OPENAI_AUTO` só
           checava se a CHAVE existia; as duas chaves do dono devolviam
           `429 no credits remaining` (medido 11/11) e o provider entrava na
           cadeia mesmo assim. Agora o boot faz uma sonda de 1 token e só
           inclui quem PROVA crédito.

           Nada aqui toca a rede: o provider é falso.
Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import pytest

from core.llm import LLMError
from runtime import launcher


class _ProviderFalso:
    """Sonda falsa: responde, devolve vazio ou levanta o erro pedido."""

    def __init__(self, resposta: str | None = "pong", erro: Exception | None = None) -> None:
        self.resposta = resposta
        self.erro = erro
        self.chamadas: list[dict] = []

    async def generate(self, prompt: str, **opcoes):
        self.chamadas.append({"prompt": prompt, **opcoes})
        if self.erro is not None:
            raise self.erro
        return self.resposta


class TestSondaDeCredito:
    def test_aprova_quando_responde(self) -> None:
        provider = _ProviderFalso("pong")
        assert launcher.openai_com_credito(provider, timeout=1.0) is True
        assert provider.chamadas, "a sonda precisa fazer uma chamada"
        # 1 token de resposta é o mínimo que prova crédito
        assert provider.chamadas[0]["timeout"] == 1.0

    def test_reprova_no_429_sem_credito(self) -> None:
        provider = _ProviderFalso(erro=LLMError("openai HTTP 429: no credits remaining"))
        assert launcher.openai_com_credito(provider, timeout=1.0) is False

    def test_reprova_em_qualquer_falha_de_rede(self) -> None:
        provider = _ProviderFalso(erro=TimeoutError("timed out"))
        assert launcher.openai_com_credito(provider, timeout=1.0) is False

    def test_reprova_quando_resposta_vazia(self) -> None:
        assert launcher.openai_com_credito(_ProviderFalso(None), timeout=1.0) is False

    def test_sonda_nunca_levantar(self) -> None:
        """Boot não pode morrer por causa da sonda."""
        class _Explode:
            async def generate(self, *_a, **_k):
                raise RuntimeError("boom")

        assert launcher.openai_com_credito(_Explode(), timeout=1.0) is False


class TestCadeiaNoBoot:
    def _nomes(self, monkeypatch, aprovado: bool) -> list[str]:
        # `env()` lê um SNAPSHOT do boot (`_ENV_CACHE`): monkeypatch nele, não
        # no os.environ — senão o .env real do projeto vaza para o teste.
        monkeypatch.setattr(
            launcher,
            "_ENV_CACHE",
            {
                "OD_OPENAI_AUTO": "1",
                "OPENAI_API_KEY": "sk-teste-sem-valor",
                "OD_CHAT_PROVIDERS": "gemini,groq,local",
            },
        )
        monkeypatch.setattr(launcher, "openai_com_credito", lambda *_a, **_k: aprovado)
        return [p.name for p in launcher.build_llm_providers()]

    def test_inclui_openai_quando_a_sonda_aprova(self, monkeypatch) -> None:
        assert "openai" in self._nomes(monkeypatch, True)

    def test_exclui_openai_quando_a_sonda_reprova(self, monkeypatch) -> None:
        nomes = self._nomes(monkeypatch, False)
        assert "openai" not in nomes
        assert nomes, "a cadeia nunca fica vazia (o local entra)"

    def test_sem_flag_nao_sona_nada(self, monkeypatch) -> None:
        monkeypatch.setattr(
            launcher,
            "_ENV_CACHE",
            {
                "OPENAI_API_KEY": "sk-teste-sem-valor",
                "OD_CHAT_PROVIDERS": "gemini,groq,local",
            },
        )
        chamou = {"n": 0}

        def _sonda(*_a, **_k):
            chamou["n"] += 1
            return True

        monkeypatch.setattr(launcher, "openai_com_credito", _sonda)
        launcher.build_llm_providers()
        assert chamou["n"] == 0
