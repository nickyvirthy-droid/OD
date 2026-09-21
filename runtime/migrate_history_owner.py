"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/migrate_history_owner.py
Descrição: one-off — reatribui BALDES de histórico órfãos para a conta do dono.

Antes do login de usuários, cada transporte gravava o histórico no seu próprio
balde: o chat web em `web`, o streaming em `ws_user`, o app em `app`, o bot do
Telegram no id numérico do Telegram. Depois que a identidade passou a sair da
credencial (2026-09-20/21), esses baldes ficaram órfãos: a conta `alex` não
enxerga nada que foi conversado por eles.

Este script move as mensagens de um balde para outro SEM tocar no conteúdo:
`UPDATE conversation_messages SET user_id = ? WHERE user_id = ?` (o perfil de
cada conversa é preservado). É idempotente — rodado duas vezes, a segunda não
encontra nada no balde de origem.

Uso:
    .venv/bin/python -m runtime.migrate_history_owner                # dry-run
    .venv/bin/python -m runtime.migrate_history_owner --apply        # migra
    .venv/bin/python -m runtime.migrate_history_owner --de web --para alex --apply

Padrões (2026-09-21): `--de web,ws_user` → `--para alex`.

Baldes que NÃO entram por padrão, de propósito:
  - `app`  — o app Flutter manda `user_id: "app"` fixo: migrar agora voltaria
    a separar na próxima mensagem do celular. Migrar só depois que o app
    autenticar com sessão (mesma decisão de `não` para o Telegram abaixo).
  - `660518870` (Telegram) — o bot identifica a pessoa pelo id do Telegram; o
    balde volta a nascer na próxima mensagem do bot.
  - `deploy-check*` — mensagens sintéticas de prova de deploy, não conversa.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any, Iterable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.runtime.migrate_history")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_ORIGINS = ("web", "ws_user")
DEFAULT_TARGET = "alex"
BACKUP_DIR = REPO_ROOT / "backups"


def _buckets(db: Any, user_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Contagem por (user_id, profile) dos baldes indicados (ordem alfabética)."""
    ids = list(user_ids)
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    return db.query(
        "SELECT user_id, profile, COUNT(*) AS mensagens, MIN(ts) AS primeira, "
        "MAX(ts) AS ultima FROM conversation_messages "
        f"WHERE user_id IN ({placeholders}) GROUP BY user_id, profile "
        "ORDER BY user_id, profile",
        tuple(ids),
    )


def _stats(db: Any, user_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Totais por `user_id` (para o antes/depois)."""
    ids = list(user_ids)
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    return db.query(
        "SELECT user_id, COUNT(*) AS mensagens FROM conversation_messages "
        f"WHERE user_id IN ({placeholders}) GROUP BY user_id ORDER BY user_id",
        tuple(ids),
    )


def plan(db: Any, origins: Iterable[str], target: str) -> dict[str, Any]:
    """O que a migração faria — sem escrever nada."""
    origins = [o for o in origins if o and o != target]
    return {
        "de": origins,
        "para": target,
        "baldes": _buckets(db, origins),
        "total_a_mover": sum(int(b["mensagens"]) for b in _buckets(db, origins)),
        "destino_antes": _stats(db, [target]),
    }


def apply(
    db: Any,
    origins: Iterable[str],
    target: str,
    *,
    backup_dir: Optional[pathlib.Path] = BACKUP_DIR,
) -> dict[str, Any]:
    """Migra os baldes e devolve o relatório. Snapshot antes; transação única."""
    origins = [o for o in origins if o and o != target]
    baldes = _buckets(db, origins)
    if not baldes:
        return {"de": origins, "para": target, "movidas": 0, "baldes": [],
                "snapshot": None, "nada_a_fazer": True}

    snapshot: Optional[pathlib.Path] = None
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot = backup_dir / f"history-owner-{time.strftime('%Y%m%d-%H%M%S')}.bak"
        # Só o necessário para desfazer: as chaves afetadas saem do relatório,
        # e este arquivo guarda os ids para o rollback (o conteúdo não muda).
        snapshot.write_text(
            json.dumps(
                {
                    "motivo": "migração de baldes de histórico órfãos",
                    "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "de": origins,
                    "para": target,
                    "baldes": baldes,
                    "rollback": [
                        f"UPDATE conversation_messages SET user_id = '{b['user_id']}' "
                        f"WHERE user_id = '{target}' AND profile = '{b['profile']}'"
                        for b in baldes
                    ],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    movidas: list[dict[str, Any]] = []
    with db.transaction():
        for balde in baldes:
            n = db.execute(
                "UPDATE conversation_messages SET user_id = ? "
                "WHERE user_id = ? AND profile = ?",
                (target, balde["user_id"], balde["profile"]),
            )
            movidas.append({"de": balde["user_id"], "profile": balde["profile"], "mensagens": n})
            log.info(
                "Balde migrado",
                de=balde["user_id"], profile=balde["profile"],
                para=target, mensagens=n,
            )

    return {
        "de": origins,
        "para": target,
        "movidas": sum(int(m["mensagens"]) for m in movidas),
        "baldes": movidas,
        "snapshot": str(snapshot) if snapshot else None,
        "destino": _stats(db, [target]),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migra baldes de histórico órfãos para a conta do dono."
    )
    parser.add_argument("--de", default=",".join(DEFAULT_ORIGINS),
                        help=f"baldes de origem, separados por vírgula (default: {','.join(DEFAULT_ORIGINS)})")
    parser.add_argument("--para", default=DEFAULT_TARGET,
                        help=f"conta de destino (default: {DEFAULT_TARGET})")
    parser.add_argument("--apply", action="store_true",
                        help="executa de verdade (sem isso é só dry-run)")
    args = parser.parse_args(argv)

    origins = [o.strip() for o in args.de.split(",") if o.strip()]
    # Import tardio: o .env (OD_DB_URL) é lido pelo launcher, não pelo script.
    from runtime.launcher import env
    from storage import Database

    db = Database(dsn=env("OD_DB_URL", ""), pool_size=3)
    try:
        antes = plan(db, origins, args.para)
        print(f"banco: {db.backend} | destino: {args.para}")
        if not antes["baldes"]:
            print(f"nada a migrar em {origins} (já migrado?)")
            return 0
        print("baldes encontrados:")
        for b in antes["baldes"]:
            print(f"  {b['user_id']:>12} / {b['profile']:<10} "
                  f"{int(b['mensagens']):>3} msgs")
        print(f"total a mover: {antes['total_a_mover']}")
        if not args.apply:
            print("\n(dry-run — rode com --apply para migrar)")
            return 0
        relatorio = apply(db, origins, args.para)
        print(f"\nmovidas: {relatorio['movidas']} mensagens"
              f" | snapshot: {relatorio['snapshot']}")
        print("destino agora:", relatorio["destino"])
        restante = _buckets(db, origins)
        print("resíduo na origem:", restante or "nenhum")
        return 0 if not restante else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
