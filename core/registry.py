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

Evolução 1.23.0 (mesmo dia, pedido do dono "vamos melhorar"):
- Busca TOLERANTE A HÍFEN: digitar "odprod20260001" ou "nvabi7f3a"
  acha a peça igual (comparação normalizada, sem separadores).
- FOTO do produto: arquivo em photo_dir/{public_id}.{jpg|png|webp},
  servida publicamente por GET /registry/{codigo}/photo; o payload
  público traz a URL quando existe.
- SALA DE BATE-PAPO por peça: tabela registry_chat — interessados
  conversam com quem tem a peça (estoque → dono do sistema; registrada →
  @dono). Leitura pública, escrita só com conta (username), moderação
  pelo admin. Avisos ao dono no Telegram (com cooldown por peça).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import re
import time
from pathlib import Path
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
    "photo": "TEXT",                          # nome do arquivo da foto (ou None)
    "created_at": "REAL NOT NULL",
    "sold_at": "REAL",
    "registered_at": "REAL",
}

# Sala de bate-papo da peça (leitura pública / escrita com conta).
REGISTRY_CHAT_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "public_id": "TEXT NOT NULL",
    "username": "TEXT NOT NULL",
    "text": "TEXT NOT NULL",
    "created_at": "REAL NOT NULL",
}

KINDS = ("exclusiva", "publica")
STATUSES = ("estoque", "vendida", "registrada")

# Limites (foto chega em base64 JSON; texto é mensagem de bate-papo).
PHOTO_MAX_BYTES = 6 * 1024 * 1024          # 6 MB de binário decodificado
PHOTO_MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
CHAT_TEXT_MAX = 2000
CHAT_PAGE_LIMIT = 200

# Campos que NUNCA saem na consulta pública (preço, anotações, PK interna).
_PRIVATE_FIELDS = frozenset({"id", "price_brl", "notes"})

# Campos aceitos no update administrativo (whitelist — nunca id/public_id).
_UPDATABLE = frozenset({
    "name", "collection", "kind", "status", "price_brl",
    "owner_username", "notes", "engraved_code", "sold_at", "registered_at",
})


def normalize_code(codigo: str) -> str:
    """Normaliza um código para busca tolerante: maiúsculas sem separadores.

    "od-prod-2026-0001", "OD PROD 2026 0001" e "odprod20260001" viram o
    mesmo alvo — a pessoa muitas vezes lê o número gravado e re-digita
    sem os hífens.
    """
    return re.sub(r"[^A-Z0-9]", "", str(codigo or "").upper())


