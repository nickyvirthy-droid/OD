"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: memory/adapters.py
Descrição: Adaptador de persistência — schemas das tabelas de memória e
           funções de migração JSON → Database (SQLite/PostgreSQL).
           Permite que history, cache, quick_responses e vector store
           funcionem sobre a Database Layer existente.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - storage/database.py (Database/Repository com backend plugável)
  - memory/history.py, memory/cache.py, memory/quick_responses.py,
    memory/vector.py (persistência JSON legada)
  - ROADMAP_V1.md item 1.2 (migração JSON → PostgreSQL)

Architecture:
    Os módulos de memória mantêm sua API pública inalterada. Quando um
    objeto Database é injetado, a persistência muda de JSON files para
    tabelas SQL. A migração é opcional e idempotente — dados JSON
    existentes são carregados e inseridos na primeira vez.

    Tabelas:
      - conversation_messages (user_id, profile, role, content, ts, llm_used)
      - llm_cache (key, prompt, response, profile, llm_used, tokens_used,
                   use_count, duplicates, created_ts, last_used_ts,
                   avg_response_time_ms)
      - quick_responses (pattern, responses_json, category, profile,
                         priority, current_index, use_count, last_used_ts,
                         avg_response_time_ms)
      - vector_documents (doc_id, namespace, text, vector_json, metadata_json,
                          created_ts)
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("omega.memory.adapters")

__signature__ = "OD // CORE"


# ---------------------------------------------------------------------------
# Schemas das tabelas de memória
# ---------------------------------------------------------------------------

CONVERSATION_MESSAGES_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "user_id": "TEXT NOT NULL",
    "profile": "TEXT NOT NULL",
    "role": "TEXT NOT NULL",
    "content": "TEXT NOT NULL",
    "ts": "REAL NOT NULL",
    "llm_used": "TEXT DEFAULT ''",
}

LLM_CACHE_SCHEMA: dict[str, str] = {
    "key": "TEXT PRIMARY KEY",
    "prompt": "TEXT NOT NULL",
    "response": "TEXT NOT NULL",
    "profile": "TEXT DEFAULT ''",
    "llm_used": "TEXT DEFAULT ''",
    "tokens_used": "INTEGER DEFAULT 0",
    "use_count": "INTEGER DEFAULT 1",
    "duplicates": "INTEGER DEFAULT 0",
    "created_ts": "REAL NOT NULL",
    "last_used_ts": "REAL NOT NULL",
    "avg_response_time_ms": "REAL DEFAULT 0.0",
}

QUICK_RESPONSES_SCHEMA: dict[str, str] = {
    "pattern": "TEXT PRIMARY KEY",
    "responses_json": "TEXT NOT NULL",
    "category": "TEXT DEFAULT ''",
    "profile": "TEXT DEFAULT ''",
    "priority": "INTEGER DEFAULT 0",
    "current_index": "INTEGER DEFAULT 0",
    "use_count": "INTEGER DEFAULT 0",
    "last_used_ts": "REAL",
    "avg_response_time_ms": "REAL DEFAULT 0.0",
}

VECTOR_DOCUMENTS_SCHEMA: dict[str, str] = {
    "doc_id": "TEXT PRIMARY KEY",
    "namespace": "TEXT NOT NULL",
    "text": "TEXT NOT NULL",
    "vector_json": "TEXT NOT NULL",
    "metadata_json": "TEXT DEFAULT '{}'",
    "created_ts": "REAL NOT NULL",
}


# ---------------------------------------------------------------------------
# Tabelas auxiliares
# ---------------------------------------------------------------------------

TABLE_NAMES = {
    "conversation_messages",
    "llm_cache",
    "quick_responses",
    "vector_documents",
}


def ensure_tables(db: Any) -> None:
    """Garante que as 4 tabelas de memória existem no banco."""
    db.create_table("conversation_messages", CONVERSATION_MESSAGES_SCHEMA)
    db.create_table("llm_cache", LLM_CACHE_SCHEMA)
    db.create_table("quick_responses", QUICK_RESPONSES_SCHEMA)
    db.create_table("vector_documents", VECTOR_DOCUMENTS_SCHEMA)


# ---------------------------------------------------------------------------
# Migração JSON → Database
# ---------------------------------------------------------------------------

def migrate_history(db: Any, json_dir: str | Any) -> int:
    """Migra dados de conversation_messages de JSON para DB.

    Lê os arquivos JSON em ``{json_dir}/{user_id}/{profile}.json`` e
    insere as mensagens na tabela ``conversation_messages``.

    Returns:
        Número de mensagens migradas (idempotente — duplicatas ignoradas
        por INSERT OR IGNORE via try/except).
    """
    from pathlib import Path

    base = Path(json_dir) if not isinstance(json_dir, Path) else json_dir
    if not base.exists():
        return 0

    count = 0
    for user_dir in sorted(base.iterdir()):
        if not user_dir.is_dir():
            continue
        for profile_file in sorted(user_dir.glob("*.json")):
            profile = profile_file.stem
            try:
                raw = profile_file.read_text(encoding="utf-8")
                data = json.loads(raw)
                messages = data.get("messages", [])
                if not messages:
                    continue
                # Verifica se já migrou (evita duplicatas)
                existing = db.scalar(
                    "SELECT COUNT(*) FROM conversation_messages "
                    "WHERE user_id = ? AND profile = ?",
                    (user_dir.name, profile),
                )
                if existing and existing > 0:
                    continue
                for msg in messages:
                    db.execute(
                        "INSERT INTO conversation_messages "
                        "(user_id, profile, role, content, ts, llm_used) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            user_dir.name,
                            profile,
                            msg.get("role", "user"),
                            msg.get("content", ""),
                            msg.get("ts", time.time()),
                            msg.get("llm_used", ""),
                        ),
                    )
                    count += 1
            except Exception as exc:
                log.warn(
                    "Migração history falhou",
                    file=str(profile_file),
                    error=str(exc),
                )
    if count > 0:
        log.info("History migrado para DB", mensagens=count)
    return count


