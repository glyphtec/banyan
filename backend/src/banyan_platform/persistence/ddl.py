# Canonical Banyan DDL.
#
# DuckDB-primary. Also compatible with PostgreSQL 13+.
#
# PostgreSQL note: consider swapping JSON → JSONB on metadata/payload columns
# to enable GIN indexing when query patterns require it.
#
# Cross-graph constraint: HIERARCHICAL and SYNONYM link types must have
# from_graph_id = to_graph_id.  This is enforced in the service layer, not here.

BANYAN_DDL = """
-- ============================================================================
-- SEQUENCES for integer primary keys
-- (DuckDB does not support GENERATED ALWAYS AS IDENTITY or SERIAL)
-- PostgreSQL also supports CREATE SEQUENCE IF NOT EXISTS / nextval().
-- ============================================================================

CREATE SEQUENCE IF NOT EXISTS seq_ledger_id     START 1;

-- ============================================================================
-- PART 1: LOOKUP / META-ENTITY TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_type (
    node_type_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL,
    notes         TEXT,
    CONSTRAINT uq_node_type_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS link_type (
    link_type_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_link_type_id UUID REFERENCES link_type(link_type_id),
    name                VARCHAR(100) NOT NULL,
    notes               TEXT,
    -- Optional JSON Schema document constraining the metadata attribute on
    -- links of this type.  NULL means no schema enforcement.
    metadata_schema     JSON,
    inserted_datetime   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_datetime    TIMESTAMPTZ,
    updated_by          VARCHAR(200),
    CONSTRAINT uq_link_type_name UNIQUE (name)
);

-- Add is_symmetric column if not present (idempotent migration).
ALTER TABLE link_type ADD COLUMN IF NOT EXISTS is_symmetric BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS graph_topology (
    topology_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(100) NOT NULL,
    notes               TEXT,
    -- Constraint flags.  Enforcement lives in the service layer.
    allow_polyhierarchy BOOLEAN NOT NULL DEFAULT TRUE,
    max_depth           INTEGER,                 -- NULL = unconstrained
    CONSTRAINT uq_topology_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS banyan_actor (
    -- Identity primitive for all attribution columns (actor_id / updated_by).
    -- Stakeholder governance relationships reference this table via actor_id.
    actor_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    handle        VARCHAR(200) NOT NULL,         -- Stable string used in actor_id / updated_by columns
    display_name  VARCHAR(200) NOT NULL,
    actor_type    VARCHAR(20)  NOT NULL,         -- SYSTEM | HUMAN | AGENT
    org           VARCHAR(200),
    notes         TEXT,
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_actor_handle UNIQUE (handle)
);

-- ============================================================================
-- PART 2: OPERATIONAL TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS graph (
    graph_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(200) NOT NULL,
    notes             TEXT,
    topology_id       UUID REFERENCES graph_topology(topology_id),
    root_node_id      UUID,                      -- Back-populated after root node creation
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_datetime  TIMESTAMPTZ,
    updated_by        VARCHAR(200),
    CONSTRAINT uq_graph_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS node (
    node_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NOTE: graph_id carries no FK constraint.
    -- DuckDB fires FK violations on UPDATE of the referenced table even when
    -- the PK column is unchanged (known DuckDB limitation — same category as
    -- from_node_id / to_node_id on the link table).
    -- Referential integrity is enforced in the service layer.
    graph_id          UUID NOT NULL,
    node_type_id      UUID NOT NULL REFERENCES node_type(node_type_id),
    source_id         VARCHAR(200) NOT NULL,     -- External business key / SKU / code
    name              VARCHAR(200) NOT NULL,
    notes             TEXT,
    metadata          JSON NOT NULL DEFAULT '{}',
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_datetime  TIMESTAMPTZ,
    updated_by        VARCHAR(200),
    CONSTRAINT uq_node_source UNIQUE (graph_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_node_graph ON node(graph_id);

CREATE TABLE IF NOT EXISTS link (
    link_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    link_type_id         UUID NOT NULL REFERENCES link_type(link_type_id),
    -- NOTE: from_graph_id / to_graph_id carry no FK constraints.
    -- DuckDB fires FK violations on UPDATE of the referenced table even when
    -- the PK column is unchanged.  Service layer enforces graph existence.
    from_graph_id        UUID NOT NULL,
    to_graph_id          UUID NOT NULL,
    -- NOTE: from_node_id / to_node_id intentionally carry no FK constraints.
    -- DuckDB does not honour intra-transaction FK visibility (known limitation),
    -- which would block deleting a node after its links are deleted in the same
    -- transaction.  Referential integrity for these columns is enforced in the
    -- service layer (pre-flight checks, ordered deletes).
    from_node_id         UUID NOT NULL,
    to_node_id           UUID NOT NULL,
    link_order           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    metadata             JSON NOT NULL DEFAULT '{}',
    valid_from_datetime  TIMESTAMPTZ,
    valid_until_datetime TIMESTAMPTZ,
    is_disabled          BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_datetime    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_datetime     TIMESTAMPTZ,
    updated_by           VARCHAR(200)
);

CREATE INDEX IF NOT EXISTS idx_link_traversal   ON link(from_graph_id, from_node_id, to_node_id);
CREATE INDEX IF NOT EXISTS idx_link_cross_graph ON link(to_node_id);

-- ============================================================================
-- PART 3: AUDIT LEDGER & SNAPSHOTS
-- V1.1: append-only ledger with global SHA-256 hash chain.
-- Each entry hashes its own content plus the previous entry's hash, forming
-- a tamper-evident chain verifiable by any party holding the ledger.
-- ============================================================================

CREATE TABLE IF NOT EXISTS banyan_ledger (
    ledger_id         BIGINT PRIMARY KEY DEFAULT nextval('seq_ledger_id'),
    transaction_id    UUID NOT NULL,             -- Groups primitives belonging to one logical operation
    actor_id          VARCHAR(200) NOT NULL,     -- Actor handle; references banyan_actor.handle (service-validated in strict mode)
    -- Primitive verbs for nodes/links:
    --   ADD_NODE | UPDATE_NODE | DELETE_NODE | CREATE_LINK | UPDATE_LINK | DESTROY_LINK
    -- Primitive verbs for meta/definitional objects (system-scope):
    --   CREATE_NODE_TYPE | UPDATE_NODE_TYPE | DELETE_NODE_TYPE
    --   CREATE_LINK_TYPE | UPDATE_LINK_TYPE | DELETE_LINK_TYPE
    --   CREATE_TOPOLOGY  | UPDATE_TOPOLOGY  | DELETE_TOPOLOGY
    --   CREATE_ACTOR     | UPDATE_ACTOR     | DELETE_ACTOR
    primitive_verb    VARCHAR(50) NOT NULL,
    -- source_graph_id: graph context for node/link operations.
    -- NULL for system-scope definitional object mutations (node_type, link_type,
    -- graph_topology, stakeholder).  Use the __system__ sentinel graph
    -- (ba0ba000-0000-0000-0000-000000000000) when a non-null value is required.
    source_graph_id   UUID,                             -- Graph context; no FK so the ledger survives graph deletion
    target_graph_id   UUID,                             -- Populated for cross-graph link operations
    entity_id         UUID NOT NULL,             -- The Node UUID, Link UUID, or meta-object UUID acted upon
    payload           JSON NOT NULL,             -- Forward mutation delta (state after)
    reversal_payload  JSON NOT NULL,             -- Full prior state required to invert this entry (UNDO)
    reverses_ledger_id BIGINT REFERENCES banyan_ledger(ledger_id), -- Back-pointer set when this entry is a compensating UNDO
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Global hash chain.  previous_hash = entry_hash of ledger_id-1; genesis sentinel = 64 zeros.
    previous_hash     VARCHAR(64)  NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
    entry_hash        VARCHAR(64)  NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000'
);

CREATE INDEX IF NOT EXISTS idx_ledger_graph_time  ON banyan_ledger(source_graph_id, inserted_datetime);
CREATE INDEX IF NOT EXISTS idx_ledger_transaction ON banyan_ledger(transaction_id);

CREATE TABLE IF NOT EXISTS graph_snapshot (
    snapshot_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_id          UUID NOT NULL REFERENCES graph(graph_id),
    version_label     VARCHAR(100) NOT NULL,     -- e.g. 'v1.4-production', 'pre-merge-review'
    ledger_id         BIGINT NOT NULL REFERENCES banyan_ledger(ledger_id),  -- Exact ledger timeline pin
    actor_id          VARCHAR(200) NOT NULL,
    notes             TEXT,
    -- snapshot_payload: full serialized graph state at this ledger position.
    -- Structure: { "banyan_export_version": "1.0", "graph": {...},
    --              "nodes": [...], "links": [...], "cross_graph_links": [...] }
    snapshot_payload  JSON NOT NULL DEFAULT '{}',
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_snapshot_version UNIQUE (graph_id, version_label)
);

-- ============================================================================
-- PART 4: STAKEHOLDER REGISTRY
-- Tracks which humans / orgs have governance interest in graphs and nodes.
-- V1 uses on-demand CTE traversal for reverse resolution (no closure table).
-- ============================================================================

CREATE TABLE IF NOT EXISTS stakeholder (
    stakeholder_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(200) NOT NULL,
    org               VARCHAR(200),
    contact_ref       VARCHAR(500),              -- Opaque: email, URL, Slack handle, etc.
    actor_id          UUID,                      -- Loose link to banyan_actor; no FK enforced
    notes             TEXT,
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_datetime  TIMESTAMPTZ,
    CONSTRAINT uq_stakeholder_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS graph_stakeholder (
    -- Attaches a stakeholder to an entire graph.
    graph_id          UUID NOT NULL REFERENCES graph(graph_id),
    stakeholder_id    UUID NOT NULL REFERENCES stakeholder(stakeholder_id),
    role              VARCHAR(50) NOT NULL,      -- OWNER | WATCHER | APPROVER
    notes             TEXT,
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (graph_id, stakeholder_id)
);

CREATE TABLE IF NOT EXISTS node_stakeholder (
    -- Attaches a stakeholder to a node with a configurable scope.
    node_id           UUID NOT NULL,             -- No FK: node may be in any graph
    stakeholder_id    UUID NOT NULL REFERENCES stakeholder(stakeholder_id),
    role              VARCHAR(50) NOT NULL,      -- OWNER | WATCHER | APPROVER
    -- Scope determines how far the interest radiates from the attachment point:
    --   NODE_ONLY  — only the exact node
    --   SUBGRAPH   — the node and all its descendants (via HIERARCHICAL links)
    --   ANCESTORS  — the node and all its ancestors  (via HIERARCHICAL links)
    scope             VARCHAR(20) NOT NULL DEFAULT 'NODE_ONLY',
    scope_depth       INTEGER,                   -- NULL = unlimited; bounded traversal (V1.1)
    scope_link_type_id UUID REFERENCES link_type(link_type_id),  -- NULL = HIERARCHICAL only
    notes             TEXT,
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (node_id, stakeholder_id)
);

-- ============================================================================
-- PART 5: AGENT WORKING MEMORY
-- Persistent cross-session notes stored by the Banyan agent.
-- Injected into the agent system prompt on every request so learned
-- shorthands, user preferences, and workflow conventions survive restarts.
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_memory (
    memory_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    category    VARCHAR(50)  NOT NULL DEFAULT 'general',  -- shorthand | preference | workflow | fact | general
    key         VARCHAR(200) NOT NULL,                    -- stable human-readable identifier; unique
    content     TEXT         NOT NULL,                    -- 1-3 sentence note
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_memory_key UNIQUE (key)
);
"""

