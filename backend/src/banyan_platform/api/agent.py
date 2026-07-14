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
_MAX_LOOPS   = 10      # safety guard against runaway tool-call loops

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
"""


def _build_system(context: dict | None) -> str:
    if not context:
        return _SYSTEM_BASE
    parts = [_SYSTEM_BASE, "\nCURRENT UI CONTEXT"]
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
            "    {\"graph\":{\"name\":\"Gravity SDOH Clinical Care STU 2.3\"},\"starting\":{\"name\":\"Food Insecurity\"},\"steps\":[{\"direction\":\"FROM\",\"link_types\":[\"HIERARCHICAL\"],\"depth\":1,\"collect\":false},{\"direction\":\"FROM\",\"link_types\":[\"HAS_MEMBER!\"],\"graphs\":[\"SNOMED CT SDOH Slice\"],\"depth\":1}],\"result\":{\"format\":\"NODE\",\"include_seed\":false}}"
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
                }
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
            # Trim large result sets to keep context manageable
            if isinstance(result.get("results"), list) and len(result["results"]) > 50:
                trimmed = result["results"][:50]
                result = {**result, "results": trimmed,
                          "_truncated": True, "_total": result.get("total_count")}
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

    # ── Request / response models ─────────────────────────────────────────

    class ChatRequest(BaseModel):
        session_id: str
        message: str
        context: dict | None = None
        actor_id: str = _AGENT_ACTOR

    class ClearRequest(BaseModel):
        session_id: str

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

        system_prompt = _build_system(body.context)
        tool_calls_log: list[dict] = []

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
                return {"reply": text, "tool_calls": tool_calls_log}

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        result = _dispatch(block.name, block.input, service, body.actor_id)
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
        }

    # ── POST /clear ────────────────────────────────────────────────────────

    @router.post("/clear")
    def clear(body: ClearRequest):
        _sessions.pop(body.session_id, None)
        return {"ok": True}

    return router
