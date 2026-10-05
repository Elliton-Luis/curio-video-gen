"""Shared validation for elapsed stage durations, always expressed in seconds."""

from __future__ import annotations

from math import isfinite


def validate_stage_elapsed(value: object, stage: str) -> float:
    """Return a finite non-negative duration or reject an invalid result."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{stage} elapsed must be a number of seconds")
    elapsed = float(value)
    if not isfinite(elapsed) or elapsed < 0:
        raise ValueError(f"{stage} elapsed must be finite and non-negative")
    return elapsed
