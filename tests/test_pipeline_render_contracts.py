import pytest
from types import SimpleNamespace

from curio.media.selection_result import MediaStageResult
from curio.pipeline_render import (
    RenderStageResult,
    RenderStageInput,
    RenderTransitionPlan,
    SceneRenderInput,
    SceneRenderPlan,
    genre_transition_kinds,
    genre_transitions,
    plan_transitions,
    transition_signature,
)
from curio.stages.scene_contract import SemanticScene
from curio.stages.scene_contract import TimelineSpan
from tests.media_test_support import with_selection


def test_render_plan_projects_validated_media_selection():
    result = MediaStageResult.from_rows([with_selection({
        "chapter_id": 1,
        "asset": {"provider": "wikimedia", "asset_id": "map-1",
                  "local_path": "/cache/map.jpg", "kind": "image"},
        "assets": [],
    })], "provider")

    plan = SceneRenderPlan.from_media_result(result)

    assert plan.scenes[0].scene_id == 1
    assert plan.scenes[0].asset.local_path == "/cache/map.jpg"
    assert plan.for_scenes((SemanticScene(1, "A scene."),))[1].kind == "image"


def test_persisted_adapter_preserves_legacy_renderable_asset_without_identity():
    plan = SceneRenderPlan.from_persisted_rows([{
        "chapter_id": 1,
        "asset": {"local_path": "/old-project/photo.jpg"},
    }])

    assert plan.scenes[0].asset.local_path == "/old-project/photo.jpg"
    assert plan.scenes[0].asset.kind == "image"


def test_transition_plan_unifies_render_choices_and_cache_signature():
    scenes = (SemanticScene(1, "Opening."), SemanticScene(2, "The army invaded."))
    spans = (TimelineSpan(1, 5, 0, 5), TimelineSpan(2, 5, 5, 10))
    identity = {"visual_sfx": False}

    plan = plan_transitions(scenes, spans, "history", "auto", identity)

    assert isinstance(plan, RenderTransitionPlan)
    assert plan.boundary_durations == tuple(genre_transitions(scenes, "history"))
    assert plan.kinds == tuple(genre_transition_kinds(scenes, "history"))
    assert plan.signature == transition_signature(
        scenes, spans, "history", "auto", identity)
    assert plan.to_dict(0.65) == {
        "genre": "history", "mode": "auto",
        "boundary_durations": list(plan.boundary_durations), "final_fade": 0.65}


def test_transition_plan_rejects_inconsistent_choices():
    with pytest.raises(ValueError, match="incomplete or inconsistent"):
        RenderTransitionPlan("history", "auto", (float("nan"),), ("fade",), "sig")
    with pytest.raises(ValueError, match="incomplete or inconsistent"):
        RenderTransitionPlan("history", "auto", (0.2,), (), "sig")


@pytest.mark.parametrize("rows, error", [
    ({}, TypeError),
    ([{"chapter_id": True, "asset": None}], ValueError),
    ([{"chapter_id": 1}, {"chapter_id": 1}], ValueError),
    ([{"chapter_id": 1, "asset": "bad"}], TypeError),
])
def test_persisted_render_adapter_rejects_invalid_scene_rows(rows, error):
    with pytest.raises(error):
        SceneRenderPlan.from_persisted_rows(rows)


def test_render_stage_input_rejects_misaligned_contracts():
    from curio.config import CurioConfig

    scenes = (SemanticScene(1, "Opening."),)
    plan = SceneRenderPlan((SceneRenderInput(1, None),))
    with pytest.raises(ValueError, match="render scenes and spans are misaligned"):
        RenderStageInput(
            semantic_scenes=scenes,
            timeline_spans=(TimelineSpan(2, 4, 0, 4),),
            visual_timeline=[], media_plan=plan, idea="idea", slug="slug",
            title="title", script_text="script", paths=object(),
            cfg=CurioConfig(), genre="history", audio_duration=4,
            tts_info={}, subtitles_changed=False, force=False,
            transition_mode="none", visual_config={})


def test_render_stage_result_uses_shared_duration_contract():
    plan = RenderTransitionPlan("history", "auto", (), (), "signature")
    args = ({}, 1.0, {}, None, None, plan, {}, "visual-signature", (), ())
    with pytest.raises(TypeError, match="render stage elapsed"):
        RenderStageResult(*args, elapsed="1")
    with pytest.raises(ValueError, match="render duration"):
        RenderStageResult({}, -1, {}, None, None, plan, {}, "visual-signature",
                          (), (), elapsed=0)


