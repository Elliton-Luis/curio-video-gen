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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from ..ua import user_agent
from ..runlog import event as run_event

USER_AGENT = user_agent()  # noqa: N816 — nome histórico, usado por testes
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
    license: str = ""
    license_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchSource":
        return cls(title=str(d.get("title", "")),
                   url=str(d.get("url", "")),
                   snippet=str(d.get("snippet", "")),
                   origin=str(d.get("origin", "wikipedia")),
                   license=str(d.get("license", "") or ""),
                   license_url=str(d.get("license_url", "") or ""))


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
    """GET JSON da API da Wikimedia, com retry em 429/5xx.

    A Wikimedia não sinaliza rate limit com 429 e corpo de erro: é um
    429 puro. Sem retry, uma rajada de queries (que é justamente o que os
    perfis de gênero provocam, porque cada um tem mais termos) mata a
    pesquisa no meio. Duas tentativas com espera resolvem o caso comum,
    que é o servidor pedir para voltar em instantes.
    """
    import json
    import time
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ultima: Exception | None = None
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            ultima = exc
            if exc.code == 429:
                esperar = 1.5 * (tentativa + 1)
            elif exc.code >= 500:
                esperar = 0.8 * (tentativa + 1)
            else:
                # Não é rate limit nem servidor: repetir não muda nada.
                # Ainda vira ResearchError, que é o contrato de _get_json.
                raise ResearchError(f"Wikipedia recusou a requisição "
                                    f"(HTTP {exc.code}).") from exc
        except Exception as exc:  # noqa: BLE001 — rede falhou
            ultima = exc
            esperar = 0.5 * (tentativa + 1)
        if tentativa < 2:
            codigo = getattr(ultima, "code", None)
            motivo = f"HTTP {codigo}" if codigo else type(ultima).__name__
            run_event("retry", f"Wikipedia: {motivo}; tentando novamente "
                      f"em {esperar:.1f}s", provider="wikipedia",
                      attempt=tentativa + 1, status=codigo,
                      delay_seconds=esperar, error=str(ultima))
            time.sleep(esperar)
    codigo = getattr(ultima, "code", None)
    if codigo == 429:
        from ..ua import aviso_contato
        raise ResearchError(
            "A Wikimedia recusou a requisição (HTTP 429, rate limit). "
            + (aviso_contato() + " " if aviso_contato() else "")
            + "A rede está boa; o problema é o User-Agent."
        ) from ultima
    raise ResearchError(f"Wikipedia indisponível ({ultima}). "
                        "Verifique a rede e tente de novo.") from ultima


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


class ResearchResult:
    """Fontes aceitas, as rejeitadas e por quê, e a entidade-alvo.

    Não é só uma lista de fontes: é a resposta à pergunta "por que estas
    fontes e não outras?". Sem a parte rejeitada com motivo, um desvio de
    entidade é invisível — foi assim que "Serra Gaúcha" e "Michel Temer"
    entraram como fundamentação para a história de um santo do século VI.
    """

    def __init__(self, target, sources: list[ResearchSource],
                 rejected: list[tuple[ResearchSource, str, str]] | None = None,
                 tried_queries: list[str] | None = None,
                 weak: bool = False,
                 weak_warnings: list[str] | None = None):
        self.target = target
        self.sources = sources
        self.rejected = rejected or []
        self.tried_queries = tried_queries or []
        self.genre = ""
        # weak=True: fontes vieram do passe relaxado (núcleo, sem
        # discriminante) ou não há fontes — o roteiro pode ser gerado,
        # mas o grounding é fraco e o pipeline deve avisar.
        self.weak = bool(weak)
        self.weak_warnings = list(weak_warnings or [])
        self.facts: list[dict] = []
        self.complementary_queries: list[dict] = []
        self.unresolved_gaps: list[dict] = []

    def __iter__(self):
        # Compatibilidade com quem só quer a lista de fontes.
        return iter(self.sources)

    def __len__(self):
        return len(self.sources)

    def __getitem__(self, i):
        return self.sources[i]


def research_topic(idea: str, language: str = "pt-BR", max_sources: int = 3,
                   metrics=None, timeout: int = WIKI_TIMEOUT,
                   cfg=None, require_relevance: bool = True,
                   genre: str = "", allow_weak: bool = False) -> ResearchResult:
    """Pesquisa a ideia, ACEITANDO SÓ fontes sobre o referente pretendido.

    A ordem importa:

    1. resolve a entidade-alvo (quem o vídeo é sobre, e o que a distingue
       de homônimos);
    2. consulta a Wikipedia primeiro com as queries do alvo, depois com a
       ideia verbatim e as palavras-chave;
    3. cada fonte passa pelo portão de relevância antes de contar;
    4. se nada passar, levanta ResearchError explaining o motivo.

    Passo 3 é o que faltava. Antes, qualquer artigo que citasse a
    palavra do tema era aceito: o grounding confirmava a fidelidade do
    roteiro a fontes que já estavam erradas, e o sistema se autovalidia em
    cima do próprio desvio.
    """
    from . import entity as entity_stage

    if not (idea or "").strip():
        raise ValueError("ideia vazia — nada para pesquisar")

    target = entity_stage.resolve_entity(idea, cfg=cfg, language=language,
                                         metrics=metrics)
    queries: list[str] = []
    tried_queries: list[str] = []
    seen_q: set[str] = set()

    def _add(q: str) -> None:
        q = (q or "").strip()
        if q and q.lower() not in seen_q:
            seen_q.add(q.lower())
            queries.append(q)

    # O primeiro passe é amplo; os termos editoriais refinam somente depois.
    _add(target.name or idea)

    def _contido(termo: str, base: str) -> bool:
        """O termo do gênero já está no nome do alvo?

        "Etimologia da palavra salário" + "etimologia" seria uma query que
        repete a mesma palavra duas vezes, e a busca da Wikipedia pune
        isso. Só a palavra inteira conta: "origem da palavra" NÃO está
        contida em "Etimologia da palavra salário" e continua valendo.
        """
        return any(p in base.lower() for p in termo.lower().split())

    # O gênero entra ANTES da busca, não depois: um perfil de etimologia
    # precisa perguntar "cognato" e "forma antiga", e um de pessoa precisa
    # perguntar "biografia" e "obras". Aplicar a estratégia só no roteiro
    # deixaria a pesquisa do gênero igual à genérica.
    from . import editorial as _editorial
    perfil = _editorial.get(genre)
    if perfil is not None:
        # Para uma ENTIDADE, a query é o nome mais o termo do gênero:
        # "São Bento de Núrsia biografia" é uma boa query da Wikipedia.
        #
        # Para uma PERGUNTA DE TEMA o caso é outro. O nome do alvo costuma
        # ser a pergunta reescrita, e pendurar o termo do gênero nela dá
        # "por que o céu é azul? mecanismo", que não é nada. O estágio de
        # entidade já devolveu topic_terms prontos e específicos; uso o
        # MAIS CURTO deles como cabeça, que é o substantivo de verdade, e o resto
        # entra como query solo.
        base = (target.name or "").strip()
        if not target.is_entity and target.topic_terms:
            cabeca = min(target.topic_terms, key=len)
            for t in target.topic_terms:
                _add(t)
            base = cabeca
        for q in perfil.research.queries:
            if not base:
                _add(q)
                continue
            if _contido(q, base):
                continue
            _add(f"{base} {q}")
    for q in target.search_queries:
        _add(q)
    _add(idea.strip())
    for kw in extract_keywords(idea, language):
        _add(kw)

    seen_urls: set[str] = set()
    sources: list[ResearchSource] = []
    rejected: list[tuple[ResearchSource, str, str]] = []

    def _consider(src: ResearchSource, query: str) -> None:
        """Portão de relevância. Só daqui para baixo a fonte é groundwork."""
        if not src.snippet or src.url in seen_urls:
            return
        if require_relevance:
            motivo, detalhe = entity_stage.source_verdict(src, target)
            if motivo != entity_stage.REASON_OK:
                rejected.append((src, motivo, detalhe))
                if metrics is not None:
                    metrics.research_record_rejection(motivo)
                return
        seen_urls.add(src.url)
        sources.append(src)
        if metrics is not None:
            metrics.research_source()
        run_event("result", f"Fonte aceita: {src.title}", operation="research_source",
                  title=src.title, url=src.url, query=query)

    for query in queries:
        if len(sources) >= max_sources:
            break
        if metrics is not None:
            metrics.research_query()
        tried_queries.append(query)
        run_event("search", f"Pesquisa: {query}", operation="research_query", query=query)
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
            _consider(src, query)

    if len(sources) < max_sources:
        if metrics is not None:
            metrics.research_query()
        ddg = duckduckgo_abstract(idea.strip())
        tried_queries.append(idea.strip())
        run_event("search", f"Pesquisa DuckDuckGo: {idea.strip()}",
                  operation="research_query", query=idea.strip(), provider="duckduckgo")
        if ddg is not None:
            _consider(ddg, "duckduckgo")

    weak = False
    weak_warnings: list[str] = []
    if not sources and rejected:
        # Passe 2 — núcleo: o artigo certo com qualificadores a mais no
        # pedido ("... de Carvalho") ou discriminante alucinado ("Saramago")
        # cai aqui em vez de zerar o vídeo. Homônimo em `forbidden`
        # continua barrado.
        relaxed = _relaxed_nucleus_accept(rejected, target, max_sources)
        if relaxed:
            weak = True
            for src in relaxed:
                seen_urls.add(src.url)
                sources.append(src)
                if metrics is not None:
                    metrics.research_source()
            weak_warnings.append(
                f"grounding fraco: {len(relaxed)} fonte(s) aceita(s) por "
                "núcleo no título, sem discriminante "
                f"({', '.join(s.title[:50] for s in relaxed)}). "
                "Fatos devem ser ditos com incerteza explícita.")
            run_event("fallback",
                      f"Pesquisa: passe relaxado (núcleo) aceitou "
                      f"{len(relaxed)} fonte(s)",
                      operation="research", entity=target.name,
                      accepted=len(relaxed))
    if not sources and target is not None:
        # Passe 3 — nova cabeça: núcleo sem qualificadores + EN. Só quando
        # o estrito zerou: com ≥1 fonte, novas cabeças trazem duplicatas
        # (o mesmo artigo em outro idioma/URL) por pouco ganho.
        for query in _reformulated_queries(idea, target, language, seen_q):
            if len(sources) >= max_sources:
                break
            _add(query)
            for lang in ([language]
                         + (["en"] if _wiki_lang(language) == "pt" else [])):
                if len(sources) >= max_sources:
                    break
                try:
                    if metrics is not None:
                        metrics.research_query()
                    tried_queries.append(query)
                    run_event("search", f"Pesquisa: {query} ({lang})",
                              operation="research_query", query=query, language=lang)
                    hits = wikipedia_search(query, lang, timeout=timeout)
                except ResearchError:
                    continue
                for hit in hits:
                    if len(sources) >= max_sources:
                        break
                    if _is_junk_hit(hit["title"]):
                        continue
                    try:
                        src = wikipedia_extract(hit["title"], lang,
                                                timeout=timeout)
                    except ResearchError:
                        continue
                    before = len(sources)
                    _consider(src, query)
                    if len(sources) == before and require_relevance:
                        # Candidata barrada no estrito entra no bolo do
                        # passe 2 ao final (núcleo), sem nova rede.
                        pass
        if not sources and rejected:
            relaxed = _relaxed_nucleus_accept(rejected, target, max_sources)
            fresh = [s for s in relaxed if s.url not in seen_urls]
            if fresh:
                weak = True
                for src in fresh:
                    seen_urls.add(src.url)
                    sources.append(src)
                    if metrics is not None:
                        metrics.research_source()
                weak_warnings.append(
                    f"grounding fraco (2º passe): {len(fresh)} fonte(s) por "
                    "núcleo no título.")

    if not sources:
        if allow_weak:
            # Garantia de texto: o roteiro sai com incerteza explícita
            # (o prompt já manda omitir ou ressalvar o que não está nas
            # fontes) em vez do erro fatal. Só cai aqui quando NADA —
            # nem estrito, nem núcleo, nem EN — falou do tema.
            msg = ("pesquisa sem fonte aceita; roteiro segue com "
                   "grounding fraco e incerteza explícita")
            run_event("fallback", msg, operation="research",
                      entity=target.name, query_count=len(tried_queries),
                      rejected=len(rejected))
            res = ResearchResult(target, [], rejected, tried_queries, weak=True,
                                 weak_warnings=[msg])
            res.genre = genre
            return res
        run_event("error", f"Pesquisa sem fontes aceitas após {len(tried_queries)} consulta(s)",
                  operation="research", entity=target.name,
                  query_count=len(tried_queries), rejected=len(rejected),
                  rejection_reasons={m: sum(1 for _, reason, _ in rejected
                                            if reason == m)
                                     for _, m, _ in rejected})
        raise ResearchError(_no_usable_source_message(idea, target, rejected))

    if not run_event("result", f"Pesquisa: {len(sources)} fonte(s) aceita(s), "
                     f"{len(rejected)} rejeitada(s)", operation="research",
                     target=target.name, source_titles=[s.title[:60]
                                                        for s in sources[:5]]):
        print(entity_stage.explain(target, sources, rejected))
    res = ResearchResult(target, sources[:max_sources], rejected, tried_queries,
                          weak=weak, weak_warnings=weak_warnings)
    res.genre = genre
    res.etymology = None
    if (genre or "").strip().lower() == "etymology":
        # Fontes especializadas SOMAM às gerais: a cadeia (Wiktionary →
        # Logeion/Perseus) fundamenta o roteiro e as entidades visuais.
        # Best-effort isolada: nunca derruba a pesquisa geral.
        try:
            from . import etymology as etymology_stage
            head = (etymology_stage.headword_of(idea)
                    or etymology_stage.headword_of(
                        "", getattr(target, "name", "") or ""))
            if head:
                res.etymology = etymology_stage.lookup(
                    head, idea, language,
                    getattr(cfg, "cache_dir", "cache") or "cache",
                    metrics, timeout)
                if res.etymology is not None:
                    run_event("result",
                              "Etimologia: " + res.etymology.chain_text(),
                              operation="research_etymology",
                              word=res.etymology.word,
                              origin=res.etymology.origin_language,
                              sources=len(res.etymology.sources))
        except Exception as exc:  # noqa: BLE001 — segue só com gerais
            run_event("warning", f"Etimologia indisponível ({exc}); "
                      "seguindo só com fontes gerais",
                      operation="research_etymology", error=str(exc))
            res.etymology = None
    _complete_research(res, idea, language, cfg, metrics, timeout)
    return res


def _source_facts(sources) -> list[dict]:
    """Extract verbatim sentences, deduplicating evidence without inventing claims."""
    facts, seen = [], set()
    for source in sources:
        for quote in re.split(r"(?<=[.!?])\s+", source.snippet.strip()):
            key = " ".join(quote.casefold().split())
            if len(quote) < 8 or key in seen:
                continue
            seen.add(key)
            facts.append({"quote": quote, "url": source.url, "title": source.title})
    return facts


def _plan_gaps(idea, sources, language, cfg, metrics):
    """One small planning call, only when an LLM is already configured."""
    from . import nvidia
    if cfg is None or not nvidia.any_llm_available():
        return {}
    prompt = (
        'Return JSON {"facts": [{"quote": "verbatim source sentence", "url": "source URL"}], '
        '"gaps": [{"query": "specific search", "reason": "why essential to answer the topic", '
        '"support_terms": ["specific evidence term", "another evidence term"]}]}. '
        'Select only relevant supported facts; copy quotes exactly. Identify at most 3 '
        'essential unanswered gaps for a correct, compelling short narration. No trivia, '
        'no generic background searches, no gaps already answered. Never invent answers. '
        'Keep queries about the intended subject. Empty gaps when evidence is sufficient.')
    try:
        data, _ = nvidia.complete_json(
            prompt, f"Topic: {idea}\nUse queries and reasons in {language}.\n" +
            format_for_prompt(sources, language),
            cfg.nvidia_model, cfg.nvidia_base_url, cfg.nvidia_timeout, metrics,
            or_model=cfg.openrouter_model, or_base_url=cfg.openrouter_base_url,
            extra=cfg.llm_overrides())
        return data
    except nvidia.NvidiaError as exc:
        run_event("warning", "Planejamento de lacunas indisponível; preservando fontes",
                  operation="research_gaps", error=str(exc))
        return {}


def _complete_research(result, idea, language, cfg, metrics, timeout):
    """Bounded follow-up inside the existing research stage, not a second pipeline."""
    from . import entity
    plan = _plan_gaps(idea, result.sources, language, cfg, metrics)
    if not isinstance(plan, dict):
        plan = {}
    initial_urls = {s.url for s in result.sources}
    result.facts = _source_facts(result.sources)
    selected = []
    planned_facts = plan.get("facts") or []
    if not isinstance(planned_facts, list):
        planned_facts = []
    for fact in planned_facts[:12]:
        if not isinstance(fact, dict):
            continue
        quote, url = str(fact.get("quote") or ""), str(fact.get("url") or "")
        if len(quote) >= 8 and any(s.url == url and quote in s.snippet for s in result.sources):
            selected.append({"quote": quote, "url": url})
    queries = {" ".join(q.casefold().split()) for q in result.tried_queries}
    urls = {s.url for s in result.sources}
    planned_gaps = plan.get("gaps") or []
    if not isinstance(planned_gaps, list):
        planned_gaps = []
    for gap in planned_gaps[:3]:
        if not isinstance(gap, dict):
            continue
        query = str(gap.get("query") or "").strip()[:180]
        reason = str(gap.get("reason") or "").strip()[:250]
        raw_terms = gap.get("support_terms") or []
        if not isinstance(raw_terms, list):
            continue
        terms = [str(t).casefold().strip() for t in raw_terms
                 if isinstance(t, str) and len(t.strip()) >= 3][:4]
        key = " ".join(query.casefold().split())
        if not query or not reason or not terms:
            continue
        def supported():
            return any(all(term in f["quote"].casefold() for term in terms)
                       for f in result.facts)
        if supported():
            continue
        if key in queries:
            result.unresolved_gaps.append({"query": query, "reason": reason})
            run_event("warning", f"Lacuna já pesquisada, ainda sem suporte: {query}",
                      operation="research_gap_unresolved", query=query, reason=reason)
            continue
        queries.add(key)
        result.tried_queries.append(query)
        result.complementary_queries.append({"query": query, "reason": reason})
        if metrics is not None:
            metrics.research_query()
            metrics.research_complementary_queries += 1
        run_event("search", f"Pesquisa complementar: {query}",
                  operation="research_complementary", query=query, reason=reason)
        try:
            hits = wikipedia_search(query, language, timeout=timeout)
        except ResearchError:
            hits = []
        for hit in hits[:3]:
            if _is_junk_hit(hit["title"]):
                continue
            try:
                source = wikipedia_extract(hit["title"], language, timeout=timeout)
            except ResearchError:
                continue
            if source.url in urls or not source.snippet:
                continue
            verdict, detail = entity.source_verdict(source, result.target)
            if verdict != entity.REASON_OK:
                result.rejected.append((source, verdict, detail))
                if metrics is not None:
                    metrics.research_record_rejection(verdict)
                continue
            # Complementary sources must contain evidence for this exact gap.
            evidence = _source_facts([source])
            if not any(all(t in f["quote"].casefold() for t in terms) for f in evidence):
                continue
            urls.add(source.url)
            result.sources.append(source)
            result.facts = _source_facts(result.sources)
            if metrics is not None:
                metrics.research_source()
            run_event("result", f"Fonte complementar aceita: {source.title}",
                      operation="research_source", url=source.url, title=source.title, query=query)
            break
        if not supported():
            result.unresolved_gaps.append({"query": query, "reason": reason})
            run_event("warning", f"Lacuna não resolvida: {query}",
                      operation="research_gap_unresolved", query=query, reason=reason)
    if selected:
        # Only validated literal quotes enter the consolidated initial context.
        selected.extend(f for f in result.facts if f["url"] not in initial_urls)
        result.facts = selected
    run_event("result", "Contexto de pesquisa consolidado",
              operation="research_context", facts=len(result.facts),
              sources=len(result.sources), complementary_queries=len(result.complementary_queries),
              unresolved_gaps=result.unresolved_gaps)


def _relaxed_nucleus_accept(
    rejected: list[tuple[ResearchSource, str, str]],
    target, max_sources: int,
) -> list[ResearchSource]:
    """Segundo passe: núcleo no título, sem exigir discriminante.

    "Guerra do Balde" passa para alvo "Guerra do Balde de Carvalho";
    "Flávio Bolsonaro" continua barrado (núcleo ausente) e homônimos
    em `forbidden` continuam barrados. É fallback honesto: quem aceitar
    aqui entra com status fraco, nunca como "confirmado".
    """
    from . import entity as entity_stage
    if target is None or not getattr(target, "is_entity", True):
        return []
    if not (getattr(target, "name", "") or "").strip():
        return []
    out: list[ResearchSource] = []
    seen: set[str] = set()
    for src, motivo, _det in rejected:
        if len(out) >= max_sources:
            break
        if motivo not in (entity_stage.REASON_ENTITY,
                          entity_stage.REASON_DISCRIMINANT):
            continue
        if src.url in seen:
            continue
        texto = f"{src.title} {src.snippet}"
        if target.matched_forbidden(texto):
            continue
        if not target.nucleus_in_title(src.title):
            continue
        seen.add(src.url)
        out.append(src)
    return out


def _reformulated_queries(idea: str, target, language: str,
                          seen: set[str]) -> list[str]:
    """Queries de segundo passe: núcleo sem qualificadores + EN.

    A cabeça errada ("de Carvalho" que não existe no título canônico)
    é o que zera a busca; o núcleo ("Guerra Balde") e o inglês
    ("War of the Bucket" via keywords) dão ao segundo passe uma cabeça
    diferente em vez de repetir as mesmas 13 consultas.
    """
    from . import entity as entity_stage
    out: list[str] = []
    core = target.core_terms() if target is not None else []
    if len(core) >= 2:
        cand = " ".join(core)
        if cand.lower() not in seen:
            out.append(cand)
    head = entity_stage._head_noun(getattr(target, "name", "") or "")
    if head and len(_strip_acc(head)) >= 4 and head.lower() not in seen:
        out.append(head)
    for kw in extract_keywords(idea, language):
        if kw.lower() not in seen:
            out.append(kw)
    return out[:4]


