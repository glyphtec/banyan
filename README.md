# Banyan

**A governed, auditable, AI-native engine for taxonomies and the crosswalks between them.**

Banyan manages vocabularies, taxonomies and code sets as typed graphs, and treats the *mappings between them* as first-class, reviewable, reversible data. Every change is recorded in a tamper-evident, hash-chained ledger. Humans, pipelines and AI agents all work against the same deterministic substrate, and every one of them leaves receipts.

> Status: working proof of concept, built for a real use case (social-care ↔ clinical-care crosswalks). Apache-2.0.

---

## The problem

Organizations run on controlled vocabularies: clinical code sets, service categories, product hierarchies, org taxonomies, reference data. They are governed by different bodies, on different release cycles, with different shapes. The hard part isn't storing them; it's the **seams**:

- *Which concept here corresponds to which concept there, and who decided that?*
- *If a term is retired or renamed in the next release, what breaks, and who needs to be told?*
- *Can we trust a mapping an AI suggested? Can we undo one a human got wrong?*

Spreadsheets and lookup tables can't answer these. Heavyweight ontology stacks (OWL/RDF triple stores) can, but at a cost most teams can't pay. Banyan sits in the middle: a small, relational, operationally simple engine built specifically for **governed taxonomy and crosswalk management**.

## What makes Banyan different

**1. The crosswalk is the product, not an afterthought.**
Graphs hold concepts; *links can cross graphs*. A mapping between two taxonomies is just a typed link with metadata, so it is versioned, diffable, queryable and auditable like everything else.

**2. Four primitives, perfectly invertible.**
All mutations compose from exactly `ADD_NODE`, `UPDATE_NODE`, `CREATE_LINK` and `DESTROY_LINK`, executed in transactional batches. Because every primitive records its own inverse, **any ledger entry can be undone** and any batch rolls back atomically.

**3. A Git-grade ledger.**
Every mutation across every graph appends to one global, monotonic ledger. Each entry stores actor, forward payload, reversal payload and a SHA-256 hash chained to the previous entry. `GET /api/v1/ledger/verify-chain` re-walks the chain and tells you whether history has been altered.

**4. Human-in-the-loop AI that is honest by construction.**
Agents (via MCP or the built-in chat agent) *propose* mappings as distinct `*_PROPOSED` link types carrying a confidence level, the evidence it rests on, a rationale, and caveats. A reviewer approves, redirects to a better target, or rejects in the Review Panel. Approval is a ledgered, reversible swap. Workflow state lives in the graph, so BQL can query "what's pending" in one step. An agent saying "no good match exists" is a first-class outcome.

**5. Impact analysis before damage.**
Destructive operations can be previewed with a recursive-traversal **ImpactSummary**, the blast radius of a change, and a CODEOWNERS-style **stakeholder** system resolves *who* needs to be consulted for it.

**6. Open vocabulary of relationships.**
Only three root link families are built in: `HIERARCHICAL`, `RELATED`, `SYNONYM`. Everything else (`SAME_AS`, `HAS_MEMBER`, `TERM_SIMILAR`, ...) is added as *data* at runtime, with optional JSON-Schema validation of link metadata. Hierarchical and synonym links stay inside one graph; only `RELATED` families may cross graphs. New relationship semantics never need a schema migration.

**7. One query language for all traversal.**
**BQL** (Banyan Query Language) is a small JSON language of seed predicates plus ordered traversal steps (direction, link families, depth, cross-graph scope). It replaces a sprawl of child/parent/ancestor endpoints, and expresses things like sibling lookup, coverage gaps and crosswalk discovery in a single query.

**8. Dual interface, one engine.**
A conventional **REST** API (FastAPI) for pipelines and apps, and a **Model Context Protocol (MCP)** server (FastMCP) exposing ~35 tools for agents. Same service layer, same ledger, same rules.

**9. Boring, inspectable persistence.**
No ORM. Raw parameter-bound SQL in a DAO layer over **DuckDB** (embedded, zero-ops; the default) with a **PostgreSQL** adapter. Your data is plain tables you can read with any SQL tool.

---

## The flagship demo: social-care ↔ clinical-care crosswalk

When a clinician finds a patient's social need (say, food insecurity) and wants to refer them to a community organization, two independently governed vocabularies have to line up: the clinical **Gravity Project** SDOH standard (SNOMED CT / ICD-10-CM) and a human-services taxonomy such as **Open Eligibility**. No open, versioned, auditable crosswalk connects them.

Banyan's reference application builds one:

| Graph | Role |
|---|---|
| Open Eligibility | Social-service taxonomy (~290 nodes) |
| Gravity SDOH Clinical Care STU 2.3 | Social-risk domains and value-set activities (~217 nodes) |
| SNOMED CT SDOH slice / Service Requests slice | Clinical codes (~590 and ~970 nodes) |
| ICD-10-CM SDOH slice | Z-codes and related (~190 nodes) |

