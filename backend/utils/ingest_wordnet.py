"""
Banyan sample taxonomy — WordNet English Noun Hierarchy  (10⁵ example, ~82K nodes)

Source: WordNet 3.1 — Princeton University
        https://wordnet.princeton.edu/
        Licence: WordNet 3.1 licence (permissive, free for research & development)

Accessed via NLTK:
    pip install nltk
    python -c "import nltk; nltk.download('wordnet')"
  (the ingest script downloads the corpus automatically on first run)

Why WordNet?
------------
WordNet organises English nouns into synsets (synonym sets) linked by IS-A
(hypernym/hyponym) relationships.  Most synsets have a single hypernym, but
some have multiple — creating genuine polyhierarchy.  The full noun hierarchy
contains ~82 000 synsets spanning virtually every domain of human knowledge,
making it an excellent large-scale performance and traversal test.

Data volume
-----------
  --max-nodes 0  (default) : all ~82 000 noun synsets
  --max-nodes N            : BFS subtree from entity.n.01, N nodes

Timing (rough, localhost DuckDB):
  82 000 nodes  → ~3–5 min (164 node batches + ~164 link batches of 500)

Usage
-----
    # Full ingest (~82K nodes):
    python utils/ingest_wordnet.py

    # Quick test with 1 000 nodes (BFS from entity.n.01):
    python utils/ingest_wordnet.py --max-nodes 1000

    # Dry-run (shows stats, no API calls):
    python utils/ingest_wordnet.py --max-nodes 5000 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error as _err
import urllib.request as _req
from collections import deque

DEFAULT_GRAPH_NAME = "WordNet Nouns"
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
        print(f"  {kind}: {done:,}/{total:,}", end="\r" if done < total else "\n", flush=True)
    return done


# ── WordNet data collection ───────────────────────────────────────────────────

def _ensure_nltk() -> None:
    try:
        import nltk  # noqa: F401
    except ImportError:
        sys.exit(
            "nltk is not installed. Run:  pip install nltk\n"
            "then re-run this script (it will download the WordNet corpus automatically)."
        )
    import nltk
    # Download silently if not present; no-op if already cached.
    nltk.download("wordnet", quiet=True)
    nltk.download("omw-1.4", quiet=True)   # multilingual wordnet metadata


def _collect_all_nouns() -> tuple[list[dict], list[tuple[str, str]]]:
    """Collect all ~82 000 noun synsets and their hypernym edges."""
    from nltk.corpus import wordnet as wn

    print("  Collecting all noun synsets …", end="", flush=True)
    synsets = list(wn.all_synsets("n"))
    name_set = {ss.name() for ss in synsets}
    print(f" {len(synsets):,}")

    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []
    poly_count = 0

    for ss in synsets:
        nodes.append({
            "source_id": ss.name(),
            "name": ss.lemma_names()[0].replace("_", " "),
            "notes": (ss.definition() or "")[:500] or None,
        })
        parents = ss.hypernyms() + ss.instance_hypernyms()
        if not parents:
            # Top-level synset → attach to graph $ROOT$
            edges.append(("$ROOT$", ss.name()))
        else:
            if len(parents) > 1:
                poly_count += 1
            for p in parents:
                if p.name() in name_set:
                    edges.append((p.name(), ss.name()))
                else:
                    edges.append(("$ROOT$", ss.name()))

    print(f"  Nodes: {len(nodes):,}   Edges: {len(edges):,}   "
          f"Polyhierarchy nodes: {poly_count:,}")
    return nodes, edges


def _collect_bfs(max_nodes: int) -> tuple[list[dict], list[tuple[str, str]]]:
    """BFS from entity.n.01, collecting up to *max_nodes* synsets."""
    from nltk.corpus import wordnet as wn

    root_ss = wn.synset("entity.n.01")
    visited: set[str] = {root_ss.name()}
    queue: deque = deque([root_ss])
    ordered: list = []

    print(f"  BFS from entity.n.01 (limit {max_nodes:,}) …", end="", flush=True)
    while queue and len(ordered) < max_nodes:
        ss = queue.popleft()
        ordered.append(ss)
        for hypo in ss.hyponyms() + ss.instance_hyponyms():
            if hypo.name() not in visited:
                visited.add(hypo.name())
                queue.append(hypo)
    print(f" {len(ordered):,} nodes collected")

    name_set = {ss.name() for ss in ordered}
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []
    poly_count = 0

    for ss in ordered:
        nodes.append({
            "source_id": ss.name(),
            "name": ss.lemma_names()[0].replace("_", " "),
            "notes": (ss.definition() or "")[:500] or None,
        })
        parents = ss.hypernyms() + ss.instance_hypernyms()
        if not parents:
            edges.append(("$ROOT$", ss.name()))
        else:
            if len(parents) > 1:
                poly_count += 1
            for p in parents:
                if p.name() in name_set:
                    edges.append((p.name(), ss.name()))
                # If parent not in BFS set, omit (keeps the subgraph clean)

    print(f"  Nodes: {len(nodes):,}   Edges: {len(edges):,}   "
          f"Polyhierarchy nodes: {poly_count:,}")
    return nodes, edges


# ── Ingest logic ──────────────────────────────────────────────────────────────

def ingest(
    base: str,
    graph_name: str,
    actor_id: str,
    dry_run: bool,
    max_nodes: int,
) -> None:
    _ensure_nltk()

    if max_nodes > 0:
        nodes, edges = _collect_bfs(max_nodes)
    else:
        nodes, edges = _collect_all_nouns()

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
    mode_note = (f"BFS subtree, {max_nodes:,} nodes" if max_nodes > 0
                 else f"full noun hierarchy, {len(nodes):,} synsets")
    status, graph = _post(
        f"{base}/api/v1/graphs",
        {"name": graph_name,
         "notes": f"WordNet 3.1 noun IS-A hierarchy (Princeton). {mode_note}."},
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
        description="Ingest WordNet English noun hierarchy into Banyan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python utils/ingest_wordnet.py                        # full ~82K\n"
            "  python utils/ingest_wordnet.py --max-nodes 1000       # BFS 1K\n"
            "  python utils/ingest_wordnet.py --max-nodes 5000 --dry-run\n"
        ),
    )
    p.add_argument("--base-url",    default="http://localhost:8000")
    p.add_argument("--graph-name",  default=DEFAULT_GRAPH_NAME)
    p.add_argument("--actor-id",    default="ingest")
    p.add_argument("--max-nodes",   type=int, default=0,
                   help="Limit to N nodes via BFS from entity.n.01.  "
                        "0 = all ~82 000 noun synsets (default).")
    p.add_argument("--dry-run",     action="store_true",
                   help="Collect WordNet data and print stats, but make no API calls")
    args = p.parse_args()
    ingest(
        base=args.base_url,
        graph_name=args.graph_name,
        actor_id=args.actor_id,
        dry_run=args.dry_run,
        max_nodes=args.max_nodes,
    )


if __name__ == "__main__":
    main()
