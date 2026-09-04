"""
OMEGA DRAKON • STORAGE
Tecnologia que respira.
Módulo: storage/database.py
Descrição: Database Layer (Fase 7, item 7.5) — camada de persistência
           relacional em SQLite (stdlib puro, sem SQLAlchemy): pool de
           conexões thread-safe (acquire/release), execução e transações,
           repositórios genéricos CRUD com schema declarativo, helpers
           (tables/table_info/scalar), métricas, health() e dump().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/database/ (DatabaseManager — pool + repositórios,
    NV_LEGACY_ANALYSIS §3.x)
  - tools/actions/actions.py (actions de banco — Fase 7.5)
  - ROADMAP_ABSORCAO.md Fase 7, item 7.5

Decisões registradas (ver CHANGELOG):
  - SQLite via stdlib (sem SQLAlchemy/aiosqlite) — mitigação do roadmap
    "preferir stdlib; isolar em adapters"
  - Pool de conexões por fila (queue.Queue) com check_same_thread=False:
    acquire/release serializa o acesso; quando o pool esgota, acquire
    bloqueia até uma conexão ser liberada (sem estouro de conexões)
  - Repository genérico com schema declarativo ({coluna: tipo SQL}) e
    CRUD tipado; a execução arbitrária de SQL fica na camada (actions de
    banco do catálogo passam a funcionar quando o Database é injetado)
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.storage.database")

# Backends suportados pela Database Layer.
BACKEND_SQLITE = "sqlite"
BACKEND_POSTGRES = "postgres"


def is_postgres_dsn(dsn: str) -> bool:
    """True se o DSN aponta para um PostgreSQL (postgres:// ou postgresql://)."""
    return dsn.strip().lower().startswith(("postgres://", "postgresql://"))


class DatabaseError(Exception):
    """Erro da camada de banco de dados."""


@dataclass(slots=True)
class DatabaseMetrics:
    """Métricas acumuladas da Database Layer."""

    queries: int = 0
    writes: int = 0
    transactions: int = 0
    commits: int = 0
    rollbacks: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "queries": self.queries,
            "writes": self.writes,
            "transactions": self.transactions,
            "commits": self.commits,
            "rollbacks": self.rollbacks,
            "errors": self.errors,
            "avg_latency_ms": round(
                self.total_latency_ms / self.queries if self.queries else 0.0,
                3,
            ),
        }


# ---------------------------------------------------------------------------
# ConnectionPool
# ---------------------------------------------------------------------------

class ConnectionPool:
    """Pool de conexões SQLite thread-safe (fila com criação sob demanda)."""

    def __init__(
        self,
        path: Union[str, Path] = ":memory:",
        *,
        size: int = 5,
    ) -> None:
        self._path = str(path)
        self._size = max(1, int(size))
        # :memory: usa URI única por pool — cada conexão enxerga o MESMO
        # banco (senão cada conexão teria um banco vazio separado e
        # transações/queries entre conexões quebrariam)
        self._connect_path = (
            f"file:od_mem_{uuid.uuid4().hex}?mode=memory&cache=shared"
            if self._path == ":memory:"
            else self._path
        )
        self._queue: "queue.Queue[sqlite3.Connection]" = queue.Queue(
            maxsize=self._size
        )
        self._conns: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._closed = False

    @property
    def path(self) -> str:
        return self._path

    def acquire(self) -> sqlite3.Connection:
        """Pega uma conexão do pool (cria sob demanda; bloqueia se esgotado)."""
        if self._closed:
            raise DatabaseError("pool fechado")
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if len(self._conns) < self._size:
                conn = self._create()
                self._conns.append(conn)
                return conn
        # Pool esgotado: aguarda uma liberação (sem estourar conexões)
        return self._queue.get()

    def release(self, conn: sqlite3.Connection) -> None:
        """Devolve a conexão ao pool (fecha se o pool estiver cheio)."""
        try:
            self._queue.put_nowait(conn)
        except queue.Full:
            self._close_conn(conn)

    def close(self) -> None:
        """Fecha todas as conexões do pool."""
        self._closed = True
        with self._lock:
            for conn in self._conns:
                self._close_conn(conn)
            self._conns.clear()
        # esvazia a fila
        while True:
            try:
                self._close_conn(self._queue.get_nowait())
            except queue.Empty:
                break

    def _create(self) -> sqlite3.Connection:
        parent = Path(self._path).parent
        if self._path != ":memory:" and str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self._connect_path,
            uri=self._path == ":memory:",
            check_same_thread=False,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        if self._path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _close_conn(conn: sqlite3.Connection) -> None:
        try:
            conn.close()
        except Exception:  # pragma: no cover — close defensivo
            pass


