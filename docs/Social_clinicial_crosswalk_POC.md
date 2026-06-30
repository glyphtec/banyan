# Project Proposal: Banyan Social–Clinical Crosswalk Demonstrator

**Working title:** Banyan Crosswalk Demonstrator (closed-loop referral payload codename: *Keystone*)
**Document type:** Technical and strategic project proposal (development input)
**Status:** Draft for development intake
**Scope note:** This document covers project *substance* only — problem, solution, data, justification, organizational context, scope, and risks. Human/project-management planning and personal stakes are intentionally excluded and handled in a separate document.

---

## 1. Executive Summary

The Banyan Crosswalk Demonstrator is a full-scale reference application that uses the Banyan engine to build, version, and audit a crosswalk between the **social-care** and **clinical-care** taxonomies that govern social-needs referrals in the United States.

When a clinician identifies a patient's social need (e.g., food insecurity) and wants to refer them to a community-based organization that can help, two separately governed vocabularies must reconcile: the healthcare side codes the need using the **Gravity Project** SDOH standard (HL7 FHIR, mapped to LOINC/SNOMED CT/ICD-10), while the social-services side categorizes the resource using a **human-services taxonomy** such as **Open Eligibility** or the proprietary 211/AIRS Taxonomy. No widely-adopted, openly-maintained, versioned crosswalk connects these two worlds, so the "closed-loop referral" frequently fails to close.

Banyan is purpose-built for exactly this: it treats taxonomies, categories, alignments, and cross-walks as a unified network matrix, with cryptographic lineage, snapshot-based versioning, and pre-flight impact analysis. The demonstrator loads two or more real open taxonomies as Banyan graphs, asserts cross-graph alignment links between them, and exposes the result over both a REST (FastAPI) and an agentic (FastMCP) interface. The end-to-end story — *patient screened → SDOH code → crosswalk resolution → social-service category → directory lookup* — closes the loop with a full audit trail.

The demonstrator is built entirely on openly-licensed data and exercises every distinctive capability of the Banyan architecture in a single coherent, mission-relevant narrative.

---

## 2. Problem Statement

### 2.1 The interoperability seam

Social determinants of health (SDOH) — the conditions in which people live, work, and age — materially affect health outcomes, and addressing them requires coordination between clinical providers and social-service organizations. The persistent obstacle is **semantic**: clinical systems and social-service directories use different, independently-governed classification systems, and the data needed to link them is frequently stored in inconsistent formats that prevent exchange [S1].

The Gravity Project was founded specifically to standardize SDOH data so it can integrate with clinical workflows, and its work now spans 17+ social-risk domains plus a complete closed-loop referral implementation guide [S2][S3]. But Gravity standardizes the *clinical* side. The *social-service* side is governed by separate taxonomies, and the Open Referral Human Services Data Specification (HSDS) — the core open exchange format for community-resource directories — deliberately remains **taxonomy-agnostic**, providing a "taxonomic overlay mechanism" rather than mandating a single vocabulary [S4][S5]. HSDS explicitly acknowledges multiple competing human-services taxonomies (211/AIRS, Open Eligibility, CMS HCBS) and stops short of reconciling them [S5][S6].

The unresolved reconciliation between the clinical SDOH vocabulary and the social-service taxonomy is the gap this project targets.

### 2.2 Why this is hard, and why it persists

- **Two governance bodies, two release cadences.** Gravity ships its SDOH Clinical Care Implementation Guide at STU 2.3, with STU 3.0 balloting January 2026 [S7]. Open Eligibility evolves independently under separate stewardship. A crosswalk is therefore a *moving target* that must be re-validated against each side's releases.
- **Provenance matters.** An incorrect mapping (e.g., conflating a housing need with a food need) routes a vulnerable person to the wrong service. Mapping decisions need to be attributable and reversible.
- **Open vs. closed.** The de facto dominant social-services taxonomy, the 211/AIRS Taxonomy, is proprietary and licensed; Open Eligibility exists as the open alternative [S8][S9]. Any open crosswalk must route around the closed incumbent without redistributing it.

These three properties — version drift, provenance/auditability, and the open/closed boundary — are precisely the conditions under which a naive lookup table fails and a governed, versioned, auditable crosswalk engine is warranted.

---

