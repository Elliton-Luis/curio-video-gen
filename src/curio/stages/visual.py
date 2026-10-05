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
import contextvars
import functools
from collections.abc import Mapping
import os
import re
import sys
import time

from .. import ffmpeg as ff
from ..config import CurioConfig
from ..media import download_asset, get_providers
from ..media.providers import (
    MediaAsset,
    MediaError,
    MediaProvider,
    classify_rights,
    min_dimension,
)
from . import media_rules
from .visual_contracts import VisualPlan
from .visual_planning import build_visual_plan
from .search_planning import build_search_plan
from .media_contracts import Candidate, CandidateRejection
from .candidate_evaluation import evaluate_generic, evaluate_specific
from .scene_contract import SemanticScene

# Limites de concorrência para busca/baixa de mídia (configuráveis via env)
MAX_CONCURRENT_SEARCHES = int(os.environ.get("CURIO_MAX_CONCURRENT_SEARCHES", "3"))
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get("CURIO_MAX_CONCURRENT_DOWNLOADS", "2"))
SEARCH_TIMEOUT = float(os.environ.get("CURIO_MEDIA_SEARCH_TIMEOUT", "15.0"))
DOWNLOAD_TIMEOUT = float(os.environ.get("CURIO_MEDIA_DOWNLOAD_TIMEOUT", "30.0"))
_SEARCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, MAX_CONCURRENT_SEARCHES), thread_name_prefix="curio-search")
_DOWNLOAD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, MAX_CONCURRENT_DOWNLOADS), thread_name_prefix="curio-download")

# Hierarquia de provedores (ordem de prioridade). Do mais específico para
# o mais genérico: primeiro os bancos de foto com chave, depois os acervos
# abertos, e o Unsplash por ÚLTIMO — é a foto mais bonita e a que mais
# foge do assunto, então só entra quando nada mais serviu, e com orçamento
# próprio de 15 requisições (a cota demo dele é 50/hora e um vídeo estoura
# isso em duas cenas).
PROVIDER_PRIORITY = ("pixabay", "pexels", "nasa",
                     "wikimedia", "openverse", "met", "aic", "unsplash")

# Resultados de busca só vivem na memória da execução, nunca entre vídeos.
# Quantos candidatos se coleta por consulta antes de escolher. O lineup
# antigo aceitava 1 asset do primeiro provedor; recolher uma dúzia e
# ordenar é o que permite escolher em vez de tomar o que veio.
CANDIDATE_MULTIPLIER = 4
MAX_SCENE_CANDIDATES = 20
# Rejeições que a folha de contato guarda por cena (o resto é ruído).
REJECTED_KEPT = 8


def _submit_search(provider_obj, query: str, metrics=None):
    """Submit one provider search, preserving run-log context in worker."""
    context = contextvars.copy_context()

    def timed_search():
        started = time.monotonic()
        try:
            return provider_obj.search(query, 5, metrics)
        finally:
            if metrics:
                metrics.media_provider_search(
                    provider_obj.name, time.monotonic() - started)

    return _SEARCH_EXECUTOR.submit(context.run, timed_search)


def _search_with_timeout(provider_obj, query: str, timeout: float,
                         metrics=None) -> list[MediaAsset]:
    """Bound wait without executor context-manager's blocking shutdown.

    Old `with ThreadPoolExecutor` waited for worker exit while leaving the
    context, so timeout never returned at timeout. Provider HTTP calls have
    their own finite network timeout; cancel stops queued work and caller
    returns immediately. A running urllib call ends on its socket timeout.
    """
    future = _submit_search(provider_obj, query, metrics)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        if metrics:
            metrics.media_record_timeout()
        raise MediaError(f"{provider_obj.name}: busca timeout ({timeout}s)") from exc


def _submit_download(asset: MediaAsset, cache_dir: str, metrics=None):
    """Submit one download while preserving execution log context."""
    context = contextvars.copy_context()
    return _DOWNLOAD_EXECUTOR.submit(context.run, _download_with_origin,
                                     asset, cache_dir, metrics)


