"""Scene planning, cache loading, semantic enrichment and persistence."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

from .config import CurioConfig
from .runlog import event as run_event
from .stages import nvidia as nvidia_stage
from .stages import scenes as scenes_stage
from .stages import visual as visual_stage
from .stages.scene_local_planning import recover_legacy_chapters
from .stages.scene_contract import (ScenePlanResult, SemanticScene,
                                    TimelineSpan)
from .stages.scene_enrichment import SceneEnrichmentResult, enrich_scenes
from .stages.scene_plan_artifact import plan_from_dict, plan_to_dict
from .stages.scenes import Chapter


@dataclass(frozen=True)
class SceneStageResult:
    semantic_scenes: tuple[SemanticScene, ...]
    timeline_spans: tuple[TimelineSpan, ...]
    source: str
    enrichment: SceneEnrichmentResult
    invalidate_media: bool
    elapsed: float

    def __post_init__(self) -> None:
        scene_ids = tuple(scene.id for scene in self.semantic_scenes)
        if not scene_ids or len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene stage must return unique semantic scenes")
        if tuple(span.scene_id for span in self.timeline_spans) != scene_ids:
            raise ValueError("scene stage spans do not match semantic scenes")
        if not self.source:
            raise ValueError("scene stage source is required")


def load_chapters(paths) -> list[Chapter]:
    """Load the persisted compatibility format and validate every scene."""
    with open(paths.chapters_json, encoding="utf-8") as fh:
        chapters = [Chapter.from_dict(row) for row in json.load(fh)]
    for chapter in chapters:
        chapter.require_valid()
    return chapters


def _chapter_projection_differs(path: str, chapters: list[Chapter]) -> bool:
    """Detect stale compatibility output without treating it as cache truth."""
    try:
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        return True
    return stored != [chapter.to_dict() for chapter in chapters]


def run_scene_stage(script_text: str, cfg: CurioConfig, paths, *,
                    force: bool, script_mode: bool, genre: str,
                    scene_target_seconds: float, max_scenes: int | None,
                    scene_directive: str, topic: str, target,
                    research_sources: list, research_timeout: float,
                    etymology, metrics, warnings: list[str],
                    write_json) -> SceneStageResult:
    """Plan/restore, enrich and persist one validated scene batch."""
    started = time.monotonic()
    scene_plan_path = getattr(paths, "scene_plan_json", "")
    has_scene_plan = bool(scene_plan_path and os.path.isfile(scene_plan_path))
    has_legacy_chapters = os.path.isfile(paths.chapters_json)
    if not force and (has_scene_plan or has_legacy_chapters):
        persist_chapters = False
        persist_plan = False
        source = "cache"
        if has_scene_plan:
            with open(scene_plan_path, encoding="utf-8") as fh:
                stored_plan = plan_from_dict(json.load(fh))
            semantic_inputs = stored_plan.semantic_scenes
            timeline_spans = stored_plan.timeline_spans
            plan_source = stored_plan.source
            recovered_legacy = False
        else:
            chapters = load_chapters(paths)
            recovered_legacy = recover_legacy_chapters(chapters)
            semantic_inputs = tuple(chapter.semantic_scene("legacy_chapters_cache")
                                    for chapter in chapters)
            timeline_spans = tuple(chapter.timeline_span() for chapter in chapters)
            plan_source = "legacy_chapters_cache"
            persist_chapters = recovered_legacy
            persist_plan = True
        if script_mode:
            visual_stage.validate_preserved(script_text, semantic_inputs)
    else:
        persist_chapters = True
        persist_plan = True
        recovered_legacy = False
        if script_mode:
            count = visual_stage.scenes_for_script(script_text, cfg, genre)
        elif cfg.duration_target <= 0:
            count = scenes_stage.scenes_for_length(
                len(script_text.split()), scene_target_seconds, max_scenes)
        else:
            count = scenes_stage.scenes_for_duration(
                cfg.duration_target, scene_target_seconds, max_scenes)
        try:
            plan = scenes_stage.build_semantic_scenes(
                script_text, cfg, n_scenes=count, metrics=metrics,
                genre=genre, target_seconds=scene_target_seconds,
                genre_directive=_scene_directive(scene_directive, etymology),
                max_scenes=max_scenes)
            semantic_inputs = plan.semantic_scenes
            timeline_spans = plan.timeline_spans
            source = plan.source
            plan_source = plan.source
        except nvidia_stage.NvidiaError as exc:
            logged = run_event(
                "fallback", f"Cenas: chain LLM falhou; divisão local ({exc})",
                operation="scenes", fallback="local", error=str(exc))
            if not logged:
                print(f"AVISO: chain LLM de cenas indisponível ({exc}) — "
                      "seguindo com divisão local.", file=sys.stderr)
            warnings.append(f"cenas locais (chain LLM indisponível: {exc})")
            plan = scenes_stage.build_local_semantic_scenes(script_text, count)
            semantic_inputs = plan.semantic_scenes
            timeline_spans = plan.timeline_spans
            source = plan.source
            plan_source = plan.source
        if script_mode:
            visual_stage.validate_preserved(script_text, semantic_inputs)

    scene_event = ("provider" if source not in ("local", "cache")
                   else "fallback" if source == "local" else "cache")
    planning_mode = ("deterministic" if source == "local" or any(
        scene.planning_mode == "deterministic" for scene in semantic_inputs)
        else "llm")
    enriched = enrich_scenes(
        semantic_inputs, timeline_spans=timeline_spans,
        topic=topic, target=target, source=source,
        planning_mode=planning_mode, genre=genre,
        research_sources=research_sources, research_timeout=research_timeout,
        etymology=etymology)
    semantic_scenes = enriched.semantic_scenes
    timings = {span.scene_id: span for span in timeline_spans}
    chapters = [Chapter.from_semantic_scene(
        scene, timing=timings.get(scene.id)) for scene in semantic_scenes]
    persist_chapters = persist_chapters or enriched.changed
    persist_chapters = persist_chapters or _chapter_projection_differs(
        paths.chapters_json, chapters)
    persist_plan = persist_plan or enriched.changed
    if persist_chapters:
        write_json(paths.chapters_json, [chapter.to_dict() for chapter in chapters])
    if scene_plan_path and persist_plan:
        write_json(scene_plan_path, plan_to_dict(ScenePlanResult(
            semantic_scenes=semantic_scenes,
            timeline_spans=tuple(timeline_spans), source=plan_source)))
    if "local_topic_anchor" in enriched.applied:
        run_event("result", "Cenas locais ancoradas no tema do vídeo",
                  operation="scenes", source=source,
                  topic_queries=(semantic_scenes[0].global_visual_queries
                                 if semantic_scenes else []))
    if "verified_entity_context" in enriched.applied:
        run_event("result", "Contexto visual recuperado da entidade pesquisada",
                  operation="scenes", source=source)
    if "etymology_visual_context" in enriched.applied:
        run_event("result", "Cenas enriquecidas com a cadeia etimológica",
                  operation="scenes", source=source,
                  word=getattr(etymology, "word", ""))
    run_event(scene_event, f"Cenas: {source}; {len(chapters)} cena(s)",
              operation="scenes", source=source, scenes=len(chapters))
    return SceneStageResult(
        semantic_scenes=semantic_scenes,
        timeline_spans=tuple(timeline_spans),
        source=source, enrichment=enriched,
        invalidate_media=enriched.changed or recovered_legacy,
        elapsed=round(time.monotonic() - started, 2))


def _scene_directive(base: str, etymology) -> str:
    if etymology is None or len(getattr(etymology, "chain", []) or []) < 2:
        return base
    directive = (f"\n\nCADEIA ETIMOLÓGICA (use as formas como entidades visuais e "
                 f"o cenário como contexto): {etymology.chain_text()}")
    if etymology.visual_context:
        directive += " | cenário: " + ", ".join(etymology.visual_context)
    return (base or "") + directive
