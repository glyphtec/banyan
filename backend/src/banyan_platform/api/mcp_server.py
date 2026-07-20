from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from banyan_platform.services.taxonomy_service import BanyanService

# ---------------------------------------------------------------------------
# Actor identity default for MCP callers.
# Agents should pass actor_id explicitly so the ledger records their identity.
# ---------------------------------------------------------------------------
_MCP_DEFAULT_ACTOR = "system:mcp-agent"


def build_mcp_server(service: BanyanService) -> FastMCP:
    """
    Return a configured FastMCP server exposing the full BanyanService as tools.

    Mounting pattern (in app.py):
        mcp_app = mcp.http_app(path="/")
        app = FastAPI(lifespan=mcp_app.lifespan)
        app.mount("/mcp", mcp_app)

    MCP endpoint will be at /mcp/
    """
    mcp = FastMCP(
        name="Banyan",
        instructions=(
            "Banyan is a taxonomy and ontology management system. "
            "Graphs are named vocabularies/taxonomies. "
            "Nodes are concepts/terms. "
            "Links are typed, directional relationships between nodes. "
            "Every node/link mutation is recorded in the audit ledger. "
            "Use get_impact_summary before deleting nodes with descendants."
        ),
    )

    # ── Graph tools ────────────────────────────────────────────────────────

    @mcp.tool
    def create_graph(
        name: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        notes: str | None = None,
        topology_id: str | None = None,
    ) -> dict:
        """Create a new graph (taxonomy / vocabulary)."""
        return service.create_graph(
            name=name, actor_id=actor_id,
            notes=notes, topology_id=topology_id,
        )

    @mcp.tool
    def get_graph(graph_id: str) -> dict:
        """Return a single graph by its UUID."""
        return service.get_graph(graph_id)

    @mcp.tool
    def list_graphs() -> list[dict]:
        """List all graphs in the system."""
        return service.list_graphs()

    @mcp.tool
    def update_graph(
        graph_id: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        name: str | None = None,
        notes: str | None = None,
        topology_id: str | None = None,
    ) -> dict:
        """Update a graph's name, notes, or topology constraint."""
        return service.update_graph(
            graph_id, actor_id=actor_id,
            name=name, notes=notes, topology_id=topology_id,
        )

    @mcp.tool
    def delete_graph(graph_id: str, actor_id: str = _MCP_DEFAULT_ACTOR) -> dict:
        """
        Delete an empty graph.  The graph must contain no nodes.
        Returns {"deleted": true} on success.
        """
        service.delete_graph(graph_id, actor_id=actor_id)
        return {"deleted": True, "graph_id": graph_id}

    # ── Node tools ─────────────────────────────────────────────────────────

    @mcp.tool
    def add_node(
        graph_id: str,
        source_id: str,
        name: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        notes: str | None = None,
        metadata: dict | None = None,
        node_type_id: str | None = None,
    ) -> dict:
        """
        Add a node (term/concept) to a graph.

        source_id is the external business key (SKU, code, URI, etc.).
        metadata is an optional free-form JSON object for additional properties.
        node_type_id defaults to the 'Generic' type if omitted.
        """
        return service.add_node(
            graph_id=graph_id,
            source_id=source_id,
            name=name,
            actor_id=actor_id,
            notes=notes,
            metadata=metadata,
            node_type_id=node_type_id,
        )

    @mcp.tool
    def get_node(node_id: str) -> dict:
        """Return a single node by its UUID."""
        return service.get_node(node_id)

    @mcp.tool
    def list_nodes(graph_id: str) -> list[dict]:
        """List all nodes in a graph, ordered by name."""
        return service.list_nodes(graph_id)

    @mcp.tool
    def update_node(
        node_id: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        name: str | None = None,
        notes: str | None = None,
        source_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Update a node's name, notes, source_id, or metadata. Only provided fields change."""
        return service.update_node(
            node_id, actor_id=actor_id,
            name=name, notes=notes,
            source_id=source_id, metadata=metadata,
        )

    @mcp.tool
    def delete_node(
        node_id: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        force: bool = False,
    ) -> dict:
        """
        Delete a node and all links touching it.

        Safety checks (both bypass-able with force=True):
          - Node has outbound links (has children) → resolve the tree first.
          - Node is referenced by cross-graph links → affects other taxonomies.

        Always call get_impact_summary first to understand the blast radius.
        Returns {"deleted_node_id": ..., "destroyed_link_count": ...}.
        """
        return service.delete_node(node_id, actor_id=actor_id, force=force)

    # ── Link tools ─────────────────────────────────────────────────────────

    @mcp.tool
    def create_link(
        link_type_id: str,
        from_graph_id: str,
        to_graph_id: str,
        from_node_id: str,
        to_node_id: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        link_order: float = 0.0,
        metadata: dict | None = None,
        valid_from_datetime: str | None = None,
        valid_until_datetime: str | None = None,
    ) -> dict:
        """
        Create a directional link between two nodes.

        HIERARCHICAL and SYNONYM link types must stay within the same graph
        (from_graph_id == to_graph_id).  RELATED links may cross graph boundaries.

        link_order controls sibling ordering (fractional, e.g. 1.0, 2.0, 1.5).
        Use get_link_types to discover available link_type_id values.

        valid_from_datetime / valid_until_datetime: optional ISO-8601 strings
        (e.g. '2026-01-01T00:00:00Z') bounding when the link is considered active.
        """
        from datetime import datetime, timezone
        def _parse_dt(s): return datetime.fromisoformat(s) if s else None
        return service.create_link(
            link_type_id=link_type_id,
            from_graph_id=from_graph_id,
            to_graph_id=to_graph_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            actor_id=actor_id,
            link_order=link_order,
            metadata=metadata,
            valid_from_datetime=_parse_dt(valid_from_datetime),
            valid_until_datetime=_parse_dt(valid_until_datetime),
        )

    @mcp.tool
    def get_link(link_id: str) -> dict:
        """Return a single link by its UUID."""
        return service.get_link(link_id)

    @mcp.tool
    def update_link(
        link_id: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        link_order: float | None = None,
        metadata: dict | None = None,
        is_disabled: bool | None = None,
        valid_from_datetime: str | None = None,
        valid_until_datetime: str | None = None,
    ) -> dict:
        """
        Update a link's order, metadata, disabled status, or temporal bounds.
        Setting is_disabled=True soft-hides the link without deleting it.
        valid_from_datetime / valid_until_datetime: ISO-8601 strings
        (e.g. '2026-01-01T00:00:00Z').  Pass an empty string to clear.
        """
        from datetime import datetime
        def _parse_dt(s): return datetime.fromisoformat(s) if s else None
        return service.update_link(
            link_id, actor_id=actor_id,
            link_order=link_order,
            metadata=metadata,
            is_disabled=is_disabled,
            valid_from_datetime=_parse_dt(valid_from_datetime),
            valid_until_datetime=_parse_dt(valid_until_datetime),
        )

    @mcp.tool
    def destroy_link(link_id: str, actor_id: str = _MCP_DEFAULT_ACTOR) -> dict:
        """
        Permanently delete a link.  A DESTROY_LINK ledger entry is written first.
        To re-parent a node: destroy the old parent link then create a new one
        — both operations share a transaction_id in the ledger.
        Returns {"destroyed": true, "link_id": ...}.
        """
        service.destroy_link(link_id, actor_id=actor_id)
        return {"destroyed": True, "link_id": link_id}

    @mcp.tool
    def get_children(
        graph_id: str,
        from_node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        """Return all active outbound links from a node, ordered by link_order."""
        return service.get_children(graph_id, from_node_id, link_type_id)

    @mcp.tool
    def get_parents(
        graph_id: str,
        to_node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        """
        Return all active inbound links to a node.
        Multiple results indicate a polyhierarchical node.
        """
        return service.get_parents(graph_id, to_node_id, link_type_id)

    # ── Traversal tools ────────────────────────────────────────────────────

    @mcp.tool
    def get_subtree(
        graph_id: str,
        root_node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        """
        Return root_node_id and all its descendants within graph_id.

        Each result includes a 'depth' field (0 = root node).
        Results are ordered depth-first by depth then name.
        Optionally restrict traversal to a specific link_type_id.
        """
        return service.get_subtree(graph_id, root_node_id, link_type_id)

    @mcp.tool
    def get_ancestors(
        graph_id: str,
        node_id: str,
        link_type_id: str | None = None,
    ) -> list[dict]:
        """
        Return all ancestors of node_id, excluding the node itself.

        'depth' = 1 is the immediate parent(s).  In a polyhierarchy, multiple
        rows may appear at the same depth level.
        """
        return service.get_ancestors(graph_id, node_id, link_type_id)

    @mcp.tool
    def get_impact_summary(graph_id: str, node_id: str) -> dict:
        """
        Pre-flight safety report for a proposed destructive operation on node_id.

        Returns:
          - descendant_count: number of nodes that would be affected
          - descendants: list of {node_id, name, depth}
          - cross_graph_link_count: links from other graphs pointing into this subtree

        Always call this before delete_node on any non-leaf node.
        """
        return service.get_impact_summary(graph_id, node_id)

    # ── Snapshot tools ─────────────────────────────────────────────────────

    @mcp.tool
    def create_snapshot(
        graph_id: str,
        version_label: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
    ) -> dict:
        """
        Pin the current graph state as a named, fully-serialized snapshot.

        Stores the complete export payload (graph + nodes + links) so the snapshot
        can be used as a Diff base without ledger replay.
        version_label should be a human-readable milestone label,
        e.g. 'v1.4-production' or 'pre-merge-review'.
        Raises if the graph has no mutation history yet.
        """
        return service.create_snapshot(
            graph_id=graph_id,
            version_label=version_label,
            actor_id=actor_id,
        )

    @mcp.tool
    def list_snapshots(graph_id: str) -> list[dict]:
        """List all snapshots for a graph, ordered by creation time."""
        return service.list_snapshots(graph_id)

    # ── Lookup tools ───────────────────────────────────────────────────────

    @mcp.tool
    def get_link_types() -> list[dict]:
        """
        Return all available link types with their IDs.

        Root families: HIERARCHICAL, RELATED, SYNONYM.
        Sub-types have a parent_link_type_id pointing to their root family.
        Use link_type_id values when calling create_link.
        """
        return service.get_link_types()

    @mcp.tool
    def get_node_types() -> list[dict]:
        """Return all available node types with their IDs."""
        return service.get_node_types()

    # ── Actor registry tools ───────────────────────────────────────────────

    @mcp.tool
    def get_actors() -> list[dict]:
        """
        Return all registered actors ordered by type then handle.
        Includes seeded system actors (system:bootstrap, system:ingest,
        system:mcp-agent, anonymous) and any registered human actors.
        """
        return service.get_actors()

    @mcp.tool
    def get_actor(handle: str) -> dict | None:
        """Return a single actor by handle, or None if not registered."""
        return service.get_actor_by_handle(handle)

    @mcp.tool
    def register_actor(
        handle: str,
        display_name: str,
        actor_type: str = "HUMAN",
        org: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """
        Register a new actor in the identity registry.

        handle       — stable identifier used in actor_id / updated_by columns
                       (e.g. 'human:jane.smith', 'agent:crosswalk-bot')
        display_name — human-readable label
        actor_type   — SYSTEM | HUMAN | AGENT
        org          — optional organisation affiliation
        """
        return service.register_actor(
            handle=handle, display_name=display_name,
            actor_type=actor_type, org=org, notes=notes,
        )

    # ── History tools ──────────────────────────────────────────────────────

    @mcp.tool
    def get_graph_history(
        graph_id: str,
        since_ledger_id: int | None = None,
    ) -> list[dict]:
        """
        Return the ordered audit trail of all mutations for a graph.

        Pass since_ledger_id (from a snapshot's ledger_id field) to fetch
        only changes made after that snapshot — useful for computing diffs.
        """
        return service.get_graph_history(graph_id, since_ledger_id)

    # ── Export / Import / Diff / Batch tools ───────────────────────────────

    @mcp.tool
    def export_graph(
        graph_id: str,
        include_cross_graph_links: bool = False,
    ) -> dict:
        """
        Serialize the full graph state as a portable document.

        Returns:
            {
              "banyan_export_version": "1.0",
              "exported_at": "<ISO-8601>",
              "graph": { ... },
              "nodes": [ ... ],
              "links": [ ... ],
              "cross_graph_links": [ ... ]   # only if include_cross_graph_links=True
            }

        Use this document for import_graph, diff_graphs, or as an archive.
        """
        return service.export_graph(graph_id, include_cross_graph_links)

    @mcp.tool
    def import_graph(
        export_doc: dict,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        new_name: str | None = None,
        merge_into_graph_id: str | None = None,
    ) -> dict:
        """
        Import an export document into a new graph or merge into an existing one.

        New graph mode (merge_into_graph_id omitted):
          Creates a new graph using new_name (or the original graph name).
          Imports all nodes and intra-graph links. Duplicate source_ids are skipped.

        Merge mode (merge_into_graph_id provided):
          Adds only nodes/links that do not already exist in the target graph.

        Returns the target graph dict.
        """
        return service.import_graph(
            export_doc=export_doc,
            actor_id=actor_id,
            new_name=new_name,
            merge_into_graph_id=merge_into_graph_id,
        )

    @mcp.tool
    def diff_graphs(
        base: str | dict,
        compare: str | dict,
        include_cross_graph_links: bool = False,
    ) -> dict:
        """
        Compare two graph states and return a structured delta.

        Each argument may be:
          - A graph_id string (live graph exported on-the-fly)
          - A snapshot reference: "snapshot:<snapshot_id>"
          - A pre-built export document dict

        Returns:
            {
              "nodes_added":   [...],   # in compare, not in base (by source_id)
              "nodes_removed": [...],   # in base, not in compare
              "nodes_changed": [...],   # same source_id, different content
              "links_added":   [...],
              "links_removed": [...]
            }
        """
        return service.diff_graphs(
            base=base,
            compare=compare,
            include_cross_graph_links=include_cross_graph_links,
        )

    @mcp.tool
    def execute_batch(
        graph_id: str,
        node_operations: list[dict],
        link_operations: list[dict],
        actor_id: str = _MCP_DEFAULT_ACTOR,
        default_link_type_id: str | None = None,
    ) -> dict:
        """
        Execute a batch of node and link operations atomically.

        All operations run in a single transaction — any failure rolls back everything.
        The engine determines correct execution order (4-phase):
          1. ADD_NODE / UPDATE_NODE
          2. CREATE_LINK / UPDATE_LINK
          3. DESTROY_LINK
          4. DELETE_NODE

        node_operations items:
          { "verb": "ADD_NODE",    "data": { "source_id": "...", "name": "..." } }
          { "verb": "UPDATE_NODE", "data": { "node_id": "...", "name": "..." } }
          { "verb": "DELETE_NODE", "data": { "node_id": "...", "force": false } }

        link_operations items:
          { "verb": "CREATE_LINK",  "data": { "from_node_id": "...", "to_node_id": "...", "link_type_id": 1 } }
          { "verb": "UPDATE_LINK",  "data": { "link_id": "...", "link_order": 2.0 } }
          { "verb": "DESTROY_LINK", "data": { "link_id": "..." } }

        Returns operation counters: nodes_added, nodes_updated, nodes_deleted,
        links_created, links_updated, links_destroyed, ledger_entries.
        """
        batch = {
            "graph_id": graph_id,
            "actor_id": actor_id,
            "default_link_type_id": default_link_type_id,
            "node_operations": node_operations,
            "link_operations": link_operations,
        }
        return service.execute_batch(batch, actor_id=actor_id)

    # ── BQL query tool ─────────────────────────────────────────────────────

    @mcp.tool
    def banyan_query(query: dict) -> dict:
        """
        Execute a BQL (Banyan Query Language) traversal query against the graph store.

        Required:
          graph — {"name": "..."} or {"id": "..."}

        Optional:
          starting — NodePredicate to seed the traversal (omit = use graph root)
          steps    — list of traversal hops; omit = full FROM traversal from seed
          result   — {"format": "LINK_NODE"|"NODE", "include_seed": bool, "limit": N}
          verbose  — true to include per-step diagnostics in response

        Each step supports:
          direction  — "FROM" | "TO" | "WITH"
          link_types — list of link type names, e.g. ["HIERARCHICAL", "SAME_AS"]
          depth      — max hops within this step (default: unlimited)
          collect    — whether to include results in output (default: true)
          graphs     — graph names to restrict traversal, or ["*"] for all graphs

        NodePredicate fields: name, name_contains, name_starts, source_id,
        source_id_prefix, node_id, node_type, metadata.<path>.
        Each field accepts a plain value or an operator dict:
        {"eq"|"neq"|"contains"|"starts"|"gte"|"lte"|"in": value}.
        Compound: {"and": [...]} / {"or": [...]}.

        Response: {seed_count, total_count, results: [...], steps: [...] if verbose}
        LINK_NODE result item: {_step, _depth, _net_depth, _direction, link: {...}, node: {...}}
        NODE result item: {_step, _depth, _net_depth, _direction, ...node_fields}
        Seed items have _step=0 and link=null.

        Example — full graph export:
          {"graph": {"name": "Open Eligibility"}}

        Example — crosswalk gap analysis (Gravity nodes that have a SAME_AS link):
          {"graph": {"name": "Gravity SDOH Clinical Care STU 2.3"},
           "steps": [{"direction": "WITH",
                      "link_types": ["SAME_AS", "SAME_AS_PROPOSED"],
                      "depth": 1,
                      "graphs": ["*"]}]}

        Example — cross-graph HAS_MEMBER codes for a specific node:
          {"graph": {"name": "Gravity SDOH Clinical Care STU 2.3"},
           "starting": {"name": "Food Insecurity"},
           "steps": [
             {"direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1, "collect": false},
             {"direction": "FROM", "link_types": ["HAS_MEMBER"], "depth": 1, "graphs": ["*"]}
           ]}
        """
        return service.execute_bql(query)

    # ── Persona-1 crosswalk tools ───────────────────────────────────────────

    @mcp.tool
    def banyan_get_crosswalk_candidates(
        gravity_node_name: str,
        target_graph_name: str = "Open Eligibility",
    ) -> dict:
        """
        Fetch the structured context needed to evaluate crosswalk candidates for a
        Gravity SDOH L1 node against a target taxonomy (default: Open Eligibility).

        Returns a crosswalk brief with five sections:
          source_node          — Gravity L1 node (node_id, name, notes, source_id,
                                 graph_id)
          source_children      — L2 children (node_id, name, source_id)
          source_codes         — HAS_MEMBER clinical codes from all L2 children
                                 (node_id, name, source_id) — may span multiple
                                 terminology graphs (SNOMED, ICD-10-CM, etc.)
          target_nodes         — candidate L1+L2 nodes in the target graph;
                                 each has node_id, name, source_id, graph_id,
                                 depth (1=L1, 2=L2), and children (list of L3 names)
          existing_crosswalk_links — any SAME_AS or SAME_AS_PROPOSED links already
                                 on this source node (link_id, link_type, to_node)

        The source_codes from clinical terminologies are the strongest matching
        signal: code display names encode clinical meaning beyond taxonomy labels.

        Use this data to reason about and rank candidate matches, then call
        banyan_create_crosswalk_link to assert the chosen link(s).
        If no candidates meet the two-signal threshold, report the gap explicitly.
        """
        GRAVITY_GRAPH = "Gravity SDOH Clinical Care STU 2.3"

        # ── 1. Source context: seed node + L2 children + HAS_MEMBER codes ──
        ctx = service.execute_bql({
            "graph": {"name": GRAVITY_GRAPH},
            "starting": {"name": gravity_node_name},
            "steps": [
                {
                    "direction": "FROM",
                    "link_types": ["HIERARCHICAL"],
                    "depth": 1,
                    "collect": True,
                },
                {
                    "direction": "FROM",
                    "link_types": ["HAS_MEMBER"],
                    "depth": 1,
                    "collect": True,
                    "graphs": ["*"],
                },
            ],
        })

        if ctx["seed_count"] == 0:
            return {"error": f"Gravity node not found: {gravity_node_name!r}"}

        source_node = None
        children: list[dict] = []
        codes: list[dict] = []

        for item in ctx["results"]:
            node = item.get("node") or item
            step = item["_step"]
            if step == 0:
                source_node = {
                    "node_id": node["node_id"],
                    "name": node["name"],
                    "notes": node.get("notes"),
                    "source_id": node["source_id"],
                    "graph_id": node["graph_id"],
                }
            elif step == 1:
                children.append({
                    "node_id": node["node_id"],
                    "name": node["name"],
                    "source_id": node["source_id"],
                })
            elif step == 2:
                codes.append({
                    "node_id": node["node_id"],
                    "name": node["name"],
                    "source_id": node["source_id"],
                })

        # ── 2. Target candidate pool (L1 + L2 + L3 names as children) ──
        oe = service.execute_bql({
            "graph": {"name": target_graph_name},
            "steps": [{
                "direction": "FROM",
                "link_types": ["HIERARCHICAL"],
                "depth": 3,
                "collect": True,
            }],
        })

        child_names_by_parent: dict[str, list[str]] = {}
        nodes_by_id: dict[str, dict] = {}
        for item in oe["results"]:
            if item["_step"] == 0:
                continue  # skip graph root
            node = item.get("node") or item
            link = item.get("link") or {}
            nid = node["node_id"]
            nd = item["_net_depth"]
            nodes_by_id[nid] = {
                "node_id": nid,
                "name": node["name"],
                "source_id": node["source_id"],
                "graph_id": node["graph_id"],
                "depth": nd,
            }
            parent_id = link.get("from_node_id")
            if parent_id:
                child_names_by_parent.setdefault(parent_id, []).append(node["name"])

        target_nodes = [
            {**data, "children": child_names_by_parent.get(nid, [])}
            for nid, data in nodes_by_id.items()
            if data["depth"] <= 2
        ]

        # ── 3. Existing crosswalk links on this source node ──
        ex = service.execute_bql({
            "graph": {"name": GRAVITY_GRAPH},
            "starting": {"name": gravity_node_name},
            "steps": [{
                "direction": "WITH",
                "link_types": ["SAME_AS", "SAME_AS_PROPOSED"],
                "depth": 1,
                "collect": True,
                "graphs": ["*"],
            }],
        })

        existing_links = [
            {
                "link_id": (item.get("link") or {}).get("link_id"),
                "link_type": (item.get("link") or {}).get("link_type_name"),
                "to_node": {
                    "node_id": (item.get("node") or {}).get("node_id"),
                    "name": (item.get("node") or {}).get("name"),
                },
            }
            for item in ex["results"]
            if item["_step"] != 0
        ]

        return {
            "source_node": source_node,
            "source_children": children,
            "source_codes": codes,
            "target_graph": target_graph_name,
            "target_nodes": target_nodes,
            "existing_crosswalk_links": existing_links,
        }

    @mcp.tool
    def banyan_create_crosswalk_link(
        from_node_id: str,
        to_node_id: str,
        link_type_name: str,
        rationale: str,
        actor_id: str = _MCP_DEFAULT_ACTOR,
        confidence_level: str | None = None,
        confidence_basis: list[str] | None = None,
        caveats: str | None = None,
    ) -> dict:
        """
        Create a typed crosswalk link between two nodes, with structured metadata.

        link_type_name must be one of:
          SAME_AS               — editorially confirmed equivalence (link_provenance='asserted')
          TERM_SIMILAR          — overlapping but not identical scope; preferred for
                                  Gravity L1 domain → OE L1 service category mappings
                                  (link_provenance='asserted')
          SAME_AS_PROPOSED      — agent-proposed SAME_AS awaiting review
          TERM_SIMILAR_PROPOSED — agent-proposed TERM_SIMILAR awaiting review;
                                  use for L1 domain-level mappings where full
                                  equivalence is unlikely

        rationale is required. Store the key evidence for and against the match.

        confidence_level: HIGH | MEDIUM | LOW | UNCERTAIN
          Categorical confidence rating - not a probability.
          Use HIGH only when evidence is strong and unambiguous.
          UNCERTAIN = plausible but no strong signal.

        confidence_basis: list of signals from:
          name_similarity | code_overlap | domain_alignment |
          population_overlap | service_alignment | no_clear_signal

        caveats: scope limitations or reasons the match may not hold.

        Graph IDs are resolved automatically from the node records.

        Returns the created link dict.
        """
        _KNOWN: dict[str, tuple[str, str]] = {
            "SAME_AS":               ("ba0ba000-0000-0000-0000-000000000011", "asserted"),
            "TERM_SIMILAR":          ("ba0ba000-0000-0000-0000-000000000013", "asserted"),
            "SAME_AS_PROPOSED":      ("ba0ba000-0000-0000-0000-000000000016", "proposed"),
            "TERM_SIMILAR_PROPOSED": ("ba0ba000-0000-0000-0000-000000000018", "proposed"),
        }
        if link_type_name not in _KNOWN:
            raise ValueError(
                f"link_type_name must be one of {list(_KNOWN)}; got {link_type_name!r}"
            )
        link_type_id, provenance = _KNOWN[link_type_name]

        # Resolve graph IDs from the nodes — agent only needs node UUIDs
        from_node = service.get_node(from_node_id)
        to_node = service.get_node(to_node_id)

        metadata: dict = {"link_provenance": provenance, "agent_rationale": rationale}
        if confidence_level:
            if confidence_level not in ("HIGH", "MEDIUM", "LOW", "UNCERTAIN"):
                raise ValueError(
                    f"confidence_level must be HIGH | MEDIUM | LOW | UNCERTAIN; got {confidence_level!r}"
                )
            metadata["confidence_level"] = confidence_level
        if confidence_basis:
            metadata["confidence_basis"] = confidence_basis
        if caveats:
            metadata["caveats"] = caveats

        return service.create_link(
            link_type_id=link_type_id,
            from_graph_id=from_node["graph_id"],
            to_graph_id=to_node["graph_id"],
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            actor_id=actor_id,
            metadata=metadata,
        )

    # ── Chain integrity ────────────────────────────────────────────────────

    @mcp.tool
    def verify_ledger_chain() -> dict:
        """
        Verify the integrity of the global ledger hash chain.

        Re-computes every entry_hash from stored fields and confirms each
        entry's previous_hash matches the preceding entry's entry_hash.
        Any gap, reorder, or field modification will break the chain.

        Returns:
          {"ok": true,  "entries_checked": N}
          {"ok": false, "entries_checked": N, "first_broken_ledger_id": M}
        """
        return service.verify_ledger_chain()

    return mcp
