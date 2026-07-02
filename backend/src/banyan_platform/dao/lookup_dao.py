from __future__ import annotations

from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


def _all_rows(cursor) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    return [normalise_row(dict(zip(cols, r))) for r in cursor.fetchall()]


def _one_row(cursor) -> dict | None:
    row = cursor.fetchone()
    if row is None:
        return None
    return normalise_row(dict(zip([c[0] for c in cursor.description], row)))


class LookupDAO:
    """
    Read-only DAO for lookup / meta-entity tables: link_type, node_type, graph_topology.

    These tables are small and change rarely.  No caching is applied here;
    the service layer may add caching if profiling warrants it.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── link_type ─────────────────────────────────────────────────────────────

    def get_link_types(self, conn) -> list[dict]:
        return _all_rows(conn.execute(
            "SELECT link_type_id, parent_link_type_id, name, notes "
            "FROM link_type ORDER BY name"
        ))

    def get_link_type_subtree(self, conn, root_name: str) -> list[dict]:
        """
        Return root_name and all its descendants in the link_type metagraph,
        using a recursive CTE.  Returns an empty list if root_name is not found.
        """
        p = self.db.placeholder
        sql = f"""
            WITH RECURSIVE family AS (
                SELECT link_type_id, parent_link_type_id, name, notes
                FROM link_type
                WHERE name = {p}

                UNION ALL

                SELECT lt.link_type_id, lt.parent_link_type_id, lt.name, lt.notes
                FROM link_type lt
                JOIN family f ON lt.parent_link_type_id = f.link_type_id
            )
            SELECT link_type_id, parent_link_type_id, name, notes
            FROM family
            ORDER BY name
        """
        return _all_rows(conn.execute(sql, [root_name]))

    def get_link_type_by_name(self, conn, name: str) -> dict | None:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"SELECT * FROM link_type WHERE name = {p}", [name]
        ))

    def get_link_type(self, conn, link_type_id: str) -> dict | None:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"SELECT * FROM link_type WHERE CAST(link_type_id AS VARCHAR) = {p}", [link_type_id]
        ))

    def get_link_type_root_family(self, conn, link_type_id: str) -> str | None:
        """
        Walk the parent_link_type_id chain and return the root family name.

        Root families are the seed rows with parent_link_type_id IS NULL:
        HIERARCHICAL, RELATED, SYNONYM.  Sub-types (user-defined) resolve to
        one of these families.  Returns None if link_type_id does not exist.
        """
        p = self.db.placeholder
        current_id = link_type_id
        for _ in range(20):  # Cycle guard
            cursor = conn.execute(
                f"SELECT name, parent_link_type_id FROM link_type "
                f"WHERE CAST(link_type_id AS VARCHAR) = {p}",
                [current_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            name, parent_id = row[0], row[1]
            if parent_id is None:
                return name
            current_id = str(parent_id)  # normalise uuid.UUID → str for next iteration
        return None  # Cycle protection fallback

    # ── node_type ─────────────────────────────────────────────────────────────

    def get_node_types(self, conn) -> list[dict]:
        return _all_rows(conn.execute(
            "SELECT node_type_id, name, notes FROM node_type ORDER BY name"
        ))

    def get_node_type(self, conn, node_type_id: str) -> dict | None:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"SELECT * FROM node_type WHERE CAST(node_type_id AS VARCHAR) = {p}", [node_type_id]
        ))

    def get_node_type_by_name(self, conn, name: str) -> dict | None:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"SELECT * FROM node_type WHERE name = {p}", [name]
        ))

    def create_link_type(
        self,
        conn,
        name: str,
        notes: str | None = None,
        parent_link_type_id: str | None = None,
    ) -> dict:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"""
            INSERT INTO link_type (name, notes, parent_link_type_id)
            VALUES ({p}, {p}, {p})
            RETURNING link_type_id, parent_link_type_id, name, notes
            """,
            [name, notes, parent_link_type_id],
        ))

    def update_link_type(
        self,
        conn,
        link_type_id: str,
        name: str | None = None,
        notes: str | None = None,
    ) -> None:
        fields, values = [], []
        p = self.db.placeholder
        if name is not None:
            fields.append(f"name = {p}"); values.append(name)
        if notes is not None:
            fields.append(f"notes = {p}"); values.append(notes)
        if not fields:
            return
        fields.append("updated_datetime = CURRENT_TIMESTAMP")
        values.append(link_type_id)
        conn.execute(
            f"UPDATE link_type SET {', '.join(fields)} WHERE CAST(link_type_id AS VARCHAR) = {p}", values
        )

    def delete_link_type(self, conn, link_type_id: str) -> None:
        p = self.db.placeholder
        conn.execute(f"DELETE FROM link_type WHERE CAST(link_type_id AS VARCHAR) = {p}", [link_type_id])

    def create_node_type(
        self,
        conn,
        name: str,
        notes: str | None = None,
    ) -> dict:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"""
            INSERT INTO node_type (name, notes)
            VALUES ({p}, {p})
            RETURNING node_type_id, name, notes
            """,
            [name, notes],
        ))

    def update_node_type(
        self,
        conn,
        node_type_id: str,
        name: str | None = None,
        notes: str | None = None,
    ) -> None:
        fields, values = [], []
        p = self.db.placeholder
        if name is not None:
            fields.append(f"name = {p}"); values.append(name)
        if notes is not None:
            fields.append(f"notes = {p}"); values.append(notes)
        if not fields:
            return
        values.append(node_type_id)
        conn.execute(
            f"UPDATE node_type SET {', '.join(fields)} WHERE CAST(node_type_id AS VARCHAR) = {p}", values
        )

    def delete_node_type(self, conn, node_type_id: str) -> None:
        p = self.db.placeholder
        conn.execute(f"DELETE FROM node_type WHERE CAST(node_type_id AS VARCHAR) = {p}", [node_type_id])

    # ── banyan_actor ──────────────────────────────────────────────────────────

    def get_actors(self, conn) -> list[dict]:
        return _all_rows(conn.execute(
            "SELECT * FROM banyan_actor ORDER BY actor_type, handle"
        ))

    def get_actor_by_handle(self, conn, handle: str) -> dict | None:
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"SELECT * FROM banyan_actor WHERE handle = {p}", [handle]
        ))

    def register_actor(
        self,
        conn,
        handle: str,
        display_name: str,
        actor_type: str = "HUMAN",
        org: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """
        Insert a new actor row.  Raises if the handle already exists.
        actor_type must be one of: SYSTEM, HUMAN, AGENT.
        """
        p = self.db.placeholder
        return _one_row(conn.execute(
            f"""
            INSERT INTO banyan_actor (handle, display_name, actor_type, org, notes)
            VALUES ({p}, {p}, {p}, {p}, {p})
            RETURNING *
            """,
            [handle, display_name, actor_type, org, notes],
        ))
