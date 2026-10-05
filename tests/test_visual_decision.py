import pytest

from curio.media.visual_decision import VisualDecision
from curio.stages.media_selection import SelectionDecision


def _selection(status="real", **updates):
    fields = {
        "scene_id": 1,
        "status": status,
        "asset_id": "asset-1",
        "provider": "wikimedia",
        "fallback_level": "specific",
        "reason": "selected by scene relevance",
    }
    fields.update(updates)
    return SelectionDecision(**fields)


def test_visual_decision_round_trip_preserves_legacy_and_extension_fields():
    source = {
        "topic": "Ottoman Empire",
        "visual_intent": "Janissary uniform",
        "queries": [{"query": "Janissary Ottoman Empire"}],
        "selection": _selection().to_dict(),
        "legacy_extension": {"origin": "project-cache"},
    }

    decision = VisualDecision.from_dict(source)
    serialized = decision.to_dict()
    serialized["legacy_extension"]["origin"] = "changed-copy"

    assert decision.selection == _selection()
    assert decision.to_dict() == source


def test_visual_decision_updates_selection_without_mutating_prior_value():
    initial = VisualDecision.create(
        _selection(), payload={"topic": "Ottoman Empire", "custom": ["kept"]})
    reused = _selection(
        "reused", reuse_reason="fresh searches exhausted",
        fallback_level="reused", reason="editorially justified donor")

    changed = initial.with_selection(
        reused, selected={"title": "Map", "provider": "wikimedia"},
        fallback="validated_reuse")

    assert initial.to_dict()["selection"]["status"] == "real"
    assert changed.to_dict()["selection"]["status"] == "reused"
    assert changed.to_dict()["custom"] == ["kept"]
    assert changed.to_dict()["fallback"] == "validated_reuse"


@pytest.mark.parametrize("field,value", [
    ("topic", 42),
    ("queries", "not-a-list"),
    ("search_exhausted", "yes"),
    ("selected", []),
])
def test_visual_decision_rejects_malformed_known_fields(field, value):
    payload = {"selection": _selection().to_dict(), field: value}

    with pytest.raises(TypeError, match="visual decision"):
        VisualDecision.from_dict(payload)


def test_visual_decision_requires_selection():
    with pytest.raises(ValueError, match="requires selection"):
        VisualDecision.from_dict({"topic": "Ottoman Empire"})
