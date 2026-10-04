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
from .stages.scene_contract import SemanticScene
from .stages.scene_enrichment import SceneEnrichmentResult, enrich_scenes
from .stages.scenes import Chapter


@dataclass(frozen=True)
class SceneStageResult:
    semantic_scenes: tuple[SemanticScene, ...]
    chapters: tuple[Chapter, ...]
    source: str
    enrichment: SceneEnrichmentResult
    invalidate_media: bool
    elapsed: float


def load_chapters(paths) -> list[Chapter]:
    """Load the persisted compatibility format and validate every scene."""
    with open(paths.chapters_json, encoding="utf-8") as fh:
        chapters = [Chapter.from_dict(row) for row in json.load(fh)]
    for chapter in chapters:
        chapter.require_valid()
    return chapters


def run_scene_stage(script_text: str, cfg: CurioConfig, paths, *,
                    force: bool, script_mode: bool, genre: str,
                    scene_target_seconds: float, max_scenes: int | None,
                    scene_directive: str, topic: str, target,
                    research_sources: list, research_timeout: float,
                    etymology, metrics, warnings: list[str],
                    write_json) -> SceneStageResult:
    """Plan/restore, enrich and persist one validated scene batch."""
    started = time.monotonic()
    if not force and os.path.isfile(paths.chapters_json):
        chapters = load_chapters(paths)
        source = "cache"
        recovered_legacy = recover_legacy_chapters(chapters)
        semantic_inputs = tuple(chapter.semantic_scene(source)
                                for chapter in chapters)
        timeline_spans = tuple(chapter.timeline_span() for chapter in chapters)
        if script_mode:
            visual_stage.validate_preserved(script_text, semantic_inputs)
    else:
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
            chapters = list(plan.timeline_chapters())
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
            chapters = list(plan.timeline_chapters())
        if script_mode:
            visual_stage.validate_preserved(script_text, semantic_inputs)
        write_json(paths.chapters_json, [chapter.to_dict() for chapter in chapters])

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
    chapters = list(enriched.chapters)
    semantic_scenes = enriched.semantic_scenes
    if enriched.changed or recovered_legacy:
        write_json(paths.chapters_json, [chapter.to_dict() for chapter in chapters])
    if "local_topic_anchor" in enriched.applied:
        run_event("result", "Cenas locais ancoradas no tema do vídeo",
                  operation="scenes", source=source,
                  topic_queries=chapters[0].global_visual_queries if chapters else [])
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
        chapters=tuple(chapters), semantic_scenes=semantic_scenes,
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
