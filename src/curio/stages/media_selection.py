"""Fresh-versus-reused ordering and explicit media selection decisions."""

from __future__ import annotations

from copy import deepcopy
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
        for field_name in ("asset_id", "provider", "query", "query_source",
                           "representation", "fallback_level", "reuse_reason",
                           "reason"):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"selection decision {field_name} must be text")
        if not self.fallback_level.strip():
            raise ValueError("selection decision must declare fallback level")
        if self.status == "none":
            if self.asset_id or self.provider or self.reuse_reason:
                raise ValueError("none selection cannot carry a selected asset")
        else:
            if not self.asset_id or not self.provider:
                raise ValueError("selected visual must include asset identity and provider")
        if self.status == "reused" and not self.reuse_reason.strip():
            raise ValueError("reused selection must explain reuse")
        if self.status != "reused" and self.reuse_reason:
            raise ValueError("only reused selection may carry reuse reason")
        if self.status == "synthetic" and self.provider != "synth":
            raise ValueError("synthetic selection must use synth provider")
        if self.status in {"real", "reused"} and self.provider == "synth":
            raise ValueError("real selection cannot use synth provider")
        if not self.reason.strip():
            raise ValueError("selection decision must explain its outcome")
        if self.score is not None and (
                isinstance(self.score, bool)
                or not isinstance(self.score, (int, float))
                or not isfinite(self.score) or not 0 <= self.score <= 100):
            raise ValueError("selection score must be finite and within 0..100")

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
        """Load persisted decisions; old records have unknown fallback level."""
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
        fallback_level = value.get("fallback_level") or "unknown"
        if not isinstance(fallback_level, str):
            raise TypeError("selection fallback_level must be text")
        return cls(
            scene_id=scene_id,
            status=str(value.get("status", "")),
            asset_id=str(value.get("asset_id", "")),
            provider=str(value.get("provider", "")),
            query=str(value.get("query", "")),
            query_source=str(value.get("query_source", "")),
            representation=str(value.get("representation", "")),
            score=score,
            fallback_level=fallback_level,
            reuse_reason=str(value.get("reuse_reason", "")),
            reason=str(value.get("reason", "")),
        )


@dataclass(frozen=True)
class ManualSwapResult:
    media_rows: list[dict]
    scene_id: int
    asset: dict
    previous_asset_id: str
    reused_from: int | None


def apply_manual_swap(media_rows: list[dict], scene_id: int,
                      pick: int) -> ManualSwapResult:
    """Apply a reviewer's choice and keep persisted selection provenance aligned."""
    if not isinstance(media_rows, list) or any(
            not isinstance(row, dict) for row in media_rows):
        raise TypeError("manual swap requires persisted media scene rows")
    if isinstance(scene_id, bool) or not isinstance(scene_id, int) or scene_id <= 0:
        raise ValueError("manual swap scene id must be positive")
    if isinstance(pick, bool) or not isinstance(pick, int) or pick < 0:
        raise ValueError("manual swap pick must be non-negative")
    ids = [row.get("chapter_id") for row in media_rows]
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
           for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("manual swap media scene ids must be unique positive integers")
    if ids.count(scene_id) != 1:
        raise LookupError(f"Cena {scene_id} não existe.")
    rows = deepcopy(media_rows)
    target = next(row for row in rows if row.get("chapter_id") == scene_id)
    entries = target.get("assets", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise TypeError("manual swap scene assets must be a list")
    if not entries:
        raise ValueError(f"Cena {scene_id} não tem imagens escolhidas para trocar.")
    if pick >= len(entries):
        raise IndexError(f"--pick fora da faixa: a cena tem {len(entries)} imagem(ns) "
                         f"(0..{len(entries) - 1}).")
    entry = entries[pick]
    if not isinstance(entry, dict):
        raise TypeError("manual swap entry must be an object")
    asset = entry.get("asset")
    if not isinstance(asset, dict):
        raise ValueError("A imagem escolhida não tem metadados válidos.")
    asset_id = asset.get("asset_id")
    provider = asset.get("provider")
    if not isinstance(asset_id, str) or not asset_id or \
            not isinstance(provider, str) or not provider:
        raise ValueError("A imagem escolhida não tem identidade de asset válida.")

    previous = target.get("asset") or {}
    previous_id = (previous.get("asset_id", "")
                   if isinstance(previous, dict) else "")
    from ..media.identity import asset_identity
    selected_identity = asset_identity(asset)
    donor = next((row for row in rows
                  if row.get("chapter_id") != scene_id
                  and isinstance(row.get("asset"), dict)
                  and selected_identity
                  and asset_identity(row["asset"]) == selected_identity), None)
    reused_from = donor.get("chapter_id") if donor else None
    updated_entry = deepcopy(entry)
    updated_entry["order"] = 0
    updated_entry.pop("reuse_reason", None)
    if reused_from:
        updated_entry["reuse_reason"] = "manually reused by reviewer"
    target["assets"] = [updated_entry] + [
        dict(deepcopy(other), order=index + 1)
        for index, other in enumerate(entries) if index != pick]
    target["asset"] = deepcopy(asset)
    if previous_id and previous_id != asset_id:
        target["swapped_from"] = previous_id
    if reused_from:
        target["reused_from"] = reused_from
    else:
        target.pop("reused_from", None)

    status = ("reused" if reused_from else
              "synthetic" if provider == "synth" else "real")
    score = updated_entry.get("score")
    if score is not None:
        score = float(score)
    decision = SelectionDecision(
        scene_id=scene_id, status=status, asset_id=asset_id, provider=provider,
        query=str(updated_entry.get("query", "") or ""),
        query_source=str(updated_entry.get("query_source", "") or ""),
        representation=str(updated_entry.get("representation", "") or ""),
        score=score, fallback_level="manual_review",
        reuse_reason=("manually reused by reviewer" if reused_from else ""),
        reason=("reviewer explicitly selected this visual" if not reused_from
                else "reviewer explicitly selected an asset already assigned to another scene"))
    audit = target.get("visual_decision") or {}
    if not isinstance(audit, dict):
        raise TypeError("manual swap visual decision must be an object")
    audit = deepcopy(audit)
    audit["selection"] = decision.to_dict()
    target["visual_decision"] = audit
    return ManualSwapResult(rows, scene_id, deepcopy(asset), previous_id,
                            reused_from)


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
