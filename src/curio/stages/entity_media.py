"""Source-bound entity images for contextual use when scene media is absent."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import urllib.parse

from .. import textnorm
from .scene_contract import VideoContext, VisualRepresentation


def _entity_claims(ids, endpoint, cache_dir, prefix=""):
    """Cache catalog statements, including confirmed empty records."""
    from . import research
    records, pending = {}, []
    for key in sorted(set(ids)):
        path = Path(cache_dir) / "entity-media" / "claims" / (prefix + key + ".json")
        try:
            records[key] = json.loads(path.read_text())
        except (OSError, ValueError):
            pending.append((key, path))
    for start in range(0, len(pending), 50):
        chunk = pending[start:start + 50]
        params = urllib.parse.urlencode({"action": "wbgetentities", "format": "json",
            "ids": "|".join(prefix + key for key, _ in chunk), "props": "claims"})
        try:
            data = research._get_json(endpoint + "?" + params, timeout=8)
        except research.ResearchError:
            continue
        for key, path in chunk:
            entity = data.get("entities", {}).get(prefix + key)
            if not isinstance(entity, dict):
                continue
            records[key] = entity.get("statements", entity.get("claims", {}))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(records[key]))
    return records


def _claim_ids(statements, property):
    return {value for claim in statements.get(property, [])
            if claim.get("rank") != "deprecated"
            for value in [claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
            if value}


def structured_depiction_evidence(evaluations, scene, config):
    """Resolve depicts statements, including a digitized artwork's depiction.

    Only P180 (depicts) and P6243 (digital representation of) edges establish
    a representation. Naming, dedication and generic association never do.
    """
    verified_sources = {alias.evidence for alias in scene.video_context.aliases if alias.verified}
    entities = {binding.get("entity_id")
                for binding in scene.video_context.get("canonical_entity_media", [])
                if binding.get("entity_id") and binding.get("source") in verified_sources}
    if not entities:
        return {}
    ids = {item.candidate.asset.asset_id for item in evaluations
           if item.candidate.asset.provider == "wikimedia"
           and item.candidate.asset.asset_id.isdigit()}
    files = _entity_claims(ids, "https://commons.wikimedia.org/w/api.php", config.cache_dir, "M")
    represented = {key: _claim_ids(claims, "P180") | _claim_ids(claims, "P6243")
                   for key, claims in files.items()}
    intermediate = set().union(*represented.values()) - entities if represented else set()
    works = _entity_claims(intermediate, "https://www.wikidata.org/w/api.php", config.cache_dir)
    evidence = {}
    for key, values in represented.items():
        direct = values & entities
        via = {work: sorted(_claim_ids(works.get(work, {}), "P180") & entities)
               for work in values - entities
               if _claim_ids(works.get(work, {}), "P180") & entities}
        if direct or via:
            evidence[key] = {"entity_ids": sorted(direct | set().union(*map(set, via.values()))),
                "source": f"https://commons.wikimedia.org/wiki/Special:EntityData/M{key}.json",
                "evidence": "catalog_depiction_graph", "via_artworks": via, "relation": "contextual"}
    return evidence


def canonical_media_evidence(asset, scene):
    if asset.get("provider") != "wikimedia":
        return None
    title = textnorm.fold_phrase(str(asset.get("title", "")).removeprefix("File:"))
    verified_sources = {alias.evidence for alias in scene.video_context.aliases
                        if alias.verified and alias.evidence}
    for binding in scene.video_context.get("canonical_entity_media", []):
        if (isinstance(binding, dict) and binding.get("source") in verified_sources
                and title == textnorm.fold_phrase(binding.get("file", ""))):
            return binding
    return None


def enrich_entity_media(scenes, config):
    """Read lead images from accepted Wikipedia identity sources, never search hits.

    These establish the depicted topic, not a particular narrated event.
    Exact file binding avoids admitting namesake products by name alone.
    """
    from . import research
    by_source = {}
    for scene in scenes:
        for alias in scene.video_context.aliases:
            url = urllib.parse.urlsplit(alias.evidence)
            if (alias.verified and url.scheme == "https"
                    and (url.hostname or "").endswith(".wikipedia.org")
                    and url.path.startswith("/wiki/")):
                by_source.setdefault(alias.evidence, None)
    for source in by_source:
        cache = Path(config.cache_dir) / "entity-media" / (hashlib.sha256(("v2:" + source).encode()).hexdigest() + ".json")
        try:
            bindings = json.loads(cache.read_text())
        except (OSError, ValueError):
            url = urllib.parse.urlsplit(source)
            params = urllib.parse.urlencode({"action": "query", "format": "json",
                "prop": "pageimages|pageprops", "piprop": "name", "pilicense": "any",
                "titles": urllib.parse.unquote(url.path[6:]), "redirects": "1"})
            try:
                data = research._get_json(f"https://{url.hostname}/w/api.php?{params}", timeout=8)
            except research.ResearchError:
                continue
            bindings = [{"file": page["pageimage"], "source": source,
                         "relation": "contextual", "evidence": "wikipedia_pageimage",
                         "entity_id": page.get("pageprops", {}).get("wikibase_item", "")}
                        for page in data.get("query", {}).get("pages", {}).values()
                        if page.get("pageimage") and "missing" not in page
                        and "disambiguation" not in page.get("pageprops", {})]
            if bindings:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(bindings, ensure_ascii=False))
        by_source[source] = bindings
    enriched = []
    for scene in scenes:
        bindings = [binding for alias in scene.video_context.aliases
                    if alias.verified for binding in by_source.get(alias.evidence) or []]
        if not bindings:
            enriched.append(scene)
            continue
        context = scene.video_context.to_dict()
        context["canonical_entity_media"] = bindings
        representations = tuple(scene.representations) + tuple(
            VisualRepresentation(binding["file"].rsplit(".", 1)[0].replace("_", " "),
                                 "entity", 9, "canonical_entity_media", binding["source"])
            for binding in bindings)
        enriched.append(replace(scene, video_context=VideoContext.from_value(context),
                                representations=representations))
    return tuple(enriched)
