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
    from curio.pipeline import _load_chapters

    cache = tmp_path / "chapters.json"
    cache.write_text(json.dumps([{
        "id": 1, "narration": "A scene.", "duration_estimate": 2,
        "video_context": {"topic": "History"},
        "representations": [{"query": "historical map", "kind": "map"}],
    }]), encoding="utf-8")
    loaded = _load_chapters(SimpleNamespace(chapters_json=str(cache)))
    assert loaded[0].require_valid() is loaded[0]
    assert isinstance(loaded[0].representations[0], VisualRepresentation)

    cache.write_text(json.dumps([{"id": 1, "narration": "  "}]), encoding="utf-8")
    with pytest.raises(ValueError, match="narration_required"):
        _load_chapters(SimpleNamespace(chapters_json=str(cache)))


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
