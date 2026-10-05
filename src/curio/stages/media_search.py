"""Provider query execution and response normalization boundary.

This module runs provider requests and returns their normalized results and
errors in priority order. It has no access to scenes or editorial relevance.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import os
import time
from dataclasses import dataclass

from ..media.providers import MediaAsset, MediaError, MediaProvider


MAX_CONCURRENT_SEARCHES = int(
    os.environ.get("CURIO_MAX_CONCURRENT_SEARCHES", "3"))
SEARCH_TIMEOUT = float(os.environ.get("CURIO_MEDIA_SEARCH_TIMEOUT", "15.0"))
_SEARCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, MAX_CONCURRENT_SEARCHES), thread_name_prefix="curio-search")


@dataclass(frozen=True)
class ProviderSearchResult:
    """One provider's normalized response for a single query."""

    query: str
    provider: str
    assets: tuple[MediaAsset, ...] = ()
    error: str = ""
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if not self.query.strip() or not self.provider.strip():
            raise ValueError("provider response requires query and provider")
        if self.error and self.assets:
            raise ValueError("provider response cannot contain assets and error")


def submit_search(provider: MediaProvider, query: str, metrics=None):
    """Submit one provider request, preserving run-log context in worker."""
    context = contextvars.copy_context()

    def timed_search():
        started = time.monotonic()
        try:
            return provider.search(query, 5, metrics)
        finally:
            if metrics:
                metrics.media_provider_search(
                    provider.name, time.monotonic() - started)

    return _SEARCH_EXECUTOR.submit(context.run, timed_search)


def search_with_timeout(provider: MediaProvider, query: str, timeout: float,
                        metrics=None) -> list[MediaAsset]:
    """Wait for one provider request without blocking on executor shutdown."""
    future = submit_search(provider, query, metrics)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        if metrics:
            metrics.media_record_timeout()
        raise MediaError(f"{provider.name}: busca timeout ({timeout}s)") from exc


def search_providers(query: str, providers: list[MediaProvider], *,
                     shared_results: dict[str, list[dict]] | None = None,
                     metrics=None, timeout: float = SEARCH_TIMEOUT):
    """Yield normalized responses in supplied priority order.

    Requests run concurrently, but results are yielded in provider-priority
    order. A consumer may stop at its candidate budget; unfinished futures are
    cancelled when the iterator closes.
    """
    active = [provider for provider in providers
              if not getattr(provider, "_disabled", False)]
    cache_enabled = shared_results is not None
    shared_results = shared_results if cache_enabled else {}
    tasks = []
    for provider in active:
        if provider.name in shared_results:
            cached = tuple(MediaAsset.from_dict(item)
                           for item in shared_results[provider.name])
            tasks.append((provider, None, cached))
        else:
            tasks.append((provider, submit_search(provider, query, metrics), None))

    deadline = time.monotonic() + timeout
    try:
        for provider, future, cached in tasks:
            if cached is not None:
                if metrics:
                    metrics.media_record_funnel("shared_search_hits")
                yield ProviderSearchResult(query, provider.name, cached,
                                           cache_hit=True)
                continue
            try:
                remaining = max(0.0, deadline - time.monotonic())
                assets = tuple(future.result(timeout=remaining))
            except concurrent.futures.TimeoutError:
                future.cancel()
                if metrics:
                    metrics.media_record_timeout()
                yield ProviderSearchResult(query, provider.name, error="timeout")
                continue
            except MediaError as exc:
                error = str(exc)
                if (any(code in error for code in ("429", "401", "403"))
                        or "Too Many Requests" in error):
                    provider._disabled = True
                    if metrics:
                        metrics.media_record_timeout()
                    from ..runlog import event
                    logged = event("fallback",
                                   f"{provider.name}: provider desativado; {error}",
                                   operation="media_search", provider=provider.name,
                                   error=error)
                    if not logged:
                        import sys
                        print(f"AVISO: {provider.name} desativado nesta execução ({error})",
                              file=sys.stderr)
                yield ProviderSearchResult(query, provider.name, error=error)
                continue
            if cache_enabled:
                shared_results[provider.name] = [asset.to_dict() for asset in assets]
            if metrics:
                metrics.media_record_results(provider.name, len(assets))
                metrics.media_record_funnel("normalized_returned", len(assets))
            yield ProviderSearchResult(query, provider.name, assets)
    finally:
        for _provider, future, _cached in tasks:
            if future is not None and not future.done():
                future.cancel()
