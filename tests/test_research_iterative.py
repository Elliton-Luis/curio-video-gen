from curio.stages import research as R
from curio.stages.entity import TargetEntity
from curio.metrics import RunMetrics


def source(title, quote):
    return R.ResearchSource(title=title, snippet=quote,
                            url=f"https://pt.wikipedia.org/wiki/{title}")


def test_complementary_searches_bounded_and_facts_verbatim(monkeypatch):
    initial = source("Lua", "A Lua é o satélite natural da Terra.")
    result = R.ResearchResult(TargetEntity(name="Lua", is_entity=False), [initial])
    plan = {"facts": [{"quote": initial.snippet, "url": initial.url},
                      {"quote": "A Lua é feita de queijo.", "url": initial.url}],
            "gaps": [{"query": f"Lua lacuna {i}", "reason": "Explicar a pergunta central",
                      "support_terms": [f"evidencia{i}"]} for i in range(5)]}
    monkeypatch.setattr(R, "_plan_gaps", lambda *args: plan)
    calls = []
    monkeypatch.setattr(R, "wikipedia_search",
                        lambda query, *args, **kwargs: calls.append(query) or [])
    metrics = RunMetrics("test", "Lua", "ai")
    R._complete_research(result, "Lua", "pt-BR", None, metrics, 5)
    assert len(calls) == len(result.complementary_queries) == 3
    assert metrics.research_queries == metrics.research_complementary_queries == 3
    assert len(result.unresolved_gaps) == 3
    assert result.facts == [{"quote": initial.snippet, "url": initial.url}]
    assert "queijo" not in R.format_for_prompt(result)


def test_skips_supported_gaps_and_repeated_queries(monkeypatch):
    result = R.ResearchResult(TargetEntity(name="Lua", is_entity=False),
                             [source("Lua", "A Lua apresenta crateras de impacto visíveis.")],
                             tried_queries=["Lua origem"])
    plan = {"gaps": [
        {"query": "Lua crateras", "reason": "Mecanismo", "support_terms": ["crateras", "impacto"]},
        {"query": "Lua origem", "reason": "Origem", "support_terms": ["formação"]}]}
    monkeypatch.setattr(R, "_plan_gaps", lambda *args: plan)
    monkeypatch.setattr(R, "wikipedia_search", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("não repetir busca suficientemente sustentada")))
    R._complete_research(result, "Lua", "pt-BR", None, None, 5)
    assert result.complementary_queries == []


def test_second_gap_skipped_when_first_search_supplies_both(monkeypatch):
    result = R.ResearchResult(TargetEntity(name="Lua", is_entity=False),
                             [source("Lua", "A Lua é o satélite natural da Terra.")])
    plan = {"gaps": [
        {"query": "Lua crateras", "reason": "Mecanismo", "support_terms": ["crateras"]},
        {"query": "Lua impacto", "reason": "Consequência", "support_terms": ["impacto"]}]}
    extra = source("Crateras", "As crateras da Lua são resultado de impacto.")
    monkeypatch.setattr(R, "_plan_gaps", lambda *args: plan)
    calls = []
    monkeypatch.setattr(R, "wikipedia_search", lambda q, *args, **kw:
                        calls.append(q) or [{"title": "Crateras"}])
    monkeypatch.setattr(R, "wikipedia_extract", lambda *args, **kw: extra)
    R._complete_research(result, "Lua", "pt-BR", None, None, 5)
    assert calls == ["Lua crateras"]
    assert result.sources[-1].url == extra.url
    assert result.unresolved_gaps == []
    assert extra.snippet in R.format_for_prompt(result)


def test_context_deduplicates_sentences_and_keeps_urls():
    quote = "A Lua apresenta crateras de impacto visíveis."
    context = R.format_for_prompt([source("Lua", quote), source("Crateras", quote)])
    assert context.count(quote) == 1
    assert "https://pt.wikipedia.org/wiki/Lua" in context
    assert len(context) <= R.PROMPT_BUDGET_CHARS


