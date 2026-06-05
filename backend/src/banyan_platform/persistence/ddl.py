POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS terms (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);
""".strip()

SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);
""".strip()


def ddl_for(dialect: str) -> str:
    if dialect == "postgres":
        return POSTGRES_DDL
    return SQLITE_DDL
