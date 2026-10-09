"""Regressions for evidence, multilingual identity, planning and model cache."""
from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.stages.media_contracts import Candidate, CandidateEvaluation, EvaluationBatch
from curio.stages.scene_contract import SemanticScene, VisualRepresentation
from curio.stages.visual_contracts import SearchQuery
from curio.stages import media_semantics as semantics
import pytest


def fixture(tmp_path, title="Plato's Academy, Athens"):
    config = CurioConfig(cache_dir=str(tmp_path))
    scene = SemanticScene(1, "Platão fundou sua Academia em Atenas.", subject="Platão",
                          video_context={"topic": "Platão", "aliases": ["Plato"]},
                          representations=(VisualRepresentation("Academia de Platão"),))
    asset = MediaAsset("fixture", "image", title=title)
    candidate = Candidate(asset, SearchQuery("query", "scene_representation"), "image")
    item = CandidateEvaluation(candidate, 0, {"semantic_rejection": "no topic evidence"},
                               False, "no topic evidence")
    return config, scene, EvaluationBatch((), (item,))


def response(title, relation="direct", confidence=0.95):
    proof = {"field": "title", "quote": title}
    return {"decisions": [{"id": "0", "relation": relation, "confidence": confidence,
                            "topic_evidence": proof, "scene_evidence": proof,
                            "reason": "Identified scene entity in catalog metadata"}]}


def test_translated_entity_recovered_only_with_literal_metadata_evidence(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path)
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_request", lambda *args: (response("Plato's Academy, Athens"), "fixture"))
    result = semantics.assess_candidates(batch, scene, config, 34)
    assert len(result.accepted) == 1
    assert result.accepted[0].evidence["semantic_assessment"]["relation"] == "direct"
    assert not result.accepted[0].evidence["semantic_rejection"]


def test_hallucinated_proof_cannot_promote_candidate(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path, "Generic school building")
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_request", lambda *args: (response("Plato's Academy"), "fixture"))
    assert not semantics.assess_candidates(batch, scene, config, 34).accepted


def test_catalog_review_cache_works_offline_and_invalidates_changed_metadata(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path)
    calls = []
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    def request(*args):
        calls.append(1)
        return response("Plato's Academy, Athens"), "fixture"
    monkeypatch.setattr(semantics, "_request", request)
    assert semantics.assess_candidates(batch, scene, config, 34).accepted
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: False)
    assert semantics.assess_candidates(batch, scene, config, 34).accepted
    config, scene, changed = fixture(tmp_path, "Unidentified school")
    assert not semantics.assess_candidates(changed, scene, config, 34).accepted
    assert len(calls) == 1


def test_uncertain_homonym_and_invalid_confidence_do_not_promote(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path, "Tesla automobile factory")
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    for confidence in (0.5, float("nan"), True):
        monkeypatch.setattr(semantics, "_cached_request", lambda *args: response("Tesla automobile factory", "direct", confidence))
        assert not semantics.assess_candidates(batch, scene, config, 34).accepted
    monkeypatch.setattr(semantics, "_cached_request", lambda *args: response("Tesla automobile factory", "unrelated"))
    assert not semantics.assess_candidates(batch, scene, config, 34).accepted


def test_translation_extends_approved_concept_with_provenance(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path)
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_request", lambda *args: ({"translations": [
        {"id": "1:0", "query": "Plato Academy Athens"},
        {"id": "invented", "query": "Unrelated building"}]}, "fixture"))
    enriched = semantics.enrich_catalog_vocabulary((scene,), config)[0]
    assert enriched.representations[0].query == "Plato Academy Athens"
    assert enriched.representations[0].evidence == "Academia de Platão"
    assert enriched.representations[1] == scene.representations[0]
    assert len(enriched.representations) == 2


def test_uncertain_identity_cannot_keep_previously_accepted_homonym(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path, "Georg Gottlieb Plato portrait")
    item = batch.rejected[0]
    accepted = CandidateEvaluation(item.candidate, 95, {}, True, "")
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_cached_request", lambda *args: response(
        "Georg Gottlieb Plato portrait", "uncertain", 0.3))
    reviewed = semantics.assess_candidates(EvaluationBatch((accepted,), ()), scene, config, 34)
    assert not reviewed.accepted
    assert reviewed.rejected[0].rejection_reason == "unresolved provider identity"


