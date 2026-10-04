"""Canonical scene-level projection of selected visual media."""

from __future__ import annotations

from dataclasses import dataclass


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
    def from_scenes(cls, scenes: list[dict] | None,
                    known: bool = True) -> "MediaSelectionStats":
        if not known or scenes is None:
            return cls(*(None for _ in range(11)))

        from ..stages.visual_beats import asset_key

        occurrences: dict[str, set[int]] = {}
        statuses: list[str] = []
        seen_primary: set[str] = set()
        for scene_index, scene in enumerate(scenes):
            decision = scene.get("visual_decision") or {}
            selection = decision.get("selection") or {}
            status = selection.get("status")
            assets = scene.get("assets") or []
            if not assets and scene.get("asset"):
                assets = [{"asset": scene["asset"]}]
            primary = (assets[0].get("asset") or {}) if assets else {}
            if status not in {"real", "reused", "synthetic", "none"}:
                if primary.get("provider") == "synth":
                    status = "synthetic"
                elif primary:
                    primary_identity = asset_key(primary)
                    status = ("reused" if scene.get("reused_from")
                              or any(item.get("reuse_reason") for item in assets)
                              or (primary_identity and primary_identity in seen_primary)
                              else "real")
                elif decision:
                    status = "none"
                else:
                    status = "unknown"
            statuses.append(status)
            primary_identity = asset_key(primary) if primary else ""
            if primary_identity and primary.get("provider") != "synth":
                seen_primary.add(primary_identity)
            for item in assets:
                asset = item.get("asset") or {}
                if not asset or asset.get("provider") == "synth":
                    continue
                key = asset_key(asset)
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
