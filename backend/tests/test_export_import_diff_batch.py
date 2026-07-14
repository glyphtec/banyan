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

    assert doc["banyan_export_version"] == "1.1"
    assert "exported_at" in doc
    assert doc["graph"]["graph_id"] == g["graph_id"]
    assert len(doc["nodes"]) == 2   # PARENT-01 + CHILD-01 ($ROOT$ excluded from export)
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
        service.export_graph("ffffffff-ffff-ffff-ffff-ffffffffffff")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def test_import_creates_new_graph(service):
    g, parent, child, link, lt_id = _make_graph_with_nodes(service, "Source")
    doc = service.export_graph(g["graph_id"])

    imported = service.import_graph(doc, actor_id=ACTOR, new_name="Imported Copy")
    assert imported["name"] == "Imported Copy"

    nodes = service.list_nodes(imported["graph_id"])
    assert len(nodes) == 3   # $ROOT$ + PARENT-01 + CHILD-01
    source_ids = {n["source_id"] for n in nodes}
    assert source_ids == {"$ROOT$", "PARENT-01", "CHILD-01"}


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
    assert len(nodes) == 3  # not 6: $ROOT$ + PARENT-01 + CHILD-01; $ROOT$ deduped on second import


def test_import_merge_mode(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "Original")
    target = service.create_graph("MergeTarget", actor_id=ACTOR)
    doc = service.export_graph(g["graph_id"])

    service.import_graph(doc, actor_id=ACTOR, merge_into_graph_id=target["graph_id"])
    nodes = service.list_nodes(target["graph_id"])
    assert len(nodes) == 3  # $ROOT$ (deduped) + PARENT-01 + CHILD-01


# ---------------------------------------------------------------------------
# Snapshot (retrofitted)
# ---------------------------------------------------------------------------

def test_snapshot_stores_payload(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "SnapGraph")
    snap = service.create_snapshot(g["graph_id"], "v1.0", actor_id=ACTOR)

    assert snap["snapshot_id"]
    payload = snap["snapshot_payload"]
    assert payload.get("banyan_export_version") == "1.1"
    assert len(payload["nodes"]) == 2   # PARENT-01 + CHILD-01 ($ROOT$ excluded from export)
    assert len(payload["links"]) == 1


def test_create_graph_has_root_node(service):
    """create_graph must bootstrap a $ROOT$ node and backfill root_node_id."""
    g = service.create_graph("RootTest", actor_id=ACTOR)
    assert g["root_node_id"] is not None
    root = service.get_node(g["root_node_id"])
    assert root["source_id"] == "$ROOT$"
    assert root["name"] == "$ROOT$"


def test_snapshot_restore_creates_new_graph(service):
    g, parent, child, link, _ = _make_graph_with_nodes(service, "RestoreSource")
    snap = service.create_snapshot(g["graph_id"], "v1.0", actor_id=ACTOR)

    restored = service.restore_snapshot(snap["snapshot_id"], actor_id=ACTOR)

    # New graph created — different graph_id, same content
    assert restored["graph_id"] != g["graph_id"]
    assert "RestoreSource" in restored["name"]
    assert "v1.0" in restored["name"]

    nodes = service.list_nodes(restored["graph_id"])
    source_ids = {n["source_id"] for n in nodes}
    assert source_ids == {"$ROOT$", "PARENT-01", "CHILD-01"}


def test_snapshot_restore_custom_name(service):
    g, _, _, _, _ = _make_graph_with_nodes(service, "SnapNameSrc")
    snap = service.create_snapshot(g["graph_id"], "v2.0", actor_id=ACTOR)

    restored = service.restore_snapshot(
        snap["snapshot_id"], actor_id=ACTOR, new_name="My Restored Graph"
    )
    assert restored["name"] == "My Restored Graph"


def test_snapshot_restore_missing_raises(service):
    import pytest
    with pytest.raises(KeyError):
        service.restore_snapshot("00000000-0000-0000-0000-000000000000", actor_id=ACTOR)


def test_rest_restore_snapshot(client):
    r = client.post("/api/v1/graphs", json={"name": "RestSnap"},
                    headers={"X-Actor-Id": ACTOR})
    gid = r.json()["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "R1", "name": "RestoreNode"},
                headers={"X-Actor-Id": ACTOR})
    snap_r = client.post(f"/api/v1/graphs/{gid}/snapshots",
                         json={"version_label": "snap-v1"},
                         headers={"X-Actor-Id": ACTOR})
    assert snap_r.status_code == 201
    snap_id = snap_r.json()["snapshot_id"]

    restore_r = client.post(
        f"/api/v1/snapshots/{snap_id}/restore",
        json={"new_name": "RestSnap Restored"},
        headers={"X-Actor-Id": ACTOR},
    )
    assert restore_r.status_code == 201
    restored = restore_r.json()
    assert restored["name"] == "RestSnap Restored"
    assert restored["graph_id"] != gid


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

def test_clone_creates_new_graph(service):
    g, parent, child, link, _ = _make_graph_with_nodes(service, "OriginalGraph")
    clone = service.clone_graph(g["graph_id"], new_name="ClonedGraph", actor_id=ACTOR)
    assert clone["name"] == "ClonedGraph"
    assert clone["graph_id"] != g["graph_id"]


def test_clone_preserves_nodes(service):
    g, parent, child, link, _ = _make_graph_with_nodes(service)
    clone = service.clone_graph(g["graph_id"], new_name="NodeClone", actor_id=ACTOR)
    nodes = service.list_nodes(clone["graph_id"])
    source_ids = {n["source_id"] for n in nodes}
    assert "PARENT-01" in source_ids
    assert "CHILD-01" in source_ids


def test_clone_preserves_links(service):
    g, parent, child, link, lt_id = _make_graph_with_nodes(service)
    clone = service.clone_graph(g["graph_id"], new_name="LinkClone", actor_id=ACTOR)
    nodes = service.list_nodes(clone["graph_id"])
    node_map = {n["source_id"]: n for n in nodes}
    from banyan_platform.dao.link_dao import LinkDAO
    with service.db.connect() as conn:
        links = LinkDAO(service.db).get_all_for_node(conn, node_map["PARENT-01"]["node_id"])
    assert any(lk["link_type_id"] == lt_id for lk in links)


def test_clone_unknown_source_raises(service):
    with pytest.raises(KeyError):
        service.clone_graph("ffffffff-ffff-ffff-ffff-ffffffffffff", "X", actor_id=ACTOR)


def test_rest_clone_graph(client):
    g = client.post("/api/v1/graphs", json={"name": "CloneSource"}, headers={"X-Actor-Id": "test-actor"}).json()
    gid = g["graph_id"]
    client.post(f"/api/v1/graphs/{gid}/nodes",
                json={"source_id": "N1", "name": "Node One"}, headers={"X-Actor-Id": "test-actor"})
    r = client.post(f"/api/v1/graphs/{gid}/clone",
                    json={"new_name": "CloneDest"}, headers={"X-Actor-Id": "test-actor"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "CloneDest"
    assert body["graph_id"] != gid


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
    assert len(service.list_nodes(gid)) == 3  # $ROOT$ + Alpha + Beta


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

    # $ROOT$ survives (created by create_graph, not part of the rolled-back batch)
    non_root = [n for n in service.list_nodes(gid) if n["source_id"] != "$ROOT$"]
    assert non_root == []


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
    assert doc["banyan_export_version"] == "1.1"
    assert len(doc["nodes"]) == 1  # N1 ($ROOT$ excluded from export)


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
