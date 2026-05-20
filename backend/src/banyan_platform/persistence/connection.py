from contextlib import contextmanager
import sqlite3

from banyan_platform.config import DatabaseConfig


class Database:
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._sqlite_connection: sqlite3.Connection | None = None

    @contextmanager
    def connect(self):
        should_close = True
        if self.config.dialect == "postgres":
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("Install psycopg to use postgres backend") from exc
            conn = psycopg.connect(self.config.postgres_dsn)
        else:
            if self.config.sqlite_path == ":memory:":
                if self._sqlite_connection is None:
                    self._sqlite_connection = sqlite3.connect(self.config.sqlite_path, check_same_thread=False)
                    self._sqlite_connection.row_factory = sqlite3.Row
                conn = self._sqlite_connection
                should_close = False
            else:
                conn = sqlite3.connect(self.config.sqlite_path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            if should_close:
                conn.close()
