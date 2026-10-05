"""Data crossing provider, evaluation, and selection boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from ..media.providers import MediaAsset
from .visual_contracts import SearchQuery


@dataclass(frozen=True)
class ProviderAssetSnapshot:
    """Immutable provider facts retained by a Candidate.

    ``MediaAsset`` remains mutable for download/cache enrichment. A candidate
    captures the provider response at the acquisition boundary so later
    mutations to either object cannot rewrite the evidence that was evaluated.
    """

    provider: str
    asset_id: str
    title: str = ""
    author: str = ""
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    download_url: str = ""
    download_fallback_url: str = ""
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    kind: str = "image"
    local_path: str = ""
    used_in: str = ""
    rights_status: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    date_created: str = ""
    media_type: str = "image"

    @classmethod
    def from_media_asset(cls, asset: MediaAsset) -> "ProviderAssetSnapshot":
        if not isinstance(asset, MediaAsset):
            raise TypeError("provider asset snapshot requires MediaAsset")
        return cls(
            provider=asset.provider, asset_id=asset.asset_id,
            title=asset.title, author=asset.author, license=asset.license,
            license_url=asset.license_url, source_url=asset.source_url,
            download_url=asset.download_url,
            download_fallback_url=asset.download_fallback_url,
            width=asset.width, height=asset.height, size_bytes=asset.size_bytes,
            kind=asset.kind, local_path=asset.local_path, used_in=asset.used_in,
            rights_status=asset.rights_status, description=asset.description,
            tags=tuple(asset.tags), categories=tuple(asset.categories),
            date_created=asset.date_created, media_type=asset.media_type)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not isinstance(self.asset_id, str):
            raise TypeError("provider asset identity must be text")
        for name in ("tags", "categories"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(
                    not isinstance(item, str) for item in value):
                raise TypeError(f"provider asset {name} must be immutable text")

    def to_dict(self) -> dict:
        """Project the same JSON fields as MediaAsset for existing consumers."""
        return {
            "provider": self.provider, "asset_id": self.asset_id,
            "title": self.title, "author": self.author,
            "license": self.license, "license_url": self.license_url,
            "source_url": self.source_url, "download_url": self.download_url,
            "download_fallback_url": self.download_fallback_url,
            "width": self.width, "height": self.height,
            "size_bytes": self.size_bytes, "kind": self.kind,
            "local_path": self.local_path, "used_in": self.used_in,
            "rights_status": self.rights_status,
            "description": self.description, "tags": list(self.tags),
            "categories": list(self.categories),
            "date_created": self.date_created, "media_type": self.media_type,
        }


@dataclass(frozen=True)
class Candidate:
    """One normalized provider result, linked to the exact query that found it."""

    asset: ProviderAssetSnapshot
    search_query: SearchQuery
    identity: str

    def __post_init__(self) -> None:
        if isinstance(self.asset, MediaAsset):
            object.__setattr__(self, "asset",
                               ProviderAssetSnapshot.from_media_asset(self.asset))
        if not isinstance(self.asset, ProviderAssetSnapshot):
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
        entry["score_detail"] = dict(self.evidence)
        entry["order"] = self.order
        if self.rejection_reason:
            entry["rejection_reason"] = self.rejection_reason
        return entry


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
