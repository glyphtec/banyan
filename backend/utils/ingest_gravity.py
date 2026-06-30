#!/usr/bin/env python3
"""
ingest_gravity.py — Generate a Banyan export document for the Gravity SDOH
Clinical Care STU 2.3 taxonomy.

Reads:  backend/data/gravity/vsac_oid_manifest.json
Writes: backend/data/gravity/gravity_sdoh_stu23.banyan.json

No network calls.  No database writes.  Review the output before importing.

Import with:
    python utils/import_graph.py backend/data/gravity/gravity_sdoh_stu23.banyan.json

Graph structure
---------------
  $ROOT$
  └── <Domain L1>          source_id: sdoh:{domain-key}
        └── <Activity L2>  source_id: sdoh:{domain-key}/{activity-slug}

All links are HIERARCHICAL.  Cross-graph links (MEMBER_OF to ICD-10-CM / SNOMED
nodes) are built separately by link_gravity_codes.py after the code graphs exist.

Node metadata
-------------
L1 domain node:
  { level, ig_category_code, gravity_version, note? }

L2 value-set type node:
  { level, domain, activity, oid, vsac_url, code_systems, grouper_oid? }

  grouper_oid: OID of the pan-domain VSAC grouper that aggregates this activity
  type across all 28 domains.  Stored as metadata only — not a structural node.
  The "Conditions" grouper is mapped to the "diagnoses" activity (different label,
  same concept — one explicit override in GROUPER_OVERRIDES below).

Value sets with a null OID in the manifest are skipped (not yet published).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "gravity" / "vsac_oid_manifest.json"
OUTPUT_PATH   = REPO_ROOT / "data" / "gravity" / "gravity_sdoh_stu23.banyan.json"

VSAC_BASE        = "https://cts.nlm.nih.gov/fhir/ValueSet"
GRAVITY_VERSION  = "STU 2.3"
ROOT_SOURCE_ID   = "$ROOT$"

# ---------------------------------------------------------------------------
# Grouper label → activity slug override table
#
# Grouper labels are matched to per-domain activity labels by slug.  The one
# case where they differ: the cross-domain grouper is named "Conditions
# (ICD-10-CM, SNOMED CT)" while individual domains call the same activity
# "Diagnoses (ICD-10-CM, SNOMED CT)".
# ---------------------------------------------------------------------------

GROUPER_OVERRIDES: dict[str, str] = {
    "conditions": "diagnoses",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slug(label: str) -> str:
    """
    Convert a Gravity value-set type label to a stable URL-safe slug.

    Strips the parenthetical code-system annotation, lowercases, and
    hyphenates.  Examples:
        "Diagnoses (ICD-10-CM, SNOMED CT)"           -> "diagnoses"
        "Screening Assessments And Questions (LOINC)" -> "screening-assessments-and-questions"
        "Service Requests (CPT, HCPCS, SNOMED CT)"   -> "service-requests"
    """
    s = re.sub(r"\s*\([^)]+\)", "", label).strip()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def display_name(label: str) -> str:
    """Strip the parenthetical from a label to get a clean human name."""
    return re.sub(r"\s*\([^)]+\)", "", label).strip()


def extract_code_systems(label: str) -> list[str]:
    """
    Extract the code system list from the parenthetical in a value-set label.

        "Diagnoses (ICD-10-CM, SNOMED CT)" -> ["ICD-10-CM", "SNOMED CT"]
        "Goals (SNOMED CT)"                -> ["SNOMED CT"]
        "Screening Assessments (LOINC)"    -> ["LOINC"]
        Labels without a parenthetical     -> []
    """
    m = re.search(r"\(([^)]+)\)", label)
    if not m:
        return []
    return [cs.strip() for cs in m.group(1).split(",")]


def build_grouper_map(groupers: dict[str, str | None]) -> dict[str, str]:
    """
    Return a map of activity_slug -> grouper_oid.

    Most grouper labels slug-match their per-domain activity label directly.
    Entries in GROUPER_OVERRIDES redirect mismatched grouper slugs to the
    correct activity slug.
    """
    mapping: dict[str, str] = {}
    for label, oid in groupers.items():
        if not oid:
            continue
        s = slug(label)
        target = GROUPER_OVERRIDES.get(s, s)
        mapping[target] = oid
    return mapping


# ---------------------------------------------------------------------------
# Document builder
# ---------------------------------------------------------------------------

def build_export_doc(manifest: dict) -> dict:
    grouper_map = build_grouper_map(manifest.get("groupers", {}))

    nodes: list[dict] = []
    links: list[dict] = []

    for domain_key, domain in manifest["domains"].items():
        label       = domain["label"]
        ig_code     = domain.get("ig_category_code")   # null for newer domains
        domain_note = domain.get("note")

        # ── L1 domain node ────────────────────────────────────────────────
        l1_source_id = f"sdoh:{domain_key}"
        l1_metadata: dict = {
            "level": "L1",
            "gravity_version": GRAVITY_VERSION,
        }
        if ig_code is not None:
            l1_metadata["ig_category_code"] = ig_code
        if domain_note:
            l1_metadata["note"] = domain_note

        nodes.append({
            "source_id": l1_source_id,
            "name": label,
            "metadata": l1_metadata,
        })

        # $ROOT$ -> L1
        links.append({
            "from_source_id": ROOT_SOURCE_ID,
            "to_source_id":   l1_source_id,
            "link_type_name": "HIERARCHICAL",
        })

        # ── L2 value-set type nodes ────────────────────────────────────────
        for vs_label, oid in domain.get("value_sets", {}).items():
            if not oid:
                # Value set not yet published (e.g. incarceration screening on hold)
                continue

            activity     = slug(vs_label)
            l2_source_id = f"sdoh:{domain_key}/{activity}"

            l2_metadata: dict = {
                "level":        "L2",
                "domain":       domain_key,
                "activity":     activity,
                "oid":          oid,
                "vsac_url":     f"{VSAC_BASE}/{oid}",
                "code_systems": extract_code_systems(vs_label),
            }
            grouper_oid = grouper_map.get(activity)
            if grouper_oid:
                l2_metadata["grouper_oid"] = grouper_oid

            nodes.append({
                "source_id": l2_source_id,
                "name":      display_name(vs_label),
                "metadata":  l2_metadata,
            })

            # L1 -> L2
            links.append({
                "from_source_id": l1_source_id,
                "to_source_id":   l2_source_id,
                "link_type_name": "HIERARCHICAL",
            })

    return {
        "banyan_export_version": "1.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "name": "Gravity SDOH Clinical Care STU 2.3",
            "notes": (
                "SDOH Clinical Care Implementation Guide STU 2.3 — social-risk "
                "domains and value set types. Source: HL7/SIREN Gravity Project. "
                "OIDs from VSAC (https://vsac.nlm.nih.gov). "
                "Generated by utils/ingest_gravity.py."
            ),
        },
        "nodes": nodes,
        "links": links,
        "cross_graph_links": [],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    doc = build_export_doc(manifest)

    l1_nodes    = [n for n in doc["nodes"] if n["metadata"]["level"] == "L1"]
    l2_nodes    = [n for n in doc["nodes"] if n["metadata"]["level"] == "L2"]
    root_links  = [lk for lk in doc["links"] if lk["from_source_id"] == ROOT_SOURCE_ID]
    hier_links  = [lk for lk in doc["links"] if lk["from_source_id"] != ROOT_SOURCE_ID]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(f"Written: {OUTPUT_PATH}")
    print(f"  Domains (L1)         : {len(l1_nodes)}")
    print(f"  Value set types (L2) : {len(l2_nodes)}")
    print(f"  $ROOT$→L1 links      : {len(root_links)}")
    print(f"  L1→L2 links          : {len(hier_links)}")
    print(f"  Total nodes          : {len(doc['nodes'])}")
    print(f"  Total links          : {len(doc['links'])}")


if __name__ == "__main__":
    main()
