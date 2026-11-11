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
import hashlib
import inspect
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover — só tipagem (evita ciclo de import)
    pass


def _profile_display_name(profile: str) -> str:
    """Nome canônico da entidade (agents.profiles.profile_display_name).

    Import tardio em função (profiles importa logger; evita ciclo no módulo).
    Falha silenciosa: devolve a própria chave.
    """
    try:
        from agents.profiles import profile_display_name

        return profile_display_name(profile)
    except Exception:
        return (profile or "").strip()

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from memory.cache import LLMCache
    from memory.semantic_cache import SemanticCache
    from memory.history import ConversationHistory
    from memory.quick_responses import QuickResponses

__signature__ = "OD // CORE"

log = get_logger("omega.core.orchestrator")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Actions cuja NEGAÇÃO de papel vira resposta guiada (permissao_negada)
# em vez de cair no LLM. v1.8.1: ha_device_control; lote 2 (escrita
# Google, 2026-10-03) — leitura Google continua allowlist do papel user.
_PAPEL_GATE_ACTIONS: frozenset[str] = frozenset({
    "ha_device_control",
    "google_drive_create", "google_drive_update", "google_drive_delete",
    "google_calendar_create", "google_calendar_delete",
    "google_gmail_send", "google_gmail_delete",
})

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

# Human-in-the-loop: ações que mudam estado FORA do sistema (escrita no Google)
# não executam no fast path — o turno pausa com `pending_human_input` e só roda
# depois do "sim" do dono (retomada pelo checkpoint). `OD_HUMAN_APPROVAL_ACTIONS`
# substitui a lista (separada por vírgula) ou desliga com off/0/false.
ACOES_SENSIVEIS_PADRAO: frozenset[str] = frozenset({
    "google_drive_create",
    "google_drive_update",
    "google_drive_delete",
    "google_calendar_create",
    "google_calendar_delete",
    "google_gmail_send",
    "google_gmail_delete",
    "ha_device_control",
})


def acoes_que_exigem_aprovacao() -> frozenset[str]:
    """Lista efetiva de ações sensíveis (padrão ou override do .env)."""
    bruto = os.getenv("OD_HUMAN_APPROVAL_ACTIONS")
    if bruto is None:
        return ACOES_SENSIVEIS_PADRAO
    bruto = bruto.strip()
    if not bruto or bruto.lower() in {"off", "0", "false", "nao", "não"}:
        return frozenset()
    return frozenset(p.strip() for p in bruto.split(",") if p.strip())


# Validade de um pedido de aprovação (human-in-the-loop), em MINUTOS.
# Passado o prazo, o "sim" atrasado NÃO executa nada: uma ação de horas atrás
# rodaria fora do contexto em que foi pedida (o dono já nem lembra do pedido).
# `OD_HUMAN_APPROVAL_TTL` aceita minutos (ex.: 15, 2.5); off/0 desliga a
# expiração. Pedidos antigos gravados SEM `criado_em` nunca expiram — evita
# quebrar checkpoints anteriores a esta regra.
HUMAN_APPROVAL_TTL_PADRAO_MIN = 30


def ttl_aprovacao_humana() -> float:
    """Validade efetiva da aprovação, em segundos (0.0 = sem expiração)."""
    bruto = os.getenv("OD_HUMAN_APPROVAL_TTL")
    if bruto is None:
        return HUMAN_APPROVAL_TTL_PADRAO_MIN * 60.0
    bruto = bruto.strip()
    if not bruto or bruto.lower() in {"off", "0", "false", "nao", "não"}:
        return 0.0
    try:
        minutos = float(bruto.replace(",", "."))
    except ValueError:
        return HUMAN_APPROVAL_TTL_PADRAO_MIN * 60.0
    return max(0.0, minutos) * 60.0


def pending_expirado(
    pendente: dict[str, Any], *, agora: Optional[float] = None
) -> str:
    """Mensagem de expiração se o pedido passou da validade; "" se ainda vale.

    Pedido sem `criado_em` (checkpoint gravado antes da expiração existir) é
    tratado como válido — não se inventa idade para dado antigo.
    """
    ttl = ttl_aprovacao_humana()
    if ttl <= 0:
        return ""
    criado = pendente.get("criado_em")
    if not isinstance(criado, (int, float)):
        return ""
    agora = time.time() if agora is None else agora
    if agora - float(criado) <= ttl:
        return ""
    minutos = max(1, int(round(ttl / 60)))
    return (
        "⏰ Aprovação expirada — nada foi executado. "
        f"O pedido valia {minutos} min e a resposta chegou depois disso; "
        "peça de novo se ainda quiser."
    )

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
    # Aviso honesto de indisponibilidade de recusa (2026-09-28) — o turno
    # seguinte tem que ir de novo ao modelo, nunca servir este aviso.
    "🤔 o modelo local não conseguiu responder",
)

# Recusa do modelo não é resposta cacheável (2026-09-28): o cache é
# servido ANTES da etapa 6.5 (anti-recusa), então uma recusa cacheada
# vira PERMANENTE — bug do ar: o gemma alucinou 'informação de
# infraestrutura é restrita ao dono' para uma pergunta de clima, a
# resposta entrou no cache e a pergunta seguinte recebia a alucinação
# instantaneamente, sem chance de retry. Frases fortes de recusa
# (a lista é conservadora: hedging tipo 'não posso garantir, mas...'
# continua cacheável).
_CACHE_BAN_REFUSALS = (
    r"restri(?:c)?t[oa]s?\s+ao\s+dono",
    r"n[aã]o posso fornecer",
    r"nao posso fornecer",
    r"n[aã]o posso informar",
    r"n[aã]o tenho acesso",
    r"sem acesso f[íi]sico",
    r"por raz[õo]es de seguran[çc]a",
    r"n[aã]o [ée] poss[íi]vel fornecer",
    # v1.15.0 (§15): 'llama.cpp' é open-source E do próprio dono — a
    # 'vedação de código proprietário' é alucinação de prompt interno.
    r"c[óo]digo propriet[áa]rio",
    r"n[aã]o posso compartilhar detalhes espec[íi]ficos",
)

# v1.15.0 (§15): etiqueta de log ESPIADA em QUALQUER posição da resposta
# (o ban por prefixo só pegava no início — a resposta de limpeza com
# '[INFO] Limpeza solicitada no dia…' NO MEIO entrou no cache).
_CACHE_ETIQUETA_EM_QUALQUER_POSICAO = re.compile(
    r"\[(?:nicky\])?(?:crit|warn|online|info)\]", re.IGNORECASE
)

# v1.15.0 (§15): frase SECA de execução do lar ('Acesse a luz do corredor!')
# também é ESTADO DE CONVERSA — o ban da v1.9.1 só pegava '💡 Confirmar:' e
# '✅ ' no início. Imperativo + alvo do lar = execução, nunca conhecimento.
_CACHE_BAN_LAR_SECOS = re.compile(
    r"^\s*(?:acesse?|acenda?|apague?|desligue?|ligue?)\s+", re.IGNORECASE
)

