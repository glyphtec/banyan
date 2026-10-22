# Banyan Project

## BQL — Banyan Query Language

A graph query and traversal language.

---

## Overview

A straightforward, proprietary language for graph search and traversal. The primary serialization is JSON; a parseable SQL-ish text overlay is a future option and does not affect the core spec.

The language assumes logical fallback/default rules so that the simplest query is genuinely simple.

BQL is intended to replace all ad-hoc child/parent traversal endpoints and to support impact analysis, crosswalk exploration, and multi-graph path queries through a single `POST /api/v1/query` endpoint — avoiding the proliferation of narrow tactical retrieval endpoints.

Advanced traversal algorithms (minimum spanning subgraph, etc.) are possible future modular inclusions but are out of scope for the initial implementation.

**Cycle prevention:** Within each step's depth traversal, a local `seen` set prevents revisiting nodes (halting infinite loops in cyclic graphs). This set starts **fresh for each step** — nodes visited in step N are not blocked from being discovered by step N+1. `depth` is the primary guard against runaway traversal within a step.

**Cross-step revisits are allowed.** Because `seen` resets between steps, the same node may appear in results from multiple steps. This is intentional: zig-zag patterns, link discovery between already-traversed nodes, and ancestor lookups all require a step to re-enter nodes that earlier steps found. Callers that need unique-node semantics should deduplicate by `node_id` at the result layer.

**LINK_NODE collection and dense clusters.** In `LINK_NODE` format, a step collects a link item even when the destination node is already in the current step's local `seen`. Only frontier expansion (adding the destination to the next hop's input) is gated on `seen`. This ensures all links touching the frontier are observable — critical for discovering links between nodes that are all members of the same frontier (e.g. finding all `TERM_EQUIVALENT` links within a graph whose nodes were all found in a prior HIERARCHICAL step).

---

## Structure

### 1. `graph` — required

The origin graph for the query. All traversal begins here unless a step explicitly names other graphs.

Specified by `name` or `id`.

```json
{ "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" } }
{ "graph": { "id": "27c5159e-ea26-4b9d-8d66-427977e74c3d" } }
```

---

### 2. `starting` — optional (default: root node)

A predicate expression that selects the seed node(s) within the origin graph. If omitted, the graph's root node is the implicit seed.

#### NodePredicate — recursive boolean expression

A `NodePredicate` is one of:

**Leaf** — an object with one or more field-predicate pairs, implicitly ANDed:
```json
{ "name": "Elder Abuse" }
{ "name_contains": "food", "node_type": "Condition" }
```

**Compound** — explicit boolean wrapper:
```json
{ "or":  [ NodePredicate, ... ] }
{ "and": [ NodePredicate, ... ] }
```

Compound and leaf forms nest freely:
```json
{
  "and": [
    { "name_contains": "Food" },
    { "or": [ { "source_id_prefix": "sdoh:" }, { "source_id_prefix": "gravity:" } ] }
  ]
}
```

#### Built-in field predicates

| Key | Match behavior |
|-----|---------------|
| `name` | Exact, case-insensitive |
| `name_contains` | Substring (ILIKE) |
| `name_starts` | Prefix match |
| `source_id` | Exact |
| `source_id_prefix` | Prefix |
| `node_id` | Exact UUID (programmatic use) |
| `node_type` | Node type name, exact |
| `metadata.<path>` | JSON field within metadata column |

#### Extended operator form

Any field may use an operator object instead of a bare value:

```json
{ "metadata.level": { "gte": 1, "lte": 3 } }
{ "name": { "in": ["Elder Abuse", "Toxic Stress"] } }
```

Supported operators: `eq`, `neq`, `contains`, `starts`, `gte`, `lte`, `in`.

The bare-value shorthand `{ "name": "X" }` is equivalent to `{ "name": { "eq": "X" } }`.

---

### 3. `steps` — optional

An ordered list of traversal steps. Each step receives as its input **only the node set produced by the immediately preceding step** (or the seed for step 1). The full accumulated result set is separate from the traversal input — step N+1 never re-traverses from step N-1 results or the seed.

