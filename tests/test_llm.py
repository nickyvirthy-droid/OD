"""
OMEGA DRAKON • TESTS
Módulo: tests/test_llm.py
Descrição: Testes de core/llm.py — OpenAICompatProvider: parse de ChatML
           para messages OpenAI, geração com rede stubada (payload,
           headers, timeouts), content vazio com reasoning, erros
           HTTP/rede/JSON, is_available() e integração com o Orchestrator
           (rota llm) usando o provider real.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/orchestrator.py (LLMProvider)
  - memory/history.py (build_chatml)
  - OMEGADRAKON_SPEC.md (llama-server local)
"""

from __future__ import annotations

import json

import pytest

from core.llm import (
    LLMError,
    OpenAICompatProvider,
    parse_chatml,
)
from core.orchestrator import Orchestrator


def fake_urlopen(monkeypatch, *, body=None, raise_error=None):
    """Stub de urllib.request.urlopen; captura request e timeout."""

    def fake(request, timeout=None):
        seen = {
            "url": request.full_url,
            "method": request.get_method(),
            "headers": dict(request.headers),
            "data": request.data.decode() if request.data else None,
            "timeout": timeout,
        }
        fake.seen = seen
        if raise_error is not None:
            raise raise_error

        class Resp:
            def __init__(self) -> None:
                self.status = 200

            def read(self) -> bytes:
                return body if body is not None else b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        return Resp()

    fake.seen = {}
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def chatml_body(system: str = "", user: str = "oi", history: list = None) -> str:
    parts = []
    if system:
        parts.append(f"<|im_start|>system\n{system}<|im_end|>")
    for role, content in history or []:
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append(f"<|im_start|>user\n{user}<|im_end|>")
    return "\n".join(parts)


# ===========================================================================
# parse_chatml
# ===========================================================================

class TestParseChatML:
    """Conversão do prompt ChatML em messages OpenAI nativas."""

    def test_system_user(self) -> None:
        prompt = (
            "<|im_start|>system\nVocê é Nicky.<|im_end|>\n"
            "<|im_start|>user\nBom dia!<|im_end|>"
        )
        assert parse_chatml(prompt) == [
            {"role": "system", "content": "Você é Nicky."},
            {"role": "user", "content": "Bom dia!"},
        ]

    def test_with_history_and_datetime_system(self) -> None:
        prompt = chatml_body(
            system="Você é o OD.",
            history=[("user", "p1"), ("assistant", "r1")],
            user="p2",
        )
        messages = parse_chatml(prompt)
        assert [m["role"] for m in messages] == [
            "system", "user", "assistant", "user",
        ]
        assert messages[-1] == {"role": "user", "content": "p2"}
        assert messages[1] == {"role": "user", "content": "p1"}

    def test_without_markers_falls_back_single_user(self) -> None:
        assert parse_chatml("texto livre") == [
            {"role": "user", "content": "texto livre"}
        ]

    def test_empty_and_unknown_roles_ignored(self) -> None:
        prompt = "<|im_start|>foo\nx<|im_end|>\n<|im_start|>user\nok<|im_end|>"
        assert parse_chatml(prompt) == [{"role": "user", "content": "ok"}]
        assert parse_chatml("<|im_start|>") == [
            {"role": "user", "content": "<|im_start|>"}
        ]


# ===========================================================================
# OpenAICompatProvider — geração
# ===========================================================================