Gravity activities link to clinical codes with `HAS_MEMBER`, and taxonomies are aligned with `SAME_AS` / `TERM_SIMILAR`. An AI agent gathers a structured evidence brief for each Gravity domain (children, member codes, candidate targets), proposes mappings with explicit confidence and rationale, and a human reviews each one. The loop closes, *with receipts*.

See [docs/Social_clinicial_crosswalk_POC.md](docs/Social_clinicial_crosswalk_POC.md) for the full proposal and [docs/CROSSWALK_VIEWER_UX_SPEC.md](docs/CROSSWALK_VIEWER_UX_SPEC.md) for the UX vision.

> **Licensing note:** the clinical terminologies (SNOMED CT, ICD-10-CM, UMLS-derived content) are subject to their own licenses and are **not distributed in this repository**. Ingest scripts under [backend/utils/](backend/utils) fetch and build them locally. Banyan itself is Apache-2.0.

Banyan is general-purpose; the same utilities also ingest MeSH, Dewey, WordNet and others as exercises in different shapes of taxonomy.

---

## How it works

### Core model

| Entity | Notes |
|---|---|
| **Graph** | A named taxonomy. Every graph has a `$ROOT$` node. Optional topology constraints (polyhierarchy, max depth). |
| **Node** | A concept: `source_id` (stable business key), `name`, `notes`, free-form JSON `metadata`, optional node type. |
| **Link** | Typed, directed edge between nodes. Fractional `link_order` for cheap reordering, validity window, `is_disabled`, JSON `metadata`. Cross-graph for `RELATED` families. |
| **Link type** | A hierarchy of relationship meanings with optional metadata schema and symmetry flag. |
| **Ledger entry** | Immutable, hash-chained record of one primitive: actor, verb, forward and reversal payloads. |
| **Snapshot** | A labeled point-in-time export of a graph, restorable and diffable. |
| **Actor** | `HUMAN`, `AGENT` or `SYSTEM`; every mutation is attributed. |
| **Stakeholder** | Parties with `OWNER` / `WATCHER` / `APPROVER` interest in a graph or node, scoped to the node, its subgraph, or its ancestors. |

Graph-level operations: create, clone, import, export, diff, batch, snapshot, restore.

### A BQL taste

Find every Gravity code-set member under a domain, then see which are already covered by a crosswalk:

```json
{
  "graph": { "name": "Gravity SDOH Clinical Care STU 2.3" },
  "starting": { "name_contains": "Food" },
  "steps": [
    { "direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1, "collect": false },
    { "direction": "FROM", "link_types": ["HAS_MEMBER"], "graphs": ["*"], "collect": true }
  ],
  "result": { "format": "LINK_NODE" }
}
```

`POST /api/v1/query`. The full language is specified in [docs/Banyan Project_ BQL Spec.md](<docs/Banyan Project_ BQL Spec.md>).

### Interfaces

| Interface | Endpoint | For |
|---|---|---|
| REST (FastAPI) | `/api/v1/...`, docs at `/docs` | Pipelines, apps, the UI |
| MCP (FastMCP) | `/mcp/` | External agents (Claude Desktop, etc.): graph/node/link CRUD, BQL, impact, snapshots, diff, batch, ledger verification, crosswalk brief + propose tools |
| Chat agent | `/api/v1/agent/chat` | Built-in Claude-powered taxonomist assistant (needs `ANTHROPIC_API_KEY`) with persistent, tiered working memory (`[ALWAYS]` / `[NEVER]` / `[FYI]`) and UI control |
| Web UI | Vite app on :5173 | Tree browsing, node detail, crosswalk review, chat |

### Architecture

```
React UI  ──►  FastAPI REST ─┐
Chat agent ─►  (Claude)      ├─►  BanyanService  ─►  DAOs (raw SQL)  ─►  DuckDB / PostgreSQL
MCP agents ─►  FastMCP ──────┘     (rules, batching,    (graph, node, link, ledger,
                                    BQL, undo)          traversal, snapshot, stakeholder)
```

Layering in [backend/src/banyan_platform/](backend/src/banyan_platform): `persistence/` (DDL, connections) → `dao/` → `services/` → `api/`.

---

## Quick start

Requires Python 3.11+ and Node 18+.

```bash
# Backend
cd backend
pip install -e .[dev]
pytest
python -m uvicorn banyan_platform.main:app --host 0.0.0.0 --port 8000
```

> Do **not** use `--reload`. DuckDB holds an exclusive file lock; a second process will crash.

