# Banyan: AI-Native Cryptographic Master Data Engine
### Core Architectural Reference Document for AI Engineering Agents

---

## 1. Executive System Overview
Banyan is an enterprise-grade, high-performance, AI-native master data and taxonomy orchestration system developed under the **Glyphstone Productions** banner. 

Unlike traditional metadata applications that rely on complex Object-Relational Mappers (ORMs) or isolated database silos, Banyan enforces an **un-abstracted, database-first paradigm**. It isolates relational logic inside highly optimized, raw parameter-bound SQL Data Access Objects (DAOs). 

The system treats taxonomies, corporate categories, alignments, and cross-walks as a unified network matrix. It is optimized to expose a flawless, real-time presentation layer simultaneously to standard automated software pipelines via a **FastAPI REST interface** and to autonomous agentic workflows via the **Model Context Protocol (MCP) using FastMCP**.

---

## 2. Core Operational Constraints & Physics

Every component built inside this codebase must rigorously conform to these four core architectural boundaries:

1. **Absolute State Mutating Symmetry:** Every complex data manipulation must be composed of a transactional batch of exactly four atomic, perfectly invertible primitives: `ADD_NODE`, `UPDATE_NODE`, `CREATE_LINK`, and `DESTROY_LINK`. 
2. **The Universal Ledger Rule:** All mutations—regardless of graph context—must append to a single, system-wide, monotonically increasing universal ledger.
3. **Git-Grade Cryptographic Lineage:** The universal ledger table forms an unbroken cryptographic chain. Every ledger entry must calculate a SHA-256 hash derived from its local transaction data combined with the hash of the immediately preceding row.
4. **Intrinsic Situational Awareness:** No destructive action (like updating a source code or dropping an entity) may execute blindly. The system must process pre-flight classical graph traversal queries (Recursive CTEs) to compile a structured blast radius report (`ImpactSummary`) before committing anything to the ledger.

---

## 3. The Universal Database Blueprint (DDL Schema)

The core relational database model utilizes four primary operational quarks and two immutable historical components. This schema is fully compatible with **PostgreSQL** and local **DuckDB** file instances.

```sql
-- ============================================================================
-- PART 1: LIVE OPERATIONAL STATE TABLES
-- ============================================================================

CREATE TABLE graph (
    graph_id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    root_node_id UUID, -- Back-reference populated after root node instantiation
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE node_type (
    node_type_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE -- e.g., 'Concept', 'Category', 'Term'
);

CREATE TABLE node (
    node_id UUID PRIMARY KEY,
    graph_id UUID NOT NULL REFERENCES graph(graph_id),
    node_type_id INT NOT NULL REFERENCES node_type(node_type_id),
    source_id VARCHAR(255) NOT NULL, -- The external systems business key/SKU/Code
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_node_uniq_source ON node(graph_id, source_id);

CREATE TABLE link_type (
    link_type_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE -- e.g., 'PARENT_OF', 'RELATED_TERM', 'SAME_AS'
);

CREATE TABLE link (
    link_id UUID PRIMARY KEY,
    graph_id UUID NOT NULL REFERENCES graph(graph_id), -- Evaluated as from_graph_id for cross-walks
    link_type_id INT NOT NULL REFERENCES link_type(link_type_id),
    from_node_id UUID NOT NULL REFERENCES node(node_id),
    to_node_id UUID NOT NULL REFERENCES node(node_id),
    link_order DOUBLE PRECISION NOT NULL DEFAULT 0.0, -- Enforces dense sequence positioning
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_link_traversal ON link(graph_id, from_node_id, to_node_id);
CREATE INDEX idx_link_cross_graph ON link(to_node_id); -- Blistering universal cross-walk lookups

-- ============================================================================
-- PART 2: IMMUTABLE LINEAGE & GOVERNANCE TABLES
-- ============================================================================

CREATE TABLE banyan_universe_ledger (
    global_sequence_id BIGSERIAL PRIMARY KEY,
    transaction_id UUID NOT NULL,             -- Groups atomic primitives executing together
    actor_id VARCHAR(200) NOT NULL,           -- Direct user or system intent identifier
    primitive_verb VARCHAR(50) NOT NULL,      -- 'ADD_NODE', 'UPDATE_NODE', 'CREATE_LINK', 'DESTROY_LINK', 'RESTORE_GRAPH'
    source_graph_id UUID NOT NULL REFERENCES graph(graph_id),
    target_graph_id UUID REFERENCES graph(graph_id), -- Populated strictly for cross-graph linkages
    entity_id UUID NOT NULL,                  -- The specific Node UUID or Link UUID acted upon
    payload JSONB NOT NULL,                   -- The exact forward mutation delta
    reversal_payload JSONB NOT NULL,          -- CRITICAL: Full context state required to perfectly invert this primitive
    reverses_ledger_id BIGINT,                -- Points back to original ledger entry if this log was born from an UNDO
    current_hash CHAR(64) NOT NULL,           -- SHA-256 of previous_hash + verb + serialized payloads
    previous_hash CHAR(64) NOT NULL,          -- Chain link tracking the state of the entire universe
    inserted_datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ledger_audit_trail ON banyan_universe_ledger(source_graph_id, target_graph_id, inserted_datetime);

CREATE TABLE graph_snapshot (
    snapshot_id UUID PRIMARY KEY,
    graph_id UUID NOT NULL REFERENCES graph(graph_id),
    version_label VARCHAR(100) NOT NULL,      -- User or pipeline milestone reference (e.g., 'v1.4-production')
    ledger_id BIGINT NOT NULL REFERENCES banyan_universe_ledger(global_sequence_id), -- Exact ledger timeline pin
    actor_id VARCHAR(200) NOT NULL,
    snapshot_metadata JSONB DEFAULT '{}'::jsonb,
    inserted_datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_snapshot_version ON graph_snapshot(graph_id, version_label);