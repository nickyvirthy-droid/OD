"""OMEGA DRAKON • EVALS • BENCHMARKS — o placar único do CI (R5).

Junta os dois tipos de exame que o projeto tem:

* **respostas** — `evals.runner` (goldens de rota/conteúdo/prompt, modo
  oracle, sem rede). É o benchmark CUSTOMIZADO do OD: perguntas reais do
  dono com a resposta esperada, incluindo os casos de alucinação que já
  derrubaram o sistema.
* **memoria** — `evals.locomo` (subset LOCOMO de memória de longa duração,
  recall@1/@5 e falsos positivos). Mede a fundação da resposta: ainda sei
  o fato certo depois de 69 turnos?

Uso (CI e mão):

    python -m evals.benchmarks            # mede e aplica o gate
    python -m evals.benchmarks --json     # relatório completo
    python -m evals.benchmarks --sem-gate # só mede
    python -m evals.benchmarks --atualizar-baseline

Sai com código 1 quando algum benchmark falha — é o passo de CI em
`.github/workflows/ci.yml`. Nada aqui escreve em produção nem toca rede.

Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from evals import locomo

BENCHMARKS: tuple[str, ...] = ("respostas", "memoria")


def _bench_respostas() -> dict[str, Any]:
    """Goldens do modo oracle (sem rede, sem LLM)."""
    from evals.runner import carregar_baseline as baseline_goldens
    from evals.runner import comparar, rodar_modo

    relatorio = rodar_modo("oracle")
    diff = comparar(relatorio, baseline_goldens("oracle"))
    return {
        "nome": "respostas",
        "fonte": "evals/goldens.jsonl (modo oracle)",
        "total": relatorio["total"],
        "passaram": relatorio["passaram"],
        "nota": relatorio["nota"],
        "quebrados": [r["id"] for r in relatorio["resultados"] if not r["ok"]],
        "comparacao": diff,
    }


def _bench_memoria() -> dict[str, Any]:
    """Subset LOCOMO de memória de longa duração."""
    relatorio = locomo.rodar_locomo()
    return {
        "nome": "memoria",
        "fonte": f"evals/{relatorio['subset']}",
        "conversas": relatorio["conversas"],
        "turnos": relatorio["turnos"],
        "perguntas": relatorio["perguntas"],
        "modos": {
            modo: {
                "recall@1": dados["recall@1"],
                "recall@5": dados["recall@5"],
                "mrr": dados["mrr"],
                "falsos_positivos": dados["falsos_positivos"],
                "por_tipo": dados["por_tipo"],
            }
            for modo, dados in relatorio["modos"].items()
        },
        "_relatorio": relatorio,
    }


_RUNNERS = {"respostas": _bench_respostas, "memoria": _bench_memoria}


def rodar(nomes: tuple[str, ...] = BENCHMARKS) -> dict[str, Any]:
    """Roda os benchmarks pedidos e devolve o placar."""
    suites: dict[str, Any] = {}
    for nome in nomes:
        if nome not in _RUNNERS:
            raise SystemExit(f"benchmark {nome!r} desconhecido (válidos: {BENCHMARKS})")
        suites[nome] = _RUNNERS[nome]()
    return {
        "data": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "suites": suites,
    }


def verificar(placar: dict[str, Any]) -> list[str]:
    """Problemas do placar (vazio = verde). Cada suite tem seu critério."""
    problemas: list[str] = []
    respostas = placar["suites"].get("respostas")
    if respostas:
        if respostas["quebrados"]:
            problemas.append(
                "respostas: goldens quebrados: " + ", ".join(respostas["quebrados"])
            )
        comparacao = respostas.get("comparacao") or {}
        if comparacao.get("piorou"):
            problemas.append(
                "respostas: regrediram em relação à baseline: "
                + ", ".join(comparacao["piorou"])
            )
    memoria = placar["suites"].get("memoria")
    if memoria:
        problemas.extend(
            f"memoria/{p}" for p in locomo.verificar(
                memoria["_relatorio"], locomo.carregar_baseline()
            )
        )
    return problemas


def _resumo(placar: dict[str, Any]) -> str:
    linhas = [f"Benchmarks — {placar['data']}"]
    respostas = placar["suites"].get("respostas")
    if respostas:
        linhas.append(
            f"  respostas  {respostas['passaram']}/{respostas['total']} "
            f"({respostas['nota']:.0%}) — goldens oracle"
        )
    memoria = placar["suites"].get("memoria")
    if memoria:
        modos = " · ".join(
            f"{modo} recall@5 {dados['recall@5']:.0%}"
            for modo, dados in memoria["modos"].items()
        )
        linhas.append(
            f"  memoria    {memoria['conversas']} conversas / "
            f"{memoria['perguntas']} perguntas — {modos}"
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.benchmarks",
        description="Placar dos benchmarks do OD (R5) — CI-safe.",
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=list(BENCHMARKS),
        default=None,
        help="roda só as suites indicadas (padrão: todas)",
    )
    parser.add_argument("--json", action="store_true", help="placar em JSON")
    parser.add_argument(
        "--sem-gate", action="store_true", help="só mede (não falha o processo)"
    )
    parser.add_argument(
        "--atualizar-baseline", action="store_true", help="regrava a baseline LOCOMO"
    )
    args = parser.parse_args(argv)

    nomes = tuple(args.suite) if args.suite else BENCHMARKS
    placar = rodar(nomes)
    problemas = verificar(placar)

    if args.json:
        print(json.dumps(placar, ensure_ascii=False, indent=2, default=str))
    else:
        print(_resumo(placar))
        for problema in problemas:
            print(f"  ✗ {problema}")

    if args.atualizar_baseline:
        memoria = placar["suites"].get("memoria")
        if memoria is None:
            print("--atualizar-baseline exige a suite memoria", file=sys.stderr)
            return 2
        caminho = locomo.gravar_baseline(memoria["_relatorio"])
        print(f"Baseline LOCOMO gravada em {caminho}")

    return 0 if args.sem_gate or not problemas else 1


if __name__ == "__main__":
    raise SystemExit(main())
