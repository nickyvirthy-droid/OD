#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_orchestrator_graph.py
Descrição: Grafo do orquestrador (F1 fase 1) — estado com reducers, fan-out
           paralelo, checkpoint em SQLite, streaming e human-in-the-loop.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F1
  - core/orchestrator_graph.py
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from core.orchestrator_graph import (
    END,
    START,
    GraphRecursionError,
    GraphStateError,
    OrchestratorState,
    SqliteSaver,
    StateGraph,
    construir_grafo,
    rota_por_intencao,
)


def _grafo(**kwargs):
    chamadas: list[tuple] = []

    def classificar(estado):
        chamadas.append(("classify", estado["text"]))
        return "chat" if "oi" in estado["text"] else "tools"

    def selecionar(estado):
        chamadas.append(("select", estado["intent"]))
        return ["clima", "agenda"]

    def executar(ferramenta, estado):
        chamadas.append(("execute", ferramenta))
        return f"{ferramenta}:ok"

    def gerar(estado):
        chamadas.append(("generate", len(estado.get("tool_results", []))))
        return f"resposta com {len(estado.get('tool_results', []))} resultado(s)"

    opcoes = dict(
        classificar=classificar,
        selecionar=selecionar,
        executar=executar,
        gerar=gerar,
    )
    opcoes.update(kwargs)
    return construir_grafo(**opcoes), chamadas


class TestFluxo:
    def test_intencao_simples_pula_ferramentas(self):
        grafo, chamadas = _grafo()
        estado = asyncio.run(grafo.ainvoke({"text": "oi", "user_id": "alex"}))
        assert estado["response"] == "resposta com 0 resultado(s)"
        assert [c[0] for c in chamadas] == ["classify", "generate"]
        assert "classify" in estado["steps"]
        assert "human_loop" in estado["steps"]

    def test_intencao_com_ferramenta_executa_e_gera(self):
        grafo, chamadas = _grafo()
        estado = asyncio.run(grafo.ainvoke({"text": "como está o tempo?"}))
        assert [c[0] for c in chamadas] == [
            "classify",
            "select",
            "execute",
            "execute",
            "generate",
        ]
        assert estado["active_tools"] == ["clima", "agenda"]
        assert {r["tool"] for r in estado["tool_results"]} == {"clima", "agenda"}
        assert estado["response"] == "resposta com 2 resultado(s)"

    def test_ferramentas_do_mesmo_passo_rodam_em_paralelo(self):
        def executar(ferramenta, estado):
            time.sleep(0.2)
            return ferramenta

        # 2 ferramentas × 0,2 s: paralelo ~0,2 s, sequencial 0,4 s.
        grafo, _ = _grafo(executar=executar)
        inicio = time.perf_counter()
        asyncio.run(grafo.ainvoke({"text": "tempo e agenda"}))
        assert time.perf_counter() - inicio < 0.35

    def test_no_assincrono_e_aceito(self):
        async def gerar(estado):
            await asyncio.sleep(0)
            return "async"

        grafo, _ = _grafo(gerar=gerar)
        assert asyncio.run(grafo.ainvoke({"text": "oi"}))["response"] == "async"

    def test_rota_por_intencao(self):
        assert rota_por_intencao({"intent": "tools"}) == "select_tools"
        assert rota_por_intencao({"intent": "chat"}) == "generate"