## 3. Proposed Solution

### 3.1 Banyan as the crosswalk substrate

The Banyan engine (see internal reference: `BANYAN_SYSTEM_ARCHITECTURE.md`) provides the operational primitives this problem needs:

- **Unified network matrix.** Each taxonomy is loaded as a Banyan `graph`; categories become `node` rows; intra-taxonomy hierarchy becomes `link` rows (`PARENT_OF`); and cross-taxonomy alignments become cross-graph `link` rows (`SAME_AS`, `RELATED_TERM`). This naturally exercises the cross-graph link path (`target_graph_id`, `idx_link_cross_graph`).
- **Cryptographic lineage.** Every mapping assertion is appended to the universal ledger with a SHA-256 hash chain, capturing the actor, the forward delta, and a reversible inverse payload.
- **Versioning via snapshots.** A crosswalk state can be pinned to a labeled snapshot (e.g., `gravity-stu-2.3_x_open-eligibility-2024`) and diffed against a later state.
- **Pre-flight impact analysis.** Before a destructive change (e.g., retiring a deprecated concept), Banyan compiles an `ImpactSummary` blast-radius report via recursive CTE traversal.
- **Dual interface.** The crosswalk is queryable over FastAPI (REST, for pipelines) and FastMCP (MCP, for agentic workflows).
- **Open link-type vocabulary.** [¹] The three root relationship families (`HIERARCHICAL`, `RELATED`, `SYNONYM`) are the only axioms baked into the engine. Every sub-type — `MEMBER_OF`, `SAME_CONCEPT_AS`, `CROSSWALK_PROPOSED`, or whatever a future Gravity release warrants — is added as data via a single API call, takes effect immediately, is fully reversible, and is recorded in the ledger with the same provenance as any other assertion. The schema never requires migration. This matters to a standards audience that lives with balloting cycles: in Banyan, recognising a new relationship type is an operational decision, not a governance one.

### 3.2 Capability-to-demonstration mapping

| Banyan capability | Demonstrated through |
|---|---|
| Cross-graph alignment links | Gravity SDOH concept ↔ Open Eligibility service category mappings |
| Snapshot versioning | Pin `Gravity STU 2.3 ↔ OE` crosswalk; diff against STU 3.0 |
| ImpactSummary (recursive CTE) | "STU 3.0 retires/renames concept X — which mappings break, which services orphan?" |
| Cryptographic ledger | Per-mapping provenance: who asserted it, when, reversible |
| FastMCP interface | Agent proposes candidate mappings (LLM-suggested, human-approved, recorded with `actor_id='agent'`) |
| FastAPI interface | Closed-loop referral lookup: SDOH code → service category → directory query |

### 3.3 The end-to-end narrative (the "Keystone" payload)

1. A patient is screened; a social need is captured as a Gravity SDOH code (e.g., food insecurity, coded via LOINC/SNOMED).
2. Banyan resolves the cross-graph crosswalk to the corresponding Open Eligibility service category (e.g., *Food*).
3. The resolved category is used to query an HSDS-formatted directory for nearby resources.
4. Every step — including the mapping that made resolution possible — is attributable in the ledger.

The loop closes, *with receipts*.

---

## 4. Justification

### 4.1 Policy and adoption momentum (the work is timely and recognized)

The clinical-social interoperability problem this project addresses is the subject of active federal and state policy:

- Gravity has become the national reference standard for SDOH interoperability and is reflected in federal guidance, CMS Medicaid policy, ONC's HTI-1 Final Rule, and USCDI; national measurement bodies such as NCQA reference its value sets [S7].
- Multiple states (Washington, Connecticut, Vermont, Oregon, Ohio) name Gravity in their health-IT roadmaps and SDOH strategies [S7].
- Gravity's closed-loop referral work was named in the White House SDOH Playbook's actions to align federal programs for SDOH information exchange and closed-loop referrals [S10].

A demonstrator that builds the *open crosswalk* enabling those referrals to resolve sits directly on this momentum.

### 4.2 Technical fit (the tool matches the problem)

The three failure conditions in §2.2 — version drift, provenance, open/closed boundary — map one-to-one onto Banyan's differentiators (versioning, cryptographic ledger, cross-graph alignment). This is not a contrived showcase: the problem independently demands the exact capabilities the engine provides, which is the strongest possible justification for the architecture.