# ---------------------------------------------------------------------------
# PostgresConnectionPool (pg8000 — driver Python puro)
# ---------------------------------------------------------------------------

class PostgresConnectionPool:
    """Pool de conexões PostgreSQL (pg8000) — mesma interface do
    ConnectionPool (acquire/release/close), com criação sob demanda e
    fila bloqueante quando esgotado.
    """

    def __init__(self, dsn: str, *, size: int = 5) -> None:
        self._dsn = dsn
        self._size = max(1, int(size))
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=self._size)
        self._conns: list[Any] = []
        self._lock = threading.Lock()
        self._closed = False

    @property
    def path(self) -> str:
        return self._dsn

    def acquire(self) -> Any:
        """Pega uma conexão do pool (cria sob demanda; bloqueia se esgotado)."""
        if self._closed:
            raise DatabaseError("pool fechado")
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if len(self._conns) < self._size:
                conn = self._create()
                self._conns.append(conn)
                return conn
        return self._queue.get()

    def release(self, conn: Any) -> None:
        try:
            self._queue.put_nowait(conn)
        except queue.Full:
            self._close_conn(conn)

    def close(self) -> None:
        self._closed = True
        with self._lock:
            for conn in self._conns:
                self._close_conn(conn)
            self._conns.clear()
        while True:
            try:
                self._close_conn(self._queue.get_nowait())
            except queue.Empty:
                break

    def _create(self) -> Any:
        import pg8000.dbapi

        parsed = urllib.parse.urlparse(self._dsn)
        raw = pg8000.dbapi.connect(
            user=urllib.parse.unquote(parsed.username or ""),
            password=urllib.parse.unquote(parsed.password or ""),
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 5432,
            database=(parsed.path or "/").lstrip("/"),
        )
        return _PgConn(raw)

    @staticmethod
    def _close_conn(conn: Any) -> None:
        try:
            conn.close()
        except Exception:  # pragma: no cover — close defensivo
            pass


