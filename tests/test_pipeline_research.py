from types import SimpleNamespace

import pytest

from curio import pipeline_research
from curio.stages import research
from curio.stages.entity import TargetEntity


def test_research_stage_consumes_declared_result_contract(monkeypatch, tmp_path):
    source = research.ResearchSource(
        title="Black holes", url="https://example.test/black-holes",
        snippet="A black hole bends light.")
    result = research.ResearchResult(
        TargetEntity(name="Black hole"), [source],
        tried_queries=["Black hole"], weak_warnings=["small sample"])
    result.facts.append({"quote": "A black hole bends light."})
    monkeypatch.setattr(research, "research_topic", lambda *a, **k: result)
    monkeypatch.setattr(research, "format_for_prompt", lambda got, _lang:
                        "research prompt" if got is result else "wrong")

    class Registry:
        claims = []

        def add_claim(self, **claim):
            self.claims.append(claim)

    registry = Registry()
    saved = {}
    warnings = []
    cfg = SimpleNamespace(language="en", research_max_sources=3,
                          research_timeout=2)
    paths = SimpleNamespace(research_json=str(tmp_path / "research.json"))
    stage = pipeline_research.run_research_stage(
        "Black holes", cfg, paths, None, "", warnings, registry,
        lambda *_args: None,
        lambda path, data: saved.update(path=path, data=data))

    assert stage.result is result
    assert stage.result.target is result.target
    assert stage.result.tried_queries == ["Black hole"]
    assert stage.result.sources is result.sources
    assert stage.status == "partial"
    assert warnings == ["pesquisa: small sample"]
    assert saved["data"]["facts"] == result.facts
    assert registry.claims[0]["title"] == source.title


def test_research_stage_rejects_incomplete_producer_before_side_effects(
        monkeypatch, tmp_path):
    monkeypatch.setattr(research, "research_topic", lambda *a, **k: [])
    saved = []
    registry = SimpleNamespace(add_claim=lambda **_claim: pytest.fail(
        "invalid result must be rejected before registration"))
    cfg = SimpleNamespace(language="en", research_max_sources=3,
                          research_timeout=2)
    paths = SimpleNamespace(research_json=str(tmp_path / "research.json"))

    with pytest.raises(TypeError, match="must return ResearchResult"):
        pipeline_research.run_research_stage(
            "Black holes", cfg, paths, None, "", [], registry,
            lambda *_args: None,
            lambda *_args: saved.append("written"))
    assert saved == []


@pytest.mark.parametrize(
    ("mutate", "error", "match"),
    [
        (lambda result: result.sources.append("bad source"), TypeError,
         "ResearchSource values"),
        (lambda result: result.rejected.append(("bad source", "reason", "detail")),
         TypeError, "ResearchSource, reason, detail"),
        (lambda result: result.tried_queries.append("  "), TypeError,
         "tried_queries"),
        (lambda result: result.facts.append("bad fact"), TypeError,
         "facts must be a list of objects"),
    ],
)
def test_research_stage_rejects_malformed_result_before_side_effects(
        monkeypatch, tmp_path, mutate, error, match):
    result = research.ResearchResult(
        TargetEntity(name="Black hole"),
        [research.ResearchSource("Black holes", "https://example.test")],
        tried_queries=["Black hole"])
    mutate(result)
    monkeypatch.setattr(research, "research_topic", lambda *a, **k: result)
    saved = []
    registry = SimpleNamespace(add_claim=lambda **_claim: pytest.fail(
        "malformed result must be rejected before registration"))
    cfg = SimpleNamespace(language="en", research_max_sources=3,
                          research_timeout=2)
    paths = SimpleNamespace(research_json=str(tmp_path / "research.json"))

    with pytest.raises(error, match=match):
        pipeline_research.run_research_stage(
            "Black holes", cfg, paths, None, "", [], registry,
            lambda *_args: None,
            lambda *_args: saved.append("written"))
    assert saved == []