# Idempotent seed data for lookup tables.
# Uses ON CONFLICT DO NOTHING so it is safe to run on every startup.
#
# All system-seeded objects use well-known UUIDs with the prefix ba0ba000-
# so they are visually identifiable in query output and referenceable as
# application-layer constants without a lookup query.
#
# Address space:
#   ba0ba000-0000-0000-0000-000000000000   __system__ sentinel graph
#   ba0ba000-0000-0000-0000-0000000000xx   link_type root families  (001–009)
#   ba0ba000-0000-0000-0000-0000000000xx   link_type sub-types      (011–099)
#   ba0ba000-0000-0000-0000-0000000001xx   node_type seeds          (101–199)
#   ba0ba000-0000-0000-0001-0000000000xx   banyan_actor seeds       (001–099)
#
# Link type root families (parent_link_type_id IS NULL):
#   HIERARCHICAL  (001) — parent/child structural; must stay within a single graph
#   RELATED       (002) — associative; may cross graph boundaries
#   SYNONYM       (003) — equivalence; must stay within a single graph
#
# RELATED sub-types:
#   SAME_AS         (011) — cross-graph editorial equivalence (crosswalk product);
#                           link_provenance='asserted' in metadata
#   TERM_EQUIVALENT (012) — intra-graph structural duplicate; same concept appearing
#                           under multiple browse paths due to source taxonomy
#                           constraints (e.g. OE single-parent limitation);
#                           link_provenance='auto' when machine-detected by name match
#   TERM_SIMILAR    (013) — overlapping but not identical scope; use when
#                           TERM_EQUIVALENT overstates certainty; add scope note
#                           in link metadata
#   TERM_VARIANT    (014) — same label, definitionally distinct concepts; use when
#                           source reuses a term name for genuinely different meanings
#   HAS_MEMBER      (015) — cross-graph membership assertion; Gravity L2 activity
#                           node → clinical code node (SNOMED / ICD-10-CM);
#                           link_provenance='derived' when sourced from VSAC expansions
#   SAME_AS_PROPOSED (016) — provisional SAME_AS candidate generated by the MCP
#                           agent, pending editorial review. Distinct link type (not
#                           metadata) so BQL can filter or combine with SAME_AS in a
#                           single step. Resolved by: DESTROY + CREATE SAME_AS/
#                           TERM_SIMILAR on acceptance, or DESTROY alone on rejection.
#
# Node type seeds:
#   Generic (101) — placeholder until domain-specific types are defined

