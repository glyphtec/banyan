"""
Banyan ingest generator — Open Eligibility taxonomy  (~290 nodes)

Source: Open Eligibility Project (openreferral/openeligibility on GitHub)
        https://github.com/openreferral/openeligibility
License: Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0)
         Original author: Aunt Bertha, Inc.  Steward: Open Referral Initiative
         Attribution and share-alike obligations apply to any derived artifact.

Design notes
------------
1:1 SOT fidelity.  Every record in taxonomy.json becomes exactly one Banyan
node keyed by source_id = "OE.<id>".  Intra-taxonomy parent/child relationships
become HIERARCHICAL links.  Root-level nodes (parent_id == "0") are linked from
the virtual graph $ROOT$.

Duplicate display names (e.g., "Nursing Home" appears under Housing, Medical
Care, and Residential Care as distinct IDs) are intentional in the source and are
preserved as separate nodes.  TERM_EQUIVALENT assertions across those nodes are
an editorial step that must be performed separately, attributed to a named actor,
and recorded in the ledger — they are explicitly NOT generated here.

Version-update workflow (post-ingest)
--------------------------------------
Do NOT re-run this importer to absorb an OE taxonomy revision.  Re-ingesting
would destroy downstream enrichment (TERM_EQUIVALENT, cross-graph SAME_AS links)
that has no counterpart in the upstream source.  Instead:

    1. python utils/ingest_oe.py --output data/oe/oe_latest.json
    2. Diff the export against the live graph via the Banyan diff endpoint.
    3. Execute a targeted batch of CREATE/DESTROY/UPDATE primitives for only the
       records that changed.

Usage
-----
    # Write export JSON to stdout:
    python utils/ingest_oe.py

    # Cache source to data/oe/ and write export to a file:
    python utils/ingest_oe.py --output data/oe/oe_2024.json

    # Use a previously downloaded taxonomy.json:
    python utils/ingest_oe.py --oe-file data/oe/taxonomy.json

    # Dry-run: download, parse, print stats — no output:
    python utils/ingest_oe.py --dry-run

    # Load into a running Banyan instance:
    python utils/ingest_oe.py | python utils/import_graph.py -
    python utils/import_graph.py data/oe/oe_2024.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error as _err
import urllib.request as _req
from collections import Counter
from datetime import datetime, timezone

OE_TAXONOMY_URL = (
    "https://raw.githubusercontent.com/openreferral/openeligibility/master/taxonomy.json"
)
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "oe")
DEFAULT_CACHE_FILE = "taxonomy.json"
DEFAULT_GRAPH_NAME = "Open Eligibility"
SOURCE_ID_PREFIX = "OE."
ROOT_SENTINEL = "$ROOT$"


# ── Source download / cache ───────────────────────────────────────────────────

def _ensure_oe_file(oe_file: str | None, cache_dir: str) -> str:
    """Return path to taxonomy.json, downloading and caching if needed."""
    if oe_file:
        if not os.path.exists(oe_file):
            sys.exit(f"OE file not found: {oe_file}")
        print(f"Using supplied OE file: {oe_file}", file=sys.stderr)
        return oe_file

    cache_path = os.path.join(cache_dir, DEFAULT_CACHE_FILE)
    if os.path.exists(cache_path):
        print(f"Using cached OE file: {cache_path}", file=sys.stderr)
        return cache_path

    print(f"Downloading Open Eligibility taxonomy from GitHub ...", file=sys.stderr)
    print(f"  URL : {OE_TAXONOMY_URL}", file=sys.stderr)
    print(f"  Dest: {cache_path}", file=sys.stderr)

    os.makedirs(cache_dir, exist_ok=True)
    try:
        with _req.urlopen(OE_TAXONOMY_URL) as resp:  # noqa: S310
            raw = resp.read()
    except _err.HTTPError as exc:
        sys.exit(f"Download failed: HTTP {exc.code} — {exc.reason}")
    except Exception as exc:
        sys.exit(f"Download failed: {exc}")

    with open(cache_path, "wb") as fh:
        fh.write(raw)
    print(f"  Saved {len(raw):,} bytes", file=sys.stderr)
    return cache_path


# ── Parse ─────────────────────────────────────────────────────────────────────

def _load_records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        records = json.load(fh)
    if not isinstance(records, list):
        sys.exit(f"Unexpected OE file format: expected a JSON array, got {type(records).__name__}")
    return records


# ── Generate ──────────────────────────────────────────────────────────────────

def generate(records: list[dict], graph_name: str = DEFAULT_GRAPH_NAME) -> dict:
    """
    Convert OE taxonomy records into a Banyan v1.1 export document.

    Each record: {"id": "1101", "name": "Emergency", "parent_id": "0", ...}
    parent_id == "0"  →  link from $ROOT$
    """
    nodes = [
        {
            "source_id": f"{SOURCE_ID_PREFIX}{r['id']}",
            "name": r["name"],
        }
        for r in records
    ]

    links = [
        {
            "from_source_id": (
                ROOT_SENTINEL if r["parent_id"] == "0"
                else f"{SOURCE_ID_PREFIX}{r['parent_id']}"
            ),
            "to_source_id": f"{SOURCE_ID_PREFIX}{r['id']}",
            "link_type_name": "HIERARCHICAL",
        }
        for r in records
    ]

    root_count = sum(1 for r in records if r["parent_id"] == "0")

    return {
        "banyan_export_version": "1.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "name": graph_name,
            "notes": (
                f"Open Eligibility taxonomy — {len(records)} nodes, "
                f"{root_count} top-level categories. "
                "Source: openreferral/openeligibility (GitHub). "
                "License: CC BY-SA 3.0. Original author: Aunt Bertha, Inc. "
                "Steward: Open Referral Initiative. "
                "Derived artifacts must carry this attribution and be released "
                "under share-alike terms."
            ),
        },
        "nodes": nodes,
        "links": links,
        "cross_graph_links": [],
    }


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _print_stats(records: list[dict]) -> None:
    root_count = sum(1 for r in records if r["parent_id"] == "0")
    name_counts = Counter(r["name"] for r in records)
    duplicates = {name: count for name, count in name_counts.items() if count > 1}

    print(f"Open Eligibility taxonomy:", file=sys.stderr)
    print(f"  Total records  : {len(records)}", file=sys.stderr)
    print(f"  Root categories: {root_count}", file=sys.stderr)
    print(f"  Child nodes    : {len(records) - root_count}", file=sys.stderr)

    if duplicates:
        print(f"  Duplicate names: {len(duplicates)} (intentional in source — "
              "separate nodes, distinct source IDs)", file=sys.stderr)
        for name, count in sorted(duplicates.items(), key=lambda x: -x[1]):
            print(f"    {count}×  {name!r}", file=sys.stderr)
    else:
        print(f"  Duplicate names: none", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate a Banyan export JSON for the Open Eligibility taxonomy."
    )
    p.add_argument(
        "--oe-file", metavar="FILE",
        help="Use a local taxonomy.json instead of downloading from GitHub",
    )
    p.add_argument(
        "--graph-name", default=DEFAULT_GRAPH_NAME,
        help="Graph name to embed in the export document",
    )
    p.add_argument(
        "--output", metavar="FILE",
        help="Write export JSON to FILE instead of stdout",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Download/parse and print stats only; do not write output",
    )
    args = p.parse_args()

    oe_path = _ensure_oe_file(args.oe_file, DEFAULT_CACHE_DIR)
    records = _load_records(oe_path)
    _print_stats(records)

    if args.dry_run:
        print("[dry-run] No output written.", file=sys.stderr)
        return

    doc = generate(records, args.graph_name)
    text = json.dumps(doc, indent=2, ensure_ascii=False)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
