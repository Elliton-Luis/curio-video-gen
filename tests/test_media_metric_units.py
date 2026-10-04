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
    metrics.visual_plan(tuple(TimelineSpan(i, 2, (i - 1) * 2, i * 2)
                              for i in range(1, 4)), scenes, 2)
    pipeline = metrics.to_dict({}, {}, "metrics")["pipeline"]

    assert pipeline["visual_timeline_assets_unique"] == 2  # real + synthetic
    assert pipeline["visual_timeline_assets_reused_across_scenes"] == 1
    assert pipeline["visual_assets_unique"] == pipeline["visual_timeline_assets_unique"]
    assert pipeline["visual_assets_reused"] == pipeline[
        "visual_timeline_assets_reused_across_scenes"]
    assert pipeline["visual_report"]["unique_assets"] == 1  # real media only
    assert pipeline["visual_report"]["reuse_count"] == 1
