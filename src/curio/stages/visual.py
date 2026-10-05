"""Modo roteiro-pronto: organiza mídia sobre uma narração já existente.

Este módulo NUNCA gera, reescreve ou altera o roteiro: o texto fornecido
pelo usuário é preservado byte a byte (só aparas de borda). A divisão em
trechos/cenas reaproveita `stages.scenes` com validação literal — se a
junção das narrações não reproduzir o roteiro, falha em voz alta em vez
de entregar narração adulterada.

Para cada trecho, busca-se até `max_images` imagens com gate de
relevância (título precisa conter algo da consulta — nunca associação
falsa só para preencher espaço). O plano visual distribui as imagens no
tempo da cena com sobreposição e entradas suaves/variadas (álbum de
fotografias): a nova imagem entra sobre a atual, assume o destaque e a
próxima repete o ciclo. Com uma única imagem adequada, o render usa Ken
Burns sutil em vez de inventar uma segunda.

Aquisição e escolha editorial são fases distintas: SearchPlan fornece as
consultas, os providers devolvem candidatos normalizados, e seleção aplica
gates, scoring e política de diversidade. Resultados de busca iguais são
compartilhados em memória dentro do vídeo; apenas bytes de assets são
persistidos no cache global. A seleção por projeto é reutilizável somente
quando seu manifesto corresponde aos inputs semânticos e à política atual.
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Mapping
import os
import sys
import time

from ..config import CurioConfig
from ..media.providers import (
    MediaAsset,
    MediaError,
    MediaProvider,
    classify_rights,
)
from . import media_rules
from .visual_contracts import VisualPlan
from .visual_planning import build_visual_plan
from .search_planning import build_search_plan
from .media_contracts import Candidate, CandidateRejection
from .candidate_evaluation import evaluate_generic, evaluate_specific
from .media_selection import (ReuseCandidate, make_selection_decision,
                              prepare_selection_pool,
                              record_asset_usage,
                              select_reuse_candidate)
from .media_selection import SelectionDecision
from .visual_audit import candidate_audit_rows
from .media_provider_policy import ordered_providers
from .scene_contract import SemanticScene
from . import media_acquisition
from . import media_search

# SearchPlan ordering and provider policy are decided before transport.

# Hierarquia de provedores (ordem de prioridade). Do mais específico para
# o mais genérico: primeiro os bancos de foto com chave, depois os acervos
# abertos, e o Unsplash por ÚLTIMO — é a foto mais bonita e a que mais
# foge do assunto, então só entra quando nada mais serviu, e com orçamento
# próprio de 15 requisições (a cota demo dele é 50/hora e um vídeo estoura
# isso em duas cenas).
# Resultados de busca só vivem na memória da execução, nunca entre vídeos.
# Quantos candidatos se coleta por consulta antes de escolher. O lineup
# antigo aceitava 1 asset do primeiro provedor; recolher uma dúzia e
# ordenar é o que permite escolher em vez de tomar o que veio.
CANDIDATE_MULTIPLIER = 4
MAX_SCENE_CANDIDATES = 20
# Rejeições que a folha de contato guarda por cena (o resto é ruído).
REJECTED_KEPT = 8


# O gate de metadados é `media_rules.asset_gate_reason`: era a terceira
# cópia da mesma regra, e a única que devolvia booleano — o que jogava fora
# a informação que o autor precisa ("por que a cena ficou sem foto").
_validate_asset_for = media_rules.asset_gate_reason


def _selection_asset_key(asset: dict) -> str:
    """Identity shared across providers when they expose the same source."""
    from ..media.identity import asset_identity
    return asset_identity(asset)


def _search_scene_with_shortcircuit(
    ch,
    providers: list[MediaProvider],
    cfg: CurioConfig,
    max_images: int,
    metrics,
    cache_dir: str,
    visual_state=None,
    genre: str = "",
    asset_uses: dict | None = None,
    shared_search_cache: dict | None = None,
) -> tuple[list[dict], list[str]]:
    """Busca mídia de uma cena: COLETA candidatos, depois FILTRA e PONTUA.

    O comportamento antigo parava no primeiro asset que passasse no gate e
    no primeiro provedor que respondesse. Isso transformava o acervo inteiro
    num sorteio: com o Pixabay primeiro na fila, ele resolvia as 23 imagens
    do vídeo, e a que "casou" com a palavra do tema era a que o Pixabay
    devolveu primeiro — não a mais próxima do assunto. Foi assim que uma
    usina termelétrica entrou numa cena de papel térmico.

    Agora: junta candidatos de vários provedores, descarta com MOTIVO
    (licença, resolução, termo decorativo, termo proibido da cena) e só
    então ordena. Um provedor que responde mal não esgota mais a cena.
    """
    warnings = []
    if hasattr(ch, "semantic_scene"):
        ch = ch.semantic_scene()
    results_before = sum(metrics.media_results_received.values()) if metrics else 0
    downloads_before = metrics.media_downloads if metrics else 0
    cache_before = metrics.media_cache_hits if metrics else 0
    planning_started = time.monotonic()
    visual_plan = build_visual_plan(ch)
    search_plan = build_search_plan(visual_plan, genre)
    if metrics:
        metrics.media_query_generation_time += time.monotonic() - planning_started
    queries = [item.query for item in search_plan.queries]
    generics = set(search_plan.generic_queries)
    search_query_by_text = {item.query: item for item in search_plan.queries}
    blocked = media_rules.scene_blocklist(ch)
    vtype = visual_plan.visual_type

    # Uma cena tipográfica NÃO tem foto. A ideia dela É uma palavra, e
    # busca lexical por essa palavra traz qualquer coisa que a carregue no
    # título: "salarium" devolve um fungo chamado Clathurella salarium e
    # um navio-hospital. Não é um defeito do Threshold nem do filtro — é a
    # pergunta errada. A cena vai direto para o cartão, que é o visual
    # certo por construção.
    if vtype == "typographic":
        from . import visuals
        from .visual_fallback_planning import build_visual_fallback_plan
        fallback_plan = build_visual_fallback_plan(
            visual_plan, ch.narration, genre, visual_state)
        synth = visuals.render_fallback_plan(
            fallback_plan, cfg.cache_dir,
            getattr(cfg, "language", "pt-BR"), genre)
        if synth is not None:
            if visual_state:
                visual_state.record(fallback_plan.subject,
                                    fallback_plan.form or fallback_plan.strategy)
            if metrics:
                metrics.media_record_visual_type(vtype)
                metrics.media_record_fallback(fallback_plan.strategy)
                metrics.media_record_synthetic_asset()
            from ..runlog import event as run_event
            run_event("fallback", f"Cena {ch.id}: form tipográfico ({fallback_plan.form})",
                      operation="media", scene=ch.id,
                      strategy=fallback_plan.strategy, form=fallback_plan.form,
                      reason=fallback_plan.reason)
            return [{
                "chapter_id": ch.id,
                "asset": synth.to_dict(),
                "assets": [{"asset": synth.to_dict(), "query": "",
                            "relevance": 0, "order": 0,
                            "score": 0.0, "strategy": fallback_plan.strategy}],
                "reused_from": None,
                "rejected": [],
                "visual_type": vtype,
                "strategy": fallback_plan.strategy,
                "visual_decision": {
                    "topic": visual_plan.topic,
                    "visual_plan": visual_plan.to_dict(),
                    "fallback_plan": fallback_plan.to_dict(),
                    "search_plan": search_plan.to_dict(),
                    "queries": [],
                    "providers_consulted": [],
                    "candidates": [{"title": synth.title,
                                     "provider": "synth",
                                     "decision": "selected",
                                     "reason": f"typographic intent rendered as {fallback_plan.form}"}],
                    "selected": {"title": synth.title, "provider": "synth",
                                 "reason": f"typographic intent rendered as {fallback_plan.form}"},
                    "fallback": fallback_plan.strategy,
                    "search_exhausted": True,
                    "search_exhaustion_reason": "typographic_visual_requires_synthetic_form",
                    "fallback_level": "synthetic_without_search",
                    "selection": SelectionDecision(
                        scene_id=ch.id, status="synthetic",
                        asset_id=synth.asset_id, provider="synth",
                        fallback_level="synthetic_without_search",
                        reason=fallback_plan.reason,
                    ).to_dict(),
                },
            }], warnings

    candidates: list[dict] = []   # candidatos que passaram nos filtros
    rejected: list[dict] = []     # (motivo, título) p/ a folha de contato
    seen_ids: set[str] = set()
    providers_consulted: set[str] = set()
    query_providers: dict[str, set[str]] = {}
    abandoned_duplicate_queries: set[str] = set()
    unexecuted_queries: dict[str, str] = {}
    duplicate_candidates = 0
    query_audit: dict[str, dict] = {q: {"results": 0, "duplicates": 0,
                                        "rejected": 0, "eligible": 0, "providers": [],
                                        "by_provider": {}, "errors_by_provider": {}}
                                    for q in queries}

    def _consider(cand: MediaAsset, query: str) -> None:
        nonlocal duplicate_candidates
        dedupe_started = time.monotonic()
        source = (cand.source_url or "").split("?", 1)[0].rstrip("/").casefold()
        identity = (f"url:{source}" if source else
                    f"{cand.provider}:{cand.asset_id}")
        candidate = Candidate(cand, search_query_by_text[query], identity)
        # Provider aliases often expose the same Commons/Met object. Prefer
        # stable source identity; asset IDs remain provider-scoped fallback.
        if identity in seen_ids:
            duplicate_candidates += 1
            query_audit[query]["duplicates"] += 1
            if metrics:
                metrics.media_record_funnel("duplicates")
                metrics.media_deduplication_time += time.monotonic() - dedupe_started
            return
        seen_ids.add(identity)
        if metrics:
            metrics.media_deduplication_time += time.monotonic() - dedupe_started
        if metrics:
            metrics.media_record_funnel("unique_considered")
        why = _validate_asset_for(cand, blocked)
        if why:
            query_audit[query]["rejected"] += 1
            semantic = scoring.semantic_relevance(cand.to_dict(), ch)
            rejected.append({**CandidateRejection(
                candidate, why, "technical_gate").to_dict(), **semantic})
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_funnel("hard_rejected")
                if classify_rights(cand.license or "", cand.provider) == "blocked":
                    metrics.media_record_rights("blocked")
            return
        if metrics:
            metrics.media_record_funnel("eligible")
        query_audit[query]["eligible"] += 1
        candidates.append(candidate)

    from . import scoring
    min_score = scoring.threshold()

    def collect(query_list: list[str], limit: int) -> None:
        for query_index, query in enumerate(query_list):
            if len(candidates) >= MAX_SCENE_CANDIDATES:
                for pending in query_list[query_index:]:
                    unexecuted_queries.setdefault(pending, "scene_candidate_budget")
                break
            candidates_before_query = len(candidates)
            query_key = query.casefold()
            identities_before = len(seen_ids)
            duplicates_before = duplicate_candidates
            shared = (shared_search_cache.setdefault(query_key, {})
                      if shared_search_cache is not None else {})
            active = [prov for prov in providers
                      if not getattr(prov, "_disabled", False)]
            scene_order = [p.name for p in
                           ordered_providers(cfg, visual_plan, genre, providers)]
            rank = {name: index for index, name in enumerate(scene_order)}
            active.sort(key=lambda p: rank.get(p.name, len(rank)))
            providers_consulted.update(prov.name for prov in active)
            query_providers.setdefault(query, set()).update(
                prov.name for prov in active)
            query_audit[query]["providers"] = [prov.name for prov in active]
            if not active:
                query_audit[query]["unavailable"] = True
            if metrics and active:
                metrics.media_queries_count += 1
            response_stream = media_search.search_providers(
                query, active,
                shared_results=(shared if shared_search_cache is not None else None),
                metrics=metrics, timeout=media_search.SEARCH_TIMEOUT)
            try:
                responses = iter(response_stream)
                for response in responses:
                    if response.query != query:
                        raise ValueError("provider response query does not match request")
                    provider_name = response.provider
                    if response.error:
                        query_audit[query]["errors_by_provider"][provider_name] = (
                            response.error)
                        continue
                    prov_results = response.assets
                    query_audit[query]["results"] += len(prov_results)
                    query_audit[query]["by_provider"][provider_name] = (
                        query_audit[query]["by_provider"].get(provider_name, 0)
                        + len(prov_results))
                    for result_index, cand in enumerate(prov_results):
                        if (len(candidates) >= MAX_SCENE_CANDIDATES
                                or len(candidates) - candidates_before_query >= limit):
                            if metrics:
                                metrics.media_record_funnel(
                                    "budget_unexamined",
                                    len(prov_results) - result_index)
                            break
                        _consider(cand, query)
                    if (len(candidates) >= MAX_SCENE_CANDIDATES
                            or len(candidates) - candidates_before_query >= limit):
                        break
            finally:
                response_stream.close()
            if (len(seen_ids) == identities_before
                    and duplicate_candidates > duplicates_before):
                abandoned_duplicate_queries.add(query)
                if metrics:
                    metrics.media_duplicate_queries += 1
    # Colete e pontue específicos antes de buscar fotos genéricas do gênero.
    # Generic queries só rodam quando nenhuma foto específica passa o gate.
    specific_queries = [q for q in queries if q.lower() not in generics]
    generic_queries = [q for q in queries if q.lower() in generics]
    # A strong metadata score is not a successful asset: download can still
    # fail or reveal unusable dimensions. Explore the bounded query tree before
    # selecting, then download ranked candidates until one passes acquisition.
    phase_budget = max(1, max_images * CANDIDATE_MULTIPLIER)
    collect(specific_queries, phase_budget)
    score_started = time.monotonic()
    specific_result = evaluate_specific(
        [candidate for candidate in candidates
         if not candidate.search_query.generic], ch, min_score)
    if metrics:
        metrics.media_selection_time += time.monotonic() - score_started
    specific = [item.to_selection_entry() for item in specific_result.accepted]
    low_specific = [item.to_selection_entry() for item in specific_result.rejected]
    evaluated_entries = [*specific, *low_specific]
    fresh_specific = [entry for entry in specific
                      if not asset_uses or not asset_uses.get(
                          _selection_asset_key(entry["asset"]), 0)]
    deferred_specific = [entry for entry in specific if entry not in fresh_specific]
    if fresh_specific:
        ranked, low = specific, low_specific
    else:
        collect(generic_queries, phase_budget)
        score_started = time.monotonic()
        generic_result = evaluate_generic(
            [candidate for candidate in candidates
             if candidate.search_query.generic], ch, min_score)
        if metrics:
            metrics.media_selection_time += time.monotonic() - score_started
        ranked = [item.to_selection_entry() for item in generic_result.accepted]
        low_generic = [item.to_selection_entry() for item in generic_result.rejected]
        evaluated_entries.extend([*ranked, *low_generic])
        low = low_specific + low_generic
        # Preserve qualified used results solely for the final fallback after
        # fresh contextual results and synthetic visuals have been tried.
        ranked.extend(deferred_specific)
    if scoring.clip_enabled(cfg) and ranked:
        status = scoring.clip_status(cfg) or ""
        if "habilitada (" in status:
            shortlist = ranked[:max(1, min(max_images * 2, 10))]
            clip_applied = False
            for entry in shortlist:
                try:
                    downloaded = media_acquisition.download_media(
                        MediaAsset.from_dict(entry["asset"]),
                        cfg.cache_dir, metrics)
                    asset = downloaded.asset
                    if not media_acquisition.downloaded_dimensions_valid(asset):
                        continue
                    entry["asset"] = asset.to_dict()
                    clip_score = scoring.clip_score_image(asset.local_path, ch, cfg)
                except (MediaError, TypeError, OSError):
                    clip_score = None
                if clip_score is None:
                    continue
                clip_applied = True
                entry["clip_score"] = round(clip_score, 4)
                detail = entry.setdefault("score_detail", {})
                detail["clip"] = round(clip_score, 4)
                detail["layers"] = list(dict.fromkeys(detail.get("layers", []) + ["clip"]))
                entry["score"] = round(entry["score"] * 0.8
                                        + ((clip_score + 1.0) * 50.0) * 0.2, 2)
            ranked.sort(key=lambda item: (-item["score"],
                                          -item.get("score_detail", {}).get("scene_relevance", 0),
                                          item.get("order", 0)))
            if metrics and clip_applied:
                metrics.media_layers_used["clip"] = metrics.media_layers_used.get("clip", 0) + 1
                metrics.media_layer_device = scoring.clip_device(cfg)
    for entry in low:
        # Descartado por NOTA, não por filtro: é o caso que mais importa
        # registrar, porque a imagem passou em todos os testes e ainda
        # assim não é do assunto (a usina que "casou" com "térmico").
        rejected.append({
            "title": entry["asset"].get("title", ""),
            "query": entry["query"],
            "reason": (entry.get("rejection_reason")
                       or entry.get("score_detail", {}).get("semantic_rejection")
                       or f"nota {entry['score']:.0f} abaixo do mínimo {min_score:.0f}"),
            "provider": entry["asset"].get("provider", ""),
            "score": entry["score"],
            "score_detail": entry.get("score_detail", {}),
        })
        if metrics:
            metrics.media_record_asset_rejected()
            metrics.media_record_funnel("score_rejected")
    from .visual_beats import asset_key
    selection_pool = prepare_selection_pool(ranked, asset_uses, _selection_asset_key)
    ranked = list(selection_pool.fresh)
    reused_ranked = list(selection_pool.reused)
    if metrics:
        metrics.media_record_selection(len(candidates), len(ranked))
        metrics.media_record_funnel("above_threshold", len(ranked))
    for rej in rejected:
        if metrics:
            metrics.media_record_rejection(rej["reason"])
    # A estratégia da cena é registrada mesmo quando ela dá certo: o
    # relatório precisa mostrar a distribuição (item 20), e um diagrama
    # não pode ser contado como falha.
    if metrics:
        metrics.media_record_visual_type(
            str(getattr(ch, "visual_type", "") or "literal"))

    picked: list[dict] = []
    scene_content_seen: set[str] = set()
    download_window = min(max(1, media_acquisition.MAX_CONCURRENT_DOWNLOADS),
                          max(1, max_images))
    download_futures: dict[int, object] = {}
    next_download = 0

    def fill_download_window() -> None:
        nonlocal next_download
        while len(download_futures) < download_window and next_download < len(ranked):
            index = next_download
            next_download += 1
            try:
                candidate = MediaAsset.from_dict(ranked[index]["asset"])
            except TypeError:
                continue
            if candidate.local_path and os.path.isfile(candidate.local_path):
                continue
            download_futures[index] = media_acquisition.submit_download(
                candidate, cfg.cache_dir, metrics)

    fill_download_window()
    for rank_index, entry in enumerate(ranked):
        if len(picked) >= max_images:
            break
        asset_dict = entry["asset"]
        if metrics:
            metrics.media_record_funnel("selected")
            metrics.media_shortlist_ids.add(asset_key(asset_dict))
        try:
            asset = MediaAsset.from_dict(asset_dict)
        except TypeError:
            continue
        local = asset.local_path
        acquisition = "cache" if local and os.path.isfile(local) else "download"
        if not (local and os.path.isfile(local)):
            future = download_futures.pop(rank_index, None)
            try:
                if future is None:
                    future = media_acquisition.submit_download(
                        asset, cfg.cache_dir, metrics)
                downloaded = future.result(
                    timeout=media_acquisition.DOWNLOAD_TIMEOUT)
                asset, acquisition = downloaded.asset, downloaded.origin
                fill_download_window()
            except (MediaError, concurrent.futures.TimeoutError) as exc:
                if future is not None:
                    future.cancel()
                fill_download_window()
                entry["rejection_reason"] = f"download failed: {exc}"
                msg = f"cena {ch.id}: download falhou ({exc})"
                warnings.append(msg)
                from ..runlog import event as run_event
                logged = run_event("warning", msg, operation="media_download",
                                   scene=ch.id, provider=asset.provider,
                                   error=str(exc))
                if not logged:
                    print(f"AVISO: {msg}", file=sys.stderr)
                if metrics:
                    metrics.media_record_funnel("download_failed")
                continue
        if not media_acquisition.downloaded_dimensions_valid(asset):
            entry["rejection_reason"] = "resolution/legibility after download"
            msg = (f"cena {ch.id}: '{asset.title[:50]}' rejeitado após "
                   f"download (resolução insuficiente ou ilegível)")
            warnings.append(msg)
            rejected.append({"title": asset.title, "query": entry["query"],
                             "reason": "resolução/legibilidade após download",
                             "provider": asset.provider})
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_rejection("resolução/legibilidade após download")
                metrics.media_record_funnel("post_download_rejected")
            continue
        content_key = _selection_asset_key(asset.to_dict())
        if (content_key.startswith("sha256:")
                and (content_key in scene_content_seen
                     or (asset_uses is not None
                         and asset_uses.get(content_key, 0)))):
            record_asset_usage(asset_uses, asset_dict, asset.to_dict(),
                               _selection_asset_key, increment=False)
            entry["rejection_reason"] = "duplicate content hash"
            rejected.append({"title": asset.title, "query": entry["query"],
                             "reason": "duplicate content hash",
                             "provider": asset.provider,
                             "content_identity": content_key})
            if metrics:
                metrics.media_record_asset_rejected()
                metrics.media_record_rejection("duplicate content hash")
                metrics.media_record_funnel("duplicate_content_hash")
            continue
        asset.used_in = f"cena {ch.id}"
        if not asset.rights_status:
            asset.rights_status = classify_rights(asset.license or "",
                                                  asset.provider)
        if asset.rights_status == "verify":
            if metrics:
                metrics.media_record_rights("verify")
            msg = (f"cena {ch.id}: licença a conferir manualmente "
                   f"({asset.provider}: {asset.license or 'desconhecida'}) — "
                   f"{asset.license_url or asset.source_url or 'sem link'}")
            warnings.append(msg)
            from ..runlog import event as run_event
            logged = run_event("warning", msg, operation="media_rights",
                               scene=ch.id, provider=asset.provider,
                               rights_status="verify")
            if not logged:
                print(f"AVISO: {msg}", file=sys.stderr)
        entry = dict(entry)
        entry["asset"] = asset.to_dict()
        if entry.get("generic") and metrics:
            metrics.media_record_funnel("generic_used")
        entry["order"] = len(picked)
        entry["acquisition"] = acquisition
        entry["score"] = entry.get("score", 0)
        if metrics:
            metrics.media_record_score(entry["score"])
        picked.append(entry)
        if content_key.startswith("sha256:"):
            scene_content_seen.add(content_key)
        if asset_uses is not None:
            key = _selection_asset_key(entry["asset"])
            if asset_uses.get(key, 0):
                entry["reuse_reason"] = "eligible_pool_exhausted"
            record_asset_usage(asset_uses, asset_dict, entry["asset"],
                               _selection_asset_key)
        if metrics:
            metrics.media_record_funnel("used_real")

    strategy_used = "image"
    if not picked:
        # Nenhuma fotografia serviu. A cena NÃO fica vazia e NÃO recebe
        # imagem genérica: ela troca de medium. Um diagrama ou um cartão
        # é a cena certa mostrada do jeito certo, e a métrica registra
        # como estratégia, não como falha.
        from . import visuals
        from .visual_fallback_planning import build_visual_fallback_plan
        fallback_plan = build_visual_fallback_plan(
            visual_plan, ch.narration, genre, visual_state)
        synth = visuals.render_fallback_plan(
            fallback_plan, cfg.cache_dir,
            getattr(cfg, "language", "pt-BR"), genre)
        if synth is not None:
            if visual_state:
                visual_state.record(fallback_plan.subject,
                                    fallback_plan.form or fallback_plan.strategy)
            picked.append({"asset": synth.to_dict(),
                           "query": queries[0] if queries else "",
                            "relevance": 0, "order": 0,
                            "score": 0.0, "strategy": "synth"})
            strategy_used = fallback_plan.strategy
            if metrics:
                metrics.media_record_fallback(strategy_used)
                metrics.media_record_synthetic_asset()
            from ..runlog import active as run_active
            if not run_active():
                print(f"cena {ch.id}: sem foto adequada — visual por código "
                      f"({strategy_used}): {synth.title[:60]}", file=sys.stderr)
    # Reuse only after all specific/context searches and the local visual.
    if not picked and reused_ranked:
        for entry in sorted(reused_ranked, key=lambda item: -item.get("score", 0)):
            asset = MediaAsset.from_dict(entry["asset"])
            try:
                if not (asset.local_path and os.path.isfile(asset.local_path)):
                    downloaded = media_acquisition.submit_download(
                        asset, cfg.cache_dir, metrics).result(
                            timeout=media_acquisition.DOWNLOAD_TIMEOUT)
                    asset, acquisition = downloaded.asset, downloaded.origin
                else:
                    acquisition = "cache"
            except (MediaError, concurrent.futures.TimeoutError):
                continue
            if not media_acquisition.downloaded_dimensions_valid(asset):
                continue
            asset.used_in = f"cena {ch.id}"
            entry = dict(entry, asset=asset.to_dict(), acquisition=acquisition,
                         reuse_reason="fresh_search_and_synthetic_exhausted")
            picked.append(entry)
            key = _selection_asset_key(entry["asset"])
            record_asset_usage(asset_uses, entry["asset"], entry["asset"],
                               _selection_asset_key)
            if metrics:
                metrics.media_record_funnel("reused_fallback")
            break
    if not picked:
        msg = (f"cena {ch.id}: sem imagem adequada "
               f"({', '.join(queries[:3]) or 'sem consultas'})"
               + (f" — {len(rejected)} candidato(s) rejeitados" if rejected else "")
               + " — vai usar estratégia visual alternativa")
        warnings.append(msg)
        from ..runlog import event as run_event
        logged = run_event("warning", msg, operation="media", scene=ch.id)
        if not logged:
            print(f"AVISO: {msg}", file=sys.stderr)
        if metrics:
            metrics.media_record_asset_rejected()
            metrics.media_record_no_visual()

    from ..runlog import event as run_event
    returned = (sum(metrics.media_results_received.values()) - results_before
                if metrics else 0)
    downloads = metrics.media_downloads - downloads_before if metrics else 0
    cache_hits = metrics.media_cache_hits - cache_before if metrics else 0
    synthetic = bool(picked and picked[0].get("asset", {}).get("provider") == "synth")
    message = (f"Cena {ch.id}: {returned} resultados; {len(candidates)} elegíveis; "
               f"{len(ranked)} acima do score; {len(picked)} selecionado(s); "
               f"{downloads} baixado(s), {cache_hits} cache hit(s)"
               + ("; card/diagrama" if synthetic else ""))
    run_event("fallback" if synthetic else "result", message,
              operation="media", scene=ch.id, returned=returned,
              eligible=len(candidates), above_threshold=len(ranked),
              selected=len(picked), downloaded=downloads,
              cache_hits=cache_hits, strategy=strategy_used)

    first = picked[0]["asset"] if picked else None
    scene_rejected = rejected[:REJECTED_KEPT]
    video_context = dict(getattr(ch, "video_context", {}) or {})
    representation_levels = {}
    representation_kinds = {}
    for rep in (getattr(ch, "representations", []) or []):
        if isinstance(rep, Mapping):
            rep_query = str(rep.get("query", ""))
            representation_kinds[rep_query] = str(rep.get("kind", "related"))
            try:
                representation_levels[rep_query] = int(
                    rep.get("level", 0) or 0)
            except (TypeError, ValueError):
                representation_levels[rep_query] = 0
    audit_candidates = candidate_audit_rows(
        evaluated_entries, rejected, picked, representation_levels, min_score)
    decision = {
        "topic": video_context.get("topic", ""),
        "visual_plan": visual_plan.to_dict(),
        "fallback_plan": (fallback_plan.to_dict()
                          if synthetic and "fallback_plan" in locals() else None),
        "search_plan": search_plan.to_dict(),
        "visual_intent": (getattr(ch, "visual_intent_structured", "")
                           or getattr(ch, "visual_intent", "")),
        "entities": list(dict.fromkeys([str(getattr(ch, "primary_entity", "") or ""),
            str(getattr(ch, "event", "") or ""),
            *(getattr(ch, "visual_entities", []) or []),
            *(getattr(ch, "context", []) or [])]))[:12],
        "primary_entity": getattr(ch, "primary_entity", "") or getattr(ch, "subject", ""),
        "representations": [rep.to_dict() for rep in visual_plan.representations],
        "representations_discarded": getattr(ch, "representation_rejections", []) or [],
        "aliases": list(video_context.get("aliases", []) or []),
        "queries": [{"query": query,
                     "source": search_query_by_text[query].source,
                     "representation": search_query_by_text[query].representation,
                     "representation_kind": search_query_by_text[query].representation_kind,
                     "alias": search_query_by_text[query].alias,
                     "query_variant": search_query_by_text[query].variant,
                     "level": search_query_by_text[query].level,
                     "generic": search_query_by_text[query].generic,
                     "providers": query_audit[query]["providers"],
                     "provider_errors": dict(query_audit[query]["errors_by_provider"]),
                     "results": query_audit[query]["results"],
                     "results_by_provider": dict(query_audit[query]["by_provider"]),
                     "duplicates": query_audit[query]["duplicates"],
                     "eligible_candidates": query_audit[query]["eligible"],
                     "rejected_candidates_total": len([
                         item for item in rejected if item.get("query") == query]),
                     "outcome": ("duplicates_only" if query in abandoned_duplicate_queries else
                                 "rejected" if query_audit[query]["rejected"] else
                                 "eligible" if query_audit[query]["eligible"] else
                                 "empty_or_unavailable"),
                     "representations": [rep for rep in representation_levels
                         if rep.casefold() in query.casefold()],
                     "representation_kinds": {rep: representation_kinds[rep]
                         for rep in representation_levels
                         if rep.casefold() in query.casefold()},
                     "aliases_used": [alias for alias in
                         list(video_context.get("aliases", []) or [])
                         if str(alias).casefold() in query.casefold()],
                     "status": ("not_consulted_budget_exhausted"
                                if unexecuted_queries.get(query) == "scene_candidate_budget" else
                                "abandoned_duplicates"
                                if query in abandoned_duplicate_queries else
                                "consulted" if query_providers.get(query)
                                else "no_provider_results"),
                     "unexecuted_reason": unexecuted_queries.get(query, "")}
                    for query in queries],
        "providers_consulted": sorted(providers_consulted),
        "candidates": audit_candidates,
        "selected": (next((item for item in audit_candidates
                           if item["decision"] == "selected"), None)
                     or ({"title": (first or {}).get("title", ""),
                          "provider": (first or {}).get("provider", ""),
                          "reason": "No candidate passed semantic gates; rendered safe local visual"}
                         if first and (first or {}).get("provider") == "synth" else None)),
        "fallback": strategy_used if synthetic or not picked else "",
        "search_exhausted": bool(
            (not picked or picked[0].get("reuse_reason")
             or (first or {}).get("provider") == "synth")
            and not unexecuted_queries
            and all(query_audit[q]["providers"]
                    and not query_audit[q]["errors_by_provider"]
                    and not query_audit[q].get("unavailable") for q in queries)),
        "search_exhaustion_reason": (
            "new_asset_selected" if picked and (first or {}).get("provider") != "synth"
            and not picked[0].get("reuse_reason") else
            "queries_not_executed" if unexecuted_queries else
            "provider_errors" if any(a["errors_by_provider"] for a in query_audit.values()) else
            "no_available_provider" if any(not a["providers"] for a in query_audit.values()) else
            "all_queries_consulted_no_valid_asset" if synthetic or not picked else
            "asset_reuse_after_search" if picked else ""),
        "fallback_level": ("synthetic_after_incomplete_search"
                           if (first or {}).get("provider") == "synth"
                           and (unexecuted_queries or any(
                               a["errors_by_provider"] or not a["providers"]
                               for a in query_audit.values())) else
                           "synthetic_after_exhaustion"
                           if (first or {}).get("provider") == "synth" else
                           "reused" if picked and picked[0].get("reuse_reason") else
                           "specific" if picked and picked[0].get("query") in representation_levels
                           else "representation_or_media_variant" if picked else "exhausted"),
    }
    decision["selection"] = make_selection_decision(
        ch.id, picked, decision["fallback_level"]).to_dict()
    return [{
        "chapter_id": ch.id,
        "asset": first,
        "assets": picked,
        "reused_from": None,
        "rejected": scene_rejected,
        "visual_decision": decision,
        "visual_type": str(getattr(ch, "visual_type", "") or "literal"),
        "strategy": strategy_used,
    }], warnings


def fetch_media_multi(semantic_scenes: list[SemanticScene], cfg: CurioConfig,
                      max_images: int = 3,
                      metrics=None, genre: str = "") -> tuple[list[dict], list[str]]:
    """Acquire candidates for each scene and select using its explicit plans.

    Exact queries share provider responses in a per-video in-memory cache;
    downloaded bytes live in the reusable global media cache. This function
    records project selection separately from both caches.
    """
    if any(not isinstance(scene, SemanticScene) for scene in semantic_scenes):
        raise TypeError("media acquisition requires SemanticScene values")
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    if not scene_ids or len(scene_ids) != len(set(scene_ids)):
        raise ValueError("media acquisition requires unique semantic scenes")
    max_images = max(1, min(5, int(max_images)))
    # A ordem de provedores é por cena: histórica quer acervo de arte
    # primeiro, as demais mantêm a ordem global.
    providers = []
    seen_names: set[str] = set()
    for scene in semantic_scenes:
        scene_plan = build_visual_plan(scene.semantic_scene()
                                       if hasattr(scene, "semantic_scene") else scene)
        for prov in ordered_providers(cfg, scene_plan, genre):
            if prov.name not in seen_names:
                seen_names.add(prov.name)
                providers.append(prov)
    # An empty provider list still uses the per-scene synthetic fallback.
    # Do not copy an unrelated neighbor's asset merely to fill the timeline.
    all_warnings = []
    scenes = []
    # O estado de variedade atravessa as cenas: é ele que impede seis cenas
    # conceituais de virarem seis cards idênticos.
    from .visual_fallback_planning import VisualDiversityState
    visual_state = VisualDiversityState()
    asset_uses: dict[str, int] = {}
    # Different scenes often emit same exact search phrase. Reuse provider
    # results within this video, including empty searches, before hitting
    # disk/query cache or network again.
    shared_search_cache: dict[str, dict[str, list[dict]]] = {}

    for scene in semantic_scenes:
        scene_scenes, scene_warnings = _search_scene_with_shortcircuit(
            scene, providers, cfg, max_images, metrics, cfg.cache_dir,
            visual_state=visual_state, genre=genre, asset_uses=asset_uses,
            shared_search_cache=shared_search_cache,
        )
        scenes.extend(scene_scenes)
        all_warnings.extend(scene_warnings)
    
    _resolve_reuse_multi(scenes, semantic_scenes)
    _annotate_reuse(scenes)
    return scenes, all_warnings


def _annotate_reuse(scenes: list[dict]) -> None:
    """Marca no media.json as imagens que aparecem em mais de uma cena.

    A São Jerônimo mostrou o caso que faltava. Duas cenas com midia
    PRÓPRIA podem receber o mesmo asset_id: cada uma buscou e o provedor
    devolveu o mesmo melhor resultado. Isso não é o que `_resolve_reuse_
    multi` trata, e o campo `reused_from` ficava vazio nas duas — o
    mesmo asset em cenas 1 e 3 só aparecia se alguém fosse comparar o
    media.json na mão.

    Entradas antigas mantêm `same_top_match`; novas seleções registram
    `eligible_pool_exhausted` quando faltam candidatas elegíveis inéditas.
    Não se inventa um motivo `thematic_reuse`. Reuso editorial intencional
    é uma decisão do autor, e o
    curio não tem como ler decisão nenhuma nos dados — afirmar
    "reuso temático" seria inventar o motivo e chamar de diagnóstico. O
    que o registro entrega é o par de cenas e o asset, para o autor
    decidir em um segundo se foi intencional.
    """
    primeira: dict[str, int] = {}
    from .visual_beats import asset_key
    for s in scenes:
        ids = []
        for entry in s.get("assets") or []:
            a = (entry or {}).get("asset") or {}
            aid = str(a.get("asset_id") or "")
            if not aid:
                continue
            ids.append((asset_key(a), a, entry))
        for aid, a, entry in ids:
            if aid in primeira:
                s.setdefault("reuse", []).append({
                    "asset": a.get("asset_id", ""),
                    "title": a.get("title", "")[:120],
                    "provider": a.get("provider", ""),
                    "previous_scene": primeira[aid],
                    "current_scene": s.get("chapter_id"),
                    "reason": entry.get("reuse_reason", "same_top_match"),
                })
            else:
                primeira[aid] = s.get("chapter_id")
    for s in scenes:
        s.setdefault("reuse", [])


def _resolve_reuse_multi(scenes: list[dict],
                          semantic_scenes: list[SemanticScene]) -> None:
    """Reuse only when donor title proves topic and scene relevance."""
    have = [s for s in scenes if s["assets"]]
    by_id = {scene.id: scene for scene in semantic_scenes}
    if not have or not by_id:
        return
    for s in scenes:
        if s["assets"]:
            continue
        cid = s["chapter_id"]
        scene = by_id.get(cid)
        if scene is None:
            continue
        eligible: list[ReuseCandidate] = []
        from . import scoring
        for donor in have:
            donor_scene = by_id.get(donor["chapter_id"])
            if donor_scene is None:
                continue
            for entry in donor.get("assets", []):
                asset = entry.get("asset") or {}
                relevance = scoring.semantic_relevance(asset, scene)
                if (relevance.get("topic_relevance", 0) or 0) > 0 and \
                        (relevance.get("scene_relevance", 0) or 0) >= 25:
                    eligible.append(ReuseCandidate(
                        donor_scene_id=donor["chapter_id"], entry=entry,
                        topic_relevance=relevance["topic_relevance"],
                        scene_relevance=relevance["scene_relevance"]))
        selected = select_reuse_candidate(eligible, cid)
        if selected is None:
            continue
        donor_entry = selected.entry
        nearest = next(item for item in have
                       if item["chapter_id"] == selected.donor_scene_id)
        reuse_reason = "validated_cross_scene_reuse"
        reused_entry = dict(donor_entry, order=0,
                            reuse_reason=reuse_reason)
        s["assets"] = [reused_entry]
        s["asset"] = s["assets"][0]["asset"]
        s["reused_from"] = nearest["chapter_id"]
        if isinstance(s.get("visual_decision"), dict):
            reused_asset = reused_entry.get("asset") or {}
            decision = make_selection_decision(
                cid, s["assets"], "validated_reuse").to_dict()
            decision["reason"] = (
                f"validated topic and scene evidence; reused from scene "
                f"{nearest['chapter_id']} after fresh and synthetic choices")
            s["visual_decision"]["fallback"] = "validated_reuse"
            s["visual_decision"]["selection"] = decision
            s["visual_decision"]["selected"] = {
                "title": reused_asset.get("title", ""),
                "provider": reused_asset.get("provider", ""),
                "topic_relevance": selected.topic_relevance,
                "scene_relevance": selected.scene_relevance,
                "reason": f"validated topic and scene evidence from scene {nearest['chapter_id']}",
            }
        print(f"AVISO: cena {cid} reusa imagem(ns) da cena "
              f"{nearest['chapter_id']} (sem mídia própria).", file=sys.stderr)
