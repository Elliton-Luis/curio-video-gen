from curio.stages.scene_projection import Chapter
from curio.stages.scene_contract import SemanticScene, VisualRepresentation
from curio.stages.scene_local_planning import (
    local_visual_representations, recover_legacy_chapters)
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


def test_legacy_recovery_is_explicit_and_semantic_projection_is_passive():
    scene = Chapter(1, "The black hole bends light.", 3)
    semantic = scene.semantic_scene()
    assert not semantic.representations
    assert not semantic.visual_queries

    assert recover_legacy_chapters([scene])
    semantic = scene.semantic_scene()
    plan = build_visual_plan(semantic)
    assert plan.representations
    assert plan.representations[0].query == local_visual_representations(scene.narration)[0]
    assert plan.representations[0].source == "legacy_local_recovery"
    assert not hasattr(plan, "local_query_seeds")
    assert plan.space_topic


def test_llm_scene_without_representation_is_never_locally_repaired():
    scene = Chapter(2, "The black hole bends light.", 3,
                    planning_mode="llm")
    assert not recover_legacy_chapters([scene])
    semantic = scene.semantic_scene()
    assert not semantic.representations
    assert not semantic.visual_queries


def test_visual_planner_does_not_reinterpret_narration():
    scene = SemanticScene(
        id=9, narration="The battle used a microscope in a laboratory.",
        visual_type="literal")

    plan = build_visual_plan(scene)

    assert not plan.historical_scene
    assert not plan.scientific_context
    assert not plan.mechanistic
    assert not hasattr(plan, "narration")


def test_visual_planner_uses_explicit_planning_mode_not_intent_sentinel():
    scene = SemanticScene(
        id=10, narration="Literal sentence.",
        visual_intent="local fallback: phrase is data, not provenance",
        planning_mode="llm")
    assert build_visual_plan(scene).planning_mode == "llm"


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


def test_search_plan_prioritizes_scene_event_and_avoids_repeated_medium():
    scene = SemanticScene(
        id=12, narration="The battle was decisive.",
        visual_type="historical_art", planning_mode="deterministic",
        video_context={"topic": "Ottoman Empire"},
        representations=(
            VisualRepresentation("Ottoman Empire painting", kind="entity", level=0,
                                 source="verified_entity_context"),
            VisualRepresentation("Battle of Mohács", kind="event", level=1,
                                 source="local_concrete_phrase"),
            VisualRepresentation("Battle of Mohács 1526", kind="event", level=1,
                                 source="local_concrete_phrase"),
        ))

    queries = [item.query for item in build_search_plan(
        build_visual_plan(scene), "history").queries]

    assert len(queries) == 8
    assert queries[0] == "Battle of Mohács Ottoman Empire"
    assert "Battle of Mohács 1526 Ottoman Empire" in queries
    assert not any("painting painting" in query.casefold() for query in queries)
    assert not any(query.casefold().count("ottoman empire") > 1
                   for query in queries)
    assert all("Ottoman Empire" in query for query in queries)


def test_science_search_never_inherits_historical_map_fallback():
    scene = SemanticScene(
        id=13, narration="The black hole bends light around its event horizon.",
        visual_type="mechanism", planning_mode="deterministic",
        video_context={"topic": "M87* black hole",
                       "primary_entities": ["M87* black hole"]},
        primary_entity="M87* black hole",
        representations=(VisualRepresentation(
            "event horizon", kind="event", level=1,
            source="local_concrete_phrase"),))

    queries = [item.query for item in build_search_plan(
        build_visual_plan(scene), "science").queries]

    assert not any("historical map" in query.casefold() for query in queries)
    assert all(query.casefold().count("m87 black hole") <= 1
               for query in queries)
