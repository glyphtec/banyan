"""
Banyan sample taxonomy — MeSH Anatomy tree  (10³ example, ~1K–7K nodes)

Source: US National Library of Medicine Medical Subject Headings (MeSH) 2025
        https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/asciimesh/d2025.bin
        Free to use; no licence required for research and development.

Why MeSH?
---------
MeSH is explicitly polyhierarchical: a single descriptor can appear at multiple
positions in the tree (multiple "tree numbers").  For example, "Shoulder" appears
under both A01.378.800.750 (Upper Extremity) and A02.835.583.748 (Shoulder Joint).
The script creates one Banyan node per descriptor and one HIERARCHICAL link per
tree-number parent relationship, so a descriptor with two tree numbers gets two
parent links — a clean test of Banyan's polyhierarchy support.

Data volume by --max-depth (Anatomy / "A" tree):
  depth 1  :   ~15 nodes  (top-level anatomical categories)
  depth 2  :  ~100 nodes
  depth 3  :  ~650 nodes
  depth 4  : ~2 500 nodes  ← default
  depth 5  : ~5 000 nodes
  unlimited: ~6 600 nodes  (full anatomy tree)

Usage
-----
    # Download & ingest at default depth 4 (~2 500 nodes):
    python utils/ingest_mesh.py

    # Full anatomy tree (no depth limit):
    python utils/ingest_mesh.py --max-depth 0

    # Use a different MeSH tree (e.g. C = Diseases):
    python utils/ingest_mesh.py --tree C

    # Use a cached file you already downloaded:
    python utils/ingest_mesh.py --mesh-file path/to/d2025.bin

    # Dry-run (download & parse, print stats, no API calls):
    python utils/ingest_mesh.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error as _err
import urllib.request as _req
from collections import defaultdict

MESH_URL_TEMPLATE = (
    "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/asciimesh/d{year}.bin"
)
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "mesh")
DEFAULT_GRAPH_NAME = "MeSH Anatomy"
BATCH_SIZE = 500


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


def _run_batches(
    base: str,
    graph_id: str,
    actor_id: str,
    lt_id: int,
    ops: list[dict],
    kind: str,
    chunk_size: int = BATCH_SIZE,
) -> int:
    """Submit ops in chunks; returns total count processed."""
    total = len(ops)
    done = 0
    for i in range(0, total, chunk_size):
        chunk = ops[i : i + chunk_size]
        payload: dict = {
            "graph_id": graph_id,
            "actor_id": actor_id,
            "default_link_type_id": lt_id,
            "node_operations": chunk if kind == "nodes" else [],
            "link_operations": chunk if kind == "links" else [],
        }
        status, result = _post(f"{base}/api/v1/graphs/batch", payload, actor_id)
        if status != 200:
            _die(status, result, f"{kind} batch {i // chunk_size + 1}")
        done += len(chunk)
        print(f"  {kind}: {done}/{total}", end="\r" if done < total else "\n", flush=True)
    return done


# ── MeSH download ─────────────────────────────────────────────────────────────

def _ensure_mesh_file(mesh_file: str | None, year: int, cache_dir: str) -> str:
    if mesh_file:
        if not os.path.exists(mesh_file):
            sys.exit(f"MeSH file not found: {mesh_file}")
        print(f"Using supplied MeSH file: {mesh_file}")
        return mesh_file

    cache_path = os.path.join(cache_dir, f"d{year}.bin")
    if os.path.exists(cache_path):
        size_mb = os.path.getsize(cache_path) / 1_048_576
        print(f"Using cached MeSH file: {cache_path}  ({size_mb:.1f} MB)")
        return cache_path

    url = MESH_URL_TEMPLATE.format(year=year)
    os.makedirs(cache_dir, exist_ok=True)
    print(f"Downloading MeSH descriptor file from NLM (~50 MB) ...")
    print(f"  URL : {url}")
    print(f"  Dest: {cache_path}")

    def _progress(block_count: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, block_count * block_size * 100 // total)
            print(f"  {pct}%", end="\r", flush=True)

    try:
        _req.urlretrieve(url, cache_path, _progress)  # noqa: S310
    except Exception as exc:
        sys.exit(f"Download failed: {exc}")
    print(f"\nDownloaded: {cache_path}")
    return cache_path


# ── MeSH parser ───────────────────────────────────────────────────────────────

def _parse_mesh(
    path: str,
    tree_prefix: str,
    max_depth: int,  # 0 = unlimited
) -> tuple[list[dict], list[tuple[str, str]]]:
    """
    Parse MeSH ASCII descriptor file and extract nodes and parent→child edges
    for all descriptors whose tree number(s) start with *tree_prefix*.

    Returns
    -------
    nodes : list of {"source_id": UI, "name": MH, "notes": SN-or-None}
    edges : list of (parent_source_id | "$ROOT$", child_source_id)
    """
    def _in_scope(mn: str) -> bool:
        if not mn.startswith(tree_prefix):
            return False
        if max_depth == 0:
            return True
        return mn.count(".") + 1 <= max_depth

    # ── Pass 1: parse file into records ──────────────────────────────────────
    print("  Parsing MeSH file …", end="", flush=True)
    records: list[dict] = []
    current: dict = {}

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n").rstrip("\r")
            if line == "*NEWRECORD":
                if current.get("UI"):
                    records.append(current)
                current = {"MN": [], "ENTRY": []}
            elif line.startswith("MH = "):
                current["MH"] = line[5:]
            elif line.startswith("UI = "):
                current["UI"] = line[5:]
            elif line.startswith("MN = "):
                current["MN"].append(line[5:])
            elif line.startswith("SN = "):
                current["SN"] = line[5:]   # scope note (useful as description)
    if current.get("UI"):
        records.append(current)
    print(f" {len(records):,} descriptors loaded")

    # ── Pass 2: filter to in-scope tree numbers ────────────────────────────────
    # tree_number → UI (for parent lookups)
    tree_to_ui: dict[str, str] = {}
    included_uis: set[str] = set()

    for rec in records:
        ui = rec["UI"]
        in_scope_mns = [mn for mn in rec["MN"] if _in_scope(mn)]
        if in_scope_mns:
            included_uis.add(ui)
            for mn in in_scope_mns:
                tree_to_ui[mn] = ui

    print(f"  In-scope descriptors (tree={tree_prefix!r}, max_depth={max_depth or '∞'}): "
          f"{len(included_uis):,}")

    # ── Pass 3: build node list and edge list ──────────────────────────────────
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []

    poly_count = 0
    for rec in records:
        ui = rec["UI"]
        if ui not in included_uis:
            continue
        nodes.append({
            "source_id": ui,
            "name": rec.get("MH", ui),
            "notes": rec.get("SN"),
        })
        in_scope_mns = [mn for mn in rec["MN"] if _in_scope(mn)]
        if len(in_scope_mns) > 1:
            poly_count += 1
        for mn in in_scope_mns:
            if "." not in mn:
                # Depth-1 node → parent is graph $ROOT$
                edges.append(("$ROOT$", ui))
            else:
                parent_mn = mn.rsplit(".", 1)[0]
                parent_ui = tree_to_ui.get(parent_mn)
                if parent_ui:
                    edges.append((parent_ui, ui))
                else:
                    # Parent tree number not in scope → attach to $ROOT$
                    edges.append(("$ROOT$", ui))

    print(f"  Nodes: {len(nodes):,}   Edges: {len(edges):,}   "
          f"Polyhierarchy nodes: {poly_count:,}")
    return nodes, edges


# ── Ingest logic ──────────────────────────────────────────────────────────────

def ingest(
    base: str,
    graph_name: str,
    actor_id: str,
    dry_run: bool,
    mesh_file: str | None,
    year: int,
    tree: str,
    max_depth: int,
    cache_dir: str,
) -> None:
    mesh_path = _ensure_mesh_file(mesh_file, year, cache_dir)
    nodes, edges = _parse_mesh(mesh_path, tree, max_depth)

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
            "Use --graph-name to choose a different name."
        )

    # ── Lookup HIERARCHICAL link type ─────────────────────────────────────────
    status, lt_list = _get(f"{base}/api/v1/link-types")
    if status != 200:
        _die(status, lt_list, "link-types")
    hier_lt_id = next(
        (lt["link_type_id"] for lt in lt_list if lt["name"] == "HIERARCHICAL"), None
    )
    if hier_lt_id is None:
        sys.exit("HIERARCHICAL link type not found.")

    # ── Create graph ──────────────────────────────────────────────────────────
    status, graph = _post(
        f"{base}/api/v1/graphs",
        {"name": graph_name,
         "notes": (
             f"MeSH 2025 — tree {tree!r}, max_depth={max_depth or '∞'}. "
             "US NLM Medical Subject Headings. Polyhierarchical."
         )},
        actor_id,
    )
    if status != 201:
        _die(status, graph, "create graph")
    graph_id = graph["graph_id"]
    print(f"  Graph created: {graph_id}")

    # ── Batch ADD_NODE ────────────────────────────────────────────────────────
    node_ops = [
        {"verb": "ADD_NODE",
         "data": {"source_id": n["source_id"], "name": n["name"],
                  **({"notes": n["notes"]} if n.get("notes") else {})}}
        for n in nodes
    ]
    _run_batches(base, graph_id, actor_id, hier_lt_id, node_ops, "nodes")

    # ── Batch CREATE_LINK using source_ids (no GET /nodes needed) ─────────────
    link_ops = [
        {"verb": "CREATE_LINK",
         "data": {"from_source_id": parent_src, "to_source_id": child_src}}
        for parent_src, child_src in edges
    ]
    _run_batches(base, graph_id, actor_id, hier_lt_id, link_ops, "links")
    print(f"Done. Graph '{graph_name}' ingested successfully.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Ingest MeSH descriptor tree into Banyan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Node counts by --max-depth (Anatomy / A tree):\n"
            "  1 →    ~15   2 →   ~100   3 →   ~650\n"
            "  4 →  ~2500   5 →  ~5000   0 → ~6600 (full)"
        ),
    )
    p.add_argument("--base-url",    default="http://localhost:8000")
    p.add_argument("--graph-name",  default=DEFAULT_GRAPH_NAME)
    p.add_argument("--actor-id",    default="ingest")
    p.add_argument("--mesh-file",   default=None,
                   help="Path to a pre-downloaded MeSH .bin file. "
                        "If omitted the file is downloaded and cached.")
    p.add_argument("--year",        type=int, default=2025,
                   help="MeSH release year used to build the download URL (default: 2025)")
    p.add_argument("--cache-dir",   default=DEFAULT_CACHE_DIR,
                   help="Directory for the downloaded .bin file")
    p.add_argument("--tree",        default="A",
                   help="MeSH tree prefix to ingest (default: A = Anatomy). "
                        "Other useful values: C (Diseases), D (Chemicals).")
    p.add_argument("--max-depth",   type=int, default=4,
                   help="Maximum tree depth to import (0 = unlimited, default: 4)")
    p.add_argument("--dry-run",     action="store_true",
                   help="Download & parse, print stats, but make no API calls")
    args = p.parse_args()
    ingest(
        base=args.base_url,
        graph_name=args.graph_name,
        actor_id=args.actor_id,
        dry_run=args.dry_run,
        mesh_file=args.mesh_file,
        year=args.year,
        tree=args.tree,
        max_depth=args.max_depth,
        cache_dir=args.cache_dir,
    )


if __name__ == "__main__":
    main()
