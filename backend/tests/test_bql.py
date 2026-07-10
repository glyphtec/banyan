"""
BQL (Banyan Query Language) tests.

Covers:
  - QueryDAO.resolve_seed   — all predicate forms
  - QueryDAO.execute_one_hop — direction, filtering, edge cases
  - BanyanService.execute_bql — full pipeline (graph resolution, seed,
    steps, multi-step, result options, cross-graph, deduplication)
  - REST POST /query endpoint — happy path and error mapping

Fixture graph "Taxonomy":
  $ROOT$
  ├── HIERARCHICAL → Food          [source=food,  metadata.level=1]
  │   ├── HIERARCHICAL → Food Access   [source=food-access]
  │   └── HIERARCHICAL → Food Safety   [source=food-safety]
  └── HIERARCHICAL → Housing       [source=housing, metadata.level=1]
      ├── HIERARCHICAL → Housing Instability  [source=housing-instability]
      └── HIERARCHICAL → Homelessness         [source=homelessness]

Fixture graph "Clinical":
  $ROOT$ → HIERARCHICAL → Clinical Food  [source=clin-food]
  Cross-graph: SAME_AS  Taxonomy.Food → Clinical.Clinical Food
"""
import pytest

from tests.conftest import ACTOR

# Well-known seeded UUIDs (see ddl.py BANYAN_SEED_DML)
HIERARCHICAL_LT_ID = "ba0ba000-0000-0000-0000-000000000001"
RELATED_LT_ID      = "ba0ba000-0000-0000-0000-000000000002"
SAME_AS_LT_ID      = "ba0ba000-0000-0000-0000-000000000011"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def bql_data(service):
    """Build the test graph pair and return a data bundle used by all tests."""
    # ── Taxonomy graph ─────────────────────────────────────────────────────
    g1 = service.create_graph("Taxonomy", actor_id=ACTOR)
    gid = g1["graph_id"]
    root_id = g1["root_node_id"]

    food    = service.add_node(gid, "food",     "Food",     actor_id=ACTOR, metadata={"level": 1})
    housing = service.add_node(gid, "housing",  "Housing",  actor_id=ACTOR, metadata={"level": 1})
    fa      = service.add_node(gid, "food-access",          "Food Access",          actor_id=ACTOR)
    fs      = service.add_node(gid, "food-safety",          "Food Safety",          actor_id=ACTOR)
    hi      = service.add_node(gid, "housing-instability",  "Housing Instability",  actor_id=ACTOR)
    hm      = service.add_node(gid, "homelessness",         "Homelessness",         actor_id=ACTOR)

    def H(from_id, to_id, g=gid):
        return service.create_link(
            link_type_id=HIERARCHICAL_LT_ID,
            from_graph_id=g, to_graph_id=g,
            from_node_id=from_id, to_node_id=to_id,
            actor_id=ACTOR,
        )

    H(root_id, food["node_id"])
    H(root_id, housing["node_id"])
    H(food["node_id"], fa["node_id"])
    H(food["node_id"], fs["node_id"])
    H(housing["node_id"], hi["node_id"])
    H(housing["node_id"], hm["node_id"])

    # ── Clinical graph ─────────────────────────────────────────────────────
    g2 = service.create_graph("Clinical", actor_id=ACTOR)
    gid2 = g2["graph_id"]
    root2_id = g2["root_node_id"]
    clin_food = service.add_node(gid2, "clin-food", "Clinical Food", actor_id=ACTOR)
    H(root2_id, clin_food["node_id"], g=gid2)

    # Cross-graph SAME_AS: Taxonomy.Food → Clinical.Clinical Food
    service.create_link(
        link_type_id=SAME_AS_LT_ID,
        from_graph_id=gid, to_graph_id=gid2,
        from_node_id=food["node_id"], to_node_id=clin_food["node_id"],
        actor_id=ACTOR,
    )

    return {
        "graph_id":   gid,
        "graph_name": "Taxonomy",
        "graph2_id":  gid2,
        "graph2_name": "Clinical",
        "root_id":    root_id,
        "nodes": {
            "food":                 food,
            "housing":              housing,
            "food-access":          fa,
            "food-safety":          fs,
            "housing-instability":  hi,
            "homelessness":         hm,
            "clin-food":            clin_food,
        },
    }


