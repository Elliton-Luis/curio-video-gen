"""Typed outputs at the boundary between scene meaning and media search."""

from __future__ import annotations

from dataclasses import dataclass

from .scene_contract import Alias, VisualRepresentation


@dataclass(frozen=True)
class VisualPlan:
    """Scene-bound visual intent consumed by search and provider policy.

    It contains neither narration nor unapproved lexical fallbacks; all
    representations arrive on the scene contract.
    """

    scene_id: int
    visual_type: str
    text_role: str
    text_language: str
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
    ordered_steps: tuple[str, ...]
    context: tuple[str, ...]
    forbidden: tuple[str, ...]
    event: str
    place: str
    period: str
    planning_mode: str
    space_topic: bool
    mechanistic: bool
    scientific_context: bool
    historical_scene: bool

    def __post_init__(self) -> None:
        if (isinstance(self.scene_id, bool)
                or not isinstance(self.scene_id, int) or self.scene_id <= 0):
            raise ValueError("visual plan scene_id must be positive")
        if any(not isinstance(alias, Alias) for alias in self.aliases):
            raise TypeError("visual plan aliases must be normalized")
        if any(not isinstance(rep, VisualRepresentation)
               for rep in self.representations):
            raise TypeError("visual plan representations must be normalized")
        expected_queries = tuple(rep.query for rep in self.representations)
        if self.visual_queries != expected_queries:
            raise ValueError("visual plan queries must mirror representations")

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "visual_type": self.visual_type,
            "text_role": self.text_role,
            "text_language": self.text_language,
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
            "ordered_steps": list(self.ordered_steps),
            "context": list(self.context),
            "forbidden": list(self.forbidden),
            "event": self.event,
            "place": self.place,
            "period": self.period,
            "planning_mode": self.planning_mode,
            "space_topic": self.space_topic,
            "mechanistic": self.mechanistic,
            "scientific_context": self.scientific_context,
            "historical_scene": self.historical_scene,
        }


@dataclass(frozen=True)
class VisualFallbackPlan:
    """Resolved synthetic visual instruction consumed by the local renderer."""

    scene_id: int
    strategy: str
    form: str
    subject: str
    subject_source: str
    visual_type: str
    text_role: str
    text_language: str
    narration: str
    quote_text: str
    period: str
    event: str
    place: str
    visual_entities: tuple[str, ...]
    context: tuple[str, ...]
    steps: tuple[str, ...]
    card_terms: tuple[str, ...]
    contrast_sides: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        strategies = {"form", "diagram"}
        forms = {"spotlight", "definition", "enumeration", "contrast",
                 "quote", "dated"}
        subject_sources = {
            "scene_event", "scene_subject", "scene_visual_entity",
            "approved_representation", "scene_context", "scene_place",
            "video_topic", "scene_identity_fallback",
        }
        if self.strategy not in {"card", "form", "diagram"}:
            raise ValueError(f"unsupported visual fallback strategy: {self.strategy}")
        if self.strategy == "form" and self.form not in forms:
            raise ValueError("form fallback requires a supported form")
        if self.strategy == "diagram" and self.form:
            raise ValueError("only form fallback may select a form")
        if self.strategy == "diagram" and len(self.steps) < 2:
            raise ValueError("diagram fallback requires at least two declared steps")
        if self.strategy == "diagram" and self.form:
            raise ValueError("diagram fallback cannot select a form")
        if self.form == "quote" and not self.quote_text.strip():
            raise ValueError("quote form requires explicit quote text")
        if self.form == "contrast" and len(self.contrast_sides) != 2:
            raise ValueError("contrast form requires two explicit sides")
        if self.scene_id <= 0:
            raise ValueError("visual fallback scene_id must be positive")
        if not self.subject.strip():
            raise ValueError("visual fallback requires a display subject")
        if self.subject_source not in subject_sources:
            raise ValueError("visual fallback requires a known subject source")
        if not self.text_role.strip():
            raise ValueError("visual fallback requires a text role")
        for name in ("visual_entities", "context", "steps", "card_terms",
                     "contrast_sides"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(
                    not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"visual fallback {name} must be a tuple of text")

    @property
    def id(self) -> int:
        """Renderer compatibility name for scene identity."""
        return self.scene_id

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "strategy": self.strategy,
            "form": self.form,
            "subject": self.subject,
            "subject_source": self.subject_source,
            "visual_type": self.visual_type,
            "text_role": self.text_role,
            "text_language": self.text_language,
            "quote_text": self.quote_text,
            "period": self.period,
            "event": self.event,
            "place": self.place,
            "visual_entities": list(self.visual_entities),
            "context": list(self.context),
            "steps": list(self.steps),
            "card_terms": list(self.card_terms),
            "contrast_sides": list(self.contrast_sides),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SearchQuery:
    query: str
    source: str
    representation: str = ""
    representation_kind: str = ""
    alias: str = ""
    variant: str = "entity"
    level: int = 1
    generic: bool = False

    def __post_init__(self) -> None:
        for field_name in ("query", "source", "representation",
                           "representation_kind", "alias", "variant"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"search query {field_name} must be text")
        if not self.query.strip():
            raise ValueError("search query text is required")
        if not self.source.strip():
            raise ValueError("search query source is required")
        if not self.variant.strip():
            raise ValueError("search query variant is required")
        if (isinstance(self.level, bool) or not isinstance(self.level, int)
                or self.level <= 0):
            raise ValueError("search query level must be positive")
        if not isinstance(self.generic, bool):
            raise TypeError("search query generic flag must be boolean")

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "source": self.source,
            "representation": self.representation,
            "representation_kind": self.representation_kind,
            "alias": self.alias,
            "variant": self.variant,
            "level": self.level,
            "generic": self.generic,
        }


@dataclass(frozen=True)
class SearchPlan:
    scene_id: int
    queries: tuple[SearchQuery, ...]

    def __post_init__(self) -> None:
        if (isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int)
                or self.scene_id <= 0):
            raise ValueError("search plan scene_id must be positive")
        if not isinstance(self.queries, tuple) or any(
                not isinstance(query, SearchQuery) for query in self.queries):
            raise TypeError("search plan queries must be a tuple of SearchQuery")
        keys = [query.query.casefold() for query in self.queries]
        if len(keys) != len(set(keys)):
            raise ValueError("search plan queries must be unique")

    @property
    def generic_queries(self) -> frozenset[str]:
        return frozenset(item.query.casefold() for item in self.queries if item.generic)

    def to_dict(self) -> dict:
        return {"scene_id": self.scene_id,
                "queries": [query.to_dict() for query in self.queries]}
