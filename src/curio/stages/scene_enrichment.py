"""Explicit post-planner enrichment of semantic scene context."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from . import etymology as etymology_stage
from .visual_context import (anchor_local_topic, attach_video_context,
                             fill_missing_context)
from .scene_contract import SemanticScene, TimelineSpan
from .scenes import Chapter


@dataclass(frozen=True)
class SceneEnrichmentResult:
    semantic_scenes: tuple[SemanticScene, ...]
    chapters: tuple[Chapter, ...]
    source: str
    applied: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def to_dict(self) -> dict:
        return {"source": self.source, "changed": self.changed,
                "applied": list(self.applied),
                "scene_ids": [int(scene.id) for scene in self.semantic_scenes]}


def enrich_scenes(scenes, *, topic: str, target=None, source: str,
                  planning_mode: str = "unknown", genre: str = "",
                  research_sources=(),
                  research_timeout: int = 20, etymology=None,
                  timeline_spans: tuple[TimelineSpan, ...] = ()
                  ) -> SceneEnrichmentResult:
    """Return complete scene context without mutating planner/cache objects.

    This compatibility boundary centralizes all enrichment decisions after
    either scene planner. Its output is the only enriched batch the pipeline
    persists and passes to media planning.
    """
    semantic_inputs = []
    inferred_spans = {}
    for scene in scenes or []:
        if isinstance(scene, SemanticScene):
            semantic_inputs.append(scene)
        else:
            semantic_inputs.append(scene.semantic_scene(source or "unknown"))
            inferred_spans[scene.id] = scene.timeline_span()
    explicit_spans = {span.scene_id: span for span in timeline_spans}
    timings = {**inferred_spans, **explicit_spans}
    timeline = [Chapter.from_semantic_scene(
        scene, timing=timings.get(scene.id)) for scene in semantic_inputs]
    enriched = deepcopy(timeline)
    applied = []
    deterministic = planning_mode == "deterministic"
    if deterministic:
        for scene in enriched:
            scene.planning_mode = "deterministic"
    if attach_video_context(enriched, topic, target):
        applied.append("video_context")
    if deterministic and anchor_local_topic(enriched, topic, target):
        applied.append("local_topic_anchor")
    if fill_missing_context(enriched, target, genre, research_sources,
                            research_timeout):
        applied.append("verified_entity_context")
    if etymology_stage.enrich_chapters(enriched, etymology):
        applied.append("etymology_visual_context")
    for scene in enriched:
        scene.require_valid()
    semantic_scenes = tuple(scene.semantic_scene(source or "unknown")
                            for scene in enriched)
    return SceneEnrichmentResult(
        semantic_scenes=semantic_scenes, chapters=tuple(enriched),
        source=str(source or "unknown"), applied=tuple(applied))
