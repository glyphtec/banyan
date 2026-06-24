"""
Banyan Graph Importer — single REST driver for Banyan export JSON files.

Reads a Banyan v1.1 export document (produced by any ingest_*.py generator)
and POSTs it to the Banyan REST API via POST /api/v1/graphs/import.

Usage
-----
    # Import from a file:
    python utils/import_graph.py data/colors.json

    # Import from stdin (pipe from generator):
    python utils/ingest_colors.py | python utils/import_graph.py -

    # Override the graph name at import time:
    python utils/import_graph.py data/colors.json --new-name "Colors v2"

    # Merge nodes into an existing graph:
    python utils/import_graph.py data/colors.json --merge-into <graph_id>

    # Point at a non-default server:
    python utils/import_graph.py data/colors.json --base-url http://localhost:9000

    # Dry-run: parse and print stats without calling the API:
    python utils/import_graph.py data/colors.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error as _err
import urllib.request as _req


DEFAULT_BASE_URL = "http://localhost:8000"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _post(url: str, data: dict, actor_id: str) -> tuple[int, object]:
    body = json.dumps(data, default=str).encode()
    req = _req.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Actor-Id": actor_id},
    )
    try:
        with _req.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except _err.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw).get("detail", raw.decode())
        except Exception:
            detail = raw.decode(errors="replace")
        return e.code, {"error": detail}


# ── Core import logic ─────────────────────────────────────────────────────────

def run_import(
    doc: dict,
    base_url: str,
    actor_id: str,
    new_name: str | None,
    merge_into: str | None,
    dry_run: bool,
) -> None:
    version = doc.get("banyan_export_version", "unknown")
    graph_name = doc.get("graph", {}).get("name", "<unnamed>")
    node_count = len(doc.get("nodes", []))
    link_count = len(doc.get("links", []))
    cross_count = len(doc.get("cross_graph_links", []))

    print(
        f"Export v{version}: graph='{graph_name}'  "
        f"nodes={node_count}  links={link_count}  cross_graph_links={cross_count}",
        file=sys.stderr,
    )

    if dry_run:
        print("[dry-run] No API call made.", file=sys.stderr)
        return

    payload: dict = {"export_doc": doc, "actor_id": actor_id}
    if new_name:
        payload["new_name"] = new_name
    if merge_into:
        payload["merge_into_graph_id"] = merge_into

    status, result = _post(f"{base_url}/api/v1/graphs/import", payload, actor_id)

    if status not in (200, 201):
        sys.exit(f"ERROR: HTTP {status} — {result}")

    imported_name = result.get("name", "?")
    imported_id = result.get("graph_id", "?")
    print(f"Imported: '{imported_name}'  graph_id={imported_id}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Import a Banyan export JSON file into a running Banyan instance."
    )
    p.add_argument(
        "file",
        metavar="FILE",
        help="Path to a Banyan export JSON file, or '-' to read from stdin.",
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help=f"Banyan API base URL (default: {DEFAULT_BASE_URL})")
    p.add_argument("--actor-id", default="import",
                   help="Actor ID recorded in the ledger for all imported mutations")
    p.add_argument("--new-name", metavar="NAME",
                   help="Override the graph name from the export document")
    p.add_argument("--merge-into", metavar="GRAPH_ID",
                   help="Merge nodes/links into an existing graph instead of creating a new one")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and print stats without calling the API")
    args = p.parse_args()

    if args.file == "-":
        raw = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8") as fh:
            raw = fh.read()

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: Invalid JSON — {exc}")

    run_import(
        doc=doc,
        base_url=args.base_url,
        actor_id=args.actor_id,
        new_name=args.new_name,
        merge_into=args.merge_into,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
