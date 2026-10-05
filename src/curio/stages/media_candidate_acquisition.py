"""Acquire ranked scene candidates and return explicit per-candidate outcomes.

This coordinator owns the attempt window and post-download gates. Provider
adapters only normalize results; media_acquisition owns bytes and technical
validation; editorial fallback ordering stays in ``visual.py``.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
from dataclasses import dataclass
from typing import Literal

from ..media.asset_snapshot import MediaAssetSnapshot
from ..media.identity import asset_identity
from ..media.providers import MediaAsset, MediaError, classify_rights
from . import media_acquisition
from .media_acquisition_contracts import CandidateAcquisitionOutcome
from .media_selection import RankedSelectionCandidate, record_asset_usage
from .visual_beats import asset_key


@dataclass(frozen=True)
class TechnicalAcquisitionAttempt:
    """Technical download/dimension result shared by fresh and reuse paths."""

    asset: MediaAssetSnapshot
    disposition: Literal["ready", "download_failed", "invalid_dimensions"]
    origin: Literal["cache", "download"] | None = None
    error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.asset, MediaAssetSnapshot):
            raise TypeError("technical acquisition requires an asset snapshot")
        if self.disposition not in {
                "ready", "download_failed", "invalid_dimensions"}:
            raise ValueError("unknown technical acquisition disposition")
        if self.origin not in {None, "cache", "download"}:
            raise ValueError("unknown technical acquisition origin")
        if not isinstance(self.error, str):
            raise TypeError("technical acquisition error must be text")
        if self.disposition == "ready":
            if self.origin not in {"cache", "download"} or self.error:
                raise ValueError("ready acquisition requires origin and no error")
        elif self.disposition == "download_failed":
            if self.origin is not None or not self.error.strip():
                raise ValueError("download failure requires an error and no origin")
        elif self.origin not in {"cache", "download"} or not self.error.strip():
            raise ValueError("invalid dimensions requires origin and reason")


def _acquire_and_validate(
        candidate: RankedSelectionCandidate, cache_dir: str, metrics=None,
        future: concurrent.futures.Future | None = None
        ) -> TechnicalAcquisitionAttempt:
    """Share byte acquisition and dimension validation across selection paths."""
    asset = MediaAsset.from_dict(candidate.asset.to_dict())
    if asset.local_path and os.path.isfile(asset.local_path):
        origin = "cache"
    else:
        try:
            if future is None:
                future = media_acquisition.submit_download(
                    asset, cache_dir, metrics)
            downloaded = future.result(timeout=media_acquisition.DOWNLOAD_TIMEOUT)
        except (MediaError, concurrent.futures.TimeoutError) as exc:
            if future is not None:
                future.cancel()
            return TechnicalAcquisitionAttempt(
                MediaAssetSnapshot.from_media_asset(asset), "download_failed",
                error=str(exc))
        asset, origin = downloaded.asset, downloaded.origin

    if not media_acquisition.downloaded_dimensions_valid(asset):
        return TechnicalAcquisitionAttempt(
            MediaAssetSnapshot.from_media_asset(asset), "invalid_dimensions",
            origin=origin, error="resolução/legibilidade após download")
    return TechnicalAcquisitionAttempt(
        MediaAssetSnapshot.from_media_asset(asset), "ready", origin=origin)


@dataclass(frozen=True)
class CandidateAcquisitionBatch:
    """Immutable ordered outcomes from one fresh-candidate attempt batch."""

    outcomes: tuple[CandidateAcquisitionOutcome, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.outcomes, tuple) or any(
                not isinstance(outcome, CandidateAcquisitionOutcome)
                for outcome in self.outcomes):
            raise TypeError("candidate acquisition outcomes must be an immutable tuple")
        if not isinstance(self.warnings, tuple) or any(
                not isinstance(message, str) for message in self.warnings):
            raise TypeError("candidate acquisition warnings must be an immutable text tuple")

    @property
    def selected(self) -> tuple[CandidateAcquisitionOutcome, ...]:
        return tuple(item for item in self.outcomes
                     if item.disposition == "selected")

    @property
    def rejected(self) -> tuple[CandidateAcquisitionOutcome, ...]:
        return tuple(item for item in self.outcomes
                     if item.disposition != "selected")


def acquire_ranked_candidates(
        scene_id: int, ranked: list[RankedSelectionCandidate], max_images: int,
        cache_dir: str, metrics=None, asset_uses: dict | None = None,
        selected_order_start: int = 0,
        ) -> CandidateAcquisitionBatch:
    """Try fresh ranked candidates until enough usable, unique assets exist."""
    if any(not isinstance(item, RankedSelectionCandidate) for item in ranked):
        raise TypeError("candidate acquisition requires ranked candidates")
    if isinstance(scene_id, bool) or not isinstance(scene_id, int) or scene_id <= 0:
        raise ValueError("candidate acquisition requires a positive scene id")
    if isinstance(max_images, bool) or not isinstance(max_images, int) or max_images <= 0:
        raise ValueError("candidate acquisition requires a positive image limit")
    if (isinstance(selected_order_start, bool)
            or not isinstance(selected_order_start, int)
            or selected_order_start < 0):
        raise ValueError("candidate acquisition order offset must be non-negative")

    outcomes: list[CandidateAcquisitionOutcome] = []
    warnings: list[str] = []
    scene_content_seen: set[str] = set()
    selected_count = 0
    download_window = min(max(1, media_acquisition.MAX_CONCURRENT_DOWNLOADS),
                          max(1, max_images))
    download_futures: dict[int, object] = {}
    next_download = 0

    def fill_download_window() -> None:
        nonlocal next_download
        while len(download_futures) < download_window and next_download < len(ranked):
            index = next_download
            next_download += 1
            asset = MediaAsset.from_dict(ranked[index].asset.to_dict())
            if asset.local_path and os.path.isfile(asset.local_path):
                continue
            download_futures[index] = media_acquisition.submit_download(
                asset, cache_dir, metrics)

    fill_download_window()
    for rank_index, candidate in enumerate(ranked):
        if selected_count >= max_images:
            break
        asset_data = candidate.asset.to_dict()
        if metrics:
            metrics.media_record_funnel("selected")
            metrics.media_shortlist_ids.add(asset_key(asset_data))
        had_local_asset = bool(asset_data.get("local_path")
                               and os.path.isfile(asset_data["local_path"]))
        future = (None if had_local_asset
                  else download_futures.pop(rank_index, None))
        attempt = _acquire_and_validate(candidate, cache_dir, metrics, future)
        if not had_local_asset:
            fill_download_window()
        asset = MediaAsset.from_dict(attempt.asset.to_dict())
        if attempt.disposition == "download_failed":
            outcome = CandidateAcquisitionOutcome(
                candidate=candidate, asset=attempt.asset,
                disposition="download_failed", rejection_stage="download",
                reason=f"download failed: {attempt.error}")
            outcomes.append(outcome)
            message = f"cena {scene_id}: download falhou ({attempt.error})"
            warnings.append(message)
            from ..runlog import event as run_event
            logged = run_event("warning", message, operation="media_download",
                               scene=scene_id, provider=asset.provider,
                               error=attempt.error)
            if not logged:
                print(f"AVISO: {message}", file=sys.stderr)
            if metrics:
                metrics.media_record_funnel("download_failed")
            continue
        acquisition = attempt.origin
        if attempt.disposition == "invalid_dimensions":
            message = (f"cena {scene_id}: '{asset.title[:50]}' rejeitado após "
                       f"download (resolução insuficiente ou ilegível)")
            warnings.append(message)
            outcomes.append(CandidateAcquisitionOutcome(
                candidate=candidate, asset=attempt.asset,
                disposition="invalid_dimensions", origin=attempt.origin,
                rejection_stage="dimensions",
                reason=attempt.error))
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_rejection("resolução/legibilidade após download")
                metrics.media_record_funnel("post_download_rejected")
            continue
        content_key = asset_identity(asset.to_dict())
        if (content_key.startswith("sha256:")
                and (content_key in scene_content_seen
                     or (asset_uses is not None
                         and asset_uses.get(content_key, 0)))):
            record_asset_usage(asset_uses, asset_data, asset.to_dict(),
                               asset_identity, increment=False)
            outcomes.append(CandidateAcquisitionOutcome(
                candidate=candidate,
                asset=MediaAssetSnapshot.from_media_asset(asset),
                disposition="duplicate_content", origin=acquisition,
                rejection_stage="duplicate_content",
                reason="duplicate content hash", content_identity=content_key))
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_rejection("duplicate content hash")
                metrics.media_record_funnel("duplicate_content_hash")
            continue

        asset.used_in = f"cena {scene_id}"
        if not asset.rights_status:
            asset.rights_status = classify_rights(asset.license or "",
                                                  asset.provider)
        if asset.rights_status == "verify":
            if metrics:
                metrics.media_record_rights("verify")
            message = (f"cena {scene_id}: licença a conferir manualmente "
                       f"({asset.provider}: {asset.license or 'desconhecida'}) — "
                       f"{asset.license_url or asset.source_url or 'sem link'}")
            warnings.append(message)
            from ..runlog import event as run_event
            logged = run_event("warning", message, operation="media_rights",
                               scene=scene_id, provider=asset.provider,
                               rights_status="verify")
            if not logged:
                print(f"AVISO: {message}", file=sys.stderr)
        if candidate.generic and metrics:
            metrics.media_record_funnel("generic_used")
        if metrics:
            metrics.media_record_score(candidate.score)
        if content_key.startswith("sha256:"):
            scene_content_seen.add(content_key)
        selected_asset = MediaAssetSnapshot.from_media_asset(asset)
        reuse_reason = ""
        if asset_uses is not None:
            key = asset_identity(selected_asset.to_dict())
            if asset_uses.get(key, 0):
                reuse_reason = "eligible_pool_exhausted"
            record_asset_usage(asset_uses, asset_data, selected_asset.to_dict(),
                               asset_identity)
        outcomes.append(CandidateAcquisitionOutcome(
            candidate=candidate, asset=selected_asset, disposition="selected",
            origin=acquisition, content_identity=content_key,
            selected_order=selected_order_start + selected_count,
            reuse_reason=reuse_reason))
        selected_count += 1
        if metrics:
            metrics.media_record_funnel("used_real")
    return CandidateAcquisitionBatch(tuple(outcomes), tuple(warnings))


def acquire_reuse_fallback(
        scene_id: int, candidates: list[RankedSelectionCandidate], cache_dir: str,
        metrics=None, asset_uses: dict | None = None
        ) -> CandidateAcquisitionOutcome | None:
    """Acquire the first eligible reused asset after editorial fallback ran."""
    if any(not isinstance(item, RankedSelectionCandidate) for item in candidates):
        raise TypeError("reuse acquisition requires ranked candidates")
    for candidate in sorted(candidates, key=lambda item: -item.score):
        attempt = _acquire_and_validate(candidate, cache_dir, metrics)
        if attempt.disposition != "ready":
            continue
        asset = MediaAsset.from_dict(attempt.asset.to_dict())
        asset.used_in = f"cena {scene_id}"
        selected_asset = MediaAssetSnapshot.from_media_asset(asset)
        identity = asset_identity(selected_asset.to_dict())
        record_asset_usage(asset_uses, candidate.asset.to_dict(),
                           selected_asset.to_dict(), asset_identity)
        if metrics:
            metrics.media_record_funnel("reused_fallback")
        return CandidateAcquisitionOutcome(
            candidate=candidate, asset=selected_asset, disposition="selected",
            origin=attempt.origin, content_identity=identity, selected_order=0,
            reuse_reason="fresh_search_and_synthetic_exhausted")
    return None
