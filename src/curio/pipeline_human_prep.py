"""Preparation workflow for projects with human narration."""

from __future__ import annotations

import json
import os
import time

from .audio import composition as audio_composition
from .audio import selection as audio_selection
from .audio.library import audio_seed
from .config import CurioConfig
from . import pipeline_media_sources as pipeline_media_sources_stage
from . import pipeline_metadata as pipeline_metadata_stage
from . import pipeline_render as pipeline_render_stage
from . import pipeline_timeline as pipeline_timeline_stage
from . import project_artifacts
from . import project_paths
from .stages import render as render_stage
from .stages import scenes as scenes_stage
from .stages import teleprompter as tele_stage
from .stages import editorial as editorial_stage
from .stages.scenes import Chapter
from .stages.scene_contract import SemanticScene, TimelineSpan


def prepare_human_project(idea: str, slug: str, cfg: CurioConfig,
                paths: project_paths.VideoPaths,
                script_text: str, script_source: str,
                semantic_scenes: tuple[SemanticScene, ...],
                scenes_source: str, media_scenes: list[dict],
                warnings: list[str], stage_times: dict, started: float,
                emit, metrics, script_mode: bool = False,
                max_images: int = 1, overlap_cap: float = 0.9,
                insert_budget: int = 0, genre_key: str = "",
                transition_mode: str = "auto",
                genre_profile: dict | None = None,
                scene_context_enrichment: dict | None = None,
                media_source: str = "unknown",
                source_registry=None, research_sources=(), grounding=None,
                media_rights_notes=(), credits=(),
                video_title: str = "", title_source: str = "") -> dict:
    # [4/6] Timeline estimada por WPM (só para leitura — nunca sincronia final)
    t0 = time.monotonic()
    emit(4, "Estimando timeline")
    cursor = 0.0
    from .stages.scene_contract import TimelineSpan
    timeline_spans = []
    for scene in semantic_scenes:
        duration = scenes_stage.estimate_duration(
            scene.narration, cfg.teleprompter_wpm)
        timeline_spans.append(TimelineSpan(
            scene.id, duration, cursor, cursor + duration))
        cursor += duration
    timeline_spans = tuple(timeline_spans)
    estimated_total = round(cursor, 2)
    project_artifacts.write_json(paths.timeline_json, [Chapter.from_semantic_scene(
        scene, timing=span).to_dict()
        for scene, span in zip(semantic_scenes, timeline_spans)])
    timeline_result = pipeline_timeline_stage.build_visual_timeline(
        semantic_scenes, timeline_spans, media_scenes,
        paths, slug, overlap_cap, cfg.visual_sfx,
        insert_budget, cfg.visual_insert_style, cfg.visual_insert_gain_db,
        max_images > 1, metrics, project_artifacts.write_json)
    visual_timeline = timeline_result.entries
    audio_events = audio_composition.sfx_events(visual_timeline)
    try:
        previous_meta = project_artifacts.read_json(paths.metadata_json)
    except (OSError, ValueError, json.JSONDecodeError):
        previous_meta = {}
    audio_plan = audio_selection.resolve_audio(
        cfg, genre_key,
        audio_seed(slug, video_title or idea, script_text),
        video_title or idea, script_text, audio_events,
        previous_meta.get("audio_request") or previous_meta.get("audio"))
    warnings.extend(audio_plan["warnings"])
    all_credits = list(dict.fromkeys([
        *credits, *(audio_plan["metadata"].get("credits") or [])]))
    if source_registry is not None:
        source_summary = pipeline_media_sources_stage.persist_source_artifacts(
            source_registry, paths, research=research_sources,
            grounding=grounding, media_notes=media_rights_notes,
            credits=all_credits)
    else:
        source_summary = {}
    stage_times["timeline"] = round(time.monotonic() - t0, 2)
    emit(4, "Estimando timeline", "OK")

    # [5/6] Vídeo silencioso
    t0 = time.monotonic()
    emit(5, "Montando silencioso")
    if visual_timeline:
        pipeline_render_stage.build_silent_visual(
                             semantic_scenes, timeline_spans,
                             visual_timeline, idea, paths, cfg,
                             paths.silent_mp4, transitions=pipeline_render_stage.genre_transitions(
                                 semantic_scenes, genre_key, transition_mode),
                             kinds=pipeline_render_stage.genre_transition_kinds(
                                 semantic_scenes, genre_key, transition_mode))
    else:
        pipeline_render_stage.build_silent(
                      semantic_scenes, timeline_spans, media_scenes,
                      idea, paths, cfg,
                      paths.silent_mp4, transitions=pipeline_render_stage.genre_transitions(
                          semantic_scenes, genre_key, transition_mode),
                      kinds=pipeline_render_stage.genre_transition_kinds(
                          semantic_scenes, genre_key, transition_mode))
    stage_times["silent"] = round(time.monotonic() - t0, 2)
    emit(5, "Montando silencioso", "OK")

    # [6/6] Teleprompter (texto grande sobre cópia do silencioso)
    t0 = time.monotonic()
    emit(6, "Gerando teleprompter")
    tele_cues = tele_stage.write_teleprompter_ass(
        semantic_scenes, timeline_spans, paths.tele_ass,
        cfg.width, cfg.height)
    tele_info = render_stage.burn_final(
        paths.silent_mp4, paths.tele_ass, None, paths.tele_mp4,
        cfg, estimated_total)
    stage_times["teleprompter"] = round(time.monotonic() - t0, 2)
    emit(6, "Gerando teleprompter", "OK")

    finalize_started = time.monotonic()
    metadata = pipeline_metadata_stage.build_base_metadata(
        idea, slug, cfg, script_text, script_source, semantic_scenes,
        timeline_spans, scenes_source, media_scenes, warnings, stage_times,
        metrics, media_source, started)
    metadata.update({
        "genre": genre_key,
        "project_dir": os.path.relpath(paths.root, cfg.out_dir),
        "audio_request": audio_plan["metadata"],
        "sources": source_summary,
        "visual_transition_signature": pipeline_render_stage.transition_signature(
            semantic_scenes, timeline_spans, genre_key, transition_mode,
            {"insertions": insert_budget,
             "insert_style": cfg.visual_insert_style,
             "insert_gain_db": cfg.visual_insert_gain_db,
             "visual_sfx": cfg.visual_sfx}),
        "visual_transitions": {
            "genre": genre_key, "mode": transition_mode,
            "boundary_durations": pipeline_render_stage.genre_transitions(
                semantic_scenes, genre_key, transition_mode),
            "final_fade": audio_composition.final_audio_fade(genre_key, transition_mode),
        },
        "genre_profile": genre_profile or editorial_stage.summary(None),
        "scene_context_enrichment": scene_context_enrichment or {},
        "typography": pipeline_metadata_stage.typography_report(cfg, genre_key),
        "narration": "human-pending",
        "mode": "script" if script_mode else "idea",
        "video_title": video_title,
        "title_source": title_source,
        "duration_actual": estimated_total,
        "teleprompter_wpm": cfg.teleprompter_wpm,
        "teleprompter_cues": tele_cues,
        "visual": ({
            "max_images": max_images,
            "overlap_cap": overlap_cap,
        } if max_images > 1 else None),
        "artifacts": {
            "script": paths.script_txt,
            "title": paths.title_txt,
            "script_manifest": paths.script_manifest_json,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "timeline": paths.timeline_json,
            **({"visual_timeline": paths.visual_json}
               if max_images > 1 else {}),
            "silent": paths.silent_mp4,
            "teleprompter": paths.tele_mp4,
            "teleprompter_ass": paths.tele_ass,
        },
    })
    return pipeline_metadata_stage.persist_run_metadata(
        metadata, paths.metadata_json, metrics, stage_times, cfg.metrics_dir,
        project_artifacts.write_json, finalize_started, started)
