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
import time
from datetime import datetime


def utcnow_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


class RunMetrics:
    """Coletor explícito de consumo. Criado por execução, passado aos estágios."""

    def __init__(self, slug: str, idea: str, narration: str):
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
        self.research_rejected: dict[str, int] = {}

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
        self.media_searches[provider] = self.media_searches.get(provider, 0) + 1
        self.media_requests_per_provider[provider] = self.media_requests_per_provider.get(provider, 0) + 1

    def media_download(self, bytes_: int, cached: bool) -> None:
        if cached:
            self.media_cache_hits += 1
        else:
            self.media_downloads += 1
            self.media_bytes += bytes_
            self.media_cache_misses += 1

    def media_record_search_time(self, provider: str, elapsed: float) -> None:
        self.media_provider_search_time[provider] = self.media_provider_search_time.get(provider, 0.0) + elapsed
        self.media_time_per_request.setdefault(provider, []).append(elapsed)

    def media_record_results(self, provider: str, count: int) -> None:
        self.media_results_received[provider] = self.media_results_received.get(provider, 0) + count

    def media_download_started(self, provider: str) -> None:
        self.media_download_attempted[provider] = (
            self.media_download_attempted.get(provider, 0) + 1)

    def media_download_ok(self, provider: str) -> None:
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

    def media_record_retry(self) -> None:
        self.media_retries += 1

    def media_record_asset_rejected(self) -> None:
        self.media_assets_rejected += 1

    def media_record_asset_reused(self) -> None:
        self.media_assets_reused += 1

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

    def media_record_visual_type(self, vtype: str) -> None:
        """Como cada cena foi visualizada. Um diagrama NÃO é falha."""
        v = (vtype or "desconhecido").strip()[:20]
        self.media_visual_types[v] = self.media_visual_types.get(v, 0) + 1

    def media_record_score(self, score: float) -> None:
        self.media_score_sum += float(score or 0.0)
        self.media_scored_count += 1
        if float(score or 0.0) < 0.34 * 100:
            self.media_low_score += 1

    def media_record_layer(self, layer: str, device: str = "") -> None:
        """Camada opcional usada (clip/vision) e em que dispositivo."""
        self.media_layers_used[layer] = self.media_layers_used.get(layer, 0) + 1
        if device:
            self.media_layer_device = device

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

    def research_report(self) -> dict:
        return {"aceitas": self.research_sources,
                "rejeitadas": dict(sorted(self.research_rejected.items())),
                "consultas": self.research_queries}

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
        geradas = sum(self.media_visual_types.get(k, 0)
                      for k in ("diagram", "card", "typographic_card"))
        return {
            "cenas": int(n_scenes or 0),
            "por_tipo": dict(sorted(self.media_visual_types.items())),
            "por_estrategia": dict(sorted(self.media_fallbacks.items())),
            "gerado_por_codigo_pct": round(100.0 * geradas / total, 1),
            "sem_visual": self.media_scenes_no_visual,
            "candidatos_total": self.media_candidates_total,
            "candidatos_mantidos": self.media_candidates_kept,
            "rejeicoes": dict(sorted(self.media_rejections.items())),
            "nota_media": (round(self.media_score_sum / self.media_scored_count, 1)
                           if self.media_scored_count else None),
            "nota_baixa": self.media_low_score,
            "camadas": dict(sorted(self.media_layers_used.items())),
            "device": self.media_layer_device or "",
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
                    "assets_rejected": self.media_assets_rejected,
                    "assets_reused": self.media_assets_reused,
                    "timeouts": self.media_timeouts,
                    "retries": self.media_retries,
                    "synth_diagrams": self.media_synth_diagrams,
                    "rights_verify": self.media_rights_verify,
                    "rights_blocked": self.media_rights_blocked,
                },
                "research": {"queries": self.research_queries,
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
        path = os.path.join(metrics_dir, f"{stamp}_{self.slug}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(meta, stage_times, metrics_dir), fh,
                      ensure_ascii=False, indent=1)
        return path


def backfill_from_metadata(slug: str, meta: dict, metrics_dir: str) -> str:
    """Gera métricas p/ vídeos antigos a partir do metadata.json.

    Contadores de consumo não existiam nessas execuções: ficam nulos com nota.
    """
    os.makedirs(metrics_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    doc = RunMetrics(slug, meta.get("input", slug),
                     meta.get("narration", "")).to_dict(meta, meta.get(
                         "stage_times", {}), metrics_dir)
    doc["source"] = ("backfill: contadores de consumo indisponíveis "
                     "(execução anterior à metrificação)")
    for section in ("nvidia", "tts", "media", "whisper"):
        doc["consumption"][section] = None
    path = os.path.join(metrics_dir, f"{stamp}_{slug}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return path
