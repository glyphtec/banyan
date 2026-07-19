"""
One-shot script to remove duplicate links from the Banyan DuckDB file.
Run while the server is stopped:  python utils/dedup_links.py

Uses the drop-indexes → delete → recreate pattern to work around a DuckDB
bug where DELETE on a table with ART indexes raises "Failed to delete all
rows from index" when many rows share the same indexed column value.
"""
import duckdb, sys

DB_PATH = "data/banyan_dev.duckdb"

conn = duckdb.connect(DB_PATH)

# Count duplicates before
before = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT from_node_id, to_node_id, link_type_id
        FROM link
        GROUP BY from_node_id, to_node_id, link_type_id
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]
print(f"Duplicate endpoint groups before: {before}")

if before == 0:
    print("No duplicates found — nothing to do.")
    conn.close()
    sys.exit(0)

# Materialise the keep-set in Python
keep = {r[0] for r in conn.execute("""
    SELECT MIN(CAST(link_id AS VARCHAR))
    FROM link
    GROUP BY
        CAST(from_node_id AS VARCHAR),
        CAST(to_node_id   AS VARCHAR),
        CAST(link_type_id AS VARCHAR)
""").fetchall()}

to_delete = [r[0] for r in conn.execute(
    "SELECT CAST(link_id AS VARCHAR) FROM link"
).fetchall() if r[0] not in keep]

print(f"Rows to delete: {len(to_delete)}")

# Drop all indexes on the link table first (DuckDB bug workaround)
print("Dropping link table indexes...")
for idx in ("idx_link_traversal", "idx_link_cross_graph", "uq_link_endpoints"):
    try:
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    except Exception as e:
        print(f"  Warning dropping {idx}: {e}")
conn.commit()

# Now delete without indexes present
print("Deleting duplicates...")
ph = ", ".join(["?" for _ in to_delete])
conn.execute(
    f"DELETE FROM link WHERE CAST(link_id AS VARCHAR) IN ({ph})",
    to_delete,
)
conn.commit()

# Recreate indexes
print("Recreating indexes...")
conn.execute("CREATE INDEX IF NOT EXISTS idx_link_traversal   ON link(from_graph_id, from_node_id, to_node_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_link_cross_graph ON link(to_node_id)")
conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_link_endpoints ON link(from_node_id, to_node_id, link_type_id)")
conn.commit()

after = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT from_node_id, to_node_id, link_type_id
        FROM link
        GROUP BY from_node_id, to_node_id, link_type_id
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]
print(f"Duplicate endpoint groups after: {after}")

conn.close()
print("Done. You can now restart the server.")

import duckdb, sys

DB_PATH = "data/banyan_dev.duckdb"

conn = duckdb.connect(DB_PATH)

# Count duplicates before
before = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT from_node_id, to_node_id, link_type_id
        FROM link
        GROUP BY from_node_id, to_node_id, link_type_id
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]
print(f"Duplicate endpoint groups before: {before}")

if before == 0:
    print("No duplicates found — nothing to do.")
    conn.close()
    sys.exit(0)

# Materialise the keep-set in Python (avoids self-referential subquery issues)
keep = {r[0] for r in conn.execute("""
    SELECT MIN(CAST(link_id AS VARCHAR))
    FROM link
    GROUP BY
        CAST(from_node_id AS VARCHAR),
        CAST(to_node_id   AS VARCHAR),
        CAST(link_type_id AS VARCHAR)
""").fetchall()}

to_delete = [r[0] for r in conn.execute(
    "SELECT CAST(link_id AS VARCHAR) FROM link"
).fetchall() if r[0] not in keep]

print(f"Rows to delete: {len(to_delete)}")

if to_delete:
    ph = ", ".join(["?" for _ in to_delete])
    conn.execute(f"DELETE FROM link WHERE CAST(link_id AS VARCHAR) IN ({ph})", to_delete)
    conn.commit()

after = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT from_node_id, to_node_id, link_type_id
        FROM link
        GROUP BY from_node_id, to_node_id, link_type_id
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]
print(f"Duplicate endpoint groups after: {after}")

conn.close()
print("Done. You can now restart the server.")
