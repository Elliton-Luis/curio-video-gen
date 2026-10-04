"""Runtime contracts for scene semantics produced by the scene planner.

The JSON representation remains intentionally stable while consumers migrate
from untyped dictionaries.  Provenance is additive and survives round trips.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite


VISUAL_TYPES = ("literal", "mechanism", "historical_art", "conceptual",
                "typographic")


@dataclass(frozen=True)
class Alias:
    value: str
    source: str = "legacy_metadata"
    evidence: str = ""
    verified: bool = False

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("alias value must not be empty")


@dataclass(frozen=True)
class VisualRepresentation(Mapping[str, object]):
    """A visual concept with its planner provenance, not a loose keyword."""

    query: str
    kind: str = "related"
    level: int = 0
    source: str = "planner"
    evidence: str = ""

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("representation query must not be empty")
        if self.level < 0:
            raise ValueError("representation level must be non-negative")

    def __getitem__(self, key: str) -> object:
        if key not in {"query", "kind", "level", "source", "evidence"}:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(("query", "kind", "level", "source", "evidence"))

    def __len__(self) -> int:
        return 5

    @classmethod
    def from_value(cls, value: object, level: int = 0) -> "VisualRepresentation | None":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            query = str(value.get("query", value.get("visual", value.get("name", ""))) or "").strip()
            if not query:
                return None
            try:
                parsed_level = int(value.get("level", level) or 0)
            except (TypeError, ValueError):
                parsed_level = level
            return cls(query, str(value.get("kind", "related") or "related"),
                       max(0, parsed_level), str(value.get("source", "planner") or "planner"),
                       str(value.get("evidence", "") or ""))
        query = str(value or "").strip()
        return cls(query, level=level) if query else None

    def to_dict(self) -> dict[str, object]:
        result = {"query": self.query, "kind": self.kind,
                  "level": self.level, "source": self.source}
        if self.evidence:
            result["evidence"] = self.evidence
        return result


@dataclass(frozen=True)
class TimelineSpan:
    """Timing owned by timeline/render, kept outside scene meaning."""

    scene_id: int
    duration_estimate: float = 0.0
    start: float = 0.0
    end: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int) \
                or self.scene_id <= 0:
            raise ValueError("timeline scene_id must be positive")
        values = (self.duration_estimate, self.start, self.end)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not isfinite(value) or value < 0 for value in values):
            raise ValueError("timeline values must be finite and non-negative")
        if self.end < self.start:
            raise ValueError("timeline end must not precede start")

    def to_dict(self) -> dict[str, float | int]:
        return {"scene_id": self.scene_id,
                "duration_estimate": self.duration_estimate,
                "start": self.start, "end": self.end}


@dataclass
class VideoContext(Mapping[str, object]):
    """Canonical shared semantic context with legacy mapping access."""

    topic: str = ""
    primary_entities: list[str] = field(default_factory=list)
    secondary_entities: list[str] = field(default_factory=list)
    aliases: list[Alias] = field(default_factory=list)
    period: str = ""
    places: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.topic = str(self.topic or "")
        self.aliases = [a if isinstance(a, Alias) else Alias(str(a).strip())
                        for a in self.aliases if str(a).strip()]
        known = {"topic", "primary_entities", "secondary_entities", "aliases",
                 "alias_provenance", "period", "places", "events"}
        self.extra = {k: v for k, v in self.extra.items() if k not in known}

    @classmethod
    def from_value(cls, value: object) -> "VideoContext":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return cls()
        provenance = value.get("alias_provenance", [])
        provenance_by_value = {
            str(item.get("value", "")): item for item in provenance
            if isinstance(item, Mapping)
        } if isinstance(provenance, list) else {}
        aliases = []
        raw_aliases = value.get("aliases", [])
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        if isinstance(raw_aliases, list):
            for item in raw_aliases:
                if isinstance(item, Mapping):
                    alias = Alias(str(item.get("value", "")).strip(),
                                  str(item.get("source", "legacy_metadata")),
                                  str(item.get("evidence", "")),
                                  bool(item.get("verified", False)))
                else:
                    raw = str(item or "").strip()
                    info = provenance_by_value.get(raw, {})
                    if not raw:
                        continue
                    alias = Alias(raw, str(info.get("source", "legacy_metadata")),
                                  str(info.get("evidence", "")),
                                  bool(info.get("verified", False)))
                aliases.append(alias)
        known = {"topic", "primary_entities", "secondary_entities", "aliases",
                 "alias_provenance", "period", "places", "events"}
        return cls(
            topic=str(value.get("topic", "") or ""),
            primary_entities=_string_list(value.get("primary_entities", [])),
            secondary_entities=_string_list(value.get("secondary_entities", [])),
            aliases=aliases,
            period=str(value.get("period", "") or ""),
            places=_string_list(value.get("places", [])),
            events=_string_list(value.get("events", [])),
            extra={k: v for k, v in value.items() if k not in known},
        )

    def to_dict(self) -> dict[str, object]:
        result = dict(self.extra)
        if self.topic:
            result["topic"] = self.topic
        for key, values in (("primary_entities", self.primary_entities),
                            ("secondary_entities", self.secondary_entities),
                            ("places", self.places), ("events", self.events)):
            if values:
                result[key] = list(values)
        if self.period:
            result["period"] = self.period
        if self.aliases:
            result["aliases"] = [a.value for a in self.aliases]
            result["alias_provenance"] = [
                {"value": a.value, "source": a.source,
                 "evidence": a.evidence, "verified": a.verified}
                for a in self.aliases]
        return result

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class SemanticScene:
    """Validated scene meaning without timeline or render timing fields."""

    id: int
    narration: str
    source: str = "unknown"
    planning_mode: str = "unknown"
    visual_type: str = "literal"
    subject: str = ""
    subject_aliases: tuple[str, ...] = ()
    visual_entities: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    video_context: VideoContext = field(default_factory=VideoContext)
    visual_intent: str = ""
    visual_intent_structured: str = ""
    primary_entity: str = ""
    event: str = ""
    place: str = ""
    period: str = ""
    text_role: str = ""
    text_language: str = ""
    representations: tuple[VisualRepresentation, ...] = ()
    visual_queries: tuple[str, ...] = ()
    global_visual_queries: tuple[str, ...] = ()
    representation_rejections: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        for name in ("subject_aliases", "visual_entities", "context", "forbidden",
                     "visual_queries", "global_visual_queries"):
            value = getattr(self, name)
            if isinstance(value, str):
                value = (value,) if value.strip() else ()
            object.__setattr__(self, name, tuple(
                str(item).strip() for item in value if str(item).strip()))
        object.__setattr__(self, "video_context",
                           VideoContext.from_value(self.video_context))
        if self.planning_mode not in {"unknown", "llm", "deterministic"}:
            raise ValueError(f"unknown scene planning_mode: {self.planning_mode}")
        representations = tuple(
            rep for index, value in enumerate(self.representations)
            if (rep := VisualRepresentation.from_value(value, index)))
        known = {rep.query.casefold() for rep in representations}
        for query in self.visual_queries:
            key = query.casefold()
            if key and key not in known:
                representations += (VisualRepresentation(
                    query=query, kind="related", level=len(representations),
                    source="declared_scene_query"),)
                known.add(key)
        object.__setattr__(self, "representations", representations)
        object.__setattr__(self, "visual_queries",
                           tuple(rep.query for rep in representations))
        object.__setattr__(self, "representation_rejections", tuple(
            dict(item) for item in self.representation_rejections
            if isinstance(item, Mapping)))
        errors = self.contract_errors()
        if errors:
            raise ValueError(f"semantic scene {self.id} invalid: {', '.join(errors)}")

    @classmethod
    def from_chapter(cls, chapter, source: str = "unknown") -> "SemanticScene":
        """Project the canonical representations and their query mirror."""
        context = deepcopy(chapter.video_context)
        representations = tuple(
            rep for index, value in enumerate(chapter.representations)
            if (rep := VisualRepresentation.from_value(value, index)))
        visual_queries = tuple(rep.query for rep in representations)
        return cls(
            id=int(chapter.id), narration=str(chapter.narration), source=source,
            planning_mode=str(getattr(chapter, "planning_mode", "unknown")),
            visual_type=str(chapter.visual_type), subject=str(chapter.subject),
            subject_aliases=tuple(chapter.subject_aliases),
            visual_entities=tuple(chapter.visual_entities),
            context=tuple(chapter.context), forbidden=tuple(chapter.forbidden),
            video_context=context,
            visual_intent=str(chapter.visual_intent),
            visual_intent_structured=str(chapter.visual_intent_structured),
            primary_entity=str(chapter.primary_entity), event=str(chapter.event),
            place=str(chapter.place), period=str(chapter.period),
            text_role=str(chapter.text_role),
            text_language=str(chapter.text_language),
            representations=representations,
            visual_queries=visual_queries,
            global_visual_queries=tuple(chapter.global_visual_queries),
            representation_rejections=tuple(chapter.representation_rejections),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SemanticScene":
        """Load the semantic contract without routing through render Chapter."""
        if not isinstance(value, Mapping):
            raise ValueError("semantic scene must be an object")
        scene_id = value.get("id")
        narration = value.get("narration")
        if isinstance(scene_id, bool) or not isinstance(scene_id, int):
            raise ValueError("semantic scene id must be an integer")
        if not isinstance(narration, str):
            raise ValueError("semantic scene narration must be text")
        string_fields = ("source", "planning_mode", "visual_type", "subject",
                         "visual_intent", "visual_intent_structured",
                         "primary_entity", "event", "place", "period",
                         "text_role", "text_language")
        for field_name in string_fields:
            field_value = value.get(field_name, "")
            if not isinstance(field_value, str):
                raise ValueError(f"semantic scene {field_name} must be text")
        list_fields = ("subject_aliases", "visual_entities", "context", "forbidden",
                       "representations", "visual_queries", "global_visual_queries",
                       "representation_rejections")
        for field_name in list_fields:
            field_value = value.get(field_name, [])
            if not isinstance(field_value, (list, tuple)):
                raise ValueError(f"semantic scene {field_name} must be a list")
        for field_name in ("subject_aliases", "visual_entities", "context",
                           "forbidden", "visual_queries", "global_visual_queries"):
            if any(not isinstance(item, str) for item in value.get(field_name, [])):
                raise ValueError(f"semantic scene {field_name} entries must be text")
        context = value.get("video_context", {})
        if not isinstance(context, (Mapping, VideoContext)):
            raise ValueError("semantic scene video_context must be an object")
        if any(not isinstance(item, (Mapping, VisualRepresentation))
               for item in value.get("representations", [])):
            raise ValueError("semantic scene representations must be objects")
        if any(not isinstance(item, Mapping)
               for item in value.get("representation_rejections", [])):
            raise ValueError("semantic scene representation_rejections must be objects")
        return cls(
            id=scene_id, narration=narration,
            source=str(value.get("source", "unknown") or "unknown"),
            planning_mode=str(value.get("planning_mode", "unknown") or "unknown"),
            visual_type=str(value.get("visual_type", "literal") or "literal"),
            subject=str(value.get("subject", "") or ""),
            subject_aliases=tuple(value.get("subject_aliases", ())),
            visual_entities=tuple(value.get("visual_entities", ())),
            context=tuple(value.get("context", ())),
            forbidden=tuple(value.get("forbidden", ())),
            video_context=VideoContext.from_value(value.get("video_context", {})),
            visual_intent=str(value.get("visual_intent", "") or ""),
            visual_intent_structured=str(
                value.get("visual_intent_structured", "") or ""),
            primary_entity=str(value.get("primary_entity", "") or ""),
            event=str(value.get("event", "") or ""),
            place=str(value.get("place", "") or ""),
            period=str(value.get("period", "") or ""),
            text_role=str(value.get("text_role", "") or ""),
            text_language=str(value.get("text_language", "") or ""),
            representations=tuple(value.get("representations", ())),
            visual_queries=tuple(value.get("visual_queries", ())),
            global_visual_queries=tuple(value.get("global_visual_queries", ())),
            representation_rejections=tuple(
                value.get("representation_rejections", ())),
        )

    def contract_errors(self) -> list[str]:
        errors = []
        if self.id <= 0:
            errors.append("scene_id_positive")
        if not self.narration.strip():
            errors.append("narration_required")
        if self.visual_type not in VISUAL_TYPES:
            errors.append("visual_type_unknown")
        if self.planning_mode not in {"unknown", "llm", "deterministic"}:
            errors.append("planning_mode_unknown")
        if not isinstance(self.video_context, VideoContext):
            errors.append("video_context_not_normalized")
        if any(not isinstance(rep, VisualRepresentation)
               for rep in self.representations):
            errors.append("representation_not_normalized")
        return errors

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "narration": self.narration, "source": self.source,
            "planning_mode": self.planning_mode,
            "visual_type": self.visual_type, "subject": self.subject,
            "subject_aliases": list(self.subject_aliases),
            "visual_entities": list(self.visual_entities),
            "context": list(self.context), "forbidden": list(self.forbidden),
            "video_context": self.video_context.to_dict(),
            "visual_intent": self.visual_intent,
            "visual_intent_structured": self.visual_intent_structured,
            "primary_entity": self.primary_entity, "event": self.event,
            "place": self.place, "period": self.period,
            "text_role": self.text_role, "text_language": self.text_language,
            "representations": [rep.to_dict() for rep in self.representations],
            "visual_queries": list(self.visual_queries),
            "global_visual_queries": list(self.global_visual_queries),
            "representation_rejections": list(self.representation_rejections),
        }


@dataclass(frozen=True)
class ScenePlanResult:
    """Validated batch output: scene meaning and timing share only IDs."""

    semantic_scenes: tuple[SemanticScene, ...]
    timeline_spans: tuple[TimelineSpan, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("planner source is required")
        if not self.semantic_scenes:
            raise ValueError("planner must emit at least one scene")
        if len(self.semantic_scenes) != len(self.timeline_spans):
            raise ValueError("planner scene/timeline counts differ")
        scene_ids = tuple(scene.id for scene in self.semantic_scenes)
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("planner scene ids must be unique")
        span_ids = tuple(span.scene_id for span in self.timeline_spans)
        if scene_ids != span_ids:
            raise ValueError("planner timeline spans do not match scene order")
        errors = [scene.contract_errors() for scene in self.semantic_scenes]
        if any(errors):
            raise ValueError("planner emitted invalid semantic scene")

def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
