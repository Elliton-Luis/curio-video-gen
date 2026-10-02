"""Adapters de fontes de pesquisa, registradas por nome.

Cada fonte implementa apenas obtenção e normalização de registros. Genre
adapters declaram identificadores; pesquisa geral permanece infraestrutura
compartilhada e a relevância decide quais fontes entram.
"""

from __future__ import annotations

import urllib.parse
from . import research


def _wikidata(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    lang = "en" if str(language or "").lower().startswith("en") else "pt"
    params = {"action": "wbsearchentities", "search": query, "language": lang,
              "uselang": lang, "format": "json", "limit": "4"}
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        data = research._get_json(url, timeout=timeout)
    except research.ResearchError:
        return []
    out = []
    for hit in data.get("search", []) or []:
        ident = str(hit.get("id", ""))
        title = str(hit.get("label", "")).strip()
        description = str(hit.get("description", "")).strip()
        if ident and title:
            out.append(research.ResearchSource(
                title=f"Wikidata — {title}",
                url=f"https://www.wikidata.org/wiki/{ident}",
                snippet=description, origin="wikidata"))
    return out


def _loc(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    params = {"q": query, "fo": "json", "c": "5"}
    url = "https://www.loc.gov/search/?" + urllib.parse.urlencode(params)
    try:
        data = research._get_json(url, timeout=timeout)
    except research.ResearchError:
        return []
    out = []
    for hit in data.get("results", []) or []:
        title = str(hit.get("title") or hit.get("item") or "").strip()
        page = str(hit.get("id") or "").strip()
        descriptions = hit.get("description") or []
        if isinstance(descriptions, str):
            descriptions = [descriptions]
        snippet = " ".join(str(x) for x in descriptions if x)[:research.EXTRACT_CHARS]
        if title and page:
            out.append(research.ResearchSource(title=f"Library of Congress — {title}",
                                               url=page, snippet=snippet,
                                               origin="library_of_congress"))
    return out


def _nasa(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    url = ("https://images-api.nasa.gov/search?" +
           urllib.parse.urlencode({"q": query, "media_type": "image"}))
    try:
        data = research._get_json(url, timeout=timeout)
    except research.ResearchError:
        return []
    out = []
    collection = data.get("collection", {})
    for item in collection.get("items", [])[:5]:
        meta = (item.get("data") or [{}])[0]
        title = str(meta.get("title") or "").strip()
        description = str(meta.get("description") or "").strip()
        links = item.get("links") or []
        page = str(links[0].get("href") or "") if links else ""
        if title and page:
            out.append(research.ResearchSource(title=f"NASA — {title}", url=page,
                                               snippet=description[:research.EXTRACT_CHARS],
                                               origin="nasa",
                                               license="NASA public domain",
                                               license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/"))
    return out


def _pubmed(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    search_url = base + "esearch.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "term": query, "retmax": "3", "retmode": "json"})
    try:
        data = research._get_json(search_url, timeout=timeout)
        ids = (data.get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        summary_url = base + "esummary.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
        summary = research._get_json(summary_url, timeout=timeout)
    except research.ResearchError:
        return []
    out = []
    result = summary.get("result", {})
    for ident in ids:
        item = result.get(ident) or {}
        title = str(item.get("title") or "").strip()
        if title:
            out.append(research.ResearchSource(
                title=f"PubMed — {title}",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{ident}/",
                snippet=title, origin="pubmed"))
    return out


def _fbi(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    url = "https://api.fbi.gov/wanted/v1/list?" + urllib.parse.urlencode(
        {"title": query, "page": "1"})
    try:
        data = research._get_json(url, timeout=timeout)
    except research.ResearchError:
        return []
    out = []
    for item in data.get("items", [])[:4]:
        title = str(item.get("title") or "").strip()
        page = str(item.get("url") or "").strip()
        snippet = str(item.get("description") or item.get("details") or "")
        if title and page:
            out.append(research.ResearchSource(title=f"FBI Wanted — {title}",
                                               url=page,
                                               snippet=snippet[:research.EXTRACT_CHARS],
                                               origin="fbi_wanted"))
    return out


def _perseus(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    from .etymology import perseus_lookup
    word = query.strip().split()[-1] if query.strip() else ""
    if not word:
        return []
    source = perseus_lookup(word, "grc", timeout).get("source")
    return [source] if source else []


def _logeion(query: str, language: str, timeout: int) -> list[research.ResearchSource]:
    from .etymology import logeion_lookup
    word = query.strip().split()[-1] if query.strip() else ""
    if not word:
        return []
    source = logeion_lookup(word, timeout).get("source")
    return [source] if source else []


SOURCE_ADAPTERS = {
    "wikidata": _wikidata,
    "loc": _loc,
    "nasa": _nasa,
    "pubmed": _pubmed,
    "fbi_wanted": _fbi,
    "perseus": _perseus,
    "logeion": _logeion,
}


def fetch(name: str, query: str, language: str, timeout: int = 20):
    """Fetch one registered specialized source. Unknown name yields []."""
    adapter = SOURCE_ADAPTERS.get(name)
    return adapter(query, language, timeout) if adapter else []


def fetch_specialized(names: tuple[str, ...] | list[str], query: str,
                      idea: str, language: str, cache_dir: str,
                      metrics=None, timeout: int = 20):
    """Fetch declared sources in adapter order; return (sources, etymology).

    Wiktionary lookup returns its related Logeion/Perseus citations as one
    chain result. Registry recognizes those aliases and avoids duplicate
    network calls. Other sources remain independent.
    """
    from . import etymology

    out = []
    ety = None
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        if name == "wiktionary":
            if ety is None and "wiktionary" in names:
                head = etymology.headword_of(idea) or etymology.headword_of("", query)
                if head:
                    ety = etymology.lookup(head, idea, language, cache_dir,
                                           metrics, timeout)
                    if ety is not None:
                        out.extend(ety.sources)
            continue
        if name in ("logeion", "perseus") and ety is not None:
            continue
        try:
            out.extend(fetch(name, query, language, timeout))
        except Exception:  # noqa: BLE001 — source adapters are best-effort
            continue
    return out, ety
