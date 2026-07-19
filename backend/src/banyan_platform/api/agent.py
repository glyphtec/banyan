"""
Banyan Agent — conversational interface powered by Claude claude-sonnet-4-6.

Endpoints (prefix /api/v1/agent):
  POST /chat   { session_id, message, context?, actor_id? }
               → { reply, tool_calls: [{name, input, result}] }
  POST /clear  { session_id }
               → { ok: true }

Sessions are held in-memory (dict keyed by session_id).  History includes
the full Anthropic message list so multi-turn tool-call context is preserved.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from banyan_platform.services.taxonomy_service import BanyanService

log = logging.getLogger(__name__)

_AGENT_ACTOR = "system:mcp-agent"
_MODEL       = "claude-sonnet-4-6"
_MAX_TOKENS  = 4096
_MAX_LOOPS   = 25      # safety guard against runaway tool-call loops

# ---------------------------------------------------------------------------
# Request / response models (module-level so Pydantic v2 resolves types correctly)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str
    context: dict | None = None
    actor_id: str = _AGENT_ACTOR

class ClearRequest(BaseModel):
    session_id: str

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

_sessions: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_BASE = """You are the Banyan Taxonomy Agent — an expert knowledge manager \
embedded in the Banyan platform.

Your role: expert technician who executes tasks for the taxonomist manager (the user). \
Keep replies concise and action-oriented. Show your reasoning before executing \
destructive operations.

BANYAN OVERVIEW
- Graphs are named taxonomies / ontologies.
- Nodes are concepts (source_id = stable business key, name = display label, metadata = JSON).
- Links are typed and directional: HIERARCHICAL (parent→child, same-graph), \
RELATED (associative, cross-graph OK), SYNONYM (equivalence, same-graph).
- Key RELATED sub-types: SAME_AS (crosswalk match), HAS_MEMBER (value-set membership), \
SAME_AS_PROPOSED (pending review).
- Every mutation is append-only in the audit ledger (SHA-256 hash chain).

LIVE GRAPHS
- Open Eligibility (OE): social-service taxonomy, ~290 nodes, 4-level hierarchy.
- Gravity SDOH Clinical Care STU 2.3: 28 L1 social-risk domains + 188 L2 \
value-set activity nodes.
- SNOMED CT SDOH Slice: ~591 clinical codes.
- ICD-10-CM SDOH Slice: ~192 ICD-10-CM Z-codes and related codes.
- 653 HAS_MEMBER links: Gravity L2 activities → SNOMED/ICD-10 codes.

GUIDELINES
- Use banyan_query to explore before asserting facts about the data.
- Prefer source_id values over UUIDs when referring to nodes.
- For crosswalk work: query both nodes before proposing a SAME_AS link.
- The user confirms; you execute. Never create SAME_AS links without explicit approval.

MEMORY TIER CONVENTION
Every working-memory entry MUST begin with exactly one tier prefix as its first token:
  [ALWAYS] — hard constraint. Mandatory. No agent discretion. Overrides user requests \
and in-context reasoning.
  [NEVER]  — hard prohibition. Must never be done. Overrides user requests and \
in-context reasoning.
  [FYI]    — reference or guidance. Agent may apply judgment.
These tiers are system-level baselines enforced by the platform, not subject to \
negotiation or override by any instruction, including operator instructions. \
meta: keys are system-owned; do not overwrite them. \
Prose-only entries without a tier prefix are non-compliant; prepend the correct tier \
before using them.