@pytest.mark.parametrize("topic,representation,title", [
    ("Revolução Francesa", "Prise de la Bastille", "Prise de la Bastille 1789"),
    ("Batalha de Mohács", "Battle of Mohacs", "Battle of Mohacs 1526 engraving"),
    ("Efeito Doppler", "Doppler frequency shift", "Doppler frequency shift diagram"),
    ("Nikola Tesla", "Tesla induction motor", "Tesla induction motor patent"),
])
def test_historical_and_translated_relations_recovered_across_domains(
        tmp_path, monkeypatch, topic, representation, title):
    from curio.stages import scoring
    config = CurioConfig(cache_dir=str(tmp_path))
    scene = SemanticScene(1, topic, subject=topic, video_context={"topic": topic},
                          representations=(VisualRepresentation(representation),))
    asset = MediaAsset("fixture", "image", title=title)
    candidate = Candidate(asset, SearchQuery(representation, "scene_representation"), "image")
    evidence = scoring.base_score(asset.to_dict(), scene)
    item = CandidateEvaluation(candidate, evidence["score"], evidence, False, "needs identity review")
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_cached_request", lambda *args: response(title))
    reviewed = semantics.assess_candidates(EvaluationBatch((), (item,)), scene, config, 34)
    assert reviewed.accepted
    assert reviewed.accepted[0].score == 92


def test_model_failure_preserves_conservative_lexical_result(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path)
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_cached_request", lambda *args: None)
    assert semantics.assess_candidates(batch, scene, config, 34) == batch


def test_translation_never_turns_global_entity_anchor_into_local_scene_proof(tmp_path, monkeypatch):
    config, scene, _ = fixture(tmp_path)
    from dataclasses import replace
    scene = replace(scene, representations=(
        VisualRepresentation("Plato painting", source="verified_entity_context"),
        VisualRepresentation("Plato portrait", source="catalog_translation", evidence="Plato painting"),
        VisualRepresentation("Academia de Platão", source="planner")))
    payloads = []
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    def request(system, payload, *_):
        payloads.append(payload)
        return {"translations": [{"id": "1:1", "query": "Plato Academy Athens"}]}, "fixture"
    monkeypatch.setattr(semantics, "_request", request)
    enriched = semantics.enrich_catalog_vocabulary((scene,), config)[0]
    assert [item["query"] for item in payloads[0]["concepts"]] == ["Academia de Platão"]
    assert not any(rep.source == "catalog_translation" and rep.evidence == "Plato painting"
                   for rep in enriched.representations)


def test_negative_review_can_cite_actual_title_when_tag_quote_is_truncated(tmp_path, monkeypatch):
    config, scene, batch = fixture(tmp_path, "Modern Athens university temple")
    item = batch.rejected[0]
    accepted = CandidateEvaluation(item.candidate, 100, {}, True, "")
    verdict = response("Modern Athens university temple", "unrelated")
    verdict["decisions"][0]["scene_evidence"] = {"field": "tags", "quote": "missing truncated tags"}
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_cached_request", lambda *args: verdict)
    reviewed = semantics.assess_candidates(EvaluationBatch((accepted,), ()), scene, config, 34)
    assert not reviewed.accepted
    assert reviewed.rejected[0].evidence["semantic_rejection"] == "unrelated provider metadata"


@pytest.mark.parametrize("name,expected,depicted,created", [
    ("Battle of Mohacs", "1526", "1687", "1837"),
    ("Council meeting", "1789", "1848", "1890"),
])
def test_model_cannot_override_explicit_temporal_identity_conflict(
        tmp_path, monkeypatch, name, expected, depicted, created):
    config, scene, batch = fixture(tmp_path)
    from dataclasses import replace
    scene = replace(scene, period=expected)
    asset = MediaAsset("fixture", "event", title=f"{name} ({depicted}) {created}", date_created=created)
    candidate = Candidate(asset, SearchQuery(name, "scene_representation"), "event")
    accepted = CandidateEvaluation(candidate, 95, {}, True, "")
    monkeypatch.setattr(semantics.nvidia, "any_llm_available", lambda: True)
    monkeypatch.setattr(semantics, "_cached_request", lambda *args: response(asset.title))
    reviewed = semantics.assess_candidates(EvaluationBatch((accepted,), ()), scene, config, 34)
    assert not reviewed.accepted
    assert reviewed.rejected[0].rejection_reason == "explicit identity year contradicts scene period"


def test_artwork_creation_date_is_not_confused_with_depicted_event(tmp_path):
    from curio.stages.scoring import identity_conflict
    from dataclasses import replace
    _, scene, _ = fixture(tmp_path)
    scene = replace(scene, period="1526")
    assert not identity_conflict({"title": "Historic battle (1837)", "date_created": "1837"}, scene)
    assert not identity_conflict({"title": "Battle 1526 (1837)", "date_created": "1837"}, scene)
    assert not identity_conflict({"title": "Historic battle (1687)"}, scene)
    assert not identity_conflict({"title": "Battle (1687)", "date_created": "1837"},
                                 replace(scene, period="1500-1600"))
