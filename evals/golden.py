"""OMEGA DRAKON • EVALS • GOLDENS — carga e validação dos casos.

Golden = pergunta real × o que se espera da resposta, em JSONL
(`evals/goldens.jsonl`). Regras da casa aplicadas aqui na carga:
id único, modo/papel conhecidos, pelo menos uma expectativa e regex
que compila — erro de digitação em expectativa NUNCA passa em silêncio
(um campo desconhecido derruba a carga, não vira expectativa morta).

Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Modos de execução (mapeamento do Nômade → Omega Drakon):
#   oracle      — pipeline real com provider FALSO: só rotas
#                 determinísticas; sem rede, sem LLM, roda no CI.
#   e2e         — pipeline real + actions + LLM local: a prova de fogo.
#   noretrieval — mesmo e2e SEM ActionRegistry: isola o quanto as
#                 actions/retrieval contribuem (o LLM puro na linha).
MODOS_CONHECIDOS: tuple[str, ...] = ("oracle", "e2e", "noretrieval")
PAPEIS_CONHECIDOS: tuple[str, ...] = ("admin", "user", "anonymous")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CAMPOS_ESPERADOS = {
    "id", "pergunta", "papel", "profile", "modos", "esperado", "nota",
}
_CAMPOS_ESPERADOS_TAMANHO = {"rota", "llm", "llm_prefix", "contem",
                             "nao_contem", "regex",
                             "prompt_contem", "prompt_nao_contem"}


class GoldenInvalido(ValueError):
    """Golden malformado — a carga aborta, nunca ignora."""


@dataclass(frozen=True)
class Esperado:
    """Expectativas de uma resposta (todas opcionais, combináveis)."""

    rota: str | None = None          # ex.: "datetime", "action_intent"
    llm: bool | None = None          # False = NUNCA deve ir ao modelo
    llm_prefix: str | None = None    # ex.: "fastpath:math"
    contem: tuple[str, ...] = ()     # substrings OBRIGATÓRIAS (casefold)
    nao_contem: tuple[str, ...] = () # substrings PROIBIDAS (casefold)
    regex: tuple[str, ...] = ()      # padrões que devem casar na resposta
    # Parte B (RAG): o que deve (não) estar no PROMPT enviado ao modelo —
    # é o que prova, inclusive em modo oracle sem rede, que o contexto
    # recuperado (ou a visibilidade por papel) chegou (ou não) lá.
    prompt_contem: tuple[str, ...] = ()
    prompt_nao_contem: tuple[str, ...] = ()


@dataclass(frozen=True)
class Golden:
    """Um caso do exame padrão."""

    id: str
    pergunta: str
    papel: str = "user"
    profile: str = "guardian"
    modos: tuple[str, ...] = ("oracle",)
    esperado: Esperado = field(default_factory=Esperado)
    nota: str = ""


def _parse_esperado(linha: int, bruto: Any) -> Esperado:
    if not isinstance(bruto, dict) or not bruto:
        raise GoldenInvalido(
            f"linha {linha}: 'esperado' precisa ser objeto não vazio"
        )
    desconhecidos = set(bruto) - _CAMPOS_ESPERADOS_TAMANHO
    if desconhecidos:
        raise GoldenInvalido(
            f"linha {linha}: campo(s) de espera desconhecido(s): "
            f"{sorted(desconhecidos)} (válidos: {sorted(_CAMPOS_ESPERADOS_TAMANHO)})"
        )
    listas: dict[str, tuple[str, ...]] = {}
    for chave in ("contem", "nao_contem", "regex",
                  "prompt_contem", "prompt_nao_contem"):
        valor = bruto.get(chave, [])
        if isinstance(valor, str):
            valor = [valor]
        if not isinstance(valor, list) or not all(
            isinstance(v, str) and v for v in valor
        ):
            raise GoldenInvalido(f"linha {linha}: '{chave}' deve ser lista de textos")
        listas[chave] = tuple(valor)
    for padrao in listas["regex"]:
        try:
            re.compile(padrao)
        except re.error as exc:
            raise GoldenInvalido(f"linha {linha}: regex inválida {padrao!r}: {exc}") from exc
    rota = bruto.get("rota")
    llm = bruto.get("llm")
    llm_prefix = bruto.get("llm_prefix")
    if rota is not None and (not isinstance(rota, str) or not rota):
        raise GoldenInvalido(f"linha {linha}: 'rota' deve ser texto não vazio")
    if llm is not None and not isinstance(llm, bool):
        raise GoldenInvalido(f"linha {linha}: 'llm' deve ser true/false")
    if llm_prefix is not None and (not isinstance(llm_prefix, str) or not llm_prefix):
        raise GoldenInvalido(f"linha {linha}: 'llm_prefix' deve ser texto não vazio")
    esperado = Esperado(
        rota=rota,
        llm=llm,
        llm_prefix=llm_prefix,
        contem=listas["contem"],
        nao_contem=listas["nao_contem"],
        regex=listas["regex"],
        prompt_contem=listas["prompt_contem"],
        prompt_nao_contem=listas["prompt_nao_contem"],
    )
    if (
        esperado.rota is None
        and esperado.llm is None
        and esperado.llm_prefix is None
        and not esperado.contem
        and not esperado.nao_contem
        and not esperado.regex
        and not esperado.prompt_contem
        and not esperado.prompt_nao_contem
    ):
        raise GoldenInvalido(f"linha {linha}: golden sem nenhuma expectativa")
    return esperado


def _parse_golden(bruto: Any, linha: int) -> Golden:
    if not isinstance(bruto, dict):
        raise GoldenInvalido(f"linha {linha}: golden deve ser objeto JSON")
    desconhecidos = set(bruto) - _CAMPOS_ESPERADOS
    if desconhecidos:
        raise GoldenInvalido(
            f"linha {linha}: campo(s) desconhecido(s): {sorted(desconhecidos)} "
            f"(válidos: {sorted(_CAMPOS_ESPERADOS)})"
        )
    gid = bruto.get("id")
    pergunta = bruto.get("pergunta")
    if not isinstance(gid, str) or not _ID_RE.match(gid or ""):
        raise GoldenInvalido(
            f"linha {linha}: 'id' inválido (use minúsculas, dígitos, '-' ou '_'): {gid!r}"
        )
    if not isinstance(pergunta, str) or not pergunta.strip():
        raise GoldenInvalido(f"linha {linha}: 'pergunta' vazia")
    papel = bruto.get("papel", "user")
    if papel not in PAPEIS_CONHECIDOS:
        raise GoldenInvalido(
            f"linha {linha}: papel {papel!r} desconhecido (válidos: {PAPEIS_CONHECIDOS})"
        )
    profile = bruto.get("profile", "guardian")
    if not isinstance(profile, str) or not profile:
        raise GoldenInvalido(f"linha {linha}: 'profile' inválido")
    modos = bruto.get("modos", ["oracle"])
    if isinstance(modos, str):
        modos = [modos]
    if not isinstance(modos, list) or not modos:
        raise GoldenInvalido(f"linha {linha}: 'modos' deve ser lista não vazia")
    for modo in modos:
        if modo not in MODOS_CONHECIDOS:
            raise GoldenInvalido(
                f"linha {linha}: modo {modo!r} desconhecido (válidos: {MODOS_CONHECIDOS})"
            )
    nota = bruto.get("nota", "")
    if not isinstance(nota, str):
        raise GoldenInvalido(f"linha {linha}: 'nota' deve ser texto")
    return Golden(
        id=gid,
        pergunta=pergunta.strip(),
        papel=papel,
        profile=profile,
        modos=tuple(dict.fromkeys(modos)),  # dedup preservando ordem
        esperado=_parse_esperado(linha, bruto.get("esperado")),
        nota=nota,
    )


def carregar_goldens(caminho: Path | str | None = None) -> list[Golden]:
    """Carrega e valida o JSONL de goldens (padrão: evals/goldens.jsonl)."""
    if caminho is None:
        caminho = Path(__file__).parent / "goldens.jsonl"
    caminho = Path(caminho)
    if not caminho.exists():
        raise GoldenInvalido(f"arquivo de goldens não encontrado: {caminho}")
    goldens: list[Golden] = []
    vistos: set[str] = set()
    for numero, linha in enumerate(
        caminho.read_text(encoding="utf-8").splitlines(), start=1
    ):
        linha = linha.strip()
        if not linha or linha.startswith("//"):
            continue
        try:
            bruto = json.loads(linha)
        except json.JSONDecodeError as exc:
            raise GoldenInvalido(f"linha {numero}: JSON inválido: {exc}") from exc
        golden = _parse_golden(bruto, numero)
        if golden.id in vistos:
            raise GoldenInvalido(f"linha {numero}: id duplicado {golden.id!r}")
        vistos.add(golden.id)
        goldens.append(golden)
    if not goldens:
        raise GoldenInvalido(f"nenhum golden em {caminho}")
    return goldens


def goldens_do_modo(
    goldens: Iterable[Golden], modo: str
) -> list[Golden]:
    """Só os goldens que participam do modo pedido."""
    if modo not in MODOS_CONHECIDOS:
        raise GoldenInvalido(f"modo {modo!r} desconhecido (válidos: {MODOS_CONHECIDOS})")
    return [g for g in goldens if modo in g.modos]
