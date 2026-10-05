from curio.metrics import RunMetrics
from curio.stages.visual import _submit_search
from curio.stages.scene_contract import TimelineSpan


def test_search_counters_are_distinct_logical_calls_requests_and_retries():
    metrics = RunMetrics("test", "idea", "ai")

    # Legacy output name aliases one mutable provider-request counter.
    metrics.media_search("wikimedia")
    assert metrics.media_searches is metrics.media_requests_per_provider
    assert metrics.media_searches == {"wikimedia": 1}

    metrics.media_record_retry("wikimedia")
    assert metrics.media_retries == 1
    assert metrics.media_retries_by_provider == {"wikimedia": 1}


def test_provider_search_timing_measures_one_adapter_call():
    metrics = RunMetrics("test", "idea", "ai")

    class Provider:
        name = "fixture"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            return []

    assert _submit_search(Provider(), "query", metrics).result(timeout=2) == []
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
