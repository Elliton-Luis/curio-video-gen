from curio.metrics import RunMetrics
from curio.stages.visual import _submit_search


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
