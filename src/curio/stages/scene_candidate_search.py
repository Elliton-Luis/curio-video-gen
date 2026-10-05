"""Collect provider candidates and apply technical eligibility gates per scene."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..config import CurioConfig
from ..media.providers import MediaAsset, MediaProvider, classify_rights
from . import media_rules, media_search
from .media_contracts import Candidate, CandidateRejection
from .media_provider_policy import ordered_providers
from .visual_audit import QueryAuditAccumulator, SearchQueryAudit
from .visual_contracts import SearchPlan, VisualPlan


@dataclass(frozen=True)
class SceneCandidateCollection:
    """Snapshot of candidates and provenance collected for one scene."""

    candidates: tuple[Candidate, ...]
    rejected: tuple[CandidateRejection, ...]
    providers_consulted: tuple[str, ...]
    query_audit: Mapping[str, SearchQueryAudit]
    planned_queries: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not isinstance(self.rejected, tuple):
            raise TypeError("candidate collection members must be immutable tuples")
        if any(not isinstance(item, Candidate) for item in self.candidates):
            raise TypeError("candidate collection requires Candidate values")
        if any(not isinstance(item, CandidateRejection) for item in self.rejected):
            raise TypeError("candidate collection requires CandidateRejection values")
        if (not isinstance(self.providers_consulted, tuple)
                or any(not isinstance(item, str) or not item.strip()
                       for item in self.providers_consulted)):
            raise TypeError("candidate collection providers must be named")
        if not isinstance(self.query_audit, Mapping):
            raise TypeError("candidate collection query audit must be an object")
        if (not isinstance(self.planned_queries, tuple)
                or any(not isinstance(query, str) or not query.strip()
                for query in self.planned_queries)
                or len(self.planned_queries) != len({
                    query.casefold() for query in self.planned_queries})):
            raise ValueError("candidate collection planned queries must be unique")
        if len(self.providers_consulted) != len(set(self.providers_consulted)):
            raise ValueError("candidate collection providers must be unique")
        if set(self.query_audit) != set(self.planned_queries):
            raise ValueError("candidate collection must audit every planned query")
        if any(not isinstance(item, SearchQueryAudit)
               for item in self.query_audit.values()):
            raise TypeError("candidate collection audit must use immutable SearchQueryAudit")
        object.__setattr__(self, "query_audit",
                           MappingProxyType(dict(self.query_audit)))
        all_candidates = (*self.candidates,
                          *(item.candidate for item in self.rejected))
        if any(item.search_query.query not in self.query_audit
               for item in all_candidates):
            raise ValueError("candidate query must belong to the collection plan")
        identities = [item.identity for item in all_candidates]
        if len(identities) != len(set(identities)):
            raise ValueError("candidate collection identities must be unique")


class SceneCandidateCollector:
    """Own provider traversal, cross-provider dedupe and technical gates.

    Query planning, semantic ranking, fallback, and final selection remain
    outside this collector. The same instance collects specific and late
    generic query batches so identity and budget are scene-wide.
    """

    def __init__(self, scene, visual_plan: VisualPlan, search_plan: SearchPlan,
                 providers: list[MediaProvider], cfg: CurioConfig, metrics,
                 blocked: list[str], genre: str = "",
                 shared_search_cache: dict | None = None,
                 max_candidates: int = 20):
        if not isinstance(visual_plan, VisualPlan):
            raise TypeError("candidate collection requires a VisualPlan")
        if not isinstance(search_plan, SearchPlan):
            raise TypeError("candidate collection requires a SearchPlan")
        if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) \
                or max_candidates <= 0:
            raise ValueError("candidate collection budget must be positive")
        self.scene = scene
        self.visual_plan = visual_plan
        self.search_plan = search_plan
        self.providers = providers
        self.cfg = cfg
        self.metrics = metrics
        self.blocked = blocked
        self.genre = genre
        self.shared_search_cache = shared_search_cache
        self.max_candidates = max_candidates
        self.candidates: list[Candidate] = []
        self.rejected: list[CandidateRejection] = []
        self.seen_ids: set[str] = set()
        self.providers_consulted: set[str] = set()
        self.query_audit = {
            query.query: QueryAuditAccumulator(
                unexecuted_reason=("tier_not_reached" if query.generic else ""))
            for query in search_plan.queries}
        self.search_query_by_text = {
            query.query: query for query in search_plan.queries}

    def collect(self, query_list: list[str], limit: int
                ) -> SceneCandidateCollection:
        """Collect a bounded query batch, keeping scene-wide identity state."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("query candidate limit must be positive")
        if any(query not in self.query_audit for query in query_list):
            raise ValueError("candidate query must belong to SearchPlan")
        for query_index, query in enumerate(query_list):
            if len(self.candidates) >= self.max_candidates:
                for pending in query_list[query_index:]:
                    self.query_audit[pending].mark_unexecuted(
                        "scene_candidate_budget")
                break
            self.query_audit[query].unexecuted_reason = ""
            candidates_before_query = len(self.candidates)
            query_key = query.casefold()
            identities_before = len(self.seen_ids)
            duplicates_before = self.query_audit[query].duplicates
            shared = (self.shared_search_cache.setdefault(query_key, {})
                      if self.shared_search_cache is not None else {})
            active = [provider for provider in self.providers
                      if not getattr(provider, "_disabled", False)]
            scene_order = [provider.name for provider in ordered_providers(
                self.cfg, self.visual_plan, self.genre, self.providers)]
            rank = {name: index for index, name in enumerate(scene_order)}
            active.sort(key=lambda provider: rank.get(provider.name, len(rank)))
            self.providers_consulted.update(provider.name for provider in active)
            self.query_audit[query].set_providers(
                [provider.name for provider in active])
            if self.metrics and active:
                self.metrics.media_queries_count += 1
            response_stream = media_search.search_providers(
                query, active,
                shared_results=(shared if self.shared_search_cache is not None
                                else None),
                metrics=self.metrics, timeout=media_search.SEARCH_TIMEOUT)
            try:
                for response in response_stream:
                    if response.query != query:
                        raise ValueError(
                            "provider response query does not match request")
                    if response.error:
                        self.query_audit[query].record_error(
                            response.provider, response.error)
                        continue
                    self.query_audit[query].record_result(
                        response.provider, len(response.assets))
                    for result_index, asset in enumerate(response.assets):
                        if (len(self.candidates) >= self.max_candidates
                                or len(self.candidates) - candidates_before_query
                                >= limit):
                            if self.metrics:
                                self.metrics.media_record_funnel(
                                    "budget_unexamined",
                                    len(response.assets) - result_index)
                            break
                        self._consider(asset, query)
                    if (len(self.candidates) >= self.max_candidates
                            or len(self.candidates) - candidates_before_query
                            >= limit):
                        break
            finally:
                response_stream.close()
            if (len(self.seen_ids) == identities_before
                    and self.query_audit[query].duplicates > duplicates_before):
                self.query_audit[query].mark_duplicates_only()
                if self.metrics:
                    self.metrics.media_duplicate_queries += 1
        return self.snapshot()

    def snapshot(self) -> SceneCandidateCollection:
        return SceneCandidateCollection(
            tuple(self.candidates), tuple(self.rejected),
            tuple(sorted(self.providers_consulted)),
            MappingProxyType({query: audit.snapshot()
                              for query, audit in self.query_audit.items()}),
            tuple(query.query for query in self.search_plan.queries))

    def _consider(self, asset: MediaAsset, query: str) -> None:
        dedupe_started = time.monotonic()
        source = (asset.source_url or "").split("?", 1)[0].rstrip("/").casefold()
        identity = (f"url:{source}" if source else
                    f"{asset.provider}:{asset.asset_id}")
        candidate = Candidate(asset, self.search_query_by_text[query], identity)
        if identity in self.seen_ids:
            self.query_audit[query].record_duplicate()
            if self.metrics:
                self.metrics.media_record_funnel("duplicates")
                self.metrics.media_deduplication_time += (
                    time.monotonic() - dedupe_started)
            return
        self.seen_ids.add(identity)
        if self.metrics:
            self.metrics.media_deduplication_time += (
                time.monotonic() - dedupe_started)
            self.metrics.media_record_funnel("unique_considered")
        reason = media_rules.asset_gate_reason(asset, self.blocked)
        if reason:
            self.query_audit[query].record_rejection()
            self.rejected.append(CandidateRejection(
                candidate, reason, "technical_gate"))
            if self.metrics:
                self.metrics.media_record_asset_rejected()
                self.metrics.media_record_funnel("hard_rejected")
                if classify_rights(asset.license or "", asset.provider) == "blocked":
                    self.metrics.media_record_rights("blocked")
            return
        if self.metrics:
            self.metrics.media_record_funnel("eligible")
        self.query_audit[query].record_eligible()
        self.candidates.append(candidate)
