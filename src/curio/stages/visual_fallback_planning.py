"""Resolve an approved scene plan into one explicit local fallback visual."""

from __future__ import annotations

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
        form = _select_form(visual, genre, repeated, steps)
        reason = ("scene_subject_already_shown" if repeated else
                  "no_declared_steps_for_diagram"
                  if visual.visual_type == "mechanism" else
                  "scene_type_fallback")

    role = visual.text_role or _fallback_role(visual)
    return VisualFallbackPlan(
        scene_id=visual.scene_id,
        strategy=strategy,
        form=form,
        subject=subject,
        subject_source=subject_source,
        visual_type=visual.visual_type,
        text_role=role,
        narration=str(narration or ""),
        quote_text=str(narration or "") if role == "quote" else "",
        period=visual.period,
        event=visual.event,
        place=visual.place,
        visual_entities=visual.visual_entities,
        context=visual.context,
        steps=steps if strategy == "diagram" else (),
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
                 steps: tuple[str, ...]) -> str:
    representation_kinds = {rep.kind for rep in visual.representations}
    person = (visual.text_role == "person" or "person" in representation_kinds)
    if visual.text_role == "quote":
        return "quote"
    if person and visual.period:
        return "dated"
    if repeated:
        return "spotlight"

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
    kinds = {rep.kind for rep in visual.representations}
    if "person" in kinds:
        return "person"
    if visual.visual_type == "typographic":
        return "term"
    return "term"
