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
    assert names == {"HIERARCHICAL", "RELATED", "SYNONYM"}


def test_bootstrap_seeds_generic_node_type(db):
    with db.connect() as conn:
        row = conn.execute("SELECT name FROM node_type WHERE name = 'Generic'").fetchone()
    assert row is not None


def test_bootstrap_is_idempotent(db):
    bootstrap(db)  # second run
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM link_type").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM node_type").fetchone()[0] == 1

