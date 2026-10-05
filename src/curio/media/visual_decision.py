"""Validated audit envelope for a scene's persisted visual decision."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping

from ..stages.media_selection import SelectionDecision


_TEXT_FIELDS = {
    "topic", "visual_intent", "primary_entity", "fallback",
    "search_exhaustion_reason", "fallback_level",
}
_OBJECT_FIELDS = {"visual_plan", "fallback_plan", "search_plan", "selected"}
_LIST_FIELDS = {
    "entities", "representations", "representations_discarded", "aliases",
    "queries", "providers_consulted", "candidates",
}


@dataclass(frozen=True)
class VisualDecision:
    """Typed selection plus validated, compatibility-preserving audit fields.

    ``to_dict`` is the persistence boundary. Unknown fields and omitted legacy
    fields survive round trips, while mutations go through explicit methods.
    """

    selection: SelectionDecision
    _payload: Mapping[str, object] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.selection, SelectionDecision):
            raise TypeError("visual decision requires SelectionDecision")
        if not isinstance(self._payload, Mapping):
            raise TypeError("visual decision audit must be an object")
        object.__setattr__(self, "_payload", MappingProxyType(
            deepcopy(dict(self._payload))))
        for name in _TEXT_FIELDS:
            if name in self._payload and not isinstance(self._payload[name], str):
                raise TypeError(f"visual decision {name} must be text")
        for name in _OBJECT_FIELDS:
            value = self._payload.get(name)
            if value is not None and not isinstance(value, Mapping):
                raise TypeError(f"visual decision {name} must be an object or null")
        for name in _LIST_FIELDS:
            value = self._payload.get(name)
            if value is not None and (not isinstance(value, list)
                    or any(not isinstance(item, (str, dict)) for item in value)):
                raise TypeError(f"visual decision {name} must be a list")
        exhausted = self._payload.get("search_exhausted")
        if exhausted is not None and not isinstance(exhausted, bool):
            raise TypeError("visual decision search_exhausted must be boolean")
        raw_selection = self._payload.get("selection")
        if raw_selection is None:
            raise ValueError("visual decision requires selection")
        parsed = SelectionDecision.from_dict(raw_selection)
        if parsed != self.selection:
            raise ValueError("visual decision selection payload is inconsistent")

    @classmethod
    def create(cls, selection: SelectionDecision, *,
               payload: Mapping[str, object] | None = None,
               **fields: object) -> "VisualDecision":
        if not isinstance(selection, SelectionDecision):
            raise TypeError("visual decision requires SelectionDecision")
        data = deepcopy(dict(payload or {}))
        data.update(fields)
        data["selection"] = selection.to_dict()
        return cls(selection, MappingProxyType(data))

    @classmethod
    def from_dict(cls, value: object) -> "VisualDecision":
        if not isinstance(value, Mapping):
            raise TypeError("visual decision must be an object")
        raw = deepcopy(dict(value))
        selection_data = raw.get("selection")
        if selection_data is None:
            raise ValueError("visual decision requires selection")
        selection = SelectionDecision.from_dict(selection_data)
        return cls(selection, MappingProxyType(raw))

    def with_selection(self, selection: SelectionDecision, *,
                       selected: Mapping[str, object] | None = None,
                       fallback: str | None = None) -> "VisualDecision":
        if not isinstance(selection, SelectionDecision):
            raise TypeError("visual decision update requires SelectionDecision")
        data = deepcopy(dict(self._payload))
        data["selection"] = selection.to_dict()
        if selected is not None:
            data["selected"] = deepcopy(dict(selected))
        if fallback is not None:
            data["fallback"] = fallback
        return VisualDecision(selection, MappingProxyType(data))

    def to_dict(self) -> dict:
        return deepcopy(dict(self._payload))
