from __future__ import annotations

import json
from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


def _deserialise_nodes(cursor) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    result = []
    for row in cursor.fetchall():
        d = normalise_row(dict(zip(cols, row)))
        if isinstance(d.get("metadata"), str):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return result


class TraversalDAO:
    """
    Graph traversal queries (breadth-first, cycle-safe).

    These queries intentionally span both the `node` and `link` tables.
    They live here rather than in NodeDAO or LinkDAO because they are
    inherently cross-entity operations.

    The walks are iterative rather than WITH RECURSIVE; see `_walk`.

    The caller (service layer) owns the connection and transaction.
    """

    _MAX_DEPTH = 50   # same ceiling as BQL's MAX_DEPTH_HARD
    _CHUNK = 500      # ids per IN (...) list

    def __init__(self, db: Database) -> None:
        self.db = db

    def _walk(
        self,
        conn,
        graph_id: str,
        start_node_id: str,
        *,
        outbound: bool,
        link_type_id: str | None,
        max_depth: int,
    ) -> list[dict]:
        """
        Breadth-first walk from *start_node_id* (returned at depth 0).

        Each node is returned once, at its shallowest depth.  A plain recursive
        CTE over all link types never terminates on cycles (symmetric link types
        such as TERM_EQUIVALENT are cycles by construction) and a single
        connection stalls every other request while it spins, so the visited set
        is kept here instead.  Plain per-level queries also behave identically
        on DuckDB and PostgreSQL.
        """
        p = self.db.placeholder
        near, far = ("from_node_id", "to_node_id") if outbound else ("to_node_id", "from_node_id")
        link_filter = f"AND CAST(l.link_type_id AS VARCHAR) = {p}" if link_type_id is not None else ""
        node_cols = "n.node_id, n.graph_id, n.node_type_id, n.source_id, n.name, n.notes, n.metadata"

        start = _deserialise_nodes(conn.execute(
            f"SELECT {node_cols} FROM node n "
            f"WHERE CAST(n.node_id AS VARCHAR) = {p} AND CAST(n.graph_id AS VARCHAR) = {p}",
            [start_node_id, graph_id],
        ))
        if not start:
            return []

        start[0]["depth"] = 0
        results = [start[0]]
        seen = {str(start[0]["node_id"]).lower()}
        frontier = [str(start[0]["node_id"])]

        for depth in range(1, max_depth + 1):
            if not frontier:
                break
            reached: list[str] = []
            for i in range(0, len(frontier), self._CHUNK):
                chunk = frontier[i:i + self._CHUNK]
                marks = ", ".join([p] * len(chunk))
                params: list = [*chunk, graph_id]
                if link_type_id is not None:
                    params.append(link_type_id)
                cursor = conn.execute(
                    f"""
                    SELECT DISTINCT CAST(l.{far} AS VARCHAR) FROM link l
                    WHERE CAST(l.{near} AS VARCHAR) IN ({marks})
                      AND CAST(l.from_graph_id AS VARCHAR) = {p}
                      AND l.is_disabled = FALSE
                      {link_filter}
                    """,
                    params,
                )
                for (nid,) in cursor.fetchall():
                    if nid.lower() not in seen:
                        seen.add(nid.lower())
                        reached.append(nid)

            frontier = []
            for i in range(0, len(reached), self._CHUNK):
                chunk = reached[i:i + self._CHUNK]
                marks = ", ".join([p] * len(chunk))
                for node in _deserialise_nodes(conn.execute(
                    f"SELECT {node_cols} FROM node n WHERE CAST(n.node_id AS VARCHAR) IN ({marks})",
                    chunk,
                )):
                    node["depth"] = depth
                    results.append(node)
                    frontier.append(str(node["node_id"]))

        results.sort(key=lambda d: (d["depth"], d["name"]))
        return results

    def get_subtree(
        self,
        conn,
        graph_id: str,
        root_node_id: str,
        link_type_id: str | None = None,
        max_depth: int = _MAX_DEPTH,
    ) -> list[dict]:
        """
        Return *root_node_id* and all its descendants within *graph_id*.

        Results include a `depth` column (0 = root), ordered by depth then name.
        Each node appears once, at its shallowest depth; cycles terminate.

        *link_type_id* — restrict traversal to a specific link type (e.g. only
        HIERARCHICAL links).  When None, all non-disabled links are followed.
        """
        return self._walk(
            conn, graph_id, root_node_id,
            outbound=True, link_type_id=link_type_id, max_depth=max_depth,
        )

    def get_ancestors(
        self,
        conn,
        graph_id: str,
        node_id: str,
        link_type_id: str | None = None,
        max_depth: int = _MAX_DEPTH,
    ) -> list[dict]:
        """
        Return all ancestors of *node_id* within *graph_id*, excluding the node itself.

        `depth` = 1 is the immediate parent(s); higher values are further up the tree.
        Each node appears once, at its shallowest depth; cycles terminate.
        """
        rows = self._walk(
            conn, graph_id, node_id,
            outbound=False, link_type_id=link_type_id, max_depth=max_depth,
        )
        return [r for r in rows if r["depth"] > 0]

    def get_impact_summary(
        self,
        conn,
        graph_id: str,
        node_id: str,
    ) -> dict:
        """
        Pre-flight blast-radius report for a proposed destructive operation on *node_id*.

        Returns:
            {
              "node_id": str,
              "descendant_count": int,
              "descendants": [{"node_id", "name", "depth"}, ...],
              "cross_graph_link_count": int,
            }

        The service layer should inspect this before committing any DELETE or
        structural UPDATE that would cascade across the tree.
        """
        descendants = self.get_subtree(conn, graph_id, node_id)
        # Exclude the root node itself from the impact count
        affected = [d for d in descendants if d["node_id"] != node_id]

        # Count cross-graph links pointing INTO this node or its descendants
        p = self.db.placeholder
        desc_ids = [d["node_id"] for d in descendants]
        if desc_ids:
            placeholders = ", ".join([p] * len(desc_ids))
            cursor = conn.execute(
                f"""
                SELECT COUNT(*) FROM link
                WHERE to_node_id IN ({placeholders})
                  AND from_graph_id != to_graph_id
                  AND is_disabled = FALSE
                """,
                desc_ids,
            )
            cross_graph_count = int(cursor.fetchone()[0])
        else:
            cross_graph_count = 0

        return {
            "node_id": node_id,
            "descendant_count": len(affected),
            "descendants": [
                {"node_id": d["node_id"], "name": d["name"], "depth": d["depth"]}
                for d in affected
            ],
            "cross_graph_link_count": cross_graph_count,
        }
