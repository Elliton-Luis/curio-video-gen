"""Validated persistence for semantic scene plans and independent timing."""

from __future__ import annotations

from collections.abc import Mapping

from .scene_contract import ScenePlanResult, SemanticScene, TimelineSpan

SCHEMA_VERSION = 1


def plan_to_dict(plan: ScenePlanResult) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": plan.source,
        "semantic_scenes": [scene.to_dict() for scene in plan.semantic_scenes],
        "timeline_spans": [span.to_dict() for span in plan.timeline_spans],
    }


def plan_from_dict(value: object) -> ScenePlanResult:
    if not isinstance(value, Mapping):
        raise ValueError("scene plan artifact must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported scene plan schema_version")
    source = value.get("source")
    scenes = value.get("semantic_scenes")
    spans = value.get("timeline_spans")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("scene plan artifact source is required")
    if not isinstance(scenes, list) or not isinstance(spans, list):
        raise ValueError("scene plan artifact scenes and spans must be lists")
    semantic_scenes = tuple(SemanticScene.from_dict(row) for row in scenes)
    timeline_spans = tuple(_timeline_span(row) for row in spans)
    return ScenePlanResult(semantic_scenes, timeline_spans, source)


def _timeline_span(value: object) -> TimelineSpan:
    if not isinstance(value, Mapping):
        raise ValueError("scene plan timeline span must be an object")
    scene_id = value.get("scene_id")
    duration = value.get("duration_estimate", 0.0)
    start = value.get("start", 0.0)
    end = value.get("end", 0.0)
    if isinstance(scene_id, bool) or not isinstance(scene_id, int):
        raise ValueError("timeline span scene_id must be an integer")
    return TimelineSpan(scene_id, duration, start, end)