API at http://localhost:8000, interactive docs at http://localhost:8000/docs, MCP at http://localhost:8000/mcp/.

```bash
# Frontend
cd frontend
npm install
npm start      # http://localhost:5173, proxies /api to the backend
```

Or run the containerized stack with `docker-compose up` (backend on PostgreSQL, plus the frontend).

### Configuration (environment / `backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `BANYAN_DB_DIALECT` | `duckdb` | `duckdb` or `postgres` |
| `BANYAN_DUCKDB_PATH` | `:memory:` | DuckDB file path (set for persistence, e.g. `data/banyan_dev.duckdb`) |
| `BANYAN_POSTGRES_DSN` | — | PostgreSQL connection string |
| `BANYAN_STRICT_ACTORS` | `false` | Reject unregistered actor handles |
| `BANYAN_ADMIN_API` | `false` | Dev-only ad-hoc SQL endpoint. **Never enable in production.** |
| `BANYAN_CORS_ORIGINS` | `http://localhost:5173` | Allowed origins |
| `ANTHROPIC_API_KEY` | — | Enables the chat agent |

### Operations

- DuckDB is periodically checkpointed and closed cleanly on shutdown. `POST /admin/checkpoint` forces a checkpoint (requires `BANYAN_ADMIN_API=true`; `backup_db.py` uses it when the server is running).
- [backend/utils/backup_db.py](backend/utils/backup_db.py) takes a safe backup; [backend/utils/recover_wal.py](backend/utils/recover_wal.py) helps recover after a failed WAL replay.

---

## Project status and TODO

Banyan is a proof of concept, not a hardened product. Please read this before pointing it at anything real. Known gaps, roughly in priority order:

**Security and deployment readiness**
- [ ] **Authentication and authorization.** There is none. Actors are asserted via the `X-Actor-Id` header (and `BANYAN_STRICT_ACTORS` is off by default), so anyone who can reach the API can read and write any graph under any identity. This applies equally to the REST API, the `/mcp/` endpoint and the chat agent. Run it only on a trusted network or behind your own auth proxy until this is fixed.
- [ ] **Agent guardrails are prompt-level only.** The chat agent is instructed to ask before creating links, but the server does not enforce approval. A server-side permission model (e.g. agents may only write `*_PROPOSED` links) is needed.
- [ ] **Chat sessions are in-memory** and lost on restart; only the agent's working memory persists.
- [ ] **Admin endpoints** (`BANYAN_ADMIN_API`) include graph purge and ad-hoc SQL. Dev only. Never enable them in a shared environment.
- [ ] Validate the PostgreSQL adapter and `docker-compose` stack. DuckDB is the primary development and test path.

**Engine**
- [ ] Enforce graph topology constraints (polyhierarchy, max depth). They are modeled in the schema only.
- [ ] Single DuckDB connection: all requests are serialized, and there are no per-request timeouts, so one slow or runaway query stalls the whole server (a cyclic-traversal bug did exactly this and is now fixed; the exposure remains). Needs request timeouts and/or connection pooling (PostgreSQL).
- [ ] Closure table for stakeholder resolution and impact analysis. Traversals are correct at pilot scale but not tuned for large graphs.
- [ ] DuckDB WAL replay can fail after an unclean shutdown. Mitigated by periodic checkpoints and the backup and recovery utilities, but not eliminated.

**Product**
- [ ] Practitioner-facing natural-language query experience (designed, not built). The current UI is a structured inspection and review tool.
- [ ] Repo hygiene: remove the committed `banyan.zip`.

The reference data pipeline depends on externally licensed vocabularies you must obtain yourself.

## Documentation

| Doc | What it covers |
|---|---|
| [BANYAN_SYSTEM_ARCHITECTURE.md](docs/BANYAN_SYSTEM_ARCHITECTURE.md) | Operating constraints, ledger design, stakeholder governance |
| [Banyan_ Entities and Methods.md](<docs/Banyan_ Entities and Methods.md>) | Entity model and verbs |
| [DEMO_WALKTHROUGH.md](docs/DEMO_WALKTHROUGH.md) | A 15-minute guided tour of the crosswalk demo |
| [Banyan Project_ BQL Spec.md](<docs/Banyan Project_ BQL Spec.md>) | BQL language reference and crosswalk cookbook |
| [Social_clinicial_crosswalk_POC.md](docs/Social_clinicial_crosswalk_POC.md) | The flagship crosswalk project |
| [CROSSWALK_VIEWER_UX_SPEC.md](docs/CROSSWALK_VIEWER_UX_SPEC.md) | Viewer and practitioner-query UX |

## License

Apache License 2.0. See [LICENSE](LICENSE). Third-party vocabularies retain their own licenses.

*A Glyphstone Productions project.*
