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

            nodes = self.nodes.list_by_graph(conn, graph_id)

            p = self.db.placeholder
            cursor = conn.execute(
                f"SELECT * FROM link WHERE from_graph_id = {p} AND to_graph_id = {p}",
                [graph_id, graph_id],
            )
            cols = [c[0] for c in cursor.description]
            from banyan_platform.dao._utils import normalise_row
            intra_links = [normalise_row(dict(zip(cols, row))) for row in cursor.fetchall()]

            cross_links: list[dict] = []
            if include_cross_graph_links:
                cursor2 = conn.execute(
                    f"SELECT * FROM link WHERE from_graph_id = {p} AND to_graph_id != {p}",
                    [graph_id, graph_id],
                )
                cols2 = [c[0] for c in cursor2.description]
                cross_links = [normalise_row(dict(zip(cols2, row))) for row in cursor2.fetchall()]

        return {
            "banyan_export_version": "1.0",
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
            else:
                name = new_name or src_graph.get("name", "Imported Graph")
                target_graph_id = self.graphs.insert(
                    conn,
                    name=name,
                    notes=src_graph.get("notes"),
                    topology_id=src_graph.get("topology_id"),
                    actor_id=actor_id,
                )
                target_graph = self.graphs.get(conn, target_graph_id)

            # ── Build source_id → new_node_id mapping ───────────────────────
            node_id_map: dict[str, str] = {}  # old_node_id → new_node_id
            default_node_type = self.lookup.get_node_type_by_name(conn, "Generic")
            default_nt_id = int(default_node_type["node_type_id"])

            for n in nodes_doc:
                existing = self.nodes.get_by_source(conn, target_graph_id, n["source_id"])
                if existing:
                    node_id_map[n["node_id"]] = existing["node_id"]
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
                txn_id = str(uuid.uuid4())
                node_data = self.nodes.get(conn, new_node_id)
                self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="ADD_NODE",
                    source_graph_id=target_graph_id,
                    entity_id=new_node_id,
                    payload=node_data,
                    reversal_payload={"node_id": new_node_id},
                )
                node_id_map[n["node_id"]] = new_node_id

            # ── Import intra-graph links ─────────────────────────────────────
            for lk in links_doc:
                new_from = node_id_map.get(lk["from_node_id"])
                new_to = node_id_map.get(lk["to_node_id"])
                if new_from is None or new_to is None:
                    continue  # endpoint not imported (e.g. cross-graph node ref)
                # Skip if this exact pair already exists
                existing_links = self.links.get_children(
                    conn, target_graph_id, new_from, lk["link_type_id"]
                )
                if any(el["to_node_id"] == new_to for el in existing_links):
                    continue
                new_link_id = self.links.insert(
                    conn,
                    link_type_id=lk["link_type_id"],
                    from_graph_id=target_graph_id,
                    to_graph_id=target_graph_id,
                    from_node_id=new_from,
                    to_node_id=new_to,
                    actor_id=actor_id,
                    metadata=lk.get("metadata"),
                )
                txn_id = str(uuid.uuid4())
                link_data = self.links.get(conn, new_link_id)
                self.ledger.append(
                    conn,
                    transaction_id=txn_id,
                    actor_id=actor_id,
                    primitive_verb="CREATE_LINK",
                    source_graph_id=target_graph_id,
                    entity_id=new_link_id,
                    payload=link_data,
                    reversal_payload={"link_id": new_link_id},
                )

            return self.graphs.get(conn, target_graph_id)

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
            frm = nodes_by_id.get(l["from_node_id"], {}).get("source_id")
            to = nodes_by_id.get(l["to_node_id"], {}).get("source_id")
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
        default_lt_id: int | None = batch.get("default_link_type_id")
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

        default_nt_id: int | None = None

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
                        default_nt_id = int(nt["node_type_id"])
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
                    link_id = self.links.insert(
                        conn,
                        link_type_id=lt_id,
                        from_graph_id=graph_id,
                        to_graph_id=to_graph_id,
                        from_node_id=data["from_node_id"],
                        to_node_id=data["to_node_id"],
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
