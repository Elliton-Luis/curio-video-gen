"""Canonical scene-level projection of selected visual media."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricAsset:
    provider: str
    asset_id: str
    source_url: str
    local_path: str
    title: str
    acquisition: str
    reuse_reason: str

    @classmethod
    def from_dict(cls, value: object) -> "MetricAsset | None":
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("metric asset must be an object or null")
        fields = {}
        for name in ("provider", "asset_id", "source_url", "local_path", "title"):
            field_value = value.get(name, "") or ""
            if not isinstance(field_value, str):
                raise TypeError(f"metric asset {name} must be a string")
            fields[name] = field_value
        acquisition = value.get("acquisition", "unknown") or "unknown"
        reuse_reason = value.get("reuse_reason", "") or ""
        if not isinstance(acquisition, str) or not isinstance(reuse_reason, str):
            raise TypeError("metric acquisition and reuse reason must be strings")
        return cls(**fields, acquisition=acquisition, reuse_reason=reuse_reason)

    def identity_fields(self) -> dict:
        return {"provider": self.provider, "asset_id": self.asset_id,
                "source_url": self.source_url, "local_path": self.local_path}


@dataclass(frozen=True)
class MetricAssetEntry:
    asset: MetricAsset | None
    acquisition: str
    reuse_reason: str


@dataclass(frozen=True)
class MetricSceneSelection:
    scene_id: int
    primary: MetricAsset | None
    assets: tuple[MetricAssetEntry, ...]
    status: str | None
    reused_from: int | None
    has_decision: bool

    def __post_init__(self) -> None:
        if isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int) \
                or self.scene_id <= 0:
            raise ValueError("metric scene id must be positive")
        if self.primary is not None and not isinstance(self.primary, MetricAsset):
            raise TypeError("metric primary asset must be typed or null")
        if not isinstance(self.assets, tuple) or any(
                not isinstance(entry, MetricAssetEntry) for entry in self.assets):
            raise TypeError("metric scene assets must be typed entries")
        if self.status is not None and not isinstance(self.status, str):
            raise TypeError("metric selection status must be a string or null")
        if not isinstance(self.has_decision, bool):
            raise TypeError("metric decision presence must be boolean")


@dataclass(frozen=True)
class MediaMetricsInput:
    """Validated metric view of live selections or persisted media rows."""

    scenes: tuple[MetricSceneSelection, ...]
    known: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.scenes, tuple) or any(
                not isinstance(scene, MetricSceneSelection) for scene in self.scenes):
            raise TypeError("media metrics input requires typed scene selections")
        ids = tuple(scene.scene_id for scene in self.scenes)
        if len(ids) != len(set(ids)):
            raise ValueError("media metrics scene ids must be unique")
        if not isinstance(self.known, bool):
            raise TypeError("media metrics known flag must be boolean")

    @classmethod
    def from_result(cls, result) -> "MediaMetricsInput":
        from .selection_result import MediaStageResult
        if not isinstance(result, MediaStageResult):
            raise TypeError("media metrics require a MediaStageResult")
        scenes = []
        for scene in result.scenes:
            primary = MetricAsset.from_dict(
                scene.asset.to_dict() if scene.asset is not None else None)
            entries = tuple(MetricAssetEntry(
                MetricAsset.from_dict(entry.asset.to_dict()),
                entry.acquisition or "unknown", entry.reuse_reason)
                for entry in scene.assets)
            status = scene.decision.status if scene.decision else None
            scenes.append(MetricSceneSelection(
                scene.scene_id, primary, entries, status, scene.reused_from,
                scene.decision is not None))
        return cls(tuple(scenes))

    @classmethod
    def from_persisted_rows(cls, rows: object,
                            known: bool = True) -> "MediaMetricsInput":
        if not known or rows is None:
            return cls((), False)
        if not isinstance(rows, list):
            raise TypeError("persisted media metrics must be a list")
        scenes = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("persisted media metric scene must be an object")
            scene_id = row.get("chapter_id")
            if isinstance(scene_id, bool) or not isinstance(scene_id, int) \
                    or scene_id <= 0:
                raise ValueError("persisted media metric chapter id must be positive")
            raw_entries = row.get("assets", [])
            if raw_entries is None:
                raw_entries = []
            if not isinstance(raw_entries, list):
                raise TypeError("persisted media metric assets must be a list")
            entries = []
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    raise TypeError("persisted media metric entry must be an object")
                asset = MetricAsset.from_dict(entry.get("asset"))
                acquisition = entry.get("acquisition", "unknown") or "unknown"
                reuse_reason = entry.get("reuse_reason", "") or ""
                if not isinstance(acquisition, str) or not isinstance(reuse_reason, str):
                    raise TypeError("persisted media metric provenance must be strings")
                entries.append(MetricAssetEntry(asset, acquisition, reuse_reason))
            decision = row.get("visual_decision")
            if decision is not None and not isinstance(decision, dict):
                raise TypeError("persisted media metric decision must be an object")
            selection = (decision or {}).get("selection") or {}
            if not isinstance(selection, dict):
                raise TypeError("persisted media metric selection must be an object")
            status = selection.get("status")
            if not isinstance(status, str) or status not in {
                    "real", "reused", "synthetic", "none"}:
                status = None
            primary = MetricAsset.from_dict(row.get("asset"))
            if primary is None and entries:
                primary = entries[0].asset
            reused_from = row.get("reused_from")
            if isinstance(reused_from, bool) or not isinstance(reused_from, int) \
                    or reused_from <= 0:
                reused_from = None
            scenes.append(MetricSceneSelection(
                scene_id, primary, tuple(entries), status, reused_from,
                status is not None))
        return cls(tuple(scenes), True)


@dataclass(frozen=True)
class MediaSelectionStats:
    scenes_with_real_asset: int | None
    unique_assets: int | None
    reused_assets: int | None
    reuse_count: int | None
    unique_asset_ratio: float | None
    scenes_with_new_asset: int | None
    scenes_with_reused_asset: int | None
    synthetic_scenes: int | None
    scenes_without_visual: int | None
    scenes_with_unknown_decision: int | None
    real_asset_occurrences: int | None

    @classmethod
    def from_input(cls, media: MediaMetricsInput) -> "MediaSelectionStats":
        if not isinstance(media, MediaMetricsInput):
            raise TypeError("selection statistics require MediaMetricsInput")
        if not media.known:
            return cls(*(None for _ in range(11)))

        from ..stages.visual_beats import asset_key

        occurrences: dict[str, set[int]] = {}
        statuses: list[str] = []
        seen_primary: set[str] = set()
        for scene_index, scene in enumerate(media.scenes):
            status = scene.status
            primary = scene.primary
            if status not in {"real", "reused", "synthetic", "none"}:
                if primary and primary.provider == "synth":
                    status = "synthetic"
                elif primary and (primary.provider or primary.asset_id
                                  or primary.source_url or primary.local_path):
                    primary_identity = asset_key(primary.identity_fields())
                    status = ("reused" if scene.reused_from
                              or any(item.reuse_reason for item in scene.assets)
                              or (primary_identity and primary_identity in seen_primary)
                              else "real")
                elif scene.has_decision:
                    status = "none"
                else:
                    status = "unknown"
            statuses.append(status)
            primary_identity = (asset_key(primary.identity_fields())
                                if primary else "")
            if primary_identity and primary.provider != "synth":
                seen_primary.add(primary_identity)
            entries = scene.assets
            if not entries and primary:
                entries = (MetricAssetEntry(primary, "unknown", ""),)
            for item in entries:
                asset = item.asset
                if not asset or asset.provider == "synth":
                    continue
                key = asset_key(asset.identity_fields())
                if key:
                    occurrences.setdefault(key, set()).add(scene_index)

        occurrence_count = sum(len(scene_indexes)
                               for scene_indexes in occurrences.values())
        unique_count = len(occurrences)
        repeated = sum(1 for scene_indexes in occurrences.values()
                       if len(scene_indexes) > 1)
        new_scenes = statuses.count("real")
        reused_scenes = statuses.count("reused")
        synthetic_scenes = statuses.count("synthetic")
        no_visual = statuses.count("none")
        unknown = statuses.count("unknown")
        real_scenes = new_scenes + reused_scenes
        return cls(
            scenes_with_real_asset=real_scenes,
            unique_assets=unique_count,
            reused_assets=repeated,
            reuse_count=max(0, occurrence_count - unique_count),
            unique_asset_ratio=(round(unique_count / occurrence_count, 3)
                                if occurrence_count else 0.0),
            scenes_with_new_asset=new_scenes,
            scenes_with_reused_asset=reused_scenes,
            synthetic_scenes=synthetic_scenes,
            scenes_without_visual=no_visual,
            scenes_with_unknown_decision=unknown,
            real_asset_occurrences=occurrence_count,
        )

    def visual_report_fields(self) -> dict:
        return {
            "unique_assets": self.unique_assets,
            "reused_assets": self.reused_assets,
            "reuse_count": self.reuse_count,
            "unique_asset_ratio": self.unique_asset_ratio,
            "scenes_with_new_asset": self.scenes_with_new_asset,
            "scenes_with_reused_asset": self.scenes_with_reused_asset,
            "synthetic_scenes": self.synthetic_scenes,
            "sem_visual": self.scenes_without_visual,
            "scenes_with_unknown_decision": self.scenes_with_unknown_decision,
            "real_asset_occurrences": self.real_asset_occurrences,
        }
