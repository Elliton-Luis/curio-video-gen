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


# Artigos sobre MAR: o portão de pertinência exige sobreposição com o
# tema, então o mock precisa devolver conteúdo do assunto. Antes, o mock
# devolvia "Sal"/"Mar" para qualquer consulta e o teste afirmava que
# qualquer artigo servia — que é exatamente o contrato removido.
_ARTIGOS_MAR = {
    "Mar": "O mar é uma grande massa de água salgada que cobre 71% da "
           "superfície terrestre.",
    "Salinidade": "A salinidade do mar é a quantidade de sais dissolvidos "
                  "na água do oceano.",
}


def _wiki_extract_payload(title, extract):
    return {"query": {"pages": {"1": {"title": title, "extract": extract}}}}


def _fake_get_json_factory():
    def fake(url, timeout=20):
        if "list=search" in url:
            return _wiki_search_payload(*_ARTIGOS_MAR)
        if "prop=extracts" in url:
            import urllib.parse as up
            q = up.parse_qs(up.urlparse(url).query)
            titulo = (q.get("titles") or [""])[0]
            trecho = _ARTIGOS_MAR.get(titulo)
            if not trecho:
                return {"query": {"pages": {}}}
            return _wiki_extract_payload(titulo, trecho)
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
                                          "extract": "Texto bom sobre o "
                                          "tema do teste com mar e fatos "
                                          "suficientes aqui."}}}}

    monkeypatch.setattr(mod, "_get_json", fake)
    srcs = R.research_topic("teste com mar", "pt-BR", max_sources=1)
    assert len(srcs) == 1 and srcs[0].title == "Bom"


def test_nucleo_tolera_um_qualificador_a_menos():
    from curio.stages.entity import TargetEntity
    alvo = TargetEntity(name="A Guerra do Balde de Carvalho")
    assert alvo.core_terms() == ["guerra", "balde", "carvalho"]
    assert alvo.nucleus_in_title("Guerra do Balde")
    assert not alvo.nucleus_in_title("Flávio Bolsonaro")
    curto = TargetEntity(name="Mar Salgado")
    assert curto.nucleus_in_title("Mar Salgado")
    assert not curto.nucleus_in_title("Mar Morto")


def test_passe_relaxado_aceita_artigo_certo_e_barra_homonimo():
    from curio.stages import entity as E
    from curio.stages.research import _relaxed_nucleus_accept
    alvo = E.TargetEntity(
        name="A Guerra do Balde de Carvalho",
        discriminants=["novel", "José Saramago", "1985"],
        forbidden=["Balde de Lixo SA"],
        search_queries=["A Guerra do Balde de Carvalho"])
    certo = ResearchSource(
        title="Guerra do Balde",
        url="https://pt.wikipedia.org/wiki/Guerra_do_Balde",
        snippet="Conflito entre Bolonha e Módena em 1325 por um balde.")
    errado = ResearchSource(
        title="Flávio Bolsonaro", url="https://pt.wikipedia.org/wiki/X",
        snippet="Político brasileiro.")
    vetado = ResearchSource(
        title="Balde de Lixo SA Guerra", url="https://pt.wikipedia.org/wiki/Y",
        snippet="Empresa Balde de Lixo SA na guerra fiscal.")
    rej = [(certo, E.REASON_DISCRIMINANT, ""), (errado, E.REASON_ENTITY, ""),
           (vetado, E.REASON_ENTITY, "")]
    out = _relaxed_nucleus_accept(rej, alvo, 3)
    assert [s.title for s in out] == ["Guerra do Balde"]


def test_allow_weak_garante_resultado_sem_fonte(monkeypatch):
    import curio.stages.research as mod

    def empty(url, timeout=20):
        if "api.duckduckgo.com" in url:
            return {"AbstractText": "", "AbstractURL": ""}
        return {"query": {"search": []}}

    monkeypatch.setattr(mod, "_get_json", empty)
    res = mod.research_topic("xyzq asdfgh", "pt-BR", allow_weak=True)
    assert res.weak is True and len(res.sources) == 0
    with pytest.raises(ResearchError, match="nenhuma fonte"):
        mod.research_topic("xyzq asdfgh", "pt-BR")
