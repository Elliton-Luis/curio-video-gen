import pytest

from curio.media.asset_snapshot import MediaAssetSnapshot
from curio.media.selection_result import SelectedAsset
from curio.stages.media_contracts import (
    Candidate, CandidateEvaluation, CandidateRejection)
from curio.stages.visual_audit import (
    QueryAuditAccumulator,
    SearchQueryAudit,
    candidate_audit_rows,
    search_query_audit_rows,
)
from curio.stages.scene_projection import Chapter
from curio.stages.visual_contracts import SearchPlan, SearchQuery
from curio.stages.visual_planning import build_visual_plan


def _evaluation(query, score, asset_data, evidence, *, accepted, reason=""):
    asset = MediaAssetSnapshot.from_dict(asset_data)
    candidate = Candidate(
        asset, SearchQuery(query, "scene_representation", query, "historical_art"),
        asset.asset_id)
    return CandidateEvaluation(candidate, score, evidence, accepted, reason)


def _visual_plan(scene_id=1, representations=(), aliases=()):
    chapter = Chapter.from_dict({
        "id": scene_id,
        "narration": "A historical scene.",
        "visual_type": "historical_art",
        "representations": [
            {"query": query, "kind": kind, "level": level}
            for query, kind, level in representations],
        "video_context": {"topic": "Ottoman Empire", "aliases": list(aliases)},
    })
    return build_visual_plan(chapter.semantic_scene())


def test_candidate_audit_projects_selected_reused_and_rejected_reasons():
    map_asset = {"provider": "wikimedia", "asset_id": "map-1",
                 "title": "Ottoman map", "source_url": "https://example/map"}
    portrait_asset = {"provider": "met", "asset_id": "portrait-1",
                      "title": "Portrait"}
    evaluated = (
        _evaluation("Ottoman map", 82, map_asset,
                    {"topic_relevance": 100, "scene_relevance": 76,
                     "topic_evidence": {"topic": ["Ottoman"]}}, accepted=True),
        _evaluation("Janissary portrait", 20, portrait_asset,
                    {"semantic_rejection": "scene evidence too weak"},
                    accepted=False, reason="scene evidence too weak"),
    )
    picked = (SelectedAsset.from_dict({
        "asset": map_asset, "query": "Ottoman map", "reuse_reason":
            "fresh_search_and_synthetic_exhausted"}, 0),)

    rows = candidate_audit_rows(
        evaluated, [{"title": "Portrait", "identity": "portrait-1",
                     "reason": "technical gate"}],
        picked, _visual_plan(representations=(
            ("Ottoman map", "map", 2),)), min_score=50)

    assert rows[0]["decision"] == "selected"
    assert rows[0]["reason"] == "reused only after fresh searches and local visual exhausted"
    assert rows[0]["query_level"] == 2
    assert rows[1]["decision"] == "rejected"
    assert rows[1]["reason"] == "scene evidence too weak"
    assert [row["title"] for row in rows].count("Portrait") == 1


def test_scene_visual_decision_builder_owns_audit_projection():
    from curio.media.selection_result import SelectedAsset
    from curio.stages.media_selection import (
        SelectionProvenance, make_selection_decision)
    from curio.stages.scene_candidate_search import SceneCandidateCollection
    from curio.stages.visual_audit import build_scene_visual_decision

    chapter = Chapter.from_dict({
        "id": 1,
        "narration": "Os janízaros formavam a elite militar otomana.",
        "primary_entity": "Janissaries",
        "event": "Ottoman military history",
        "visual_type": "historical_art",
        "representations": [{
            "query": "Ottoman Janissaries", "kind": "person_group", "level": 1}],
        "video_context": {"topic": "Ottoman Empire"},
    })
    scene = chapter.semantic_scene()
    visual_plan = build_visual_plan(scene)
    query = SearchQuery("Ottoman Janissaries", "scene_representation",
                        "Ottoman Janissaries", "person_group")
    search_plan = SearchPlan(1, (query,))
    audit = {query.query: SearchQueryAudit(providers=("wikimedia",),
                                           results=1, eligible=1)}
    collection = SceneCandidateCollection(
        (), (), ("wikimedia",), audit, (query.query,))
    picked = SelectedAsset.from_dict({
        "asset": {"provider": "wikimedia", "asset_id": "janissary-1",
                  "title": "Ottoman Janissaries",
                  "source_url": "https://museum.test/janissary-1"},
        "query": query.query, "score": 85, "relevance": 85,
    }, 0)
    selection = make_selection_decision(1, [picked], "specific")
    provenance = SelectionProvenance(
        False, "new_asset_selected", "specific")
    candidate = Candidate(picked.asset, query, "janissary-1")
    evaluation = CandidateEvaluation(
        candidate, 85, {"topic_relevance": 90, "scene_relevance": 85}, True)

    decision = build_scene_visual_decision(
        selection=selection, selection_provenance=provenance,
        scene=scene, visual_plan=visual_plan, search_plan=search_plan,
        collection=collection, evaluations=(evaluation,), rejected=[],
        technical_rejections=(),
        picked=(picked,), min_score=40, fallback_plan=None, strategy="image")
    row = decision.to_dict()

    assert row["selection"]["asset_id"] == "janissary-1"
    assert row["topic"] == "Ottoman Empire"
    assert row["providers_consulted"] == ["wikimedia"]
    assert row["queries"][0]["query"] == query.query
    assert row["candidates"][0]["decision"] == "selected"
    assert row["search_exhaustion_reason"] == "new_asset_selected"


