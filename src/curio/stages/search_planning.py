"""Pure deterministic query planning from a narration-free VisualPlan."""

from __future__ import annotations

import re

from .. import textnorm
from . import editorial
from .visual_contracts import SearchPlan, SearchQuery, VisualPlan

SPACE_GENERIC_QUERIES = ("night sky", "stars", "galaxy", "space telescope")
SCIENCE_GENERIC_QUERIES = (
    "laboratory", "microscope", "science", "research", "experiment", "test tube",
)
ART_MEDIA_HINTS = (
    "painting", "fresco", "engraving", "woodcut", "illustration", "manuscript",
    "altarpiece", "mosaic", "drawing", "etching",
)


def build_search_plan(plan: VisualPlan, genre: str = "") -> SearchPlan:
    """Generate a bounded, ordered catalog query tree with provenance."""
    seen: set[str] = set()
    planned: list[SearchQuery] = []
    topic = plan.topic.strip()
    aliases = [alias.value.strip() for alias in plan.aliases if alias.value.strip()]
    anchor_alias = next((alias for alias in aliases
                         if topic and alias.casefold() != topic.casefold()), topic)
    from .scoring import _tokens

    def contextual(query: str) -> str:
        tokens = set(_tokens(query))
        anchors = [topic, *aliases]
        if any(set(_tokens(anchor)).issubset(tokens)
               for anchor in anchors if _tokens(anchor)):
            return query
        return f"{query} {anchor_alias}".strip()

    def add(query: str, *, source: str, representation: str = "",
            kind: str = "", alias: str = "", variant: str = "entity",
            level: int = 1, generic: bool = False) -> None:
        query = re.sub(r"[^\w\s-]", "", query or "").strip()
        for anchor in [topic, *aliases]:
            if anchor:
                query = re.sub(rf"\b({re.escape(anchor)})\s+\1\b", r"\1",
                               query, flags=re.I)
        if not query or query.casefold() in seen:
            return
        seen.add(query.casefold())
        used_alias = alias or next((name for name in aliases
                                    if name.casefold() in query.casefold()), "")
        planned.append(SearchQuery(query, source, representation, kind,
                                  used_alias, variant, level, generic))

    ai = list(plan.visual_queries)
    representations = sorted(plan.representations, key=lambda item: item.level)
    names = [set(_tokens(name)) for name in [plan.subject, *plan.subject_aliases]
             if _tokens(name)]
    same_subject = len(ai) >= 2 and all(
        any(name.issubset(set(_tokens(query))) for name in names) for query in ai[:2])

    if not plan.local_fallback:
        for rep in representations:
            focus, kind = rep.query.strip(), rep.kind
            add(contextual(focus), source="scene_representation",
                representation=focus, kind=kind, alias=anchor_alias,
                level=max(1, rep.level + 1))
            for medium in _media_variants(kind, plan.visual_type, historical=True):
                add(f"{focus} {medium} {anchor_alias}".strip(),
                    source="representation_variant", representation=focus,
                    kind=kind, alias=anchor_alias, variant=medium,
                    level=max(2, rep.level + 2))

    structured = bool(representations or plan.visual_intent_structured or topic)
    if plan.local_fallback and topic:
        topic_names = [topic, *aliases, *plan.primary_entities]
        anchor_sets = [set(_tokens(name)) for name in topic_names if _tokens(name)]

        def topic_representation(rep):
            tokens = set(_tokens(rep.query))
            return (any(tokens.issubset(anchor) for anchor in anchor_sets)
                    or rep.kind == "empire")

        specific = [rep for rep in representations if not topic_representation(rep)]
        to_search = specific or [rep for rep in representations if topic_representation(rep)]
        for rep in to_search:
            focus, kind = rep.query.strip(), rep.kind
            add(f"{focus} {anchor_alias}", source="scene_representation",
                representation=focus, kind=kind, alias=anchor_alias,
                level=max(1, rep.level + 1))
            if anchor_alias.casefold() != topic.casefold():
                add(f"{focus} {topic}", source="topic_context",
                    representation=focus, kind=kind, alias=topic,
                    level=max(2, rep.level + 1))
            if plan.period:
                add(f"{focus} {plan.period} {anchor_alias}",
                    source="representation_period", representation=focus,
                    kind=kind, alias=anchor_alias, variant=plan.period,
                    level=max(2, rep.level + 2))
            for medium in _media_variants(kind, plan.visual_type, historical=False):
                add(f"{focus} {medium} {anchor_alias}",
                    source="representation_variant", representation=focus,
                    kind=kind, alias=anchor_alias, variant=medium,
                    level=max(2, rep.level + 2))
        for entity in plan.primary_entities[:2]:
            add(f"{entity} {topic}", source="topic_entity", representation=entity,
                alias=topic, level=4)
        add(f"{anchor_alias} historical map", source="topic_fallback",
            representation=topic, alias=anchor_alias, variant="historical map",
            level=5, generic=True)

    if len(ai) >= 2 and not same_subject and not plan.local_fallback:
        add(contextual(" ".join(ai[:2])), source="combined_scene_queries",
            representation=" / ".join(ai[:2]), alias=anchor_alias, level=3)
    if not plan.local_fallback:
        for term in ai:
            add(contextual(term), source="scene_query", representation=term,
                alias=anchor_alias, level=3)

    if not plan.local_fallback and not ai and not representations and plan.subject:
        for alias in plan.subject_aliases:
            add(alias, source="subject_alias", representation=plan.subject,
                alias=alias, level=2)
        add(plan.subject, source="scene_subject", representation=plan.subject,
            level=2)
    if not ai and not (plan.local_fallback and topic) and not structured:
        for term in plan.local_query_seeds:
            add(term, source="local_query_seed", representation=term, level=3)

    for term in plan.global_visual_queries:
        add(term, source="global_context", representation=term, alias=anchor_alias,
            level=4)

    if plan.visual_type == "historical_art":
        art_terms = ([rep.query for rep in representations[:2]]
                     or ([] if plan.local_fallback else ai[:2])
                     or list(plan.visual_entities[:2])
                     or [plan.subject or ""])
        for term in art_terms:
            for medium in ART_MEDIA_HINTS:
                add(f"{term} {medium}", source="historical_visual_variant",
                    representation=term, variant=medium, level=4)

    if ai and not plan.local_fallback:
        for term in ai:
            if topic and not set(_tokens(topic)).issubset(set(_tokens(term))):
                add(f"{term} {anchor_alias}", source="scene_query_contextual",
                    representation=term, alias=anchor_alias, level=3)
            else:
                add(term, source="scene_query", representation=term, level=2)
        if plan.mechanistic:
            add(" ".join(ai[:2]) + " diagram", source="mechanism_visual_variant",
                representation=" / ".join(ai[:2]), variant="diagram", level=4)

    for term in _generic_queries(genre, plan):
        add(term, source="genre_fallback", variant=term, level=5, generic=True)
    if not planned and plan.space_topic:
        add("black hole", source="space_topic_fallback", representation="black hole",
            level=4)
    return SearchPlan(plan.scene_id, tuple(planned[:8]))


