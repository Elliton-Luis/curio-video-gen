"""Regressions: local scene nouns must stay anchored to video topic."""

from curio.stages import scoring, visual
from curio.stages.entity import TargetEntity
from curio.stages.scenes import Chapter, _local_chapters
from curio.stages.visual_context import anchor_local_topic


def test_absoluto_never_generates_sun_query():
    text = ("A França, antes de 1789, era governada por um rei absoluto "
            "que dominava a nação há séculos.")
    assert "sun" not in visual.local_queries(text)
    assert visual.local_queries(text)[0] == "france"


def test_local_revolution_scenes_share_translated_video_anchor():
    script = ("A França era governada por um rei absoluto. "
              "O povo cansado de privilégios decidiu agir.")
    chapters = _local_chapters(script, 2)
    target = TargetEntity("Revolução Francesa", is_entity=True)
    assert anchor_local_topic(chapters, "A Revolução Francesa", target)
    assert all(ch.global_visual_queries == ["french revolution"]
               for ch in chapters)


def test_local_revolution_rejects_argentina_and_church_fallback():
    ch = Chapter(id=1, narration="A França antes de 1789.",
                 duration_estimate=5, subject="sun", visual_queries=["sun", "nation"],
                 global_visual_queries=["french revolution"],
                 visual_intent="local fallback: sun nation")
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
                 visual_intent="local fallback: mass radiation")
    bus = {"title": "Bus, mass station, public transport"}
    black_hole = {"title": "Black hole mass and event horizon"}
    assert not scoring.topic_anchor_matches(bus, ch)
    assert scoring.topic_anchor_matches(black_hole, ch)
    assert scoring.base_score(bus, ch)["score"] == 0


def test_person_video_keeps_person_portrait_across_local_context_scenes():
    ch = Chapter(id=4, narration="Marco Aurélio liderou campanhas na Armênia.",
                 duration_estimate=6, subject="Armenia", visual_queries=["Armenia", "war"],
                 global_visual_queries=["marcus aurelius"],
                 visual_intent="local fallback: Armenia war")
    portrait = {"title": "Bust of Marcus Aurelius, Roman emperor"}
    namesake = {"title": "Fábio Aurélio football player portrait"}
    assert scoring.topic_anchor_matches(portrait, ch)
    assert scoring.base_score(portrait, ch)["score"] >= scoring.threshold()
    assert not scoring.topic_anchor_matches(namesake, ch)
    assert scoring.base_score(namesake, ch)["score"] == 0
