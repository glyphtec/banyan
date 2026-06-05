from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from banyan_platform.dao.graph_dao import GraphDAO
from banyan_platform.dao.node_dao import NodeDAO
from banyan_platform.dao.link_dao import LinkDAO
from banyan_platform.dao.ledger_dao import LedgerDAO
from banyan_platform.dao.traversal_dao import TraversalDAO
from banyan_platform.dao.lookup_dao import LookupDAO
from banyan_platform.dao.snapshot_dao import SnapshotDAO

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

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_node_type_id(self, conn, node_type_id: int | None) -> int:
        if node_type_id is not None:
            return node_type_id
        nt = self.lookup.get_node_type_by_name(conn, "Generic")
        if nt is None:
            raise RuntimeError("Default node type 'Generic' not found. Run bootstrap() first.")
        return int(nt["node_type_id"])

    # ── Graph operations (no ledger) ──────────────────────────────────────────

    def create_graph(
        self,
        name: str,
        actor_id: str,
        notes: str | None = None,
        topology_id: int | None = None,
    ) -> dict:
        with self.db.connect() as conn:
            graph_id = self.graphs.insert(
                conn, name=name, notes=notes,
                topology_id=topology_id, actor_id=actor_id,
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
        topology_id: int | None = None,
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

    # ── Node operations ───────────────────────────────────────────────────────

    def add_node(
        self,
        graph_id: str,
        source_id: str,
        name: str,
        actor_id: str,
        notes: str | None = None,
        metadata: dict | None = None,
        node_type_id: int | None = None,
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
        link_type_id: int,
        from_graph_id: str,
        to_graph_id: str,
        from_node_id: str,
        to_node_id: str,
        actor_id: str,
        link_order: float = 0.0,
        metadata: dict | None = None,
    ) -> dict:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            family = self.lookup.get_link_type_root_family(conn, link_type_id)
            if family in ("HIERARCHICAL", "SYNONYM") and from_graph_id != to_graph_id:
                raise ValueError(
                    f"{family} links must remain within a single graph "
                    f"(from_graph_id={from_graph_id!r}, to_graph_id={to_graph_id!r})."
                )
            link_id = self.links.insert(
                conn,
                link_type_id=link_type_id,
                from_graph_id=from_graph_id,
                to_graph_id=to_graph_id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                link_order=link_order,
                metadata=metadata,
                actor_id=actor_id,
            )
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
    ) -> dict:
        txn_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            prior = self.links.get(conn, link_id)
            if prior is None:
                raise KeyError(f"Link '{link_id}' not found.")
            delta: dict = {}
            if link_order is not None:  delta["link_order"] = link_order
            if metadata is not None:    delta["metadata"] = metadata
            if is_disabled is not None: delta["is_disabled"] = is_disabled
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
        self, graph_id: str, from_node_id: str, link_type_id: int | None = None
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.links.get_children(conn, graph_id, from_node_id, link_type_id)

    def get_parents(
        self, graph_id: str, to_node_id: str, link_type_id: int | None = None
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.links.get_parents(conn, graph_id, to_node_id, link_type_id)

    # ── Traversal (read-only, no ledger) ──────────────────────────────────────

    def get_subtree(
        self,
        graph_id: str,
        root_node_id: str,
        link_type_id: int | None = None,
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.traversal.get_subtree(conn, graph_id, root_node_id, link_type_id)

    def get_ancestors(
        self,
        graph_id: str,
        node_id: str,
        link_type_id: int | None = None,
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.traversal.get_ancestors(conn, graph_id, node_id, link_type_id)

    def get_impact_summary(self, graph_id: str, node_id: str) -> dict:
        with self.db.connect() as conn:
            return self.traversal.get_impact_summary(conn, graph_id, node_id)

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def create_snapshot(
        self,
        graph_id: str,
        version_label: str,
        actor_id: str,
        metadata: dict | None = None,
    ) -> dict:
        """
        Pin the current ledger timeline position for *graph_id* as a named snapshot.
        Raises if the graph has no ledger history (no node/link mutations yet).
        """
        with self.db.connect() as conn:
            history = self.ledger.get_graph_history(conn, graph_id)
            if not history:
                raise ValueError(
                    f"Graph '{graph_id}' has no ledger history. "
                    "Create at least one node before snapshotting."
                )
            latest_ledger_id = history[-1]["ledger_id"]
            snapshot_id = self.snapshots.create(
                conn,
                graph_id=graph_id,
                version_label=version_label,
                ledger_id=latest_ledger_id,
                actor_id=actor_id,
                metadata=metadata,
            )
            return self.snapshots.get(conn, snapshot_id)

    def list_snapshots(self, graph_id: str) -> list[dict]:
        with self.db.connect() as conn:
            return self.snapshots.list_by_graph(conn, graph_id)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get_link_types(self) -> list[dict]:
        with self.db.connect() as conn:
            return self.lookup.get_link_types(conn)

    def get_node_types(self) -> list[dict]:
        with self.db.connect() as conn:
            return self.lookup.get_node_types(conn)

    # ── History ───────────────────────────────────────────────────────────────

    def get_graph_history(
        self, graph_id: str, since_ledger_id: int | None = None
    ) -> list[dict]:
        with self.db.connect() as conn:
            return self.ledger.get_graph_history(conn, graph_id, since_ledger_id)
