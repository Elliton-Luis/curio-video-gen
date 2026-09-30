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


# --- Verificação de fundamentação (a IA não inventa) -------------------
# O prompt manda a IA não inventar, prompt não é garantia. Aqui o número
# é conferido: toda data, medida, quantidade e percentual afirmado na
# narração precisa aparecer em alguma fonte. O que não bate é listado
# como "não verificado" e vai para o relatório — não é apagado do texto
# (a decisão editorial é do autor), mas fica visível e não se apresenta
# como confirmado.

# Unidades reconhecidas: PT e EN. Sem unidade, só entram anos de 4 dígitos
# e decimais — assim "1" ou "2" de uma contagem de capítulos não vira falso
# positivo.
_UNITS = (
    r"%|por\s?cento|porcento|per\s?cent|percent|anos?|years?|dias?|days?|"
    r"meses|months?|anos|séculos?|seculos?|centuries|almil|mil|million|milhão|"
    r"milhões|millions|bilhão|billions|trilhão|trilhões|"
    r"km|quilômetro|quilômetros|quilos?|kg|gramas?|g|miligrama|mg|"
    r"ml|mililitro|litros?|l|metros?|m|cm|mm|quilômetros|"
    r"graus?|°|°c|°f|hz|khz|mhz|ghz|nm|µm|um|micra|microns|"
    r"times|vezes|people|pessoas|habitantes|habitantes|cidades|aldeias|"
    r"espécies|species|asteroides|planetas|continentes"
)
_FACT_RE = re.compile(
    r"(?<![\w.])"
    r"(\d{1,3}(?:[.\s]\d{3})+|\d+(?:[.,]\d+)?)"  # 1.500 | 3,5 | 42
    r"(\s*(?:" + _UNITS + r"))?",
    re.IGNORECASE,
)

# Números que aparecem em qualquer texto sem serem afirmação factual.
_TRIVIAL = {"0", "1", "2", "3", "4", "5", "10", "100", "1000", "mil"}


def _norm_number(raw: str) -> str:
    """Normaliza p/ comparar: '1.500' e '1500' viram a mesma coisa."""
    digits = raw.replace(".", "").replace(" ", "").replace(" ", "")
    if "," in digits:
        digits = digits.replace(",", ".")
    digits = digits.rstrip("0").rstrip(".") if "." in digits else digits
    return digits


def _fact_tokens(text: str) -> set[str]:
    """Fatos verificáveis de um texto.

    Entra tudo que é conferível: número de 2+ dígitos ("900 crateras"),
    decimal ("3,5"), ano de 4 dígitos, e qualquer número com unidade
    ("687 dias", "40%"). Fica de fora o número solto de um dígito
    ("1", "7") e a contagem genérica que a IA usa para pontuar o texto —
    checá-los geraria ruído suficiente para o relatório ser ignorado.
    Números por extenso ("dois", "três") não são extraídos: não têm
    forma canônica para comparar com a fonte.
    """
    out: set[str] = set()
    for num, unit in _FACT_RE.findall(text or ""):
        norm = _norm_number(num)
        if not norm or norm in _TRIVIAL:
            continue
        is_year = bool(re.fullmatch(r"\d{4}", norm))
        is_decimal = ("," in num) or ("." in num and len(num) > 4)
        if not (unit or is_year or is_decimal or len(norm) >= 2):
            continue
        out.add(norm)
        if unit:
            out.add(f"{norm} {re.sub(r'\\s+', ' ', unit.strip().lower())}")
    return out


def verify_grounding(script_text: str, sources: list[ResearchSource],
                     language: str = "pt-BR") -> dict:
    """Confere se os fatos do roteiro estão nas fontes (anti-invenção).

    Devolve {"checked": n, "grounded": [...], "unverified": [...],
    "coverage": 0.0–1.0}. `unverified` são os fatos que o texto afirma e
    nenhuma fonte sustenta — é o mecanismo que torna a promessa "a IA
    nunca inventa" auditável em vez de só prometida no prompt.

    É conferência de números, não prova semântica: um texto pode parafrasear
    um fato sem repetir o mesmo numeral. Por isso o relatório é
    informativo e a cobertura vai para o metadata/relatório do projeto.
    """
    script_facts = _fact_tokens(script_text)
    if not script_facts:
        return {"checked": 0, "grounded": [], "unverified": [],
                "coverage": 1.0, "language": language}
    haystack = " ".join(f"{s.title} {s.snippet} {s.url}" for s in sources)
    source_facts = _fact_tokens(haystack)
    # Formas alternativas: ano "44" casa com "44 a.C." e com "44".
    grounded, unverified = [], []
    for fact in sorted(script_facts):
        if fact in source_facts or fact.split()[0] in source_facts:
            grounded.append(fact)
        else:
            unverified.append(fact)
    checked = len(grounded) + len(unverified)
    return {
        "checked": checked,
        "grounded": grounded,
        "unverified": unverified,
        "coverage": round(len(grounded) / checked, 3) if checked else 1.0,
        "language": language,
    }
