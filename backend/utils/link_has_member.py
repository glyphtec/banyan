#!/usr/bin/env python3
"""
link_has_member.py — Generate a Banyan batch document asserting HAS_MEMBER
links from Gravity L2 activity nodes to clinical code nodes in the SNOMED CT
and ICD-10-CM graphs.

Reads:
  backend/data/gravity/vsac_oid_manifest.json
  backend/data/gravity/vsac/*.json  (VSAC expansion cache)

Writes:
  backend/data/gravity/has_member_links.batch.json

No network calls.  No database writes.  Review the output before submitting.

Submit with:
    python utils/run_batch.py backend/data/gravity/has_member_links.batch.json

Batch document format
---------------------
This file uses a Banyan "named batch" format.  Graph names and link type names
are stored as human-readable strings; run_batch.py resolves them to UUIDs at
submission time by calling the API.

    {
      "banyan_batch_version": "1.0",
      "from_graph_name": "Gravity SDOH Clinical Care STU 2.3",
      "actor_id": "system:ingest",
      "default_link_type_name": "HAS_MEMBER",
      "link_operations": [
          {
            "verb": "CREATE_LINK",
            "data": {
              "from_source_id": "sdoh:food-insecurity/diagnoses",
              "to_source_id":   "http://snomed.info/sct|73211009",
              "to_graph_name":  "SNOMED CT SDOH Slice",
              "metadata": {
                "link_provenance": "derived",
                "vsac_oid": "2.16.840.1.113762.1.4.1247.17"
              }
            }
          }
      ]
    }

Link scope
----------
HAS_MEMBER links are generated only where the target code is guaranteed to
exist in the destination graph:

  SNOMED CT   — activities: diagnoses, goals, findings
                (matches SEED_ACTIVITIES in ingest_snomed_sdoh.py)
  ICD-10-CM   — activities: diagnoses
                (matches SEED_ACTIVITIES in ingest_icd10.py)

Activities outside these sets (procedures, service-requests, screening
assessments) are skipped — their codes were not ingested into code graphs.

Source ID conventions
---------------------
  Gravity L2 :  sdoh:{domain}/{activity-slug}
  SNOMED CT   :  http://snomed.info/sct|{code}
  ICD-10-CM   :  http://hl7.org/fhir/sid/icd-10-cm|{code}
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

REPO_ROOT     = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "gravity" / "vsac_oid_manifest.json"
VSAC_CACHE    = REPO_ROOT / "data" / "gravity" / "vsac"
OUTPUT_PATH   = REPO_ROOT / "data" / "gravity" / "has_member_links.batch.json"

GRAVITY_GRAPH_NAME = "Gravity SDOH Clinical Care STU 2.3"
SNOMED_GRAPH_NAME  = "SNOMED CT SDOH Slice"
ICD10_GRAPH_NAME   = "ICD-10-CM SDOH Slice"

SNOMED_SYSTEM = "http://snomed.info/sct"
ICD10_SYSTEM  = "http://hl7.org/fhir/sid/icd-10-cm"

# Activities whose SNOMED codes were ingested into the SNOMED graph.
SNOMED_ACTIVITIES = {"diagnoses", "goals", "findings"}
# Activities whose ICD-10-CM codes were ingested into the ICD-10 graph.
ICD10_ACTIVITIES  = {"diagnoses"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def activity_slug(vs_label: str) -> str:
    """Derive the activity slug from a value set label.

    Strips the parenthetical code-system suffix, lower-cases, and
    replaces non-alphanumeric runs with hyphens.

    Examples:
      "Diagnoses (ICD-10-CM, SNOMED CT)"  → "diagnoses"
      "Goals (SNOMED CT)"                 → "goals"
      "Screening Assessments And Questions (LOINC)" → "screening-assessments-and-questions"
    """
    label = re.sub(r"\s*\([^)]+\)", "", vs_label).strip()
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_batch(manifest: dict) -> dict:
    link_ops: list[dict] = []
    skipped_cache_miss = 0
    seen: set[tuple[str, str, str]] = set()   # dedup (from_src, to_src, graph)

    domains = manifest.get("domains", {})

    for domain_key, domain in domains.items():
        for vs_label, oid in domain.get("value_sets", {}).items():
            if not oid:
                continue

            slug = activity_slug(vs_label)

            # Determine which code systems are in scope for this activity
            in_scope_systems: dict[str, str] = {}
            if slug in SNOMED_ACTIVITIES:
                in_scope_systems[SNOMED_SYSTEM] = SNOMED_GRAPH_NAME
            if slug in ICD10_ACTIVITIES:
                in_scope_systems[ICD10_SYSTEM] = ICD10_GRAPH_NAME

            if not in_scope_systems:
                continue   # e.g. procedures, service-requests — skip

            cache_file = VSAC_CACHE / f"{oid}.json"
            if not cache_file.exists():
                print(
                    f"  WARNING: cache miss {oid} ({domain_key}/{slug})"
                    f" — run fetch_vsac_expansions.py first"
                )
                skipped_cache_miss += 1
                continue

            with cache_file.open(encoding="utf-8") as f:
                cached = json.load(f)

            from_source_id = f"sdoh:{domain_key}/{slug}"

            for entry in cached.get("codes", []):
                system = entry.get("system", "")
                code   = entry.get("code", "")
                if not code or system not in in_scope_systems:
                    continue

                to_graph_name  = in_scope_systems[system]
                to_source_id   = f"{system}|{code}"

                key = (from_source_id, to_source_id, to_graph_name)
                if key in seen:
                    continue
                seen.add(key)

                link_ops.append({
                    "verb": "CREATE_LINK",
                    "data": {
                        "from_source_id": from_source_id,
                        "to_source_id":   to_source_id,
                        "to_graph_name":  to_graph_name,
                        "metadata": {
                            "link_provenance": "derived",
                            "vsac_oid":        oid,
                        },
                    },
                })

    return {
        "banyan_batch_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from_graph_name": GRAVITY_GRAPH_NAME,
        "actor_id": "system:ingest",
        "default_link_type_name": "HAS_MEMBER",
        "link_operations": link_ops,
        "_meta": {
            "skipped_cache_miss": skipped_cache_miss,
            "total_links": len(link_ops),
        },
    }


def main() -> None:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    if not VSAC_CACHE.exists() or not any(VSAC_CACHE.glob("*.json")):
        print(
            "ERROR: VSAC cache is empty.  Run fetch_vsac_expansions.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Reading VSAC manifest ...")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    print("Building HAS_MEMBER link operations ...")
    batch = build_batch(manifest)

    ops      = batch["link_operations"]
    snomed_n = sum(1 for o in ops if o["data"]["to_graph_name"] == SNOMED_GRAPH_NAME)
    icd10_n  = sum(1 for o in ops if o["data"]["to_graph_name"] == ICD10_GRAPH_NAME)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nWritten: {OUTPUT_PATH}")
    print(f"  Total link operations : {len(ops)}")
    print(f"    → SNOMED CT links   : {snomed_n}")
    print(f"    → ICD-10-CM links   : {icd10_n}")
    if batch["_meta"]["skipped_cache_miss"]:
        print(f"  Skipped (cache miss)  : {batch['_meta']['skipped_cache_miss']}")


if __name__ == "__main__":
    main()
