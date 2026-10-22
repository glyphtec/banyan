# Demo Walkthrough — Closing the Loop Between Clinical and Social Care

A guided tour of Banyan using the flagship dataset: the **Gravity Project SDOH** clinical standard on one side, the **Open Eligibility** social-service taxonomy on the other, and the crosswalk between them. About 15 minutes.

**The story:** a clinician identifies a patient's social need and wants to refer them to a community organization. Two independently governed vocabularies have to line up. Banyan shows how that alignment is built, reviewed, trusted and maintained, with a receipt for every decision.

---

## Before you start

1. **Run the stack** (see the [README](../README.md#quick-start)):
   - Backend on http://localhost:8000, with `BANYAN_DUCKDB_PATH` pointing at a database loaded with the demo graphs. The clinical terminologies are licensed content and are not in the repo; the ingest scripts in [backend/utils/](../backend/utils) build them locally.
   - Frontend on http://localhost:5173.
   - `ANTHROPIC_API_KEY` set if you want the Agent act.
2. **Back up first.** The Agent and Review acts write to the live database. Run `python backend/utils/backup_db.py` (it uses `POST /admin/checkpoint`, so `BANYAN_ADMIN_API=true` is needed while the server is running).
3. **Sign in.** The UI asks you to pick or register an actor. Use a human handle, e.g. `human:you`. Everything you do is attributed to it.
4. The API examples use `curl`; in PowerShell use `curl.exe` or `Invoke-RestMethod`. Set a base URL:

   ```bash
   BASE=http://localhost:8000/api/v1
   ```

The graphs you should see in the picker:

| Graph | Role |
|---|---|
| Gravity SDOH Clinical Care STU 2.3 | Clinical social-risk domains and value sets |
| SNOMED SDOH Service Requests Slice | SNOMED codes for service requests |
| SNOMED CT SDOH Slice, ICD-10-CM SDOH Slice | Other clinical codes |
| Open Eligibility | Social-service taxonomy |

---

## Act 1 — Two worlds

*"Healthcare and social services describe the same need in different languages."*

1. Pick **Gravity SDOH Clinical Care STU 2.3** and expand **Food Insecurity**. Under it are value-set groups: Service Requests, Procedures, Goals, Diagnoses, Screening Assessments.
2. Select **Service Requests**. In the detail pane, the **Related** section lists the clinical codes that belong to this value set (`HAS_MEMBER` links into SNOMED CT and HCPCS).
3. Switch to **Open Eligibility** and expand **Food**: Food Pantry, Food Delivery, Free Meals, Help Pay for Food, Emergency Food, and so on.

**Point to make:** each side is internally coherent, and they are governed by different bodies on different release cycles. Nothing connects them yet in the open.

## Act 2 — The seam

*"A crosswalk is a set of assertions, and each one has an author."*

1. Switch to **SNOMED SDOH Service Requests Slice** and search for *Provision of healthy groceries*.
2. In **Related**, the code points to the Open Eligibility categories **Help Pay for Food** and **Free Meals** through `SAME_AS`. Open one link's metadata: `link_provenance: asserted` and `approved_by` name the human who signed off.
3. Click through to the Open Eligibility node. Navigation crosses graph boundaries, and **← Back** returns you.

**Point to make:** the mapping is data in the graph, not a spreadsheet beside it. It is typed, attributed and queryable.

## Act 3 — An AI proposes

*"The model is a fast junior analyst. It never gets the last word."*

Open **✨ Agent** and try:

> Which Food Insecurity service-request codes don't have an Open Eligibility mapping yet?

The agent answers with a single traversal (the coverage pattern in the [BQL cookbook](<Banyan Project_ BQL Spec.md#5-coverage-which-service-request-codes-are-not-yet-mapped>)), and its tool calls are visible in the chat. Then:

> Pick three of the uncovered codes and propose Open Eligibility mappings. Explain your confidence.

Each proposal is created as a `SAME_AS_PROPOSED` (or `TERM_SIMILAR_PROPOSED`) link, not as an approved mapping. It carries `confidence_level`, `confidence_basis`, `agent_rationale` and `caveats`, and is attributed to the agent's actor.

**Point to make:** the agent can reason over the whole graph and the clinical codes under each domain, but its output lands in a *pending* state that is visible and queryable. If it finds no good match, "no mapping exists" is a valid answer.

> **Heads-up:** the agent writes to the live graph, and its approval rule is currently enforced by its prompt rather than by the server (see the README TODO list). Do this act on a backed-up database.

## Act 4 — A human decides

*"Approval is a ledgered action, not a column edit."*

Open **✓ Review**:

1. Choose the graph, set **Show** to `SAME_AS_PROPOSED` and **Approve as** to `SAME_AS`. The queue lists each proposal with the agent's rationale and confidence.
2. For one good proposal, click **✓ SAME_AS**. The proposal becomes an approved `SAME_AS` link stamped with your handle.
3. For one that is close but wrong, click **⇄ Alt**, pick the correct target in the tree, and approve it. The panel warns you if that link already exists.
4. For one you are unsure about, click **⊘ Defer** and leave a note. It stays in the queue under the *Deferred* filter. Use **reviewed by me** to find your own decisions later.
5. **✕ Delete** rejects a proposal outright.

**Point to make:** reviewing is the only path from "an AI thinks" to "the crosswalk says". Every click above is a transaction in the ledger.

## Act 5 — Receipts

*"Show me who changed what, and prove history wasn't edited."*

Pull the history of the graph. Each entry has the actor, the verb, the forward payload, the **reversal payload**, and a SHA-256 hash chained to the previous entry:

```bash
curl -s "$BASE/graphs/<graph_id>/history?since_ledger_id=<n>"
```

(`<graph_id>` comes from `GET $BASE/graphs`; use `since_ledger_id` to see only recent entries.)

Verify the whole chain:

```bash
curl -s $BASE/ledger/verify-chain
# {"ok": true, "entries_checked": ...}
```

Now undo something. Try this on a scratch graph so you don't touch the real crosswalk:

```bash
H='-H X-Actor-Id:human:you -H Content-Type:application/json'
GID=$(curl -s -X POST $BASE/graphs $H -d '{"name":"Scratch"}' | python -c "import sys,json;print(json.load(sys.stdin)['graph_id'])")
A=$(curl -s -X POST $BASE/graphs/$GID/nodes $H -d '{"source_id":"A","name":"Alpha"}' | python -c "import sys,json;print(json.load(sys.stdin)['node_id'])")
B=$(curl -s -X POST $BASE/graphs/$GID/nodes $H -d '{"source_id":"B","name":"Beta"}'  | python -c "import sys,json;print(json.load(sys.stdin)['node_id'])")
HIER=$(curl -s $BASE/link-types | python -c "import sys,json;print(next(l['link_type_id'] for l in json.load(sys.stdin) if l['name']=='HIERARCHICAL'))")
curl -s -X POST $BASE/links $H -d "{\"link_type_id\":\"$HIER\",\"from_graph_id\":\"$GID\",\"to_graph_id\":\"$GID\",\"from_node_id\":\"$A\",\"to_node_id\":\"$B\"}"

curl -s $BASE/graphs/$GID/history                       # note the CREATE_LINK ledger_id
curl -s -X POST $BASE/ledger/<ledger_id>/undo -H X-Actor-Id:human:you
curl -s $BASE/ledger/verify-chain                       # still ok
```

The undo is itself a new ledger entry (a `DESTROY_LINK` that references the entry it reverses). History is never rewritten, and the chain stays valid.

**Point to make:** any assertion, human or agent, can be attributed, inspected and reversed, and tampering is detectable. That is the difference between a governed crosswalk and a lookup table.

## Act 6 — Blast radius

*"What breaks if we change this?"*

In the Open Eligibility graph, look up the **Food** node's id (for example with the BQL query in the [cookbook](<Banyan Project_ BQL Spec.md>)), then:

```bash
curl -s "$BASE/graphs/<oe_graph_id>/nodes/<food_node_id>/impact"
```

You get the descendants that would be affected and `cross_graph_link_count`, the number of crosswalk links from other graphs that point into this subtree. For *Food* that is well over a hundred, which is every clinical mapping you would be silently breaking by restructuring it.

Banyan can also answer *who* needs to hear about it. Register stakeholders with `POST /stakeholders`, attach them to nodes or graphs with an `OWNER`, `WATCHER` or `APPROVER` role and a scope (`NODE_ONLY`, `SUBGRAPH`, `ANCESTORS`), then:

```bash
curl -s "$BASE/nodes/<node_id>/stakeholders/resolve?graph_id=<graph_id>"
```

**Point to make:** impact analysis plus stakeholder resolution turns "we changed a term" into a precise consultation list.

## Act 7 — Versions

*"The next release of either standard will change something."*

```bash
# Pin the crosswalk state
curl -s -X POST $BASE/graphs/<graph_id>/snapshots $H -d '{"version_label":"gravity-2.3_x_oe-2024","notes":"pre-review"}'

# ...time passes, edits happen...

# What changed since the snapshot?
curl -s -X POST $BASE/graphs/diff -H Content-Type:application/json \
  -d '{"base":"snapshot:<snapshot_id>","compare":"<graph_id>"}'
# {"nodes_added": [...], "nodes_removed": [...], "nodes_changed": [...], "links_added": [...], "links_removed": [...]}
```

Snapshots can also be restored as a new graph (`POST /snapshots/{id}/restore`), and a new Gravity release can be imported and diffed against the old one the same way.

## Act 8 — Closing the loop

*"A patient needs a service. Where do we send them?"*

One BQL query takes a clinical service-request code to the social-service category and its parent:

```bash
curl -s -X POST $BASE/query -H Content-Type:application/json -d '{
  "graph": { "name": "SNOMED SDOH Service Requests Slice" },
  "starting": { "source_id": "http://snomed.info/sct|951411000124107" },
  "steps": [
    { "direction": "FROM", "link_types": ["SAME_AS!", "SAME_AS_PROPOSED!"], "depth": 1, "graphs": ["Open Eligibility"] },
    { "direction": "TO",   "link_types": ["HIERARCHICAL"], "depth": 1, "graphs": ["Open Eligibility"] }
  ],
  "result": { "format": "LINK_NODE", "include_seed": true }
}'
```

*Provision of healthy groceries* resolves to **Help Pay for Food** and **Free Meals**, under **Food**, and each hop includes who approved it and when. The next step in a real deployment would be querying an HSDS community-resource directory for that category.

**Point to make:** the loop closes *with receipts*: the answer is deterministic, and every mapping behind it is attributable and reversible.

---

## Bonus — Any agent, same engine

Banyan exposes the same operations over the **Model Context Protocol** at `http://localhost:8000/mcp/`. Point any MCP-capable client at it and it gets about 35 tools, including graph/node/link operations, `banyan_query`, `get_impact_summary`, `verify_ledger_chain`, and the crosswalk tools `banyan_get_crosswalk_candidates` and `banyan_create_crosswalk_link`. Agents connecting this way are attributed as `system:mcp-agent` unless they pass their own `actor_id`.

## Cleanup

- Delete the scratch graph (`DELETE $BASE/graphs/<id>`), or restore the backup you took at the start.
- Review decisions you made are real ledger entries. Undo them via `POST /ledger/{id}/undo` if you want the crosswalk back as it was.

## Rough edges to know about

These come from the [README TODO list](../README.md#project-status-and-todo):

- There is no authentication, so don't demo on an exposed network.
- Chat sessions are in memory and reset when the server restarts.
- The agent's "ask before approving" rule is prompt-level, not server-enforced.
