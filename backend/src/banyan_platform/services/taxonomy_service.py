from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from banyan_platform.dao.graph_dao import GraphDAO
from banyan_platform.dao.node_dao import NodeDAO
from banyan_platform.dao.link_dao import LinkDAO
from banyan_platform.dao.ledger_dao import LedgerDAO
from banyan_platform.dao.traversal_dao import TraversalDAO
from banyan_platform.dao.lookup_dao import LookupDAO
from banyan_platform.dao.snapshot_dao import SnapshotDAO
from banyan_platform.dao.query_dao import QueryDAO
from banyan_platform.dao.stakeholder_dao import StakeholderDAO
from banyan_platform.dao.memory_dao import MemoryDAO

if TYPE_CHECKING:
    from banyan_platform.persistence.connection import Database


class BanyanService:
    """
    Single service layer coordinating all Banyan DAOs.

    Owns transaction boundaries — every public method opens exactly one
    ``db.connect()`` context and passes the connection to whichever DAOs
    it needs.  No DAO ever calls ``db.connect()`` itself.

    Ledger discipline:
      - Every node/link mutation appends to ``banyan_ledger`` in the same
        transaction.  Graph-level CRUD is not ledgered (graph objects are
        metadata, not content).
      - ``primitive_verb`` values: ADD_NODE, UPDATE_NODE, DELETE_NODE,
        CREATE_LINK, UPDATE_LINK, DESTROY_LINK.
      - A logical operation (e.g. re-parenting = DESTROY_LINK + CREATE_LINK)
        groups both entries under one ``transaction_id``.

    Cross-graph constraint:
      HIERARCHICAL and SYNONYM link types must have from_graph_id == to_graph_id.
      Enforced here, not in DDL.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.graphs = GraphDAO(db)
        self.nodes = NodeDAO(db)
        self.links = LinkDAO(db)
        self.ledger = LedgerDAO(db)
        self.traversal = TraversalDAO(db)
        self.lookup = LookupDAO(db)
        self.snapshots = SnapshotDAO(db)
        self.query_dao = QueryDAO(db)
        self.stakeholders = StakeholderDAO(db)
        self.stakeholders = StakeholderDAO(db)
        self.memory = MemoryDAO(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_node_type_id(self, conn, node_type_id: str | None) -> str:
        if node_type_id is not None:
            return node_type_id
        nt = self.lookup.get_node_type_by_name(conn, "Generic")
        if nt is None:
            raise RuntimeError("Default node type 'Generic' not found. Run bootstrap() first.")
        return nt["node_type_id"]

    # ── Graph operations (no ledger) ──────────────────────────────────────────

    _ROOT_SOURCE_ID = "$ROOT$"

    def create_graph(
        self,
        name: str,
        actor_id: str,
        notes: str | None = None,
        topology_id: str | None = None,
    ) -> dict:
        """
        Create a graph and atomically bootstrap its mandatory root node.

        Every graph is born with a single ``$ROOT$`` node whose ``source_id``
        and ``name`` are both ``"$ROOT$"``.  The graph's ``root_node_id`` is
        set in the same transaction.  An ADD_NODE ledger entry is written so
        the graph immediately has auditable history.
        """
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            graph_id = self.graphs.insert(
                conn, name=name, notes=notes,
                topology_id=topology_id, actor_id=actor_id,
            )
            resolved_type_id = self._resolve_node_type_id(conn, None)
            root_node_id = self.nodes.insert(
                conn,
                graph_id=graph_id,
                node_type_id=resolved_type_id,
                source_id=self._ROOT_SOURCE_ID,
                name=self._ROOT_SOURCE_ID,
                actor_id=actor_id,
            )
            self.graphs.set_root_node(conn, graph_id, root_node_id)
            root_node = self.nodes.get(conn, root_node_id)
            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="ADD_NODE",
                source_graph_id=graph_id,
                entity_id=root_node_id,
                payload=root_node,
                reversal_payload={"node_id": root_node_id},
            )
            return self.graphs.get(conn, graph_id)

    def get_graph(self, graph_id: str) -> dict:
        with self.db.connect() as conn:
            g = self.graphs.get(conn, graph_id)
        if g is None:
            raise KeyError(f"Graph '{graph_id}' not found.")
        return g

    def list_graphs(self) -> list[dict]:
        with self.db.connect() as conn:
            return self.graphs.list(conn)

    def update_graph(
        self,
        graph_id: str,
        actor_id: str,
        name: str | None = None,
        notes: str | None = None,
        topology_id: str | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            if self.graphs.get(conn, graph_id) is None:
                raise KeyError(f"Graph '{graph_id}' not found.")
            self.graphs.update(
                conn, graph_id,
                name=name, notes=notes, topology_id=topology_id,
                actor_id=actor_id,
            )
            return self.graphs.get(conn, graph_id)

    def delete_graph(self, graph_id: str, actor_id: str) -> None:
        """Delete a graph.  Raises if the graph still contains nodes."""
        with self.db.connect() as conn:
            if self.graphs.get(conn, graph_id) is None:
                raise KeyError(f"Graph '{graph_id}' not found.")
            node_count = len(self.nodes.list_by_graph(conn, graph_id))
            if node_count > 0:
                raise ValueError(
                    f"Graph '{graph_id}' contains {node_count} node(s). "
                    "Delete all nodes before deleting the graph."
                )
            self.graphs.delete(conn, graph_id)

    def purge_graph(self, graph_id: str) -> dict:
        """
        Hard-delete a graph and all its content with prejudice.

        Dev/debug environments only.  Skips ledger discipline, referential
        integrity checks, and the "empty first" guard on delete_graph.

        Deletes in FK-safe order:
          1. All links where from_graph_id OR to_graph_id matches.
          2. All nodes belonging to the graph.
          3. All ledger entries referencing the graph.
          4. All snapshots belonging to the graph.
          5. The graph row itself.

        Returns a summary dict of row counts deleted.
        """
        p = self.db.placeholder
        with self.db.connect() as conn:
            if self.graphs.get(conn, graph_id) is None:
                raise KeyError(f"Graph '{graph_id}' not found.")

            cur = conn.execute(
                f"DELETE FROM link WHERE CAST(from_graph_id AS VARCHAR) = {p} OR CAST(to_graph_id AS VARCHAR) = {p}",
                [graph_id, graph_id],
            )
            links_deleted = cur.rowcount if cur.rowcount is not None else -1

            cur = conn.execute(
                f"DELETE FROM node WHERE CAST(graph_id AS VARCHAR) = {p}", [graph_id]
            )
            nodes_deleted = cur.rowcount if cur.rowcount is not None else -1

            cur = conn.execute(
                f"DELETE FROM banyan_ledger WHERE CAST(source_graph_id AS VARCHAR) = {p}", [graph_id]
            )
            ledger_deleted = cur.rowcount if cur.rowcount is not None else -1

            cur = conn.execute(
                f"DELETE FROM snapshot WHERE graph_id = {p}", [graph_id]
            )
            snapshots_deleted = cur.rowcount if cur.rowcount is not None else -1

            self.graphs.delete(conn, graph_id)

        return {
            "graph_id": graph_id,
            "links_deleted": links_deleted,
            "nodes_deleted": nodes_deleted,
            "ledger_entries_deleted": ledger_deleted,
            "snapshots_deleted": snapshots_deleted,
        }

    # ── Node operations ───────────────────────────────────────────────────────

    def add_node(
        self,
        graph_id: str,
        source_id: str,
        name: str,
        actor_id: str,
        notes: str | None = None,
        metadata: dict | None = None,
        node_type_id: str | None = None,
    ) -> dict:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            resolved_type_id = self._resolve_node_type_id(conn, node_type_id)
            node_id = self.nodes.insert(
                conn,
                graph_id=graph_id,
                node_type_id=resolved_type_id,
                source_id=source_id,
                name=name,
                notes=notes,
                metadata=metadata,
                actor_id=actor_id,
            )
            node = self.nodes.get(conn, node_id)
            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="ADD_NODE",
                source_graph_id=graph_id,
                entity_id=node_id,
                payload=node,
                reversal_payload={"node_id": node_id},
            )
            return node

    def get_node(self, node_id: str) -> dict:
        with self.db.connect() as conn:
            n = self.nodes.get(conn, node_id)
        if n is None:
            raise KeyError(f"Node '{node_id}' not found.")
        return n

    def list_nodes(self, graph_id: str) -> list[dict]:
        with self.db.connect() as conn:
            return self.nodes.list_by_graph(conn, graph_id)

    def update_node(
        self,
        node_id: str,
        actor_id: str,
        name: str | None = None,
        notes: str | None = None,
        source_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            prior = self.nodes.get(conn, node_id)
            if prior is None:
                raise KeyError(f"Node '{node_id}' not found.")
            delta: dict = {}
            if name is not None:      delta["name"] = name
            if notes is not None:     delta["notes"] = notes
            if source_id is not None: delta["source_id"] = source_id
            if metadata is not None:  delta["metadata"] = metadata
            if not delta:
                return prior
            self.nodes.update(conn, node_id, **delta, actor_id=actor_id)
            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="UPDATE_NODE",
                source_graph_id=prior["graph_id"],
                entity_id=node_id,
                payload=delta,
                reversal_payload={k: prior[k] for k in delta},
            )
            return self.nodes.get(conn, node_id)

    def delete_node(
        self,
        node_id: str,
        actor_id: str,
        force: bool = False,
    ) -> dict:
        """
        Delete a node and all links touching it.

        Pre-flight safety checks (both overridable with ``force=True``):
          - Outbound links exist  → node has dependents; callers should
            resolve children before deleting a parent.
          - Cross-graph links exist → deletion affects other graphs.

        Returns a summary of what was destroyed.
        """
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            node = self.nodes.get(conn, node_id)
            if node is None:
                raise KeyError(f"Node '{node_id}' not found.")

            all_links = self.links.get_all_for_node(conn, node_id)
            outbound = [lk for lk in all_links if lk["from_node_id"] == node_id]
            cross_graph = [
                lk for lk in all_links
                if lk["from_graph_id"] != lk["to_graph_id"]
            ]

            if outbound and not force:
                raise ValueError(
                    f"Node '{node_id}' has {len(outbound)} outbound link(s). "
                    "Remove them first, or pass force=True."
                )
            if cross_graph and not force:
                raise ValueError(
                    f"Node '{node_id}' is involved in {len(cross_graph)} "
                    "cross-graph link(s). Pass force=True to delete anyway."
                )

            for lk in all_links:
                cross = lk["from_graph_id"] != lk["to_graph_id"]
                self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="DESTROY_LINK",
                    source_graph_id=lk["from_graph_id"],
                    target_graph_id=lk["to_graph_id"] if cross else None,
                    entity_id=lk["link_id"],
                    payload={"link_id": lk["link_id"]},
                    reversal_payload=lk,
                )
                self.links.delete(conn, lk["link_id"])

            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="DELETE_NODE",
                source_graph_id=node["graph_id"],
                entity_id=node_id,
                payload={"node_id": node_id},
                reversal_payload=node,
            )
            self.nodes.delete(conn, node_id)

        return {
            "deleted_node_id": node_id,
            "destroyed_link_count": len(all_links),
        }

    # ── Link operations ───────────────────────────────────────────────────────

    def create_link(
        self,
        link_type_id: str,
        from_graph_id: str,
        to_graph_id: str,
        from_node_id: str,
        to_node_id: str,
        actor_id: str,
        link_order: float = 0.0,
        metadata: dict | None = None,
        valid_from_datetime: datetime | None = None,
        valid_until_datetime: datetime | None = None,
    ) -> dict:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            family = self.lookup.get_link_type_root_family(conn, link_type_id)
            if family in ("HIERARCHICAL", "SYNONYM") and from_graph_id != to_graph_id:
                raise ValueError(
                    f"{family} links must remain within a single graph "
                    f"(from_graph_id={from_graph_id!r}, to_graph_id={to_graph_id!r})."
                )
            lt = self.lookup.get_link_type(conn, link_type_id)
            if lt and lt.get("is_symmetric"):
                p = self.db.placeholder
                reverse = conn.execute(
                    f"SELECT link_id FROM link WHERE "
                    f"CAST(from_node_id AS VARCHAR) = {p} AND "
                    f"CAST(to_node_id   AS VARCHAR) = {p} AND "
                    f"CAST(link_type_id AS VARCHAR) = {p} LIMIT 1",
                    [str(to_node_id), str(from_node_id), str(link_type_id)],
                ).fetchone()
                if reverse:
                    raise ValueError(
                        f"Reverse link already exists (link_id={reverse[0]}). "
                        f"{lt['name']} is symmetric — the existing link covers both directions."
                    )
            try:
                link_id = self.links.insert(
                    conn,
                    link_type_id=link_type_id,
                    from_graph_id=from_graph_id,
                    to_graph_id=to_graph_id,
                    from_node_id=from_node_id,
                    to_node_id=to_node_id,
                    link_order=link_order,
                    metadata=metadata,
                    valid_from_datetime=valid_from_datetime,
                    valid_until_datetime=valid_until_datetime,
                    actor_id=actor_id,
                )
            except Exception as exc:
                msg = str(exc).lower()
                if "unique" in msg or "constraint" in msg or "duplicate" in msg:
                    raise ValueError(
                        f"A link of this type already exists between "
                        f"node '{from_node_id}' and node '{to_node_id}'."
                    ) from exc
                raise
            link = self.links.get(conn, link_id)
            cross = from_graph_id != to_graph_id
            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="CREATE_LINK",
                source_graph_id=from_graph_id,
                target_graph_id=to_graph_id if cross else None,
                entity_id=link_id,
                payload=link,
                reversal_payload={"link_id": link_id},
            )
            return link

    def get_link(self, link_id: str) -> dict:
        with self.db.connect() as conn:
            lk = self.links.get(conn, link_id)
        if lk is None:
            raise KeyError(f"Link '{link_id}' not found.")
        return lk

    def update_link(
        self,
        link_id: str,
        actor_id: str,
        link_order: float | None = None,
        metadata: dict | None = None,
        is_disabled: bool | None = None,
        valid_from_datetime: datetime | None = None,
        valid_until_datetime: datetime | None = None,
    ) -> dict:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            prior = self.links.get(conn, link_id)
            if prior is None:
                raise KeyError(f"Link '{link_id}' not found.")
            delta: dict = {}
            if link_order is not None:          delta["link_order"] = link_order
            if metadata is not None:            delta["metadata"] = metadata
            if is_disabled is not None:         delta["is_disabled"] = is_disabled
            if valid_from_datetime is not None: delta["valid_from_datetime"] = valid_from_datetime
            if valid_until_datetime is not None: delta["valid_until_datetime"] = valid_until_datetime
            if not delta:
                return prior
            self.links.update(conn, link_id, **delta, actor_id=actor_id)
            cross = prior["from_graph_id"] != prior["to_graph_id"]
            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="UPDATE_LINK",
                source_graph_id=prior["from_graph_id"],
                target_graph_id=prior["to_graph_id"] if cross else None,
                entity_id=link_id,
                payload=delta,
                reversal_payload={k: prior[k] for k in delta},
            )
            return self.links.get(conn, link_id)

    def destroy_link(self, link_id: str, actor_id: str) -> None:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            lk = self.links.get(conn, link_id)
            if lk is None:
                raise KeyError(f"Link '{link_id}' not found.")
            cross = lk["from_graph_id"] != lk["to_graph_id"]
            self.ledger.append(
                conn,
                transaction_id=txn_id,
                actor_id=actor_id,
                primitive_verb="DESTROY_LINK",
                source_graph_id=lk["from_graph_id"],
                target_graph_id=lk["to_graph_id"] if cross else None,
                entity_id=link_id,
                payload={"link_id": link_id},
                reversal_payload=lk,
            )
            self.links.delete(conn, link_id)

    def get_children(
        self, graph_id: str, from_node_id: str, link_type_id: str | None = None
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.links.get_children(conn, graph_id, from_node_id, link_type_id)

    def get_parents(
        self, graph_id: str, to_node_id: str, link_type_id: str | None = None
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.links.get_parents(conn, graph_id, to_node_id, link_type_id)

    # ── Traversal (read-only, no ledger) ──────────────────────────────────────

    def get_subtree(
        self,
        graph_id: str,
        root_node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.traversal.get_subtree(conn, graph_id, root_node_id, link_type_id)

    def get_ancestors(
        self,
        graph_id: str,
        node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.traversal.get_ancestors(conn, graph_id, node_id, link_type_id)

    def get_impact_summary(self, graph_id: str, node_id: str) -> dict:
        with self.db.connect() as conn:
            return self.traversal.get_impact_summary(conn, graph_id, node_id)

    # ── Export / Import / Diff / Batch ────────────────────────────────────────

    def export_graph(
        self,
        graph_id: str,
        include_cross_graph_links: bool = False,
    ) -> dict:
        """
        Serialize the full graph state as a portable document.

        Structure:
            {
              "banyan_export_version": "1.0",
              "exported_at": "<ISO-8601>",
              "graph": { ... },
              "nodes": [ ... ],
              "links": [ ... ],          # intra-graph links only by default
              "cross_graph_links": [ ... ]  # outbound cross-graph links (opt-in)
            }

        ``graph_id`` must exist.  Returns a plain dict (JSON-serializable).
        """
        with self.db.connect() as conn:
            graph = self.graphs.get(conn, graph_id)
            if graph is None:
                raise KeyError(f"Graph '{graph_id}' not found.")

            all_nodes = self.nodes.list_by_graph(conn, graph_id)
            # Exclude the implicit $ROOT$ node — it is bootstrapped automatically
            # on every graph creation and is not part of user-managed content.
            nodes = [n for n in all_nodes if n["source_id"] != self._ROOT_SOURCE_ID]

            # node_id → source_id (include $ROOT$ so link annotations are complete)
            node_id_to_source: dict[str, str] = {
                n["node_id"]: n["source_id"] for n in all_nodes
            }
            # link_type_id → name for human-readable link annotations
            lt_id_to_name: dict[int, str] = {
                lt["link_type_id"]: lt["name"]
                for lt in self.lookup.get_link_types(conn)
            }

            def _annotate(raw_links: list[dict]) -> list[dict]:
                out = []
                for lk in raw_links:
                    a = dict(lk)
                    a["from_source_id"] = node_id_to_source.get(
                        lk["from_node_id"], lk["from_node_id"]
                    )
                    a["to_source_id"] = node_id_to_source.get(
                        lk["to_node_id"], lk["to_node_id"]
                    )
                    a["link_type_name"] = lt_id_to_name.get(lk["link_type_id"])
                    out.append(a)
                return out

            p = self.db.placeholder
            cursor = conn.execute(
                f"SELECT * FROM link WHERE CAST(from_graph_id AS VARCHAR) = {p} AND CAST(to_graph_id AS VARCHAR) = {p}",
                [graph_id, graph_id],
            )
            cols = [c[0] for c in cursor.description]
            from banyan_platform.dao._utils import normalise_row
            intra_links = _annotate(
                [normalise_row(dict(zip(cols, row))) for row in cursor.fetchall()]
            )

            cross_links: list[dict] = []
            if include_cross_graph_links:
                cursor2 = conn.execute(
                    f"SELECT * FROM link WHERE ("
                    f"  CAST(from_graph_id AS VARCHAR) = {p} AND CAST(to_graph_id AS VARCHAR) != {p}"
                    f") OR ("
                    f"  CAST(to_graph_id AS VARCHAR) = {p} AND CAST(from_graph_id AS VARCHAR) != {p}"
                    f")",
                    [graph_id, graph_id, graph_id, graph_id],
                )
                cols2 = [c[0] for c in cursor2.description]
                cross_links = _annotate(
                    [normalise_row(dict(zip(cols2, row))) for row in cursor2.fetchall()]
                )

        return {
            "banyan_export_version": "1.1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "graph": graph,
            "nodes": nodes,
            "links": intra_links,
            "cross_graph_links": cross_links,
        }

    def import_graph(
        self,
        export_doc: dict,
        actor_id: str,
        new_name: str | None = None,
        merge_into_graph_id: str | None = None,
    ) -> dict:
        """
        Import an export document into a new graph (default) or merge nodes/links
        into an existing graph.

        New graph mode (``merge_into_graph_id`` is None):
          - Creates a fresh graph using ``new_name`` (or the original graph name).
          - Imports all nodes (preserving ``source_id``).
          - Imports all intra-graph links.
          - Duplicate ``source_id`` values are skipped (idempotent re-import).

        Merge mode (``merge_into_graph_id`` provided):
          - Adds nodes whose ``source_id`` does not already exist in the target.
          - Adds intra-graph links whose (from_node_id, to_node_id) pair does not
            already exist in the target (matched by source_id of the endpoint nodes).
          - Cross-graph links in the export document are ignored.

        Returns the target graph dict.
        """
        nodes_doc: list[dict] = export_doc.get("nodes", [])
        links_doc: list[dict] = export_doc.get("links", [])
        src_graph: dict = export_doc.get("graph", {})

        with self.db.connect() as conn:
            # ── Resolve or create the target graph ──────────────────────────
            if merge_into_graph_id:
                target_graph = self.graphs.get(conn, merge_into_graph_id)
                if target_graph is None:
                    raise KeyError(f"Target graph '{merge_into_graph_id}' not found.")
                target_graph_id = merge_into_graph_id
                existing_root = self.nodes.get_by_source(
                    conn, target_graph_id, self._ROOT_SOURCE_ID
                )
                root_node_id = existing_root["node_id"] if existing_root else None
            else:
                name = new_name or src_graph.get("name", "Imported Graph")
                target_graph_id = self.graphs.insert(
                    conn,
                    name=name,
                    notes=src_graph.get("notes"),
                    topology_id=src_graph.get("topology_id"),
                    actor_id=actor_id,
                )
                # Bootstrap $ROOT$ inline — mirrors create_graph() but cannot call
                # it here since we are already inside an open connection.
                resolved_nt_id = self._resolve_node_type_id(conn, None)
                root_node_id = self.nodes.insert(
                    conn,
                    graph_id=target_graph_id,
                    node_type_id=resolved_nt_id,
                    source_id=self._ROOT_SOURCE_ID,
                    name=self._ROOT_SOURCE_ID,
                    actor_id=actor_id,
                )
                self.graphs.set_root_node(conn, target_graph_id, root_node_id)
                root_node = self.nodes.get(conn, root_node_id)
                self.ledger.append(
                    conn,
                    transaction_id=str(uuid.uuid4()),
                    actor_id=actor_id,
                    primitive_verb="ADD_NODE",
                    source_graph_id=target_graph_id,
                    entity_id=root_node_id,
                    payload=root_node,
                    reversal_payload={"node_id": root_node_id},
                )

            # ── Pre-load lookup tables ───────────────────────────────────────
            default_node_type = self.lookup.get_node_type_by_name(conn, "Generic")
            default_nt_id = default_node_type["node_type_id"]
            lt_name_to_id: dict[str, str] = {
                lt["name"]: lt["link_type_id"]
                for lt in self.lookup.get_link_types(conn)
            }

            # ── Import nodes ─────────────────────────────────────────────────
            # node_id_map  : old UUID → new UUID  (backward compat, v1.0 format)
            # source_id_map: source_id → new UUID  (primary path, v1.1 format)
            node_id_map: dict[str, str] = {}
            source_id_map: dict[str, str] = {self._ROOT_SOURCE_ID: root_node_id}

            for n in nodes_doc:
                # $ROOT$ is already bootstrapped; skip insert but register mapping
                if n["source_id"] == self._ROOT_SOURCE_ID:
                    if n.get("node_id"):
                        node_id_map[n["node_id"]] = root_node_id
                    continue

                existing = self.nodes.get_by_source(conn, target_graph_id, n["source_id"])
                if existing:
                    if n.get("node_id"):
                        node_id_map[n["node_id"]] = existing["node_id"]
                    source_id_map[n["source_id"]] = existing["node_id"]
                    continue

                new_node_id = self.nodes.insert(
                    conn,
                    graph_id=target_graph_id,
                    source_id=n["source_id"],
                    name=n["name"],
                    notes=n.get("notes"),
                    metadata=n.get("metadata"),
                    node_type_id=n.get("node_type_id") or default_nt_id,
                    actor_id=actor_id,
                )
                node_data = self.nodes.get(conn, new_node_id)
                self.ledger.append(
                    conn,
                    transaction_id=str(uuid.uuid4()),
                    actor_id=actor_id,
                    primitive_verb="ADD_NODE",
                    source_graph_id=target_graph_id,
                    entity_id=new_node_id,
                    payload=node_data,
                    reversal_payload={"node_id": new_node_id},
                )
                if n.get("node_id"):
                    node_id_map[n["node_id"]] = new_node_id
                source_id_map[n["source_id"]] = new_node_id

            # ── Import links ─────────────────────────────────────────────────
            for lk in links_doc:
                # Resolve link type: accept link_type_id (int) or link_type_name
                lt_id = lk.get("link_type_id")
                if lt_id is None:
                    lt_id = lt_name_to_id.get(lk.get("link_type_name", ""))
                if not lt_id:
                    continue  # unresolvable link type

                # Resolve endpoints: prefer source_id (v1.1); fall back to
                # UUID node_id_map for backward compat with v1.0 format.
                new_from = (
                    source_id_map.get(lk["from_source_id"])
                    if lk.get("from_source_id")
                    else node_id_map.get(lk.get("from_node_id", ""))
                )
                new_to = (
                    source_id_map.get(lk["to_source_id"])
                    if lk.get("to_source_id")
                    else node_id_map.get(lk.get("to_node_id", ""))
                )
                if new_from is None or new_to is None:
                    continue  # unresolvable endpoint

                # Dedup: skip if this (parent, child, link_type) already exists
                existing_links = self.links.get_children(
                    conn, target_graph_id, new_from, lt_id
                )
                if any(el["to_node_id"] == new_to for el in existing_links):
                    continue

                new_link_id = self.links.insert(
                    conn,
                    link_type_id=lt_id,
                    from_graph_id=target_graph_id,
                    to_graph_id=target_graph_id,
                    from_node_id=new_from,
                    to_node_id=new_to,
                    actor_id=actor_id,
                    metadata=lk.get("metadata"),
                )
                link_data = self.links.get(conn, new_link_id)
                self.ledger.append(
                    conn,
                    transaction_id=str(uuid.uuid4()),
                    actor_id=actor_id,
                    primitive_verb="CREATE_LINK",
                    source_graph_id=target_graph_id,
                    entity_id=new_link_id,
                    payload=link_data,
                    reversal_payload={"link_id": new_link_id},
                )

            return self.graphs.get(conn, target_graph_id)

    def clone_graph(
        self,
        source_graph_id: str,
        new_name: str,
        actor_id: str,
    ) -> dict:
        """
        Duplicate a graph under a new name.

        Exports the source graph (intra-graph links only — cross-graph links are
        not cloned; the clone starts as a standalone graph) and re-imports it as
        a fresh graph with ``new_name``.  Source-id uniqueness and node ordering
        are preserved.  Returns the new graph dict.
        """
        export_doc = self.export_graph(source_graph_id, include_cross_graph_links=False)
        return self.import_graph(export_doc, actor_id=actor_id, new_name=new_name)

    def diff_graphs(
        self,
        base: str | dict,
        compare: str | dict,
        include_cross_graph_links: bool = False,
    ) -> dict:
        """
        Compare two graph states and return a structured delta.

        Each argument may be:
          - A ``graph_id`` string  → live graph is exported on-the-fly
          - A ``snapshot_id`` string prefixed with ``"snapshot:"``
            e.g. ``"snapshot:abc123"``
          - A pre-built export document dict

        Returns:
            {
              "nodes_added":    [ ... ],   # in compare, not in base (by source_id)
              "nodes_removed":  [ ... ],   # in base, not in compare (by source_id)
              "nodes_changed":  [ ... ],   # same source_id, different name/notes/metadata
              "links_added":    [ ... ],   # (from source_id, to source_id) in compare not base
              "links_removed":  [ ... ],
            }
        """
        base_doc = self._resolve_export(base, include_cross_graph_links)
        cmp_doc = self._resolve_export(compare, include_cross_graph_links)

        # Index by source_id
        base_nodes = {n["source_id"]: n for n in base_doc["nodes"]}
        cmp_nodes = {n["source_id"]: n for n in cmp_doc["nodes"]}

        nodes_added = [n for sid, n in cmp_nodes.items() if sid not in base_nodes]
        nodes_removed = [n for sid, n in base_nodes.items() if sid not in cmp_nodes]
        nodes_changed = []
        for sid in base_nodes.keys() & cmp_nodes.keys():
            b, c = base_nodes[sid], cmp_nodes[sid]
            if b["name"] != c["name"] or b.get("notes") != c.get("notes") or b.get("metadata") != c.get("metadata"):
                nodes_changed.append({"base": b, "compare": c})

        # Index links by (from source_id, to source_id, link_type_id)
        def _link_key(l: dict, nodes_by_id: dict) -> tuple | None:
            # Prefer annotated source_ids (v1.1); fall back to UUID lookup (v1.0)
            frm = l.get("from_source_id") or nodes_by_id.get(
                l.get("from_node_id", ""), {}
            ).get("source_id")
            to = l.get("to_source_id") or nodes_by_id.get(
                l.get("to_node_id", ""), {}
            ).get("source_id")
            if frm is None or to is None:
                return None
            return (frm, to, l["link_type_id"])

        base_nodes_by_id = {n["node_id"]: n for n in base_doc["nodes"]}
        cmp_nodes_by_id = {n["node_id"]: n for n in cmp_doc["nodes"]}

        base_links: dict[tuple, dict] = {}
        for l in base_doc["links"]:
            k = _link_key(l, base_nodes_by_id)
            if k:
                base_links[k] = l

        cmp_links: dict[tuple, dict] = {}
        for l in cmp_doc["links"]:
            k = _link_key(l, cmp_nodes_by_id)
            if k:
                cmp_links[k] = l

        links_added = [l for k, l in cmp_links.items() if k not in base_links]
        links_removed = [l for k, l in base_links.items() if k not in cmp_links]

        return {
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "nodes_changed": nodes_changed,
            "links_added": links_added,
            "links_removed": links_removed,
        }

    def _resolve_export(self, ref: str | dict, include_cross_graph_links: bool) -> dict:
        """Resolve a graph_id, 'snapshot:<id>', or export dict to an export document."""
        if isinstance(ref, dict):
            return ref
        if isinstance(ref, str) and ref.startswith("snapshot:"):
            snapshot_id = ref[len("snapshot:"):]
            with self.db.connect() as conn:
                snap = self.snapshots.get(conn, snapshot_id)
            if snap is None:
                raise KeyError(f"Snapshot '{snapshot_id}' not found.")
            payload = snap.get("snapshot_payload")
            if not payload or payload == {}:
                raise ValueError(
                    f"Snapshot '{snapshot_id}' has no stored payload. "
                    "It may have been created before export-backed snapshots were introduced."
                )
            return payload
        # Treat as graph_id
        return self.export_graph(ref, include_cross_graph_links=include_cross_graph_links)

    # ── Batch execution ───────────────────────────────────────────────────────

    def execute_batch(self, batch: dict, actor_id: str | None = None) -> dict:
        """
        Execute a batch of node and link operations atomically in one transaction.

        Batch document structure:
            {
              "graph_id": "<uuid>",
              "actor_id": "<str>",           # optional, overridden by actor_id param
              "default_link_type_id": <int>, # fallback link_type_id for CREATE_LINK ops
              "node_operations": [
                  { "verb": "ADD_NODE",    "data": { "source_id": "...", "name": "..." } },
                  { "verb": "UPDATE_NODE", "data": { "node_id": "...", "name": "..." } },
                  { "verb": "DELETE_NODE", "data": { "node_id": "...", "force": false } }
              ],
              "link_operations": [
                  { "verb": "CREATE_LINK",  "data": { "from_node_id": "...", "to_node_id": "..." } },
                  { "verb": "UPDATE_LINK",  "data": { "link_id": "...", ... } },
                  { "verb": "DESTROY_LINK", "data": { "link_id": "..." } }
              ]
            }

        Execution order (4-phase, always):
          1. ADD_NODE / UPDATE_NODE
          2. CREATE_LINK / UPDATE_LINK
          3. DESTROY_LINK
          4. DELETE_NODE

        Every mutation produces its own ledger entry.  All phases run inside one
        DB transaction — any failure rolls back the entire batch.

        Returns:
            {
              "graph_id": "...",
              "nodes_added": int,
              "nodes_updated": int,
              "nodes_deleted": int,
              "links_created": int,
              "links_updated": int,
              "links_destroyed": int,
              "ledger_entries": int,
            }
        """
        graph_id: str = batch["graph_id"]
        effective_actor = actor_id or batch.get("actor_id", "batch-anonymous")
        default_lt_id: str | None = batch.get("default_link_type_id")
        node_ops: list[dict] = batch.get("node_operations", [])
        link_ops: list[dict] = batch.get("link_operations", [])

        # Partition link ops into phases
        create_update_links = [o for o in link_ops if o["verb"] in ("CREATE_LINK", "UPDATE_LINK")]
        destroy_links = [o for o in link_ops if o["verb"] == "DESTROY_LINK"]

        # Partition node ops into phases
        add_update_nodes = [o for o in node_ops if o["verb"] in ("ADD_NODE", "UPDATE_NODE")]
        delete_nodes = [o for o in node_ops if o["verb"] == "DELETE_NODE"]

        counters = dict(nodes_added=0, nodes_updated=0, nodes_deleted=0,
                        links_created=0, links_updated=0, links_destroyed=0,
                        ledger_entries=0)

        default_nt_id: str | None = None

        with self.db.connect() as conn:
            if self.graphs.get(conn, graph_id) is None:
                raise KeyError(f"Graph '{graph_id}' not found.")

            # ── Phase 1: ADD / UPDATE nodes ──────────────────────────────────
            for op in add_update_nodes:
                verb = op["verb"]
                data = op["data"]
                txn_id = str(uuid.uuid4())

                if verb == "ADD_NODE":
                    if default_nt_id is None:
                        nt = self.lookup.get_node_type_by_name(conn, "Generic")
                        default_nt_id = nt["node_type_id"]
                    node_id = self.nodes.insert(
                        conn,
                        graph_id=graph_id,
                        source_id=data["source_id"],
                        name=data["name"],
                        notes=data.get("notes"),
                        metadata=data.get("metadata"),
                        node_type_id=data.get("node_type_id") or default_nt_id,
                        actor_id=effective_actor,
                    )
                    node_data = self.nodes.get(conn, node_id)
                    self.ledger.append(
                        conn, transaction_id=txn_id, actor_id=effective_actor,
                        primitive_verb="ADD_NODE", source_graph_id=graph_id,
                        entity_id=node_id, payload=node_data,
                        reversal_payload={"node_id": node_id},
                    )
                    counters["nodes_added"] += 1
                    counters["ledger_entries"] += 1

                elif verb == "UPDATE_NODE":
                    node_id = data["node_id"]
                    prior = self.nodes.get(conn, node_id)
                    if prior is None:
                        raise KeyError(f"Node '{node_id}' not found (UPDATE_NODE).")
                    self.nodes.update(
                        conn, node_id,
                        name=data.get("name"),
                        notes=data.get("notes"),
                        metadata=data.get("metadata"),
                        node_type_id=data.get("node_type_id"),
                        actor_id=effective_actor,
                    )
                    updated = self.nodes.get(conn, node_id)
                    self.ledger.append(
                        conn, transaction_id=txn_id, actor_id=effective_actor,
                        primitive_verb="UPDATE_NODE", source_graph_id=graph_id,
                        entity_id=node_id, payload=updated, reversal_payload=prior,
                    )
                    counters["nodes_updated"] += 1
                    counters["ledger_entries"] += 1

            # ── Phase 2: CREATE / UPDATE links ───────────────────────────────
            for op in create_update_links:
                verb = op["verb"]
                data = op["data"]
                txn_id = str(uuid.uuid4())

                if verb == "CREATE_LINK":
                    lt_id = data.get("link_type_id") or default_lt_id
                    if lt_id is None:
                        raise ValueError(
                            "CREATE_LINK requires link_type_id in data or "
                            "default_link_type_id in batch header."
                        )
                    to_graph_id = data.get("to_graph_id", graph_id)

                    # Resolve from_node_id — accept UUID directly or look up by
                    # source_id.  Resolution happens inside the open transaction, so
                    # nodes added in Phase 1 of this same batch are visible here.
                    from_node_id = data.get("from_node_id")
                    if not from_node_id:
                        from_src = data.get("from_source_id")
                        if not from_src:
                            raise ValueError(
                                "CREATE_LINK requires either from_node_id or from_source_id."
                            )
                        fn = self.nodes.get_by_source(conn, graph_id, from_src)
                        if fn is None:
                            raise KeyError(
                                f"CREATE_LINK: no node with source_id={from_src!r} "
                                f"in graph {graph_id!r}."
                            )
                        from_node_id = fn["node_id"]

                    # Resolve to_node_id — same pattern; to_graph_id may differ for
                    # cross-graph RELATED links.
                    to_node_id = data.get("to_node_id")
                    if not to_node_id:
                        to_src = data.get("to_source_id")
                        if not to_src:
                            raise ValueError(
                                "CREATE_LINK requires either to_node_id or to_source_id."
                            )
                        tn = self.nodes.get_by_source(conn, to_graph_id, to_src)
                        if tn is None:
                            raise KeyError(
                                f"CREATE_LINK: no node with source_id={to_src!r} "
                                f"in graph {to_graph_id!r}."
                            )
                        to_node_id = tn["node_id"]

                    link_id = self.links.insert(
                        conn,
                        link_type_id=lt_id,
                        from_graph_id=graph_id,
                        to_graph_id=to_graph_id,
                        from_node_id=from_node_id,
                        to_node_id=to_node_id,
                        actor_id=effective_actor,
                        metadata=data.get("metadata"),
                    )
                    link_data = self.links.get(conn, link_id)
                    self.ledger.append(
                        conn, transaction_id=txn_id, actor_id=effective_actor,
                        primitive_verb="CREATE_LINK", source_graph_id=graph_id,
                        entity_id=link_id, payload=link_data,
                        reversal_payload={"link_id": link_id},
                        target_graph_id=to_graph_id if to_graph_id != graph_id else None,
                    )
                    counters["links_created"] += 1
                    counters["ledger_entries"] += 1

                elif verb == "UPDATE_LINK":
                    link_id = data["link_id"]
                    prior = self.links.get(conn, link_id)
                    if prior is None:
                        raise KeyError(f"Link '{link_id}' not found (UPDATE_LINK).")
                    self.links.update(
                        conn, link_id,
                        link_type_id=data.get("link_type_id"),
                        link_order=data.get("link_order"),
                        metadata=data.get("metadata"),
                        actor_id=effective_actor,
                    )
                    updated = self.links.get(conn, link_id)
                    self.ledger.append(
                        conn, transaction_id=txn_id, actor_id=effective_actor,
                        primitive_verb="UPDATE_LINK", source_graph_id=graph_id,
                        entity_id=link_id, payload=updated, reversal_payload=prior,
                    )
                    counters["links_updated"] += 1
                    counters["ledger_entries"] += 1

            # ── Phase 3: DESTROY links ───────────────────────────────────────
            for op in destroy_links:
                link_id = op["data"]["link_id"]
                txn_id = str(uuid.uuid4())
                prior = self.links.get(conn, link_id)
                if prior is None:
                    raise KeyError(f"Link '{link_id}' not found (DESTROY_LINK).")
                self.links.delete(conn, link_id)
                self.ledger.append(
                    conn, transaction_id=txn_id, actor_id=effective_actor,
                    primitive_verb="DESTROY_LINK", source_graph_id=graph_id,
                    entity_id=link_id, payload={"link_id": link_id}, reversal_payload=prior,
                )
                counters["links_destroyed"] += 1
                counters["ledger_entries"] += 1

            # ── Phase 4: DELETE nodes ────────────────────────────────────────
            for op in delete_nodes:
                node_id = op["data"]["node_id"]
                force = op["data"].get("force", False)
                txn_id = str(uuid.uuid4())
                prior = self.nodes.get(conn, node_id)
                if prior is None:
                    raise KeyError(f"Node '{node_id}' not found (DELETE_NODE).")
                # Pre-flight: outbound links (after Phase 3 has run)
                outbound = self.links.get_all_for_node(conn, node_id)
                if outbound and not force:
                    raise ValueError(
                        f"Node '{node_id}' still has {len(outbound)} link(s). "
                        "Include DESTROY_LINK operations or set force=true."
                    )
                if outbound and force:
                    for lk in outbound:
                        self.links.delete(conn, lk["link_id"])
                self.nodes.delete(conn, node_id)
                self.ledger.append(
                    conn, transaction_id=txn_id, actor_id=effective_actor,
                    primitive_verb="DELETE_NODE", source_graph_id=graph_id,
                    entity_id=node_id, payload={"node_id": node_id}, reversal_payload=prior,
                )
                counters["nodes_deleted"] += 1
                counters["ledger_entries"] += 1

        return {"graph_id": graph_id, **counters}

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def create_snapshot(
        self,
        graph_id: str,
        version_label: str,
        actor_id: str,
        notes: str | None = None,
    ) -> dict:
        """
        Pin the current graph state as a named, fully-serialized snapshot.

        The snapshot stores the complete export payload (graph + nodes + links)
        so it can be used as a Diff base or for future restore without ledger replay.
        Raises if the graph has no ledger history.
        """
        with self.db.connect() as conn:
            history = self.ledger.get_graph_history(conn, graph_id)
            if not history:
                raise ValueError(
                    f"Graph '{graph_id}' has no ledger history. "
                    "Create at least one node before snapshotting."
                )
            latest_ledger_id = history[-1]["ledger_id"]

        # Export outside the above connection (DuckDB single-connection constraint)
        export_payload = self.export_graph(graph_id, include_cross_graph_links=True)

        with self.db.connect() as conn:
            snapshot_id = self.snapshots.create(
                conn,
                graph_id=graph_id,
                version_label=version_label,
                ledger_id=latest_ledger_id,
                actor_id=actor_id,
                payload=export_payload,
                notes=notes,
            )
            return self.snapshots.get(conn, snapshot_id)

    def list_snapshots(self, graph_id: str) -> list[dict]:
        with self.db.connect() as conn:
            return self.snapshots.list_by_graph(conn, graph_id)

    def undo_ledger_entry(self, ledger_id: int, actor_id: str) -> dict:
        """
        Create a compensating ledger entry that inverts a prior mutation.

        Reads *reversal_payload* of the original entry to reconstruct the prior
        state, applies the inverse mutation to the graph, and records a new
        ledger entry with *reverses_ledger_id* pointing back to the original.

        Single-entry undo only.  To undo a multi-entry transaction (e.g. a
        delete_node that also destroyed links), undo each entry individually
        in reverse ledger_id order.

        Raises:
            KeyError  — ledger entry not found, or target entity no longer exists.
            ValueError — entity already exists (undo of DELETE/DESTROY when entity
                         was re-created by other means), or unrecognised verb.
        """
        with self.db.connect() as conn:
            entry = self.ledger.get(conn, ledger_id)
            if entry is None:
                raise KeyError(f"Ledger entry {ledger_id} not found.")

            txn_id = str(uuid.uuid4())
            verb = entry["primitive_verb"]
            rp = entry["reversal_payload"]

            if verb == "ADD_NODE":
                node_id = rp["node_id"]
                node = self.nodes.get(conn, node_id)
                if node is None:
                    raise KeyError(
                        f"Cannot undo ADD_NODE {ledger_id}: "
                        f"node '{node_id}' no longer exists."
                    )
                self.nodes.delete(conn, node_id)
                new_ledger_id = self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="DELETE_NODE",
                    source_graph_id=entry["source_graph_id"],
                    entity_id=node_id,
                    payload={"node_id": node_id},
                    reversal_payload=node,
                    reverses_ledger_id=ledger_id,
                )

            elif verb == "UPDATE_NODE":
                node_id = entry["entity_id"]
                node = self.nodes.get(conn, node_id)
                if node is None:
                    raise KeyError(
                        f"Cannot undo UPDATE_NODE {ledger_id}: "
                        f"node '{node_id}' no longer exists."
                    )
                current_vals = {k: node[k] for k in rp}
                self.nodes.update(conn, node_id, **rp, actor_id=actor_id)
                new_ledger_id = self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="UPDATE_NODE",
                    source_graph_id=entry["source_graph_id"],
                    entity_id=node_id,
                    payload=rp,
                    reversal_payload=current_vals,
                    reverses_ledger_id=ledger_id,
                )

            elif verb == "DELETE_NODE":
                if self.nodes.get(conn, rp["node_id"]) is not None:
                    raise ValueError(
                        f"Cannot undo DELETE_NODE {ledger_id}: "
                        f"node '{rp['node_id']}' already exists."
                    )
                self.nodes.insert(
                    conn,
                    node_id=rp["node_id"],
                    graph_id=rp["graph_id"],
                    node_type_id=rp["node_type_id"],
                    source_id=rp["source_id"],
                    name=rp["name"],
                    notes=rp.get("notes"),
                    metadata=rp.get("metadata"),
                    actor_id=actor_id,
                )
                restored = self.nodes.get(conn, rp["node_id"])
                new_ledger_id = self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="ADD_NODE",
                    source_graph_id=entry["source_graph_id"],
                    entity_id=rp["node_id"],
                    payload=restored,
                    reversal_payload={"node_id": rp["node_id"]},
                    reverses_ledger_id=ledger_id,
                )

            elif verb == "CREATE_LINK":
                link_id = rp["link_id"]
                lk = self.links.get(conn, link_id)
                if lk is None:
                    raise KeyError(
                        f"Cannot undo CREATE_LINK {ledger_id}: "
                        f"link '{link_id}' no longer exists."
                    )
                self.links.delete(conn, link_id)
                new_ledger_id = self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="DESTROY_LINK",
                    source_graph_id=entry["source_graph_id"],
                    target_graph_id=entry.get("target_graph_id"),
                    entity_id=link_id,
                    payload={"link_id": link_id},
                    reversal_payload=lk,
                    reverses_ledger_id=ledger_id,
                )

            elif verb == "UPDATE_LINK":
                link_id = entry["entity_id"]
                lk = self.links.get(conn, link_id)
                if lk is None:
                    raise KeyError(
                        f"Cannot undo UPDATE_LINK {ledger_id}: "
                        f"link '{link_id}' no longer exists."
                    )
                current_vals = {k: lk[k] for k in rp}
                self.links.update(conn, link_id, **rp, actor_id=actor_id)
                new_ledger_id = self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="UPDATE_LINK",
                    source_graph_id=entry["source_graph_id"],
                    target_graph_id=entry.get("target_graph_id"),
                    entity_id=link_id,
                    payload=rp,
                    reversal_payload=current_vals,
                    reverses_ledger_id=ledger_id,
                )

            elif verb == "DESTROY_LINK":
                if self.links.get(conn, rp["link_id"]) is not None:
                    raise ValueError(
                        f"Cannot undo DESTROY_LINK {ledger_id}: "
                        f"link '{rp['link_id']}' already exists."
                    )
                self.links.insert(
                    conn,
                    link_id=rp["link_id"],
                    link_type_id=rp["link_type_id"],
                    from_graph_id=rp["from_graph_id"],
                    to_graph_id=rp["to_graph_id"],
                    from_node_id=rp["from_node_id"],
                    to_node_id=rp["to_node_id"],
                    link_order=rp.get("link_order", 0.0),
                    metadata=rp.get("metadata"),
                    valid_from_datetime=rp.get("valid_from_datetime"),
                    valid_until_datetime=rp.get("valid_until_datetime"),
                    actor_id=actor_id,
                )
                restored_lk = self.links.get(conn, rp["link_id"])
                new_ledger_id = self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="CREATE_LINK",
                    source_graph_id=entry["source_graph_id"],
                    target_graph_id=entry.get("target_graph_id"),
                    entity_id=rp["link_id"],
                    payload=restored_lk,
                    reversal_payload={"link_id": rp["link_id"]},
                    reverses_ledger_id=ledger_id,
                )

            else:
                raise ValueError(
                    f"Verb '{verb}' on ledger entry {ledger_id} cannot be undone."
                )

            return self.ledger.get(conn, new_ledger_id)

    def restore_snapshot(
        self,
        snapshot_id: str,
        actor_id: str,
        new_name: str | None = None,
    ) -> dict:
        """
        Restore a snapshot by importing its stored export payload as a new graph.

        The original graph is untouched.  The restored graph is a new graph
        whose name defaults to ``"<original_name> (restored from <version_label>)"``.
        All nodes and links from the snapshot payload are imported via
        ``import_graph()``, with full ledger attribution.

        Returns the newly created graph dict.
        """
        with self.db.connect() as conn:
            snap = self.snapshots.get(conn, snapshot_id)
        if snap is None:
            raise KeyError(f"Snapshot '{snapshot_id}' not found.")
        payload = snap.get("snapshot_payload")
        if not payload:
            raise ValueError(
                f"Snapshot '{snapshot_id}' has no stored payload. "
                "It may have been created before export-backed snapshots were introduced."
            )
        resolved_name = new_name or (
            f"{payload.get('graph', {}).get('name', 'Graph')} "
            f"(restored from {snap['version_label']})"
        )
        return self.import_graph(payload, actor_id=actor_id, new_name=resolved_name)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get_link_types(self, root: str | None = None) -> list[dict]:
        with self.db.connect() as conn:
            if root is None:
                return self.lookup.get_link_types(conn)
            return self.lookup.get_link_type_subtree(conn, root)

    def create_link_type(
        self,
        name: str,
        notes: str | None = None,
        parent_link_type_id: str | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            if parent_link_type_id is not None:
                if self.lookup.get_link_type(conn, parent_link_type_id) is None:
                    raise KeyError(f"Parent link type '{parent_link_type_id}' not found.")
            return self.lookup.create_link_type(
                conn, name=name, notes=notes,
                parent_link_type_id=parent_link_type_id,
            )

    def update_link_type(
        self,
        link_type_id: str,
        name: str | None = None,
        notes: str | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            if self.lookup.get_link_type(conn, link_type_id) is None:
                raise KeyError(f"Link type '{link_type_id}' not found.")
            self.lookup.update_link_type(conn, link_type_id, name=name, notes=notes)
            return self.lookup.get_link_type(conn, link_type_id)

    def delete_link_type(self, link_type_id: str) -> None:
        with self.db.connect() as conn:
            if self.lookup.get_link_type(conn, link_type_id) is None:
                raise KeyError(f"Link type '{link_type_id}' not found.")
            p = self.db.placeholder
            child_count = conn.execute(
                f"SELECT COUNT(*) FROM link_type WHERE CAST(parent_link_type_id AS VARCHAR) = {p}",
                [link_type_id],
            ).fetchone()[0]
            if child_count:
                raise ValueError(
                    f"Link type has {child_count} child sub-type(s). "
                    "Delete or re-parent them first."
                )
            usage_count = conn.execute(
                f"SELECT COUNT(*) FROM link WHERE CAST(link_type_id AS VARCHAR) = {p}",
                [link_type_id],
            ).fetchone()[0]
            if usage_count:
                raise ValueError(
                    f"Link type is referenced by {usage_count} link(s) and cannot be deleted."
                )
            self.lookup.delete_link_type(conn, link_type_id)

    def get_node_types(self) -> list[dict]:
        with self.db.connect() as conn:
            return self.lookup.get_node_types(conn)

    def create_node_type(self, name: str, notes: str | None = None) -> dict:
        with self.db.connect() as conn:
            return self.lookup.create_node_type(conn, name=name, notes=notes)

    def update_node_type(
        self,
        node_type_id: str,
        name: str | None = None,
        notes: str | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            if self.lookup.get_node_type(conn, node_type_id) is None:
                raise KeyError(f"Node type '{node_type_id}' not found.")
            self.lookup.update_node_type(conn, node_type_id, name=name, notes=notes)
            return self.lookup.get_node_type(conn, node_type_id)

    def delete_node_type(self, node_type_id: str) -> None:
        with self.db.connect() as conn:
            if self.lookup.get_node_type(conn, node_type_id) is None:
                raise KeyError(f"Node type '{node_type_id}' not found.")
            p = self.db.placeholder
            usage_count = conn.execute(
                f"SELECT COUNT(*) FROM node WHERE CAST(node_type_id AS VARCHAR) = {p}",
                [node_type_id],
            ).fetchone()[0]
            if usage_count:
                raise ValueError(
                    f"Node type is referenced by {usage_count} node(s) and cannot be deleted."
                )
            self.lookup.delete_node_type(conn, node_type_id)

    # ── Actor registry ────────────────────────────────────────────────────────

    def get_actors(self) -> list[dict]:
        with self.db.connect() as conn:
            return self.lookup.get_actors(conn)

    def get_actor_by_handle(self, handle: str) -> dict | None:
        with self.db.connect() as conn:
            return self.lookup.get_actor_by_handle(conn, handle)

    def register_actor(
        self,
        handle: str,
        display_name: str,
        actor_type: str = "HUMAN",
        org: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """
        Register a new actor.  Raises if the handle already exists.
        In strict_actor_validation mode, ledger writes require the actor to be registered.
        """
        with self.db.connect() as conn:
            return self.lookup.register_actor(
                conn, handle=handle, display_name=display_name,
                actor_type=actor_type, org=org, notes=notes,
            )

    # ── History ───────────────────────────────────────────────────────────────

    def get_graph_history(
        self, graph_id: str, since_ledger_id: int | None = None
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.ledger.get_graph_history(conn, graph_id, since_ledger_id)

    def verify_ledger_chain(self) -> dict:
        """Re-compute and verify the global ledger hash chain. See LedgerDAO.verify_chain."""
        with self.db.connect() as conn:
            return self.ledger.verify_chain(conn)

    # -- Stakeholder registry -------------------------------------------------

    def create_stakeholder(
        self,
        name: str,
        org: str | None = None,
        contact_ref: str | None = None,
        actor_id: str | None = None,
        notes: str | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            sid = self.stakeholders.insert(
                conn, name=name, org=org,
                contact_ref=contact_ref, actor_id=actor_id, notes=notes,
            )
            result = self.stakeholders.get(conn, sid)
        if result is None:
            raise RuntimeError("Stakeholder insert failed.")
        return result

    def get_stakeholder(self, stakeholder_id: str) -> dict:
        with self.db.connect() as conn:
            s = self.stakeholders.get(conn, stakeholder_id)
        if s is None:
            raise KeyError(f"Stakeholder '{stakeholder_id}' not found.")
        return s

    def list_stakeholders(self) -> list[dict]:
        with self.db.connect() as conn:
            return self.stakeholders.list(conn)

    def update_stakeholder(
        self,
        stakeholder_id: str,
        name: str | None = None,
        org: str | None = None,
        contact_ref: str | None = None,
        actor_id: str | None = None,
        notes: str | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            if self.stakeholders.get(conn, stakeholder_id) is None:
                raise KeyError(f"Stakeholder '{stakeholder_id}' not found.")
            self.stakeholders.update(
                conn, stakeholder_id,
                name=name, org=org, contact_ref=contact_ref,
                actor_id=actor_id, notes=notes,
            )
            return self.stakeholders.get(conn, stakeholder_id)

    def delete_stakeholder(self, stakeholder_id: str) -> None:
        with self.db.connect() as conn:
            if self.stakeholders.get(conn, stakeholder_id) is None:
                raise KeyError(f"Stakeholder '{stakeholder_id}' not found.")
            self.stakeholders.delete(conn, stakeholder_id)

    def attach_stakeholder_to_graph(
        self, graph_id: str, stakeholder_id: str, role: str, notes: str | None = None
    ) -> None:
        with self.db.connect() as conn:
            if self.graphs.get(conn, graph_id) is None:
                raise KeyError(f"Graph '{graph_id}' not found.")
            if self.stakeholders.get(conn, stakeholder_id) is None:
                raise KeyError(f"Stakeholder '{stakeholder_id}' not found.")
            self.stakeholders.attach_to_graph(conn, graph_id, stakeholder_id, role, notes)

    def detach_stakeholder_from_graph(self, graph_id: str, stakeholder_id: str) -> None:
        with self.db.connect() as conn:
            self.stakeholders.detach_from_graph(conn, graph_id, stakeholder_id)

    def list_graph_stakeholders(self, graph_id: str) -> list[dict]:
        with self.db.connect() as conn:
            if self.graphs.get(conn, graph_id) is None:
                raise KeyError(f"Graph '{graph_id}' not found.")
            return self.stakeholders.list_for_graph(conn, graph_id)

    def attach_stakeholder_to_node(
        self,
        node_id: str,
        stakeholder_id: str,
        role: str,
        scope: str = "NODE_ONLY",
        scope_depth: int | None = None,
        scope_link_type_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        valid_scopes = {"NODE_ONLY", "SUBGRAPH", "ANCESTORS"}
        if scope not in valid_scopes:
            raise ValueError(f"Invalid scope '{scope}'. Must be one of {valid_scopes}.")
        with self.db.connect() as conn:
            if self.nodes.get(conn, node_id) is None:
                raise KeyError(f"Node '{node_id}' not found.")
            if self.stakeholders.get(conn, stakeholder_id) is None:
                raise KeyError(f"Stakeholder '{stakeholder_id}' not found.")
            self.stakeholders.attach_to_node(
                conn, node_id, stakeholder_id, role,
                scope=scope, scope_depth=scope_depth,
                scope_link_type_id=scope_link_type_id, notes=notes,
            )

    def detach_stakeholder_from_node(self, node_id: str, stakeholder_id: str) -> None:
        with self.db.connect() as conn:
            self.stakeholders.detach_from_node(conn, node_id, stakeholder_id)

    def list_node_stakeholders(self, node_id: str) -> list[dict]:
        with self.db.connect() as conn:
            if self.nodes.get(conn, node_id) is None:
                raise KeyError(f"Node '{node_id}' not found.")
            return self.stakeholders.list_for_node(conn, node_id)

    def resolve_stakeholders_for_node(self, node_id: str, graph_id: str) -> list[dict]:
        """
        Return all stakeholders with governance interest in node_id,
        accounting for NODE_ONLY, SUBGRAPH, ANCESTORS, and GRAPH attachment scopes.
        """
        with self.db.connect() as conn:
            return self.stakeholders.resolve_for_node(conn, node_id, graph_id)

    # ── Agent working memory ──────────────────────────────────────────────────

    def upsert_memory(self, *, category: str, key: str, content: str) -> dict:
        """Store or overwrite a cross-session agent memory note."""
        with self.db.connect() as conn:
            return self.memory.upsert(conn, category=category, key=key, content=content)

    def delete_memory(self, *, key: str) -> bool:
        """Remove a memory note by key.  Returns True if it existed."""
        with self.db.connect() as conn:
            return self.memory.delete(conn, key=key)

    def list_memories(self) -> list[dict]:
        """Return all memory notes ordered by category then updated_at desc."""
        with self.db.connect() as conn:
            return self.memory.list_all(conn)

    # ── BQL query engine ─────────────────────────────────────────────────────

    _MAX_SEED_SIZE = 500
    _MAX_STEP_BUFFER = 5_000
    _MAX_DEPTH_HARD = 50

    def execute_bql(self, query: dict) -> dict:
        """
        Execute a BQL (Banyan Query Language) query.

        query is the raw dict parsed from the POST /api/v1/query request body.
        Returns a response envelope: {success, seed_count, total_count, steps, results}.
        """
        with self.db.connect() as conn:
            return self._execute_bql_conn(conn, query)

    def _execute_bql_conn(self, conn, query: dict) -> dict:
        # ── 1. Resolve origin graph ───────────────────────────────────────────
        graph_ref = query.get("graph", {})
        if graph_ref.get("id"):
            graph = self.graphs.get(conn, str(graph_ref["id"]))
        elif graph_ref.get("name"):
            graph = self.graphs.get_by_name(conn, str(graph_ref["name"]))
        else:
            raise ValueError("query.graph must specify 'name' or 'id'")
        if graph is None:
            raise KeyError(f"Graph not found: {graph_ref}")

        origin_graph_id: str = graph["graph_id"]

        # ── 2. Resolve result options ─────────────────────────────────────────
        result_opts: dict = query.get("result") or {}
        fmt: str = result_opts.get("format", "LINK_NODE")
        include_seed: bool = result_opts.get("include_seed", True)
        limit: int | None = result_opts.get("limit", None)
        verbose: bool = result_opts.get("verbose", False)

        # ── 3. Resolve seed nodes ─────────────────────────────────────────────
        starting = query.get("starting")
        if starting is None:
            root_id = graph.get("root_node_id")
            seed_nodes = [self.nodes.get(conn, root_id)] if root_id else []
            seed_nodes = [n for n in seed_nodes if n is not None]
        else:
            seed_nodes = self.query_dao.resolve_seed(conn, origin_graph_id, starting)

        seed_count = len(seed_nodes)
        if seed_count > self._MAX_SEED_SIZE:
            raise ValueError(
                f"starting predicate matched {seed_count} nodes; "
                f"exceeds MAX_SEED_SIZE={self._MAX_SEED_SIZE}. Narrow the predicate."
            )

        # ── 4. Initialize accumulators ────────────────────────────────────────
        # seen is intentionally NOT tracked globally across steps.
        # Each step gets its own fresh seen set (seeded with its input frontier)
        # so that subsequent steps can traverse nodes visited in earlier steps.
        # This is correct: seen prevents cycles WITHIN a step; depth limits are
        # the runaway guard.  Cross-step deduplication is a separate concern.
        net_depths: dict[str, int] = {n["node_id"]: 0 for n in seed_nodes}
        response_items: list[dict] = []
        step_diagnostics: list[dict] = []

        if include_seed:
            for node in seed_nodes:
                response_items.append(
                    _make_result_item(node, step=0, depth=0, net_depth=0, direction=None, link=None, fmt=fmt)
                )

        # ── 5. Resolve and execute steps ──────────────────────────────────────
        raw_steps: list[dict] = query.get("steps") or [
            {"direction": "FROM"}
        ]  # default step: full traversal from seed

        step_buffer: list[dict] = list(seed_nodes)

        for step_idx, step in enumerate(raw_steps, start=1):
            direction: str = step.get("direction", "FROM").upper()
            raw_link_types: list[str] = step.get("link_types") or []
            depth_limit: int = min(
                step.get("depth") or self._MAX_DEPTH_HARD,
                self._MAX_DEPTH_HARD,
            )
            node_type_filter: list[str] = step.get("node_types") or []
            graphs_filter: list[str] = step.get("graphs") or []
            collect: bool = step.get("collect", True)
            # reset_seen option removed — seen is now always per-step.

            # Resolve allowed graph IDs for this step
            if graphs_filter == ["*"]:
                allowed_graph_ids = None  # No restriction
            elif graphs_filter:
                allowed_graph_ids = []
                for gref in graphs_filter:
                    g = self.graphs.get_by_name(conn, gref) or self.graphs.get(conn, gref)
                    if g:
                        allowed_graph_ids.append(g["graph_id"])
            else:
                allowed_graph_ids = [origin_graph_id]  # default: origin graph only

            # Resolve link_type_ids (expand families unless ! suffix)
            link_type_ids: list[str] | None = None
            if raw_link_types:
                link_type_ids = []
                for lt_name in raw_link_types:
                    exact = lt_name.endswith("!")
                    name = lt_name.rstrip("!")
                    if exact:
                        lt = self.lookup.get_link_type_by_name(conn, name)
                        if lt:
                            link_type_ids.append(lt["link_type_id"])
                    else:
                        family = self.lookup.get_link_type_subtree(conn, name)
                        link_type_ids.extend(lt["link_type_id"] for lt in family)

            # Resolve node_type filter IDs
            node_type_ids: set[str] = set()
            for nt_name in node_type_filter:
                nt = self.lookup.get_node_type_by_name(conn, nt_name)
                if nt:
                    node_type_ids.add(nt["node_type_id"])

            # ── Iterative one-hop traversal within this step ──────────────────
            current_frontier: list[dict] = step_buffer
            step_output: list[dict] = []  # deduped output for this step
            step_truncated = False

            # Fresh seen per step, starts empty.
            # Accumulates within the hop loop to prevent within-step cycles.
            # The depth limit is the primary runaway guard.
            # NOT pre-seeded with the frontier — that would block finding links
            # between nodes that are already in the frontier (e.g. intra-graph
            # symmetric links where both endpoints were discovered in a prior step).
            seen: set[str] = set()

            for hop in range(depth_limit):
                if not current_frontier:
                    break

                frontier_ids = [n["node_id"] for n in current_frontier]
                raw_hops = self.query_dao.execute_one_hop(
                    conn,
                    direction=direction,
                    frontier_ids=frontier_ids,
                    link_type_ids=link_type_ids,
                    allowed_graph_ids=allowed_graph_ids,
                )

                new_frontier: list[dict] = []
                for link_info, parent_id, node in raw_hops:
                    node_id = node["node_id"]
                    already_seen = node_id in seen

                    if node_type_ids and node["node_type_id"] not in node_type_ids:
                        continue

                    if not already_seen:
                        seen.add(node_id)
                        parent_nd = net_depths.get(parent_id, 0)
                        node_nd = parent_nd + 1
                        net_depths[node_id] = node_nd
                        new_frontier.append(node)
                        step_output.append(node)
                    else:
                        node_nd = net_depths.get(node_id, 0)

                    # In LINK_NODE format, collect the link item even when the
                    # destination is already seen — the frontier is not expanded
                    # (cycle guard still holds), but the caller can observe all
                    # links touching the frontier and deduplicate by link_id.
                    # In NODE format, only collect genuinely new nodes.
                    if collect and (fmt == "LINK_NODE" or not already_seen):
                        response_items.append(
                            _make_result_item(
                                node,
                                step=step_idx,
                                depth=hop + 1,
                                net_depth=node_nd,
                                direction=link_info["traversal_direction"],
                                link=link_info,
                                fmt=fmt,
                            )
                        )

                    if limit and len(response_items) >= limit:
                        step_truncated = True
                        break

                if step_truncated:
                    break

                if not new_frontier:
                    break  # Graph exhausted at this hop depth

                if len(step_output) >= self._MAX_STEP_BUFFER:
                    step_truncated = True
                    break

                current_frontier = new_frontier

            if verbose:
                step_diagnostics.append({
                    "step": step_idx,
                    "input_count": len(step_buffer),
                    "output_count": len(step_output),
                    "collected": collect,
                    "truncated": step_truncated,
                })

            step_buffer = step_output  # output of this step feeds next step

        return {
            "success": True,
            "seed_count": seed_count,
            "total_count": len(response_items),
            "steps": step_diagnostics if verbose else None,
            "results": response_items,
        }


def _make_result_item(
    node: dict,
    step: int,
    depth: int,
    net_depth: int,
    direction: str | None,
    link: dict | None,
    fmt: str,
) -> dict:
    base = {
        "_step": step,
        "_depth": depth,
        "_net_depth": net_depth,
        "_direction": direction,
    }
    if fmt == "NODE":
        return {**base, **node}
    return {**base, "link": link, "node": node}
