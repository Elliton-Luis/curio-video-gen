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
