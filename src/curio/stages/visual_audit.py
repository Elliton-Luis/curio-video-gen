"""Own query provenance and project visual search/evaluation audit rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from math import isfinite
from typing import TYPE_CHECKING

from ..media.selection_result import SelectedAsset
from .media_contracts import CandidateEvaluation, CandidateRejection
from .scene_contract import SemanticScene
from .visual_contracts import SearchPlan, SearchQuery, VisualPlan

if TYPE_CHECKING:
    from ..media.selection_result import SelectedAsset
    from ..media.visual_decision import VisualDecision
    from .media_selection import SelectionDecision, SelectionProvenance
    from .scene_candidate_search import SceneCandidateCollection
    from .visual_contracts import VisualFallbackPlan


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
               visual_plan: VisualPlan) -> dict:
        outcome = ("duplicates_only" if self.duplicates_only else
                   "rejected" if self.rejected else
                   "eligible" if self.eligible else "empty_or_unavailable")
        status = ("not_consulted_budget_exhausted"
                  if self.unexecuted_reason == "scene_candidate_budget" else
                  "not_consulted" if self.unexecuted_reason else
                  "abandoned_duplicates" if self.duplicates_only else
                  "consulted" if self.providers else "no_provider_results")
        matching_representations = [
            representation.query for representation in visual_plan.representations
            if representation.query.casefold() in query.query.casefold()]
        representation_kinds = {representation.query: representation.kind
                                for representation in visual_plan.representations}
        aliases = [alias.value for alias in visual_plan.aliases]
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
        rejected: list[dict], visual_plan: VisualPlan) -> list[dict]:
    """Project query states in SearchPlan order, preserving their provenance."""
    if not isinstance(plan, SearchPlan):
        raise TypeError("query audit requires a SearchPlan")
    if not isinstance(visual_plan, VisualPlan):
        raise TypeError("query audit requires a VisualPlan")
    if plan.scene_id != visual_plan.scene_id:
        raise ValueError("query audit plans must belong to the same scene")
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
        visual_plan=visual_plan,
    ) for query in plan.queries]


def candidate_audit_rows(
    evaluations: tuple[CandidateEvaluation, ...],
    rejected: list[dict],
    picked: tuple[SelectedAsset, ...],
    visual_plan: VisualPlan,
    min_score: float,
    technical_rejections: tuple[CandidateRejection, ...] = (),
) -> list[dict]:
    """Project evaluation outcomes without changing selection or candidates."""
    if not isinstance(visual_plan, VisualPlan):
        raise TypeError("candidate audit requires a VisualPlan")
    if not isinstance(evaluations, tuple) or any(
            not isinstance(item, CandidateEvaluation) for item in evaluations):
        raise TypeError("candidate audit requires CandidateEvaluation values")
    if not isinstance(picked, tuple) or any(
            not isinstance(item, SelectedAsset) for item in picked):
        raise TypeError("candidate audit requires selected asset values")
    if not isinstance(rejected, list) or any(
            not isinstance(item, dict) for item in rejected):
        raise TypeError("candidate audit technical rejections must be rows")
    if not isinstance(technical_rejections, tuple) or any(
            not isinstance(item, CandidateRejection)
            for item in technical_rejections):
        raise TypeError("candidate audit requires typed technical rejections")
    representation_levels = {rep.query: rep.level
                             for rep in visual_plan.representations}
    rows = []
    for evaluation in evaluations:
        candidate = evaluation.candidate
        asset = candidate.asset
        detail = evaluation.evidence_dict()
        lifecycle_rejection = next((item for item in rejected
            if item.get("identity") == candidate.identity), None)
        technical_rejection = next((item for item in technical_rejections
            if item.candidate.identity == candidate.identity), None)
        selected_item = next((item for item in picked
            if (item.asset.provider, item.asset.asset_id) ==
               (asset.provider, asset.asset_id)), None)
        was_selected = selected_item is not None
        score = evaluation.score
        semantic_rejection = detail.get("semantic_rejection")
        is_rejected = bool(evaluation.rejection_reason or semantic_rejection
                           or lifecycle_rejection or technical_rejection
                           or score < min_score)
        if was_selected:
            reason = ("reused only after fresh searches and local visual exhausted"
                      if selected_item.reuse_reason else
                      "selected by scene relevance, topic relevance, then quality")
            decision = "selected"
        else:
            reason = (evaluation.rejection_reason or semantic_rejection or
                      (technical_rejection.reason if technical_rejection else "") or
                      ((lifecycle_rejection or {}).get("audit_reason")
                       or (lifecycle_rejection or {}).get("reason")) or
                      ("score below threshold" if score < min_score else
                       "passed gate; ranked below image limit"))
            decision = "rejected" if is_rejected else "not_selected"
        rows.append({
            "title": asset.title[:160],
            "provider": asset.provider,
            "query": candidate.search_query.query,
            "query_level": representation_levels.get(
                candidate.search_query.query,
                5 if candidate.search_query.generic else 3),
            "topic_relevance": detail.get("topic_relevance"),
            "scene_relevance": detail.get("scene_relevance"),
            "score": score,
            "bonus": detail.get("bonus", 0),
            "clip_score": detail.get("clip"),
            "creator": asset.author[:120],
            "source_url": asset.source_url[:300],
            "date_created": asset.date_created,
            "media_type": asset.media_type or "image",
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
    rows.extend({
        "title": item.candidate.asset.title,
        "provider": item.candidate.asset.provider,
        "query": item.candidate.search_query.query,
        "topic_relevance": item.evidence.get("topic_relevance"),
        "scene_relevance": item.evidence.get("scene_relevance"),
        "creator": item.candidate.asset.author[:120],
        "source_url": item.candidate.asset.source_url[:300],
        "date_created": item.candidate.asset.date_created,
        "media_type": item.candidate.asset.media_type or "image",
        "decision": "rejected",
        "reason": item.reason,
    } for item in technical_rejections if not any(
        row["title"] == item.candidate.asset.title for row in rows))
    return rows[:40]


def build_scene_visual_decision(*, selection: "SelectionDecision",
                                selection_provenance: "SelectionProvenance",
                                scene: SemanticScene, visual_plan: VisualPlan,
                                search_plan: SearchPlan,
                                collection: "SceneCandidateCollection",
                                evaluations: tuple[CandidateEvaluation, ...],
                                rejected: list[dict],
                                technical_rejections: tuple[CandidateRejection, ...],
                                picked: tuple["SelectedAsset", ...],
                                min_score: float,
                                fallback_plan: "VisualFallbackPlan | None",
                                strategy: str) -> "VisualDecision":
    """Assemble the persisted decision from typed stage outputs and audit facts."""
    from ..media.selection_result import SelectedAsset
    from ..media.visual_decision import VisualDecision
    from ..stages.media_selection import (SelectionDecision,
                                          SelectionProvenance)
    from ..stages.scene_candidate_search import SceneCandidateCollection
    from ..stages.visual_contracts import VisualFallbackPlan

    if not isinstance(selection, SelectionDecision):
        raise TypeError("visual audit requires SelectionDecision")
    if not isinstance(selection_provenance, SelectionProvenance):
        raise TypeError("visual audit requires SelectionProvenance")
    if not isinstance(scene, SemanticScene):
        raise TypeError("visual audit requires SemanticScene")
    if not isinstance(visual_plan, VisualPlan) or not isinstance(search_plan, SearchPlan):
        raise TypeError("visual audit requires VisualPlan and SearchPlan")
    if (scene.id != visual_plan.scene_id or scene.id != search_plan.scene_id
            or scene.id != selection.scene_id):
        raise ValueError("visual audit inputs must belong to the same scene")
    if not isinstance(collection, SceneCandidateCollection):
        raise TypeError("visual audit requires SceneCandidateCollection")
    if set(collection.planned_queries) != {
            query.query for query in search_plan.queries}:
        raise ValueError("visual audit collection must match SearchPlan")
    if (not isinstance(picked, tuple)
            or any(not isinstance(item, SelectedAsset) for item in picked)):
        raise TypeError("visual audit requires selected asset values")
    if (not isinstance(evaluations, tuple)
            or any(not isinstance(item, CandidateEvaluation)
                   for item in evaluations)
            or not isinstance(rejected, list)
            or any(not isinstance(item, dict) for item in rejected)
            or not isinstance(technical_rejections, tuple)
            or any(not isinstance(item, CandidateRejection)
                   for item in technical_rejections)):
        raise TypeError("visual audit requires typed evaluations/rejections")
    if (isinstance(min_score, bool) or not isinstance(min_score, (int, float))
            or not isfinite(min_score) or not 0 <= min_score <= 100):
        raise ValueError("visual audit minimum score must be within 0..100")
    if bool(picked) == (selection.status == "none"):
        raise ValueError("visual audit selection state differs from picked assets")
    if picked and (selection.asset_id != picked[0].asset.asset_id
                   or selection.provider != picked[0].asset.provider):
        raise ValueError("visual audit selected asset differs from SelectionDecision")
    if (selection_provenance.fallback_level != selection.fallback_level
            or not isinstance(strategy, str) or not strategy.strip()):
        raise ValueError("visual audit selection provenance is inconsistent")
    if fallback_plan is not None and not isinstance(fallback_plan, VisualFallbackPlan):
        raise TypeError("visual audit fallback plan must be VisualFallbackPlan or null")
    if fallback_plan is not None and fallback_plan.scene_id != scene.id:
        raise ValueError("visual audit fallback plan belongs to another scene")

    candidates = candidate_audit_rows(
        evaluations, rejected, picked, visual_plan, min_score,
        technical_rejections)
    query_rejections = [*rejected,
                        *(item.to_dict() for item in technical_rejections)]
    first = picked[0] if picked else None
    synthetic = bool(first and first.asset.provider == "synth")
    selected = next((item for item in candidates
                     if item["decision"] == "selected"), None)
    if selected is None and synthetic:
        selected = {
            "title": first.asset.title,
            "provider": first.asset.provider,
            "reason": "No candidate passed semantic gates; rendered safe local visual",
        }
    entities = list(dict.fromkeys([
        str(scene.primary_entity or ""), str(scene.event or ""),
        *(str(item) for item in scene.visual_entities),
        *(str(item) for item in scene.context),
    ]))[:12]
    return VisualDecision.create(
        selection,
        topic=visual_plan.topic,
        visual_plan=visual_plan.to_dict(),
        fallback_plan=(fallback_plan.to_dict() if synthetic else None),
        search_plan=search_plan.to_dict(),
        visual_intent=(scene.visual_intent_structured or scene.visual_intent),
        entities=entities,
        primary_entity=scene.primary_entity or scene.subject,
        representations=[rep.to_dict() for rep in visual_plan.representations],
        representations_discarded=list(scene.representation_rejections),
        aliases=[alias.value for alias in visual_plan.aliases],
        queries=search_query_audit_rows(
            search_plan, collection.query_audit, query_rejections, visual_plan),
        providers_consulted=list(collection.providers_consulted),
        candidates=candidates,
        selected=selected,
        fallback=strategy if synthetic or not picked else "",
        search_exhausted=selection_provenance.search_exhausted,
        search_exhaustion_reason=selection_provenance.search_exhaustion_reason,
        fallback_level=selection_provenance.fallback_level,
    )
