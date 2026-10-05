"""Validated scene decision contract with a compatibility JSON projection."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

from ..stages.media_selection import SelectionDecision


_TEXT_FIELDS = (
    "topic", "visual_intent", "primary_entity", "fallback",
    "search_exhaustion_reason", "fallback_level",
)
_OBJECT_FIELDS = ("visual_plan", "fallback_plan", "search_plan", "selected")
_LIST_FIELDS = (
    "entities", "representations", "representations_discarded", "aliases",
    "queries", "providers_consulted", "candidates",
)
_KNOWN_FIELDS = frozenset(("selection", *_TEXT_FIELDS, *_OBJECT_FIELDS,
                           *_LIST_FIELDS, "search_exhausted"))


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_value(item)
                             for key, item in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return deepcopy(value)


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class VisualDecision:
    """Explicit in-memory facts for one visual choice.

    ``from_dict`` and ``to_dict`` are the legacy project-format adapter.
    Known fields have named attributes; unknown keys and absent known fields
    are preserved so reading and rewriting an older project is lossless.
    Query/candidate audit rows remain JSON objects until their own contracts
    are migrated.
    """

    selection: SelectionDecision
    topic: str | None = None
    visual_plan: Mapping[str, object] | None = None
    fallback_plan: Mapping[str, object] | None = None
    search_plan: Mapping[str, object] | None = None
    visual_intent: str | None = None
    entities: tuple[str, ...] | None = None
    primary_entity: str | None = None
    representations: tuple[object, ...] | None = None
    representations_discarded: tuple[object, ...] | None = None
    aliases: tuple[object, ...] | None = None
    queries: tuple[Mapping[str, object], ...] | None = None
    providers_consulted: tuple[str, ...] | None = None
    candidates: tuple[Mapping[str, object], ...] | None = None
    selected: Mapping[str, object] | None = None
    fallback: str | None = None
    search_exhausted: bool | None = None
    search_exhaustion_reason: str | None = None
    fallback_level: str | None = None
    _present_fields: frozenset[str] = field(default_factory=frozenset,
                                             repr=False, compare=False)
    _extensions: Mapping[str, object] = field(default_factory=dict,
                                               repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.selection, SelectionDecision):
            raise TypeError("visual decision requires SelectionDecision")
        for name in _TEXT_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"visual decision {name} must be text")
        for name in _OBJECT_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, Mapping):
                raise TypeError(f"visual decision {name} must be an object or null")
            if value is not None:
                object.__setattr__(self, name, _freeze_mapping(value))
        for name in _LIST_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, tuple):
                raise TypeError(f"visual decision {name} must be a tuple")
            if name in {"entities", "providers_consulted"}:
                if any(not isinstance(item, str) for item in value):
                    raise TypeError(f"visual decision {name} must contain text")
            elif name in {"queries", "candidates"}:
                if any(not isinstance(item, Mapping) for item in value):
                    raise TypeError(f"visual decision {name} must contain objects")
                object.__setattr__(self, name, tuple(
                    _freeze_mapping(item) for item in value))
            elif any(not isinstance(item, (str, Mapping)) for item in value):
                raise TypeError(f"visual decision {name} has invalid items")
            else:
                object.__setattr__(self, name, tuple(
                    _freeze_mapping(item) if isinstance(item, Mapping) else item
                    for item in value))
        if self.search_exhausted is not None and not isinstance(
                self.search_exhausted, bool):
            raise TypeError("visual decision search_exhausted must be boolean")
        if not isinstance(self._present_fields, frozenset):
            raise TypeError("visual decision field presence must be immutable")
        if self._present_fields - _KNOWN_FIELDS:
            raise ValueError("visual decision has unknown present field markers")
        if "selection" not in self._present_fields:
            object.__setattr__(self, "_present_fields",
                               self._present_fields | {"selection"})
        if not isinstance(self._extensions, Mapping):
            raise TypeError("visual decision extensions must be an object")
        object.__setattr__(self, "_extensions",
                           _freeze_mapping(self._extensions))

    @classmethod
    def create(cls, selection: SelectionDecision, *,
               payload: Mapping[str, object] | None = None,
               **fields: object) -> "VisualDecision":
        """Build through the same validation used for persisted decisions."""
        if not isinstance(selection, SelectionDecision):
            raise TypeError("visual decision requires SelectionDecision")
        unknown = set(fields) - (_KNOWN_FIELDS - {"selection"})
        if unknown:
            raise ValueError("unknown VisualDecision fields: "
                             + ", ".join(sorted(unknown)))
        data = deepcopy(dict(payload or {}))
        data.update(fields)
        data["selection"] = selection.to_dict()
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, value: object) -> "VisualDecision":
        if not isinstance(value, Mapping):
            raise TypeError("visual decision must be an object")
        raw = deepcopy(dict(value))
        selection_data = raw.get("selection")
        if selection_data is None:
            raise ValueError("visual decision requires selection")
        selection = SelectionDecision.from_dict(selection_data)
        parsed: dict[str, object] = {name: raw.get(name) for name in _TEXT_FIELDS}
        for name in _OBJECT_FIELDS:
            item = raw.get(name)
            if item is not None and not isinstance(item, Mapping):
                raise TypeError(f"visual decision {name} must be an object or null")
            parsed[name] = item
        for name in _LIST_FIELDS:
            item = raw.get(name)
            if item is not None:
                if not isinstance(item, (list, tuple)):
                    raise TypeError(f"visual decision {name} must be a list")
                item = tuple(item)
            parsed[name] = item
        exhausted = raw.get("search_exhausted")
        if exhausted is not None and not isinstance(exhausted, bool):
            raise TypeError("visual decision search_exhausted must be boolean")
        parsed["search_exhausted"] = exhausted
        parsed["_present_fields"] = frozenset(raw) & _KNOWN_FIELDS
        parsed["_extensions"] = {
            name: item for name, item in raw.items() if name not in _KNOWN_FIELDS}
        return cls(selection=selection, **parsed)

    def with_selection(self, selection: SelectionDecision, *,
                       selected: Mapping[str, object] | None = None,
                       fallback: str | None = None) -> "VisualDecision":
        if not isinstance(selection, SelectionDecision):
            raise TypeError("visual decision update requires SelectionDecision")
        data = self.to_dict()
        data["selection"] = selection.to_dict()
        if selected is not None:
            data["selected"] = dict(selected)
        if fallback is not None:
            data["fallback"] = fallback
        return VisualDecision.from_dict(data)

    def to_dict(self) -> dict:
        """Project explicit fields into the persisted media.json schema."""
        data = _json_value(self._extensions)
        for name in self._present_fields:
            if name == "selection":
                data[name] = self.selection.to_dict()
            else:
                data[name] = _json_value(getattr(self, name))
        data["selection"] = self.selection.to_dict()
        return data
