import pytest
import json
from types import SimpleNamespace

from curio.stages.scene_contract import (Alias, SemanticScene, VideoContext,
                                         VisualRepresentation)
from curio.stages.scenes import Chapter


def test_legacy_scene_json_roundtrips_into_typed_contract_and_back():
    chapter = Chapter.from_dict({
        "id": 2,
        "narration": "The Battle of Mohács changed the region.",
        "duration_estimate": 5,
        "video_context": {
            "topic": "Ottoman Empire",
            "aliases": ["Devlet-i ʿAlīye"],
            "primary_entities": ["Ottoman Empire"],
        },
        "representations": [{
            "query": "Battle of Mohács 1526",
            "kind": "event",
            "level": 1,
            "source": "entity_catalog",
            "evidence": "entity:Q123",
        }],
    })

    assert isinstance(chapter.video_context, VideoContext)
    assert isinstance(chapter.video_context.aliases[0], Alias)
    assert chapter.video_context.aliases[0].verified is False
    assert isinstance(chapter.representations[0], VisualRepresentation)
    assert chapter.require_valid() is chapter
    saved = chapter.to_dict()
    assert saved["video_context"]["aliases"] == ["Devlet-i ʿAlīye"]
    assert saved["video_context"]["alias_provenance"][0]["source"] == "legacy_metadata"
    assert saved["representations"][0]["evidence"] == "entity:Q123"
    assert Chapter.from_dict(saved).to_dict() == saved


def test_legacy_local_fallback_sentinel_is_interpreted_only_at_load_boundary():
    legacy = Chapter.from_dict({
        "id": 1, "narration": "Uma cena local.", "duration_estimate": 2,
        "visual_intent": "local fallback: french revolution",
    })
    current = Chapter(2, "A cena usa as palavras local fallback.", 2,
                      visual_intent="local fallback is only literal text")
    assert legacy.planning_mode == "deterministic"
    assert current.planning_mode == "unknown"


def test_contract_boundary_reports_invalid_scene_structure():
    chapter = Chapter(1, "   ", 3, visual_type="unrecognized")
    assert chapter.contract_errors() == ["narration_required", "visual_type_unknown"]
    with pytest.raises(ValueError, match="narration_required"):
        chapter.require_valid()


def test_alias_provenance_roundtrip_preserves_verified_evidence():
    context = VideoContext.from_value({
        "topic": "Ottoman Empire",
        "aliases": ["Ottoman Empire"],
        "alias_provenance": [{
            "value": "Ottoman Empire", "source": "wikipedia_langlink",
            "evidence": "https://en.wikipedia.org/wiki/Ottoman_Empire",
            "verified": True,
        }],
    })
    alias = context.aliases[0]
    assert (alias.source, alias.verified) == ("wikipedia_langlink", True)
    assert VideoContext.from_value(context.to_dict()).aliases[0] == alias


def test_legacy_cache_is_normalized_and_validated_at_load_boundary(tmp_path):
    from curio.pipeline_scenes import load_chapters

    cache = tmp_path / "chapters.json"
    cache.write_text(json.dumps([{
        "id": 1, "narration": "A scene.", "duration_estimate": 2,
        "video_context": {"topic": "History"},
        "representations": [{"query": "historical map", "kind": "map"}],
    }]), encoding="utf-8")
    loaded = load_chapters(SimpleNamespace(chapters_json=str(cache)))
    assert loaded[0].require_valid() is loaded[0]
    assert isinstance(loaded[0].representations[0], VisualRepresentation)

    cache.write_text(json.dumps([{"id": 1, "narration": "  "}]), encoding="utf-8")
    with pytest.raises(ValueError, match="narration_required"):
        load_chapters(SimpleNamespace(chapters_json=str(cache)))


def test_semantic_scene_excludes_timeline_and_preserves_meaning_provenance():
    chapter = Chapter.from_dict({
        "id": 7, "narration": "Battle of Mohács in 1526.",
        "duration_estimate": 5, "start": 12, "end": 17,
        "visual_type": "historical_art", "event": "Battle of Mohács",
        "representations": [{"query": "Battle of Mohács 1526",
                             "kind": "event", "source": "planner"}],
    })

    scene = chapter.semantic_scene("llm")

    assert isinstance(scene, SemanticScene)
    assert scene.source == "llm"
    assert scene.planning_mode == "unknown"
    assert scene.event == "Battle of Mohács"
    assert scene.representations[0].kind == "event"
    assert scene.contract_errors() == []
    assert not hasattr(scene, "duration_estimate")
    assert not hasattr(scene, "start")
    assert not hasattr(scene, "end")
    assert "duration_estimate" not in scene.to_dict()
    scene.video_context.topic = "changed downstream"
    assert chapter.video_context.topic != "changed downstream"


