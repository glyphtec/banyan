"""Traversal query tests (subtree, ancestors, impact summary)."""
from tests.conftest import ACTOR


def _setup_tree(service):
    """
    Build a simple 3-level taxonomy for traversal tests:

        root
          ├─ cat_a
          │    └─ cat_a1
          └─ cat_b
    """
    g = service.create_graph("Tree", actor_id=ACTOR)
    gid = g["graph_id"]
    lt = next(lt for lt in service.get_link_types() if lt["name"] == "HIERARCHICAL")
    lt_id = lt["link_type_id"]

    root = service.add_node(gid, "root", "Root", actor_id=ACTOR)
    cat_a = service.add_node(gid, "cat_a", "Category A", actor_id=ACTOR)
    cat_b = service.add_node(gid, "cat_b", "Category B", actor_id=ACTOR)
    cat_a1 = service.add_node(gid, "cat_a1", "Category A1", actor_id=ACTOR)

    service.create_link(lt_id, gid, gid, root["node_id"], cat_a["node_id"], actor_id=ACTOR)
    service.create_link(lt_id, gid, gid, root["node_id"], cat_b["node_id"], actor_id=ACTOR)
    service.create_link(lt_id, gid, gid, cat_a["node_id"], cat_a1["node_id"], actor_id=ACTOR)

    return gid, lt_id, root, cat_a, cat_b, cat_a1


def test_get_subtree_returns_all_descendants(service):
    gid, lt_id, root, cat_a, cat_b, cat_a1 = _setup_tree(service)
    subtree = service.get_subtree(gid, root["node_id"], link_type_id=lt_id)
    ids = {n["node_id"] for n in subtree}
    assert root["node_id"] in ids
    assert cat_a["node_id"] in ids
    assert cat_b["node_id"] in ids
    assert cat_a1["node_id"] in ids
    assert len(subtree) == 4


def test_get_subtree_respects_root(service):
    gid, lt_id, root, cat_a, cat_b, cat_a1 = _setup_tree(service)
    subtree = service.get_subtree(gid, cat_a["node_id"], link_type_id=lt_id)
    ids = {n["node_id"] for n in subtree}
    assert cat_a["node_id"] in ids
    assert cat_a1["node_id"] in ids
    assert root["node_id"] not in ids
    assert cat_b["node_id"] not in ids


def test_get_ancestors_returns_path_to_root(service):
    gid, lt_id, root, cat_a, cat_b, cat_a1 = _setup_tree(service)
    ancestors = service.get_ancestors(gid, cat_a1["node_id"], link_type_id=lt_id)
    ids = {n["node_id"] for n in ancestors}
    assert cat_a["node_id"] in ids
    assert root["node_id"] in ids
    assert cat_a1["node_id"] not in ids  # self not included


def test_get_impact_summary_counts_descendants(service):
    gid, lt_id, root, cat_a, cat_b, cat_a1 = _setup_tree(service)
    impact = service.get_impact_summary(gid, root["node_id"])
    assert impact["node_id"] == root["node_id"]
    assert impact["descendant_count"] == 3  # cat_a, cat_b, cat_a1
    assert impact["cross_graph_link_count"] == 0


def test_get_impact_summary_detects_cross_graph_links(service):
    gid, lt_id, root, cat_a, cat_b, cat_a1 = _setup_tree(service)
    # Create a second graph with a RELATED link pointing at cat_a1
    g2 = service.create_graph("Crosswalk", actor_id=ACTOR)
    n_ext = service.add_node(g2["graph_id"], "EXT-1", "External", actor_id=ACTOR)
    rel_lt = next(lt for lt in service.get_link_types() if lt["name"] == "RELATED")
    service.create_link(
        rel_lt["link_type_id"],
        g2["graph_id"], gid,
        n_ext["node_id"], cat_a1["node_id"],
        actor_id=ACTOR,
    )
    impact = service.get_impact_summary(gid, root["node_id"])
    assert impact["cross_graph_link_count"] >= 1

