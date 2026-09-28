"""Orquestração do pipeline (PRD §4, §15, §16, §19).

Etapas: roteiro → narração → sincronização/legendas → montagem → finalização.
Artefatos intermediários são preservados e reutilizados se já existirem.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import ffmpeg as ff
from .config import CurioConfig
from .slug import slugify
from .stages import render as render_stage
from .stages import script as script_stage
from .stages import subs as subs_stage
from .stages import tts as tts_stage

STAGES = ["roteiro", "narração", "legendas", "montagem", "finalização"]


@dataclass
class VideoPaths:
    root: str
    script_txt: str
    narration_wav: str
    subs_srt: str
    subs_ass: str
    final_mp4: str
    metadata_json: str


def video_paths(out_dir: str, slug: str) -> VideoPaths:
    root = os.path.join(out_dir, slug)
    return VideoPaths(
        root=root,
        script_txt=os.path.join(root, "script", "script.txt"),
        narration_wav=os.path.join(root, "audio", "narration.wav"),
        subs_srt=os.path.join(root, "subtitles", "subs.srt"),
        subs_ass=os.path.join(root, "subtitles", "subs.ass"),
        final_mp4=os.path.join(root, "render", "final.mp4"),
        metadata_json=os.path.join(root, "metadata.json"),
    )


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run_pipeline(idea: str, cfg: CurioConfig, slug: str | None = None,
                 force: bool = False, on_progress=None) -> dict:
    started = time.monotonic()
    stage_times: dict[str, float] = {}

    def emit(idx: int, label: str, status: str = "…") -> None:
        if on_progress:
            on_progress(idx, len(STAGES), label, status)

    slug = slug or slugify(idea)
    paths = video_paths(cfg.out_dir, slug)
    for d in ("script", "audio", "subtitles", "assets", "render"):
        os.makedirs(os.path.join(paths.root, d), exist_ok=True)

    # [1/5] Roteiro
    t0 = time.monotonic()
    emit(1, "Gerando roteiro")
    if not force and os.path.isfile(paths.script_txt):
        script_text, script_source = _read(paths.script_txt), "cache"
    else:
        script_text, script_source = script_stage.generate_script(idea, cfg)
        with open(paths.script_txt, "w", encoding="utf-8") as fh:
            fh.write(script_text)
    stage_times["script"] = round(time.monotonic() - t0, 2)
    emit(1, "Gerando roteiro", "OK")

    # [2/5] Narração
    t0 = time.monotonic()
    emit(2, "Gerando narração")
    if not force and os.path.isfile(paths.narration_wav):
        audio_duration = ff.probe_duration(paths.narration_wav)
        tts_info = {"provider": cfg.tts_provider, "voice": cfg.tts_voice,
                    "speed": cfg.tts_speed, "reused": True}
    else:
        res = tts_stage.synthesize(script_text, paths.narration_wav,
                                   cfg.tts_provider, cfg.tts_voice,
                                   cfg.tts_speed, cfg.duration_target)
        audio_duration = res.duration
        tts_info = {"provider": res.provider, "voice": res.voice,
                    "speed": res.speed, "reused": False}
    stage_times["tts"] = round(time.monotonic() - t0, 2)
    emit(2, "Gerando narração", "OK")

    # [3/5] Legendas
    t0 = time.monotonic()
    emit(3, "Sincronizando legendas")
    cue_count = None
    if force or not (os.path.isfile(paths.subs_srt)
                     and os.path.isfile(paths.subs_ass)):
        cue_count = subs_stage.write_subtitles(
            script_text, audio_duration, paths.subs_srt, paths.subs_ass,
            cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v)
    else:
        content = _read(paths.subs_srt)
        cue_count = content.count("-->")
    stage_times["subs"] = round(time.monotonic() - t0, 2)
    emit(3, "Sincronizando legendas", "OK")

    # [4/5] Montagem
    t0 = time.monotonic()
    emit(4, "Montando vídeo")
    if not force and os.path.isfile(paths.final_mp4):
        video_duration = ff.probe_duration(paths.final_mp4)
        render_info = {"backend": "cache", "encoder": "cache",
                       "duration": video_duration, "path": paths.final_mp4}
    else:
        render_info = render_stage.render_video(
            paths.narration_wav, paths.subs_ass, paths.final_mp4,
            idea, audio_duration, cfg)
        video_duration = render_info["duration"]
    stage_times["render"] = round(time.monotonic() - t0, 2)
    emit(4, "Montando vídeo", "OK")

    # [5/5] Finalização
    t0 = time.monotonic()
    emit(5, "Finalizando")
    metadata = {
        "title": idea.strip(),
        "input": idea,
        "slug": slug,
        "duration_target": cfg.duration_target,
        "duration_actual": round(video_duration, 2),
        "audio_duration": round(audio_duration, 2),
        "script_source": script_source,
        "script_chars": len(script_text),
        "subtitle_cues": cue_count,
        "tts_provider": tts_info["provider"],
        "tts_voice": tts_info["voice"],
        "tts_speed": tts_info["speed"],
        "tts_reused": tts_info["reused"],
        "render_backend": render_info["backend"],
        "render_encoder": render_info["encoder"],
        "width": cfg.width,
        "height": cfg.height,
        "fps": cfg.fps,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "stage_times": stage_times,
        "pipeline_version": "mvp-0.1",
        "artifacts": {
            "script": paths.script_txt,
            "audio": paths.narration_wav,
            "subtitles": paths.subs_srt,
            "subtitles_ass": paths.subs_ass,
            "video": paths.final_mp4,
        },
    }
    with open(paths.metadata_json, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, ensure_ascii=False, indent=2)
    stage_times["finalize"] = round(time.monotonic() - t0, 2)
    metadata["stage_times"] = stage_times
    emit(5, "Finalizando", "OK")

    return metadata
