import pytest

from curio.media.providers import MediaAsset, MediaError
from curio.metrics import RunMetrics
from curio.stages.media_search import ProviderSearchResult, search_providers


def test_provider_query_returns_normalized_responses_in_priority_order():
    class Provider:
        def __init__(self, name):
            self.name = name

        def search(self, query, limit, metrics):
            assert query == "Battle of Mohacs engraving"
            assert limit == 5
            return [MediaAsset(self.name, self.name, title="Engraving")]

    results = list(search_providers("Battle of Mohacs engraving", [
        Provider("wikimedia"), Provider("met")], timeout=1))

    assert [result.provider for result in results] == ["wikimedia", "met"]
    assert all(result.query == "Battle of Mohacs engraving" for result in results)
    assert all(isinstance(result, ProviderSearchResult) for result in results)
    assert [result.assets[0].provider for result in results] == ["wikimedia", "met"]


def test_query_response_cache_returns_assets_without_recalling_provider():
    class Provider:
        name = "wikimedia"
        calls = 0

        def search(self, *_args):
            self.calls += 1
            return [MediaAsset(self.name, "mohacs", title="Battle engraving")]

    provider = Provider()
    cache = {}
    first = list(search_providers("Battle of Mohacs", [provider],
                                  shared_results=cache, timeout=1))
    second = list(search_providers("Battle of Mohacs", [provider],
                                   shared_results=cache, timeout=1))

    assert provider.calls == 1
    assert first[0].cache_hit is False
    assert second[0].cache_hit is True
    assert second[0].query == "Battle of Mohacs"
    assert second[0].assets[0].asset_id == "mohacs"


def test_provider_error_is_returned_as_transport_result():
    class Provider:
        name = "met"

        def search(self, *_args):
            raise MediaError("met: unavailable")

    result, = search_providers("Battle of Mohacs", [Provider()], timeout=1)

    assert result.provider == "met"
    assert result.error == "met: unavailable"
    assert result.assets == ()


@pytest.mark.parametrize(("error", "reason"), [
    ("429 Too Many Requests", "rate_limited"),
    ("403 Forbidden", "access_denied"),
])
def test_provider_disablement_is_not_counted_as_timeout(monkeypatch, error, reason):
    class Provider:
        name = "met"
        _disabled = False

        def search(self, *_args):
            raise MediaError(error)

    monkeypatch.setattr("curio.runlog.event", lambda *args, **kwargs: True)
    provider = Provider()
    metrics = RunMetrics("test", "topic", "narration")

    result, = search_providers("a query", [provider], metrics=metrics, timeout=1)
    report = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]

    assert result.error == error
    assert provider._disabled is True
    assert report["timeouts"] == 0
    assert report["timeouts_by_provider"] == {}
    assert report["disabled_providers"] == {"met": {reason: 1}}


def test_actual_search_timeout_is_counted_for_its_provider():
    import time

    class Provider:
        name = "wikimedia"

        def search(self, *_args):
            time.sleep(0.04)
            return []

    metrics = RunMetrics("test", "topic", "narration")
    result, = search_providers("a query", [Provider()], metrics=metrics,
                              timeout=0.001)
    report = metrics.to_dict({}, {}, "metrics")["consumption"]["media"]

    assert result.error == "timeout"
    assert report["timeouts"] == 1
    assert report["timeouts_by_provider"] == {"wikimedia": 1}


def test_provider_response_rejects_assets_and_error_together():
    asset = MediaAsset("met", "1", title="Work")

    with pytest.raises(ValueError, match="cannot contain assets and error"):
        ProviderSearchResult("query", "met", (asset,), error="failed")
