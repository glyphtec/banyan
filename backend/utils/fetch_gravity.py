#!/usr/bin/env python3
"""
fetch_gravity.py — Download raw Gravity SDOH public data artifacts.

Downloads (no UMLS required):
  1. FHIR IG package (hl7.fhir.us.sdoh-clinicalcare 2.3.0) — all JSON
     StructureDefinitions, CodeSystems, ValueSets, Examples
  2. data_dictionary.json from GitHub
  3. VSAC OID manifest (built from Gravity Confluence page, no auth needed)

Output layout:
  backend/data/gravity/
    ig_package/          extracted FHIR IG npm package (*.json)
    data_dictionary.json
    vsac_oid_manifest.json
    manifest.json        summary of what was fetched and when
"""

import io
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent / "data" / "gravity"
IG_PACKAGE_DIR = BASE_DIR / "ig_package"

IG_PACKAGE_URL = (
    "https://packages.simplifier.net/hl7.fhir.us.sdoh-clinicalcare"
    "/-/hl7.fhir.us.sdoh-clinicalcare-2.3.0.tgz"
)
DATA_DICT_URL = (
    "https://raw.githubusercontent.com/HL7/fhir-sdoh-clinicalcare"
    "/master/data-dictionary/data_dictionary.json"
)

# ---------------------------------------------------------------------------
# VSAC OID manifest — built from Gravity Confluence public page
# (https://confluence.hl7.org/display/GRAV/Social+Risk+Terminology+Value+Sets)
# No auth needed to read the OIDs; auth needed to expand the value sets.
# Updated: 2026-06-26 (Confluence last updated 2026-01-08)
# ---------------------------------------------------------------------------

