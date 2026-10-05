from curio.media.providers import MediaAsset
from curio.stages.candidate_evaluation import evaluate_specific
from curio.stages.media_contracts import Candidate
from curio.stages.scene_projection import Chapter
from curio.stages.visual_contracts import SearchQuery


def _entry(asset_id, title):
    candidate = Candidate(
        MediaAsset(provider="wikimedia", asset_id=asset_id, title=title,
                   license="CC BY 4.0"),
        SearchQuery("Julius Caesar portrait", "scene_representation",
                    representation="Julius Caesar", representation_kind="person"),
        f"wikimedia:{asset_id}")
    return candidate


def test_evaluator_returns_explained_accepted_and_rejected_results():
    scene = Chapter(1, "Julius Caesar led the campaign.", 5,
                    subject="Julius Caesar", subject_aliases=["Caesar"])
    portrait = _entry("portrait", "Julius Caesar marble bust")
    landscape = _entry("landscape", "Mountain landscape")
    batch = evaluate_specific([portrait, landscape], scene, threshold=34)

    assert len(batch.accepted) == 1
    assert batch.accepted[0].candidate.asset.asset_id == "portrait"
    assert batch.accepted[0].candidate is portrait
    assert batch.accepted[0].evidence["base"] >= 34
    assert len(batch.rejected) == 1
    rejected = batch.rejected[0]
    assert rejected.candidate.asset.asset_id == "landscape"
    assert rejected.rejection_reason.startswith("nota ")
    assert rejected.to_selection_entry()["query_source"] == "scene_representation"


def test_evaluator_rejects_untyped_dict_candidate():
    import pytest

    scene = Chapter(1, "Julius Caesar led the campaign.", 5,
                    subject="Julius Caesar")
    with pytest.raises(TypeError, match="requires Candidate values"):
        evaluate_specific([{"query": "Julius Caesar"}], scene, threshold=34)


def test_evaluation_batch_rejects_partition_that_disagrees_with_decision():
    import pytest

    scene = Chapter(1, "Julius Caesar led the campaign.", 5,
                    subject="Julius Caesar")
    result = evaluate_specific([_entry("portrait", "Julius Caesar bust")],
                               scene, threshold=34)
    with pytest.raises(ValueError, match="rejected partition is inconsistent"):
        type(result)((), (result.accepted[0],))
