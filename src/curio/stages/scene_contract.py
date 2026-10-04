"""Runtime contracts for scene semantics produced by the scene planner.

The JSON representation remains intentionally stable while consumers migrate
from untyped dictionaries.  Provenance is additive and survives round trips.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field


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


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