BANYAN_SEED_DML = """
INSERT INTO link_type (link_type_id, name, notes) VALUES
    ('ba0ba000-0000-0000-0000-000000000001', 'HIERARCHICAL', 'Parent-child structural relationships. Must remain within a single graph.'),
    ('ba0ba000-0000-0000-0000-000000000002', 'RELATED',      'Associative relationships. May cross graph boundaries.'),
    ('ba0ba000-0000-0000-0000-000000000003', 'SYNONYM',      'Equivalence relationships. Must remain within a single graph.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO link_type (link_type_id, parent_link_type_id, name, notes) VALUES
    ('ba0ba000-0000-0000-0000-000000000011', 'ba0ba000-0000-0000-0000-000000000002',
     'SAME_AS',
     'Cross-graph editorial equivalence assertion. Links a node in one taxonomy to its counterpart in another (e.g. OE to Gravity). Set link_provenance=''asserted'' in metadata.'),
    ('ba0ba000-0000-0000-0000-000000000012', 'ba0ba000-0000-0000-0000-000000000002',
     'TERM_EQUIVALENT',
     'Intra-graph structural duplicate. Same concept appearing under multiple browse paths due to source taxonomy constraints (e.g. OE single-parent limitation). Set link_provenance=''auto'' when machine-detected by name match.'),
    ('ba0ba000-0000-0000-0000-000000000013', 'ba0ba000-0000-0000-0000-000000000002',
     'TERM_SIMILAR',
     'Overlapping but not identical scope. Use when TERM_EQUIVALENT overstates certainty. Add a scope note in link metadata to describe the variance.'),
    ('ba0ba000-0000-0000-0000-000000000014', 'ba0ba000-0000-0000-0000-000000000002',
     'TERM_VARIANT',
     'Same label, definitionally distinct concepts. Use when a source reuses a term name for genuinely different meanings.'),
    ('ba0ba000-0000-0000-0000-000000000015', 'ba0ba000-0000-0000-0000-000000000002',
     'HAS_MEMBER',
     'Cross-graph membership assertion. Links a Gravity value-set activity node (source) to a clinical code node in a terminology graph (target). Indicates the code is a member of the Gravity value set. Set link_provenance=''derived'' when generated from VSAC expansion data.'),
    ('ba0ba000-0000-0000-0000-000000000016', 'ba0ba000-0000-0000-0000-000000000002',
     'SAME_AS_PROPOSED',
     'Provisional SAME_AS candidate generated by the MCP agent, pending editorial review. Encodes workflow state as a link type (rather than metadata) so BQL can filter or combine with SAME_AS in a single step. Resolved by DESTROY + CREATE SAME_AS/TERM_SIMILAR on acceptance, or DESTROY alone on rejection. Set link_provenance=''proposed'' and include agent_rationale in metadata.'),
    ('ba0ba000-0000-0000-0000-000000000017', 'ba0ba000-0000-0000-0000-000000000002',
     'TERM_EQUIVALENT_PROPOSED',
     'Provisional TERM_EQUIVALENT candidate generated by the MCP agent, pending editorial review. Used for asserting intra-graph structural duplicates (e.g. OE polyhierarchy) before human confirmation. Follows the same propose/approve workflow as SAME_AS_PROPOSED: DESTROY + CREATE TERM_EQUIVALENT on acceptance, DESTROY alone on rejection. Set link_provenance=''proposed'' and include agent_rationale in metadata.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO node_type (node_type_id, name, notes) VALUES
    ('ba0ba000-0000-0000-0000-000000000101', 'Generic', 'General-purpose node type. Refine with domain-specific types as needed.')
ON CONFLICT (name) DO NOTHING;

-- Sentinel graph for system-scope ledger entries.
-- Meta-object mutations (node_type, link_type, graph_topology, stakeholder) set
-- source_graph_id to this well-known UUID rather than NULL.
INSERT INTO graph (graph_id, name, notes, updated_by)
VALUES (
    'ba0ba000-0000-0000-0000-000000000000',
    '__system__',
    'Sentinel graph for system-scope ledger entries (node_type, link_type, graph_topology, actor mutations). Not a real graph.',
    'system:bootstrap'
)
ON CONFLICT (name) DO NOTHING;

-- Well-known system actors.  Handles must match the strings used in actor_id /
-- updated_by columns throughout the codebase and seed DML.
INSERT INTO banyan_actor (actor_id, handle, display_name, actor_type, notes) VALUES
    ('ba0ba000-0000-0000-0001-000000000001', 'system:bootstrap',  'System Bootstrap',   'SYSTEM', 'Seed and schema initialisation operations.'),
    ('ba0ba000-0000-0000-0001-000000000002', 'system:ingest',     'Automated Ingest',   'SYSTEM', 'Batch data ingest pipelines.'),
    ('ba0ba000-0000-0000-0001-000000000003', 'system:mcp-agent',  'MCP Agent',          'AGENT',  'LLM agent operations via the MCP interface.'),
    ('ba0ba000-0000-0000-0001-000000000004', 'anonymous',         'Anonymous',          'HUMAN',  'Unauthenticated or unidentified human actor.')
ON CONFLICT (handle) DO NOTHING;

-- Set is_symmetric flag for link types where directionality carries no meaning.
-- Idempotent: UPDATE is safe to re-run.
UPDATE link_type SET is_symmetric = TRUE
WHERE name IN ('SAME_AS', 'SAME_AS_PROPOSED', 'TERM_EQUIVALENT', 'TERM_EQUIVALENT_PROPOSED', 'TERM_SIMILAR', 'TERM_VARIANT');

-- Remove reverse-direction duplicates for symmetric link types.
-- (Handled in bootstrap() as a direct Python call to avoid _split_statements issues.)

-- (Same-direction dedup and unique index also handled in bootstrap() directly.)

-- Baseline agent memory entries.  These encode non-overridable conventions so
-- they survive a full memory wipe and re-appear on every bootstrap.
INSERT INTO agent_memory (memory_id, category, key, content, created_at, updated_at) VALUES
    (gen_random_uuid(), 'general', 'meta:memory-tier-convention',
     '[ALWAYS] All memory entries must begin with a tier prefix: [ALWAYS] = mandatory no agent discretion | [NEVER] = hard prohibition no agent discretion | [FYI] = reference/guidance agent may use judgment. No exceptions.',
     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    (gen_random_uuid(), 'general', 'meta:memory-tier-enforcement',
     '[ALWAYS] When creating or updating any memory entry, always apply the correct tier prefix ([ALWAYS], [NEVER], or [FYI]) as the first token in the content field. Prose-only entries without a tier prefix are non-compliant and must be corrected.',
     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    (gen_random_uuid(), 'general', 'meta:bql-limit-override',
     '[NEVER] Override or increase the banyan_query result limit without an explicit operator instruction in the current message. The default cap exists to protect context size - autonomous increases are not permitted.',
     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (key) DO NOTHING;
"""


