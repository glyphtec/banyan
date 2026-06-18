"""
Banyan sample taxonomy — Dewey Decimal Classification  (10² example, ~110 nodes)

Top two levels of the Dewey Decimal System:
  10 main classes  (000s – 900s)
  100 divisions    (000 – 990, 10 per main class)

Total: 110 nodes, strict two-level hierarchy, no polyhierarchy.
Used to validate basic tree structure, traversal, and subtree queries.

The DDC top-level structure is public knowledge.  No external download needed.

Usage
-----
    python utils/ingest_dewey.py
    python utils/ingest_dewey.py --base-url http://localhost:9000
    python utils/ingest_dewey.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error as _err
import urllib.request as _req

# ── Taxonomy data ─────────────────────────────────────────────────────────────
# (source_id, display_name, parent_source_id | None → graph $ROOT$)

_NODES: list[tuple[str, str, str | None]] = [
    # ── 10 main classes (parent = $ROOT$) ─────────────────────────────────────
    ("DDC.000s", "000s – Computer science, information & general works", None),
    ("DDC.100s", "100s – Philosophy & psychology",                       None),
    ("DDC.200s", "200s – Religion",                                      None),
    ("DDC.300s", "300s – Social sciences",                               None),
    ("DDC.400s", "400s – Language",                                      None),
    ("DDC.500s", "500s – Natural sciences & mathematics",                None),
    ("DDC.600s", "600s – Technology & applied sciences",                 None),
    ("DDC.700s", "700s – Arts & recreation",                             None),
    ("DDC.800s", "800s – Literature",                                    None),
    ("DDC.900s", "900s – History & geography",                           None),

    # ── 000s divisions ────────────────────────────────────────────────────────
    ("DDC.000", "000 – Computer science, information & general works", "DDC.000s"),
    ("DDC.010", "010 – Bibliography",                                  "DDC.000s"),
    ("DDC.020", "020 – Library & information sciences",                "DDC.000s"),
    ("DDC.030", "030 – Encyclopedias & books of facts",                "DDC.000s"),
    ("DDC.040", "040 – Unassigned",                                    "DDC.000s"),
    ("DDC.050", "050 – Magazines, journals & serials",                 "DDC.000s"),
    ("DDC.060", "060 – Associations, organizations & museums",         "DDC.000s"),
    ("DDC.070", "070 – News media, journalism & publishing",           "DDC.000s"),
    ("DDC.080", "080 – Quotations",                                    "DDC.000s"),
    ("DDC.090", "090 – Manuscripts & rare books",                      "DDC.000s"),

    # ── 100s divisions ────────────────────────────────────────────────────────
    ("DDC.100", "100 – Philosophy",                            "DDC.100s"),
    ("DDC.110", "110 – Metaphysics",                           "DDC.100s"),
    ("DDC.120", "120 – Epistemology",                          "DDC.100s"),
    ("DDC.130", "130 – Parapsychology & occultism",            "DDC.100s"),
    ("DDC.140", "140 – Philosophical schools & viewpoints",    "DDC.100s"),
    ("DDC.150", "150 – Psychology",                            "DDC.100s"),
    ("DDC.160", "160 – Logic",                                 "DDC.100s"),
    ("DDC.170", "170 – Ethics",                                "DDC.100s"),
    ("DDC.180", "180 – Ancient, medieval & eastern philosophy","DDC.100s"),
    ("DDC.190", "190 – Modern western philosophy",             "DDC.100s"),

    # ── 200s divisions ────────────────────────────────────────────────────────
    ("DDC.200", "200 – Religion",                                        "DDC.200s"),
    ("DDC.210", "210 – Philosophy & theory of religion",                 "DDC.200s"),
    ("DDC.220", "220 – The Bible",                                       "DDC.200s"),
    ("DDC.230", "230 – Christianity & Christian theology",               "DDC.200s"),
    ("DDC.240", "240 – Christian practice & observance",                 "DDC.200s"),
    ("DDC.250", "250 – Christian pastoral practice & religious orders",  "DDC.200s"),
    ("DDC.260", "260 – Christian social & ecclesiastical theology",      "DDC.200s"),
    ("DDC.270", "270 – History of Christianity",                         "DDC.200s"),
    ("DDC.280", "280 – Christian denominations",                         "DDC.200s"),
    ("DDC.290", "290 – Other religions",                                 "DDC.200s"),

    # ── 300s divisions ────────────────────────────────────────────────────────
    ("DDC.300", "300 – Social sciences, sociology & anthropology",   "DDC.300s"),
    ("DDC.310", "310 – Statistics",                                  "DDC.300s"),
    ("DDC.320", "320 – Political science & government",              "DDC.300s"),
    ("DDC.330", "330 – Economics",                                   "DDC.300s"),
    ("DDC.340", "340 – Law",                                         "DDC.300s"),
    ("DDC.350", "350 – Public administration & military science",    "DDC.300s"),
    ("DDC.360", "360 – Social problems & social services",           "DDC.300s"),
    ("DDC.370", "370 – Education",                                   "DDC.300s"),
    ("DDC.380", "380 – Commerce, communications & transportation",   "DDC.300s"),
    ("DDC.390", "390 – Customs, etiquette & folklore",               "DDC.300s"),

    # ── 400s divisions ────────────────────────────────────────────────────────
    ("DDC.400", "400 – Language",                          "DDC.400s"),
    ("DDC.410", "410 – Linguistics",                       "DDC.400s"),
    ("DDC.420", "420 – English & Old English languages",   "DDC.400s"),
    ("DDC.430", "430 – German & related languages",        "DDC.400s"),
    ("DDC.440", "440 – French & related languages",        "DDC.400s"),
    ("DDC.450", "450 – Italian, Romanian & related",       "DDC.400s"),
    ("DDC.460", "460 – Spanish & Portuguese languages",    "DDC.400s"),
    ("DDC.470", "470 – Latin & Italic languages",          "DDC.400s"),
    ("DDC.480", "480 – Classical & modern Greek",          "DDC.400s"),
    ("DDC.490", "490 – Other languages",                   "DDC.400s"),

    # ── 500s divisions ────────────────────────────────────────────────────────
    ("DDC.500", "500 – Science",                        "DDC.500s"),
    ("DDC.510", "510 – Mathematics",                    "DDC.500s"),
    ("DDC.520", "520 – Astronomy",                      "DDC.500s"),
    ("DDC.530", "530 – Physics",                        "DDC.500s"),
    ("DDC.540", "540 – Chemistry & allied sciences",    "DDC.500s"),
    ("DDC.550", "550 – Earth sciences & geology",       "DDC.500s"),
    ("DDC.560", "560 – Fossils & prehistoric life",     "DDC.500s"),
    ("DDC.570", "570 – Biology & life sciences",        "DDC.500s"),
    ("DDC.580", "580 – Plants (Botany)",                "DDC.500s"),
    ("DDC.590", "590 – Animals (Zoology)",              "DDC.500s"),

    # ── 600s divisions ────────────────────────────────────────────────────────
    ("DDC.600", "600 – Technology",                          "DDC.600s"),
    ("DDC.610", "610 – Medicine & health",                   "DDC.600s"),
    ("DDC.620", "620 – Engineering",                         "DDC.600s"),
    ("DDC.630", "630 – Agriculture",                         "DDC.600s"),
    ("DDC.640", "640 – Home economics & family living",      "DDC.600s"),
    ("DDC.650", "650 – Management & public relations",       "DDC.600s"),
    ("DDC.660", "660 – Chemical engineering",                "DDC.600s"),
    ("DDC.670", "670 – Manufacturing",                       "DDC.600s"),
    ("DDC.680", "680 – Manufacture for specific uses",       "DDC.600s"),
    ("DDC.690", "690 – Building & construction",             "DDC.600s"),

    # ── 700s divisions ────────────────────────────────────────────────────────
    ("DDC.700", "700 – Arts",                                        "DDC.700s"),
    ("DDC.710", "710 – Area planning & landscape architecture",      "DDC.700s"),
    ("DDC.720", "720 – Architecture",                                "DDC.700s"),
    ("DDC.730", "730 – Sculpture, ceramics & metalwork",             "DDC.700s"),
    ("DDC.740", "740 – Drawing & decorative arts",                   "DDC.700s"),
    ("DDC.750", "750 – Painting",                                    "DDC.700s"),
    ("DDC.760", "760 – Graphic arts & printmaking",                  "DDC.700s"),
    ("DDC.770", "770 – Photography & computer art",                  "DDC.700s"),
    ("DDC.780", "780 – Music",                                       "DDC.700s"),
    ("DDC.790", "790 – Sports, games & entertainment",               "DDC.700s"),

    # ── 800s divisions ────────────────────────────────────────────────────────
    ("DDC.800", "800 – Literature, rhetoric & criticism",    "DDC.800s"),
    ("DDC.810", "810 – American literature in English",      "DDC.800s"),
    ("DDC.820", "820 – English literature",                  "DDC.800s"),
    ("DDC.830", "830 – German literature",                   "DDC.800s"),
    ("DDC.840", "840 – French literature",                   "DDC.800s"),
    ("DDC.850", "850 – Italian, Romanian & related",         "DDC.800s"),
    ("DDC.860", "860 – Spanish & Portuguese literatures",    "DDC.800s"),
    ("DDC.870", "870 – Latin & Italic literatures",          "DDC.800s"),
    ("DDC.880", "880 – Classical & modern Greek literature", "DDC.800s"),
    ("DDC.890", "890 – Other literatures",                   "DDC.800s"),

    # ── 900s divisions ────────────────────────────────────────────────────────
    ("DDC.900", "900 – History",                      "DDC.900s"),
    ("DDC.910", "910 – Geography & travel",           "DDC.900s"),
    ("DDC.920", "920 – Biography & genealogy",        "DDC.900s"),
    ("DDC.930", "930 – History of the ancient world", "DDC.900s"),
    ("DDC.940", "940 – History of Europe",            "DDC.900s"),
    ("DDC.950", "950 – History of Asia",              "DDC.900s"),
    ("DDC.960", "960 – History of Africa",            "DDC.900s"),
    ("DDC.970", "970 – History of North America",     "DDC.900s"),
    ("DDC.980", "980 – History of South America",     "DDC.900s"),
    ("DDC.990", "990 – History of other areas",       "DDC.900s"),
]

DEFAULT_GRAPH_NAME = "Dewey Decimal Classification"


# ── HTTP helpers (identical to other ingest scripts) ─────────────────────────

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
    main_classes = [n for n in _NODES if n[2] is None]
    divisions = [n for n in _NODES if n[2] is not None]
    print(f"Dewey Decimal Classification: {len(_NODES)} nodes "
          f"({len(main_classes)} main classes, {len(divisions)} divisions)")
    print("  Strict two-level hierarchy, no polyhierarchy.")

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
        sys.exit("HIERARCHICAL link type not found. Is the database bootstrapped?")

    # ── Create graph ──────────────────────────────────────────────────────────
    status, graph = _post(
        f"{base}/api/v1/graphs",
        {"name": graph_name,
         "notes": "Dewey Decimal Classification — top 2 levels (10² example)"},
        actor_id,
    )
    if status != 201:
        _die(status, graph, "create graph")
    graph_id = graph["graph_id"]
    print(f"  Graph created: {graph_id}")

    # ── Single batch: ADD_NODE then CREATE_LINK ───────────────────────────────
    node_ops = [
        {"verb": "ADD_NODE", "data": {"source_id": sid, "name": name}}
        for sid, name, _ in _NODES
    ]
    link_ops = [
        {"verb": "CREATE_LINK",
         "data": {"from_source_id": parent_sid if parent_sid else "$ROOT$",
                  "to_source_id": sid}}
        for sid, _, parent_sid in _NODES
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
    print(f"  Nodes added: {result['nodes_added']}  Links created: {result['links_created']}")
    print(f"Done. Graph '{graph_name}' ingested successfully.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Ingest Dewey Decimal Classification (top 2 levels) into Banyan"
    )
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--graph-name", default=DEFAULT_GRAPH_NAME)
    p.add_argument("--actor-id", default="ingest")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without making any API calls")
    args = p.parse_args()
    ingest(args.base_url, args.graph_name, args.actor_id, args.dry_run)


if __name__ == "__main__":
    main()