def test_representation_is_canonical_and_query_field_is_compatibility_mirror():
    query_only = Chapter(id=1, narration="A cena mostra Marte.",
                         duration_estimate=4, visual_queries=["Mars surface"])
    representation_only = Chapter(
        id=2, narration="A cena mostra Marte.", duration_estimate=4,
        representations=[{"query": "Mars surface", "kind": "place"}])

    projected_query = query_only.semantic_scene()
    projected_representation = representation_only.semantic_scene()

    assert projected_query.visual_queries == ("Mars surface",)
    assert projected_query.representations[0].source == "declared_scene_query"
    assert projected_representation.visual_queries == ("Mars surface",)
    assert [rep.query for rep in projected_representation.representations] == [
        "Mars surface"]


def test_semantic_projection_round_trips_into_timeline_chapter():
    chapter = Chapter(
        id=3, narration="A frase latina abre a cena.", duration_estimate=4.5,
        start=2.0, end=6.5, subject="Frase latina", text_role="quote",
        text_language="la", visual_queries=["Latin inscription"])

    projected = Chapter.from_semantic_scene(
        chapter.semantic_scene("llm"), timing=chapter.timeline_span())

    assert projected.semantic_scene("llm").to_dict() == \
        chapter.semantic_scene("llm").to_dict()
    assert (projected.duration_estimate, projected.start, projected.end) == \
        (4.5, 2.0, 6.5)


def test_timeline_span_rejects_negative_or_reversed_time():
    from curio.stages.scene_contract import TimelineSpan

    with pytest.raises(ValueError, match="non-negative"):
        TimelineSpan(scene_id=1, start=-1)
    with pytest.raises(ValueError, match="must not precede"):
        TimelineSpan(scene_id=1, start=3, end=2)
    with pytest.raises(ValueError, match="must not precede"):
        TimelineSpan(scene_id=1, start=1)
    with pytest.raises(ValueError, match="finite"):
        TimelineSpan(scene_id=1, duration_estimate=float("nan"))


def test_scene_plan_rejects_duplicate_ids_and_missing_provenance():
    from curio.stages.scene_contract import ScenePlanResult
    from curio.stages.scene_contract import TimelineSpan

    scene = SemanticScene(id=1, narration="A scene.")
    with pytest.raises(ValueError, match="unique"):
        ScenePlanResult((scene, scene),
                        (TimelineSpan(1), TimelineSpan(1)), "llm")
    with pytest.raises(ValueError, match="source is required"):
        ScenePlanResult((scene,), (TimelineSpan(1),), "")


def test_semantic_scene_json_roundtrip_does_not_require_chapter_projection():
    scene = SemanticScene(
        id=2, narration="Battle of Mohács in 1526.", source="provider",
        planning_mode="llm", visual_type="historical_art",
        event="Battle of Mohács", representations=(
            VisualRepresentation("Battle of Mohács 1526", kind="event",
                                 source="planner", evidence="scene:event"),),
        video_context=VideoContext(topic="Ottoman Empire"))

    loaded = SemanticScene.from_dict(scene.to_dict())

    assert loaded.to_dict() == scene.to_dict()
    with pytest.raises(ValueError, match="must be an integer"):
        SemanticScene.from_dict({"id": "2", "narration": "A scene."})
    with pytest.raises(ValueError, match="must be a list"):
        SemanticScene.from_dict({"id": 2, "narration": "A scene.",
                                 "representations": "loose keyword"})


def test_scene_plan_artifact_keeps_semantics_and_time_separate():
    from curio.stages.scene_contract import TimelineSpan
    from curio.stages.scene_plan_artifact import plan_from_dict, plan_to_dict
    from curio.stages.scene_contract import ScenePlanResult

    plan = ScenePlanResult(
        (SemanticScene(id=1, narration="A scene."),),
        (TimelineSpan(1, 4, 1, 5),), "local")
    data = plan_to_dict(plan)

    assert "start" not in data["semantic_scenes"][0]
    assert data["timeline_spans"] == [{"scene_id": 1,
                                      "duration_estimate": 4,
                                      "start": 1, "end": 5}]
    assert plan_from_dict(data).semantic_scenes[0].to_dict() == \
        plan.semantic_scenes[0].to_dict()
    data["schema_version"] = 999
    with pytest.raises(ValueError, match="schema_version"):
        plan_from_dict(data)
