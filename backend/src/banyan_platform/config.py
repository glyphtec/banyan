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
    # Admin API: exposes GET /admin/query for ad-hoc SQL.
    # NEVER enable in production. Set BANYAN_ADMIN_API=true in .env for local dev.
    enable_admin_api: bool = os.getenv("BANYAN_ADMIN_API", "false").lower() == "true"
