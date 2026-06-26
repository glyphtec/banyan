# Banyan Crosswalk Viewer — UX Project Specification

**Status:** Design approved, not yet scaffolded  
**Target:** Integrated into the Banyan monorepo (`frontend/`)  
**Purpose:** Read-only visualization layer for the Social-Clinical Crosswalk POC  
**Audience for this doc:** Strategic review, project hygiene, implementation handoff

---

## Versioning Note

This specification covers two distinct UX modes with different audiences and release scopes.
They are **not feature flags on the same interface** — they serve different demonstration
purposes and are deliberately sequenced.

| Mode | Audience | Release |
|---|---|---|
| **V1 — Structured Viewer** | System validator; ontology-aware technology evaluator | Current scope |
| **V2 — Practitioner Query** | Practitioner; AI-first interactive demonstration | Essential pre-demo; sequenced after V1 substrate |

V1 proves the graph is correct, the crosswalks are sound, and the provenance is real.
V2 proves the same power is accessible to a non-technical practitioner through natural language,
and that the system is honest when there is no good answer.

---

## 1. Context and Rationale

### V1 — Structured Viewer

Primary audience: **the system validator** (the builder, confirming the graph is correct) and
an **ontology-aware technology evaluator** (a standards body representative, informatics
specialist, or HIE technical lead who can read a taxonomy tree and interpret link-type semantics).

This audience does not need narrative. They need to see the *actual structure*: what nodes
exist, how they are linked, what crosswalk assertions have been recorded, and what the ledger
says about each one. The visualisation is the proof. The V1 interface is a structured inspection
tool, not a consumer product.

A full CRUDX frontend would take weeks and deliver marginal POC value. Inverting the priority —
building a read-only, visualization-first UI — delivers the entire demonstrator narrative in a
fraction of the time. CRUDX functionality is explicitly deferred until there is an active second
stakeholder audience requiring it.

### V2 — Practitioner Query (Deferred Fork)

Primary audience: **a practitioner** — a care coordinator, social worker, or program director
who does not read ontology graphs and does not need to. They have a question in their own words
and need a trustable answer, or an honest acknowledgment that no answer exists yet.

V2 demonstrates that the same curated, auditable graph that satisfies the technology evaluator
is also accessible via a native AI-first capability: the practitioner speaks; an LLM resolves
their language to a graph node via MCP tools; the deterministic substrate answers from real
structure; the interface shows both what the model did and what the graph says, with the seam
between them explicit. A refusal — "no crosswalk link is recorded for this term" — is a
first-class, trustworthy answer, not a failure.

V2 is a separate UX fork, not a tab or mode added to V1. It shares the backend (same REST and
MCP endpoints) but has a different entry-point interaction and a different explanation surface.
It is the primary practitioner-facing demonstration of the thesis and is considered essential
before any external demo. V1 is its prerequisite substrate, not an end state. It is documented
here now to prevent architectural decisions in V1 from foreclosing it.

---

## 2. Scope

### V1 — In Scope
- Graph selector: choose any Banyan graph to explore
- Searchable, collapsible taxonomy tree (single graph)
- Node selection with properties display
- Term Equivalents tab: intra-graph TERM_EQUIVALENT neighbors and their parent context
- Crosswalk tab: SAME_AS links to a user-selected comparison graph
- History tab: ledger audit trail for selected node (lightweight, V1 — no visual diff required)

### V1 — Out of Scope (explicitly deferred)
- Any create, update, or delete operations
- User authentication / RBAC
- Graph editing or link authoring through the UI
- Mobile layout
- Stakeholder registry UI

