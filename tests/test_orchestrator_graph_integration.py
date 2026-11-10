#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_orchestrator_graph_integration.py
Descrição: F1 fase 2 — grafo ligado ao process() por OD_ORCHESTRATOR_GRAPH=1,
           com checkpoint em SQLite e fallback para o loop direto.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/orchestrator.py (_resposta_llm / _resposta_llm_grafo)
  - core/orchestrator_graph.py
"""

from __future__ import annotations

import sqlite3

import pytest

from core.orchestrator import Orchestrator, StaticProvider
from core.orchestrator_graph import habilitado_por_env


def _orch() -> Orchestrator:
    return Orchestrator(providers=[StaticProvider("stub", "resposta do stub")])


class TestFlag:
    def test_desligada_por_padrao(self, monkeypatch):
        monkeypatch.delenv("OD_ORCHESTRATOR_GRAPH", raising=False)
        assert habilitado_por_env() is False

    @pytest.mark.parametrize("valor", ["1", "true", "ON", "sim", " yes "])
    def test_valores_ligados(self, monkeypatch, valor):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", valor)
        assert habilitado_por_env() is True

    @pytest.mark.parametrize("valor", ["0", "false", "", "nao", "off"])
    def test_valores_desligados(self, monkeypatch, valor):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", valor)
        assert habilitado_por_env() is False


@pytest.mark.asyncio
class TestProcessoComGrafo:
    async def test_flag_ligada_gera_resposta_e_checkpoints(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = _orch()

        result = await orch.process("alex", "guardian", "qual a capital do brasil?")

        assert result.ok
        assert result.route == "llm"
        assert result.message == "resposta do stub"
        assert (tmp_path / "ck.db").exists()
        with sqlite3.connect(tmp_path / "ck.db") as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM od_graph_checkpoints"
            ).fetchone()[0]
            # 8 nós do pipeline + checkpoint inicial.
            assert total == 9

    async def test_flag_ligada_preserva_guardas_e_pos_processamento(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        provider = StaticProvider("stub", "criado com sucesso")
        orch = Orchestrator(providers=[provider])

        result = await orch.process("alex", "guardian", "cria um evento")

        # Anti-falso-sucesso (etapa 6.7) continua valendo dentro do nó.
        assert "criado com sucesso" not in result.message
        assert result.message

    async def test_falha_do_grafo_cai_no_caminho_direto(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")

        def explode(self):
            raise RuntimeError("sqlite indisponível")

        monkeypatch.setattr(
            Orchestrator, "_obter_graph_saver", explode, raising=True
        )
        orch = _orch()

        result = await orch.process("alex", "guardian", "olá")

        assert result.ok
        assert result.route == "llm"
        assert result.message == "resposta do stub"

    async def test_rota_terminal_para_cedo_no_grafo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        provider = StaticProvider("stub", "nunca")
        orch = Orchestrator(providers=[provider])

        result = await orch.process("alex", "guardian", "que horas são?")

        assert result.route == "datetime"
        assert "Agora são" in result.message
        with sqlite3.connect(tmp_path / "ck.db") as conn:
            # inicial + rate_limit + datetime; os outros nós não rodam.
            total = conn.execute(
                "SELECT COUNT(*) FROM od_graph_checkpoints"
            ).fetchone()[0]
            assert total == 3

    async def test_cache_acerta_no_grafo_sem_chamar_llm(self, tmp_path, monkeypatch):
        from memory.cache import LLMCache

        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        provider = StaticProvider("stub", "resposta cacheada")
        cache = LLMCache(cache_dir=tmp_path / "cache")
        orch = Orchestrator(providers=[provider], cache=cache)

        primeira = await orch.process("alex", "guardian", "capital do brasil?")
        segunda = await orch.process("alex", "guardian", "capital do brasil?")

        assert primeira.route == "llm"
        assert segunda.route == "cache"
        assert segunda.cached
        assert segunda.message == "resposta cacheada"

    async def test_anonimo_persist_false_nao_grava_no_grafo(
        self, tmp_path, monkeypatch
    ):
        from memory.cache import LLMCache
        from memory.history import ConversationHistory

        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        history = ConversationHistory(base_dir=tmp_path / "conversas")
        cache = LLMCache(cache_dir=tmp_path / "cache")
        orch = Orchestrator(
            providers=[StaticProvider("stub", "resposta")],
            history=history,
            cache=cache,
        )

        result = await orch.process(
            "anonimo", "guardian", "oi", role="anonymous", persist=False
        )

        assert result.route == "llm"
        assert history.get_history("anonimo", "guardian") == []
        assert cache.stats()["entries"] == 0

    async def test_direto_e_grafo_concordam_na_rota_e_resposta(
        self, tmp_path, monkeypatch
    ):
        respostas = {}
        for flag in ("0", "1"):
            monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", flag)
            monkeypatch.setenv(
                "OD_GRAPH_CHECKPOINT_DB", str(tmp_path / f"ck-{flag}.db")
            )
            orch = Orchestrator(providers=[StaticProvider("stub", "mesma resposta")])
            resultado = await orch.process(
                f"alex{flag}", "guardian", "bom dia, tudo bem?"
            )
            respostas[flag] = (resultado.route, resultado.message)
        assert respostas["0"] == respostas["1"] == ("llm", "mesma resposta")

    async def test_flag_desligada_nao_cria_banco(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OD_ORCHESTRATOR_GRAPH", raising=False)
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = _orch()

        result = await orch.process("alex", "guardian", "olá")

        assert result.route == "llm"
        assert not (tmp_path / "ck.db").exists()
