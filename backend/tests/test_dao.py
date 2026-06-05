"""Unit tests for the individual DAOs.  Uses the shared in-memory db fixture."""
import uuid

from tests.conftest import ACTOR


def _new_graph(db, name="Test Graph"):
    with db.connect() as conn:
        from banyan_platform.dao.graph_dao import GraphDAO
        gid = GraphDAO(db).insert(conn, name=name, actor_id=ACTOR)
    return gid


def _hierarchical_lt_id(db):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT link_type_id FROM link_type WHERE name = 'HIERARCHICAL'"
        ).fetchone()
    return row[0]


def _generic_nt_id(db):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT node_type_id FROM node_type WHERE name = 'Generic'"
        ).fetchone()
    return row[0]


# ── GraphDAO ─────────────────────────────────────────────────────────────────

def test_graph_insert_and_get(db):
    from banyan_platform.dao.graph_dao import GraphDAO
    dao = GraphDAO(db)
    with db.connect() as conn:
        gid = dao.insert(conn, name="Taxonomy A", actor_id=ACTOR)
        row = dao.get(conn, gid)
    assert row["name"] == "Taxonomy A"
    assert row["graph_id"] == gid


def test_graph_set_root_node(db):
    from banyan_platform.dao.graph_dao import GraphDAO
    from banyan_platform.dao.node_dao import NodeDAO
    gid = _new_graph(db, "Rooted Graph")
    nt_id = _generic_nt_id(db)
    with db.connect() as conn:
        nid = NodeDAO(db).insert(
            conn, graph_id=gid, node_type_id=nt_id,
            source_id="root", name="Root Node", actor_id=ACTOR,
        )
        GraphDAO(db).set_root_node(conn, gid, nid)
        row = GraphDAO(db).get(conn, gid)
    assert row["root_node_id"] == nid


# ── NodeDAO ───────────────────────────────────────────────────────────────────

def test_node_insert_get_by_source(db):
    from banyan_platform.dao.node_dao import NodeDAO
    gid = _new_graph(db)
    nt_id = _generic_nt_id(db)
    with db.connect() as conn:
        nid = NodeDAO(db).insert(
            conn, graph_id=gid, node_type_id=nt_id,
            source_id="CAT-001", name="Category 1", actor_id=ACTOR,
        )
        by_src = NodeDAO(db).get_by_source(conn, gid, "CAT-001")
    assert by_src["node_id"] == nid
    assert by_src["name"] == "Category 1"


def test_node_update(db):
    from banyan_platform.dao.node_dao import NodeDAO
    gid = _new_graph(db)
    nt_id = _generic_nt_id(db)
    with db.connect() as conn:
        nid = NodeDAO(db).insert(
            conn, graph_id=gid, node_type_id=nt_id,
            source_id="N1", name="Old Name", actor_id=ACTOR,
        )
        NodeDAO(db).update(conn, nid, name="New Name", actor_id=ACTOR)
        row = NodeDAO(db).get(conn, nid)
    assert row["name"] == "New Name"


# ── LinkDAO ───────────────────────────────────────────────────────────────────

def test_link_insert_and_get_children(db):
    from banyan_platform.dao.node_dao import NodeDAO
    from banyan_platform.dao.link_dao import LinkDAO
    gid = _new_graph(db)
    nt_id = _generic_nt_id(db)
    lt_id = _hierarchical_lt_id(db)
    with db.connect() as conn:
        pid = NodeDAO(db).insert(conn, graph_id=gid, node_type_id=nt_id,
                                  source_id="P1", name="Parent", actor_id=ACTOR)
        cid = NodeDAO(db).insert(conn, graph_id=gid, node_type_id=nt_id,
                                  source_id="C1", name="Child", actor_id=ACTOR)
        LinkDAO(db).insert(conn, link_type_id=lt_id, from_graph_id=gid, to_graph_id=gid,
                           from_node_id=pid, to_node_id=cid, actor_id=ACTOR)
        children = LinkDAO(db).get_children(conn, gid, pid)
    assert len(children) == 1
    assert children[0]["to_node_id"] == cid


# ── LedgerDAO ─────────────────────────────────────────────────────────────────

def test_ledger_append_and_retrieve(db):
    from banyan_platform.dao.ledger_dao import LedgerDAO
    gid = _new_graph(db)
    node_id = str(uuid.uuid4())
    txn_id = str(uuid.uuid4())
    with db.connect() as conn:
        lid = LedgerDAO(db).append(
            conn,
            transaction_id=txn_id,
            actor_id=ACTOR,
            primitive_verb="ADD_NODE",
            source_graph_id=gid,
            entity_id=node_id,
            payload={"node_id": node_id},
            reversal_payload={"node_id": node_id},
        )
        entries = LedgerDAO(db).get_by_transaction(conn, txn_id)
    assert lid >= 1
    assert len(entries) == 1
    assert entries[0]["primitive_verb"] == "ADD_NODE"


# ── LookupDAO ─────────────────────────────────────────────────────────────────

def test_lookup_link_type_root_family(db):
    from banyan_platform.dao.lookup_dao import LookupDAO
    with db.connect() as conn:
        lt_id = conn.execute(
            "SELECT link_type_id FROM link_type WHERE name = 'HIERARCHICAL'"
        ).fetchone()[0]
        family = LookupDAO(db).get_link_type_root_family(conn, lt_id)
    assert family == "HIERARCHICAL"

