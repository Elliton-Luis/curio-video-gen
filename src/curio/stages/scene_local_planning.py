"""Deterministic local visual representation planning for scenes."""

from __future__ import annotations

import re

from .. import textnorm
from . import scenes as scenes_stage

# Heurística offline p/ consultas visuais (sem chave NVIDIA as cenas locais
# não trazem `visual_queries` — sem isto, tudo cairia em fallback). Extrai
# palavras-cheia do trecho e verte substantivos visuais PT→EN, pois os
# bancos de mídia respondem melhor em inglês. O gate de relevância continua
# valendo: só entra imagem cujo título contenha a consulta.
# Stopword e léxico PT→EN vivem em `curio.textnorm`: são dado linguístico
# compartilhado com a pesquisa e com o filtro de mídia, e manter cópia
# própria por estágio é o que faz "buraco negro" virar query "field"
# num lugar e continuar certo em outro.
PT_STOP = textnorm.VISUAL_STOP_PT
PT_EN = textnorm.PT_LEXICON


# Verte PT→EN (singular/plural) usando o léxico compartilhado.
_en = textnorm.translate


# Minúsculas sem acento: mesma comparação de texto da pesquisa e do scoring.
_strip_acc = textnorm.fold


# --- tópico espacial: nunca ilustrar com laboratório -------------------
# Sinais (já sem acento/minúsculas) de que a cena é sobre espaço/
# astronomia. "buraco negro" precisa estar aqui como expressão: sem isso,
# "campo gravitacional" virava query "field" e o vídeo recebia microscópio.
# O que é "tema espacial" é uma decisão de `textnorm`, não deste arquivo:
# a busca, o gate de imagem e o classificador de cena precisam
# reconhecer o mesmo conjunto.
def _space_boost(narration: str) -> list[str]:
    """Queries do tema espacial presentes NESTA narração, em ordem."""
    hay = _strip_acc(str(narration or ""))
    out: list[str] = []
    if ("buraco negro" in hay or "buracos negros" in hay
            or "black hole" in hay or "corpo negro" in hay):
        out.append("black hole")
    if "horizonte de eventos" in hay or "event horizon" in hay:
        out.append("event horizon")
    for marker, query in (("galaxia", "galaxy"), ("galaxias", "galaxies"),
                          ("galaxy", "galaxy"), ("galaxies", "galaxies"),
                          ("nebulosa", "nebula"), ("nebula", "nebula"),
                          ("universo", "universe"), ("universe", "universe"),
                          ("gravidade", "gravity"), ("gravitacional", "gravity"),
                          ("gravitacao", "gravity"),
                          ("estrela", "star"), ("estrelas", "stars"),
                          ("sol", "sun"), ("solar", "sun"),
                          ("telescopio", "telescope"),
                          ("luz", "light"), ("massa", "mass"),
                          ("radiacao", "radiation")):
        # Word boundaries matter: `sol` inside `absoluto` made a French
        # Revolution video search for Argentine flags as if it were astronomy.
        if (re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", hay)
                and query not in out):
            out.append(query)
    return out