# ===========================================================================
# QueryDAO — resolve_seed
# ===========================================================================

class TestResolveSeed:

    def test_exact_name(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"name": "Food"}
            )
        assert len(results) == 1
        assert results[0]["source_id"] == "food"

    def test_exact_name_case_insensitive(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"name": "FOOD"}
            )
        assert len(results) == 1
        assert results[0]["source_id"] == "food"

    def test_name_contains(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"name_contains": "food"}
            )
        source_ids = {r["source_id"] for r in results}
        # Food, Food Access, Food Safety — but NOT Housing or cross-graph nodes
        assert source_ids == {"food", "food-access", "food-safety"}

    def test_name_starts(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"name_starts": "Housing"}
            )
        source_ids = {r["source_id"] for r in results}
        assert source_ids == {"housing", "housing-instability"}

    def test_source_id_exact(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"source_id": "food-access"}
            )
        assert len(results) == 1
        assert results[0]["name"] == "Food Access"

    def test_source_id_prefix(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"source_id_prefix": "food"}
            )
        source_ids = {r["source_id"] for r in results}
        assert source_ids == {"food", "food-access", "food-safety"}

    def test_node_id_exact(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"node_id": food_id}
            )
        assert len(results) == 1
        assert results[0]["source_id"] == "food"

    def test_compound_or(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"],
                {"or": [{"name": "Food"}, {"name": "Housing"}]},
            )
        source_ids = {r["source_id"] for r in results}
        assert source_ids == {"food", "housing"}

    def test_compound_and(self, service, bql_data):
        # Only nodes whose name contains "food" AND have metadata.level = "1"
        # → only Food (Food Access / Food Safety have no level metadata)
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"],
                {"and": [{"name_contains": "food"}, {"metadata.level": "1"}]},
            )
        assert len(results) == 1
        assert results[0]["source_id"] == "food"

    def test_metadata_path_match(self, service, bql_data):
        # metadata.level = "1" → Food and Housing
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"metadata.level": "1"}
            )
        source_ids = {r["source_id"] for r in results}
        assert source_ids == {"food", "housing"}

    def test_in_operator(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"],
                {"name": {"in": ["Food", "Homelessness"]}},
            )
        source_ids = {r["source_id"] for r in results}
        assert source_ids == {"food", "homelessness"}

    def test_no_match_returns_empty(self, service, bql_data):
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"name": "Nonexistent XYZ"}
            )
        assert results == []

    def test_scoped_to_graph(self, service, bql_data):
        # "Clinical Food" exists in graph2 but not in graph1
        with service.db.connect() as conn:
            results = service.query_dao.resolve_seed(
                conn, bql_data["graph_id"], {"name_contains": "Clinical"}
            )
        assert results == []

    def test_invalid_metadata_path_raises(self, service, bql_data):
        with service.db.connect() as conn:
            with pytest.raises(ValueError, match="Invalid metadata path"):
                service.query_dao.resolve_seed(
                    conn, bql_data["graph_id"], {"metadata.bad path!": "x"}
                )


# ===========================================================================
# QueryDAO — execute_one_hop
# ===========================================================================

