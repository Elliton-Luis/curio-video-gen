"""Narration, audio timing and subtitle phases shared by video pipeline."""

from __future__ import annotations

import os
import json
import sys
import time
from dataclasses import dataclass

from . import ffmpeg as ff
from .stages import subs as subs_stage
from .stages import tts as tts_stage
from .stages.scene_contract import SemanticScene, TimelineSpan
from .stages.scenes import Chapter
from .stages.timing import align_word_boundaries, proportional_spans


@dataclass
class AudioStageResult:
    timeline_spans: tuple[TimelineSpan, ...]
    words: list[dict] | None
    audio_duration: float
    tts_info: dict
    timed_source: str
    cue_count: int
    subtitles_changed: bool
    stage_times: dict[str, float]


def run_audio_stages(script_text: str, semantic_scenes: tuple[SemanticScene, ...],
                     timeline_spans: tuple[TimelineSpan, ...], paths, cfg, force: bool,
                     metrics, warnings: list, emit, write_json,
                     stage_times: dict[str, float],
                     pacing=None, caption_style=None) -> AudioStageResult:
    """Run TTS, timing alignment and subtitle generation."""
    start_time = time.monotonic()
    emit(4, "Gerando narração")
    words = None
    if (not force and os.path.isfile(paths.narration_wav)
            and os.path.isfile(paths.words_json)):
        audio_duration = ff.probe_duration(paths.narration_wav)
        with open(paths.words_json, encoding="utf-8") as fh:
            words = json.load(fh)
        if not tts_stage.tts_coverage_ok(words, script_text):
            print(f"AVISO: narração em cache cobre só "
                  f"{len(words or [])}/{len(script_text.split())} palavras — "
                  "sintetizando de novo.", file=sys.stderr)
            warnings.append("narração parcial em cache — refeita")
            words = None
        else:
            tts_info = {"provider": cfg.tts_provider, "voice": cfg.tts_voice,
                        "speed": cfg.tts_speed, "reused": True}
    if words is None:
        result = tts_stage.synthesize(
            script_text, paths.narration_wav, cfg.tts_provider, cfg.tts_voice,
            cfg.tts_speed, cfg.duration_target, words_path=paths.words_json,
            metrics=metrics, language=cfg.language)
        audio_duration = result.duration
        words = result.words
        tts_info = {"provider": result.provider, "voice": result.voice,
                    "speed": result.speed, "reused": False}
        from .runlog import event as run_event
        run_event("cache" if tts_info.get("reused") else "provider",
                  f"TTS: {tts_info['provider']} / {tts_info['voice']} "
                  f"({audio_duration:.1f}s)", operation="tts",
                  provider=tts_info["provider"], voice=tts_info["voice"],
                  duration_seconds=round(audio_duration, 2),
                  cache=tts_info.get("reused", False))
    stage_times["tts"] = round(time.monotonic() - start_time, 2)
    emit(4, "Gerando narração", "OK")

    try:
        aligned_spans = align_word_boundaries(
            semantic_scenes, timeline_spans, words or [])
        timed_source = "wordboundary"
    except (ValueError, IndexError) as exc:
        print(f"AVISO: {exc} — timeline proporcional.", file=sys.stderr)
        warnings.append(f"timeline proporcional ({exc})")
        cursor = words[0]["start"] if words else 0.15
        aligned_spans = proportional_spans(
            semantic_scenes, timeline_spans, audio_duration, float(cursor))
        timed_source = "proporcional"
    chapters = tuple(Chapter.from_semantic_scene(scene, timing=span)
                     for scene, span in zip(semantic_scenes, aligned_spans))
    write_json(paths.timeline_json, [chapter.to_dict() for chapter in chapters])

    start_time = time.monotonic()
    emit(5, "Sincronizando legendas")
    if os.path.isfile(paths.subs_ass):
        with open(paths.subs_ass, encoding="utf-8") as fh:
            previous_ass = fh.read()
    else:
        previous_ass = ""
    cue_count = subs_stage.write_subtitles(
        script_text, audio_duration, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size,
        subs_stage.safe_subtitle_margin(cfg.height, cfg.sub_margin_v),
        words=words if tts_info["provider"] == "edge-tts" else None,
        cache_dir=cfg.cache_dir,
        max_words=min(5, pacing.caption_max_words if pacing is not None else 5),
        highlight="word", upper=False, karaoke=True,
        **({"outline": caption_style.outline,
            "shadow": caption_style.shadow}
           if caption_style is not None else {}))
    with open(paths.subs_ass, encoding="utf-8") as fh:
        subtitles_changed = fh.read() != previous_ass
    if subtitles_changed and not force and os.path.isfile(paths.final_mp4):
        print("AVISO: texto das legendas mudou — refazendo o MP4 final "
              "para acompanhar.", file=sys.stderr)
        warnings.append("legendas atualizadas (rebuild do final.mp4)")
    stage_times["subs"] = round(time.monotonic() - start_time, 2)
    from .runlog import event as run_event
    run_event("result", f"Legendas: {cue_count} cue(s); "
              f"{'WordBoundary' if words and tts_info['provider'] == 'edge-tts' else 'proporcional'}",
              operation="subtitles", cues=cue_count,
              timing=("wordboundary" if words and tts_info["provider"] == "edge-tts"
                      else "proporcional"))
    emit(5, "Sincronizando legendas", "OK")
    return AudioStageResult(aligned_spans, words, audio_duration, tts_info,
                            timed_source, cue_count, subtitles_changed,
                            stage_times)
