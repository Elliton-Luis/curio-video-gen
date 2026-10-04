"""Explicit post-planner enrichment of semantic scene context."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from . import etymology as etymology_stage
from .visual_context import (anchor_local_topic, attach_video_context,
                             fill_missing_context)


@dataclass(frozen=True)
class SceneEnrichmentResult:
    scenes: tuple
    source: str
    applied: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def to_dict(self) -> dict:
        return {"source": self.source, "changed": self.changed,
                "applied": list(self.applied),
                "scene_ids": [int(scene.id) for scene in self.scenes]}


def enrich_scenes(scenes, *, topic: str, target=None, source: str,
                  local_fallback: bool, genre: str, research_sources=(),
                  research_timeout: int = 20, etymology=None
                  ) -> SceneEnrichmentResult:
    """Return complete scene context without mutating planner/cache objects.

    This compatibility boundary centralizes all enrichment decisions after
    either scene planner. Its output is the only enriched batch the pipeline
    persists and passes to media planning.
    """
    enriched = deepcopy(list(scenes or []))
    applied = []
    if local_fallback:
        for scene in enriched:
            if not str(scene.visual_intent or "").startswith("local fallback"):
                scene.visual_intent = (
                    "local fallback: cached "
                    + str(scene.visual_intent or "")).strip()
    if attach_video_context(enriched, topic, target):
        applied.append("video_context")
    if local_fallback and anchor_local_topic(enriched, topic, target):
        applied.append("local_topic_anchor")
    if fill_missing_context(enriched, target, genre, research_sources,
                            research_timeout):
        applied.append("verified_entity_context")
    if etymology_stage.enrich_chapters(enriched, etymology):
        applied.append("etymology_visual_context")
    for scene in enriched:
        scene.require_valid()
    return SceneEnrichmentResult(tuple(enriched), str(source or "unknown"),
                                 tuple(applied))
