"""Explicit post-planner enrichment of semantic scene context."""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import etymology as etymology_stage
from .visual_context import (anchor_local_topic, attach_video_context,
                             fill_missing_context)
from .scene_contract import SemanticScene, TimelineSpan


@dataclass(frozen=True)
class SceneEnrichmentResult:
    semantic_scenes: tuple[SemanticScene, ...]
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
    semantic_inputs = tuple(scenes or ())
    if any(not isinstance(scene, SemanticScene) for scene in semantic_inputs):
        raise TypeError("scene enrichment requires SemanticScene values")
    scene_ids = tuple(scene.id for scene in semantic_inputs)
    if len(scene_ids) != len(set(scene_ids)):
        raise ValueError("scene enrichment scene ids must be unique")
    if any(scene.contract_errors() for scene in semantic_inputs):
        raise ValueError("scene enrichment received invalid semantic scene")
    if any(not isinstance(span, TimelineSpan) for span in timeline_spans):
        raise TypeError("scene enrichment requires TimelineSpan values")
    if timeline_spans and tuple(span.scene_id for span in timeline_spans) != scene_ids:
        raise ValueError("scene enrichment spans do not match scene order")
    enriched = tuple(semantic_inputs)
    applied = []
    deterministic = planning_mode == "deterministic"
    if deterministic:
        enriched = tuple(replace(scene, planning_mode="deterministic")
                         for scene in enriched)
        if enriched != tuple(semantic_inputs):
            applied.append("planning_mode")
    updated = attach_video_context(enriched, topic, target)
    if updated != enriched:
        applied.append("video_context")
    enriched = updated
    if deterministic:
        updated = anchor_local_topic(enriched, topic, target)
        if updated != enriched:
            applied.append("local_topic_anchor")
        enriched = updated
    updated = fill_missing_context(enriched, target, genre, research_sources,
                                   research_timeout)
    if updated != enriched:
        applied.append("verified_entity_context")
    enriched = updated
    updated = etymology_stage.enrich_scenes(enriched, etymology)
    if updated != enriched:
        applied.append("etymology_visual_context")
    enriched = updated
    for scene in enriched:
        errors = scene.contract_errors()
        if errors:
            raise ValueError(f"enrichment emitted invalid scene: {errors}")
    semantic_scenes = tuple(enriched)
    return SceneEnrichmentResult(
        semantic_scenes=semantic_scenes,
        source=str(source or "unknown"), applied=tuple(applied))
