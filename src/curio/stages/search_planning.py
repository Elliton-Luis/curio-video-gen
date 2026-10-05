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
    aliases = [alias.value.strip() for alias in plan.aliases
               if alias.value.strip() and alias.verified]
    anchor_alias = next((alias for alias in aliases
                         if topic and alias.casefold() != topic.casefold()), topic)
    def contextual(query: str) -> str:
        anchors = [topic, *aliases]
        if any(_contains_phrase(query, anchor) for anchor in anchors if anchor):
            return query
        return _with_context(query, anchor_alias)

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
    deterministic = plan.planning_mode == "deterministic"
    representations = sorted(
        plan.representations,
        key=lambda item: (_representation_priority(item), item.level))
    query_only_sources = {"declared_scene_query", "entity_context",
                          "verified_entity_context"}
    semantic_representations = [
        rep for rep in representations if rep.source not in query_only_sources]
    legacy_unanchored_queries = (
        bool(representations) and not topic and not aliases
        and all(rep.source == "legacy_scene_query" for rep in representations))
    names = [set(textnorm.tokens(name))
             for name in [plan.subject, *plan.subject_aliases]
             if textnorm.tokens(name)]
    same_subject = len(ai) >= 2 and all(
        any(name.issubset(set(textnorm.tokens(query))) for name in names)
        for query in ai[:2])

    if not deterministic and not legacy_unanchored_queries:
        for rep in semantic_representations:
            focus, kind = rep.query.strip(), rep.kind
            add(contextual(focus), source="scene_representation",
                representation=focus, kind=kind, alias=anchor_alias,
                level=max(1, rep.level + 1))
            for medium in _media_variants(kind, plan.visual_type, historical=True):
                if not _already_contains(focus, medium):
                    add(_with_context(f"{focus} {medium}", anchor_alias),
                        source="representation_variant", representation=focus,
                        kind=kind, alias=anchor_alias, variant=medium,
                        level=max(2, rep.level + 2))

    if deterministic and topic:
        topic_names = [topic, *aliases, *plan.primary_entities]
        anchor_sets = [set(textnorm.tokens(name)) for name in topic_names
                       if textnorm.tokens(name)]

        def topic_representation(rep):
            tokens = set(textnorm.tokens(rep.query))
            return (any(tokens.issubset(anchor) for anchor in anchor_sets)
                    or rep.kind == "empire")

        specific = [rep for rep in representations if not topic_representation(rep)]
        to_search = specific or [rep for rep in representations if topic_representation(rep)]
        for rep in to_search:
            focus, kind = rep.query.strip(), rep.kind
            add(_with_context(focus, anchor_alias), source="scene_representation",
                representation=focus, kind=kind, alias=anchor_alias,
                level=max(1, rep.level + 1))
            if anchor_alias.casefold() != topic.casefold():
                add(_with_context(focus, topic), source="topic_context",
                    representation=focus, kind=kind, alias=topic,
                    level=max(2, rep.level + 1))
            if plan.period:
                add(f"{focus} {plan.period} {anchor_alias}",
                    source="representation_period", representation=focus,
                    kind=kind, alias=anchor_alias, variant=plan.period,
                    level=max(2, rep.level + 2))
            for medium in _media_variants(kind, plan.visual_type, historical=False):
                if not _already_contains(focus, medium):
                    add(_with_context(f"{focus} {medium}", anchor_alias),
                        source="representation_variant", representation=focus,
                        kind=kind, alias=anchor_alias, variant=medium,
                        level=max(2, rep.level + 2))
        for entity in plan.primary_entities[:2]:
            add(_with_context(entity, topic), source="topic_entity",
                representation=entity, alias=topic, level=4)
        historical_query_context = (
            genre == "history" or plan.visual_type == "historical_art"
            or bool(plan.period)
            or any(rep.kind in {"empire", "army", "monument", "artifact", "map"}
                   for rep in representations))
        if historical_query_context:
            add(_with_context(anchor_alias, "historical map"),
                source="topic_fallback", representation=topic,
                alias=anchor_alias, variant="historical map",
                level=5, generic=True)

    if deterministic and not topic:
        # A recovered/local scene without global context still has explicit
        # scene anchors. Search those declared concepts; do not replace them
        # with a generic topic query or re-extract narration here.
        for rep in representations:
            add(rep.query, source="local_scene_representation",
                representation=rep.query, kind=rep.kind,
                level=max(1, rep.level + 1))

    if len(ai) >= 2 and not same_subject and not deterministic:
        add(contextual(" ".join(ai[:2])), source="combined_scene_queries",
            representation=" / ".join(ai[:2]), alias=anchor_alias, level=3)
    if not deterministic:
        for term in ai:
            add(contextual(term), source="scene_query", representation=term,
                alias=anchor_alias, level=3)

    if not deterministic and not ai and not representations and plan.subject:
        for alias in plan.subject_aliases:
            add(alias, source="subject_alias", representation=plan.subject,
                alias=alias, level=2)
        add(plan.subject, source="scene_subject", representation=plan.subject,
            level=2)
    for term in plan.global_visual_queries:
        add(term, source="global_context", representation=term, alias=anchor_alias,
            level=4)

    if plan.visual_type == "historical_art":
        art_terms = ([rep.query for rep in representations[:2]]
                     or ([] if deterministic else ai[:2])
                     or list(plan.visual_entities[:2])
                     or [plan.subject or ""])
        for term in art_terms:
            for medium in ART_MEDIA_HINTS:
                if not _already_contains(term, medium):
                    add(_with_context(f"{term} {medium}", anchor_alias),
                        source="historical_visual_variant",
                        representation=term, variant=medium, level=4)

    if ai and not deterministic:
        for term in ai:
            if topic and not set(textnorm.tokens(topic)).issubset(
                    set(textnorm.tokens(term))):
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


def _representation_priority(rep) -> int:
    """Keep scene events/entities ahead of broad topic-only anchors."""
    if rep.kind in {"event", "person", "monument", "artifact", "army", "object"}:
        return 0
    if (rep.source in {"entity_context", "verified_entity_context"}
            or rep.kind in {"empire", "map"}):
        return 2
    return 1


def _already_contains(query: str, phrase: str) -> bool:
    return _contains_phrase(query, phrase)


def _contains_phrase(query: str, phrase: str) -> bool:
    phrase_tokens = textnorm.tokens(phrase, min_len=2)
    query_tokens = textnorm.tokens(query, min_len=2)
    size = len(phrase_tokens)
    return bool(size) and any(query_tokens[index:index + size] == phrase_tokens
                              for index in range(len(query_tokens) - size + 1))


def _with_context(query: str, context: str) -> str:
    if not context or _already_contains(query, context):
        return query
    return f"{query} {context}".strip()


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
