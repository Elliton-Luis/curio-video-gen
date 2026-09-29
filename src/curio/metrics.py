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

    def media_download(self, bytes_: int, cached: bool) -> None:
        if cached:
            self.media_cache_hits += 1
        else:
            self.media_downloads += 1
            self.media_bytes += bytes_

    def whisper(self, model: str) -> None:
        self.whisper_calls += 1
        self.whisper_model = model

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
                    "assets": sum(1 for s in media if s.get("asset")),
                    "fallbacks": sum(1 for s in media if not s.get("asset")),
                    "reused": sum(1 for s in media if s.get("reused_from")),
                },
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
