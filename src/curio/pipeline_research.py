"""Research stage orchestration and persistence for the video pipeline."""

from __future__ import annotations

import time
import sys
from dataclasses import dataclass

from .runlog import event as run_event
from .stages import research as research_stage


@dataclass
class ResearchStageResult:
    result: object
    sources: list
    target: object
    rejected: list
    queries: list[str]
    etymology: object
    status: str
    prompt: str
    elapsed: float


def run_research_stage(idea, cfg, paths, metrics, genre, warnings,
                       sources_registry, emit, write_json) -> ResearchStageResult:
    """Run research, persist provenance, and return grounding context."""
    started = time.monotonic()
    emit(0, "Pesquisando fontes")
    result = research_stage.research_topic(
        idea, cfg.language, max_sources=cfg.research_max_sources,
        metrics=metrics, timeout=cfg.research_timeout, cfg=cfg,
        genre=genre, allow_weak=True)
    sources = list(result)
    target = getattr(result, "target", None)
    rejected = list(getattr(result, "rejected", []))
    queries = list(getattr(result, "tried_queries", []))
    etymology = getattr(result, "etymology", None)
    weak = bool(getattr(result, "weak", False))
    status = ("weak" if weak or not sources
              else "confirmed" if len(sources) >= 2 else "partial")
    for warning in getattr(result, "weak_warnings", []):
        warnings.append(f"pesquisa: {warning}")
        print(f"AVISO pesquisa: {warning}", file=sys.stderr)
    target_name = getattr(target, "name", "") or "tema"
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
        "facts": getattr(result, "facts", []),
        "complementary_queries": getattr(result, "complementary_queries", []),
        "unresolved_gaps": getattr(result, "unresolved_gaps", []),
        "sources": [source.to_dict() for source in sources],
        "rejected": [{"title": source.title, "url": source.url,
                      "reason": reason, "detail": detail}
                     for source, reason, detail in rejected],
    })
    prompt = research_stage.format_for_prompt(result, cfg.language)
    print(f"Fontes: {len(sources)} ({', '.join(s.title[:40] for s in sources)})")
    elapsed = round(time.monotonic() - started, 2)
    emit(0, "Pesquisando fontes", "OK")
    return ResearchStageResult(result, sources, target, rejected, queries,
                               etymology, status, prompt, elapsed)
