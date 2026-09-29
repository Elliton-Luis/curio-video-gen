"""Cache local de mídia (§12).

`cache/media/<provider>/<asset_id>.<ext>` + sidecar `.json` com proveniência.
Nunca baixa duas vezes: arquivo + sidecar existentes = reuso.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .providers import TIMEOUT, USER_AGENT, MediaAsset, MediaError

RETRIES = 3


def _fetch(url: str) -> bytes:
    """GET com retry + backoff em 429/5xx (cortesia com o provedor)."""
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429 and not 500 <= exc.code < 600:
                break
        except Exception as exc:  # noqa: BLE001 — 1 retry em erro genérico
            last = exc
            if attempt >= 1:
                break
        time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise last


def _safe_ext(url: str) -> str:
    m = re.search(r"\.(jpe?g|png|webp)(?:\?|$)", url, re.I)
    return "." + m.group(1).lower().replace("jpeg", "jpg") if m else ".jpg"


def download_asset(asset: MediaAsset, cache_dir: str,
                   metrics=None) -> MediaAsset:
    dest_dir = os.path.join(cache_dir, "media", asset.provider)
    os.makedirs(dest_dir, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", asset.asset_id) or "asset"
    dest = os.path.join(dest_dir, safe_id + _safe_ext(asset.download_url))
    sidecar = dest + ".json"
    if os.path.isfile(dest) and os.path.isfile(sidecar):
        asset.local_path = dest
        if metrics is not None:
            metrics.media_download(0, True)
        return asset  # cache: zero downloads repetidos
    try:
        data = _fetch(asset.download_url)
    except Exception as first_exc:
        if not asset.download_fallback_url:
            raise MediaError(
                f"{asset.provider}: download falhou ({asset.asset_id}): {first_exc}"
            ) from first_exc
        try:
            data = _fetch(asset.download_fallback_url)
        except Exception as exc:
            raise MediaError(
                f"{asset.provider}: download falhou ({asset.asset_id}): {exc}"
            ) from exc
    with open(dest, "wb") as fh:
        fh.write(data)
    if metrics is not None:
        metrics.media_download(os.path.getsize(dest), False)
    time.sleep(1.0)  # intervalo entre downloads (cortesia)
    asset.local_path = dest
    record = asset.to_dict()
    record["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)
    return asset
