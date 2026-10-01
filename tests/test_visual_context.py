"""Contexto de pesquisa preserva identidade e alinha busca e scoring."""

from curio.stages.entity import TargetEntity
from curio.stages.scenes import Chapter
from curio.stages import scoring
from curio.stages.visual_context import fill_missing_context
from curio.stages.research import ResearchSource


def test_local_context_uses_authoritative_alias_and_rejects_namesake(monkeypatch):
    monkeypatch.setattr("curio.stages.research._get_json", lambda *a, **k: {
        "query": {"pages": {"1": {"langlinks": [{"lang": "en", "*": "Thomas Aquinas"}]}}}})
    target = TargetEntity("São Tomás de Aquino", aliases=["Tomás de Aquino", "São Tomás"],
                          forbidden=["São Tomás RS"])
    ch = Chapter(1, "Tomás de Aquino explicou filosofia e teologia.", 5)
    narration = ch.narration
    assert fill_missing_context([ch], target, "people", [ResearchSource(
        "Tomás de Aquino", "https://pt.wikipedia.org/wiki/Tomás_de_Aquino")])
    assert ch.narration == narration
    assert "Saint Thomas Aquinas painting" == ch.visual_queries[0]
    assert "Thomas Aquinas" in ch.subject_aliases
    for title in ("File:Thomas Aquinas painting.jpg", "File:Tomás de Aquino.jpg"):
        assert scoring.base_score({"title": title}, ch)["score"] >= 34
    for title in ("Melchora Aquino monument", "Aquino city", "Saint Thomas island",
                  "Aristoteles crater", "Toll-Like Receptors"):
        assert scoring.base_score({"title": title}, ch)["score"] < 34
    assert Chapter.from_dict(ch.to_dict()).subject_aliases == ch.subject_aliases


def test_explicit_location_scores_without_diluted_narration():
    target = TargetEntity("Tomás de Aquino")
    ch = Chapter(1, "Em 1274, Tomás morreu em Fossanova. Sua influência continuou.", 5)
    assert fill_missing_context([ch], target, "people")
    assert ch.subject == "Fossanova"
    assert ch.visual_queries == ["Fossanova"]
    assert scoring.base_score({"title": "Fossanova Abbey"}, ch)["score"] == 75
    assert scoring.base_score({"title": "Mairie d'Anos"}, ch)["score"] == 0


def test_llm_scene_with_entity_subject_keeps_queries_and_gains_aliases(monkeypatch):
    monkeypatch.setattr("curio.stages.research._get_json", lambda *a, **k: {
        "query": {"pages": {"1": {"langlinks": [{"lang": "en", "*": "Thomas Aquinas"}]}}}})
    ch = Chapter(1, "Quem foi Tomás de Aquino?", 5, subject="Tomás de Aquino",
                 visual_queries=["medieval scholar portrait"])
    narration, subject = ch.narration, ch.subject
    assert fill_missing_context([ch], TargetEntity("São Tomás de Aquino",
        aliases=["Tomás de Aquino"]), "people",
        [ResearchSource("Tomás de Aquino", "https://pt.wikipedia.org/wiki/Tomás_de_Aquino")])
    assert ch.narration == narration
    assert ch.subject == subject
    assert ch.visual_queries[0] == "Saint Thomas Aquinas painting"
    assert "medieval scholar portrait" in ch.visual_queries
    assert scoring.base_score(
        {"title": "File:Saint Thomas Aquinas (Crivelli, 15th-century).jpg"},
        ch)["score"] >= 34
    assert scoring.base_score({"title": "Melchora Aquino monument"}, ch)["score"] < 34
    assert Chapter.from_dict(ch.to_dict()).subject_aliases == ch.subject_aliases


def test_llm_scene_with_other_subject_is_untouched():
    ch = Chapter(1, "Ele entrou na Ordem dos Pregadores.", 5,
                 subject="Ordem dos Pregadores",
                 visual_queries=["monastery interior"])
    original = ch.to_dict()
    assert not fill_missing_context([ch], TargetEntity("São Tomás de Aquino"), "people")
    assert ch.to_dict() == original


