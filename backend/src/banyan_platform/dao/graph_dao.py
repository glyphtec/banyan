from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


def _row(cursor, row) -> dict | None:
    if row is None:
        return None
    return normalise_row(dict(zip([d[0] for d in cursor.description], row)))


class GraphDAO:
    """
    Single-table DAO for the `graph` entity.

    Every method accepts an open *conn* supplied by the service layer.
    The service owns the transaction boundary; these methods never call
    connect() themselves.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(
        self,
        conn,
        name: str,
        notes: str | None = None,
        topology_id: str | None = None,
        actor_id: str | None = None,
    ) -> str:
        graph_id = str(uuid.uuid4())
        p = self.db.placeholder
        conn.execute(
            f"""
            INSERT INTO graph (graph_id, name, notes, topology_id, updated_by)
            VALUES ({p}, {p}, {p}, {p}, {p})
            """,
            [graph_id, name, notes, topology_id, actor_id],
        )
        return graph_id

    def get(self, conn, graph_id: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM graph WHERE CAST(graph_id AS VARCHAR) = {p}", [graph_id]
        )
        return _row(cursor, cursor.fetchone())

    def list(self, conn) -> list[dict]:
        cursor = conn.execute("SELECT * FROM graph ORDER BY inserted_datetime")
        cols = [d[0] for d in cursor.description]
        return [normalise_row(dict(zip(cols, r))) for r in cursor.fetchall()]

    def update(
        self,
        conn,
        graph_id: str,
        name: str | None = None,
        notes: str | None = None,
        topology_id: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        fields, values = [], []
        p = self.db.placeholder
        if name is not None:
            fields.append(f"name = {p}"); values.append(name)
        if notes is not None:
            fields.append(f"notes = {p}"); values.append(notes)
        if topology_id is not None:
            fields.append(f"topology_id = {p}"); values.append(topology_id)
        if not fields:
            return
        fields.append("updated_datetime = CURRENT_TIMESTAMP")
        if actor_id is not None:
            fields.append(f"updated_by = {p}"); values.append(actor_id)
        values.append(graph_id)
        conn.execute(
            f"UPDATE graph SET {', '.join(fields)} WHERE CAST(graph_id AS VARCHAR) = {p}", values
        )

    def set_root_node(self, conn, graph_id: str, root_node_id: str) -> None:
        """Back-populate root_node_id after the root node has been created."""
        p = self.db.placeholder
        conn.execute(
            f"UPDATE graph SET root_node_id = {p} WHERE CAST(graph_id AS VARCHAR) = {p}",
            [root_node_id, graph_id],
        )

    def delete(self, conn, graph_id: str) -> None:
        p = self.db.placeholder
        conn.execute(f"DELETE FROM graph WHERE CAST(graph_id AS VARCHAR) = {p}", [graph_id])
