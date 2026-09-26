"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/orchestrator.py
Descrição: Orchestrator Pipeline — pipeline de 8 etapas para processamento
           de mensagens: rate limit → datetime → quick responses (AIML) →
           cache LLM → histórico → LLM → fallback → pós-processamento.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky core/orchestrator.py (pipeline de 8 etapas, v0.7.0)
  - NICKY_LEGACY_ANALYSIS.md §4.2 (etapas documentadas do legado)
  - ROADMAP_ABSORCAO.md Fase 3, item 3.4

Architecture:
    process() percorre as etapas em ordem, com atalhos (short-circuit):
      1. RATE LIMIT    — janela deslizante por usuário (padrão 10 msg/60s).
      2. DATETIME      — detecção PT-BR ("que horas", "que dia") responde sem
                         LLM; além disso injeta data/hora no system prompt
                         quando o caminho segue para o LLM.
      3. QUICK RESPONSES — respostas instantâneas (AIML legado) — rota
                         "quick_response", sem chamar LLM.
      4. CACHE LLM     — consulta ao LLMCache por prompt normalizado +
                         perfil (SHA-256); hit responde sem LLM.
      5. HISTÓRICO     — monta o contexto ChatML com os últimos N turns da
                         conversa (memória ConversationHistory).
      6. LLM           — providers são tentados em ordem; o primeiro que
                         responder é usado.
      7. FALLBACK      — se um provider falhar (exceção/timeout), o próximo
                         da lista assume; esgotados → "llm_unavailable".
      8. PÓS-PROCESSAMENTO — grava resposta no cache e no histórico e
                         registra métricas.

    O Orchestrator aceita providers plugáveis (protocolo LLMProvider) —
    nenhum LLM externo é obrigatório: sem providers, respostas curtas
    (datetime/quick) ainda funcionam e o resto responde "indisponível".
    Componentes de memória (history/cache/quick) são opcionais; quando
    ausentes, as etapas correspondentes são puladas.

Usage:
    from core.orchestrator import Orchestrator, StaticProvider

    orch = Orchestrator(
        providers=[StaticProvider("qwen", "Olá!")],
        history=ConversationHistory(base_dir="data/conversations"),
        cache=LLMCache(cache_dir="data/llm_cache"),
        quick=QuickResponses(data_dir="data/quick_responses"),
    )
    result = await orch.process("alex", "guardian", "Bom dia!")
    result.route       # "quick_response" | "llm" | "fallback" | ...
    result.message     # texto da resposta
