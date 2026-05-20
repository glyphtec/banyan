from banyan_platform.persistence.connection import Database
from banyan_platform.persistence.ddl import ddl_for


class TaxonomyDAO:
    def __init__(self, db: Database, dialect: str):
        self.db = db
        self.dialect = dialect

    def initialize_schema(self) -> None:
        with self.db.connect() as conn:
            conn.execute(ddl_for(self.dialect))

    def create_term(self, name: str, description: str | None = None) -> int:
        insert_sql = (
            "INSERT INTO terms (name, description) VALUES (%s, %s) RETURNING id"
            if self.dialect == "postgres"
            else "INSERT INTO terms (name, description) VALUES (?, ?)"
        )
        with self.db.connect() as conn:
            cursor = conn.execute(insert_sql, (name, description))
            if self.dialect == "postgres":
                return int(cursor.fetchone()[0])
            return int(cursor.lastrowid)

    def get_term(self, term_id: int) -> dict | None:
        select_sql = (
            "SELECT id, name, description FROM terms WHERE id = %s"
            if self.dialect == "postgres"
            else "SELECT id, name, description FROM terms WHERE id = ?"
        )
        with self.db.connect() as conn:
            row = conn.execute(select_sql, (term_id,)).fetchone()
            if not row:
                return None
            if self.dialect == "postgres":
                return {"id": row[0], "name": row[1], "description": row[2]}
            return {"id": row["id"], "name": row["name"], "description": row["description"]}
