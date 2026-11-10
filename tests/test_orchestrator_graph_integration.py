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
            # classify → generate → human_loop: 3 passos + checkpoint inicial.
            assert total == 4

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

    async def test_flag_desligada_nao_cria_banco(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OD_ORCHESTRATOR_GRAPH", raising=False)
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = _orch()

        result = await orch.process("alex", "guardian", "olá")

        assert result.route == "llm"
        assert not (tmp_path / "ck.db").exists()
