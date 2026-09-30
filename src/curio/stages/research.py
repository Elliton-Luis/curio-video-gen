"""Pesquisa web p/ grounding do roteiro (RAG leve, sem chave).

Todo texto do vídeo precisa de ao menos UMA fonte real — nunca só a IA.
Fluxo: extrai palavras-chave da ideia → consulta a Wikipedia (sem chave,
confiável) → monta um pack de fontes (título, URL, trechos) que é
injetado no prompt do LLM e registrado em `sources.json`.

Sem nenhuma fonte: falha explícita (ResearchError) — nunca roteiro
"só IA" silencioso. Sem rede: a mesma falha, com mensagem acionável.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

USER_AGENT = "curio/0.1 (educational local video tool; no contact)"
WIKI_TIMEOUT = 20
EXTRACT_CHARS = 1200  # por fonte: suficiente p/ fatos, cabe no prompt
PROMPT_BUDGET_CHARS = 2500  # teto total do pack injetado no LLM

STOP_PT = {
    "para", "como", "mais", "muito", "isso", "esse", "esta", "este",
    "aquele", "aquela", "foram", "eram", "sido", "entre", "sobre",
    "quando", "onde", "qual", "quais", "todo", "toda", "todos", "todas",
    "cada", "muita", "muitas", "muitos", "pouco", "pouca", "mesmo",
    "mesma", "outro", "outra", "outros", "outras", "depois", "antes",
    "durante", "sempre", "nunca", "também", "através", "porque", "porém",
    "entretanto", "portanto", "então", "assim", "aqui", "agora", "hoje",
    "ainda", "coisa", "algo", "alguém", "ninguém", "tudo", "nada",
    "seja", "sejam", "pode", "podem", "deve", "devem", "fazer", "fez",
    "fazem", "seria", "seriam", "tinha", "tinham", "esteve", "sendo",
    "teria", "teriam", "pois", "qualquer", "tanto", "quanto", "desde",
    "até", "meio", "grande", "pequeno", "novo", "velho", "primeiro",
    "último", "você", "eles", "elas", "nós", "isso", "isto", "aquilo",
    "meu", "minha", "seu", "sua", "nosso", "nossa", "esse", "essa",
    "este", "esta", "fato", "verdade", "mentira", "realmente", "anos",
}

STOP_EN = {
    "what", "why", "how", "when", "where", "who", "which", "that",
    "this", "with", "from", "into", "about", "really", "does", "happen",
    "when", "your", "there", "their", "they", "them", "then", "than",
    "also", "just", "like", "more", "most", "very", "much", "many",
    "some", "such", "only", "over", "under", "between", "through",
}


class ResearchError(RuntimeError):
    """Nenhuma fonte encontrada: roteiro bloqueado (exige ≥1 fonte)."""


@dataclass
class ResearchSource:
    """Uma fonte web real p/ grounding (título, URL, trechos)."""
    title: str
    url: str
    snippet: str = ""
    origin: str = "wikipedia"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchSource":
        return cls(title=str(d.get("title", "")),
                   url=str(d.get("url", "")),
                   snippet=str(d.get("snippet", "")),
                   origin=str(d.get("origin", "wikipedia")))


def _strip_acc(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in norm if not unicodedata.combining(c))


def extract_keywords(text: str, language: str = "pt-BR",
                     max_n: int = 4) -> list[str]:
    """Palavras-chave p/ busca web: substantivos/conteúdo, sem stopwords."""
    stop = STOP_EN if str(language or "").lower().startswith("en") else STOP_PT
    words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", text or "")
    freq: dict[str, int] = {}
    keep: dict[str, str] = {}
    for w in words:
        base = _strip_acc(w)
        if base in stop or len(base) < 4:
            continue
        freq[base] = freq.get(base, 0) + 1
        keep.setdefault(base, w.strip("?.!,;:"))
    ranked = sorted(freq, key=lambda b: -freq[b])
    return [keep[b] for b in ranked[:max_n]]


def _get_json(url: str, timeout: int = WIKI_TIMEOUT):
    import json
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _wiki_lang(language: str) -> str:
    return "en" if str(language or "").lower().startswith("en") else "pt"


def wikipedia_search(query: str, language: str = "pt-BR",
                     limit: int = 5,
                     timeout: int = WIKI_TIMEOUT) -> list[dict]:
    """Busca títulos na Wikipedia (sem chave). Retorna [{title}]."""
    lang = _wiki_lang(language)
    params = {"action": "query", "list": "search", "srsearch": query,
              "srlimit": str(limit), "format": "json"}
    url = (f"https://{lang}.wikipedia.org/w/api.php?"
           + urllib.parse.urlencode(params))
    try:
        data = _get_json(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — rede falhou: lista vazia
        raise ResearchError(f"Wikipedia indisponível ({exc}). "
                            "Verifique a rede e tente de novo.") from exc
    out = []
    for hit in ((data.get("query") or {}).get("search") or []):
        title = str(hit.get("title", "")).strip()
        if title:
            out.append({"title": title})
    return out


def wikipedia_extract(title: str, language: str = "pt-BR",
                      timeout: int = WIKI_TIMEOUT) -> ResearchSource:
    """Baixa título + URL + introdução do artigo (texto puro)."""
    lang = _wiki_lang(language)
    params = {"action": "query", "prop": "extracts", "exintro": "1",
              "explaintext": "1", "exchars": str(EXTRACT_CHARS),
              "titles": title, "format": "json"}
    url = (f"https://{lang}.wikipedia.org/w/api.php?"
           + urllib.parse.urlencode(params))
    try:
        data = _get_json(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — pula p/ o próximo artigo
        raise ResearchError(f"extract de '{title}' falhou ({exc}).") from exc
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        if "missing" in page:
            continue
        real = str(page.get("title", title))
        extract = re.sub(r"\s+", " ", str(page.get("extract", ""))).strip()
        page_url = ("https://" + lang + ".wikipedia.org/wiki/"
                    + urllib.parse.quote(real.replace(" ", "_")))
        return ResearchSource(title=real, url=page_url,
                              snippet=extract[:EXTRACT_CHARS])
    raise ResearchError(f"artigo '{title}' sem conteúdo na Wikipedia.")


_JUNK_HIT = re.compile(
    r"(?i)\((telenovela|desambigua[çc][aã]o|disambiguation)\)"
    r"|^lista de\b|^list of\b")


def _is_junk_hit(title: str) -> bool:
    """Descarta hits de desambiguação/entretenimento/listicles."""
    return bool(_JUNK_HIT.search(title or ""))


def duckduckgo_abstract(query: str) -> ResearchSource | None:
    """Resposta instantânea do DDG (sem chave). Best-effort: None se vazio."""
    params = {"q": query, "format": "json", "no_html": "1",
              "skip_disambig": "1"}
    url = ("https://api.duckduckgo.com/?" + urllib.parse.urlencode(params))
    try:
        data = _get_json(url, timeout=15)
    except Exception:  # noqa: BLE001 — DDG instável: ignora em silêncio
        return None
    text = str(data.get("AbstractText", "")).strip()
    url_out = str(data.get("AbstractURL", "")).strip()
    if not text or not url_out:
        return None
    return ResearchSource(title=text.split(".")[0][:80] or query,
                          url=url_out, snippet=text[:EXTRACT_CHARS],
                          origin="duckduckgo")


def research_topic(idea: str, language: str = "pt-BR", max_sources: int = 3,
                   metrics=None, timeout: int = WIKI_TIMEOUT) -> list[ResearchSource]:
    """Pesquisa a ideia na web. Exige ≥1 fonte ou levanta ResearchError.

    Ordem: ideia verbatim → palavras-chave → DDG (complemento).
    Dedup por URL. Registra contadores em metrics quando presente.
    """
    if not (idea or "").strip():
        raise ValueError("ideia vazia — nada para pesquisar")
    queries = [idea.strip()]
    queries += extract_keywords(idea, language)
    seen_urls: set[str] = set()
    sources: list[ResearchSource] = []
    n_queries = 0
    for query in queries:
        if len(sources) >= max_sources:
            break
        n_queries += 1
        if metrics is not None:
            metrics.research_query()
        try:
            hits = wikipedia_search(query, language, timeout=timeout)
        except ResearchError:
            if sources:
                break
            raise
        for hit in hits:
            if len(sources) >= max_sources:
                break
            if _is_junk_hit(hit["title"]):
                continue
            try:
                src = wikipedia_extract(hit["title"], language,
                                        timeout=timeout)
            except ResearchError:
                continue
            if not src.snippet or src.url in seen_urls:
                continue
            seen_urls.add(src.url)
            sources.append(src)
            if metrics is not None:
                metrics.research_source()
    if len(sources) < max_sources:
        n_queries += 1
        if metrics is not None:
            metrics.research_query()
        ddg = duckduckgo_abstract(idea.strip())
        if ddg and ddg.url not in seen_urls:
            seen_urls.add(ddg.url)
            sources.append(ddg)
            if metrics is not None:
                metrics.research_source()
    if not sources:
        raise ResearchError(
            f"nenhuma fonte encontrada p/ {idea.strip()[:80]!r}. "
            "Sem fonte real o roteiro não é gerado (exige ≥1 fonte). "
            "Verifique a rede ou reformule a ideia com termos buscáveis.")
    return sources[:max_sources]


def format_for_prompt(sources: list[ResearchSource],
                      language: str = "pt-BR") -> str:
    """Bloco de fontes p/ injetar no prompt do LLM (com teto de tamanho)."""
    english = str(language or "").lower().startswith("en")
    head = ("MANDATORY SOURCES (web research — use ONLY these facts):"
            if english else
            "FONTES OBRIGATÓRIAS (pesquisa web — use SOMENTE estes fatos):")
    parts = [head]
    used = len(head)
    for i, src in enumerate(sources, 1):
        chunk = f"[{i}] {src.title} — {src.url}\n    trecho: {src.snippet}"
        if used + len(chunk) > PROMPT_BUDGET_CHARS:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)
