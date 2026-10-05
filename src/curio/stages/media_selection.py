"""Fresh-versus-reused ordering and explicit media selection decisions."""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import dataclass, replace
from math import isfinite
from typing import TYPE_CHECKING

from ..media.asset_snapshot import MediaAssetSnapshot
from .media_contracts import CandidateEvaluation
from .scene_contract import SemanticScene

if TYPE_CHECKING:
    from ..media.selection_result import MediaStageResult
    from ..media.selection_result import SelectedAsset


@dataclass(frozen=True)
class RankedSelectionCandidate:
    """Typed candidate state between evaluation, optional CLIP, and selection.

    The asset snapshot may include a local path prepared for CLIP; the mutable
    ``MediaAsset`` used by the download implementation never crosses this
    contract. JSON rows are projected only when the coordinator enters the
    remaining legacy acquisition loop.
    """

    evaluation: CandidateEvaluation
    asset: MediaAssetSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation, CandidateEvaluation):
            raise TypeError("ranked selection candidate requires CandidateEvaluation")
        if not self.evaluation.accepted:
            raise ValueError("ranked selection candidate must have passed evaluation")
        if not isinstance(self.asset, MediaAssetSnapshot):
            raise TypeError("ranked selection candidate requires an asset snapshot")

    @classmethod
    def from_evaluation(cls, evaluation: CandidateEvaluation
                        ) -> "RankedSelectionCandidate":
        if not isinstance(evaluation, CandidateEvaluation):
            raise TypeError("ranked selection requires CandidateEvaluation")
        return cls(evaluation, evaluation.candidate.asset)

    @property
    def score(self) -> float:
        return self.evaluation.score

    @property
    def generic(self) -> bool:
        return self.evaluation.candidate.search_query.generic

    @property
    def order(self) -> int:
        return self.evaluation.order

    @property
    def clip_score(self) -> float | None:
        value = self.evaluation.evidence.get("clip")
        return float(value) if value is not None else None

    def with_prepared_asset(self, asset: MediaAssetSnapshot
                            ) -> "RankedSelectionCandidate":
        return replace(self, asset=asset)

    def with_clip_score(self, clip_score: float, asset: MediaAssetSnapshot
                        ) -> "RankedSelectionCandidate":
        return replace(self,
                       evaluation=self.evaluation.with_clip_score(clip_score),
                       asset=asset)

    def to_selection_entry(self) -> dict:
        entry = self.evaluation.to_selection_entry()
        entry["asset"] = self.asset.to_dict()
        if self.clip_score is not None:
            entry["clip_score"] = self.clip_score
        return entry


@dataclass(frozen=True)
class SelectionPool:
    fresh: tuple[RankedSelectionCandidate, ...]
    reused: tuple[RankedSelectionCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fresh, tuple) or not isinstance(self.reused, tuple):
            raise TypeError("selection pool members must be tuples")
        if any(not isinstance(item, RankedSelectionCandidate)
               for item in (*self.fresh, *self.reused)):
            raise TypeError("selection pool requires ranked selection candidates")


@dataclass(frozen=True)
class ReuseCandidate:
    donor_scene_id: int
    entry: SelectedAsset
    topic_relevance: float
    scene_relevance: float

    def __post_init__(self) -> None:
        if (isinstance(self.donor_scene_id, bool)
                or not isinstance(self.donor_scene_id, int)
                or self.donor_scene_id <= 0):
            raise ValueError("reuse donor scene id must be positive")
        from ..media.selection_result import SelectedAsset
        if not isinstance(self.entry, SelectedAsset):
            raise TypeError("reuse candidate entry must be a SelectedAsset")
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
    from ..media.visual_decision import VisualDecision
    target["visual_decision"] = VisualDecision.create(
        decision, payload=audit).to_dict()
    return ManualSwapResult(rows, scene_id, deepcopy(asset), previous_id,
                            reused_from)


def prepare_selection_pool(ranked: list[RankedSelectionCandidate],
                           asset_uses: dict | None,
                           identity_of) -> SelectionPool:
    """Prefer fresh assets without modifying relevance scores or rank."""
    if any(not isinstance(item, RankedSelectionCandidate) for item in ranked):
        raise TypeError("selection pool requires ranked selection candidates")
    fresh, reused = [], []
    for entry in ranked:
        key = identity_of(entry.asset.to_dict())
        if asset_uses is not None and key and asset_uses.get(key, 0):
            reused.append(entry)
        else:
            fresh.append(entry)
    if asset_uses is not None:
        fresh.sort(key=lambda entry: (
            -entry.score, entry.generic,
            asset_uses.get(identity_of(entry.asset.to_dict()), 0)))
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


