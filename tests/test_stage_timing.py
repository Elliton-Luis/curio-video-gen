import pytest

from curio.pipeline_research import ResearchStageResult
from curio.pipeline_scenes import SceneStageResult
from curio.pipeline_script import ScriptStageResult
from curio.stage_timing import StageTiming, StageTimings, validate_stage_elapsed
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


def test_stage_timings_are_immutable_unique_and_project_to_json_mapping():
    timings = StageTimings().with_stage("script", 1)
    combined = timings.merged(StageTimings().with_stage("tts", 2))

    assert dict(combined) == {"script": 1.0, "tts": 2.0}
    assert timings.to_dict() == {"script": 1.0}
    with pytest.raises(ValueError, match="already recorded"):
        timings.with_stage("script", 3)
    with pytest.raises(ValueError, match="duplicate names"):
        timings.merged(StageTimings().with_stage("script", 2))
    with pytest.raises(TypeError, match="immutable tuple"):
        StageTimings([StageTiming("script", 1)])
