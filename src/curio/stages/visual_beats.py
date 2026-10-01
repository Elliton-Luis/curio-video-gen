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
