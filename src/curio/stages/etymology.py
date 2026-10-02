"""Fontes especializadas de etimologia (gênero `etymology`).

Três fontes, três papéis:

- **Wiktionary** (primária): API oficial (`w/api.php`, `prop=revisions`,
  `rvprop=content`), `User-Agent` identificável via `curio.ua`, parse do
  wikitexto das seções de etimologia. Dela saem a cadeia de formas
  (candidato → candidatus → candidus), o idioma de origem e as notas
  culturais ("candidates wore a white toga"). Texto sob CC BY-SA.
- **Logeion** (grego/latim): dicionários agregados (Lewis & Short etc., em
  domínio público). O site é um SPA — o HTML servido não contém o verbete
  — então a integração é referência citável por headword + leitura
  best-effort com degradação para referência pura.
- **Perseus Digital Library** (complementar grego/latim): morfologia e
  ocorrências em textos clássicos, mesma estratégia de referência +
  leitura best-effort (o Hopper oscila; nunca pode derrubar o vídeo).

Nada aqui substitui a pesquisa geral: o resultado (`Etymology`) viaja
pendurado no `ResearchResult` e alimenta o prompt do roteiro (PARÁFRASE,
nunca cópia do verbete) e as entidades visuais das cenas. Sem rede ou sem
verbete, `lookup()` devolve `None` e o vídeo segue só com as fontes
gerais. Custo zero: nenhuma das três exige chave.
"""

from __future__ import annotations

import hashlib
import concurrent.futures
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .. import textnorm
from ..ua import user_agent

TIMEOUT = 20
CACHE_TTL_DAYS = 30
MAX_CHAIN_DEPTH = 4

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
WIKTIONARY_LICENSE = "CC BY-SA 4.0 (verbete Wiktionary)"
WIKTIONARY_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

LOGEION_URL = "https://logeion.uchicago.edu/{word}"
LOGEION_LICENSE = ("verbete agrega dicionários em domínio público "
                   "(Lewis & Short e outros); ver página da fonte")

PERSEUS_MORPH_URL = ("https://www.perseus.tufts.edu/hopper/morph"
                     "?l={word}&la={lang}")
PERSEUS_SEARCH_URL = "https://www.perseus.tufts.edu/hopper/searchresults?q={word}"
PERSEUS_LICENSE = ("textos clássicos em domínio público; ver página da fonte "
                   "(uso como referência)")

# Códigos de idioma do Wiktionary → nome exibido.
LANG_NAMES = {
    "pt": "português", "en": "inglês", "es": "espanhol", "it": "italiano",
    "fr": "francês", "la": "latim", "grc": "grego antigo", "el": "grego",
    "de": "alemão", "nl": "holandês", "ca": "catalão", "gl": "galego",
    "ro": "romeno", "da": "dinamarquês", "nb": "norueguês", "sv": "sueco",
    "pl": "polonês", "mul": "translingual", "ine-pro": "proto-indo-europeu",
}

# Origem clássica → conceitos visuais de cultura material. A ponte é
# declarada pelo IDIOMA de origem (dado parseado, não inventado): latim
# desemboca em Roma, grego em Atenas. São cenários, não afirmações — a
# cena continua podendo escolher cartão/diagrama.
CULTURE_VISUALS = {
    "la": (["Roma antiga", "toga romana", "senado romano"], "latim"),
    "grc": (["Grécia antiga", "templo grego", "ágora"], "grego antigo"),
}

# Sufixos de função em entidades visuais ("Faustina portrait" → pessoa +
# meio). Aqui o meio é descartado para casar o nome: "candidatus" casa
# com o título, "noun" não.
_MEDIUM_WORDS = frozenset({
    "portrait", "statue", "statues", "bust", "busts", "painting",
    "paintings", "photograph", "photo", "photos", "sculpture",
    "sculptures", "image", "images", "noun", "verb", "adjective",
})


def _fold(text: str) -> str:
    return textnorm.fold(text)


