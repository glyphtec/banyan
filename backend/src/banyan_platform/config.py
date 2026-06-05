from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DatabaseConfig:
    # 'duckdb' for local/dev; 'postgres' for production
    dialect: str = os.getenv("BANYAN_DB_DIALECT", "duckdb")
    # DuckDB file path. ':memory:' for in-process testing.
    duckdb_path: str = os.getenv("BANYAN_DUCKDB_PATH", ":memory:")
    postgres_dsn: str = os.getenv(
        "BANYAN_POSTGRES_DSN",
        "postgresql://postgres:postgres@localhost:5432/banyan",
    )
