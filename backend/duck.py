"""
Banyan DuckDB interactive spelunking console.

Usage (from backend/ directory):
    python duck.py

Opens the dev database in READ-ONLY mode so it can run concurrently with
the uvicorn server.  All queries go through `q()`.

Quick-start cheat-sheet
-----------------------
  tables()          -- list all tables
  schema("graph")   -- column info for one table
  q("SELECT ...")   -- run any SQL, returns a pandas-style result
  rows("graph")     -- SELECT * FROM <table> (all rows, pretty-printed)
  counts()          -- row counts for every table
  graph_detail()    -- graphs with their root_node info
  ledger(n=20)      -- last n ledger entries
  nodes(graph_id)   -- all nodes for a graph_id (or None for all)
  links(graph_id)   -- all links touching nodes in a graph
  tree(root_id)     -- recursive subtree from a node_id

Type help() or ? for Python help.  Ctrl+Z / exit() to quit.
"""
import os, sys, textwrap

# Allow running from any cwd; resolve relative to this file's location
_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_DIR, "data", "banyan_dev.duckdb")

try:
    import duckdb
except ImportError:
    sys.exit("duckdb package not found — run: pip install duckdb")

print(f"\n  Banyan spelunker  (duckdb {duckdb.__version__})")
print(f"  DB : {_DB_PATH}")

# Try read-only first (works when no other process holds a write lock).
# On Windows, DuckDB uses exclusive OS-level locks so if uvicorn is running
# against this file you must stop it first, then re-run duck.py.
_conn = None
for _ro in (True, False):
    try:
        _conn = duckdb.connect(_DB_PATH, read_only=_ro)
        _mode = "READ-ONLY" if _ro else "READ-WRITE"
        print(f"  Mode: {_mode}\n")
        break
    except Exception as _e:
        if _ro:
            continue   # try read-write
        # Both modes failed
        print(f"\n  !! Could not open database: {_e}")
        print("  Is uvicorn running against this file?  Stop it with Ctrl+C,")
        print("  then re-run:  python duck.py\n")
        sys.exit(1)


# ── helpers ──────────────────────────────────────────────────────────────────

def q(sql: str):
    """Execute SQL and return a DuckDB Relation (auto-displayed in REPL)."""
    return _conn.execute(sql).fetchdf()


def tables():
    """List all tables in the database."""
    return q("SHOW TABLES")


def schema(table: str):
    """Column details for *table*."""
    return q(f"DESCRIBE {table}")


def rows(table: str, limit: int = 50):
    """All rows from *table* (up to *limit*)."""
    return q(f"SELECT * FROM {table} LIMIT {limit}")


def counts():
    """Row count for every table."""
    tbls = _conn.execute("SHOW TABLES").fetchall()
    parts = [f"SELECT '{t[0]}' AS tbl, COUNT(*) AS n FROM {t[0]}" for t in tbls]
    return q(" UNION ALL ".join(parts) + " ORDER BY tbl")


def graph_detail():
    """Graphs joined to their root node."""
    return q("""
        SELECT g.graph_id, g.name AS graph_name, g.root_node_id,
               n.name AS root_node_name, n.source_id AS root_source_id,
               g.inserted_datetime
        FROM graph g
        LEFT JOIN node n ON n.node_id = g.root_node_id
        ORDER BY g.inserted_datetime
    """)


def ledger(n: int = 20):
    """Last *n* ledger entries."""
    return q(f"""
        SELECT ledger_id, transaction_id, primitive_verb, actor_id,
               graph_id, node_id, inserted_datetime
        FROM banyan_ledger
        ORDER BY ledger_id DESC
        LIMIT {n}
    """)


def nodes(graph_id: str | None = None, limit: int = 100):
    """All nodes, optionally filtered by graph_id."""
    where = f"WHERE graph_id = '{graph_id}'" if graph_id else ""
    return q(f"SELECT * FROM node {where} ORDER BY inserted_datetime LIMIT {limit}")


def links(graph_id: str | None = None, limit: int = 100):
    """Links, optionally filtered to those whose from_node is in *graph_id*."""
    where = f"WHERE from_graph_id = '{graph_id}'" if graph_id else ""
    return q(f"SELECT * FROM link {where} ORDER BY inserted_datetime LIMIT {limit}")


def tree(root_id: str, max_depth: int = 20):
    """Recursive subtree from *root_id* via HIERARCHICAL links."""
    return q(f"""
        WITH RECURSIVE subtree AS (
            SELECT n.node_id, n.name, n.source_id, 0 AS depth
            FROM node n WHERE n.node_id = '{root_id}'
            UNION ALL
            SELECT child.node_id, child.name, child.source_id, s.depth + 1
            FROM link lk
            JOIN subtree s   ON lk.from_node_id = s.node_id
            JOIN node child  ON child.node_id    = lk.to_node_id
            JOIN link_type lt ON lt.link_type_id = lk.link_type_id
            WHERE lt.name = 'HIERARCHICAL' AND s.depth < {max_depth}
        )
        SELECT depth, node_id, source_id, name FROM subtree ORDER BY depth, name
    """)


# ── banner ───────────────────────────────────────────────────────────────────
print(textwrap.dedent("""
  Available helpers:
    tables()               list all tables
    schema("table")        column info
    rows("table")          SELECT * (first 50 rows)
    counts()               row counts per table
    graph_detail()         graphs + root node join
    ledger(n=20)           last n ledger entries
    nodes(graph_id=None)   list nodes
    links(graph_id=None)   list links
    tree(node_id)          recursive subtree via HIERARCHICAL
    q("SELECT ...")        run any SQL

  Results are pandas DataFrames. To see more rows:
    df = graph_detail(); print(df.to_string())
"""))

if __name__ == "__main__":
    import code
    code.interact(local={**globals(), **locals()}, banner="")