class _PgConn:
    """Wrapper de conexão pg8000 com a MESMA superfície usada pelo
    Database (execute/executemany/commit/rollback/close) — o pg8000 exige
    cursor para executar, o sqlite3.Connection executa direto."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        cur = self._raw.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq: list[tuple[Any, ...]]) -> Any:
        cur = self._raw.cursor()
        cur.executemany(sql, seq)
        return cur

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    """Camada de persistência relacional (Fase 7, item 7.5).

    Uso típico:
        db = Database("data/od.db")
        db.create_table("users", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"})
        db.execute("INSERT INTO users (name) VALUES (?)", ("Nicky",))

        repo = db.repository("users")
        repo.insert({"name": "Alex"})

    Conexões vêm do ConnectionPool; toda operação adquire/release.
    """

    def __init__(
        self,
        path: Union[str, Path] = ":memory:",
        *,
        dsn: Optional[str] = None,
        pool_size: int = 5,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        """Camada de persistência relacional com backend plugável.

        - SQLite (default): `Database("data/od.db")` — stdlib puro;
        - PostgreSQL: `Database(dsn="postgres://user:pass@host:port/db")`
          via driver pg8000 (Python puro, sem extensão nativa).
        """
        if dsn:
            if not is_postgres_dsn(dsn):
                raise DatabaseError(
                    "dsn deve ser postgres:// ou postgresql:// "
                    "(backend PostgreSQL)"
                )
            self.backend = BACKEND_POSTGRES
            self._pool = PostgresConnectionPool(dsn, size=pool_size)
        else:
            self.backend = BACKEND_SQLITE
            self._pool = ConnectionPool(path, size=pool_size)
        self._metrics = DatabaseMetrics()
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        # Conexão ativa da transação corrente (por thread): operações
        # dentro de `with db.transaction()` usam a MESMA conexão — sem
        # isso, execute/query committariam fora da transação
        self._local = threading.local()

    @property
    def path(self) -> str:
        return self._pool.path

    @property
    def metrics(self) -> DatabaseMetrics:
        return self._metrics

    def _ph(self, sql: str) -> str:
        """Ajusta os placeholders ao backend (? = SQLite, %s = PostgreSQL)."""
        if self.backend == BACKEND_POSTGRES:
            return sql.replace("?", "%s")
        return sql

    @staticmethod
    def _error_types() -> tuple[type[Exception], ...]:
        """Tipos de erro nativos dos backends suportados."""
        types: list[type[Exception]] = [sqlite3.Error]
        try:
            import pg8000.dbapi

            types.append(pg8000.dbapi.Error)
        except ImportError:  # pragma: no cover — pg8000 opcional
            pass
        return tuple(types)

    # -- Execução -------------------------------------------------------------

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Executa uma instrução de escrita (commita). Retorna rowcount.

        Dentro de `with db.transaction()` usa a conexão da transação
        (o commit fica a cargo do contexto).
        """
        started = self._clock()
        conn, owned = self._conn_for_op()
        try:
            cursor = conn.execute(self._ph(sql), params)
            if owned:
                conn.commit()
            with self._lock:
                self._metrics.writes += 1
            return int(cursor.rowcount)
        except self._error_types() as exc:
            with self._lock:
                self._metrics.errors += 1
            log.warn("DB execute falhou", error=str(exc), sql=sql[:120])
            raise DatabaseError(str(exc)) from exc
        finally:
            if owned:
                self._pool.release(conn)
            self._count_query(started)

    def executemany(self, sql: str, seq: list[tuple[Any, ...]]) -> int:
        """Executa em lote (commita). Retorna rowcount total."""
        started = self._clock()
        conn, owned = self._conn_for_op()
        try:
            cursor = conn.executemany(self._ph(sql), seq)
            if owned:
                conn.commit()
            with self._lock:
                self._metrics.writes += 1
            return int(cursor.rowcount)
        except self._error_types() as exc:
            with self._lock:
                self._metrics.errors += 1
            log.warn("DB executemany falhou", error=str(exc))
            raise DatabaseError(str(exc)) from exc
        finally:
            if owned:
                self._pool.release(conn)
            self._count_query(started)

    def query(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Executa uma consulta e devolve linhas como dicts."""
        started = self._clock()
        conn, owned = self._conn_for_op()
        try:
            cursor = conn.execute(self._ph(sql), params)
            if self.backend == BACKEND_POSTGRES:
                raw = cursor.fetchmany(limit) if limit else cursor.fetchall()
                columns = [d[0] for d in (cursor.description or ())]
                rows = [dict(zip(columns, row)) for row in raw]
            else:
                rows = cursor.fetchmany(limit) if limit else cursor.fetchall()
                rows = [dict(row) for row in rows]
            return rows
        except self._error_types() as exc:
            with self._lock:
                self._metrics.errors += 1
            log.warn("DB query falhou", error=str(exc), sql=sql[:120])
            raise DatabaseError(str(exc)) from exc
        finally:
            if owned:
                self._pool.release(conn)
            self._count_query(started)

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        """Primeiro valor da primeira linha (None se vazio)."""
        rows = self.query(sql, params, limit=1)
        if not rows:
            return None
        return next(iter(rows[0].values()))

    # -- Transação ------------------------------------------------------------

    def transaction(self) -> "_Transaction":
        """Context manager de transação: commit no fim, rollback em erro."""
        return _Transaction(self)

    # -- Schema ---------------------------------------------------------------

    def create_table(
        self,
        table: str,
        schema: dict[str, str],
        *,
        if_not_exists: bool = True,
    ) -> None:
        """Cria uma tabela a partir de {coluna: tipo SQL}.

        No PostgreSQL, `INTEGER PRIMARY KEY` (idioma SQLite) é traduzido
        para `SERIAL PRIMARY KEY` (auto-incremento nativo).
        """
        if self.backend == BACKEND_POSTGRES:
            schema = {
                name: type_.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
                for name, type_ in schema.items()
            }
        columns = ", ".join(f"{name} {type_}" for name, type_ in schema.items())
        clause = "IF NOT EXISTS " if if_not_exists else ""
        self.execute(f"CREATE TABLE {clause}{table} ({columns})")
        return True

    def tables(self) -> list[str]:
        """Tabelas do banco (sem internos do backend)."""
        if self.backend == BACKEND_POSTGRES:
            rows = self.query(
                "SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY name"
            )
        else:
            rows = self.query(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        return [row["name"] for row in rows]

    def table_info(self, table: str) -> list[dict[str, Any]]:
        """Colunas de uma tabela (PRAGMA / information_schema)."""
        try:
            if self.backend == BACKEND_POSTGRES:
                return self.query(
                    "SELECT column_name AS name, data_type AS type "
                    "FROM information_schema.columns "
                    "WHERE table_name = %s ORDER BY ordinal_position",
                    (table,),
                )
            return self.query(f"PRAGMA table_info({table})")
        except DatabaseError:  # tabela inexistente
            return []

    # -- Repositórios ---------------------------------------------------------

    def repository(
        self,
        table: str,
        schema: Optional[dict[str, str]] = None,
        *,
        pk: str = "id",
    ) -> "Repository":
        """Repositório CRUD genérico sobre uma tabela."""
        return Repository(self, table, schema=schema, pk=pk)

    # -- Saúde e introspecção -------------------------------------------------

    def health(self) -> dict[str, Any]:
        try:
            ok = self.scalar("SELECT 1") == 1
        except DatabaseError:
            ok = False
        return {
            "ok": ok,
            "status": "ok" if ok else "down",
            "path": self.path,
            "tables": len(self.tables()),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "path": self.path,
                "tables": len(self.tables()),
                "metrics": self._metrics.snapshot(),
            }

    def dump(self) -> dict[str, Any]:
        data = self.snapshot()
        data["table_names"] = self.tables()
        return data

    def close(self) -> None:
        self._pool.close()

    # -- Internos -------------------------------------------------------------

    def _count_query(self, started: float) -> None:
        latency = (self._clock() - started) * 1000.0
        with self._lock:
            self._metrics.queries += 1
            self._metrics.total_latency_ms += latency

    def _conn_for_op(self) -> tuple[sqlite3.Connection, bool]:
        """Conexão da transação ativa (owned=False) ou nova do pool."""
        active = getattr(self._local, "tx_conn", None)
        if active is not None:
            return active, False
        return self._pool.acquire(), True

    def _begin(self) -> Any:
        conn = self._pool.acquire()
        if getattr(conn, "in_transaction", False):
            conn.rollback()
        conn.execute("BEGIN")
        self._local.tx_conn = conn
        return conn

    def _order_identity(self) -> str:
        """Expressão de ordenação 'ordem de inserção' por backend."""
        return "rowid" if self.backend == BACKEND_SQLITE else "1"


# ---------------------------------------------------------------------------
# _Transaction
# ---------------------------------------------------------------------------

class _Transaction:
    """Context manager: commit no sucesso, rollback em exceção.

    As operações executadas dentro do bloco usam a conexão da transação
    (afinidade por thread) — o commit/rollback acontece apenas aqui.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "_Transaction":
        self._conn = self._db._begin()
        with self._db._lock:
            self._db._metrics.transactions += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        conn = self._conn
        try:
            if exc_type is None:
                conn.commit()
                with self._db._lock:
                    self._db._metrics.commits += 1
            else:
                conn.rollback()
                with self._db._lock:
                    self._db._metrics.rollbacks += 1
            return False
        finally:
            self._db._local.tx_conn = None
            self._db._pool.release(conn)
            self._conn = None


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class Repository:
    """Repositório CRUD genérico sobre uma tabela (Fase 7.5).

    Uso típico:
        repo = db.repository("users", {"id": "INTEGER PRIMARY KEY",
                                       "name": "TEXT"})
        repo.insert({"name": "Nicky"})
        repo.get(1)          # {"id": 1, "name": "Nicky"}
        repo.update(1, {"name": "Nicky Virthy"})
        repo.find(name="Nicky Virthy")
    """

    def __init__(
        self,
        db: Database,
        table: str,
        *,
        schema: Optional[dict[str, str]] = None,
        pk: str = "id",
    ) -> None:
        self._db = db
        self.table = table
        self.pk = pk
        if schema:
            db.create_table(table, schema)

    def insert(self, record: dict[str, Any]) -> Any:
        """Insere um registro; devolve o valor da pk (ou rowcount)."""
        if not record:
            raise DatabaseError("registro vazio")
        columns = list(record)
        placeholders = ", ".join("?" for _ in columns)
        values = tuple(record[c] for c in columns)
        sql = (
            f"INSERT INTO {self.table} ({', '.join(columns)}) "
            f"VALUES ({placeholders})"
        )
        if self.pk in record:
            self._db.execute(sql, values)
            return record[self.pk]
        if self._db.backend == BACKEND_POSTGRES:
            # RETURNING devolve a pk gerada (SERIAL) numa única ida.
            return self._db.scalar(
                f"{sql} RETURNING {self.pk}", values
            )
        self._db.execute(sql, values)
        return self._db.scalar("SELECT last_insert_rowid()")

    def get(self, pk: Any) -> Optional[dict[str, Any]]:
        """Busca pela chave primária (None se não existe)."""
        rows = self._db.query(
            f"SELECT * FROM {self.table} WHERE {self.pk} = ?",
            (pk,),
            limit=1,
        )
        return rows[0] if rows else None

    def update(self, pk: Any, fields: dict[str, Any]) -> bool:
        """Atualiza campos de um registro. Retorna True se alterou."""
        if not fields:
            return False
        assignments = ", ".join(f"{col} = ?" for col in fields)
        rowcount = self._db.execute(
            f"UPDATE {self.table} SET {assignments} WHERE {self.pk} = ?",
            tuple(fields.values()) + (pk,),
        )
        return rowcount > 0

    def delete(self, pk: Any) -> bool:
        """Remove um registro. Retorna True se removeu."""
        rowcount = self._db.execute(
            f"DELETE FROM {self.table} WHERE {self.pk} = ?", (pk,)
        )
        return rowcount > 0

    def all(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Todos os registros (em ordem de inserção)."""
        sql = f"SELECT * FROM {self.table} ORDER BY {self._db._order_identity()}"
        return self._db.query(sql, limit=limit)

    def find(self, **filters: Any) -> list[dict[str, Any]]:
        """Registros que casam com coluna = valor (AND)."""
        if not filters:
            return self.all()
        clauses = " AND ".join(f"{col} = ?" for col in filters)
        return self._db.query(
            f"SELECT * FROM {self.table} WHERE {clauses}",
            tuple(filters.values()),
        )

    def count(self) -> int:
        """Quantidade de registros na tabela."""
        value = self._db.scalar(f"SELECT COUNT(*) FROM {self.table}")
        return int(value or 0)

    def exists(self, pk: Any) -> bool:
        """A pk existe na tabela?"""
        return self.get(pk) is not None