def test_research_topic_runs_broad_pass_then_specific_gap_and_logs(monkeypatch, tmp_path):
    import json
    from curio.runlog import RunLog
    target = TargetEntity(name="Lua", is_entity=False)
    monkeypatch.setattr("curio.stages.entity.resolve_entity", lambda *a, **kw: target)
    queries = []
    def search(query, *args, **kwargs):
        queries.append(query)
        return [{"title": "Lua" if query == "Lua" else "Crateras"}]
    monkeypatch.setattr(R, "wikipedia_search", search)
    monkeypatch.setattr(R, "wikipedia_extract", lambda title, *a, **kw:
                        source(title, "A Lua é o satélite natural da Terra." if title == "Lua"
                               else "As crateras da Lua são resultado de impacto."))
    monkeypatch.setattr(R, "_plan_gaps", lambda *a: {"gaps": [{
        "query": "Lua crateras impacto", "reason": "Explicar relevo lunar",
        "support_terms": ["crateras", "impacto"]}]})
    metrics = RunMetrics("test", "Lua", "ai")
    with RunLog(tmp_path / "research.jsonl", "test"):
        result = R.research_topic("Fale da Lua", max_sources=1, metrics=metrics)
    assert queries == ["Lua", "Lua crateras impacto"]
    assert len(result.sources) == 2
    assert metrics.research_queries == 2
    assert metrics.research_complementary_queries == 1
    rows = [json.loads(line) for line in (tmp_path / "research.jsonl").read_text().splitlines()]
    assert any(row["details"].get("reason") == "Explicar relevo lunar" for row in rows)
    report = metrics.to_dict({"artifacts": {}}, {}, "metrics")["consumption"]["research"]
    assert report["queries"] == 2 and report["sources"] == 2
    assert report["complementary_queries"] == 1


def test_unresolved_gap_is_not_lost_when_context_is_full():
    result = R.ResearchResult(None, [source("Lua", ("A Lua é um satélite natural. " * 100))])
    result.unresolved_gaps = [{"query": "Lua afirmação sem suporte", "reason": "Questão central"}]
    context = R.format_for_prompt(result)
    assert "SEM SUPORTE" in context
    assert len(context) <= R.PROMPT_BUDGET_CHARS


def test_supplement_rejects_irrelevant_sources_even_with_matching_terms(monkeypatch):
    result = R.ResearchResult(TargetEntity(name="Lua", is_entity=True),
                             [source("Lua", "A Lua é o satélite natural da Terra.")])
    monkeypatch.setattr(R, "_plan_gaps", lambda *a: {"gaps": [{
        "query": "Lua crateras", "reason": "Explicar relevo",
        "support_terms": ["crateras"]}]})
    monkeypatch.setattr(R, "wikipedia_search", lambda *a, **kw: [{"title": "Marte"}])
    monkeypatch.setattr(R, "wikipedia_extract", lambda *a, **kw:
                        source("Marte", "Marte apresenta crateras grandes e numerosas."))
    R._complete_research(result, "Lua", "pt-BR", None, None, 5)
    assert len(result.sources) == 1
    assert result.rejected and result.unresolved_gaps
    assert "Marte" not in R.format_for_prompt(result)


def test_malformed_gap_plan_keeps_existing_evidence(monkeypatch):
    result = R.ResearchResult(None, [source("Lua", "A Lua é o satélite natural da Terra.")])
    monkeypatch.setattr(R, "_plan_gaps", lambda *a: {"facts": {}, "gaps": "wrong type"})
    R._complete_research(result, "Lua", "pt-BR", None, None, 5)
    assert result.facts and result.complementary_queries == []


def test_research_query_batch_runs_concurrently_and_keeps_input_order(monkeypatch):
    import threading
    import time

    lock = threading.Lock()
    active = 0
    peak = 0

    def search(query, *args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return [{"title": query}]

    monkeypatch.setattr(R, "wikipedia_search", search)
    before = time.monotonic()
    out = R._search_query_batch(["a", "b", "c"], "pt-BR", 5)
    elapsed = time.monotonic() - before
    assert [hits[0]["title"] for hits in out] == ["a", "b", "c"]
    assert peak > 1
    assert elapsed < 0.11


def test_rich_research_skips_llm_gap_planner(monkeypatch):
    quotes = [f"Evidence sentence number {i} explains the lunar finding in detail."
              for i in range(12)]
    rich = source("Moon research", " ".join(quotes))
    result = R.ResearchResult(TargetEntity(name="Moon", is_entity=False), [rich, source(
        "Lunar study", "Independent study confirms lunar evidence and measurement.")])
    monkeypatch.setattr(R, "_plan_gaps", lambda *a: (_ for _ in ()).throw(
        AssertionError("gap planner called despite rich source evidence")))
    R._complete_research(result, "Moon", "en-US", None, None, 5)
    assert result.facts and result.complementary_queries == []