class TestCheckpoint:
    def test_um_checkpoint_por_superstep(self, tmp_path):
        saver = SqliteSaver(tmp_path / "ck.db")
        grafo, _ = _grafo(checkpointer=saver)
        asyncio.run(
            grafo.ainvoke({"text": "tempo"}, {"configurable": {"thread_id": "s1"}})
        )
        passos = saver.historico("s1")
        assert [p.passo for p in passos] == [0, 1, 2, 3, 4, 5]
        assert passos[-1].estado["response"].startswith("resposta")
        saver.fechar()

    def test_estado_sobrevive_a_outra_instancia(self, tmp_path):
        caminho = tmp_path / "ck.db"
        saver1 = SqliteSaver(caminho)
        grafo1, _ = _grafo(checkpointer=saver1)
        asyncio.run(
            grafo1.ainvoke({"text": "tempo"}, {"configurable": {"thread_id": "s2"}})
        )
        saver1.fechar()
        saver2 = SqliteSaver(caminho)
        grafo2, _ = _grafo(checkpointer=saver2)
        final = asyncio.run(
            grafo2.ainvoke(None, {"configurable": {"thread_id": "s2"}}, resume=True)
        )
        assert final["response"].startswith("resposta")
        assert final["active_tools"] == ["clima", "agenda"]
        saver2.fechar()

    def test_concluido_so_no_ultimo_passo(self, tmp_path):
        saver = SqliteSaver(tmp_path / "ck.db")
        saver.put("t1", 0, {}, ["n1"])
        assert saver.ultimo("t1").concluido is False
        saver.put("t1", 1, {}, [], concluido=True)
        ultimo = saver.ultimo("t1")
        assert ultimo.concluido is True
        assert ultimo.proximos == []
        assert saver.historico("t1")[0].concluido is False
        saver.fechar()

    def test_ultimo_e_o_gravado_por_ultimo_nao_o_de_maior_passo(self, tmp_path):
        """Turno repetido na mesma thread recomeça no passo 0.

        O checkpoint antigo (passo 9, do turno anterior) continuava sendo
        devolvido como "último": a decisão humana era aplicada no estado
        velho — e o cancelado respondia com a mensagem do turno anterior.
        """
        saver = SqliteSaver(tmp_path / "ck.db")
        saver.put("t", 0, {"texto": "antigo"}, ["n1"])
        saver.put("t", 9, {"texto": "antigo"}, ["human_loop"])
        saver.put("t", 0, {"texto": "novo"}, ["human_loop"])

        ultimo = saver.ultimo("t")
        assert ultimo.passo == 0
        assert ultimo.estado == {"texto": "novo"}
        saver.fechar()

    def test_migracao_de_banco_antigo_adiciona_concluido(self, tmp_path):
        caminho = tmp_path / "antigo.db"
        conn = sqlite3.connect(caminho)
        conn.executescript(
            "CREATE TABLE od_graph_checkpoints ("
            "thread_id TEXT NOT NULL, passo INTEGER NOT NULL, estado TEXT NOT NULL, "
            "proximos TEXT NOT NULL, created_at REAL NOT NULL, "
            "PRIMARY KEY (thread_id, passo));"
        )
        conn.execute(
            "INSERT INTO od_graph_checkpoints VALUES ('old', 0, '{}', '[\"x\"]', 1.0)"
        )
        conn.commit()
        conn.close()

        saver = SqliteSaver(caminho)
        salvo = saver.ultimo("old")
        assert salvo is not None and salvo.concluido is False
        saver.put("old", 1, {}, [], concluido=True)
        assert saver.ultimo("old").concluido is True
        saver.fechar()

    def test_retomar_sem_checkpoint_falha(self, tmp_path):
        saver = SqliteSaver(tmp_path / "ck.db")
        grafo, _ = _grafo(checkpointer=saver)
        with pytest.raises(GraphStateError):
            grafo.retomar("inexistente", {"human_decision": "aprovar"})
        saver.fechar()