def _download_with_origin(asset: MediaAsset, cache_dir: str, metrics=None):
    """Download one asset and report whether bytes came from local cache."""
    from ..media.cache import _safe_ext
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", asset.asset_id) or "asset"
    path = os.path.join(cache_dir, "media", asset.provider,
                        safe_id + _safe_ext(asset.download_url))
    cached = os.path.isfile(path) and os.path.isfile(path + ".json")
    result = download_asset(asset, cache_dir, metrics)
    return result, "cache" if cached else "download"


# O gate de metadados é `media_rules.asset_gate_reason`: era a terceira
# cópia da mesma regra, e a única que devolvia booleano — o que jogava fora
# a informação que o autor precisa ("por que a cena ficou sem foto").
_validate_asset_for = media_rules.asset_gate_reason


def _probe_dims(path: str) -> tuple[int, int]:
    """Dimensões reais via ffprobe; cache por caminho, tamanho e mtime."""
    try:
        stat = os.stat(path)
    except OSError:
        return 0, 0
    return _probe_dims_cached(path, stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=512)
def _probe_dims_cached(path: str, size: int,
                       mtime_ns: int) -> tuple[int, int]:
    """Cache invalida quando imagem muda; evita repetir subprocesso ffprobe."""
    _ = size, mtime_ns
    try:
        proc = ff.run([ff.FFPROBE, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height",
                       "-of", "csv=p=0", path])
        if proc.returncode == 0:
            w, h = proc.stdout.strip().split(",")[:2]
            return int(w), int(h)
    except (OSError, ValueError):
        pass
    return 0, 0


def _downloaded_dims_ok(asset: MediaAsset) -> bool:
    """Confere arquivo real pós-download; atualiza o asset (p/ o cache)."""
    try:
        size = os.path.getsize(asset.local_path)
    except OSError:
        return False
    if size <= 10000:
        return False
    asset.size_bytes = max(asset.size_bytes, size)
    if asset.width > 0 and asset.height > 0:
        return True  # já validado nos metadados
    w, h = _probe_dims(asset.local_path)
    if w <= 0 or h <= 0:
        return False  # ilegível: o render quebraria depois
    asset.width, asset.height = w, h
    return min(w, h) >= min_dimension()