class TestOpenAICompatProvider:
    """Payload, headers, erros e is_available com rede stubada."""

    @pytest.mark.asyncio
    async def test_generate_sends_native_messages(self, monkeypatch) -> None:
        stub = fake_urlopen(
            monkeypatch,
            body=json.dumps({
                "choices": [{"message": {"role": "assistant",
                                         "content": "olá!"}}]
            }).encode(),
        )
        provider = OpenAICompatProvider(
            name="llama-test", base_url="http://127.0.0.1:8081", model="m1"
        )
        out = await provider.generate(chatml_body(system="seja educado",
                                                  user="oi"))
        assert out == "olá!"
        payload = json.loads(stub.seen["data"])
        assert payload["messages"] == [
            {"role": "system", "content": "seja educado"},
            {"role": "user", "content": "oi"},
        ]
        assert stub.seen["url"] == "http://127.0.0.1:8081/v1/chat/completions"
        assert stub.seen["method"] == "POST"

    @pytest.mark.asyncio
    async def test_generate_passes_timeout(self, monkeypatch) -> None:
        stub = fake_urlopen(
            monkeypatch,
            body=json.dumps({"choices": [{"message": {"content": "x"}}]}).encode(),
        )
        provider = OpenAICompatProvider(timeout=30.0)
        await provider.generate("oi", timeout=45.0)
        assert stub.seen["timeout"] == 45.0

    @pytest.mark.asyncio
    async def test_api_key_header(self, monkeypatch) -> None:
        stub = fake_urlopen(
            monkeypatch,
            body=json.dumps({"choices": [{"message": {"content": "x"}}]}).encode(),
        )
        provider = OpenAICompatProvider(api_key="sk-123")
        await provider.generate("oi")
        assert stub.seen["headers"]["Authorization"] == "Bearer sk-123"

    @pytest.mark.asyncio
    async def test_empty_content_with_reasoning(self, monkeypatch) -> None:
        fake_urlopen(
            monkeypatch,
            body=json.dumps({
                "choices": [{"message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "pensando sobre a resposta...",
                }}]
            }).encode(),
        )
        provider = OpenAICompatProvider()
        out = await provider.generate("oi")
        assert out == "pensando sobre a resposta..."

    @pytest.mark.asyncio
    async def test_empty_everything_returns_none(self, monkeypatch) -> None:
        fake_urlopen(monkeypatch, body=json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "  "}}]
        }).encode())
        assert await OpenAICompatProvider().generate("oi") is None

    @pytest.mark.asyncio
    async def test_http_error_raises_llm_error(self, monkeypatch) -> None:
        import io
        import urllib.error

        error = urllib.error.HTTPError(
            "url", 500, "internal", {}, io.BytesIO(b"erro")
        )
        fake_urlopen(monkeypatch, raise_error=error)
        with pytest.raises(LLMError, match="500"):
            await OpenAICompatProvider().generate("oi")

    @pytest.mark.asyncio
    async def test_network_error_raises_llm_error(self, monkeypatch) -> None:
        import urllib.error

        fake_urlopen(
            monkeypatch,
            raise_error=urllib.error.URLError("connection refused"),
        )
        with pytest.raises(LLMError, match="indispon"):
            await OpenAICompatProvider().generate("oi")

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self, monkeypatch) -> None:
        fake_urlopen(monkeypatch, body=b"{quebrado")
        with pytest.raises(LLMError, match="JSON"):
            await OpenAICompatProvider().generate("oi")

    def test_is_available_true(self, monkeypatch) -> None:
        fake_urlopen(monkeypatch, body=b'{"status":"ok"}')
        assert OpenAICompatProvider().is_available() is True

    def test_is_available_false_on_error(self, monkeypatch) -> None:
        import urllib.error

        fake_urlopen(
            monkeypatch,
            raise_error=urllib.error.URLError("refused"),
        )
        assert OpenAICompatProvider().is_available() is False

    def test_dump_shape(self) -> None:
        provider = OpenAICompatProvider(
            name="local", base_url="http://127.0.0.1:8081/", api_key="k"
        )
        data = provider.dump()
        assert data["name"] == "local"
        assert data["base_url"] == "http://127.0.0.1:8081"  # sem barra final
        assert data["api_key"] is True


# ===========================================================================
# Integração com o Orchestrator
# ===========================================================================

class TestOrchestratorWithProvider:
    """Orchestrator.process com OpenAICompatProvider (rota llm)."""

    @pytest.mark.asyncio
    async def test_process_llm_route(self, monkeypatch) -> None:
        fake_urlopen(
            monkeypatch,
            body=json.dumps({
                "choices": [{"message": {
                    "role": "assistant", "content": "resposta do llm",
                }}]
            }).encode(),
        )
        provider = OpenAICompatProvider(name="llama-test")
        orch = Orchestrator(providers=[provider])
        result = await orch.process("alex", "guardian", "pergunta única")
        assert result.route == "llm"
        assert result.message == "resposta do llm"
        assert result.llm_used == "llama-test"
        assert result.ok

    @pytest.mark.asyncio
    async def test_provider_failure_falls_through(self, monkeypatch) -> None:
        import urllib.error

        fake_urlopen(
            monkeypatch,
            raise_error=urllib.error.URLError("refused"),
        )
        orch = Orchestrator(providers=[OpenAICompatProvider(name="fora")])
        result = await orch.process("alex", "guardian", "oi")
        assert result.route == "llm_unavailable"
        assert not result.ok