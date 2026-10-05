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

from ..media.asset_snapshot import MediaAssetSnapshot
from ..media.identity import asset_identity
from ..media.providers import MediaAsset, MediaError, classify_rights
from . import media_acquisition
from .media_acquisition_contracts import CandidateAcquisitionOutcome
from .media_selection import RankedSelectionCandidate, record_asset_usage
from .visual_beats import asset_key


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
        cache_dir: str, metrics=None, asset_uses: dict | None = None
        ) -> CandidateAcquisitionBatch:
    """Try fresh ranked candidates until enough usable, unique assets exist."""
    if any(not isinstance(item, RankedSelectionCandidate) for item in ranked):
        raise TypeError("candidate acquisition requires ranked candidates")
    if isinstance(scene_id, bool) or not isinstance(scene_id, int) or scene_id <= 0:
        raise ValueError("candidate acquisition requires a positive scene id")
    if isinstance(max_images, bool) or not isinstance(max_images, int) or max_images <= 0:
        raise ValueError("candidate acquisition requires a positive image limit")

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
        asset = MediaAsset.from_dict(asset_data)
        local = asset.local_path
        acquisition = "cache" if local and os.path.isfile(local) else "download"
        if not (local and os.path.isfile(local)):
            future = download_futures.pop(rank_index, None)
            try:
                if future is None:
                    future = media_acquisition.submit_download(
                        asset, cache_dir, metrics)
                downloaded = future.result(
                    timeout=media_acquisition.DOWNLOAD_TIMEOUT)
                asset, acquisition = downloaded.asset, downloaded.origin
                fill_download_window()
            except (MediaError, concurrent.futures.TimeoutError) as exc:
                if future is not None:
                    future.cancel()
                fill_download_window()
                outcome = CandidateAcquisitionOutcome(
                    candidate=candidate,
                    asset=MediaAssetSnapshot.from_media_asset(asset),
                    disposition="download_failed", rejection_stage="download",
                    reason=f"download failed: {exc}")
                outcomes.append(outcome)
                message = f"cena {scene_id}: download falhou ({exc})"
                warnings.append(message)
                from ..runlog import event as run_event
                logged = run_event("warning", message, operation="media_download",
                                   scene=scene_id, provider=asset.provider,
                                   error=str(exc))
                if not logged:
                    print(f"AVISO: {message}", file=sys.stderr)
                if metrics:
                    metrics.media_record_funnel("download_failed")
                continue
        if not media_acquisition.downloaded_dimensions_valid(asset):
            message = (f"cena {scene_id}: '{asset.title[:50]}' rejeitado após "
                       f"download (resolução insuficiente ou ilegível)")
            warnings.append(message)
            outcomes.append(CandidateAcquisitionOutcome(
                candidate=candidate,
                asset=MediaAssetSnapshot.from_media_asset(asset),
                disposition="invalid_dimensions", origin=acquisition,
                rejection_stage="dimensions",
                reason="resolução/legibilidade após download"))
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
            selected_order=selected_count,
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
        asset = MediaAsset.from_dict(candidate.asset.to_dict())
        try:
            if not (asset.local_path and os.path.isfile(asset.local_path)):
                downloaded = media_acquisition.submit_download(
                    asset, cache_dir, metrics).result(
                        timeout=media_acquisition.DOWNLOAD_TIMEOUT)
                asset, origin = downloaded.asset, downloaded.origin
            else:
                origin = "cache"
        except (MediaError, concurrent.futures.TimeoutError):
            continue
        if not media_acquisition.downloaded_dimensions_valid(asset):
            continue
        asset.used_in = f"cena {scene_id}"
        selected_asset = MediaAssetSnapshot.from_media_asset(asset)
        identity = asset_identity(selected_asset.to_dict())
        record_asset_usage(asset_uses, candidate.asset.to_dict(),
                           selected_asset.to_dict(), asset_identity)
        if metrics:
            metrics.media_record_funnel("reused_fallback")
        return CandidateAcquisitionOutcome(
            candidate=candidate, asset=selected_asset, disposition="selected",
            origin=origin, content_identity=identity, selected_order=0,
            reuse_reason="fresh_search_and_synthetic_exhausted")
    return None
