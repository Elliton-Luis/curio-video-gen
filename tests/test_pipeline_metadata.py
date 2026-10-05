from curio import pipeline_metadata
from curio.media.selection_result import MediaStageResult
from curio.stages.scene_contract import SemanticScene, TimelineSpan


def test_final_metadata_and_metrics_share_finalize_measurement(
        tmp_path, monkeypatch):
    clock = iter((20.25, 24.0))
    monkeypatch.setattr(pipeline_metadata.time, "monotonic", lambda: next(clock))
    writes = []

    class Metrics:
        def save(self, metadata, stage_times, metrics_dir):
            assert stage_times["finalize"] == 0.25
            assert metadata["stage_times"]["finalize"] == 0.25
            assert metrics_dir == str(tmp_path)
            return str(tmp_path / "metrics.json")

    metadata = {"stage_times": {"script": 1.0}}
    result = pipeline_metadata.persist_run_metadata(
        metadata, str(tmp_path / "metadata.json"), Metrics(),
        metadata["stage_times"], str(tmp_path),
        lambda path, value: writes.append((path, value.copy())),
        finalize_started=20.0, run_started=10.0)

    assert result["processing_time_seconds"] == 14.0
    assert result["metrics_file"] == str(tmp_path / "metrics.json")
    assert writes[0][1]["stage_times"] == {"script": 1.0, "finalize": 0.25}
    assert writes[0][1]["metrics_file"] == str(tmp_path / "metrics.json")


def test_base_metadata_projects_legacy_chapters_from_aligned_contracts():
    class Cfg:
        duration_target = 45
        width, height, fps = 1080, 1920, 30

    class Metrics:
        def media_visual_report(self, count):
            return {"scene_count": count}

        def media_download_report(self):
            return {}

    scene = SemanticScene(id=1, narration="Cena de teste.",
                          visual_type="literal")
    span = TimelineSpan(scene_id=1, duration_estimate=4, start=2, end=6)
    media = MediaStageResult.from_rows(
        [{"chapter_id": 1, "asset": None, "assets": []}], "project-cache")
    metadata = pipeline_metadata.build_base_metadata(
        "teste", "teste", Cfg(), "Cena de teste.", "fixture",
        (scene,), (span,), "fixture", media, [], {}, Metrics(), 0)
    assert metadata["chapters"][0]["id"] == 1
    assert metadata["chapters"][0]["start"] == 2
    assert metadata["chapters"][0]["end"] == 6
    assert metadata["visual_report"] == {"scene_count": 1}
    assert metadata["media"] == media.to_rows()
    assert metadata["media_resolution_source"] == "project-cache"


def test_base_metadata_rejects_misaligned_scene_and_timing_batches():
    import pytest

    with pytest.raises(ValueError, match="metadata scenes, media and spans are misaligned"):
        pipeline_metadata.build_base_metadata(
            "teste", "teste", object(), "", "fixture",
            (SemanticScene(id=1, narration="Cena."),),
            (TimelineSpan(scene_id=2),), "fixture",
            MediaStageResult.from_rows(
                [{"chapter_id": 1, "asset": None}], "provider"),
            [], {}, object(), 0)


def test_base_metadata_rejects_media_selection_for_different_scene():
    import pytest

    class Cfg:
        duration_target = 45
        width, height, fps = 1080, 1920, 30

    scene = SemanticScene(id=1, narration="Cena.")
    span = TimelineSpan(scene_id=1)
    media = MediaStageResult.from_rows(
        [{"chapter_id": 2, "asset": None}], "provider")
    with pytest.raises(ValueError, match="metadata scenes, media and spans"):
        pipeline_metadata.build_base_metadata(
            "teste", "teste", Cfg(), "Cena.", "fixture", (scene,),
            (span,), "fixture", media, [], {}, object(), 0)
