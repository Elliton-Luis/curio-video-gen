"""Resolve an approved scene plan into one explicit local fallback visual."""

from __future__ import annotations

import re

from .visual_contracts import VisualFallbackPlan, VisualPlan

_FORM_NAMES = {
    "spotlight", "definition", "enumeration", "contrast", "quote", "dated",
}
_KIND_PRIORITY = {
    "event": 0, "person": 1, "monument": 2, "artifact": 3,
    "army": 4, "object": 5, "place": 6, "entity": 7, "related": 8,
}
_NON_DISPLAY_SOURCES = {
    "entity_context", "verified_entity_context", "declared_scene_query",
}
_FORM_BY_TYPE = {
    "typographic": "definition",
    "mechanism": "spotlight",
    "conceptual": "definition",
    "historical_art": "spotlight",
    "literal": "spotlight",
}


class VisualDiversityState:
    """Selection history used only to vary synthetic fallback presentation."""

    _NEGATIONS = {"lack", "falta", "missing", "absence", "no", "nao",
                  "não", "nothing", "nada", "sem"}

    def __init__(self) -> None:
        self.forms: list[str] = []
        self.subjects: list[str] = []

    def least_used_form(self, forms: tuple[str, ...]) -> str:
        counts = {form: self.forms.count(form) for form in forms}
        return min(forms, key=lambda form: counts[form])

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    @classmethod
    def _core(cls, value: str) -> set[str]:
        return {token for token in cls._norm(value).split()
                if token not in cls._NEGATIONS}

    def subject_repeated(self, subject: str) -> bool:
        normalized = self._norm(subject)
        if not normalized:
            return False
        for seen in self.subjects:
            if normalized == seen:
                return True
            current_core, seen_core = self._core(subject), set(seen.split())
            if current_core and seen_core and len(current_core & seen_core) / len(
                    current_core | seen_core) >= 0.5:
                return True
        return False

    def record(self, subject: str, form: str) -> None:
        if form:
            self.forms.append(form)
        normalized = self._norm(subject)
        if normalized and normalized not in self.subjects:
            self.subjects.append(normalized)


def build_visual_fallback_plan(visual: VisualPlan, narration: str,
                               genre: str = "", state=None
                               ) -> VisualFallbackPlan:
    """Choose synthetic strategy and display subject from approved scene data.

    Narration is carried verbatim for display. This planner never extracts
    search terms from it; providers, scoring and rendering are already done.
    """
    steps = tuple(dict.fromkeys(visual.ordered_steps))[:4]
    subject, subject_source = _display_subject(visual, state)
    repeated = bool(state and state.subject_repeated(subject))

    if visual.visual_type == "mechanism" and len(steps) >= 2:
        strategy, form = "diagram", ""
        reason = "mechanism_has_declared_ordered_steps"
    else:
        strategy = "form"
        form = _select_form(visual, genre, repeated, steps, state)
        reason = ("scene_subject_already_shown" if repeated else
                  "no_declared_steps_for_diagram"
                  if visual.visual_type == "mechanism" else
                  "scene_type_fallback")

    role = visual.text_role or _fallback_role(visual)
    if form == "quote" and not visual.text_role:
        role = "quote"
    return VisualFallbackPlan(
        scene_id=visual.scene_id,
        strategy=strategy,
        form=form,
        subject=subject,
        subject_source=subject_source,
        visual_type=visual.visual_type,
        text_role=role,
        text_language=visual.text_language,
        narration=str(narration or ""),
        quote_text=str(narration or "") if form == "quote" else "",
        period=visual.period,
        event=visual.event,
        place=visual.place,
        visual_entities=visual.visual_entities,
        context=visual.context,
        steps=steps if strategy == "diagram" else (),
        card_terms=tuple(_card_terms(visual, subject)),
        contrast_sides=steps[:2] if form == "contrast" else (),
        reason=reason,
    )


def _display_subject(visual: VisualPlan, state=None) -> tuple[str, str]:
    if visual.event:
        return visual.event, "scene_event"
    if visual.subject and visual.subject.casefold() != visual.topic.casefold():
        return visual.subject, "scene_subject"
    if visual.visual_entities:
        return visual.visual_entities[0], "scene_visual_entity"

    candidates = [rep for rep in visual.representations
                  if rep.source not in _NON_DISPLAY_SOURCES]
    candidates.sort(key=lambda rep: (
        _KIND_PRIORITY.get(rep.kind, 9), rep.level,
        visual.representations.index(rep)))
    if state and candidates:
        fresh = [rep for rep in candidates
                 if not state.subject_repeated(rep.query)]
        if fresh:
            candidates = fresh
    if candidates:
        return candidates[0].query, "approved_representation"
    if visual.context:
        return visual.context[0], "scene_context"
    if visual.place:
        return visual.place, "scene_place"
    if visual.subject:
        return visual.subject, "scene_subject"
    if visual.topic:
        return visual.topic, "video_topic"
    return f"Cena {visual.scene_id}", "scene_identity_fallback"


def _select_form(visual: VisualPlan, genre: str, repeated: bool,
                 steps: tuple[str, ...], state=None) -> str:
    representation_kinds = {rep.kind for rep in visual.representations}
    person = (visual.text_role == "person" or "person" in representation_kinds)
    if visual.text_role == "quote":
        return "quote"
    if person and visual.period:
        return "dated"
    if repeated:
        candidates = ("spotlight", "definition", "enumeration") if steps else (
            "spotlight", "definition")
        return state.least_used_form(candidates) if state else candidates[0]

    from . import editorial
    profile = editorial.get(genre)
    preferred = (profile.visual.preferred_forms[0]
                 if profile is not None and profile.visual.preferred_forms else "")
    form = preferred if preferred in _FORM_NAMES else _FORM_BY_TYPE.get(
        visual.visual_type, "spotlight")
    if form == "enumeration" and not steps:
        return "spotlight"
    if form == "contrast":
        intent = visual.visual_intent_structured.casefold()
        return ("contrast" if len(steps) >= 2
                and any(term in intent for term in ("contrast", "versus", "vs."))
                else "spotlight")
    return form


def _fallback_role(visual: VisualPlan) -> str:
    if visual.text_language.casefold() in {"la", "latin"}:
        return "latin"
    kinds = {rep.kind for rep in visual.representations}
    if "person" in kinds:
        return "person"
    if visual.visual_type == "typographic":
        return "term"
    return "term"


def _card_terms(visual: VisualPlan, subject: str) -> list[str]:
    """Close typography terms before rendering; never derive from queries."""
    if visual.visual_type != "typographic":
        return []
    display_subject = subject.strip().casefold()
    terms = [term for term in visual.visual_entities
             if term.strip().casefold() != display_subject]
    return list(dict.fromkeys(terms))[:4]
