from curio.stages.entity import TargetEntity
from curio.stages.scene_enrichment import enrich_scenes
from curio.stages.scenes import Chapter


def test_scene_enrichment_returns_valid_batch_without_mutating_planner_output():
    original = Chapter(
        id=1,
        narration="A massa de uma estrela curva o espaço.",
        duration_estimate=5,
        subject="massa",
        visual_intent="local fallback: massa estrela",
    )
    before = original.to_dict()

    result = enrich_scenes(
        [original], topic="Buracos negros",
        target=TargetEntity("Buracos negros", is_entity=False),
        source="local", local_fallback=True, genre="science")

    assert original.to_dict() == before
    assert result.scenes[0] is not original
    assert result.scenes[0].contract_errors() == []
    assert result.scenes[0].video_context.topic == "Buracos negros"
    assert result.scenes[0].global_visual_queries
    assert result.source == "local"
    assert result.changed
    assert "video_context" in result.applied
    assert "local_topic_anchor" in result.applied


def test_scene_enrichment_is_an_explicit_identity_transform_when_no_context():
    chapter = Chapter(1, "Uma descrição da cena.", 4)

    result = enrich_scenes([chapter], topic="", source="llm",
                           local_fallback=False, genre="")

    assert result.scenes[0].to_dict() == chapter.to_dict()
    assert result.source == "llm"
    assert result.applied == ()
    assert not result.changed
