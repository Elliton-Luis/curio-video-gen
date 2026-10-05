import pytest

from curio.pipeline_research import ResearchStageResult
from curio.pipeline_scenes import SceneStageResult
from curio.pipeline_script import ScriptStageResult
from curio.stage_timing import validate_stage_elapsed
from curio.stages.research import ResearchResult
from curio.stages.scene_contract import SemanticScene, TimelineSpan
from curio.stages.scene_enrichment import SceneEnrichmentResult
from curio.stages.script import ScriptArtifact, TitleArtifact


@pytest.mark.parametrize("value", [0, 1.25])
def test_stage_elapsed_is_seconds_and_normalizes_numeric_values(value):
    assert validate_stage_elapsed(value, "test stage") == float(value)


@pytest.mark.parametrize("value", [True, "1.2", None])
def test_stage_elapsed_rejects_non_numeric_values(value):
    with pytest.raises(TypeError, match="number of seconds"):
        validate_stage_elapsed(value, "test stage")


@pytest.mark.parametrize("value", [-0.1, float("inf"), float("nan")])
def test_stage_elapsed_rejects_negative_or_non_finite_values(value):
    with pytest.raises(ValueError, match="finite and non-negative"):
        validate_stage_elapsed(value, "test stage")


def test_stage_results_share_the_same_elapsed_invariant():
    with pytest.raises(ValueError, match="research stage elapsed"):
        ResearchStageResult(ResearchResult(None, []), "ok", "", -1)

    with pytest.raises(TypeError, match="script stage elapsed"):
        ScriptStageResult(ScriptArtifact("Narration.", "provided"),
                          TitleArtifact("Title", "provided"), {},
                          False, False, (), "0.3")

    scene = SemanticScene(1, "Narration.")
    enrichment = SceneEnrichmentResult((scene,), "cached", ())
    with pytest.raises(ValueError, match="scene stage elapsed"):
        SceneStageResult((TimelineSpan(1, 1, 0, 1),), "cached",
                         enrichment, False, float("nan"))
