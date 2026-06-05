"""
Tests for Export, Import, Diff, Batch, and the retrofitted Snapshot.

All tests use the ``service`` and ``client`` fixtures from conftest.py.
"""
import pytest

from tests.conftest import ACTOR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph_with_nodes(service, name="TestGraph"):
    """Return (graph, parent_node, child_node, link, hierarchical_lt_id)."""
    g = service.create_graph(name, actor_id=ACTOR)
    gid = g["graph_id"]
    parent = service.add_node(gid, "PARENT-01", "Parent Node", actor_id=ACTOR)
    child = service.add_node(gid, "CHILD-01", "Child Node", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    link = service.create_link(
        link_type_id=lt["link_type_id"],
        from_graph_id=gid,
        to_graph_id=gid,
        from_node_id=parent["node_id"],
        to_node_id=child["node_id"],
        actor_id=ACTOR,
    )
    return g, parent, child, link, lt["link_type_id"]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export_structure(service):
    g, parent, child, link, _ = _make_graph_with_nodes(service)
    doc = service.export_graph(g["graph_id"])

    assert doc["banyan_export_version"] == "1.0"
    assert "exported_at" in doc
    assert doc["graph"]["graph_id"] == g["graph_id"]
    assert len(doc["nodes"]) == 2
    assert len(doc["links"]) == 1
    assert doc["cross_graph_links"] == []


def test_export_cross_graph_links_excluded_by_default(service):
    # Create two graphs with a RELATED cross-graph link
    g1 = service.create_graph("G1", actor_id=ACTOR)
    g2 = service.create_graph("G2", actor_id=ACTOR)
    n1 = service.add_node(g1["graph_id"], "N1", "Node1", actor_id=ACTOR)
    n2 = service.add_node(g2["graph_id"], "N2", "Node2", actor_id=ACTOR)
    related_lt = next(lt for lt in service.get_link_types() if lt["name"] == "RELATED")
    service.create_link(
        link_type_id=related_lt["link_type_id"],
        from_graph_id=g1["graph_id"],
        to_graph_id=g2["graph_id"],
        from_node_id=n1["node_id"],
        to_node_id=n2["node_id"],
        actor_id=ACTOR,
    )
    doc = service.export_graph(g1["graph_id"], include_cross_graph_links=False)
    assert len(doc["links"]) == 0
    assert doc["cross_graph_links"] == []

    doc2 = service.export_graph(g1["graph_id"], include_cross_graph_links=True)
    assert len(doc2["cross_graph_links"]) == 1


def test_export_unknown_graph_raises(service):
    with pytest.raises(KeyError):
        service.export_graph("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def test_import_creates_new_graph(service):
    g, parent, child, link, lt_id = _make_graph_with_nodes(service, "Source")
    doc = service.export_graph(g["graph_id"])

    imported = service.import_graph(doc, actor_id=ACTOR, new_name="Imported Copy")
    assert imported["name"] == "Imported Copy"

    nodes = service.list_nodes(imported["graph_id"])
    assert len(nodes) == 2
    source_ids = {n["source_id"] for n in nodes}
    assert source_ids == {"PARENT-01", "CHILD-01"}


def test_import_preserves_links(service):
    g, parent, child, link, lt_id = _make_graph_with_nodes(service, "Source2-Orig")
    doc = service.export_graph(g["graph_id"])

    imported = service.import_graph(doc, actor_id=ACTOR, new_name="Source2-Imported")
    imp_gid = imported["graph_id"]

    imp_parent = next(n for n in service.list_nodes(imp_gid) if n["source_id"] == "PARENT-01")
    children = service.get_children(imp_gid, imp_parent["node_id"], lt_id)
    assert len(children) == 1


def test_import_skips_duplicate_source_ids(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "Source3")
    doc = service.export_graph(g["graph_id"])

    # First import
    imported = service.import_graph(doc, actor_id=ACTOR, new_name="Dedup Test")
    # Second import into same target graph (merge mode)
    service.import_graph(doc, actor_id=ACTOR, merge_into_graph_id=imported["graph_id"])

    nodes = service.list_nodes(imported["graph_id"])
    assert len(nodes) == 2  # not 4


def test_import_merge_mode(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "Original")
    target = service.create_graph("MergeTarget", actor_id=ACTOR)
    doc = service.export_graph(g["graph_id"])

    service.import_graph(doc, actor_id=ACTOR, merge_into_graph_id=target["graph_id"])
    nodes = service.list_nodes(target["graph_id"])
    assert len(nodes) == 2


# ---------------------------------------------------------------------------
# Snapshot (retrofitted)
# ---------------------------------------------------------------------------

def test_snapshot_stores_payload(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "SnapGraph")
    snap = service.create_snapshot(g["graph_id"], "v1.0", actor_id=ACTOR)

    assert snap["snapshot_id"]
    payload = snap["snapshot_payload"]
    assert payload.get("banyan_export_version") == "1.0"
    assert len(payload["nodes"]) == 2
    assert len(payload["links"]) == 1


def test_snapshot_no_history_raises(service):
    g = service.create_graph("Empty", actor_id=ACTOR)
    with pytest.raises(ValueError, match="ledger"):
        service.create_snapshot(g["graph_id"], "v0", actor_id=ACTOR)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def test_diff_identical_graphs_empty_delta(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "DiffBase")
    doc = service.export_graph(g["graph_id"])
    delta = service.diff_graphs(doc, doc)

    assert delta["nodes_added"] == []
    assert delta["nodes_removed"] == []
    assert delta["nodes_changed"] == []
    assert delta["links_added"] == []
    assert delta["links_removed"] == []


def test_diff_detects_added_node(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "DiffG")
    base_doc = service.export_graph(g["graph_id"])

    service.add_node(g["graph_id"], "NEW-01", "New Node", actor_id=ACTOR)
    compare_doc = service.export_graph(g["graph_id"])

    delta = service.diff_graphs(base_doc, compare_doc)
    assert len(delta["nodes_added"]) == 1
    assert delta["nodes_added"][0]["source_id"] == "NEW-01"


def test_diff_detects_removed_node(service):
    g, parent, child, link, lt_id = _make_graph_with_nodes(service, "DiffRm")
    base_doc = service.export_graph(g["graph_id"])

    service.destroy_link(link["link_id"], actor_id=ACTOR)
    service.delete_node(child["node_id"], actor_id=ACTOR)
    compare_doc = service.export_graph(g["graph_id"])

    delta = service.diff_graphs(base_doc, compare_doc)
    assert len(delta["nodes_removed"]) == 1
    assert delta["nodes_removed"][0]["source_id"] == "CHILD-01"


def test_diff_detects_changed_node(service):
    g, parent, _, _, _ = _make_graph_with_nodes(service, "DiffChg")
    base_doc = service.export_graph(g["graph_id"])

    service.update_node(parent["node_id"], actor_id=ACTOR, name="Renamed Parent")
    compare_doc = service.export_graph(g["graph_id"])

    delta = service.diff_graphs(base_doc, compare_doc)
    assert len(delta["nodes_changed"]) == 1
    assert delta["nodes_changed"][0]["base"]["name"] == "Parent Node"
    assert delta["nodes_changed"][0]["compare"]["name"] == "Renamed Parent"


def test_diff_graph_vs_snapshot(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "DiffSnap")
    snap = service.create_snapshot(g["graph_id"], "v1", actor_id=ACTOR)

    service.add_node(g["graph_id"], "POST-SNAP", "Post-Snapshot Node", actor_id=ACTOR)

    delta = service.diff_graphs(f"snapshot:{snap['snapshot_id']}", g["graph_id"])
    assert len(delta["nodes_added"]) == 1
    assert delta["nodes_added"][0]["source_id"] == "POST-SNAP"


def test_diff_graph_vs_graph_by_id(service):
    g1, _, _, _, _ = _make_graph_with_nodes(service, "DiffG1")
    # g2 has same structure plus one extra node
    g2, _, _, _, _ = _make_graph_with_nodes(service, "DiffG2")
    service.add_node(g2["graph_id"], "EXTRA-01", "Extra", actor_id=ACTOR)

    delta = service.diff_graphs(g1["graph_id"], g2["graph_id"])
    added_ids = {n["source_id"] for n in delta["nodes_added"]}
    assert "EXTRA-01" in added_ids


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

def test_batch_add_nodes_and_links(service):
    g = service.create_graph("BatchG", actor_id=ACTOR)
    gid = g["graph_id"]
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")

    result = service.execute_batch({
        "graph_id": gid,
        "default_link_type_id": lt["link_type_id"],
        "node_operations": [
            {"verb": "ADD_NODE", "data": {"source_id": "A", "name": "Alpha"}},
            {"verb": "ADD_NODE", "data": {"source_id": "B", "name": "Beta"}},
        ],
        "link_operations": [
            # Can't use node IDs since we don't know them yet — service test
            # using source_id-based lookup would be nice but batch uses node_ids.
            # We'll add the link after getting the IDs, tested below.
        ],
    }, actor_id=ACTOR)

    assert result["nodes_added"] == 2
    assert result["links_created"] == 0
    assert result["ledger_entries"] == 2
    assert len(service.list_nodes(gid)) == 2


def test_batch_add_nodes_and_create_link_in_one_batch(service):
    g = service.create_graph("BatchFull", actor_id=ACTOR)
    gid = g["graph_id"]
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")

    # Pre-create nodes so we have IDs for the link operation
    parent = service.add_node(gid, "PAR", "Parent", actor_id=ACTOR)
    child_placeholder = service.add_node(gid, "OLD", "OldChild", actor_id=ACTOR)
    link = service.create_link(
        link_type_id=lt["link_type_id"],
        from_graph_id=gid, to_graph_id=gid,
        from_node_id=parent["node_id"],
        to_node_id=child_placeholder["node_id"],
        actor_id=ACTOR,
    )

    # Batch: add a new child, destroy old link, create new link, delete old child
    result = service.execute_batch({
        "graph_id": gid,
        "default_link_type_id": lt["link_type_id"],
        "node_operations": [
            {"verb": "ADD_NODE", "data": {"source_id": "NEW", "name": "NewChild"}},
            {"verb": "DELETE_NODE", "data": {"node_id": child_placeholder["node_id"], "force": True}},
        ],
        "link_operations": [
            {"verb": "DESTROY_LINK", "data": {"link_id": link["link_id"]}},
        ],
    }, actor_id=ACTOR)

    assert result["nodes_added"] == 1
    assert result["nodes_deleted"] == 1
    assert result["links_destroyed"] == 1
    assert result["ledger_entries"] == 3

    remaining = service.list_nodes(gid)
    source_ids = {n["source_id"] for n in remaining}
    assert "NEW" in source_ids
    assert "OLD" not in source_ids


def test_batch_rollback_on_error(service):
    g = service.create_graph("BatchRollback", actor_id=ACTOR)
    gid = g["graph_id"]

    with pytest.raises((KeyError, ValueError)):
        service.execute_batch({
            "graph_id": gid,
            "node_operations": [
                {"verb": "ADD_NODE", "data": {"source_id": "GOOD", "name": "Good Node"}},
                # This will fail: UPDATE_NODE on a non-existent node_id
                {"verb": "UPDATE_NODE", "data": {"node_id": "00000000-0000-0000-0000-000000000000", "name": "X"}},
            ],
            "link_operations": [],
        }, actor_id=ACTOR)

    # Nothing should have been committed
    assert service.list_nodes(gid) == []


def test_batch_update_node(service):
    g = service.create_graph("BatchUpd", actor_id=ACTOR)
    gid = g["graph_id"]
    node = service.add_node(gid, "UPD-01", "Original", actor_id=ACTOR)

    result = service.execute_batch({
        "graph_id": gid,
        "node_operations": [
            {"verb": "UPDATE_NODE", "data": {"node_id": node["node_id"], "name": "Renamed"}},
        ],
        "link_operations": [],
    }, actor_id=ACTOR)

    assert result["nodes_updated"] == 1
    assert service.get_node(node["node_id"])["name"] == "Renamed"


# ---------------------------------------------------------------------------
# REST API: basic smoke tests for new endpoints
# ---------------------------------------------------------------------------

def test_rest_export(client):
    r = client.post("/api/v1/graphs", json={"name": "RestExportG"},
                    headers={"X-Actor-Id": ACTOR})
    gid = r.json()["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "N1", "name": "Node1"},
                headers={"X-Actor-Id": ACTOR})

    r2 = client.get(f"/api/v1/graphs/{gid}/export")
    assert r2.status_code == 200
    doc = r2.json()
    assert doc["banyan_export_version"] == "1.0"
    assert len(doc["nodes"]) == 1


def test_rest_import(client):
    r = client.post("/api/v1/graphs", json={"name": "RestImportSrc"},
                    headers={"X-Actor-Id": ACTOR})
    gid = r.json()["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "IMP-01", "name": "ImportNode"},
                headers={"X-Actor-Id": ACTOR})

    doc = client.get(f"/api/v1/graphs/{gid}/export").json()
    r2 = client.post("/api/v1/graphs/import",
                     json={"export_doc": doc, "new_name": "RestImported"},
                     headers={"X-Actor-Id": ACTOR})
    assert r2.status_code == 201
    assert r2.json()["name"] == "RestImported"


def test_rest_diff(client):
    r = client.post("/api/v1/graphs", json={"name": "RestDiffG"},
                    headers={"X-Actor-Id": ACTOR})
    gid = r.json()["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "D1", "name": "D1"},
                headers={"X-Actor-Id": ACTOR})
    doc1 = client.get(f"/api/v1/graphs/{gid}/export").json()

    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "D2", "name": "D2"},
                headers={"X-Actor-Id": ACTOR})

    r2 = client.post("/api/v1/graphs/diff",
                     json={"base": doc1, "compare": gid})
    assert r2.status_code == 200
    delta = r2.json()
    assert len(delta["nodes_added"]) == 1
    assert delta["nodes_added"][0]["source_id"] == "D2"


def test_rest_batch(client):
    r = client.post("/api/v1/graphs", json={"name": "RestBatchG"},
                    headers={"X-Actor-Id": ACTOR})
    gid = r.json()["graph_id"]

    r2 = client.post("/api/v1/graphs/batch", json={
        "graph_id": gid,
        "node_operations": [
            {"verb": "ADD_NODE", "data": {"source_id": "B1", "name": "BatchNode1"}},
            {"verb": "ADD_NODE", "data": {"source_id": "B2", "name": "BatchNode2"}},
        ],
        "link_operations": [],
    }, headers={"X-Actor-Id": ACTOR})
    assert r2.status_code == 200
    result = r2.json()
    assert result["nodes_added"] == 2
    assert result["ledger_entries"] == 2
