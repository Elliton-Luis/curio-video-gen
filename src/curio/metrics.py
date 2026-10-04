"""Metrificação por vídeo: consumo, tempo e informações gerais.

Cada execução (generate/finalize) grava `metrics/<timestamp>_<slug>.json` com:
- tempos (total + por etapa), durações e tamanhos de arquivo;
- consumo externo real: chamadas NVIDIA + tokens, TTS (chamadas/chars),
  mídia (buscas/downloads/bytes/cache), Whisper;
- provedores/modelos, contagens (cenas, cues, palavras) e avisos.
Nada aqui contém segredos (sem chaves).
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from .media.selection_metrics import MediaSelectionStats


def utcnow_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


class RunMetrics:
    """Coletor explícito de consumo. Criado por execução, passado aos estágios."""

    def __init__(self, slug: str, idea: str, narration: str):
        # Media search/download workers can update one collector concurrently.
        self._lock = threading.RLock()
        self.slug = slug
        self.idea = idea
        self.narration = narration
        self.started_at = utcnow_iso()
        self.started_monotonic = time.monotonic()
        self.nvidia_calls = 0
        self.nvidia_prompt_tokens = 0
        self.nvidia_completion_tokens = 0
        self.nvidia_models: list[str] = []
        self.tts_calls: list[dict] = []
        self.media_searches: dict[str, int] = {}
        self.media_downloads = 0
        self.media_bytes = 0
        self.media_cache_hits = 0
        self.whisper_calls = 0
        self.whisper_model = ""
        # Detailed media metrics
        self.media_query_generation_time = 0.0
        self.media_provider_search_time: dict[str, float] = {}
        self.media_downloads_time = 0.0
        self.media_selection_time = 0.0
        self.media_deduplication_time = 0.0
        self.media_queries_count = 0
        self.media_requests_per_provider: dict[str, int] = {}
        self.media_time_per_request: dict[str, list[float]] = {}
        self.media_results_received: dict[str, int] = {}
        # Diagnóstico POR PROVEDOR do download. A pergunta que a execução
        # de São Jerônimo deixou em aberto era "o Pixabay está quebrado,
        # ou está achando candidato e falhando no download?", e as duas
        # coisas produzem a mesma linha de log — "download falhou
        # (HTTP 403)" — várias vezes. Só de contar as duas separadas dá
        # para saber qual é.
        self.media_download_attempted: dict[str, int] = {}
        self.media_download_succeeded: dict[str, int] = {}
        self.media_download_failed: dict[str, int] = {}
        self.media_download_http_403: dict[str, int] = {}
        self.media_download_other_error: dict[str, int] = {}
        self.media_cache_misses = 0
        self.media_assets_rejected = 0
        self.media_assets_reused = 0
        self.media_timeouts = 0
        self.media_retries = 0
        self.media_synth_diagrams = 0
        self.media_rights_verify = 0
        self.media_rights_blocked = 0
        # Cenas que terminaram sem nenhum visual (a única falha real).
        self.media_scenes_no_visual = 0
        # Seleção: candidatos vistos, mantidos, e o motivo de cada descarte.
        self.media_candidates_total = 0
        self.media_candidates_kept = 0
        self.media_rejections: dict[str, int] = {}
        self.media_funnel: dict[str, int] = {}
        # Estratégia visual por cena. Um diagrama ou cartão NÃO é falha:
        # é a cena certa visualizada do jeito certo.
        self.media_visual_types: dict[str, int] = {}
        self.media_fallbacks: dict[str, int] = {}
        self.media_score_sum = 0.0
        self.media_scored_count = 0
        self.media_low_score = 0
        # Camadas opcionais (clip/vision) e dispositivo usado.
        self.media_layers_used: dict[str, int] = {}
        self.media_layer_device = ""
        self.research_queries = 0
        self.research_sources = 0
        self.research_complementary_queries = 0
        self.research_rejected: dict[str, int] = {}
        self.visual_scene_count = 0
        self.visual_beat_count = 0
        self.visual_beat_seconds = 0.0
        self.visual_asset_uses = 0
        self.visual_asset_ids: set[str] = set()
        self.media_selected_ids: set[str] = set()
        self.media_available_ids: set[str] = set()
        self.media_available_acquisitions: dict[str, int] = {}
        self.visual_asset_beat_counts: dict[str, int] = {}
        self.visual_asset_scene_counts: dict[str, int] = {}
        self.visual_asset_details: dict[str, dict] = {}
        self.media_scene_decisions: dict[str, dict] = {}
        self.media_scenes_new_asset = 0
        self.media_scenes_reused_asset = 0
        self.media_scenes_synthetic = 0
        self.media_unique_assets = 0
        self.media_reuse_count = 0
        self.media_duplicate_queries = 0
        self.media_real_asset_occurrences = 0
        self.media_selection_stats: MediaSelectionStats | None = None

    # -- registros (chamados pelos estágios; nunca falham a execução) --
    def nvidia(self, model: str, usage: dict | None) -> None:
        self.nvidia_calls += 1
        if model not in self.nvidia_models:
            self.nvidia_models.append(model)
        usage = usage or {}
        self.nvidia_prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.nvidia_completion_tokens += int(usage.get("completion_tokens") or 0)

    def tts(self, provider: str, chars: int) -> None:
        self.tts_calls.append({"provider": provider, "chars": chars})

    def media_search(self, provider: str) -> None:
        with self._lock:
            self.media_searches[provider] = self.media_searches.get(provider, 0) + 1
            self.media_requests_per_provider[provider] = (
                self.media_requests_per_provider.get(provider, 0) + 1)

    def media_download(self, bytes_: int, cached: bool) -> None:
        with self._lock:
            if cached:
                self.media_cache_hits += 1
            else:
                self.media_downloads += 1
                self.media_bytes += bytes_
                self.media_cache_misses += 1

    def media_record_results(self, provider: str, count: int) -> None:
        self.media_results_received[provider] = self.media_results_received.get(provider, 0) + count

    def media_download_started(self, provider: str) -> None:
        with self._lock:
            self.media_download_attempted[provider] = (
                self.media_download_attempted.get(provider, 0) + 1)

    def media_download_ok(self, provider: str) -> None:
        with self._lock:
            self.media_download_succeeded[provider] = (
                self.media_download_succeeded.get(provider, 0) + 1)

    def media_download_error(self, provider: str, exc: BaseException
                             ) -> None:
        """Conta a falha e separa o 403, que é um caso próprio.

        403 do Pixabay costuma ser a URL de download exigindo requisição
        diferente, ou o hotlink bloqueado — não é o provedor fora do ar
        nem a chave inválida. Tratar "403" como "erro qualquer" esconde a
        diferença entre "está Achando bom e baixando mal" e "não acha
        nada", que são correções opostas.
        """
        with self._lock:
            self.media_download_failed[provider] = (
                self.media_download_failed.get(provider, 0) + 1)
            alvo = self.media_download_http_403
            for parte in str(exc).split():
                if "403" in parte:
                    alvo[provider] = alvo.get(provider, 0) + 1
                    return
            self.media_download_other_error[provider] = (
                self.media_download_other_error.get(provider, 0) + 1)

    def media_download_report(self) -> dict:
        """O resumo por provedor que responde "está quebrado ou vazio?"."""
        nomes = set(self.media_download_attempted) | \
            set(self.media_download_failed) | set(self.media_results_received)
        out = {}
        for nome in sorted(nomes):
            tentados = self.media_download_attempted.get(nome, 0)
            ok = self.media_download_succeeded.get(nome, 0)
            out[nome] = {
                "candidates_found": self.media_results_received.get(nome, 0),
                "downloads_attempted": tentados,
                "downloads_succeeded": ok,
                "downloads_failed": self.media_download_failed.get(nome, 0),
                "http_403": self.media_download_http_403.get(nome, 0),
                "other_errors": self.media_download_other_error.get(nome, 0),
            }
        return out

    def media_record_timeout(self) -> None:
        self.media_timeouts += 1

    def media_record_asset_rejected(self) -> None:
        self.media_assets_rejected += 1

    def media_record_synth(self) -> None:
        self.media_synth_diagrams += 1

    def media_record_rights(self, status: str) -> None:
        if status == "verify":
            self.media_rights_verify += 1
        elif status == "blocked":
            self.media_rights_blocked += 1

    def media_record_selection(self, candidates: int, kept: int) -> None:
        """Candidatos que passaram nos filtros e quantos ficaram na cena.

        `candidates` alto com `kept` baixo é o sinal de que os hard filters
        estão descartando coisa que talvez servisse.
        """
        self.media_candidates_total += max(0, int(candidates))
        self.media_candidates_kept += max(0, int(kept))

    def media_record_rejection(self, reason: str) -> None:
        """Contabiliza o MOTIVO da rejeição, não só que houve uma."""
        key = (reason or "outro").split(":")[0].strip()[:40] or "outro"
        self.media_rejections[key] = self.media_rejections.get(key, 0) + 1

    def media_record_funnel(self, stage: str, count: int = 1) -> None:
        """Conta candidatos nos pontos de decisão, sem guardar logs individuais."""
        self.media_funnel[stage] = self.media_funnel.get(stage, 0) + count

    def media_record_visual_type(self, vtype: str) -> None:
        """Como cada cena foi visualizada. Um diagrama NÃO é falha."""
        v = (vtype or "desconhecido").strip()[:20]
        self.media_visual_types[v] = self.media_visual_types.get(v, 0) + 1

    def media_record_scene_decision(self, scene_id: int, decision: dict) -> None:
        """Persist bounded visual intent and candidate evidence per scene."""
        if not isinstance(decision, dict):
            return
        safe = dict(decision)
        safe["candidates"] = list(safe.get("candidates", []))[:40]
        safe["queries"] = list(safe.get("queries", []))[:16]
        self.media_scene_decisions[str(scene_id)] = safe

    def media_record_score(self, score: float) -> None:
        self.media_score_sum += float(score or 0.0)
        self.media_scored_count += 1
        if float(score or 0.0) < 0.34 * 100:
            self.media_low_score += 1

    def media_record_fallback(self, strategy: str) -> None:
        """Cena que trocou de estratégia visual (não encontrou foto boa)."""
        self.media_fallbacks[strategy] = self.media_fallbacks.get(strategy, 0) + 1

    def research_query(self) -> None:
        self.research_queries += 1

    def research_source(self) -> None:
        self.research_sources += 1

    def research_record_rejection(self, reason: str) -> None:
        """Fonte descartada por não ser do referente pretendido."""
        key = (reason or "motivo desconhecido")[:60]
        self.research_rejected[key] = self.research_rejected.get(key, 0) + 1

    def visual_plan(self, chapters, media_scenes, beat_seconds: float,
                    visual_timeline=None, rendered_duration: float | None = None,
                    cached_selection: bool | None = None,
                    known_selection: bool = True) -> None:
        """Snapshot selected/available assets and renderer-bound beat identities."""
        from .stages.visual_beats import asset_key, plan
        by_scene = {s.get("chapter_id"): s for s in (media_scenes or [])}
        by_timeline = {s["chapter_id"]: s for s in (visual_timeline or [])}
        if cached_selection is None:
            cached_selection = not self.media_funnel.get("selected") and not self.media_downloads
        self.visual_scene_count = self.visual_beat_count = self.visual_asset_uses = 0
        self.visual_beat_seconds = 0.0
        self.visual_asset_ids.clear()
        self.media_available_ids.clear()
        self.media_available_acquisitions.clear()
        self.visual_asset_beat_counts.clear()
        self.visual_asset_scene_counts.clear()
        self.visual_asset_details.clear()
        self.media_scenes_new_asset = 0
        self.media_scenes_reused_asset = 0
        self.media_scenes_synthetic = 0
        self.media_unique_assets = 0
        self.media_reuse_count = 0
        self.media_assets_reused = 0
        for chapter in chapters:
            timeline = by_timeline.get(chapter.id)
            start = float(timeline["start"]) if timeline else float(chapter.start)
            end = float(timeline["end"]) if timeline else float(chapter.end)
            if rendered_duration is not None:
                end = min(end, rendered_duration)
            duration = max(0.0, end - start)
            self.visual_scene_count += int(duration > 0)
            self.visual_beat_seconds += duration
            scene = by_scene.get(chapter.id, {})
            assets = scene.get("assets") or []
            if not assets and scene.get("asset"):
                assets = [{"asset": scene["asset"]}]
            primary = next((item.get("asset") or {} for item in assets), {})
            for item in assets:
                asset = item.get("asset") or {}
                key = asset_key(asset)
                if key:
                    self.media_available_ids.add(key)
                    self.visual_asset_beat_counts.setdefault(key, 0)
                    acquisition = ("cache" if cached_selection else "generated"
                                   if asset.get("provider") == "synth" else
                                   item.get("acquisition", "unknown"))
                    self.media_available_acquisitions[acquisition] = (
                        self.media_available_acquisitions.get(acquisition, 0) + 1)
                    if asset.get("provider") != "synth":
                        self.media_selected_ids.add(key)
                    self.visual_asset_details[key] = {
                        "title": asset.get("title", ""),
                        "provider": asset.get("provider", ""),
                        "local_path": asset.get("local_path", ""),
                        "acquisition": acquisition}
            beats = timeline.get("visual_beats", []) if timeline else plan(duration, start)
            beats = [beat for beat in beats if beat["start"] < end]
            self.visual_beat_count += len(beats)
            base = asset_key(scene.get("asset") or (assets[0].get("asset") if assets else {}) or {})
            scene_keys = set()
            for beat in beats:
                if timeline:
                    images = timeline.get("images") or []
                    background = asset_key(beat) or (asset_key(images[0]) if images else "")
                    keys = [background] if background else []
                    keys.extend(asset_key(image) for image in images[1:]
                                if image["start"] < min(beat["end"], end) - start)
                else:
                    keys = [base] if base else []
                for key in set(keys):
                    if not key:
                        continue
                    self.visual_asset_ids.add(key)
                    scene_keys.add(key)
                    self.visual_asset_uses += 1
                    self.visual_asset_beat_counts[key] = self.visual_asset_beat_counts.get(key, 0) + 1
            for key in scene_keys:
                self.visual_asset_scene_counts[key] = self.visual_asset_scene_counts.get(key, 0) + 1
        self.media_selection_stats = MediaSelectionStats.from_scenes(
            media_scenes, known=known_selection)
        stats = self.media_selection_stats
        if stats.unique_assets is not None:
            self.media_unique_assets = stats.unique_assets
            self.media_assets_reused = stats.reused_assets or 0
            self.media_reuse_count = stats.reuse_count or 0
            self.media_scenes_new_asset = stats.scenes_with_new_asset or 0
            self.media_scenes_reused_asset = stats.scenes_with_reused_asset or 0
            self.media_scenes_synthetic = stats.synthetic_scenes or 0
            self.media_real_asset_occurrences = stats.real_asset_occurrences or 0

    def whisper(self, model: str) -> None:
        self.whisper_calls += 1
        self.whisper_model = model

    def media_record_no_visual(self) -> None:
        """Cena que ficou sem nenhum visual — o único caso de falha."""
        self.media_scenes_no_visual += 1

    def media_visual_report(self, n_scenes: int) -> dict:
        """Resumo por estratégia visual (item 20 da spec).

        A leitura importante: `sem_visual` e `gerado_por_codigo` NÃO são
        falha. Uma cena com diagrama está visualizada; uma cena sem
       Strategy nenhuma é que é problema, e é a única que aparece aqui
        como zero.
        """
        total = max(1, int(n_scenes or 0))
        # `sem_visual` é a ÚNICA métrica que é problema: uma cena sem
        # estratégia nenhuma. Diagrama e cartão contam como visualizadas.
        stats = self.media_selection_stats
        geradas = (stats.synthetic_scenes if stats and
                   stats.synthetic_scenes is not None else self.media_synth_diagrams)
        selection_fields = (stats.visual_report_fields() if stats else {})
        return {
            "cenas": int(n_scenes or 0),
            "por_tipo": dict(sorted(self.media_visual_types.items())),
            "por_estrategia": dict(sorted(self.media_fallbacks.items())),
            "gerado_por_codigo_pct": round(100.0 * geradas / total, 1),
            "sem_visual": (selection_fields.get("sem_visual")
                           if stats else self.media_scenes_no_visual),
            "candidatos_total": self.media_candidates_total,
            "candidatos_mantidos": self.media_candidates_kept,
            "rejeicoes": dict(sorted(self.media_rejections.items())),
            "nota_media": (round(self.media_score_sum / self.media_scored_count, 1)
                           if self.media_scored_count else None),
            "nota_baixa": self.media_low_score,
            "camadas": dict(sorted(self.media_layers_used.items())),
            "device": self.media_layer_device or "",
            "unique_assets": selection_fields.get("unique_assets", self.media_unique_assets),
            "reused_assets": selection_fields.get("reused_assets", self.media_assets_reused),
            "reuse_count": selection_fields.get("reuse_count", self.media_reuse_count),
            "unique_asset_ratio": selection_fields.get(
                "unique_asset_ratio", round(
                    self.media_unique_assets / max(1, self.media_real_asset_occurrences), 3)),
            "scenes_with_new_asset": selection_fields.get(
                "scenes_with_new_asset", self.media_scenes_new_asset),
            "scenes_with_reused_asset": selection_fields.get(
                "scenes_with_reused_asset", self.media_scenes_reused_asset),
            "synthetic_scenes": selection_fields.get(
                "synthetic_scenes", self.media_scenes_synthetic),
            "scenes_with_unknown_decision": selection_fields.get(
                "scenes_with_unknown_decision"),
            "real_asset_occurrences": selection_fields.get(
                "real_asset_occurrences", self.media_real_asset_occurrences),
            "queries_abandoned_duplicates": self.media_duplicate_queries,
        }

    # -- saída --
    def to_dict(self, meta: dict, stage_times: dict, metrics_dir: str) -> dict:
        total = round(time.monotonic() - self.started_monotonic, 2)
        artifacts = (meta.get("artifacts") or {})

        def _size(key: str) -> int | None:
            path = artifacts.get(key)
            try:
                return os.path.getsize(path) if path else None
            except OSError:
                return None

        media = meta.get("media") or []
        chapters = meta.get("chapters") or []
        return {
            "timestamp": self.started_at,
            "slug": self.slug,
            "title": meta.get("title", self.idea),
            "narration": meta.get("narration", self.narration),
            "source": "live",
            "time": {
                "started_at": self.started_at,
                "finished_at": utcnow_iso(),
                "total_seconds": total,
                "stages": dict(stage_times),
            },
            "video": {
                "duration_target": meta.get("duration_target"),
                "duration_actual": meta.get("duration_actual"),
                "audio_duration": meta.get("audio_duration"),
                "width": meta.get("width"),
                "height": meta.get("height"),
                "size_bytes": {
                    "final": _size("video"),
                    "silent": _size("silent"),
                    "audio": _size("audio") or _size("human_audio"),
                    "teleprompter": _size("teleprompter"),
                },
            },
            "pipeline": {
                "script_source": meta.get("script_source"),
                "script_chars": meta.get("script_chars"),
                "scenes_source": meta.get("scenes_source"),
                "chapters": len(chapters),
                "subtitle_cues": meta.get("subtitle_cues"),
                "subtitle_source": meta.get("subtitle_source"),
                "tts_provider": meta.get("tts_provider"),
                "tts_voice": meta.get("tts_voice"),
                "render_backend": meta.get("render_backend"),
                "render_encoder": meta.get("render_encoder"),
                "transcription_model": meta.get("transcription_model"),
                "visual_scenes": self.visual_scene_count,
                "visual_beats": self.visual_beat_count,
                "visual_assets_unique": len(self.visual_asset_ids),
                "visual_asset_beat_counts": dict(self.visual_asset_beat_counts),
                "visual_asset_scene_counts": dict(self.visual_asset_scene_counts),
                "visual_asset_details": dict(self.visual_asset_details),
                "media_scene_decisions": dict(self.media_scene_decisions),
                "visual_report": (meta.get("visual_report") or
                                  self.media_visual_report(len(chapters))),
                "visual_assets_reused": max(
                    0, sum(self.visual_asset_scene_counts.values()) - len(self.visual_asset_ids)),
                "visual_average_seconds_per_beat": (
                    round(self.visual_beat_seconds / self.visual_beat_count, 2)
                    if self.visual_beat_count else None),
            },
            "consumption": {
                "nvidia": {
                    "calls": self.nvidia_calls,
                    "prompt_tokens": self.nvidia_prompt_tokens,
                    "completion_tokens": self.nvidia_completion_tokens,
                    "models": list(self.nvidia_models),
                },
                "tts": {"calls": list(self.tts_calls)},
                "media": {
                    "selected_unique": len(self.media_selected_ids),
                    "selection_attempts": self.media_funnel.get("selected", 0),
                    "available_unique": len(self.media_available_ids),
                    "available_occurrences": sum(self.media_available_acquisitions.values()),
                    "available_by_acquisition": dict(self.media_available_acquisitions),
                    "searches": dict(self.media_searches),
                    "downloads": self.media_downloads,
                    "bytes": self.media_bytes,
                    "cache_hits": self.media_cache_hits,
                    "cache_misses": self.media_cache_misses,
                    "assets": sum(1 for s in media if s.get("asset")),
                    "fallbacks": sum(1 for s in media if not s.get("asset")),
                    "reused": sum(1 for s in media if s.get("reused_from")),
                    "query_generation_time": round(self.media_query_generation_time, 2),
                    "provider_search_time": {k: round(v, 2) for k, v in self.media_provider_search_time.items()},
                    "downloads_time": round(self.media_downloads_time, 2),
                    "selection_time": round(self.media_selection_time, 2),
                    "deduplication_time": round(self.media_deduplication_time, 2),
                    "queries_count": self.media_queries_count,
                    "requests_per_provider": dict(self.media_requests_per_provider),
                    "time_per_request": {k: [round(t, 2) for t in v] for k, v in self.media_time_per_request.items()},
                    "results_received": dict(self.media_results_received),
                    "funnel": dict(self.media_funnel),
                    "rejection_reasons": dict(self.media_rejections),
                    "assets_rejected": self.media_assets_rejected,
                    "assets_reused": self.media_assets_reused,
                    "timeouts": self.media_timeouts,
                    "retries": self.media_retries,
                    "synth_diagrams": self.media_synth_diagrams,
                    "rights_verify": self.media_rights_verify,
                    "rights_blocked": self.media_rights_blocked,
                },
                "research": {"queries": self.research_queries,
                             "complementary_queries": self.research_complementary_queries,
                             "sources": self.research_sources},
                "whisper": {"calls": self.whisper_calls,
                            "model": self.whisper_model},
            },
            "warnings": list(meta.get("warnings", []) +
                             meta.get("finalize_warnings", [])),
            "metrics_dir": metrics_dir,
        }

    def save(self, meta: dict, stage_times: dict, metrics_dir: str) -> str:
        os.makedirs(metrics_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # Project references may include a genre prefix ("history/<slug>").
        # Keep that path out of the metrics filename.
        safe_slug = self.slug.replace("/", "_").replace("\\", "_")
        path = os.path.join(metrics_dir, f"{stamp}_{safe_slug}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(meta, stage_times, metrics_dir), fh,
                      ensure_ascii=False, indent=1)
        return path


def backfill_from_metadata(slug: str, meta: dict, metrics_dir: str) -> str:
    """Backfill visual and timing fields; unavailable request counts stay null."""
    os.makedirs(metrics_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    collector = RunMetrics(slug, meta.get("input", slug),
                           meta.get("narration", ""))
    media = meta.get("media") or []
    for scene in media:
        strategy = str(scene.get("strategy") or "")
        collector.media_record_visual_type(
            str(scene.get("visual_type") or "literal"))
        if strategy and strategy != "image":
            collector.media_record_fallback(strategy)
        if (scene.get("asset") or {}).get("provider") == "synth":
            collector.media_record_synth()
        decision = scene.get("visual_decision")
        if isinstance(decision, dict):
            collector.media_record_scene_decision(
                int(scene.get("chapter_id", 0)), decision)
    chapters = [SimpleNamespace(
        id=int(ch.get("id", 0)),
        start=float(ch.get("start", 0) or 0),
        end=float(ch.get("end", ch.get("duration_estimate", 0)) or 0))
        for ch in (meta.get("chapters") or [])]
    visual_timeline = []
    timeline_path = (meta.get("artifacts") or {}).get("visual_timeline")
    if timeline_path:
        try:
            with open(timeline_path, encoding="utf-8") as fh:
                visual_timeline = json.load(fh)
        except (OSError, ValueError, json.JSONDecodeError):
            visual_timeline = []
    collector.visual_plan(chapters, media, 2.1, visual_timeline,
                          rendered_duration=meta.get("duration_actual"),
                          cached_selection=False,
                          known_selection="media" in meta and meta.get("media") is not None)
    query_statuses = [query.get("status")
                      for decision in collector.media_scene_decisions.values()
                      for query in decision.get("queries", [])]
    if query_statuses:
        if "abandoned_duplicates" in query_statuses:
            collector.media_duplicate_queries = query_statuses.count(
                "abandoned_duplicates")
        else:
            # Older metadata did not distinguish empty from duplicate-only results.
            collector.media_duplicate_queries = None
    stage_times = meta.get("stage_times", {})
    doc = collector.to_dict(meta, stage_times, metrics_dir)
    doc["pipeline"]["visual_report"] = collector.media_visual_report(
        len(meta.get("chapters") or []))
    doc["source"] = ("backfill: visual decisions, assets, and timing derived "
                     "from project metadata; provider request counts unavailable")
    duration = meta.get("processing_time_seconds")
    try:
        duration = max(0.0, float(duration))
    except (TypeError, ValueError):
        duration = max(0.0, sum(float(value or 0) for value in stage_times.values()))
    finished_at = meta.get("created_at") or utcnow_iso()
    try:
        finished = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
        started = finished - timedelta(seconds=duration)
        doc["timestamp"] = started.isoformat()
        doc["time"].update({"started_at": started.isoformat(),
                            "finished_at": finished.isoformat(),
                            "total_seconds": round(duration, 2)})
    except ValueError:
        doc["time"]["total_seconds"] = round(duration, 2)
    research = meta.get("research") or {}
    doc["consumption"]["research"]["sources"] = research.get("sources")
    for section in ("nvidia", "tts", "media", "whisper"):
        doc["consumption"][section] = None
    safe_slug = slug.replace("/", "_").replace("\\", "_")
    path = os.path.join(metrics_dir, f"{stamp}_{safe_slug}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return path
