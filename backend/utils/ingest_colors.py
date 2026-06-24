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
    # Write export JSON to stdout:
    python utils/ingest_colors.py

    # Write to a file:
    python utils/ingest_colors.py --output data/colors.json

    # Customize the graph name embedded in the export:
    python utils/ingest_colors.py --graph-name "My Colors"

    # Print stats only (no output):
    python utils/ingest_colors.py --dry-run

    # Load into a running Banyan instance:
    python utils/ingest_colors.py | python utils/import_graph.py -
    python utils/import_graph.py data/colors.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


# ── Taxonomy data ─────────────────────────────────────────────────────────────
# (source_id, display_name, primary_parent_source_id | None → $ROOT$)
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


# ── Generator ─────────────────────────────────────────────────────────────────

def generate(graph_name: str = DEFAULT_GRAPH_NAME) -> dict:
    """Return a Banyan v1.1 export document for the color taxonomy."""
    nodes = [
        {"source_id": sid, "name": name}
        for sid, name, _ in _NODES
    ]
    # Primary parent links (None parent → $ROOT$)
    links = [
        {
            "from_source_id": parent_sid if parent_sid else "$ROOT$",
            "to_source_id": sid,
            "link_type_name": "HIERARCHICAL",
        }
        for sid, _, parent_sid in _NODES
    ]
    # Extra polyhierarchy parent links
    links += [
        {
            "from_source_id": extra_parent,
            "to_source_id": child,
            "link_type_name": "HIERARCHICAL",
        }
        for child, extra_parent in _EXTRA_PARENTS
    ]
    poly_nodes = {child for child, _ in _EXTRA_PARENTS}
    return {
        "banyan_export_version": "1.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "name": graph_name,
            "notes": (
                f"Fabricated color taxonomy — zero/smoke-test example "
                f"({len(_NODES)} nodes, polyhierarchy on: "
                f"{', '.join(sorted(poly_nodes))})"
            ),
        },
        "nodes": nodes,
        "links": links,
        "cross_graph_links": [],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate a Banyan export JSON for the color taxonomy."
    )
    p.add_argument("--graph-name", default=DEFAULT_GRAPH_NAME,
                   help="Graph name to embed in the export document")
    p.add_argument("--output", metavar="FILE",
                   help="Write JSON to FILE instead of stdout")
    p.add_argument("--dry-run", action="store_true",
                   help="Print stats only; do not write output")
    args = p.parse_args()

    poly_nodes = {child for child, _ in _EXTRA_PARENTS}
    print(
        f"Color taxonomy: {len(_NODES)} nodes, "
        f"{len(_EXTRA_PARENTS)} extra polyhierarchy links "
        f"(nodes: {', '.join(sorted(poly_nodes))})",
        file=sys.stderr,
    )

    if args.dry_run:
        print("[dry-run] No output written.", file=sys.stderr)
        return

    doc = generate(args.graph_name)
    text = json.dumps(doc, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