def _split_statements(sql: str) -> list[str]:
    """
    Split a DDL/DML string into individual executable statements.

    Rules:
    - Split on ';' only when it appears in the SQL portion of a line
      (i.e. before any '--' comment on that line).
    - Skip fragments that contain no real SQL (comment-only or blank).
    """
    result: list[str] = []
    current: list[str] = []

    for line in sql.splitlines():
        # Determine where the comment starts on this line (if at all)
        comment_idx = line.find("--")
        sql_part = line[:comment_idx] if comment_idx >= 0 else line

        if ";" in sql_part:
            before, _, after = sql_part.partition(";")
            current.append(before)
            stmt = "\n".join(current).strip()
            if _has_real_sql(stmt):
                result.append(stmt)
            current = [after] if after.strip() else []
        else:
            current.append(line)

    # Flush any trailing content without a terminating semicolon
    if current:
        stmt = "\n".join(current).strip()
        if _has_real_sql(stmt):
            result.append(stmt)

    return result


def _has_real_sql(stmt: str) -> bool:
    """Return True if *stmt* contains at least one non-blank, non-comment line."""
    return any(
        ln.strip() and not ln.strip().startswith("--")
        for ln in stmt.splitlines()
    )


def bootstrap(db) -> None:
    """
    Run BANYAN_DDL then BANYAN_SEED_DML against *db*.

    All DDL uses CREATE TABLE/INDEX IF NOT EXISTS and all seed DML uses
    ON CONFLICT DO NOTHING, so this is safe to call on every startup.

    The dedup logic (removing historical duplicate links) was a one-time
    cleanup operation.  Use utils/dedup_links.py if duplicates ever need
    to be removed manually.  The unique index (uq_link_endpoints) and
    create_link's pre-flight check together prevent new duplicates from
    being created, so the dedup phase is not needed here.
    """
    with db.connect() as conn:
        for stmt in _split_statements(BANYAN_DDL):
            conn.execute(stmt)

    with db.connect() as conn:
        for stmt in _split_statements(BANYAN_SEED_DML):
            conn.execute(stmt)