def _norm_term(term: str) -> str:
    """Forma canônica p/ buscar o próximo elo: sem macrons, minúscula."""
    t = unicodedata.normalize("NFKD", str(term or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-zà-ÿā-ȳ]+", "", t.lower()).strip()


class Etymon:
    """Um elo da cadeia: forma + idioma (+ glosa/nota quando houver)."""

    def __init__(self, term: str = "", language: str = "",
                 language_code: str = "", gloss: str = "",
                 note: str = "", url: str = "", origin: str = "wiktionary"):
        self.term = term
        self.language = language
        self.language_code = language_code
        self.gloss = gloss
        self.note = note
        self.url = url
        self.origin = origin

    def to_dict(self) -> dict:
        return {"term": self.term, "language": self.language,
                "language_code": self.language_code, "gloss": self.gloss,
                "note": self.note, "url": self.url, "origin": self.origin}

    @classmethod
    def from_dict(cls, d: dict) -> "Etymon":
        return cls(term=str(d.get("term", "")),
                   language=str(d.get("language", "")),
                   language_code=str(d.get("language_code", "")),
                   gloss=str(d.get("gloss", "")),
                   note=str(d.get("note", "")),
                   url=str(d.get("url", "")),
                   origin=str(d.get("origin", "wiktionary")))


class Etymology:
    """Cadeia + fontes + conceitos visuais de um verbete pesquisado."""

    def __init__(self, word: str = "", chain: list | None = None,
                 origin_language: str = "", origin_code: str = "",
                 visual_entities: list | None = None,
                 visual_context: list | None = None,
                 sources: list | None = None):
        self.word = word
        self.chain = list(chain or [])
        self.origin_language = origin_language
        self.origin_code = origin_code
        self.visual_entities = list(visual_entities or [])
        self.visual_context = list(visual_context or [])
        self.sources = list(sources or [])

    def to_dict(self) -> dict:
        return {"word": self.word,
                "chain": [e.to_dict() if isinstance(e, Etymon) else e
                          for e in self.chain],
                "origin_language": self.origin_language,
                "origin_code": self.origin_code,
                "visual_entities": list(self.visual_entities),
                "visual_context": list(self.visual_context),
                "sources": [s.to_dict() if hasattr(s, "to_dict") else s
                            for s in self.sources]}

    @classmethod
    def from_dict(cls, d: dict) -> "Etymology":
        from .research import ResearchSource
        chain = [Etymon.from_dict(e) if isinstance(e, dict) else e
                 for e in (d.get("chain") or [])]
        sources = []
        for s in (d.get("sources") or []):
            if isinstance(s, dict):
                try:
                    sources.append(ResearchSource.from_dict(s))
                except Exception:  # noqa: BLE001 — fonte ruim: pula
                    continue
            else:
                sources.append(s)
        return cls(word=str(d.get("word", "")), chain=chain,
                   origin_language=str(d.get("origin_language", "")),
                   origin_code=str(d.get("origin_code", "")),
                   visual_entities=list(d.get("visual_entities") or []),
                   visual_context=list(d.get("visual_context") or []),
                   sources=sources)

    def chain_text(self) -> str:
        """'candidato → candidatus (latim) → candidus (latim)': p/ prompt."""
        parts = []
        for e in self.chain:
            label = e.term
            if e.language:
                label += f" ({e.language})"
            parts.append(label)
        return " → ".join(parts)


_LICENSES = {
    "wiktionary": (WIKTIONARY_LICENSE, WIKTIONARY_LICENSE_URL),
    "logeion": (LOGEION_LICENSE, ""),
    "perseus": (PERSEUS_LICENSE, ""),
}


def source_license(origin: str) -> tuple[str, str]:
    """(licença, url_da_licença) p/ o registro em sources.json."""
    return _LICENSES.get((origin or "").strip().lower(), ("", ""))


# --- headword ----------------------------------------------------------

_HEADWORD_PATTERNS = (
    r"palavra\s+[\"“']?([A-Za-zÀ-ÿ-]+)[\"”']?",
    r"termo\s+[\"“']?([A-Za-zÀ-ÿ-]+)[\"”']?",
    r"etimologia\s+(?:da palavra|do termo|de)\s+[\"“']?([A-Za-zÀ-ÿ-]+)[\"”']?",
    r"de onde ve[ií]o\s+(?:a palavra\s+|o termo\s+)?[\"“']?([A-Za-zÀ-ÿ-]+)[\"”']?",
    r"origem\s+(?:da palavra|do termo)\s+[\"“']?([A-Za-zÀ-ÿ-]+)[\"”']?",
    r"[\"“']([A-Za-zÀ-ÿ-]{3,})[\"”']",
)


def headword_of(idea: str, fallback: str = "") -> str:
    """A palavra cujo verbete pesquisar. "" quando não há candidato claro."""
    text = str(idea or "").strip()
    for pat in _HEADWORD_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cand = m.group(1).strip().strip("\"“”'").strip()
            if len(cand) >= 2 and " " not in cand:
                return cand.lower()
    fb = str(fallback or "").strip()
    if fb and " " not in fb and len(fb) >= 2:
        return fb.lower()
    return ""


# --- cache local -------------------------------------------------------

def _cache_file(cache_dir: str, source: str, word: str) -> str:
    key = hashlib.sha256(f"{source}|{_fold(word)}".encode()).hexdigest()[:16]
    return os.path.join(cache_dir, "etymology", f"{source}_{key}.json")


def _cache_read(path: str):
    try:
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        age_days = (time.time() - float(data.get("fetched_at", 0))) / 86400.0
        if age_days > CACHE_TTL_DAYS:
            return None
        return data.get("payload")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_write(path: str, payload) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": time.time(), "payload": payload},
                      fh, ensure_ascii=False)
    except OSError:
        pass  # cache nunca derruba a pesquisa


