"""
Banyan sample taxonomy — Color Taxonomy  (zero / smoke-test example, ~36 nodes)

A fabricated color hierarchy used as the simplest possible Banyan test case.

Structure
---------
  $ROOT$
  ├── Chromatic
  │   ├── Warm  → Red, Orange, Yellow  (+named shades)
  │   └── Cool  → Green, Blue, Violet  (+named shades)
  └── Achromatic → White, Black, Gray, Brown  (+shades)

Polyhierarchy (3 nodes with two HIERARCHICAL parents each):
  Magenta  → Red  AND  Violet
  Teal     → Green AND  Blue
  Indigo   → Blue  AND  Violet

Usage
-----
    python utils/ingest_colors.py
    python utils/ingest_colors.py --base-url http://localhost:9000
    python utils/ingest_colors.py --dry-run
    python utils/ingest_colors.py --graph-name "My Colors"
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error as _err
import urllib.request as _req

# ── Taxonomy data ─────────────────────────────────────────────────────────────
# (source_id, display_name, primary_parent_source_id | None → graph $ROOT$)
_NODES: list[tuple[str, str, str | None]] = [
    # Top-level groupings
    ("chromatic",   "Chromatic",   None),
    ("achromatic",  "Achromatic",  None),
    # Chromatic sub-groups
    ("warm",        "Warm",        "chromatic"),
    ("cool",        "Cool",        "chromatic"),
    # Warm colour families
    ("red",         "Red",         "warm"),
    ("orange",      "Orange",      "warm"),
    ("yellow",      "Yellow",      "warm"),
    # Red shades (Magenta primary parent = Red)
    ("crimson",     "Crimson",     "red"),
    ("scarlet",     "Scarlet",     "red"),
    ("rose",        "Rose",        "red"),
    ("magenta",     "Magenta",     "red"),
    # Orange shades
    ("amber",       "Amber",       "orange"),
    ("coral",       "Coral",       "orange"),
    # Yellow shades
    ("gold",        "Gold",        "yellow"),
    ("lemon",       "Lemon",       "yellow"),
    # Cool colour families
    ("green",       "Green",       "cool"),
    ("blue",        "Blue",        "cool"),
    ("violet",      "Violet",      "cool"),
    # Green shades (Teal primary parent = Green)
    ("emerald",     "Emerald",     "green"),
    ("olive",       "Olive",       "green"),
    ("mint",        "Mint",        "green"),
    ("teal",        "Teal",        "green"),
    # Blue shades (Indigo primary parent = Blue)
    ("navy",        "Navy",        "blue"),
    ("sky",         "Sky Blue",    "blue"),
    ("cerulean",    "Cerulean",    "blue"),
    ("indigo",      "Indigo",      "blue"),
    # Violet shades
    ("purple",      "Purple",      "violet"),
    ("lavender",    "Lavender",    "violet"),
    # Achromatic
    ("white",       "White",       "achromatic"),
    ("black",       "Black",       "achromatic"),
    ("gray",        "Gray",        "achromatic"),
    ("brown",       "Brown",       "achromatic"),
    ("light-gray",  "Light Gray",  "gray"),
    ("dark-gray",   "Dark Gray",   "gray"),
    ("tan",         "Tan",         "brown"),
    ("chocolate",   "Chocolate",   "brown"),
]

# Extra parent links for polyhierarchy nodes (child, additional_parent)
_EXTRA_PARENTS: list[tuple[str, str]] = [
    ("magenta", "violet"),
    ("teal",    "blue"),
    ("indigo",  "violet"),
]

DEFAULT_GRAPH_NAME = "Colors"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str) -> tuple[int, object]:
    try:
        with _req.urlopen(url) as r:
            return r.status, json.loads(r.read())
    except _err.HTTPError as e:
        body = e.read()
        try:
            detail = json.loads(body).get("detail", body.decode())
        except Exception:
            detail = body.decode(errors="replace")
        return e.code, {"error": detail}


def _post(url: str, data: dict, actor_id: str = "ingest") -> tuple[int, object]:
    body = json.dumps(data, default=str).encode()
    req = _req.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Actor-Id": actor_id},
    )
    try:
        with _req.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except _err.HTTPError as e:
        body = e.read()
        try:
            detail = json.loads(body).get("detail", body.decode())
        except Exception:
            detail = body.decode(errors="replace")
        return e.code, {"error": detail}


def _die(status: int, data: object, context: str) -> None:
    sys.exit(f"ERROR [{context}] HTTP {status}: {data}")


# ── Ingest logic ──────────────────────────────────────────────────────────────

def ingest(base: str, graph_name: str, actor_id: str, dry_run: bool) -> None:
    poly_nodes = {child for child, _ in _EXTRA_PARENTS}
    print(f"Color taxonomy: {len(_NODES)} nodes, {len(_EXTRA_PARENTS)} polyhierarchy extra links")
    print(f"  Polyhierarchy nodes: {', '.join(sorted(poly_nodes))}")

    if dry_run:
        print("[dry-run] No API calls made.")
        return

    # ── Check for name collision ──────────────────────────────────────────────
    status, graphs = _get(f"{base}/api/v1/graphs")
    if status != 200:
        _die(status, graphs, "list graphs")
    if any(g["name"] == graph_name for g in graphs):
        sys.exit(
            f"Graph '{graph_name}' already exists. "
            "Use --graph-name to choose a different name, "
            "or use cleanup.py --purge-all to clear the database."
        )

    # ── Lookup HIERARCHICAL link type ─────────────────────────────────────────
    status, lt_list = _get(f"{base}/api/v1/link-types")
    if status != 200:
        _die(status, lt_list, "link-types")
    hier_lt_id = next(
        (lt["link_type_id"] for lt in lt_list if lt["name"] == "HIERARCHICAL"), None
    )
    if hier_lt_id is None:
        sys.exit("HIERARCHICAL link type not found. Is the database bootstrapped?")

    # ── Create graph ──────────────────────────────────────────────────────────
    status, graph = _post(
        f"{base}/api/v1/graphs",
        {"name": graph_name, "notes": "Fabricated color taxonomy — zero/smoke-test example"},
        actor_id,
    )
    if status != 201:
        _die(status, graph, "create graph")
    graph_id = graph["graph_id"]
    print(f"  Graph created: {graph_id}")

    # ── Single batch: ADD_NODE then CREATE_LINK (Phase 1 runs before Phase 2
    # inside one transaction, so source_id resolution finds same-batch nodes) ──
    node_ops = [
        {"verb": "ADD_NODE", "data": {"source_id": sid, "name": name}}
        for sid, name, _ in _NODES
    ]
    # Primary hierarchy links (parent_sid=None → "$ROOT$" which is the auto-
    # created root node every graph gets on creation)
    link_ops = [
        {"verb": "CREATE_LINK",
         "data": {"from_source_id": parent_sid if parent_sid else "$ROOT$",
                  "to_source_id": sid}}
        for sid, _, parent_sid in _NODES
    ]
    # Extra polyhierarchy parent links
    link_ops += [
        {"verb": "CREATE_LINK",
         "data": {"from_source_id": extra_parent, "to_source_id": child}}
        for child, extra_parent in _EXTRA_PARENTS
    ]

    status, result = _post(
        f"{base}/api/v1/graphs/batch",
        {"graph_id": graph_id, "actor_id": actor_id,
         "default_link_type_id": hier_lt_id,
         "node_operations": node_ops, "link_operations": link_ops},
        actor_id,
    )
    if status != 200:
        _die(status, result, "batch")
    print(f"  Nodes added: {result['nodes_added']}  "
          f"Links created: {result['links_created']} "
          f"(includes {len(_EXTRA_PARENTS)} polyhierarchy extra-parent links)")
    print(f"Done. Graph '{graph_name}' ingested successfully.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Ingest color taxonomy into Banyan")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--graph-name", default=DEFAULT_GRAPH_NAME)
    p.add_argument("--actor-id", default="ingest")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without making any API calls")
    args = p.parse_args()
    ingest(args.base_url, args.graph_name, args.actor_id, args.dry_run)


if __name__ == "__main__":
    main()
