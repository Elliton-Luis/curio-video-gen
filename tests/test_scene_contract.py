import pytest

from curio.stages.scene_contract import Alias, VideoContext, VisualRepresentation
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
