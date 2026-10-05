"""Build an explicit, narration-free plan for downstream media search."""

from __future__ import annotations

from .. import textnorm
from .scene_contract import VideoContext, VisualRepresentation
from .visual_contracts import VisualPlan

_MECHANISM_CUES = (
    "antibody", "antibodies", "antigen", "hormone", "hcg", "strip",
    "lateral flow", "control line", "test line", "nanoparticle", "molecule",
    "microscope", "test tube", "pregnancy test", "anticorpo", "anticorpos",
    "hormonio", "hormônio", "tira", "linha de controle", "molecula",
    "molécula", "microscopio", "microscópio", "laboratorio", "laboratório",
    "gravidez",
)
_HISTORY_CUES = (
    "batalha", "battle", "império", "imperio", "empire", "século",
    "seculo", "century", "revolução", "revolution", "guerra", "war",
)
_SCIENCE_CONTEXT_CUES = ("experiment", "experimento", "science", "ciência",
                         "research", "pesquisa")


def build_visual_plan(scene) -> VisualPlan:
    """Close scene-level visual inputs into a typed plan before acquisition.

    Meaning and representations arrive on the semantic scene; this projection
    adds only typed visual policy and provider selection context.
    """
    context = VideoContext.from_value(getattr(scene, "video_context", {}))
    reps = tuple(rep for value in (getattr(scene, "representations", []) or [])
                 if (rep := VisualRepresentation.from_value(value)))
    visual_queries = tuple(rep.query for rep in reps)
    planning_mode = str(getattr(scene, "planning_mode", "unknown") or "unknown")
    subject = str(getattr(scene, "subject", "") or "")
    subject_aliases = _strings(getattr(scene, "subject_aliases", []))
    visual_entities = _strings(getattr(scene, "visual_entities", []))
    scene_context = _strings(getattr(scene, "context", []))
    lexical_context = " ".join((context.topic,
                                *(alias.value for alias in context.aliases),
                                str(getattr(scene, "visual_intent", "") or ""),
                                str(getattr(scene, "visual_intent_structured", "") or ""),
                                *(rep.query for rep in reps), *visual_queries, subject,
                                *subject_aliases, *visual_entities, *scene_context))
    folded = lexical_context.casefold()
    visual_type = str(getattr(scene, "visual_type", "") or "literal")
    kinds = {rep.kind for rep in reps}
    return VisualPlan(
        scene_id=int(getattr(scene, "id", 0) or 0),
        visual_type=visual_type,
        text_role=str(getattr(scene, "text_role", "") or ""),
        text_language=str(getattr(scene, "text_language", "") or ""),
        visual_intent=str(getattr(scene, "visual_intent", "") or ""),
        visual_intent_structured=str(getattr(scene, "visual_intent_structured", "") or ""),
        topic=context.topic,
        aliases=tuple(context.aliases),
        primary_entities=tuple(context.primary_entities),
        representations=reps,
        visual_queries=visual_queries,
        global_visual_queries=tuple(_strings(
            getattr(scene, "global_visual_queries", []))),
        subject=subject,
        subject_aliases=subject_aliases,
        visual_entities=visual_entities,
        ordered_steps=tuple(_strings(getattr(scene, "visual_steps", []))),
        context=scene_context,
        forbidden=tuple(_strings(getattr(scene, "forbidden", []))),
        event=str(getattr(scene, "event", "") or ""),
        place=str(getattr(scene, "place", "") or ""),
        period=str(getattr(scene, "period", "") or ""),
        planning_mode=planning_mode,
        space_topic=textnorm.is_space_topic(lexical_context),
        mechanistic=any(cue in folded for cue in _MECHANISM_CUES),
        scientific_context=(visual_type == "mechanism"
                            or any(cue in folded for cue in _MECHANISM_CUES)
                            or any(cue in folded for cue in _SCIENCE_CONTEXT_CUES)),
        historical_scene=(visual_type == "historical_art"
                          or bool(kinds & {"event", "person", "empire", "army"})
                          or any(cue in folded for cue in _HISTORY_CUES)),
    )


def _strings(values) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(value).strip() for value in values
                               if str(value).strip()))
