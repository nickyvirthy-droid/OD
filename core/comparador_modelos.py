"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/comparador_modelos.py
Descrição: Comparador de modelos lado a lado (fila item 5, 26/11). O mesmo
           prompt vai para 2+ modelos da MESMA cadeia do chat, em paralelo,
           e cada resposta volta com a latência medida — é a diferença
           entre escolher a IA por log antigo e ver ao vivo.

Contrato (pensado para o painel /admin):
    modelos_disponiveis() -> [{"nome", "modelo"}, ...]
    comparar(prompt, nomes=[...]) -> {
        "ok": bool,              # pelo menos um modelo respondeu
        "prompt": str,
        "comparado_em": iso8601,
        "modelos": [{"nome", "modelo", "ok", "resposta", "latencia_ms",
                     "erro"}, ...],
    }

Regras:
  * MENOS de 2 modelos não é comparação — ValueError (o painel devolve 400
    em vez de fingir que comparou);
  * um modelo que falha não derruba os outros: erro vira campo `erro` e
    `latencia_ms` mede até a falha;
  * `timeout_s` é teto por modelo (asyncio.wait_for) — o local pode ter
    timeout próprio de 240 s e travaria a comparação sozinho;
  * nada é persistido: a comparação é um retrato do agora.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

MIN_MODELOS = 2
MAX_MODELOS = 4
MAX_PROMPT = 4000
TIMEOUT_PADRAO_S = 90.0


class ComparadorError(ValueError):
    """Pedido inválido (prompt vazio, menos de 2 modelos, nome desconhecido)."""


def _provedores() -> list[Any]:
    """Cadeia real do chat — a MESMA que responde às mensagens do dono."""
    from runtime.launcher import build_llm_providers

    return build_llm_providers()


def _descrever(provider: Any) -> dict[str, str]:
    return {
        "nome": str(getattr(provider, "name", "") or "?"),
        "modelo": str(getattr(provider, "model", "") or ""),
    }


def modelos_disponiveis(providers: Optional[Sequence[Any]] = None) -> list[dict[str, str]]:
    """Modelos que respondem AGORA (a cadeia já exclui provider sem chave)."""
    lista = list(providers) if providers is not None else _provedores()
    return [_descrever(p) for p in lista]


def _selecionar(
    providers: Sequence[Any], nomes: Optional[Sequence[str]]
) -> list[Any]:
    """Filtra a cadeia pelos nomes pedidos, preservando a ordem dela."""
    if not nomes:
        return list(providers)
    pedidos = [str(n).strip().lower() for n in nomes if str(n).strip()]
    if len(pedidos) < MIN_MODELOS:
        raise ComparadorError(
            f"escolha pelo menos {MIN_MODELOS} modelos para comparar"
        )
    if len(pedidos) > MAX_MODELOS:
        raise ComparadorError(f"no máximo {MAX_MODELOS} modelos por vez")
    por_nome = {str(getattr(p, "name", "")).lower(): p for p in providers}
    desconhecidos = [n for n in pedidos if n not in por_nome]
    if desconhecidos:
        raise ComparadorError(
            "modelo(s) indisponível(is): " + ", ".join(desconhecidos)
        )
    return [por_nome[n] for n in pedidos]


async def _comparar_um(
    provider: Any, prompt: str, timeout_s: float
) -> dict[str, Any]:
    """Uma chamada, medida — falha e timeout são resultado, não exceção."""
    inicio = time.perf_counter()
    descricao = _descrever(provider)
    try:
        texto = await asyncio.wait_for(
            provider.generate(prompt), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        return {
            **descricao,
            "ok": False,
            "resposta": "",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000.0, 1),
            "erro": f"tempo esgotado em {timeout_s:g}s",
        }
    except Exception as exc:  # provider quebrado não derruba a comparação
        return {
            **descricao,
            "ok": False,
            "resposta": "",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000.0, 1),
            "erro": f"{type(exc).__name__}: {exc}",
        }
    return {
        **descricao,
        "ok": bool((texto or "").strip()),
        "resposta": (texto or "").strip(),
        "latencia_ms": round((time.perf_counter() - inicio) * 1000.0, 1),
        "erro": "" if (texto or "").strip() else "resposta vazia",
    }


async def comparar_async(
    prompt: str,
    nomes: Optional[Sequence[str]] = None,
    providers: Optional[Sequence[Any]] = None,
    timeout_s: float = TIMEOUT_PADRAO_S,
) -> dict[str, Any]:
    """Versão async (testes e chamadores dentro de event loop)."""
    texto = (prompt or "").strip()
    if not texto:
        raise ComparadorError("prompt vazio")
    if len(texto) > MAX_PROMPT:
        raise ComparadorError(f"prompt acima de {MAX_PROMPT} caracteres")
    cadeia = list(providers) if providers is not None else _provedores()
    selecionados = _selecionar(cadeia, nomes)
    if len(selecionados) < MIN_MODELOS:
        raise ComparadorError(
            f"menos de {MIN_MODELOS} modelos disponíveis para comparar"
        )
    resultados = await asyncio.gather(
        *(_comparar_um(p, texto, float(timeout_s)) for p in selecionados)
    )
    return {
        "ok": any(r["ok"] for r in resultados),
        "prompt": texto,
        "comparado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timeout_s": float(timeout_s),
        "modelos": list(resultados),
    }


def comparar(
    prompt: str,
    nomes: Optional[Sequence[str]] = None,
    providers: Optional[Sequence[Any]] = None,
    timeout_s: float = TIMEOUT_PADRAO_S,
) -> dict[str, Any]:
    """Versão síncrona para o handler HTTP (thread sem event loop)."""
    return asyncio.run(
        comparar_async(prompt, nomes=nomes, providers=providers, timeout_s=timeout_s)
    )
