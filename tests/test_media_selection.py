import pytest

from curio.stages.media_selection import (
    RankedSelectionCandidate,
    ReuseCandidate,
    SelectionDecision,
    make_selection_decision,
    prepare_selection_pool,
    record_asset_usage,
    select_reuse_candidate,
)
from tests.media_test_support import with_selection


def test_fresh_candidates_are_separated_before_reuse_without_score_penalty():
    from curio.media.providers import MediaAsset
    from curio.stages.media_contracts import Candidate, CandidateEvaluation
    from curio.stages.visual_contracts import SearchQuery

    used = {"asset-old": 7}
    def ranked_candidate(asset_id, score):
        candidate = Candidate(
            MediaAsset("fixture", asset_id, title=asset_id),
            SearchQuery("topic portrait", "scene_representation"),
            f"fixture:{asset_id}")
        evaluated = CandidateEvaluation(candidate, score, {}, True)
        return RankedSelectionCandidate.from_evaluation(evaluated)

    ranked = [ranked_candidate("asset-old", 95),
              ranked_candidate("asset-new", 61)]

    pool = prepare_selection_pool(ranked, used,
                                  lambda asset: asset["asset_id"])

    assert [entry.asset.asset_id for entry in pool.fresh] == ["asset-new"]
    assert [entry.asset.asset_id for entry in pool.reused] == ["asset-old"]
    assert ranked[0].score == 95


def test_ranked_selection_candidate_keeps_clip_and_prepared_asset_typed():
    from curio.media.asset_snapshot import MediaAssetSnapshot
    from curio.media.providers import MediaAsset
    from curio.stages.media_contracts import Candidate, CandidateEvaluation
    from curio.stages.visual_contracts import SearchQuery

    candidate = Candidate(
        MediaAsset("fixture", "portrait", title="Historical portrait"),
        SearchQuery("historical portrait", "scene_representation"),
        "fixture:portrait")
    ranked = RankedSelectionCandidate.from_evaluation(
        CandidateEvaluation(candidate, 90, {"layers": ["base"]}, True))
    prepared = MediaAssetSnapshot.from_media_asset(MediaAsset(
        "fixture", "portrait", title="Historical portrait",
        local_path="/cache/portrait.jpg"))

    adjusted = ranked.with_clip_score(0.5, prepared)

    assert ranked.asset.local_path == ""
    assert ranked.score == 90
    assert adjusted.asset.local_path == "/cache/portrait.jpg"
    assert adjusted.score == 87.0
    assert adjusted.evaluation.evidence["clip"] == 0.5
    assert adjusted.evaluation.evidence["layers"] == ("base", "clip")
    row = adjusted.to_selection_entry()
    assert row["clip_score"] == 0.5
    assert row["score_detail"]["layers"] == ["base", "clip"]


def test_selection_pool_rejects_untyped_candidate_rows():
    with pytest.raises(TypeError, match="ranked selection candidates"):
        prepare_selection_pool([{"asset": {"asset_id": "legacy"}}], {},
                               lambda asset: asset.get("asset_id", ""))


def test_candidate_acquisition_outcome_projects_selected_and_rejected_states():
    from curio.media.asset_snapshot import MediaAssetSnapshot
    from curio.media.providers import MediaAsset
    from curio.stages.media_acquisition_contracts import CandidateAcquisitionOutcome
    from curio.stages.media_contracts import Candidate, CandidateEvaluation
    from curio.stages.visual_contracts import SearchQuery

    candidate = Candidate(
        MediaAsset("fixture", "asset-1", title="Battle painting"),
        SearchQuery("Battle painting", "scene_representation"),
        "fixture:asset-1")
    ranked = RankedSelectionCandidate.from_evaluation(
        CandidateEvaluation(candidate, 82, {"scene_relevance": 80}, True))
    downloaded = MediaAssetSnapshot.from_media_asset(MediaAsset(
        "fixture", "asset-1", title="Battle painting",
        local_path="/cache/battle.jpg", size_bytes=12000))

    selected = CandidateAcquisitionOutcome(
        candidate=ranked, asset=downloaded, disposition="selected",
        origin="download", content_identity="sha256:abc",
        selected_order=0)
    selected_asset = selected.to_selected_asset()
    assert selected_asset.asset.local_path == "/cache/battle.jpg"
    assert selected_asset.query == "Battle painting"
    assert selected_asset.acquisition == "download"
    assert selected_asset.score == 82

    rejected = CandidateAcquisitionOutcome(
        candidate=ranked, asset=downloaded,
        disposition="invalid_dimensions", origin="download",
        rejection_stage="dimensions",
        reason="resolução/legibilidade após download")
    rejection_row = rejected.to_rejection_row()
    assert rejection_row["identity"] == "fixture:asset-1"
    assert rejection_row["audit_reason"] == "resolution/legibility after download"

    with pytest.raises(ValueError, match="selected candidate requires acquisition origin"):
        CandidateAcquisitionOutcome(
            candidate=ranked, asset=downloaded, disposition="selected",
            selected_order=0)


