"""OMEGA DRAKON • EVALS • AVALIAÇÃO — compara resposta × expectativa.

Funções PURAS (sem I/O, sem rede, sem estado): recebem o resultado do
pipeline e devolvem a lista de problemas (vazia = passou). É o coração
testável do eval — mutação nele é pega pela suíte.

Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from evals.golden import Esperado, Golden

# Rotas que significam "o MODELO respondeu" (cache também: é resposta
# de modelo, guardada — avaliar como sem-LLM seria mentir da métrica).
_ROTAS_DE_LLM = frozenset({"llm", "fallback", "cache"})
_MAX_RESPOSTA = 400


@dataclass
class Resultado:
    """Resultado de um golden numa rodada."""

    id: str
    ok: bool
    problemas: list[str] = field(default_factory=list)
    rota: str = ""
    llm_used: str = ""
    latencia_ms: float = 0.0
    resposta: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ok": self.ok,
            "problemas": self.problemas,
            "rota": self.rota,
            "llm_used": self.llm_used,
            "latencia_ms": round(self.latencia_ms, 1),
            "resposta": self.resposta,
        }


def usou_llm(rota: str, llm_used: str) -> bool:
    """True quando a resposta veio do modelo (ou do cache dele).

    As rotas fastpath (`fastpath:*`) são determinísticas SEM modelo —
    por isso são as únicas com `llm_used` preenchido que contam como
    "sem LLM".
    """
    if rota in _ROTAS_DE_LLM:
        return True
    return bool(llm_used) and not llm_used.startswith("fastpath:")


def avaliar(
    golden: Golden,
    *,
    rota: str,
    mensagem: str,
    llm_used: str,
) -> list[str]:
    """Aplica as expectativas do golden. Lista vazia = passou."""
    esp: Esperado = golden.esperado
    problemas: list[str] = []
    texto = mensagem or ""

    if esp.rota is not None and rota != esp.rota:
        problemas.append(f"rota esperada {esp.rota!r}, veio {rota!r}")

    if esp.llm is False and usou_llm(rota, llm_used):
        problemas.append(
            f"não deveria ir ao LLM (rota {rota!r}, llm_used {llm_used!r})"
        )
    if esp.llm is True and not usou_llm(rota, llm_used):
        problemas.append(
            f"esperava resposta do LLM (rota {rota!r}, llm_used {llm_used!r})"
        )

    if esp.llm_prefix is not None and not llm_used.startswith(esp.llm_prefix):
        problemas.append(
            f"llm_used deveria começar com {esp.llm_prefix!r}, veio {llm_used!r}"
        )

    baixo = texto.casefold()
    for obrigatoria in esp.contem:
        if obrigatoria.casefold() not in baixo:
            problemas.append(f"resposta não contém {obrigatoria!r}")
    for proibida in esp.nao_contem:
        if proibida.casefold() in baixo:
            problemas.append(f"resposta contém texto proibido {proibida!r}")
    for padrao in esp.regex:
        if not re.search(padrao, texto):
            problemas.append(f"resposta não casa /{padrao}/")

    return problemas


def resultado_de(
    golden: Golden,
    *,
    rota: str,
    mensagem: str,
    llm_used: str,
    latencia_ms: float,
) -> Resultado:
    """Avalia e monta o Resultado (truncando a resposta no relatório)."""
    problemas = avaliar(golden, rota=rota, mensagem=mensagem, llm_used=llm_used)
    return Resultado(
        id=golden.id,
        ok=not problemas,
        problemas=problemas,
        rota=rota,
        llm_used=llm_used,
        latencia_ms=latencia_ms,
        resposta=(mensagem or "")[:_MAX_RESPOSTA],
    )