# --- rede (UA identificável, retry curto, nunca fatal) ------------------

def _fetch_text(url: str, timeout: int = TIMEOUT) -> str | None:
    """GET com UA do curio. None em qualquer falha (best-effort)."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    ultima: Exception | None = None
    for tentativa in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            charset = "utf-8"
            try:
                ctype = resp.headers.get_content_charset()
                if ctype:
                    charset = ctype
            except Exception:  # noqa: BLE001 — charset nunca é fatal
                pass
            return raw.decode(charset, errors="replace")
        except Exception as exc:  # noqa: BLE001 — best-effort
            ultima = exc
            time.sleep(0.5 * (tentativa + 1))
    _ = ultima
    return None


def _wiktionary_api(params: dict, timeout: int = TIMEOUT):
    """JSON da API oficial do Wiktionary. None em qualquer falha."""
    params = {"format": "json", "formatversion": "2", **params}
    url = WIKTIONARY_API + "?" + urllib.parse.urlencode(params)
    text = _fetch_text(url, timeout=timeout)
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def wiktionary_wikitext(word: str, timeout: int = TIMEOUT) -> str | None:
    """Wikitexto bruto do verbete (todas as línguas). None se ausente."""
    data = _wiktionary_api({
        "action": "query", "prop": "revisions",
        "rvprop": "content", "rvslots": "main", "titles": word,
    }, timeout=timeout)
    try:
        pages = ((data or {}).get("query") or {}).get("pages") or []
        page = pages[0] if pages else {}
        if page.get("missing"):
            return None
        revs = page.get("revisions") or []
        return (((revs[0] if revs else {}).get("slots") or {})
                .get("main", {}).get("content"))
    except (IndexError, KeyError, AttributeError, TypeError):
        return None


# --- parse do wikitexto -------------------------------------------------

_LANG_SECTION = re.compile(r"^==(?!=)([^=\n]+)==[ \t]*$", re.MULTILINE)
_ETYM_HEADING = re.compile(r"^===\s*(Etymology(?:\s+\d+)?)\s*===[ \t]*$",
                           re.MULTILINE)
_TEMPLATE = re.compile(r"\{\{([^{}|]+)((?:\|[^{}]*)?)\}\}")
_LANG_TERM = re.compile(r"^([a-z]{2,3}(?:-[a-z]+)?):(.+)$")
_DEFINITION = re.compile(r"^#(?![:*#])(.*)$", re.MULTILINE)

_REL_TEMPLATES = {"ety", "der", "inh", "bor", "lbor"}
_REL_TYPES = {"der", "inh", "bor", "lbor"}


def _split_templates(text: str) -> list[tuple[str, list[str]]]:
    """Templates de topo: (nome, [args]). Aninhados são ignorados."""
    out = []
    for m in _TEMPLATE.finditer(text or ""):
        name = m.group(1).strip().lower()
        args = [a.strip() for a in m.group(2).split("|")[1:]]
        out.append((name, args))
    return out


def _strip_templates(text: str) -> str:
    """Texto corrido sem templates/links: p/ notas legíveis e curtas."""
    text = re.sub(r"\{\{[^{}]*\}\}", "", text or "")
    text = re.sub(r"\[\[[^|\]]*\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" ,;.")


def _template_links(args: list[str]) -> list[tuple[str, str]]:
    """Pares (idioma, termo) nos args: 'la:candidātus'."""
    out = []
    for arg in args:
        if "=" in arg and not _LANG_TERM.match(arg.split("=", 1)[-1].strip()):
            continue
        val = arg.split("=", 1)[-1].strip() if "=" in arg else arg
        m = _LANG_TERM.match(val)
        if m and len(m.group(2).strip()) >= 2:
            out.append((m.group(1), m.group(2).strip()))
    return out


def parse_language_sections(wikitext: str) -> dict[str, str]:
    """Divide o verbete por idioma: {'Portuguese': '...', 'Latin': '...'}."""
    out: dict[str, str] = {}
    matches = list(_LANG_SECTION.finditer(wikitext or ""))
    for i, m in enumerate(matches):
        lang = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        if lang and lang.lower() not in ("see also", "anagrams", "references"):
            out[lang] = wikitext[start:end]
    return out


def parse_etymology_blocks(section: str) -> list[dict]:
    """Blocos ===Etymology=== de UMA seção de idioma.

    Cada bloco: relação herdada/emprestada (`der|inh|bor|lbor`), elos
    (`xx:termo`), afixos (`af`), cognatos (`cog`), glosas (`t1=...`) e a
    primeira definição (`# ...`). Sem seção de etimologia: [].
    """
    blocks = []
    matches = list(_ETYM_HEADING.finditer(section or ""))
    # Sem cabeçalho de etimologia, o corpo inteiro é um bloco anônimo
    # (verbete de uma linha, comum em latim/grego).
    spans = ([(m.group(1), m.end(),
               matches[i + 1].start() if i + 1 < len(matches) else len(section))
              for i, m in enumerate(matches)]
             if matches else [("", 0, len(section or ""))])
    for _title, start, end in spans:
        body = section[start:end]
        templates = _split_templates(body)
        relations: list[tuple[str, str, str]] = []
        affix_parts: list[str] = []
        affix_lang = ""
        glosses: list[str] = []
        for name, args in templates:
            if name in _REL_TEMPLATES:
                rel = next((a.lstrip(":") for a in args
                            if a.lstrip(":") in _REL_TYPES), "der")
                for lang, term in _template_links(args):
                    relations.append((rel, lang, term))
            elif name == "af":
                for arg in args:
                    if "=" in arg:
                        key, val = arg.split("=", 1)
                        if key.strip().lower().startswith("t") and val.strip():
                            glosses.append(val.strip().strip("\"'"))
                    elif re.match(r"^[a-z]{2,3}(?:-[a-z]+)?$", arg.strip()):
                        if not affix_lang:
                            affix_lang = arg.strip()
                        continue  # código de idioma, não parte
                    elif arg.strip() and not _LANG_TERM.match(arg.strip()):
                        affix_parts.append(arg.strip())
                for lang, term in _template_links(args):
                    affix_parts.append(term)
            elif name in ("l", "cog"):
                positional_lang = ""
                for arg in args:
                    if "=" in arg:
                        continue
                    if not positional_lang and re.match(
                            r"^[a-z]{2,3}(?:-[a-z]+)?$", arg.strip()):
                        positional_lang = arg.strip()
                        continue
                    term = arg.strip().lstrip("*").strip()
                    if len(term) >= 2 and positional_lang:
                        relations.append(("cog" if name == "cog" else "ref",
                                          positional_lang, term))
                for lang, term in _template_links(args):
                    relations.append(("cog" if name == "cog" else "ref",
                                      lang, term))
            elif name == "desc":
                continue  # descendentes: direção errada da cadeia
        defs = [d.strip() for d in _DEFINITION.findall(body)
                if _strip_templates(d).strip()]
        note = _strip_templates(
            body.split("====")[0].split("===Pronunciation")[0])[:280]
        blocks.append({"relations": relations, "affix_parts": affix_parts,
                       "affix_lang": affix_lang, "glosses": glosses,
                       "definitions": defs[:3], "note": note})
    return blocks


def _section_for(sections: dict[str, str], prefer: list[str]) -> str:
    """Seção no idioma preferido; senão a primeira com etimologia."""
    folded = {_fold(k): v for k, v in sections.items()}
    for want in prefer:
        for lang, body in folded.items():
            if _fold(want) in lang:
                return body
    for body in sections.values():
        if _ETYM_HEADING.search(body):
            return body
    return next(iter(sections.values()), "")


def _page_url(word: str) -> str:
    return ("https://en.wiktionary.org/wiki/"
            + urllib.parse.quote(word.replace(" ", "_")))


def _chain_step_url(term: str) -> str:
    return _page_url(term)


def build_chain(word: str, language: str = "pt-BR",
                fetch=None,
                timeout: int = TIMEOUT) -> tuple[list[Etymon], str, str]:
    """Cadeia de formas: [(termo, idioma)] do verbete até a raiz.

    Segue elos `xx:termo` (empréstimo/herança) e afixos (`af`), no máximo
    MAX_CHAIN_DEPTH, com guarda contra ciclos. O primeiro elo é sempre a
    palavra pedida. Devolve (elos, idioma_de_origem, código).
    """
    if fetch is None:
        fetch = wiktionary_wikitext
    prefer = ["portuguese"] if not str(language or "").lower().startswith("en") \
        else ["english"]
    chain: list[Etymon] = [Etymon(term=word, language="",
                                  url=_page_url(word))]
    seen = {_norm_term(word)}
    current, current_section = word, None
    origin_code, origin_lang = "", ""
    for _depth in range(MAX_CHAIN_DEPTH):
        text = fetch(current, timeout) if callable(fetch) else None
        if not text:
            break
        sections = parse_language_sections(text)
        if not sections:
            break
        if current_section is None:
            body = _section_for(sections, prefer)
        else:
            body = sections.get(current_section, "") or _section_for(
                sections, [current_section])
        blocks = parse_etymology_blocks(body)
        # Bloco com relação tem prioridade; afixo vale como elo parcial.
        target: tuple[str, str, str] | None = None
        glosses: list[str] = []
        note = ""
        for block in blocks:
            glosses.extend(block["glosses"])
            if not note and block["note"]:
                note = block["note"]
            for rel in block["relations"]:
                if rel[0] in ("der", "inh", "bor", "lbor"):
                    target = rel
                    break
            if target is not None:
                break
        if target is None:
            # Afixo: "candidus + -ātus" — o radical vira o próximo elo.
            radical = ""
            radical_lang = ""
            for block in blocks:
                for part in block["affix_parts"]:
                    if _norm_term(part) and not part.startswith("-") \
                            and _norm_term(part) not in seen:
                        radical = part
                        radical_lang = block.get("affix_lang", "")
                        break
                if radical:
                    break
            if not radical:
                if glosses and chain:
                    chain[-1].gloss = "; ".join(glosses[:2])[:160]
                if note and chain and not chain[-1].note:
                    chain[-1].note = note[:200]
                break
            code = radical_lang or "la"
            lang = LANG_NAMES.get(code, code)
            chain.append(Etymon(term=radical, language=lang,
                                language_code=code,
                                gloss="; ".join(glosses[:2])[:160],
                                note=note[:200],
                                url=_chain_step_url(radical)))
            seen.add(_norm_term(radical))
            origin_code, origin_lang = code, lang
            current, current_section = radical, "Latin"
            continue
        _rel, lang_code, term = target
        norm = _norm_term(term)
        if not norm or norm in seen:
            break
        seen.add(norm)
        lang = LANG_NAMES.get(lang_code, lang_code)
        chain.append(Etymon(term=term, language=lang,
                            language_code=lang_code,
                            gloss="; ".join(glosses[:2])[:160],
                            note=note[:200],
                            url=_chain_step_url(term)))
        origin_code, origin_lang = lang_code, lang
        # Próximo passo: seção do idioma de origem ("Latin", "Ancient Greek").
        current = term
        current_section = {"la": "Latin", "grc": "Ancient Greek",
                           "el": "Greek"}.get(lang_code, "")
        if not current_section:
            break
    if chain:
        chain[0].language = LANG_NAMES.get(
            "pt" if not str(language or "").lower().startswith("en") else "en",
            "")
    return chain, origin_lang, origin_code


# --- Logeion / Perseus (referência + leitura best-effort) ---------------

def _entry_markers(html: str) -> bool:
    """O HTML traz verbete legível (não o shell do SPA)?"""
    hay = html or ""
    return bool(re.search(r"(?i)(lewis|short|logeion|entry|definit|gloss|morpholog)",
                          hay))


def logeion_lookup(word: str, timeout: int = TIMEOUT) -> dict:
    """Referência Logeion por headword. Nunca levanta."""
    from .research import ResearchSource
    url = LOGEION_URL.format(word=urllib.parse.quote(word))
    snippet = ""
    try:
        html = _fetch_text(url, timeout=timeout)
        if html and _entry_markers(html):
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            idx = text.lower().find(word.lower())
            snippet = text[max(0, idx - 120):idx + 400].strip()[:600]
    except Exception:  # noqa: BLE001 — referência pura como fallback
        pass
    return {"source": ResearchSource(
        title=f"Logeion — {word}", url=url, snippet=snippet,
        origin="logeion", license=LOGEION_LICENSE, license_url=""), "license": LOGEION_LICENSE}


def perseus_lookup(word: str, language_code: str = "",
                   timeout: int = TIMEOUT) -> dict:
    """Referência Perseus (morfologia + ocorrências). Nunca levanta."""
    from .research import ResearchSource
    la = "greek" if language_code in ("grc", "el") else "la"
    morph_url = PERSEUS_MORPH_URL.format(
        word=urllib.parse.quote(word), lang=la)
    snippet = ""
    try:
        html = _fetch_text(morph_url, timeout=timeout)
        if html and _entry_markers(html):
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()[:600]
            snippet = text
    except Exception:  # noqa: BLE001 — referência pura como fallback
        pass
    return {"source": ResearchSource(
        title=f"Perseus — {word} (morfologia e ocorrências)", url=morph_url,
        snippet=snippet, origin="perseus", license=PERSEUS_LICENSE,
        license_url=""), "license": PERSEUS_LICENSE,
        "search_url": PERSEUS_SEARCH_URL.format(
            word=urllib.parse.quote(word))}


# --- orquestração ---------------------------------------------------------

def lookup(word: str, idea: str = "", language: str = "pt-BR",
           cache_dir: str = "cache", metrics=None,
           timeout: int = TIMEOUT) -> Etymology | None:
    """Cadeia + fontes + visuais p/ a palavra. None = sem verbete/rede.

    Ordem de custo: cache → Wiktionary (parse) → referências. Cada fonte
    externa é best-effort isolada: Logeion/Perseus nunca bloqueiam o
    Wiktionary, e nada aqui levanta para o pipeline.
    """
    head = _norm_term(word) or headword_of(idea)
    if not head:
        return None
    display = str(word or head).strip() or head
    cached = _cache_read(_cache_file(cache_dir, "etymology", head))
    if isinstance(cached, dict):
        try:
            return Etymology.from_dict(cached)
        except Exception:  # noqa: BLE001 — cache ruim: pesquisa de novo
            pass
    if metrics is not None:
        try:
            metrics.research_query()
        except Exception:  # noqa: BLE001 — métrica nunca é fatal
            pass
    try:
        chain, origin_lang, origin_code = build_chain(
            display, language, timeout=timeout)
    except Exception:  # noqa: BLE001 — sem cadeia, sem etimologia
        return None
    if len(chain) < 2:
        return None  # verbete sem ancestral: nada a encadear
    if metrics is not None:
        try:
            metrics.research_source()
        except Exception:  # noqa: BLE001 — métrica nunca é fatal
            pass
    from .research import ResearchSource
    sources: list = []
    first = chain[0]
    gloss_bits = [e.gloss for e in chain[1:] if e.gloss][:2]
    notes = [e.note for e in chain[1:] if e.note][:1]
    wikt_snippet = " → ".join(
        e.term + (f" ({e.language})" if e.language else "") for e in chain)
    if gloss_bits:
        wikt_snippet += ". " + "; ".join(gloss_bits)
    if notes:
        wikt_snippet += ". " + notes[0]
    sources.append(ResearchSource(
        title=f"Wiktionary — {display} (cadeia etimológica)",
        url=_page_url(display), snippet=wikt_snippet[:800],
        origin="wiktionary", license=WIKTIONARY_LICENSE,
        license_url=WIKTIONARY_LICENSE_URL))
    needs_classics = any(e.language_code in ("la", "grc", "el")
                         for e in chain) or origin_code in ("la", "grc", "el")
    if needs_classics:
        # These reference lookups are independent; run them in parallel.
        # The Wiktionary chain itself remains sequential because each next
        # headword depends on the previous entry's parsed etymology.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2,
                                                   thread_name_prefix="curio-ety-ref") as pool:
            futures = [pool.submit(logeion_lookup, display, timeout),
                       pool.submit(perseus_lookup, display, origin_code, timeout)]
            references = []
            for future in futures:  # stable source order despite parallel I/O
                try:
                    references.append(future.result())
                except Exception:  # noqa: BLE001 — best-effort references
                    references.append({})
        for ref in references:
            try:
                sources.append(ref["source"])
            except Exception:  # noqa: BLE001 — referência nunca é fatal
                pass
    entities, context = visual_concepts(chain, display)
    ety = Etymology(word=display, chain=chain,
                    origin_language=origin_lang, origin_code=origin_code,
                    visual_entities=entities, visual_context=context,
                    sources=sources)
    _cache_write(_cache_file(cache_dir, "etymology", head), ety.to_dict())
    return ety


def visual_concepts(chain: list[Etymon], head: str = "") -> tuple[list, list]:
    """Formas distintivas + cenário cultural p/ a etapa de mídia.

    Entidades: os elos da cadeia (sem a palavra pedida, sem afixos como
    "-ātus"). Contexto: cultura material do idioma de origem (latim →
    Roma/toga). Ex.: candidato → [candidatus, candidus] + [Roma antiga,
    toga romana, ...].
    """
    seen: set[str] = set()
    entities: list[str] = []
    origin_code = ""
    for e in chain:
        term = (e.term or "").strip()
        if not term or term.startswith("-") or term.endswith("-"):
            continue
        if _norm_term(term) == _norm_term(head):
            continue
        key = _norm_term(term)
        if not key or key in seen:
            continue
        seen.add(key)
        entities.append(term)
        if not origin_code and e.language_code:
            origin_code = e.language_code
    if not origin_code:
        for e in chain:
            if e.language_code in CULTURE_VISUALS:
                origin_code = e.language_code
                break
    context = list(CULTURE_VISUALS.get(origin_code, ([], ""))[0])
    return entities[:4], context[:3]


def enrich_chapters(chapters, etymology: Etymology | None) -> bool:
    """Preenche entidades/contexto vazios com a cadeia (não destrutivo).

    Só escreve onde a cena não declarou nada: cena da IA intacta nunca é
    reescrita. Devolve True se algo mudou (p/ forçar refazer a mídia).
    """
    if etymology is None:
        return False
    changed = False
    for ch in chapters or []:
        try:
            if not getattr(ch, "visual_entities", None) and etymology.visual_entities:
                ch.visual_entities = list(etymology.visual_entities[:4])
                changed = True
            if not getattr(ch, "context", None) and etymology.visual_context:
                ch.context = list(etymology.visual_context[:3])
                changed = True
        except Exception:  # noqa: BLE001 — cena estranha: pula
            continue
    return changed


def prompt_block(etymology: Etymology | None, language: str = "pt-BR") -> str:
    """Bloco de etimologia p/ o prompt do roteiro (cadeia + URLs).

    Cabeçalho manda PARAFRASEAR: a cadeia fundamenta, o verbete nunca é
    transcrito no vídeo.
    """
    if etymology is None or len(etymology.chain) < 2:
        return ""
    english = str(language or "").lower().startswith("en")
    if english:
        head = ("SPECIALIZED ETYMOLOGY (Wiktionary/Logeion/Perseus — "
                "PARAPHRASE in your own words, never transcribe the entry):")
    else:
        head = ("ETIMOLOGIA ESPECIALIZADA (Wiktionary/Logeion/Perseus — "
                "PARAFRASEIE com suas palavras, nunca transcreva o verbete):")
    lines = [head, f"cadeia: {etymology.chain_text()}"]
    for e in etymology.chain[1:]:
        extra = "; ".join(p for p in (e.gloss, e.note) if p)[:200]
        if extra:
            lines.append(f"  {e.term}: {extra}")
    seen_urls: set[str] = set()
    for e in etymology.chain:
        if e.url and e.url not in seen_urls:
            seen_urls.add(e.url)
            lines.append(f"  verbete ({e.origin}): {e.url}")
    for src in (etymology.sources or [])[:3]:
        url = getattr(src, "url", "") or ""
        origin = getattr(src, "origin", "") or ""
        if url and url not in seen_urls:
            seen_urls.add(url)
            lines.append(f"  fonte ({origin}): {url}")
    return "\n".join(lines)
