import pytest

from curio.media.providers import MediaAsset
from curio.media.asset_snapshot import MediaAssetSnapshot
from curio.stages.media_contracts import (
    Candidate,
    CandidateEvaluation,
    CandidateRejection,
)
from curio.stages.visual_contracts import SearchQuery


def test_candidate_retains_provider_query_and_representation_provenance():
    query = SearchQuery(
        "Battle of Mohacs 1526 engraving", "representation_variant",
        representation="Battle of Mohacs", representation_kind="event",
        alias="Ottoman Empire", variant="engraving", level=2)
    asset = MediaAsset(
        provider="wikimedia", asset_id="commons-1", title="Battle of Mohacs",
        source_url="https://commons.wikimedia.org/wiki/File:Mohacs.jpg",
        download_url="https://upload.wikimedia.org/mohacs.jpg")
    candidate = Candidate(asset, query, "url:https://commons.wikimedia.org/wiki/file:mohacs.jpg")

    normalized = candidate.to_evaluation_input()
    assert isinstance(candidate.asset, MediaAssetSnapshot)
    assert normalized["asset"]["provider"] == "wikimedia"
    assert normalized["query"] == query.query
    assert normalized["query_source"] == "representation_variant"
    assert normalized["representation"] == "Battle of Mohacs"
    assert normalized["representation_kind"] == "event"
    assert normalized["alias"] == "Ottoman Empire"
    assert normalized["query_variant"] == "engraving"
    assert normalized["identity"] == candidate.identity


def test_candidate_freezes_provider_asset_without_freezing_download_asset():
    asset = MediaAsset(
        provider="wikimedia", asset_id="commons-2", title="Janissary portrait",
        tags=["janissary"], categories=["Ottoman Empire"])
    query = SearchQuery("Janissary Ottoman Empire portrait", "scene_representation",
                        representation="Janissary", representation_kind="person")
    candidate = Candidate(asset, query, "wikimedia:commons-2")
    original_snapshot = candidate.asset.to_dict()

    asset.title = "Changed after provider response"
    asset.tags.append("changed")
    asset.local_path = "/cache/downloaded.jpg"

    assert candidate.asset.to_dict() == original_snapshot
    assert candidate.to_evaluation_input()["asset"]["title"] == "Janissary portrait"
    assert candidate.asset.tags == ("janissary",)
    assert asset.local_path == "/cache/downloaded.jpg"
    with pytest.raises((AttributeError, TypeError)):
        candidate.asset.title = "mutated candidate"
    with pytest.raises(AttributeError):
        candidate.asset.tags.append("mutated candidate")


def test_candidate_evaluation_freezes_evidence_and_projects_mutable_json_copy():
    candidate = Candidate(
        MediaAsset(provider="wikimedia", asset_id="commons-3", title="Map"),
        SearchQuery("Ottoman Empire map", "scene_representation"),
        "wikimedia:commons-3")
    evidence = {"layers": ["base"],
                "topic_evidence": {"matched": ["Ottoman Empire"]}}
    evaluation = CandidateEvaluation(candidate, 75.0, evidence, True)

    evidence["layers"].append("changed")
    evidence["topic_evidence"]["matched"].clear()
    assert evaluation.evidence["layers"] == ("base",)
    assert evaluation.evidence["topic_evidence"]["matched"] == (
        "Ottoman Empire",)
    with pytest.raises(TypeError):
        evaluation.evidence["score"] = 75
    with pytest.raises(AttributeError):
        evaluation.evidence["layers"].append("changed")

    projected = evaluation.to_selection_entry()
    assert projected["score_detail"] == {
        "layers": ["base"],
        "topic_evidence": {"matched": ["Ottoman Empire"]},
    }
    projected["score_detail"]["layers"].append("selection-local")
    assert evaluation.evidence["layers"] == ("base",)


def test_candidate_rejection_names_stage_and_preserves_originating_query():
    query = SearchQuery("French Revolution map", "scene_representation",
                        representation="French Revolution", level=1)
    candidate = Candidate(MediaAsset(
        provider="wikimedia", asset_id="blocked-1", title="French Revolution map"),
        query, "wikimedia:blocked-1")

    rejection = CandidateRejection(candidate, "rights_blocked", "technical_gate").to_dict()
    assert rejection["stage"] == "technical_gate"
    assert rejection["reason"] == "rights_blocked"
    assert rejection["query_source"] == "scene_representation"
    assert rejection["representation"] == "French Revolution"
