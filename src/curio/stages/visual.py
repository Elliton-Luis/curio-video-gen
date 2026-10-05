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

import sys
import time
from typing import TYPE_CHECKING

from ..config import CurioConfig
from ..media.selection_result import SceneMediaSelection, SelectedAsset
from ..media.providers import MediaProvider
from ..media.visual_decision import VisualDecision
from . import media_rules
from .visual_contracts import SearchPlan, VisualPlan
from .visual_planning import build_visual_plan
from .search_planning import build_search_plan
from .candidate_evaluation import (apply_clip_layer,
                                  describe_technical_rejections,
                                  evaluate_generic, evaluate_specific)
from .media_selection import (annotate_reuse, make_selection_decision,
                              RankedSelectionCandidate,
                              prepare_selection_pool,
                              resolve_cross_scene_reuse,
                              SelectionFallbackAction,
                              next_selection_fallback,
                              describe_selection_provenance)
from .media_selection import SelectionDecision
from .visual_audit import (build_scene_visual_decision,
                           candidate_rejection_rows)
from .media_contracts import CandidateEvaluation
from .media_provider_policy import ordered_providers
from .scene_contract import SemanticScene
from .scene_candidate_search import SceneCandidateCollector

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
    visual_plan: VisualPlan,
    search_plan: SearchPlan,
    providers: list[MediaProvider],
    cfg: CurioConfig,
    max_images: int,
    metrics,
    cache_dir: str,
    visual_state=None,
    genre: str = "",
    asset_uses: dict | None = None,
    shared_search_cache: dict | None = None,
) -> tuple[SceneMediaSelection, list[str]]:
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
    if not isinstance(visual_plan, VisualPlan):
        raise TypeError("scene search requires a VisualPlan")
    if not isinstance(search_plan, SearchPlan):
        raise TypeError("scene search requires a SearchPlan")
    if visual_plan.scene_id != ch.id or search_plan.scene_id != ch.id:
        raise ValueError("scene search plans must belong to the searched scene")
    results_before = sum(metrics.media_results_received.values()) if metrics else 0
    downloads_before = metrics.media_downloads if metrics else 0
    cache_before = metrics.media_cache_hits if metrics else 0
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
            selected_asset = SelectedAsset.from_dict({
                "asset": synth.to_dict(), "query": "", "relevance": 0,
                "order": 0, "score": 0.0,
                "strategy": fallback_plan.strategy,
            }, 0)
            from ..runlog import event as run_event
            run_event("fallback", f"Cena {ch.id}: form tipográfico ({fallback_plan.form})",
                      operation="media", scene=ch.id,
                      strategy=fallback_plan.strategy, form=fallback_plan.form,
                      reason=fallback_plan.reason)
            return SceneMediaSelection.from_components(
                ch.id, (selected_asset,), visual_decision,
                visual_type=vtype, strategy=fallback_plan.strategy), warnings

    from . import scoring
    min_score = scoring.threshold()
    # Colete e pontue específicos antes das queries genéricas. A busca genérica
    # também pode ser necessária se o melhor candidato específico falhar ao
    # adquirir bytes ou passar pela validação técnica pós-download.
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
    low_specific = specific_result.rejected
    evaluations = [*specific_result.accepted, *specific_result.rejected]
    fresh_specific = [entry for entry in specific_ranked
                      if not asset_uses or not asset_uses.get(
                          _selection_asset_key(entry.asset.to_dict()), 0)]
    deferred_specific = [entry for entry in specific_ranked
                         if entry not in fresh_specific]
    generic_collected = False
    if fresh_specific:
        ranked_candidates, low = specific_ranked, low_specific
    else:
        collection = collector.collect(generic_queries, phase_budget)
        generic_collected = True
        candidates = list(collection.candidates)
        score_started = time.monotonic()
        generic_result = evaluate_generic(
            [candidate for candidate in candidates
             if candidate.search_query.generic], ch, min_score)
        if metrics:
            metrics.media_selection_time += time.monotonic() - score_started
        ranked_candidates = [RankedSelectionCandidate.from_evaluation(item)
                             for item in generic_result.accepted]
        low_generic = generic_result.rejected
        evaluations.extend((*generic_result.accepted, *generic_result.rejected))
        low = low_specific + low_generic
        # Preserve qualified used results solely for the final fallback after
        # fresh contextual results and synthetic visuals have been tried.
        ranked_candidates.extend(deferred_specific)
    collection = collector.snapshot()
    technical_rejections = list(
        describe_technical_rejections(collection.rejected, ch))
    acquisition_rejections = []
    ranked_candidates = apply_clip_layer(
        ranked_candidates, ch, cfg, metrics, max_images)

    def record_low_rejections(entries: tuple[CandidateEvaluation, ...]):
        if not metrics:
            return
        for _evaluation in entries:
            metrics.media_record_asset_rejected()
            metrics.media_record_funnel("score_rejected")

    record_low_rejections(low)
    selection_pool = prepare_selection_pool(
        ranked_candidates, asset_uses, _selection_asset_key)
    ranked = list(selection_pool.fresh)
    reused_ranked = list(selection_pool.reused)
    if metrics:
        metrics.media_record_selection(len(candidates), len(ranked))
        metrics.media_record_funnel("above_threshold", len(ranked))
    for rej in technical_rejections:
        if metrics:
            metrics.media_record_rejection(rej.reason)
    for evaluation in low:
        if metrics:
            metrics.media_record_rejection(
                evaluation.rejection_reason
                or evaluation.evidence.get("semantic_rejection")
                or "score threshold")
    # A estratégia da cena é registrada mesmo quando ela dá certo: o
    # relatório precisa mostrar a distribuição (item 20), e um diagrama
    # não pode ser contado como falha.
    if metrics:
        metrics.media_record_visual_type(
            str(getattr(ch, "visual_type", "") or "literal"))

    from .media_candidate_acquisition import acquire_ranked_candidates

    acquisition_batch = acquire_ranked_candidates(
        ch.id, ranked, max_images, cfg.cache_dir, metrics, asset_uses)
    picked: list[SelectedAsset] = [
        outcome.to_selected_asset() for outcome in acquisition_batch.selected]
    acquisition_rejections.extend(acquisition_batch.rejected)
    warnings.extend(acquisition_batch.warnings)

    # Generic/context representations are the next search tier, not an excuse
    # to stop after a score-only candidate that could not be acquired.
    fallback_action = next_selection_fallback(
        selected_count=len(picked), requested_count=max_images,
        contextual_available=bool(generic_queries),
        contextual_searched=generic_collected, synthetic_attempted=False,
        reuse_available=bool(reused_ranked))
    if fallback_action is SelectionFallbackAction.CONTEXTUAL_SEARCH:
        collection = collector.collect(generic_queries, phase_budget)
        generic_collected = True
        generic_candidates = [candidate for candidate in collection.candidates
                              if candidate.search_query.generic]
        score_started = time.monotonic()
        generic_result = evaluate_generic(
            generic_candidates, ch, min_score)
        if metrics:
            metrics.media_selection_time += time.monotonic() - score_started
        generic_ranked = [RankedSelectionCandidate.from_evaluation(item)
                          for item in generic_result.accepted]
        generic_ranked = apply_clip_layer(
            generic_ranked, ch, cfg, metrics, max_images)
        generic_low = generic_result.rejected
        evaluations.extend((*generic_result.accepted, *generic_result.rejected))
        record_low_rejections(generic_low)

        previous_rejection_ids = {
            item.candidate.identity for item in technical_rejections}
        previous_rejection_ids.update(item.candidate.identity
                                      for item in evaluations
                                      if not item.accepted)
        previous_rejection_ids.update(
            item.candidate.evaluation.candidate.identity
            for item in acquisition_rejections)
        collection = collector.snapshot()
        additional_technical_rejections = describe_technical_rejections(
            collection.rejected, ch)
        new_technical_rejections = tuple(
            item for item in additional_technical_rejections
            if item.candidate.identity not in previous_rejection_ids)
        technical_rejections = list(additional_technical_rejections)
        candidates = list(collection.candidates)

        generic_pool = prepare_selection_pool(
            generic_ranked, asset_uses, _selection_asset_key)
        generic_fresh = list(generic_pool.fresh)
        reused_ranked.extend(generic_pool.reused)
        if metrics:
            metrics.media_record_selection(len(generic_candidates), len(generic_fresh))
            metrics.media_record_funnel("above_threshold", len(generic_fresh))
        for item in new_technical_rejections:
            if metrics:
                metrics.media_record_rejection(item.reason)
        for evaluation in generic_low:
            if metrics:
                metrics.media_record_rejection(
                    evaluation.rejection_reason
                    or evaluation.evidence.get("semantic_rejection")
                    or "score threshold")

        if generic_fresh:
            generic_batch = acquire_ranked_candidates(
                ch.id, generic_fresh, max_images - len(picked), cfg.cache_dir,
                metrics, asset_uses, selected_order_start=len(picked))
            picked.extend(outcome.to_selected_asset()
                          for outcome in generic_batch.selected)
            acquisition_rejections.extend(generic_batch.rejected)
            warnings.extend(generic_batch.warnings)
            ranked.extend(generic_fresh)

    strategy_used = "image"
    fallback_action = next_selection_fallback(
        selected_count=len(picked), requested_count=max_images,
        contextual_available=bool(generic_queries),
        contextual_searched=generic_collected, synthetic_attempted=False,
        reuse_available=bool(reused_ranked))
    if fallback_action is SelectionFallbackAction.SYNTHETIC:
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
    fallback_action = next_selection_fallback(
        selected_count=len(picked), requested_count=max_images,
        contextual_available=bool(generic_queries),
        contextual_searched=generic_collected, synthetic_attempted=True,
        reuse_available=bool(reused_ranked))
    if fallback_action is SelectionFallbackAction.REUSE:
        from .media_candidate_acquisition import acquire_reuse_fallback
        reuse_outcome = acquire_reuse_fallback(
            ch.id, reused_ranked, cfg.cache_dir, metrics, asset_uses)
        if reuse_outcome is not None:
            picked.append(reuse_outcome.to_selected_asset())
    if not picked:
        msg = (f"cena {ch.id}: sem imagem adequada "
               f"({', '.join(queries[:3]) or 'sem consultas'})"
               + (f" — {sum(not item.accepted for item in evaluations) + len(technical_rejections) + len(acquisition_rejections)} candidato(s) rejeitados"
                  if any(not item.accepted for item in evaluations)
                  or technical_rejections or acquisition_rejections else "")
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

    scene_rejected = candidate_rejection_rows(
        tuple(evaluations), tuple(technical_rejections),
        tuple(acquisition_rejections))[:REJECTED_KEPT]
    selection_provenance = describe_selection_provenance(
        tuple(picked), visual_plan, search_plan, collection.query_audit)
    selection = make_selection_decision(
        ch.id, picked, selection_provenance.fallback_level)
    visual_decision = build_scene_visual_decision(
        selection=selection, selection_provenance=selection_provenance,
        scene=ch, visual_plan=visual_plan, search_plan=search_plan,
        collection=collection, evaluations=tuple(evaluations),
        technical_rejections=tuple(technical_rejections),
        acquisition_rejections=tuple(acquisition_rejections),
        picked=tuple(picked), min_score=min_score,
        fallback_plan=(fallback_plan
                       if synthetic and "fallback_plan" in locals() else None),
        strategy=strategy_used)
    return SceneMediaSelection.from_components(
        ch.id, tuple(picked), visual_decision,
        visual_type=str(getattr(ch, "visual_type", "") or "literal"),
        strategy=strategy_used, rejected=tuple(scene_rejected)), warnings


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
    # An empty provider list still uses the per-scene synthetic fallback.
    # Do not copy an unrelated neighbor's asset merely to fill the timeline.
    all_warnings = []
    scene_selections = []
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
        planning_started = time.monotonic()
        scene_plan = build_visual_plan(scene.semantic_scene()
                                       if hasattr(scene, "semantic_scene") else scene)
        search_plan = build_search_plan(scene_plan, genre)
        if metrics:
            metrics.media_query_generation_time += time.monotonic() - planning_started
        providers = ordered_providers(cfg, scene_plan, genre)
        scene_selection, scene_warnings = _search_scene_with_shortcircuit(
            scene, scene_plan, search_plan, providers, cfg, max_images,
            metrics, cfg.cache_dir,
            visual_state=visual_state, genre=genre, asset_uses=asset_uses,
            shared_search_cache=shared_search_cache,
        )
        scene_selections.append(scene_selection)
        all_warnings.extend(scene_warnings)
    
    from ..media.selection_result import MediaStageResult
    from .media_selection import annotate_reuse, resolve_cross_scene_reuse

    result = MediaStageResult(tuple(scene_selections), "provider",
                              tuple(all_warnings))
    result = resolve_cross_scene_reuse(result, semantic_scenes)
    return annotate_reuse(result)