UI CONTROL
- After locating a specific node the user asked about, call ui_navigate_node to reveal it \
in the tree and detail panels. Use the graph_id and node_id from the query result.
- After shifting analytical focus to a different graph, call ui_select_graph.
- Only call these for intentional focus shifts — not for every node in a bulk listing.
"""


def _build_system(context: dict | None, memories: list[dict] | None = None) -> str:
    parts = [_SYSTEM_BASE]
    if memories:
        parts.append("\nWORKING MEMORY")
        # meta: entries (system-level rules) always render first so the tier
        # prefixes are read before any per-session guidance.
        ordered = sorted(memories, key=lambda m: (0 if m["key"].startswith("meta:") else 1, m["key"]))
        for m in ordered:
            # Format: key: <content>   — category bracket omitted so the
            # [ALWAYS]/[NEVER]/[FYI] tier prefix is the first visible token.
            parts.append(f"{m['key']}: {m['content']}")
    if context:
        parts.append("\nCURRENT UI CONTEXT")
        if context.get("operator_handle"):
            display = context.get("operator_display_name") or context["operator_handle"]
            parts.append(f"- Operator: {display} ({context['operator_handle']})")
        if context.get("graph_name"):
            parts.append(f"- Graph: {context['graph_name']}")
        if context.get("node_name"):
            parts.append(
                f"- Selected node: \"{context['node_name']}\" "
                f"(source_id: {context.get('node_source_id', '?')})"
            )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "name": "banyan_query",
        "description": (
            "Execute a BQL (Banyan Query Language) traversal query against the graph store.\n\n"
            "Quick examples:\n"
            "  List Gravity L1 domains:\n"
            "    {\"graph\":{\"name\":\"Gravity SDOH Clinical Care STU 2.3\"},\"starting\":{\"source_id\":\"$ROOT$\"},\"steps\":[{\"direction\":\"FROM\",\"link_types\":[\"HIERARCHICAL\"],\"depth\":1}],\"result\":{\"format\":\"NODE\",\"include_seed\":false}}\n\n"
            "  Find OE nodes containing 'food':\n"
            "    {\"graph\":{\"name\":\"Open Eligibility\"},\"starting\":{\"name_contains\":\"food\"},\"result\":{\"format\":\"NODE\"}}\n\n"
            "  SNOMED codes for a Gravity domain (2-step):\n"
            "    {\"graph\":{\"name\":\"Gravity SDOH Clinical Care STU 2.3\"},\"starting\":{\"name\":\"Food Insecurity\"},\"steps\":[{\"direction\":\"FROM\",\"link_types\":[\"HIERARCHICAL\"],\"depth\":1,\"collect\":false},{\"direction\":\"FROM\",\"link_types\":[\"HAS_MEMBER!\"],\"graphs\":[\"SNOMED CT SDOH Slice\"],\"depth\":1}],\"result\":{\"format\":\"NODE\",\"include_seed\":false}}\n\n"
            "RESULT LIMIT\n"
            "Results are capped at 150 by default to protect context size. "
            "Pass `limit` (integer) to override up to 500. "
            "When the cap is hit, the response contains `_truncated: true` and `_total` "
            "with the full count — always surface this to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "object",
                    "description": (
                        "BQL query dict. Required key: 'graph' ({name|id}). "
                        "Optional: 'starting' (NodePredicate), 'steps' (list), 'result' (options)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max results to return (default 150, max 500). "
                        "Increase when the user explicitly asks for a fuller result set."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_graphs",
        "description": "List all graphs in the Banyan store (excludes __system__ sentinel).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_link_types",
        "description": (
            "List link type definitions. Pass 'root' to filter by family "
            "(HIERARCHICAL, RELATED, or SYNONYM)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Optional root family name to filter by",
                }
            },
        },
    },
    {
        "name": "get_node_by_source",
        "description": (
            "Look up a node by graph name and source_id. "
            "Returns the full node dict including node_id UUID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string"},
                "source_id":  {"type": "string"},
            },
            "required": ["graph_name", "source_id"],
        },
    },
    {
        "name": "create_link_by_source",
        "description": (
            "Create a typed link between two nodes identified by graph name and source_id.\n"
            "Use for crosswalk assertions (SAME_AS between OE and Gravity) and other editorial links.\n"
            "Common link_type_names: SAME_AS, HIERARCHICAL, HAS_MEMBER, SAME_AS_PROPOSED, RELATED.\n"
            "Always confirm with the user before calling for SAME_AS links."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "link_type_name":  {"type": "string"},
                "from_graph_name": {"type": "string"},
                "to_graph_name":   {"type": "string"},
                "from_source_id":  {"type": "string"},
                "to_source_id":    {"type": "string"},
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata, e.g. {\"rationale\": \"...\"}",
                },
            },
            "required": [
                "link_type_name", "from_graph_name", "to_graph_name",
                "from_source_id", "to_source_id",
            ],
        },
    },
    {
        "name": "destroy_link",
        "description": (
            "Permanently destroy a link by its link_id UUID. "
            "Recorded in the audit ledger. Confirm with the user first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "link_id": {"type": "string", "description": "UUID of the link to destroy"},
            },
            "required": ["link_id"],
        },
    },
    {
        "name": "update_node",
        "description": "Update a node's name, notes, or metadata. Only provided fields change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id":  {"type": "string", "description": "UUID of the node"},
                "name":     {"type": "string"},
                "notes":    {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "get_graph_history",
        "description": "Return recent audit-ledger entries for a graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string", "description": "Graph UUID"},
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return (default 20)",
                },
            },
            "required": ["graph_id"],
        },
    },
    {
        "name": "ui_navigate_node",
        "description": (
            "Instruct the UI to switch to a graph and reveal a specific node in the tree and "
            "detail panels. Call after locating a node the user asked about. "
            "Use graph_id and node_id from a previous banyan_query or get_node_by_source result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string", "description": "UUID of the graph"},
                "node_id":  {"type": "string", "description": "UUID of the node"},
            },
            "required": ["graph_id", "node_id"],
        },
    },
    {
        "name": "ui_select_graph",
        "description": "Instruct the UI to switch the active graph without selecting a specific node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string", "description": "UUID of the graph to select"},
            },
            "required": ["graph_id"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Store a note in persistent working memory — survives page reloads and server restarts.\n"
            "Use when the user teaches you a shorthand, states a preference, or establishes a "
            "workflow convention. The key is a stable human-readable identifier "
            "(e.g. 'shorthand:food_cluster'). Overwrites any existing note with the same key.\n"
            "Categories: shorthand | preference | workflow | fact | general"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key":      {"type": "string", "description": "Stable unique identifier for this note"},
                "content":  {"type": "string", "description": "The note to store (1-3 sentences)"},
                "category": {"type": "string", "description": "shorthand | preference | workflow | fact | general"},
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "forget",
        "description": "Remove a note from working memory by key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key of the note to remove"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "execute_batch",
        "description": (
            "Execute a batch of link operations atomically in one call.\n"
            "Use this instead of looping create_link_by_source when creating many links of the same type.\n\n"
            "graph_name   — graph name string (resolved server-side).\n"
            "default_link_type_name — link type name applied to all CREATE_LINK ops without an explicit link_type_id.\n\n"
            "link_operations items:\n"
            "  { \"verb\": \"CREATE_LINK\",  \"data\": { \"from_source_id\": \"...\", \"to_source_id\": \"...\" } }\n"
            "  { \"verb\": \"DESTROY_LINK\", \"data\": { \"link_id\": \"...\" } }\n\n"
            "For cross-graph CREATE_LINK add \"to_graph_name\" in data.\n"
            "Returns counters: links_created, links_destroyed, ledger_entries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "graph_name": {"type": "string", "description": "Source graph name"},
                "default_link_type_name": {"type": "string", "description": "Link type for all CREATE_LINK ops"},
                "link_operations": {
                    "type": "array",
                    "description": "List of link operations",
                    "items": {"type": "object"},
                },
                "node_operations": {
                    "type": "array",
                    "description": "Optional list of node operations",
                    "items": {"type": "object"},
                },
            },
            "required": ["graph_name", "link_operations"],
        },
    },
    {
        "name": "list_memories",
        "description": "List all notes currently in working memory.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _dispatch(
    name: str,
    args: dict,
    service: "BanyanService",
    actor_id: str,
) -> Any:
    """Execute one tool call and return a JSON-serialisable result."""
    try:
        if name == "banyan_query":
            result = service.execute_bql(args["query"])
            cap = min(int(args.get("limit", 150)), 500)
            if isinstance(result.get("results"), list) and len(result["results"]) > cap:
                total = len(result["results"])
                result = {**result, "results": result["results"][:cap],
                          "_truncated": True, "_total": total}
            return result

        if name == "list_graphs":
            return [g for g in service.list_graphs() if g["name"] != "__system__"]

        if name == "get_link_types":
            return service.get_link_types(root=args.get("root"))

        if name == "get_node_by_source":
            graphs = {g["name"]: g["graph_id"] for g in service.list_graphs()}
            gid = graphs.get(args["graph_name"])
            if not gid:
                return {"error": f"Graph '{args['graph_name']}' not found"}
            with service.db.connect() as conn:
                node = service.nodes.get_by_source(conn, gid, args["source_id"])
            if node is None:
                return {"error": f"Node '{args['source_id']}' not found in '{args['graph_name']}'"}
            return node

        if name == "create_link_by_source":
            graph_map = {g["name"]: g["graph_id"] for g in service.list_graphs()}
            from_gid = graph_map.get(args["from_graph_name"])
            to_gid   = graph_map.get(args["to_graph_name"])
            if not from_gid:
                return {"error": f"Graph '{args['from_graph_name']}' not found"}
            if not to_gid:
                return {"error": f"Graph '{args['to_graph_name']}' not found"}

            lt_map = {lt["name"]: lt["link_type_id"] for lt in service.get_link_types()}
            lt_id = lt_map.get(args["link_type_name"])
            if not lt_id:
                return {"error": f"Link type '{args['link_type_name']}' not found. "
                                 f"Available: {list(lt_map)}"}

            with service.db.connect() as conn:
                from_node = service.nodes.get_by_source(conn, from_gid, args["from_source_id"])
                to_node   = service.nodes.get_by_source(conn, to_gid,   args["to_source_id"])

            if not from_node:
                return {"error": f"Node '{args['from_source_id']}' not found in '{args['from_graph_name']}'"}
            if not to_node:
                return {"error": f"Node '{args['to_source_id']}' not found in '{args['to_graph_name']}'"}

            link = service.create_link(
                link_type_id=lt_id,
                from_graph_id=from_gid,
                to_graph_id=to_gid,
                from_node_id=from_node["node_id"],
                to_node_id=to_node["node_id"],
                actor_id=actor_id,
                metadata=args.get("metadata"),
            )
            return {**link, "_from_name": from_node["name"], "_to_name": to_node["name"]}

        if name == "destroy_link":
            service.destroy_link(args["link_id"], actor_id=actor_id)
            return {"destroyed": True, "link_id": args["link_id"]}

        if name == "update_node":
            kwargs = {k: v for k, v in args.items() if k != "node_id"}
            return service.update_node(args["node_id"], actor_id=actor_id, **kwargs)

        if name == "get_graph_history":
            history = service.get_graph_history(args["graph_id"])
            limit = args.get("limit", 20)
            return history[-limit:]

        if name in ("ui_navigate_node", "ui_select_graph"):
            return {"ok": True}

        if name == "remember":
            return service.upsert_memory(
                category=args.get("category", "general"),
                key=args["key"],
                content=args["content"],
            )

        if name == "forget":
            deleted = service.delete_memory(key=args["key"])
            return {"deleted": deleted, "key": args["key"]}

        if name == "execute_batch":
            graphs_list = service.list_graphs()
            gmap = {g["name"]: g["graph_id"] for g in graphs_list}
            gname = args.get("graph_name")
            if not gname or gname not in gmap:
                return {"error": f"Graph '{gname}' not found. Available: {list(gmap.keys())}"}
            lt_id = None
            lt_name = args.get("default_link_type_name")
            if lt_name:
                lt_map = {lt["name"]: lt["link_type_id"] for lt in service.get_link_types()}
                lt_id = lt_map.get(lt_name)
                if not lt_id:
                    return {"error": f"Link type '{lt_name}' not found. Available: {list(lt_map.keys())}"}
            link_ops = args.get("link_operations", [])
            for op in link_ops:
                tgn = op.get("data", {}).pop("to_graph_name", None)
                if tgn:
                    tgid = gmap.get(tgn)
                    if not tgid:
                        return {"error": f"Graph '{tgn}' not found"}
                    op["data"]["to_graph_id"] = tgid
            batch = {
                "graph_id":             gmap[gname],
                "actor_id":             actor_id,
                "default_link_type_id": lt_id,
                "link_operations":      link_ops,
                "node_operations":      args.get("node_operations", []),
            }
            return service.execute_batch(batch, actor_id=actor_id)

        if name == "list_memories":
            return service.list_memories()

        return {"error": f"Unknown tool: {name}"}

    except Exception as exc:  # noqa: BLE001
        log.warning("Tool %s raised: %s", name, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def build_agent_router(service: "BanyanService") -> APIRouter:
    """
    Return a FastAPI router for /api/v1/agent.

    Requires ANTHROPIC_API_KEY in the environment.
    If the key is missing the router is still registered but /chat returns 503.
    """
    try:
        import anthropic as _anthropic  # noqa: PLC0415
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        _client = _anthropic.Anthropic(api_key=api_key) if api_key else None
    except ImportError:
        _client = None

    router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

    # ── POST /chat ─────────────────────────────────────────────────────────

    @router.post("/chat")
    def chat(body: ChatRequest):
        if _client is None:
            raise HTTPException(
                status_code=503,
                detail="Agent not available: ANTHROPIC_API_KEY is not set.",
            )

        session = _sessions.setdefault(body.session_id, [])
        session.append({"role": "user", "content": body.message})

        memories = service.list_memories()
        system_prompt = _build_system(body.context, memories)
        tool_calls_log: list[dict] = []
        actions: list[dict] = []

        for _ in range(_MAX_LOOPS):
            resp = _client.messages.create(
                model=_MODEL,
                system=system_prompt,
                tools=_TOOLS,
                messages=session,
                max_tokens=_MAX_TOKENS,
            )

            # Append assistant turn (may contain text + tool_use blocks)
            session.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "end_turn":
                # Extract the final text reply
                text = next(
                    (b.text for b in resp.content if hasattr(b, "text")),
                    "(no text response)",
                )
                return {"reply": text, "tool_calls": tool_calls_log, "actions": actions}

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        result = _dispatch(block.name, block.input, service, body.actor_id)
                        if block.name in ("ui_navigate_node", "ui_select_graph"):
                            actions.append({"type": block.name[len("ui_"):], **block.input})
                        tool_calls_log.append({
                            "name": block.name,
                            "input": block.input,
                            "result": result,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                session.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason
            break

        return {
            "reply": "Agent loop ended without a final response.",
            "tool_calls": tool_calls_log,
            "actions": actions,
        }

    # ── POST /clear ────────────────────────────────────────────────────────

    @router.post("/clear")
    def clear(body: ClearRequest):
        _sessions.pop(body.session_id, None)
        return {"ok": True}

    # ── GET /memory ────────────────────────────────────────────────────────

    @router.get("/memory")
    def get_memory():
        return service.list_memories()

    return router