def migrate_cache(db: Any, json_path: str | Any) -> int:
    """Migra entradas do cache LLM de JSON para DB.

    Lê ``{json_path}/cache.json`` e insere na tabela ``llm_cache``.

    Returns:
        Número de entradas migradas.
    """
    from pathlib import Path

    path = Path(json_path) if not isinstance(json_path, Path) else json_path
    if not path.exists():
        return 0

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        entries = data.get("entries", [])
        if not entries:
            return 0
        # Verifica se já migrou
        existing = db.scalar("SELECT COUNT(*) FROM llm_cache")
        if existing and existing > 0:
            return 0
        count = 0
        for entry in entries:
            db.execute(
                "INSERT INTO llm_cache "
                "(key, prompt, response, profile, llm_used, tokens_used, "
                "use_count, duplicates, created_ts, last_used_ts, "
                "avg_response_time_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.get("key", ""),
                    entry.get("prompt", ""),
                    entry.get("response", ""),
                    entry.get("profile", ""),
                    entry.get("llm_used", ""),
                    entry.get("tokens_used", 0),
                    entry.get("use_count", 1),
                    entry.get("duplicates", 0),
                    entry.get("created_ts", time.time()),
                    entry.get("last_used_ts", time.time()),
                    entry.get("avg_response_time_ms", 0.0),
                ),
            )
            count += 1
        if count > 0:
            log.info("Cache migrado para DB", entradas=count)
        return count
    except Exception as exc:
        log.warn("Migração cache falhou", error=str(exc))
        return 0


def migrate_quick_responses(db: Any, json_path: str | Any) -> int:
    """Migra respostas rápidas de JSON para DB.

    Lê ``{json_path}/quick_responses.json`` e insere na tabela
    ``quick_responses``.

    Returns:
        Número de padrões migrados.
    """
    from pathlib import Path

    path = Path(json_path) if not isinstance(json_path, Path) else json_path
    if not path.exists():
        return 0

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        items = data.get("responses", [])
        if not items:
            return 0
        existing = db.scalar("SELECT COUNT(*) FROM quick_responses")
        if existing and existing > 0:
            return 0
        count = 0
        for item in items:
            db.execute(
                "INSERT INTO quick_responses "
                "(pattern, responses_json, category, profile, priority, "
                "current_index, use_count, last_used_ts, "
                "avg_response_time_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.get("pattern", ""),
                    json.dumps(item.get("responses", []), ensure_ascii=False),
                    item.get("category", ""),
                    item.get("profile", ""),
                    item.get("priority", 0),
                    item.get("current_index", 0),
                    item.get("use_count", 0),
                    item.get("last_used_ts"),
                    item.get("avg_response_time_ms", 0.0),
                ),
            )
            count += 1
        if count > 0:
            log.info("QuickResponses migrado para DB", padroes=count)
        return count
    except Exception as exc:
        log.warn("Migração quick_responses falhou", error=str(exc))
        return 0


def migrate_vector(db: Any, json_path: str | Any) -> int:
    """Migra vector store de JSON para DB.

    Lê ``{json_path}/vector_store.json`` e insere na tabela
    ``vector_documents``.

    Returns:
        Número de documentos migrados.
    """
    from pathlib import Path

    path = Path(json_path) if not isinstance(json_path, Path) else json_path
    if not path.exists():
        return 0

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        docs = data.get("documents", [])
        if not docs:
            return 0
        existing = db.scalar("SELECT COUNT(*) FROM vector_documents")
        if existing and existing > 0:
            return 0
        count = 0
        for doc in docs:
            db.execute(
                "INSERT INTO vector_documents "
                "(doc_id, namespace, text, vector_json, metadata_json, "
                "created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    doc.get("doc_id", ""),
                    doc.get("namespace", ""),
                    doc.get("text", ""),
                    json.dumps(doc.get("vector", [])),
                    json.dumps(doc.get("metadata", {}), ensure_ascii=False),
                    doc.get("created_ts", time.time()),
                ),
            )
            count += 1
        if count > 0:
            log.info("VectorStore migrado para DB", docs=count)
        return count
    except Exception as exc:
        log.warn("Migração vector falhou", error=str(exc))
        return 0


def migrate_all(
    db: Any,
    *,
    history_dir: str | Any = "data/conversations",
    cache_dir: str | Any = "data/llm_cache",
    quick_dir: str | Any = "data/quick_responses",
    vector_dir: str | Any = "data/vector_memory",
) -> dict[str, int]:
    """Executa a migração completa JSON→DB (idempotente).

    Returns:
        Dict com contagem de registros migrados por domínio.
    """
    ensure_tables(db)
    result: dict[str, int] = {
        "conversation_messages": migrate_history(db, history_dir),
        "llm_cache": migrate_cache(db, cache_dir),
        "quick_responses": migrate_quick_responses(db, quick_dir),
        "vector_documents": migrate_vector(db, vector_dir),
    }
    total = sum(result.values())
    if total > 0:
        log.info("Migração JSON→DB concluída", total=total, detalhes=result)
    return result