def local_visual_representations(narration: str, k: int = 2) -> list[str]:
    """Conceitos visuais locais; nunca promove palavras frequentes a âncoras."""
    # Entidades: capitalizada no MEIO da frase, ou 1ª palavra só se for
    # substantivo próprio conhecido (ex.: Roma, Cesar).
    mids = set(re.findall(r"[a-zà-ÿ]\s+([A-ZÀ-Þ][a-zà-ÿ]{2,})",
                          " " + narration))
    entities: list[str] = []
    for ent in dict.fromkeys(list(mids) + re.findall(
            r"[A-ZÀ-Þ][a-zà-ÿ]{2,}", narration)):
        base = _strip_acc(ent)
        if base in PT_STOP or len(base) < 3:
            continue
        if ent not in mids and base not in PT_EN:
            continue  # capitalizada só por abrir frase ("Não", "Virou")
        term = PT_EN.get(base, ent)
        if term not in entities:
            entities.append(term)
    boost = list(dict.fromkeys([
        *textnorm.topic_phrases(narration), *_space_boost(narration)]))
    # Coletar nomes próprios compostos preserva as unidades semânticas. Não
    # dividir "Corno de Ouro" em "gold", nem aceitar capitalização de início
    # de frase como entidade por si só.
    proper: list[str] = []
    name_re = re.compile(
        r"(?<!\w)[A-ZÀ-Þ][\wÀ-ÿ'-]*(?:(?:\s+(?:de|do|da|dos|das|of|the)\s+|\s+)[A-ZÀ-Þ][\wÀ-ÿ'-]*){0,4}")
    for match in name_re.finditer(narration):
        role_context = bool(re.match(r"^(?:sob|sobre|under)\s+",
                                     match.group(0), re.I))
        phrase = re.sub(r"^(?:o|a|os|as|the|sob|sobre|under)\s+", "",
                        match.group(0).strip(), flags=re.I)
        if not phrase:
            continue
        first = _strip_acc(phrase.split()[0].lower())
        if first in PT_STOP or len(phrase) < 4:
            continue
        before = narration[:match.start()].rstrip()
        if not before or before.endswith((".", "!", "?")):
            if (len(phrase.split()) == 1 and not role_context and first not in PT_EN
                    and phrase.lower() not in boost):
                continue
        if re.search(r",\s*(?:o|a|the)$", before, re.I) and proper:
            proper[-1] = f"{proper[-1]}, {phrase}"
        elif phrase not in proper:
            proper.append(phrase)
    # Nomes comuns concretos entram apenas quando são complementos nominais
    # explícitos. Lista curta de classes visuais; verbos e ordinais não passam.
    concrete = re.findall(
        r"\b(?:os|as|o|a|the|um|uma)\s+((?:jan[ií]zar\w+|soldad\w+|canh[oõ]es|espadas?|muralhas|fortalezas|navios?|frotas?|moedas|armas|est[aá]tuas|documentos|artefatos|monumentos|ex[eé]rcitos?|cavalarias?|uniformes?))\b",
        narration, re.I)
    # Eventos históricos usam uma taxonomia pequena e determinística; o
    # local/nome próprio é mantido junto ao tipo do evento.
    event_heads = ("batalha", "battle", "cerco", "siege", "revolução",
                   "revolution", "guerra", "war", "conquista", "conquest")
    event = next((head for head in event_heads
                  if re.search(rf"\b{head}\w*\b", narration, re.I)), "")
    year = next(iter(re.findall(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b", narration)), "")
    event_terms = []
    if event and proper:
        head = {"batalha": "Battle of", "battle": "Battle of",
                "cerco": "Siege of", "siege": "Siege of",
                "revolução": "Revolution", "revolution": "Revolution",
                "guerra": "War", "war": "War",
                "conquista": "Conquest of", "conquest": "Conquest of"}
        direct = re.search(
            r"\b(?:batalha|battle|cerco|siege|conquista|conquest|revolu[cç][aã]o|revolution|guerra|war)"
            r"\s+(?:de|do|da|of|at|a)\s+"
            r"([A-ZÀ-Þ][\wÀ-ÿ'-]*(?:\s+(?:de|do|da|dos|das|of|the)\s+[A-ZÀ-Þ][\wÀ-ÿ'-]*)*)",
            narration, re.I)
        siege_object = re.search(r"\b(?:cercou|besieged|sieged)\s+([A-ZÀ-Þ][\wÀ-ÿ'-]+)",
                                 narration)
        place = direct.group(1) if direct else (
            siege_object.group(1) if siege_object else "")
        if place:
            if len(place.split()) == 1:
                place = PT_EN.get(_strip_acc(place.lower()), place)
            event_query = f"{head[event]} {place}"
            event_terms.append(event_query)
            if year:
                event_terms.append(f"{event_query} {year}")
    # Keep established domain phrase matching (e.g. induction motor) and
    # known entities, but never use arbitrary frequency-ranked tokens.
    result: list[str] = []
    # Don't split a token from a multi-word place/person (notably a named
    # landmark ending in a translatable common noun such as "Ouro").
    embedded = {word.strip(" ,.;:").casefold()
                for phrase in proper if len(phrase.split()) > 1
                for word in phrase.split()}
    embedded.update(PT_EN.get(_strip_acc(word), word).casefold()
                    for word in list(embedded))
    safe_entities = [term for term in entities
                     if term.casefold() not in embedded]
    for term in [*boost, *event_terms, *proper, *safe_entities, *concrete]:
        term = re.sub(r"\s+", " ", str(term)).strip(" ,.;:")
        if scenes_stage._representation_rejection_reason(term, "entity"):
            continue
        if len(term.split()) == 1:
            term = PT_EN.get(_strip_acc(term.lower()), term)
        if not term:
            continue
        if term.casefold() not in {q.casefold() for q in result}:
            result.append(term)
    return result[:max(1, min(k, 5))]


