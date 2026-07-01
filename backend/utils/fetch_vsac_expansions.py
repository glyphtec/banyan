#!/usr/bin/env python3
"""
fetch_vsac_expansions.py — Download and cache VSAC value set expansions.

Reads:  backend/data/gravity/vsac_oid_manifest.json
Writes: backend/data/gravity/vsac/{oid}.json  (one file per OID)

Calls the VSAC FHIR $expand endpoint for every OID in the manifest (domain
value sets + cross-domain groupers).  Each cache file stores the extracted
code list plus provenance metadata from the FHIR response.

Resume-safe: OIDs whose cache file already exists are skipped.  Re-run the
script after a failure and it will pick up where it left off.

Usage
-----
    # API key from environment variable (recommended):
    set UMLS_API_KEY=e4f376d9-...
    python utils/fetch_vsac_expansions.py

    # API key as CLI argument:
    python utils/fetch_vsac_expansions.py --api-key e4f376d9-...

    # Dry-run: print OID list and counts without fetching:
    python utils/fetch_vsac_expansions.py --dry-run

    # Fetch only a specific OID (useful for debugging a single value set):
    python utils/fetch_vsac_expansions.py --only 2.16.840.1.113762.1.4.1247.17

Auth
----
VSAC FHIR API uses HTTP Basic auth: username "apikey", password = UMLS API key.
Obtain your API key from https://uts.nlm.nih.gov/uts/profile after logging in.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error as _err
import urllib.request as _req
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

REPO_ROOT    = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "gravity" / "vsac_oid_manifest.json"
CACHE_DIR    = REPO_ROOT / "data" / "gravity" / "vsac"

VSAC_BASE    = "https://cts.nlm.nih.gov/fhir/ValueSet"
REQUEST_DELAY = 0.5   # seconds between API calls (polite rate limiting)
MAX_RETRIES   = 2


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _auth_header(api_key: str) -> str:
    raw = f"apikey:{api_key}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _fetch_expansion(oid: str, auth: str) -> dict:
    """
    Call VSAC FHIR $expand and return a normalised cache dict.

    Raises urllib.error.HTTPError on non-2xx responses.
    """
    url = f"{VSAC_BASE}/{oid}/$expand"
    req = _req.Request(url, headers={"Authorization": auth, "Accept": "application/json"})

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with _req.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            break
        except _err.HTTPError as exc:
            if exc.code in (401, 403):
                raise  # credential error — no point retrying
            if attempt == MAX_RETRIES:
                raise
            print(f"    HTTP {exc.code} on attempt {attempt}, retrying …")
            time.sleep(2)
        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"    Error on attempt {attempt}: {exc}, retrying …")
            time.sleep(2)

    expansion = body.get("expansion", {})
    contains  = expansion.get("contains", [])

    return {
        "oid":        oid,
        "title":      body.get("title") or body.get("name") or "",
        "version":    body.get("version", ""),
        "status":     body.get("status", ""),
        "total":      expansion.get("total", len(contains)),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "codes": [
            {
                "system":  c.get("system", ""),
                "code":    c.get("code", ""),
                "display": c.get("display", ""),
            }
            for c in contains
        ],
    }


# ---------------------------------------------------------------------------
# OID collection
# ---------------------------------------------------------------------------

def collect_oids(manifest: dict) -> list[tuple[str, str]]:
    """
    Return a list of (label, oid) pairs from all domains + groupers.
    Null OIDs are excluded.
    """
    pairs: list[tuple[str, str]] = []

    for label, oid in manifest.get("groupers", {}).items():
        if oid:
            pairs.append((f"[grouper] {label}", oid))

    for domain_key, domain in manifest.get("domains", {}).items():
        for vs_label, oid in domain.get("value_sets", {}).items():
            if oid:
                pairs.append((f"{domain['label']} / {vs_label}", oid))

    # Deduplicate by OID while preserving first-seen label
    seen: dict[str, str] = {}
    for label, oid in pairs:
        if oid not in seen:
            seen[oid] = label

    return [(label, oid) for oid, label in seen.items()]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Cache VSAC value set expansions locally.")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("UMLS_API_KEY", ""),
        help="UMLS API key (default: UMLS_API_KEY env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print OID list and counts without making API calls",
    )
    parser.add_argument(
        "--only",
        metavar="OID",
        help="Fetch a single OID (overrides full manifest run; useful for debugging)",
    )
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    all_pairs = collect_oids(manifest)

    if args.only:
        all_pairs = [(lbl, oid) for lbl, oid in all_pairs if oid == args.only]
        if not all_pairs:
            print(f"ERROR: OID {args.only!r} not found in manifest.", file=sys.stderr)
            sys.exit(1)

    print(f"OIDs in manifest : {len(all_pairs)}")

    if args.dry_run:
        for label, oid in all_pairs:
            cached = (CACHE_DIR / f"{oid}.json").exists()
            mark = "[cached]" if cached else "[fetch]"
            print(f"  {mark}  {oid}  {label}")
        return

    if not args.api_key:
        print(
            "ERROR: UMLS API key required.\n"
            "  Set UMLS_API_KEY environment variable, or pass --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    auth = _auth_header(args.api_key)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    pending  = [(lbl, oid) for lbl, oid in all_pairs if not (CACHE_DIR / f"{oid}.json").exists()]
    cached   = len(all_pairs) - len(pending)

    print(f"Already cached   : {cached}")
    print(f"To fetch         : {len(pending)}")
    print()

    fetched = 0
    skipped = 0
    errors  = 0

    for i, (label, oid) in enumerate(pending, 1):
        cache_path = CACHE_DIR / f"{oid}.json"
        print(f"[{i}/{len(pending)}] {oid}  {label}")

        try:
            data = _fetch_expansion(oid, auth)
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            code_counts = {}
            for c in data["codes"]:
                sys_short = c["system"].split("/")[-1].split("|")[-1]
                code_counts[sys_short] = code_counts.get(sys_short, 0) + 1
            summary = ", ".join(f"{v} {k}" for k, v in code_counts.items())
            print(f"    -> {data['total']} codes  ({summary})")
            fetched += 1
        except _err.HTTPError as exc:
            if exc.code == 404:
                print(f"    -> 404 Not Found (OID not in VSAC — skipping)")
                skipped += 1
            elif exc.code in (401, 403):
                print(f"\nERROR: Authentication failed (HTTP {exc.code}). Check your API key.", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"    -> HTTP {exc.code} error — skipping")
                errors += 1
        except Exception as exc:
            print(f"    -> ERROR: {exc} — skipping")
            errors += 1

        if i < len(pending):
            time.sleep(REQUEST_DELAY)

    print()
    print("Done.")
    print(f"  Fetched  : {fetched}")
    print(f"  Skipped  : {skipped}  (404 / not in VSAC)")
    print(f"  Errors   : {errors}")
    print(f"  Cache    : {CACHE_DIR}")

    # Summary: code counts by system across all cached files
    print()
    print("Cache summary (all cached files):")
    system_totals: dict[str, int] = {}
    total_value_sets = 0
    for cache_file in sorted(CACHE_DIR.glob("*.json")):
        with cache_file.open(encoding="utf-8") as f:
            cached_data = json.load(f)
        total_value_sets += 1
        for c in cached_data.get("codes", []):
            sys_key = c.get("system", "unknown")
            system_totals[sys_key] = system_totals.get(sys_key, 0) + 1
    print(f"  Value sets cached : {total_value_sets}")
    for sys_url, count in sorted(system_totals.items(), key=lambda x: -x[1]):
        print(f"    {count:5d}  {sys_url}")


if __name__ == "__main__":
    main()
