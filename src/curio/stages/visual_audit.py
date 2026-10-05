"""Own query provenance and project visual search/evaluation audit rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping

from .visual_contracts import SearchPlan, SearchQuery


@dataclass
class QueryAuditAccumulator:
    """Mutable facts collected for one query inside the acquisition owner."""

    results: int = 0
    duplicates: int = 0
    rejected: int = 0
    eligible: int = 0
    providers: list[str] = field(default_factory=list)
    results_by_provider: dict[str, int] = field(default_factory=dict)
    provider_errors: dict[str, str] = field(default_factory=dict)
    unavailable: bool = False
    duplicates_only: bool = False
    unexecuted_reason: str = ""

    def set_providers(self, providers: list[str]) -> None:
        self.providers = list(providers)
        self.unavailable = not self.providers

    def record_result(self, provider: str, count: int) -> None:
        if count < 0:
            raise ValueError("provider result count cannot be negative")
        self.results += count
        self.results_by_provider[provider] = (
            self.results_by_provider.get(provider, 0) + count)

    def record_error(self, provider: str, error: str) -> None:
        self.provider_errors[provider] = error

    def record_duplicate(self) -> None:
        self.duplicates += 1

    def record_rejection(self) -> None:
        self.rejected += 1

    def record_eligible(self) -> None:
        self.eligible += 1

    def mark_duplicates_only(self) -> None:
        self.duplicates_only = True

    def mark_unexecuted(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("unexecuted query requires a reason")
        self.unexecuted_reason = reason

    def snapshot(self) -> "SearchQueryAudit":
        """Freeze the collected facts before exposing them to another stage."""
        return SearchQueryAudit(
            results=self.results, duplicates=self.duplicates,
            rejected=self.rejected, eligible=self.eligible,
            providers=tuple(self.providers),
            results_by_provider=tuple(self.results_by_provider.items()),
            provider_errors=tuple(self.provider_errors.items()),
            unavailable=self.unavailable,
            duplicates_only=self.duplicates_only,
            unexecuted_reason=self.unexecuted_reason)


@dataclass(frozen=True)
class SearchQueryAudit:
    """Immutable query facts emitted by candidate collection."""

    results: int = 0
    duplicates: int = 0
    rejected: int = 0
    eligible: int = 0
    providers: tuple[str, ...] = ()
    results_by_provider: tuple[tuple[str, int], ...] = ()
    provider_errors: tuple[tuple[str, str], ...] = ()
    unavailable: bool = False
    duplicates_only: bool = False
    unexecuted_reason: str = ""

    def __post_init__(self) -> None:
        for name in ("results", "duplicates", "rejected", "eligible"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"query audit {name} must be a nonnegative integer")
        if not isinstance(self.providers, tuple) or any(
                not isinstance(provider, str) or not provider.strip()
                for provider in self.providers):
            raise TypeError("query audit providers must be immutable names")
        if len(self.providers) != len(set(self.providers)):
            raise ValueError("query audit providers must be unique")
        for name in ("results_by_provider", "provider_errors"):
            items = getattr(self, name)
            if not isinstance(items, tuple) or any(
                    not isinstance(item, tuple) or len(item) != 2
                    or not isinstance(item[0], str) for item in items):
                raise TypeError(f"query audit {name} must be immutable pairs")
        if any(isinstance(count, bool) or not isinstance(count, int) or count < 0
               for _provider, count in self.results_by_provider):
            raise ValueError("query audit provider result counts must be nonnegative")
        if any(not isinstance(error, str)
               for _provider, error in self.provider_errors):
            raise TypeError("query audit provider errors must be text")
        if not isinstance(self.unavailable, bool) or not isinstance(
                self.duplicates_only, bool):
            raise TypeError("query audit flags must be boolean")
        if not isinstance(self.unexecuted_reason, str):
            raise TypeError("query audit unexecuted reason must be text")

    def to_row(self, query: SearchQuery, *, rejected_candidates_total: int,
               representations: list[str], representation_kinds: dict[str, str],
               aliases: list[object]) -> dict:
        outcome = ("duplicates_only" if self.duplicates_only else
                   "rejected" if self.rejected else
                   "eligible" if self.eligible else "empty_or_unavailable")
        status = ("not_consulted_budget_exhausted"
                  if self.unexecuted_reason == "scene_candidate_budget" else
                  "abandoned_duplicates" if self.duplicates_only else
                  "consulted" if self.providers else "no_provider_results")
        matching_representations = [
            representation for representation in representations
            if representation.casefold() in query.query.casefold()]
        return {
            "query": query.query,
            "source": query.source,
            "representation": query.representation,
            "representation_kind": query.representation_kind,
            "alias": query.alias,
            "query_variant": query.variant,
            "level": query.level,
            "generic": query.generic,
            "providers": list(self.providers),
            "provider_errors": dict(self.provider_errors),
            "results": self.results,
            "results_by_provider": dict(self.results_by_provider),
            "duplicates": self.duplicates,
            "eligible_candidates": self.eligible,
            "rejected_candidates_total": rejected_candidates_total,
            "outcome": outcome,
            "representations": matching_representations,
            "representation_kinds": {
                representation: representation_kinds[representation]
                for representation in matching_representations
                if representation in representation_kinds},
            "aliases_used": [alias for alias in aliases
                             if str(alias).casefold() in query.query.casefold()],
            "status": status,
            "unexecuted_reason": self.unexecuted_reason,
        }


def search_query_audit_rows(
        plan: SearchPlan, states: Mapping[str, SearchQueryAudit],
        rejected: list[dict], representation_levels: dict[str, int],
        representation_kinds: dict[str, str], aliases: list[object]) -> list[dict]:
    """Project query states in SearchPlan order, preserving their provenance."""
    if not isinstance(plan, SearchPlan):
        raise TypeError("query audit requires a SearchPlan")
    if not isinstance(states, Mapping) or any(
            not isinstance(state, SearchQueryAudit) for state in states.values()):
        raise TypeError("query audit projection requires immutable audit states")
    planned_queries = {query.query for query in plan.queries}
    if set(states) != planned_queries:
        raise ValueError("query audit states must match SearchPlan queries")
    return [states[query.query].to_row(
        query,
        rejected_candidates_total=sum(
            item.get("query") == query.query for item in rejected),
        representations=list(representation_levels),
        representation_kinds=representation_kinds,
        aliases=aliases,
    ) for query in plan.queries]


def candidate_audit_rows(
    evaluated_entries: list[dict],
    rejected: list[dict],
    picked: list[dict],
    representation_levels: dict[str, int],
    min_score: float,
) -> list[dict]:
    """Project evaluation outcomes without changing selection or candidates."""
    rows = []
    for entry in evaluated_entries:
        detail = entry.get("score_detail", {})
        asset_data = entry.get("asset") or {}
        lifecycle_rejection = next((item for item in rejected
            if entry.get("identity")
            and item.get("identity") == entry.get("identity")), None)
        selected_item = next((item for item in picked
            if (item.get("asset", {}).get("provider"),
                item.get("asset", {}).get("asset_id")) ==
               (asset_data.get("provider"), asset_data.get("asset_id"))), None)
        was_selected = selected_item is not None
        score = entry.get("score", 0)
        semantic_rejection = detail.get("semantic_rejection")
        is_rejected = bool(entry.get("rejection_reason") or semantic_rejection
                           or lifecycle_rejection or score < min_score)
        if was_selected:
            reason = ("reused only after fresh searches and local visual exhausted"
                      if selected_item.get("reuse_reason") else
                      "selected by scene relevance, topic relevance, then quality")
            decision = "selected"
        else:
            reason = (entry.get("rejection_reason") or semantic_rejection or
                      ((lifecycle_rejection or {}).get("audit_reason")
                       or (lifecycle_rejection or {}).get("reason")) or
                      ("score below threshold" if score < min_score else
                       "passed gate; ranked below image limit"))
            decision = "rejected" if is_rejected else "not_selected"
        rows.append({
            "title": str(asset_data.get("title", ""))[:160],
            "provider": asset_data.get("provider", ""),
            "query": entry.get("query", ""),
            "query_level": representation_levels.get(
                entry.get("query", ""), 5 if entry.get("generic") else 3),
            "topic_relevance": detail.get("topic_relevance"),
            "scene_relevance": detail.get("scene_relevance"),
            "score": score,
            "bonus": detail.get("bonus", 0),
            "clip_score": entry.get("clip_score"),
            "creator": str(asset_data.get("author", ""))[:120],
            "source_url": str(asset_data.get("source_url", ""))[:300],
            "date_created": asset_data.get("date_created", ""),
            "media_type": asset_data.get("media_type", "image"),
            "metadata_support": detail.get("metadata_support", 0.0),
            "topic_evidence": detail.get("topic_evidence", {}),
            "scene_evidence": detail.get("scene_evidence", {}),
            "decision": decision,
            "reason": reason,
        })

    rows.extend({
        "title": item.get("title", ""),
        "provider": item.get("provider", ""),
        "query": item.get("query", ""),
        "topic_relevance": item.get("topic_relevance"),
        "scene_relevance": item.get("scene_relevance"),
        "creator": str((item.get("asset") or {}).get("author", ""))[:120],
        "source_url": str((item.get("asset") or {}).get("source_url", ""))[:300],
        "date_created": (item.get("asset") or {}).get("date_created", ""),
        "media_type": (item.get("asset") or {}).get("media_type", "image"),
        "decision": "rejected",
        "reason": item.get("reason", ""),
    } for item in rejected if not any(
        row["title"] == item.get("title") for row in rows))
    return rows[:40]