class TestExecuteOneHop:

    def test_from_direction_returns_children(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="FROM",
                frontier_ids=[food_id],
                link_type_ids=[HIERARCHICAL_LT_ID],  # HIERARCHICAL only; excludes SAME_AS cross-graph
                allowed_graph_ids=None,
            )
        target_source_ids = {node["source_id"] for _, _, node in hops}
        assert target_source_ids == {"food-access", "food-safety"}

    def test_to_direction_returns_parent(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="TO",
                frontier_ids=[food_id],
                link_type_ids=None,
                allowed_graph_ids=None,
            )
        target_source_ids = {node["source_id"] for _, _, node in hops}
        assert "$ROOT$" in target_source_ids

    def test_with_direction_is_union_of_from_and_to(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="WITH",
                frontier_ids=[food_id],
                link_type_ids=None,
                allowed_graph_ids=None,
            )
        target_source_ids = {node["source_id"] for _, _, node in hops}
        # Children (FROM) + parent $ROOT$ (TO)
        assert {"food-access", "food-safety"}.issubset(target_source_ids)
        assert "$ROOT$" in target_source_ids

    def test_link_type_filter_restricts_results(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        # Filter to HIERARCHICAL only; the SAME_AS cross-graph link is excluded
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="FROM",
                frontier_ids=[food_id],
                link_type_ids=[HIERARCHICAL_LT_ID],
                allowed_graph_ids=None,
            )
        assert all(li["link_type_name"] == "HIERARCHICAL" for li, _, _ in hops)
        target_source_ids = {node["source_id"] for _, _, node in hops}
        # Clinical Food excluded; only HIERARCHICAL children found
        assert "clin-food" not in target_source_ids

    def test_parent_node_id_is_correct(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="FROM",
                frontier_ids=[food_id],
                link_type_ids=[HIERARCHICAL_LT_ID],
                allowed_graph_ids=None,
            )
        for _, parent_id, _ in hops:
            assert parent_id == food_id

    def test_empty_frontier_returns_empty(self, service, bql_data):
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="FROM",
                frontier_ids=[],
                link_type_ids=None,
                allowed_graph_ids=None,
            )
        assert hops == []

    def test_empty_allowed_graph_ids_returns_empty(self, service, bql_data):
        food_id = bql_data["nodes"]["food"]["node_id"]
        with service.db.connect() as conn:
            hops = service.query_dao.execute_one_hop(
                conn,
                direction="FROM",
                frontier_ids=[food_id],
                link_type_ids=None,
                allowed_graph_ids=[],   # No graphs allowed
            )
        assert hops == []


# ===========================================================================
# Service — graph resolution
# ===========================================================================

class TestBQLGraphResolution:

    def test_graph_by_name(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
        })
        assert result["success"] is True
        assert result["seed_count"] == 1

    def test_graph_by_id(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"id": bql_data["graph_id"]},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
        })
        assert result["success"] is True
        assert result["seed_count"] == 1

    def test_unknown_graph_raises_key_error(self, service, bql_data):
        with pytest.raises(KeyError):
            service.execute_bql({
                "graph": {"name": "Does Not Exist"},
            })

    def test_missing_graph_key_raises_value_error(self, service, bql_data):
        with pytest.raises(ValueError, match="graph"):
            service.execute_bql({"graph": {}})


# ===========================================================================
# Service — seed resolution
# ===========================================================================

class TestBQLSeedResolution:

    def test_no_starting_uses_root_node(self, service, bql_data):
        # With no starting, seed = $ROOT$ (seed_count == 1)
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"include_seed": False},
        })
        assert result["seed_count"] == 1

    def test_starting_predicate_no_match_gives_empty_results(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Nonexistent XYZ"},
        })
        assert result["seed_count"] == 0
        assert result["total_count"] == 0

    def test_starting_predicate_multi_match(self, service, bql_data):
        # "metadata.level": "1" matches Food AND Housing
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"metadata.level": "1"},
            "result": {"include_seed": True},
            "steps": [],
        })
        assert result["seed_count"] == 2


# ===========================================================================
# Service — step traversal
# ===========================================================================

