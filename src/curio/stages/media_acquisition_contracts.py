"""Typed outcomes for acquiring one ranked scene candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..media.asset_snapshot import MediaAssetSnapshot
from .media_selection import RankedSelectionCandidate

if TYPE_CHECKING:
    from ..media.selection_result import SelectedAsset


AcquisitionDisposition = Literal[
    "selected", "download_failed", "invalid_dimensions", "duplicate_content"]
AcquisitionStage = Literal["download", "dimensions", "duplicate_content"]
AcquisitionOrigin = Literal["cache", "download"]


@dataclass(frozen=True)
class CandidateAcquisitionOutcome:
    """Immutable result of one attempted ranked-candidate acquisition.

    The candidate preserves provider/query/score provenance. ``asset`` is the
    provider snapshot after any technical acquisition updates. Rejected and
    selected states have disjoint required fields and serialize only at an
    audit or selected-media boundary.
    """

    candidate: RankedSelectionCandidate
    asset: MediaAssetSnapshot
    disposition: AcquisitionDisposition
    origin: AcquisitionOrigin | None = None
    rejection_stage: AcquisitionStage | None = None
    reason: str = ""
    content_identity: str = ""
    selected_order: int | None = None
    reuse_reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, RankedSelectionCandidate):
            raise TypeError("acquisition outcome requires RankedSelectionCandidate")
        if not isinstance(self.asset, MediaAssetSnapshot):
            raise TypeError("acquisition outcome requires MediaAssetSnapshot")
        if self.disposition not in {
                "selected", "download_failed", "invalid_dimensions",
                "duplicate_content"}:
            raise ValueError("unknown candidate acquisition disposition")
        if self.origin not in {None, "cache", "download"}:
            raise ValueError("unknown candidate acquisition origin")
        for name in ("reason", "content_identity", "reuse_reason"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"candidate acquisition {name} must be text")
        if self.disposition == "selected":
            if self.origin not in {"cache", "download"}:
                raise ValueError("selected candidate requires acquisition origin")
            if (isinstance(self.selected_order, bool)
                    or not isinstance(self.selected_order, int)
                    or self.selected_order < 0):
                raise ValueError("selected candidate requires non-negative order")
            if self.rejection_stage is not None or self.reason:
                raise ValueError("selected candidate cannot carry rejection state")
            if not self.content_identity.strip():
                raise ValueError("selected candidate requires content identity")
        else:
            if not self.reason.strip():
                raise ValueError("rejected candidate requires a reason")
            if self.selected_order is not None or self.reuse_reason:
                raise ValueError("rejected candidate cannot carry selection state")
            if self.rejection_stage not in {
                    "download", "dimensions", "duplicate_content"}:
                raise ValueError("rejected candidate requires a known rejection stage")
        if (self.disposition == "download_failed"
                and self.rejection_stage != "download"):
            raise ValueError("download failure requires download stage")
        if (self.disposition == "invalid_dimensions"
                and self.rejection_stage != "dimensions"):
            raise ValueError("invalid dimensions requires dimensions stage")
        if self.disposition in {"invalid_dimensions", "duplicate_content"} \
                and self.origin not in {"cache", "download"}:
            raise ValueError("post-download rejection requires acquisition origin")
        if self.disposition == "duplicate_content":
            if self.rejection_stage != "duplicate_content":
                raise ValueError("duplicate content requires duplicate stage")
            if not self.content_identity.startswith("sha256:"):
                raise ValueError("duplicate content requires a sha256 identity")

    def to_selected_asset(self) -> "SelectedAsset":
        """Project a successful outcome into the validated selected-asset type."""
        if self.disposition != "selected":
            raise ValueError("rejected candidate has no selected asset")
        from ..media.selection_result import SelectedAsset

        row = self.candidate.to_selection_entry()
        row.update({
            "asset": self.asset.to_dict(),
            "order": self.selected_order,
            "acquisition": self.origin,
        })
        if self.reuse_reason:
            row["reuse_reason"] = self.reuse_reason
        return SelectedAsset.from_dict(row, self.selected_order or 0)

    def to_rejection_row(self) -> dict:
        """Project technical rejection with candidate identity for audit joining."""
        if self.disposition == "selected":
            raise ValueError("selected candidate has no rejection row")
        row = {
            "title": self.asset.title,
            "query": self.candidate.evaluation.candidate.search_query.query,
            "reason": self.reason,
            "provider": self.asset.provider,
            "identity": self.candidate.evaluation.candidate.identity,
        }
        if self.disposition == "invalid_dimensions":
            row["audit_reason"] = "resolution/legibility after download"
        if self.content_identity:
            row["content_identity"] = self.content_identity
        return row
