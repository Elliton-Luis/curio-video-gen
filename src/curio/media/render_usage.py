"""Provenance for media inputs accepted by visual segment rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualRenderSceneUsage:
    scene_id: int
    requested_asset_ids: tuple[str, ...]
    passed_asset_ids: tuple[str, ...]
    unavailable_asset_ids: tuple[str, ...]
    omitted_asset_ids: tuple[str, ...]
    fallback_used: bool
    segment_reused: bool

    def __post_init__(self) -> None:
        if isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int) \
                or self.scene_id <= 0:
            raise ValueError("render usage scene id must be positive")
        for name in ("requested_asset_ids", "passed_asset_ids",
                     "unavailable_asset_ids", "omitted_asset_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                    not isinstance(value, str) or not value for value in values):
                raise TypeError(f"render usage {name} must be a tuple of IDs")
            if len(values) != len(set(values)):
                raise ValueError(f"render usage {name} must be unique")
        requested = set(self.requested_asset_ids)
        if (not set(self.passed_asset_ids) <= requested
                or not set(self.unavailable_asset_ids) <= requested
                or not set(self.omitted_asset_ids) <= requested):
            raise ValueError("render usage IDs must belong to requested assets")
        if set(self.passed_asset_ids) & set(self.unavailable_asset_ids):
            raise ValueError("render usage asset cannot be passed and unavailable")
        if set(self.omitted_asset_ids) != requested - set(self.passed_asset_ids):
            raise ValueError("render usage omitted IDs must match unpassed IDs")
        if (not isinstance(self.fallback_used, bool)
                or not isinstance(self.segment_reused, bool)):
            raise TypeError("render usage flags must be boolean")
        if self.fallback_used != (not self.passed_asset_ids):
            raise ValueError("render usage fallback must match passed asset IDs")

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "requested_asset_ids": list(self.requested_asset_ids),
            "passed_asset_ids": list(self.passed_asset_ids),
            "unavailable_asset_ids": list(self.unavailable_asset_ids),
            "omitted_asset_ids": list(self.omitted_asset_ids),
            "fallback_used": self.fallback_used,
            "segment_reused": self.segment_reused,
        }


@dataclass(frozen=True)
class VisualRenderUsage:
    output_path: str
    scenes: tuple[VisualRenderSceneUsage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.output_path, str) or not self.output_path:
            raise ValueError("render usage output path is required")
        if not isinstance(self.scenes, tuple) or not self.scenes or any(
                not isinstance(scene, VisualRenderSceneUsage)
                for scene in self.scenes):
            raise TypeError("render usage requires visual scene usage values")
        ids = tuple(scene.scene_id for scene in self.scenes)
        if len(ids) != len(set(ids)):
            raise ValueError("render usage scene ids must be unique")

    def to_dict(self) -> dict:
        return {"output_path": self.output_path,
                "scenes": [scene.to_dict() for scene in self.scenes]}
