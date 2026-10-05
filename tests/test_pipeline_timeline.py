from types import SimpleNamespace

import pytest

from curio.media.selection_result import MediaStageResult
from curio.pipeline_timeline import build_visual_timeline
from curio.stages.scene_contract import SemanticScene, TimelineSpan


def _selection(scene_id=1):
    return MediaStageResult.from_rows(
        [{"chapter_id": scene_id, "asset": None, "assets": []}], "provider")


class _Metrics:
    def __init__(self):
        self.visual = None

    def visual_plan(self, spans, media, beat_seconds, entries):
        self.visual = (spans, media, beat_seconds, entries)


def test_timeline_stage_returns_and_persists_the_same_plan(tmp_path, monkeypatch):
    entries = [{"chapter_id": 1, "fallback": True,
                "images": [{"order": 0}, {"order": 1}]}]
    monkeypatch.setattr("curio.pipeline_timeline.visual_timeline_stage.build_visual_timeline",
                        lambda *args, **kwargs: entries)
    writes = []
    metrics = _Metrics()
    semantic_scenes = (SemanticScene(1, "A scene."),)
    spans = (TimelineSpan(1, 1, 0, 1),)
    media_result = _selection()
    from curio.media.selection_metrics import MediaMetricsInput
    metric_input = MediaMetricsInput.from_result(media_result)

    result = build_visual_timeline(
        semantic_scenes, spans, media_result,
        SimpleNamespace(visual_json=str(tmp_path / "visual.json")),
        "slug", 0.8, False, 2, "drop_in", -15, True, metrics,
        lambda path, data: writes.append((path, data)))

    assert result.entries is entries
    assert result.insertion_count == 1
    assert result.enabled is True
    assert writes == [(str(tmp_path / "visual.json"), entries)]
    assert metrics.visual[0:2] == (spans, metric_input)
    assert metrics.visual[3] is entries


def test_disabled_timeline_still_records_visual_metrics_without_writes(monkeypatch):
    monkeypatch.setattr(
        "curio.pipeline_timeline.visual_timeline_stage.build_visual_timeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("no overlays requested")))
    metrics = _Metrics()

    result = build_visual_timeline(
        (SemanticScene(1, "A scene."),), (TimelineSpan(1, 1, 0, 1),),
        _selection(), SimpleNamespace(visual_json="unused"), "slug", 0.8,
        False, 0, "drop_in", -15, False, metrics,
        lambda *_: (_ for _ in ()).throw(AssertionError("must not persist")))

    assert result.entries == []
    assert result.insertion_count == 0
    assert result.enabled is False
    assert metrics.visual[3] == []


def test_timeline_rejects_untyped_or_misaligned_media():
    scene = SemanticScene(1, "A scene.")
    span = TimelineSpan(1, 1, 0, 1)
    args = (scene,), (span,), None, SimpleNamespace(visual_json="unused")

    with pytest.raises(TypeError, match="MediaStageResult"):
        build_visual_timeline(
            args[0], args[1], [{"chapter_id": 1}], args[3], "slug", 0.8,
            False, 0, "drop_in", -15, True, _Metrics(), lambda *_: None)
    with pytest.raises(ValueError, match="misaligned"):
        build_visual_timeline(
            args[0], args[1], _selection(2), args[3], "slug", 0.8,
            False, 0, "drop_in", -15, True, _Metrics(), lambda *_: None)