def make_selection_decision(scene_id: int, picked: list["SelectedAsset"],
                            fallback_level: str) -> SelectionDecision:
    """Describe the chosen result after downloads/fallback policy complete."""
    from ..media.selection_result import SelectedAsset

    if not isinstance(picked, list) or any(
            not isinstance(entry, SelectedAsset) for entry in picked):
        raise TypeError("selection decision requires SelectedAsset values")
    if not picked:
        return SelectionDecision(
            scene_id, "none", fallback_level=fallback_level,
            reason="no candidate downloaded and no visual fallback was produced")
    entry = picked[0]
    asset = entry.asset
    provider = asset.provider
    status = ("synthetic" if provider == "synth" else
              "reused" if entry.reuse_reason else "real")
    if status == "synthetic":
        reason = "no eligible fresh real asset remained; semantic synthetic fallback selected"
    elif status == "reused":
        reason = "all fresh searches and local visual fallbacks were exhausted before reuse"
    else:
        reason = "fresh candidate passed gates, ranked for the scene, and downloaded"
    return SelectionDecision(
        scene_id=scene_id,
        status=status,
        asset_id=asset.asset_id,
        provider=provider,
        query=entry.query,
        query_source=entry.query_source,
        representation=entry.representation,
        score=entry.score,
        fallback_level=fallback_level,
        reuse_reason=entry.reuse_reason,
        reason=reason,
    )


def annotate_reuse(result: MediaStageResult) -> MediaStageResult:
    """Return a validated selection result with repeated identities annotated."""
    from ..media.selection_result import MediaStageResult
    from ..media.identity import asset_identity

    if not isinstance(result, MediaStageResult):
        raise TypeError("reuse annotation requires a MediaStageResult")
    first_scene: dict[str, int] = {}
    updated_scenes = []
    for scene in result.scenes:
        reuse = []
        for entry in scene.assets:
            asset = entry.asset
            if not asset.asset_id:
                continue
            identity = asset_identity(asset.to_dict())
            if identity in first_scene:
                reuse.append({
                    "asset": asset.asset_id,
                    "title": asset.title[:120],
                    "provider": asset.provider,
                    "previous_scene": first_scene[identity],
                    "current_scene": scene.scene_id,
                    "reason": entry.reuse_reason or "same_top_match",
                })
            else:
                first_scene[identity] = scene.scene_id
        updated_scenes.append(scene.with_reuse_audit(reuse))
    return MediaStageResult(tuple(updated_scenes), result.source, result.warnings)


def resolve_cross_scene_reuse(
        result: MediaStageResult,
        semantic_scenes: list[SemanticScene]) -> MediaStageResult:
    """Fill empty scenes only from a semantically qualified selected asset."""
    from ..media.selection_result import MediaStageResult, SelectedAsset

    if not isinstance(result, MediaStageResult):
        raise TypeError("cross-scene reuse requires a MediaStageResult")
    have = [scene for scene in result.scenes if scene.assets]
    by_id = {scene.id: scene for scene in semantic_scenes}
    if not have or not by_id:
        return result
    from . import scoring

    updated_scenes = []
    for scene_row in result.scenes:
        if scene_row.assets:
            updated_scenes.append(scene_row)
            continue
        scene_id = scene_row.scene_id
        scene = by_id.get(scene_id)
        if scene is None:
            updated_scenes.append(scene_row)
            continue
        eligible: list[ReuseCandidate] = []
        for donor in have:
            donor_scene = by_id.get(donor.scene_id)
            if donor_scene is None:
                continue
            for entry in donor.assets:
                asset = entry.asset.to_dict()
                relevance = scoring.semantic_relevance(asset, scene)
                if ((relevance.get("topic_relevance", 0) or 0) > 0
                        and (relevance.get("scene_relevance", 0) or 0) >= 25):
                    eligible.append(ReuseCandidate(
                        donor_scene_id=donor.scene_id, entry=entry,
                        topic_relevance=relevance["topic_relevance"],
                        scene_relevance=relevance["scene_relevance"]))
        selected = select_reuse_candidate(eligible, scene_id)
        if selected is None:
            updated_scenes.append(scene_row)
            continue
        donor_entry = selected.entry.to_dict()
        donor_row = next(item for item in have
                         if item.scene_id == selected.donor_scene_id)
        reuse_reason = "validated_cross_scene_reuse"
        reused_entry = dict(donor_entry, order=0,
                            reuse_reason=reuse_reason)
        reused_asset = SelectedAsset.from_dict(reused_entry, 0)
        decision = make_selection_decision(
            scene_id, [reused_asset], "validated_reuse")
        decision = replace(
            decision,
            reason=("validated topic and scene evidence; reused from scene "
                    f"{donor_row.scene_id} after fresh and synthetic choices"))
        updated_scenes.append(scene_row.with_cross_scene_reuse(
            reused_asset, donor_row.scene_id, decision,
            selected.topic_relevance, selected.scene_relevance))
        print(f"AVISO: cena {scene_id} reusa imagem(ns) da cena "
              f"{donor_row.scene_id} (sem mídia própria).", file=sys.stderr)
    return MediaStageResult(tuple(updated_scenes), result.source, result.warnings)