class TestBQLStepTraversal:

    def test_no_starting_no_steps_exports_full_graph(self, service, bql_data):
        # Default: root seed + FROM all types depth=50 → all 7 taxonomy nodes
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
        })
        assert result["seed_count"] == 1
        # 1 root + 2 top-level + 4 leaf nodes
        assert result["total_count"] == 7

    def test_starting_only_gives_full_subtree(self, service, bql_data):
        # Starting at Food, no steps → Food subtree (Food + 2 children)
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
        })
        assert result["seed_count"] == 1
        node_names = _names(result)
        assert node_names == {"Food", "Food Access", "Food Safety"}

    def test_depth_one_returns_only_immediate_children(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"source_id": "$ROOT$"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        assert node_names == {"Food", "Housing"}

    def test_to_direction_returns_ancestor_chain(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food Access"},
            "steps": [{"direction": "TO", "link_types": ["HIERARCHICAL"], "depth": 99}],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        assert "Food" in node_names
        assert "$ROOT$" in node_names
        # Should not include siblings
        assert "Food Safety" not in node_names

    def test_with_direction_traverses_both_ways(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "WITH", "link_types": ["HIERARCHICAL"], "depth": 1}],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        # Children via FROM
        assert "Food Access" in node_names
        assert "Food Safety" in node_names
        # Parent via TO
        assert "$ROOT$" in node_names

    def test_step_depth_metadata(self, service, bql_data):
        # Verify _depth and _net_depth are populated correctly
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1}],
            "result": {"include_seed": False},
        })
        for item in result["results"]:
            assert item["_depth"] == 1
            assert item["_net_depth"] == 1
            assert item["_step"] == 1


# ===========================================================================
# Service — multi-step and collect behaviour
# ===========================================================================

class TestBQLMultiStep:

    def test_zig_zag_sibling_pattern(self, service, bql_data):
        """
        Step 1: walk TO (find parent), collect=False.
        Step 2: walk FROM (find siblings).
        Result: seed + siblings only; parent is never collected.
        """
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food Access"},
            "steps": [
                {"direction": "TO",   "link_types": ["HIERARCHICAL"], "depth": 1, "collect": False},
                {"direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1},
            ],
            "result": {"include_seed": True},
        })
        node_names = _names(result)
        assert "Food Access" in node_names   # seed (step 0)
        assert "Food Safety" in node_names   # sibling (step 2)
        assert "Food" not in node_names      # parent — step 1 collect=false

    def test_collect_false_step_not_in_results_but_feeds_next_step(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"source_id": "$ROOT$"},
            "steps": [
                # Step 1: depth=1 down, collect=False (finds Food and Housing, not collected)
                {"direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1, "collect": False},
                # Step 2: depth=1 down from Food+Housing (finds leaf nodes)
                {"direction": "FROM", "link_types": ["HIERARCHICAL"], "depth": 1, "collect": True},
            ],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        # Mid-level nodes were not collected
        assert "Food" not in node_names
        assert "Housing" not in node_names
        # Leaf nodes were collected via step 2
        assert "Food Access" in node_names
        assert "Homelessness" in node_names

    def test_deduplication_prevents_revisiting_nodes(self, service, bql_data):
        # Two overlapping FROM steps; each node should appear at most once
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "$ROOT$"},
            "steps": [
                {"direction": "FROM", "depth": 10},
                {"direction": "FROM", "depth": 10},
            ],
        })
        all_ids = [item["node"]["node_id"] for item in result["results"]]
        # No duplicates (except the seed itself which is step-0 only)
        assert len(all_ids) == len(set(all_ids))


# ===========================================================================
# Service — link_type filters
# ===========================================================================

class TestBQLLinkTypeFilters:

    def test_exact_link_type_suffix(self, service, bql_data):
        """HIERARCHICAL! matches only HIERARCHICAL, not its subtypes (none seeded here,
        but the flag should be accepted and the query should function correctly)."""
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "link_types": ["HIERARCHICAL!"], "depth": 1}],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        assert node_names == {"Food Access", "Food Safety"}

    def test_family_expansion_includes_subtypes(self, service, bql_data):
        """RELATED (no !) expands to its whole family, including SAME_AS."""
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{
                "direction": "FROM",
                "link_types": ["RELATED"],
                "graphs": ["*"],    # Allow cross-graph so SAME_AS link can be followed
                "depth": 1,
            }],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        # SAME_AS is a child of RELATED; Clinical Food should be reachable
        assert "Clinical Food" in node_names

    def test_hierarchical_only_excludes_cross_graph_related(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{
                "direction": "FROM",
                "link_types": ["HIERARCHICAL"],
                "graphs": ["*"],
                "depth": 1,
            }],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        assert "Clinical Food" not in node_names
        assert node_names == {"Food Access", "Food Safety"}


