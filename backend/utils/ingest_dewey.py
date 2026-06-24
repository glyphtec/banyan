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
    # Write export JSON to stdout:
    python utils/ingest_dewey.py

    # Write to a file:
    python utils/ingest_dewey.py --output data/dewey.json

    # Load into a running Banyan instance:
    python utils/ingest_dewey.py | python utils/import_graph.py -
    python utils/import_graph.py data/dewey.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

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


# ── Generator ─────────────────────────────────────────────────────────────────

def generate(graph_name: str = DEFAULT_GRAPH_NAME) -> dict:
    """Return a Banyan v1.1 export document for the Dewey Decimal top 2 levels."""
    nodes = [
        {"source_id": sid, "name": name}
        for sid, name, _ in _NODES
    ]
    links = [
        {
            "from_source_id": parent_sid if parent_sid else "$ROOT$",
            "to_source_id": sid,
            "link_type_name": "HIERARCHICAL",
        }
        for sid, _, parent_sid in _NODES
    ]
    main_classes = sum(1 for _, _, p in _NODES if p is None)
    divisions = len(_NODES) - main_classes
    return {
        "banyan_export_version": "1.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "name": graph_name,
            "notes": (
                f"Dewey Decimal Classification — top 2 levels "
                f"({main_classes} main classes, {divisions} divisions; "
                f"strict two-level hierarchy, no polyhierarchy)"
            ),
        },
        "nodes": nodes,
        "links": links,
        "cross_graph_links": [],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate a Banyan export JSON for the Dewey Decimal Classification."
    )
    p.add_argument("--graph-name", default=DEFAULT_GRAPH_NAME,
                   help="Graph name to embed in the export document")
    p.add_argument("--output", metavar="FILE",
                   help="Write JSON to FILE instead of stdout")
    p.add_argument("--dry-run", action="store_true",
                   help="Print stats only; do not write output")
    args = p.parse_args()

    main_classes = sum(1 for _, _, p in _NODES if p is None)
    divisions = len(_NODES) - main_classes
    print(
        f"Dewey Decimal Classification: {len(_NODES)} nodes "
        f"({main_classes} main classes, {divisions} divisions; no polyhierarchy)",
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
