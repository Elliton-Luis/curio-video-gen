"""Validated persistence for semantic scene plans and independent timing."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from .scene_contract import ScenePlanResult, SemanticScene, TimelineSpan

SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ScenePlanManifest:
    """Identity of the inputs that produced a persisted semantic plan."""

    inputs_sha256: str

    def __post_init__(self) -> None:
        if (len(self.inputs_sha256) != 64
                or any(char not in "0123456789abcdef"
                       for char in self.inputs_sha256)):
            raise ValueError("scene plan input identity must be SHA-256")

    def to_dict(self) -> dict:
        return {"schema_version": MANIFEST_SCHEMA_VERSION,
                "inputs_sha256": self.inputs_sha256}

    @classmethod
    def from_dict(cls, value: object) -> "ScenePlanManifest":
        if (not isinstance(value, Mapping)
                or value.get("schema_version") != MANIFEST_SCHEMA_VERSION):
            raise ValueError("unsupported scene plan manifest")
        digest = value.get("inputs_sha256")
        if not isinstance(digest, str):
            raise ValueError("scene plan manifest input identity is required")
        return cls(digest)


def scene_plan_inputs_signature(script_text: str, cfg, *, genre: str,
                                scene_target_seconds: float,
                                max_scenes: int | None,
                                scene_directive: str, topic: str, target,
                                research_sources, research_timeout: float,
                                etymology) -> str:
    """Hash semantic planner/enrichment inputs, excluding credentials."""
    target_data = {}
    if target is not None:
        for name in ("name", "aliases", "discriminants", "forbidden",
                     "ambiguous", "source", "is_entity", "topic_terms"):
            if hasattr(target, name):
                target_data[name] = getattr(target, name)
    sources = [_plain(source) for source in (research_sources or ())]
    etymology_data = _plain(etymology) if etymology is not None else None
    data = {
        "script": script_text,
        "duration_target": getattr(cfg, "duration_target", None),
        "language": getattr(cfg, "language", ""),
        "nvidia_model": getattr(cfg, "nvidia_model", ""),
        "nvidia_base_url": getattr(cfg, "nvidia_base_url", ""),
        "nvidia_timeout": getattr(cfg, "nvidia_timeout", None),
        "openrouter_model": getattr(cfg, "openrouter_model", ""),
        "openrouter_base_url": getattr(cfg, "openrouter_base_url", ""),
        "llm_overrides": (cfg.llm_overrides() if hasattr(cfg, "llm_overrides")
                          else {}),
        "scene_target_seconds": scene_target_seconds,
        "max_scenes": max_scenes,
        "genre": genre,
        "scene_directive": scene_directive,
        "topic": topic,
        "target": target_data,
        "research_sources": sources,
        "research_timeout": research_timeout,
        "etymology": etymology_data,
    }
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_manifest(path: str) -> ScenePlanManifest | None:
    try:
        with open(path, encoding="utf-8") as stream:
            return ScenePlanManifest.from_dict(json.load(stream))
    except (OSError, ValueError, TypeError):
        return None


def write_manifest(path: str, manifest: ScenePlanManifest) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(manifest.to_dict(), stream, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


def _plain(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items()
                if not key.startswith("_")}
    return value


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
