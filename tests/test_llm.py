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
        # o model configurado VAI no payload (Groq recusa sem ele)
        assert payload["model"] == "m1"

    @pytest.mark.asyncio
    async def test_sem_model_nao_manda_chave_model(self, monkeypatch) -> None:
        """O llama-server local nunca recebeu \"model\" — com model vazio
        o payload precisa ficar idêntico ao de sempre (runtime intacto)."""
        stub = fake_urlopen(
            monkeypatch,
            body=b'{"choices": [{"message": {"content": "ok"}}]}',
        )
        await OpenAICompatProvider().generate("oi")
        assert "model" not in json.loads(stub.seen["data"])

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
    async def test_user_agent_sempre_presente(self, monkeypatch) -> None:
        """Cloudflare do Groq recusa urllib SEM User-Agent (HTTP 403,
        error 1010) — achado ao vivo na auditoria 22/10: sem este header
        o juiz online inteiro cai na reserva local em silêncio."""
        stub = fake_urlopen(
            monkeypatch,
            body=b'{"choices": [{"message": {"content": "ok"}}]}',
        )
        p = OpenAICompatProvider(api_key="sk-x")
        await p.generate("oi")
        assert stub.seen["headers"]["User-agent"] == (
            "OmegaDrakon/od-core (LLM client)")
        assert stub.seen["headers"]["Authorization"] == "Bearer sk-x"

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

# ===========================================================================
# Gemini como 1º provider do chat (regra 19) + cadeia do launcher
# ===========================================================================


class TestGeminiProvider:
    def test_url_modelo_e_autenticacao(self, monkeypatch) -> None:
        from core.llm import GeminiProvider

        fake = fake_urlopen(
            monkeypatch,
            body=json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
            ).encode(),
        )
        provider = GeminiProvider(api_key="chave-teste")
        assert provider.configurado is True
        assert provider.model == "gemini-3-flash-preview"

        import asyncio

        saida = asyncio.run(provider.generate(chatml_body(user="oi")))

        assert saida == "ok"
        # A base do Gemini já tem o prefixo: NADA de /v1/chat/completions.
        assert fake.seen["url"] == (
            "https://generativelanguage.googleapis.com/v1beta/openai"
            "/chat/completions"
        )
        assert fake.seen["headers"]["Authorization"] == "Bearer chave-teste"
        assert json.loads(fake.seen["data"])["model"] == "gemini-3-flash-preview"

    def test_sem_chave_nao_esta_configurado(self, monkeypatch) -> None:
        from core.llm import GeminiProvider

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider(api_key="")
        assert provider.configurado is False
        assert provider.is_available() is False

    def test_local_continua_em_v1_chat_completions(self, monkeypatch) -> None:
        # Regressão: o caminho do llama-server não pode mudar.
        fake = fake_urlopen(monkeypatch, body=b"{}")
        provider = OpenAICompatProvider(name="local", base_url="http://127.0.0.1:8081")

        import asyncio

        asyncio.run(provider.generate(chatml_body()))

        assert fake.seen["url"] == "http://127.0.0.1:8081/v1/chat/completions"


class TestCadeiaDoChat:
    """build_llm_providers: Gemini primeiro, local de reserva."""

    def _build(self, monkeypatch, ordem: str | None, chave: str | None):
        import runtime.launcher as launcher

        # Hermético: sem ler o .env real da máquina (ele tem chave de verdade).
        monkeypatch.setattr(launcher, "load_env", lambda: {}, raising=True)
        monkeypatch.setattr(launcher, "_ENV_CACHE", None, raising=False)
        if ordem is None:
            monkeypatch.delenv("OD_CHAT_PROVIDERS", raising=False)
        else:
            monkeypatch.setenv("OD_CHAT_PROVIDERS", ordem)
        if chave is None:
            monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        else:
            monkeypatch.setenv("GEMINI_API_KEY", chave)
        return launcher.build_llm_providers()

    def test_padrao_e_gemini_e_depois_local(self, monkeypatch) -> None:
        providers = self._build(monkeypatch, None, "chave")
        assert [p.name for p in providers] == ["gemini", "gemma-local"]

    def test_local_sozinho_reproduz_o_comportamento_antigo(self, monkeypatch) -> None:
        providers = self._build(monkeypatch, "local", "chave")
        assert [p.name for p in providers] == ["gemma-local"]

    def test_sem_chave_o_gemini_fica_fora(self, monkeypatch) -> None:
        providers = self._build(monkeypatch, "gemini,local", None)
        assert [p.name for p in providers] == ["gemma-local"]

    def test_nome_desconhecido_e_ignorado(self, monkeypatch) -> None:
        providers = self._build(monkeypatch, "local,openai-antigo", "chave")
        assert [p.name for p in providers] == ["gemma-local"]

    @pytest.mark.asyncio
    async def test_gemini_falhando_cai_no_local(self, monkeypatch) -> None:
        """Sem internet/cota o chat continua: Gemini erra, local responde."""
        import urllib.error

        from core.llm import GeminiProvider

        corpo = json.dumps(
            {"choices": [{"message": {"role": "assistant",
                                      "content": "resposta local"}}]}
        ).encode()

        def fake(request, timeout=None):
            if "generativelanguage" in request.full_url:
                raise urllib.error.URLError("sem internet")

            class Resp:
                status = 200

                def read(self) -> bytes:
                    return corpo

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return None

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake)
        orch = Orchestrator(
            providers=[
                GeminiProvider(api_key="chave"),
                OpenAICompatProvider(name="gemma-local"),
            ]
        )

        result = await orch.process("alex", "guardian", "oi")

        assert result.llm_used == "gemma-local"
        assert result.message == "resposta local"
        # index > 0 na cadeia ⇒ resposta de reserva.
        assert result.route == "fallback"
        assert result.fallback_used is True

    def test_build_orchestrator_sobe_com_a_cadeia(self, monkeypatch, tmp_path) -> None:
        """Smoke: o boot do orchestrator real monta Gemini + local.

        Este teste existe porque o deploy de 11/11 crashou em loop: o
        `llm_timeout` saiu do `build_orchestrator` e continuou sendo usado no
        `OrchestratorConfig` — nenhum teste chamava a função inteira.
        """
        import runtime.launcher as launcher

        monkeypatch.setattr(launcher, "load_env", lambda: {}, raising=True)
        monkeypatch.setattr(launcher, "_ENV_CACHE", None, raising=False)
        monkeypatch.setattr(launcher, "DATA_DIR", tmp_path, raising=True)
        monkeypatch.setattr(launcher, "build_rag", lambda: None, raising=True)
        monkeypatch.setattr(
            launcher, "build_enciclopedia", lambda: None, raising=True
        )
        monkeypatch.setenv("GEMINI_API_KEY", "chave")

        orch = launcher.build_orchestrator(database=None)

        assert [p.name for p in orch.providers] == ["gemini", "gemma-local"]
        assert orch.cache is not None
