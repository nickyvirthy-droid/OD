"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/setup_frases_radio.py
Descrição: cria as 4 tabelas de frases da rádio Nicky no banco do OD e
           povoa as vazias com as frases do legado (idempotente —
           re-rodar nunca duplica; ver integrations/radio.py).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Uso:
    .venv/bin/python -m runtime.setup_frases_radio          # Postgres (OD_DB_URL)
    .venv/bin/python -m runtime.setup_frases_radio --db data/od.db   # SQLite

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import argparse
import os
import pathlib

from integrations.radio import TABELAS, garantir_frases
from storage import Database

__signature__ = "OD // CORE"

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Popula as frases da rádio Nicky (idempotente)."
    )
    parser.add_argument(
        "--db", default="", help="caminho SQLite (default: OD_DB_URL/Postgres)"
    )
    args = parser.parse_args(argv)

    if args.db:
        db = Database(args.db)
        fonte = args.db
    else:
        dsn = os.environ.get("OD_DB_URL", "")
        if not dsn:
            print("OD_DB_URL ausente — passe --db <sqlite> ou exporte a URL.")
            return 2
        db = Database(dsn=dsn)
        fonte = "Postgres (OD_DB_URL)"

    contagem = garantir_frases(db)
    db.close()
    print(f"Fonte: {fonte}")
    for tabela in TABELAS:
        print(f"  {tabela}: {contagem[tabela]} frase(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
