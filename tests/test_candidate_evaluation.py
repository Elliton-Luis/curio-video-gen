from curio.media.providers import MediaAsset
from curio.stages.candidate_evaluation import evaluate_specific
from curio.stages.media_contracts import Candidate
from curio.stages.scenes import Chapter
from curio.stages.visual_contracts import SearchQuery


def _entry(asset_id, title):
    candidate = Candidate(
        MediaAsset(provider="wikimedia", asset_id=asset_id, title=title,
                   license="CC BY 4.0"),
        SearchQuery("Julius Caesar portrait", "scene_representation",
                    representation="Julius Caesar", representation_kind="person"),
        f"wikimedia:{asset_id}")
    return candidate.to_evaluation_input()


def test_evaluator_returns_explained_accepted_and_rejected_results():
    scene = Chapter(1, "Julius Caesar led the campaign.", 5,
                    subject="Julius Caesar", subject_aliases=["Caesar"])
    batch = evaluate_specific([
        _entry("portrait", "Julius Caesar marble bust"),
        _entry("landscape", "Mountain landscape"),
    ], scene, threshold=34)

    assert len(batch.accepted) == 1
    assert batch.accepted[0].candidate.asset.asset_id == "portrait"
    assert batch.accepted[0].evidence["base"] >= 34
    assert len(batch.rejected) == 1
    rejected = batch.rejected[0]
    assert rejected.candidate.asset.asset_id == "landscape"
    assert rejected.rejection_reason.startswith("nota ")
    assert rejected.to_selection_entry()["query_source"] == "scene_representation"
