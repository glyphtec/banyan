from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


def _row(cursor, row, json_cols: tuple[str, ...] = ("metadata",)) -> dict | None:
    if row is None:
        return None
    d = normalise_row(dict(zip([c[0] for c in cursor.description], row)))
    for col in json_cols:
        if col in d and isinstance(d[col], str):
            d[col] = json.loads(d[col])
    return d


class NodeDAO:
    """
    Single-table DAO for the `node` entity.

    The caller (service layer) owns the connection and transaction.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(
        self,
        conn,
        graph_id: str,
        node_type_id: int,
        source_id: str,
        name: str,
        notes: str | None = None,
        metadata: dict | None = None,
        actor_id: str | None = None,
    ) -> str:
        node_id = str(uuid.uuid4())
        p = self.db.placeholder
        conn.execute(
            f"""
            INSERT INTO node
                (node_id, graph_id, node_type_id, source_id, name, notes, metadata, updated_by)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            [node_id, graph_id, node_type_id, source_id, name, notes,
             json.dumps(metadata or {}), actor_id],
        )
        return node_id

    def get(self, conn, node_id: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(f"SELECT * FROM node WHERE node_id = {p}", [node_id])
        return _row(cursor, cursor.fetchone())

    def get_by_source(self, conn, graph_id: str, source_id: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM node WHERE graph_id = {p} AND source_id = {p}",
            [graph_id, source_id],
        )
        return _row(cursor, cursor.fetchone())

    def list_by_graph(self, conn, graph_id: str) -> list[dict]:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM node WHERE graph_id = {p} ORDER BY name", [graph_id]
        )
        cols = [c[0] for c in cursor.description]
        result = []
        for row in cursor.fetchall():
            d = normalise_row(dict(zip(cols, row)))
            if isinstance(d.get("metadata"), str):
                d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def update(
        self,
        conn,
        node_id: str,
        name: str | None = None,
        notes: str | None = None,
        source_id: str | None = None,
        metadata: dict | None = None,
        actor_id: str | None = None,
    ) -> None:
        fields, values = [], []
        p = self.db.placeholder
        if name is not None:
            fields.append(f"name = {p}"); values.append(name)
        if notes is not None:
            fields.append(f"notes = {p}"); values.append(notes)
        if source_id is not None:
            fields.append(f"source_id = {p}"); values.append(source_id)
        if metadata is not None:
            fields.append(f"metadata = {p}"); values.append(json.dumps(metadata))
        if not fields:
            return
        fields.append("updated_datetime = CURRENT_TIMESTAMP")
        if actor_id is not None:
            fields.append(f"updated_by = {p}"); values.append(actor_id)
        values.append(node_id)
        conn.execute(
            f"UPDATE node SET {', '.join(fields)} WHERE node_id = {p}", values
        )

    def delete(self, conn, node_id: str) -> None:
        p = self.db.placeholder
        conn.execute(f"DELETE FROM node WHERE node_id = {p}", [node_id])
