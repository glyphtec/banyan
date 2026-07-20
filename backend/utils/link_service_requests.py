#!/usr/bin/env python3
"""
link_service_requests.py — Generate a Banyan batch document asserting
HAS_MEMBER links from Gravity L2 "Service Requests" activity nodes to
SNOMED CT and HCPCS code nodes in the SNOMED SDOH Service Requests Slice.

Reads:
  backend/data/gravity/vsac_oid_manifest.json
  backend/data/gravity/vsac/*.json  (VSAC expansion cache)

Writes:
  backend/data/gravity/service_request_links.batch.json

No network calls.  No database writes.  Review the output before submitting.

Prerequisites
-------------
The SNOMED SDOH Service Requests Slice graph must already be imported:
  python utils/ingest_snomed_sr.py
  python utils/import_graph.py backend/data/gravity/snomed_sr.banyan.json

Submit the batch with:
  python utils/run_batch.py backend/data/gravity/service_request_links.batch.json

Source ID conventions
---------------------
  Gravity L2        :  sdoh:{domain}/service-requests
  SNOMED CT         :  http://snomed.info/sct|{code}
  HCPCS Level II    :  http://www.nlm.nih.gov/research/umls/hcpcs|{code}

CPT codes are excluded (AMA-proprietary license required).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "gravity" / "vsac_oid_manifest.json"
VSAC_CACHE    = REPO_ROOT / "data" / "gravity" / "vsac"
OUTPUT_PATH   = REPO_ROOT / "data" / "gravity" / "service_request_links.batch.json"

GRAVITY_GRAPH_NAME = "Gravity SDOH Clinical Care STU 2.3"
SR_GRAPH_NAME      = "SNOMED SDOH Service Requests Slice"

SNOMED_SYSTEM = "http://snomed.info/sct"
HCPCS_SYSTEM  = "http://www.nlm.nih.gov/research/umls/hcpcs"


def activity_slug(vs_label: str) -> str:
    label = re.sub(r"\s*\([^)]+\)", "", vs_label).strip()
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def build_batch(manifest: dict) -> dict:
    link_ops: list[dict] = []
    skipped_cache_miss = 0
    seen: set[tuple[str, str]] = set()   # dedup (from_src, to_src)

    domains = manifest.get("domains", {})

    for domain_key, domain in domains.items():
        for vs_label, oid in domain.get("value_sets", {}).items():
            if activity_slug(vs_label) != "service-requests":
                continue

            cache_file = VSAC_CACHE / f"{oid}.json"
            if not cache_file.exists():
                print(f"  WARNING: cache miss {oid} ({domain_key}) — run fetch_vsac_expansions.py first",
                      file=sys.stderr)
                skipped_cache_miss += 1
                continue

            with cache_file.open(encoding="utf-8") as f:
                cached = json.load(f)

            from_source_id = f"sdoh:{domain_key}/service-requests"

            for entry in cached.get("codes", []):
                system  = entry.get("system", "")
                code    = entry.get("code", "")
                if not code:
                    continue

                # Determine target source_id — skip CPT
                if "snomed" in system.lower() or system.endswith("/sct"):
                    to_source_id = f"{SNOMED_SYSTEM}|{code}"
                elif "hcpcs" in system.lower() or "HCPCS" in system:
                    to_source_id = f"{HCPCS_SYSTEM}|{code}"
                else:
                    continue   # CPT or unknown — skip

                key = (from_source_id, to_source_id)
                if key in seen:
                    continue
                seen.add(key)

                link_ops.append({
                    "verb": "CREATE_LINK",
                    "data": {
                        "from_source_id": from_source_id,
                        "to_source_id":   to_source_id,
                        "to_graph_name":  SR_GRAPH_NAME,
                        "metadata": {
                            "link_provenance": "derived",
                            "vsac_oid": oid,
                        },
                    },
                })

    if skipped_cache_miss:
        print(f"  Skipped {skipped_cache_miss} OID(s) due to cache miss.", file=sys.stderr)

    return {
        "banyan_batch_version": "1.0",
        "from_graph_name":       GRAVITY_GRAPH_NAME,
        "actor_id":              "system:ingest",
        "default_link_type_name": "HAS_MEMBER",
        "link_operations":       link_ops,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator":    "utils/link_service_requests.py",
            "total_links":  len(link_ops),
            "note":         "CPT codes excluded (AMA license required). SNOMED CT + HCPCS L2 only.",
        },
    }


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    print("Building service-request HAS_MEMBER batch...")
    batch = build_batch(manifest)

    total = len(batch["link_operations"])
    print(f"  Generated {total} HAS_MEMBER link operations")

    OUTPUT_PATH.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")
    print()
    print("Next step:")
    print(f"  python utils/run_batch.py {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
