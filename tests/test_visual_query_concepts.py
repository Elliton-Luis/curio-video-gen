from types import SimpleNamespace

from curio.stages.entity import TargetEntity
from curio.stages.scenes import Chapter, _local_chapters, classify_visual_type
from curio.stages import visual
from curio.stages.scene_local_planning import local_visual_representations
from curio.stages.visual_context import attach_video_context
from tests.test_support.search_plan import patch_search_plan, plan_queries


def _local_scene(text, topic="Ottoman Empire", aliases=()):
    chapters = _local_chapters(text, 1)
    attach_video_context(chapters, topic, TargetEntity(
        topic, aliases=list(aliases), is_entity=True))
    return chapters[0]


def test_local_scene_queries_entity_and_event_as_catalog_phrases():
    janissaries = _local_scene(
        "Os janízaros formavam a elite militar do Império Otomano.",
        aliases=("Ottoman Empire",))
    queries, _ = plan_queries(janissaries)
    assert queries[0] == "janízaros Ottoman Empire"
    assert all(q.casefold() not in {"formavam", "gold", "laboratory", "microscope"}
               for q in queries)
    assert janissaries.representation_rejections == [
        {"query": "formavam", "kind": "related", "reason": "isolated_inflected_verb"},
        {"query": "elite", "kind": "related", "reason": "isolated_abstract_or_material"},
    ]
    assert next(r for r in janissaries.representations
                if r["query"] == "janízaros")["kind"] == "army"
    assert any("uniform" in q for q in queries)

    battle = _local_scene("A Batalha de Mohács ocorreu em 1526.",
                          aliases=("Ottoman Empire",))
    battle_queries, _ = plan_queries(battle)
    assert battle_queries[0] == "Battle of Mohács Ottoman Empire"
    assert any("1526" in q for q in battle_queries)
    assert not any(q == "Mohács" for q in battle_queries)


def test_local_representations_cover_empire_person_monument_and_object():
    empire = _local_scene("O Império Bizantino controlava Constantinopla.",
                          "Byzantine Empire")
    assert any(rep["kind"] == "empire" for rep in empire.representations)

    person = _local_scene("O imperador Justiniano governou Constantinopla.",
                          "Byzantine Empire", ("Justinian I", "Byzantine Empire"))
    person_queries, _ = plan_queries(person)
    assert any("portrait" in q for q in person_queries)

    monument = _local_scene("A Mesquita Azul foi concluída em Istambul.")
    monument_queries, _ = plan_queries(monument)
    assert any("monument" in q for q in monument_queries)

    artifact = _local_scene("A espada cerimonial foi preservada no museu.")
    artifact_queries, _ = plan_queries(artifact)
    assert any("museum object" in q or "artifact" in q for q in artifact_queries)


def test_isolated_noise_is_rejected_and_alias_backed_indirect_visual_survives():
    chapter = Chapter.from_dict({
        "id": 1,
        "narration": "O ouro financiou a primeira campanha.",
        "representations": [
            {"query": "gold", "kind": "entity"},
            {"query": "primeira", "kind": "related"},
            {"query": "formavam", "kind": "related"},
            {"query": "Liberty statue", "kind": "monument"},
        ],
        "visual_queries": ["gold", "primeira", "formavam"],
        "video_context": {"topic": "freedom", "aliases": ["Liberty"]},
        "visual_intent": "scene planner",
    })
    assert [r["query"] for r in chapter.representations] == ["Liberty statue"]
    assert {r["reason"] for r in chapter.representation_rejections} == {
        "isolated_abstract_or_material", "isolated_ordinal", "isolated_inflected_verb"}
    assert not any(term in {"gold", "primeira"}
                   for term in local_visual_representations(chapter.narration))
    queries, _ = plan_queries(chapter)
    assert "Liberty statue" in queries
    assert not any(q in {"gold", "primeira", "formavam"} for q in queries)


def test_science_queries_do_not_leak_into_history_and_science_is_specific():
    history = _local_scene("Os janízaros formavam a elite militar do Império Otomano.",
                           aliases=("Ottoman Empire",))
    history_queries, _ = plan_queries(history)
    assert not any("laboratory" in q or "microscope" in q for q in history_queries)
    assert classify_visual_type(
        "O império cresceu, transformando fronteiras durante séculos.") == "historical_art"
    contextual_history = _local_scene("Selim Primeiro derrotou os mamelucos em Marj Dabiq.")
    assert contextual_history.visual_type == "historical_art"
    assert not any("Ottoman Empire Ottoman Empire" == q for q in history_queries)

    science = SimpleNamespace(
        id=2, narration="A microscope reveals cells in a laboratory experiment.",
        visual_queries=["microscope"], global_visual_queries=[],
        visual_intent="planner", visual_type="mechanism", subject="microscope",
        visual_entities=["microscope"], context=[], forbidden=[], representations=[])
    science_queries, _ = plan_queries(science)
    assert "laboratory" in science_queries or "microscope" in science_queries


