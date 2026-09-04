"""
OMEGA DRAKON • TESTS
Módulo: tests/test_database.py
Descrição: Testes da Database Layer (storage/database.py) — Fase 7, item
           7.5: Database (execute/query/scalar, create_table, tables/
           table_info, transações commit/rollback, métricas, health),
           ConnectionPool (acquire/release, close), Repository (CRUD
           genérico, schema auto-criado, find/count/exists), persistência
           em arquivo entre instâncias e integração com as actions de
           banco do catálogo (configure_database).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/database/ (DatabaseManager — NV_LEGACY_ANALYSIS §3.x)
  - tools/actions/actions.py (actions de banco — Fase 7.5)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.5
"""

from __future__ import annotations

import pytest

from storage import ConnectionPool, Database, DatabaseError, Repository
from tools.actions import (
    configure_database,
    database_query,
    database_schema,
    database_tables,
)


@pytest.fixture()
def db():
    database = Database()
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class TestDatabase:
    """Execução, schema, transações e introspecção."""

    def test_execute_query_scalar(self, db):
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, nome TEXT)")
        db.execute("INSERT INTO t (nome) VALUES (?)", ("Nicky",))
        db.execute("INSERT INTO t (nome) VALUES (?)", ("Alex",))
        rows = db.query("SELECT * FROM t ORDER BY id")
        assert [r["nome"] for r in rows] == ["Nicky", "Alex"]
        assert db.scalar("SELECT COUNT(*) FROM t") == 2
        assert db.scalar("SELECT nome FROM t WHERE id = 1") == "Nicky"

    def test_execute_returns_rowcount(self, db):
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, nome TEXT)")
        assert db.execute("INSERT INTO t (nome) VALUES (?)", ("x",)) == 1

    def test_query_limit(self, db):
        db.execute("CREATE TABLE t (v INTEGER)")
        db.executemany("INSERT INTO t (v) VALUES (?)", [(i,) for i in range(10)])
        rows = db.query("SELECT v FROM t", limit=3)
        assert len(rows) == 3

    def test_create_table_and_tables(self, db):
        db.create_table("users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"})
        assert db.tables() == ["users"]
        assert db.create_table("users", {"id": "INTEGER PRIMARY KEY"})  # IF NOT EXISTS

    def test_table_info(self, db):
        db.create_table("users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"})
        columns = db.table_info("users")
        names = [c["name"] for c in columns]
        assert names == ["id", "name"]
        assert db.table_info("nao_existe") == []

    def test_sql_error_raises_database_error(self, db):
        with pytest.raises(DatabaseError):
            db.query("SELECT * FROM nao_existe")
        assert db.metrics.errors == 1

    def test_metrics(self, db):
        db.execute("CREATE TABLE t (v INTEGER)")
        db.execute("INSERT INTO t (v) VALUES (1)")
        db.query("SELECT * FROM t")
        snap = db.metrics.snapshot()
        assert snap["queries"] >= 3  # create_table + insert + select
        assert snap["writes"] >= 2
        assert snap["avg_latency_ms"] >= 0.0

    def test_health_and_snapshot(self, db):
        db.execute("CREATE TABLE t (v INTEGER)")
        health = db.health()
        assert health["ok"] is True
        assert health["tables"] == 1
        snap = db.snapshot()
        assert snap["tables"] == 1
        dump = db.dump()
        assert dump["table_names"] == ["t"]


class TestTransactions:
    """Commit no sucesso, rollback em erro."""

    def test_commit_on_success(self, db):
        db.execute("CREATE TABLE t (v INTEGER)")
        with db.transaction():
            db.execute("INSERT INTO t (v) VALUES (1)")
            db.execute("INSERT INTO t (v) VALUES (2)")
        assert db.scalar("SELECT COUNT(*) FROM t") == 2
        assert db.metrics.commits == 1
        assert db.metrics.rollbacks == 0

    def test_rollback_on_error(self, db):
        db.execute("CREATE TABLE t (v INTEGER)")
        with pytest.raises(DatabaseError):
            with db.transaction():
                db.execute("INSERT INTO t (v) VALUES (1)")
                db.execute("INSERT INTO t (v) VALUES (2)")
                db.query("SELECT * FROM nao_existe")  # erro dentro da tx
        assert db.scalar("SELECT COUNT(*) FROM t") == 0  # rollback total
        assert db.metrics.rollbacks == 1