### 4.3 AI-native relevance

Hybrid retrieval architectures combining vector search, graph traversal, and structured lookup are the dominant production pattern in 2025–2026, with "agentic" orchestration over a knowledge graph used as persistent, structured memory cited as the emerging frontier [S11]. Banyan's FastMCP interface positions the crosswalk as agent-navigable infrastructure, and the human-in-the-loop, ledger-audited mapping-proposal workflow is a credible answer to the well-documented risk that LLM-built graphs introduce incorrect or merged entities [S12].

### 4.4 Open-data integrity (the demonstrator is fully shareable)

The project uses only openly-licensed inputs and can be published openly, including the derived crosswalk (see §5 for license terms). This both honors the open-source ethos of the target ecosystem and sidesteps redistribution of proprietary vocabularies.

---

## 5. Data Sources and Licensing

| Source | Role in demo | License / access | Reference |
|---|---|---|---|
| **Open Eligibility** (Aunt Bertha / Findhelp; stewarded via Open Referral) | Primary social-service taxonomy graph; facets: Human Services + Human Situations | CC BY-SA 3.0; XML/CSV/JSON/YAML on GitHub | [S8][S9] |
| **Gravity Project SDOH Clinical Care IG** (HL7 FHIR Accelerator; SIREN) | Clinical SDOH concept graph; social-risk domains and codes | Open via HL7; public IG + GitHub repo | [S2][S3][S13] |
| **LOINC / SNOMED CT / ICD-10** (referenced by Gravity value sets) | Underlying clinical code systems for SDOH concepts | LOINC free (license click-through); SNOMED CT free in US via NLM/UMLS; ICD-10 free | [S3] |
| **Open Referral HSDS** | Directory data model for the resource-lookup step | Open specification; schemas on GitHub | [S4][S5] |
| **211/AIRS Taxonomy** | Referenced as the proprietary incumbent the open crosswalk routes around | Proprietary / licensed — **do not redistribute** | [S6] |

**License obligations to honor in the build:**
- Open Eligibility is **CC BY-SA 3.0** — attribution to Aunt Bertha, Inc. is required, and any derived crosswalk that incorporates it must be released under share-alike terms [S8][S9]. This is compatible with an openly-published demonstrator.
- SNOMED CT content must only be used under the applicable NLM/UMLS license terms; the demo should reference SNOMED codes as identifiers without redistributing proprietary descriptions beyond what the license permits.
- The 211/AIRS Taxonomy must not be ingested or redistributed; reference it conceptually only.

---

## 6. Organizational Touch Points

The demonstrator sits inside an active, identifiable ecosystem of standards bodies, stewards, and implementers. These are relevant both as technical reference points and as natural audiences/collaborators.

**Standards stewards (the bodies whose artifacts the demo consumes):**
- **Open Referral Initiative** — steward of HSDS and the Open Eligibility project repository; the taxonomic-overlay design is theirs [S4][S5][S8].
- **Findhelp (formerly Aunt Bertha)** — originator and license holder of the Human Services Taxonomy underlying Open Eligibility [S8][S9].
- **Gravity Project / HL7 / SIREN (UCSF)** — stewards of the SDOH Clinical Care standard; an open, public, consensus-driven collaborative of 2,500+ participants [S2][S3][S14].
- **HL7 International** — host of the FHIR specifications and terminology (THO) the clinical side depends on [S13].

**Implementers and conveners (where this work is applied):**
- **Civitas Networks for Health** — convenes Gravity SDOH pilots with health information exchanges and community organizations [S14].
- **State health-IT / HIE programs** (WA, CT, VT, OR, OH) — adopting Gravity in roadmaps and Medicaid alignment [S7].

**Open-source civic/health-tech organizations (peer implementers in the space):**
- **Code for America** — civic-tech nonprofit with a large open-source footprint, focused on the social safety net [S15].
- **Nava PBC** — public-benefit corporation building government benefits and eligibility systems, with an explicit open-source practice [S16].

**Adjacent research-infrastructure reference (stability/credibility anchor):**
- **OHDSI / OMOP** — the open-community standard for observational health data and its standardized vocabularies, demonstrating the same versioned-crosswalk discipline at national scale [S17][S18].

