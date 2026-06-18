"""
Banyan dev-environment cleanup utility.

Lists graphs and optionally purges them via the Admin API.
Requires the server to be running with enable_admin_api = True.

Usage
-----
# List all graphs and their node counts:
    python utils/cleanup.py

# Purge a single graph:
    python utils/cleanup.py --purge <graph_id>

# Purge ALL graphs (interactive confirmation):
    python utils/cleanup.py --purge-all

Options
-------
--base-url   Base URL of the running Banyan server  [default: http://localhost:8000]
--yes        Skip interactive confirmation for --purge-all
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    import urllib.request as _req
    import urllib.error as _err
except ImportError:
    sys.exit("urllib is unavailable — this should never happen.")


def _call(method: str, url: str) -> tuple[int, object]:
    """Minimal HTTP helper using stdlib only (no httpx / requests required)."""
    request = _req.Request(url, method=method)
    try:
        with _req.urlopen(request) as resp:  # noqa: S310 — localhost only
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else {}
    except _err.HTTPError as exc:
        body = exc.read().decode()
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        return exc.code, {"error": detail}


def cmd_list(base_url: str) -> None:
    status, data = _call("GET", f"{base_url}/admin/graphs")
    if status != 200:
        sys.exit(f"ERROR {status}: {data}")
    if not data:
        print("No graphs found.")
        return
    col_id  = max(len(g["graph_id"]) for g in data)
    col_nm  = max(len(g["name"])     for g in data)
    col_nc  = max(len(str(g["node_count"])) for g in data)
    header  = f"{'graph_id':<{col_id}}  {'name':<{col_nm}}  {'nodes':>{col_nc}}"
    print(header)
    print("-" * len(header))
    for g in data:
        print(f"{g['graph_id']:<{col_id}}  {g['name']:<{col_nm}}  {g['node_count']:>{col_nc}}")


def cmd_purge(base_url: str, graph_id: str) -> None:
    status, data = _call("DELETE", f"{base_url}/admin/graphs/{graph_id}")
    if status != 200:
        sys.exit(f"ERROR {status}: {data}")
    print(f"Purged graph {graph_id}")
    print(f"  nodes deleted:          {data.get('nodes_deleted', '?')}")
    print(f"  links deleted:          {data.get('links_deleted', '?')}")
    print(f"  ledger entries deleted: {data.get('ledger_entries_deleted', '?')}")
    print(f"  snapshots deleted:      {data.get('snapshots_deleted', '?')}")


def cmd_purge_all(base_url: str, yes: bool) -> None:
    # Fetch list first so the user can see what they're about to nuke.
    status, graphs = _call("GET", f"{base_url}/admin/graphs")
    if status != 200:
        sys.exit(f"ERROR {status}: {graphs}")
    if not graphs:
        print("No graphs to purge.")
        return

    print(f"About to purge {len(graphs)} graph(s):")
    for g in graphs:
        print(f"  {g['graph_id']}  {g['name']}  ({g['node_count']} nodes)")

    if not yes:
        answer = input("\nType 'yes' to confirm: ").strip()
        if answer.lower() != "yes":
            print("Aborted.")
            return

    status, data = _call("DELETE", f"{base_url}/admin/graphs?confirm=yes")
    if status != 200:
        sys.exit(f"ERROR {status}: {data}")
    print(f"\nPurged {data['purged']} graph(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Banyan dev cleanup utility")
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="Base URL of the running Banyan server (default: http://localhost:8000)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--purge", metavar="GRAPH_ID", help="Purge a single graph by ID")
    group.add_argument("--purge-all", action="store_true", help="Purge ALL graphs")
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip interactive confirmation when using --purge-all",
    )
    args = parser.parse_args()

    if args.purge:
        cmd_purge(args.base_url, args.purge)
    elif args.purge_all:
        cmd_purge_all(args.base_url, args.yes)
    else:
        cmd_list(args.base_url)


if __name__ == "__main__":
    main()