### V2 — Deferred Fork (not in V1 scope)
- Natural language query bar
- LLM resolution via Banyan MCP tools (`api/mcp_server.py`)
- Resolution trace display (the model's tool calls, the node it landed on, confidence)
- Logic path panel showing the boundary between model work and graph answer
- Honest refusal surface for queries with no recorded crosswalk answer
- Practitioner-readable explanation of graph results (framing only — graph data is authoritative)

V2 shares the same backend. The `setSelectedNode` abstraction in V1 is the designed unification
point: V2 produces a node selection through LLM resolution; V1 produces it through tree browsing.
The downstream detail panel is the same component.

---

## 3. Architecture

### Repo placement
Integrated into the existing Banyan monorepo at `frontend/`. No separate repo.
Rationale: the viewer has no meaning without a running Banyan backend instance; it is a
demonstrator of the platform, not an independent product. A repo split is appropriate only
when a second independent frontend consumer exists.

### Tech stack
| Concern | Library | Notes |
|---|---|---|
| Build | Vite 5 | Already in `frontend/package.json` |
| UI framework | React 18 | Already present |
| Component library | shadcn/ui | Unstyled primitives, Tailwind-based |
| Data fetching | TanStack Query (React Query v5) | Caching, loading states, background refetch |
| Tree view | react-arborist | Virtualised, handles 1000+ nodes, built-in search |
| Neighborhood graph | ReactFlow (@xyflow/react) | Pan/zoom canvas, edge rendering |
| Styling | Tailwind CSS | Via shadcn/ui setup |

### Backend dependencies
All data comes from existing, fully-tested REST endpoints. No new backend endpoints required.

| Data needed | Endpoint |
|---|---|
| List all graphs | `GET /api/v1/graphs` |
| Full tree + intra-graph links | `GET /api/v1/graphs/{id}/export` |
| Cross-graph (crosswalk) links | `GET /api/v1/graphs/{id}/export?include_cross_graph_links=true` |
| Node ledger history | `GET /api/v1/graphs/{id}/history` (filter by `entity_id` client-side) |

**CORS:** FastAPI CORS middleware must be enabled for `http://localhost:5173` (Vite dev server).
Not yet configured in `app.py` — required before first browser test.

---

## 4. Component Architecture

```
App
├── GraphSelector          — dropdown populated from GET /api/v1/graphs
│                            filters out __system__ sentinel graph
└── GraphExplorer          — mounts when a graph is selected; fetches export
    ├── TreePanel  (left, ~40% viewport width)
    │   ├── SearchInput    — controlled input drives arborist searchTerm prop
    │   └── ArboristTree   — virtualised tree; read-only (no drag/drop)
    │                        onSelect triggers right panel update
    └── DetailPanel  (right, ~60% viewport width)
        ├── NodeHeader     — compact properties bar (always visible when node selected)
        │                    fields: name, source_id, breadcrumb path to root,
        │                    link-count badges (children, TERM_EQUIV, SAME_AS)
        ├── CrosswalkTargetSelector
        │                  — graph picker at panel level; persists across node selections
        │                    excludes the currently browsed graph from options
        └── TabPanel
            ├── Tab: Equivalents   — TERM_EQUIVALENT neighbors + their parent chain
            ├── Tab: Crosswalk     — ReactFlow mini-canvas (see Section 5)
            └── Tab: History       — ledger entries for selected node (Phase 2)
```

---

## 5. Detailed View Specifications

### 5.1 Tree Panel

**Data source:** `nodes` + `links` arrays from the export payload. Client builds a
`Map<node_id, children[]>` adjacency structure keyed by HIERARCHICAL link type
(`ba0ba000-0000-0000-0000-000000000001`). Root node (`source_id = "$ROOT$"`) is the
arborist tree root but is not displayed as a visible node — its children are the L1 terms.

**Search behaviour:** Uses react-arborist native `searchTerm` prop. Matching is
case-insensitive substring on `node.name`. Non-matching nodes are hidden (not dimmed).
Matching nodes whose parents are hidden remain visible — arborist handles this.

**Search → select → refocus flow:**
1. User types in SearchInput → `searchTerm` state updates → tree filters
2. User clicks a match → `onSelect` fires:
   - `setSelectedNode(node.data)` — updates right panel
   - `setSearchTerm("")` — clears filter, full tree re-renders
   - `setTimeout(() => treeRef.current?.scrollTo(node.id, "auto"), 0)` — scroll after
     re-render tick; ancestors are auto-expanded by arborist on scroll
3. Full tree is now visible with selected node centred in viewport

The `setTimeout(0)` deferred scroll is required: `scrollTo` needs the full node list
rendered in the DOM before it has a valid scroll target.

**Tree node renderer:** Each row shows `node.name`. No inline edit controls.
Selected node highlighted with accent background. Expand/collapse chevron on
nodes that have children.

### 5.2 Node Header (NodeHeader component)

Displayed immediately when a node is selected. Compact single-card layout:

```
┌────────────────────────────────────────────────────┐
│  Pain Management                  source_id: 1189  │
│  ▸ End-of-Life Care ▸ Health                       │
│  ○ 0 children   ≡ 2 TERM_EQUIV   ↔ 1 SAME_AS      │
└────────────────────────────────────────────────────┘
```

Breadcrumb is derived client-side by walking the HIERARCHICAL inbound link chain from
the selected node to the root. Badge counts are derived from the link array filtered
by link type and endpoint.

### 5.3 Equivalents Tab

Purpose: reveal the browse-copy structure of OE (and any source taxonomy with similar
single-parent constraints). For each TERM_EQUIVALENT partner of the selected node,
show the partner node card and its immediate parent — the "proxy co-parent."

```
Also appears under:

  Pain Management  (1222)          Pain Management  (1291)
  └─ Prevent & Treat               └─ End-of-Life Care
     └─ Medical Care                  └─ Care
```

**Data derivation (entirely from export payload, no additional API calls):**
1. Filter `links` for `link_type_id = ba0ba000-0000-0000-0000-000000000012` (TERM_EQUIVALENT)
   where `from_node_id` or `to_node_id` equals `selectedNode.node_id`
2. For each partner node, walk HIERARCHICAL inbound links to build parent chain
3. Render as stacked cards, one per partner

If no TERM_EQUIVALENT links exist, the tab shows: *"No equivalent terms — this node
appears only once in this taxonomy."*

### 5.4 Crosswalk Tab

Purpose: show the selected node's SAME_AS connections to a user-chosen comparison graph.
Rendered as a ReactFlow mini-canvas with pan and zoom.

**Canvas layout:**
```
        [parent node]
             │  HIERARCHICAL
        [SELECTED NODE] ────── SAME_AS ──────► [Gravity term A]
             │                        ──────► [Gravity term B]
    ┌────────┴────────┐
[child 1]         [child 2]
```

Left column: selected node's immediate HIERARCHICAL neighborhood (parent + children)
from the browsed graph.

Right column: SAME_AS targets from the comparison graph. Each target card shows
`name` and `source_id`. Clicking a target card is a no-op in Phase 1 (read-only).

**CrosswalkTargetSelector** (above the tab panel, not inside the tab):
- Populated from `GET /api/v1/graphs`
- Excludes the currently browsed graph
- Selecting a comparison graph triggers
  `GET /api/v1/graphs/{browsed_id}/export?include_cross_graph_links=true`
- Result is cached by TanStack Query

**Data derivation:**
1. Filter `cross_graph_links` for `link_type_id = ba0ba000-0000-0000-0000-000000000011`
   (SAME_AS) where one endpoint is `selectedNode.node_id` and
   `to_graph_id` or `from_graph_id` matches the selected comparison graph
2. Look up target node details from the comparison graph's export (separately fetched
   and cached)