---

## 7. Scope and Deliverables

**In scope (demonstrator):**
1. Ingestion of Open Eligibility into Banyan graph/node/link tables (one graph per taxonomy).
2. Ingestion of a representative slice of Gravity SDOH concepts (priority domains: food, housing, transportation) as a second graph.
3. A seed crosswalk: cross-graph `SAME_AS`/`RELATED_TERM` links between Gravity concepts and Open Eligibility categories, asserted through the four Banyan primitives and recorded in the ledger.
4. Snapshot + diff of the crosswalk across two taxonomy versions.
5. ImpactSummary report for a representative deprecation/rename scenario.
6. FastAPI endpoint: closed-loop referral resolution (SDOH code → service category → HSDS directory query).
7. FastMCP endpoint: agent-assisted mapping proposal with human approval and ledger attribution.

**Out of scope (this document):**
- Project-management plan, timeline, staffing, and personal objectives (separate document).
- Production-grade directory data sourcing, PHI handling, and live clinical integration.
- Reconciliation against the proprietary 211/AIRS Taxonomy.

**Definition of "killer app" / success criteria:**
- The full closed-loop narrative runs end-to-end on real open data.
- All five distinctive Banyan capabilities (cross-graph alignment, versioning, impact analysis, cryptographic lineage, MCP) are each exercised by a concrete, observable step.
- The derived crosswalk is publishable under share-alike terms with correct attribution.

---

## 8. Risks and Constraints

| Risk | Mitigation |
|---|---|
| **Crosswalk validity.** Automated or naive mappings can be semantically wrong, with real-world referral consequences. | Treat all mappings as assertions requiring human approval; record provenance in the ledger; scope seed mappings to well-understood priority domains. |
| **LLM-proposed mapping errors** (entity merge/mismatch, a documented GraphRAG failure mode [S12]). | Human-in-the-loop approval gate; agent actions are proposals only, attributed as `actor_id='agent'` and reversible. |
| **License missteps** (SNOMED redistribution; AIRS ingestion; missing CC BY-SA attribution). | Explicit license register (§5); reference proprietary content by identifier only; ship attribution and share-alike notices with any published artifact. |
| **Version drift** between taxonomy releases. | This is the demonstrated feature, not merely a risk — snapshots + ImpactSummary are the response. |
| **Scope creep into production concerns** (PHI, live EHR/CBO integration). | Explicitly out of scope; demonstrator uses synthetic/sample directory data. |

---

## 9. Sources

