"""
OMEGA DRAKON • TESTS
Módulo: tests/test_database_postgres.py
Descrição: Testes do backend PostgreSQL da Database Layer (v0.28.0) —
           mesmo contrato do SQLite (pool, execução, transações, schema,
           Repository CRUD), agora sobre pg8000 (driver Python puro).

           Herança de teste: `OD_TEST_POSTGRES_DSN` (postgres://...) — sem
           a variável, a suíte é pulada (pytest.skip). Para rodar:
             OD_TEST_POSTGRES_DSN=postgres://od:od@127.0.0.1:55432/od \\
               .venv/bin/python -m pytest tests/test_database_postgres.py -q
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - storage/database.py (Database/Repository com backend plugável)
  - tests/test_database.py (contrato SQLite equivalente)
"""

from __future__ import annotations

import os

import pytest

from storage.database import Database, DatabaseError

DSN = os.environ.get("OD_TEST_POSTGRES_DSN", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="defina OD_TEST_POSTGRES_DSN (postgres://...) para rodar os "
           "testes do backend PostgreSQL",
)


@pytest.fixture()
def db() -> Database:
    database = Database(dsn=DSN, pool_size=3)
    # limpa tabelas de teste entre fixtures
    for table in ("items", "users", "tx_test"):
        try:
            database.execute(f"DROP TABLE IF EXISTS {table}")
        except DatabaseError:  # pragma: no cover
            pass
    yield database
    database.close()


class TestPostgresBackend:
    """Backend detectado, DSN inválido e operações básicas."""

    def test_backend_detectado(self, db: Database) -> None:
        assert db.backend == "postgres"
        assert db.path.startswith("postgres://")

    def test_dsn_invalido_erro(self) -> None:
        with pytest.raises(DatabaseError):
            Database(dsn="mysql://user:pass@host/db")

    def test_health_select_1(self, db: Database) -> None:
        health = db.health()
        assert health["ok"] is True
        assert health["status"] == "ok"

    def test_create_table_e_tables(self, db: Database) -> None:
        db.create_table("items", {"id": "INTEGER PRIMARY KEY", "nome": "TEXT"})
        assert "items" in db.tables()

    def test_table_info(self, db: Database) -> None:
        db.create_table("items", {"id": "INTEGER PRIMARY KEY", "nome": "TEXT"})
        info = db.table_info("items")
        names = {row["name"] for row in info}
        assert {"id", "nome"} <= names

    def test_execute_e_query_params(self, db: Database) -> None:
        db.create_table("items", {"id": "INTEGER PRIMARY KEY", "nome": "TEXT"})
        db.execute("INSERT INTO items (nome) VALUES (%s)", ("nicky",))
        rows = db.query("SELECT * FROM items WHERE nome = %s", ("nicky",))
        assert rows[0]["nome"] == "nicky"

    def test_scalar(self, db: Database) -> None:
        db.create_table("items", {"id": "INTEGER PRIMARY KEY", "nome": "TEXT"})
        db.execute("INSERT INTO items (nome) VALUES (%s)", ("a",))
        db.execute("INSERT INTO items (nome) VALUES (%s)", ("b",))
        assert db.scalar("SELECT COUNT(*) FROM items") == 2

    def test_executemany(self, db: Database) -> None:
        db.create_table("items", {"id": "INTEGER PRIMARY KEY", "nome": "TEXT"})
        db.executemany(
            "INSERT INTO items (nome) VALUES (%s)",
            [("a",), ("b",), ("c",)],
        )
        assert db.scalar("SELECT COUNT(*) FROM items") == 3

    def test_query_erro_vira_database_error(self, db: Database) -> None:
        with pytest.raises(DatabaseError):
            db.query("SELECT * FROM tabela_que_nao_existe")


class TestPostgresTransactions:
    """Transações: commit no sucesso, rollback em exceção (afinidade)."""

    def test_transaction_commit(self, db: Database) -> None:
        db.create_table("tx_test", {"id": "INTEGER PRIMARY KEY", "v": "INTEGER"})
        with db.transaction():
            db.execute("INSERT INTO tx_test (v) VALUES (%s)", (1,))
        assert db.scalar("SELECT COUNT(*) FROM tx_test") == 1

    def test_transaction_rollback(self, db: Database) -> None:
        db.create_table("tx_test", {"id": "INTEGER PRIMARY KEY", "v": "INTEGER"})
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.execute("INSERT INTO tx_test (v) VALUES (%s)", (1,))
                raise RuntimeError("boom")
        assert db.scalar("SELECT COUNT(*) FROM tx_test") == 0

    def test_metrics_transacao(self, db: Database) -> None:
        db.create_table("tx_test", {"id": "INTEGER PRIMARY KEY", "v": "INTEGER"})
        with db.transaction():
            db.execute("INSERT INTO tx_test (v) VALUES (%s)", (1,))
        snap = db.metrics.snapshot()
        assert snap["transactions"] == 1
        assert snap["commits"] == 1


class TestPostgresRepository:
    """Repository CRUD genérico sobre PostgreSQL (RETURNING + ORDER BY)."""

    def test_insert_retorna_pk_gerada(self, db: Database) -> None:
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        user_id = repo.insert({"name": "Nicky"})
        assert user_id == 1  # SERIAL começa em 1
        assert repo.get(user_id) == {"id": 1, "name": "Nicky"}

    def test_insert_com_pk_explicita(self, db: Database) -> None:
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        assert repo.insert({"id": 42, "name": "Alex"}) == 42

    def test_crud_completo(self, db: Database) -> None:
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        uid = repo.insert({"name": "A"})
        repo.insert({"name": "B"})
        assert repo.count() == 2
        assert repo.exists(uid)
        assert repo.update(uid, {"name": "A2"})
        assert repo.get(uid)["name"] == "A2"
        assert [r["name"] for r in repo.all()] == ["A2", "B"]
        assert [r["name"] for r in repo.find(name="B")] == ["B"]
        assert repo.delete(uid)
        assert not repo.exists(uid)
        assert repo.count() == 1

    def test_all_ordem_de_insercao(self, db: Database) -> None:
        repo = db.repository(
            "users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        for name in ("primeiro", "segundo", "terceiro"):
            repo.insert({"name": name})
        assert [r["name"] for r in repo.all()] == [
            "primeiro", "segundo", "terceiro",
        ]