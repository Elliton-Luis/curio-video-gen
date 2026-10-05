"""Vocabulário visual compartilhado para cenas sem descrição estruturada."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import replace

from .. import textnorm
from . import editorial
from . import scoring
from .scene_contract import Alias, SemanticScene, VideoContext, VisualRepresentation

_HONORIFICS = {"sao", "santo", "santa", "saint"}

# Assuntos vagos que, num vídeo sobre uma pessoa e sem outros nomes na
# cena, referem-se à própria entidade ("Quem foi o homem que...").
_GENERIC_PERSON = {"homem", "homens", "mulher", "mulheres", "pessoa",
                   "pessoas", "man", "men", "woman", "women", "person",
                   "boy", "girl", "menino", "menina"}


def _semantic_batch(scenes) -> tuple[SemanticScene, ...]:
    batch = tuple(scenes or ())
    if any(not isinstance(scene, SemanticScene) for scene in batch):
        raise TypeError("visual context enrichment requires SemanticScene")
    return batch


def attach_video_context(scenes, topic: str, target=None) -> tuple[SemanticScene, ...]:
    """Return scenes with shared topic context; never mutate planner output."""
    scenes = _semantic_batch(scenes)
    topic = str(topic or "").strip()
    if target is not None:
        canonical = str(getattr(target, "name", "") or "").strip()
        if canonical:
            topic = canonical
    if not topic:
        return tuple(scenes or ())
    canonical_names = list(dict.fromkeys(
        str(x).strip() for x in
        ([topic] + list(getattr(target, "aliases", []) or [])) if str(x).strip()))

    def _list(value):
        if isinstance(value, str):
            return [value] if value.strip() else []
        return list(value) if isinstance(value, (list, tuple)) else []

    enriched = []
    for scene in scenes or ():
        context = scene.video_context.to_dict()
        # A scene planner may suggest visual details, but it cannot replace
        # the researched topic with a conflicting entity or event name.
        context["topic"] = topic
        context["primary_entities"] = list(dict.fromkeys(
            [*_list(context.get("primary_entities")), *canonical_names]))[:8]
        context["secondary_entities"] = _list(context.get("secondary_entities"))
        context["places"] = _list(context.get("places"))
        context["events"] = _list(context.get("events"))
        context["period"] = str(context.get("period") or "")
        # Keep planner aliases for audit, but do not silently promote them to
        # search anchors. Target aliases remain unverified until corroborated
        # by an explicit source (for example a Wikipedia language link).
        existing_aliases = VideoContext.from_value(context).aliases
        alias_by_value = {alias.value.casefold(): alias
                          for alias in existing_aliases}
        for name in canonical_names:
            alias_by_value.setdefault(name.casefold(), Alias(
                name, source="target_entity", evidence="", verified=False))
        aliases = list(alias_by_value.values())
        aliases.sort(key=lambda alias: not alias.verified)
        aliases = aliases[:8]
        context["aliases"] = [alias.value for alias in aliases]
        context["alias_provenance"] = [
            {"value": alias.value, "source": alias.source,
             "evidence": alias.evidence, "verified": alias.verified}
            for alias in aliases]
        updates = {"video_context": VideoContext.from_value(context)}
        if scene.planning_mode == "deterministic":
            # Local noun extraction is search support, not trusted screen
            # content. Show the known topic until scene meaning is resolved.
            updates.update(subject=topic, primary_entity=topic, visual_entities=())
            # Local genre cues are incomplete until the global subject is
            # attached. History topics classify scenes with no explicit
            # date/event too, and a process verb must not force science.
            if scene.visual_type != "typographic":
                from .scene_visual_type import classify_visual_type
                contextual_type = classify_visual_type(f"{scene.narration} {topic}")
                if contextual_type == "historical_art":
                    updates["visual_type"] = contextual_type
            if not scene.visual_intent_structured:
                updates["visual_intent_structured"] = (
                    f"Topic-level visual for {topic}; scene representation unresolved")
        if not scene.global_visual_queries:
            updates["global_visual_queries"] = (topic,)
        enriched.append(replace(scene, **updates))
    return tuple(enriched)


def _identity_tokens(name):
    return set(scoring._tokens(name)) - _HONORIFICS


def _language_alias(names, sources, timeout):
    """Usa ligação de idioma do artigo aceito, não tradução inventada de nome."""
    from . import research
    for source in sources:
        url = urllib.parse.urlsplit(source.url)
        if (not url.hostname or not url.hostname.endswith(".wikipedia.org")
                or not any(_identity_tokens(source.title) == _identity_tokens(name)
                           for name in names)):
            continue
        params = urllib.parse.urlencode({"action": "query", "format": "json",
                                        "prop": "langlinks", "lllang": "en",
                                        "titles": source.title, "redirects": "1"})
        try:
            data = research._get_json(f"https://{url.hostname}/w/api.php?{params}",
                                      timeout=timeout)
            for page in (data.get("query", {}).get("pages") or {}).values():
                for link in page.get("langlinks") or []:
                    if link.get("lang") == "en" and link.get("*"):
                        return str(link["*"])
        except research.ResearchError:
            return ""
        break
    return ""


def _subject_matches_entity(subject, names) -> bool:
    """Assunto idêntico a um nome da entidade, ignorando acentos e caixa."""
    subject_tokens = _identity_tokens(subject)
    if not subject_tokens:
        return False
    return any(subject_tokens == _identity_tokens(name) for name in names)


def _generic_person_subject(ch, names, genre: str) -> bool:
    """Assunto vago de pessoa sem concorrentes na narração.

    Só ancora quando o assunto é um substantivo genérico minúsculo e a
    narração não cita outro nome próprio além da entidade. "O papa" ou
    "o rei" no meio da frase impedem a ancoragem: seriam outra pessoa.
    """
    if genre not in ("people", "history", "mythology"):
        return False
    if (ch.subject or "").strip().lower() not in _GENERIC_PERSON:
        return False
    alias_tokens = {t for name in names for t in _identity_tokens(name)}
    for sentence in re.split(r"(?<=[.!?…])\s+", ch.narration or ""):
        words = re.findall(r"[A-Za-zÀ-ÿ']+", sentence)
        for word in words[1:]:
            if word[:1].isupper() and _identity_tokens(word) - alias_tokens:
                return False
    return True


def _with_visual_queries(scene: SemanticScene, queries, *, source: str,
                         kind: str) -> SemanticScene:
    existing = {rep.query.casefold(): rep for rep in scene.representations}
    representations = []
    seen = set()
    for query in queries:
        query = str(query or "").strip()
        if query and query.casefold() not in seen:
            key = query.casefold()
            representations.append(existing.get(key) or VisualRepresentation(
                query=query, kind=kind, level=len(representations), source=source))
            seen.add(key)
    for representation in scene.representations:
        key = representation.query.casefold()
        if key not in seen:
            representations.append(representation)
            seen.add(key)
    return replace(scene, representations=tuple(representations),
                   visual_queries=tuple(rep.query for rep in representations))


def fill_missing_context(scenes, target, genre: str = "", sources=(),
                         timeout: int = 20) -> tuple[SemanticScene, ...]:
    """Return entity context enrichment without mutating semantic scenes."""
    scenes = _semantic_batch(scenes)
    if target is None:
        return scenes
    names = list(dict.fromkeys(n.strip() for n in target.all_names() if n.strip()))
    if not names:
        return scenes
    if not getattr(target, "is_entity", False) and not any(
            _subject_matches_entity(source.title, names) for source in sources):
        return scenes  # Only anchor to an entity confirmed by research.
    empty = [scene for scene in scenes
             if not scene.subject and not scene.visual_queries]
    bare = [scene for scene in scenes if scene not in empty and
            (not scene.subject_aliases or (
                _subject_matches_entity(scene.subject, names)
                and not any(alias not in names for alias in scene.subject_aliases)))]
    if not empty and not bare:
        return scenes
    english = _language_alias(names, sources, timeout) if sources else ""
    if english and english not in names:
        names.append(english)
    person_tokens = {t for name in names for t in _identity_tokens(name)}
    needs = [scene for scene in scenes
             if scene in empty
             or (scene in bare and (_subject_matches_entity(scene.subject, names)
                                    or _generic_person_subject(scene, names, genre)))]
    english_subject = english
    if english and names[0].startswith(("São ", "Santo ", "Santa ")):
        english_subject = english if english.startswith("Saint ") else f"Saint {english}"
    perfil = editorial.get(genre)
    medium = perfil.visual_context_medium if perfil else ""
    replacements = {}
    for scene in needs:
        context = scene.video_context.to_dict()
        for key in ("primary_entities",):
            context[key] = list(dict.fromkeys(
                [*(context.get(key, []) or []), *names]))[:8]
        alias_by_value = {alias.value.casefold(): alias
                          for alias in VideoContext.from_value(context).aliases}
        for name in names:
            alias_by_value.setdefault(name.casefold(), Alias(
                name, source="target_entity", verified=False))
        if english:
            evidence = next((source.url for source in sources
                             if source.url and any(
                                 _identity_tokens(source.title) == _identity_tokens(name)
                                 for name in names)), "Wikipedia language link")
            alias_by_value[english.casefold()] = Alias(
                english, source="wikipedia_langlink", evidence=evidence,
                verified=bool(evidence))
        aliases = list(alias_by_value.values())
        aliases.sort(key=lambda alias: not alias.verified)
        aliases = aliases[:8]
        context["aliases"] = [alias.value for alias in aliases]
        context["alias_provenance"] = [
            {"value": alias.value, "source": alias.source,
             "evidence": alias.evidence, "verified": alias.verified}
            for alias in aliases]
        updates = {"video_context": VideoContext.from_value(context)}
        if not scene.subject and not scene.visual_queries:
            subject = names[0]
            aliases = names
            # Um local precisa constar literalmente na cena, não ser adivinhado.
            places = re.findall(
                r"\b(?:em|in)\s+([A-ZÀ-Þ][\wÀ-ÿ'-]+"
                r"(?:\s+(?:de|da|do)\s+[A-ZÀ-Þ][\wÀ-ÿ'-]+)*)", scene.narration)
            for place in places:
                tokens = set(scoring._tokens(place))
                if tokens and not tokens.intersection(person_tokens):
                    subject, aliases = place, [place]
                    if len(tokens) == 1:
                        # Correspondência EXATA, sem a queda de plural de
                        # `translate`: aqui é um nome próprio de lugar, e
                        # "Paris" não pode casar com "pari".
                        english_term = textnorm.PT_LEXICON.get(
                            next(iter(tokens)))
                        if english_term:
                            aliases.append(english_term)
                    break
            updates["subject"] = subject
            updates["subject_aliases"] = tuple(
                name for name in aliases
                if len(_identity_tokens(name)) >= 2 or name == subject
                or subject != names[0])
            queries = list(dict.fromkeys(aliases))
            if subject == names[0]:
                queries = [f"{english_subject or subject} {medium}".strip(), subject,
                           *([english] if english else [])]
            scene = _with_visual_queries(
                scene, list(dict.fromkeys(queries))[:5], source="entity_context",
                kind="person" if "portrait" in medium.casefold() else "entity")
            updates["visual_queries"] = scene.visual_queries
            updates["representations"] = scene.representations
            updates["global_visual_queries"] = scene.visual_queries
            updates["forbidden"] = tuple(dict.fromkeys(
                [*scene.forbidden, *target.forbidden]))
        else:
            # Cena da IA com assunto da entidade: só aliases e consulta
            # ancorada; assunto e consultas existentes ficam intactas.
            updates["subject_aliases"] = tuple(dict.fromkeys([
                *scene.subject_aliases, *(name for name in names
                     if len(_identity_tokens(name)) >= 2 or name == scene.subject)]))
            anchored = f"{english_subject or names[0]} {medium}".strip()
            existing = {q.lower() for q in scene.visual_queries}
            if anchored.lower() not in existing:
                scene = _with_visual_queries(
                    scene, [anchored, *scene.visual_queries][:5],
                    source="verified_entity_context",
                    kind="person" if "portrait" in medium.casefold() else "entity")
                updates["visual_queries"] = scene.visual_queries
                updates["representations"] = scene.representations
                updates["global_visual_queries"] = scene.visual_queries
            updates["forbidden"] = tuple(dict.fromkeys(
                [*scene.forbidden, *target.forbidden]))
        replacements[scene.id] = replace(scene, **updates)
    return tuple(replacements.get(scene.id, scene) for scene in scenes)


def anchor_local_topic(scenes, idea: str, target=None) -> tuple[SemanticScene, ...]:
    """Return local scenes anchored to the verified video topic.

    Local scene splitting lacks the LLM's scene context. Without this anchor,
    a scene query `mass` in a black-hole video scored bus station photo at 85;
    `sun` from `absoluto` selected Argentine flag in French Revolution video.
    Full phrase anchor prevents scene nouns from drifting to homonyms.
    """
    scenes = _semantic_batch(scenes)
    candidates = []
    if target is not None:
        candidates.extend([getattr(target, "name", ""),
                           *(getattr(target, "aliases", []) or [])])
    candidates.append(idea)
    query = next((str(value).strip() for value in candidates if str(value).strip()), "")
    translated = next((textnorm.translate_phrase(value) for value in candidates
                       if textnorm.translate_phrase(value)), "")
    anchors = [translated or query]
    if not anchors:
        return tuple(scenes or ())
    enriched = []
    for scene in scenes or ():
        context = scene.video_context.to_dict()
        context.setdefault("topic", query)
        context.setdefault("primary_entities", [query])
        context.setdefault("secondary_entities", [])
        context.setdefault("places", [])
        context.setdefault("events", [])
        context.setdefault("period", "")
        enriched.append(replace(scene, global_visual_queries=tuple(anchors),
                                video_context=VideoContext.from_value(context)))
    return tuple(enriched)
