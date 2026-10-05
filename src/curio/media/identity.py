"""Stable identity for acquired media, preferring content when available."""

from __future__ import annotations

import functools
import hashlib
import os
import urllib.parse


@functools.lru_cache(maxsize=1024)
def _file_sha256(path: str, size: int, mtime_ns: int) -> str:
    """Hash a local asset once per file version."""
    _ = size, mtime_ns
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_identity(asset: dict) -> str:
    """Return content identity, then canonical source URL, then provider ID."""
    path = str(asset.get("local_path") or "")
    if path:
        try:
            stat = os.stat(path)
            if os.path.isfile(path):
                return "sha256:" + _file_sha256(path, stat.st_size,
                                                 stat.st_mtime_ns)
        except OSError:
            pass

    source = str(asset.get("source_url") or "")
    if source:
        parsed = urllib.parse.urlsplit(source)
        canonical = urllib.parse.urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(),
             parsed.path.rstrip("/"), "", ""))
        if canonical:
            return "url:" + canonical

    if asset.get("asset_id"):
        return ((f"{asset['provider']}:" if asset.get("provider") else "")
                + str(asset["asset_id"]))
    return path
