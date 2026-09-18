"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/llm.py
Descrição: Camada de providers LLM REAIS — OpenAICompatProvider conecta o
           Orchestrator a qualquer servidor OpenAI-compatível (llama-server
           local, vLLM, APIs de nuvem) via urllib stdlib. Converte o prompt
           ChatML do Orchestrator em messages nativas, aplica timeout,
           expõe is_available() (usado pelo ProactiveNotifier) e degrada
           com segurança em erros de rede/HTTP.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/orchestrator.py (LLMProvider: generate(prompt, timeout=...))
  - memory/history.py (build_chatml — <|im_start|>/<|im_end|>)
  - OMEGADRAKON_SPEC.md (LLM local via llama-server, porta 8081)
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.llm")

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"

# 512 tokens ≈ resposta de chat completa em CPU (llama.cpp a ~5 tok/s):
# mantém o pior caso < 2min. Aumente com OD_LLM_MAX_TOKENS se necessário.
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.7
DEFAULT_LLM_URL = "http://127.0.0.1:8081"  # llama-server local (legado)

_VALID_ROLES = {"system", "user", "assistant", "tool"}


class LLMError(Exception):
    """Erro de comunicação/configuração com o servidor de LLM."""


def parse_chatml(prompt: str) -> list[dict[str, str]]:
    """Converte o prompt ChatML do Orchestrator em messages OpenAI nativas.

    Formato esperado (memory/history.build_chatml):
        <|im_start|>system\\n...<|im_end|>
        <|im_start|>user\\n...<|im_end|>

    Se o prompt não contiver marcadores ChatML, devolve uma única mensagem
    de usuário (fallback para servidores com template próprio).
    """
    if IM_START not in prompt:
        return [{"role": "user", "content": prompt}]
    messages: list[dict[str, str]] = []
    for block in prompt.split(IM_START):
        block = block.strip()
        if not block:
            continue
        if IM_END not in block:
            # Prompt truncado/sem fechamento — trata o resto como conteúdo
            role, _, content = block.partition("\n")
            role = role.strip().lower()
            if role in _VALID_ROLES:
                messages.append({"role": role, "content": content.strip()})
            continue
        raw, _, _ = block.partition(IM_END)
        role, _, content = raw.partition("\n")
        role = role.strip().lower()
        if role not in _VALID_ROLES:
            continue
        messages.append({"role": role, "content": content.strip()})
    if not messages:
        return [{"role": "user", "content": prompt}]
    return messages


class OpenAICompatProvider:
    """Provider OpenAI-compatível (urllib stdlib) para o Orchestrator.

    Attributes:
        name:      Nome do provider (aparece em /llms e nos logs).
        base_url:  Ex: http://127.0.0.1:8081 (llama-server).
        model:     Nome do modelo enviado no payload ('' = default).
        timeout:   Timeout padrão de cada chamada (segundos).
    """

    def __init__(
        self,
        name: str = "llama-local",
        base_url: str = DEFAULT_LLM_URL,
        *,
        model: str = "",
        api_key: str = "",
        timeout: float = 120.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.name = name
        self.base_url = (base_url or DEFAULT_LLM_URL).rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._health_url = f"{self.base_url}/health"

    # -- API (usada pelo Orchestrator) ---------------------------------------

    async def generate(
        self, prompt: str, **options: Any
    ) -> Optional[str]:
        """Gera uma resposta para o prompt ChatML do Orchestrator.

        Executa a chamada HTTP síncrona fora do event loop (executor) e
        aplica o timeout configurado. Retorna o conteúdo da resposta.
        """
        timeout = float(options.get("timeout") or self.timeout)
        messages = parse_chatml(prompt)
        body = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            data = await asyncio.to_thread(
                self._post_chat, body, timeout
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"falha ao gerar com {self.name}: {type(exc).__name__}: {exc}"
            ) from exc
        message = (data.get("choices") or [{}])[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if content:
            return content
        # Modelos de raciocínio (ex: gemma-4) podem esvaziar content quando
        # o limite de tokens estoura no bloco de pensamento — devolve o
        # raciocínio como melhor esforço em vez de silêncio.
        reasoning = (message.get("reasoning_content") or "").strip()
        if reasoning:
            log.warn(
                "Resposta sem content — devolvendo reasoning",
                provider=self.name,
            )
            return reasoning
        return None

    # -- Streaming ---------------------------------------------------------

    async def generate_stream(
        self, prompt: str, **options: Any
    ):
        """Gera uma resposta em streaming (token a token).

        Yields chunks de texto conforme o servidor LLM os produz.
        Cada chunk é uma string com um ou mais tokens.
        """
        timeout = float(options.get("timeout") or self.timeout)
        messages = parse_chatml(prompt)
        body = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        try:
            async for chunk in self._post_chat_stream(body, timeout):
                yield chunk
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"falha ao gerar stream com {self.name}: {type(exc).__name__}: {exc}"
            ) from exc

    def is_available(self) -> bool:
        """Sonda /health do servidor (usado pelo ProactiveNotifier)."""
        request = urllib.request.Request(
            self._health_url, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=5.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    # -- HTTP -----------------------------------------------------------------

    async def _post_chat_stream(
        self, body: dict[str, Any], timeout: float
    ):
        """POST com streaming (SSE) — yield de chunks de texto.

        Formato SSE do OpenAI:
          data: {"choices":[{"delta":{"content":"token"}}]}
          data: [DONE]

        Mesma tolerância do caminho não-streaming: modelos de raciocínio
        (ex: gemma-4) podem mandar só `reasoning_content` — nesse caso o
        raciocínio é devolvido como melhor esforço, em vez de stream vazio.
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            resp = await asyncio.to_thread(
                lambda: urllib.request.urlopen(request, timeout=timeout)
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise LLMError(
                f"{self.name} HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"{self.name} indisponível: {exc.reason or exc}"
            ) from exc

        reasoning_parts: list[str] = []
        content_seen = False
        done = False
        try:
            # Ler a resposta streaming linha por linha
            buffer = b""
            while not done:
                # Ler do socket diretamente para ter controle do streaming
                chunk = await asyncio.to_thread(resp.read, 4096)
                if not chunk:
                    break
                buffer += chunk
                # Processar linhas completas
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue  # vazio, comentário (: keep-alive) ou outro campo
                    data_str = line[6:]  # remover "data: "
                    if data_str == "[DONE]":
                        done = True
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        # Ignorar linhas JSON inválidas
                        continue
                    for choice in data.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            content_seen = True
                            yield content
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            reasoning_parts.append(reasoning)

            if not content_seen and reasoning_parts:
                log.warn(
                    "Stream sem content — devolvendo reasoning",
                    provider=self.name,
                )
                yield "".join(reasoning_parts).strip()
        finally:
            resp.close()

    def _post_chat(self, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise LLMError(
                f"{self.name} HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"{self.name} indisponível: {exc.reason or exc}"
            ) from exc
        if not raw:
            raise LLMError(f"{self.name} respondeu vazio")
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"{self.name} resposta JSON inválida: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise LLMError(f"{self.name} resposta inesperada")
        return data

    # -- Introspecção ---------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": bool(self.api_key),
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }