"""RAG de fontes web (rede mockada): keywords, Wikipedia, DDG, erros."""

import pytest

from curio.stages import research as R
from curio.stages.research import ResearchError, ResearchSource


def test_extract_keywords_pt():
    kws = R.extract_keywords("Por que o mar é salgado se toda chuva é doce?")
    assert "salgado" in kws and "chuva" in kws and "doce" in kws
    for stop in ("por", "que", "se"):
        assert stop not in kws


def test_extract_keywords_en():
    kws = R.extract_keywords("How does fiber internet cross the ocean?", "en-US")
    assert "fiber" in kws and "internet" in kws
    assert "how" not in kws and "does" not in kws


def test_format_for_prompt_contem_fatos_e_urls():
    srcs = [ResearchSource(title="Sal", url="https://pt.wikipedia.org/wiki/Sal",
                           snippet="O sal é cloreto de sódio."),
            ResearchSource(title="Mar", url="https://pt.wikipedia.org/wiki/Mar",
                           snippet="O mar cobre 71% da Terra.")]
    pack = R.format_for_prompt(srcs, "pt-BR")
    assert "FONTES OBRIGATÓRIAS" in pack
    assert "https://pt.wikipedia.org/wiki/Sal" in pack
    assert "cloreto de sódio" in pack
    assert len(pack) <= R.PROMPT_BUDGET_CHARS + 500


def test_format_for_prompt_en():
    pack = R.format_for_prompt(
        [ResearchSource(title="Salt", url="https://en.wikipedia.org/wiki/Salt",
                        snippet="Salt is sodium chloride.")], "en-US")
    assert "MANDATORY SOURCES" in pack


def _wiki_search_payload(*titles):
    return {"query": {"search": [{"title": t} for t in titles]}}


def _wiki_extract_payload(title, extract):
    return {"query": {"pages": {"1": {"title": title, "extract": extract}}}}


def _fake_get_json_factory():
    def fake(url, timeout=20):
        if "list=search" in url:
            return _wiki_search_payload("Sal", "Mar")
        if "prop=extracts" in url:
            if "titles=Sal" in url:
                return _wiki_extract_payload("Sal", "O sal é cloreto de sódio. Usado há milênios.")
            return _wiki_extract_payload("Mar", "O mar cobre 71% da superfície da Terra.")
        if "api.duckduckgo.com" in url:
            return {"AbstractText": "", "AbstractURL": ""}
        raise AssertionError(f"URL inesperada: {url}")
    return fake


def test_research_topic_sucesso(monkeypatch):
    import curio.stages.research as mod
    monkeypatch.setattr(mod, "_get_json", _fake_get_json_factory())
    srcs = R.research_topic("Por que o mar é salgado?", "pt-BR", max_sources=2)
    assert len(srcs) == 2
    assert all(s.url.startswith("https://pt.wikipedia.org/wiki/") for s in srcs)
    assert all(len(s.snippet) > 20 for s in srcs)
    assert srcs[0].url != srcs[1].url


def test_research_topic_exige_ao_menos_uma_fonte(monkeypatch):
    import curio.stages.research as mod

    def empty(url, timeout=20):
        if "api.duckduckgo.com" in url:
            return {"AbstractText": "", "AbstractURL": ""}
        return {"query": {"search": []}}

    monkeypatch.setattr(mod, "_get_json", empty)
    with pytest.raises(ResearchError, match="nenhuma fonte"):
        R.research_topic("xyzq asdfgh", "pt-BR")


def test_research_topic_falha_de_rede_explicita(monkeypatch):
    import curio.stages.research as mod

    def down(url, timeout=20):
        raise OSError("sem rede")

    monkeypatch.setattr(mod, "_get_json", down)
    with pytest.raises(ResearchError, match="Wikipedia indisponível"):
        R.research_topic("salário", "pt-BR")


def test_research_topic_conta_metricas(monkeypatch):
    import curio.stages.research as mod
    from curio.metrics import RunMetrics
    monkeypatch.setattr(mod, "_get_json", _fake_get_json_factory())
    m = RunMetrics("slug-teste", "ideia", "ai")
    R.research_topic("Por que o mar é salgado?", "pt-BR", max_sources=2,
                     metrics=m)
    d = m.to_dict({"artifacts": {}}, {}, "metrics")
    assert d["consumption"]["research"]["sources"] == 2
    assert d["consumption"]["research"]["queries"] >= 1


def test_registry_recebe_claims_da_pesquisa():
    from curio.stages import sources as S
    reg = S.SourceRegistry(slug="t")
    src = ResearchSource(title="Sal", url="https://pt.wikipedia.org/wiki/Sal",
                         snippet="O sal é cloreto de sódio.")
    reg.add_claim(claim=src.title, title=src.title, url=src.url,
                  evidence=src.snippet[:300], status="partial",
                  notes="RAG web (wikipedia)")
    assert len(reg.claims) == 1
    assert reg.claims[0].url.startswith("https://")
    assert reg.claims[0].status == "partial"


def test_junk_hit_filtrado():
    assert R._is_junk_hit("Mar Salgado (telenovela)")
    assert R._is_junk_hit("X (desambiguação)")
    assert R._is_junk_hit("Lista de países por salário mínimo")
    assert not R._is_junk_hit("Mar Morto")
    assert not R._is_junk_hit("Salário")


def test_extract_erro_de_rede_vira_research_error(monkeypatch):
    import curio.stages.research as mod

    def boom(url, timeout=20):
        raise OSError("rede caiu")

    monkeypatch.setattr(mod, "_get_json", boom)
    with pytest.raises(ResearchError):
        R.wikipedia_extract("Sal", "pt-BR")


def test_research_pula_artigo_com_falha(monkeypatch):
    import curio.stages.research as mod

    def fake(url, timeout=20):
        if "list=search" in url:
            return {"query": {"search": [{"title": "Ruim"}, {"title": "Bom"}]}}
        if "titles=Ruim" in url:
            raise OSError("429 throttled")
        return {"query": {"pages": {"1": {"title": "Bom",
                                          "extract": "Texto bom com fatos suficientes aqui."}}}}

    monkeypatch.setattr(mod, "_get_json", fake)
    srcs = R.research_topic("teste", "pt-BR", max_sources=1)
    assert len(srcs) == 1 and srcs[0].title == "Bom"
