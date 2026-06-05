"""REST API integration tests."""
from tests.conftest import ACTOR

HEADERS = {"x-actor-id": ACTOR}


# ── Graph endpoints ───────────────────────────────────────────────────────────

def test_create_graph(client):
    r = client.post("/api/v1/graphs", json={"name": "Plants"}, headers=HEADERS)
    assert r.status_code == 201
    assert r.json()["name"] == "Plants"


def test_list_graphs(client):
    client.post("/api/v1/graphs", json={"name": "G1"}, headers=HEADERS)
    client.post("/api/v1/graphs", json={"name": "G2"}, headers=HEADERS)
    r = client.get("/api/v1/graphs")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_get_graph_not_found(client):
    r = client.get("/api/v1/graphs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_update_graph(client):
    r = client.post("/api/v1/graphs", json={"name": "Old"}, headers=HEADERS)
    gid = r.json()["graph_id"]
    r2 = client.patch(f"/api/v1/graphs/{gid}", json={"name": "New"}, headers=HEADERS)
    assert r2.status_code == 200
    assert r2.json()["name"] == "New"


# ── Node endpoints ────────────────────────────────────────────────────────────

def test_add_and_get_node(client):
    g = client.post("/api/v1/graphs", json={"name": "G"}, headers=HEADERS).json()
    gid = g["graph_id"]
    r = client.post(f"/api/v1/graphs/{gid}/nodes",
                    json={"source_id": "A-001", "name": "Alpha"},
                    headers=HEADERS)
    assert r.status_code == 201
    nid = r.json()["node_id"]
    r2 = client.get(f"/api/v1/nodes/{nid}")
    assert r2.status_code == 200
    assert r2.json()["source_id"] == "A-001"


def test_list_nodes(client):
    g = client.post("/api/v1/graphs", json={"name": "G"}, headers=HEADERS).json()
    gid = g["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "N1", "name": "N1"}, headers=HEADERS)
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "N2", "name": "N2"}, headers=HEADERS)
    r = client.get(f"/api/v1/graphs/{gid}/nodes")
    assert len(r.json()) == 2


def test_update_node(client):
    g = client.post("/api/v1/graphs", json={"name": "G"}, headers=HEADERS).json()
    gid = g["graph_id"]
    n = client.post(f"/api/v1/graphs/{gid}/nodes",
                    json={"source_id": "N1", "name": "Old"}, headers=HEADERS).json()
    r = client.patch(f"/api/v1/nodes/{n['node_id']}",
                     json={"name": "New"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["name"] == "New"


def test_delete_node_blocked_without_force(client):
    g = client.post("/api/v1/graphs", json={"name": "G"}, headers=HEADERS).json()
    gid = g["graph_id"]
    p = client.post(f"/api/v1/graphs/{gid}/nodes",
                    json={"source_id": "P", "name": "Parent"}, headers=HEADERS).json()
    c = client.post(f"/api/v1/graphs/{gid}/nodes",
                    json={"source_id": "C", "name": "Child"}, headers=HEADERS).json()
    lt_id = next(
        lt["link_type_id"]
        for lt in client.get("/api/v1/link-types").json()
        if lt["name"] == "HIERARCHICAL"
    )
    client.post("/api/v1/links", json={
        "link_type_id": lt_id,
        "from_graph_id": gid, "to_graph_id": gid,
        "from_node_id": p["node_id"], "to_node_id": c["node_id"],
    }, headers=HEADERS)
    r = client.delete(f"/api/v1/nodes/{p['node_id']}", headers=HEADERS)
    assert r.status_code == 400


# ── Link endpoints ────────────────────────────────────────────────────────────

def test_create_and_get_link(client):
    g = client.post("/api/v1/graphs", json={"name": "G"}, headers=HEADERS).json()
    gid = g["graph_id"]
    p = client.post(f"/api/v1/graphs/{gid}/nodes",
                    json={"source_id": "P", "name": "P"}, headers=HEADERS).json()
    c = client.post(f"/api/v1/graphs/{gid}/nodes",
                    json={"source_id": "C", "name": "C"}, headers=HEADERS).json()
    lt_id = next(
        lt["link_type_id"]
        for lt in client.get("/api/v1/link-types").json()
        if lt["name"] == "HIERARCHICAL"
    )
    r = client.post("/api/v1/links", json={
        "link_type_id": lt_id,
        "from_graph_id": gid, "to_graph_id": gid,
        "from_node_id": p["node_id"], "to_node_id": c["node_id"],
    }, headers=HEADERS)
    assert r.status_code == 201
    lid = r.json()["link_id"]
    r2 = client.get(f"/api/v1/links/{lid}")
    assert r2.status_code == 200
    assert r2.json()["from_node_id"] == p["node_id"]


# ── Lookup + History ─────────────────────────────────────────────────────────

def test_get_link_types(client):
    r = client.get("/api/v1/link-types")
    assert r.status_code == 200
    names = {lt["name"] for lt in r.json()}
    assert names == {"HIERARCHICAL", "RELATED", "SYNONYM"}


def test_get_node_types(client):
    r = client.get("/api/v1/node-types")
    assert r.status_code == 200
    assert any(nt["name"] == "Generic" for nt in r.json())


def test_graph_history_after_mutations(client):
    g = client.post("/api/v1/graphs", json={"name": "G"}, headers=HEADERS).json()
    gid = g["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "N1", "name": "N1"}, headers=HEADERS)
    r = client.get(f"/api/v1/graphs/{gid}/history")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["primitive_verb"] == "ADD_NODE"

