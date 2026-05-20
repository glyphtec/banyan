from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DatabaseConfig:
    dialect: str = os.getenv("BANYAN_DB_DIALECT", "sqlite")
    sqlite_path: str = os.getenv("BANYAN_SQLITE_PATH", ":memory:")
    postgres_dsn: str = os.getenv(
        "BANYAN_POSTGRES_DSN",
        "postgresql://postgres:postgres@postgres:5432/banyan",
    )