def test_visual_render_usage_records_paths_passed_and_unavailable_assets(
        tmp_path, monkeypatch):
    from curio import pipeline_render
    from curio.config import CurioConfig
    from curio.metrics import RunMetrics
    from curio.stages.visual_beats import asset_key

    existing = tmp_path / "present.jpg"
    existing.write_bytes(b"image")
    paths = SimpleNamespace(root=str(tmp_path))
    monkeypatch.setattr(
        "curio.stages.render.render_image_segment",
        lambda *args, **kwargs: str(tmp_path / "segment.mp4"))
    monkeypatch.setattr(
        "curio.stages.render.concat_copy",
        lambda segments, out_path, cfg: out_path)
    timeline = [{
        "chapter_id": 1,
        "start": 0,
        "end": 2,
        "images": [
            {"provider": "fixture", "asset_id": "present",
             "local_path": str(existing), "start": 0, "duration": 2},
            {"provider": "fixture", "asset_id": "missing",
             "local_path": str(tmp_path / "missing.jpg"),
             "start": 0, "duration": 1, "order": 1},
        ],
    }]

    result = pipeline_render.build_silent_visual(
        (SemanticScene(1, "A scene."),), (TimelineSpan(1, 2, 0, 2),),
        timeline, "topic", paths, CurioConfig(), str(tmp_path / "silent.mp4"))
    metrics = RunMetrics("fixture", "topic", "narration")
    metrics.visual_record_render_usage(result)

    missing_key = asset_key(timeline[0]["images"][1])
    present_key = asset_key(timeline[0]["images"][0])
    assert result.scenes[0].requested_asset_ids == tuple(
        sorted((missing_key, present_key)))
    assert result.scenes[0].segment_asset_ids == (present_key,)
    assert result.scenes[0].unavailable_asset_ids == (missing_key,)
    assert result.scenes[0].omitted_asset_ids == (missing_key,)
    assert result.scenes[0].fallback_used is False
    assert result.scenes[0].segment_reused is False
    assert metrics.to_dict({}, {}, "metrics")["pipeline"][
        "visual_render_usage"] == result.to_dict()


def test_visual_render_usage_marks_synthetic_fallback_when_no_file_is_usable(
        tmp_path, monkeypatch):
    from curio import pipeline_render
    from curio.config import CurioConfig

    paths = SimpleNamespace(root=str(tmp_path))
    monkeypatch.setattr(
        "curio.stages.render.render_fallback_segment",
        lambda duration, out_path, cfg, title: str(tmp_path / "fallback.mp4"))
    monkeypatch.setattr(
        "curio.stages.render.concat_copy",
        lambda segments, out_path, cfg: out_path)
    result = pipeline_render.build_silent_visual(
        (SemanticScene(1, "A scene."),), (TimelineSpan(1, 2, 0, 2),),
        [{"chapter_id": 1, "start": 0, "end": 2,
          "images": [{"provider": "fixture", "asset_id": "missing",
                      "local_path": str(tmp_path / "missing.jpg")}]}],
        "topic", paths, CurioConfig(), str(tmp_path / "silent.mp4"))

    usage = result.scenes[0]
    assert usage.requested_asset_ids == ("fixture:missing",)
    assert usage.segment_asset_ids == ()
    assert usage.unavailable_asset_ids == ("fixture:missing",)
    assert usage.fallback_used is True
    assert usage.segment_reused is False


def test_primary_asset_render_usage_covers_legacy_non_timeline_path(
        tmp_path, monkeypatch):
    from curio import pipeline_render
    from curio.config import CurioConfig
    from curio.stages.visual_beats import asset_key

    present = tmp_path / "present.jpg"
    present.write_bytes(b"image")
    missing = tmp_path / "missing.jpg"
    rows = [
        {"chapter_id": 1, "asset": {
            "provider": "fixture", "asset_id": "present",
            "local_path": str(present)}},
        {"chapter_id": 2, "asset": {
            "provider": "fixture", "asset_id": "missing",
            "local_path": str(missing)}},
    ]
    plan = SceneRenderPlan.from_persisted_rows(rows)
    paths = SimpleNamespace(root=str(tmp_path))
    monkeypatch.setattr(
        "curio.stages.render.render_image_segment",
        lambda *args, **kwargs: str(tmp_path / "image-segment.mp4"))
    monkeypatch.setattr(
        "curio.stages.render.render_fallback_segment",
        lambda *args, **kwargs: str(tmp_path / "fallback-segment.mp4"))
    monkeypatch.setattr(
        "curio.stages.render.concat_copy",
        lambda segments, out_path, cfg: out_path)

    result = pipeline_render.build_silent(
        (SemanticScene(1, "First."), SemanticScene(2, "Second.")),
        (TimelineSpan(1, 2, 0, 2), TimelineSpan(2, 2, 2, 4)),
        plan, "topic", paths, CurioConfig(), str(tmp_path / "silent.mp4"))

    assert result.scenes[0].segment_asset_ids == (
        asset_key(rows[0]["asset"]),)
    assert result.scenes[0].fallback_used is False
    assert result.scenes[0].segment_reused is False
    assert result.scenes[1].unavailable_asset_ids == (
        asset_key(rows[1]["asset"]),)
    assert result.scenes[1].fallback_used is True
    assert result.scenes[1].segment_reused is False
