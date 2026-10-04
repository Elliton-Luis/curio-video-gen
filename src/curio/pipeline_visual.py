"""Resolve project media from manual input, a valid project cache, or providers."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from .media.artifacts import (media_selection_signature,
                              selection_cache_is_current, write_manifest)
from .media.providers import get_providers
from .pipeline_media import manual_media_dir, manual_media_scenes
from .runlog import event as run_event
from .stages import scoring as scoring_stage
from .stages import visual as visual_stage
from .stages.media_selection import SelectionDecision
from .stages.scene_contract import SemanticScene


@dataclass(frozen=True)
class MediaStageResult:
    """Complete outcome of resolving visual selections for one project."""

    scenes: list[dict]
    source: str
    warnings: list[str]
    real_scenes: int
    synthetic_scenes: int
    scenes_without_visual: int

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("media stage source is required")
        ids = []
        real = synthetic = missing = 0
        for scene in self.scenes:
            if not isinstance(scene, dict):
                raise TypeError("media stage scenes must be objects")
            scene_id = scene.get("chapter_id")
            if isinstance(scene_id, bool) or not isinstance(scene_id, int) \
                    or scene_id <= 0:
                raise ValueError("media scene chapter_id must be positive")
            ids.append(scene_id)
            asset = scene.get("asset")
            entries = scene.get("assets") or []
            if asset is not None and not isinstance(asset, dict):
                raise TypeError("selected media asset must be an object or null")
            if not isinstance(entries, list) or any(
                    not isinstance(entry, dict) for entry in entries):
                raise TypeError("media scene assets must be a list of objects")
            if entries and asset is None:
                raise ValueError("scene asset list requires a selected asset")
            if entries and isinstance(entries[0].get("asset"), dict) and asset:
                first = entries[0]["asset"]
                for key in ("provider", "asset_id"):
                    if (first.get(key) and asset.get(key)
                            and first[key] != asset[key]):
                        raise ValueError("scene asset differs from first selected entry")
            visual_decision = scene.get("visual_decision")
            if visual_decision is not None and not isinstance(visual_decision, dict):
                raise TypeError("visual_decision must be an object")
            decision_data = (visual_decision or {}).get("selection")
            if decision_data is not None:
                decision = SelectionDecision.from_dict(decision_data)
                if decision.scene_id != scene_id:
                    raise ValueError("selection decision belongs to another scene")
                if asset and decision.asset_id and asset.get("asset_id") \
                        and decision.asset_id != asset["asset_id"]:
                    raise ValueError("selection decision asset does not match scene")
                if decision.status == "none" and asset:
                    raise ValueError("empty selection decision has a selected asset")
                if decision.status != "none" and not asset:
                    raise ValueError("selected decision has no selected asset")
                if asset:
                    provider = str(asset.get("provider", "") or "")
                    if decision.provider and decision.provider != provider:
                        raise ValueError("selection decision provider does not match asset")
                    if (decision.status == "synthetic") != (provider == "synth"):
                        raise ValueError("selection decision status does not match asset type")
            provider = str((asset or {}).get("provider", "") or "")
            if provider == "synth":
                synthetic += 1
            elif provider:
                real += 1
            else:
                missing += 1
        if len(ids) != len(set(ids)):
            raise ValueError("media stage scene ids must be unique")
        if (real, synthetic, missing) != (
                self.real_scenes, self.synthetic_scenes,
                self.scenes_without_visual):
            raise ValueError("media stage counts do not match its scene results")


def resolve_media(scenes: list[SemanticScene], cfg, paths, max_images: int,
                  genre: str, metrics, force: bool, write_json) -> MediaStageResult:
    """Choose a valid manual/cache selection or acquire and persist a new one."""
    warnings: list[str] = []
    manual_dir = manual_media_dir(paths)
    manual = manual_media_scenes(scenes, manual_dir)
    available_providers = [provider.name for provider in get_providers(cfg)]
    signature = media_selection_signature(
        scenes, genre, max_images, available_providers,
        scoring_stage.threshold())

    if manual is not None:
        warnings.append(
            f"mídia manual: {len({entry['asset']['local_path'] for scene in manual for entry in scene.get('assets') or []})} "
            f"foto(s) de {manual_dir}")
        print(f"Mídia manual: usando fotos de {manual_dir}.", file=sys.stderr)
        run_event("cache", f"Mídia manual: {len(manual)} cena(s)",
                  operation="media", source="manual", scenes=len(manual))
        _write_selection(paths, manual, signature, source="manual",
                         write_json=write_json)
        return _record_selection(manual, "manual", warnings, metrics)

    if not force and os.path.isfile(paths.media_json):
        cached = _read_current_cache(scenes, paths, signature, max_images)
        if cached is not None:
            run_event("cache", "Mídia reutilizada do cache",
                      operation="media", scenes=len(cached))
            return _record_selection(cached, "project-cache", warnings, metrics)

    selected, acquisition_warnings = visual_stage.fetch_media_multi(
        scenes, cfg, max_images, metrics, genre=genre)
    warnings.extend(acquisition_warnings)
    _write_selection(paths, selected, signature, source="provider",
                     write_json=write_json)
    for warning in acquisition_warnings[:8]:
        run_event("warning", str(warning), operation="media")
    return _record_selection(selected, "provider", warnings, metrics)


def _record_selection(scenes: list[dict], source: str, warnings: list[str],
                      metrics) -> MediaStageResult:
    """Record the resolution outcome once, regardless of selection source."""
    real_scenes = synthetic_scenes = scenes_without_visual = 0
    for scene in scenes:
        if metrics and scene.get("visual_decision"):
            metrics.media_record_scene_decision(
                int(scene.get("chapter_id", 0)), scene["visual_decision"])
        entries = scene.get("assets") or []
        asset = scene.get("asset") or {}
        provider = str(asset.get("provider", "") or "")
        synthetic = provider == "synth"
        if synthetic:
            synthetic_scenes += 1
        elif provider:
            real_scenes += 1
        else:
            scenes_without_visual += 1
        run_event(
            "fallback" if synthetic or not provider else "result",
            f"Mídia cena {scene.get('chapter_id')}: {len(entries)} asset(s); "
            f"{'visual sintético' if synthetic else provider or 'sem visual'}",
            operation="media", scene=scene.get("chapter_id"),
            candidates=len(entries), provider=provider,
            fallback=synthetic or not provider,
            rejected=len(scene.get("rejected") or []))
    run_event(
        "result",
        f"Mídia: {real_scenes}/{len(scenes)} cena(s) selecionaram asset real; "
        f"{synthetic_scenes} sintético(s), {scenes_without_visual} sem visual",
        operation="media", scenes_with_real_asset=real_scenes,
        synthetic_scenes=synthetic_scenes,
        scenes_without_visual=scenes_without_visual,
        downloads=getattr(metrics, "media_downloads", 0),
        cache_hits=getattr(metrics, "media_cache_hits", 0))
    return MediaStageResult(scenes, source, warnings, real_scenes,
                            synthetic_scenes, scenes_without_visual)


def _read_current_cache(scenes: list[SemanticScene], paths, signature: str,
                        max_images: int) -> list[dict] | None:
    try:
        saved = _read_json(paths.media_json)
        expected_ids = [scene.id for scene in scenes]
        if ([scene["chapter_id"] for scene in saved] != expected_ids
                or not selection_cache_is_current(
                    saved, paths.media_manifest_json, signature, expected_ids)
                or not all(isinstance(scene.get("visual_decision"), dict)
                           for scene in saved
                           if (scene.get("asset") or {}).get("provider") != "manual")):
            return None

        by_id = {scene.id: scene for scene in scenes}
        for record in saved:
            scene = by_id.get(record["chapter_id"])
            if scene is None:
                return None
            blocked = visual_stage.media_rules.scene_blocklist(scene)
            entries = record.get("assets") or []
            if any(visual_stage.media_rules.rejection_reason(
                    entry.get("asset") or {}, blocked)
                    for entry in entries
                    if (entry.get("asset") or {}).get("provider") != "synth"):
                return None
            first = record.get("asset")
            if first is not None and not os.path.isfile(first.get("local_path", "")):
                return None
            if max_images > 1:
                if "assets" not in record:
                    return None
                if any(not os.path.isfile((entry.get("asset") or {}).get("local_path", ""))
                       for entry in entries):
                    return None
        return saved
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _write_selection(paths, scenes: list[dict], signature: str,
                     source: str, write_json) -> None:
    write_json(paths.media_json, scenes)
    if source == "provider" and any(
            scene.get("asset") or scene.get("assets") for scene in scenes):
        write_manifest(paths.media_manifest_json, scenes, signature)
    elif source == "provider" and os.path.isfile(paths.media_manifest_json):
        os.unlink(paths.media_manifest_json)


def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


        fh.write("\n")