def test_asset_usage_links_provider_identity_to_downloaded_content_hash():
    usage = {}
    searched = {"asset_id": "same-id", "provider": "wikimedia",
                "source_url": "https://commons.wikimedia.org/wiki/File:A"}
    acquired = {**searched, "local_path": "/tmp/a.jpg"}

    def identity(asset):
        return "sha256:bytes" if asset.get("local_path") else \
            "url:" + asset["source_url"]

    record_asset_usage(usage, searched, acquired, identity)

    assert usage == {"url:https://commons.wikimedia.org/wiki/File:A": 1,
                     "sha256:bytes": 1}
    record_asset_usage(usage, searched, acquired, identity, increment=False)
    assert set(usage.values()) == {1}


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
    from curio.media.selection_result import SelectedAsset

    selected = [SelectedAsset.from_dict(entry, index)
                for index, entry in enumerate(picked)]
    decision = make_selection_decision(3, selected, fallback)

    assert decision.status == status
    assert decision.reason
    assert decision.fallback_level == fallback
    assert decision.to_dict()["scene_id"] == 3


def test_selected_decision_requires_identity_and_reason():
    with pytest.raises(ValueError, match="asset identity"):
        SelectionDecision(scene_id=1, status="real", fallback_level="specific",
                          reason="selected")
    with pytest.raises(ValueError, match="explain"):
        SelectionDecision(scene_id=1, status="none", fallback_level="exhausted")


def test_selection_decision_rejects_contradictory_state_and_missing_fallback():
    with pytest.raises(ValueError, match="declare fallback level"):
        SelectionDecision(scene_id=1, status="none", reason="no asset")
    with pytest.raises(ValueError, match="reuse"):
        SelectionDecision(scene_id=1, status="reused", asset_id="a",
                          provider="wikimedia", fallback_level="reused",
                          reason="selected")
    with pytest.raises(ValueError, match="synth provider"):
        SelectionDecision(scene_id=1, status="synthetic", asset_id="a",
                          provider="wikimedia", fallback_level="synthetic",
                          reason="synthetic")


def test_selection_decision_rejects_untyped_rows():
    with pytest.raises(TypeError, match="SelectedAsset"):
        make_selection_decision(
            1, [{"asset": {"provider": "fixture", "asset_id": "a"}}],
            "specific")


def test_selection_decision_reads_provenance_from_selected_asset_contract():
    from curio.media.selection_result import SelectedAsset

    picked = SelectedAsset.from_dict({
        "asset": {"provider": "wikimedia", "asset_id": "battle"},
        "query": "Battle of Mohacs painting",
        "query_source": "scene_representation",
        "representation": "Battle of Mohacs",
        "score": 84,
    }, 0)

    decision = make_selection_decision(4, [picked], "specific")

    assert decision.query == "Battle of Mohacs painting"
    assert decision.query_source == "scene_representation"
    assert decision.representation == "Battle of Mohacs"


def test_cross_scene_reuse_prefers_scene_relevance_then_nearest_donor():
    from curio.media.selection_result import SelectedAsset

    def entry(asset_id):
        return SelectedAsset.from_dict({
            "asset": {"provider": "fixture", "asset_id": asset_id}}, 0)

    far_strong = ReuseCandidate(1, entry("strong"),
                               topic_relevance=100, scene_relevance=90)
    near_weaker = ReuseCandidate(4, entry("near"),
                                 topic_relevance=100, scene_relevance=80)
    near_equal_earlier = ReuseCandidate(
        3, entry("earlier"),
        topic_relevance=100, scene_relevance=90)
    near_equal_later = ReuseCandidate(
        5, entry("later"),
        topic_relevance=100, scene_relevance=90)

    selected = select_reuse_candidate(
        [far_strong, near_weaker, near_equal_earlier, near_equal_later], 4)

    assert selected is near_equal_earlier


def test_reuse_candidate_requires_immutable_selected_asset():
    with pytest.raises(TypeError, match="SelectedAsset"):
        ReuseCandidate(1, {"asset": {"asset_id": "legacy-dict"}},
                       topic_relevance=80, scene_relevance=60)


def test_cross_scene_reuse_updates_the_selection_contract():
    from curio.media.selection_result import MediaStageResult
    from curio.stages.scene_contract import SemanticScene
    from curio.stages.media_selection import resolve_cross_scene_reuse

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
        with_selection({"chapter_id": 1, "asset": selected_asset, "assets": [
            {"asset": selected_asset, "score": 88},
            {"asset": other_asset, "score": 70},
        ]}),
        {"chapter_id": 2, "asset": None, "assets": [],
         "visual_decision": {"selection": SelectionDecision(
             2, "none", fallback_level="exhausted",
             reason="no candidate").to_dict()}},
    ]

    outcome = resolve_cross_scene_reuse(
        MediaStageResult.from_rows(media_scenes, "provider"), list(scenes))
    reused = outcome.to_rows()[1]

    assert outcome.real_scenes == 2
    assert reused["reused_from"] == 1
    assert [entry["asset"]["asset_id"] for entry in reused["assets"]] == [
        "ottoman-map"]
    assert reused["visual_decision"]["selection"]["status"] == "reused"
    assert reused["visual_decision"]["selection"]["asset_id"] == "ottoman-map"
    assert reused["visual_decision"]["selection"]["fallback_level"] == (
        "validated_reuse")


