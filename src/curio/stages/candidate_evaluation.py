"""Editorial evaluation of acquired candidates, separate from providers."""

from __future__ import annotations

from . import scoring
from .media_contracts import Candidate, CandidateEvaluation, EvaluationBatch


def evaluate_specific(entries: list[dict], scene, threshold: float) -> EvaluationBatch:
    """Score scene-specific candidates and partition by the semantic gate."""
    prepared = [_copy_entry(entry) for entry in entries]
    ranked = scoring.rank_candidates(prepared, scene)
    semantic_rejects = [entry for entry in ranked
                        if entry.get("score_detail", {}).get("semantic_rejection")]
    scoreable = [entry for entry in ranked if entry not in semantic_rejects]
    accepted, below = scoring.below_threshold(scoreable, threshold)
    rejected = [*below, *semantic_rejects]
    accepted_ids = {id(entry) for entry in accepted}
    return EvaluationBatch(
        accepted=tuple(_evaluation(entry, id(entry) in accepted_ids, threshold)
                       for entry in ranked if id(entry) in accepted_ids),
        rejected=tuple(_evaluation(entry, False, threshold) for entry in rejected),
    )


def evaluate_generic(entries: list[dict], scene, threshold: float) -> EvaluationBatch:
    """Score late generic candidates against their own terms and topic gates."""
    evaluated = []
    for raw in entries:
        entry = _copy_entry(raw)
        info = scoring.generic_score(entry["asset"], entry["query"])
        if not scoring.topic_anchor_matches(entry["asset"], scene):
            info["score"] = 0.0
        semantic = scoring.semantic_relevance(entry["asset"], scene)
        if semantic["topic_relevance"] is not None:
            if not semantic["topic_matches"]:
                info["score"] = 0.0
                semantic["semantic_rejection"] = "generic candidate lacks topic evidence"
            elif semantic["scene_relevance"] < 25:
                info["score"] = 0.0
                semantic["semantic_rejection"] = "generic candidate lacks scene evidence"
            elif not semantic["scene_matches"]:
                info["score"] = min(info["score"], 55.0)
            if info["score"] > 0:
                info["score"] = min(100.0,
                                     info["score"] + semantic.get("metadata_support", 0.0))
            info.update(semantic)
        entry["score"] = float(info["score"])
        entry["score_detail"] = {
            "base": info["score"],
            "matched": info["matched"],
            "missing": info["missing"],
            "topic_relevance": info.get("topic_relevance"),
            "scene_relevance": info.get("scene_relevance"),
            "topic_matches": info.get("topic_matches", []),
            "scene_matches": info.get("scene_matches", []),
            "topic_evidence": info.get("topic_evidence", {}),
            "scene_evidence": info.get("scene_evidence", {}),
            "metadata_support": info.get("metadata_support", 0.0),
            "provider": info.get("provider", ""),
            "creator": info.get("creator", ""),
            "source_url": info.get("source_url", ""),
            "date_created": info.get("date_created", ""),
            "media_type": info.get("media_type", ""),
            "semantic_rejection": info.get("semantic_rejection", ""),
            "layers": ["base-generic"],
        }
        evaluated.append(entry)
    evaluated.sort(key=lambda entry: (-entry["score"], entry["query"]))
    semantic_rejects = [entry for entry in evaluated
                        if entry["score_detail"].get("semantic_rejection")]
    scoreable = [entry for entry in evaluated if entry not in semantic_rejects]
    accepted, below = scoring.below_threshold(scoreable, threshold)
    rejected = [*below, *semantic_rejects]
    return EvaluationBatch(
        accepted=tuple(_evaluation(entry, True, threshold) for entry in accepted),
        rejected=tuple(_evaluation(entry, False, threshold) for entry in rejected),
    )


def _copy_entry(entry: dict) -> dict:
    return {**entry, "asset": dict(entry.get("asset") or {})}


def _evaluation(entry: dict, accepted: bool,
                threshold: float) -> CandidateEvaluation:
    reason = ""
    if not accepted:
        reason = (entry.get("score_detail", {}).get("semantic_rejection")
                  or f"nota {entry.get('score', 0):.0f} abaixo do mínimo {threshold:.0f}")
    return CandidateEvaluation(
        candidate=Candidate.from_evaluation_input(entry),
        score=float(entry.get("score", 0.0)),
        evidence=dict(entry.get("score_detail", {})),
        accepted=accepted,
        rejection_reason=reason,
        order=int(entry.get("order", 0) or 0),
    )
