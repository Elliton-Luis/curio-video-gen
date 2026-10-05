import pytest

from curio.metrics import RunMetrics
from curio.stages.media_search import submit_search
from curio.stages.scene_contract import TimelineSpan


@pytest.mark.parametrize("duration", [0, 12.5])
def test_live_metrics_total_uses_pipeline_processing_duration(
        duration, monkeypatch, tmp_path):
    metrics = RunMetrics("test", "idea", "ai")
    monkeypatch.setattr("curio.metrics.time.monotonic",
                        lambda: metrics.started_monotonic + 100)

    report = metrics.to_dict(
        {"processing_time_seconds": duration}, {}, str(tmp_path))

    assert report["time"]["total_seconds"] == duration


def test_direct_metrics_total_uses_collector_clock_when_pipeline_duration_unknown(
        monkeypatch, tmp_path):
    metrics = RunMetrics("test", "idea", "ai")
    monkeypatch.setattr("curio.metrics.time.monotonic",
                        lambda: metrics.started_monotonic + 3.25)

    report = metrics.to_dict({}, {}, str(tmp_path))

    assert report["time"]["total_seconds"] == 3.25


def test_search_counters_are_distinct_logical_calls_requests_and_retries():
    metrics = RunMetrics("test", "idea", "ai")

    # Legacy output name aliases one mutable provider-request counter.
    metrics.media_search("wikimedia")
    assert metrics.media_searches is metrics.media_requests_per_provider
    assert metrics.media_searches == {"wikimedia": 1}

    metrics.media_record_retry("wikimedia", operation="search")
    metrics.media_record_retry("wikimedia", operation="download")
    assert metrics.media_retries == 2
    assert metrics.media_retries_by_provider == {"wikimedia": 2}
    assert metrics.media_retries_by_operation == {
        "search": 1, "download": 1, "unknown": 0}
    assert metrics.media_retries_by_provider_operation == {
        "wikimedia": {"search": 1, "download": 1, "unknown": 0}}

    media = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]
    assert media["retries"] == 2
    assert media["retries_by_operation"] == metrics.media_retries_by_operation
    assert media["retries_by_provider_operation"] == (
        metrics.media_retries_by_provider_operation)


def test_provider_search_timing_measures_one_adapter_call():
    metrics = RunMetrics("test", "idea", "ai")

    class Provider:
        name = "fixture"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            return []

    assert submit_search(Provider(), "query", metrics).result(timeout=2) == []
    record = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]

    assert record["requests_per_provider"] == {"fixture": 1}
    assert record["provider_search_calls"] == {"fixture": 1}
    assert len(record["provider_search_durations"]["fixture"]) == 1
    assert record["provider_search_durations"]["fixture"][0] >= 0
    assert record["time_per_request"] is None


def test_timeline_asset_metrics_are_named_separately_from_real_selection():
    metrics = RunMetrics("test", "Rome", "ai")
    real = {"provider": "wikimedia", "asset_id": "rome"}
    synthetic = {"provider": "synth", "asset_id": "card"}
    scenes = [
        {"chapter_id": 1, "asset": real, "assets": [{"asset": real}],
         "visual_decision": {"selection": {"status": "real"}}},
        {"chapter_id": 2, "asset": real, "assets": [{"asset": real}],
         "visual_decision": {"selection": {"status": "reused"}}},
        {"chapter_id": 3, "asset": synthetic, "assets": [{"asset": synthetic}],
         "visual_decision": {"selection": {"status": "synthetic"}}},
    ]
    from curio.media.selection_metrics import MediaMetricsInput
    metrics.visual_plan(tuple(TimelineSpan(i, 2, (i - 1) * 2, i * 2)
                              for i in range(1, 4)),
                        MediaMetricsInput.from_persisted_rows(scenes), 2)
    pipeline = metrics.to_dict({}, {}, "metrics")["pipeline"]

    assert pipeline["visual_timeline_assets_unique"] == 2  # real + synthetic
    assert pipeline["visual_timeline_assets_reused_across_scenes"] == 1
    assert pipeline["visual_assets_unique"] == pipeline["visual_timeline_assets_unique"]
    assert pipeline["visual_assets_reused"] == pipeline[
        "visual_timeline_assets_reused_across_scenes"]
    assert pipeline["visual_report"]["unique_assets"] == 1  # real media only
    assert pipeline["visual_report"]["reuse_count"] == 1


def test_media_metrics_distinguish_download_shortlist_from_final_scene_assets():
    metrics = RunMetrics("test", "black holes", "ai")
    from curio.media.selection_metrics import MediaMetricsInput
    metrics.media_shortlist_ids.update({"candidate-a", "candidate-b"})
    selected = {"provider": "wikimedia", "asset_id": "content-a"}
    metrics.visual_plan(
        (TimelineSpan(1, 2, 0, 2),),
        MediaMetricsInput.from_persisted_rows([{
            "chapter_id": 1, "asset": selected,
            "assets": [{"asset": selected}],
            "visual_decision": {"selection": {"status": "real"}}}]),
        2,
    )
    media = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]

    assert media["shortlist_assets_unique"] == 2
    assert media["selected_unique"] == media["shortlist_assets_unique"]
    assert media["real_scene_assets_unique"] == 1
    assert media["real_scene_asset_occurrences"] == 1


