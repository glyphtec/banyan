"""Service-layer integration tests."""
import pytest

from tests.conftest import ACTOR


# ── Graph ─────────────────────────────────────────────────────────────────────

def test_create_and_get_graph(service):
    g = service.create_graph(name="Animals", actor_id=ACTOR)
    assert g["name"] == "Animals"
    fetched = service.get_graph(g["graph_id"])
    assert fetched["graph_id"] == g["graph_id"]


def test_get_graph_not_found_raises(service):
    with pytest.raises(KeyError):
        service.get_graph("00000000-0000-0000-0000-000000000000")


def test_list_graphs(service):
    service.create_graph("G1", actor_id=ACTOR)
    service.create_graph("G2", actor_id=ACTOR)
    assert len(service.list_graphs()) >= 2


def test_delete_graph_requires_empty(service):
    # graph is pre-populated with $ROOT$ by create_graph; delete should be blocked
    g = service.create_graph("ToDelete", actor_id=ACTOR)
    with pytest.raises(ValueError, match="node"):
        service.delete_graph(g["graph_id"], actor_id=ACTOR)


# ── Node + Ledger ─────────────────────────────────────────────────────────────

def test_add_node_writes_ledger_entry(service):
    g = service.create_graph("Taxonomy", actor_id=ACTOR)
    node = service.add_node(g["graph_id"], "T-001", "Term One", actor_id=ACTOR)
    history = service.get_graph_history(g["graph_id"])
    # history[0] is the auto-root ADD_NODE; history[1] is T-001
    entry = next(e for e in history if e["entity_id"] == node["node_id"])
    assert entry["primitive_verb"] == "ADD_NODE"
    assert entry["entity_id"] == node["node_id"]


def test_update_node_writes_delta_to_ledger(service):
    g = service.create_graph("Taxonomy", actor_id=ACTOR)
    node = service.add_node(g["graph_id"], "T-001", "Original", actor_id=ACTOR)
    service.update_node(node["node_id"], actor_id=ACTOR, name="Revised")
    history = service.get_graph_history(g["graph_id"])
    update_entry = next(e for e in history if e["primitive_verb"] == "UPDATE_NODE")
    assert update_entry["payload"]["name"] == "Revised"
    assert update_entry["reversal_payload"]["name"] == "Original"