VSAC_OID_MANIFEST = {
    "_meta": {
        "source": "https://confluence.hl7.org/display/GRAV/Social+Risk+Terminology+Value+Sets",
        "confluence_last_updated": "2026-01-08",
        "fetched": "2026-06-26",
        "note": (
            "OIDs are public. Value set expansions require free NLM/UMLS account. "
            "VSAC FHIR API: https://cts.nlm.nih.gov/fhir/ValueSet/{oid}/$expand"
        ),
    },
    "groupers": {
        "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.206",
        "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.126",
        "Conditions (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1196.788",
        "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.71",
        "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1196.789",
        "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1196.790",
    },
    "domains": {
        "food-insecurity": {
            "label": "Food Insecurity",
            "ig_category_code": "food-insecurity",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.194",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.127",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3484",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.174",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.17",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.16",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.7",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.11",
            },
        },
        "housing-instability": {
            "label": "Housing Instability",
            "ig_category_code": "housing-instability",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.197",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.130",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3487",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.177",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.24",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.161",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.44",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.45",
            },
        },
        "homelessness": {
            "label": "Homelessness",
            "ig_category_code": "homelessness",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.196",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.129",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3486",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.176",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.18",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.159",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.20",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.21",
            },
        },
        "inadequate-housing": {
            "label": "Inadequate Housing",
            "ig_category_code": "inadequate-housing",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3520",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.131",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.167",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.178",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.48",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.50",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.52",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.53",
            },
        },
        "transportation-insecurity": {
            "label": "Transportation Insecurity",
            "ig_category_code": "transportation-insecurity",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.204",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.128",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.170",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.182",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.26",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.163",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.27",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.28",
            },
        },
        "financial-insecurity": {
            "label": "Financial Insecurity",
            "ig_category_code": "financial-insecurity",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.193",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.138",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3483",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.173",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.108",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.30",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.32",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.31",
            },
        },
        "material-hardship": {
            "label": "Material Hardship",
            "ig_category_code": "material-hardship",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.200",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.139",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.168",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.180",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.35",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.37",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.39",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.38",
            },
        },
        "employment-status": {
            "label": "Employment Status (Unemployment)",
            "ig_category_code": "employment-status",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.205",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.133",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.171",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.183",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.42",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.70",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.59",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.60",
            },
        },
        "educational-attainment": {
            "label": "Educational Attainment (Less Than High School)",
            "ig_category_code": "educational-attainment",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.199",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.132",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3488",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.179",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.103",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.55",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.56",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.57",
            },
        },
        "veteran-status": {
            "label": "Veteran Status",
            "ig_category_code": "veteran-status",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.192",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.134",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.172",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.184",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.78",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.215",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.90",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.91",
            },
        },
        "stress": {
            "label": "Stress",
            "ig_category_code": "stress",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.203",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.136",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.169",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.181",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.75",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.86",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.87",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.92",
            },
        },
        "social-connection": {
            "label": "Social Connection",
            "ig_category_code": "social-connection",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.202",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.135",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.212",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.210",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.81",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.89",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.94",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.95",
            },
        },
        "intimate-partner-violence": {
            "label": "Intimate Partner Violence",
            "ig_category_code": "intimate-partner-violence",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.198",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.140",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.211",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.209",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.84",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.100",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.97",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.98",
            },
        },
        "elder-abuse": {
            "label": "Elder Abuse",
            "ig_category_code": "elder-abuse",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.191",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.144",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.189",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.190",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.63",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.65",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.67",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.68",
            },
        },
        "personal-health-literacy": {
            "label": "Personal Health Literacy",
            "ig_category_code": "personal-health-literacy",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.195",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.141",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3485",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.175",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.116",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.117",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.118",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.119",
            },
        },
        "medical-cost-burden": {
            "label": "Medical Cost Burden",
            "ig_category_code": "medical-cost-burden",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.201",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.142",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.188",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.187",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.153",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.120",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.122",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.123",
            },
        },
        "health-insurance-coverage-status": {
            "label": "Health Insurance Coverage Status",
            "ig_category_code": "health-insurance-coverage-status",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1196.3519",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.143",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.186",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.185",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.148",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.121",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.125",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.124",
            },
        },
        "digital-literacy": {
            "label": "Digital Literacy",
            "ig_category_code": None,
            "note": "Not yet in IG category value set (newer domain)",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.228",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.221",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.222",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.223",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.224",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.225",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.226",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.227",
            },
        },
        "digital-access": {
            "label": "Digital Access",
            "ig_category_code": None,
            "note": "Not yet in IG category value set (newer domain)",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.240",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.237",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.238",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.239",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.231",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.233",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.235",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.236",
            },
        },
        "utility-insecurity": {
            "label": "Utility Insecurity",
            "ig_category_code": None,
            "note": "Not yet in IG category value set (newer domain)",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.251",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.248",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.249",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.250",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.243",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.245",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.247",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.252",
            },
        },
        "language-access": {
            "label": "Language Access",
            "ig_category_code": None,
            "note": "Not yet in IG category value set (newer domain)",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": "2.16.840.1.113762.1.4.1247.273",
                "Screening Assessments (LOINC)": "2.16.840.1.113762.1.4.1247.270",
                "Screening Assessments Questions (LOINC)": "2.16.840.1.113762.1.4.1247.272",
                "Screening Assessments Answers (LOINC)": "2.16.840.1.113762.1.4.1247.271",
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.262",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.266",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.268",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.269",
            },
        },
        "incarceration-status": {
            "label": "Incarceration Status",
            "ig_category_code": None,
            "note": "Screening on hold by Gravity due to bias concerns",
            "value_sets": {
                "Screening Assessments And Questions (LOINC)": None,
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.258",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.257",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.260",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.261",
            },
        },
        "racism": {
            "label": "Racism",
            "ig_category_code": None,
            "note": "Screening work in progress",
            "value_sets": {
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.276",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.278",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.291",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.281",
            },
        },
        "toxic-stress": {
            "label": "Toxic Stress",
            "ig_category_code": None,
            "note": "Screening work in progress",
            "value_sets": {
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.288",
                "Goals (SNOMED CT)": "2.16.840.1.113762.1.4.1247.289",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.280",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.292",
            },
        },
        "protective-factors": {
            "label": "Protective Factors",
            "ig_category_code": None,
            "note": "Screening work in progress; uses 'Findings' not 'Diagnoses'",
            "value_sets": {
                "Findings (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.311",
            },
        },
        "low-community-food-access": {
            "label": "Low Community Food Access",
            "ig_category_code": None,
            "note": "Community-level domain; screening work in progress",
            "value_sets": {
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.319",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.324",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.321",
            },
        },
        "inadequate-community-safety": {
            "label": "Inadequate Community Safety",
            "ig_category_code": None,
            "note": "Community-level domain; screening work in progress",
            "value_sets": {
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.331",
                "Procedures (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.336",
                "Service Requests (CPT, HCPCS, SNOMED CT)": "2.16.840.1.113762.1.4.1247.335",
            },
        },
        "inadequate-community-natural-environment": {
            "label": "Inadequate Community Natural Environment",
            "ig_category_code": None,
            "note": "Community-level domain; screening work in progress",
            "value_sets": {
                "Diagnoses (ICD-10-CM, SNOMED CT)": "2.16.840.1.113762.1.4.1247.343",
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download(url: str, label: str) -> bytes:
    print(f"  Downloading {label} ...", flush=True)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved {path.relative_to(BASE_DIR.parent.parent)}")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def fetch_ig_package() -> dict:
    """Download FHIR IG npm package and extract all JSON files."""
    IG_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    tgz_bytes = download(IG_PACKAGE_URL, "FHIR IG package (tgz)")
    print(f"  Extracting to {IG_PACKAGE_DIR} ...", flush=True)

    extracted = []
    with tarfile.open(fileobj=io.BytesIO(tgz_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.endswith(".json"):
                continue
            # flatten: drop the leading "package/" prefix
            filename = Path(member.name).name
            dest = IG_PACKAGE_DIR / filename
            f = tar.extractfile(member)
            if f:
                dest.write_bytes(f.read())
                extracted.append(filename)

    print(f"  Extracted {len(extracted)} JSON files")
    return {"files": sorted(extracted), "count": len(extracted), "source": IG_PACKAGE_URL}


def fetch_data_dictionary() -> dict:
    raw = download(DATA_DICT_URL, "data_dictionary.json")
    dest = BASE_DIR / "data_dictionary.json"
    dest.write_bytes(raw)
    print(f"  Saved {dest.relative_to(BASE_DIR.parent.parent)}")
    return {"source": DATA_DICT_URL, "bytes": len(raw)}


def write_vsac_manifest() -> dict:
    dest = BASE_DIR / "vsac_oid_manifest.json"
    save_json(dest, VSAC_OID_MANIFEST)
    domain_count = len(VSAC_OID_MANIFEST["domains"])
    oid_count = sum(
        len([v for v in d["value_sets"].values() if v])
        for d in VSAC_OID_MANIFEST["domains"].values()
    )
    return {"domains": domain_count, "oids": oid_count}


def write_manifest(ig_info: dict, dd_info: dict, vsac_info: dict) -> None:
    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ig_version": "2.3.0",
        "ig_package": ig_info,
        "data_dictionary": dd_info,
        "vsac_oid_manifest": vsac_info,
        "notes": {
            "ig_package": "FHIR IG npm package — all StructureDefinitions, CodeSystems, ValueSets, Examples",
            "data_dictionary": "Gravity data dictionary spreadsheet in JSON (profiles x elements)",
            "vsac_oid_manifest": (
                "OIDs for all Gravity VSAC value sets per domain x artifact type. "
                "OIDs are public. Expansions require free UMLS account."
            ),
        },
    }
    save_json(BASE_DIR / "manifest.json", manifest)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nFetching Gravity data into {BASE_DIR}\n")

    print("[1/3] FHIR IG package")
    ig_info = fetch_ig_package()

    print("\n[2/3] Data dictionary")
    dd_info = fetch_data_dictionary()

    print("\n[3/3] VSAC OID manifest")
    vsac_info = write_vsac_manifest()

    print("\n[manifest]")
    write_manifest(ig_info, dd_info, vsac_info)

    print(f"\nDone.")
    print(f"  IG package files : {ig_info['count']}")
    print(f"  VSAC domains     : {vsac_info['domains']}")
    print(f"  VSAC OIDs        : {vsac_info['oids']}")


if __name__ == "__main__":
    main()
