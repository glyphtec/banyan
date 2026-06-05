from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


def _deserialise(rows: list, cols: list[str]) -> list[dict]:
    result = []
    for row in rows:
        d = normalise_row(dict(zip(cols, row)))
        if isinstance(d.get("metadata"), str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return result


class LinkDAO:
    """
    Single-table DAO for the `link` entity.

    Cross-graph constraint (HIERARCHICAL/SYNONYM must have from_graph_id = to_graph_id)
    is enforced by the service layer, not here.

    The caller (service layer) owns the connection and transaction.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(
        self,
        conn,
        link_type_id: int,
        from_graph_id: str,
        to_graph_id: str,
        from_node_id: str,
        to_node_id: str,
        link_order: float = 0.0,
        metadata: dict | None = None,
        valid_from_datetime: datetime | None = None,
        valid_until_datetime: datetime | None = None,
        actor_id: str | None = None,
    ) -> str:
        link_id = str(uuid.uuid4())
        p = self.db.placeholder
        conn.execute(
            f"""
            INSERT INTO link (
                link_id, link_type_id,
                from_graph_id, to_graph_id,
                from_node_id, to_node_id,
                link_order, metadata,
                valid_from_datetime, valid_until_datetime,
                updated_by
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            [
                link_id, link_type_id,
                from_graph_id, to_graph_id,
                from_node_id, to_node_id,
                link_order, json.dumps(metadata or {}),
                valid_from_datetime, valid_until_datetime,
                actor_id,
            ],
        )
        return link_id

    def get(self, conn, link_id: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(f"SELECT * FROM link WHERE link_id = {p}", [link_id])
        row = cursor.fetchone()
        if row is None:
            return None
        d = normalise_row(dict(zip([c[0] for c in cursor.description], row)))
        if isinstance(d.get("metadata"), str):
            d["metadata"] = json.loads(d["metadata"])
        return d

    def get_children(
        self,
        conn,
        graph_id: str,
        from_node_id: str,
        link_type_id: int | None = None,
    ) -> list[dict]:
        """Return active outbound links from from_node_id, ordered by link_order."""
        p = self.db.placeholder
        sql = f"""
            SELECT * FROM link
            WHERE from_graph_id = {p}
              AND from_node_id = {p}
              AND is_disabled = FALSE
        """
        params: list = [graph_id, from_node_id]
        if link_type_id is not None:
            sql += f" AND link_type_id = {p}"
            params.append(link_type_id)
        sql += " ORDER BY link_order"
        cursor = conn.execute(sql, params)
        return _deserialise(cursor.fetchall(), [c[0] for c in cursor.description])

    def get_parents(
        self,
        conn,
        graph_id: str,
        to_node_id: str,
        link_type_id: int | None = None,
    ) -> list[dict]:
        """Return active inbound links to to_node_id (supports polyhierarchy)."""
        p = self.db.placeholder
        sql = f"""
            SELECT * FROM link
            WHERE from_graph_id = {p}
              AND to_node_id = {p}
              AND is_disabled = FALSE
        """
        params: list = [graph_id, to_node_id]
        if link_type_id is not None:
            sql += f" AND link_type_id = {p}"
            params.append(link_type_id)
        cursor = conn.execute(sql, params)
        return _deserialise(cursor.fetchall(), [c[0] for c in cursor.description])

    def update(
        self,
        conn,
        link_id: str,
        link_order: float | None = None,
        metadata: dict | None = None,
        is_disabled: bool | None = None,
        valid_from_datetime: datetime | None = None,
        valid_until_datetime: datetime | None = None,
        actor_id: str | None = None,
    ) -> None:
        fields, values = [], []
        p = self.db.placeholder
        if link_order is not None:
            fields.append(f"link_order = {p}"); values.append(link_order)
        if metadata is not None:
            fields.append(f"metadata = {p}"); values.append(json.dumps(metadata))
        if is_disabled is not None:
            fields.append(f"is_disabled = {p}"); values.append(is_disabled)
        if valid_from_datetime is not None:
            fields.append(f"valid_from_datetime = {p}"); values.append(valid_from_datetime)
        if valid_until_datetime is not None:
            fields.append(f"valid_until_datetime = {p}"); values.append(valid_until_datetime)
        if not fields:
            return
        fields.append("updated_datetime = CURRENT_TIMESTAMP")
        if actor_id is not None:
            fields.append(f"updated_by = {p}"); values.append(actor_id)
        values.append(link_id)
        conn.execute(
            f"UPDATE link SET {', '.join(fields)} WHERE link_id = {p}", values
        )

    def get_all_for_node(self, conn, node_id: str) -> list[dict]:
        """
        Return every link where node_id appears as from_node_id OR to_node_id,
        regardless of graph scope.  Used for pre-delete cascade resolution.
        """
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM link WHERE from_node_id = {p} OR to_node_id = {p}",
            [node_id, node_id],
        )
        return _deserialise(cursor.fetchall(), [c[0] for c in cursor.description])

    def delete(self, conn, link_id: str) -> None:
        """Hard delete. Service layer should write a DESTROY_LINK ledger entry first."""
        p = self.db.placeholder
        conn.execute(f"DELETE FROM link WHERE link_id = {p}", [link_id])
