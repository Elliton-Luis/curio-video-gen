"""Final persistence boundary for completed generation metadata."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from .media.selection_result import MediaStageResult
from .runlog import current_log_path
from .stages import editorial as editorial_stage
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


def build_assisted_run_metadata(*, idea: str, slug: str, cfg,
                                script_result, research_output, scene_result,
                                media_result: MediaStageResult, audio_result,
                                render_result, visual_timeline_result,
                                source_summary: dict, genre: str,
                                script_mode: bool, max_images: int,
                                overlap_cap: float, insert_budget: int,
                                warnings: list[str], stage_times: dict,
                                metrics, started: float, paths) -> dict:
    """Project completed typed stage results into the assisted-run schema."""
    from .pipeline_audio import AudioStageResult
    from .pipeline_render import RenderStageResult
    from .pipeline_research import ResearchStageResult
    from .pipeline_scenes import SceneStageResult
    from .pipeline_script import ScriptStageResult
    from .pipeline_timeline import VisualTimelineResult

    expected = (
        (script_result, ScriptStageResult, "ScriptStageResult"),
        (research_output, ResearchStageResult, "ResearchStageResult"),
        (scene_result, SceneStageResult, "SceneStageResult"),
        (audio_result, AudioStageResult, "AudioStageResult"),
        (render_result, RenderStageResult, "RenderStageResult"),
        (visual_timeline_result, VisualTimelineResult, "VisualTimelineResult"),
    )
    for value, contract, name in expected:
        if not isinstance(value, contract):
            raise TypeError(f"assisted metadata requires {name}")
    if not isinstance(source_summary, dict):
        raise TypeError("assisted metadata sources must be an object")

    scenes = scene_result.enrichment.semantic_scenes
    spans = audio_result.timeline_spans
    metadata = build_base_metadata(
        idea, slug, cfg, script_result.script.text, script_result.script.source,
        scenes, spans, scene_result.source, media_result, warnings, stage_times,
        metrics, started)
    research = research_output.result
    render_info = render_result.render_info
    tts_info = audio_result.tts_info
    metadata.update({
        "genre": genre,
        "scene_context_enrichment": scene_result.enrichment.to_dict(),
        "project_dir": os.path.relpath(paths.root, cfg.out_dir),
        "genre_profile": editorial_stage.summary(editorial_stage.get(genre)),
        "typography": typography_report(cfg, genre),
        "narration": "ai",
        "mode": "script" if script_mode else "idea",
        "video_title": script_result.title.text,
        "title_source": script_result.title.source,
        "timeline_source": audio_result.timed_source,
        "duration_actual": round(render_result.duration, 2),
        "audio_duration": round(audio_result.audio_duration, 2),
        "subtitle_cues": audio_result.cue_count,
        "subtitle_source": ("wordboundary" if audio_result.words and
                            tts_info["provider"] == "edge-tts"
                            else "proporcional"),
        "tts_provider": tts_info["provider"],
        "tts_voice": tts_info["voice"],
        "tts_speed": tts_info["speed"],
        "tts_reused": tts_info["reused"],
        "render_backend": render_info["backend"],
        "render_encoder": render_info["encoder"],
        "visual": ({
            "max_images": max_images,
            "overlap_cap": overlap_cap,
            "sfx": bool(render_result.sfx_path),
            "insertions": visual_timeline_result.insertion_count,
            "insert_budget": insert_budget,
            "insert_style": cfg.visual_insert_style,
            "insert_gain_db": cfg.visual_insert_gain_db,
        } if max_images > 1 else None),
        "audio": render_result.audio_metadata,
        "visual_transition_signature": render_result.transition_plan.signature,
        "visual_plan_signature": render_result.visual_plan_signature,
        "visual_transitions": render_result.transition_metadata,
        "sources": source_summary,
        "research": {
            "sources": len(research.sources),
            "status": research_output.status,
            "titles": [source.title for source in research.sources],
            "etymology": (research.etymology.to_dict()
                          if research.etymology is not None else None),
            "grounding": script_result.grounding,
            "target_entity": (research.target.to_dict()
                              if research.target is not None else None),
            "rejected": [{"title": source.title, "reason": reason}
                         for source, reason, _detail in research.rejected],
        },
        "artifacts": {
            "script": paths.script_txt,
            "title": paths.title_txt,
            "script_manifest": paths.script_manifest_json,
            "research": paths.research_json,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "audio": paths.narration_wav,
            "words": paths.words_json,
            "timeline": paths.timeline_json,
            **({"visual_timeline": paths.visual_json} if max_images > 1 else {}),
            **({"sfx": render_result.sfx_path} if render_result.sfx_path else {}),
            **({"music": render_result.music_path}
               if render_result.music_path else {}),
            "subtitles": paths.subs_srt,
            "subtitles_ass": paths.subs_ass,
            "silent": paths.silent_mp4,
            "video": paths.final_mp4,
        },
    })
    return metadata
