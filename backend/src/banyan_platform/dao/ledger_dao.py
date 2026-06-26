from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


# ---------------------------------------------------------------------------
# Hash chain constants and helpers
# ---------------------------------------------------------------------------

_GENESIS_HASH = "0" * 64  # previous_hash for the very first ledger entry


def _compute_entry_hash(
    previous_hash: str,
    ledger_id: int,
    transaction_id: str,
    actor_id: str,
    primitive_verb: str,
    source_graph_id: str | None,
    target_graph_id: str | None,
    entity_id: str,
    payload_str: str,
    reversal_payload_str: str,
) -> str:
    """SHA-256 over the canonical pipe-delimited content of one ledger entry."""
    content = "|".join([
        previous_hash,
        str(ledger_id),
        transaction_id,
        actor_id,
        primitive_verb,
        source_graph_id or "",
        target_graph_id or "",
        entity_id,
        payload_str,
        reversal_payload_str,
    ])
    return hashlib.sha256(content.encode()).hexdigest()


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
        "CREATE_ACTOR",
        "UPDATE_ACTOR",
        "DELETE_ACTOR",
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

        Computes and stores a global SHA-256 hash chain entry:
          previous_hash = entry_hash of the immediately preceding row
                          (genesis sentinel '000...0' for the first entry)
          entry_hash    = SHA-256 of all significant fields + previous_hash

        *payload*            — state after the mutation (forward delta)
        *reversal_payload*   — full prior state needed to perfectly invert this entry
        *reverses_ledger_id* — set when this entry is a compensating UNDO of a prior entry
        """
        p = self.db.placeholder

        # Pre-allocate the ledger_id so we can include it in the hash.
        ledger_id = int(
            conn.execute("SELECT nextval('seq_ledger_id')").fetchone()[0]
        )

        # Generate the timestamp in Python so it is included in the hash
        # before the row is written — no two-phase insert needed.
        inserted_at = datetime.now(timezone.utc)

        # Fetch the tip of the chain (last committed entry_hash).
        tip = conn.execute(
            "SELECT entry_hash FROM banyan_ledger ORDER BY ledger_id DESC LIMIT 1"
        ).fetchone()
        previous_hash = tip[0] if tip else _GENESIS_HASH

        # Serialise payloads to the exact strings that will be stored.
        payload_str = _dumps(payload)
        reversal_str = _dumps(reversal_payload)

        entry_hash = _compute_entry_hash(
            previous_hash=previous_hash,
            ledger_id=ledger_id,
            transaction_id=transaction_id,
            actor_id=actor_id,
            primitive_verb=primitive_verb,
            source_graph_id=source_graph_id,
            target_graph_id=target_graph_id,
            entity_id=entity_id,
            payload_str=payload_str,
            reversal_payload_str=reversal_str,
        )

        conn.execute(
            f"""
            INSERT INTO banyan_ledger (
                ledger_id, transaction_id, actor_id, primitive_verb,
                source_graph_id, target_graph_id, entity_id,
                payload, reversal_payload, reverses_ledger_id,
                inserted_datetime, previous_hash, entry_hash
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """,
            [
                ledger_id, transaction_id, actor_id, primitive_verb,
                source_graph_id, target_graph_id, entity_id,
                payload_str, reversal_str, reverses_ledger_id,
                inserted_at, previous_hash, entry_hash,
            ],
        )
        return ledger_id

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

    def verify_chain(self, conn) -> dict:
        """
        Walk the entire ledger in ledger_id order and verify the global hash chain.

        Re-computes each entry_hash from stored fields and checks:
          - entry[n].previous_hash == entry[n-1].entry_hash  (or genesis sentinel)
          - entry[n].entry_hash    == recomputed hash

        Returns:
          {"ok": True,  "entries_checked": N}
          {"ok": False, "entries_checked": N, "first_broken_ledger_id": M}
        """
        cursor = conn.execute(
            """
            SELECT ledger_id, transaction_id, actor_id, primitive_verb,
                   source_graph_id, target_graph_id, entity_id,
                   payload, reversal_payload,
                   inserted_datetime, previous_hash, entry_hash
            FROM banyan_ledger
            ORDER BY ledger_id
            """
        )
        cols = [c[0] for c in cursor.description]
        rows = cursor.fetchall()

        expected_previous = _GENESIS_HASH
        for i, raw in enumerate(rows):
            r = dict(zip(cols, raw))
            # payload / reversal_payload come back as strings from DuckDB JSON columns
            payload_str = r["payload"] if isinstance(r["payload"], str) else _dumps(r["payload"])
            reversal_str = r["reversal_payload"] if isinstance(r["reversal_payload"], str) else _dumps(r["reversal_payload"])

            expected_hash = _compute_entry_hash(
                previous_hash=expected_previous,
                ledger_id=int(r["ledger_id"]),
                transaction_id=str(r["transaction_id"]),
                actor_id=str(r["actor_id"]),
                primitive_verb=str(r["primitive_verb"]),
                source_graph_id=str(r["source_graph_id"]) if r["source_graph_id"] is not None else None,
                target_graph_id=str(r["target_graph_id"]) if r["target_graph_id"] is not None else None,
                entity_id=str(r["entity_id"]),
                payload_str=payload_str,
                reversal_payload_str=reversal_str,
            )

            if r["previous_hash"] != expected_previous or r["entry_hash"] != expected_hash:
                return {
                    "ok": False,
                    "entries_checked": i + 1,
                    "first_broken_ledger_id": int(r["ledger_id"]),
                }

            expected_previous = r["entry_hash"]

        return {"ok": True, "entries_checked": len(rows)}
