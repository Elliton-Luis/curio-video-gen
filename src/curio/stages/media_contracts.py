"""Data crossing provider, evaluation, and selection boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from math import isfinite
from types import MappingProxyType

from ..media.asset_snapshot import MediaAssetSnapshot
from ..media.providers import MediaAsset
from .visual_contracts import SearchQuery


def _freeze_mapping(value: Mapping) -> Mapping:
    return MappingProxyType({key: _freeze_value(item)
                             for key, item in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return deepcopy(value)


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class Candidate:
    """One normalized provider result, linked to the exact query that found it."""

    asset: MediaAssetSnapshot
    search_query: SearchQuery
    identity: str

    def __post_init__(self) -> None:
        if isinstance(self.asset, MediaAsset):
            object.__setattr__(self, "asset",
                               MediaAssetSnapshot.from_media_asset(self.asset))
        if not isinstance(self.asset, MediaAssetSnapshot):
            raise TypeError("candidate asset must be a provider asset snapshot")
        if not isinstance(self.search_query, SearchQuery):
            raise TypeError("candidate search_query must be a SearchQuery")
        if not isinstance(self.identity, str) or not self.identity.strip():
            raise ValueError("candidate identity is required")

    def to_evaluation_input(self) -> dict:
        return {
            "asset": self.asset.to_dict(),
            "query": self.search_query.query,
            "query_source": self.search_query.source,
            "representation": self.search_query.representation,
            "representation_kind": self.search_query.representation_kind,
            "alias": self.search_query.alias,
            "query_variant": self.search_query.variant,
            "query_level": self.search_query.level,
            "generic": self.search_query.generic,
            "identity": self.identity,
            "relevance": 0,
            "order": 0,
        }


@dataclass(frozen=True)
class CandidateRejection:
    candidate: Candidate
    reason: str
    stage: str

    def to_dict(self) -> dict:
        return {
            "title": self.candidate.asset.title,
            "provider": self.candidate.asset.provider,
            "query": self.candidate.search_query.query,
            "query_source": self.candidate.search_query.source,
            "representation": self.candidate.search_query.representation,
            "reason": self.reason,
            "stage": self.stage,
        }


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    score: float
    evidence: dict
    accepted: bool
    rejection_reason: str = ""
    order: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, Candidate):
            raise TypeError("evaluation candidate must be a Candidate")
        if (isinstance(self.score, bool)
                or not isinstance(self.score, (int, float))
                or not isfinite(self.score) or not 0 <= self.score <= 100):
            raise ValueError("candidate score must be finite and within 0..100")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("candidate score evidence must be an object")
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence))
        if not isinstance(self.accepted, bool):
            raise TypeError("candidate accepted flag must be boolean")
        if (isinstance(self.order, bool) or not isinstance(self.order, int)
                or self.order < 0):
            raise ValueError("candidate evaluation order must be non-negative")
        if not isinstance(self.rejection_reason, str):
            raise TypeError("candidate rejection reason must be text")
        if self.accepted and self.rejection_reason:
            raise ValueError("accepted candidate cannot have rejection reason")
        if not self.accepted and not self.rejection_reason.strip():
            raise ValueError("rejected candidate requires rejection reason")

    def to_selection_entry(self) -> dict:
        entry = self.candidate.to_evaluation_input()
        entry["score"] = self.score
        entry["score_detail"] = _json_value(self.evidence)
        entry["order"] = self.order
        if self.rejection_reason:
            entry["rejection_reason"] = self.rejection_reason
        return entry

    def with_clip_score(self, clip_score: float) -> "CandidateEvaluation":
        """Return the score/evidence adjustment from the optional CLIP layer."""
        if (isinstance(clip_score, bool) or not isinstance(clip_score, (int, float))
                or not isfinite(clip_score) or not -1.0 <= clip_score <= 1.0):
            raise ValueError("CLIP score must be finite and within -1..1")
        rounded = round(float(clip_score), 4)
        evidence = _json_value(self.evidence)
        evidence["clip"] = rounded
        evidence["layers"] = list(dict.fromkeys(
            [*evidence.get("layers", []), "clip"]))
        score = round(self.score * 0.8 + ((clip_score + 1.0) * 50.0) * 0.2, 2)
        return replace(self, score=score, evidence=evidence)


@dataclass(frozen=True)
class EvaluationBatch:
    accepted: tuple[CandidateEvaluation, ...]
    rejected: tuple[CandidateEvaluation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, tuple) or not isinstance(self.rejected, tuple):
            raise TypeError("evaluation batch members must be tuples")
        if any(not isinstance(item, CandidateEvaluation)
               for item in (*self.accepted, *self.rejected)):
            raise TypeError("evaluation batch requires CandidateEvaluation values")
        if any(not item.accepted for item in self.accepted):
            raise ValueError("evaluation batch accepted partition is inconsistent")
        if any(item.accepted for item in self.rejected):
            raise ValueError("evaluation batch rejected partition is inconsistent")
        accepted_ids = {item.candidate.identity for item in self.accepted}
        rejected_ids = {item.candidate.identity for item in self.rejected}
        if accepted_ids & rejected_ids:
            raise ValueError("evaluation candidate cannot be both accepted and rejected")
