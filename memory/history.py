"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/history.py
Descrição: Histórico de conversas por usuário/perfil com persistência JSON
           e formatação ChatML para o LLM local.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky storage/conversation_history.py
  - ROADMAP_ABSORCAO.md Fase 2, item 2.1
  - Tabela legada conversation_messages (user_id, profile, role, content,
    llm_used, created_at)

Architecture:
    O histórico persiste em arquivos JSON separados por usuário e perfil:
        data/conversations/{user_id}/{profile}.json
    Cada arquivo guarda até `max_entries` mensagens (mais recentes). Em
    memória, tudo é carregado via load_all() no startup. A saída ChatML
    (<|im_start|>/<|im_end|>) é consumida pelo cliente do LLM local.

Usage:
    from memory.history import ConversationHistory

    history = ConversationHistory(base_dir="data/conversations")
    history.load_all()

    history.add_interaction("alex", "guardian", "Bom dia!", "Olá, Alex!")
    msgs = history.get_history("alex", "guardian")
    chatml = history.get_chatml("alex", "guardian", system_prompt="Você é Nicky.")
"""

from __future__ import annotations

import json
from core.logger import make_audit_nicky
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_audit_nicky = make_audit_nicky("omega.memory.history")

__signature__ = "OD // CORE"





# ---------------------------------------------------------------------------
# ChatML
# ---------------------------------------------------------------------------

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"


def build_chatml(messages: list[Any], system_prompt: str = "") -> str:
    """Constrói uma string no formato ChatML a partir de mensagens.

    Suporta objetos com atributos `.role`/`.content` (Message) ou dicts
    com chaves "role"/"content". Se `system_prompt` for fornecido, ele é
    prependido como mensagem de sistema.

    Returns:
        String ChatML, ex:
        <|im_start|>system
        Você é Nicky.<|im_end|>
        <|im_start|>user
        Olá!<|im_end|>
    """
    parts: list[str] = []
    if system_prompt:
        parts.append(f"{IM_START}system\n{system_prompt}{IM_END}")
    for msg in messages:
        role = getattr(msg, "role", None) or msg.get("role", "user")
        content = getattr(msg, "content", None) or msg.get("content", "")
        parts.append(f"{IM_START}{role}\n{content}{IM_END}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Message:
    """Uma mensagem de conversa (imutável)."""

    role: str  # "system" | "user" | "assistant"
    content: str
    ts: float = field(default_factory=time.time)
    llm_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "ts": self.ts,
            "llm_used": self.llm_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=data["role"],
            content=data["content"],
            ts=data.get("ts", time.time()),
            llm_used=data.get("llm_used", ""),
        )


# ---------------------------------------------------------------------------
# ConversationHistory
# ---------------------------------------------------------------------------

class ConversationHistory:
    """Histórico de conversas por usuário/perfil com persistência JSON.

    Attributes:
        base_dir:    Diretório raiz dos arquivos de histórico.
        max_entries: Número máximo de mensagens mantidas por conversa.
        users:       Cache em memória: user_id -> profile -> list[Message].
    """

    def __init__(
        self,
        *,
        base_dir: str | Path = "data/conversations",
        max_entries: int = 20,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._max_entries = max(1, max_entries)
        self._users: dict[str, dict[str, list[Message]]] = {}
        self._lock = threading.RLock()

    # -- Lifecycle -----------------------------------------------------------

    def load_all(self) -> int:
        """Carrega todo o histórico do disco para a memória.

        Returns:
            Número de conversas (user/profile) carregadas.
        """
        with self._lock:
            self._users.clear()
            count = 0
            if not self._base_dir.exists():
                return 0
            for user_dir in sorted(self._base_dir.iterdir()):
                if not user_dir.is_dir():
                    continue
                for profile_file in sorted(user_dir.glob("*.json")):
                    profile = profile_file.stem
                    messages = self._read_file(user_dir.name, profile)
                    if messages:
                        self._users.setdefault(user_dir.name, {})[profile] = messages
                        count += 1
            _audit_nicky("INFO", "History loaded", conversations=count)
            return count

    # -- Escrita -------------------------------------------------------------

    def add_message(
        self,
        user_id: str,
        profile: str,
        role: str,
        content: str,
        *,
        llm_used: str = "",
    ) -> Message:
        """Adiciona uma mensagem avulsa à conversa e persiste."""
        msg = Message(role=role, content=content, llm_used=llm_used)
        with self._lock:
            conv = self._get_conversation(user_id, profile)
            conv.append(msg)
            self._trim(conv)
            self._write(user_id, profile, conv)
        return msg

    def add_interaction(
        self,
        user_id: str,
        profile: str,
        user_message: str,
        assistant_message: str,
        *,
        llm_used: str = "",
    ) -> int:
        """Registra um turno completo (usuário + assistente).

        Returns:
            Número de mensagens adicionadas (2).
        """
        with self._lock:
            conv = self._get_conversation(user_id, profile)
            conv.append(Message(role="user", content=user_message))
            conv.append(Message(role="assistant", content=assistant_message, llm_used=llm_used))
            self._trim(conv)
            self._write(user_id, profile, conv)
        _audit_nicky(
            "INFO",
            "Interaction recorded",
            user=user_id,
            profile=profile,
        )
        return 2

    def add_system(
        self,
        user_id: str,
        profile: str,
        content: str,
    ) -> Message:
        """Adiciona uma mensagem de sistema à conversa."""
        return self.add_message(user_id, profile, "system", content)

    # -- Leitura -------------------------------------------------------------

    def get_history(self, user_id: str, profile: str) -> list[Message]:
        """Retorna as mensagens da conversa (cópia)."""
        with self._lock:
            conv = self._users.get(user_id, {}).get(profile)
            if conv is None:
                return []
            return list(conv)

    def get_chatml(
        self,
        user_id: str,
        profile: str,
        *,
        system_prompt: str = "",
    ) -> str:
        """Retorna a conversa formatada em ChatML."""
        messages = self.get_history(user_id, profile)
        return build_chatml(messages, system_prompt=system_prompt)

    def last_interaction(
        self,
        user_id: str,
        profile: str,
    ) -> Optional[Message]:
        """Retorna a última mensagem da conversa, ou None se vazia."""
        conv = self.get_history(user_id, profile)
        return conv[-1] if conv else None

    # -- Consulta ------------------------------------------------------------

    def list_users(self) -> list[str]:
        with self._lock:
            return sorted(self._users.keys())

    def list_profiles(self, user_id: str) -> list[str]:
        with self._lock:
            return sorted(self._users.get(user_id, {}).keys())

    def stats(self, user_id: Optional[str] = None) -> dict[str, Any]:
        """Estatísticas do histórico: mensagens por conversa, última atividade."""
        with self._lock:
            result: dict[str, Any] = {
                "users": len(self._users),
                "conversations": 0,
                "messages": 0,
                "per_user": {},
            }
            for uid, profiles in self._users.items():
                if user_id and uid != user_id:
                    continue
                user_stats: dict[str, Any] = {"conversations": 0, "messages": 0, "profiles": {}}
                for profile, conv in profiles.items():
                    user_stats["conversations"] += 1
                    user_stats["messages"] += len(conv)
                    user_stats["profiles"][profile] = {
                        "messages": len(conv),
                        "last_ts": conv[-1].ts if conv else None,
                    }
                result["conversations"] += user_stats["conversations"]
                result["messages"] += user_stats["messages"]
                if not user_id or uid == user_id:
                    result["per_user"][uid] = user_stats
            return result

    # -- Remoção -------------------------------------------------------------

    def clear(self, user_id: str, profile: Optional[str] = None) -> int:
        """Limpa uma conversa (ou todas do usuário). Retorna nº removido."""
        with self._lock:
            removed = 0
            if profile is not None:
                conv = self._users.get(user_id, {}).pop(profile, None)
                if conv is not None:
                    removed = len(conv)
                self._remove_file(user_id, profile)
            else:
                profiles = self._users.pop(user_id, {})
                for p, conv in profiles.items():
                    removed += len(conv)
                    self._remove_file(user_id, p)
            _audit_nicky("INFO", "History cleared", user=user_id, profile=profile or "*", removed=removed)
            return removed

    def clear_all(self) -> int:
        """Limpa todo o histórico em memória e no disco."""
        with self._lock:
            removed = 0
            for user_id in list(self._users.keys()):
                removed += self.clear(user_id)
            return removed

    # -- Interno -------------------------------------------------------------

    def _get_conversation(self, user_id: str, profile: str) -> list[Message]:
        """Obtém a conversa em memória (carregando do disco se necessário)."""
        conv = self._users.get(user_id, {}).get(profile)
        if conv is None:
            conv = self._read_file(user_id, profile)
            self._users.setdefault(user_id, {})[profile] = conv
        return conv

    def _trim(self, conv: list[Message]) -> None:
        if len(conv) > self._max_entries:
            del conv[: len(conv) - self._max_entries]

    # -- Persistência --------------------------------------------------------

    def _file_path(self, user_id: str, profile: str) -> Path:
        return self._base_dir / user_id / f"{profile}.json"

    def _read_file(self, user_id: str, profile: str) -> list[Message]:
        path = self._file_path(user_id, profile)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return [Message.from_dict(m) for m in data.get("messages", [])]
        except Exception as exc:
            _audit_nicky(
                "WARN",
                "History read failed",
                user=user_id,
                profile=profile,
                error=type(exc).__name__,
            )
            return []

    def _write(self, user_id: str, profile: str, conv: list[Message]) -> None:
        path = self._file_path(user_id, profile)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "user_id": user_id,
                "profile": profile,
                "updated_at": time.time(),
                "messages": [m.to_dict() for m in conv],
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as exc:
            _audit_nicky(
                "CRIT",
                "History write failed",
                user=user_id,
                profile=profile,
                error=type(exc).__name__,
            )

    def _remove_file(self, user_id: str, profile: str) -> None:
        path = self._file_path(user_id, profile)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "base_dir": str(self._base_dir),
            "max_entries": self._max_entries,
            "stats": self.stats(),
        }