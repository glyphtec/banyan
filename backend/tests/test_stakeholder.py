"""
Stakeholder registry tests.

Covers: StakeholderDAO, BanyanService stakeholder methods,
and the REST endpoints for CRUD + graph/node attachment + resolve.
"""
import pytest

from tests.conftest import ACTOR

HIERARCHICAL_LT_ID = "ba0ba000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph_with_hierarchy(service):
    """
    Create:
        Graph
          $ROOT$
          └── HIERARCHICAL → Parent
                └── HIERARCHICAL → Child
    Returns (graph, parent, child).
    """
    g = service.create_graph("StakeholderGraph", actor_id=ACTOR)
    gid = g["graph_id"]
    root_id = g["root_node_id"]

    parent = service.add_node(gid, "PARENT", "Parent Node", actor_id=ACTOR)
    child  = service.add_node(gid, "CHILD",  "Child Node",  actor_id=ACTOR)

    service.create_link(
        link_type_id=HIERARCHICAL_LT_ID,
        from_graph_id=gid, to_graph_id=gid,
        from_node_id=root_id, to_node_id=parent["node_id"],
        actor_id=ACTOR,
    )
    service.create_link(
        link_type_id=HIERARCHICAL_LT_ID,
        from_graph_id=gid, to_graph_id=gid,
        from_node_id=parent["node_id"], to_node_id=child["node_id"],
        actor_id=ACTOR,
    )
    return g, parent, child


# ===========================================================================
# StakeholderDAO / service CRUD
# ===========================================================================

def test_create_and_get_stakeholder(service):
    s = service.create_stakeholder(
        name="Alice", org="ACME", contact_ref="alice@acme.com", notes="Primary owner"
    )
    assert s["name"] == "Alice"
    assert s["org"] == "ACME"
    fetched = service.get_stakeholder(s["stakeholder_id"])
    assert fetched["stakeholder_id"] == s["stakeholder_id"]


def test_list_stakeholders(service):
    service.create_stakeholder(name="Bob")
    service.create_stakeholder(name="Carol")
    names = {s["name"] for s in service.list_stakeholders()}
    assert {"Bob", "Carol"}.issubset(names)


def test_update_stakeholder(service):
    s = service.create_stakeholder(name="Dave")
    updated = service.update_stakeholder(s["stakeholder_id"], org="Updated Corp")
    assert updated["org"] == "Updated Corp"
    assert updated["name"] == "Dave"


def test_delete_stakeholder(service):
    s = service.create_stakeholder(name="Ephemeral")
    service.delete_stakeholder(s["stakeholder_id"])
    with pytest.raises(KeyError):
        service.get_stakeholder(s["stakeholder_id"])


def test_get_stakeholder_not_found(service):
    with pytest.raises(KeyError):
        service.get_stakeholder("ffffffff-ffff-ffff-ffff-ffffffffffff")


# ===========================================================================
# Graph-level attachment
# ===========================================================================

def test_attach_and_list_graph_stakeholder(service):
    g, _, _ = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="GraphOwner")
    service.attach_stakeholder_to_graph(g["graph_id"], s["stakeholder_id"], role="OWNER")
    rows = service.list_graph_stakeholders(g["graph_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in rows)
    assert rows[0]["role"] == "OWNER"


def test_detach_graph_stakeholder(service):
    g, _, _ = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="TempWatcher")
    service.attach_stakeholder_to_graph(g["graph_id"], s["stakeholder_id"], role="WATCHER")
    service.detach_stakeholder_from_graph(g["graph_id"], s["stakeholder_id"])
    rows = service.list_graph_stakeholders(g["graph_id"])
    assert not any(r["stakeholder_id"] == s["stakeholder_id"] for r in rows)


def test_upsert_graph_stakeholder_role(service):
    """Attaching the same stakeholder twice updates the role (upsert)."""
    g, _, _ = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="RoleChanger")
    service.attach_stakeholder_to_graph(g["graph_id"], s["stakeholder_id"], role="WATCHER")
    service.attach_stakeholder_to_graph(g["graph_id"], s["stakeholder_id"], role="APPROVER")
    rows = service.list_graph_stakeholders(g["graph_id"])
    match = next(r for r in rows if r["stakeholder_id"] == s["stakeholder_id"])
    assert match["role"] == "APPROVER"


# ===========================================================================
# Node-level attachment
# ===========================================================================

