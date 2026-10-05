import pytest

from curio.media.selection_result import MediaStageResult
from curio.pipeline_render import (
    RenderTransitionPlan,
    SceneRenderPlan,
    genre_transition_kinds,
    genre_transitions,
    plan_transitions,
    transition_signature,
)
from curio.stages.scene_contract import SemanticScene
from curio.stages.scene_contract import TimelineSpan


def test_render_plan_projects_validated_media_selection():
    result = MediaStageResult.from_rows([{
        "chapter_id": 1,
        "asset": {"provider": "wikimedia", "asset_id": "map-1",
                  "local_path": "/cache/map.jpg", "kind": "image"},
        "assets": [],
    }], "provider")

    plan = SceneRenderPlan.from_media_result(result)

    assert plan.scenes[0].scene_id == 1
    assert plan.scenes[0].asset.local_path == "/cache/map.jpg"
    assert plan.for_scenes((SemanticScene(1, "A scene."),))[1].kind == "image"


def test_persisted_adapter_preserves_legacy_renderable_asset_without_identity():
    plan = SceneRenderPlan.from_persisted_rows([{
        "chapter_id": 1,
        "asset": {"local_path": "/old-project/photo.jpg"},
    }])

    assert plan.scenes[0].asset.local_path == "/old-project/photo.jpg"
    assert plan.scenes[0].asset.kind == "image"


def test_transition_plan_unifies_render_choices_and_cache_signature():
    scenes = (SemanticScene(1, "Opening."), SemanticScene(2, "The army invaded."))
    spans = (TimelineSpan(1, 5, 0, 5), TimelineSpan(2, 5, 5, 10))
    identity = {"visual_sfx": False}

    plan = plan_transitions(scenes, spans, "history", "auto", identity)

    assert isinstance(plan, RenderTransitionPlan)
    assert plan.boundary_durations == tuple(genre_transitions(scenes, "history"))
    assert plan.kinds == tuple(genre_transition_kinds(scenes, "history"))
    assert plan.signature == transition_signature(
        scenes, spans, "history", "auto", identity)
    assert plan.to_dict(0.65) == {
        "genre": "history", "mode": "auto",
        "boundary_durations": list(plan.boundary_durations), "final_fade": 0.65}


def test_transition_plan_rejects_inconsistent_choices():
    with pytest.raises(ValueError, match="incomplete or inconsistent"):
        RenderTransitionPlan("history", "auto", (float("nan"),), ("fade",), "sig")
    with pytest.raises(ValueError, match="incomplete or inconsistent"):
        RenderTransitionPlan("history", "auto", (0.2,), (), "sig")


@pytest.mark.parametrize("rows, error", [
    ({}, TypeError),
    ([{"chapter_id": True, "asset": None}], ValueError),
    ([{"chapter_id": 1}, {"chapter_id": 1}], ValueError),
    ([{"chapter_id": 1, "asset": "bad"}], TypeError),
])
def test_persisted_render_adapter_rejects_invalid_scene_rows(rows, error):
    with pytest.raises(error):
        SceneRenderPlan.from_persisted_rows(rows)
