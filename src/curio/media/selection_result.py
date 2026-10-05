"""Validated in-memory result of assigning visual media to scenes.

The persisted ``media.json`` row remains the project format. These values
provide typed access to its selected assets and selection decision; ``to_dict``
is the explicit compatibility projection for consumers not yet migrated.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite

from .providers import MediaAsset
from ..stages.media_selection import SelectionDecision


@dataclass(frozen=True)
class SelectedAsset:
    asset: MediaAsset
    query: str
    relevance: float
    order: int
    generic: bool
    score: float | None
    acquisition: str
    reuse_reason: str
    strategy: str
    score_detail: dict | None
    _row: dict = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, value: object, index: int) -> "SelectedAsset":
        if not isinstance(value, dict):
            raise TypeError("selected media entry must be an object")
        raw_asset = value.get("asset")
        if not isinstance(raw_asset, dict):
            raise ValueError("selected media entry requires an asset object")
        asset = MediaAsset.from_dict(raw_asset)
        if not asset.provider or not asset.asset_id:
            raise ValueError("selected media asset requires provider and asset id")
        relevance = _finite_number(value.get("relevance", 0), "asset relevance")
        score_raw = value.get("score")
        score = None if score_raw is None else _finite_number(score_raw, "asset score")
        order = value.get("order", index)
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise ValueError("selected asset order must be a non-negative integer")
        generic = value.get("generic", False)
        if not isinstance(generic, bool):
            raise TypeError("selected asset generic flag must be boolean")
        query = value.get("query", "")
        if not isinstance(query, str):
            raise TypeError("selected asset query must be a string")
        score_detail = value.get("score_detail")
        if score_detail is not None and not isinstance(score_detail, dict):
            raise TypeError("selected asset score detail must be an object or null")
        return cls(
            asset=asset, query=query,
            relevance=relevance, order=order, generic=generic, score=score,
            acquisition=_string(value, "acquisition"),
            reuse_reason=_string(value, "reuse_reason"),
            strategy=_string(value, "strategy"),
            score_detail=deepcopy(score_detail), _row=deepcopy(value))

    def to_dict(self) -> dict:
        """Return the original row, without normalizing project metadata."""
        return deepcopy(self._row)


@dataclass(frozen=True)
class SceneMediaSelection:
    scene_id: int
    asset: MediaAsset | None
    assets: tuple[SelectedAsset, ...]
    decision: SelectionDecision
    reused_from: int | None
    visual_type: str
    strategy: str
    rejected: tuple[dict, ...]
    reuse: tuple[dict, ...]
    visual_audit: dict
    _row: dict = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, value: object) -> "SceneMediaSelection":
        if not isinstance(value, dict):
            raise TypeError("media scene must be an object")
        scene_id = value.get("chapter_id")
        if isinstance(scene_id, bool) or not isinstance(scene_id, int) or scene_id <= 0:
            raise ValueError("media scene chapter_id must be positive")

        raw_asset = value.get("asset")
        if raw_asset is not None and not isinstance(raw_asset, dict):
            raise TypeError("selected media asset must be an object or null")
        asset = MediaAsset.from_dict(raw_asset) if raw_asset is not None else None
        if asset is not None and (not asset.provider or not asset.asset_id):
            raise ValueError("selected media asset requires provider and asset id")

        raw_entries = value.get("assets") or []
        if not isinstance(raw_entries, list):
            raise TypeError("media scene assets must be a list")
        entries = tuple(SelectedAsset.from_dict(entry, index)
                        for index, entry in enumerate(raw_entries))
        if entries and asset is None:
            raise ValueError("scene asset list requires a selected asset")
        if entries and asset:
            first = entries[0].asset
            if ((first.provider and asset.provider and first.provider != asset.provider)
                    or (first.asset_id and asset.asset_id
                        and first.asset_id != asset.asset_id)):
                raise ValueError("scene asset differs from first selected entry")

        raw_decision = value.get("visual_decision")
        if raw_decision is not None and not isinstance(raw_decision, dict):
            raise TypeError("visual_decision must be an object")
        decision_data = (raw_decision or {}).get("selection")
        if decision_data is None:
            raise ValueError("media scene requires an explicit selection decision")
        decision = SelectionDecision.from_dict(decision_data)
        if decision.scene_id != scene_id:
            raise ValueError("selection decision belongs to another scene")
        if asset and decision.asset_id and asset.asset_id \
                and decision.asset_id != asset.asset_id:
            raise ValueError("selection decision asset does not match scene")
        if decision.status == "none" and asset:
            raise ValueError("empty selection decision has a selected asset")
        if decision.status != "none" and not asset:
            raise ValueError("selected decision has no selected asset")
        if asset and decision.provider and decision.provider != asset.provider:
            raise ValueError("selection decision provider does not match asset")
        if asset and ((decision.status == "synthetic")
                      != (asset.provider == "synth")):
            raise ValueError("selection decision status does not match asset type")

        reused_from = value.get("reused_from")
        if reused_from is not None and (
                isinstance(reused_from, bool) or not isinstance(reused_from, int)
                or reused_from <= 0):
            raise ValueError("media reuse donor must be a positive scene id or null")
        rejected = value.get("rejected") or []
        reuse = value.get("reuse") or []
        if not isinstance(rejected, list) or any(not isinstance(x, dict) for x in rejected):
            raise TypeError("media rejections must be a list of objects")
        if not isinstance(reuse, list) or any(not isinstance(x, dict) for x in reuse):
            raise TypeError("media reuse audit must be a list of objects")
        visual_type = value.get("visual_type", "") or ""
        strategy = value.get("strategy", "") or ""
        if not isinstance(visual_type, str) or not isinstance(strategy, str):
            raise TypeError("media visual type and strategy must be strings")
        return cls(
            scene_id=scene_id, asset=asset, assets=entries, decision=decision,
            reused_from=reused_from, visual_type=visual_type, strategy=strategy,
            rejected=tuple(deepcopy(rejected)), reuse=tuple(deepcopy(reuse)),
            visual_audit=deepcopy(raw_decision or {}), _row=deepcopy(value))

    def to_dict(self) -> dict:
        """Return the original project row without schema expansion."""
        return deepcopy(self._row)


@dataclass(frozen=True)
class MediaStageResult:
    scenes: tuple[SceneMediaSelection, ...]
    source: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("media stage source is required")
        if not self.scenes or any(not isinstance(scene, SceneMediaSelection)
                                  for scene in self.scenes):
            raise TypeError("media stage requires typed scene selections")
        ids = tuple(scene.scene_id for scene in self.scenes)
        if len(ids) != len(set(ids)):
            raise ValueError("media stage scene ids must be unique")
        if any(not isinstance(warning, str) for warning in self.warnings):
            raise TypeError("media stage warnings must be strings")

    @classmethod
    def from_rows(cls, rows: list[dict], source: str,
                  warnings=()) -> "MediaStageResult":
        return cls(tuple(SceneMediaSelection.from_dict(row) for row in rows),
                   source, tuple(warnings))

    @property
    def real_scenes(self) -> int:
        return sum(scene.asset is not None and scene.asset.provider != "synth"
                   for scene in self.scenes)

    @property
    def synthetic_scenes(self) -> int:
        return sum(scene.asset is not None and scene.asset.provider == "synth"
                   for scene in self.scenes)

    @property
    def scenes_without_visual(self) -> int:
        return sum(scene.asset is None for scene in self.scenes)

    @property
    def selected_asset_count(self) -> int:
        return sum(scene.asset is not None for scene in self.scenes)

    def to_rows(self) -> list[dict]:
        """Project selected scenes to the persisted/legacy media row schema."""
        return [scene.to_dict() for scene in self.scenes]


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _string(value: dict, key: str) -> str:
    item = value.get(key, "") or ""
    if not isinstance(item, str):
        raise TypeError(f"selected asset {key} must be a string")
    return item
