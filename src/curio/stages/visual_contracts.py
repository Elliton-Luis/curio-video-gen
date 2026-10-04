"""Typed outputs at the boundary between scene meaning and media search."""

from __future__ import annotations

from dataclasses import dataclass

from .scene_contract import Alias, VisualRepresentation


@dataclass(frozen=True)
class VisualPlan:
    """Scene-bound visual intent consumed by search and provider policy.

    It deliberately contains no narration. Any lexical fallback derived from
    narration is materialized as `local_query_seeds` by the planner.
    """

    scene_id: int
    visual_type: str
    visual_intent: str
    visual_intent_structured: str
    topic: str
    aliases: tuple[Alias, ...]
    primary_entities: tuple[str, ...]
    representations: tuple[VisualRepresentation, ...]
    visual_queries: tuple[str, ...]
    global_visual_queries: tuple[str, ...]
    subject: str
    subject_aliases: tuple[str, ...]
    visual_entities: tuple[str, ...]
    context: tuple[str, ...]
    forbidden: tuple[str, ...]
    event: str
    place: str
    period: str
    local_fallback: bool
    local_query_seeds: tuple[str, ...]
    space_topic: bool
    mechanistic: bool
    scientific_context: bool
    historical_scene: bool

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "visual_type": self.visual_type,
            "intent": self.visual_intent,
            "structured_intent": self.visual_intent_structured,
            "topic": self.topic,
            "aliases": [{"value": a.value, "source": a.source,
                         "evidence": a.evidence, "verified": a.verified}
                        for a in self.aliases],
            "primary_entities": list(self.primary_entities),
            "representations": [r.to_dict() for r in self.representations],
            "scene_queries": list(self.visual_queries),
            "global_queries": list(self.global_visual_queries),
            "subject": self.subject,
            "subject_aliases": list(self.subject_aliases),
            "visual_entities": list(self.visual_entities),
            "context": list(self.context),
            "forbidden": list(self.forbidden),
            "event": self.event,
            "place": self.place,
            "period": self.period,
            "local_fallback": self.local_fallback,
            "local_query_seeds": list(self.local_query_seeds),
            "space_topic": self.space_topic,
            "mechanistic": self.mechanistic,
            "scientific_context": self.scientific_context,
            "historical_scene": self.historical_scene,
        }