def _provider_priority_order(cfg: CurioConfig, ch=None,
                            genre: str = "", providers=None) -> list[MediaProvider]:
    """Provedores na ordem de prioridade para ESTA cena.

    Para `historical_art` os museus e acervos sobem: uma foto de banco
    moderno é pior que nenhuma imagem para um santo do século XIII, e o
    Met/AIC/Wikimedia guardam pintura, fresco, escultura e objeto antigo em
    domínio público sem chave. A ordem global continua valendo para os
    demais tipos - a escada é por cena, não uma preferência permanente.
    """
    all_providers = list(providers) if providers is not None else get_providers(cfg)
    order = list(PROVIDER_PRIORITY)
    from . import editorial
    adapter = editorial.get(genre or getattr(cfg, "genre", ""))
    adapter_priority = list(adapter.media_provider_priority) if adapter else []
    plan = (ch if isinstance(ch, VisualPlan) else
            build_visual_plan(ch.semantic_scene()
                              if hasattr(ch, "semantic_scene") else ch))
    visual_type = plan.visual_type
    historical_scene = plan.historical_scene
    space_topic = plan.space_topic
    if historical_scene:
        adapter_priority = ["met", "aic", "wikimedia", "openverse"]
        order = adapter_priority + [p for p in order if p not in adapter_priority]
    if space_topic or visual_type == "mechanism":
        order = ["nasa", "wikimedia", "openverse", "pixabay", "pexels",
                 "met", "aic", "unsplash"]
    if adapter_priority:
        art_first = [p for p in adapter_priority if p in order]
        order = art_first + [p for p in order if p not in art_first]
    priority_map = {name: i for i, name in enumerate(order)}
    return sorted(all_providers, key=lambda p: priority_map.get(p.name, 999))


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
        synth = visuals.visual_for_scene(ch, cfg.cache_dir,
                                         getattr(cfg, "language", "pt-BR"),
                                         visual_state, genre)
        if synth is not None:
            if metrics:
                metrics.media_record_visual_type(vtype)
                metrics.media_record_fallback("card")
                metrics.media_synth_diagrams += 1
            from ..runlog import event as run_event
            run_event("fallback", f"Cena {ch.id}: card tipográfico",
                      operation="media", scene=ch.id, strategy="card")
            return [{
                "chapter_id": ch.id,
                "asset": synth.to_dict(),
                "assets": [{"asset": synth.to_dict(), "query": "",
                            "relevance": 0, "order": 0,
                            "score": 0.0, "strategy": "card"}],
                "reused_from": None,
                "rejected": [],
                "visual_type": vtype,
                "strategy": "card",
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
        candidates.append(candidate.to_evaluation_input())

    from . import scoring
    from .media_selection import make_selection_decision, prepare_selection_pool
    min_score = scoring.threshold()

    def collect(query_list: list[str], limit: int,
                stop_when_proven: bool = False) -> None:
        for query_index, query in enumerate(query_list):
            if len(candidates) >= MAX_SCENE_CANDIDATES:
                for pending in query_list[query_index:]:
                    unexecuted_queries.setdefault(pending, "scene_candidate_budget")
                break
            candidates_before_query = len(candidates)
            query_key = query.casefold()
            identities_before = len(seen_ids)
            duplicates_before = duplicate_candidates
            rejected_before = len(rejected)
            shared = (shared_search_cache.setdefault(query_key, {})
                      if shared_search_cache is not None else {})
            active = [prov for prov in providers
                      if not getattr(prov, "_disabled", False)]
            scene_order = [p.name for p in
                           _provider_priority_order(cfg, visual_plan, genre, providers)]
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
            tasks = []
            for prov in active:
                if prov.name in shared:
                    tasks.append((prov, None,
                                  [MediaAsset.from_dict(item)
                                   for item in shared[prov.name]]))
                else:
                    tasks.append((prov, _submit_search(prov, query, metrics), None))
            deadline = time.monotonic() + SEARCH_TIMEOUT
            # Wait in provider-priority order, even though requests run at
            # once. Candidate order and tie-breaks remain deterministic.
            for prov, future, cached_results in tasks:
                if (len(candidates) >= MAX_SCENE_CANDIDATES
                        or len(candidates) - candidates_before_query >= limit):
                    for _later_provider, later, _cached in tasks:
                        if later is not None:
                            later.cancel()
                    break
                if cached_results is not None:
                    results = cached_results
                    if metrics:
                        metrics.media_record_funnel("shared_search_hits")
                else:
                    try:
                        remaining = max(0.0, deadline - time.monotonic())
                        results = future.result(timeout=remaining)
                    except concurrent.futures.TimeoutError:
                        future.cancel()
                        query_audit[query]["errors_by_provider"][prov.name] = "timeout"
                        if metrics:
                            metrics.media_record_timeout()
                        continue
                    except MediaError as exc:
                        query_audit[query]["errors_by_provider"][prov.name] = str(exc)
                        if (any(code in str(exc) for code in ("429", "401", "403"))
                                or "Too Many Requests" in str(exc)):
                            prov._disabled = True
                            if metrics:
                                metrics.media_record_timeout()
                            from ..runlog import event as run_event
                            logged = run_event(
                                "fallback", f"{prov.name}: provider desativado; {exc}",
                                operation="media_search", provider=prov.name,
                                error=str(exc))
                            if not logged:
                                print(f"AVISO: {prov.name} desativado nesta execução ({exc})",
                                      file=sys.stderr)
                        continue
                    if shared_search_cache is not None:
                        shared[prov.name] = [result.to_dict() for result in results]
                    if metrics:
                        metrics.media_record_results(prov.name, len(results))
                        metrics.media_record_funnel("normalized_returned", len(results))
                query_audit[query]["results"] += len(results)
                query_audit[query]["by_provider"][prov.name] = (
                    query_audit[query]["by_provider"].get(prov.name, 0) + len(results))
                for result_index, cand in enumerate(results):
                    if len(candidates) >= limit:
                        if metrics:
                            metrics.media_record_funnel(
                                "budget_unexamined", len(results) - result_index)
                        break
                    _consider(cand, query)
            if (len(seen_ids) == identities_before
                    and duplicate_candidates > duplicates_before):
                abandoned_duplicate_queries.add(query)
                if metrics:
                    metrics.media_duplicate_queries += 1
            if stop_when_proven:
                # A contextual result already selected elsewhere is not
                # evidence that this scene has an adequate fresh result.
                fresh = [entry for entry in candidates
                         if not asset_uses or not asset_uses.get(
                             _selection_asset_key(entry["asset"]), 0)]
                score_started = time.monotonic()
                checked = [item.to_selection_entry() for item in evaluate_specific(
                    [entry for entry in fresh if not entry["generic"]],
                    ch, min_score).accepted]
                if metrics:
                    metrics.media_selection_time += time.monotonic() - score_started
                if any(entry.get("score", 0) >= min_score
                       and entry.get("score_detail", {}).get("topic_relevance") == 100
                       and entry.get("score_detail", {}).get("scene_relevance", 0) >= 70
                       for entry in checked):
                    for pending in query_list[query_index + 1:]:
                        unexecuted_queries.setdefault(pending, "fresh_match_proven")
                    break

    # Colete e pontue específicos antes de buscar fotos genéricas do gênero.
    # Generic queries só rodam quando nenhuma foto específica passa o gate.
    specific_queries = [q for q in queries if q.lower() not in generics]
    generic_queries = [q for q in queries if q.lower() in generics]
    # Bound each query, then keep exploring later representations unless a
    # strong fresh result proves sufficient. The scene-wide cap prevents an
    # oversized provider response from multiplying downloads without bound.
    phase_budget = max(1, max_images * CANDIDATE_MULTIPLIER)
    collect(specific_queries, phase_budget, stop_when_proven=True)
    score_started = time.monotonic()
    specific_result = evaluate_specific(
        [entry for entry in candidates if not entry["generic"]], ch, min_score)
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
            [entry for entry in candidates if entry["generic"]], ch, min_score)
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
                    asset = download_asset(MediaAsset.from_dict(entry["asset"]),
                                           cfg.cache_dir, metrics)
                    if not _downloaded_dims_ok(asset):
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
    download_window = min(max(1, MAX_CONCURRENT_DOWNLOADS), max(1, max_images))
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
            download_futures[index] = _submit_download(
                candidate, cfg.cache_dir, metrics)

    fill_download_window()
    for rank_index, entry in enumerate(ranked):
        if len(picked) >= max_images:
            break
        asset_dict = entry["asset"]
        if metrics:
            metrics.media_record_funnel("selected")
            metrics.media_selected_ids.add(asset_key(asset_dict))
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
                    future = _submit_download(asset, cfg.cache_dir, metrics)
                asset, acquisition = future.result(timeout=DOWNLOAD_TIMEOUT)
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
        if not _downloaded_dims_ok(asset):
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
            asset_uses[key] = asset_uses.get(key, 0) + 1
        if metrics:
            metrics.media_record_funnel("used_real")

    if not picked and visual_plan.mechanistic:
        synth = _synth_diagram_for_scene(ch, queries, cfg, metrics, genre)
        if synth is not None:
            picked.append(synth)
            seen_ids.add(synth["asset"]["asset_id"])
    strategy_used = "image"
    if not picked:
        # Nenhuma fotografia serviu. A cena NÃO fica vazia e NÃO recebe
        # imagem genérica: ela troca de medium. Um diagrama ou um cartão
        # é a cena certa mostrada do jeito certo, e a métrica registra
        # como estratégia, não como falha.
        from . import visuals
        synth = visuals.visual_for_scene(ch, cfg.cache_dir,
                                         getattr(cfg, "language", "pt-BR"),
                                         visual_state, genre)
        if synth is not None:
            picked.append({"asset": synth.to_dict(),
                           "query": queries[0] if queries else "",
                            "relevance": 0, "order": 0,
                            "score": 0.0, "strategy": "synth"})
            strategy_used = ("diagram"
                             if synth.title.startswith("Diagrama")
                             else synth.title.split(" — ")[0].lower())
            if metrics:
                metrics.media_record_fallback(strategy_used)
                metrics.media_synth_diagrams += 1
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
                    asset, acquisition = download_asset(asset, cfg.cache_dir, metrics)
                else:
                    acquisition = "cache"
            except MediaError:
                continue
            if not _downloaded_dims_ok(asset):
                continue
            asset.used_in = f"cena {ch.id}"
            entry = dict(entry, asset=asset.to_dict(), acquisition=acquisition,
                         reuse_reason="fresh_search_and_synthetic_exhausted")
            picked.append(entry)
            key = _selection_asset_key(entry["asset"])
            asset_uses[key] = asset_uses.get(key, 0) + 1
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
    audit_candidates = []
    for entry in evaluated_entries:
        detail = entry.get("score_detail", {})
        selected_item = next((item for item in picked
            if (item.get("asset", {}).get("provider"),
                item.get("asset", {}).get("asset_id")) ==
               ((entry.get("asset") or {}).get("provider"),
                (entry.get("asset") or {}).get("asset_id"))), None)
        was_selected = selected_item is not None
        audit_candidates.append({
            "title": str((entry.get("asset") or {}).get("title", ""))[:160],
            "provider": (entry.get("asset") or {}).get("provider", ""),
            "query": entry.get("query", ""),
            "query_level": representation_levels.get(
                entry.get("query", ""), 5 if entry.get("generic") else 3),
            "topic_relevance": detail.get("topic_relevance"),
            "scene_relevance": detail.get("scene_relevance"),
            "score": entry.get("score", 0), "bonus": detail.get("bonus", 0),
            "clip_score": entry.get("clip_score"),
            "creator": str((entry.get("asset") or {}).get("author", ""))[:120],
            "source_url": str((entry.get("asset") or {}).get("source_url", ""))[:300],
            "date_created": (entry.get("asset") or {}).get("date_created", ""),
            "media_type": (entry.get("asset") or {}).get("media_type", "image"),
            "metadata_support": detail.get("metadata_support", 0.0),
            "topic_evidence": detail.get("topic_evidence", {}),
            "scene_evidence": detail.get("scene_evidence", {}),
            "provider": (entry.get("asset") or {}).get("provider", ""),
            "creator": str((entry.get("asset") or {}).get("author", ""))[:120],
            "source_url": str((entry.get("asset") or {}).get("source_url", ""))[:300],
            "date_created": (entry.get("asset") or {}).get("date_created", ""),
            "media_type": (entry.get("asset") or {}).get("media_type", "image"),
            "decision": ("selected" if was_selected else
                         "rejected" if (entry.get("rejection_reason")
                                        or detail.get("semantic_rejection")
                                        or entry.get("score", 0) < min_score)
                         else "not_selected"),
            "reason": (("reused only after fresh searches and local visual exhausted"
                        if selected_item and selected_item.get("reuse_reason") else
                        "selected by scene relevance, topic relevance, then quality")
                       if was_selected else entry.get("rejection_reason")
                       or detail.get("semantic_rejection")
                       or ("score below threshold"
                           if entry.get("score", 0) < min_score
                           else "passed gate; ranked below image limit")),
        })
    decision = {
        "topic": video_context.get("topic", ""),
        "visual_plan": visual_plan.to_dict(),
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
                                "not_consulted_after_fresh_match"
                                if unexecuted_queries.get(query) == "fresh_match_proven" else
                                "abandoned_duplicates"
                                if query in abandoned_duplicate_queries else
                                "consulted" if query_providers.get(query)
                                else "no_provider_results"),
                     "unexecuted_reason": unexecuted_queries.get(query, "")}
                    for query in queries],
        "providers_consulted": sorted(providers_consulted),
        "candidates": (audit_candidates + [{"title": item.get("title", ""),
            "provider": item.get("provider", ""), "query": item.get("query", ""),
            "topic_relevance": item.get("topic_relevance"),
            "scene_relevance": item.get("scene_relevance"),
            "creator": str((item.get("asset") or {}).get("author", ""))[:120],
            "source_url": str((item.get("asset") or {}).get("source_url", ""))[:300],
            "date_created": (item.get("asset") or {}).get("date_created", ""),
            "media_type": (item.get("asset") or {}).get("media_type", "image"),
            "decision": "rejected", "reason": item.get("reason", "")}
            for item in rejected if not any(a["title"] == item.get("title")
                                           for a in audit_candidates)])[:40],
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


