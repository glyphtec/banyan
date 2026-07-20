from banyan_platform.persistence.ddl import bootstrap


def test_bootstrap_creates_core_tables(db):
    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    for table in ("graph", "node", "link", "banyan_ledger",
                  "graph_snapshot", "node_type", "link_type"):
        assert table in names, f"Missing table: {table}"


def test_bootstrap_seeds_link_type_families(db):
    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM link_type").fetchall()}
    # Root families
    assert {"HIERARCHICAL", "RELATED", "SYNONYM"}.issubset(names)
    # RELATED sub-types added for crosswalk use
    assert {"SAME_AS", "TERM_EQUIVALENT", "TERM_SIMILAR", "TERM_VARIANT"}.issubset(names)


def test_bootstrap_seeds_generic_node_type(db):
    with db.connect() as conn:
        row = conn.execute("SELECT name FROM node_type WHERE name = 'Generic'").fetchone()
    assert row is not None


def test_bootstrap_is_idempotent(db):
    bootstrap(db)  # second run
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM link_type").fetchone()[0] == 11
        assert conn.execute("SELECT COUNT(*) FROM node_type").fetchone()[0] == 1


def test_banyan_ledger_has_hash_chain_columns(db):
    """banyan_ledger must expose previous_hash and entry_hash columns."""
    with db.connect() as conn:
        cols = {r[0] for r in conn.execute("DESCRIBE banyan_ledger").fetchall()}
    assert "previous_hash" in cols
    assert "entry_hash" in cols


def test_banyan_actor_table_exists_and_is_seeded(db):
    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        assert "banyan_actor" in names
        handles = {r[0] for r in conn.execute("SELECT handle FROM banyan_actor").fetchall()}
    assert {"system:bootstrap", "system:ingest", "system:mcp-agent", "anonymous"}.issubset(handles)


def test_bootstrap_is_idempotent_with_actors(db):
    from banyan_platform.persistence.ddl import bootstrap
    bootstrap(db)  # second run
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM banyan_actor").fetchone()[0] == 4

