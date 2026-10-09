"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/registry.py
Descrição: Registro Mestre de peças físicas (tabela registry_items) —
           autenticidade pública verificável + posse por QR (item 2 da
           pauta de divergências, 2026-10-09).

Modelo (decisões do dono, 09/10):
- Toda peça tem um ID PESQUISÁVEL por qualquer um (a pessoa está com a
  PEÇA na mão, não com o cartão): public_id canônico OD-PROD-AAAA-NNNN
  + código curto gravado (engraved_code, ex.: NV-ABI-7F3A).
- Consulta pública mostra o USERNAME de quem registrou (não o nome
  real) — prova de que tem dono, sem expor dados privados.
- QR = símbolo de propriedade (entregue na compra; quem tem é o dono).
  A gravação/entrega do QR vem numa etapa posterior; este módulo guarda
  o banco e a consulta.
- Peças públicas (chaveiros etc.): kind=publica, sem QR/registro de dono.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import time
from typing import Any, Optional

from storage import Database

__signature__ = "OD // CORE"

REGISTRY_ITEMS_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "public_id": "TEXT UNIQUE NOT NULL",      # OD-PROD-2026-0001 (pesquisável)
    "engraved_code": "TEXT UNIQUE",           # código curto gravado na peça
    "name": "TEXT NOT NULL",
    "collection": "TEXT",                     # ex.: ABISSAL, DRAKONIS, LUMEN NOX
    "kind": "TEXT NOT NULL",                  # exclusiva | publica
    "status": "TEXT NOT NULL",                # estoque | vendida | registrada
    "price_brl": "REAL",                      # só o dono do sistema vê
    "owner_username": "TEXT",                 # username público do registrante
    "notes": "TEXT",                          # internas — nunca públicas
    "created_at": "REAL NOT NULL",
    "sold_at": "REAL",
    "registered_at": "REAL",
}

KINDS = ("exclusiva", "publica")
STATUSES = ("estoque", "vendida", "registrada")

# Campos que NUNCA saem na consulta pública (preço, anotações, PK interna).
_PRIVATE_FIELDS = frozenset({"id", "price_brl", "notes"})

# Campos aceitos no update administrativo (whitelist — nunca id/public_id).
_UPDATABLE = frozenset({
    "name", "collection", "kind", "status", "price_brl",
    "owner_username", "notes", "engraved_code", "sold_at", "registered_at",
})


class RegistryStore:
    """Registro Mestre de peças sobre o Database do sistema."""

    def __init__(self, database: Database) -> None:
        self._db = database
        database.create_table("registry_items", REGISTRY_ITEMS_SCHEMA)

    # ------------------------------------------------------------------#
    # Identificação                                                      #
    # ------------------------------------------------------------------#
    def _next_public_id(self) -> str:
        """Próximo ID canônico do ano corrente: OD-PROD-AAAA-NNNN."""
        year = time.localtime().tm_year
        prefix = f"OD-PROD-{year}-"
        seq = 0
        for row in self._db.query(
            "SELECT public_id FROM registry_items WHERE public_id LIKE ?",
            (prefix + "%",),
        ):
            tail = str(row.get("public_id") or "").rsplit("-", 1)[-1]
            if tail.isdigit():
                seq = max(seq, int(tail))
        return f"{prefix}{seq + 1:04d}"

    # ------------------------------------------------------------------#
    # CRUD (admin)                                                       #
    # ------------------------------------------------------------------#
    def create(
        self,
        *,
        name: str,
        kind: str,
        collection: Optional[str] = None,
        engraved_code: Optional[str] = None,
        price_brl: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Cadastra uma peça nova (estado inicial: estoque)."""
        name = str(name or "").strip()
        if not name:
            raise ValueError("nome_obrigatorio")
        kind = str(kind or "").strip().lower()
        if kind not in KINDS:
            raise ValueError("kind_invalido")
        code = (str(engraved_code).strip().upper() or None) if engraved_code else None
        if code is not None and self.get(code) is not None:
            raise ValueError("codigo_duplicado")
        row = {
            "public_id": self._next_public_id(),
            "engraved_code": code,
            "name": name,
            "collection": (str(collection).strip().upper() or None) if collection else None,
            "kind": kind,
            "status": "estoque",
            "price_brl": float(price_brl) if price_brl is not None else None,
            "owner_username": None,
            "notes": str(notes) if notes else None,
            "created_at": time.time(),
            "sold_at": None,
            "registered_at": None,
        }
        self._db.execute(
            "INSERT INTO registry_items (public_id, engraved_code, name, "
            "collection, kind, status, price_brl, owner_username, notes, "
            "created_at, sold_at, registered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["public_id"], row["engraved_code"], row["name"],
                row["collection"], row["kind"], row["status"], row["price_brl"],
                row["owner_username"], row["notes"], row["created_at"],
                row["sold_at"], row["registered_at"],
            ),
        )
        return dict(row)

    def get(self, codigo: str) -> Optional[dict[str, Any]]:
        """Busca por public_id OU código gravado (normalizado maiúsculas)."""
        cod = str(codigo or "").strip().upper()
        if not cod:
            return None
        rows = self._db.query(
            "SELECT * FROM registry_items WHERE public_id = ? OR engraved_code = ?",
            (cod, cod),
        )
        return dict(rows[0]) if rows else None

    def list_all(self) -> list[dict[str, Any]]:
        """Lista completa (admin — inclui preço e notas)."""
        return [dict(r) for r in self._db.query(
            "SELECT * FROM registry_items ORDER BY id"
        )]

    def update(self, codigo: str, **fields: Any) -> Optional[dict[str, Any]]:
        """Atualiza campos permitidos (whitelist) e coerência de estados.

        `codigo` identifica a peça (public_id ou engraved_code); campos
        fora da whitelist (id, public_id) são ignorados — nunca mudam.
        """
        item = self.get(codigo)
        if item is None:
            return None
        sets: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in _UPDATABLE:
                continue
            if key == "kind":
                value = str(value or "").strip().lower()
                if value not in KINDS:
                    raise ValueError("kind_invalido")
            if key == "status":
                value = str(value or "").strip().lower()
                if value not in STATUSES:
                    raise ValueError("status_invalido")
                # Coerência: registrar exige dono (username).
                if value == "registrada" and not (
                    fields.get("owner_username") or item.get("owner_username")
                ):
                    raise ValueError("registrada_sem_dono")
            if key == "engraved_code" and value:
                value = str(value).strip().upper()
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return item
        params.append(item["public_id"])
        self._db.execute(
            f"UPDATE registry_items SET {', '.join(sets)} WHERE public_id = ?",
            tuple(params),
        )
        return self.get(item["public_id"])

    # ------------------------------------------------------------------#
    # Consulta pública                                                   #
    # ------------------------------------------------------------------#
    def verify_public(self, codigo: str) -> Optional[dict[str, Any]]:
        """Projeção PÚBLICA de uma peça: nunca expõe preço/notas/PK."""
        item = self.get(codigo)
        if item is None:
            return None
        public = {k: v for k, v in item.items() if k not in _PRIVATE_FIELDS}
        # Username só aparece quando a peça foi registrada (comprador dono).
        if item.get("status") != "registrada":
            public["owner_username"] = None
        public["registered"] = item.get("status") == "registrada"
        return public
