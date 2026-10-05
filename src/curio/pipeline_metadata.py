"""Final persistence boundary for completed generation metadata."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from .media.selection_result import MediaStageResult
from .runlog import current_log_path
from .stages.scene_projection import Chapter


def typography_report(cfg, genre_key: str = "") -> dict:
    """Describe resolved typography roles for persisted project metadata."""
    if not genre_key:
        return {}
    from .stages import typography as typography_stage
    return typography_stage.for_genre(
        genre_key, (cfg.typography or {}).get(genre_key)).report()


def build_base_metadata(idea: str, slug: str, cfg, script_text: str,
                        script_source: str, semantic_scenes, timeline_spans,
                        scenes_source: str, media_result: MediaStageResult,
                        warnings, stage_times: dict, metrics,
                        started: float) -> dict:
    """Build the shared persisted metadata projection for both run modes."""
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    span_ids = tuple(span.scene_id for span in timeline_spans)
    if not isinstance(media_result, MediaStageResult):
        raise TypeError("metadata requires a MediaStageResult")
    media_ids = tuple(scene.scene_id for scene in media_result.scenes)
    if (not scene_ids or len(scene_ids) != len(set(scene_ids))
            or scene_ids != span_ids or scene_ids != media_ids):
        raise ValueError("metadata scenes, media and spans are misaligned")
    chapters = [Chapter.from_semantic_scene(scene, timing=span)
                for scene, span in zip(semantic_scenes, timeline_spans)]
    media_rows = media_result.to_rows()
    return {
        "title": idea.strip(),
        "input": idea,
        "slug": slug,
        "duration_target": cfg.duration_target,
        "script_source": script_source,
        "script_chars": len(script_text),
        "scenes_source": scenes_source,
        "chapters": [chapter.to_dict() for chapter in chapters],
        "media": media_rows,
        "media_resolution_source": media_result.source,
        "warnings": warnings,
        "width": cfg.width,
        "height": cfg.height,
        "fps": cfg.fps,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_log": current_log_path(),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "stage_times": stage_times,
        "pipeline_version": "scenes-0.2",
        "visual_report": metrics.media_visual_report(len(chapters)),
        "provider_downloads": metrics.media_download_report(),
    }


def persist_run_metadata(metadata: dict, metadata_path: str, metrics,
                         stage_times: dict, metrics_dir: str, write_json,
                         finalize_started: float, run_started: float) -> dict:
    """Persist one consistent project/metrics view after output artifacts exist.

    The finalization duration covers metadata/report assembly before this
    boundary. Metrics and project metadata share the same stage-time snapshot;
    the project file also records the generated metrics path.
    """
    stage_times["finalize"] = round(max(0.0, time.monotonic() - finalize_started), 2)
    metadata["processing_time_seconds"] = round(
        max(0.0, time.monotonic() - run_started), 2)
    metadata["stage_times"] = dict(stage_times)
    metadata["metrics_file"] = metrics.save(metadata, stage_times, metrics_dir)
    write_json(metadata_path, metadata)
    return metadata