def test_scene_selection_contract_owns_and_validates_reuse_projection():
    from curio.media.selection_result import MediaStageResult, SelectedAsset
    from tests.media_test_support import with_selection

    empty = with_selection({"chapter_id": 2, "asset": None, "assets": []})
    target = MediaStageResult.from_rows([empty], "fixture").scenes[0]
    reused_row = {"asset": {"provider": "fixture", "asset_id": "asset-1"},
                  "order": 0, "reuse_reason": "validated_cross_scene_reuse"}
    reused_asset = SelectedAsset.from_dict(reused_row, 0)
    decision = make_selection_decision(2, [reused_asset], "validated_reuse")

    updated = target.with_cross_scene_reuse(
        reused_asset, 1, decision, topic_relevance=100,
        scene_relevance=75)

    assert updated.asset.asset_id == "asset-1"
    assert updated.decision.status == "reused"
    assert updated.reused_from == 1
    assert updated.to_dict()["visual_decision"]["fallback"] == "validated_reuse"
    with pytest.raises(ValueError, match="another positive scene"):
        target.with_cross_scene_reuse(
            reused_asset, 2, decision, topic_relevance=100,
            scene_relevance=75)


def test_media_stage_result_uses_typed_scene_selection_and_roundtrips_project_row():
    from curio.media.asset_snapshot import MediaAssetSnapshot
    from curio.media.selection_result import (MediaStageResult,
                                              SceneMediaSelection)

    rows = [with_selection({
        "chapter_id": 1,
        "asset": {"provider": "wikimedia", "asset_id": "map-1",
                  "title": "Historical map"},
        "assets": [{"asset": {"provider": "wikimedia", "asset_id": "map-1",
                                "title": "Historical map"},
                    "query": "historical map", "score": 87.5}],
        "extension_field": {"source": "legacy"},
    })]
    result = MediaStageResult.from_rows(rows, "provider")

    assert isinstance(result.scenes[0], SceneMediaSelection)
    assert isinstance(result.scenes[0].asset, MediaAssetSnapshot)
    assert result.scenes[0].assets[0].query == "historical map"
    assert result.real_scenes == result.selected_asset_count == 1
    assert result.to_rows() == rows
    projected = result.to_rows()
    projected[0]["asset"]["title"] = "mutated projection"
    assert result.scenes[0].asset.title == "Historical map"


def test_scene_media_selection_freezes_assets_and_nested_project_rows():
    from curio.media.selection_result import MediaStageResult
    from tests.media_test_support import with_selection

    row = with_selection({
        "chapter_id": 1,
        "asset": {"provider": "wikimedia", "asset_id": "map-1",
                  "title": "Historical map", "tags": ["map"]},
        "assets": [{"asset": {"provider": "wikimedia", "asset_id": "map-1",
                                "title": "Historical map"},
                    "score_detail": {"topic_evidence": {"matched": ["Ottoman"]}}}],
        "rejected": [{"reason": "weak", "evidence": {"terms": ["unrelated"]}}],
        "reuse": [{"reason": "none", "details": {"scenes": [1, 2]}}],
    })
    result = MediaStageResult.from_rows([row], "fixture")
    scene = result.scenes[0]

    row["asset"]["title"] = "changed source row"
    row["rejected"][0]["evidence"]["terms"].append("changed source row")
    assert scene.asset.title == "Historical map"
    assert scene.rejected[0]["evidence"]["terms"] == ("unrelated",)

    with pytest.raises((AttributeError, TypeError)):
        scene.asset.title = "changed"
    with pytest.raises(TypeError):
        scene.assets[0].score_detail["topic_evidence"]["matched"] = ("changed",)
    with pytest.raises(AttributeError):
        scene.rejected[0]["evidence"]["terms"].append("changed")
    with pytest.raises(TypeError):
        scene.reuse[0]["details"]["scenes"] = (9,)

    mutable_projection = result.to_rows()
    mutable_projection[0]["rejected"][0]["evidence"]["terms"].append("edited")
    assert result.to_rows()[0]["rejected"][0]["evidence"]["terms"] == ["unrelated"]


def test_media_stage_result_rejects_selected_asset_without_identity():
    import pytest
    from curio.media.selection_result import MediaStageResult

    with pytest.raises(ValueError, match="provider and asset id"):
        MediaStageResult.from_rows(
            [{"chapter_id": 1, "asset": {"provider": "wikimedia"},
              "assets": [],
              "visual_decision": {"selection": {
                  "scene_id": 1, "status": "real", "asset_id": "valid",
                  "provider": "wikimedia", "reason": "fixture"}}}], "provider")


def test_media_stage_result_requires_explicit_decision_for_empty_scene():
    from curio.media.selection_result import MediaStageResult

    with pytest.raises(ValueError, match="explicit selection decision"):
        MediaStageResult.from_rows(
            [{"chapter_id": 1, "asset": None, "assets": []}], "provider")
