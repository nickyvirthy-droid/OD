"""
OMEGA DRAKON * TESTS
Modulo: tests/test_memory_db.py
Descricao: Testes da camada de persistencia via Database para os modulos
           de memoria (history, cache, quick_responses, vector) - item 1.2
           da v1.0.0 (migracao JSON -> PostgreSQL/SQLite).

           Todos os testes usam Database em :memory: (SQLite) - sem
           dependencia de PostgreSQL.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from storage.database import Database
from memory.history import ConversationHistory
from memory.cache import LLMCache, normalize_prompt
from memory.quick_responses import QuickResponses
from memory.vector import VectorStore, HashEmbeddingProvider
from memory.adapters import (
    ensure_tables,
    migrate_history,
    migrate_cache,
    migrate_quick_responses,
    migrate_vector,
    migrate_all,
    CONVERSATION_MESSAGES_SCHEMA,
    LLM_CACHE_SCHEMA,
    QUICK_RESPONSES_SCHEMA,
    VECTOR_DOCUMENTS_SCHEMA,
)


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:", pool_size=2)
    ensure_tables(database)
    yield database
    database.close()


# ---------------------------------------------------------------------------
# History via Database
# ---------------------------------------------------------------------------


class TestHistoryDB:
    def test_add_and_get(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_message("alex", "guardian", "user", "oi")
        h.add_message("alex", "guardian", "assistant", "ola!")
        msgs = h.get_history("alex", "guardian")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].content == "ola!"

    def test_add_interaction(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        count = h.add_interaction("bia", "guardian", "oi", "ola bia")
        assert count == 2
        msgs = h.get_history("bia", "guardian")
        assert len(msgs) == 2

    def test_load_all_from_db(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_message("alex", "guardian", "user", "msg1")
        h.add_message("bia", "nexus", "user", "msg2")
        h2 = ConversationHistory(database=db)
        count = h2.load_all()
        assert count == 2

    def test_stats(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_interaction("alex", "guardian", "oi", "ola")
        h.add_interaction("bia", "guardian", "oi2", "ola2")
        stats = h.stats()
        assert stats["users"] == 2
        assert stats["conversations"] == 2
        assert stats["messages"] == 4

    def test_stats_filtered(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_interaction("alex", "guardian", "oi", "ola")
        h.add_interaction("bia", "guardian", "oi2", "ola2")
        stats = h.stats(user_id="bia")
        assert stats["conversations"] == 1
        assert "bia" in stats["per_user"]

    def test_clear(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_interaction("alex", "guardian", "oi", "ola")
        removed = h.clear("alex", "guardian")
        assert removed == 2
        assert h.get_history("alex", "guardian") == []

    def test_clear_all(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_interaction("alex", "guardian", "oi", "ola")
        h.add_interaction("bia", "nexus", "oi2", "ola2")
        removed = h.clear_all()
        assert removed == 4

    def test_dump_backend_db(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        d = h.dump()
        assert d["backend"] == "db"
        assert "base_dir" not in d

    def test_get_chatml(self, db: Database) -> None:
        h = ConversationHistory(database=db)
        h.add_interaction("alex", "guardian", "Oi!", "Ola, Alex!")
        chatml = h.get_chatml("alex", "guardian", system_prompt="Voce e Nicky.")
        assert "system" in chatml
        assert "user" in chatml
        assert "assistant" in chatml


# ---------------------------------------------------------------------------
# LLMCache via Database
# ---------------------------------------------------------------------------


class TestCacheDB:
    def test_set_and_get(self, db: Database) -> None:
        c = LLMCache(database=db, profile="guardian")
        c.set("qual a capital?", "Brasilia.")
        resp = c.get("qual a capital?")
        assert resp == "Brasilia."

    def test_hit_miss(self, db: Database) -> None:
        c = LLMCache(database=db)
        c.get("nao existe")
        c.set("oi", "ola")
        c.get("oi")
        m = c.metrics()
        assert m["misses"] == 1
        assert m["hits"] == 1

    def test_dedup(self, db: Database) -> None:
        c = LLMCache(database=db)
        c.set("oi", "ola")
        c.set("oi", "ola2")
        m = c.metrics()
        assert m["duplicates"] == 1

    def test_delete(self, db: Database) -> None:
        c = LLMCache(database=db)
        c.set("oi", "ola")
        assert c.delete("oi") is True
        assert c.get("oi") is None

    def test_clear(self, db: Database) -> None:
        c = LLMCache(database=db)
        c.set("a", "1")
        c.set("b", "2")
        removed = c.clear()
        assert removed == 2

    def test_load(self, db: Database) -> None:
        c = LLMCache(database=db)
        c.set("x", "y")
        c2 = LLMCache(database=db)
        count = c2.load()
        assert count == 1

    def test_stats_db(self, db: Database) -> None:
        c = LLMCache(database=db)
        c.set("a", "1")
        stats = c.stats()
        assert stats["entries"] == 1
        assert stats["backend" if "backend" in stats else "entries"] == 1

    def test_dump_backend_db(self, db: Database) -> None:
        c = LLMCache(database=db)
        d = c.dump()
        assert d["backend"] == "db"
        assert "cache_dir" not in d

    def test_ttl_expiration(self, db: Database) -> None:
        c = LLMCache(database=db, ttl_seconds=0.1)
        c.set("x", "y")
        time.sleep(0.15)
        assert c.get("x") is None

    def test_has(self, db: Database) -> None:
        c = LLMCache(database=db)
        assert c.has("nope") is False
        c.set("yes", "ok")
        assert c.has("yes") is True


# ---------------------------------------------------------------------------
# QuickResponses via Database
# ---------------------------------------------------------------------------


class TestQuickResponsesDB:
    def test_get(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=True)
        resp = qr.get("oi")
        assert resp is not None
        assert len(resp) > 0

    def test_add_and_has(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("teste", ["ok", "recebido"])
        assert qr.has("teste") is True
        assert qr.get("teste") in ["ok", "recebido"]

    def test_round_robin(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("test", ["a", "b", "c"])
        r1 = qr.get("test")
        r2 = qr.get("test")
        r3 = qr.get("test")
        r4 = qr.get("test")
        # Deve rotacionar
        assert r1 == "a"
        assert r2 == "b"
        assert r3 == "c"
        assert r4 == "a"

    def test_remove(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("x", ["y"])
        assert qr.remove("x") is True
        assert qr.has("x") is False

    def test_add_response(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("x", ["a"])
        qr.add_response("x", "b")
        entry = qr.get_entry("x")
        assert "b" in entry.responses

    def test_remove_response(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("x", ["a", "b"])
        assert qr.remove_response("x", "b") is True
        entry = qr.get_entry("x")
        assert "b" not in entry.responses

    def test_list_patterns(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("alpha", ["1"])
        qr.add("beta", ["2"])
        patterns = qr.list_patterns()
        assert "alpha" in patterns
        assert "beta" in patterns

    def test_analytics(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("x", ["a"])
        qr.get("x")
        qr.get("x")
        a = qr.analytics("x")
        assert a["use_count"] == 2

    def test_dump_backend_db(self, db: Database) -> None:
        qr = QuickResponses(database=db)
        d = qr.dump()
        assert d["backend"] == "db"
        assert "data_dir" not in d

    def test_peek(self, db: Database) -> None:
        qr = QuickResponses(database=db, seed_defaults=False)
        qr.add("x", ["a", "b"])
        peeked = qr.peek("x")
        assert peeked == "a"
        # peek nao consome
        assert qr.peek("x") == "a"


# ---------------------------------------------------------------------------
# VectorStore via Database
# ---------------------------------------------------------------------------


class TestVectorDB:
    def test_add_and_search(self, db: Database) -> None:
        vs = VectorStore(database=db, top_k=2)
        vs.add("docs", "O OmegaDrakon roda em Linux")
        vs.add("docs", "Python e a linguagem principal")
        results = vs.search("docs", "sistema operacional")
        assert len(results) > 0
        assert results[0].namespace == "docs"

    def test_add_many(self, db: Database) -> None:
        vs = VectorStore(database=db)
        ids = vs.add_many("ns", ["a", "b", "c"])
        assert len(ids) == 3
        assert vs.count("ns") == 3

    def test_delete(self, db: Database) -> None:
        vs = VectorStore(database=db)
        doc_id = vs.add("ns", "teste")
        assert vs.delete(doc_id) is True
        assert vs.get(doc_id) is None

    def test_clear(self, db: Database) -> None:
        vs = VectorStore(database=db)
        vs.add("ns1", "a")
        vs.add("ns2", "b")
        removed = vs.clear("ns1")
        assert removed == 1
        assert vs.count() == 1

    def test_clear_all(self, db: Database) -> None:
        vs = VectorStore(database=db)
        vs.add("ns1", "a")
        vs.add("ns2", "b")
        removed = vs.clear()
        assert removed == 2

    def test_list_namespaces(self, db: Database) -> None:
        vs = VectorStore(database=db)
        vs.add("alpha", "x")
        vs.add("beta", "y")
        ns = vs.list_namespaces()
        assert "alpha" in ns
        assert "beta" in ns

    def test_load(self, db: Database) -> None:
        vs = VectorStore(database=db)
        vs.add("ns", "texto")
        vs2 = VectorStore(database=db)
        count = vs2.load()
        assert count == 1

    def test_dump_backend_db(self, db: Database) -> None:
        vs = VectorStore(database=db)
        d = vs.dump()
        assert d["backend"] == "db"
        assert "store_dir" not in d

    def test_get_com_metadata(self, db: Database) -> None:
        vs = VectorStore(database=db)
        vs.add("ns", "teste", metadata={"source": "doc1"})
        all_ns = vs.list_namespaces()
        doc_id = None
        for ns in all_ns:
            results = vs.search(ns, "teste", top_k=1)
            if results:
                doc_id = results[0].doc_id
                break
        if doc_id:
            doc = vs.get(doc_id)
            assert doc is not None
            assert doc["metadata"]["source"] == "doc1"


# ---------------------------------------------------------------------------
# Adapter: ensure_tables
# ---------------------------------------------------------------------------


class TestAdaptersEnsureTables:
    def test_creates_all_tables(self, db: Database) -> None:
        tables = db.tables()
        for name in ("conversation_messages", "llm_cache", "quick_responses", "vector_documents"):
            assert name in tables

    def test_idempotent(self, db: Database) -> None:
        # Segunda chamada nao deve dar erro
        ensure_tables(db)
        ensure_tables(db)
        assert len(db.tables()) == 4


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------


class TestMigration:
    def test_migrate_history(self, db: Database, tmp_path: Path) -> None:
        conv_dir = tmp_path / "conversations" / "alex"
        conv_dir.mkdir(parents=True)
        data = {
            "user_id": "alex",
            "profile": "guardian",
            "messages": [
                {"role": "user", "content": "oi", "ts": 1.0, "llm_used": ""},
                {"role": "assistant", "content": "ola!", "ts": 2.0, "llm_used": "gemma"},
            ],
        }
        (conv_dir / "guardian.json").write_text(json.dumps(data))
        count = migrate_history(db, tmp_path / "conversations")
        assert count == 2
        # Idempotente
        count2 = migrate_history(db, tmp_path / "conversations")
        assert count2 == 0

    def test_migrate_cache(self, db: Database, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache.json"
        data = {
            "entries": [
                {"key": "abc", "prompt": "oi", "response": "ola", "profile": "",
                 "llm_used": "", "tokens_used": 0, "use_count": 1, "duplicates": 0,
                 "created_ts": 1.0, "last_used_ts": 1.0, "avg_response_time_ms": 0.0},
            ]
        }
        cache_file.write_text(json.dumps(data))
        count = migrate_cache(db, cache_file)
        assert count == 1
        # Idempotente
        assert migrate_cache(db, cache_file) == 0

    def test_migrate_quick_responses(self, db: Database, tmp_path: Path) -> None:
        qr_file = tmp_path / "quick_responses.json"
        data = {
            "responses": [
                {"pattern": "oi", "responses": ["Oi!", "Ola!"], "category": "",
                 "profile": "", "priority": 0, "current_index": 0, "use_count": 0,
                 "last_used_ts": None, "avg_response_time_ms": 0.0},
            ]
        }
        qr_file.write_text(json.dumps(data))
        count = migrate_quick_responses(db, qr_file)
        assert count == 1
        assert migrate_quick_responses(db, qr_file) == 0

    def test_migrate_vector(self, db: Database, tmp_path: Path) -> None:
        vs_file = tmp_path / "vector_store.json"
        data = {
            "documents": [
                {"doc_id": "abc123", "namespace": "docs", "text": "teste",
                 "vector": [0.1, 0.2], "metadata": {"src": "test"},
                 "created_ts": 1.0},
            ]
        }
        vs_file.write_text(json.dumps(data))
        count = migrate_vector(db, vs_file)
        assert count == 1
        assert migrate_vector(db, vs_file) == 0

    def test_migrate_all(self, db: Database, tmp_path: Path) -> None:
        # Create minimal JSON data for each module
        hist_dir = tmp_path / "conversations" / "u1"
        hist_dir.mkdir(parents=True)
        (hist_dir / "guardian.json").write_text(json.dumps({
            "messages": [{"role": "user", "content": "x", "ts": 1.0}]
        }))
        (tmp_path / "cache.json").write_text(json.dumps({"entries": []}))
        (tmp_path / "quick_responses.json").write_text(json.dumps({"responses": []}))
        (tmp_path / "vector_store.json").write_text(json.dumps({"documents": []}))

        result = migrate_all(
            db,
            history_dir=tmp_path / "conversations",
            cache_dir=tmp_path / "cache.json",
            quick_dir=tmp_path / "quick_responses.json",
            vector_dir=tmp_path / "vector_store.json",
        )
        assert result["conversation_messages"] == 1
        assert result["llm_cache"] == 0

    def test_migrate_missing_dirs(self, db: Database, tmp_path: Path) -> None:
        assert migrate_history(db, tmp_path / "nonexistent") == 0
        assert migrate_cache(db, tmp_path / "nonexistent.json") == 0
        assert migrate_quick_responses(db, tmp_path / "nonexistent.json") == 0
        assert migrate_vector(db, tmp_path / "nonexistent.json") == 0
