"""
run_batch.py — Submit a Banyan named batch document to the API.

A "named batch" file (produced by link_has_member.py and similar generators)
stores graph names and link type names as human-readable strings.  This
runner resolves those names to UUIDs by calling the API, then POSTs the
resolved batch to POST /api/v1/graphs/batch.

Named batch document format
----------------------------
    {
      "banyan_batch_version": "1.0",
      "from_graph_name":       "Gravity SDOH Clinical Care STU 2.3",
      "actor_id":              "system:ingest",
      "default_link_type_name": "HAS_MEMBER",
      "link_operations": [
          {
            "verb": "CREATE_LINK",
            "data": {
              "from_source_id": "sdoh:food-insecurity/diagnoses",
              "to_source_id":   "http://snomed.info/sct|73211009",
              "to_graph_name":  "SNOMED CT SDOH Slice",
              "metadata": { ... }
            }
          },
          ...
      ]
    }

All 'to_graph_name' values are resolved to UUIDs in a single pre-flight
lookup.  If any name is not found, the runner aborts before submitting
anything.

Usage
-----
    python utils/run_batch.py data/gravity/has_member_links.batch.json

    # Point at a non-default server:
    python utils/run_batch.py data/gravity/has_member_links.batch.json \\
        --base-url http://localhost:9000

    # Dry-run: resolve names and print the resolved batch without submitting:
    python utils/run_batch.py data/gravity/has_member_links.batch.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error as _err
import urllib.request as _req


DEFAULT_BASE_URL = "http://localhost:8000"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str) -> tuple[int, object]:
    req = _req.Request(url, headers={"Accept": "application/json"})
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


# ── Name resolution ───────────────────────────────────────────────────────────

def resolve_graph_names(
    base_url: str,
    names: set[str],
) -> dict[str, str]:
    """Return {graph_name → graph_id} for all requested names.

    Aborts (sys.exit) if any name is not found.
    """
    status, graphs = _get(f"{base_url}/api/v1/graphs")
    if status != 200:
        sys.exit(f"ERROR: could not list graphs — HTTP {status}: {graphs}")

    name_to_id = {g["name"]: g["graph_id"] for g in graphs}
    missing = names - set(name_to_id)
    if missing:
        sys.exit(
            "ERROR: the following graph names were not found in the API:\n"
            + "".join(f"  · {n}\n" for n in sorted(missing))
            + "Import the missing graphs first."
        )
    return {n: name_to_id[n] for n in names}


def resolve_link_type_name(base_url: str, name: str) -> str:
    """Return the link_type_id for the given name.

    Aborts (sys.exit) if the name is not found.
    """
    status, link_types = _get(f"{base_url}/api/v1/link-types")
    if status != 200:
        sys.exit(f"ERROR: could not list link types — HTTP {status}: {link_types}")

    for lt in link_types:
        if lt["name"] == name:
            return lt["link_type_id"]

    sys.exit(
        f"ERROR: link type '{name}' not found.\n"
        f"Create it first via POST /api/v1/link-types."
    )


# ── Resolution + submission ───────────────────────────────────────────────────

def run_batch(
    doc: dict,
    base_url: str,
    actor_id: str | None,
    dry_run: bool,
) -> None:
    version = doc.get("banyan_batch_version", "?")
    if version != "1.0":
        print(
            f"WARNING: unknown banyan_batch_version '{version}' — proceeding anyway.",
            file=sys.stderr,
        )

    from_graph_name       = doc.get("from_graph_name")
    default_lt_name       = doc.get("default_link_type_name")
    link_ops: list[dict]  = doc.get("link_operations", [])
    effective_actor       = actor_id or doc.get("actor_id", "batch-anonymous")

    if not from_graph_name:
        sys.exit("ERROR: batch document is missing 'from_graph_name'.")

    print(f"Batch v{version}: from_graph='{from_graph_name}'  ops={len(link_ops)}")

    # Collect all graph names referenced in the document
    graph_names_needed: set[str] = {from_graph_name}
    for op in link_ops:
        tgn = op.get("data", {}).get("to_graph_name")
        if tgn:
            graph_names_needed.add(tgn)

    print(f"Resolving {len(graph_names_needed)} graph name(s) ...")
    graph_ids = resolve_graph_names(base_url, graph_names_needed)
    for name, gid in sorted(graph_ids.items()):
        print(f"  '{name}' → {gid}")

    default_lt_id: str | None = None
    if default_lt_name:
        print(f"Resolving link type '{default_lt_name}' ...")
        default_lt_id = resolve_link_type_name(base_url, default_lt_name)
        print(f"  '{default_lt_name}' → {default_lt_id}")

    # Build resolved batch payload
    resolved_ops: list[dict] = []
    for op in link_ops:
        data = dict(op["data"])
        # Resolve to_graph_name → to_graph_id
        tgn = data.pop("to_graph_name", None)
        if tgn:
            data["to_graph_id"] = graph_ids[tgn]
        # Per-op link_type_name (future-proof; not generated by current scripts)
        lt_name = data.pop("link_type_name", None)
        if lt_name:
            data["link_type_id"] = resolve_link_type_name(base_url, lt_name)
        resolved_ops.append({"verb": op["verb"], "data": data})

    payload = {
        "graph_id":             graph_ids[from_graph_name],
        "actor_id":             effective_actor,
        "default_link_type_id": default_lt_id,
        "link_operations":      resolved_ops,
    }

    if dry_run:
        print(f"\n[dry-run] Resolved payload (first 3 ops shown):")
        preview = {**payload, "link_operations": payload["link_operations"][:3]}
        print(json.dumps(preview, indent=2))
        print(f"... ({len(resolved_ops)} operations total, not submitted)")
        return

    print(f"Submitting {len(resolved_ops)} link operation(s) ...")
    status, result = _post(
        f"{base_url}/api/v1/graphs/batch",
        payload,
        effective_actor,
    )

    if status not in (200, 201):
        sys.exit(f"ERROR: HTTP {status} — {result}")

    print("\nBatch result:")
    for k, v in result.items():
        print(f"  {k}: {v}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Submit a Banyan named batch document to the API."
    )
    p.add_argument(
        "file",
        metavar="FILE",
        help="Path to a named batch JSON file, or '-' to read from stdin.",
    )
    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the Banyan API (default: {DEFAULT_BASE_URL})",
    )
    p.add_argument(
        "--actor-id",
        default=None,
        help="Override the actor_id in the batch document.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve names and print the resolved payload without submitting.",
    )
    args = p.parse_args()

    if args.file == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(args.file, encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            sys.exit(f"ERROR: cannot read file — {e}")

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: invalid JSON — {e}")

    run_batch(doc, base_url=args.base_url, actor_id=args.actor_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
