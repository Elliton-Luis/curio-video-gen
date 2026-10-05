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
from typing import TYPE_CHECKING

from ..config import CurioConfig
from ..media.asset_snapshot import MediaAssetSnapshot
from ..media.providers import (
    MediaAsset,
    MediaError,
    MediaProvider,
    classify_rights,
)
from ..media.visual_decision import VisualDecision
from . import media_rules
from .visual_contracts import VisualPlan
from .visual_planning import build_visual_plan
from .search_planning import build_search_plan
from .candidate_evaluation import (describe_technical_rejections,
                                  evaluate_generic, evaluate_specific)
from .media_selection import (annotate_reuse, make_selection_decision,
                              RankedSelectionCandidate,
                              prepare_selection_pool, record_asset_usage,
                              resolve_cross_scene_reuse)
from .media_selection import SelectionDecision
from .visual_audit import candidate_audit_rows, search_query_audit_rows
from .media_provider_policy import ordered_providers
from .scene_contract import SemanticScene
from .scene_candidate_search import SceneCandidateCollector
from . import media_acquisition

if TYPE_CHECKING:
    from ..media.selection_result import MediaStageResult

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
            reason = f"typographic intent rendered as {fallback_plan.form}"
            selection = SelectionDecision(
                scene_id=ch.id, status="synthetic", asset_id=synth.asset_id,
                provider="synth", fallback_level="synthetic_without_search",
                reason=fallback_plan.reason)
            visual_decision = VisualDecision.create(
                selection, topic=visual_plan.topic,
                visual_plan=visual_plan.to_dict(),
                fallback_plan=fallback_plan.to_dict(),
                search_plan=search_plan.to_dict(), queries=[],
                providers_consulted=[],
                candidates=[{"title": synth.title, "provider": "synth",
                             "decision": "selected", "reason": reason}],
                selected={"title": synth.title, "provider": "synth",
                          "reason": reason},
                fallback=fallback_plan.strategy, search_exhausted=True,
                search_exhaustion_reason=(
                    "typographic_visual_requires_synthetic_form"),
                fallback_level="synthetic_without_search")
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
                "visual_decision": visual_decision.to_dict(),
            }], warnings

    from . import scoring
    min_score = scoring.threshold()
    # Colete e pontue específicos antes de buscar fotos genéricas do gênero.
    # Generic queries só rodam quando nenhuma foto específica passa o gate.
    specific_queries = [q for q in queries if q.lower() not in generics]
    generic_queries = [q for q in queries if q.lower() in generics]
    # A strong metadata score is not a successful asset: download can still
    # fail or reveal unusable dimensions. Explore the bounded query tree before
    # selecting, then download ranked candidates until one passes acquisition.
    phase_budget = max(1, max_images * CANDIDATE_MULTIPLIER)
    collector = SceneCandidateCollector(
        ch, visual_plan, search_plan, providers, cfg, metrics, blocked,
        genre=genre, shared_search_cache=shared_search_cache,
        max_candidates=MAX_SCENE_CANDIDATES)
    collection = collector.collect(specific_queries, phase_budget)
    candidates = list(collection.candidates)
    score_started = time.monotonic()
    specific_result = evaluate_specific(
        [candidate for candidate in candidates
         if not candidate.search_query.generic], ch, min_score)
    if metrics:
        metrics.media_selection_time += time.monotonic() - score_started
    specific_ranked = [RankedSelectionCandidate.from_evaluation(item)
                       for item in specific_result.accepted]
    specific = [item.to_selection_entry() for item in specific_result.accepted]
    low_specific = [item.to_selection_entry() for item in specific_result.rejected]
    evaluated_entries = [*specific, *low_specific]
    fresh_specific = [entry for entry in specific_ranked
                      if not asset_uses or not asset_uses.get(
                          _selection_asset_key(entry.asset.to_dict()), 0)]
    deferred_specific = [entry for entry in specific_ranked
                         if entry not in fresh_specific]
    if fresh_specific:
        ranked_candidates, low = specific_ranked, low_specific
    else:
        collection = collector.collect(generic_queries, phase_budget)
        candidates = list(collection.candidates)
        score_started = time.monotonic()
        generic_result = evaluate_generic(
            [candidate for candidate in candidates
             if candidate.search_query.generic], ch, min_score)
        if metrics:
            metrics.media_selection_time += time.monotonic() - score_started
        ranked_candidates = [RankedSelectionCandidate.from_evaluation(item)
                             for item in generic_result.accepted]
        generic_entries = [item.to_selection_entry()
                           for item in generic_result.accepted]
        low_generic = [item.to_selection_entry() for item in generic_result.rejected]
        evaluated_entries.extend([*generic_entries, *low_generic])
        low = low_specific + low_generic
        # Preserve qualified used results solely for the final fallback after
        # fresh contextual results and synthetic visuals have been tried.
        ranked_candidates.extend(deferred_specific)
    collection = collector.snapshot()
    rejected = list(describe_technical_rejections(collection.rejected, ch))
    if scoring.clip_enabled(cfg) and ranked_candidates:
        status = scoring.clip_status(cfg) or ""
        if "habilitada (" in status:
            shortlist_size = max(1, min(max_images * 2, 10))
            clip_applied = False
            for index in range(min(shortlist_size, len(ranked_candidates))):
                entry = ranked_candidates[index]
                try:
                    downloaded = media_acquisition.download_media(
                        MediaAsset.from_dict(entry.asset.to_dict()),
                        cfg.cache_dir, metrics)
                    asset = downloaded.asset
                    if not media_acquisition.downloaded_dimensions_valid(asset):
                        continue
                    asset_snapshot = MediaAssetSnapshot.from_media_asset(asset)
                    entry = entry.with_prepared_asset(asset_snapshot)
                    clip_score = scoring.clip_score_image(asset.local_path, ch, cfg)
                except (MediaError, TypeError, OSError):
                    clip_score = None
                if clip_score is None:
                    ranked_candidates[index] = entry
                    continue
                clip_applied = True
                ranked_candidates[index] = entry.with_clip_score(
                    clip_score, asset_snapshot)
            ranked_candidates.sort(key=lambda item: (
                -item.score,
                -item.evaluation.evidence.get("scene_relevance", 0),
                item.order))
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
    selection_pool = prepare_selection_pool(
        ranked_candidates, asset_uses, _selection_asset_key)
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

    from ..media.selection_result import SelectedAsset
    picked: list[SelectedAsset] = []
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
                candidate = MediaAsset.from_dict(ranked[index].asset.to_dict())
            except TypeError:
                continue
            if candidate.local_path and os.path.isfile(candidate.local_path):
                continue
            download_futures[index] = media_acquisition.submit_download(
                candidate, cfg.cache_dir, metrics)

    fill_download_window()
    for rank_index, ranked_candidate in enumerate(ranked):
        if len(picked) >= max_images:
            break
        entry = ranked_candidate.to_selection_entry()
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
                rejection_reason = f"download failed: {exc}"
                entry["rejection_reason"] = rejection_reason
                rejected.append({
                    "title": asset.title, "query": entry["query"],
                    "reason": rejection_reason, "provider": asset.provider,
                    "identity": entry.get("identity", ""),
                })
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
                             "audit_reason": "resolution/legibility after download",
                             "provider": asset.provider,
                             "identity": entry.get("identity", "")})
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
                             "identity": entry.get("identity", ""),
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
        if content_key.startswith("sha256:"):
            scene_content_seen.add(content_key)
        if asset_uses is not None:
            key = _selection_asset_key(entry["asset"])
            if asset_uses.get(key, 0):
                entry["reuse_reason"] = "eligible_pool_exhausted"
            record_asset_usage(asset_uses, asset_dict, entry["asset"],
                               _selection_asset_key)
        picked.append(SelectedAsset.from_dict(entry, len(picked)))
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
            picked.append(SelectedAsset.from_dict({
                "asset": synth.to_dict(),
                "query": queries[0] if queries else "",
                "relevance": 0, "order": 0,
                "score": 0.0, "strategy": "synth",
            }, len(picked)))
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
        for candidate in sorted(reused_ranked, key=lambda item: -item.score):
            entry = candidate.to_selection_entry()
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
            key = _selection_asset_key(entry["asset"])
            record_asset_usage(asset_uses, entry["asset"], entry["asset"],
                               _selection_asset_key)
            picked.append(SelectedAsset.from_dict(entry, len(picked)))
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
    synthetic = bool(picked and picked[0].asset.provider == "synth")
    message = (f"Cena {ch.id}: {returned} resultados; {len(candidates)} elegíveis; "
               f"{len(ranked)} acima do score; {len(picked)} selecionado(s); "
               f"{downloads} baixado(s), {cache_hits} cache hit(s)"
               + ("; card/diagrama" if synthetic else ""))
    run_event("fallback" if synthetic else "result", message,
              operation="media", scene=ch.id, returned=returned,
              eligible=len(candidates), above_threshold=len(ranked),
              selected=len(picked), downloaded=downloads,
              cache_hits=cache_hits, strategy=strategy_used)

    first = picked[0].asset.to_dict() if picked else None
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
    picked_rows = [entry.to_dict() for entry in picked]
    audit_candidates = candidate_audit_rows(
        evaluated_entries, rejected, picked_rows, representation_levels, min_score)
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
        "queries": search_query_audit_rows(
            search_plan, collection.query_audit, rejected, representation_levels,
            representation_kinds,
            list(video_context.get("aliases", []) or [])),
        "providers_consulted": list(collection.providers_consulted),
        "candidates": audit_candidates,
        "selected": (next((item for item in audit_candidates
                           if item["decision"] == "selected"), None)
                     or ({"title": (first or {}).get("title", ""),
                          "provider": (first or {}).get("provider", ""),
                          "reason": "No candidate passed semantic gates; rendered safe local visual"}
                         if first and (first or {}).get("provider") == "synth" else None)),
        "fallback": strategy_used if synthetic or not picked else "",
        "search_exhausted": bool(
            (not picked or picked[0].reuse_reason
             or (first or {}).get("provider") == "synth")
            and all(not state.unexecuted_reason
                    for state in collection.query_audit.values())
            and all(state.providers and not state.provider_errors
                    and not state.unavailable
                    for state in collection.query_audit.values())),
        "search_exhaustion_reason": (
            "new_asset_selected" if picked and (first or {}).get("provider") != "synth"
            and not picked[0].reuse_reason else
            "queries_not_executed" if any(
                state.unexecuted_reason
                for state in collection.query_audit.values()) else
            "provider_errors" if any(
                state.provider_errors
                for state in collection.query_audit.values()) else
            "no_available_provider" if any(
                not state.providers
                for state in collection.query_audit.values()) else
            "all_queries_consulted_no_valid_asset" if synthetic or not picked else
            "asset_reuse_after_search" if picked else ""),
        "fallback_level": ("synthetic_after_incomplete_search"
                           if (first or {}).get("provider") == "synth"
                           and (any(state.unexecuted_reason
                                    for state in collection.query_audit.values())
                                or any(state.provider_errors or not state.providers
                                       for state in collection.query_audit.values())) else
                           "synthetic_after_exhaustion"
                           if (first or {}).get("provider") == "synth" else
                           "reused" if picked and picked[0].reuse_reason else
                           "specific" if picked and picked[0].query in representation_levels
                           else "representation_or_media_variant" if picked else "exhausted"),
    }
    selection = make_selection_decision(
        ch.id, picked, decision["fallback_level"])
    decision = VisualDecision.create(selection, **decision).to_dict()
    return [{
        "chapter_id": ch.id,
        "asset": first,
        "assets": picked_rows,
        "reused_from": None,
        "rejected": scene_rejected,
        "visual_decision": decision,
        "visual_type": str(getattr(ch, "visual_type", "") or "literal"),
        "strategy": strategy_used,
    }], warnings


def fetch_media_multi(semantic_scenes: list[SemanticScene], cfg: CurioConfig,
                      max_images: int = 3,
                      metrics=None, genre: str = "") -> MediaStageResult:
    """Acquire candidates for each scene and select using its explicit plans.

    Exact queries share provider responses in a per-video in-memory cache;
    downloaded bytes live in the reusable global media cache. This function
    returns the validated stage result; project selection is recorded
    separately from both caches.
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
    
    from ..media.selection_result import MediaStageResult
    from .media_selection import annotate_reuse, resolve_cross_scene_reuse

    result = MediaStageResult.from_rows(scenes, "provider", all_warnings)
    result = resolve_cross_scene_reuse(result, semantic_scenes)
    return annotate_reuse(result)
