"""Fresh-versus-reused ordering and explicit media selection decisions."""

from __future__ import annotations

from math import isfinite
from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionPool:
    fresh: tuple[dict, ...]
    reused: tuple[dict, ...]


@dataclass(frozen=True)
class ReuseCandidate:
    donor_scene_id: int
    entry: dict
    topic_relevance: float
    scene_relevance: float

    def __post_init__(self) -> None:
        if (isinstance(self.donor_scene_id, bool)
                or not isinstance(self.donor_scene_id, int)
                or self.donor_scene_id <= 0):
            raise ValueError("reuse donor scene id must be positive")
        if not isinstance(self.entry, dict):
            raise TypeError("reuse candidate entry must be an object")
        for value in (self.topic_relevance, self.scene_relevance):
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not isfinite(value):
                raise ValueError("reuse relevance must be finite")


@dataclass(frozen=True)
class SelectionDecision:
    scene_id: int
    status: str
    asset_id: str = ""
    provider: str = ""
    query: str = ""
    query_source: str = ""
    representation: str = ""
    score: float | None = None
    fallback_level: str = ""
    reuse_reason: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if (isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int)
                or self.scene_id <= 0):
            raise ValueError("selection decision scene_id must be positive")
        if self.status not in {"real", "reused", "synthetic", "none"}:
            raise ValueError(f"unknown selection status: {self.status}")
        if self.status != "none" and not self.asset_id:
            raise ValueError("selected visual must include asset identity")
        if not self.reason.strip():
            raise ValueError("selection decision must explain its outcome")
        if self.score is not None and not isfinite(self.score):
            raise ValueError("selection score must be finite")

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "status": self.status,
            "asset_id": self.asset_id,
            "provider": self.provider,
            "query": self.query,
            "query_source": self.query_source,
            "representation": self.representation,
            "score": self.score,
            "fallback_level": self.fallback_level,
            "reuse_reason": self.reuse_reason,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "SelectionDecision":
        """Validate the persisted decision at a consumer boundary."""
        if not isinstance(value, dict):
            raise TypeError("selection decision must be an object")
        scene_id = value.get("scene_id")
        if isinstance(scene_id, bool) or not isinstance(scene_id, int):
            raise ValueError("selection decision scene_id must be an integer")
        score = value.get("score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError) as exc:
                raise ValueError("selection score must be numeric or null") from exc
        return cls(
            scene_id=scene_id,
            status=str(value.get("status", "")),
            asset_id=str(value.get("asset_id", "")),
            provider=str(value.get("provider", "")),
            query=str(value.get("query", "")),
            query_source=str(value.get("query_source", "")),
            representation=str(value.get("representation", "")),
            score=score,
            fallback_level=str(value.get("fallback_level", "")),
            reuse_reason=str(value.get("reuse_reason", "")),
            reason=str(value.get("reason", "")),
        )


def prepare_selection_pool(ranked: list[dict], asset_uses: dict | None,
                           identity_of) -> SelectionPool:
    """Prefer fresh assets without modifying relevance scores or rank."""
    fresh, reused = [], []
    for entry in ranked:
        key = identity_of(entry["asset"])
        if asset_uses is not None and key and asset_uses.get(key, 0):
            reused.append(entry)
        else:
            fresh.append(entry)
    if asset_uses is not None:
        fresh.sort(key=lambda entry: (
            -entry.get("score", 0), bool(entry.get("generic")),
            asset_uses.get(identity_of(entry["asset"]), 0)))
    return SelectionPool(tuple(fresh), tuple(reused))


def record_asset_usage(asset_uses: dict[str, int] | None,
                       searched_asset: dict, acquired_asset: dict,
                       identity_of, *, increment: bool = True) -> None:
    """Keep provisional provider identity linked to acquired content identity.

    Before download an asset is identified by source URL or provider ID; after
    download its SHA-256 becomes canonical. Both identities must reflect the
    same cross-scene usage so search does not mistake a known asset for a new
    candidate and short-circuit before trying another representation.
    """
    if asset_uses is None:
        return
    keys = {key for key in (identity_of(searched_asset),
                            identity_of(acquired_asset)) if key}
    if not keys:
        return
    previous = max((asset_uses.get(key, 0) for key in keys), default=0)
    usage = previous + 1 if increment else previous
    for key in keys:
        asset_uses[key] = max(asset_uses.get(key, 0), usage)


def select_reuse_candidate(candidates: list[ReuseCandidate],
                           scene_id: int) -> ReuseCandidate | None:
    """Pick the strongest relevant donor, then the nearest earlier scene."""
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: (
        -candidate.scene_relevance,
        abs(candidate.donor_scene_id - scene_id),
        0 if candidate.donor_scene_id < scene_id else 1))


def make_selection_decision(scene_id: int, picked: list[dict],
                            fallback_level: str) -> SelectionDecision:
    """Describe the chosen result after downloads/fallback policy complete."""
    if not picked:
        return SelectionDecision(
            scene_id, "none", fallback_level=fallback_level,
            reason="no candidate downloaded and no visual fallback was produced")
    entry = picked[0]
    asset = entry.get("asset") or {}
    provider = str(asset.get("provider", ""))
    status = ("synthetic" if provider == "synth" else
              "reused" if entry.get("reuse_reason") else "real")
    if status == "synthetic":
        reason = "no eligible fresh real asset remained; semantic synthetic fallback selected"
    elif status == "reused":
        reason = "all fresh searches and local visual fallbacks were exhausted before reuse"
    else:
        reason = "fresh candidate passed gates, ranked for the scene, and downloaded"
    return SelectionDecision(
        scene_id=scene_id,
        status=status,
        asset_id=str(asset.get("asset_id", "")),
        provider=provider,
        query=str(entry.get("query", "")),
        query_source=str(entry.get("query_source", "")),
        representation=str(entry.get("representation", "")),
        score=float(entry["score"]) if entry.get("score") is not None else None,
        fallback_level=fallback_level,
        reuse_reason=str(entry.get("reuse_reason", "")),
        reason=reason,
    )