def test_search_continues_after_topic_only_candidate(tmp_path, monkeypatch):
    from curio.media.providers import MediaAsset

    weak = MediaAsset("wikimedia", "map", title="Ottoman Empire map",
                      download_url="https://cdn.test/map.jpg", width=1600,
                      height=1200, license="CC BY 4.0")
    exact = MediaAsset("wikimedia", "battle", title="Battle of Mohacs 1526",
                       download_url="https://cdn.test/battle.jpg", width=1600,
                       height=1200, license="CC BY 4.0")

    class Provider:
        name = "wikimedia"
        calls = []

        def search(self, query, *_args, **_kwargs):
            self.calls.append(query)
            return [weak] if "historical map" in query else [exact]

    provider = Provider()
    image = tmp_path / "winner.jpg"
    image.write_bytes(b"x" * 20000)
    monkeypatch.setattr(visual, "download_asset",
                        lambda asset, *_a, **_kw: _attach(asset, image))
    monkeypatch.setattr(visual, "_downloaded_dims_ok", lambda _asset: True)
    patch_search_plan(monkeypatch, visual,
                      ["Ottoman Empire historical map",
                       "Battle of Mohacs Ottoman Empire"])
    chapter = Chapter(
        id=4, narration="A Batalha de Mohács foi decisiva.", duration_estimate=6,
        visual_queries=["Battle of Mohacs Ottoman Empire"], subject="Battle of Mohacs",
        event="Battle of Mohacs", primary_entity="Battle of Mohacs",
        visual_entities=["Battle of Mohacs"], global_visual_queries=["Ottoman Empire"],
        representations=[{"query": "Battle of Mohacs", "kind": "event", "level": 1}],
        video_context={"topic": "Ottoman Empire", "aliases": ["Ottoman Empire"]})
    result, _ = visual._search_scene_with_shortcircuit(
        chapter, [provider], SimpleNamespace(cache_dir=str(tmp_path), language="en-US"),
        1, None, str(tmp_path))
    assert provider.calls == ["Ottoman Empire historical map",
                              "Battle of Mohacs Ottoman Empire"]
    assert result[0]["asset"]["asset_id"] == "battle"
    audit = result[0]["visual_decision"]
    assert audit["visual_plan"]["topic"] == "Ottoman Empire"
    assert audit["visual_plan"]["representations"][0]["kind"] == "event"
    assert "narration" not in audit["visual_plan"]


def test_provider_failures_never_claim_search_exhausted(tmp_path, monkeypatch):
    from curio.media.providers import MediaError

    class BrokenProvider:
        name = "wikimedia"

        def search(self, *_args, **_kwargs):
            raise MediaError("wikimedia HTTP 503")

    chapter = Chapter(
        id=5, narration="A Batalha de Mohács foi decisiva.", duration_estimate=6,
        visual_queries=["Battle of Mohacs"], subject="Battle of Mohacs",
        event="Battle of Mohacs", primary_entity="Battle of Mohacs",
        visual_entities=["Battle of Mohacs"], global_visual_queries=[],
        representations=[{"query": "Battle of Mohacs", "kind": "event", "level": 1}],
        video_context={"topic": "Ottoman Empire", "aliases": ["Ottoman Empire"]})
    patch_search_plan(monkeypatch, visual, ["Battle of Mohacs Ottoman Empire"])
    result, _ = visual._search_scene_with_shortcircuit(
        chapter, [BrokenProvider()], SimpleNamespace(cache_dir=str(tmp_path), language="en-US"),
        1, None, str(tmp_path))
    decision = result[0]["visual_decision"]
    assert decision["search_exhausted"] is False
    assert decision["search_exhaustion_reason"] == "provider_errors"
    assert decision["fallback_level"] == "synthetic_after_incomplete_search"
    assert decision["queries"][0]["provider_errors"] == {"wikimedia": "wikimedia HTTP 503"}


def _attach(asset, image):
    asset.local_path = str(image)
    return asset
