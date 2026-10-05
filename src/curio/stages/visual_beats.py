"""Short visual rhythm plan over existing scenes and assets."""

from __future__ import annotations

import math

BEAT_SECONDS = 2.1
MOTIONS = ("zoom", "pan_left", "pan_right", "reframe")


def plan(duration: float, start: float = 0.0) -> list[dict]:
    """Split scene time into 1.5–2.5 s camera beats; add no media query."""
    duration = max(0.0, float(duration))
    if duration <= 0:
        return []
    count = max(1, math.ceil(duration / BEAT_SECONDS))
    step = duration / count
    return [{"index": index,
             "start": round(start + index * step, 3),
             "end": round(start + min(duration, (index + 1) * step), 3),
             "motion": MOTIONS[index % len(MOTIONS)]}
            for index in range(count)]


def average_seconds(beats: list[dict]) -> float | None:
    if not beats:
        return None
    return round(sum(float(b["end"]) - float(b["start"]) for b in beats)
                 / len(beats), 2)


def asset_key(asset: dict) -> str:
    """Stable content identity across providers, with URL/ID fallbacks."""
    from ..media.identity import asset_identity
    return asset_identity(asset)


def bind_assets(beats: list[dict], assets: list[dict], start: float) -> list[dict]:
    """Assign all usable distinct backgrounds to consecutive existing beats."""
    distinct, seen = [], set()
    for asset in assets:
        key = asset_key(asset)
        if key and key not in seen:
            distinct.append(asset)
            seen.add(key)
    distinct = distinct[:len(beats)]
    backgrounds = []
    for index, asset in enumerate(distinct):
        first = index * len(beats) // len(distinct)
        last = (index + 1) * len(beats) // len(distinct)
        backgrounds.append({**asset,
                            "start": round(beats[first]["start"] - start, 3),
                            "duration": round(beats[last - 1]["end"] - beats[first]["start"], 3)})
        for beat in beats[first:last]:
            beat.update(asset_id=asset.get("asset_id", ""),
                        provider=asset.get("provider", ""),
                        local_path=asset.get("local_path", ""),
                        asset_ids=[asset_key(asset)])
    return backgrounds