Nodes found across all steps are accumulated into the response, subject to each step's `collect` flag. Because `seen` is per-step, a node may appear more than once across steps — callers should deduplicate by `node_id` if unique-node results are required.

**When `steps` is absent**, a single default step is implied:

| Field | Default value |
|-------|---------------|
| `direction` | `FROM` |
| `link_types` | all types |
| `depth` | unlimited |
| `node_types` | no filter |
| `graphs` | origin graph only |

With no `starting` and no `steps`: full graph export from root — equivalent to the export endpoint.
With `starting` and no `steps`: full subtree rooted at the matched node(s).

#### Step fields

| Field | Values | Default | Notes |
|-------|--------|---------|-------|
| `direction` | `FROM`, `TO`, `WITH` | required | `FROM` = outbound links; `TO` = inbound links; `WITH` = both directions |
| `link_types` | list of link type names | all types | Append `!` to a name for exact-type match (no subtypes). E.g. `["HIERARCHICAL!", "RELATED"]` |
| `depth` | integer ≥ 1 | unlimited | Max hops for this step's traversal |
| `node_types` | list of node type names | no filter | Restricts nodes included in this step's result |
| `graphs` | list of graph names or ids | origin graph only | Graphs the traversal may enter. Use `["*"]` for unrestricted cross-graph |
| `collect` | `true`, `false` | `true` | Whether this step’s results are included in the response. The step always executes and its output always feeds the next step regardless of this flag. |

**`link_types` modifier:** `"HIERARCHICAL"` matches that type and all its subtypes (family traversal). `"HIERARCHICAL!"` matches only that exact type, ignoring subtypes.

---

### 4. `result` — optional

Controls the shape and content of the response.

| Field | Values | Default |
|-------|--------|---------|
| `format` | `NODE`, `LINK_NODE` | `LINK_NODE` |
| `include_seed` | `true`, `false` | `true` |
| `limit` | integer | none |
| `verbose` | `true`, `false` | `false` |

**`format: LINK_NODE`** — each result item is a wrapper containing the traversed link and the reached node.

**`format: NODE`** — only node objects are returned, without link wrappers. Traversal metadata (`_step`, `_depth`, `_net_depth`) is still attached to each node object.

**`include_seed` semantics:** When `true`, seed nodes are proactively added to the result set before step 1 runs. When `false`, they are not proactively added — but if a traversal step reaches a seed node, that node will appear in the results as a normal step result. `include_seed` controls proactive insertion, not global exclusion.

**`verbose: true`** adds per-step diagnostic counts to the response envelope (see Response Envelope below).

---

## Response Envelope

All BQL responses are wrapped in a consistent envelope regardless of result count:

```json
{
  "success": true,
  "seed_count": 1,
  "total_count": 5,
  "steps": null,
  "results": [ ... ]
}
```

With `verbose: true`, the `steps` field is populated with per-step diagnostics:

```json
{
  "success": true,
  "seed_count": 1,
  "total_count": 5,
  "steps": [
    { "step": 1, "input_count": 1, "output_count": 1, "collected": false },
    { "step": 2, "input_count": 1, "output_count": 4, "collected": true }
  ],
  "results": [ ... ]
}
```

`seed_count` is always present — it's the number of nodes matched by the `starting` predicate (useful for debugging silent empty results due to seed mismatch). A `total_count` of 0 with a `seed_count` of 0 means the starting predicate found nothing; a `total_count` of 0 with a `seed_count` > 0 means the traversal found nothing from valid seeds.

---

## Result Item Shape

### `LINK_NODE` format

```json
{
  "_step": 1,
  "_depth": 2,
  "_net_depth": 2,
  "_direction": "FROM",
  "link": {
    "link_id": "...",
    "link_type_id": "...",
    "link_type_name": "HIERARCHICAL",
    "from_node_id": "...",
    "to_node_id": "..."
  },
  "node": { }
}
```

Seed nodes (when `include_seed: true`) appear with `_step: 0`, `_depth: 0`, `_net_depth: 0`, `_direction: null`, `link: null`.