3. Build ReactFlow nodes and edges from the derived data

If no comparison graph selected: tab shows prompt *"Select a comparison graph above
to see crosswalk connections."*

If no SAME_AS links exist for this node: *"No crosswalk links recorded for this term yet."*

### 5.5 History Tab

Purpose: demonstrate that every assertion has a receipt. This is the provenance story made
visible — the differentiator from a graph store with no memory. High value for the
ontology-aware evaluator audience.

**Data source:** `GET /api/v1/graphs/{id}/history`, filtered client-side where
`entity_id = selectedNode.node_id`. Displayed in reverse-chronological order.

**Rendered columns per entry:**
- `inserted_datetime` — human-formatted timestamp
- `primitive_verb` — the action (CREATE_NODE, CREATE_LINK, etc.)
- `actor_id` — who or what asserted it (system, ingest script, user)
- `source_graph_id` — originating graph if cross-graph (nullable; omit column if null for all)

No payload diff view. No visual comparison between versions. A flat, honest chronological
log is sufficient and appropriate for the V1 audience.

---

## 6. Well-Known System Constants

These UUIDs are stable seed values and should be referenced as named constants in the
frontend source (e.g. `src/constants/banyan.js`), never hardcoded inline:

```js
export const LINK_TYPE = {
  HIERARCHICAL:    "ba0ba000-0000-0000-0000-000000000001",
  RELATED:         "ba0ba000-0000-0000-0000-000000000002",
  SYNONYM:         "ba0ba000-0000-0000-0000-000000000003",
  SAME_AS:         "ba0ba000-0000-0000-0000-000000000011",
  TERM_EQUIVALENT: "ba0ba000-0000-0000-0000-000000000012",
  TERM_SIMILAR:    "ba0ba000-0000-0000-0000-000000000013",
  TERM_VARIANT:    "ba0ba000-0000-0000-0000-000000000014",
}

export const NODE_TYPE = {
  GENERIC: "ba0ba000-0000-0000-0000-000000000101",
}

export const SYSTEM_GRAPH_ID = "ba0ba000-0000-0000-0000-000000000000"
```

---

## 7. Build Order

| Phase | Deliverable | Key dependencies |
|---|---|---|
| 1a | Backend CORS config + npm install (shadcn, arborist, ReactFlow, TanStack Query) | None |
| 1b | GraphSelector + bare GraphExplorer shell, fetches export, logs to console | CORS live |
| 1c | ArboristTree rendering full taxonomy, expand/collapse working | Export data flowing |
| 1d | SearchInput wired, search → select → refocus flow complete | Tree rendering |
| 1e | NodeHeader panel, breadcrumb, badge counts | Node selection |
| 1f | Equivalents tab | Node selection, link data |
| 1g | CrosswalkTargetSelector + cross_graph_links fetch | Two graphs loaded |
| 1h | Crosswalk tab (ReactFlow canvas) | Cross-graph links |
| 1i | History tab (lightweight ledger list) | Ledger endpoint |
| — | **Backend: hash-chain ledger (elevated priority)** | Separate work item; required before external demo |

---

## 8. Open Questions / Decisions Deferred

| Question | Status |
|---|---|
| Clicking a crosswalk target node — does it navigate to that node in its own graph? | Deferred (requires graph-switch UX) |
| TERM_SIMILAR / TERM_VARIANT display in Equivalents tab | Deferred until first use case |
| Dark/light mode | Not decided |
| Whether `$ROOT$` node children (L1 terms) should be the arborist root level or L0 should show | Decided: hide `$ROOT$`, L1 is visual root |
| Diff view (compare two snapshots visually) | Phase 3 |