# ===========================================================================
# Service — cross-graph traversal
# ===========================================================================

class TestBQLCrossGraph:

    def test_cross_graph_with_star_graphs(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{
                "direction": "FROM",
                "link_types": ["SAME_AS!"],
                "graphs": ["*"],
                "depth": 1,
            }],
            "result": {"include_seed": False},
        })
        assert result["seed_count"] == 1
        node_names = _names(result)
        assert "Clinical Food" in node_names

    def test_cross_graph_with_named_target_graph(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{
                "direction": "FROM",
                "link_types": ["SAME_AS!"],
                "graphs": ["Clinical"],
                "depth": 1,
            }],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        assert "Clinical Food" in node_names

    def test_no_cross_graph_by_default(self, service, bql_data):
        # Without graphs: ["*"], the default restricts to origin graph
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "link_types": ["RELATED"], "depth": 1}],
            "result": {"include_seed": False},
        })
        node_names = _names(result)
        assert "Clinical Food" not in node_names


# ===========================================================================
# Service — result options
# ===========================================================================

class TestBQLResultOptions:

    def test_format_link_node_includes_link_wrapper(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"format": "LINK_NODE", "include_seed": False},
        })
        for item in result["results"]:
            assert "link" in item
            assert "node" in item
            assert item["link"] is not None

    def test_format_node_returns_flat_node(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"format": "NODE", "include_seed": False},
        })
        for item in result["results"]:
            assert "node_id" in item       # node fields at top level
            assert "link" not in item      # no link wrapper
            assert "_step" in item         # traversal metadata still present

    def test_include_seed_true_adds_seed_as_step_zero(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"include_seed": True},
        })
        step_zero = [item for item in result["results"] if item["_step"] == 0]
        assert len(step_zero) == 1
        assert step_zero[0]["node"]["name"] == "Food"
        assert step_zero[0]["link"] is None
        assert step_zero[0]["_direction"] is None

    def test_include_seed_false_omits_seed_from_proactive_insertion(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"include_seed": False},
        })
        step_zero = [item for item in result["results"] if item["_step"] == 0]
        assert step_zero == []

    def test_limit_truncates_results(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "result": {"limit": 3},
        })
        assert len(result["results"]) <= 3

    def test_verbose_adds_step_diagnostics(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
            "result": {"verbose": True},
        })
        assert result["steps"] is not None
        assert len(result["steps"]) == 1
        diag = result["steps"][0]
        assert diag["step"] == 1
        assert "input_count" in diag
        assert "output_count" in diag
        assert "collected" in diag

    def test_verbose_false_steps_field_is_none(self, service, bql_data):
        result = service.execute_bql({
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
        })
        assert result["steps"] is None


# ===========================================================================
# REST endpoint — POST /query
# ===========================================================================

class TestBQLRestEndpoint:

    def test_post_query_returns_envelope(self, client, bql_data):
        resp = client.post("/api/v1/query", json={
            "graph": {"name": "Taxonomy"},
            "starting": {"name": "Food"},
            "steps": [{"direction": "FROM", "depth": 1}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "seed_count" in body
        assert "total_count" in body
        assert "results" in body

    def test_post_query_unknown_graph_returns_404(self, client, bql_data):
        resp = client.post("/api/v1/query", json={
            "graph": {"name": "Does Not Exist"},
        })
        assert resp.status_code == 404

    def test_post_query_invalid_predicate_returns_400(self, client, bql_data):
        resp = client.post("/api/v1/query", json={
            "graph": {"name": "Taxonomy"},
            "starting": {"metadata.bad path!": "x"},
        })
        assert resp.status_code == 400


# ===========================================================================
# Helpers
# ===========================================================================

def _names(result: dict) -> set[str]:
    """Extract the set of node names from a BQL result envelope."""
    names = set()
    for item in result["results"]:
        if "node" in item:
            names.add(item["node"]["name"])
        else:
            names.add(item.get("name", ""))
    return names