`_direction` reflects the actual direction traversed — useful when the step used `WITH`.

### `NODE` format

```json
{
  "_step": 1,
  "_depth": 2,
  "_net_depth": 2,
  "_direction": "FROM",
  "node_id": "...",
  "name": "...",
  ...
}
```

---

## Examples

### Full graph export — no starting, no steps

Equivalent to the export endpoint. Default step (FROM, all types, unlimited depth) is implied.

```json
{
  "graph": { "name": "Open Eligibility" }
}
```

### Subtree from a named node — starting only, no steps

All descendants of "Food" via any link type, unlimited depth.

```json
{
  "graph": { "name": "Open Eligibility" },
  "starting": { "name": "Food" }
}
```

### Path to parent (ancestor chain) — replaces the get-parents endpoint

Traverse TO (inbound) HIERARCHICAL links from a node upward. Returns the full ancestor chain in traversal order, closest parent first.

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": { "name": "Elder Abuse" },
  "steps": [
    {
      "direction": "TO",
      "link_types": ["HIERARCHICAL"],
      "depth": 50
    }
  ],
  "result": { "format": "LINK_NODE", "include_seed": false }
}
```

### Sibling nodes — the zig-zag pattern

Step 1 walks TO the immediate parent (`collect: false` — used as a waypoint only). Step 2 walks FROM that parent back down, reaching all siblings. The seed is in the result set before step 2 runs, so dedup silently prevents it re-appearing. The response contains only the seed and its siblings — the parent is never collected.

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": { "name": "Elder Abuse" },
  "steps": [
    {
      "direction": "TO",
      "link_types": ["HIERARCHICAL"],
      "depth": 1,
      "collect": false
    },
    {
      "direction": "FROM",
      "link_types": ["HIERARCHICAL"],
      "depth": 1
    }
  ],
  "result": { "format": "NODE", "include_seed": true }
}
```

> **Zig-zag result breakdown:**
> - `_step: 0` — Elder Abuse (seed, from `include_seed: true`)
> - `_step: 1` — parent (not collected, used only to seed step 2)
> - `_step: 2` — all children of the parent, including Elder Abuse itself

> **Filtering the seed from siblings:** Because `seen` is per-step, step 2 will re-discover Elder Abuse as a child of its parent. The seed appears at both `_step: 0` and `_step: 2`. To get siblings only (excluding the seed), either filter results where `_step == 2 && node_id != seed_node_id`, or set `include_seed: false` and deduplicate by `node_id` across steps.

### 2nd-degree subtree from two named nodes

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": {
    "or": [
      { "name": "Elder Abuse" },
      { "name": "Toxic Stress" }
    ]
  },
  "steps": [
    {
      "direction": "FROM",
      "link_types": ["HIERARCHICAL"],
      "depth": 2
    }
  ],
  "result": {
    "format": "LINK_NODE",
    "include_seed": true
  }
}
```

### Cross-graph: clinical codes that belong to a Gravity domain

`HAS_MEMBER` links run from a Gravity value-set node *to* codes in clinical terminology graphs (SNOMED CT, ICD-10-CM), not to Open Eligibility. Step 1 walks down to the domain's value-set nodes and is used only as a waypoint; step 2 crosses into the terminology graphs.

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": { "name": "Food Insecurity" },
  "steps": [
    {
      "direction": "FROM",
      "link_types": ["HIERARCHICAL"],
      "depth": 2,
      "collect": false
    },
    {
      "direction": "FROM",
      "link_types": ["HAS_MEMBER!"],
      "graphs": ["SNOMED SDOH Service Requests Slice", "SNOMED CT SDOH Slice", "ICD-10-CM SDOH Slice"]
    }
  ],
  "result": { "format": "NODE", "include_seed": false }
}
```

### Symmetric link discovery within a graph

Find all `TERM_EQUIVALENT_PROPOSED` links inside a graph where both endpoints are content nodes. Because both endpoints are in the frontier after the HIERARCHICAL fan-out (step 1), and `seen` resets for step 2, both endpoint nodes are discoverable via `WITH` traversal. The result contains two items per link (one per direction); group by `link.link_id` to pair them and retrieve both node objects without an extra lookup.

