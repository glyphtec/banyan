#!/usr/bin/env python3
"""
backup_db.py — Checkpoint and backup the Banyan DuckDB database.

Workflow
--------
1. If the server is running, call POST /admin/checkpoint to flush the WAL
   into the main .duckdb file before copying.
2. Copy banyan_dev.duckdb to data/archive/ with a UTC timestamp suffix.

The backup is always taken from the main .duckdb file (never the WAL), so it
is safe to restore by itself.  The WAL is intentionally excluded — it will be
empty after a successful checkpoint.

Usage
-----
    python utils/backup_db.py
    python utils/backup_db.py --base-url http://localhost:9000
    python utils/backup_db.py --skip-checkpoint   # server not running; skip API call
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error as _err
import urllib.request as _req
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT    = Path(__file__).resolve().parent.parent
DB_PATH      = REPO_ROOT / "data" / "banyan_dev.duckdb"
ARCHIVE_DIR  = REPO_ROOT / "data" / "archive"
DEFAULT_BASE = "http://localhost:8000"


def _checkpoint_via_api(base_url: str) -> bool:
    """Call POST /admin/checkpoint.  Returns True on success, False on failure."""
    url = f"{base_url}/admin/checkpoint"
    req = _req.Request(url, data=b"", method="POST",
                       headers={"Content-Type": "application/json"})
    try:
        with _req.urlopen(req, timeout=15) as r:
            print(f"  Checkpoint: {r.read().decode()}")
            return True
    except _err.HTTPError as e:
        print(f"  Checkpoint API returned {e.code}: {e.read().decode(errors='replace')}",
              file=sys.stderr)
        return False
    except OSError as e:
        print(f"  Could not reach server ({e}) — WAL may not be fully flushed.",
              file=sys.stderr)
        return False


def main() -> None:
    p = argparse.ArgumentParser(description="Checkpoint and backup the Banyan DuckDB file.")
    p.add_argument("--base-url", default=DEFAULT_BASE,
                   help=f"API base URL (default: {DEFAULT_BASE})")
    p.add_argument("--skip-checkpoint", action="store_true",
                   help="Skip the API checkpoint call (use when server is not running).")
    args = p.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}")

    # ── Step 1: checkpoint ────────────────────────────────────────────────────
    if args.skip_checkpoint:
        print("Skipping checkpoint (--skip-checkpoint specified).")
        wal = DB_PATH.with_suffix(".duckdb.wal")
        if wal.exists():
            print(f"  WARNING: WAL file exists ({wal.stat().st_size / 1024:.0f} KB). "
                  "The backup may be missing uncommitted data.", file=sys.stderr)
    else:
        print(f"Checkpointing via {args.base_url}/admin/checkpoint …")
        _checkpoint_via_api(args.base_url)

    # ── Step 2: copy ──────────────────────────────────────────────────────────
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = ARCHIVE_DIR / f"banyan_dev_{ts}.duckdb"

    size_mb = DB_PATH.stat().st_size / 1_048_576
    print(f"Copying {DB_PATH.name} ({size_mb:.1f} MB) → {dest.name} …")
    shutil.copy2(DB_PATH, dest)
    print(f"Backup complete: {dest}")


if __name__ == "__main__":
    main()
