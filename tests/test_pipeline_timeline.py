from types import SimpleNamespace

from curio.pipeline_timeline import build_visual_timeline
from curio.stages.scene_contract import SemanticScene, TimelineSpan


class _Metrics:
    def __init__(self):
        self.visual = None

    def visual_plan(self, spans, media, beat_seconds, entries):
        self.visual = (spans, media, beat_seconds, entries)


def test_timeline_stage_returns_and_persists_the_same_plan(tmp_path, monkeypatch):
    entries = [{"chapter_id": 1, "fallback": True,
                "images": [{"order": 0}, {"order": 1}]}]
    monkeypatch.setattr("curio.pipeline_timeline.visual_stage.build_visual_timeline",
                        lambda *args, **kwargs: entries)
    writes = []
    metrics = _Metrics()
    semantic_scenes = (SemanticScene(1, "A scene."),)
    spans = (TimelineSpan(1, 1, 0, 1),)
    scenes = [{"chapter_id": 1}]

    result = build_visual_timeline(
        semantic_scenes, spans, scenes,
        SimpleNamespace(visual_json=str(tmp_path / "visual.json")),
        "slug", 0.8, False, 2, "drop_in", -15, True, metrics,
        lambda path, data: writes.append((path, data)))

    assert result.entries is entries
    assert result.insertion_count == 1
    assert result.enabled is True
    assert writes == [(str(tmp_path / "visual.json"), entries)]
    assert metrics.visual[0:2] == (spans, scenes)
    assert metrics.visual[3] is entries


def test_disabled_timeline_still_records_visual_metrics_without_writes(monkeypatch):
    monkeypatch.setattr(
        "curio.pipeline_timeline.visual_stage.build_visual_timeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("no overlays requested")))
    metrics = _Metrics()

    result = build_visual_timeline(
        [], [], [], SimpleNamespace(visual_json="unused"), "slug", 0.8,
        False, 0, "drop_in", -15, False, metrics,
        lambda *_: (_ for _ in ()).throw(AssertionError("must not persist")))

    assert result.entries == []
    assert result.insertion_count == 0
    assert result.enabled is False
    assert metrics.visual[3] == []