```json
{
  "graph": { "name": "Open Eligibility" },
  "steps": [
    {
      "direction": "FROM",
      "link_types": ["HIERARCHICAL"],
      "depth": 50,
      "collect": false
    },
    {
      "direction": "WITH",
      "link_types": ["TERM_EQUIVALENT_PROPOSED!"],
      "depth": 1,
      "graphs": ["*"],
      "collect": true
    },
    {
      "direction": "TO",
      "link_types": ["HIERARCHICAL"],
      "depth": 10,
      "graphs": ["*"],
      "collect": true
    }
  ],
  "result": { "format": "LINK_NODE", "include_seed": false }
}
```

Step 3 collects ancestor nodes for each step-2 peer, enabling breadcrumb path construction. Group step-3 results by `link.to_node_id` to build a `child → parent` map.

---

## Cookbook — the Social–Clinical Crosswalk

These recipes use the flagship demo dataset (see the [README](../README.md)). They are real queries that run against it; counts in your instance will differ.

**Graphs**

| Graph name | What it is | `source_id` convention |
|---|---|---|
| `Gravity SDOH Clinical Care STU 2.3` | Clinical social-risk domains (L1) and their value-set activities (L2) | `sdoh:food-insecurity`, `sdoh:food-insecurity/service-requests` |
| `Open Eligibility` | Social-service taxonomy | `OE.1102` |
| `SNOMED SDOH Service Requests Slice` | SNOMED CT codes for service requests | `http://snomed.info/sct\|951351000124101` |
| `SNOMED CT SDOH Slice` | SNOMED CT diagnoses, screening and other codes | `http://snomed.info/sct\|<code>` |
| `ICD-10-CM SDOH Slice` | ICD-10-CM Z-codes and related | code-system-prefixed |

**Link types used**

| Link type | Direction in the demo data | Meaning |
|---|---|---|
| `HIERARCHICAL` | parent → child, same graph | Taxonomy structure |
| `HAS_MEMBER` | Gravity value-set node → clinical code | The code belongs to the value set |
| `SAME_AS` | SNOMED code → OE category | Approved crosswalk assertion. Metadata: `link_provenance: "asserted"`, `approved_by` |
| `SAME_AS_PROPOSED` / `TERM_SIMILAR_PROPOSED` | Same | Agent-proposed mapping awaiting review. Metadata: `confidence_level`, `confidence_basis`, `agent_rationale`, `caveats`, later `review_status` / `reviewed_by` / `reviewer_note` |
| `TERM_EQUIVALENT` | OE node ↔ OE node | The same concept filed under two browse paths |