class RegistryStore:
    """Registro Mestre de peças sobre o Database do sistema."""

    def __init__(self, database: Database, photo_dir: Optional[Path] = None) -> None:
        self._db = database
        self._photo_dir = Path(photo_dir) if photo_dir else None
        database.create_table("registry_items", REGISTRY_ITEMS_SCHEMA)
        database.create_table("registry_chat", REGISTRY_CHAT_SCHEMA)
        # Migração da coluna photo: a tabela nasceu antes dela (1.23.0) e
        # create_table é IF NOT EXISTS — sozinho não adiciona coluna nova.
        self._ensure_column("registry_items", "photo", "TEXT")
        if self._photo_dir is not None:
            self._photo_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_column(self, table: str, column: str, type_sql: str) -> None:
        cols = {str(c.get("name") or c.get("column_name") or "")
                for c in self._db.table_info(table)}
        if column not in cols:
            self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")

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
        """Busca por public_id OU código gravado — tolerante a hífens.

        Primeiro tenta exato (rápido, índice UNIQUE); sem match, compara
        a versão NORMALIZADA (maiúsculas, sem separadores) de todos os
        cadastros — "odprod20260001" e "NVABI7F3A" acham a peça.
        """
        cod = str(codigo or "").strip().upper()
        if not cod:
            return None
        rows = self._db.query(
            "SELECT * FROM registry_items WHERE public_id = ? OR engraved_code = ?",
            (cod, cod),
        )
        if rows:
            return dict(rows[0])
        alvo = normalize_code(cod)
        if not alvo:
            return None
        for row in self._db.query("SELECT * FROM registry_items"):
            if alvo in (normalize_code(row.get("public_id")),
                        normalize_code(row.get("engraved_code"))):
                return dict(row)
        return None

    def list_all(self) -> list[dict[str, Any]]:
        """Lista completa (admin — inclui preço e notas)."""
        return [dict(r) for r in self._db.query(
            "SELECT * FROM registry_items ORDER BY id"
        )]

    def delete(self, codigo: str) -> bool:
        """Remove uma peça (admin — limpeza de cadastros de teste).

        Leva junto a foto (arquivo) e a sala de bate-papo da peça.

        Returns:
            True se removeu; False se o código não existe.
        """
        item = self.get(codigo)
        if item is None:
            return False
        self._db.execute(
            "DELETE FROM registry_items WHERE public_id = ?",
            (item["public_id"],),
        )
        self._db.execute(
            "DELETE FROM registry_chat WHERE public_id = ?",
            (item["public_id"],),
        )
        path = self._photo_file(item)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def update(self, codigo: str, **fields: Any) -> Optional[dict[str, Any]]:
        """Atualiza campos permitidos (whitelist) e coerência de estados.

        `codigo` identifica a peça (public_id ou engraved_code); campos
        fora da whitelist (id, public_id) são ignorados — nunca mudam.

        Transições (pedido do dono, 09/10):
        - vendida → estoque = DESFAZER VENDA (o comprador desistiu antes
          de concluir): volta para o estoque e o carimbo sold_at é
          apagado — a peça não foi vendida de verdade.
        - registrada → qualquer coisa ABAIXO é bloqueada por enquanto:
          desfazer o registro depende do código exclusivo e secreto da
          peça (sistema do QR), que ainda vai nascer. O dono tratou de
          deixar isso para depois — o bloqueio impede apagamento acidental
          de posse sem a prova secreta.
        """
        item = self.get(codigo)
        if item is None:
            return None
        novo_status = fields.get("status")
        if isinstance(novo_status, str):
            novo_status = novo_status.strip().lower()
        # Posse registrada só cai com o código secreto da peça (futuro).
        if item.get("status") == "registrada" and novo_status in (
            "estoque", "vendida",
        ):
            raise ValueError("registro_pendente_codigo_secreto")
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
        # Coerência de tempo: a transição grava o carimbo sozinha.
        if novo_status == "vendida" and not item.get("sold_at") \
                and not fields.get("sold_at"):
            sets.append("sold_at = ?")
            params.append(time.time())
        elif novo_status == "registrada" and not item.get("registered_at") \
                and not fields.get("registered_at"):
            sets.append("registered_at = ?")
            params.append(time.time())
        elif novo_status == "estoque" and item.get("status") != "estoque":
            # Desfazer venda: a peça nunca saiu de fato — apaga os
            # carimbos de venda/registro junto (nada de estoque "vendido").
            sets.append("sold_at = NULL")
            sets.append("registered_at = NULL")
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
        # Foto: o público recebe a URL de serviço, nunca o nome do arquivo.
        public["photo"] = (
            f"/registry/{item['public_id']}/photo" if item.get("photo") else None
        )
        return public

    # ------------------------------------------------------------------#
    # Foto do produto                                                    #
    # ------------------------------------------------------------------#
    def _photo_file(self, item: dict[str, Any]) -> Optional[Path]:
        """Arquivo da foto de uma peça (None se sem foto ou sem diretório)."""
        if self._photo_dir is None or not item.get("photo"):
            return None
        return self._photo_dir / str(item["photo"])

    def save_photo(self, codigo: str, data: bytes, mime: str) -> Optional[str]:
        """Grava/substitui a foto da peça. Retorna o nome do arquivo.

        Raises:
            ValueError: peça inexistente, mime não suportado ou grande demais.
        """
        item = self.get(codigo)
        if item is None:
            raise ValueError("peca_inexistente")
        if self._photo_dir is None:
            raise ValueError("foto_indisponivel")
        mime = str(mime or "").strip().lower()
        ext = PHOTO_MIME_EXT.get(mime)
        if ext is None:
            raise ValueError("formato_invalido")
        if len(data) > PHOTO_MAX_BYTES:
            raise ValueError("foto_grande_demais")
        if not data:
            raise ValueError("foto_vazia")
        # Nome de arquivo segue o public_id — troca de foto substitui o arquivo.
        filename = f"{item['public_id']}{ext}"
        (self._photo_dir / filename).write_bytes(data)
        antigo = item.get("photo")
        self._db.execute(
            "UPDATE registry_items SET photo = ? WHERE public_id = ?",
            (filename, item["public_id"]),
        )
        if antigo and antigo != filename:
            try:
                (self._photo_dir / str(antigo)).unlink(missing_ok=True)
            except OSError:
                pass
        return filename

    def photo_path(self, codigo: str) -> Optional[Path]:
        """Arquivo da foto para servir (None: sem foto/desativada)."""
        item = self.get(codigo)
        if item is None:
            return None
        path = self._photo_file(item)
        if path is not None and not path.is_file():
            return None
        return path

    # ------------------------------------------------------------------#
    # Sala de bate-papo da peça                                          #
    # ------------------------------------------------------------------#
    def chat_post(self, codigo: str, username: str, text: str) -> dict[str, Any]:
        """Publica uma mensagem na sala da peça.

        Raises:
            ValueError: peça inexistente, texto vazio/grande ou sem sala.
        """
        item = self.get(codigo)
        if item is None:
            raise ValueError("peca_inexistente")
        username = str(username or "").strip()
        text = str(text or "").strip()
        if not username:
            raise ValueError("username_obrigatorio")
        if not text:
            raise ValueError("texto_vazio")
        if len(text) > CHAT_TEXT_MAX:
            raise ValueError("texto_longo")
        created = time.time()
        self._db.execute(
            "INSERT INTO registry_chat (public_id, username, text, created_at) "
            "VALUES (?,?,?,?)",
            (item["public_id"], username, text, created),
        )
        rows = self._db.query(
            "SELECT * FROM registry_chat WHERE public_id = ? ORDER BY id DESC "
            "LIMIT 1",
            (item["public_id"],),
        )
        return dict(rows[0]) if rows else {
            "public_id": item["public_id"], "username": username,
            "text": text, "created_at": created,
        }

    def chat_messages(
        self, codigo: str, since_id: int = 0, limit: int = CHAT_PAGE_LIMIT,
    ) -> Optional[list[dict[str, Any]]]:
        """Mensagens da sala (cronológica). None se a peça não existe."""
        item = self.get(codigo)
        if item is None:
            return None
        limit = max(1, min(int(limit or CHAT_PAGE_LIMIT), CHAT_PAGE_LIMIT))
        rows = self._db.query(
            "SELECT * FROM registry_chat WHERE public_id = ? AND id > ? "
            "ORDER BY id LIMIT ?",
            (item["public_id"], int(since_id or 0), limit),
        )
        return [dict(r) for r in rows]

    def chat_delete(self, codigo: str, msg_id: int) -> bool:
        """Apaga uma mensagem da sala (moderação do admin)."""
        item = self.get(codigo)
        if item is None:
            return False
        removed = self._db.execute(
            "DELETE FROM registry_chat WHERE public_id = ? AND id = ?",
            (item["public_id"], int(msg_id)),
        )
        return bool(removed)