- **[S1]** SDOH and the Gravity Project — overview of SDOH interoperability challenges. Kodjin. https://kodjin.com/blog/sdoh-and-gravity-project/
- **[S2]** Gravity Project — Project Information (17+ social-risk domains; closed-loop referral IG). HL7 Confluence. https://confluence.hl7.org/spaces/GRAV/pages/161061071/Project+Information
- **[S3]** HL7 SDOH Clinical Care FHIR Implementation Guide (value sets; referral workflow; screening/diagnosis/goal/intervention). https://hl7.org/fhir/us/sdoh-clinicalcare/
- **[S4]** Human Services Data Specification (HSDS) — overview and data model (taxonomy_term object). Open Referral. https://docs.openreferral.org/en/latest/hsds/overview.html
- **[S5]** HSDS FAQs — taxonomy-agnostic design; "overlay a taxonomy of the user's choosing"; default Open Eligibility. Open Referral. http://docs.openreferral.org/en/latest/hsds/hsds_faqs.html
- **[S6]** FHIR Human Services Directory IG — variation across human-services taxonomies (211 LA, Open Eligibility, CMS HCBS). HL7. https://build.fhir.org/ig/HL7/FHIR-IG-Human-Services-Directory/implementation.html
- **[S7]** State Momentum Grows Around Gravity SDOH-CC-IG Implementation (federal guidance, CMS, USCDI, NCQA; STU 2.3 / STU 3.0 Jan 2026; state roadmaps). HL7 News, Jan 2026. https://hl7news.hl7.org/2026/01/20/state-momentum-grows-around-gravity-sdoh-cc-ig-implementation/
- **[S8]** Open Eligibility Project repository (CC BY-SA 3.0; XML/CSV/JSON/YAML). Open Referral. https://github.com/openreferral/openeligibility
- **[S9]** Open Eligibility Project — original repository and license (Aunt Bertha, Inc.). https://github.com/auntbertha/openeligibility ; license background: https://creativecommons.org/2013/12/02/human-services-taxonomy/
- **[S10]** Gravity Project named in the White House "U.S. Playbook to Address Social Determinants of Health" (closed-loop referral alignment). Gravity Project. https://www.linkedin.com/company/gravity-project
- **[S11]** Knowledge Base vs Knowledge Graph for LLM Systems — hybrid retrieval and agentic Graph RAG as the 2025–2026 dominant/emerging patterns. Kloia. https://www.kloia.com/blog/knowledge-base-vs-knowledge-graph-llm
- **[S12]** What is GraphRAG — documented entity-merge/mismatch failure modes in LLM-built graphs. Articsledge. https://www.articsledge.com/post/graphrag-retrieval-augmented-generation
- **[S13]** Gravity Project FHIR SDOH Clinical Care repository. HL7. https://github.com/HL7/fhir-sdoh-clinicalcare
- **[S14]** Civitas Networks for Health / Gravity Project SDOH pilots; Gravity as open public collaborative (2,500+ participants). https://civitasforhealth.org/civitas-networks-for-health-in-partnership-with-gravity-project-announces-four-new-pilot-sites-to-further-implementation-of-sdoh-data-standards/ ; SIREN: https://sirenetwork.ucsf.edu/TheGravityProject
- **[S15]** Code for America — careers and open-source civic-tech focus. https://codeforamerica.org/jobs/ ; GitHub org: https://github.com/codeforamerica
- **[S16]** Nava PBC — public-benefit civic-tech consultancy; open-source practice. https://www.linkedin.com/company/nava-pbc
- **[S17]** OMOP Common Data Model — open community data standard and standardized vocabularies. OHDSI. https://www.ohdsi.org/data-standardization/
- **[S18]** OHDSI Standardized Vocabularies as a centralized reference ontology for international data harmonization (support for historical/retired concepts). JAMIA. https://academic.oup.com/jamia/article/31/3/583/7510741
- **[S-internal]** Banyan System Architecture — `BANYAN_SYSTEM_ARCHITECTURE.md` (internal reference; engine primitives, ledger, schema, ImpactSummary, FastAPI/FastMCP interfaces).

---

*Prepared as development intake. Project-management plan and personal-objective framing are maintained separately, per scope note in §0.*

---

**Footnotes**

[¹] **On the openness of link types.** A common assumption in interoperability tooling is that relationship types must be enumerated and locked into the schema up front — a design that reflects the constraint of relational databases and the caution of standards balloting cycles. Banyan inverts this: the three root families (`HIERARCHICAL`, `RELATED`, `SYNONYM`) are the only structural axioms; every sub-type is a data row, not a schema element. Adding `MEMBER_OF` to record that a clinical code belongs to a Gravity value set, or adding `SAME_CONCEPT_AS` to record that two codes in different authority domains share a UMLS Concept Unique Identifier (CUI), requires a single `POST /link-types` call. The new type takes effect immediately, carries full ledger provenance, and is reversible. For an audience accustomed to waiting for a balloting cycle to recognise a new relationship type, this is a meaningful operational difference.

## Appendix I: data source notes for Minumum Fundable Unit (MFU)



**1. Open Eligibility — fully open, grab it first (you may already have this).**
Source: `github.com/openreferral/openeligibility`. Ships as `taxonomy.csv`, `.json`, `.yaml`, `.xml` — take the JSON. License CC BY-SA 3.0 (attribute Aunt Bertha, share-alike). This is your social-services tree: two roots (Human Services, Human Situations), shallow hierarchy, a few hundred terms. Maps cleanly to one graph, nodes = terms, links = `PARENT_OF`. Zero friction, no login.

