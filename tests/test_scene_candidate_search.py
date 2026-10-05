from dataclasses import replace
from types import SimpleNamespace

import pytest

from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.stages.media_search import ProviderSearchResult
from curio.stages.scene_candidate_search import SceneCandidateCollector
from curio.stages.candidate_evaluation import describe_technical_rejections
from curio.stages.scene_contract import SemanticScene, VideoContext, VisualRepresentation
from curio.stages.visual_audit import SearchQueryAudit
from curio.stages.visual_contracts import SearchPlan, SearchQuery
from curio.stages.visual_planning import build_visual_plan


def _collector(monkeypatch, *, max_candidates=20, responses=None,
               include_generic=False):
    scene = SemanticScene(
        id=1, narration="Battle of Mohacs in 1526",
        subject="Battle of Mohacs", primary_entity="Battle of Mohacs",
        event="Battle of Mohacs", visual_type="historical_art",
        representations=(VisualRepresentation(
            "Battle of Mohacs", "event", 1, "planner"),),
        video_context=VideoContext(topic="Ottoman Empire"))
    visual_plan = build_visual_plan(scene)
    queries = (
        SearchQuery("Battle of Mohacs Ottoman Empire", "scene_representation",
                    representation="Battle of Mohacs", representation_kind="event"),
        SearchQuery("Battle of Mohacs 1526 Ottoman Empire", "representation_period",
                    representation="Battle of Mohacs", representation_kind="event",
                    variant="1526", level=2),
    )
    if include_generic:
        queries += (SearchQuery("Ottoman Empire historical map", "topic_fallback",
                                representation="Ottoman Empire", generic=True),)
    search_plan = SearchPlan(scene.id, queries)
    provider = SimpleNamespace(name="wikimedia", _disabled=False)
    asset = MediaAsset(
        "wikimedia", "mohacs", title="Battle of Mohacs engraving",
        download_url="https://example.test/mohacs.jpg",
        source_url="https://example.test/item/mohacs",
        license="CC0", width=1800, height=1200)
    query_responses = responses or {query.query: (asset,) for query in queries}

    def search(query, providers, **_kwargs):
        assert providers == [provider]
        def stream():
            yield ProviderSearchResult(query, "wikimedia",
                                       query_responses.get(query, ()))
        return stream()

    monkeypatch.setattr(
        "curio.stages.scene_candidate_search.media_search.search_providers",
        search)
    collector = SceneCandidateCollector(
        scene, visual_plan, search_plan, [provider], CurioConfig(), None, [],
        max_candidates=max_candidates)
    return collector, search_plan


def test_candidate_collection_deduplicates_across_planned_queries(monkeypatch):
    collector, plan = _collector(monkeypatch)

    result = collector.collect([query.query for query in plan.queries], 10)

    assert len(result.candidates) == 1
    assert result.candidates[0].search_query == plan.queries[0]
    assert result.query_audit[plan.queries[0].query].eligible == 1
    duplicate = result.query_audit[plan.queries[1].query]
    assert duplicate.duplicates == 1
    assert duplicate.duplicates_only is True
    assert result.providers_consulted == ("wikimedia",)
    with pytest.raises(TypeError):
        result.query_audit[plan.queries[0].query] = SearchQueryAudit()
    with pytest.raises((AttributeError, TypeError)):
        duplicate.duplicates = 0


def test_candidate_collection_snapshots_audit_before_next_query_batch(monkeypatch):
    collector, plan = _collector(monkeypatch)

    first = collector.collect([plan.queries[0].query], 10)
    collector.collect([plan.queries[1].query], 10)

    assert first.query_audit[plan.queries[1].query].results == 0


def test_candidate_collection_freezes_caller_supplied_audit_mapping(monkeypatch):
    collector, plan = _collector(monkeypatch)
    result = collector.collect([plan.queries[0].query], 10)
    supplied = dict(result.query_audit)

    copied = replace(result, query_audit=supplied)
    supplied.clear()

    assert set(copied.query_audit) == {query.query for query in plan.queries}
    with pytest.raises(TypeError):
        copied.query_audit[plan.queries[0].query] = SearchQueryAudit()


def test_candidate_collection_marks_queries_skipped_by_scene_budget(monkeypatch):
    collector, plan = _collector(monkeypatch, max_candidates=1)

    result = collector.collect([query.query for query in plan.queries], 10)

    assert len(result.candidates) == 1
    skipped = result.query_audit[plan.queries[1].query]
    assert skipped.unexecuted_reason == "scene_candidate_budget"


def test_generic_query_audit_distinguishes_deferred_from_executed(monkeypatch):
    collector, plan = _collector(monkeypatch, include_generic=True)
    generic = plan.queries[-1]

    before = collector.snapshot().query_audit[generic.query]
    assert before.unexecuted_reason == "tier_not_reached"

    collector.collect([plan.queries[0].query], 10)
    deferred = collector.snapshot().query_audit[generic.query]
    assert deferred.unexecuted_reason == "tier_not_reached"

    collector.collect([generic.query], 10)
    executed = collector.snapshot().query_audit[generic.query]
    assert executed.unexecuted_reason == ""
    assert executed.providers == ("wikimedia",)


def test_candidate_collection_rejects_query_outside_search_plan(monkeypatch):
    collector, _plan = _collector(monkeypatch)

    with pytest.raises(ValueError, match="belong to SearchPlan"):
        collector.collect(["unplanned query"], 1)


def test_technical_gate_rejections_stay_typed_until_evidence_projection(monkeypatch):
    collector, plan = _collector(monkeypatch, responses={
        plan_query: (MediaAsset("wikimedia", "missing-url",
                                title="Battle of Mohacs engraving",
                                license="CC0"),)
        for plan_query in ["Battle of Mohacs Ottoman Empire"]
    })

    result = collector.collect([plan.queries[0].query], 10)
    descriptions = describe_technical_rejections(result.rejected,
                                                 collector.scene)

    assert result.candidates == ()
    assert result.rejected[0].reason == "sem URL de download"
    assert descriptions[0]["stage"] == "technical_gate"
    assert "topic_relevance" in descriptions[0]
