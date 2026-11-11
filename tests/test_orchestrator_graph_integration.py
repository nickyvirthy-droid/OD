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

import hashlib
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
            # 10 nós do pipeline + checkpoint inicial (rate_limit, datetime, quick,
            # infra_guard, cache_terminal, classify, generate, post_process, human_loop).
            assert total == 10

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

    async def test_thread_estavel_por_sessao_e_texto(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = Orchestrator(providers=[StaticProvider("stub", "resposta")])

        await orch.process("alex", "guardian", "mesma pergunta", session_id="s1")
        await orch.process("alex", "guardian", "mesma pergunta", session_id="s1")
        await orch.process("alex", "guardian", "mesma pergunta", session_id="s2")

        chave = hashlib.sha256(
            b"s1\x00mesma pergunta\x00guardian\x00admin"
        ).hexdigest()[:20]
        with sqlite3.connect(tmp_path / "ck.db") as conn:
            threads = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT thread_id FROM od_graph_checkpoints"
                )
            ]
        assert len(threads) == 2
        assert f"alex:s1:{chave}" in threads

    async def test_retoma_turno_interrompido_sem_repetir_llm(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))

        class ProviderContador:
            name = "contador"

            def __init__(self) -> None:
                self.chamadas = 0

            def generate(self, prompt: str, timeout=None) -> str:
                self.chamadas += 1
                return "resposta única"

        # Primeiro processo: morre logo depois de gerar a resposta.
        p1 = ProviderContador()
        orch1 = Orchestrator(providers=[p1])

        async def explode(**_kwargs):
            raise RuntimeError("restart simulado")

        original = Orchestrator._etapa_post_processo
        monkeypatch.setattr(orch1, "_etapa_post_processo", explode)
        with pytest.raises(RuntimeError):
            await orch1._executar_grafo(
                user_id="alex",
                profile="guardian",
                text="pergunta que sobrevive ao restart",
                system_prompt="",
                session_id="sess-restart",
                role="admin",
                persist=True,
            )
        assert p1.chamadas == 1

        # Segundo processo: instância nova, mesmo banco — retoma do checkpoint.
        p2 = ProviderContador()
        orch2 = Orchestrator(providers=[p2])
        monkeypatch.setattr(orch2, "_etapa_post_processo", original.__get__(orch2))
        final = await orch2._executar_grafo(
            user_id="alex",
            profile="guardian",
            text="pergunta que sobrevive ao restart",
            system_prompt="",
            session_id="sess-restart",
            role="admin",
            persist=True,
        )

        assert final["route"] == "llm"
        assert final["message"] == "resposta única"
        assert final.get("pos_processado") is True
        assert p2.chamadas == 0  # LLM não foi pago de novo

        chave = hashlib.sha256(
            b"sess-restart\x00pergunta que sobrevive ao restart\x00guardian\x00admin"
        ).hexdigest()[:20]
        with sqlite3.connect(tmp_path / "ck.db") as conn:
            concluido = conn.execute(
                "SELECT concluido FROM od_graph_checkpoints "
                "WHERE thread_id = ? ORDER BY passo DESC LIMIT 1",
                (f"alex:sess-restart:{chave}",),
            ).fetchone()[0]
        assert concluido == 1

    async def test_falha_em_processo_nao_deixa_turno_retomavel(
        self, tmp_path, monkeypatch
    ):
        """Se o grafo falha e o direto responde, o turno não fica 'pendente'."""
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = Orchestrator(providers=[StaticProvider("stub", "resposta")])

        original = Orchestrator._etapa_post_processo
        falhas = {"n": 0}

        async def explode(**kwargs):
            # Só o grafo falha; o fallback direto completa normalmente.
            falhas["n"] += 1
            if falhas["n"] == 1:
                raise RuntimeError("falha simulada no nó final")
            return await original.__get__(orch)(**kwargs)

        monkeypatch.setattr(orch, "_etapa_post_processo", explode)
        result = await orch.process(
            "alex", "guardian", "pergunta com falha", session_id="s-falha"
        )

        assert result.route == "llm"
        assert result.message == "resposta"
        chave = hashlib.sha256(
            b"s-falha\x00pergunta com falha\x00guardian\x00admin"
        ).hexdigest()[:20]
        with sqlite3.connect(tmp_path / "ck.db") as conn:
            concluido, proximos = conn.execute(
                "SELECT concluido, proximos FROM od_graph_checkpoints "
                "WHERE thread_id = ? ORDER BY passo DESC LIMIT 1",
                (f"alex:s-falha:{chave}",),
            ).fetchone()
        assert concluido == 1
        assert proximos == "[]"

    async def test_flag_desligada_nao_cria_banco(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OD_ORCHESTRATOR_GRAPH", raising=False)
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = _orch()

        result = await orch.process("alex", "guardian", "olá")

        assert result.route == "llm"
        assert not (tmp_path / "ck.db").exists()


@pytest.mark.asyncio
class TestRetomadaHumana:
    async def test_retomar_fecha_pausa_e_roda_post_process(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        orch = _orch()
        chamadas: list[str] = []

        async def fake_execute(nome, params=None, user_id="", role=""):
            chamadas.append(nome)
            return {"ok": True}

        monkeypatch.setattr(orch, "execute_action", fake_execute)
        saver = orch._obter_graph_saver()
        thread_id = "alex:tg:1:abc"
        # Checkpoint de um turno pausado no human_loop (o que o astream grava).
        saver.put(
            thread_id,
            5,
            {
                "user_id": "alex",
                "profile": "guardian",
                "session_id": "tg:1",
                "role": "admin",
                "text": "liga a luz",
                "system_prompt": "",
                "persist": False,
                "extra_history": None,
                "route": "llm",
                "message": "resposta do stub",
                "llm_used": "stub",
                "prompt": "p",
                "terminal": False,
                "pending_human_input": {
                    "acao": "ha_device_control",
                    "params": {"entity_id": "switch.luz", "on": True},
                },
                "steps": ["generate"],
            },
            ["human_loop"],
        )

        final = await orch.retomar_turno_humano(thread_id, "aprovar")

        assert final["human_decision"] is None  # consumida pela aprovação
        assert final["pending_human_input"] is None
        assert final["pos_processado"] is True
        assert "human_loop" in final["steps"]
        assert chamadas == ["ha_device_control"]


@pytest.mark.asyncio
class TestAprovacaoHumana:
    """Origem do human_loop: ação sensível pausa antes de executar."""

    def _orch_com_registro(self, monkeypatch):
        chamadas: list[tuple] = []

        async def fake_execute(nome, params=None, user_id="", role=""):
            chamadas.append((nome, params, user_id, role))
            return {"ok": True, "name": (params or {}).get("name", "arquivo")}

        orch = _orch()
        monkeypatch.setattr(orch, "execute_action", fake_execute)
        return orch, chamadas

    async def test_acao_sensivel_pausa_sem_executar(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.delenv("OD_HUMAN_APPROVAL_ACTIONS", raising=False)
        orch, chamadas = self._orch_com_registro(monkeypatch)

        result = await orch.process(
            "alex", "guardian", "apaga o arquivo relatorio no drive",
            role="admin", session_id="s-aprova",
        )

        assert result.paused is True
        assert result.route == "human_loop_pending"
        assert result.pending_human_input["acao"] == "google_drive_delete"
        assert result.thread_id
        assert chamadas == []  # nada executou antes da aprovação

    async def test_aprovar_executa_a_acao(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.delenv("OD_HUMAN_APPROVAL_ACTIONS", raising=False)
        orch, chamadas = self._orch_com_registro(monkeypatch)

        result = await orch.process(
            "alex", "guardian", "apaga o arquivo relatorio no drive",
            role="admin", session_id="s-aprova-2",
        )
        final = await orch.retomar_turno_humano(result.thread_id, "aprovar")

        assert [c[0] for c in chamadas] == ["google_drive_delete"]
        assert final["pending_human_input"] is None
        assert final["message"]
        assert final["route"] == "google_drive_delete"

    async def test_cancelar_nao_executa(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.delenv("OD_HUMAN_APPROVAL_ACTIONS", raising=False)
        orch, chamadas = self._orch_com_registro(monkeypatch)

        result = await orch.process(
            "alex", "guardian", "apaga o arquivo relatorio no drive",
            role="admin", session_id="s-aprova-3",
        )
        final = await orch.retomar_turno_humano(result.thread_id, "cancelar")

        assert chamadas == []
        assert final["pending_human_input"] is None
        assert "cancelada" in final["message"].lower()

    async def test_calendar_create_pausa_e_aprova(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.delenv("OD_HUMAN_APPROVAL_ACTIONS", raising=False)
        orch, chamadas = self._orch_com_registro(monkeypatch)

        result = await orch.process(
            "alex", "guardian", "cria um compromisso reuniao amanha as 15 horas",
            role="admin", session_id="s-aprova-cal",
        )
        assert result.paused is True
        assert result.pending_human_input["acao"] == "google_calendar_create"
        final = await orch.retomar_turno_humano(result.thread_id, "aprovar")

        assert [c[0] for c in chamadas] == ["google_calendar_create"]
        assert final["pending_human_input"] is None

    async def test_ha_device_control_pausa_e_aprova(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.delenv("OD_HUMAN_APPROVAL_ACTIONS", raising=False)
        import core.intents as intents_mod

        def fake_intent(texto):
            if "luz" in texto:
                return (
                    "ha_device_control",
                    {"entity_id": "switch.luz_cozinha", "on": True,
                     "alvo": "cozinha"},
                )
            return None

        monkeypatch.setattr(intents_mod, "detect_action_intent", fake_intent)
        orch, chamadas = self._orch_com_registro(monkeypatch)

        result = await orch.process(
            "alex", "guardian", "liga a luz da cozinha",
            role="admin", session_id="s-aprova-ha",
        )
        assert result.paused is True
        assert result.pending_human_input["acao"] == "ha_device_control"
        final = await orch.retomar_turno_humano(result.thread_id, "aprovar")

        assert [c[0] for c in chamadas] == ["ha_device_control"]
        assert final["pending_human_input"] is None

    async def test_stream_pausa_acao_sensivel(self, tmp_path, monkeypatch):
        """O caminho de streaming (WS) também pausa antes de executar.

        Antes ele tinha uma cópia própria da classificação sem a checagem de
        aprovação: o app recebia a ação executada em vez de
        `human_loop_pending` — e o frame `decision` nunca teria o que decidir.
        """
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.delenv("OD_HUMAN_APPROVAL_ACTIONS", raising=False)
        orch, chamadas = self._orch_com_registro(monkeypatch)

        chunks = [
            chunk
            async for chunk in orch.process_stream(
                "alex", "guardian", "apaga o arquivo relatorio no drive",
                session_id="s-stream-aprova", role="admin",
            )
        ]

        pausas = [c for c in chunks if c["type"] == "human_loop_pending"]
        assert len(pausas) == 1
        assert pausas[0]["thread_id"]
        assert pausas[0]["pending_human_input"]["acao"] == "google_drive_delete"
        assert not [c for c in chunks if c["type"] == "done"]
        assert chamadas == []

        final = await orch.retomar_turno_humano(
            pausas[0]["thread_id"], "cancelar"
        )
        assert chamadas == []
        assert final["pending_human_input"] is None

    async def test_aprovacao_humana_pula_confirmacao_de_2_passos(self):
        from tools.actions.actions import (
            _light_confirm_check,
            _write_confirm_check,
            aprovacao_humana_em_curso,
        )

        assert _light_confirm_check("user-teste-bypass", "switch.luz", True) == "required"
        with aprovacao_humana_em_curso():
            assert _light_confirm_check("user-teste-bypass", "switch.luz", True) == "confirmed"

        params = {"name": "notas"}
        assert _write_confirm_check(
            "user-teste-bypass", "google_drive_create", "chave",
            alvo="notas", params=params,
        ) == "required"
        with aprovacao_humana_em_curso():
            assert _write_confirm_check(
                "user-teste-bypass", "google_drive_create", "chave",
                alvo="notas", params=params,
            ) == "confirmed"

    async def test_lista_desligada_executa_sem_pausar(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "ck.db"))
        monkeypatch.setenv("OD_HUMAN_APPROVAL_ACTIONS", "off")
        orch, chamadas = self._orch_com_registro(monkeypatch)
        # Sem a lista de aprovação, quem decide a rota é o classificador.
        orch._query_router = type(
            "RouterTool", (), {"classify": lambda *a, **k: "tool"}
        )()

        result = await orch.process(
            "alex", "guardian", "apaga o arquivo relatorio no drive",
            role="admin", session_id="s-aprova-4",
        )

        assert result.paused is False
        assert [c[0] for c in chamadas] == ["google_drive_delete"]
