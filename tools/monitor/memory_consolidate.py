#!/usr/bin/env python3
"""
OMEGA DRAKON • TOOLS
Módulo: tools/monitor/memory_consolidate.py
Descrição: Consolidação periódica da memória longa (F4 fase 3): deduplica
           fatos repetidos e aposenta os efêmeros vencidos. Roda pelo timer
           `od-memory-consolidate` (semanal) e é seguro rodar à mão.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F4 (fase 3: consolidação)
  - core/memory_layer.py (MemoryGraph.consolidar)

Uso:
    python tools/monitor/memory_consolidate.py            # todos os usuários
    python tools/monitor/memory_consolidate.py --dry-run  # só o stats, sem mexer
    OD_MEMORY_PATH=/caminho/mem.db python ... --user alex
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core.memory_layer import MemoryGraph, MemoryLayerError, obter_memoria  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consolidação da memória longa")
    parser.add_argument("--user", default="", help="só este usuário (padrão: todos)")
    parser.add_argument(
        "--dry-run", action="store_true", help="mostra o estado sem consolidar"
    )
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args(argv)

    try:
        memoria = obter_memoria()
    except MemoryLayerError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    antes = memoria.stats(args.user or None)
    if args.dry_run:
        dados = {"antes": antes, "consolidado": None, "depois": antes}
    else:
        resultado = memoria.consolidar(args.user or None)
        dados = {"antes": antes, "consolidado": resultado, "depois": memoria.stats(args.user or None)}

    if args.json:
        print(json.dumps(dados, ensure_ascii=False, indent=2))
    else:
        print(
            f"memoria: antes fatos={antes['fatos']} ativos={antes['ativos']} "
            f"efemeros={antes['efemeros']} expirados={antes['expirados']}"
        )
        if dados["consolidado"]:
            c = dados["consolidado"]
            print(
                f"consolidacao: duplicados={c['duplicados']} expirados={c['expirados']} "
                f"usuarios={c['usuarios']}"
            )
            d = dados["depois"]
            print(
                f"depois: ativos={d['ativos']} substituidos={d['substituidos']} "
                f"expirados={d['expirados']}"
            )
        else:
            print("dry-run: nada foi alterado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