# v1.15.0 (§15): estado de página/resposta vazia ('Em construção...') — o
# modelo devolvendo o placeholder do sistema como se fosse conteúdo.
_CACHE_BAN_ESTADO_PAGINA = re.compile(
    r'^\s*["\u201c]?em constru[çc][aã]o', re.IGNORECASE
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
    # v1.15.0 (§15): etiqueta de log em QUALQUER posição — a resposta de
    # limpeza com '[INFO] …' NO MEIO entrou no cache pelo ban só-prefixo.
    if _CACHE_ETIQUETA_EM_QUALQUER_POSICAO.search(candidate):
        return "etiqueta de log no meio da resposta"
    # Recusa do modelo (alucinação de vedação ou desculpa): se entrar no
    # cache, é servida antes do anti-recusa e vira permanente.
    for frase in _CACHE_BAN_REFUSALS:
        if re.search(frase, lowered):
            return f"recusa do modelo: {frase}"
    # Truncamento no meio da frase (max_tokens estourou): incompleto.
    if candidate[-1] in ",;:-":
        return "truncada (pontuação final aberta)"
    # Controle do lar (v1.9.1): confirmação e execução são ESTADO DE
    # CONVERSA, não conhecimento — cacheadas, viravam incoerência
    # ('sim' servia a confirmação velha; 'luzes acesas' podia responder
    # 'Confirmar: ligar Luzes Acessas' — casos reais de 29/09).
    if candidate.startswith(("💡 Confirmar:", "✅ ")):
        return "confirmação/execução do lar (estado de conversa)"
    # v1.15.0 (§15): frase SECA de execução ('Acesse a luz do corredor!')
    # — mesmo estado de conversa, sem o emoji da confirmação.
    if _CACHE_BAN_LAR_SECOS.match(candidate):
        return "execução do lar em frase seca (estado de conversa)"
    # v1.15.0 (§15): placeholder do sistema como resposta ('Em construção…').
    if _CACHE_BAN_ESTADO_PAGINA.match(lowered):
        return "estado de página (Em construção) — não é conteúdo"
    return ""


# Anti-FALSO-SUCESSO (08/10, IDs 769-782): sem a palavra 'evento' na rota
# determinística, a frase caiu no LLM e a gemma (1) ECOU uma confirmação
# VELHA do histórico como se fosse nova e (2) respondeu 'Compromisso
# criado com sucesso' sem executar NADA (agenda vazia). O LLM NUNCA
# executa ação — quem confirma é a rota fastpath, com pendência gravada.
_FAKE_ACTION_RES = re.compile(
    r"confirmar:"                       # eco de confirmação (✍️/💡/texto)
    r"|\b(?:criad[oa]s?|marcad[oa]s?|agendad[oa]s?|adicionad[oa]s?"
    r"|inserid[oa]s?|executad[oa]s?|conclu[íi]d[oa]s?)"
    r"(?:\s+\w+){0,3}\s+com\s+sucesso"   # '… criado com sucesso'
    r"|\b✅[^.\n]{0,60}(?:criad|marcad|agendad|adicionad|inserid|executad)"
    r"|\b(?:marquei|agendei|criei|adicionei|coloquei|anotei|inseri|executei)\b"
    r"[^.?!]{0,80}\b(?:compromisso|evento|agenda|hor[áa]rio)",
    re.IGNORECASE,
)
FAKE_ACTION_MESSAGE = (
    "⚠️ Não executei nada — compromisso só é criado pela rota de ação: "
    "você vê a confirmação e responde 'sim'. Escreva, por exemplo: "
    "'criar compromisso reunião para as 15 horas' ou 'crie um evento "
    "para as 7:00' que eu extraio título e hora na hora."
)


def fake_action_reason(text: str) -> str:
    """Motivo de a resposta FINGIR execução de ação ('' = ok).

    Guarda das etapas 6.7 (stream e REST): a resposta do LLM é trocada
    por FAKE_ACTION_MESSAGE antes de ir para o usuário, do histórico e do
    cache — nunca um 'criado com sucesso' sem evento na agenda.
    """
    if not text:
        return ""
    m = _FAKE_ACTION_RES.search(text)
    return m.group(0)[:60] if m else ""

ROUTE_LLM = "llm"
ROUTE_FALLBACK = "fallback"
ROUTE_UNAVAILABLE = "llm_unavailable"
ROUTE_ERROR = "error"

# Texto da resposta de rate limit. É constante (e não literal solto em cada
# caminho) porque `process` e `process_stream` precisam registrar e publicar a
# MESMA mensagem para a mesma situação.
RATE_LIMITED_MESSAGE = "Muitas mensagens em pouco tempo. Aguarde um instante."

# Negação de infraestrutura para quem NÃO é o dono (v1.7.0): resposta
# determinística, sem passar pelo LLM — a pergunta nem chega ao modelo.
INFRA_DENIED_MESSAGE = (
    "🔒 Informação de infraestrutura (IP, portas, topologia de rede) é "
    "restrita ao dono do sistema."
)

# Credenciais/segredos (v1.8.0): negação determinística para TODOS os
# papéis — o LLM alucinou uma senha de MQTT no ar ('OmegaDrakon2026',
# falsa). O valor real de um segredo nunca vive no modelo; vive no
# .env/cofre — e nem o dono pede isso pelo chat.
SECRETS_DENIED_MESSAGE = (
    "🔐 Senhas e credenciais não são respondidas pelo chat — nem para o "
    "dono. O valor real vive no .env/cofre do servidor; para trocar ou "
    "consultar, acesse o servidor diretamente."
)

# Recusa persistente do modelo em ASSUNTO EXTERNO (2026-09-28): esgotados
# os retries (2 para assunto externo), quem pergunta recebe este aviso
# honesto — NUNCA a recusa falsa do modelo (que alega vedação de sistema
# que não existe para a pergunta). Não é cacheável (prefixo banido em
# _CACHE_BAN_PREFIXES) para a próxima tentativa ir de novo ao modelo.
EXTERNAL_UNAVAILABLE_MESSAGE = (
    "🤔 O modelo local não conseguiu responder agora. Tente perguntar de "
    "novo em instantes."
)

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
    # Orçamento de contexto por TOKENS (Parte B — NOMAD): janela do modelo
    # em tokens. 0 = desligado (histórico limitado só por turnos, como
    # sempre); > 0 = o ContextManager encaixa o histórico no que sobra da
    # janela depois de system + bloco RAG + resposta, e o descarte vira
    # métrica (contexto_descartados).
    orcamento_janela: int = 0
    orcamento_resposta: int = 512
    # Memória longa no prompt (F4 fase 2): injeta os fatos do próprio
    # usuário que casam com a mensagem, antes do LLM. Orçamento em fatos e
    # em caracteres para o bloco nunca competir com o histórico.
    memoria_no_prompt: bool = True
    memoria_max_fatos: int = 5
    memoria_max_chars: int = 600


@dataclass(slots=True)
class OrchestrationResult:
    """Resultado de uma mensagem processada pelo pipeline.

    Attributes:
        user_id:    Usuário da conversa.
        profile:    Perfil usado.
        text:       Mensagem original.
        route:      Etapa que produziu a resposta (rate_limited, datetime,
                    quick_response, cache, llm, fallback, llm_unavailable,
                    error, human_loop_pending).
        message:    Texto da resposta.
        llm_used:   Nome do provider que respondeu ("" se sem LLM).
        fallback_used: True quando um provider reserva respondeu.
        cached:     True quando veio do cache.
        prompt:     Prompt ChatML enviado ao LLM (rotas llm/fallback).
        latency_ms: Tempo total do pipeline.
        error:      Mensagem de erro (rota error/llm_unavailable).
        thread_id:  ID do thread do grafo (quando pausado no human_loop).
        pending_human_input: Dados da aprovação pendente (quando pausado).
        paused:     True quando o turno pausou aguardando decisão humana.
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
    thread_id: str = ""
    pending_human_input: Optional[dict[str, Any]] = None
    paused: bool = False
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
            "profile_name": _profile_display_name(self.profile),
            "text": self.text,
            "route": self.route,
            "ok": self.ok,
            "message": self.message,
            "llm_used": self.llm_used,
            "fallback_used": self.fallback_used,
            "cached": self.cached,
            "latency_ms": round(self.latency_ms, 3),
            "error": self.error,
            "thread_id": self.thread_id,
            "pending_human_input": self.pending_human_input,
            "paused": self.paused,
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
    infra_denied: int = 0  # v1.7.0: IP/portas negados a não-dono (Etapa 3.4)
    # Parte B (NOMAD): pipeline RAG — o descartado é métrica (floor,
    # visibilidade e orçamento), nunca silêncio.
    rag_consultas: int = 0
    rag_trechos: int = 0
    rag_descartados: int = 0
    rag_tokens_descartados: int = 0
    # Etapa 4.6 (Kiwix, 24/10): Wikipédia offline como fallback do RAG.
    enciclopedias: int = 0
    enciclopedia_blocos: int = 0
    enciclopedia_erros: int = 0
    # Etapa 4.6b (26/10): pergunta de fato sem artigo em NENHUMA fonte —
    # a nota honesta entrou no prompt em vez de o modelo local inventar.
    enciclopedia_sem_fonte: int = 0
    contexto_descartados: int = 0  # turnos de histórico fora do orçamento
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
            "rag_consultas": self.rag_consultas,
            "rag_trechos": self.rag_trechos,
            "rag_descartados": self.rag_descartados,
            "rag_tokens_descartados": self.rag_tokens_descartados,
            "enciclopedias": self.enciclopedias,
            "enciclopedia_blocos": self.enciclopedia_blocos,
            "enciclopedia_erros": self.enciclopedia_erros,
            "enciclopedia_sem_fonte": self.enciclopedia_sem_fonte,
            "contexto_descartados": self.contexto_descartados,
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
        cache:      LLMCache opcional (etapas 4 e 8) — chave exata.
        semantic_cache: SemanticCache opcional (etapas 4 e 8) — similaridade ≥ threshold.
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
        semantic_cache: Optional[SemanticCache] = None,
        quick: Optional[QuickResponses] = None,
        event_bus: Optional[EventBus] = None,
        config: Optional[OrchestratorConfig] = None,
        clock: Optional[Callable[[], float]] = None,
        action_registry: Optional[Any] = None,
        rag: Optional[Any] = None,
        enciclopedia: Optional[Any] = None,
    ) -> None:
        self._providers = list(providers or [])
        self.history = history
        self.cache = cache
        self.semantic_cache = semantic_cache
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
        self._rag = rag  # Parte B (NOMAD): pipeline de retrieval no prompt
        # Etapa 4.6 (parking lot §5, 24/10): Wikipédia offline via Kiwix,
        # consultada SÓ quando o RAG local não achou nada (memória interna
        # é a 1ª fonte). Lazia e inofensiva: erro = block "" (sem exceção).
        self._enciclopedia = enciclopedia
        # F1 fase 2: checkpointer do grafo, criado só na primeira mensagem
        # quando OD_ORCHESTRATOR_GRAPH=1 (abrir SQLite no boot é desperdício).
        self._graph_saver: Optional[Any] = None

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

    @property
    def rag(self) -> Optional[Any]:
        """Pipeline RAG (Parte B — NOMAD) — opcional; None = sem retrieval."""
        return self._rag

    def set_rag(self, pipeline: Optional[Any]) -> None:
        """Define (ou desliga, com None) o pipeline RAG do prompt."""
        self._rag = pipeline

    @property
    def enciclopedia(self) -> Optional[Any]:
        """Enciclopédia (Kiwix) — opcional; None = sem referência externa."""
        return self._enciclopedia

    def set_enciclopedia(self, enciclopedia: Optional[Any]) -> None:
        """Define (ou desliga, com None) a enciclopédia do prompt."""
        self._enciclopedia = enciclopedia

    @property
    def query_router(self) -> Any:
        """Query Router (I4) — classificador leve para rotear estratégia."""
        if not hasattr(self, "_query_router"):
            from core.query_router import get_query_router
            self._query_router = get_query_router()
        return self._query_router

    def add_action(self, name: str, handler: Callable) -> None:
        """Adiciona uma ação injetável pelo framework (não usa o registry)."""
        self._action_callables[name] = handler

    def add_provider(self, provider: LLMProvider) -> None:
        """Adiciona um provider ao final da lista (último = fallback)."""
        self._providers.append(provider)

    # -- Pipeline ------------------------------------------------------------

    async def _process_stream_grafo(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        session_id: str,
        role: str,
    ):
        """Streaming via grafo: rende updates por superstep + tokens do LLM."""
        from core.orchestrator_graph import (
            END,
            REDUTORES,
            START,
            OrchestratorState,
            StateGraph,
            criar_nos,
            rota_por_intencao,
        )
        import time

        started = time.perf_counter()

        # Função de classificação de intenção
        async def classificar(estado: dict[str, Any]) -> str:
            from core.intents import detect_action_intent
            intent = detect_action_intent(estado.get("text", ""))
            if intent is not None and intent[0] == "__secrets_denied__":
                return "secrets_denied"
            # Ação sensível não depende do acerto do classificador: vai para
            # select_tools, que pausa o turno (human_loop) — mesma regra do
            # grafo de `process`, senão o streaming executa sem aprovação.
            if intent is not None and self._exige_aprovacao_humana(intent[0]):
                return "tools"
            if (
                self._config.enable_action_intents
                and self._action_registry is not None
                and estado.get("role") != "anonymous"
            ):
                return "tools"
            return "chat"

        # Função de seleção de ferramentas
        async def selecionar(estado: dict[str, Any]) -> Any:
            from core.intents import detect_action_intent
            intent = detect_action_intent(estado.get("text", ""))
            if intent is not None and intent[0] != "__secrets_denied__":
                action_name, params = intent
                # Pedido incompleto segue para o generate (falta dado).
                if action_name == "ha_device_control" and not params.get(
                    "entity_id"
                ):
                    return []
                if action_name == "google_calendar_create" and not (
                    params.get("quando") or params.get("data")
                    or params.get("start")
                ):
                    return []
                if self._exige_aprovacao_humana(action_name):
                    # Streaming também pausa: o app recebe
                    # `human_loop_pending` e decide por frame `decision`.
                    return {
                        "intent": "tools",
                        "pending_human_input": self._pedido_de_aprovacao(
                            action_name, params, estado.get("text", "")
                        ),
                    }
                return [action_name]
            return []

        # Função de execução de ferramentas
        async def executar(ferramenta: str, estado: dict[str, Any]) -> Any:
            user_id = estado.get("user_id", "")
            role = estado.get("role", "admin")
            text = estado.get("text", "")
            from core.intents import detect_action_intent
            intent = detect_action_intent(text)
            if intent is not None and intent[0] == ferramenta:
                action_name, params = intent
                if action_name in ("ha_device_control", "google_calendar_create"):
                    params = dict(params)
                    params["user_id"] = user_id
                return await self.execute_action(action_name, params, user_id, role)
            return None

        # Função de geração de resposta (LLM) - retorna completo para o grafo
        # O streaming de tokens é feito fora do grafo
        async def gerar(estado: dict[str, Any]) -> dict[str, Any]:
            message, llm_used, fallback_used, prompt = await self._gerar_com_contexto(
                user_id=estado.get("user_id", ""),
                profile=estado.get("profile", ""),
                text=estado.get("text", ""),
                system_prompt=estado.get("system_prompt", ""),
                role=estado.get("role", "admin"),
                extra_history=estado.get("extra_history"),
            )
            if message is None:
                self._metrics.unavailable += 1
                return {
                    "terminal": True,
                    "route": ROUTE_UNAVAILABLE,
                    "message": self._config.unavailable_message,
                    "error": DEFAULT_UNAVAILABLE_ERROR,
                    "prompt": prompt,
                    "registrar": None,
                }
            if fallback_used:
                self._metrics.fallback += 1
            else:
                self._metrics.llm += 1
            return {
                "terminal": False,
                "route": ROUTE_FALLBACK if fallback_used else ROUTE_LLM,
                "message": message,
                "llm_used": llm_used,
                "fallback_used": fallback_used,
                "prompt": prompt,
            }

        # Nó de decisão humana
        async def humano(estado: dict[str, Any]) -> dict[str, Any]:
            if estado.get("pending_human_input"):
                return await self._aplicar_decisao_humana(estado)
            return {"steps": ["human_loop"]}

        # Cache terminal
        async def no_cache(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_cache(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                persist=estado.get("persist", True)
            )

        def rota(proximo: str):
            def _rota(estado: dict[str, Any]) -> str:
                return END if estado.get("terminal") else proximo
            return _rota

        # Constrói o grafo
        builder = StateGraph(OrchestratorState, reducers=REDUTORES)
        nos = criar_nos(
            classificar=classificar,
            selecionar=selecionar,
            executar=executar,
            gerar=gerar,
            humano=humano,
            max_paralelo=4,
        )
        for nome, fn in nos.items():
            builder.add_node(nome, fn)
        builder.add_node("cache_terminal", no_cache)

        # Nós terminais
        async def no_rate(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_rate_limit(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", "")
            )

        async def no_datetime(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_datetime(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                persist=estado.get("persist", True)
            )

        async def no_quick(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_quick(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                persist=estado.get("persist", True)
            )

        async def no_infra(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_infra(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                role=estado.get("role", "admin"), 
                persist=estado.get("persist", True)
            )

        for nome, fn in (
            ("rate_limit", no_rate),
            ("datetime", no_datetime),
            ("quick", no_quick),
            ("infra_guard", no_infra),
        ):
            builder.add_node(nome, fn)

        builder.add_edge(START, "rate_limit")
        builder.add_conditional_edges("rate_limit", rota("datetime"))
        builder.add_conditional_edges("datetime", rota("quick"))
        builder.add_conditional_edges("quick", rota("infra_guard"))
        builder.add_conditional_edges("infra_guard", rota("cache_terminal"))
        builder.add_conditional_edges("cache_terminal", rota("classify"))

        builder.add_conditional_edges(
            "classify",
            rota_por_intencao,
            {"select_tools": "select_tools", "generate": "generate", "secrets_denied": "generate"}
        )
        builder.add_edge("select_tools", "execute_parallel")
        builder.add_edge("execute_parallel", "generate")
        builder.add_edge("generate", "human_loop")
        builder.add_conditional_edges("human_loop", lambda _estado: END)

        # Post process
        async def no_post(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_post_processo(
                user_id=estado.get("user_id", ""),
                profile=estado.get("profile", ""),
                text=estado.get("text", ""),
                persist=estado.get("persist", True),
                estado=estado,
            )
        builder.add_node("post_process", no_post)
        builder.add_edge("generate", "post_process")
        builder.add_edge("post_process", "human_loop")

        saver = self._obter_graph_saver()
        grafo = builder.compile(checkpointer=saver)
        thread_id = self._thread_grafo(user_id, session_id, text, profile, role)
        salvo = saver.ultimo(thread_id)
        retomar = salvo is not None and not salvo.concluido

        if retomar:
            log.info(
                f"Grafo stream: retomando {thread_id} "
                f"(passo {salvo.passo}, próximos={salvo.proximos})"
            )

        entrada = None if retomar else {
            "user_id": user_id,
            "profile": profile,
            "session_id": session_id,
            "role": role,
            "text": text,
            "system_prompt": system_prompt,
            "persist": True,
            "extra_history": None,
            "messages": [{"role": "user", "content": text}],
        }

        # Executa o grafo com streaming de supersteps
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
        
        full_response = ""
        route = ROUTE_LLM
        llm_used = ""
        fallback_used = False
        prompt = ""

        async for update in grafo.astream(entrada, config, resume=retomar):
            # Rende progresso do superstep
            yield {
                "type": "progress",
                "step": update.get("passo", 0),
                "nodes": update.get("nos", []),
                "next": update.get("proximos", []),
            }

            estado = update.get("estado", {})
            
            # Se chegou ao generate e tem resposta completa, faz streaming de tokens
            if estado.get("message") and not full_response:
                full_response = estado["message"]
                route = estado.get("route", ROUTE_LLM)
                llm_used = estado.get("llm_used", "")
                fallback_used = estado.get("fallback_used", False)
                prompt = estado.get("prompt", "")
                
                # Rende tokens simulados (o LLM já gerou completo no nó)
                # Para streaming real, precisaríamos modificar o nó gerar
                yield {"type": "token", "content": full_response}

            # Verifica pausa humana
            if estado.get("pending_human_input") and not estado.get("human_decision"):
                yield {
                    "type": "human_loop_pending",
                    "thread_id": thread_id,
                    "pending_human_input": estado["pending_human_input"],
                }
                return

        # Finalização
        if full_response:
            # Anti-recusa e anti-falso-sucesso (igual ao processo direto)
            refusal = self._refusal_reason(full_response, role, text)
            if refusal:
                log.warn("Recusa indevida detectada — refazendo", reason=refusal)
                # Em streaming, não refazemos — logamos e seguimos
            
            fake = fake_action_reason(full_response)
            if fake:
                log.warn("Resposta do LLM fingia executar ação — substituída", reason=fake)
                full_response = FAKE_ACTION_MESSAGE

            if fallback_used:
                self._metrics.fallback += 1
            else:
                self._metrics.llm += 1

            await self._post_process(user_id, profile, text, full_response, llm_used)

            result = self._stream_result(
                user_id, profile, text, route, full_response,
                llm_used=llm_used, fallback_used=fallback_used, prompt=prompt,
            )
            await self._finish(result, started)

            yield {
                "type": "done",
                "profile_name": _profile_display_name(profile),
                "content": full_response,
                "route": route,
                "llm_used": llm_used,
                "fallback_used": fallback_used,
                "cached": False,
            }
        else:
            # Caminhos terminais (rate_limit, datetime, quick, infra, cache)
            # O estado final deve ter a resposta
            estado_final = estado
            if estado_final.get("terminal"):
                yield {
                    "type": "done",
                    "profile_name": _profile_display_name(profile),
                    "content": estado_final.get("message", ""),
                    "route": estado_final.get("route", ROUTE_ERROR),
                    "llm_used": estado_final.get("llm_used", ""),
                    "fallback_used": estado_final.get("fallback_used", False),
                    "cached": estado_final.get("cached", False),
                }

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
        
        Se OD_ORCHESTRATOR_GRAPH=1, usa o grafo com streaming de supersteps.
        """
        from core.orchestrator_graph import habilitado_por_env

        if habilitado_por_env():
            # Usa o grafo com streaming de supersteps
            async for chunk in self._process_stream_grafo(
                user_id=user_id,
                profile=profile,
                text=text,
                system_prompt=system_prompt,
                session_id=session_id,
                role=role,
            ):
                yield chunk
            return

        # Caminho direto (fallback ou grafo desligado) - lógica original
        if not system_prompt:
            system_prompt = self._config.default_system_prompt
        started = time.perf_counter()

        # Etapa 1 — Rate limit
        if not self._limiter.allow(user_id):
            self._metrics.rate_limited += 1
            result = self._stream_result(
                user_id, profile, text, ROUTE_RATE_LIMITED, RATE_LIMITED_MESSAGE
            )
            await self._finish(result, started)
            yield {"type": "error", "message": "rate_limited"}
            return

        # Etapa 2 — Datetime (resposta direta). O stream NÃO tem persist:
        # só é chamado com conta autenticada (REST/WS), então registra.
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
                    "profile_name": _profile_display_name(profile),
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
                    "profile_name": _profile_display_name(profile),
                    "content": quick_answer,
                    "route": ROUTE_QUICK,
                    "llm_used": "",
                }
                return

        # Etapa 3.4 — GUARDA de infraestrutura: perguntas de IP/portas/topologia
        # só o dono (admin) faz. Para user/anônimo é NEGAÇÃO determinística —
        # a pergunta NEM chega ao LLM (o gemma entregava o IP mesmo com a
        # vedação no prompt — v1.7.0, reportado pelo dono).
        if role != "admin":
            from core.intents import detect_infra_intent

            if detect_infra_intent(text):
                self._metrics.infra_denied += 1
                result = self._stream_result(
                    user_id,
                    profile,
                    text,
                    ROUTE_INTENT,
                    INFRA_DENIED_MESSAGE,
                    llm_used="",
                )
                await self._record_terminal(result, text, persist=True)
                await self._finish(result, started)
                yield {"type": "token", "content": INFRA_DENIED_MESSAGE}
                yield {
                    "type": "done",
                    "profile_name": _profile_display_name(profile),
                    "content": INFRA_DENIED_MESSAGE,
                    "route": ROUTE_INTENT,
                    "llm_used": "",
                }
                return

        # Etapa 3.5 — Fast path de intenções (mesma regra do `process`: papel
        # vem da credencial; "anonymous" não aciona action). v1.8.0: trava de
        # credenciais ANTES do gate de anonymous (mesma regra do `process`).
        from core.intents import (
            detect_action_intent,
            detect_confirmation,
            format_intent_result,
            safe_math,
        )

        intent = detect_action_intent(text)
        if intent is not None and intent[0] == "__secrets_denied__":
            # Papel importa (ordem do dono 22/10: "o master admin pode fazer
            # qualquer coisa" + "as senhas vem do cofre"): o DONO recebe o
            # valor REAL do cofre; os demais papéis seguem com a negação
            # honesta de sempre (confidencial = não passa).
            if role == "admin":
                segredo = await self._segredo_do_cofre(text, user_id, role)
                self._metrics.intents += 1
                result = self._stream_result(
                    user_id, profile, text, ROUTE_INTENT, segredo, llm_used="",
                )
                # persist=False: o VALOR não entra no histórico (nunca vira
                # prompt, cache nem relatório da auditoria).
                await self._record_terminal(result, text, persist=False)
                await self._finish(result, started)
                yield {"type": "token", "content": segredo}
                yield {
                    "type": "done",
                    "profile_name": _profile_display_name(profile),
                    "content": segredo,
                    "route": ROUTE_INTENT,
                    "llm_used": "",
                }
                return
            self._metrics.infra_denied += 1
            result = self._stream_result(
                user_id, profile, text, ROUTE_INTENT, SECRETS_DENIED_MESSAGE,
                llm_used="",
            )
            await self._record_terminal(result, text, persist=True)
            await self._finish(result, started)
            yield {"type": "token", "content": SECRETS_DENIED_MESSAGE}
            yield {
                "type": "done",
                "profile_name": _profile_display_name(profile),
                "content": SECRETS_DENIED_MESSAGE,
                "route": ROUTE_INTENT,
                "llm_used": "",
            }
            return
        if (
            self._config.enable_action_intents
            and self._action_registry is not None
            and role != "anonymous"
        ):
            answer = safe_math(text)
            route_detail = "math"
            if answer is None:
                # Confirmação de 2 passos do controle do lar (v1.8.1):
                # 'sim' não gera intenção — consulta a intenção pendente do
                # user e executa a MESMA luz/ação que ele pediu antes.
                # v1.9.1: COERÊNCIA obrigatória — o 'sim' que menciona outro
                # dispositivo NÃO executa o anterior: recusa genérica e
                # honesta, sem LLM, e a intenção velha é descartada.
                from tools.actions.actions import (
                    confirm_texts_match_pending,
                    drop_pending_google_write,
                    peek_pending_calendar_when,
                    peek_pending_google_write,
                    peek_pending_light_confirmation,
                )
                from core.intents import GOOGLE_WRITE_ACTIONS

                pending = peek_pending_light_confirmation(user_id)
                pending_gw = (
                    peek_pending_google_write(user_id) if pending is None else None
                )
                if pending is not None and detect_confirmation(text):
                    entity_id, on, alvo = pending
                    if not confirm_texts_match_pending(text, alvo, entity_id):
                        from tools.actions.actions import (
                            drop_pending_light_confirmation,
                        )

                        drop_pending_light_confirmation(user_id)
                        answer = (
                            "🤔 Essa confirmação não bate com o que você "
                            "pediu antes (que já expirou). Diga de novo o "
                            "que quer — por exemplo: 'liga a luz da sala'."
                        )
                        done_result = self._stream_result(
                            user_id, profile, text, ROUTE_INTENT, answer,
                            llm_used="fastpath:ha_device_control",
                        )
                        await self._record_terminal(done_result, text, persist=True)
                        await self._finish(done_result, started)
                        yield {"type": "token", "content": answer}
                        yield {
                            "type": "done",
                            "profile_name": _profile_display_name(profile),
                            "content": answer,
                            "route": ROUTE_INTENT,
                            "llm_used": "fastpath:ha_device_control",
                        }
                        return
                    data = await self.execute_action(
                        "ha_device_control",
                        {"entity_id": entity_id, "on": on,
                         "user_id": user_id},
                        user_id,
                        role=role,
                    )
                    answer = format_intent_result("ha_device_control", data)
                    # O default do ramo é "math" (linha de safe_math); sem
                    # reatribuir aqui a execução real da luz era registrada
                    # como fastpath:math — telemetria mentindo sobre a rota
                    # (achado em 08/10 na auditoria das conversas; o caminho
                    # NÃO-streaming abaixo já atribuía certo).
                    route_detail = "ha_device_control"
                elif pending_gw is not None and detect_confirmation(text):
                    # Escrita Google (lote 2): o 'sim' do MESMO user executa a
                    # intenção pendente — mesmo espelho das luzes.
                    gw_action, gw_params, gw_alvo = pending_gw
                    if not confirm_texts_match_pending(text, gw_alvo, ""):
                        drop_pending_google_write(user_id)
                        answer = (
                            "🤔 Essa confirmação não bate com o que você "
                            "pediu antes (a intenção expirou). Diga de novo "
                            "o que quer."
                        )
                        route_detail = gw_action
                    else:
                        gw_exec = dict(gw_params)
                        gw_exec["user_id"] = user_id
                        gw_exec["alvo"] = gw_alvo
                        data = await self.execute_action(
                            gw_action, gw_exec, user_id, role=role
                        )
                        answer = format_intent_result(gw_action, data)
                        route_detail = gw_action
                # 'sim'/'s' sem NADA pendente → resposta honesta, SEM LLM
                # (08/10, IDs 771-782: a gemma ecoou uma confirmação VELHA
                # do histórico, não gravou pendência nenhuma e respondeu
                # 'Compromisso criado com sucesso' sem executar — mentira
                # no chat do dono; a agenda seguia vazia).
                if answer is None and detect_confirmation(text):
                    answer = (
                        "🤔 Não tenho nada pendente pra confirmar — ou o "
                        "pedido anterior não existia, ou a confirmação "
                        "expirou (2 minutos). Diga de novo o que quer, por "
                        "exemplo: 'criar compromisso reunião para as 15 horas'."
                    )
                    route_detail = "confirmacao_sem_pendencia"
            if answer is None:
                intent = detect_action_intent(text)
                if intent is not None:
                    action_name, params = intent
                    if action_name == "ha_device_control" or action_name in GOOGLE_WRITE_ACTIONS:
                        params = dict(params)
                        params["user_id"] = user_id
                    data = await self.execute_action(
                        action_name, params, user_id, role=role
                    )
                    answer = format_intent_result(action_name, data)
                    if answer is None:
                        # Casa de Limitações (v1.13.0): a action degradou
                        # (sem rede, fonte indisponível) — registro honesto
                        # do que o sistema NÃO conseguiu entregar agora.
                        try:
                            from core.limitacoes import registrar_action_degradada
                            registrar_action_degradada(action_name, text)
                        except Exception:
                            pass
                    route_detail = action_name
                else:
                    # Create aguardando 'quando': a frase 'hoje'/'amanhã às
                    # 15h' completa a MESMA intenção no fastpath (sem LLM).
                    # Sem este ramo a frase caía no LLM, que alucinava
                    # 'Marquei o compromisso…' sem chamar a API (prova real
                    # de 08/10, chat ID 700 — 'Testar Agenda' nunca existiu).
                    when_params = peek_pending_calendar_when(user_id, text)
                    if when_params is not None:
                        when_params = dict(when_params)
                        when_params["user_id"] = user_id
                        data = await self.execute_action(
                            "google_calendar_create", when_params,
                            user_id, role=role,
                        )
                        answer = format_intent_result(
                            "google_calendar_create", data
                        )
                        route_detail = "google_calendar_create"
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
                    "profile_name": _profile_display_name(profile),
                    "content": answer,
                    "route": ROUTE_INTENT,
                    "llm_used": f"fastpath:{route_detail}",
                }
                return

        # Etapa 4 — Cache LLM (exato + semântico)
        # Ordem: 1) LLMCache exato, 2) SemanticCache (similaridade ≥ threshold)
        cached = None
        cache_route = ROUTE_CACHE
        if self.cache is not None:
            cached = self.cache.get(text, profile=profile)
            cache_route = ROUTE_CACHE
        if cached is None and self.semantic_cache is not None:
            cached = self.semantic_cache.get(text, profile=profile)
            cache_route = "semantic_cache"
        if cached is not None:
            self._metrics.cache_hits += 1
            result = self._stream_result(
                user_id, profile, text, cache_route, cached, cached=True
            )
            await self._record_terminal(result, text, persist=True)
            await self._finish(result, started)
            yield {"type": "token", "content": cached}
            yield {
                "type": "done",
                "profile_name": _profile_display_name(profile),
                "content": cached,
                "route": cache_route,
                "llm_used": "",
                "cached": True,
            }
            return

        # Etapa 4.5 — RAG (Parte B NOMAD): mesmo caminho do REST (reescrita
        # com histórico, floor duplo, reranker, orçamento) — os dois
        # transportes enxergam o MESMO contexto, senão o app e o chat
        # responderiam com bagagens diferentes.
        contexto = self._contexto_msgs(user_id, profile, None)
        system_efetivo = self._resolve_system(system_prompt, profile, role)
        # Etapas 4.5 (RAG) + 4.6 (enciclopédia) + 4.6b (nota de fonte):
        # UMA fonte por prompt — duas fontes de verdade brigando no mesmo
        # prompt é receita para alucinação. Em pergunta de FATO a ordem é
        # a nova (régua do dono, 26/10): fonte verificada primeiro.
        rag_block = self._bloco_de_referencia(
            text, contexto, role, system_efetivo
        )

        # Etapa 5 — Histórico: monta contexto ChatML
        prompt = self._build_prompt(
            user_id, profile, text, system_efetivo,
            contexto=contexto, rag_block=rag_block,
        )

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

        # Etapa 6.5 — Anti-recusa do dono: o gemma às vezes recusa dados
        # operacionais ignorando o system prompt. Para o ADMIN, refaz UMA vez
        # com reforço; persistindo, o chat cai para a action real (etapa 6.6).
        refusal = self._refusal_reason(full_response, role, text)
        if refusal:
            log.warn(
                "Recusa indevida detectada — refazendo",
                reason=refusal,
                role=role,
            )
            retry = await self._resolve_refusal(prompt, role, text)
            if retry is not None:
                full_response, llm_used = retry[0], retry[1]
                fallback_used = True
                route = ROUTE_FALLBACK
                yield {"type": "token", "content": full_response}

        # Etapa 6.7 — Anti-FALSO-SUCESSO (08/10, IDs 769-782): a gemma
        # emitiu '✍️ Confirmar: …' e 'Compromisso criado com sucesso' sem
        # executar nada (a agenda seguia vazia). Trocado ANTES do cache e
        # do histórico: nunca um sucesso inventado no chat do dono.
        fake = fake_action_reason(full_response)
        if fake:
            log.warn(
                "Resposta do LLM fingia executar ação — substituída",
                reason=fake,
                route=route,
            )
            full_response = FAKE_ACTION_MESSAGE

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
            "profile_name": _profile_display_name(profile),
            "content": full_response,
            "route": route,
            "llm_used": llm_used,
            "latency_ms": result.latency_ms,
        }

    async def process_stream_sse(
        self,
        user_id: str,
        profile: str,
        text: str,
        *,
        system_prompt: str = "",
        session_id: str = "",
        role: str = "admin",
    ):
        """Wrapper SSE para `process_stream` — rende eventos `text/event-stream`.

        Formato:
            event: progress
            data: {"step": 3, "nodes": [...], "next": [...]}

            event: token
            data: {"content": "..."}

            event: done
            data: {"route": "...", "content": "...", "llm_used": "...", "cached": false}

            event: human_loop_pending
            data: {"thread_id": "...", "pending_human_input": {...}}

            event: error
            data: {"message": "..."}
        """
        import json
        
        async for chunk in self.process_stream(
            user_id=user_id,
            profile=profile,
            text=text,
            system_prompt=system_prompt,
            session_id=session_id,
            role=role,
        ):
            chunk_type = chunk.get("type", "")
            
            if chunk_type == "progress":
                yield f"event: progress\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif chunk_type == "token":
                yield f"event: token\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif chunk_type == "done":
                yield f"event: done\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif chunk_type == "human_loop_pending":
                yield f"event: human_loop_pending\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif chunk_type == "error":
                yield f"event: error\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            else:
                # Fallback para chunks desconhecidos
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

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

        # Pipeline completo: etapas 1–4 e 8 como nós terminais/condicionais
        # quando OD_ORCHESTRATOR_GRAPH=1; sem a flag, o mesmo encadeamento é
        # executado direto (fallback também cai aqui).
        estado = await self._executar_pipeline(
            user_id=user_id,
            profile=profile,
            text=text,
            system_prompt=system_prompt,
            session_id=session_id,
            role=role,
            persist=persist,
            extra_history=extra_history,
        )

        # Se o grafo pausou aguardando decisão humana, retorna estado especial
        # para que o chamador (ex: Telegram bot) possa aguardar a resposta do usuário.
        if estado.get("pausado_human_loop"):
            result.route = "human_loop_pending"
            result.message = ""  # não há resposta ainda
            result.prompt = ""
            result.thread_id = estado.get("thread_id")
            result.pending_human_input = estado.get("pending_human_input")
            result.paused = True
            # Não chama _finalizar_estado completo — o turno não terminou.
            result.finished_at = time.time()
            result.latency_ms = (result.finished_at - started) * 1000
            return result

        return await self._finalizar_estado(result, estado, text, persist, started)

    @staticmethod
    def _estado_terminal(
        result: OrchestrationResult,
        *,
        registrar: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Snapshot de uma rota terminal — o que o grafo e o direto devolvem."""
        return {
            "terminal": True,
            "route": result.route,
            "message": result.message,
            "llm_used": result.llm_used,
            "cached": result.cached,
            "fallback_used": result.fallback_used,
            "prompt": result.prompt,
            "error": result.error,
            "registrar": registrar,
        }

    async def _etapa_rate_limit(self, *, user_id: str, profile: str, text: str) -> dict[str, Any]:
        """Etapa 1: janela deslizante. Vazio = segue o pipeline."""
        result = OrchestrationResult(user_id=user_id, profile=profile, text=text)

        # Etapa 1 — Rate limit (janela deslizante por usuário)
        if not self._limiter.allow(user_id):
            result.route = ROUTE_RATE_LIMITED
            result.message = RATE_LIMITED_MESSAGE
            self._metrics.rate_limited += 1
            return self._estado_terminal(result, registrar=None)

        return {}

    async def _etapa_datetime(self, *, user_id: str, profile: str, text: str, persist: bool) -> dict[str, Any]:
        """Etapa 2: data/hora em PT-BR, sem LLM."""
        result = OrchestrationResult(user_id=user_id, profile=profile, text=text)

        # Etapa 2 — Datetime (resposta direta PT-BR, sem LLM)
        if self._config.inject_datetime:
            answer = detect_datetime_question(text)
            if answer is not None:
                result.route = ROUTE_DATETIME
                result.message = answer
                self._metrics.datetime += 1
                return self._estado_terminal(result, registrar=persist)

        return {}

    async def _etapa_quick(self, *, user_id: str, profile: str, text: str, persist: bool) -> dict[str, Any]:
        """Etapa 3: respostas rápidas do AIML legado."""
        result = OrchestrationResult(user_id=user_id, profile=profile, text=text)

        # Etapa 3 — Quick responses (AIML legado)
        if self.quick is not None:
            quick_answer = self.quick.get(text.strip().lower())
            if quick_answer is not None:
                result.route = ROUTE_QUICK
                result.message = quick_answer
                self._metrics.quick += 1
                return self._estado_terminal(result, registrar=persist)

        return {}

    async def _etapa_infra(self, *, user_id: str, profile: str, text: str, role: str, persist: bool) -> dict[str, Any]:
        """Etapa 3.4: negação determinística de infraestrutura para não-admin."""
        result = OrchestrationResult(user_id=user_id, profile=profile, text=text)

        # Etapa 3.4 — GUARDA de infraestrutura: IP/portas/topologia são do
        # dono. Para user/anônimo é NEGAÇÃO determinística, sem LLM (o gemma
        # entregava o IP mesmo com a vedação no prompt — v1.7.0).
        if role != "admin":
            from core.intents import detect_infra_intent

            if detect_infra_intent(text):
                self._metrics.infra_denied += 1
                result.route = ROUTE_INTENT
                result.message = INFRA_DENIED_MESSAGE
                return self._estado_terminal(result, registrar=persist)

        return {}

    async def _etapa_intents(self, *, user_id: str, profile: str, text: str, role: str, persist: bool) -> dict[str, Any]:
        """Etapa 3.5: fast path de intenções/actions sem LLM."""
        result = OrchestrationResult(user_id=user_id, profile=profile, text=text)

        # Etapa 3.5 — Fast path de intenções (v0.27.5): respostas
        # operacionais sem LLM (matemática básica + actions de leitura),
        # só quando o ActionRegistry está conectado. Quem conversa sem conta
        # (papel "anonymous") não aciona action nenhuma: a matemática continua,
        # mas a intenção operacional cai para o LLM.
        # v1.8.0: a intenção __secrets_denied__ é avaliada ANTES do gate de
        # anonymous — credencial/segredo é negação determinística para
        # TODOS (o LLM alucinou uma senha de MQTT no ar; para o papel user
        # a negação é de direito; para o dono, o valor real não vive no
        # modelo — viver no .env/cofre).
        from core.intents import (
            detect_action_intent,
            detect_confirmation,
            format_intent_result,
            safe_math,
        )

        intent = detect_action_intent(text)
        if intent is not None and intent[0] == "__secrets_denied__":
            # DONO (ordem 22/10): valor REAL do cofre, nunca LLM — e o
            # resultado é terminal SEM persistência (o valor não entra no
            # histórico). Demais papéis: negação honesta de sempre.
            if role == "admin":
                self._metrics.intents += 1
                result.route = ROUTE_INTENT
                result.message = await self._segredo_do_cofre(
                    text, user_id, role
                )
                return self._estado_terminal(result, registrar=False)
            self._metrics.infra_denied += 1
            result.route = ROUTE_INTENT
            result.message = SECRETS_DENIED_MESSAGE
            return self._estado_terminal(result, registrar=persist)
        if (
            self._config.enable_action_intents
            and self._action_registry is not None
            and role != "anonymous"
        ):
            answer: Optional[str] = safe_math(text)
            route_detail = "math"
            if answer is None:
                # Confirmação de 2 passos do controle do lar (v1.8.1):
                # 'sim' não gera intenção — consulta a intenção pendente do
                # user e executa a MESMA luz/ação que ele pediu antes.
                # v1.9.1: COERÊNCIA obrigatória — o 'sim' que menciona outro
                # dispositivo NÃO executa o anterior: recusa genérica e
                # honesta, sem LLM, e a intenção velha é descartada.
                from tools.actions.actions import (
                    confirm_texts_match_pending,
                    drop_pending_google_write,
                    peek_pending_calendar_when,
                    peek_pending_google_write,
                    peek_pending_light_confirmation,
                )
                from core.intents import GOOGLE_WRITE_ACTIONS

                pending = peek_pending_light_confirmation(user_id)
                pending_gw = (
                    peek_pending_google_write(user_id) if pending is None else None
                )
                if pending is not None and detect_confirmation(text):
                    entity_id, on, alvo = pending
                    if not confirm_texts_match_pending(text, alvo, entity_id):
                        from tools.actions.actions import (
                            drop_pending_light_confirmation,
                        )

                        drop_pending_light_confirmation(user_id)
                        answer = (
                            "🤔 Essa confirmação não bate com o que você "
                            "pediu antes (que já expirou). Diga de novo o "
                            "que quer — por exemplo: 'liga a luz da sala'."
                        )
                        route_detail = "ha_device_control"
                    else:
                        data = await self.execute_action(
                            "ha_device_control",
                            {"entity_id": entity_id, "on": on,
                             "user_id": user_id},
                            user_id,
                            role=role,
                        )
                        answer = format_intent_result(
                            "ha_device_control", data,
                        )
                        route_detail = "ha_device_control"
                elif pending_gw is not None and detect_confirmation(text):
                    # Escrita Google (lote 2): o 'sim' do MESMO user executa a
                    # intenção pendente — mesmo espelho das luzes.
                    gw_action, gw_params, gw_alvo = pending_gw
                    if not confirm_texts_match_pending(text, gw_alvo, ""):
                        drop_pending_google_write(user_id)
                        answer = (
                            "🤔 Essa confirmação não bate com o que você "
                            "pediu antes (a intenção expirou). Diga de novo "
                            "o que quer."
                        )
                    else:
                        gw_exec = dict(gw_params)
                        gw_exec["user_id"] = user_id
                        gw_exec["alvo"] = gw_alvo
                        data = await self.execute_action(
                            gw_action, gw_exec, user_id, role=role
                        )
                        answer = format_intent_result(gw_action, data)
                    route_detail = gw_action
                # Espelho do stream: 'sim' sem NADA pendente → honesto,
                # sem LLM (a gemma mentia 'criado com sucesso' — IDs 771-782).
                if answer is None and detect_confirmation(text):
                    answer = (
                        "🤔 Não tenho nada pendente pra confirmar — ou o "
                        "pedido anterior não existia, ou a confirmação "
                        "expirou (2 minutos). Diga de novo o que quer, por "
                        "exemplo: 'criar compromisso reunião para as 15 horas'."
                    )
                    route_detail = "confirmacao_sem_pendencia"
            if answer is None:
                intent = detect_action_intent(text)
                if intent is not None:
                    action_name, params = intent
                    if action_name == "ha_device_control" or action_name in GOOGLE_WRITE_ACTIONS:
                        params = dict(params)
                        params["user_id"] = user_id
                    data = await self.execute_action(
                        action_name, params, user_id, role=role
                    )
                    answer = format_intent_result(action_name, data)
                    if answer is None:
                        # Casa de Limitações (v1.13.0) — igual ao stream.
                        try:
                            from core.limitacoes import registrar_action_degradada
                            registrar_action_degradada(action_name, text)
                        except Exception:
                            pass
                    route_detail = action_name
                else:
                    # Espelho do stream: create aguardando 'quando' — a
                    # frase 'hoje'/'amanhã às 15h' completa a MESMA intenção
                    # no fastpath, sem ir ao LLM alucinar a criação.
                    when_params = peek_pending_calendar_when(user_id, text)
                    if when_params is not None:
                        when_params = dict(when_params)
                        when_params["user_id"] = user_id
                        data = await self.execute_action(
                            "google_calendar_create", when_params,
                            user_id, role=role,
                        )
                        answer = format_intent_result(
                            "google_calendar_create", data
                        )
                        route_detail = "google_calendar_create"
            if answer is not None:
                result.route = ROUTE_INTENT
                result.message = answer
                result.llm_used = f"fastpath:{route_detail}"
                self._metrics.intents += 1
                return self._estado_terminal(result, registrar=persist)

        return {}

    async def _etapa_cache(self, *, user_id: str, profile: str, text: str, persist: bool) -> dict[str, Any]:
        """Etapa 4: cache LLM (nunca para conversa anônima)."""
        result = OrchestrationResult(user_id=user_id, profile=profile, text=text)

        # Etapa 4 — Cache LLM (SHA-256, prompt normalizado + perfil).
        # `persist=False` (conversa anônima) NÃO usa o cache: ele vive no
        # banco e serviria resposta de outra conversa.
        cached = None
        cache_route = ROUTE_CACHE
        if self.cache is not None and persist:
            cached = self.cache.get(text, profile=profile)
            cache_route = ROUTE_CACHE
        if cached is None and self.semantic_cache is not None and persist:
            cached = self.semantic_cache.get(text, profile=profile)
            cache_route = "semantic_cache"
        if cached is not None:
            result.route = cache_route
            result.message = cached
            result.cached = True
            self._metrics.cache_hits += 1
            return self._estado_terminal(result, registrar=persist)

        return {}

    async def _etapa_llm(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        role: str,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Etapas 4.5–6.7: contexto, RAG, prompt, LLM e guardas."""
        message, llm_used, fallback_used, prompt = await self._gerar_com_contexto(
            user_id=user_id,
            profile=profile,
            text=text,
            system_prompt=system_prompt,
            role=role,
            extra_history=extra_history,
        )
        if message is None:
            self._metrics.unavailable += 1
            return {
                "terminal": True,
                "route": ROUTE_UNAVAILABLE,
                "message": self._config.unavailable_message,
                "error": DEFAULT_UNAVAILABLE_ERROR,
                "prompt": prompt,
                "registrar": None,
            }
        if fallback_used:
            self._metrics.fallback += 1
        else:
            self._metrics.llm += 1
        return {
            # Não é terminal: ainda passa pelo nó de pós-processamento.
            "terminal": False,
            "route": ROUTE_FALLBACK if fallback_used else ROUTE_LLM,
            "message": message,
            "llm_used": llm_used,
            "fallback_used": fallback_used,
            "prompt": prompt,
        }

    async def _etapa_post_processo(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        persist: bool,
        estado: dict[str, Any],
    ) -> dict[str, Any]:
        """Etapa 8: cache + histórico, só para resposta de LLM bem-sucedida."""
        if persist and estado.get("route") in (ROUTE_LLM, ROUTE_FALLBACK):
            await self._post_process(
                user_id,
                profile,
                text,
                str(estado.get("message") or ""),
                str(estado.get("llm_used") or ""),
            )
        return {"pos_processado": True}

    async def _executar_direto(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        session_id: str,
        role: str,
        persist: bool,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Encadeamento linear (fallback e flag desligada), etapa por etapa."""
        # Fábricas, não corrotinas: etapa terminal não deve deixar as
        # seguintes criadas sem await (RuntimeWarning de coroutine órfã).
        etapas = (
            lambda: self._etapa_rate_limit(
                user_id=user_id, profile=profile, text=text
            ),
            lambda: self._etapa_datetime(
                user_id=user_id, profile=profile, text=text, persist=persist
            ),
            lambda: self._etapa_quick(
                user_id=user_id, profile=profile, text=text, persist=persist
            ),
            lambda: self._etapa_infra(
                user_id=user_id, profile=profile, text=text, role=role, persist=persist
            ),
            lambda: self._etapa_intents(
                user_id=user_id, profile=profile, text=text, role=role, persist=persist
            ),
            lambda: self._etapa_cache(
                user_id=user_id, profile=profile, text=text, persist=persist
            ),
        )
        for etapa in etapas:
            estado = await etapa()
            if estado:
                return estado

        estado = await self._etapa_llm(
            user_id=user_id,
            profile=profile,
            text=text,
            system_prompt=system_prompt,
            role=role,
            extra_history=extra_history,
        )
        if estado.get("terminal"):
            return estado
        await self._etapa_post_processo(
            user_id=user_id,
            profile=profile,
            text=text,
            persist=persist,
            estado=estado,
        )
        return estado

    async def _executar_grafo(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        session_id: str,
        role: str,
        persist: bool,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Pipeline inteiro como grafo: terminais viram END, LLM segue p/ etapa 8."""
        from core.orchestrator_graph import (
            END,
            REDUTORES,
            START,
            OrchestratorState,
            StateGraph,
            criar_nos,
            rota_por_intencao,
        )

        # Função de classificação de intenção (usa Query Router I4)
        async def classificar(estado: dict[str, Any]) -> str:
            text = estado.get("text", "")
            role = estado.get("role", "admin")
            profile = estado.get("profile", "")
            recent_history = estado.get("extra_history")
            
            # Secrets denied check (mantém comportamento existente)
            from core.intents import detect_action_intent
            intent = detect_action_intent(text)
            if intent is not None and intent[0] == "__secrets_denied__":
                estado["intent"] = "secrets_denied"
                estado["router_strategy"] = "secrets_denied"
                return "secrets_denied"

            # Ação sensível NÃO pode depender do acerto do classificador: o
            # pedido vai para select_tools, que pausa o turno (human_loop).
            if intent is not None and self._exige_aprovacao_humana(intent[0]):
                estado["intent"] = "tools"
                estado["router_strategy"] = "tool"
                return "tool"
            
            # Query Router para classificação rica
            try:
                from core.query_router import (
                    STRATEGY_DIRECT,
                    STRATEGY_TOOL,
                    STRATEGY_RAG,
                    STRATEGY_HYBRID,
                    STRATEGY_LLM_ONLY,
                )
                strategy = self.query_router.classify(
                    text, profile=profile, role=role,
                    recent_history=recent_history[-3:] if recent_history else None,
                )
                
                # Armazena estratégia completa no estado para o nó gerar
                estado["router_strategy"] = strategy
                
                # Mapeia para intent usado pelo rota_por_intencao
                if strategy == STRATEGY_TOOL:
                    estado["intent"] = "tools"
                elif strategy == STRATEGY_DIRECT:
                    estado["intent"] = "direct"
                else:
                    estado["intent"] = "chat"  # rag, hybrid, llm_only -> chat (gera LLM)
                
                return strategy  # Retorna estratégia completa para debug/log
            except Exception as exc:
                log.warn("Query Router falhou no grafo, usando classificação padrão", error=str(exc))
                # Fallback para lógica original
                if (
                    self._config.enable_action_intents
                    and self._action_registry is not None
                    and role != "anonymous"
                ):
                    estado["intent"] = "tools"
                else:
                    estado["intent"] = "chat"
                return "chat"

        # Função de seleção de ferramentas
        async def selecionar(estado: dict[str, Any]) -> Any:
            from core.intents import detect_action_intent, safe_math
            intent = detect_action_intent(estado.get("text", ""))
            if intent is not None and intent[0] != "__secrets_denied__":
                action_name, params = intent
                # Fluxo próprio de completar o pedido: sem alvo/quando não há
                # o que aprovar — o generate pede o dado que falta.
                if action_name == "ha_device_control" and not params.get(
                    "entity_id"
                ):
                    return []
                if action_name == "google_calendar_create" and not (
                    params.get("quando") or params.get("data")
                    or params.get("start")
                ):
                    return []
                if self._exige_aprovacao_humana(action_name):
                    # ORIGEM do human_loop: não executa ação sensível sem o
                    # "sim" do dono; o motor pausa e grava o checkpoint.
                    return {
                        "intent": "tools",
                        "pending_human_input": self._pedido_de_aprovacao(
                            action_name, params, estado.get("text", "")
                        ),
                    }
                return [action_name]
            # Matemática básica não precisa de ferramenta no grafo
            return []

        # Função de execução de ferramentas (usa execute_action do orchestrator)
        async def executar(ferramenta: str, estado: dict[str, Any]) -> Any:
            user_id = estado.get("user_id", "")
            role = estado.get("role", "admin")
            text = estado.get("text", "")
            
            # Extrai parâmetros da intenção detectada
            from core.intents import detect_action_intent
            intent = detect_action_intent(text)
            if intent is not None and intent[0] == ferramenta:
                action_name, params = intent
                if action_name in ("ha_device_control", "google_calendar_create"):
                    # Para actions que precisam de user_id
                    params = dict(params)
                    params["user_id"] = user_id
                return await self.execute_action(action_name, params, user_id, role)
            return None

        # Função de geração de resposta (LLM)
        async def gerar(estado: dict[str, Any]) -> dict[str, Any]:
            router_strategy = estado.get("router_strategy", "chat")
            
            # Ajusta comportamento baseado na estratégia do Query Router
            # Salva config original de RAG
            original_rag = self._rag
            original_enciclopedia = self._enciclopedia
            
            try:
                if router_strategy == "llm_only":
                    # LLM direto sem RAG nem enciclopédia
                    self._rag = None
                    self._enciclopedia = None
                elif router_strategy == "direct":
                    # Direct: sem LLM (já deveria ter sido capturado antes)
                    # Mas se chegou aqui, usa LLM sem RAG
                    self._rag = None
                    self._enciclopedia = None
                elif router_strategy == "hybrid":
                    # Hybrid: usa HybridRetriever se disponível via _rag
                    # O _rag deve ser um HybridRetriever
                    pass  # Mantém _rag como está (pode ser HybridRetriever)
                # rag e chat usam RAG normal
                
                message, llm_used, fallback_used, prompt = await self._gerar_com_contexto(
                    user_id=estado.get("user_id", ""),
                    profile=estado.get("profile", ""),
                    text=estado.get("text", ""),
                    system_prompt=estado.get("system_prompt", ""),
                    role=estado.get("role", "admin"),
                    extra_history=estado.get("extra_history"),
                )
            finally:
                # Restaura config original
                self._rag = original_rag
                self._enciclopedia = original_enciclopedia
            
            if message is None:
                self._metrics.unavailable += 1
                return {
                    "terminal": True,
                    "route": ROUTE_UNAVAILABLE,
                    "message": self._config.unavailable_message,
                    "error": DEFAULT_UNAVAILABLE_ERROR,
                    "prompt": prompt,
                    "registrar": None,
                }
            if fallback_used:
                self._metrics.fallback += 1
            else:
                self._metrics.llm += 1
            return {
                "terminal": False,
                "route": ROUTE_FALLBACK if fallback_used else ROUTE_LLM,
                "message": message,
                "llm_used": llm_used,
                "fallback_used": fallback_used,
                "prompt": prompt,
            }

        # Nó de decisão humana (para aprovações)
        async def humano(estado: dict[str, Any]) -> dict[str, Any]:
            if estado.get("pending_human_input"):
                return await self._aplicar_decisao_humana(estado)
            # A pausa em si é tratada no motor do grafo.
            return {"steps": ["human_loop"]}

        # Cache terminal (verifica cache LLM antes de ir para o LLM)
        async def no_cache(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_cache(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                persist=estado.get("persist", True)
            )

        def rota(proximo: str):
            def _rota(estado: dict[str, Any]) -> str:
                return END if estado.get("terminal") else proximo
            return _rota

        # Constrói o grafo completo com 10 nós
        builder = StateGraph(OrchestratorState, reducers=REDUTORES)
        nos = criar_nos(
            classificar=classificar,
            selecionar=selecionar,
            executar=executar,
            gerar=gerar,
            humano=humano,
            max_paralelo=4,
        )
        for nome, fn in nos.items():
            builder.add_node(nome, fn)
        
        # Adiciona o nó de cache terminal
        builder.add_node("cache_terminal", no_cache)

        # Edges do grafo: START → rate_limit → datetime → quick → infra_guard → cache → classify
        async def no_rate(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_rate_limit(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", "")
            )

        async def no_datetime(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_datetime(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                persist=estado.get("persist", True)
            )

        async def no_quick(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_quick(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                persist=estado.get("persist", True)
            )

        async def no_infra(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_infra(
                user_id=estado.get("user_id", ""), 
                profile=estado.get("profile", ""), 
                text=estado.get("text", ""), 
                role=estado.get("role", "admin"), 
                persist=estado.get("persist", True)
            )

        # Adiciona os nós terminais ao grafo
        for nome, fn in (
            ("rate_limit", no_rate),
            ("datetime", no_datetime),
            ("quick", no_quick),
            ("infra_guard", no_infra),
        ):
            builder.add_node(nome, fn)

        # Conecta os nós terminais: START → rate_limit → datetime → quick → infra_guard → cache_terminal → classify
        builder.add_edge(START, "rate_limit")
        builder.add_conditional_edges("rate_limit", rota("datetime"))
        builder.add_conditional_edges("datetime", rota("quick"))
        builder.add_conditional_edges("quick", rota("infra_guard"))
        builder.add_conditional_edges("infra_guard", rota("cache_terminal"))
        builder.add_conditional_edges("cache_terminal", rota("classify"))

        # Conecta o classify com roteamento condicional
        builder.add_conditional_edges(
            "classify",
            rota_por_intencao,
            {"select_tools": "select_tools", "generate": "generate", "secrets_denied": "generate"}
        )
        builder.add_edge("select_tools", "execute_parallel")
        builder.add_edge("execute_parallel", "generate")
        builder.add_edge("generate", "human_loop")
        builder.add_conditional_edges("human_loop", lambda _estado: END)

        # Nó de pós-processamento (para compatibilidade com testes de retomada)
        async def no_post(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_post_processo(
                user_id=estado.get("user_id", ""),
                profile=estado.get("profile", ""),
                text=estado.get("text", ""),
                persist=estado.get("persist", True),
                estado=estado,
            )
        builder.add_node("post_process", no_post)
        # O post_process é chamado após o generate (antes do human_loop) se não for terminal
        # Mas para manter compatibilidade, adicionamos como nó opcional
        # O fluxo real agora: generate → human_loop → END
        # Para testes: podemos adicionar edge generate → post_process → human_loop
        builder.add_edge("generate", "post_process")
        builder.add_edge("post_process", "human_loop")

        saver = self._obter_graph_saver()
        grafo = builder.compile(checkpointer=saver)
        thread_id = self._thread_grafo(user_id, session_id, text, profile, role)
        salvo = saver.ultimo(thread_id)
        retomar = salvo is not None and not salvo.concluido
        if retomar:
            log.info(
                f"Grafo: retomando turno interrompido {thread_id} "
                f"(passo {salvo.passo}, próximos={salvo.proximos})"
            )
        entrada = None if retomar else {
            "user_id": user_id,
            "profile": profile,
            "session_id": session_id,
            "role": role,
            "text": text,
            "system_prompt": system_prompt,
            "persist": persist,
            "extra_history": extra_history,
            "messages": [{"role": "user", "content": text}],
        }
        estado_final = await grafo.ainvoke(
            entrada,
            {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 50,
            },
            resume=retomar,
        )

        # Se o grafo pausou aguardando decisão humana, retorna o estado
        # com pending_human_input para que o chamador decida o que fazer.
        if estado_final.get("pending_human_input") and not estado_final.get("human_decision"):
            estado_final["thread_id"] = thread_id
            estado_final["pausado_human_loop"] = True
            return estado_final

        return estado_final


    async def _executar_pipeline(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        session_id: str,
        role: str,
        persist: bool,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Grafo se ligado; fallback imediato para o encadeamento direto."""
        from core.orchestrator_graph import habilitado_por_env

        if habilitado_por_env():
            try:
                return await self._executar_grafo(
                    user_id=user_id,
                    profile=profile,
                    text=text,
                    system_prompt=system_prompt,
                    session_id=session_id,
                    role=role,
                    persist=persist,
                    extra_history=extra_history,
                )
            except Exception as exc:
                log.warn(
                    "Grafo do orquestrador falhou — usando o pipeline direto",
                    motivo=f"{type(exc).__name__}: {exc}",
                )
                # O direto vai responder agora; este turno não deve ser
                # retomado depois como se o processo tivesse morrido.
                if self._graph_saver is not None:
                    thread_id = self._thread_grafo(
                        user_id, session_id, text, profile, role
                    )
                    ultimo = self._graph_saver.ultimo(thread_id)
                    if ultimo is not None and not ultimo.concluido:
                        self._graph_saver.put(
                            thread_id,
                            ultimo.passo,
                            ultimo.estado,
                            [],
                            concluido=True,
                        )
        return await self._executar_direto(
            user_id=user_id,
            profile=profile,
            text=text,
            system_prompt=system_prompt,
            session_id=session_id,
            role=role,
            persist=persist,
            extra_history=extra_history,
        )

    @staticmethod
    def _exige_aprovacao_humana(acao: str) -> bool:
        """True se a ação precisa passar pelo human_loop antes de executar."""
        return acao in acoes_que_exigem_aprovacao()

    @staticmethod
    def _pedido_de_aprovacao(
        acao: str, params: dict[str, Any], text: str
    ) -> dict[str, Any]:
        """Pacote de `pending_human_input` guardado no checkpoint."""
        descricoes = {
            "google_drive_create": "criar arquivo no Drive",
            "google_drive_update": "atualizar arquivo no Drive",
            "google_drive_delete": "apagar arquivo do Drive",
            "google_calendar_create": "criar compromisso na agenda",
            "google_calendar_delete": "apagar compromisso da agenda",
            "google_gmail_send": "enviar e-mail",
            "google_gmail_delete": "apagar e-mail",
            "ha_device_control": (
                "ligar dispositivo do lar" if params.get("on", True)
                else "desligar dispositivo do lar"
            ),
        }
        alvo = str(
            params.get("alvo")
            or params.get("name")
            or params.get("titulo")
            or params.get("para")
            or ""
        ).strip()
        detalhes = descricoes.get(acao, "executar ação externa")
        if alvo:
            detalhes = f"{detalhes}: {alvo}"
        return {
            "acao": acao,
            "params": dict(params),
            "texto": text,
            "detalhes": detalhes,
            # `criado_em` é o relógio da validade (ttl_aprovacao_humana).
            "criado_em": time.time(),
        }

    async def _aplicar_decisao_humana(
        self, estado: dict[str, Any]
    ) -> dict[str, Any]:
        """Fecha a pausa e executa (ou descarta) a ação aprovada.

        Só roda depois que o dono respondeu: o grafo pausa ANTES do nó
        `human_loop` quando há `pending_human_input` sem decisão.
        """
        pendente = estado.get("pending_human_input") or {}
        decisao = str(estado.get("human_decision") or "").strip().lower()
        if not pendente:
            return {"pending_human_input": None, "steps": ["human_loop"]}

        # Validade do pedido: um "sim" atrasado não executa ação fora de
        # contexto. Sem `criado_em` (checkpoint anterior), não expira.
        expirado_em = pending_expirado(pendente)
        if expirado_em:
            return {
                "pending_human_input": None,
                "human_decision": None,
                "message": expirado_em,
                "route": "human_loop_expirado",
                "registrar": False,
                "steps": ["human_loop"],
            }

        aprovacoes = {"aprovar", "aprovo", "sim", "s", "yes", "y", "confirmo", "ok"}
        recusas = {"cancelar", "cancela", "recusar", "recuso", "nao", "não", "n", "no"}

        if decisao not in aprovacoes and decisao not in recusas:
            return {
                "steps": ["human_loop"],
                "message": (
                    "❓ Ação pendente. Responda 'sim' para aprovar ou "
                    "'não' para cancelar."
                ),
                "route": "human_loop_pendente",
                "registrar": False,
            }

        if decisao in recusas:
            return {
                "pending_human_input": None,
                "human_decision": None,
                "message": "🚫 Ação cancelada — nada foi executado.",
                "route": "human_loop_cancelado",
                "registrar": False,
                "steps": ["human_loop"],
            }

        acao = str(pendente.get("acao") or "")
        params = dict(pendente.get("params") or {})
        if not acao:
            return {
                "pending_human_input": None,
                "human_decision": None,
                "message": "⚠️ Pedido de aprovação sem ação — nada executado.",
                "route": "human_loop_invalido",
                "registrar": False,
                "steps": ["human_loop"],
            }

        # A aprovação humana é a confirmação: a action não deve pedir o
        # "sim" de 2 passos outra vez (HA e escritas Google).
        from tools.actions.actions import aprovacao_humana_em_curso

        with aprovacao_humana_em_curso():
            data = await self.execute_action(
                acao,
                params,
                str(estado.get("user_id") or ""),
                role=str(estado.get("role") or "admin"),
            )
        from core.intents import format_intent_result

        resposta = format_intent_result(acao, data) or "✅ Ação executada."
        return {
            "pending_human_input": None,
            "human_decision": None,
            "message": resposta,
            "route": acao,
            "llm_used": f"human_loop:{acao}",
            "registrar": False,
            "steps": ["human_loop"],
        }

    async def retomar_turno_humano(
        self,
        thread_id: str,
        decisao: str,
    ) -> dict[str, Any]:
        """Retoma um turno pausado no human_loop com a decisão do usuário.

        Chamado quando o dono responde à solicitação de aprovação (ex: 'sim', 'não').
        Aplica a decisão no checkpoint e continua a execução do grafo até o fim.
        """
        from core.orchestrator_graph import habilitado_por_env

        if not habilitado_por_env():
            raise RuntimeError("Grafo do orquestrador desligado (OD_ORCHESTRATOR_GRAPH=0)")

        saver = self._obter_graph_saver()
        salvo = saver.ultimo(thread_id)
        if salvo is None:
            raise RuntimeError(f"Thread sem checkpoint: {thread_id}")

        # Aplica a decisão humana no checkpoint. O turno pausou ANTES do
        # human_loop consumir a decisão, e o post_process ficou pendente:
        # retomar só o human_loop pularia a etapa 8.
        estado = dict(salvo.estado)
        estado["human_decision"] = decisao
        # `pending_human_input` fica no estado: o nó human_loop precisa da
        # ação/params para executar depois do "sim" (ou descartar no "não").
        proximos = list(salvo.proximos)
        if proximos == ["human_loop"]:
            proximos = ["human_loop", "post_process"]
        saver.put(thread_id, salvo.passo, estado, proximos)

        # Reconstrói o grafo completo para retomar a execução
        from core.orchestrator_graph import (
            END,
            REDUTORES,
            START,
            OrchestratorState,
            StateGraph,
        )

        # O estado salvo já tem todos os parâmetros necessários (user_id, profile, text, etc.)
        # Extraímos do estado salvo
        saved_user_id = estado.get("user_id", "")
        saved_profile = estado.get("profile", "")
        saved_text = estado.get("text", "")
        saved_system_prompt = estado.get("system_prompt", "")
        saved_role = estado.get("role", "admin")
        saved_session_id = estado.get("session_id", "")
        saved_persist = estado.get("persist", True)
        saved_extra_history = estado.get("extra_history")

        async def no_rate(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_rate_limit(
                user_id=saved_user_id, profile=saved_profile, text=saved_text
            )

        async def no_datetime(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_datetime(
                user_id=saved_user_id, profile=saved_profile, text=saved_text, persist=saved_persist
            )

        async def no_quick(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_quick(
                user_id=saved_user_id, profile=saved_profile, text=saved_text, persist=saved_persist
            )

        async def no_infra(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_infra(
                user_id=saved_user_id, profile=saved_profile, text=saved_text, role=saved_role, persist=saved_persist
            )

        async def no_intents(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_intents(
                user_id=saved_user_id, profile=saved_profile, text=saved_text, role=saved_role, persist=saved_persist
            )

        async def no_cache(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_cache(
                user_id=saved_user_id, profile=saved_profile, text=saved_text, persist=saved_persist
            )

        async def no_llm(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_llm(
                user_id=saved_user_id,
                profile=saved_profile,
                text=saved_text,
                system_prompt=saved_system_prompt,
                role=saved_role,
                extra_history=saved_extra_history,
            )

        async def no_post(estado: dict[str, Any]) -> dict[str, Any]:
            return await self._etapa_post_processo(
                user_id=saved_user_id,
                profile=saved_profile,
                text=saved_text,
                persist=saved_persist,
                estado=estado,
            )

        async def no_humano(estado: dict[str, Any]) -> dict[str, Any]:
            # Executa a ação aprovada (ou descarta, se cancelada) e fecha a
            # pausa; o pedido segue no estado até este ponto.
            return await self._aplicar_decisao_humana(estado)

        def rota(proximo: str):
            def _rota(estado: dict[str, Any]) -> str:
                return END if estado.get("terminal") else proximo
            return _rota

        builder = StateGraph(OrchestratorState, reducers=REDUTORES)
        for nome, fn in (
            ("rate_limit", no_rate),
            ("datetime", no_datetime),
            ("quick", no_quick),
            ("infra_guard", no_infra),
            ("intents", no_intents),
            ("cache", no_cache),
            ("generate", no_llm),
            ("post_process", no_post),
            ("human_loop", no_humano),
        ):
            builder.add_node(nome, fn)
        builder.add_edge(START, "rate_limit")
        builder.add_conditional_edges("rate_limit", rota("datetime"))
        builder.add_conditional_edges("datetime", rota("quick"))
        builder.add_conditional_edges("quick", rota("infra_guard"))
        builder.add_conditional_edges("infra_guard", rota("intents"))
        builder.add_conditional_edges("intents", rota("cache"))
        builder.add_conditional_edges("cache", rota("generate"))
        builder.add_conditional_edges("generate", rota("post_process"))
        builder.add_edge("post_process", END)
        builder.add_conditional_edges("human_loop", lambda _estado: END)

        grafo = builder.compile(checkpointer=saver)

        # Resume a execução do grafo
        estado_final = await grafo.ainvoke(
            None,
            {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 50,
            },
            resume=True,
        )

        return estado_final

    @staticmethod
    def _thread_grafo(
        user_id: str, session_id: str, text: str, profile: str, role: str
    ) -> str:
        """Thread determinística por turno.

        O MESMO texto na MESMA sessão é o retry do cliente depois de um
        restart, então retoma o checkpoint em vez de pagar o LLM de novo.
        Texto/perfil/papel diferentes = thread nova, sem herdar estado alheio.
        """
        chave = hashlib.sha256(
            f"{session_id}\x00{text}\x00{profile}\x00{role}".encode("utf-8")
        ).hexdigest()[:20]
        return f"{user_id}:{session_id or 'sem-sessao'}:{chave}"

    async def _finalizar_estado(
        self,
        result: OrchestrationResult,
        estado: dict[str, Any],
        text: str,
        persist: bool,
        started: float,
    ) -> OrchestrationResult:
        """Monta o resultado a partir do estado e registra rota terminal."""
        result.route = str(estado.get("route") or "")
        result.message = str(estado.get("message") or "")
        result.llm_used = str(estado.get("llm_used") or "")
        result.cached = bool(estado.get("cached"))
        result.fallback_used = bool(estado.get("fallback_used"))
        result.prompt = str(estado.get("prompt") or "")
        result.error = str(estado.get("error") or "")
        registrar = estado.get("registrar")
        if registrar is not None:
            await self._record_terminal(result, text, persist=bool(registrar))
        return await self._finish(result, started)

    async def _gerar_com_contexto(
        self,
        *,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        role: str,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> tuple[Optional[str], str, bool, str]:
        """Etapas 4.5–6.7: contexto + RAG + prompt + LLM + guardas."""
        # Etapa 4.5 — RAG (Parte B NOMAD): reescrita da consulta com o
        # histórico, floor de relevância duplo, reranker e orçamento do
        # bloco de referência. Recuperado ANTES do prompt e injetado no
        # system (após a linha de data/hora); o que não coube fica
        # registrado em métricas (nunca some em silêncio).
        contexto = self._contexto_msgs(user_id, profile, extra_history)
        system_efetivo = self._resolve_system(system_prompt, profile, role)
        # Etapas 4.5 (RAG) + 4.6 (enciclopédia) + 4.6b (nota de fonte):
        # UMA fonte por prompt — duas fontes de verdade brigando no mesmo
        # prompt é receita para alucinação. Em pergunta de FATO a ordem é
        # a nova (régua do dono, 26/10): fonte verificada primeiro.
        rag_block = self._bloco_de_referencia(
            text, contexto, role, system_efetivo
        )

        # Etapa 5 — Histórico: monta contexto ChatML
        prompt = self._build_prompt(
            user_id,
            profile,
            text,
            system_efetivo,
            contexto=contexto,
            rag_block=rag_block,
        )

        # Etapas 6 e 7 — LLM com fallback
        message, llm_used, fallback_used = await self._generate(prompt)
        if message is None:
            return None, llm_used, fallback_used, prompt

        # Etapa 6.5 — Anti-recusa (2026-09-28): o REST não tinha esta etapa
        # (assimetria com o WS) e a recusa-alucinação do gemma chegava
        # INTEIRA ao usuário — caso real: 'temperatura em presidente
        # venceslau sp' respondida com 'informação de infraestrutura é
        # restrita ao dono'. Para admin é a recusa de dados operacionais de
        # sempre; para user/anônimo só aciona quando o ASSUNTO é do mundo
        # externo (o 'não posso' na vedação de infra é de direito do papel).
        refusal = self._refusal_reason(message, role, text)
        if refusal:
            log.warn(
                "Recusa indevida detectada — refazendo",
                reason=refusal,
                role=role,
            )
            retry = await self._resolve_refusal(prompt, role, text)
            if retry is not None:
                message, llm_used = retry
                fallback_used = True

        # Etapa 6.7 — Anti-FALSO-SUCESSO (espelho do stream): a resposta
        # que fingia confirmar/executar ação é trocada pela honesta antes
        # do resultado, do histórico e do cache.
        fake = fake_action_reason(message)
        if fake:
            log.warn(
                "Resposta do LLM fingia executar ação — substituída",
                reason=fake,
            )
            message = FAKE_ACTION_MESSAGE
        return message, llm_used, fallback_used, prompt

    def _obter_graph_saver(self) -> Any:
        """SqliteSaver preguiçoso — abrir banco no boot é desperdício."""
        if self._graph_saver is None:
            from core.orchestrator_graph import SqliteSaver

            caminho = os.getenv("OD_GRAPH_CHECKPOINT_DB", "")
            if not caminho:
                raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                caminho = os.path.join(raiz, "data", "checkpoints.db")
            with self._lock:
                if self._graph_saver is None:
                    self._graph_saver = SqliteSaver(caminho)
        return self._graph_saver

    # -- Etapas internas -----------------------------------------------------

    def _resolve_system(self, system_prompt: str, profile: str, role: str) -> str:
        """System prompt efetivo: explícito > identidade por perfil+papel.

        O padrão do launcher (`default_system_prompt`) é um prompt ESTÁTICO
        (guardian, limites genéricos) — para o chat de verdade o prompt é
        reconstruído com o PERFIL pedido (Nyx responde como Nyx) e o PAPEL
        de quem fala: o dono (admin) tem acesso pleno aos dados do sistema;
        o papel user mantém a vedação.
        """
        if system_prompt:
            return system_prompt
        try:
            from agents.nicky_virthy.personality import get_system_prompt

            return get_system_prompt(profile, role)
        except Exception:
            return self._config.default_system_prompt

    @staticmethod
    def _refusal_reason(
        response: str, role: str, text: str = ""
    ) -> str:
        """Motivo pelo qual a resposta é uma RECUSA indevida ('' = ok).

        Para o DONO (admin): o modelo (gemma) às vezes ignora o system
        prompt e recusa dados operacionais ("não posso", "não tenho
        acesso", "por segurança") — quando isso acontece com o dono, o
        pipeline REFAZ a geração com reforço; persistindo, responde com a
        action real em vez da recusa do modelo.

        Para user/anonymous (2026-09-28): a recusa só é "indevida" quando
        o ASSUNTO é do mundo externo (clima/geografia/conhecimento geral)
        — a vedação de infraestrutura é de DIREITO do papel user, e um
        "não posso" nela não é recusa, é o sistema funcionando. Com assunto
        externo, porém, o modelo ALUCINA a vedação ('restrita ao dono' para
        uma pergunta de clima) — caso real do dono no ar.
        """
        if not response:
            return ""
        from core.intents import detect_external_intent

        low = response.lower()
        # Etiqueta de log em QUALQUER posição (o gemma entregava
        # '[NICKY][WARN] Não posso...' — startswith deixava passar quando
        # o modelo embutia a etiqueta depois de um texto) (2026-09-27).
        for etiqueta in ("[crit]", "[warn]", "[info]", "[online]", "[nicky]"):
            if etiqueta in low:
                return f"etiqueta de log no lugar da resposta ({etiqueta})"
        if role != "admin":
            # Só interessa quando a pergunta é do MUNDO EXTERNO: recusa
            # nela é alucinação da vedação — nunca é a proteção funcionando
            # (a proteção determinística de IP/portas é Etapa 3.4, antes do
            # LLM; um 'não posso' vindo DO LLM sobre IP/portas com a
            # Etapa 3.4 no ar é desculpa inventada, não direito do user).
            if not detect_external_intent(text):
                return ""
            recusas_user = (
                r"n[aã]o posso",
                r"nao posso",
                r"n[aã]o tenho",
                r"restri(?:c)?t[oa]s?",
                r"restrita ao dono",
                r"restritas ao dono",
            )
            for frase in recusas_user:
                if re.search(frase, low):
                    return f"alucinação de vedação para assunto externo ({frase})"
            return ""
        recusas = (
            "não posso fornecer",
            "nao posso fornecer",
            "não posso ajudar",
            "não posso revelar",
            "não tenho acesso",
            "não tenho informa",
            "não é possível fornecer",
            "não posso dar",
            "não vou fornecer",
            "por razões de segurança",
            "por segurança, não",
            "não posso fornecer essas informações",
            "sem acesso físico",
            "não tenho como verificar",
            # Novos padrões vistos no ar (27/09): 'não posso fornecer
            # informações sobre o clima' e variantes com 'informação'.
            "não posso fornecer informações sobre",
            "não posso fornecer informações de",
            "informações sobre o clima específico",
            "são restritas ao dono",
            "é restrita ao dono",
            "não posso fornecer o clima",
            "não posso informar",
        )
        for frase in recusas:
            if frase in low:
                return f"recusa indevida para o dono ({frase})"
        return ""

    async def _resolve_refusal(
        self,
        prompt: str,
        role: str,
        text: str,
    ) -> Optional[tuple[str, str]]:
        """Resolve uma recusa detectada: retries + fallback honesto.

        ASSUNTO EXTERNO (qualquer papel): até 2 retries (3 gerações no
        total) — recusar clima/geografia é alucinação, e quem pergunta
        não deve ver a mentira do modelo; esgotando, devolve o aviso
        honesto EXTERNAL_UNAVAILABLE_MESSAGE (não cacheável; a próxima
        tentativa vai de novo ao modelo).
        DADO DE SISTEMA (admin): 1 retry, como sempre — persistindo, o
        chamador (WS) cai para a action real e o REST devolve a recusa
        original (que, para IP/portas de fato vedados ao user, é a
        resposta certa).
        """
        from core.intents import detect_external_intent

        attempts = 2 if detect_external_intent(text) else 1
        result: Optional[tuple[str, str]] = await self._retry_generation(
            prompt, role, text
        )
        for _ in range(attempts - 1):
            if result is not None:
                return result
            result = await self._retry_generation(prompt, role, text)
        if result is not None:
            return result
        if attempts > 1:
            # Assunto externo: o fallback é honesto e não cacheável — nunca
            # a recusa falsa do modelo.
            # Casa de Limitações (v1.13.0): o sistema não soube responder —
            # registra como candidata a melhoria (nunca derruba o pipeline).
            try:
                from core.limitacoes import registrar_fallback_honesto
                registrar_fallback_honesto(text)
            except Exception:
                pass
            return EXTERNAL_UNAVAILABLE_MESSAGE, ""
        return None

    async def _retry_generation(
        self,
        prompt: str,
        role: str = "admin",
        text: str = "",
    ) -> Optional[tuple[str, str]]:
        """Segunda passada do LLM com reforço anti-recusa (por papel).

        Para o DONO: dados operacionais da máquina são DELE — responda por
        completo.
        Para user/anônimo: só chega aqui com assunto do MUNDO EXTERNO (a
        Etapa 3.4 já negou infra antes do LLM) — o reforço reafirma a
        vedação real do papel e manda responder o assunto externo sem
        inventar restrição.

        Returns:
            (resposta, llm_used) ou None quando o retry também falha ou
            devolve recusa/etiqueta de novo.
        """
        # O prompt ChatML termina no marcador de assistant; o reforço entra
        # como um system EXTRA antes da resposta do modelo.
        if role == "admin":
            reforco = (
                prompt
                + "<|im_start|>system\nREFORÇO AO MODELO: quem pergunta é o "
                "DONO/ADMIN autenticado do servidor. Informações operacionais "
                "desta máquina (IPs, portas, serviços, paths, métricas, "
                "temperatura, sensores) são DELE e devem ser respondidas por "
                "completo. Perguntas do MUNDO EXTERNO (clima de cidade, "
                "temperatura de lugar, geografia) são CONVERSA LIVRE — responda "
                "com o que souber, sem inventar restrição. NÃO recuse, NÃO peça "
                "para verificar manualmente, NÃO use etiquetas de log "
                "([NICKY][...]) — responda SOMENTE o conteúdo, direto.<|im_end|>\n"
            )
        else:
            reforco = (
                prompt
                + "<|im_start|>system\nREFORÇO AO MODELO: a pergunta é sobre o "
                "MUNDO EXTERNO (clima, lugar, geografia, conhecimento geral) — "
                "NÃO é dado deste servidor. Responda com o que souber, direto "
                "e por completo. A única vedação real deste sistema é de dados "
                "que podem PREJUDICAR O SERVIDOR (IPs, portas, paths, "
                "credenciais) — e não é o caso desta pergunta. NÃO recuse, NÃO "
                "invente restrição, NÃO use etiquetas de log ([NICKY][...]) — "
                "responda SOMENTE o conteúdo.<|im_end|>\n"
            )
        message, llm_used, _ = await self._generate(reforco)
        if not message or self._refusal_reason(message, role, text):
            return None
        return message, llm_used

    def _contexto_msgs(
        self,
        user_id: str,
        profile: str,
        extra_history: Optional[list[dict[str, str]]] = None,
    ) -> list[dict[str, str]]:
        """Turnos recentes da conversa (sem a pergunta atual).

        Com `extra_history`, o contexto vem do cliente (conversa anônima);
        senão, do banco. É a MESMA lista usada pelo prompt e pela reescrita
        da consulta RAG — uma fonte só de verdade para os dois.
        """
        messages: list[dict[str, str]] = []
        turn_limit = self._config.max_history_turns
        if extra_history is not None:
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
        return messages

    def _registrar_rag(self, resultado: Any) -> None:
        """Acumula as métricas do RAG — descartado é métrica, não silêncio."""
        metrics = self._metrics
        metrics.rag_consultas += 1
        metrics.rag_trechos += len(getattr(resultado, "trechos", None) or [])
        metrics.rag_descartados += int(getattr(resultado, "descartados", 0) or 0)
        metrics.rag_tokens_descartados += int(
            getattr(resultado, "tokens_descartados", 0) or 0
        )

    def _bloco_rag(
        self,
        text: str,
        contexto: Any,
        role: str,
        system_efetivo: str,
        *,
        fato: bool = False,
    ) -> str:
        """Etapa 4.5 — bloco do acervo da casa ("" sem RAG plugado).

        `fato=True` repassa o piso de FATO do RAG: o trecho tem que citar
        o termo mais raro da pergunta, senão vira nota 4.6b honesta.
        """
        if self._rag is None:
            return ""
        resultado_rag = self._rag.consult(
            text,
            historico=contexto,
            papel=role,
            system_prompt=system_efetivo,
            fato=fato,
        )
        self._registrar_rag(resultado_rag)
        return resultado_rag.block or ""

    def _bloco_de_referencia(
        self, text: str, contexto: Any, role: str, system_efetivo: str
    ) -> str:
        """Etapa 4.5 + 4.6 + 4.6b — escolhe a FONTE do prompt (uma só).

        Ordem das fontes (régua do dono, 26/10 — "aprenda com o passado,
        responda certo no presente"):

        - **pergunta de FATO** (`eh_pergunta_de_fato`): a fonte verificada
          (Wikipédia offline, etapa 4.6) é consultada ANTES do acervo da
          casa; o acervo só entra se a fonte não achar artigo. Sem artigo
          em NENHUMA das duas → **nota honesta 4.6b** — o modelo local
          respondia o fato inventado (6x na auditoria de 24/10).
        - **fora de pergunta de fato**: ordem antiga (memória interna >
          enciclopédia).

        Uma fonte por prompt: duas fontes de verdade brigando é receita
        para alucinação (docstring de memory/enciclopedia.py).
        """
        from memory.enciclopedia import NOTA_SEM_FONTE, eh_pergunta_de_fato

        if self._enciclopedia is not None and eh_pergunta_de_fato(text):
            bloco = self._bloco_enciclopedia(text)  # fonte verificada 1ª
            if bloco:
                return bloco
            # Acervo só se CASAR com o fato (piso de fato do RAG) — trecho
            # fraco não abre mão da nota honesta.
            bloco = self._bloco_rag(
                text, contexto, role, system_efetivo, fato=True
            )
            if bloco:
                return bloco
            # Etapa 4.6b — nenhuma fonte tem o artigo: nota honesta no
            # lugar do silêncio (sem ela o modelo local inventava).
            self._metrics.enciclopedia_sem_fonte += 1
            log.info("Nota de fonte (4.6b): pergunta de fato sem artigo")
            return NOTA_SEM_FONTE

        bloco = self._bloco_rag(text, contexto, role, system_efetivo)
        if bloco:
            return bloco
        return self._bloco_enciclopedia(text)

    def _bloco_memoria(self, user_id: str, text: str) -> str:
        """Bloco de memória longa (F4 fase 2): o que já se sabe do usuário.

        Recupera os fatos do GRÁFO daquele usuário que casam com a mensagem
        (até `memoria_max_fatos`, cortados em `memoria_max_chars`). Sem
        memória, usuário anônimo ou erro: devolve "" e o prompt segue
        idêntico ao de antes da fase 2 — memória é acessório, nunca caminho
        crítico.
        """
        if not self._config.memoria_no_prompt:
            return ""
        if not user_id:
            return ""
        try:
            from core.memory_layer import obter_memoria

            fatos = obter_memoria().buscar(
                user_id, text, limite=max(1, self._config.memoria_max_fatos)
            )
        except Exception as exc:  # noqa: BLE001 — memória nunca derruba o chat
            log.warn(
                "Memória longa: leitura falhou (prompt segue sem bloco)",
                erro=f"{type(exc).__name__}: {exc}",
            )
            return ""
        if not fatos:
            return ""
        linhas = "\n".join(f"- {fato.conteudo}" for fato in fatos)
        bloco = (
            "Memória do usuário (fatos que ele mesmo contou em conversas "
            "anteriores; use se ajudar, sem repetir à toa):\n" + linhas
        )
        if len(bloco) > self._config.memoria_max_chars:
            bloco = bloco[: self._config.memoria_max_chars].rstrip() + "…"
        return bloco

    def _bloco_enciclopedia(self, text: str) -> str:
        """Etapa 4.6 — Wikipédia offline (Kiwix).

        Em pergunta de fato é a PRIMEIRA fonte (chamada antes do RAG);
        fora disso só entra com `rag_block == ""` — uma fonte por prompt.
        Qualquer erro/timeout do Kiwix vira block "" + métrica — o chat
        segue normalmente, sem exceção no caminho.
        """
        if self._enciclopedia is None:
            return ""
        metrics = self._metrics
        metrics.enciclopedias += 1
        try:
            resultado = self._enciclopedia.consult(text)
        except Exception as exc:  # noqa: BLE001 — nunca derrubar o chat
            metrics.enciclopedia_erros += 1
            log.warn(
                "Enciclopédia falhou (chat segue sem bloco)",
                erro=f"{type(exc).__name__}: {exc}",
            )
            return ""
        bloco = getattr(resultado, "block", "") or ""
        if getattr(resultado, "erro", ""):
            metrics.enciclopedia_erros += 1
        if bloco:
            metrics.enciclopedia_blocos += 1
        return bloco

    def _build_prompt(
        self,
        user_id: str,
        profile: str,
        text: str,
        system_prompt: str,
        extra_history: Optional[list[dict[str, str]]] = None,
        contexto: Optional[list[dict[str, str]]] = None,
        rag_block: str = "",
    ) -> str:
        """Monta o prompt ChatML com histórico (últimos N turns) + datetime.

        Com `extra_history`, o contexto vem do cliente (conversa anônima) em
        vez do banco — mesma regra de truncamento por turnos. Com `contexto`
        pré-montado, usa-se a MESMA lista da etapa 4.5 (RAG). Com
        `rag_block`, o bloco de referência entra DEPOIS do system e da
        data/hora (o prefixo estático continua idêntico para o cache de KV).
        Com o orçamento ligado (`orcamento_janela`), o histórico é encaixado
        no que sobra da janela depois de system + bloco + resposta — e o
        que foi descartado vira métrica (`contexto_descartados`).
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
        if rag_block:
            system = f"{system}\n{rag_block}"
        bloco_memoria = self._bloco_memoria(user_id, text)
        if bloco_memoria:
            # Memória entra DEPOIS do bloco de referência: o que o usuário
            # contou sobre si é mais estável que o texto recuperado, então
            # o prefixo cacheado do llama-server sobrevive melhor aqui.
            system = f"{system}\n{bloco_memoria}"

        if contexto is None:
            messages = self._contexto_msgs(user_id, profile, extra_history)
        else:
            messages = list(contexto)

        orcamento = self._config.orcamento_janela
        if orcamento > 0 and messages:
            from memory.context import ContextManager, estimate_tokens

            ctx = ContextManager(
                max_tokens=orcamento,
                reserved_tokens=(
                    self._config.orcamento_resposta + estimate_tokens(system)
                ),
            )
            ajustado = ctx.fit(messages)
            descartados = len(messages) - len(ajustado)
            if descartados > 0:
                self._metrics.contexto_descartados += descartados
                log.warn(
                    "Histórico fora do orçamento — turnos descartados",
                    descartados=descartados,
                    tokens_saved=ctx.stats().get("tokens_saved", 0),
                    janela=orcamento,
                )
            messages = ajustado

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
        # LLMCache (chave exata)
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
        # SemanticCache (similaridade)
        if self.semantic_cache is not None and _cacheable(message):
            try:
                self.semantic_cache.set(
                    text,
                    message,
                    llm_used=llm_used,
                    tokens_used=0,
                    response_time_ms=1.0,
                    profile=profile,
                )
            except Exception as exc:
                log.warn(
                    "Orchestrator semantic cache write failed",
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
        self._memorizar(user_id, text)

    def _memorizar(self, user_id: str, text: str) -> None:
        """Memória longa (F4 fase 1): guarda fatos do que o usuário disse.

        A extração é determinística (regex em `core/memory_layer`), custa
        microssegundos e só toca o SQLite quando há fato reconhecido. É
        melhor-esforço: falha de memória NUNCA quebra a resposta.
        Desligável com `OD_MEMORY_AUTO=0`.
        """
        if os.environ.get("OD_MEMORY_AUTO", "1").strip().lower() in {"0", "false", "no"}:
            return
        try:
            from core.memory_layer import extrair_fatos, obter_memoria

            fatos = extrair_fatos(text)
            if not fatos:
                return
            memoria = obter_memoria()
            for fato in fatos:
                memoria.adicionar_fato(
                    user_id,
                    fato["conteudo"],
                    tipo=fato["tipo"],
                    entidade=fato["entidade"],
                    origem="chat",
                )
        except Exception as exc:
            log.warn(
                "Memória longa: gravação falhou",
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
            # Controle do lar pelo chat (v1.8.1 luzes; v1.9.0 tomadas): a
            # negação do Registry é o GATE DE PAPEL determinístico — vira
            # resposta guiada em vez de cair no LLM (que podia alucinar
            # confirmação).
            if action_name in _PAPEL_GATE_ACTIONS:
                return {"ok": False, "error": "permissao_negada"}
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

    async def _segredo_do_cofre(self, text: str, user_id: str, role: str) -> str:
        """Credencial do DONO vem do COFRE (ordens do dono 22/10:
        "o master admin pode fazer qualquer coisa" + "as senhas vem do cofre").

        Só o papel admin chega aqui (o gate fica na chamada). A resposta sai
        das actions vault_list/vault_get — o sistema NUNCA gera valor: cofre
        fora = recusa honesta, empatado = o dono escolhe, sem achado = lista
        os títulos (títulos não são segredo). O resultado é terminal com
        persist=False: o VALOR não entra no histórico — nunca vira prompt,
        cache nem relatório da auditoria; o log só registra a rota.
        """
        from core.intents import extrair_termo_segredo, resolver_item_segredo

        if self._action_registry is None:
            return SECRETS_DENIED_MESSAGE
        termo = extrair_termo_segredo(text)
        lista = await self.execute_action(
            "vault_list", {}, user_id=user_id, role=role
        )
        if not isinstance(lista, dict):
            return ("🔒 Cofre indisponível agora — sem cofre não há senha para "
                    "mostrar, e inventar eu não invento.")
        if lista.get("ok") is False:
            return (f"🔒 Cofre indisponível: "
                    f"{lista.get('message') or lista.get('error')}.")
        nomes = [str(i.get("nome") or "").strip()
                 for i in (lista.get("itens") or [])]
        nomes = [n for n in nomes if n]
        melhor, empatados = resolver_item_segredo(termo, nomes)
        if empatados:
            return ("🔐 Vários itens casam com isso: " + ", ".join(empatados)
                    + " — qual deles?")
        if melhor is None:
            if not termo:
                return ("🔐 Qual credencial? Títulos do cofre: "
                        + ", ".join(nomes) + ".")
            return (f"🔐 Não achei '{termo}' no cofre. Títulos: "
                    + ", ".join(nomes) + ".")
        item = await self.execute_action(
            "vault_get", {"name": melhor}, user_id=user_id, role=role
        )
        if not isinstance(item, dict):
            return ("🔒 Cofre não respondeu — nada inventado; tente de novo "
                    "em instantes.")
        if item.get("ok") is False:
            return f"🔒 Cofre: {item.get('message') or item.get('error')}."
        dados = item.get("item") or {}
        senha = str(dados.get("password") or "")
        if not senha:
            return f"🔐 {melhor}: o item existe mas está sem valor."
        linha = f"🔐 {melhor}: {senha}"
        usuario = str(dados.get("username") or "")
        if usuario:
            linha += f"\n   usuário: {usuario}"
        return linha

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
