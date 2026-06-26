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
    Graph traversal queries using recursive CTEs.

    These queries intentionally span both the `node` and `link` tables.
    They live here rather than in NodeDAO or LinkDAO because they are
    inherently cross-entity operations.

    Both DuckDB and PostgreSQL support the standard WITH RECURSIVE syntax used here.

    The caller (service layer) owns the connection and transaction.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_subtree(
        self,
        conn,
        graph_id: str,
        root_node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        """
        Return *root_node_id* and all its descendants within *graph_id*.

        Results include a `depth` column (0 = root).  Ordered depth-first by
        depth then name for predictable display ordering.

        *link_type_id* — restrict traversal to a specific link type (e.g. only
        HIERARCHICAL links).  When None, all non-disabled links are followed.
        """
        p = self.db.placeholder
        link_filter = f"AND l.link_type_id = {p}" if link_type_id is not None else ""
        sql = f"""
            WITH RECURSIVE subtree AS (
                -- Anchor: the root node itself
                SELECT
                    n.node_id, n.graph_id, n.node_type_id,
                    n.source_id, n.name, n.notes, n.metadata,
                    0 AS depth
                FROM node n
                WHERE n.node_id = {p}
                  AND n.graph_id = {p}

                UNION ALL

                -- Recursive: follow outbound links to children
                SELECT
                    n.node_id, n.graph_id, n.node_type_id,
                    n.source_id, n.name, n.notes, n.metadata,
                    st.depth + 1
                FROM node n
                JOIN link l ON l.to_node_id = n.node_id
                JOIN subtree st ON l.from_node_id = st.node_id
                WHERE l.from_graph_id = {p}
                  AND l.is_disabled = FALSE
                  {link_filter}
            )
            SELECT * FROM subtree ORDER BY depth, name
        """
        params: list = [root_node_id, graph_id, graph_id]
        if link_type_id is not None:
            params.append(link_type_id)
        return _deserialise_nodes(conn.execute(sql, params))

    def get_ancestors(
        self,
        conn,
        graph_id: str,
        node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        """
        Return all ancestors of *node_id* within *graph_id*, excluding the node itself.

        `depth` = 1 is the immediate parent(s); higher values are further up the tree.
        In a polyhierarchical graph there may be multiple rows at each depth level.
        """
        p = self.db.placeholder
        link_filter = f"AND l.link_type_id = {p}" if link_type_id is not None else ""
        sql = f"""
            WITH RECURSIVE ancestors AS (
                -- Anchor: the starting node (excluded from final result)
                SELECT
                    n.node_id, n.graph_id, n.node_type_id,
                    n.source_id, n.name, n.notes, n.metadata,
                    0 AS depth
                FROM node n
                WHERE n.node_id = {p}
                  AND n.graph_id = {p}

                UNION ALL

                -- Recursive: walk inbound links to parents
                SELECT
                    n.node_id, n.graph_id, n.node_type_id,
                    n.source_id, n.name, n.notes, n.metadata,
                    a.depth + 1
                FROM node n
                JOIN link l ON l.from_node_id = n.node_id
                JOIN ancestors a ON l.to_node_id = a.node_id
                WHERE l.from_graph_id = {p}
                  AND l.is_disabled = FALSE
                  {link_filter}
            )
            SELECT * FROM ancestors
            WHERE depth > 0
            ORDER BY depth, name
        """
        params: list = [node_id, graph_id, graph_id]
        if link_type_id is not None:
            params.append(link_type_id)
        return _deserialise_nodes(conn.execute(sql, params))

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
