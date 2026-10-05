"""Byte acquisition and technical validation for normalized media assets.

This boundary knows provider asset metadata, the byte cache and ffprobe. It
does not know scenes, queries, relevance, fallback policy or reuse policy.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import functools
import os
import re
from dataclasses import dataclass
from typing import Literal

from .. import ffmpeg as ff
from ..media import download_asset
from ..media.providers import MediaAsset, MediaError, min_dimension


@dataclass(frozen=True)
class DownloadedMedia:
    """Downloaded/cached bytes and their acquisition provenance."""

    asset: MediaAsset
    origin: Literal["cache", "download"]


MAX_CONCURRENT_DOWNLOADS = int(
    os.environ.get("CURIO_MAX_CONCURRENT_DOWNLOADS", "2"))
DOWNLOAD_TIMEOUT = float(os.environ.get("CURIO_MEDIA_DOWNLOAD_TIMEOUT", "30.0"))
_DOWNLOAD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, MAX_CONCURRENT_DOWNLOADS),
    thread_name_prefix="curio-download")


def submit_download(asset: MediaAsset, cache_dir: str, metrics=None):
    """Submit byte acquisition while preserving run-log context."""
    context = contextvars.copy_context()
    return _DOWNLOAD_EXECUTOR.submit(context.run, _download_with_origin,
                                     asset, cache_dir, metrics)


def _download_with_origin(asset: MediaAsset, cache_dir: str,
                          metrics=None) -> DownloadedMedia:
    return download_media(asset, cache_dir, metrics)


def download_media(asset: MediaAsset, cache_dir: str,
                   metrics=None) -> DownloadedMedia:
    """Acquire one asset synchronously with an explicit cache origin."""
    from ..media.cache import _safe_ext
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", asset.asset_id) or "asset"
    path = os.path.join(cache_dir, "media", asset.provider,
                        safe_id + _safe_ext(asset.download_url))
    cached = os.path.isfile(path) and os.path.isfile(path + ".json")
    downloaded = download_asset(asset, cache_dir, metrics)
    return DownloadedMedia(downloaded, "cache" if cached else "download")


def probe_dimensions(path: str) -> tuple[int, int]:
    """Read image dimensions with a cache invalidated by file metadata."""
    try:
        stat = os.stat(path)
    except OSError:
        return 0, 0
    return _probe_dimensions_cached(path, stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=512)
def _probe_dimensions_cached(path: str, size: int,
                             mtime_ns: int) -> tuple[int, int]:
    _ = size, mtime_ns
    try:
        proc = ff.run([ff.FFPROBE, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height",
                       "-of", "csv=p=0", path])
        if proc.returncode == 0:
            width, height = proc.stdout.strip().split(",")[:2]
            return int(width), int(height)
    except (OSError, ValueError):
        pass
    return 0, 0


def downloaded_dimensions_valid(asset: MediaAsset) -> bool:
    """Validate the actual downloaded file and hydrate missing dimensions."""
    try:
        size = os.path.getsize(asset.local_path)
    except OSError:
        return False
    if size <= 10000:
        return False
    asset.size_bytes = max(asset.size_bytes, size)
    if asset.width > 0 and asset.height > 0:
        return True
    width, height = probe_dimensions(asset.local_path)
    if width <= 0 or height <= 0:
        return False
    asset.width, asset.height = width, height
    return min(width, height) >= min_dimension()
