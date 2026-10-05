"""Regressions: local scene nouns must stay anchored to video topic."""

from curio.stages import scoring
from curio.stages.entity import TargetEntity
from curio.stages.scene_projection import Chapter
from curio.stages.scenes import build_local_semantic_scenes
from curio.stages.scene_enrichment import enrich_scenes
from curio.stages.scene_local_planning import local_visual_representations


def test_absoluto_never_generates_sun_query():
    text = ("A França, antes de 1789, era governada por um rei absoluto "
            "que dominava a nação há séculos.")
    assert "sun" not in local_visual_representations(text)
    assert local_visual_representations(text)[0] == "france"


def test_local_revolution_scenes_share_translated_video_anchor():
    script = ("A França era governada por um rei absoluto. "
              "O povo cansado de privilégios decidiu agir.")
    plan = build_local_semantic_scenes(script, 2)
    assert any(scene.representations for scene in plan.semantic_scenes)
    assert all(not scene.global_visual_queries for scene in plan.semantic_scenes)
    target = TargetEntity("Revolução Francesa", is_entity=True)
    enriched = enrich_scenes(
        plan.semantic_scenes, timeline_spans=plan.timeline_spans,
        topic="A Revolução Francesa", target=target, source="local",
        planning_mode="deterministic")
    chapters = enriched.semantic_scenes
    assert "local_topic_anchor" in enriched.applied
    assert all(any("revolução francesa" in q.casefold()
                   or "french revolution" in q.casefold()
                   for q in ch.global_visual_queries)
               for ch in chapters)


def test_local_revolution_rejects_argentina_and_church_fallback():
    ch = Chapter(id=1, narration="A França antes de 1789.",
                 duration_estimate=5, subject="sun", visual_queries=["sun", "nation"],
                 global_visual_queries=["french revolution"],
                 visual_intent="sun nation", planning_mode="deterministic")
    argentina = {"title": "Argentinian flag, sun, country, nation"}
    church = {"title": "Catholic church interior, nave, altar"}
    french_revolution = {"title": "French Revolution, Paris, 1789"}
    assert not scoring.topic_anchor_matches(argentina, ch)
    assert not scoring.topic_anchor_matches(church, ch)
    assert scoring.topic_anchor_matches(french_revolution, ch)
    assert scoring.base_score(argentina, ch)["score"] == 0


def test_local_black_hole_rejects_bus_mass():
    ch = Chapter(id=1, narration="Black holes contain enormous mass.",
                 duration_estimate=5, subject="mass",
                 visual_queries=["mass", "radiation"],
                 global_visual_queries=["black hole"],
                 visual_intent="mass radiation", planning_mode="deterministic")
    bus = {"title": "Bus, mass station, public transport"}
    black_hole = {"title": "Black hole mass and event horizon"}
    assert not scoring.topic_anchor_matches(bus, ch)
    assert scoring.topic_anchor_matches(black_hole, ch)
    assert scoring.base_score(bus, ch)["score"] == 0


def test_person_video_keeps_person_portrait_across_local_context_scenes():
    ch = Chapter(id=4, narration="Marco Aurélio liderou campanhas na Armênia.",
                 duration_estimate=6, subject="Armenia", visual_queries=["Armenia", "war"],
                 global_visual_queries=["marcus aurelius"],
                 visual_intent="Armenia war", planning_mode="deterministic")
    portrait = {"title": "Bust of Marcus Aurelius, Roman emperor"}
    namesake = {"title": "Fábio Aurélio football player portrait"}
    assert scoring.topic_anchor_matches(portrait, ch)
    assert scoring.base_score(portrait, ch)["score"] >= scoring.threshold()
    assert not scoring.topic_anchor_matches(namesake, ch)
    assert scoring.base_score(namesake, ch)["score"] == 0


def test_topic_anchor_does_not_reparse_narration():
    ch = Chapter(id=5, narration="French Revolution Paris 1789.",
                 duration_estimate=5, planning_mode="deterministic")
    assert scoring.topic_anchor_matches({"title": "unrelated artwork"}, ch)


def test_tesla_current_queries_distinguish_electricity_from_river():
    narration = ("Tesla desenvolveu o motor de indução de corrente alternada; "
                 "Edison defendia corrente contínua.")
    queries = local_visual_representations(narration)
    assert "induction motor" in queries
    assert "alternating current" in queries
    assert "direct current" in local_visual_representations(
        "Edison defendia corrente contínua.")
    assert "river" not in queries


def test_tesla_anchor_accepts_invention_but_rejects_river_bridge():
    ch = Chapter(id=2,
                 narration="Tesla desenvolveu corrente alternada e um motor de indução.",
                 duration_estimate=5, subject="current",
                 visual_queries=["alternating current", "induction motor"],
                 global_visual_queries=["nikola tesla"],
                 visual_intent="current induction motor",
                 planning_mode="deterministic")
    river = {"title": "Ponte sobre o Rio Corrente"}
    ac_motor = {"title": "Alternating current induction motor, Nikola Tesla"}
    assert not scoring.topic_anchor_matches(river, ch)
    assert scoring.topic_anchor_matches(ac_motor, ch)
