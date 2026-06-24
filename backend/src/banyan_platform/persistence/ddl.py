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

CREATE SEQUENCE IF NOT EXISTS seq_node_type_id  START 1;
CREATE SEQUENCE IF NOT EXISTS seq_link_type_id  START 1;
CREATE SEQUENCE IF NOT EXISTS seq_topology_id   START 1;
CREATE SEQUENCE IF NOT EXISTS seq_ledger_id     START 1;

-- ============================================================================
-- PART 1: LOOKUP / META-ENTITY TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_type (
    node_type_id  INTEGER PRIMARY KEY DEFAULT nextval('seq_node_type_id'),
    name          VARCHAR(100) NOT NULL,
    notes         TEXT,
    CONSTRAINT uq_node_type_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS link_type (
    link_type_id        INTEGER PRIMARY KEY DEFAULT nextval('seq_link_type_id'),
    parent_link_type_id INTEGER REFERENCES link_type(link_type_id),
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

CREATE TABLE IF NOT EXISTS graph_topology (
    topology_id         INTEGER PRIMARY KEY DEFAULT nextval('seq_topology_id'),
    name                VARCHAR(100) NOT NULL,
    notes               TEXT,
    -- Constraint flags.  Enforcement lives in the service layer.
    allow_polyhierarchy BOOLEAN NOT NULL DEFAULT TRUE,
    max_depth           INTEGER,                 -- NULL = unconstrained
    CONSTRAINT uq_topology_name UNIQUE (name)
);

-- ============================================================================
-- PART 2: OPERATIONAL TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS graph (
    graph_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(200) NOT NULL,
    notes             TEXT,
    topology_id       INTEGER REFERENCES graph_topology(topology_id),
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
    node_type_id      INTEGER NOT NULL REFERENCES node_type(node_type_id),
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
    link_type_id         INTEGER NOT NULL REFERENCES link_type(link_type_id),
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
-- V1: plain audit log with undo capability.  No cryptographic chain.
-- ============================================================================

CREATE TABLE IF NOT EXISTS banyan_ledger (
    ledger_id         BIGINT PRIMARY KEY DEFAULT nextval('seq_ledger_id'),
    transaction_id    UUID NOT NULL,             -- Groups primitives belonging to one logical operation
    actor_id          VARCHAR(200) NOT NULL,     -- Authenticated user or system process identifier
    -- Primitive verbs:
    --   ADD_NODE | UPDATE_NODE | DELETE_NODE | CREATE_LINK | UPDATE_LINK | DESTROY_LINK
    primitive_verb    VARCHAR(50) NOT NULL,
    source_graph_id   UUID NOT NULL,                    -- Graph context; no FK so the ledger survives graph deletion
    target_graph_id   UUID,                             -- Populated for cross-graph link operations
    entity_id         UUID NOT NULL,             -- The Node UUID or Link UUID acted upon
    payload           JSON NOT NULL,             -- Forward mutation delta (state after)
    reversal_payload  JSON NOT NULL,             -- Full prior state required to invert this entry (UNDO)
    reverses_ledger_id BIGINT REFERENCES banyan_ledger(ledger_id), -- Back-pointer set when this entry is a compensating UNDO
    inserted_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
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
"""

# Idempotent seed data for lookup tables.
# Uses ON CONFLICT DO NOTHING so it is safe to run on every startup.
#
# Link type families (no parent):
#   HIERARCHICAL  — parent/child structural links; must stay within a single graph
#   RELATED       — associative links; may cross graph boundaries
#   SYNONYM       — equivalence links; must stay within a single graph
#
# Node type:
#   Generic       — placeholder until domain-specific types are defined

BANYAN_SEED_DML = """
INSERT INTO link_type (name, notes) VALUES
    ('HIERARCHICAL', 'Parent-child structural relationships. Must remain within a single graph.'),
    ('RELATED',      'Associative relationships. May cross graph boundaries.'),
    ('SYNONYM',      'Equivalence relationships. Must remain within a single graph.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO node_type (name, notes) VALUES
    ('Generic', 'General-purpose node type. Refine with domain-specific types as needed.')
ON CONFLICT (name) DO NOTHING;
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
    """
    with db.connect() as conn:
        for stmt in _split_statements(BANYAN_DDL):
            conn.execute(stmt)
        for stmt in _split_statements(BANYAN_SEED_DML):
            conn.execute(stmt)