def test_candidate_audit_marks_below_threshold_without_semantic_reason():
    rows = candidate_audit_rows(
        (_evaluation("Ottoman map", 12,
                     {"asset_id": "map", "title": "Map"}, {},
                     accepted=False, reason="score below threshold"),),
        [], (), _visual_plan(), min_score=50)

    assert rows == [{
        "title": "Map", "provider": "", "query": "Ottoman map", "query_level": 3,
        "topic_relevance": None, "scene_relevance": None, "score": 12,
        "bonus": 0, "clip_score": None, "creator": "", "source_url": "",
        "date_created": "", "media_type": "image", "metadata_support": 0.0,
        "topic_evidence": {}, "scene_evidence": {}, "decision": "rejected",
        "reason": "score below threshold",
    }]


def test_candidate_audit_rejects_untyped_evaluation_rows():
    with pytest.raises(TypeError, match="CandidateEvaluation"):
        candidate_audit_rows([{"query": "Ottoman map"}], [], (),
                             _visual_plan(), min_score=50)


def test_candidate_audit_projects_typed_technical_rejection():
    evaluation = _evaluation(
        "Ottoman map", 0,
        {"asset_id": "map", "title": "Map", "provider": "wikimedia"},
        {}, accepted=True)
    rejection = CandidateRejection(
        evaluation.candidate, "blocked technical term", "technical_gate",
        {"topic_relevance": 80, "scene_relevance": 12})

    rows = candidate_audit_rows(
        (), [], (), _visual_plan(), min_score=50,
        technical_rejections=(rejection,))

    assert rows == [{
        "title": "Map", "provider": "wikimedia", "query": "Ottoman map",
        "topic_relevance": 80, "scene_relevance": 12, "creator": "",
        "source_url": "", "date_created": "", "media_type": "image",
        "decision": "rejected", "reason": "blocked technical term",
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
            _visual_plan(scene_id=4, representations=(
            ("Battle of Mohács", "event", 2),),
            aliases=("Ottoman Empire",)))

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
        [], _visual_plan(scene_id=1))

    assert (rows[0]["outcome"], rows[0]["status"]) == (
        "duplicates_only", "abandoned_duplicates")
    assert rows[1]["status"] == "not_consulted_budget_exhausted"
    assert rows[1]["unexecuted_reason"] == "scene_candidate_budget"


def test_query_audit_reports_deferred_tier_as_not_consulted():
    query = SearchQuery("Ottoman Empire historical map", "topic_fallback",
                       generic=True)
    deferred = QueryAuditAccumulator(unexecuted_reason="tier_not_reached")

    row = search_query_audit_rows(
        SearchPlan(1, (query,)), {query.query: deferred.snapshot()}, [],
        _visual_plan(scene_id=1))[0]

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
        search_query_audit_rows(plan, {}, [], _visual_plan(scene_id=1))


def test_query_audit_rejects_visual_plan_for_another_scene():
    query = SearchQuery("French Revolution", "scene_representation")
    with pytest.raises(ValueError, match="same scene"):
        search_query_audit_rows(
            SearchPlan(1, (query,)), {query.query: SearchQueryAudit()}, [],
            _visual_plan(scene_id=2))
