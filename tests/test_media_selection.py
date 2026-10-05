import pytest

from curio.stages.media_selection import (
    SelectionDecision,
    make_selection_decision,
    prepare_selection_pool,
)


def test_fresh_candidates_are_separated_before_reuse_without_score_penalty():
    used = {"asset-old": 7}
    ranked = [
        {"asset": {"asset_id": "asset-old"}, "score": 95},
        {"asset": {"asset_id": "asset-new"}, "score": 61},
    ]

    pool = prepare_selection_pool(ranked, used,
                                  lambda asset: asset["asset_id"])

    assert [entry["asset"]["asset_id"] for entry in pool.fresh] == ["asset-new"]
    assert [entry["asset"]["asset_id"] for entry in pool.reused] == ["asset-old"]
    assert ranked[0]["score"] == 95


@pytest.mark.parametrize(("picked", "fallback", "status"), [
    ([{"asset": {"asset_id": "a", "provider": "wikimedia"}, "score": 88}],
     "specific", "real"),
    ([{"asset": {"asset_id": "a", "provider": "wikimedia"},
       "reuse_reason": "fresh search exhausted"}], "reused", "reused"),
    ([{"asset": {"asset_id": "a", "provider": "synth"}}],
     "synthetic_after_exhaustion", "synthetic"),
    ([], "exhausted", "none"),
])
def test_selection_decision_explains_all_outcomes(picked, fallback, status):
    decision = make_selection_decision(3, picked, fallback)

    assert decision.status == status
    assert decision.reason
    assert decision.fallback_level == fallback
    assert decision.to_dict()["scene_id"] == 3


def test_selected_decision_requires_identity_and_reason():
    with pytest.raises(ValueError, match="asset identity"):
        SelectionDecision(scene_id=1, status="real", reason="selected")
    with pytest.raises(ValueError, match="explain"):
        SelectionDecision(scene_id=1, status="none")


def test_cross_scene_reuse_updates_the_selection_contract():
    from curio.pipeline_visual import MediaStageResult
    from curio.stages.scene_contract import SemanticScene
    from curio.stages.visual import _resolve_reuse_multi

    scene_context = {"topic": "Ottoman Empire"}
    scenes = (
        SemanticScene(1, "The Ottoman Empire used Janissaries.",
                     event="Ottoman Empire historical map",
                     video_context=scene_context),
        SemanticScene(2, "The Ottoman Empire used Janissaries.",
                     event="Ottoman Empire historical map",
                     video_context=scene_context),
    )
    selected_asset = {
        "asset_id": "ottoman-map", "provider": "fixture",
        "title": "Ottoman Empire historical map",
    }
    other_asset = {
        "asset_id": "unrelated", "provider": "fixture",
        "title": "Unrelated portrait",
    }
    media_scenes = [
        {"chapter_id": 1, "asset": selected_asset, "assets": [
            {"asset": selected_asset, "score": 88},
            {"asset": other_asset, "score": 70},
        ]},
        {"chapter_id": 2, "asset": None, "assets": [],
         "visual_decision": {"selection": SelectionDecision(
             2, "none", reason="no candidate").to_dict()}},
    ]

    _resolve_reuse_multi(media_scenes, scenes)
    reused = media_scenes[1]
    outcome = MediaStageResult(media_scenes, "provider", [], 2, 0, 0)

    assert outcome.real_scenes == 2
    assert reused["reused_from"] == 1
    assert [entry["asset"]["asset_id"] for entry in reused["assets"]] == [
        "ottoman-map"]
    assert reused["visual_decision"]["selection"]["status"] == "reused"
    assert reused["visual_decision"]["selection"]["asset_id"] == "ottoman-map"
    assert reused["visual_decision"]["selection"]["fallback_level"] == (
        "validated_reuse")
