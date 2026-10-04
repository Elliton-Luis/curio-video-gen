"""Research stage orchestration and persistence for the video pipeline."""

from __future__ import annotations

import time
import sys
from dataclasses import dataclass

from .runlog import event as run_event
from .stages import research as research_stage
from .stages.research import ResearchSource


@dataclass
class ResearchStageResult:
    result: research_stage.ResearchResult
    status: str
    prompt: str
    elapsed: float


def validate_research_result(result) -> research_stage.ResearchResult:
    """Reject partial producer output before it is registered or persisted."""
    if not isinstance(result, research_stage.ResearchResult):
        raise TypeError("research_topic must return ResearchResult")
    if result.target is not None and not hasattr(result.target, "to_dict"):
        raise TypeError("research result target must be a TargetEntity or null")
    if not isinstance(result.sources, list):
        raise TypeError("research result sources must be a list")
    for source in result.sources:
        if not isinstance(source, ResearchSource):
            raise TypeError("research result sources must be ResearchSource values")
        if (not isinstance(source.title, str) or not source.title.strip()
                or not isinstance(source.url, str) or not source.url.strip()):
            raise ValueError("accepted research source requires title and URL")
    if not isinstance(result.rejected, list):
        raise TypeError("research result rejected must be a list")
    for item in result.rejected:
        if (not isinstance(item, tuple) or len(item) != 3
                or not isinstance(item[0], ResearchSource)
                or not all(isinstance(value, str) for value in item[1:])):
            raise TypeError("rejected source must be (ResearchSource, reason, detail)")
    if (not isinstance(result.tried_queries, list)
            or any(not isinstance(query, str) or not query.strip()
                   for query in result.tried_queries)):
        raise TypeError("research tried_queries must be non-empty strings")
    if not isinstance(result.weak, bool):
        raise TypeError("research weak must be boolean")
    if (not isinstance(result.weak_warnings, list)
            or any(not isinstance(value, str) or not value.strip()
                   for value in result.weak_warnings)):
        raise TypeError("research weak_warnings must be non-empty strings")
    if not isinstance(result.genre, str):
        raise TypeError("research genre must be a string")
    for name in ("facts", "complementary_queries", "unresolved_gaps"):
        values = getattr(result, name, None)
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise TypeError(f"research {name} must be a list of objects")
    if result.etymology is not None and not all(
            callable(getattr(result.etymology, attr, None))
            for attr in ("to_dict", "chain_text")):
        raise TypeError("research etymology must expose to_dict and chain_text")
    return result


def run_research_stage(idea, cfg, paths, metrics, genre, warnings,
                       sources_registry, emit, write_json) -> ResearchStageResult:
    """Run research, persist provenance, and return grounding context."""
    started = time.monotonic()
    emit(0, "Pesquisando fontes")
    result = research_stage.research_topic(
        idea, cfg.language, max_sources=cfg.research_max_sources,
        metrics=metrics, timeout=cfg.research_timeout, cfg=cfg,
        genre=genre, allow_weak=True)
    result = validate_research_result(result)
    sources = list(result)
    target = result.target
    rejected = list(result.rejected)
    queries = list(result.tried_queries)
    etymology = result.etymology
    weak = result.weak
    status = ("weak" if weak or not sources
              else "confirmed" if len(sources) >= 2 else "partial")
    for warning in result.weak_warnings:
        warnings.append(f"pesquisa: {warning}")
        print(f"AVISO pesquisa: {warning}", file=sys.stderr)
    target_name = target.name if target is not None and target.name else "tema"
    run_event("result",
              f"Entidade: {target_name}; consultas: {len(queries)}; "
              f"fontes aceitas: {len(sources)}, rejeitadas: {len(rejected)}",
              operation="research", entity=target_name,
              query_count=len(queries), found=len(sources) + len(rejected),
              accepted=len(sources), rejected=len(rejected),
              sources=[source.title[:60] for source in sources[:3]])
    for source in sources:
        sources_registry.add_claim(
            claim=source.title, title=source.title, url=source.url,
            evidence=source.snippet[:300], status=status,
            notes=f"RAG web ({source.origin})", license=source.license,
            license_url=source.license_url)
    if etymology is not None:
        from .stages import etymology as etymology_stage
        chain = etymology.chain_text()
        for source in etymology.sources:
            license_text, license_url = etymology_stage.source_license(source.origin)
            sources_registry.add_claim(
                claim=f"etimologia: {chain}" if chain else source.title,
                title=source.title, url=source.url,
                evidence=(source.snippet or "")[:300], status=status,
                notes=f"RAG etimologia ({source.origin})",
                license=source.license or license_text,
                license_url=source.license_url or license_url)
    write_json(paths.research_json, {
        "idea": idea,
        "target_entity": target.to_dict() if target is not None else None,
        "queries": queries,
        "etymology": etymology.to_dict() if etymology is not None else None,
        "facts": result.facts,
        "complementary_queries": result.complementary_queries,
        "unresolved_gaps": result.unresolved_gaps,
        "sources": [source.to_dict() for source in sources],
        "rejected": [{"title": source.title, "url": source.url,
                      "reason": reason, "detail": detail}
                     for source, reason, detail in rejected],
    })
    prompt = research_stage.format_for_prompt(result, cfg.language)
    print(f"Fontes: {len(sources)} ({', '.join(s.title[:40] for s in sources)})")
    elapsed = round(time.monotonic() - started, 2)
    emit(0, "Pesquisando fontes", "OK")
    return ResearchStageResult(result, status, prompt, elapsed)
