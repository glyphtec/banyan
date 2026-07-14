from __future__ import annotations

from typing import TYPE_CHECKING

from banyan_platform.dao._utils import normalise_row

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


def _row(cursor, row) -> dict:
    return normalise_row(dict(zip([c[0] for c in cursor.description], row)))


def _rows(cursor) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    return [normalise_row(dict(zip(cols, r))) for r in cursor.fetchall()]


class StakeholderDAO:
    """
    DAO for the stakeholder registry tables:
      stakeholder, graph_stakeholder, node_stakeholder.

    All methods accept an open connection (caller owns the transaction).

    Reverse resolution (which stakeholders are affected by a node change) is
    handled by resolve_for_node(), which uses CTE-based traversal for V1.
    Closure-table indexing is deferred to V1.1.
    """

    def __init__(self, db: "Database") -> None:
        self.db = db

    # ── stakeholder CRUD ──────────────────────────────────────────────────────

    def insert(
        self,
        conn,
        name: str,
        org: str | None = None,
        contact_ref: str | None = None,
        actor_id: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Insert a new stakeholder and return its stakeholder_id."""
        p = self.db.placeholder
        cursor = conn.execute(
            f"""
            INSERT INTO stakeholder (name, org, contact_ref, actor_id, notes)
            VALUES ({p}, {p}, {p}, {p}, {p})
            RETURNING stakeholder_id
            """,
            [name, org, contact_ref, actor_id, notes],
        )
        return str(cursor.fetchone()[0])

    def get(self, conn, stakeholder_id: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM stakeholder WHERE CAST(stakeholder_id AS VARCHAR) = {p}",
            [stakeholder_id],
        )
        row = cursor.fetchone()
        return _row(cursor, row) if row else None

    def get_by_name(self, conn, name: str) -> dict | None:
        p = self.db.placeholder
        cursor = conn.execute(
            f"SELECT * FROM stakeholder WHERE name = {p}", [name]
        )
        row = cursor.fetchone()
        return _row(cursor, row) if row else None

    def list(self, conn) -> list[dict]:
        cursor = conn.execute("SELECT * FROM stakeholder ORDER BY name")
        return _rows(cursor)

    def update(
        self,
        conn,
        stakeholder_id: str,
        name: str | None = None,
        org: str | None = None,
        contact_ref: str | None = None,
        actor_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        p = self.db.placeholder
        sets, params = [], []
        if name        is not None: sets.append(f"name = {p}");        params.append(name)
        if org         is not None: sets.append(f"org = {p}");         params.append(org)
        if contact_ref is not None: sets.append(f"contact_ref = {p}"); params.append(contact_ref)
        if actor_id    is not None: sets.append(f"actor_id = {p}");    params.append(actor_id)
        if notes       is not None: sets.append(f"notes = {p}");       params.append(notes)
        if not sets:
            return
        sets.append("updated_datetime = CURRENT_TIMESTAMP")
        params.append(stakeholder_id)
        conn.execute(
            f"UPDATE stakeholder SET {', '.join(sets)} WHERE CAST(stakeholder_id AS VARCHAR) = {p}",
            params,
        )

    def delete(self, conn, stakeholder_id: str) -> None:
        p = self.db.placeholder
        conn.execute(
            f"DELETE FROM stakeholder WHERE CAST(stakeholder_id AS VARCHAR) = {p}",
            [stakeholder_id],
        )

    # ── graph_stakeholder ─────────────────────────────────────────────────────

    def attach_to_graph(
        self,
        conn,
        graph_id: str,
        stakeholder_id: str,
        role: str,
        notes: str | None = None,
    ) -> None:
        p = self.db.placeholder
        conn.execute(
            f"""
            INSERT INTO graph_stakeholder (graph_id, stakeholder_id, role, notes)
            VALUES ({p}, {p}, {p}, {p})
            ON CONFLICT (graph_id, stakeholder_id) DO UPDATE
                SET role = EXCLUDED.role,
                    notes = EXCLUDED.notes
            """,
            [graph_id, stakeholder_id, role, notes],
        )

    def detach_from_graph(self, conn, graph_id: str, stakeholder_id: str) -> None:
        p = self.db.placeholder
        conn.execute(
            f"""
            DELETE FROM graph_stakeholder
            WHERE CAST(graph_id AS VARCHAR) = {p}
              AND CAST(stakeholder_id AS VARCHAR) = {p}
            """,
            [graph_id, stakeholder_id],
        )

    def list_for_graph(self, conn, graph_id: str) -> list[dict]:
        p = self.db.placeholder
        cursor = conn.execute(
            f"""
            SELECT gs.*, s.name, s.org, s.contact_ref
            FROM graph_stakeholder gs
            JOIN stakeholder s
              ON CAST(gs.stakeholder_id AS VARCHAR) = CAST(s.stakeholder_id AS VARCHAR)
            WHERE CAST(gs.graph_id AS VARCHAR) = {p}
            ORDER BY s.name
            """,
            [graph_id],
        )
        return _rows(cursor)

    # ── node_stakeholder ──────────────────────────────────────────────────────

    def attach_to_node(
        self,
        conn,
        node_id: str,
        stakeholder_id: str,
        role: str,
        scope: str = "NODE_ONLY",
        scope_depth: int | None = None,
        scope_link_type_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        p = self.db.placeholder
        conn.execute(
            f"""
            INSERT INTO node_stakeholder
                (node_id, stakeholder_id, role, scope, scope_depth, scope_link_type_id, notes)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
            ON CONFLICT (node_id, stakeholder_id) DO UPDATE
                SET role = EXCLUDED.role,
                    scope = EXCLUDED.scope,
                    scope_depth = EXCLUDED.scope_depth,
                    scope_link_type_id = EXCLUDED.scope_link_type_id,
                    notes = EXCLUDED.notes
            """,
            [node_id, stakeholder_id, role, scope, scope_depth, scope_link_type_id, notes],
        )

    def detach_from_node(self, conn, node_id: str, stakeholder_id: str) -> None:
        p = self.db.placeholder
        conn.execute(
            f"""
            DELETE FROM node_stakeholder
            WHERE CAST(node_id AS VARCHAR) = {p}
              AND CAST(stakeholder_id AS VARCHAR) = {p}
            """,
            [node_id, stakeholder_id],
        )

    def list_for_node(self, conn, node_id: str) -> list[dict]:
        """Direct node_stakeholder rows (NODE_ONLY semantics, no traversal)."""
        p = self.db.placeholder
        cursor = conn.execute(
            f"""
            SELECT ns.*, s.name, s.org, s.contact_ref
            FROM node_stakeholder ns
            JOIN stakeholder s
              ON CAST(ns.stakeholder_id AS VARCHAR) = CAST(s.stakeholder_id AS VARCHAR)
            WHERE CAST(ns.node_id AS VARCHAR) = {p}
            ORDER BY s.name
            """,
            [node_id],
        )
        return _rows(cursor)

    # ── Reverse resolution ────────────────────────────────────────────────────

    def resolve_for_node(self, conn, node_id: str, graph_id: str) -> list[dict]:
        """
        Return all stakeholders with governance interest in *node_id*.

        Checks three attachment types in one query:
          1. NODE_ONLY  — direct attachment to this exact node.
          2. SUBGRAPH   — the node is a descendant of a SUBGRAPH attachment root
                          (recursive CTE walking outbound HIERARCHICAL links from root
                          downward; node_id must appear in the subtree).
          3. ANCESTORS  — the node is an ancestor of an ANCESTORS attachment root
                          (recursive CTE walking outbound HIERARCHICAL links upward
                          from node_id; any attachment root must appear in that chain).
          4. Graph-level — stakeholder is attached to the graph containing node_id.

        Returns deduplicated stakeholder rows annotated with the attachment_type
        ("NODE_ONLY", "SUBGRAPH", "ANCESTORS", "GRAPH") and role.

        V1: on-demand CTE traversal.  No closure table.
        """
        p = self.db.placeholder
        hierarchical_id = "ba0ba000-0000-0000-0000-000000000001"

        sql = f"""
        WITH RECURSIVE

        -- All HIERARCHICAL link types (root family ba0...001 and its sub-types)
        hier_types(link_type_id) AS (
            SELECT CAST(link_type_id AS VARCHAR)
            FROM link_type
            WHERE CAST(link_type_id AS VARCHAR) = '{hierarchical_id}'
               OR CAST(parent_link_type_id AS VARCHAR) = '{hierarchical_id}'
        ),

        -- Subtree rooted at each SUBGRAPH attachment node (walk DOWN from root).
        -- Used to check if the query node is a descendant of an attachment root.
        subgraph_descendants(root_node_id, descendant_id) AS (
            SELECT CAST(ns.node_id AS VARCHAR),
                   CAST(ns.node_id AS VARCHAR)
            FROM node_stakeholder ns
            WHERE ns.scope = 'SUBGRAPH'
              AND CAST(ns.node_id AS VARCHAR) IN (
                  SELECT CAST(node_id AS VARCHAR) FROM node
                  WHERE CAST(graph_id AS VARCHAR) = {p}
              )
            UNION ALL
            SELECT sd.root_node_id,
                   CAST(l.to_node_id AS VARCHAR)
            FROM subgraph_descendants sd
            JOIN link l
              ON CAST(l.from_node_id AS VARCHAR) = sd.descendant_id
             AND CAST(l.from_graph_id AS VARCHAR) = {p}
             AND CAST(l.to_graph_id   AS VARCHAR) = {p}
             AND CAST(l.link_type_id  AS VARCHAR) IN (SELECT link_type_id FROM hier_types)
             AND l.is_disabled = FALSE
        ),

        -- Descendants of the query node (walk DOWN from query node).
        -- Used to check whether any ANCESTORS-scoped attachment root is a descendant
        -- of the query node (i.e. the query node is an ancestor of the attachment root).
        query_descendants(descendant_id) AS (
            SELECT {p} AS descendant_id
            UNION ALL
            SELECT CAST(l.to_node_id AS VARCHAR)
            FROM query_descendants qd
            JOIN link l
              ON CAST(l.from_node_id AS VARCHAR) = qd.descendant_id
             AND CAST(l.from_graph_id AS VARCHAR) = {p}
             AND CAST(l.to_graph_id   AS VARCHAR) = {p}
             AND CAST(l.link_type_id  AS VARCHAR) IN (SELECT link_type_id FROM hier_types)
             AND l.is_disabled = FALSE
        )

        -- 1. NODE_ONLY: direct attachment to this node
        SELECT s.*, ns.role, 'NODE_ONLY' AS attachment_type
        FROM node_stakeholder ns
        JOIN stakeholder s
          ON CAST(ns.stakeholder_id AS VARCHAR) = CAST(s.stakeholder_id AS VARCHAR)
        WHERE CAST(ns.node_id AS VARCHAR) = {p}
          AND ns.scope = 'NODE_ONLY'

        UNION

        -- 2. SUBGRAPH: the query node is a descendant of a SUBGRAPH attachment root
        SELECT s.*, ns.role, 'SUBGRAPH' AS attachment_type
        FROM subgraph_descendants sd
        JOIN node_stakeholder ns
          ON CAST(ns.node_id AS VARCHAR) = sd.root_node_id
         AND ns.scope = 'SUBGRAPH'
        JOIN stakeholder s
          ON CAST(ns.stakeholder_id AS VARCHAR) = CAST(s.stakeholder_id AS VARCHAR)
        WHERE sd.descendant_id = {p}

        UNION

        -- 3. ANCESTORS: the query node is an ancestor of (or equal to) an attachment root.
        --    A stakeholder attached at node X with ANCESTORS scope cares about changes to
        --    X and all of X's ancestors.  We find this by walking DOWN from the query node
        --    and checking if any ANCESTORS attachment root appears among its descendants.
        SELECT s.*, ns.role, 'ANCESTORS' AS attachment_type
        FROM query_descendants qd
        JOIN node_stakeholder ns
          ON CAST(ns.node_id AS VARCHAR) = qd.descendant_id
         AND ns.scope = 'ANCESTORS'
        JOIN stakeholder s
          ON CAST(ns.stakeholder_id AS VARCHAR) = CAST(s.stakeholder_id AS VARCHAR)

        UNION

        -- 4. GRAPH-level attachment
        SELECT s.*, gs.role, 'GRAPH' AS attachment_type
        FROM graph_stakeholder gs
        JOIN stakeholder s
          ON CAST(gs.stakeholder_id AS VARCHAR) = CAST(s.stakeholder_id AS VARCHAR)
        WHERE CAST(gs.graph_id AS VARCHAR) = {p}
        """

        params = [
            graph_id,  # subgraph_descendants base filter
            graph_id,  # subgraph_descendants expand from_graph_id
            graph_id,  # subgraph_descendants expand to_graph_id
            node_id,   # query_descendants base
            graph_id,  # query_descendants expand from_graph_id
            graph_id,  # query_descendants expand to_graph_id
            node_id,   # NODE_ONLY where
            node_id,   # SUBGRAPH descendant_id
            graph_id,  # GRAPH attachment
        ]

        cursor = conn.execute(sql, params)
        return _rows(cursor)
