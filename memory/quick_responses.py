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
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("omega.memory.quick_responses")

NICKY_PREFIX = "[NICKY][{level}]"

__signature__ = "OD // CORE"


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


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

    Attributes:
        data_dir: Diretório de persistência.
        profile:  Perfil padrão das respostas (isolamento por agente).
    """

    def __init__(
        self,
        *,
        data_dir: str | Path = "data/quick_responses",
        profile: str = "",
        seed_defaults: bool = True,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._profile = profile
        self._entries: dict[str, QuickResponse] = {}
        self._lock = threading.RLock()
        if seed_defaults:
            for pattern, responses in DEFAULT_RESPONSES.items():
                self._entries[pattern] = QuickResponse(pattern=pattern, responses=list(responses), profile=profile)

    # -- Gestão --------------------------------------------------------------

    def add(
        self,
        pattern: str,
        responses: list[str] | str,
        *,
        category: str = "",
        priority: int = 0,
    ) -> QuickResponse:
        """Adiciona (ou atualiza) um padrão com suas respostas."""
        normalized = pattern.strip().lower()
        if isinstance(responses, str):
            responses = [responses]
        responses = [r for r in responses if r]
        if not responses:
            raise ValueError("Pelo menos uma resposta é obrigatória")
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
        normalized = pattern.strip().lower()
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
        normalized = pattern.strip().lower()
        with self._lock:
            if self._entries.pop(normalized, None) is not None:
                self._persist()
                return True
            return False

    def remove_response(self, pattern: str, response: str) -> bool:
        """Remove uma variação. Retorna True se existia e foi removida."""
        normalized = pattern.strip().lower()
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
        return pattern.strip().lower() in self._entries

    # -- Consulta ------------------------------------------------------------

    def get(self, pattern: str, *, response_time_ms: float = 0.0) -> Optional[str]:
        """Retorna a próxima resposta (alternância round-robin) e registra uso.

        Returns:
            A resposta escolhida, ou None se o padrão não existe.
        """
        normalized = pattern.strip().lower()
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

    def peek(self, pattern: str) -> Optional[str]:
        """Retorna a próxima resposta sem consumir (sem alternar nem contar)."""
        normalized = pattern.strip().lower()
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None or not entry.responses:
                return None
            return entry.responses[entry.current_index]

    def get_entry(self, pattern: str) -> Optional[QuickResponse]:
        normalized = pattern.strip().lower()
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None:
                return None
            return QuickResponse.from_dict(entry.to_dict())  # cópia

    def list_patterns(self) -> list[str]:
        with self._lock:
            return sorted(self._entries.keys())

    # -- Analytics -----------------------------------------------------------

    def analytics(self, pattern: Optional[str] = None) -> dict[str, Any]:
        """Estatísticas de uso por padrão (e por resposta)."""
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
        """Carrega o catálogo do disco. Retorna nº de padrões carregados."""
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
        with self._lock:
            return {
                "data_dir": str(self._data_dir),
                "profile": self._profile,
                "analytics": self.analytics(),
            }