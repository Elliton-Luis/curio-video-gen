"""Shared validation for elapsed stage durations, always expressed in seconds."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from math import isfinite


def validate_stage_elapsed(value: object, stage: str) -> float:
    """Return a finite non-negative duration or reject an invalid result."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{stage} elapsed must be a number of seconds")
    elapsed = float(value)
    if not isfinite(elapsed) or elapsed < 0:
        raise ValueError(f"{stage} elapsed must be finite and non-negative")
    return elapsed


@dataclass(frozen=True)
class StageTiming:
    """One measured stage duration, expressed in seconds."""

    name: str
    seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("stage timing name is required")
        object.__setattr__(self, "seconds",
                           validate_stage_elapsed(self.seconds, self.name))


@dataclass(frozen=True)
class StageTimings(Mapping[str, float]):
    """Immutable per-run collection; JSON dicts are created only at persistence."""

    entries: tuple[StageTiming, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or any(
                not isinstance(entry, StageTiming) for entry in self.entries):
            raise TypeError("stage timings require an immutable tuple of StageTiming")
        names = tuple(entry.name for entry in self.entries)
        if len(names) != len(set(names)):
            raise ValueError("stage timing names must be unique")

    def with_stage(self, name: str, seconds: object) -> "StageTimings":
        timing = StageTiming(name, seconds)
        if name in self:
            raise ValueError(f"stage timing already recorded: {name}")
        return StageTimings((*self.entries, timing))

    def merged(self, other: "StageTimings") -> "StageTimings":
        if not isinstance(other, StageTimings):
            raise TypeError("stage timing merge requires StageTimings")
        merged_names = {entry.name for entry in self.entries}
        if any(entry.name in merged_names for entry in other.entries):
            raise ValueError("stage timing merge contains duplicate names")
        return StageTimings((*self.entries, *other.entries))

    def to_dict(self) -> dict[str, float]:
        """Project the canonical collection into the persisted JSON mapping."""
        return {entry.name: entry.seconds for entry in self.entries}

    def __getitem__(self, name: str) -> float:
        for entry in self.entries:
            if entry.name == name:
                return entry.seconds
        raise KeyError(name)

    def __iter__(self) -> Iterator[str]:
        return (entry.name for entry in self.entries)

    def __len__(self) -> int:
        return len(self.entries)
