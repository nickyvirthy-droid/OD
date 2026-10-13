"""OMEGA DRAKON • EVALS • CLI — `python -m evals`.

Uso (raiz do repositório, no .venv):

    python -m evals                      # modo oracle (padrão, CI-safe)
    python -m evals --modo e2e           # pipeline real + LLM local
    python -m evals --modo noretrieval   # LLM puro, sem actions
    python -m evals --modo todos         # um relatório por modo
    python -m evals --comparar           # antes/depois contra a baseline
    python -m evals --atualizar-baseline # grava a nota atual como baseline

Sai com código 1 quando algum golden falha (gate amigável para CI/scripts).

Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.golden import MODOS_CONHECIDOS, carregar_goldens
from evals.runner import (
    carregar_baseline,
    comparar,
    gravar_baseline,
    rodar_modo,
)


def _resumo(relatorio: dict) -> str:
    linhas = [
        f"Modo {relatorio['modo']}: {relatorio['passaram']}/{relatorio['total']} "
        f"({relatorio['nota']:.0%}) — {relatorio['data']}"
    ]
    for r in relatorio["resultados"]:
        marca = "✅" if r["ok"] else "❌"
        linhas.append(f"  {marca} {r['id']}: {r['rota'] or '-'} ({r['llm_used'] or 'sem LLM'})")
        for problema in r["problemas"]:
            linhas.append(f"       → {problema}")
    return "\n".join(linhas)


def _resumo_comparativo(diff: dict) -> str:
    if diff.get("sem_baseline"):
        return f"Sem baseline ainda — nota atual {diff['nota_depois']:.0%}."
    linhas = [
        f"Baseline {diff['nota_antes']:.0%} → atual {diff['nota_depois']:.0%}"
    ]
    if diff["melhorou"]:
        linhas.append(f"  ▲ melhoraram: {', '.join(diff['melhorou'])}")
    if diff["piorou"]:
        linhas.append(f"  ▼ pioraram: {', '.join(diff['piorou'])}")
    if diff["novo"]:
        linhas.append(f"  + novos: {', '.join(diff['novo'])}")
    if diff["removido"]:
        linhas.append(f"  − fora da baseline: {', '.join(diff['removido'])}")
    if not any(diff[k] for k in ("melhorou", "piorou", "novo", "removido")):
        linhas.append("  = nada mudou")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="Exame padrão do assistente (Parte A — eval NOMAD).",
    )
    parser.add_argument(
        "--modo",
        choices=[*MODOS_CONHECIDOS, "todos"],
        default="oracle",
        help="modo de execução (padrão: oracle)",
    )
    parser.add_argument("--goldens", type=Path, default=None, help="caminho alternativo do JSONL")
    parser.add_argument("--comparar", action="store_true", help="compara com a baseline versionada")
    parser.add_argument(
        "--atualizar-baseline",
        action="store_true",
        help="grava o relatório atual como baseline",
    )
    parser.add_argument("--saida", type=Path, default=None, help="grava o relatório JSON em PATH")
    parser.add_argument("--json", action="store_true", help="imprime o relatório em JSON no stdout")
    args = parser.parse_args(argv)

    modos = list(MODOS_CONHECIDOS) if args.modo == "todos" else [args.modo]
    goldens = carregar_goldens(args.goldens)
    relatorios = [rodar_modo(modo, goldens) for modo in modos]

    falhas = 0
    for relatorio in relatorios:
        falhas += relatorio["total"] - relatorio["passaram"]
        if args.json:
            print(json.dumps(relatorio, ensure_ascii=False, indent=2))
        else:
            print(_resumo(relatorio))
            if args.comparar:
                print(
                    _resumo_comparativo(
                        comparar(relatorio, carregar_baseline(relatorio["modo"]))
                    )
                )

    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        payload = relatorios[0] if len(relatorios) == 1 else {"relatorios": relatorios}
        args.saida.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Relatório gravado em {args.saida}")

    if args.atualizar_baseline:
        if len(relatorios) != 1:
            print("--atualizar-baseline exige um modo só (não 'todos')", file=sys.stderr)
            return 2
        caminho = gravar_baseline(relatorios[0])
        print(f"Baseline gravada em {caminho}")

    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
