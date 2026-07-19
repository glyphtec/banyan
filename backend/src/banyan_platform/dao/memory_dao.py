from __future__ import annotations

from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database

_COLS = ("memory_id", "category", "key", "content", "created_at", "updated_at")
_SELECT = f"SELECT {', '.join(_COLS)} FROM agent_memory"


class MemoryDAO:
    """DAO for the agent_memory table.

    Provides upsert-by-key semantics so the agent can overwrite a note
    without needing to know whether it already exists.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Public interface ──────────────────────────────────────────────────────

    def upsert(self, conn, *, category: str, key: str, content: str) -> dict:
        """Insert or overwrite a memory note.  created_at is preserved on update."""
        p = self.db.placeholder
        exists = conn.execute(
            f"SELECT 1 FROM agent_memory WHERE key = {p}", [key]
        ).fetchone()
        if exists:
            conn.execute(
                f"UPDATE agent_memory SET category = {p}, content = {p}, updated_at = now() "
                f"WHERE key = {p}",
                [category, content, key],
            )
        else:
            conn.execute(
                f"INSERT INTO agent_memory (memory_id, category, key, content, created_at, updated_at) "
                f"VALUES (gen_random_uuid(), {p}, {p}, {p}, now(), now())",
                [category, key, content],
            )
        return self._fetch_by_key(conn, key)

    def delete(self, conn, *, key: str) -> bool:
        """Delete a note by key.  Returns True if a row was removed."""
        p = self.db.placeholder
        exists = conn.execute(
            f"SELECT 1 FROM agent_memory WHERE key = {p}", [key]
        ).fetchone()
        if not exists:
            return False
        conn.execute(f"DELETE FROM agent_memory WHERE key = {p}", [key])
        return True

    def list_all(self, conn) -> list[dict]:
        """Return all notes ordered by category then most-recently-updated."""
        rows = conn.execute(
            f"{_SELECT} ORDER BY category, updated_at DESC"
        ).fetchall()
        return [normalise_row(dict(zip(_COLS, r))) for r in rows]

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_by_key(self, conn, key: str) -> dict:
        p = self.db.placeholder
        row = conn.execute(
            f"{_SELECT} WHERE key = {p}", [key]
        ).fetchone()
        return normalise_row(dict(zip(_COLS, row))) if row else {}
