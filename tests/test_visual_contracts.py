from curio.stages.scenes import Chapter
from curio.stages.visual import local_queries
from curio.stages.visual_planning import build_visual_plan


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

    plan = build_visual_plan(scene, local_queries)
    assert plan.scene_id == scene.id
    assert plan.topic == "Ottoman Empire"
    assert plan.representations[0].query == "Ottoman Janissaries"
    assert plan.historical_scene
    assert not hasattr(plan, "narration")
    assert "narration" not in plan.to_dict()


def test_visual_plan_materializes_legacy_local_query_fallback_once():
    scene = Chapter(1, "The black hole bends light.", 3)
    plan = build_visual_plan(scene, local_queries)
    assert plan.local_query_seeds == tuple(local_queries(scene.narration))
    assert plan.space_topic
