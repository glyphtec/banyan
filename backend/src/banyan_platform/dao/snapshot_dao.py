from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


class SnapshotDAO:
    """DAO for the graph_snapshot table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        conn,
        graph_id: str,
        version_label: str,
        ledger_id: int,
        actor_id: str,
        metadata: dict | None = None,
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        p = self.db.placeholder
        conn.execute(
            f"""
            INSERT INTO graph_snapshot
                (snapshot_id, graph_id, version_label, ledger_id, actor_id, snapshot_metadata)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
            """,
            [snapshot_id, graph_id, version_label, ledger_id, actor_id,
             json.dumps(metadata or {})],
        )
        return snapshot_id

    def get(self, conn, snapshot_id: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM graph_snapshot WHERE snapshot_id = {p}", [snapshot_id]
        )
        row = cursor.fetchone()
        if row is None:
            return None
        d = normalise_row(dict(zip([c[0] for c in cursor.description], row)))
        if isinstance(d.get("snapshot_metadata"), str):
            d["snapshot_metadata"] = json.loads(d["snapshot_metadata"])
        return d

    def list_by_graph(self, conn, graph_id: str) -> list[dict]:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM graph_snapshot WHERE graph_id = {p} "
            f"ORDER BY inserted_datetime",
            [graph_id],
        )
        cols = [c[0] for c in cursor.description]
        result = []
        for row in cursor.fetchall():
            d = normalise_row(dict(zip(cols, row)))
            if isinstance(d.get("snapshot_metadata"), str):
                d["snapshot_metadata"] = json.loads(d["snapshot_metadata"])
            result.append(d)
        return result