def _media_variants(kind: str, visual_type: str, historical: bool) -> tuple[str, ...]:
    if kind == "event":
        return ("painting", "engraving", "illustration")
    if kind == "person":
        return ("portrait", "bust", "painting", "engraving")
    if kind == "monument":
        return ("monument", "historical photograph", "engraving")
    if kind == "army":
        return ("army", "uniform", "cavalry", "military engraving")
    if kind == "artifact":
        return ("artifact", "museum object", "historical illustration")
    if kind in (("place", "empire", "map") if historical else ("place", "empire")):
        return ("historical map", "painting", "engraving")
    if historical and visual_type == "historical_art" and kind in ("entity", "related"):
        return ("painting", "engraving", "illustration")
    if not historical and kind == "entity":
        return ("painting", "engraving", "artifact")
    return ()


def _generic_queries(genre: str, plan: VisualPlan) -> tuple[str, ...]:
    if plan.space_topic:
        return SPACE_GENERIC_QUERIES
    if (plan.visual_type != "historical_art"
            and (plan.scientific_context or plan.mechanistic
                 or plan.visual_type == "mechanism")):
        return SCIENCE_GENERIC_QUERIES
    adapter = editorial.get(genre)
    if adapter and adapter.generic_media_queries:
        return adapter.generic_media_queries
    return SCIENCE_GENERIC_QUERIES if genre else ()