def test_attach_and_list_node_stakeholder(service):
    g, parent, _ = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="NodeOwner")
    service.attach_stakeholder_to_node(
        parent["node_id"], s["stakeholder_id"], role="OWNER", scope="NODE_ONLY"
    )
    rows = service.list_node_stakeholders(parent["node_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in rows)


def test_invalid_scope_raises(service):
    g, parent, _ = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="ScopeTest")
    with pytest.raises(ValueError, match="scope"):
        service.attach_stakeholder_to_node(
            parent["node_id"], s["stakeholder_id"], role="WATCHER", scope="INVALID"
        )


# ===========================================================================
# Reverse resolution — resolve_stakeholders_for_node
# ===========================================================================

def test_resolve_node_only_scope(service):
    g, parent, child = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="NodeOnlyStakeholder")
    service.attach_stakeholder_to_node(
        parent["node_id"], s["stakeholder_id"], role="WATCHER", scope="NODE_ONLY"
    )
    # Attached to parent — should appear when resolving parent
    parent_result = service.resolve_stakeholders_for_node(parent["node_id"], g["graph_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in parent_result)

    # Should NOT appear when resolving child (NODE_ONLY, not SUBGRAPH)
    child_result = service.resolve_stakeholders_for_node(child["node_id"], g["graph_id"])
    assert not any(r["stakeholder_id"] == s["stakeholder_id"] for r in child_result)


def test_resolve_subgraph_scope(service):
    g, parent, child = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="SubgraphStakeholder")
    service.attach_stakeholder_to_node(
        parent["node_id"], s["stakeholder_id"], role="OWNER", scope="SUBGRAPH"
    )
    # Stakeholder attached to parent with SUBGRAPH scope
    # Should appear when resolving child (descendant of parent)
    child_result = service.resolve_stakeholders_for_node(child["node_id"], g["graph_id"])
    sids = {r["stakeholder_id"] for r in child_result}
    assert s["stakeholder_id"] in sids

    # Should also appear when resolving parent itself
    parent_result = service.resolve_stakeholders_for_node(parent["node_id"], g["graph_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in parent_result)


def test_resolve_ancestors_scope(service):
    g, parent, child = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="AncestorsStakeholder")
    # Attach at child with ANCESTORS scope — anyone who changes an ancestor of child
    # is of interest.  Resolving PARENT (an ancestor of child) should return this stakeholder.
    service.attach_stakeholder_to_node(
        child["node_id"], s["stakeholder_id"], role="WATCHER", scope="ANCESTORS"
    )
    # Resolving parent: parent is an ancestor of the attachment root (child)
    parent_result = service.resolve_stakeholders_for_node(parent["node_id"], g["graph_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in parent_result)

    # Resolving child itself: child is in its own ancestor chain (base case)
    child_result = service.resolve_stakeholders_for_node(child["node_id"], g["graph_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in child_result)


def test_resolve_graph_scope(service):
    g, parent, child = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="GraphWatcher")
    service.attach_stakeholder_to_graph(g["graph_id"], s["stakeholder_id"], role="WATCHER")
    # Graph-level attachment should surface for any node in the graph
    result = service.resolve_stakeholders_for_node(child["node_id"], g["graph_id"])
    assert any(r["stakeholder_id"] == s["stakeholder_id"] for r in result)


def test_resolve_returns_all_applicable_scopes(service):
    """A stakeholder attached at multiple scopes appears once per scope (UNION)."""
    g, parent, child = _make_graph_with_hierarchy(service)
    s = service.create_stakeholder(name="MultiScope")
    service.attach_stakeholder_to_node(
        parent["node_id"], s["stakeholder_id"], role="OWNER", scope="SUBGRAPH"
    )
    service.attach_stakeholder_to_graph(g["graph_id"], s["stakeholder_id"], role="WATCHER")
    # Resolving child: should find stakeholder via both SUBGRAPH and GRAPH
    result = service.resolve_stakeholders_for_node(child["node_id"], g["graph_id"])
    types = {r["attachment_type"] for r in result if r["stakeholder_id"] == s["stakeholder_id"]}
    assert "SUBGRAPH" in types
    assert "GRAPH" in types


# ===========================================================================
# REST endpoints
# ===========================================================================

HEADERS = {"X-Actor-Id": "test-actor"}


def test_rest_stakeholder_crud(client):
    # Create
    r = client.post("/api/v1/stakeholders", json={"name": "REST Owner", "org": "Org A"})
    assert r.status_code == 201
    sid = r.json()["stakeholder_id"]

    # Get
    r = client.get(f"/api/v1/stakeholders/{sid}")
    assert r.status_code == 200
    assert r.json()["name"] == "REST Owner"

    # List
    r = client.get("/api/v1/stakeholders")
    assert r.status_code == 200
    assert any(s["stakeholder_id"] == sid for s in r.json())

    # Update
    r = client.patch(f"/api/v1/stakeholders/{sid}", json={"org": "Org B"})
    assert r.status_code == 200
    assert r.json()["org"] == "Org B"

    # Delete
    r = client.delete(f"/api/v1/stakeholders/{sid}")
    assert r.status_code == 204

    r = client.get(f"/api/v1/stakeholders/{sid}")
    assert r.status_code == 404


def test_rest_graph_stakeholder_attach_and_resolve(client):
    g = client.post("/api/v1/graphs", json={"name": "SH Graph"}, headers=HEADERS).json()
    gid = g["graph_id"]
    s = client.post("/api/v1/stakeholders", json={"name": "SH Test"}).json()
    sid = s["stakeholder_id"]

    r = client.post(f"/api/v1/graphs/{gid}/stakeholders",
                    json={"stakeholder_id": sid, "role": "OWNER"})
    assert r.status_code == 204

    r = client.get(f"/api/v1/graphs/{gid}/stakeholders")
    assert r.status_code == 200
    assert any(row["stakeholder_id"] == sid for row in r.json())

    r = client.delete(f"/api/v1/graphs/{gid}/stakeholders/{sid}")
    assert r.status_code == 204


def test_rest_node_stakeholder_resolve(client):
    g = client.post("/api/v1/graphs", json={"name": "NodeSH"}, headers=HEADERS).json()
    gid = g["graph_id"]
    node = client.post(f"/api/v1/graphs/{gid}/nodes",
                       json={"source_id": "N1", "name": "SH Node"}, headers=HEADERS).json()
    nid = node["node_id"]

    s = client.post("/api/v1/stakeholders", json={"name": "NodeSH Owner"}).json()
    sid = s["stakeholder_id"]

    r = client.post(f"/api/v1/nodes/{nid}/stakeholders",
                    json={"stakeholder_id": sid, "role": "OWNER", "scope": "NODE_ONLY"})
    assert r.status_code == 204

    r = client.get(f"/api/v1/nodes/{nid}/stakeholders/resolve",
                   params={"graph_id": gid})
    assert r.status_code == 200
    assert any(row["stakeholder_id"] == sid for row in r.json())
