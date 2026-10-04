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
from .stages.scene_contract import SemanticScene


@dataclass(frozen=True)
class MediaStageResult:
    """Complete outcome of resolving visual selections for one project."""

    scenes: list[dict]
    source: str
    warnings: list[str]


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
        return MediaStageResult(manual, "manual", warnings)

    if not force and os.path.isfile(paths.media_json):
        cached = _read_current_cache(scenes, paths, signature, max_images)
        if cached is not None:
            run_event("cache", "Mídia reutilizada do cache",
                      operation="media", scenes=len(cached))
            return MediaStageResult(cached, "project-cache", warnings)

    selected, acquisition_warnings = visual_stage.fetch_media_multi(
        scenes, cfg, max_images, metrics, genre=genre)
    warnings.extend(acquisition_warnings)
    _write_selection(paths, selected, signature, source="provider",
                     write_json=write_json)
    for warning in acquisition_warnings[:8]:
        run_event("warning", str(warning), operation="media")
    return MediaStageResult(selected, "provider", warnings)


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
