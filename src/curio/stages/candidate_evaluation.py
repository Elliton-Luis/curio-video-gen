"""Editorial evaluation of acquired candidates, separate from providers."""

from __future__ import annotations

from . import scoring
from .media_contracts import (Candidate, CandidateEvaluation, CandidateRejection,
                              EvaluationBatch)


def evaluate_specific(candidates: list[Candidate], scene,
                      threshold: float) -> EvaluationBatch:
    """Score scene-specific candidates and partition by the semantic gate."""
    prepared, by_identity = _scoring_entries(candidates, generic=False)
    ranked = scoring.rank_candidates(prepared, scene)
    semantic_rejects = [entry for entry in ranked
                        if entry.get("score_detail", {}).get("semantic_rejection")]
    scoreable = [entry for entry in ranked if entry not in semantic_rejects]
    accepted, below = scoring.below_threshold(scoreable, threshold)
    rejected = [*below, *semantic_rejects]
    accepted_ids = {id(entry) for entry in accepted}
    return EvaluationBatch(
        accepted=tuple(_evaluation(entry, by_identity, True, threshold)
                       for entry in ranked if id(entry) in accepted_ids),
        rejected=tuple(_evaluation(entry, by_identity, False, threshold)
                       for entry in rejected),
    )


def evaluate_generic(candidates: list[Candidate], scene,
                     threshold: float) -> EvaluationBatch:
    """Score late generic candidates against their own terms and topic gates."""
    entries, by_identity = _scoring_entries(candidates, generic=True)
    evaluated = []
    for entry in entries:
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
        accepted=tuple(_evaluation(entry, by_identity, True, threshold)
                       for entry in accepted),
        rejected=tuple(_evaluation(entry, by_identity, False, threshold)
                       for entry in rejected),
    )


def describe_technical_rejections(
        rejected: tuple[CandidateRejection, ...], scene) -> tuple[dict, ...]:
    """Add semantic evidence to technical rejections without changing gates."""
    if not isinstance(rejected, tuple) or any(
            not isinstance(item, CandidateRejection) for item in rejected):
        raise TypeError("technical rejection evidence requires CandidateRejection values")
    return tuple({**item.to_dict(), **scoring.semantic_relevance(
        item.candidate.asset.to_dict(), scene)} for item in rejected)


def _scoring_entries(candidates: list[Candidate], *, generic: bool
                     ) -> tuple[list[dict], dict[str, Candidate]]:
    if any(not isinstance(candidate, Candidate) for candidate in candidates):
        raise TypeError("candidate evaluation requires Candidate values")
    selected = [candidate for candidate in candidates
                if candidate.search_query.generic is generic]
    identities = [candidate.identity for candidate in selected]
    if len(identities) != len(set(identities)):
        raise ValueError("candidate evaluation identities must be unique")
    return ([candidate.to_evaluation_input() for candidate in selected],
            {candidate.identity: candidate for candidate in selected})


def _evaluation(entry: dict, by_identity: dict[str, Candidate], accepted: bool,
                threshold: float) -> CandidateEvaluation:
    reason = ""
    if not accepted:
        reason = (entry.get("score_detail", {}).get("semantic_rejection")
                  or f"nota {entry.get('score', 0):.0f} abaixo do mínimo {threshold:.0f}")
    return CandidateEvaluation(
        candidate=by_identity[entry["identity"]],
        score=float(entry.get("score", 0.0)),
        evidence=dict(entry.get("score_detail", {})),
        accepted=accepted,
        rejection_reason=reason,
        order=int(entry.get("order", 0) or 0),
    )
