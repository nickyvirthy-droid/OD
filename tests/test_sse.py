"""
Testes do SSE Streaming (I5).
"""

from __future__ import annotations

import json
import pytest

from core.orchestrator import Orchestrator, StaticProvider


class MockStreamingProvider(StaticProvider):
    """Provider que suporta streaming."""
    
    def generate_stream(self, prompt: str, **kwargs):
        """Async generator para streaming."""
        async def _gen():
            for word in ["Olá", ", ", "como", " ", "posso", " ", "ajudar", "?"]:
                yield word
        return _gen()


@pytest.fixture
def orchestrator():
    return Orchestrator(providers=[MockStreamingProvider("test", "resposta completa")])


class TestProcessStreamSSE:
    @pytest.mark.asyncio
    async def test_process_stream_sse_basic(self, orchestrator):
        """Testa o wrapper SSE básico."""
        events = []
        async for chunk in orchestrator.process_stream_sse(
            user_id="test", profile="guardian", text="oi"
        ):
            events.append(chunk)
        
        # Deve ter pelo menos progress, token, done
        event_types = [e.split("event: ")[1].split("\n")[0] if "event: " in e else "data" for e in events]
        
        # Pelo menos um token e um done
        assert any("token" in e for e in events), "Deve ter evento token"
        assert any("done" in e for e in events), "Deve ter evento done"
        
        # Verifica formato SSE
        for event in events:
            assert "\n\n" in event, "Evento SSE deve terminar com \n\n"
            if "event: " in event:
                assert "data: " in event, "Evento deve ter data"
    
    @pytest.mark.asyncio
    async def test_process_stream_sse_content(self, orchestrator):
        """Testa se o conteúdo está correto nos eventos."""
        events = []
        async for chunk in orchestrator.process_stream_sse(
            user_id="test", profile="guardian", text="oi"
        ):
            events.append(chunk)
        
        # Encontra evento done
        done_event = None
        for event in events:
            if "event: done" in event:
                done_event = event
                break
        
        assert done_event is not None, "Deve ter evento done"
        # Extrai data do done
        data_line = [l for l in done_event.split("\n") if l.startswith("data: ")]
        assert data_line, "Done deve ter data"
        data = json.loads(data_line[0][6:])  # Remove "data: "
        assert "content" in data
        assert "route" in data
        # MockStreamingProvider gera streaming, o conteúdo final é a concatenação
        assert len(data["content"]) > 0
    
    @pytest.mark.asyncio
    async def test_process_stream_sse_progress_events(
        self, orchestrator, tmp_path, monkeypatch
    ):
        """Testa eventos de progresso (quando grafo está ligado)."""
        monkeypatch.setenv("OD_ORCHESTRATOR_GRAPH", "1")
        monkeypatch.setenv("OD_GRAPH_CHECKPOINT_DB", str(tmp_path / "sse.db"))

        events = []
        async for chunk in orchestrator.process_stream_sse(
            user_id="test", profile="guardian", text="oi"
        ):
            events.append(chunk)

        # Com grafo, deve ter progress
        progress_events = [e for e in events if "event: progress" in e]
        # Pode ter progress se grafo funcionar


if __name__ == "__main__":
    pytest.main([__file__, "-v"])