def _no_usable_source_message(idea: str, target, rejected) -> str:
    """A falha precisa dizer QUAL foi a falha: não achou, ou achou errado."""
    base = (f"nenhuma fonte utilizável p/ {idea.strip()[:80]!r}. ")
    if not rejected:
        return (base + "A pesquisa não retornou nada (verifique a rede ou "
                "reformule a ideia com termos buscáveis).")
    motivos: dict[str, int] = {}
    for _src, motivo, _det in rejected:
        motivos[motivo] = motivos.get(motivo, 0) + 1
    resumo = ", ".join(f"{n}× {m}" for m, n in motivos.items())
    # Citar os títulos é o que permite ao autor reconhecer o desvio: sem
    # eles a mensagem diz quantas fontes caíram, mas não sobre o quê.
    alguns = "; ".join(str(s.title)[:50] for s, _m, _d in rejected[:4])
    return (
        base + f"A pesquisa achou {len(rejected)} fonte(s), mas nenhuma "
        f"falava do referente pretendido ({resumo}). "
        f"Descartadas: {alguns}. "
        f"Entidade-alvo: {target.name or 'não identificada'}"
        + (f" (termos que a distinguem: {', '.join(target.discriminants)})"
           if target.discriminants else "")
        + ". Sem fonte do tema certo o roteiro não é gerado: um vídeo "
        "fundamentado em fontes de outro sujeito é pior do que nenhum "
        "vídeo. Reformule a ideia com o nome completo do sujeito.")


