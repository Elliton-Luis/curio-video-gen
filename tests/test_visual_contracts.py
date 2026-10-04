from curio.stages.scenes import Chapter
from curio.stages.scene_contract import SemanticScene
from curio.stages.scene_local_planning import local_visual_representations
from curio.stages.visual_planning import build_visual_plan
from curio.stages.search_planning import build_search_plan


def test_visual_plan_closes_scene_inputs_without_copying_narration():
    scene = Chapter.from_dict({
        "id": 3,
        "narration": "Os janízaros formavam a elite militar do Império Otomano.",
        "duration_estimate": 4,
        "visual_type": "historical_art",
        "visual_intent": "scene planner",
        "visual_intent_structured": "Janissary military elite",
        "visual_queries": ["Ottoman Janissaries"],
        "representations": [{
            "query": "Ottoman Janissaries", "kind": "army", "level": 0,
            "source": "scene_planner",
        }],
        "video_context": {
            "topic": "Ottoman Empire",
            "aliases": ["Ottoman Empire"],
        },
    })

    plan = build_visual_plan(scene.semantic_scene())
    assert plan.scene_id == scene.id
    assert plan.topic == "Ottoman Empire"
    assert plan.representations[0].query == "Ottoman Janissaries"
    assert plan.historical_scene
    assert not hasattr(plan, "narration")
    assert "narration" not in plan.to_dict()


def test_semantic_scene_materializes_local_representations_before_visual_plan():
    scene = Chapter(1, "The black hole bends light.", 3)
    semantic = scene.semantic_scene()
    plan = build_visual_plan(semantic)
    assert plan.representations
    assert plan.representations[0].query == local_visual_representations(scene.narration)[0]
    assert not hasattr(plan, "local_query_seeds")
    assert plan.space_topic


def test_visual_planner_does_not_reinterpret_narration():
    scene = SemanticScene(
        id=9, narration="The battle used a microscope in a laboratory.",
        visual_type="literal")

    plan = build_visual_plan(scene)

    assert not plan.historical_scene
    assert not plan.scientific_context
    assert not plan.mechanistic
    assert not hasattr(plan, "narration")


def test_search_plan_queries_have_representation_context_and_provenance():
    scene = Chapter.from_dict({
        "id": 8,
        "narration": "Os janízaros formavam a elite militar do Império Otomano.",
        "duration_estimate": 4,
        "visual_type": "historical_art",
        "visual_queries": ["Ottoman Janissaries"],
        "representations": [{
            "query": "Ottoman Janissaries", "kind": "army", "level": 0,
            "source": "entity_catalog",
        }],
        "video_context": {"topic": "Ottoman Empire",
                          "aliases": ["Ottoman Empire"]},
    })
    plan = build_search_plan(build_visual_plan(scene.semantic_scene()), "history")
    assert plan.queries
    assert all(item.source and item.level >= 1 for item in plan.queries)
    assert all("formavam" not in item.query.casefold() for item in plan.queries)
    assert all("microscope" not in item.query.casefold() for item in plan.queries)
    specific = next(item for item in plan.queries if item.query.startswith("Ottoman Janissaries"))
    assert specific.representation == "Ottoman Janissaries"
    assert specific.representation_kind == "army"
    assert specific.alias == "Ottoman Empire"
