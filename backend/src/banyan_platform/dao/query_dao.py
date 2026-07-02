from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


# ---------------------------------------------------------------------------
# Predicate compiler
# ---------------------------------------------------------------------------

_SAFE_METADATA_PATH = re.compile(r'^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)*$')

_NODE_COLS = (
    "n.node_id, n.graph_id, n.node_type_id, n.source_id, "
    "n.name, n.notes, n.metadata"
)


def _build_pred(pred: dict, p: str) -> tuple[str, list]:
    """
    Recursively compile a NodePredicate dict into a SQL WHERE fragment.
    Returns (sql_fragment, params_list).

    pred must be one of:
      - {"and": [pred, ...]}  — compound AND
      - {"or":  [pred, ...]}  — compound OR
      - leaf: field-predicate pairs implicitly ANDed
    """
    if "and" in pred:
        parts, params = [], []
        for sub in pred["and"]:
            frag, sub_p = _build_pred(sub, p)
            parts.append(f"({frag})")
            params.extend(sub_p)
        return (" AND ".join(parts) if parts else "TRUE"), params

    if "or" in pred:
        parts, params = [], []
        for sub in pred["or"]:
            frag, sub_p = _build_pred(sub, p)
            parts.append(f"({frag})")
            params.extend(sub_p)
        return (" OR ".join(parts) if parts else "FALSE"), params

    # Leaf: all field predicates are implicitly ANDed
    clauses: list[str] = []
    params: list = []

    for key, val in pred.items():
        if key == "name":
            if isinstance(val, dict):
                frag, vp = _op_clause("LOWER(name)", val, p, lower_value=True)
            else:
                frag, vp = f"LOWER(name) = LOWER({p})", [str(val)]
            clauses.append(frag)
            params.extend(vp)

        elif key == "name_contains":
            clauses.append(f"LOWER(name) LIKE {p}")
            params.append(f"%{str(val).lower()}%")

        elif key == "name_starts":
            clauses.append(f"LOWER(name) LIKE {p}")
            params.append(f"{str(val).lower()}%")

        elif key == "source_id":
            if isinstance(val, dict):
                frag, vp = _op_clause("source_id", val, p)
            else:
                frag, vp = f"source_id = {p}", [str(val)]
            clauses.append(frag)
            params.extend(vp)

        elif key == "source_id_prefix":
            clauses.append(f"source_id LIKE {p}")
            params.append(f"{str(val)}%")

        elif key == "node_id":
            clauses.append(f"CAST(node_id AS VARCHAR) = {p}")
            params.append(str(val))

        elif key == "node_type":
            # Resolved via subquery to avoid a JOIN on the outer query
            clauses.append(
                f"node_type_id = (SELECT node_type_id FROM node_type WHERE name = {p})"
            )
            params.append(str(val))

        elif key.startswith("metadata."):
            field_path = key[len("metadata."):]
            if not _SAFE_METADATA_PATH.match(field_path):
                raise ValueError(f"Invalid metadata path: {field_path!r}")
            col = f"json_extract_string(metadata, '$.{field_path}')"
            if isinstance(val, dict):
                frag, vp = _op_clause(col, val, p)
            else:
                frag, vp = f"{col} = {p}", [str(val)]
            clauses.append(frag)
            params.extend(vp)

        # Unknown keys are silently ignored to allow forward-compatibility.

    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _op_clause(
    col: str, op_dict: dict, p: str, lower_value: bool = False
) -> tuple[str, list]:
    """Convert an operator dict {"eq": v} / {"gte": v, "lte": v} / {"in": [...]} to SQL."""
    parts: list[str] = []
    params: list = []
    for op, val in op_dict.items():
        v = str(val).lower() if lower_value else val
        if op == "eq":
            parts.append(f"{col} = {p}")
            params.append(v)
        elif op == "neq":
            parts.append(f"{col} != {p}")
            params.append(v)
        elif op == "contains":
            parts.append(f"{col} LIKE {p}")
            params.append(f"%{v}%")
        elif op == "starts":
            parts.append(f"{col} LIKE {p}")
            params.append(f"{v}%")
        elif op == "gte":
            parts.append(f"{col} >= {p}")
            params.append(val)
        elif op == "lte":
            parts.append(f"{col} <= {p}")
            params.append(val)
        elif op == "in":
            if not isinstance(val, list):
                raise ValueError("'in' operator requires a list value")
            phs = ", ".join(p for _ in val)
            parts.append(f"{col} IN ({phs})")
            params.extend(str(vi).lower() if lower_value else vi for vi in val)
        else:
            raise ValueError(f"Unknown predicate operator: {op!r}")
    return " AND ".join(parts), params