def format_for_prompt(sources: list[ResearchSource],
                      language: str = "pt-BR") -> str:
    """Bloco de fontes p/ injetar no prompt do LLM (com teto de tamanho)."""
    english = str(language or "").lower().startswith("en")
    head = ("MANDATORY SOURCES (web research — use ONLY these facts):"
            if english else
            "FONTES OBRIGATÓRIAS (pesquisa web — use SOMENTE estes fatos):")
    parts = [head]
    used = len(head)
    # Etimologia especializada tem PRIORIDADE: entra primeiro no prompt,
    # antes das fontes gerais — mas sem deslocá-las (orçamento manda).
    try:
        from . import etymology as etymology_stage
        block = etymology_stage.prompt_block(
            getattr(sources, "etymology", None), language)
        if block and used + len(block) + 1 <= PROMPT_BUDGET_CHARS:
            parts.append(block)
            used += len(block) + 1
    except Exception:  # noqa: BLE001 — bloco opcional nunca é fatal
        pass
    for gap in getattr(sources, "unresolved_gaps", [])[:3]:
        chunk = (("UNSUPPORTED — do not claim: " if english else
                  "SEM SUPORTE — não afirmar: ") + gap["query"])
        if used + len(chunk) + 1 <= PROMPT_BUDGET_CHARS:
            parts.append(chunk)
            used += len(chunk) + 1
    facts = getattr(sources, "facts", None) or _source_facts(sources)
    seen = set()
    for i, fact in enumerate(facts, 1):
        quote = fact["quote"]
        key = " ".join(quote.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        chunk = f"[{i}] {fact['url']}\n    trecho: {quote}"
        if used + len(chunk) + 1 <= PROMPT_BUDGET_CHARS:
            parts.append(chunk)
            used += len(chunk) + 1
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


def _claim_for(script_text: str, fact: str, window: int = 90) -> str:
    """A frase do roteiro onde o fato aparece.

    Sem isto o aviso dice "135" e o desenvolvedor não tem por onde
    começar: 135 é um número, não um identificador, e há dezenas no
    texto. A janela em volta é o bastante para reconhecer a afirmação sem
    despejar o parágrafo inteiro no log.
    """
    alvo = fact.split()[0] if fact else ""
    if not alvo:
        return ""
    melhor, pos = "", -1
    # Procura a menção mais próxima do NÚMERO, não da string completa:
    # o token pode ser "480 anos" e no texto aparecer só "480".
    for m in re.finditer(r"(?<![\w.])" + re.escape(alvo) + r"(?![\w])",
                         script_text):
        ini = max(0, m.start() - window)
        fim = min(len(script_text), m.end() + window)
        trecho = " ".join(script_text[ini:fim].split())
        if len(trecho) > len(melhor):
            melhor, pos = trecho, m.start()
        break
    if not melhor:
        return alvo
    return ("…" if pos > 0 else "") + melhor + (
        "…" if pos + window < len(script_text) else "")


def _cause(fact: str, source_facts: set[str],
           sources: list[ResearchSource]) -> str:
    """A causa provável, para o aviso distinguir três coisas diferentes.

    A CONFERÊNCIA NÃO MUDA: isto é só a leitura do mesmo resultado. O que
    se oferece aqui é a distinção entre "faltou fonte", "a fonte tem o
    dado com outro valor" e "o número simplesmente não está lá" — que
    são três correções diferentes e que o aviso antigotreatava como uma.
    """
    num = fact.split()[0] if fact else ""
    unidade = fact.split()[1] if len(fact.split()) > 1 else ""
    # Mesma unidade com OUTRO valor: a fonte cobre o assunto e diverge.
    if unidade:
        irmas = {f for f in source_facts if f.split()[-1:] == [unidade]
                 and f.split()[0] != num}
        if irmas:
            return ("fonte_presente_valor_diferente: alguma fonte traz "
                    f"'{unidade}' com outro número ({min(irmas)})")
    # Algum número nas fontes, mas não este: provável valor inventado ou
    # transcrição trocada.
    if any(any(c.isdigit() for c in f) for f in source_facts):
        return "valor_ausente_das_fontes"
    # Nenhum número em lugar nenhum do material: as fontes não são
    # numéricas, então a afirmação não tem como ter vindo delas.
    return "fontes_sem_dado_numerico"


def verify_grounding(script_text: str, sources: list[ResearchSource],
                     language: str = "pt-BR") -> dict:
    """Confere se os fatos do roteiro estão nas fontes (anti-invenção).

    Devolve {"checked": n, "grounded": [...], "unverified": [...],
    "unverified_detail": [...], "coverage": 0.0–1.0}. `unverified` são os
    fatos que o texto afirma e nenhuma fonte sustenta — é o mecanismo que
    torna a promessa "a IA nunca inventa" auditável em vez de só
    prometida no prompt.

    `unverified_detail` é o mesmo resultado com endereço: a frase do
    roteiro, os títulos das fontes avaliadas e a causa provável. É
    diagnóstico, não decisão: o gate acima é idêntico com ou sem ele.

    É conferência de números, não prova semântica: um texto pode parafrasear
    um fato sem repetir o mesmo numeral. Por isso o relatório é
    informativo e a cobertura vai para o metadata/relatório do projeto.
    """
    script_facts = _fact_tokens(script_text)
    if not script_facts:
        return {"checked": 0, "grounded": [], "unverified": [],
                "unverified_detail": [], "unverified_display": [],
                "sources_checked": [s.title for s in sources],
                "coverage": 1.0, "language": language}
    haystack = " ".join(f"{s.title} {s.snippet} {s.url}" for s in sources)
    source_facts = _fact_tokens(haystack)
    # Formas alternativas: ano "44" casa com "44 a.C." e com "44".
    grounded, unverified, detalhe = [], [], []
    for fact in sorted(script_facts):
        if fact in source_facts or fact.split()[0] in source_facts:
            grounded.append(fact)
        else:
            unverified.append(fact)
            detalhe.append({
                "fact": fact,
                "claim": _claim_for(script_text, fact),
                "cause": _cause(fact, source_facts, sources),
            })
    checked = len(grounded) + len(unverified)
    # Na EXIBIÇÃO, "135" e "135 anos" são o mesmo dado duas vezes: o
    # extrator guarda o número solto e o número com unidade. O gate conta
    # os dois, que é o comportamento antigo e não se mexe; o diagnóstico
    # mostra um, com a unidade, porque é o que o leitor reconhece.
    com_unidade = {f for f in unverified if len(f.split()) > 1}
    detalhe_visivel = [d for d in detalhe
                       if d["fact"] in com_unidade
                       or d["fact"] not in {c.split()[0] for c in com_unidade}]
    return {
        "checked": checked,
        "grounded": grounded,
        "unverified": unverified,
        "unverified_detail": detalhe,
        "unverified_display": detalhe_visivel,
        "sources_checked": [s.title for s in sources],
        "coverage": round(len(grounded) / checked, 3) if checked else 1.0,
        "language": language,
    }
