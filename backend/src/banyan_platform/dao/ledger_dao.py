from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


class _IsoEncoder(json.JSONEncoder):
    """Extend the default encoder to handle datetime/date/UUID → JSON-safe types."""

    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


def _dumps(obj: dict) -> str:
    return json.dumps(obj, cls=_IsoEncoder)


def _hydrate(row: tuple, cols: list[str]) -> dict:
    d = normalise_row(dict(zip(cols, row)))
    for field in ("payload", "reversal_payload"):
        if field in d and isinstance(d[field], str):
            d[field] = json.loads(d[field])
    return d


class LedgerDAO:
    """
    Append-only DAO for `banyan_ledger`.

    Entries are never updated or deleted — the ledger is the immutable record
    of every mutation the system has performed.

    The caller (service layer) owns the connection and transaction.
    """

    # Valid primitive verbs for runtime validation at the service boundary.
    VERBS = frozenset({
        "ADD_NODE",
        "UPDATE_NODE",
        "DELETE_NODE",
        "CREATE_LINK",
        "UPDATE_LINK",
        "DESTROY_LINK",
        # Meta/definitional object verbs (system-scope, source_graph_id = __system__ sentinel):
        "CREATE_NODE_TYPE",
        "UPDATE_NODE_TYPE",
        "DELETE_NODE_TYPE",
        "CREATE_LINK_TYPE",
        "UPDATE_LINK_TYPE",
        "DELETE_LINK_TYPE",
        "CREATE_TOPOLOGY",
        "UPDATE_TOPOLOGY",
        "DELETE_TOPOLOGY",
        "CREATE_STAKEHOLDER",
        "UPDATE_STAKEHOLDER",
        "DELETE_STAKEHOLDER",
    })

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, conn, ledger_id: int) -> dict | None:
        """Fetch a single ledger entry by primary key."""
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM banyan_ledger WHERE ledger_id = {p}", [ledger_id]
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _hydrate(row, [c[0] for c in cursor.description])

    def append(
        self,
        conn,
        *,
        transaction_id: str,
        actor_id: str,
        primitive_verb: str,
        source_graph_id: str,
        entity_id: str,
        payload: dict,
        reversal_payload: dict,
        target_graph_id: str | None = None,
        reverses_ledger_id: int | None = None,
    ) -> int:
        """
        Append one atomic ledger entry and return its ledger_id.

        *payload*            — state after the mutation (forward delta)
        *reversal_payload*   — full prior state needed to perfectly invert this entry
        *reverses_ledger_id* — set when this entry is a compensating UNDO of a prior entry
        """
        p = self.db.placeholder
        cursor = conn.execute(
            f"""
            INSERT INTO banyan_ledger (
                transaction_id, actor_id, primitive_verb,
                source_graph_id, target_graph_id, entity_id,
                payload, reversal_payload, reverses_ledger_id
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            RETURNING ledger_id
            """,
            [
                transaction_id, actor_id, primitive_verb,
                source_graph_id, target_graph_id, entity_id,
                _dumps(payload), _dumps(reversal_payload), reverses_ledger_id,
            ],
        )
        return int(cursor.fetchone()[0])

    def get_by_transaction(self, conn, transaction_id: str) -> list[dict]:
        """Return all ledger entries belonging to one logical transaction, in order."""
        p = self.db.placeholder
        cursor = conn.execute(
            f"""
            SELECT * FROM banyan_ledger
            WHERE transaction_id = {p}
            ORDER BY ledger_id
            """,
            [transaction_id],
        )
        cols = [c[0] for c in cursor.description]
        return [_hydrate(r, cols) for r in cursor.fetchall()]

    def get_graph_history(
        self,
        conn,
        source_graph_id: str,
        since_ledger_id: int | None = None,
    ) -> list[dict]:
        """
        Return the ordered mutation history for a graph.
        Pass *since_ledger_id* to fetch only entries after a snapshot pin.
        """
        p = self.db.placeholder
        sql = f"SELECT * FROM banyan_ledger WHERE source_graph_id = {p}"
        params: list = [source_graph_id]
        if since_ledger_id is not None:
            sql += f" AND ledger_id > {p}"
            params.append(since_ledger_id)
        sql += " ORDER BY ledger_id"
        cursor = conn.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [_hydrate(r, cols) for r in cursor.fetchall()]