class TestConnectionPool:
    """Pool: acquire/release funcional e close limpo."""

    def test_acquire_release_roundtrip(self):
        pool = ConnectionPool()
        conn = pool.acquire()
        row = conn.execute("SELECT 1 AS x").fetchone()
        assert row["x"] == 1
        pool.release(conn)
        pool.close()

    def test_acquire_after_close_raises(self):
        pool = ConnectionPool()
        pool.close()
        with pytest.raises(DatabaseError):
            pool.acquire()


class TestPersistence:
    """Banco em arquivo sobrevive entre instâncias."""

    def test_file_persists_between_instances(self, tmp_path):
        path = tmp_path / "od.db"
        first = Database(path)
        first.execute("CREATE TABLE t (v INTEGER)")
        first.execute("INSERT INTO t (v) VALUES (42)")
        first.close()

        second = Database(path)
        try:
            assert second.scalar("SELECT v FROM t") == 42
        finally:
            second.close()

    def test_memory_db_is_isolated(self):
        a = Database()
        b = Database()
        a.execute("CREATE TABLE t (v INTEGER)")
        assert b.tables() == []
        a.close()
        b.close()


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class TestRepository:
    """CRUD genérico com schema declarativo."""

    def test_insert_get(self, db):
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        pk = repo.insert({"name": "Nicky"})
        assert pk == 1
        row = repo.get(1)
        assert row["name"] == "Nicky"
        assert repo.exists(1) is True
        assert repo.exists(99) is False

    def test_insert_with_explicit_pk(self, db):
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        assert repo.insert({"id": 7, "name": "Alex"}) == 7
        assert repo.get(7)["name"] == "Alex"

    def test_update(self, db):
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        repo.insert({"name": "Nicky"})
        assert repo.update(1, {"name": "Nicky Virthy"}) is True
        assert repo.get(1)["name"] == "Nicky Virthy"
        assert repo.update(99, {"name": "x"}) is False

    def test_delete(self, db):
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        repo.insert({"name": "a"})
        repo.insert({"name": "b"})
        assert repo.delete(1) is True
        assert repo.delete(1) is False
        assert repo.count() == 1

    def test_all_and_find(self, db):
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "perfil": "TEXT"}
        )
        repo.insert({"name": "a", "perfil": "guardian"})
        repo.insert({"name": "b", "perfil": "nyx"})
        repo.insert({"name": "c", "perfil": "guardian"})
        assert repo.count() == 3
        assert len(repo.all()) == 3
        found = repo.find(perfil="guardian")
        assert len(found) == 2
        assert len(repo.find(name="b")) == 1
        assert repo.find(perfil="nada") == []

    def test_repository_without_schema_uses_existing_table(self, db):
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        repo = Repository(db, "t")
        repo.insert({"v": "ok"})
        assert repo.get(1)["v"] == "ok"

    def test_empty_insert_raises(self, db):
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        repo = Repository(db, "t")
        with pytest.raises(DatabaseError):
            repo.insert({})


# ---------------------------------------------------------------------------
# Integração com as actions do catálogo
# ---------------------------------------------------------------------------

class TestDatabaseActions:
    """configure_database liga as actions de banco à camada real."""

    @pytest.fixture()
    def reset_db(self):
        yield
        configure_database(None)  # não vaza para outros testes

    def test_actions_without_database_degrade(self):
        configure_database(None)
        result = database_tables()
        assert result["ok"] is False
        assert "Fase 7.5" in result["error"]

    def test_actions_work_with_database(self, db, reset_db):
        db.create_table("users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"})
        configure_database(db)
        tables = database_tables()
        assert tables["ok"] is True
        assert tables["tables"] == ["users"]
        schema = database_schema("users")
        assert schema["ok"] is True
        assert [c["name"] for c in schema["columns"]] == ["id", "name"]
        query = database_query("SELECT COUNT(*) AS n FROM users")
        assert query["ok"] is True
        assert query["rows"][0]["n"] == 0

    def test_database_query_error_reported(self, db, reset_db):
        configure_database(db)
        result = database_query("SELECT * FROM nao_existe")
        assert result["ok"] is False
        assert result["error"]