def _synth_diagram_for_scene(ch, queries: list[str], cfg: CurioConfig,
                             metrics, genre: str = "") -> dict | None:
    """Gera diagrama de tira de teste p/ cena de mecanismo (offline).

    Retorna a entrada `picked` pronta ou None (PIL ausente/falha).

    O gênero entra porque a tira é desenhada por PIL com texto, e texto
    sem papel tipográfico sai na sans pesada de sempre — que é
    exatamente o que este projeto deixou de fazer.
    """
    try:
        from . import diagram as diagram_stage
    except ImportError as exc:
        print(f"AVISO: diagrama sintético indisponível ({exc}).",
              file=sys.stderr)
        return None
    try:
        terms = " ".join(queries[:2]) or ch.narration[:60]
        from . import typography as typo_stage
        asset = diagram_stage.render_strip_diagram(
            terms, cfg.cache_dir,
            language=getattr(cfg, "language", "pt-BR"),
            typo=typo_stage.for_genre(genre))
    except Exception as exc:  # noqa: BLE001 — fallback honesto abaixo
        print(f"AVISO: diagrama sintético falhou ({exc}).", file=sys.stderr)
        return None
    if metrics:
        metrics.media_record_synth()
    asset.used_in = f"cena {ch.id}"
    return {"asset": asset.to_dict(), "query": terms,
            "relevance": 50, "order": 0}


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
        for prov in _provider_priority_order(cfg, scene, genre):
            if prov.name not in seen_names:
                seen_names.add(prov.name)
                providers.append(prov)
    # An empty provider list still uses the per-scene synthetic fallback.
    # Do not copy an unrelated neighbor's asset merely to fill the timeline.
    all_warnings = []
    scenes = []
    # O estado de variedade atravessa as cenas: é ele que impede seis cenas
    # conceituais de virarem seis cards idênticos.
    from . import visuals as _visuals
    visual_state = _visuals.VisualState()
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
        eligible = []
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
                    eligible.append((donor, entry, relevance))
        if not eligible:
            continue
        donor, donor_entry, relevance = min(eligible, key=lambda item: (
            -item[2]["scene_relevance"],
            abs(item[0]["chapter_id"] - cid),
            0 if item[0]["chapter_id"] < cid else 1))
        nearest = donor
        s["assets"] = [dict(entry, order=i)
                       for i, entry in enumerate(nearest["assets"])]
        s["asset"] = s["assets"][0]["asset"]
        s["reused_from"] = nearest["chapter_id"]
        if isinstance(s.get("visual_decision"), dict):
            reused_asset = donor_entry.get("asset") or {}
            s["visual_decision"]["fallback"] = "validated_reuse"
            s["visual_decision"]["selected"] = {
                "title": reused_asset.get("title", ""),
                "provider": reused_asset.get("provider", ""),
                "topic_relevance": relevance.get("topic_relevance"),
                "scene_relevance": relevance.get("scene_relevance"),
                "reason": f"validated topic and scene evidence from scene {nearest['chapter_id']}",
            }
        print(f"AVISO: cena {cid} reusa imagem(ns) da cena "
              f"{nearest['chapter_id']} (sem mídia própria).", file=sys.stderr)
