"""Data crossing provider, evaluation, and selection boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from ..media.providers import MediaAsset
from .visual_contracts import SearchQuery


@dataclass(frozen=True)
class Candidate:
    """One normalized provider result, linked to the exact query that found it."""

    asset: MediaAsset
    search_query: SearchQuery
    identity: str

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
