"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/quick_responses.py
Descrição: Respostas rápidas personalizadas — alternância entre variações
           e analytics de uso por padrão e por resposta.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky storage/quick_response_db.py
  - ROADMAP_ABSORCAO.md Fase 2, item 2.3
  - Tabelas legadas quick_responses (pattern, category, profile, response,
    response_alt, priority) e response_analytics (pattern, profile,
    use_count, avg_response_time_ms, last_used_at)

Architecture:
    Cada padrão (trigger) possui uma lista de respostas alternativas. A cada
    consulta, a resposta é rotacionada (round-robin) e o uso é contabilizado
    em analytics. Persistência JSON com escrita atômica e thread safety.

Usage:
    from memory.quick_responses import QuickResponses

    qr = QuickResponses(data_dir="data/quick_responses")
    qr.add("oi", ["Oi!", "Olá!", "Opa!"])
    resp = qr.get("oi")   # "Oi!" (primeira)
    resp = qr.get("oi")   # "Olá!" (rotaciona)
"""

from __future__ import annotations

import json
from core.logger import make_audit_nicky
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from storage.database import Database

_audit_nicky = make_audit_nicky("omega.memory.quick_responses")

__signature__ = "OD // CORE"





# ---------------------------------------------------------------------------
# Defaults (PT-BR)
# ---------------------------------------------------------------------------

DEFAULT_RESPONSES: dict[str, list[str]] = {
    "oi": ["Oi! 👋", "Olá!", "Opa, tudo bem?"],
    "olá": ["Olá!", "Oi! 👋", "Prazer em te ver."],
    "bom dia": ["Bom dia! ☀️", "Bom dia! Como posso ajudar?"],
    "boa tarde": ["Boa tarde! 🌤️", "Boa tarde! Em que posso ajudar?"],
    "boa noite": ["Boa noite! 🌙", "Boa noite! Descanse bem."],
    "obrigado": ["De nada! 😊", "Por nada!", "Sempre à disposição."],
    "obrigada": ["De nada! 😊", "Por nada!", "Sempre à disposição."],
    "quem é você": [
        "Eu sou o *Omega Drakon* — tecnologia que respira. 🐉",
        "Sou o Omega Drakon, a Interface Viva do sistema.",
    ],
    "o que é você": [
        "Sou o *Omega Drakon* — tecnologia que respira. 🐉",
        "Sou o sistema vivo deste servidor — análise, ações e memória.",
    ],
    "qual seu nome": ["Meu nome é *Omega Drakon* (ou OD, para os íntimos). 🐉"],
    "quem te criou": [
        "Fui criado pelo Alex Projeti, com a Interface Viva Nicky Virthy.",
    ],
    "você está aí": ["Estou aqui! 👋 Pronto para ajudar.", "Presente! 😄"],
    "tudo bem": ["Tudo ótimo! E com você? 😊", "Tudo em ordem por aqui!", "Tranquilo! E aí?"] ,
    "teste": ["Funcionando! 🟢", "Recebido! Sistema operacional."],
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class QuickResponse:
    """Um padrão com suas respostas alternativas e métricas de uso."""

    pattern: str
    responses: list[str] = field(default_factory=list)
    category: str = ""
    profile: str = ""
    priority: int = 0
    current_index: int = 0
    use_count: int = 0
    last_used_ts: Optional[float] = None
    avg_response_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "responses": list(self.responses),
            "category": self.category,
            "profile": self.profile,
            "priority": self.priority,
            "current_index": self.current_index,
            "use_count": self.use_count,
            "last_used_ts": self.last_used_ts,
            "avg_response_time_ms": self.avg_response_time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuickResponse":
        return cls(
            pattern=data["pattern"],
            responses=list(data.get("responses", [])),
            category=data.get("category", ""),
            profile=data.get("profile", ""),
            priority=data.get("priority", 0),
            current_index=data.get("current_index", 0),
            use_count=data.get("use_count", 0),
            last_used_ts=data.get("last_used_ts"),
            avg_response_time_ms=data.get("avg_response_time_ms", 0.0),
        )


# ---------------------------------------------------------------------------
# QuickResponses
# ---------------------------------------------------------------------------

class QuickResponses:
    """Catálogo de respostas rápidas com alternância e analytics.

    Persiste em JSON (default) ou Database (quando injetada).

    Attributes:
        data_dir: Diretório de persistência (JSON).
        profile:  Perfil padrão das respostas (isolamento por agente).
        _database: Database Layer opcional (取代 JSON quando presente).
    """

    def __init__(
        self,
        *,
        data_dir: str | Path = "data/quick_responses",
        profile: str = "",
        seed_defaults: bool = True,
        database: Optional["Database"] = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._profile = profile
        self._entries: dict[str, QuickResponse] = {}
        self._lock = threading.RLock()
        self._database = database
        if self._database is not None:
            from memory.adapters import QUICK_RESPONSES_SCHEMA
            self._database.create_table("quick_responses", QUICK_RESPONSES_SCHEMA)
        if seed_defaults:
            for pattern, responses in DEFAULT_RESPONSES.items():
                self._entries[pattern] = QuickResponse(pattern=pattern, responses=list(responses), profile=profile)
            if self._database is not None:
                self._seed_defaults_db()

    def _seed_defaults_db(self) -> None:
        """Insere os padrões default no DB (apenas os que não existem)."""
        db = self._database
        for pattern, responses in DEFAULT_RESPONSES.items():
            try:
                existing = db.scalar(
                    "SELECT COUNT(*) FROM quick_responses WHERE pattern = ?",
                    (pattern,),
                )
                if existing and existing > 0:
                    continue
                db.execute(
                    "INSERT INTO quick_responses "
                    "(pattern, responses_json, category, profile, priority) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (pattern, json.dumps(responses, ensure_ascii=False),
                     "", self._profile, 0),
                )
            except Exception:
                pass  # pragma: no cover

    # -- Gestão --------------------------------------------------------------

    @staticmethod
    def _normalize(pattern: str) -> str:
        """Normaliza o padrão para lookup: minúsculas, sem pontuação final
        e espaços colapsados ("Quem é você?" casa com "quem é você")."""
        import re as _re

        return _re.sub(r"\s+", " ", pattern.strip().lower()).rstrip("?!.,;:")

    def add(
        self,
        pattern: str,
        responses: list[str] | str,
        *,
        category: str = "",
        priority: int = 0,
    ) -> QuickResponse:
        """Adiciona (ou atualiza) um padrão com suas respostas."""
        normalized = self._normalize(pattern)
        if isinstance(responses, str):
            responses = [responses]
        responses = [r for r in responses if r]
        if not responses:
            raise ValueError("Pelo menos uma resposta é obrigatória")
        if self._database is not None:
            db = self._database
            existing = db.query(
                "SELECT pattern FROM quick_responses WHERE pattern = ?",
                (normalized,), limit=1,
            )
            if existing:
                db.execute(
                    "UPDATE quick_responses SET responses_json = ?, category = ?, "
                    "priority = ?, current_index = 0 WHERE pattern = ?",
                    (json.dumps(responses, ensure_ascii=False),
                     category, priority, normalized),
                )
            else:
                db.execute(
                    "INSERT INTO quick_responses "
                    "(pattern, responses_json, category, profile, priority) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (normalized, json.dumps(responses, ensure_ascii=False),
                     category, self._profile, priority),
                )
            entry = QuickResponse(
                pattern=normalized, responses=list(responses),
                category=category, profile=self._profile, priority=priority,
            )
            with self._lock:
                self._entries[normalized] = entry
            return entry
        with self._lock:
            existing = self._entries.get(normalized)
            if existing is not None:
                existing.responses = list(responses)
                existing.category = category or existing.category
                existing.priority = priority
                existing.current_index = 0
                entry = existing
            else:
                entry = QuickResponse(
                    pattern=normalized,
                    responses=list(responses),
                    category=category,
                    profile=self._profile,
                    priority=priority,
                )
                self._entries[normalized] = entry
            self._persist()
            return entry

    def add_response(self, pattern: str, response: str) -> bool:
        """Adiciona uma variação a um padrão existente. Retorna False se não existe."""
        normalized = self._normalize(pattern)
        if self._database is not None:
            db = self._database
            row = db.query(
                "SELECT pattern, responses_json FROM quick_responses "
                "WHERE pattern = ?", (normalized,), limit=1,
            )
            if not row:
                return False
            responses = json.loads(row[0]["responses_json"])
            if response not in responses:
                responses.append(response)
                db.execute(
                    "UPDATE quick_responses SET responses_json = ? WHERE pattern = ?",
                    (json.dumps(responses, ensure_ascii=False), normalized),
                )
            with self._lock:
                entry = self._entries.get(normalized)
                if entry is not None and response not in entry.responses:
                    entry.responses.append(response)
            return True
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None:
                return False
            if response not in entry.responses:
                entry.responses.append(response)
            self._persist()
            return True

    def remove(self, pattern: str) -> bool:
        """Remove um padrão inteiro. Retorna True se existia."""
        normalized = self._normalize(pattern)
        if self._database is not None:
            rowcount = self._database.execute(
                "DELETE FROM quick_responses WHERE pattern = ?", (normalized,)
            )
            with self._lock:
                self._entries.pop(normalized, None)
            return rowcount > 0
        with self._lock:
            if self._entries.pop(normalized, None) is not None:
                self._persist()
                return True
            return False

    def remove_response(self, pattern: str, response: str) -> bool:
        """Remove uma variação. Retorna True se existia e foi removida."""
        normalized = self._normalize(pattern)
        if self._database is not None:
            db = self._database
            row = db.query(
                "SELECT responses_json FROM quick_responses WHERE pattern = ?",
                (normalized,), limit=1,
            )
            if not row:
                return False
            responses = json.loads(row[0]["responses_json"])
            if response not in responses:
                return False
            responses.remove(response)
            if not responses:
                db.execute("DELETE FROM quick_responses WHERE pattern = ?", (normalized,))
            else:
                db.execute(
                    "UPDATE quick_responses SET responses_json = ? WHERE pattern = ?",
                    (json.dumps(responses, ensure_ascii=False), normalized),
                )
            with self._lock:
                entry = self._entries.get(normalized)
                if entry is not None and response in entry.responses:
                    entry.responses.remove(response)
                    if not entry.responses:
                        self._entries.pop(normalized, None)
            return True
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None or response not in entry.responses:
                return False
            entry.responses.remove(response)
            if not entry.responses:
                self._entries.pop(normalized, None)
            self._persist()
            return True

    def has(self, pattern: str) -> bool:
        normalized = self._normalize(pattern)
        if self._database is not None:
            return self._database.scalar(
                "SELECT COUNT(*) FROM quick_responses WHERE pattern = ?",
                (normalized,),
            ) > 0
        return normalized in self._entries

    # -- Consulta ------------------------------------------------------------

    def get(self, pattern: str, *, response_time_ms: float = 0.0) -> Optional[str]:
        """Retorna a próxima resposta (alternância round-robin) e registra uso.

        Returns:
            A resposta escolhida, ou None se o padrão não existe.
        """
        normalized = self._normalize(pattern)
        if self._database is not None:
            return self._get_db(normalized, response_time_ms)
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None or not entry.responses:
                return None

            response = entry.responses[entry.current_index]
            entry.current_index = (entry.current_index + 1) % len(entry.responses)
            entry.use_count += 1
            entry.last_used_ts = time.time()
            if response_time_ms > 0:
                if entry.avg_response_time_ms <= 0:
                    entry.avg_response_time_ms = response_time_ms
                else:
                    entry.avg_response_time_ms = (entry.avg_response_time_ms + response_time_ms) / 2
            self._persist()
            return response

    def _get_db(self, normalized: str, response_time_ms: float) -> Optional[str]:
        db = self._database
        row = db.query(
            "SELECT responses_json, current_index, use_count, "
            "avg_response_time_ms FROM quick_responses WHERE pattern = ?",
            (normalized,), limit=1,
        )
        if not row:
            return None
        r = row[0]
        responses = json.loads(r["responses_json"])
        if not responses:
            return None
        idx = r["current_index"] % len(responses)
        response = responses[idx]
        new_idx = (idx + 1) % len(responses)
        new_count = r["use_count"] + 1
        avg = r["avg_response_time_ms"]
        if response_time_ms > 0:
            if avg <= 0:
                avg = response_time_ms
            else:
                avg = (avg + response_time_ms) / 2
        db.execute(
            "UPDATE quick_responses SET current_index = ?, use_count = ?, "
            "last_used_ts = ?, avg_response_time_ms = ? WHERE pattern = ?",
            (new_idx, new_count, time.time(), avg, normalized),
        )
        return response

    def peek(self, pattern: str) -> Optional[str]:
        """Retorna a próxima resposta sem consumir (sem alternar nem contar)."""
        normalized = self._normalize(pattern)
        if self._database is not None:
            row = self._database.query(
                "SELECT responses_json, current_index FROM quick_responses "
                "WHERE pattern = ?", (normalized,), limit=1,
            )
            if not row:
                return None
            responses = json.loads(row[0]["responses_json"])
            if not responses:
                return None
            return responses[row[0]["current_index"] % len(responses)]
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None or not entry.responses:
                return None
            return entry.responses[entry.current_index]

    def get_entry(self, pattern: str) -> Optional[QuickResponse]:
        normalized = self._normalize(pattern)
        if self._database is not None:
            row = self._database.query(
                "SELECT * FROM quick_responses WHERE pattern = ?",
                (normalized,), limit=1,
            )
            if not row:
                return None
            r = row[0]
            return QuickResponse(
                pattern=r["pattern"],
                responses=json.loads(r["responses_json"]),
                category=r["category"],
                profile=r["profile"],
                priority=r["priority"],
                current_index=r["current_index"],
                use_count=r["use_count"],
                last_used_ts=r["last_used_ts"],
                avg_response_time_ms=r["avg_response_time_ms"],
            )
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None:
                return None
            return QuickResponse.from_dict(entry.to_dict())  # cópia

    def list_patterns(self) -> list[str]:
        if self._database is not None:
            rows = self._database.query(
                "SELECT pattern FROM quick_responses ORDER BY pattern"
            )
            return [r["pattern"] for r in rows]
        with self._lock:
            return sorted(self._entries.keys())

    # -- Analytics -----------------------------------------------------------

    def analytics(self, pattern: Optional[str] = None) -> dict[str, Any]:
        """Estatísticas de uso por padrão (e por resposta)."""
        if self._database is not None:
            db = self._database
            if pattern is not None:
                normalized = self._normalize(pattern)
                row = db.query(
                    "SELECT pattern, category, use_count, last_used_ts, "
                    "avg_response_time_ms, responses_json FROM quick_responses "
                    "WHERE pattern = ?", (normalized,), limit=1,
                )
                if not row:
                    return {}
                r = row[0]
                return {
                    "pattern": r["pattern"],
                    "category": r["category"],
                    "use_count": r["use_count"],
                    "last_used_ts": r["last_used_ts"],
                    "avg_response_time_ms": r["avg_response_time_ms"],
                    "responses": len(json.loads(r["responses_json"])),
                }
            rows = db.query(
                "SELECT pattern, use_count, last_used_ts FROM quick_responses"
            )
            result: dict[str, Any] = {
                "patterns": len(rows),
                "total_uses": 0,
                "per_pattern": {},
            }
            for r in rows:
                result["total_uses"] += r["use_count"]
                result["per_pattern"][r["pattern"]] = {
                    "use_count": r["use_count"],
                    "last_used_ts": r["last_used_ts"],
                }
            return result
        with self._lock:
            if pattern is not None:
                normalized = pattern.strip().lower()
                entry = self._entries.get(normalized)
                if entry is None:
                    return {}
                return {
                    "pattern": entry.pattern,
                    "category": entry.category,
                    "use_count": entry.use_count,
                    "last_used_ts": entry.last_used_ts,
                    "avg_response_time_ms": entry.avg_response_time_ms,
                    "responses": len(entry.responses),
                }
            result: dict[str, Any] = {
                "patterns": len(self._entries),
                "total_uses": 0,
                "per_pattern": {},
            }
            for pattern_key, entry in self._entries.items():
                result["total_uses"] += entry.use_count
                result["per_pattern"][pattern_key] = {
                    "use_count": entry.use_count,
                    "last_used_ts": entry.last_used_ts,
                }
            return result

    # -- Persistência --------------------------------------------------------

    def load(self) -> int:
        """Carrega o catálogo do disco/DB. Retorna nº de padrões carregados."""
        if self._database is not None:
            return self._load_db()
        path = self._file_path()
        if not path.exists():
            return 0
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._entries.clear()
                for item in data.get("responses", []):
                    entry = QuickResponse.from_dict(item)
                    self._entries[entry.pattern] = entry
                return len(self._entries)
            except Exception as exc:
                _audit_nicky("WARN", "QuickResponses load failed", error=type(exc).__name__)
                return 0

    def _load_db(self) -> int:
        """Carrega padrões do Database para a memória."""
        db = self._database
        rows = db.query("SELECT * FROM quick_responses")
        with self._lock:
            self._entries.clear()
            for row in rows:
                entry = QuickResponse(
                    pattern=row["pattern"],
                    responses=json.loads(row["responses_json"]),
                    category=row["category"],
                    profile=row["profile"],
                    priority=row["priority"],
                    current_index=row["current_index"],
                    use_count=row["use_count"],
                    last_used_ts=row["last_used_ts"],
                    avg_response_time_ms=row["avg_response_time_ms"],
                )
                self._entries[entry.pattern] = entry
            return len(self._entries)

    def _persist(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "profile": self._profile,
                "updated_at": time.time(),
                "responses": [e.to_dict() for e in self._entries.values()],
            }
            path = self._file_path()
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as exc:
            _audit_nicky("CRIT", "QuickResponses persist failed", error=type(exc).__name__)

    def _file_path(self) -> Path:
        return self._data_dir / "quick_responses.json"

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        backend = "db" if self._database is not None else "json"
        result: dict[str, Any] = {
            "backend": backend,
            "profile": self._profile,
            "analytics": self.analytics(),
        }
        if self._database is None:
            result["data_dir"] = str(self._data_dir)
        return result