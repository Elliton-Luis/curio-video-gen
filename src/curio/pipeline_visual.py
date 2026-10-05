"""Resolve project media from manual input, a valid project cache, or providers."""

from __future__ import annotations

import json
import os
import sys

from .media.artifacts import (media_selection_signature,
                              selection_cache_is_current, write_manifest)
from .media.providers import get_providers
from .pipeline_media import manual_media_dir, manual_media_scenes
from .runlog import event as run_event
from . import project_artifacts
from .stages import scoring as scoring_stage
from .stages import visual as visual_stage
from .stages.scene_contract import SemanticScene
from .media.selection_result import MediaStageResult as _MediaStageResult


def resolve_media(scenes: list[SemanticScene], cfg, paths, max_images: int,
                  genre: str, metrics, force: bool, write_json) -> _MediaStageResult:
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
                      metrics) -> _MediaStageResult:
    """Record the resolution outcome once, regardless of selection source."""
    result = _MediaStageResult.from_rows(scenes, source, warnings)
    for scene in result.scenes:
        provider = scene.asset.provider if scene.asset is not None else ""
        if metrics and scene.visual_audit:
            metrics.media_record_scene_decision(
                scene.scene_id, scene.visual_audit)
        synthetic = provider == "synth"
        run_event(
            "fallback" if synthetic or not provider else "result",
            f"Mídia cena {scene.scene_id}: {len(scene.assets)} asset(s); "
            f"{'visual sintético' if synthetic else provider or 'sem visual'}",
            operation="media", scene=scene.scene_id,
            candidates=len(scene.assets), provider=provider,
            fallback=synthetic or not provider,
            rejected=len(scene.rejected))
    run_event(
        "result",
        f"Mídia: {result.real_scenes}/{len(result.scenes)} cena(s) selecionaram asset real; "
        f"{result.synthetic_scenes} sintético(s), {result.scenes_without_visual} sem visual",
        operation="media", scenes_with_real_asset=result.real_scenes,
        synthetic_scenes=result.synthetic_scenes,
        scenes_without_visual=result.scenes_without_visual,
        downloads=getattr(metrics, "media_downloads", 0),
        cache_hits=getattr(metrics, "media_cache_hits", 0))
    return result


def _read_current_cache(scenes: list[SemanticScene], paths, signature: str,
                        max_images: int) -> list[dict] | None:
    try:
        saved = project_artifacts.read_json(paths.media_json)
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


        fh.write("\n")
