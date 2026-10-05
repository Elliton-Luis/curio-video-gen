import pytest

from curio.stages.scene_contract import SemanticScene
from curio.stages.visual_contracts import VisualFallbackPlan
from curio.stages.visual_fallback_planning import build_visual_fallback_plan
from curio.stages.visual_planning import build_visual_plan


def _scene(scene_id, *, visual_type="literal", visual_steps=(), reps=()):
    return SemanticScene(
        id=scene_id,
        narration="Janissaries formed the Ottoman elite military force.",
        visual_type=visual_type,
        subject="Ottoman Empire",
        video_context={"topic": "Ottoman Empire"},
        representations=tuple(reps),
        visual_steps=tuple(visual_steps),
    )


def test_scene_specific_representation_wins_over_global_topic():
    scene = _scene(1, reps=[{"query": "Ottoman Janissaries", "kind": "army",
                            "source": "scene_planner"}])

    plan = build_visual_fallback_plan(build_visual_plan(scene), scene.narration)

    assert plan.subject == "Ottoman Janissaries"
    assert plan.subject_source == "approved_representation"
    assert plan.strategy == "form"
    assert "Ottoman Janissaries" in plan.to_dict()["subject"]


def test_mechanism_needs_explicit_ordered_steps_for_diagram():
    no_steps = _scene(2, visual_type="mechanism", reps=[
        {"query": "antibody binding", "kind": "object", "source": "planner"},
        {"query": "test line", "kind": "object", "source": "planner"},
    ])
    with_steps = _scene(3, visual_type="mechanism",
                        visual_steps=("antibody binds hCG", "test line appears"))

    first = build_visual_fallback_plan(build_visual_plan(no_steps), no_steps.narration)
    second = build_visual_fallback_plan(build_visual_plan(with_steps), with_steps.narration)

    assert first.strategy == "form"
    assert first.steps == ()
    assert second.strategy == "diagram"
    assert second.steps == ("antibody binds hCG", "test line appears")


def test_invalid_diagram_plan_is_rejected():
    with pytest.raises(ValueError, match="two declared steps"):
        VisualFallbackPlan(
            scene_id=4, strategy="diagram", form="", subject="test",
            subject_source="approved_representation", visual_type="mechanism",
            text_role="term", narration="narration", quote_text="", period="",
            event="", place="", visual_entities=(), context=(), steps=("only one",),
            reason="test",
        )
