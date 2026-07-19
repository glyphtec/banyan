from __future__ import annotations

import atexit
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from banyan_platform.config import DatabaseConfig


class Database(ABC):
    """
    Abstract connection provider.

    Concrete implementations expose a ``connect()`` context manager that yields
    an open connection wrapped in an explicit transaction.  Callers commit on
    success; any unhandled exception triggers a rollback.

    ``placeholder`` is the SQL parameter substitution character used by this
    backend ('?' for DuckDB, '%s' for psycopg/PostgreSQL).  DAOs must use it
    when building parameterised queries.
    """

    placeholder: str

    @contextmanager
    @abstractmethod
    def connect(self):
        """Yield a transactional connection for this backend."""
        ...


class DuckDBDatabase(Database):
    """Local / dev backend.  A single DuckDB connection is reused per instance."""

    placeholder = "?"

    def __init__(self, config: DatabaseConfig) -> None:
        self._path = config.duckdb_path
        self._conn = None
        self._lock = threading.Lock()
        # Ensure the connection is closed cleanly on process exit (including
        # Ctrl+C / KeyboardInterrupt).  Without this, DuckDB leaves the WAL
        # file uncheckpointed, causing "Failure while replaying WAL file" on
        # the next startup.
        atexit.register(self._close)

    def _close(self) -> None:
        """Close the DuckDB connection and checkpoint the WAL."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def _get_conn(self):
        if self._conn is None:
            try:
                import duckdb  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "Install duckdb (pip install duckdb) to use the duckdb backend."
                ) from exc
            self._conn = duckdb.connect(self._path)
        return self._conn

    @contextmanager
    def connect(self):
        with self._lock:
            conn = self._get_conn()
            # Proactively rollback before begin(): DuckDB does not raise on begin()
            # when a transaction is in an aborted state, only on the next execute().
            # The lock serialises all DB access across threads (FastAPI runs sync
            # handlers in a thread pool), preventing concurrent-transaction races.
            try:
                conn.rollback()
            except Exception:
                pass
            conn.begin()
            try:
                yield conn
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise


class PostgresDatabase(Database):
    """Production backend via psycopg 3."""

    placeholder = "%s"

    def __init__(self, config: DatabaseConfig) -> None:
        self._dsn = config.postgres_dsn

    @contextmanager
    def connect(self):
        try:
            import psycopg  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install psycopg (pip install psycopg) to use the postgres backend."
            ) from exc
        with psycopg.connect(self._dsn) as conn:
            yield conn


def create_database(config: DatabaseConfig) -> Database:
    """Factory: return the correct Database implementation for *config.dialect*."""
    if config.dialect == "duckdb":
        return DuckDBDatabase(config)
    if config.dialect == "postgres":
        return PostgresDatabase(config)
    raise ValueError(
        f"Unsupported BANYAN_DB_DIALECT: '{config.dialect}'. "
        "Valid values are 'duckdb' and 'postgres'."
    )