class TestHumanoNoLoop:
    def test_pausa_quando_ha_pendencia(self, tmp_path):
        def humano(estado):
            return "aprovar"

        def classificar(estado):
            return "chat"

        saver = SqliteSaver(tmp_path / "ck.db")
        grafo, _ = _grafo(
            classificar=classificar,
            gerar=lambda estado: {
                "response": "preciso aprovar luz",
                "pending_human_input": {"acao": "ligar_luz"},
            },
            humano=humano,
            checkpointer=saver,
        )

        async def cenario():
            eventos = [
                e async for e in grafo.astream(
                    {"text": "liga a luz"}, {"configurable": {"thread_id": "h1"}}
                )
            ]
            assert "__interrupt__" in eventos[-1]
            # Nada foi gerado de verdade ainda além do pedido de aprovação.
            salvo = saver.ultimo("h1")
            assert salvo is not None
            assert salvo.proximos == ["human_loop"]
            assert salvo.estado["pending_human_input"] == {"acao": "ligar_luz"}

            grafo.retomar("h1", {"human_decision": "aprovar"})
            final = await grafo.ainvoke(
                None, {"configurable": {"thread_id": "h1"}}, resume=True
            )
            assert final["human_decision"] == "aprovar"
            assert final["pending_human_input"] is None
            assert final["response"] == "preciso aprovar luz"

        asyncio.run(cenario())
        saver.fechar()

    def test_humano_sem_decisao_mantem_pausa(self, tmp_path):
        saver = SqliteSaver(tmp_path / "ck.db")
        grafo, _ = _grafo(
            gerar=lambda estado: {
                "response": "aguardando",
                "pending_human_input": {"acao": "x"},
            },
            humano=lambda estado: None,
            checkpointer=saver,
        )

        async def cenario():
            eventos = [
                e
                async for e in grafo.astream(
                    {"text": "oi"}, {"configurable": {"thread_id": "h2"}}
                )
            ]
            assert "__interrupt__" in eventos[-1]
            salvo = saver.ultimo("h2")
            assert salvo is not None
            assert salvo.estado["pending_human_input"] == {"acao": "x"}

        asyncio.run(cenario())
        saver.fechar()


class TestMotor:
    def test_reducer_concatena_saidas_do_mesmo_passo(self):
        def a(estado):
            return {"messages": [{"role": "user", "content": "a"}]}

        def b(estado):
            return {"messages": [{"role": "assistant", "content": "b"}]}

        builder = StateGraph(OrchestratorState)
        builder.add_node("a", a)
        builder.add_node("b", b)
        builder.add_edge(START, "a")
        builder.add_edge("a", "b")  # fan-out: b e c no mesmo superstep
        builder.add_node(
            "c", lambda estado: {"messages": [{"role": "system", "content": "c"}]}
        )
        builder.add_edge("a", "c")
        builder.add_edge("b", END)
        builder.add_edge("c", END)
        grafo = builder.compile()
        estado = asyncio.run(grafo.ainvoke({"messages": []}))
        assert [m["content"] for m in estado["messages"]] == ["a", "b", "c"]

    def test_recursion_limit(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("loop", lambda estado: {"steps": ["loop"]})
        builder.add_edge(START, "loop")
        builder.add_edge("loop", "loop")
        grafo = builder.compile()
        with pytest.raises(GraphRecursionError):
            asyncio.run(grafo.ainvoke({}, {"recursion_limit": 3}))

    def test_rota_desconhecida_falha(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("a", lambda estado: {})
        builder.add_edge(START, "a")
        builder.add_conditional_edges("a", lambda estado: "nao_existe")
        grafo = builder.compile()
        with pytest.raises(GraphStateError):
            asyncio.run(grafo.ainvoke({}))

    def test_no_que_devolve_nao_dict_falha(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("a", lambda estado: "texto")
        builder.add_edge(START, "a")
        grafo = builder.compile()
        with pytest.raises(GraphStateError):
            asyncio.run(grafo.ainvoke({}))

    def test_resume_de_thread_concluida_preserva_checkpoint(self, tmp_path):
        saver = SqliteSaver(tmp_path / "ck.db")
        grafo, _ = _grafo(checkpointer=saver)
        asyncio.run(
            grafo.ainvoke({"text": "oi"}, {"configurable": {"thread_id": "done"}})
        )
        antes = saver.ultimo("done")
        assert antes.concluido is True
        asyncio.run(
            grafo.ainvoke(None, {"configurable": {"thread_id": "done"}}, resume=True)
        )
        depois = saver.ultimo("done")
        assert depois.concluido is True
        assert depois.passo == antes.passo
        saver.fechar()

    def test_stream_rende_updates_por_passo(self):
        grafo, _ = _grafo()

        async def cenario():
            eventos = [
                e
                async for e in grafo.astream(
                    {"text": "tempo"}, {"configurable": {"thread_id": "st"}}
                )
            ]
            assert [e["passo"] for e in eventos] == [1, 2, 3, 4, 5]
            assert eventos[0]["nos"] == ["classify"]

        asyncio.run(cenario())
