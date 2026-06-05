"""
Tests for the MCP server layer (api/mcp_server.py).

Strategy:
- Call build_mcp_server(service) and verify the server is configured.
- Call each tool via mcp.call_tool() (same dispatch path an LLM agent uses).
  ToolResult.structured_content holds the raw dict the tool returned.
- Verify that app.py mounts the MCP sub-app at /mcp.
"""

from __future__ import annotations

import asyncio

import pytest

from banyan_platform.api.mcp_server import build_mcp_server
from banyan_platform.app import create_app
from banyan_platform.config import DatabaseConfig
from banyan_platform.persistence.connection import create_database
from banyan_platform.persistence.ddl import bootstrap
from banyan_platform.services.taxonomy_service import BanyanService

ACTOR = "test-mcp-agent"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    cfg = DatabaseConfig(dialect="duckdb", duckdb_path=":memory:")
    _db = create_database(cfg)
    bootstrap(_db)
    return _db


@pytest.fixture
def service(db):
    return BanyanService(db)


@pytest.fixture
def mcp_server(service):
    return build_mcp_server(service)


def _call(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _data(result):
    """Extract the structured dict/list from a FastMCP ToolResult.

    FastMCP wraps list return values as {"result": [...]}.  Unwrap that.
    """
    assert not result.is_error, result.content
    data = result.structured_content
    if isinstance(data, dict) and set(data.keys()) == {"result"}:
        return data["result"]
    return data


# ---------------------------------------------------------------------------
# Server structure tests
# ---------------------------------------------------------------------------


def test_mcp_server_has_name(mcp_server):
    assert mcp_server.name == "Banyan"


def test_mcp_server_tools_registered(mcp_server):
    """All expected tools must appear in list_tools()."""
    tools = _call(mcp_server.list_tools())
    names = {t.name for t in tools}
    expected = {
        "create_graph", "get_graph", "list_graphs", "update_graph", "delete_graph",
        "add_node", "get_node", "list_nodes", "update_node", "delete_node",
        "create_link", "get_link", "update_link", "destroy_link",
        "get_children", "get_parents",
        "get_subtree", "get_ancestors", "get_impact_summary",
        "create_snapshot", "list_snapshots",
        "get_link_types", "get_node_types",
        "get_graph_history",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


# ---------------------------------------------------------------------------
# Graph tool tests
# ---------------------------------------------------------------------------


def test_mcp_create_and_get_graph(mcp_server):
    data = _data(_call(mcp_server.call_tool("create_graph", {"name": "Animals", "actor_id": ACTOR})))
    graph_id = data["graph_id"]
    assert graph_id

    data2 = _data(_call(mcp_server.call_tool("get_graph", {"graph_id": graph_id})))
    assert data2["name"] == "Animals"


def test_mcp_list_graphs(mcp_server):
    _call(mcp_server.call_tool("create_graph", {"name": "Plants", "actor_id": ACTOR}))
    graphs = _data(_call(mcp_server.call_tool("list_graphs", {})))
    assert isinstance(graphs, list)
    assert any(g["name"] == "Plants" for g in graphs)


# ---------------------------------------------------------------------------
# Node tool tests
# ---------------------------------------------------------------------------


def test_mcp_add_and_get_node(mcp_server):
    graph_id = _data(_call(mcp_server.call_tool(
        "create_graph", {"name": "TestGraph", "actor_id": ACTOR}
    )))["graph_id"]

    node_id = _data(_call(mcp_server.call_tool(
        "add_node", {"graph_id": graph_id, "source_id": "MAMMAL-01", "name": "Mammal", "actor_id": ACTOR}
    )))["node_id"]
    assert node_id

    node = _data(_call(mcp_server.call_tool("get_node", {"node_id": node_id})))
    assert node["name"] == "Mammal"


def test_mcp_list_nodes(mcp_server):
    graph_id = _data(_call(mcp_server.call_tool(
        "create_graph", {"name": "G2", "actor_id": ACTOR}
    )))["graph_id"]

    _call(mcp_server.call_tool("add_node", {"graph_id": graph_id, "source_id": "ALPHA-01", "name": "Alpha", "actor_id": ACTOR}))
    _call(mcp_server.call_tool("add_node", {"graph_id": graph_id, "source_id": "BETA-01", "name": "Beta", "actor_id": ACTOR}))

    nodes = _data(_call(mcp_server.call_tool("list_nodes", {"graph_id": graph_id})))
    assert len(nodes) == 2


# ---------------------------------------------------------------------------
# Lookup tool tests
# ---------------------------------------------------------------------------


def test_mcp_get_link_types(mcp_server):
    link_types = _data(_call(mcp_server.call_tool("get_link_types", {})))
    assert isinstance(link_types, list)
    assert "HIERARCHICAL" in {lt["name"] for lt in link_types}


def test_mcp_get_node_types(mcp_server):
    node_types = _data(_call(mcp_server.call_tool("get_node_types", {})))
    assert isinstance(node_types, list)
    assert len(node_types) >= 1


# ---------------------------------------------------------------------------
# App mount test
# ---------------------------------------------------------------------------


def test_app_mounts_mcp():
    """create_app() should mount the MCP sub-app at /mcp."""
    app = create_app(DatabaseConfig(dialect="duckdb", duckdb_path=":memory:"))
    mount_paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mcp" in mount_paths, f"Expected /mcp mount, got: {mount_paths}"
