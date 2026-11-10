"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/memory_embeddings.py
Descrição: Embeddings opcionais (F4, fase 4) — a única peça da busca de
           memória que a sobreposição de termos não resolve: sinônimo
           ("animal" ≈ "cachorro"). Provider por API, cache em SQLite.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F4 fase 4 (o furo medido: 1 caso em 10)
  - Gemini API `gemini-embedding-001` (3072 dims, pedimos 768)

Architecture:
    A busca lexical do `MemoryGraph` acerta 9/10 no conjunto medido; o furo é
    sinonímia, que exige vetor. Este módulo NÃO substitui a busca: é o
    fallback dela — só é chamado quando a busca por termos volta vazia.

    Sem SDK: `urllib` da stdlib, uma chamada em lote por vez, timeout curto e
    QUALQUER falha (sem chave, sem rede, 429, JSON estranho) devolve `None`.
    Memória é acessório; nunca é caminho crítico do chat.

    Vetores ficam em `memory_vectors` no mesmo `data/memory.db`, com o nome do
    modelo — trocar de modelo não mistura espaço vetorial, só re-embeda.

Usage:
    from core.memory_embeddings import embed_textos, provedor_ativo

    if provedor_ativo():
        vetores = embed_textos(["tem um cachorro chamado Rex"])  # ou None
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

_log = get_logger("omega.core.memory_embeddings")

PROVEDOR_PADRAO = "auto"
MODELO_PADRAO = "gemini-embedding-001"
DIMS_PADRAO = 768
TIMEOUT_PADRAO = 3.0
# Piso absoluto de similaridade para aceitar um fato vindo só do vetor.
MIN_PADRAO = 0.78
# Margem sobre a mediana dos fatos: é o que separa "assunto meu" de "assunto
# aleatório" — no Gemini o cosseno de pares sem relação já fica ~0,75, então
# limiar absoluto sozinho não decide nada.
MARGEM_PADRAO = 0.05

_URL_GEMINI = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{modelo}:batchEmbedContents?key={chave}"
)
# A API aceita até 100 textos por chamada; ficamos abaixo para o corpo e o
# tempo de resposta não explodirem.
_LOTE = 50


def _env_float(nome: str, padrao: float) -> float:
    try:
        return float(os.environ.get(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def modelo() -> str:
    """Modelo de embedding em uso (entra na chave do cache)."""
    return os.environ.get("OD_MEMORY_EMBEDDING_MODELO") or MODELO_PADRAO


def dimensoes() -> int:
    """Dimensão pedida ao provider (768 basta e ocupa 1/4 de 3072)."""
    return max(64, _env_int("OD_MEMORY_EMBEDDING_DIMS", DIMS_PADRAO))


def minimo() -> float:
    """Piso absoluto de cosseno para aceitar um fato semântico."""
    return _env_float("OD_MEMORY_SEMANTICA_MIN", MIN_PADRAO)


def margem() -> float:
    """Margem mínima sobre a mediana dos fatos para aceitar o palpite."""
    return _env_float("OD_MEMORY_SEMANTICA_MARGEM", MARGEM_PADRAO)


def provedor_ativo() -> str:
    """Provider de embedding disponível: 'gemini' ou '' (busca só lexical).

    `OD_MEMORY_EMBEDDING=off` desliga de vez (é o que a suíte de testes usa);
    `auto` (padrão) liga se houver `GEMINI_API_KEY` no ambiente.
    """
    escolha = (os.environ.get("OD_MEMORY_EMBEDDING") or PROVEDOR_PADRAO).strip().lower()
    if escolha in {"0", "off", "false", "nao", "não", "none"}:
        return ""
    if escolha in {"gemini", "auto"} and os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return ""


def cosseno(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno; 0.0 se algum vetor for nulo."""
    if not a or not b:
        return 0.0
    produto = sum(x * y for x, y in zip(a, b))
    norma = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return produto / norma if norma else 0.0


def _pedir_gemini(textos: list[str]) -> Optional[list[list[float]]]:
    chave = os.environ.get("GEMINI_API_KEY") or ""
    if not chave:
        return None
    corpo = {
        "requests": [
            {
                "model": f"models/{modelo()}",
                "content": {"parts": [{"text": t}]},
                "taskType": "SEMANTIC_SIMILARITY",
                "outputDimensionality": dimensoes(),
            }
            for t in textos
        ]
    }
    pedido = urllib.request.Request(
        _URL_GEMINI.format(modelo=modelo(), chave=chave),
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(
        pedido, timeout=_env_float("OD_MEMORY_EMBEDDING_TIMEOUT", TIMEOUT_PADRAO)
    ) as resp:
        dados = json.load(resp)
    vetores = [e.get("values") for e in dados.get("embeddings", [])]
    if len(vetores) != len(textos) or any(not v for v in vetores):
        return None
    return vetores


def embed_textos(textos: list[str]) -> Optional[list[list[float]]]:
    """Vetores de uma lista de textos, ou `None` se o provider não ajudar.

    Nunca levanta exceção: falha de rede, timeout, cota ou resposta inválida
    viram `None` e a busca lexical segue sozinha.
    """
    limpos = [t for t in (textos or []) if isinstance(t, str) and t.strip()]
    if not limpos:
        return []
    if not provedor_ativo():
        return None
    saida: list[list[float]] = []
    try:
        for i in range(0, len(limpos), _LOTE):
            parte = _pedir_gemini(limpos[i : i + _LOTE])
            if parte is None:
                return None
            saida.extend(parte)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        _log.debug(f"embeddings: provider falhou ({type(exc).__name__}); busca segue lexical")
        return None
    return saida