"""

from __future__ import annotations

import asyncio
import inspect
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from memory.cache import LLMCache
    from memory.history import ConversationHistory
    from memory.quick_responses import QuickResponses

__signature__ = "OD // CORE"

log = get_logger("omega.core.orchestrator")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_RATE_LIMIT_MAX = 10
DEFAULT_RATE_LIMIT_WINDOW_S = 60.0
DEFAULT_LLM_TIMEOUT_S = 60.0
DEFAULT_MAX_HISTORY_TURNS = 3  # legado: 3 turns = 6 mensagens
DEFAULT_UNAVAILABLE_MESSAGE = "Nenhum LLM disponível no momento."
# Motivo registrado no resultado/evento quando nenhum provider responde — o
# mesmo em `process` e `process_stream`.
DEFAULT_UNAVAILABLE_ERROR = "todos os providers de LLM falharam"

# Rotas possíveis do pipeline
ROUTE_RATE_LIMITED = "rate_limited"
ROUTE_DATETIME = "datetime"
ROUTE_QUICK = "quick_response"
ROUTE_INTENT = "action_intent"
ROUTE_CACHE = "cache"

# Respostas que NUNCA entram no cache: são falha do momento (LLM alucinou
# etiqueta de log, recusou por prompt interno, truncou) e não conhecimento.
# Cacheadas, renasciam a cada repetição da pergunta — "resposta de cache sem
# nexo" (2026-09-26). Casada contra o INÍCIO da resposta, sanitizada.
_CACHE_BAN_PREFIXES = (
    "[nicky][crit]",
    "[crit]",
    "[nicky][warn]",
    "[warn]",
    "[nicky][online]",
    "[online]",
    "[nicky][info]",
    "[info]",
    # Vazamento de raciocínio do modelo (CoT em inglês) não é resposta.
    "here's a thinking process",
    "here is a thinking process",
)


def _cacheable(text: str) -> bool:
    """True quando a resposta pode ser cacheada (não é falha/truncamento)."""
    return cache_failure_reason(text) == ""


def cache_failure_reason(text: str) -> str:
    """Motivo pelo qual a resposta NÃO deve ser cacheada ('' = cacheável).

    Usado pela guarda da etapa 8 e pelo saneamento /admin/cache/prune.
    """
    candidate = (text or "").strip()
    if not candidate:
        return "vazia"
    lowered = candidate.lower()
    for prefix in _CACHE_BAN_PREFIXES:
        if lowered.startswith(prefix):
            return f"etiqueta de log/falha: {prefix}"
    # Truncamento no meio da frase (max_tokens estourou): incompleto.
    if candidate[-1] in ",;:-":
        return "truncada (pontuação final aberta)"
    return ""
ROUTE_LLM = "llm"
ROUTE_FALLBACK = "fallback"
ROUTE_UNAVAILABLE = "llm_unavailable"
ROUTE_ERROR = "error"

# Texto da resposta de rate limit. É constante (e não literal solto em cada
# caminho) porque `process` e `process_stream` precisam registrar e publicar a
# MESMA mensagem para a mesma situação.
RATE_LIMITED_MESSAGE = "Muitas mensagens em pouco tempo. Aguarde um instante."

TERMINAL_NO_LLM = {ROUTE_RATE_LIMITED, ROUTE_DATETIME, ROUTE_QUICK, ROUTE_CACHE}
# Rotas que registram a interação no histórico (quando persist): além do
# caminho LLM, as respostas terminais sem LLM também entram na conta —
# antes só a etapa 8 gravava e quem repetia uma pergunta (caía no cache,
# datetime ou quick) via a conversa sumir do histórico (2026-09-24).
# Rate limit e indisponível NÃO registram (não houve resposta da conta).
PERSISTED_ROUTES = {
    ROUTE_DATETIME, ROUTE_QUICK, ROUTE_INTENT, ROUTE_CACHE, ROUTE_LLM, ROUTE_FALLBACK,
}

# ---------------------------------------------------------------------------
# Providers de LLM
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """Provider de LLM consumido pelo Orchestrator.

    Implemente `generate(prompt, ...) -> str` (sync ou async). Exceções e
    timeouts fazem o Orchestrator tentar o próximo provider da lista.
    """

    name: str

    def generate(self, prompt: str, **options: Any) -> Any:
        """Gera resposta para o prompt (str ou awaitable)."""


class StaticProvider:
    """Provider determinístico — útil para testes e pipelines locais."""

    name: str

    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self.text = text

    def generate(self, prompt: str, **options: Any) -> str:
        return self.text


class RecordingProvider:
    """Provider que registra os prompts recebidos (para inspeção/testes).

    Attributes:
        name:    Nome do provider.
        reply:   Texto fixo devolvido.
        prompts: Lista de prompts recebidos.
    """

    def __init__(self, name: str, reply: str = "resposta", *, fail: bool = False) -> None:
        self.name = name
        self.reply = reply
        self.fail = fail
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **options: Any) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError(f"{self.name} indisponível")
        return self.reply


# ---------------------------------------------------------------------------
# Datetime PT-BR
# ---------------------------------------------------------------------------

_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

_TIME_RE = re.compile(
    r"\b(que horas|horas (é|são|estão)|hora agora|hora atual|hora certa|quanto é a hora)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(que dia|que dia é|dia é hoje|dia de hoje|data de hoje|data atual|qual a data|qual é a data|em que dia)\b",
    re.IGNORECASE,
)


def build_datetime_line(now: Optional[time.struct_time] = None) -> str:
    """Linha de contexto data/hora em PT-BR anexada ao system prompt."""
    t = now or time.localtime()
    wd = _WEEKDAYS[t.tm_wday]
    mo = _MONTHS[t.tm_mon - 1]
    return (
        f"Hoje é {wd}, {t.tm_mday} de {mo} de {t.tm_year}, "
        f"e agora são {t.tm_hour:02d}:{t.tm_min:02d}."
    )


def detect_datetime_question(
    text: str,
    now: Optional[time.struct_time] = None,
) -> Optional[str]:
    """Responde perguntas de data/hora em PT-BR sem LLM.

    Returns:
        Resposta pronta quando o texto pergunta hora/data, senão None.
    """
    t = now or time.localtime()
    if _TIME_RE.search(text):
        return f"Agora são {t.tm_hour:02d}:{t.tm_min:02d}."
    if _DATE_RE.search(text):
        return f"Hoje é {_WEEKDAYS[t.tm_wday]}, {t.tm_mday} de {_MONTHS[t.tm_mon - 1]} de {t.tm_year}."
    return None


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Rate limit por usuário com janela deslizante.

    Attributes:
        max_requests: Máximo de chamadas por janela.
        window_seconds: Tamanho da janela em segundos.
        clock: Função de relógio (injetável para testes).
    """

    def __init__(
        self,
        *,
        max_requests: int = DEFAULT_RATE_LIMIT_MAX,
        window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_S,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = max(0.1, window_seconds)
        self._clock = clock or time.monotonic
        self._window: dict[str, deque[float]] = {}

    def allow(self, user_id: str) -> bool:
        """Consome um slot se dentro do limite. False = limitado."""
        now = self._clock()
        bucket = self._window.setdefault(user_id, deque())
        while bucket and now - bucket[0] >= self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            return False
        bucket.append(now)
        return True

    def remaining(self, user_id: str) -> int:
        """Slots restantes na janela corrente."""
        now = self._clock()
        bucket = self._window.get(user_id)
        if bucket is None:
            return self.max_requests
        while bucket and now - bucket[0] >= self.window_seconds:
            bucket.popleft()
        return max(0, self.max_requests - len(bucket))

    def clear(self, user_id: Optional[str] = None) -> int:
        """Limpa janelas (de um usuário ou de todos). Retorna nº removido."""
        if user_id is not None:
            bucket = self._window.pop(user_id, None)
            return len(bucket) if bucket else 0
        count = sum(len(b) for b in self._window.values())
        self._window.clear()
        return count


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OrchestratorConfig:
    """Configuração do pipeline."""

    rate_limit_max: int = DEFAULT_RATE_LIMIT_MAX
    rate_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_S
    llm_timeout_s: float = DEFAULT_LLM_TIMEOUT_S
    inject_datetime: bool = True
    enable_action_intents: bool = True  # fast path determinístico (v0.27.5)
    max_history_turns: Optional[int] = DEFAULT_MAX_HISTORY_TURNS
    unavailable_message: str = DEFAULT_UNAVAILABLE_MESSAGE
    # System prompt padrão (ex: identidade da Interface Viva) usado quando
    # process() é chamado sem system_prompt explícito.
    default_system_prompt: str = ""


@dataclass(slots=True)
class OrchestrationResult:
    """Resultado de uma mensagem processada pelo pipeline.

    Attributes:
        user_id:    Usuário da conversa.
        profile:    Perfil usado.
        text:       Mensagem original.
        route:      Etapa que produziu a resposta (rate_limited, datetime,
                    quick_response, cache, llm, fallback, llm_unavailable,
                    error).
        message:    Texto da resposta.
        llm_used:   Nome do provider que respondeu ("" se sem LLM).
        fallback_used: True quando um provider reserva respondeu.
        cached:     True quando veio do cache.
        prompt:     Prompt ChatML enviado ao LLM (rotas llm/fallback).
        latency_ms: Tempo total do pipeline.
        error:      Mensagem de erro (rota error/llm_unavailable).
    """

    user_id: str = ""
    profile: str = ""
    text: str = ""
    route: str = ROUTE_ERROR
    message: str = ""
    llm_used: str = ""
    fallback_used: bool = False
    cached: bool = False
    prompt: str = ""
    latency_ms: float = 0.0
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    @property
    def ok(self) -> bool:
        """True quando a rota produziu uma resposta utilizável."""
        return self.route not in (ROUTE_RATE_LIMITED, ROUTE_UNAVAILABLE, ROUTE_ERROR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "profile": self.profile,
            "text": self.text,
            "route": self.route,
            "ok": self.ok,
            "message": self.message,
            "llm_used": self.llm_used,
            "fallback_used": self.fallback_used,
            "cached": self.cached,
            "latency_ms": round(self.latency_ms, 3),
            "error": self.error,
        }


@dataclass(slots=True)
class OrchestratorMetrics:
    """Métricas acumuladas do pipeline."""

    processed: int = 0
    rate_limited: int = 0
    datetime: int = 0
    quick: int = 0
    intents: int = 0
    cache_hits: int = 0
    llm: int = 0
    fallback: int = 0
    unavailable: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        if self.processed == 0:
            return 0.0
        return round(self.total_latency_ms / self.processed, 3)

    def snapshot(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "rate_limited": self.rate_limited,
            "datetime": self.datetime,
            "quick": self.quick,
            "intents": self.intents,
            "cache_hits": self.cache_hits,
            "llm": self.llm,
            "fallback": self.fallback,
            "unavailable": self.unavailable,
            "errors": self.errors,
            "avg_latency_ms": self.avg_latency_ms,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """Pipeline central de 8 etapas para mensagens.

    Attributes:
        providers:  Lista ordenada de providers LLM (fallback por ordem).
        history:    ConversationHistory opcional (etapas 5 e 8).
        cache:      LLMCache opcional (etapas 4 e 8).
        quick:      QuickResponses opcional (etapa 3).
        event_bus:  EventBus opcional (publica orchestrator.responded).
        config:     OrchestratorConfig.
        action_registry: ActionRegistry opcional para execução de ações.
    """

    def __init__(
        self,
        *,
        providers: Optional[list[LLMProvider]] = None,
        history: Optional[ConversationHistory] = None,
        cache: Optional[LLMCache] = None,
        quick: Optional[QuickResponses] = None,
        event_bus: Optional[EventBus] = None,
        config: Optional[OrchestratorConfig] = None,
        clock: Optional[Callable[[], float]] = None,
        action_registry: Optional[Any] = None,
    ) -> None:
        self._providers = list(providers or [])
        self.history = history
        self.cache = cache
        self.quick = quick
        self._event_bus = event_bus
        self._config = config or OrchestratorConfig()
        self._limiter = RateLimiter(
            max_requests=self._config.rate_limit_max,
            window_seconds=self._config.rate_window_seconds,
            clock=clock,
        )
        self._metrics = OrchestratorMetrics()
        self._lock = threading.RLock()
        self._action_registry = action_registry
        self._action_callables: dict[str, Callable] = {}  # ações injetadas pelo framework

    # -- Propriedades --------------------------------------------------------

    @property
    def metrics(self) -> OrchestratorMetrics:
        return self._metrics

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    @property
    def providers(self) -> tuple[LLMProvider, ...]:
        """Providers registrados, na ordem de fallback (leitura)."""
        return tuple(self._providers)

    @property
    def action_registry(self) -> Optional[Any]:
        """ActionRegistry para execução de ações (opcional)."""
        return self._action_registry

    def set_action_registry(self, registry: Any) -> None:
        """Define o ActionRegistry para execução de ações."""
        self._action_registry = registry

    def add_action(self, name: str, handler: Callable) -> None:
        """Adiciona uma ação injetável pelo framework (não usa o registry)."""
        self._action_callables[name] = handler

    def add_provider(self, provider: LLMProvider) -> None:
        """Adiciona um provider ao final da lista (último = fallback)."""
        self._providers.append(provider)

    # -- Pipeline ------------------------------------------------------------

    async def process_stream(
        self,
        user_id: str,
        profile: str,
        text: str,
        *,
        system_prompt: str = "",
        session_id: str = "",
        role: str = "admin",
    ):
        """Processa uma mensagem com streaming token-a-token.

        Yields chunks de texto conforme o LLM os produz.
        No final, yields um dict com metadados da resposta.

        Os MESMOS desfechos do `process` são registrados aqui: toda saída
        terminal passa pelo `_finish`, então métricas, evento
        `orchestrator.responded` e o log "Message processed" saem iguais nos
        dois transportes (REST e WebSocket).
        """
        if not system_prompt:
            system_prompt = self._config.default_system_prompt
        started = time.perf_counter()

        # Etapa 1 — Rate limit
        if not self._limiter.allow(user_id):
            self._metrics.rate_limited += 1
            # O cliente recebe o código curto no chunk de erro; o evento e o
            # log levam a mesma mensagem que o `process` publicaria.
            result = self._stream_result(
                user_id, profile, text, ROUTE_RATE_LIMITED, RATE_LIMITED_MESSAGE
            )
            await self._finish(result, started)
            yield {"type": "error", "message": "rate_limited"}
            return

        # Etapa 2 — Datetime (resposta direta). O stream NÃO tem persist:
        # só é chamado com conta autenticada (REST/WS), então registra.
        if self._config.inject_datetime:
            answer = detect_datetime_question(text)
            if answer is not None:
                self._metrics.datetime += 1
                result = self._stream_result(
                    user_id, profile, text, ROUTE_DATETIME, answer
                )
                await self._record_terminal(result, text, persist=True)
                await self._finish(result, started)
                yield {"type": "token", "content": answer}
                yield {
                    "type": "done",
                    "content": answer,
                    "route": ROUTE_DATETIME,
                    "llm_used": "",
                }
                return

        # Etapa 3 — Quick responses
        if self.quick is not None:
            quick_answer = self.quick.get(text.strip().lower())
            if quick_answer is not None:
                self._metrics.quick += 1
                result = self._stream_result(
                    user_id, profile, text, ROUTE_QUICK, quick_answer
                )
                await self._record_terminal(result, text, persist=True)
                await self._finish(result, started)
                yield {"type": "token", "content": quick_answer}
                yield {
                    "type": "done",
                    "content": quick_answer,
                    "route": ROUTE_QUICK,
                    "llm_used": "",
                }
                return

        # Etapa 3.5 — Fast path de intenções (mesma regra do `process`: papel
        # vem da credencial; "anonymous" não aciona action).
        if (
            self._config.enable_action_intents
            and self._action_registry is not None
            and role != "anonymous"
        ):
            from core.intents import detect_action_intent, format_intent_result, safe_math

            answer = safe_math(text)
            route_detail = "math"
            if answer is None:
                intent = detect_action_intent(text)
                if intent is not None:
                    action_name, params = intent
                    data = await self.execute_action(
                        action_name, params, user_id, role=role
                    )
                    answer = format_intent_result(action_name, data)
                    route_detail = action_name
            if answer is not None:
                self._metrics.intents += 1
                result = self._stream_result(
                    user_id,
                    profile,
                    text,
                    ROUTE_INTENT,
                    answer,
                    llm_used=f"fastpath:{route_detail}",
                )
                await self._record_terminal(result, text, persist=True)
                await self._finish(result, started)
                yield {"type": "token", "content": answer}
                yield {
                    "type": "done",
                    "content": answer,
                    "route": ROUTE_INTENT,
                    "llm_used": f"fastpath:{route_detail}",
                }
                return

        # Etapa 4 — Cache LLM
        if self.cache is not None:
            cached = self.cache.get(text, profile=profile)
            if cached is not None:
                self._metrics.cache_hits += 1
                result = self._stream_result(
                    user_id, profile, text, ROUTE_CACHE, cached, cached=True
                )
                await self._record_terminal(result, text, persist=True)
                await self._finish(result, started)
                yield {"type": "token", "content": cached}
                yield {
                    "type": "done",
                    "content": cached,
                    "route": ROUTE_CACHE,
                    "llm_used": "",
                    "cached": True,
                }
                return

        # Etapa 5 — Histórico: monta contexto ChatML
        prompt = self._build_prompt(user_id, profile, text, system_prompt)

        # Etapas 6 e 7 — LLM com streaming
        if not self._providers:
            self._metrics.unavailable += 1
            result = self._stream_result(
                user_id,
                profile,
                text,
                ROUTE_UNAVAILABLE,
                self._config.unavailable_message,
                error=DEFAULT_UNAVAILABLE_ERROR,
            )
            await self._finish(result, started)
            yield {"type": "error", "message": "providers_indisponiveis"}
            return

        # Tentar streaming com fallback para non-streaming
        full_response = ""
        llm_used = ""
        fallback_used = False
        route = ROUTE_LLM

        for index, provider in enumerate(self._providers):
            try:
                llm_used = provider.name
                fallback_used = index > 0
                if fallback_used:
                    route = ROUTE_FALLBACK

                # Tentar streaming
                async for chunk in provider.generate_stream(
                    prompt, timeout=self._config.llm_timeout_s
                ):
                    full_response += chunk
                    yield {"type": "token", "content": chunk}
                break  # Sucesso, sair do loop
            except Exception as exc:
                log.warn(
                    "LLM provider streaming failed",
                    provider=provider.name,
                    error=f"{type(exc).__name__}: {exc}",
                )
                # Fallback para non-streaming NESTE provider, com a mesma
                # tolerância do `_generate` (provider sync também vale).
                try:
                    message = await self._generate_one(provider, prompt)
                except Exception:
                    continue
                if message:
                    full_response = message
                    yield {"type": "token", "content": message}
                    break
        else:
            # Todos os providers falharam
            self._metrics.unavailable += 1
            result = self._stream_result(
                user_id,
                profile,
                text,
                ROUTE_UNAVAILABLE,
                self._config.unavailable_message,
                error=DEFAULT_UNAVAILABLE_ERROR,
            )
            await self._finish(result, started)
            yield {"type": "error", "message": "todos_providers_falharam"}
            return

        if not full_response:
            self._metrics.unavailable += 1
            result = self._stream_result(
                user_id,
                profile,
                text,
                ROUTE_UNAVAILABLE,
                self._config.unavailable_message,
                error=DEFAULT_UNAVAILABLE_ERROR,
            )
            await self._finish(result, started)
            yield {"type": "error", "message": "resposta_vazia"}
            return

        # Atualizar métricas
        if fallback_used:
            self._metrics.fallback += 1
        else:
            self._metrics.llm += 1

        # Etapa 8 — Pós-processamento
        await self._post_process(user_id, profile, text, full_response, llm_used)

        # Finalização igual à do `process`: métricas, evento no EventBus, log.
        # (O `processed`/`total_latency_ms` sai daqui — não somar de novo.)
        result = self._stream_result(
            user_id,
            profile,
            text,
            route,
            full_response,
            llm_used=llm_used,
            fallback_used=fallback_used,
            prompt=prompt,
        )
        await self._finish(result, started)

        yield {
            "type": "done",
            "content": full_response,
            "route": route,
            "llm_used": llm_used,
            "latency_ms": result.latency_ms,
        }

    async def process(
        self,
        user_id: str,
        profile: str,
        text: str,
        *,
        system_prompt: str = "",
        session_id: str = "",
        role: str = "admin",
        persist: bool = True,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> OrchestrationResult:
        """Processa uma mensagem pelo pipeline de 8 etapas.

        Args:
            user_id:      Usuário da conversa.
            profile:      Perfil (ex: "guardian").
            text:         Mensagem do usuário.
            system_prompt: Prompt de sistema (identidade/instruções).
            session_id:   Identificador de sessão (auditoria/eventos).
            role:         Papel de quem fala, para o fast path de intenções
                          (o dono é "admin"; a conta comum, "user"; quem
                          conversa sem conta, "anonymous" — que NÃO aciona
                          action nenhuma).
            persist:      Quando False, não grava cache nem histórico (a
                          conversa anônima vive só no navegador do cliente).
            extra_history: Conversa vinda do CLIENTE (lista de {"role",
                          "content"}), usada no lugar do histórico do banco.
                          É o que dá contexto à conversa anônima sem gravar
                          nada.

        Returns:
            OrchestrationResult com a rota que produziu a resposta.
        """
        if not system_prompt:
            system_prompt = self._config.default_system_prompt
        started = time.perf_counter()
        result = OrchestrationResult(
            user_id=user_id,
            profile=profile,
            text=text,
        )

        # Etapa 1 — Rate limit (janela deslizante por usuário)
        if not self._limiter.allow(user_id):
            result.route = ROUTE_RATE_LIMITED
            result.message = RATE_LIMITED_MESSAGE
            self._metrics.rate_limited += 1
            return await self._finish(result, started)

        # Etapa 2 — Datetime (resposta direta PT-BR, sem LLM)
        if self._config.inject_datetime:
            answer = detect_datetime_question(text)
            if answer is not None:
                result.route = ROUTE_DATETIME
                result.message = answer
                self._metrics.datetime += 1
                await self._record_terminal(result, text, persist=persist)
                return await self._finish(result, started)

        # Etapa 3 — Quick responses (AIML legado)
        if self.quick is not None:
            quick_answer = self.quick.get(text.strip().lower())
            if quick_answer is not None:
                result.route = ROUTE_QUICK
                result.message = quick_answer
                self._metrics.quick += 1
                await self._record_terminal(result, text, persist=persist)
                return await self._finish(result, started)

        # Etapa 3.5 — Fast path de intenções (v0.27.5): respostas
        # operacionais sem LLM (matemática básica + actions de leitura),
        # só quando o ActionRegistry está conectado. Quem conversa sem conta
        # (papel "anonymous") não aciona action nenhuma: a matemática continua,
        # mas a intenção operacional cai para o LLM.
        if (
            self._config.enable_action_intents
            and self._action_registry is not None
            and role != "anonymous"
        ):
            from core.intents import detect_action_intent, format_intent_result, safe_math

            answer: Optional[str] = safe_math(text)
            route_detail = "math"
            if answer is None:
                intent = detect_action_intent(text)
                if intent is not None:
                    action_name, params = intent
                    data = await self.execute_action(
                        action_name, params, user_id, role=role
                    )
                    answer = format_intent_result(action_name, data)
                    route_detail = action_name
            if answer is not None:
                result.route = ROUTE_INTENT
                result.message = answer
                result.llm_used = f"fastpath:{route_detail}"
                self._metrics.intents += 1
                await self._record_terminal(result, text, persist=persist)
                return await self._finish(result, started)

        # Etapa 4 — Cache LLM (SHA-256, prompt normalizado + perfil).
        # `persist=False` (conversa anônima) NÃO usa o cache: ele vive no
        # banco e serviria resposta de outra conversa.
        if self.cache is not None and persist:
            cached = self.cache.get(text, profile=profile)
            if cached is not None:
                result.route = ROUTE_CACHE
                result.message = cached
                result.cached = True
                self._metrics.cache_hits += 1
                await self._record_terminal(result, text, persist=persist)
                return await self._finish(result, started)

        # Etapa 5 — Histórico: monta contexto ChatML
        prompt = self._build_prompt(
            user_id, profile, text, system_prompt, extra_history=extra_history
        )

        # Etapas 6 e 7 — LLM com fallback
        message, llm_used, fallback_used = await self._generate(prompt)
        if message is None:
            result.route = ROUTE_UNAVAILABLE
            result.message = self._config.unavailable_message
            result.error = DEFAULT_UNAVAILABLE_ERROR
            result.prompt = prompt
            self._metrics.unavailable += 1
            return await self._finish(result, started)

        result.route = ROUTE_FALLBACK if fallback_used else ROUTE_LLM
        result.message = message
        result.llm_used = llm_used
        result.fallback_used = fallback_used
        result.prompt = prompt
        if fallback_used:
            self._metrics.fallback += 1
        else:
            self._metrics.llm += 1

        # Etapa 8 — Pós-processamento: persiste cache + histórico
        # (a conversa anônima não grava nada — "nada no banco").
        if persist:
            await self._post_process(user_id, profile, text, message, llm_used)
        return await self._finish(result, started)

    # -- Etapas internas -----------------------------------------------------

    def _build_prompt(
        self,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> str:
        """Monta o prompt ChatML com histórico (últimos N turns) + datetime.

        Com `extra_history`, o contexto vem do cliente (conversa anônima) em
        vez do banco — mesma regra de truncamento por turnos.
        """
        from memory.history import build_chatml

        system = system_prompt or ""
        if self._config.inject_datetime:
            context_line = build_datetime_line()
            # A linha de data/hora vai DEPOIS do system prompt: o prefixo
            # (identidade estática) fica idêntico entre requests e o
            # llama-server reaproveita o cache de KV (~25s economizados por
            # mensagem em CPU; inverter a ordem invalida o cache todo minuto).
            system = f"{system}\n{context_line}".strip() if system else context_line

        messages: list[dict[str, str]] = []
        turn_limit = self._config.max_history_turns
        if extra_history is not None:
            # Contexto vindo do cliente (anônimo): nada é lido do banco.
            turnos = list(extra_history)
            if turn_limit is not None:
                turnos = turnos[-(turn_limit * 2):]
            for msg in turnos:
                if not isinstance(msg, dict):
                    continue
                papel = str(msg.get("role") or "")
                conteudo = str(msg.get("content") or "")
                if papel in ("user", "assistant") and conteudo:
                    messages.append({"role": papel, "content": conteudo})
        elif self.history is not None:
            history_messages = self.history.get_history(user_id, profile)
            if turn_limit is not None:
                max_msgs = turn_limit * 2
                history_messages = history_messages[-max_msgs:]
            for msg in history_messages:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": text})
        return build_chatml(messages, system_prompt=system)

    async def _generate_one(self, provider: Any, prompt: str) -> Optional[str]:
        """Chama `provider.generate` aceitando implementação sync OU async.

        Serve os dois caminhos: o não-streaming (`_generate`) e o fallback do
        streaming. Sem isso, um provider sync responderia no REST e falharia no
        WebSocket — a mesma conversa mudando de comportamento por transporte.
        """
        call = provider.generate(prompt, timeout=self._config.llm_timeout_s)
        if inspect.isawaitable(call):
            output = await asyncio.wait_for(call, timeout=self._config.llm_timeout_s)
        else:
            output = call
        if output is None:
            raise RuntimeError("provider retornou vazio")
        return str(output)

    async def _generate(self, prompt: str) -> tuple[Optional[str], str, bool]:
        """Tenta providers em ordem; retorna (texto, nome, usou_fallback)."""
        if not self._providers:
            return None, "", False
        for index, provider in enumerate(self._providers):
            try:
                output = await self._generate_one(provider, prompt)
                return output, provider.name, index > 0
            except asyncio.TimeoutError:
                log.warn(
                    "LLM provider timeout",
                    provider=provider.name,
                    timeout=self._config.llm_timeout_s,
                )
            except Exception as exc:
                log.warn(
                    "LLM provider failed",
                    provider=provider.name,
                    error=f"{type(exc).__name__}: {exc}",
                )
        return None, "", False

    async def _record_terminal(
        self,
        result: OrchestrationResult,
        text: str,
        *,
        persist: bool,
    ) -> None:
        """Registra a interação de uma rota terminal SEM LLM (melhor esforço).

        Só o histórico é gravado aqui — o cache é printo da ETAPA que respondeu
        (a rota cache já veio dele; datetime/quick/intent não são LLM). Respeita
        `persist` (conversa anônima continua sem deixar rastro) e NUNCA quebra a
        resposta: falha de escrita vira log de aviso, igual à etapa 8.
        """
        if not persist or self.history is None:
            return
        if result.route not in PERSISTED_ROUTES:
            return
        try:
            self.history.add_interaction(
                result.user_id, result.profile, text, result.message or "",
                llm_used=result.llm_used,
            )
        except Exception as exc:
            log.warn(
                "Orchestrator history write failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _post_process(
        self,
        user_id: str,
        profile: str,
        text: str,
        message: str,
        llm_used: str,
    ) -> None:
        """Grava cache + histórico (melhor esforço, nunca quebra a resposta).

        Respostas de falha (etiqueta de log [CRIT]/[WARN]..., truncadas no
        meio) NÃO vão para o cache: cacheadas, a mesma pergunta devolvia a
        falha para sempre — "resposta de cache sem nexo" (2026-09-26).
        """
        if self.cache is not None and _cacheable(message):
            try:
                self.cache.set(
                    text,
                    message,
                    llm_used=llm_used,
                    response_time_ms=1.0,
                    profile=profile,
                )
            except Exception as exc:
                log.warn(
                    "Orchestrator cache write failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
        if self.history is not None:
            try:
                self.history.add_interaction(
                    user_id, profile, text, message, llm_used=llm_used
                )
            except Exception as exc:
                log.warn(
                    "Orchestrator history write failed",
                    error=f"{type(exc).__name__}: {exc}",
                )

    def _stream_result(
        self,
        user_id: str,
        profile: str,
        text: str,
        route: str,
        message: str,
        *,
        llm_used: str = "",
        cached: bool = False,
        fallback_used: bool = False,
        prompt: str = "",
        error: str = "",
    ) -> OrchestrationResult:
        """Monta o `OrchestrationResult` equivalente ao fim de um stream.

        O streaming devolve chunks (e não um resultado), mas a resposta precisa
        ser registrada da MESMA forma que no caminho não-streaming: sem isto, a
        mesma conversa contava nas métricas e era publicada em
        `orchestrator.responded` de um jeito diferente só por causa do
        transporte (REST x WebSocket) — ou simplesmente não era publicada.
        """
        return OrchestrationResult(
            user_id=user_id,
            profile=profile,
            text=text,
            route=route,
            message=message,
            llm_used=llm_used,
            cached=cached,
            fallback_used=fallback_used,
            prompt=prompt,
            error=error,
        )

    async def _finish(self, result: OrchestrationResult, started: float) -> OrchestrationResult:
        """Finaliza o resultado: duração, métricas e evento opcional."""
        result.finished_at = time.time()
        result.latency_ms = (time.perf_counter() - started) * 1000.0

        with self._lock:
            self._metrics.processed += 1
            self._metrics.total_latency_ms += result.latency_ms

        if result.route == ROUTE_ERROR:
            self._metrics.errors += 1

        await self._publish_event(result)

        log.info(
            "Message processed",
            route=result.route,
            user=result.user_id or "-",
            profile=result.profile or "-",
            llm=result.llm_used or "-",
            latency_ms=round(result.latency_ms, 3),
        )
        return result

    async def execute_action(
        self,
        action_name: str,
        params: Optional[dict[str, Any]] = None,
        user_id: str = "",
        role: str = "admin",
    ) -> Any:
        """Executa uma ação via ActionRegistry.

        Args:
            action_name: Nome da ação a executar.
            params: Parâmetros da ação (opcional).
            user_id: ID do usuário para registro de auditoria.
            role: Papel do solicitante (para Security Layer).

        Returns:
            Resultado da ação (dados brutos) ou None em caso de erro.

        Raises:
            RuntimeError: Se ActionRegistry não estiver disponível.
        """
        if self._action_registry is None:
            raise RuntimeError("ActionRegistry não disponível no Orchestrator")
        import asyncio
        result = await self._action_registry.execute(
            action_name,
            params=params or {},
            role=role,
        )
        if result.status == "ok":
            return result.data
        elif result.status == "denied":
            log.warn("Orchestrator action denied", action=action_name, error=result.error)
            return None
        elif result.status == "invalid":
            log.warn("Orchestrator action invalid params", action=action_name, errors=result.errors)
            return None
        elif result.status == "not_found":
            log.warn("Orchestrator action not found", action=action_name)
            return None
        else:
            log.error("Orchestrator action error", action=action_name, error=result.error)
            return None

    async def _publish_event(self, result: OrchestrationResult) -> None:
        """Publica orchestrator.responded no EventBus (best-effort)."""
        if self._event_bus is None or not getattr(
            self._event_bus, "running", False
        ):
            return
        try:
            from core.event_bus import Event

            await self._event_bus.publish(
                Event(
                    topic="orchestrator.responded",
                    data={
                        "user_id": result.user_id,
                        "profile": result.profile,
                        "route": result.route,
                        "message": result.message,
                        "llm_used": result.llm_used,
                    },
                    source="orchestrator",
                )
            )
        except Exception as exc:
            log.warn(
                "Orchestrator event publish failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico do pipeline."""
        return {
            "providers": [getattr(p, "name", str(p)) for p in self._providers],
            "stages": [
                "rate_limit",
                "datetime",
                "quick_responses",
                "action_intents",
                "cache",
                "history",
                "llm",
                "fallback",
                "post_processing",
            ],
            "config": {
                "rate_limit_max": self._config.rate_limit_max,
                "rate_window_seconds": self._config.rate_window_seconds,
                "llm_timeout_s": self._config.llm_timeout_s,
                "inject_datetime": self._config.inject_datetime,
                "max_history_turns": self._config.max_history_turns,
            },
            "metrics": self._metrics.snapshot(),
        }