def test_llm_scene_in_english_matches_entity_after_language_alias(monkeypatch):
    monkeypatch.setattr("curio.stages.research._get_json", lambda *a, **k: {
        "query": {"pages": {"1": {"langlinks": [{"lang": "en", "*": "Thomas Aquinas"}]}}}})
    ch = Chapter(1, "Thomas Aquinas was born in Roccasecca.", 5,
                 subject="Thomas Aquinas",
                 visual_queries=["portrait painting", "historical portrait"])
    assert fill_missing_context([ch], TargetEntity("São Tomás de Aquino",
        aliases=["Tomás de Aquino"]), "people",
        [ResearchSource("Tomás de Aquino", "https://pt.wikipedia.org/wiki/Tomás_de_Aquino")])
    assert ch.subject == "Thomas Aquinas"
    assert ch.visual_queries[0] == "Saint Thomas Aquinas painting"
    assert scoring.base_score(
        {"title": "File:Saint Thomas Aquinas (Crivelli, 15th-century).jpg"},
        ch)["score"] >= 34


def test_generic_person_subject_anchors_to_entity_without_other_names(monkeypatch):
    monkeypatch.setattr("curio.stages.research._get_json", lambda *a, **k: {
        "query": {"pages": {"1": {"langlinks": [{"lang": "en", "*": "Thomas Aquinas"}]}}}})
    ch = Chapter(1, "Quem foi o homem que juntou fé e razão?", 5,
                 subject="man", visual_queries=["man portrait"])
    assert fill_missing_context([ch], TargetEntity("São Tomás de Aquino",
        aliases=["Tomás de Aquino"]), "people",
        [ResearchSource("Tomás de Aquino", "https://pt.wikipedia.org/wiki/Tomás_de_Aquino")])
    assert ch.subject == "man"
    assert ch.visual_queries[0] == "Saint Thomas Aquinas painting"
    assert scoring.base_score(
        {"title": "soldier, british, general, war, military, man"}, ch)["score"] < 34
    assert scoring.base_score(
        {"title": "File:Saint Thomas Aquinas (Crivelli, 15th-century).jpg"},
        ch)["score"] >= 34


def test_generic_person_subject_with_rival_name_is_untouched():
    ch = Chapter(1, "O homem conheceu o Papa em Roma.", 5,
                 subject="man", visual_queries=["man portrait"])
    original = ch.to_dict()
    assert not fill_missing_context([ch], TargetEntity("São Tomás de Aquino"), "people")
    assert ch.to_dict() == original


def test_structured_scenes_and_no_target_do_not_change():
    ch = Chapter(1, "Texto.", 3, subject="thermal receipt", visual_queries=["thermal receipt"])
    original = ch.to_dict()
    assert not fill_missing_context([ch], TargetEntity("Tomás de Aquino"), "people")
    assert ch.to_dict() == original
    empty = Chapter(2, "Texto sem entidade.", 3)
    assert not fill_missing_context([empty], TargetEntity("tema", is_entity=False))


def test_religious_order_is_not_mistaken_for_place():
    ch = Chapter(1, "Tomás ingressou na Ordem dos Pregadores.", 4)
    assert fill_missing_context([ch], TargetEntity("Tomás de Aquino"), "people")
    assert ch.subject == "Tomás de Aquino"
    assert scoring.base_score({"title": "Antas da Ordem"}, ch)["score"] == 0


def test_real_candidates_allow_existing_insertion_rule_without_synthetic_assets(monkeypatch):
    from curio.stages.visual import order_for_insertion
    monkeypatch.setattr("curio.stages.research._get_json", lambda *a, **k: {
        "query": {"pages": {"1": {"langlinks": [{"lang": "en", "*": "Thomas Aquinas"}]}}}})
    ch = Chapter(1, "Tomás de Aquino escreveu sobre filosofia.", 5)
    fill_missing_context([ch], TargetEntity("São Tomás de Aquino",
        aliases=["Tomás de Aquino", "Santo Tomás de Aquino"]), "people",
        [ResearchSource("Tomás de Aquino", "https://pt.wikipedia.org/wiki/Tomás_de_Aquino")])
    entries = [{"asset": {"provider": "wikimedia", "title": title}} for title in (
        "File:Apoteosis de Santo Tomás de Aquino, Francisco de Zurbarán.jpg",
        "File:Saint Thomas Aquinas (Crivelli, 15th-century).jpg")]
    background, insertion = order_for_insertion(entries, ch)
    assert background[0] == entries[0]
    assert insertion[0] == entries[1]
