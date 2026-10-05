import pytest

from curio.stages.visual_audit import (
    QueryAuditAccumulator,
    SearchQueryAudit,
    candidate_audit_rows,
    search_query_audit_rows,
)
from curio.stages.visual_contracts import SearchPlan, SearchQuery


def test_candidate_audit_projects_selected_reused_and_rejected_reasons():
    evaluated = [
        {"query": "Ottoman map", "score": 82,
         "asset": {"provider": "wikimedia", "asset_id": "map-1",
                   "title": "Ottoman map", "source_url": "https://example/map"},
         "score_detail": {"topic_relevance": 100, "scene_relevance": 76,
                          "topic_evidence": {"topic": ["Ottoman"]}}},
        {"query": "Janissary portrait", "score": 20, "asset": {
            "provider": "met", "asset_id": "portrait-1", "title": "Portrait"},
         "score_detail": {"semantic_rejection": "scene evidence too weak"}},
    ]
    picked = [{"asset": evaluated[0]["asset"],
               "reuse_reason": "fresh_search_and_synthetic_exhausted"}]

    rows = candidate_audit_rows(
        evaluated, [{"title": "Portrait", "reason": "technical gate"}],
        picked, {"Ottoman map": 2}, min_score=50)

    assert rows[0]["decision"] == "selected"
    assert rows[0]["reason"] == "reused only after fresh searches and local visual exhausted"
    assert rows[0]["query_level"] == 2
    assert rows[1]["decision"] == "rejected"
    assert rows[1]["reason"] == "scene evidence too weak"
    assert [row["title"] for row in rows].count("Portrait") == 1


def test_candidate_audit_marks_below_threshold_without_semantic_reason():
    rows = candidate_audit_rows(
        [{"query": "Ottoman map", "score": 12, "asset": {"title": "Map"}}],
        [], [], {}, min_score=50)

    assert rows == [{
        "title": "Map", "provider": "", "query": "Ottoman map", "query_level": 3,
        "topic_relevance": None, "scene_relevance": None, "score": 12,
        "bonus": 0, "clip_score": None, "creator": "", "source_url": "",
        "date_created": "", "media_type": "image", "metadata_support": 0.0,
        "topic_evidence": {}, "scene_evidence": {}, "decision": "rejected",
        "reason": "score below threshold",
    }]


def test_query_audit_projects_provider_results_and_search_provenance():
    query = SearchQuery(
        "Battle of Mohács Ottoman Empire engraving",
        "representation_variant", representation="Battle of Mohács",
        representation_kind="event", alias="Ottoman Empire",
        variant="engraving", level=2)
    state = QueryAuditAccumulator()
    state.set_providers(["wikimedia", "met"])
    state.record_error("met", "timeout")
    state.record_result("wikimedia", 3)
    state.record_duplicate()
    state.record_rejection()
    state.record_eligible()

    rows = search_query_audit_rows(
        SearchPlan(4, (query,)), {query.query: state.snapshot()},
        [{"query": query.query}],
        {"Battle of Mohács": 2}, {"Battle of Mohács": "event"},
        ["Ottoman Empire"])

    assert rows == [{
        "query": query.query,
        "source": "representation_variant",
        "representation": "Battle of Mohács",
        "representation_kind": "event",
        "alias": "Ottoman Empire",
        "query_variant": "engraving",
        "level": 2,
        "generic": False,
        "providers": ["wikimedia", "met"],
        "provider_errors": {"met": "timeout"},
        "results": 3,
        "results_by_provider": {"wikimedia": 3},
        "duplicates": 1,
        "eligible_candidates": 1,
        "rejected_candidates_total": 1,
        "outcome": "rejected",
        "representations": ["Battle of Mohács"],
        "representation_kinds": {"Battle of Mohács": "event"},
        "aliases_used": ["Ottoman Empire"],
        "status": "consulted",
        "unexecuted_reason": "",
    }]


def test_query_audit_distinguishes_duplicate_only_and_budget_exhaustion():
    duplicate_query = SearchQuery("Battle of Mohács", "scene_representation")
    budget_query = SearchQuery("Mohács painting", "representation_variant")
    duplicate = QueryAuditAccumulator()
    duplicate.set_providers(["wikimedia"])
    duplicate.record_duplicate()
    duplicate.mark_duplicates_only()
    budget = QueryAuditAccumulator()
    budget.mark_unexecuted("scene_candidate_budget")

    rows = search_query_audit_rows(
        SearchPlan(1, (duplicate_query, budget_query)),
        {duplicate_query.query: duplicate.snapshot(),
         budget_query.query: budget.snapshot()},
        [], {}, {}, [])

    assert (rows[0]["outcome"], rows[0]["status"]) == (
        "duplicates_only", "abandoned_duplicates")
    assert rows[1]["status"] == "not_consulted_budget_exhausted"
    assert rows[1]["unexecuted_reason"] == "scene_candidate_budget"


def test_query_audit_reports_deferred_tier_as_not_consulted():
    query = SearchQuery("Ottoman Empire historical map", "topic_fallback",
                       generic=True)
    deferred = QueryAuditAccumulator(unexecuted_reason="tier_not_reached")

    row = search_query_audit_rows(
        SearchPlan(1, (query,)), {query.query: deferred.snapshot()}, [], {}, {}, [])[0]

    assert row["status"] == "not_consulted"
    assert row["unexecuted_reason"] == "tier_not_reached"


def test_query_audit_snapshot_is_immutable_and_preserves_provider_facts():
    accumulator = QueryAuditAccumulator()
    accumulator.set_providers(["wikimedia"])
    accumulator.record_result("wikimedia", 2)
    snapshot = accumulator.snapshot()

    with pytest.raises((AttributeError, TypeError)):
        snapshot.results = 99
    with pytest.raises((AttributeError, TypeError)):
        snapshot.providers += ("met",)
    accumulator.record_result("wikimedia", 1)

    assert snapshot.results == 2
    assert snapshot.results_by_provider == (("wikimedia", 2),)


def test_query_audit_requires_state_for_each_planned_query():
    plan = SearchPlan(1, (
        SearchQuery("French Revolution", "scene_representation"),))
    with pytest.raises(ValueError, match="must match SearchPlan"):
        search_query_audit_rows(plan, {}, [], {}, {}, [])