### 1. What is inside a domain?

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": { "name": "Food Insecurity" },
  "steps": [{ "direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1 }],
  "result": { "format": "NODE" }
}
```

Returns the domain plus its L2 value-set nodes (Service Requests, Procedures, Goals, Diagnoses, Screening Assessments, ...).

### 2. Which codes define a need? (clinical side)

See *Cross-graph: clinical codes that belong to a Gravity domain* under Examples. The same pattern works for any Gravity domain by changing `starting`.

### 3. The closed loop: clinical code → service category

*"A patient needs this service. Where do I send them?"* Start from a service-request code, follow its crosswalk to Open Eligibility, then step up to the parent category.

```json
{
  "graph": { "name": "SNOMED SDOH Service Requests Slice" },
  "starting": { "source_id": "http://snomed.info/sct|951411000124107" },
  "steps": [
    {
      "direction": "FROM",
      "link_types": ["SAME_AS!", "SAME_AS_PROPOSED!"],
      "depth": 1,
      "graphs": ["Open Eligibility"]
    },
    {
      "direction": "TO",
      "link_types": ["HIERARCHICAL"],
      "depth": 1,
      "graphs": ["Open Eligibility"]
    }
  ],
  "result": { "format": "LINK_NODE", "include_seed": true }
}
```

For "Provision of healthy groceries ..." this returns the code itself (step 0), the OE categories *Help Pay for Food* and *Free Meals* (step 1, with each link's provenance metadata), and their parent *Food* (step 2).

- Step 2 must list `graphs` too: the default scope is the origin graph only.
- *Food* appears twice because two step-1 nodes share that parent. Deduplicate by `node_id`.
- Including `SAME_AS_PROPOSED!` lets you see unreviewed candidates; check `link.metadata.link_provenance` (`asserted` vs `proposed`) to tell them apart, or drop it to return only approved mappings.

### 4. The reverse: which clinical codes map to a service category?

```json
{
  "graph": { "name": "Open Eligibility" },
  "starting": { "source_id": "OE.1132" },
  "steps": [
    {
      "direction": "TO",
      "link_types": ["SAME_AS!"],
      "depth": 1,
      "graphs": ["SNOMED SDOH Service Requests Slice"]
    }
  ],
  "result": { "format": "LINK_NODE", "include_seed": false }
}
```

Crosswalk links are stored in one direction (clinical → OE here), so reading them from the OE side uses `TO`. If you don't know which way a link was recorded, use `WITH`.

### 5. Coverage: which service-request codes are not yet mapped?

One query, then a set difference on the client:

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": { "source_id": "sdoh:food-insecurity/service-requests" },
  "steps": [
    {
      "direction": "FROM",
      "link_types": ["HAS_MEMBER!"],
      "graphs": ["SNOMED SDOH Service Requests Slice"],
      "depth": 1
    },
    {
      "direction": "FROM",
      "link_types": ["SAME_AS!", "SAME_AS_PROPOSED!"],
      "graphs": ["Open Eligibility"],
      "depth": 1
    }
  ],
  "result": { "format": "LINK_NODE", "include_seed": false, "verbose": true }
}
```

- `_step == 1` items are *all* codes in the value set.
- `_step == 2` items carry `link.from_node_id`, the codes that already have a crosswalk link.
- **Uncovered = step-1 `node_id`s minus step-2 `link.from_node_id`s.**

Do this in one query, never with one query per code.

### 6. The review queue: what is waiting for a human?

```json
{
  "graph": { "name": "Open Eligibility" },
  "steps": [
    { "direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 50, "collect": false },
    {
      "direction": "TO",
      "link_types": ["SAME_AS_PROPOSED!", "TERM_SIMILAR_PROPOSED!"],
      "depth": 1,
      "graphs": ["*"],
      "collect": true
    }
  ],
  "result": { "format": "LINK_NODE", "include_seed": false }
}
```

Step 1 fans out to every OE node as a waypoint; step 2 collects the proposed links pointing at them. Each item's `link.metadata` holds the agent's confidence, evidence, rationale and caveats, plus `review_status` once a reviewer has touched it. Because proposal state is a *link type*, "what is pending" needs no special endpoint.

### 7. Polyhierarchy: the same concept under two browse paths

Open Eligibility is single-parent, so some concepts appear twice (e.g. *Emergency Food*). Those are tied together with `TERM_EQUIVALENT` links.

```json
{
  "graph": { "name": "Open Eligibility" },
  "starting": { "source_id": "OE.1128" },
  "steps": [
    {
      "direction": "WITH",
      "link_types": ["TERM_EQUIVALENT", "TERM_EQUIVALENT_PROPOSED"],
      "depth": 1
    }
  ],
  "result": { "format": "NODE", "include_seed": false }
}
```

---

## Calling BQL

| Surface | How |
|---|---|
| REST | `POST /api/v1/query` with the query object as the JSON body |
| MCP | Tool `banyan_query`, argument `query` |
| Chat agent | Tool `banyan_query` |

```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"graph":{"name":"Open Eligibility"},"starting":{"source_id":"OE.1102"},"steps":[{"direction":"FROM","link_types":["HIERARCHICAL"],"depth":1}],"result":{"format":"NODE"}}'
```

An unknown graph returns HTTP 404 with a `detail` message. A `starting` predicate matching more than `MAX_SEED_SIZE` nodes is rejected; narrow it.

## Gotchas

- **`graphs` is per step and defaults to the origin graph only.** Any step that should enter another graph must name it (or use `["*"]`), including a later step that needs to stay inside that other graph, as in recipe 3.
- **`link_types` matches a family.** `"RELATED"` includes `SAME_AS`, `HAS_MEMBER` and the rest; `"SAME_AS!"` matches that exact type only.
- **Duplicates are normal.** `seen` resets per step, so a node can appear in several steps or twice within one `LINK_NODE` step (once per incoming link). Deduplicate by `node_id`.
- **`LINK_NODE` counts links, not nodes.** `total_count` and the number of items are link-based, while the `output_count` in verbose step diagnostics counts distinct nodes.
- **Link direction is data.** Symmetric types (`SAME_AS`, `TERM_EQUIVALENT`, ...) are stored in one direction. Use `WITH` when you don't know which.
- **`depth` is clamped.** "Unlimited" and anything above `MAX_DEPTH_HARD` (50) become 50.
- **`seed_count: 0` means the `starting` predicate matched nothing**, usually a name typo or the wrong graph. `total_count: 0` with a positive `seed_count` means the traversal found nothing from valid seeds.
- **`limit` truncates the result set**, and verbose step diagnostics will show `truncated: true`.

---

## Implementation Note — Storage Backend

**Development runtime:** DuckDB (embedded, single-file). Sufficient for graphs up to ~1–5M nodes. Requires `CAST(uuid_col AS VARCHAR)` workarounds due to a zone-map optimizer bug in DuckDB 1.x with UUID columns (see project notes). Seed resolution (`name_contains`) requires full table scans.

**Production target: PostgreSQL.** Recommended for any deployment expected to load large clinical terminologies (SNOMED CT, RxNorm, LOINC). Key capabilities:

| Capability | Benefit for BQL |
|------------|-----------------|
| Native `uuid` type + B-tree index | Eliminates CAST workarounds; O(log n) node lookups |
| `pg_trgm` GIN index on `name` | `name_contains` seed resolution sub-millisecond at 350K+ nodes |
| Table partitioning by `graph_id` | Graph-scoped queries skip all other graph partitions entirely |
| Connection pooling | Concurrent BQL queries execute in parallel |
| `ltree` extension (optional) | O(log n) subtree queries for pure HIERARCHICAL traversal via materialized paths |

**The BQL query engine is storage-agnostic by design.** It calls DAO methods; the DAO layer handles SQL dialect differences (parameter style, UUID handling, index hints). Switching backends requires only a new DAO implementation — BQL semantics, the iterative one-hop loop, the Python accumulator, and all hard caps are unchanged.

**Hard caps (configurable, apply to both backends):**

| Cap | Purpose |
|-----|---------|
| `MAX_SEED_SIZE` (500) | Prevents unbounded fan-out from overly broad `starting` predicates; the query is rejected |
| `MAX_STEP_BUFFER` (5,000) | Truncates runaway intermediate node sets; sets `truncated: true` in verbose diagnostics |
| `MAX_DEPTH_HARD` (50) | Server-side ceiling; "unlimited" in the query maps to this value |

---

## Todo / Future

- **Projection**: a field selection list applied to result nodes, yielding row objects (e.g. `["name", "source_id", "metadata.level"]`)
- **Text overlay**: a parseable SQL-ish surface that compiles to this JSON structure
- **Advanced traversal modes**: minimum spanning subgraph, shortest path between two seeds
- **Step-level `include_seed`**: per-step control (currently query-global)
- **PostgreSQL DAO implementation**: asyncpg + pgBouncer, `ltree` column maintained on node insert/move
- **Impact analysis extensions**: stakeholder-aware filtering and result types. Specifically: (a) a `stakeholders` filter on steps that restricts results to nodes/links associated with a given actor or role; (b) a `format: IMPACT` result type that annotates each result item with the set of stakeholders affected by a change to that node; (c) a reverse-impact query pattern (`direction: TO`, link_types inferred from stakeholder relationship types) that answers "who is affected if this node changes". Implementation deferred pending stakeholder relationship schema definition.

