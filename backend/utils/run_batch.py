"""
run_batch.py — Submit a batch document to the Banyan API.

The /api/v1/graphs/batch endpoint accepts graph_id or graph_name,
default_link_type_id or default_link_type_name, and to_graph_name inside
link operation data — all resolved server-side.  This script is a
passthrough: read the file, POST it, print the result.

Usage
-----
    python utils/run_batch.py my_batch.json
    python utils/run_batch.py my_batch.json --base-url http://localhost:9000
    python utils/run_batch.py my_batch.json --actor-id human:jane.smith
    python utils/run_batch.py my_batch.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error as _err
import urllib.request as _req

DEFAULT_BASE_URL = "http://localhost:8000"


def main() -> None:
    p = argparse.ArgumentParser(description="Submit a Banyan batch document to the API.")
    p.add_argument("file", metavar="FILE", help="Batch JSON file, or '-' to read from stdin.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"API base URL (default: {DEFAULT_BASE_URL})")
    p.add_argument("--actor-id", default=None, help="Override actor_id in the document.")
    p.add_argument("--dry-run", action="store_true", help="Print the payload without submitting.")
    args = p.parse_args()

    raw = sys.stdin.read() if args.file == "-" else open(args.file).read()
    doc = json.loads(raw)

    if args.actor_id:
        doc["actor_id"] = args.actor_id

    if args.dry_run:
        print(json.dumps(doc, indent=2))
        return

    actor = doc.get("actor_id", "batch-anonymous")
    body = json.dumps(doc, default=str).encode()
    req = _req.Request(
        f"{args.base_url}/api/v1/graphs/batch",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Actor-Id": actor},
    )
    try:
        with _req.urlopen(req) as r:
            print(json.dumps(json.loads(r.read()), indent=2))
    except _err.HTTPError as e:
        raw_err = e.read()
        try:
            detail = json.loads(raw_err).get("detail", raw_err.decode())
        except Exception:
            detail = raw_err.decode(errors="replace")
        sys.exit(f"HTTP {e.code}: {detail}")


if __name__ == "__main__":
    main()
