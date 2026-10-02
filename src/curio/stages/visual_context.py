"""Vocabulário visual compartilhado para cenas sem descrição estruturada."""

from __future__ import annotations

import re
import urllib.parse

from .. import textnorm
from . import editorial
from . import scoring

_HONORIFICS = {"sao", "santo", "santa", "saint"}

# Assuntos vagos que, num vídeo sobre uma pessoa e sem outros nomes na
# cena, referem-se à própria entidade ("Quem foi o homem que...").
_GENERIC_PERSON = {"homem", "homens", "mulher", "mulheres", "pessoa",
                   "pessoas", "man", "men", "woman", "women", "person",
                   "boy", "girl", "menino", "menina"}


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


def fill_missing_context(chapters, target, genre: str = "", sources=(),
                         timeout: int = 20) -> bool:
    """Preserva identidade da pesquisa sem reescrever narração ou cenas da IA.

    Cenas sem assunto e consultas recebem contexto completo. Cenas cujo
    assunto já é o nome da entidade apenas ganham aliases e uma consulta
    ancorada na entidade; assunto, narração e consultas existentes ficam.
    """
    if target is None:
        return False
    names = list(dict.fromkeys(n.strip() for n in target.all_names() if n.strip()))
    if not names:
        return False
    if not getattr(target, "is_entity", False) and not any(
            _subject_matches_entity(source.title, names) for source in sources):
        return False  # Anchor a topic only to a verified canonical source title.
    empty = [ch for ch in chapters
             if not ch.subject and not ch.visual_queries]
    bare = [ch for ch in chapters if ch not in empty and
            (not ch.subject_aliases or (_subject_matches_entity(ch.subject, names)
             and not any(alias not in names for alias in ch.subject_aliases)))]
    if not empty and not bare:
        return False
    english = _language_alias(names, sources, timeout) if sources else ""
    if english and english not in names:
        names.append(english)
    person_tokens = {t for name in names for t in _identity_tokens(name)}
    needs = [ch for ch in chapters
             if ch in empty
             or (ch in bare and (_subject_matches_entity(ch.subject, names)
                                 or _generic_person_subject(ch, names, genre)))]
    english_subject = english
    if english and names[0].startswith(("São ", "Santo ", "Santa ")):
        english_subject = english if english.startswith("Saint ") else f"Saint {english}"
    perfil = editorial.get(genre)
    medium = perfil.visual_context_medium if perfil else ""
    changed = False
    for ch in needs:
        previous = ch.to_dict()
        if not ch.subject and not ch.visual_queries:
            subject = names[0]
            aliases = names
            # Um local precisa constar literalmente na cena, não ser adivinhado.
            places = re.findall(
                r"\b(?:em|in)\s+([A-ZÀ-Þ][\wÀ-ÿ'-]+"
                r"(?:\s+(?:de|da|do)\s+[A-ZÀ-Þ][\wÀ-ÿ'-]+)*)", ch.narration)
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
            ch.subject = subject
            # Não aceitar apelido isolado como identidade de uma pessoa ambígua.
            ch.subject_aliases = [name for name in aliases
                                   if len(_identity_tokens(name)) >= 2 or name == subject
                                   or subject != names[0]]
            queries = list(dict.fromkeys(aliases))
            if subject == names[0]:
                queries = [f"{english_subject or subject} {medium}".strip(), subject,
                           *([english] if english else [])]
            ch.visual_queries = list(dict.fromkeys(queries))[:5]
            ch.global_visual_queries = list(ch.visual_queries)
            ch.forbidden = list(dict.fromkeys(ch.forbidden + list(target.forbidden)))
        else:
            # Cena da IA com assunto da entidade: só aliases e consulta
            # ancorada; assunto e consultas existentes ficam intactas.
            ch.subject_aliases = list(dict.fromkeys([
                *ch.subject_aliases, *(name for name in names
                                     if len(_identity_tokens(name)) >= 2 or name == ch.subject)]))
            anchored = f"{english_subject or names[0]} {medium}".strip()
            existing = {q.lower() for q in ch.visual_queries}
            if anchored.lower() not in existing:
                ch.visual_queries = [anchored, *ch.visual_queries][:5]
                ch.global_visual_queries = list(ch.visual_queries)
            ch.forbidden = list(dict.fromkeys(ch.forbidden + list(target.forbidden)))
        changed = changed or ch.to_dict() != previous
    return changed


def anchor_local_topic(chapters, idea: str, target=None) -> bool:
    """Add verified video topic to local-fallback scenes as a hard visual anchor.

    Local scene splitting lacks the LLM's scene context. Without this anchor,
    a scene query `mass` in a black-hole video scored bus station photo at 85;
    `sun` from `absoluto` selected Argentine flag in French Revolution video.
    Full phrase anchor prevents scene nouns from drifting to homonyms.
    """
    candidates = []
    if target is not None:
        candidates.extend([getattr(target, "name", ""),
                           *(getattr(target, "aliases", []) or [])])
    candidates.append(idea)
    query = next((textnorm.translate_phrase(value) for value in candidates
                  if textnorm.translate_phrase(value)), "")
    if not query:
        return False
    changed = False
    for chapter in chapters or []:
        if list(getattr(chapter, "global_visual_queries", []) or []) != [query]:
            chapter.global_visual_queries = [query]
            changed = True
    return changed