# ---------------------------------------------------------------------------
# QueryDAO
# ---------------------------------------------------------------------------

def _deserialise_node(cols: list[str], row) -> dict:
    d = normalise_row(dict(zip(cols, row)))
    if isinstance(d.get("metadata"), str):
        d["metadata"] = json.loads(d["metadata"])
    elif d.get("metadata") is None:
        d["metadata"] = {}
    return d


class QueryDAO:
    """
    SQL layer for BQL query execution.

    Provides two operations:
      - resolve_seed: compile a NodePredicate dict to SQL and fetch matching nodes.
      - execute_one_hop: single-JOIN traversal hop from a frontier node set.

    The service layer owns the connection and drives the iterative depth loop.
    """

    def __init__(self, db: "Database") -> None:
        self.db = db

    # ── Seed resolution ───────────────────────────────────────────────────────

    def resolve_seed(self, conn, graph_id: str, predicate: dict) -> list[dict]:
        """
        Find all nodes in graph_id that match the given NodePredicate.
        Returns a list of node dicts.
        """
        p = self.db.placeholder
        where_frag, pred_params = _build_pred(predicate, p)
        sql = f"""
            SELECT {_NODE_COLS}
            FROM node n
            WHERE CAST(n.graph_id AS VARCHAR) = {p}
              AND ({where_frag})
        """
        params: list = [graph_id] + pred_params
        cursor = conn.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [_deserialise_node(cols, row) for row in cursor.fetchall()]

    # ── One-hop traversal ─────────────────────────────────────────────────────

    def execute_one_hop(
        self,
        conn,
        direction: str,
        frontier_ids: list[str],
        link_type_ids: list[str] | None,
        allowed_graph_ids: list[str] | None,
    ) -> list[tuple[dict, str, dict]]:
        """
        Traverse one hop from frontier_ids in the given direction.

        direction:         FROM | TO | WITH (WITH = union of FROM + TO)
        frontier_ids:      node_ids of the current traversal frontier
        link_type_ids:     None = all types; list = restrict to these IDs
        allowed_graph_ids: None = no restriction; list = target node must be in one of these graphs

        Returns list of (link_info, parent_node_id, target_node) tuples.
        parent_node_id is the frontier node that generated each hop result,
        used by the caller to track net_depth.
        """
        if not frontier_ids:
            return []

        if direction == "WITH":
            from_r = self._hop(conn, "FROM", frontier_ids, link_type_ids, allowed_graph_ids)
            to_r = self._hop(conn, "TO", frontier_ids, link_type_ids, allowed_graph_ids)
            return from_r + to_r

        return self._hop(conn, direction, frontier_ids, link_type_ids, allowed_graph_ids)

    def _hop(
        self,
        conn,
        direction: str,
        frontier_ids: list[str],
        link_type_ids: list[str] | None,
        allowed_graph_ids: list[str] | None,
    ) -> list[tuple[dict, str, dict]]:
        p = self.db.placeholder

        # Build VALUES clause for frontier
        values_phs = ", ".join(f"({p})" for _ in frontier_ids)

        if direction == "FROM":
            frontier_join = "CAST(l.from_node_id AS VARCHAR) = f.node_id"
            target_join = (
                "CAST(l.to_node_id AS VARCHAR) = CAST(n.node_id AS VARCHAR) "
                "AND CAST(l.to_graph_id AS VARCHAR) = CAST(n.graph_id AS VARCHAR)"
            )
            parent_col = "CAST(l.from_node_id AS VARCHAR)"
            graph_col = "CAST(l.to_graph_id AS VARCHAR)"
        else:  # TO
            frontier_join = "CAST(l.to_node_id AS VARCHAR) = f.node_id"
            target_join = (
                "CAST(l.from_node_id AS VARCHAR) = CAST(n.node_id AS VARCHAR) "
                "AND CAST(l.from_graph_id AS VARCHAR) = CAST(n.graph_id AS VARCHAR)"
            )
            parent_col = "CAST(l.to_node_id AS VARCHAR)"
            graph_col = "CAST(l.from_graph_id AS VARCHAR)"

        lt_filter = ""
        lt_params: list = []
        if link_type_ids:
            lt_phs = ", ".join(p for _ in link_type_ids)
            lt_filter = f"AND CAST(l.link_type_id AS VARCHAR) IN ({lt_phs})"
            lt_params = list(link_type_ids)

        graph_filter = ""
        graph_params: list = []
        if allowed_graph_ids is not None:
            if not allowed_graph_ids:
                return []  # No graphs allowed — nothing to traverse into
            g_phs = ", ".join(p for _ in allowed_graph_ids)
            graph_filter = f"AND {graph_col} IN ({g_phs})"
            graph_params = list(allowed_graph_ids)

        sql = f"""
            WITH frontier(node_id) AS (
                VALUES {values_phs}
            )
            SELECT
                CAST(l.link_id      AS VARCHAR) AS link_id,
                CAST(l.link_type_id AS VARCHAR) AS link_type_id,
                lt.name                         AS link_type_name,
                CAST(l.from_node_id AS VARCHAR) AS from_node_id,
                CAST(l.to_node_id   AS VARCHAR) AS to_node_id,
                CAST(l.from_graph_id AS VARCHAR) AS from_graph_id,
                CAST(l.to_graph_id   AS VARCHAR) AS to_graph_id,
                {parent_col}                    AS parent_node_id,
                '{direction}'                   AS traversal_direction,
                {_NODE_COLS}
            FROM link l
            JOIN frontier f ON {frontier_join}
            JOIN node n ON {target_join}
            JOIN link_type lt
              ON CAST(l.link_type_id AS VARCHAR) = CAST(lt.link_type_id AS VARCHAR)
            WHERE l.is_disabled = FALSE
              {lt_filter}
              {graph_filter}
        """

        params: list = list(frontier_ids) + lt_params + graph_params
        cursor = conn.execute(sql, params)
        cols = [c[0] for c in cursor.description]

        results: list[tuple[dict, str, dict]] = []
        for row in cursor.fetchall():
            d = normalise_row(dict(zip(cols, row)))
            link_info = {
                "link_id": d["link_id"],
                "link_type_id": d["link_type_id"],
                "link_type_name": d["link_type_name"],
                "from_node_id": d["from_node_id"],
                "to_node_id": d["to_node_id"],
                "from_graph_id": d["from_graph_id"],
                "to_graph_id": d["to_graph_id"],
                "traversal_direction": d["traversal_direction"],
            }
            parent_node_id = str(d["parent_node_id"])
            node = {
                "node_id": d["node_id"],
                "graph_id": d["graph_id"],
                "node_type_id": d["node_type_id"],
                "source_id": d["source_id"],
                "name": d["name"],
                "notes": d["notes"],
                "metadata": (
                    json.loads(d["metadata"])
                    if isinstance(d.get("metadata"), str)
                    else (d.get("metadata") or {})
                ),
            }
            results.append((link_info, parent_node_id, node))

        return results