def test_delete_node_blocked_by_outbound_link(service):
    g = service.create_graph("G", actor_id=ACTOR)
    gid = g["graph_id"]
    parent = service.add_node(gid, "P", "Parent", actor_id=ACTOR)
    child = service.add_node(gid, "C", "Child", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    service.create_link(
        link_type_id=lt["link_type_id"],
        from_graph_id=gid, to_graph_id=gid,
        from_node_id=parent["node_id"], to_node_id=child["node_id"],
        actor_id=ACTOR,
    )
    with pytest.raises(ValueError, match="outbound"):
        service.delete_node(parent["node_id"], actor_id=ACTOR)


def test_delete_node_force_removes_links_and_node(service):
    g = service.create_graph("G", actor_id=ACTOR)
    gid = g["graph_id"]
    parent = service.add_node(gid, "P", "Parent", actor_id=ACTOR)
    child = service.add_node(gid, "C", "Child", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    service.create_link(
        link_type_id=lt["link_type_id"],
        from_graph_id=gid, to_graph_id=gid,
        from_node_id=parent["node_id"], to_node_id=child["node_id"],
        actor_id=ACTOR,
    )
    result = service.delete_node(parent["node_id"], actor_id=ACTOR, force=True)
    assert result["destroyed_link_count"] == 1
    with pytest.raises(KeyError):
        service.get_node(parent["node_id"])


# ── Link + Cross-graph constraint ─────────────────────────────────────────────

def test_create_hierarchical_link_same_graph(service):
    g = service.create_graph("G", actor_id=ACTOR)
    gid = g["graph_id"]
    p = service.add_node(gid, "P", "Parent", actor_id=ACTOR)
    c = service.add_node(gid, "C", "Child", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    link = service.create_link(
        lt["link_type_id"], gid, gid,
        p["node_id"], c["node_id"], actor_id=ACTOR,
    )
    assert link["link_id"] is not None


def test_hierarchical_link_cross_graph_raises(service):
    g1 = service.create_graph("G1", actor_id=ACTOR)
    g2 = service.create_graph("G2", actor_id=ACTOR)
    n1 = service.add_node(g1["graph_id"], "N1", "Node 1", actor_id=ACTOR)
    n2 = service.add_node(g2["graph_id"], "N2", "Node 2", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    with pytest.raises(ValueError, match="HIERARCHICAL"):
        service.create_link(
            lt["link_type_id"],
            g1["graph_id"], g2["graph_id"],
            n1["node_id"], n2["node_id"],
            actor_id=ACTOR,
        )


def test_related_link_cross_graph_allowed(service):
    g1 = service.create_graph("G1", actor_id=ACTOR)
    g2 = service.create_graph("G2", actor_id=ACTOR)
    n1 = service.add_node(g1["graph_id"], "N1", "Node 1", actor_id=ACTOR)
    n2 = service.add_node(g2["graph_id"], "N2", "Node 2", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "RELATED")
    link = service.create_link(
        lt["link_type_id"],
        g1["graph_id"], g2["graph_id"],
        n1["node_id"], n2["node_id"],
        actor_id=ACTOR,
    )
    assert link["link_id"] is not None


def test_destroy_link_writes_ledger_entry(service):
    g = service.create_graph("G", actor_id=ACTOR)
    gid = g["graph_id"]
    p = service.add_node(gid, "P", "Parent", actor_id=ACTOR)
    c = service.add_node(gid, "C", "Child", actor_id=ACTOR)
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    link = service.create_link(lt["link_type_id"], gid, gid,
                               p["node_id"], c["node_id"], actor_id=ACTOR)
    service.destroy_link(link["link_id"], actor_id=ACTOR)
    history = service.get_graph_history(gid)
    verbs = [e["primitive_verb"] for e in history]
    assert "DESTROY_LINK" in verbs


# ── Snapshot ──────────────────────────────────────────────────────────────────

def test_snapshot_requires_ledger_history(service):
    # create_graph always writes a $ROOT$ ADD_NODE ledger entry,
    # so a freshly-created graph already has history and can be snapshotted.
    g = service.create_graph("HasHistory", actor_id=ACTOR)
    snap = service.create_snapshot(g["graph_id"], "v0", actor_id=ACTOR)
    assert snap["version_label"] == "v0"


def test_snapshot_created_after_node_mutation(service):
    g = service.create_graph("G", actor_id=ACTOR)
    service.add_node(g["graph_id"], "N1", "Node", actor_id=ACTOR)
    snap = service.create_snapshot(g["graph_id"], "v1.0", actor_id=ACTOR)
    assert snap["version_label"] == "v1.0"
    snaps = service.list_snapshots(g["graph_id"])
    assert len(snaps) == 1


# ---------------------------------------------------------------------------
# Undo tests
# ---------------------------------------------------------------------------

def test_undo_add_node(service):
    g = service.create_graph("G", actor_id=ACTOR)
    n = service.add_node(g["graph_id"], "N1", "Node", actor_id=ACTOR)
    history = service.get_graph_history(g["graph_id"])
    add_entry = next(e for e in history if e["primitive_verb"] == "ADD_NODE" and e["entity_id"] == n["node_id"])

    undo_entry = service.undo_ledger_entry(add_entry["ledger_id"], actor_id=ACTOR)

    assert undo_entry["primitive_verb"] == "DELETE_NODE"
    assert undo_entry["reverses_ledger_id"] == add_entry["ledger_id"]
    assert not any(nd["node_id"] == n["node_id"] for nd in service.list_nodes(g["graph_id"]))


def test_undo_update_node(service):
    g = service.create_graph("G", actor_id=ACTOR)
    n = service.add_node(g["graph_id"], "N1", "Original", actor_id=ACTOR)
    service.update_node(n["node_id"], actor_id=ACTOR, name="Modified")
    history = service.get_graph_history(g["graph_id"])
    upd_entry = next(e for e in history if e["primitive_verb"] == "UPDATE_NODE")

    undo_entry = service.undo_ledger_entry(upd_entry["ledger_id"], actor_id=ACTOR)

    assert undo_entry["primitive_verb"] == "UPDATE_NODE"
    assert undo_entry["reverses_ledger_id"] == upd_entry["ledger_id"]
    assert service.get_node(n["node_id"])["name"] == "Original"


def test_undo_delete_node(service):
    g = service.create_graph("G", actor_id=ACTOR)
    n = service.add_node(g["graph_id"], "N1", "Node", actor_id=ACTOR)
    node_id = n["node_id"]
    service.delete_node(node_id, actor_id=ACTOR)
    history = service.get_graph_history(g["graph_id"])
    del_entry = next(e for e in history if e["primitive_verb"] == "DELETE_NODE")

    undo_entry = service.undo_ledger_entry(del_entry["ledger_id"], actor_id=ACTOR)

    assert undo_entry["primitive_verb"] == "ADD_NODE"
    assert undo_entry["reverses_ledger_id"] == del_entry["ledger_id"]
    restored = service.get_node(node_id)
    assert restored["node_id"] == node_id
    assert restored["name"] == "Node"


def test_undo_create_link(service):
    g = service.create_graph("G", actor_id=ACTOR)
    root = service.add_node(g["graph_id"], "ROOT", "Root", actor_id=ACTOR)
    child = service.add_node(g["graph_id"], "CHILD", "Child", actor_id=ACTOR)
    lt_id = next(lt["link_type_id"] for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    lk = service.create_link(
        link_type_id=lt_id,
        from_graph_id=g["graph_id"], to_graph_id=g["graph_id"],
        from_node_id=root["node_id"], to_node_id=child["node_id"],
        actor_id=ACTOR,
    )
    history = service.get_graph_history(g["graph_id"])
    cl_entry = next(e for e in history if e["primitive_verb"] == "CREATE_LINK")

    undo_entry = service.undo_ledger_entry(cl_entry["ledger_id"], actor_id=ACTOR)

    assert undo_entry["primitive_verb"] == "DESTROY_LINK"
    assert undo_entry["reverses_ledger_id"] == cl_entry["ledger_id"]
    import pytest
    with pytest.raises(KeyError):
        service.get_link(lk["link_id"])


def test_undo_missing_ledger_entry(service):
    import pytest
    with pytest.raises(KeyError):
        service.undo_ledger_entry(999999, actor_id=ACTOR)


def test_undo_stores_reverses_ledger_id_in_history(service):
    g = service.create_graph("G", actor_id=ACTOR)
    n = service.add_node(g["graph_id"], "N1", "Node", actor_id=ACTOR)
    history = service.get_graph_history(g["graph_id"])
    add_entry = next(e for e in history if e["primitive_verb"] == "ADD_NODE" and e["entity_id"] == n["node_id"])
    service.undo_ledger_entry(add_entry["ledger_id"], actor_id=ACTOR)

    full_history = service.get_graph_history(g["graph_id"])
    undo_entry = next(e for e in full_history if e["primitive_verb"] == "DELETE_NODE")
    assert undo_entry["reverses_ledger_id"] == add_entry["ledger_id"]

