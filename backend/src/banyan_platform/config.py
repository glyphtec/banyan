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
    # Actor validation mode.
    # False (default): any actor handle passes through — unknown actors are not rejected.
    # True: actor handle must exist in banyan_actor; raise ValueError on unknown handles.
    # Keep False during POC/development; harden to True before production deployment.
    strict_actor_validation: bool = os.getenv("BANYAN_STRICT_ACTORS", "false").lower() == "true"
    # CORS allowed origins. Comma-separated in env var.
    # Default covers the Vite dev server.
    cors_origins: list = None

    def __post_init__(self):
        if self.cors_origins is None:
            raw = os.getenv("BANYAN_CORS_ORIGINS", "http://localhost:5173")
            object.__setattr__(self, "cors_origins", [o.strip() for o in raw.split(",")])
