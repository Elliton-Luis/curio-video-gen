from curio import pipeline_metadata


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
