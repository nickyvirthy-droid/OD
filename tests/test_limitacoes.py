"""Casa de Limitações (v1.13.0) — o sistema registra o que NÃO sabe responder.

Cobertura: registro/dedup, teto de arquivo (poda do mais antigo), append
atômico, hooks do Orchestrator (fallback honesto + action degradada) e
contratos de leitura/limpeza para o painel admin.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.limitacoes import (
    DEDUP_WINDOW_S,
    LIMITACOES_FILE,
    LIMITACOES_MAX_BYTES,
    ler_limitacoes,
    limpar_limitacoes,
    registrar_action_degradada,
    registrar_fallback_honesto,
    registrar_limitacao,
)


@pytest.fixture(autouse=True)
def _cwd_limpo(tmp_path, monkeypatch):
    """Cada teste roda em tmp: o limitacoes.txt real nunca é tocado."""
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def _dedup_zerado():
    """O estado de dedup é em memória — zera entre testes."""
    from core.limitacoes import _ultimo_registro
    _ultimo_registro.clear()
    yield
    _ultimo_registro.clear()


class TestRegistro:
    """registrar_limitacao: grava, dedupa, nunca derruba o pipeline."""

    def test_registra_e_le_de_volta(self) -> None:
        assert registrar_limitacao(
            "fallback_honesto_esgotado", "qual o valor do dólar"
        ) is True
        data = ler_limitacoes()
        assert data["total"] == 1
        e = data["entradas"][0]
        assert e["motivo"] == "fallback_honesto_esgotado"
        assert e["pergunta"] == "qual o valor do dólar"
        assert "T" in e["ts"]  # ISO

    def test_dedup_mesma_pergunta_na_janela(self) -> None:
        assert registrar_limitacao("m", "pergunta igual") is True
        assert registrar_limitacao("m", "Pergunta   IGUAL ") is False
        assert ler_limitacoes()["total"] == 1

    def test_dedup_janela_expirada_registra_de_novo(self, monkeypatch) -> None:
        registrar_limitacao("m", "pergunta")
        real_time = time.time
        futuro = real_time() + DEDUP_WINDOW_S + 1
        monkeypatch.setattr(
            "core.limitacoes.time.time", lambda: futuro
        )
        assert registrar_limitacao("m", "pergunta") is True
        assert ler_limitacoes()["total"] == 2

    def test_motivo_diferente_nao_dedupa(self) -> None:
        registrar_limitacao("motivo_a", "mesma pergunta")
        assert registrar_limitacao("motivo_b", "mesma pergunta") is True

    def test_vazio_nao_registra(self) -> None:
        assert registrar_limitacao("", "pergunta") is False
        assert registrar_limitacao("motivo", "") is False
        assert registrar_limitacao("motivo", "   ") is False
        assert ler_limitacoes()["total"] == 0

    def test_norma_acentos_ignorada_no_dedup(self) -> None:
        # dedup usa minúsculas + espaços colapsados; acentos permanecem
        # (são parte da pergunta), mas caixa/espaço não re-registram.
        registrar_limitacao("m", "Qual o VALOR  do dólar?")
        assert registrar_limitacao("m", "qual o valor do dólar?") is False


class TestTetoEAtomicidade:
    """Teto de arquivo (poda do mais antigo) e append atômico."""

    def test_teto_poda_mais_antigo(self, monkeypatch) -> None:
        import core.limitacoes as mod
        monkeypatch.setattr(mod, "LIMITACOES_MAX_BYTES", 400)
        for i in range(20):
            registrar_limitacao(f"motivo_{i:02d}", f"pergunta número {i:02d}")
        data = ler_limitacoes()
        # As antigas foram podadas; a mais recente SEMPRE está.
        assert data["entradas"][-1]["motivo"] == "motivo_19"
        assert data["bytes"] <= 400 + 200  # folga de uma entrada

    def test_arquivo_sem_linha_final_nao_cola_entradas(
        self, monkeypatch
    ) -> None:
        LIMITACOES_FILE.write_text(
            "## [2026-09-30T10:00:00] antigo\npergunta antiga",
            encoding="utf-8",
        )
        registrar_limitacao("novo", "pergunta nova")
        data = ler_limitacoes()
        assert data["total"] == 2
        assert data["entradas"][0]["pergunta"] == "pergunta antiga"
        assert data["entradas"][1]["pergunta"] == "pergunta nova"

    def test_limpar_zera_e_idempotente(self) -> None:
        registrar_limitacao("m", "p")
        assert limpar_limitacoes()["total"] == 0
        assert limpar_limitacoes()["total"] == 0  # idempotente
        assert LIMITACOES_FILE.read_text(encoding="utf-8") == ""


class TestHooks:
    """Hooks do Orchestrator (v1.13.0)."""

    def test_hook_fallback_honesto(self) -> None:
        assert registrar_fallback_honesto("quem é o dono do universo") is True
        e = ler_limitacoes()["entradas"][0]
        assert e["motivo"] == "fallback_honesto_esgotado"

    def test_hook_action_degradada_carrega_action(self) -> None:
        assert registrar_action_degradada(
            "weather_city", "clima em atlantis"
        ) is True
        e = ler_limitacoes()["entradas"][0]
        assert e["motivo"] == "action_degradada:weather_city"

    def test_hooks_compartilham_dedup_por_pergunta(self) -> None:
        registrar_fallback_honesto("pergunta difícil")
        # mesmo motivo+pergunta → dedup; motivo diferente → registra
        assert registrar_action_degradada("weather_city", "pergunta difícil") is True


class TestIntegracaoOrchestrator:
    """O hook de fallback dispara de _resolve_refusal quando esgota."""

    @pytest.mark.asyncio
    async def test_fallback_esgotado_registra_limitacao(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Recusa persistente em assunto EXTERNO (2 retries esgotados) →
        fallback honesto E limitação registrada."""
        from core.orchestrator import Orchestrator, StaticProvider

        limpar_limitacoes()
        orch = Orchestrator(
            providers=[StaticProvider("recusa", "Não posso fornecer isso.")],
        )
        resultado = await orch.process(
            "alex",
            "guardian",
            "qual a temperatura em atlantis sul",
            role="admin",
        )
        # O fallback honesto foi devolvido E a limitação ficou registrada.
        assert resultado.ok
        data = ler_limitacoes()
        assert data["total"] >= 1
        motivos = {e["motivo"] for e in data["entradas"]}
        assert "fallback_honesto_esgotado" in motivos
        limpar_limitacoes()



class TestDefesaDoPipeline:
    """Falha de I/O no registro NUNCA derruba o pipeline (padrão da casa)."""

    def test_falha_de_escrita_nao_propaga(self, monkeypatch) -> None:
        import core.limitacoes as mod

        def _explode(entrada: str) -> None:
            raise OSError("disco cheio")

        monkeypatch.setattr(mod, "_append_atomico", _explode)
        # NÃO propaga: devolve False (a resposta ao usuário segue normal).
        assert registrar_limitacao("m", "pergunta") is False