def test_consumption_selection_totals_share_canonical_scene_statistics():
    from curio.media.selection_metrics import MediaMetricsInput

    real = {"provider": "wikimedia", "asset_id": "asset-a"}
    synthetic = {"provider": "synth", "asset_id": "card"}
    rows = [
        {"chapter_id": 1, "asset": real,
         "visual_decision": {"selection": {"status": "real"}}},
        {"chapter_id": 2, "asset": real, "reused_from": 1,
         "visual_decision": {"selection": {"status": "reused"}}},
        {"chapter_id": 3, "asset": synthetic,
         "visual_decision": {"selection": {"status": "synthetic"}}},
        {"chapter_id": 4,
         "visual_decision": {"selection": {"status": "none"}}},
        {"chapter_id": 5},
    ]
    metrics = RunMetrics("test", "topic", "narration")
    metrics.visual_plan(
        tuple(TimelineSpan(i, 2, (i - 1) * 2, i * 2) for i in range(1, 6)),
        MediaMetricsInput.from_persisted_rows(rows), 2)

    media = metrics.to_dict({"media": rows}, {}, "metrics")["consumption"]["media"]

    assert media["scenes_with_real_asset"] == 2
    assert media["scenes_with_selected_visual"] == 3
    assert media["unique_assets"] == 1
    assert media["real_asset_occurrences"] == 2
    assert media["reused_assets"] == 1
    assert media["reuse_count"] == 1
    assert media["unique_asset_ratio"] == 0.5
    assert media["scenes_with_new_asset"] == 1
    assert media["scenes_with_reused_asset"] == 1
    assert media["synthetic_scenes"] == 1
    assert media["scenes_without_visual"] == 1
    assert media["scenes_with_unknown_decision"] == 1
    assert media["assets"] == media["scenes_with_selected_visual"]
    assert media["fallbacks"] == media["scenes_without_visual"]
    assert media["reused"] == media["scenes_with_reused_asset"]


def test_selection_metrics_are_unknown_until_visual_selection_is_projected():
    metrics = RunMetrics("test", "topic", "narration")

    media = metrics.to_dict({"media": [{"chapter_id": 1, "asset": {}}]}, {},
                            "metrics")["consumption"]["media"]

    assert media["assets"] is None
    assert media["fallbacks"] is None
    assert media["reused"] is None
    assert media["unique_assets"] is None


def test_synthetic_asset_metric_has_a_canonical_name_and_public_alias():
    metrics = RunMetrics("test", "topic", "narration")
    metrics.media_record_synthetic_asset()

    media = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]

    assert media["synthetic_assets"] == 1
    assert media["synth_diagrams"] == media["synthetic_assets"]


def test_download_and_shared_search_cache_metrics_have_explicit_units():
    metrics = RunMetrics("test", "topic", "narration")
    metrics.media_download(0, cached=True)
    metrics.media_download(512, cached=False)
    metrics.media_record_funnel("shared_search_hits", 2)

    media = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]

    assert media["download_cache_hits"] == 1
    assert media["download_cache_misses"] == 1
    assert media["shared_search_cache_hits"] == 2
    assert media["cache_hits"] == media["download_cache_hits"]
    assert media["cache_misses"] == media["download_cache_misses"]


def test_live_media_result_uses_typed_metrics_input_and_missing_scene_is_unknown():
    import pytest
    from curio.media.selection_metrics import MediaMetricsInput
    from curio.media.selection_result import MediaStageResult
    from curio.stages.scene_contract import TimelineSpan

    selected = {"provider": "wikimedia", "asset_id": "asset-1"}
    result = MediaStageResult.from_rows([{
        "chapter_id": 1, "asset": selected,
        "assets": [{"asset": selected}],
        "visual_decision": {"selection": {
            "scene_id": 1, "status": "real", "asset_id": "asset-1",
            "provider": "wikimedia", "reason": "specific visual"}},
    }], "provider")
    assert result.scenes[0].decision.fallback_level == "unknown"
    metrics = RunMetrics("test", "topic", "ai")
    with pytest.raises(TypeError, match="MediaMetricsInput"):
        metrics.visual_plan((TimelineSpan(1, 2, 0, 2),), [], 2)

    metrics.visual_plan(
        (TimelineSpan(1, 2, 0, 2), TimelineSpan(2, 2, 2, 4)),
        MediaMetricsInput.from_result(result), 2)
    report = metrics.media_visual_report(2)
    assert report["unique_assets"] == 1
    assert report["scenes_with_unknown_decision"] == 1


def test_unknown_persisted_media_does_not_become_zero_statistics():
    from curio.media.selection_metrics import MediaMetricsInput, MediaSelectionStats

    stats = MediaSelectionStats.from_input(
        MediaMetricsInput.from_persisted_rows(None, known=False))

    assert stats.unique_assets is None
    assert stats.scenes_without_visual is None


def test_unknown_persisted_selection_status_stays_unknown():
    from curio.media.selection_metrics import MediaMetricsInput, MediaSelectionStats

    metrics = MediaMetricsInput.from_persisted_rows([{
        "chapter_id": 1,
        "visual_decision": {"selection": {"status": ["invalid"]}},
    }])
    stats = MediaSelectionStats.from_input(metrics)

    assert stats.scenes_with_unknown_decision == 1
    assert stats.scenes_without_visual == 0
