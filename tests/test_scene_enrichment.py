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
        planning_mode="deterministic",
    )
    before = original.to_dict()

    result = enrich_scenes(
        [original], topic="Buracos negros",
        target=TargetEntity("Buracos negros", is_entity=False),
        source="local", planning_mode="deterministic", genre="science")

    assert original.to_dict() == before
    assert result.chapters[0] is not original
    assert result.semantic_scenes[0].contract_errors() == []
    assert result.semantic_scenes[0].video_context.topic == "Buracos negros"
    assert result.semantic_scenes[0].global_visual_queries
    assert result.source == "local"
    assert result.changed
    assert "video_context" in result.applied
    assert "local_topic_anchor" in result.applied


def test_scene_enrichment_is_an_explicit_identity_transform_when_no_context():
    chapter = Chapter(1, "Uma descrição da cena.", 4)

    result = enrich_scenes([chapter], topic="", source="llm",
                           planning_mode="llm", genre="")

    assert result.semantic_scenes[0].to_dict() == chapter.semantic_scene("llm").to_dict()
    assert result.source == "llm"
    assert result.applied == ()
    assert not result.changed


def test_semantic_scene_input_uses_same_enrichment_contract():
    chapter = Chapter(
        1, "A estrela curva o espaço.", 4, subject="estrela",
        planning_mode="deterministic", text_role="quote")
    semantic = chapter.semantic_scene("local")

    result = enrich_scenes([semantic], topic="Buracos negros",
                           source="local", planning_mode="deterministic")

    assert result.semantic_scenes[0].video_context.topic == "Buracos negros"
    assert result.semantic_scenes[0].text_role == "quote"
    assert result.chapters[0].duration_estimate == 0.0
    assert result.chapters[0].text_role == "quote"