**2. ICD-10-CM SDOH Z-codes — yes, relevant, and the easiest *clinical* slice to get.**
To your question: ICD-10-CM is very relevant. It's one of the two code systems on Gravity's **diagnosis** axis (SNOMED CT is the other), and it carries the dedicated SDOH block. The SDOH-related codes are categories Z55–Z65 — the ICD-10-CM diagnosis codes used to document housing, food insecurity, transportation, and similar, sitting in Chapter 21, "Factors Influencing Health Status and Contact with Health Services." Tellingly for your crosswalk, the Gravity Project itself submitted codes here — e.g., Z59.82 Transportation insecurity, and Z59.41 is food insecurity. So the diagnosis side of your Big 5 is already a small, named, public set.
Source: the full ICD-10-CM release is free/public-domain from CMS (`cms.gov/medicare/coding-billing/icd-10`) and CDC/NCHS (`cdc.gov/nchs/icd/icd-10-cm`). But you don't need 70,000 codes — there's a published Z55–Z65 extract (e.g., ASHA's SDOH list) covering exactly that block, and CMS publishes SDOH Z-code reference resources directly. Grab just Z55–Z65. It's both a small hierarchy (Z59 → Z59.4 → Z59.41, so `PARENT_OF`) and the member set of Gravity's diagnosis cells (`MEMBER_OF`).

**3. LOINC — what it is, and why it's the screening axis.**
LOINC (Logical Observation Identifiers Names and Codes) is the universal code system for *observations* — lab tests, vital signs, and, the part that matters here, **survey/screening instruments and their individual questions and answer choices**. In Gravity, LOINC is the **screening** axis: a screener like the Hunger Vital Sign or PRAPARE, each question, and each coded answer, all carry LOINC codes. So if your MFU wants to show "a screening result led to a coded need," LOINC is where the screening lives.
Source: `loinc.org` — free, but requires a free account and license acceptance to download the bulk release (a mild paywall, no cost). MFU tactic: don't pull the ~100k-term release; lift only the specific LOINC codes Gravity's screening value sets reference (you can read them off the Gravity IG value-set pages — see next). Those become member nodes of Gravity's screening cells.

**4. Gravity — not one file; structure is open, full code expansions are behind a free login.**
This is the "this side of the paywall" nuance you're navigating. Two layers:
- *Structure + value-set definitions (open):* the SDOH Clinical Care IG at `hl7.org/fhir/us/sdoh-clinicalcare/` and its source repo `github.com/HL7/fhir-sdoh-clinicalcare`. The IG pages give you the domain × activity matrix, the FHIR profiles, and each ValueSet resource as JSON — often with the code list visible. This is enough to scaffold the whole Gravity skeleton and read off which LOINC/ICD/SNOMED codes each cell references. No login.
- *Authoritative value-set expansions (free login):* the complete, versioned member code lists are published in VSAC at `vsac.nlm.nih.gov`, which needs a free UMLS account. You go here when you want the exact, complete expansion rather than what's rendered in the IG.
For the MFU you can likely build the entire Gravity slice from the open IG alone and only touch VSAC if a specific expansion is incomplete on the IG page. Gravity maps to your 2-level tree (domain L1 → activity L2), with each L2 cell a value-set node whose members are the code nodes from #2/#3 via cross-graph `MEMBER_OF`.

**5. SNOMED CT — the deferred big one, login-gated.**
The other diagnosis-axis code system alongside ICD-10. Free in the US but via the UMLS license (`nlm.nih.gov/healthit/snomedct`, UMLS account). Per everything we discussed, leave it out of the MFU — use ICD-10 Z-codes for the diagnosis axis and keep SNOMED as the documented "where this goes" affordance. If you later want it, you only need the handful of SNOMED codes Gravity's cells cite, not the 350k-concept release.

So the reference set, assembled: an **Open Eligibility** tree (graph 1), a **Gravity** 2-level domain×activity tree whose cells are value-set nodes (graph 2), a small **code graph** of the cited **ICD-10 Z-codes** and **LOINC** screening codes (graph 3), joined cell→code by `MEMBER_OF`, and your **`SAME_AS`** crosswalk links from Gravity domains to Open Eligibility categories (the actual product). Big 5 only. Everything except the LOINC and VSAC expansions is grabbable with no login at all — which means you can stand up the full shape today and only hit the free-login wall for the last bits of completeness.

One accuracy caveat to verify yourself as you pull these: exact code memberships and the STU version (2.3 now, 3.0 was balloting January 2026) shift between Gravity releases, so pin which release you're building against and note it on the snapshot — the versioning discipline you already designed is there precisely for this.

