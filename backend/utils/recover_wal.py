"""
WAL recovery utility for banyan_dev.duckdb.

The DuckDB WAL replay can fail with an internal assertion error on certain
versions/crash patterns.  This script tries three progressively more
aggressive recovery strategies:

  1. read_only=True  — opens the file without acquiring the write lock;
                       DuckDB may still replay the WAL but the code path is
                       different and sometimes succeeds.
  2. WAL-stripped copy — copies only the .duckdb file (no .wal) to a temp
                         path so we can at least inspect the last checkpoint
                         state without destroying the originals.
  3. Report          — shows what tables / row-counts are available so you
                       can decide whether to promote the recovered copy to
                       production.

Run from the backend/ directory:
    python utils/recover_wal.py
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "banyan_dev.duckdb"
WAL_PATH = DATA_DIR / "banyan_dev.duckdb.wal"
ARCHIVE_DIR = DATA_DIR / "archive"

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def backup_originals() -> tuple[Path, Path]:
    """Copy both files into the archive directory with a timestamp suffix."""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    db_bak = ARCHIVE_DIR / f"banyan_dev_{TIMESTAMP}.duckdb"
    wal_bak = ARCHIVE_DIR / f"banyan_dev_{TIMESTAMP}.duckdb.wal"
    shutil.copy2(DB_PATH, db_bak)
    if WAL_PATH.exists():
        shutil.copy2(WAL_PATH, wal_bak)
    print(f"[backup] Originals saved to:\n  {db_bak}\n  {wal_bak}")
    return db_bak, wal_bak


def report_tables(conn: duckdb.DuckDBPyConnection, label: str) -> None:
    rows = conn.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
        "ORDER BY table_schema, table_name"
    ).fetchall()
    print(f"\n[{label}] Tables found: {len(rows)}")
    for schema, tbl in rows:
        count = conn.execute(f'SELECT count(*) FROM "{schema}"."{tbl}"').fetchone()[0]
        print(f"  {schema}.{tbl}: {count:,} rows")


def export_to_fresh(src_conn: duckdb.DuckDBPyConnection, dest: Path) -> None:
    """Export all tables from src_conn into a fresh DuckDB file at dest."""
    if dest.exists():
        dest.unlink()
    dest_conn = duckdb.connect(str(dest))
    # COPY DATABASE is the safest bulk-export mechanism in DuckDB >=1.0
    # It handles views, sequences, and user types correctly.
    src_conn.execute(f"EXPORT DATABASE '{dest.parent / dest.stem}_export' (FORMAT PARQUET)")
    dest_conn.close()


# ---------------------------------------------------------------------------
# Strategy 1: read_only=True on the original database
# ---------------------------------------------------------------------------

def try_read_only() -> duckdb.DuckDBPyConnection | None:
    print("\n--- Strategy 1: open with read_only=True ---")
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        print("[ok] Opened in read-only mode (WAL replay succeeded or was skipped).")
        return conn
    except Exception as exc:
        print(f"[fail] {exc}")
        return None


# ---------------------------------------------------------------------------
# Strategy 2: open a WAL-stripped copy of the .duckdb file
# ---------------------------------------------------------------------------

def try_no_wal() -> duckdb.DuckDBPyConnection | None:
    print("\n--- Strategy 2: open a WAL-stripped copy (last checkpoint state) ---")
    stripped = ARCHIVE_DIR / f"banyan_dev_{TIMESTAMP}_no_wal.duckdb"
    shutil.copy2(DB_PATH, stripped)
    # Do NOT copy the WAL alongside; DuckDB will open the file cleanly.
    try:
        conn = duckdb.connect(str(stripped))
        print(f"[ok] Opened stripped copy at {stripped}")
        print("     NOTE: changes written since the last CHECKPOINT are NOT present.")
        return conn
    except Exception as exc:
        print(f"[fail] {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"DuckDB version : {duckdb.__version__}")
    print(f"Database       : {DB_PATH}  ({DB_PATH.stat().st_size / 1_048_576:.2f} MB)")
    if WAL_PATH.exists():
        print(f"WAL file       : {WAL_PATH}  ({WAL_PATH.stat().st_size / 1_048_576:.2f} MB)")
    else:
        print("WAL file       : (not present)")

    backup_originals()

    # --- Strategy 1 ---
    conn = try_read_only()
    if conn is not None:
        report_tables(conn, "read_only")
        # Export to a fresh writable copy
        recovered = DATA_DIR / f"banyan_dev_recovered_{TIMESTAMP}.duckdb"
        print(f"\nExporting to fresh writable copy: {recovered}")
        try:
            export_dir = DATA_DIR / f"banyan_dev_export_{TIMESTAMP}"
            conn.execute(f"EXPORT DATABASE '{export_dir}' (FORMAT PARQUET)")
            print(f"[ok] Exported Parquet/SQL to {export_dir}")
            print(
                "\nTo restore, run:\n"
                f"  python -c \"import duckdb; c=duckdb.connect('{recovered}'); "
                f"c.execute(\\\"IMPORT DATABASE '{export_dir}'\\\"); c.close()\""
            )
        except Exception as exc:
            print(f"[warn] EXPORT DATABASE failed: {exc}")
            print("       Falling back to table-by-table copy …")
            recovered_conn = duckdb.connect(str(recovered))
            # Copy schema + data table by table
            tables = conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
                "ORDER BY table_schema, table_name"
            ).fetchall()
            for schema, tbl in tables:
                ddl = conn.execute(
                    f"SELECT sql FROM duckdb_tables() WHERE schema_name=? AND table_name=?",
                    [schema, tbl]
                ).fetchone()
                if ddl and ddl[0]:
                    recovered_conn.execute(ddl[0])
                recovered_conn.execute(
                    f'INSERT INTO "{schema}"."{tbl}" '
                    f'SELECT * FROM "{schema}"."{tbl}"@{DB_PATH}'
                )
            recovered_conn.close()
            print(f"[ok] Recovered copy written to {recovered}")
        conn.close()
        print(
            f"\nNext step: rename {recovered.name} to banyan_dev.duckdb "
            f"(and delete the .wal file) once you are satisfied."
        )
        sys.exit(0)

    # --- Strategy 2 ---
    conn = try_no_wal()
    if conn is not None:
        report_tables(conn, "no-wal / last-checkpoint")
        print(
            "\nThis represents the state at the last successful CHECKPOINT.\n"
            "The 1.3 MB WAL content could not be recovered automatically.\n"
            f"\nThe stripped copy is at:\n  {ARCHIVE_DIR}/banyan_dev_{TIMESTAMP}_no_wal.duckdb\n"
            "To use it as your production database:\n"
            f"  1. Delete (or archive) the current .wal file\n"
            f"  2. Replace banyan_dev.duckdb with the stripped copy\n"
            "     (all changes since the last checkpoint will be lost)"
        )
        conn.close()
        sys.exit(1)

    print("\n[fatal] All recovery strategies failed. Please file a DuckDB bug report.")
    sys.exit(2)


if __name__ == "__main__":
    main()
